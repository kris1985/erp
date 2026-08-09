"""A2a：出货前放货回款提示 — 复用 finance_service.customer_pay_risk。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Order, OrderStatus, OwnProduct, Partner, Receivable, ReceivableStatus, Tenant
from app.services import finance_service
from app.api.v1.partners import get_partner_pay_risk


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


def _seed_customer(db, *, aging_60_balance: Decimal | None = None) -> tuple[int, int]:
    tenant = Tenant(name="放货提示厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="回款客户", is_customer=True, is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="A2A-1")
    db.add_all([partner, product])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="A2A-ORD-1",
        customer_id=partner.id,
        customer_name=partner.name,
        own_product_id=product.id,
        total_qty=10,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    if aging_60_balance is not None:
        db.add(
            Receivable(
                tenant_id=tenant.id,
                customer_id=partner.id,
                customer_name=partner.name,
                order_id=order.id,
                receivable_date=date.today() - timedelta(days=75),
                amount=aging_60_balance,
                adjustment=Decimal("0"),
                received_amount=Decimal("0"),
                status=ReceivableStatus.open,
            )
        )
    db.commit()
    return tenant.id, partner.id


class _FakeUser:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id


def test_customer_pay_risk_high_for_aged_ar(db):
    tenant_id, partner_id = _seed_customer(db, aging_60_balance=Decimal("5000"))
    risk = finance_service.customer_pay_risk(db, tenant_id, customer_id=partner_id)
    assert risk["risk"] == "high"
    assert risk["reasons"]
    assert risk["open_balance"] == 5000.0


def test_customer_pay_risk_low_without_open_ar(db):
    tenant_id, partner_id = _seed_customer(db)
    risk = finance_service.customer_pay_risk(db, tenant_id, customer_id=partner_id)
    assert risk["risk"] == "low"
    assert risk["open_balance"] == 0


def test_partner_pay_risk_endpoint_reuses_service(db):
    """thin GET /partners/{id}/pay-risk：直接调用路由函数验证接线正确。"""
    tenant_id, partner_id = _seed_customer(db, aging_60_balance=Decimal("3000"))
    resp = get_partner_pay_risk(partner_id, db=db, user=_FakeUser(tenant_id))
    data = resp["data"] if isinstance(resp, dict) and "data" in resp else resp
    assert data["risk"] == "high"
    assert data["customer_id"] == partner_id


def test_partner_pay_risk_endpoint_unknown_partner_404(db):
    from fastapi import HTTPException

    tenant_id, _partner_id = _seed_customer(db)
    with pytest.raises(HTTPException):
        get_partner_pay_risk(999999, db=db, user=_FakeUser(tenant_id))
