"""物料仓手工入库：同步色卡和供应商，并增加库存。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    Employee,
    MaterialCategory,
    Partner,
    PricingUnit,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(session):
    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _setup():
    session = _session()
    tenant = Tenant(name="入库厂")
    session.add(tenant)
    session.flush()
    user = Employee(tenant_id=tenant.id, name="仓管", username="admin", is_active=True)
    category = MaterialCategory(tenant_id=tenant.id, name="皮料", is_active=True)
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="38", is_active=True)
    unit = PricingUnit(tenant_id=tenant.id, name="米", is_active=True)
    customer = Partner(tenant_id=tenant.id, name="老客户", is_customer=True, is_active=True)
    session.add_all([user, category, color, size, unit, customer])
    session.commit()
    return session, user


def test_manual_receive_creates_supplier_color_card_and_stock():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    category = session.scalar(select(MaterialCategory))
    color = session.scalar(select(Color))
    unit = session.scalar(select(PricingUnit))
    try:
        res = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-001",
                "name": "黑皮",
                "supplier_name": "新皮料商",
                "qty": "12.5",
                "category_id": category.id,
                "color_id": color.id,
                "pricing_unit_id": unit.id,
                "unit_price": "3.5",
                "image_url": "/uploads/black.jpg",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["product_created"] is True
        assert body["partner_created"] is True
        assert Decimal(str(body["qty"])) == Decimal("12.5")

        product = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "ML-001"))
        partner = session.get(Partner, product.partner_id)
        assert product.name == "黑皮"
        assert product.category_id == category.id
        assert product.color_id == color.id
        assert product.pricing_unit_id == unit.id
        assert product.unit_price == Decimal("3.5000") or product.unit_price == Decimal("3.5")
        assert product.image_url == "/uploads/black.jpg"
        assert partner.name == "新皮料商"
        assert partner.is_supplier is True

        listed = client.get("/api/v1/shared-materials", headers=headers)
        rows = listed.json()["data"]
        assert len(rows) == 1
        assert rows[0]["supplier_product_code"] == "ML-001"
        assert rows[0]["partner_name"] == "新皮料商"
        assert rows[0]["category_name"] == "皮料"

        ledger = session.scalar(select(SharedMaterialLedger))
        assert ledger.ledger_type == SharedLedgerType.manual_receive
        assert ledger.qty_delta == Decimal("12.5")
        assert ledger.note == "手工入库"
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_updates_card_adds_qty_and_reuses_supplier():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    category = session.scalar(select(MaterialCategory))
    color = session.scalar(select(Color))
    size = session.scalar(select(Size))
    try:
        first = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-002",
                "name": "原名",
                "supplier_name": "新皮料商",
                "qty": "2",
                "unit_price": "1",
                "image_url": "/uploads/old.jpg",
            },
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-002",
                "name": "新名",
                "supplier_name": "新皮料商",
                "qty": "3",
                "category_id": category.id,
                "color_id": color.id,
                "size_id": size.id,
                "unit_price": "4",
            },
        )
        assert second.status_code == 200, second.text
        body = second.json()["data"]
        assert body["product_created"] is False
        assert body["partner_created"] is False
        assert Decimal(str(body["qty"])) == Decimal("3")

        session.expire_all()
        product = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "ML-002"))
        assert product.name == "新名"
        assert product.image_url == "/uploads/old.jpg"
        assert product.unit_price == Decimal("4.0000") or product.unit_price == Decimal("4")
        partners = session.scalars(select(Partner).where(Partner.name == "新皮料商")).all()
        assert len(partners) == 1
        stocks = session.scalars(select(SharedMaterialStock).order_by(SharedMaterialStock.id)).all()
        assert len(stocks) == 2
        assert stocks[0].size_id is None
        assert stocks[0].qty == Decimal("2")
        assert stocks[1].size_id == size.id
        assert stocks[1].qty == Decimal("3")
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_marks_existing_partner_as_supplier():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        res = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-003",
                "name": "扣件",
                "supplier_name": "老客户",
                "qty": "1",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["partner_created"] is False
        session.expire_all()
        partner = session.scalar(select(Partner).where(Partner.name == "老客户"))
        assert partner.is_customer is True
        assert partner.is_supplier is True
        assert session.scalar(select(Partner.id).where(Partner.name == "老客户").limit(1))
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_rejects_bad_qty_and_foreign_category():
    session, user = _setup()
    other = Tenant(name="别厂")
    session.add(other)
    session.flush()
    foreign = MaterialCategory(tenant_id=other.id, name="别类", is_active=True)
    session.add(foreign)
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        empty = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={"product_code": "ML-004", "name": "扣件", "supplier_name": "甲", "qty": "0"},
        )
        assert empty.status_code == 400
        assert "数量" in empty.json()["detail"]

        bad = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-004",
                "name": "扣件",
                "supplier_name": "甲",
                "qty": "1",
                "category_id": foreign.id,
            },
        )
        assert bad.status_code == 400
        assert "分类" in bad.json()["detail"]
        assert session.scalar(select(SupplierProduct.id)) is None
    finally:
        app.dependency_overrides.clear()
