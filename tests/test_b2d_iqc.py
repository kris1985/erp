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
    SharedMaterialStock,
    SupplierProduct,
    Tenant,
)
from app.services import iqc_service, purchase_service
from app.services.iqc_service import IqcError


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


def test_receive_pending_then_fail_not_in_pool(db):
    ctx = _seed(db)
    out = purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 10}],
        user_id=1,
    )
    assert out.get("iqc_pending_count") == 1
    assert _pool_qty(db, ctx["tenant"].id, ctx["sp"].id) == 0
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == 0

    rid = out["iqc_pending_ids"][0]
    iqc_service.decide_iqc(db, ctx["tenant"].id, rid, decision="fail", user_id=1)
    assert _pool_qty(db, ctx["tenant"].id, ctx["sp"].id) == 0
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == 0


def test_pass_then_pool_and_allocate(db):
    ctx = _seed(db)
    out = purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 6}],
        user_id=1,
    )
    rid = out["iqc_pending_ids"][0]
    iqc_service.decide_iqc(db, ctx["tenant"].id, rid, decision="pass", user_id=1)
    # 入池后又自动分配到订单 → 池余 0，arrived=6
    assert _pool_qty(db, ctx["tenant"].id, ctx["sp"].id) == 0
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == Decimal("6")
    db.refresh(ctx["line"])
    assert ctx["line"].received_qty == Decimal("6")


def test_concede_posts_like_pass(db):
    ctx = _seed(db)
    out = purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 4}],
    )
    rid = out["iqc_pending_ids"][0]
    iqc_service.decide_iqc(db, ctx["tenant"].id, rid, decision="concede")
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == Decimal("4")


def test_skip_iqc_direct_pool(db):
    ctx = _seed(db)
    purchase_service.receive_po(
        db,
        ctx["tenant"].id,
        ctx["po"].id,
        [{"line_id": ctx["line"].id, "qty": 3}],
        skip_iqc=True,
    )
    db.refresh(ctx["req"])
    assert ctx["req"].arrived_qty == Decimal("3")
