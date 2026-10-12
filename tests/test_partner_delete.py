"""合作商删除：未被业务引用可删；有引用则拒绝。"""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.partners import create_partner, delete_partner
from app.db import Base
from app.models import Partner, PartnerContact, PartnerSettlementPolicy, SupplierProduct, Tenant
from app.schemas.api import PartnerCreate


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


class _User:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id


def _tenant(db) -> int:
    t = Tenant(name="合作商删除厂")
    db.add(t)
    db.flush()
    return t.id


def test_delete_unreferenced_partner_and_owned_rows(db):
    tenant_id = _tenant(db)
    user = _User(tenant_id)
    created = create_partner(
        PartnerCreate(
            name="可删供应商",
            is_supplier=True,
            contacts=[{"name": "张三", "is_primary": True}],
        ),
        db,
        user,
    )["data"]
    pid = created["id"]
    assert db.get(Partner, pid)
    assert db.scalar(select(PartnerContact).where(PartnerContact.partner_id == pid))

    out = delete_partner(pid, db=db, user=user)
    assert out["data"]["deleted"] is True
    assert db.get(Partner, pid) is None
    assert db.scalar(select(PartnerContact).where(PartnerContact.partner_id == pid)) is None
    assert (
        db.scalar(select(PartnerSettlementPolicy).where(PartnerSettlementPolicy.partner_id == pid))
        is None
    )


def test_delete_partner_blocked_when_referenced(db):
    tenant_id = _tenant(db)
    user = _User(tenant_id)
    created = create_partner(
        PartnerCreate(name="有色卡供应商", is_supplier=True),
        db,
        user,
    )["data"]
    pid = created["id"]
    db.add(
        SupplierProduct(
            tenant_id=tenant_id,
            product_code="SP-DEL-1",
            name="皮料",
            partner_id=pid,
            unit_price=Decimal("1"),
            is_active=True,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as ei:
        delete_partner(pid, db=db, user=user)
    assert ei.value.status_code == 400
    assert "物料色卡" in str(ei.value.detail)
    assert db.get(Partner, pid) is not None
