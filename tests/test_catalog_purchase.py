"""色卡批量购买：按供应商拆草稿；可选 size_id 按码入库。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Partner, PurchaseOrder, PurchaseOrderLine, Size, SupplierProduct, Tenant
from app.services.purchase_service import PurchaseError, create_catalog_purchase_drafts


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
    tenant = Tenant(name="色卡厂")
    session.add(tenant)
    session.flush()
    a = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    b = Partner(tenant_id=tenant.id, name="五金店", is_supplier=True, is_active=True)
    session.add_all([a, b])
    session.flush()
    session.add(
        SupplierProduct(
            tenant_id=tenant.id,
            partner_id=a.id,
            product_code="LEATHER-1",
            name="黑皮",
            unit_price=Decimal("12.5"),
            is_active=True,
        )
    )
    session.add(
        SupplierProduct(
            tenant_id=tenant.id,
            partner_id=b.id,
            product_code="SOLE-1",
            name="大底",
            unit_price=Decimal("3"),
            is_active=True,
        )
    )
    session.add(Size(tenant_id=tenant.id, size_value="37", sort_order=37, is_active=True))
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=38, is_active=True))
    session.commit()
    yield session
    session.close()


def test_create_catalog_purchase_splits_by_supplier(db):
    tenant_id = db.scalar(select(Tenant.id))
    leather_id = db.scalar(select(SupplierProduct.id).where(SupplierProduct.product_code == "LEATHER-1"))
    sole_id = db.scalar(select(SupplierProduct.id).where(SupplierProduct.product_code == "SOLE-1"))
    created = create_catalog_purchase_drafts(
        db,
        tenant_id,
        [
            {"supplier_product_id": leather_id, "qty": Decimal("3")},
            {"supplier_product_id": sole_id, "qty": Decimal("100")},
        ],
        user_id=None,
    )
    assert len(created) == 2
    pos = db.scalars(select(PurchaseOrder)).all()
    assert len(pos) == 2
    assert all(po.notes and po.notes.startswith("色卡批量购买") for po in pos)
    lines = db.scalars(select(PurchaseOrderLine)).all()
    assert {float(l.qty) for l in lines} == {3.0, 100.0}
    assert all(l.size_id is None for l in lines)


def test_create_catalog_purchase_by_size(db):
    tenant_id = db.scalar(select(Tenant.id))
    sole_id = db.scalar(select(SupplierProduct.id).where(SupplierProduct.product_code == "SOLE-1"))
    size_37 = db.scalar(select(Size.id).where(Size.size_value == "37"))
    size_38 = db.scalar(select(Size.id).where(Size.size_value == "38"))
    created = create_catalog_purchase_drafts(
        db,
        tenant_id,
        [
            {"supplier_product_id": sole_id, "qty": Decimal("20"), "size_id": size_37},
            {"supplier_product_id": sole_id, "qty": Decimal("30"), "size_id": size_38},
        ],
        user_id=None,
    )
    assert len(created) == 1
    lines = db.scalars(select(PurchaseOrderLine)).all()
    assert len(lines) == 2
    by_size = {l.size_id: float(l.qty) for l in lines}
    assert by_size[size_37] == 20.0
    assert by_size[size_38] == 30.0


def test_create_catalog_purchase_rejects_zero_qty(db):
    tenant_id = db.scalar(select(Tenant.id))
    sole_id = db.scalar(select(SupplierProduct.id).where(SupplierProduct.product_code == "SOLE-1"))
    with pytest.raises(PurchaseError):
        create_catalog_purchase_drafts(
            db,
            tenant_id,
            [{"supplier_product_id": sole_id, "qty": 0}],
            user_id=None,
        )
