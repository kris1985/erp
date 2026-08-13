"""干掉生产单 K4-C：无壳执行单开裁 / trace-units / 看板焦点。"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    ExecutionHeader,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    Tenant,
    TraceUnit,
    User,
    UserRole,
    Worker,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.workshop_display_service import workshop_display


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
    tenant = Tenant(name="K4C厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4C-A", is_active=True, trace_enabled=True
    )
    session.add(product)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=early.id,
                process_name=early.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=late.id,
                process_name=late.name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
        ]
    )
    session.add(Worker(tenant_id=tenant.id, name="报工员", mobile="13900004444"))
    session.add(
        User(
            tenant_id=tenant.id,
            username="k4c_admin",
            display_name="管理员",
            password_hash=hash_password("admin123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    session.commit()
    yield session
    session.close()


def _so_item(db, *, order_no: str, qty: int, product_id: int, color_id: int, size_id: int, tenant_id: int):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=qty,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant_id,
        sales_order_line_id=line.id,
        color_id=color_id,
        size_id=size_id,
        qty=qty,
        allocated_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return so, line, item


def _header_only_exe(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4C",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert exe.shop_order_id is None
    return tenant, header, exe


def test_cut_cards_for_execution_without_shop(db):
    tenant, header, exe = _header_only_exe(db)
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=20,
        only_missing=True,
        mode="bundles",
    )
    assert cut["created"]
    assert cut["execution_id"] == exe.id
    units = list(
        db.scalars(select(TraceUnit).where(TraceUnit.header_id == header.id)).all()
    )
    assert units
    assert all(u.order_id is None for u in units)
    assert all(u.header_id == header.id for u in units)


def test_api_header_trace_units_after_cut(db):
    tenant, header, exe = _header_only_exe(db)
    cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=20,
        only_missing=True,
        mode="bundles",
    )

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "k4c_admin", "password": "admin123"},
            )
            assert login.status_code == 200
            token = login.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            res = client.get(
                f"/api/v1/executions/headers/{header.id}/trace-units",
                headers=headers,
            )
            assert res.status_code == 200
            items = res.json()["data"]["items"]
            assert items
            assert all(u.get("header_id") == header.id for u in items)
    finally:
        app.dependency_overrides.clear()


def test_workshop_display_includes_header_only(db):
    tenant, header, _exe = _header_only_exe(db)
    board = workshop_display(db, tenant.id)
    nos = [o["order_no"] for o in board["focus_orders"]]
    assert header.header_no in nos
    focus = next(o for o in board["focus_orders"] if o["order_no"] == header.header_no)
    assert focus["header_id"] == header.id
    assert focus["header_no"] == header.header_no
    assert focus["shop_order_no"] is None
