"""采购单下单：汇总数量按行分摊，确认后直接变为已反馈。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Partner,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services.purchase_service import (
    set_summary_loss,
    set_summary_qty,
    submit_po,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_summary_qty_splits_lines_then_submit_orders():
    db = _session()
    tenant = Tenant(name="采购厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="牛皮",
        partner_id=partner.id,
    )
    db.add(leather)
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-QTY-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date(2026, 10, 20),
    )
    db.add(po)
    db.flush()
    db.add_all(
        [
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                qty=Decimal("6"),
                unit_price=Decimal("10"),
            ),
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                qty=Decimal("4"),
                unit_price=Decimal("10"),
            ),
        ]
    )
    db.commit()

    updated = set_summary_qty(db, tenant.id, po.id, leather.id, Decimal("20"))
    qtys = sorted(Decimal(str(ln["qty"])) for ln in updated["lines"])
    assert qtys == [Decimal("8.0000"), Decimal("12.0000")]
    assert sum(qtys) == Decimal("20.0000")

    ordered = submit_po(db, tenant.id, po.id)
    assert ordered["status"] == "ordered"
    db.close()


def test_size_qty_updates_one_size_without_padded_decimals():
    db = _session()
    tenant = Tenant(name="采购厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-2",
        name="牛皮",
        partner_id=partner.id,
    )
    size40 = Size(tenant_id=tenant.id, size_value="40", sort_order=40)
    size42 = Size(tenant_id=tenant.id, size_value="42", sort_order=42)
    db.add_all([leather, size40, size42])
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-SIZE-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date(2026, 10, 20),
    )
    db.add(po)
    db.flush()
    db.add_all(
        [
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                size_id=size40.id,
                qty=Decimal("6"),
                unit_price=Decimal("10"),
            ),
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                size_id=size42.id,
                qty=Decimal("4"),
                unit_price=Decimal("10"),
            ),
        ]
    )
    db.commit()

    updated = set_summary_qty(db, tenant.id, po.id, leather.id, Decimal("9"), size_value="40")
    by_size = {ln["size_value"]: Decimal(str(ln["qty"])) for ln in updated["lines"]}
    assert by_size["40"] == Decimal("9")
    assert by_size["42"] == Decimal("4")
    db.close()


def test_draft_qty_can_change_without_approval():
    db = _session()
    tenant = Tenant(name="采购厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-3",
        name="牛皮",
        partner_id=partner.id,
    )
    db.add(leather)
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-LOCK-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        approval_status="pending",
        expected_date=date(2026, 10, 20),
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=leather.id,
            qty=Decimal("6"),
            unit_price=Decimal("10"),
        )
    )
    db.commit()

    updated = set_summary_qty(db, tenant.id, po.id, leather.id, Decimal("8"))
    assert Decimal(str(updated["lines"][0]["qty"])) == Decimal("8")
    ordered = submit_po(db, tenant.id, po.id)
    assert ordered["status"] == "ordered"
    db.close()


def test_loss_is_added_to_qty_when_order_is_placed():
    db = _session()
    tenant = Tenant(name="采购厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-4",
        name="牛皮",
        partner_id=partner.id,
    )
    db.add(leather)
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-LOSS-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date(2026, 10, 20),
    )
    db.add(po)
    db.flush()
    db.add_all(
        [
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                qty=Decimal("6"),
                unit_price=Decimal("10"),
            ),
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                qty=Decimal("4"),
                unit_price=Decimal("10"),
            ),
        ]
    )
    db.commit()

    noted = set_summary_loss(db, tenant.id, po.id, leather.id, Decimal("2"))
    assert noted["status"] == "draft"
    assert sum(Decimal(str(ln["qty"])) for ln in noted["lines"]) == Decimal("10")
    assert sum(Decimal(str(ln["loss_qty"])) for ln in noted["lines"]) == Decimal("2")

    ordered = submit_po(db, tenant.id, po.id)
    assert ordered["status"] == "ordered"
    assert sum(Decimal(str(ln["qty"])) for ln in ordered["lines"]) == Decimal("12")
    assert sum(Decimal(str(ln["loss_qty"])) for ln in ordered["lines"]) == Decimal("2")
    db.close()


def test_sized_loss_updates_only_that_size():
    db = _session()
    tenant = Tenant(name="采购厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-5",
        name="牛皮",
        partner_id=partner.id,
    )
    size40 = Size(tenant_id=tenant.id, size_value="40", sort_order=40)
    size42 = Size(tenant_id=tenant.id, size_value="42", sort_order=42)
    db.add_all([leather, size40, size42])
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-LOSS-SIZE",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date(2026, 10, 20),
    )
    db.add(po)
    db.flush()
    db.add_all(
        [
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                size_id=size40.id,
                qty=Decimal("6"),
                unit_price=Decimal("10"),
            ),
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=leather.id,
                size_id=size42.id,
                qty=Decimal("4"),
                unit_price=Decimal("10"),
            ),
        ]
    )
    db.commit()

    noted = set_summary_loss(db, tenant.id, po.id, leather.id, Decimal("1"), size_value="40")
    by_size = {ln["size_value"]: ln for ln in noted["lines"]}
    assert Decimal(str(by_size["40"]["loss_qty"])) == Decimal("1")
    assert Decimal(str(by_size["42"]["loss_qty"])) == Decimal("0")
    assert Decimal(str(by_size["40"]["qty"])) == Decimal("6")

    ordered = submit_po(db, tenant.id, po.id)
    ordered_by_size = {ln["size_value"]: ln for ln in ordered["lines"]}
    assert Decimal(str(ordered_by_size["40"]["qty"])) == Decimal("7")
    assert Decimal(str(ordered_by_size["42"]["qty"])) == Decimal("4")
    db.close()
