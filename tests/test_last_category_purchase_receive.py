"""楦头分类：采购到货入模具仓（生产部），待结算走采购应付，不进物料仓。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Department,
    Employee,
    MaterialCategory,
    Partner,
    PayableLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
    ToolingItem,
    ToolingStock,
)
from app.services import purchase_service
from app.services.material_service import is_locked_last_category_name
from app.services.purchase_service import PurchaseError
from app.services.tooling_service import list_ledgers, list_receipts


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="楦头采购厂")
    db.add(tenant)
    db.flush()
    user = Employee(tenant_id=tenant.id, name="采购", mobile="13900002222", is_active=True)
    supplier = Partner(tenant_id=tenant.id, name="楦厂", is_supplier=True, is_active=True)
    cat = MaterialCategory(
        tenant_id=tenant.id,
        name="楦头",
        suggest_usage_by_size=True,
        is_active=True,
    )
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    production = Department(tenant_id=tenant.id, name="生产部", is_active=True, sort_order=1)
    db.add_all([user, supplier, cat, size, production])
    db.flush()
    product = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="LAST-36",
        name="36楦",
        category_id=cat.id,
        is_active=True,
    )
    db.add(product)
    db.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-LAST-1",
        public_token="tok-last-1",
        partner_id=supplier.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant.id,
        purchase_order_id=po.id,
        supplier_product_id=product.id,
        size_id=size.id,
        qty=Decimal("10"),
        received_qty=Decimal("0"),
        unit_price=Decimal("12"),
    )
    db.add(line)
    db.commit()
    return db, tenant.id, user.id, po.id, line.id, product.id, size.id, production.id


def test_last_category_is_locked():
    assert is_locked_last_category_name("楦头")
    assert not is_locked_last_category_name("模具楦头")
    assert not is_locked_last_category_name("皮料")


def test_purchase_receive_last_goes_to_tooling_not_material(ctx):
    db, tenant_id, user_id, po_id, line_id, product_id, size_id, production_id = ctx

    purchase_service.receive_po(
        db,
        tenant_id,
        po_id,
        [{"line_id": line_id, "qty": Decimal("4")}],
        user_id=user_id,
        delivery_note_no="DN-LAST",
    )

    material = db.scalars(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == product_id,
        )
    ).all()
    assert material == []

    item = db.scalar(
        select(ToolingItem).where(
            ToolingItem.tenant_id == tenant_id, ToolingItem.code == "LAST-36"
        )
    )
    assert item is not None
    assert item.kind == "shoe_last"
    stock = db.scalar(
        select(ToolingStock).where(
            ToolingStock.tooling_item_id == item.id,
            ToolingStock.size_id == size_id,
            ToolingStock.department_id == production_id,
        )
    )
    assert stock is not None
    assert stock.qty == Decimal("4")

    ap_lines = db.scalars(
        select(PayableLine).where(
            PayableLine.tenant_id == tenant_id,
            PayableLine.source_type == "purchase_receive",
        )
    ).all()
    assert len(ap_lines) == 1
    assert ap_lines[0].item_code == "LAST-36"
    assert float(ap_lines[0].amount) == 48
    assert not db.scalars(
        select(PayableLine).where(
            PayableLine.tenant_id == tenant_id,
            PayableLine.source_type == "tooling_receive",
        )
    ).all()

    ledgers = list_ledgers(db, tenant_id, item.id)
    assert len(ledgers) == 1
    assert ledgers[0]["source_label"] == "采购到货"
    assert ledgers[0]["po_no"] == "PO-LAST-1"
    assert ledgers[0]["delivery_note_no"] == "DN-LAST"
    assert ledgers[0]["department_name"] == "生产部"
    assert "notes" not in ledgers[0]

    receipts = list_receipts(db, tenant_id)
    assert len(receipts) == 1
    assert receipts[0]["from_purchase"] is True
    assert receipts[0]["code"] == "LAST-36"
    assert receipts[0]["po_no"] == "PO-LAST-1"
    assert receipts[0]["delivery_note_no"] == "DN-LAST"
    assert receipts[0]["department_name"] == "生产部"
    assert receipts[0]["total_qty"] == 4
    assert receipts[0]["sizes"] == [{"size_id": size_id, "size_value": "36", "qty": 4}]


def test_purchase_receive_last_requires_size(ctx):
    db, tenant_id, user_id, po_id, line_id, *_ = ctx
    line = db.get(PurchaseOrderLine, line_id)
    line.size_id = None
    db.commit()
    with pytest.raises(PurchaseError, match="按码"):
        purchase_service.receive_po(
            db,
            tenant_id,
            po_id,
            [{"line_id": line_id, "qty": Decimal("1")}],
            user_id=user_id,
        )
