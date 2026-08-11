"""公开采购单预览：免登录、不含单价金额。"""

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
    SupplierProduct,
    Tenant,
)
from app.services import purchase_service


def test_public_po_out_omits_prices():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="公开预览厂")
        db.add(tenant)
        db.flush()
        partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
        db.add(partner)
        db.flush()
        sp = SupplierProduct(
            tenant_id=tenant.id,
            partner_id=partner.id,
            product_code="底-37",
            name="大底",
            unit_price=Decimal("9.5"),
        )
        db.add(sp)
        db.flush()
        po = PurchaseOrder(
            tenant_id=tenant.id,
            po_no="PO-PUB-1",
            public_token="tok-public-1",
            partner_id=partner.id,
            status=PurchaseOrderStatus.ordered,
        )
        db.add(po)
        db.flush()
        db.add(
            PurchaseOrderLine(
                tenant_id=tenant.id,
                purchase_order_id=po.id,
                supplier_product_id=sp.id,
                qty=Decimal("12"),
                unit_price=Decimal("9.5"),
                received_qty=Decimal("0"),
            )
        )
        db.commit()

        out = purchase_service.public_po_out(db, po)
        assert out["po_no"] == "PO-PUB-1"
        assert "summary_total_amount" not in out
        assert out["summary_lines"]
        line = out["summary_lines"][0]
        assert Decimal(str(line["qty"])) == Decimal("12")
        assert "unit_price" not in line
        assert "amount" not in line
    finally:
        db.close()
