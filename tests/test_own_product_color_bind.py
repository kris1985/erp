"""一色一款：产品必须绑色；单据记下 color_id；导入不暗补多色。"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    OwnProduct,
    OwnProductColor,
    Partner,
    SalesOrderLineItem,
    Size,
    Tenant,
    Employee,
)
from app.schemas.api import SalesOrderCreate, SalesOrderLineIn, SalesOrderLineItemIn
from app.services import rbac_service
from app.services.sales_order_import import _ensure_product_color
from app.services.sales_order_service import SalesOrderError, create_sales_order


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_create_own_product_requires_color():
    db = _session()
    tenant = Tenant(name="色绑厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(admin)
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(black)
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post("/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}).json()[
            "data"
        ]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        missing = client.post("/api/v1/own-products", json={"product_code": "A-BK"}, headers=headers)
        assert missing.status_code in (400, 422)

        empty = client.post(
            "/api/v1/own-products",
            json={"product_code": "A-BK", "color_ids": []},
            headers=headers,
        )
        assert empty.status_code == 400

        ok = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "A-BK",
                "color_ids": [black.id],
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 1.2,
                        "requirement_note": "线距均匀，不得跳针",
                    }
                ],
            },
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        data = ok.json()["data"]
        assert data["color_ids"] == [black.id]
        assert data["labors"][0]["requirement_note"] == "线距均匀，不得跳针"
        pid = data["id"]

        cleared = client.patch(
            f"/api/v1/own-products/{pid}",
            json={"color_ids": []},
            headers=headers,
        )
        assert cleared.status_code == 400
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_sales_line_items_stamp_line_color():
    db = _session()
    tenant = Tenant(name="色单据厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="38", sort_order=0, is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="A-BK", is_active=True)
    customer = Partner(tenant_id=tenant.id, name="客户甲", is_customer=True, is_active=True)
    db.add_all([color, size, product, customer])
    db.flush()
    db.add(OwnProductColor(tenant_id=tenant.id, own_product_id=product.id, color_id=color.id))
    db.flush()

    so = create_sales_order(
        db,
        tenant.id,
        SalesOrderCreate(
            order_no="SO-COLOR-1",
            customer_id=customer.id,
            ordered_at=date.today(),
            lines=[
                SalesOrderLineIn(
                    own_product_id=product.id,
                    color_id=color.id,
                    unit_price=Decimal("80"),
                    items=[SalesOrderLineItemIn(size_id=size.id, qty=10)],
                )
            ],
        ),
        created_by=None,
    )
    item = db.scalar(select(SalesOrderLineItem).where(SalesOrderLineItem.sales_order_line_id == so.lines[0].id))
    assert item is not None
    assert item.color_id == color.id
    db.close()


def test_import_does_not_append_extra_color_on_bound_product():
    db = _session()
    tenant = Tenant(name="导入色厂")
    db.add(tenant)
    db.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    white = Color(tenant_id=tenant.id, name="白", code="W")
    product = OwnProduct(tenant_id=tenant.id, product_code="A-BK", is_active=True)
    db.add_all([black, white, product])
    db.flush()
    db.add(OwnProductColor(tenant_id=tenant.id, own_product_id=product.id, color_id=black.id))
    db.flush()

    _ensure_product_color(db, tenant.id, product, black.id)
    try:
        _ensure_product_color(db, tenant.id, product, white.id)
        raise AssertionError("expected invalid_color")
    except SalesOrderError as e:
        assert e.code == "invalid_color"

    unbound = OwnProduct(tenant_id=tenant.id, product_code="OLD", is_active=True)
    db.add(unbound)
    db.flush()
    _ensure_product_color(db, tenant.id, unbound, white.id)
    bound = list(
        db.scalars(select(OwnProductColor).where(OwnProductColor.own_product_id == unbound.id)).all()
    )
    assert [c.color_id for c in bound] == [white.id]
    db.close()
