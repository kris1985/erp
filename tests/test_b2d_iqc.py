"""B2d：来料 IQC — 待检不入池；合格/让步入池；不合格不占齐套。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    OwnProduct,
    Partner,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    MaterialIqcRecord,
    MaterialIqcStatus,
    SharedMaterialStock,
    SupplierProduct,
    Tenant,
)
from app.services import purchase_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed(db):
    tenant = Tenant(
        name="IQC厂",
        settings_json={"inventory": {"iqc_before_pool": True, "auto_allocate_on_receive": True}},
    )
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="IQC款", quote_price=Decimal("10"))
    db.add_all([partner, product])
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="底-37",
        name="大底",
        unit_price=Decimal("2"),
    )
    db.add(sp)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="IQC-O1",
        customer_name="客",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=10,
        delivery_date=date.today() + timedelta(days=7),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    req = OrderMaterialRequirement(
        tenant_id=tenant.id,
        order_id=order.id,
        supplier_product_id=sp.id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("10"),
        arrived_qty=Decimal("0"),
    )
    db.add(req)
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-IQC-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
        expected_date=date.today(),
    )
    db.add(po)
    db.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant.id,
        purchase_order_id=po.id,
        supplier_product_id=sp.id,
        order_id=order.id,
        order_material_requirement_id=req.id,
        qty=Decimal("10"),
        unit_price=Decimal("2"),
        received_qty=Decimal("0"),
    )
    db.add(line)
    db.commit()
    return {
        "tenant": tenant,
        "po": po,
        "line": line,
        "req": req,
        "sp": sp,
        "order": order,
    }


def _pool_qty(db, tenant_id, sp_id):
    row = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    return Decimal(str(row.qty)) if row else Decimal("0")


def test_receive_posts_pool_without_iqc(db):
    ctx = _seed(db)
    out = purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 6}],
        user_id=1,
    )
    assert "iqc_pending_count" not in out
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == Decimal("0")
    db.refresh(ctx["line"])
    assert ctx["line"].received_qty == Decimal("6")
    assert _pool_qty(db, ctx["tenant"].id, ctx["sp"].id) == Decimal("6")
    assert db.scalar(select(MaterialIqcRecord).where(MaterialIqcRecord.purchase_order_id == ctx["po"].id)) is None


def test_receive_by_material_total_fills_fractional_lines(db):
    ctx = _seed(db)
    ctx["line"].qty = Decimal("87.3333")
    other = PurchaseOrderLine(
        tenant_id=ctx["tenant"].id,
        purchase_order_id=ctx["po"].id,
        supplier_product_id=ctx["sp"].id,
        qty=Decimal("174.6667"),
        unit_price=Decimal("2"),
        received_qty=Decimal("0"),
    )
    db.add(other)
    db.commit()
    po = purchase_service.get_po(db, ctx["tenant"].id, ctx["po"].id)
    rounded = purchase_service.reconcile_receive_lines(
        db,
        ctx["tenant"].id,
        po,
        [
            {"line_id": ctx["line"].id, "qty": Decimal("87.33")},
            {"line_id": other.id, "qty": Decimal("174.67")},
        ],
    )
    purchase_service.receive_po(db, ctx["tenant"].id, ctx["po"].id, rounded, user_id=1)
    db.refresh(ctx["line"])
    db.refresh(other)
    db.refresh(ctx["po"])
    assert ctx["line"].received_qty == Decimal("87.3333")
    assert other.received_qty == Decimal("174.6667")
    assert ctx["po"].status == PurchaseOrderStatus.received

    po = purchase_service.get_po(db, ctx["tenant"].id, ctx["po"].id)
    with pytest.raises(purchase_service.PurchaseError) as exc:
        purchase_service.expand_receive_items(
            db,
            ctx["tenant"].id,
            po,
            [{"supplier_product_id": ctx["sp"].id, "qty": Decimal("1")}],
        )
    assert exc.value.code == "over_receive"


def test_partial_unsubscribe_reduces_open_qty_and_keeps_status(db):
    ctx = _seed(db)
    other = PurchaseOrderLine(
        tenant_id=ctx["tenant"].id,
        purchase_order_id=ctx["po"].id,
        supplier_product_id=ctx["sp"].id,
        qty=Decimal("5"),
        unit_price=Decimal("2"),
        received_qty=Decimal("0"),
        loss_qty=Decimal("1"),
    )
    db.add(other)
    db.commit()
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 4}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    db.refresh(other)
    assert ctx["line"].qty == Decimal("6")
    assert ctx["line"].received_qty == Decimal("0")
    assert other.qty == Decimal("5")
    assert ctx["po"].status == PurchaseOrderStatus.ordered


def test_full_unsubscribe_cancels_when_nothing_received(db):
    ctx = _seed(db)
    ctx["line"].loss_qty = Decimal("3")
    db.commit()
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 10}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    assert ctx["line"].qty == Decimal("0")
    assert ctx["line"].loss_qty == Decimal("0")
    assert ctx["po"].status == PurchaseOrderStatus.cancelled


def test_unsubscribe_remainder_after_receive_marks_received(db):
    ctx = _seed(db)
    purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 6}],
        user_id=1,
    )
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 4}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    assert ctx["line"].qty == Decimal("6")
    assert ctx["line"].received_qty == Decimal("6")
    assert ctx["po"].status == PurchaseOrderStatus.received
    assert _pool_qty(db, ctx["tenant"].id, ctx["sp"].id) == Decimal("6")


def test_unsubscribe_cannot_exceed_open_or_pending_iqc(db):
    ctx = _seed(db)
    db.add(
        MaterialIqcRecord(
            tenant_id=ctx["tenant"].id,
            purchase_order_id=ctx["po"].id,
            purchase_order_line_id=ctx["line"].id,
            supplier_product_id=ctx["sp"].id,
            qty=Decimal("3"),
            status=MaterialIqcStatus.pending,
        )
    )
    db.commit()
    with pytest.raises(purchase_service.PurchaseError) as over:
        purchase_service.unsubscribe_po(
            db,
            ctx["tenant"].id,
            ctx["po"].id,
            [{"line_id": ctx["line"].id, "qty": 8}],
        )
    assert over.value.code == "over_unsubscribe"
    db.refresh(ctx["line"])
    assert ctx["line"].qty == Decimal("10")
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 7}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    assert ctx["line"].qty == Decimal("3")
    assert ctx["po"].status == PurchaseOrderStatus.ordered


def test_unsubscribe_draft_keeps_unreported_until_nothing_left(db):
    ctx = _seed(db)
    ctx["po"].status = PurchaseOrderStatus.draft
    db.commit()
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 4}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    assert ctx["line"].qty == Decimal("6")
    assert ctx["po"].status == PurchaseOrderStatus.draft
    purchase_service.unsubscribe_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 6}],
    )
    db.refresh(ctx["line"])
    db.refresh(ctx["po"])
    assert ctx["line"].qty == Decimal("0")
    assert ctx["po"].status == PurchaseOrderStatus.cancelled
