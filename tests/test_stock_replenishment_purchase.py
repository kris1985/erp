"""备库采购：安全库存 − 可用/在途/草稿 → 生成不挂销售的采购草稿。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Partner, PurchaseOrder, PurchaseOrderLine, SupplierProduct, Tenant
from app.services.purchase_service import (
    PurchaseError,
    create_stock_replenishment_drafts,
    list_stock_replenishment,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="备库厂")
    session.add(tenant)
    session.flush()
    partner = Partner(tenant_id=tenant.id, name="五金店", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    session.add(
        SupplierProduct(
            tenant_id=tenant.id,
            partner_id=partner.id,
            product_code="NAIL-1",
            name="钉子",
            unit_price=Decimal("0.5"),
            min_stock_qty=Decimal("100"),
            is_active=True,
        )
    )
    session.add(
        SupplierProduct(
            tenant_id=tenant.id,
            partner_id=partner.id,
            product_code="HAMMER-1",
            name="锤子",
            unit_price=Decimal("20"),
            min_stock_qty=None,
            is_active=True,
        )
    )
    session.commit()
    yield session
    session.close()


def test_list_stock_replenishment_below_min(db):
    tenant_id = db.scalar(select(Tenant.id))
    rows = list_stock_replenishment(db, tenant_id, below_only=True)
    assert len(rows) == 1
    assert rows[0]["supplier_product_code"] == "NAIL-1"
    assert Decimal(str(rows[0]["buy_qty"])) == Decimal("100")
    assert rows[0]["can_create_draft"] is True


def test_create_stock_replenishment_drafts(db):
    tenant_id = db.scalar(select(Tenant.id))
    sp_id = db.scalar(select(SupplierProduct.id).where(SupplierProduct.product_code == "NAIL-1"))
    created = create_stock_replenishment_drafts(db, tenant_id, [sp_id], user_id=None)
    assert len(created) == 1
    po = db.scalar(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()))
    assert po is not None
    assert po.notes and po.notes.startswith("备库")
    pl = db.scalar(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
    assert pl is not None
    assert pl.sales_order_id is None
    assert pl.order_material_requirement_id is None
    assert Decimal(str(pl.qty)) == Decimal("100")

    rows = list_stock_replenishment(db, tenant_id, below_only=True)
    assert rows == []
    with pytest.raises(PurchaseError):
        create_stock_replenishment_drafts(db, tenant_id, [sp_id], user_id=None)
