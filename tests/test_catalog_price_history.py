"""下单反馈改物料色卡单价，并留下历史。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Employee,
    Partner,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierProduct,
    SupplierProductPriceHistory,
    Tenant,
)
from app.services.purchase_service import PurchaseError, submit_po
from app.services.supplier_product_price import list_catalog_price_history, price_history_product_ids


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(price="10"):
    session = _session()
    tenant = Tenant(name="色卡厂")
    session.add(tenant)
    session.flush()
    user = Employee(tenant_id=tenant.id, name="采购", username="buyer", is_active=True)
    partner = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    session.add_all([user, partner])
    session.flush()
    product = SupplierProduct(
        tenant_id=tenant.id,
        product_code="ML-1",
        name="黑皮",
        partner_id=partner.id,
        unit_price=Decimal(price),
        is_active=True,
    )
    session.add(product)
    session.flush()
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date(2026, 10, 20),
        created_by=user.id,
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=product.id,
            qty=Decimal("2"),
            unit_price=Decimal("8"),
        )
    )
    session.commit()
    return session, tenant, user, product, po


def test_feedback_updates_catalog_and_keeps_history():
    session, tenant, user, product, po = _seed()
    submit_po(session, tenant.id, po.id, changed_by=user.id)
    session.refresh(product)
    assert product.unit_price == Decimal("8.0000")
    rows = list_catalog_price_history(session, tenant.id, product.id)
    assert len(rows) == 1
    assert rows[0]["old_price"] == Decimal("10.0000")
    assert rows[0]["new_price"] == Decimal("8.0000")
    assert rows[0]["source"] == "purchase_feedback"
    assert rows[0]["po_no"] == "PO-1"
    assert rows[0]["changed_by_name"] == "采购"
    assert price_history_product_ids(session, tenant.id, [product.id]) == {product.id}


def test_same_price_does_not_write_history():
    session, tenant, user, product, po = _seed(price="8")
    submit_po(session, tenant.id, po.id, changed_by=user.id)
    session.refresh(product)
    assert product.unit_price == Decimal("8.0000")
    assert session.scalars(select(SupplierProductPriceHistory)).all() == []


def test_price_above_catalog_does_not_change_catalog():
    session, tenant, user, product, po = _seed(price="6")
    line = session.scalar(select(PurchaseOrderLine))
    line.unit_price = Decimal("9")
    session.commit()
    try:
        submit_po(session, tenant.id, po.id, changed_by=user.id)
        raise AssertionError("高于色卡单价应被拦住")
    except PurchaseError as exc:
        assert exc.code == "price_above_catalog"
    session.refresh(product)
    assert product.unit_price == Decimal("6.0000")
    assert session.scalars(select(SupplierProductPriceHistory)).all() == []
