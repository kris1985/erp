from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    ProcessDefinition,
    Size,
    Style,
    StyleProcessRoute,
    Tenant,
    User,
    UserRole,
    Worker,
)
from app.services.report_service import ReportError, submit_report
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant = Tenant(name="测试厂")
    session.add(tenant)
    session.flush()
    session.add(
        User(
            tenant_id=tenant.id,
            username="admin",
            password_hash=hash_password("admin123"),
            display_name="管理员",
            role=UserRole.admin,
        )
    )
    for name, code in [("红", "R"), ("黑", "BK")]:
        session.add(Color(tenant_id=tenant.id, name=name, code=code))
    for i, v in enumerate(["37", "38"]):
        session.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))
    procs = []
    for name, code, price, seq in [
        ("裁断", "CT", "0.3", 1),
        ("针车", "ZC", "0.5", 2),
        ("成型", "CX", "0.8", 3),
    ]:
        p = ProcessDefinition(
            tenant_id=tenant.id, name=name, code=code, default_price=Decimal(price), sort_order=seq
        )
        session.add(p)
        session.flush()
        procs.append(p)
    style = Style(tenant_id=tenant.id, style_code="A款", style_name="A款红", default_color="红")
    session.add(style)
    session.flush()
    for p in procs:
        session.add(
            StyleProcessRoute(
                tenant_id=tenant.id,
                style_id=style.id,
                process_id=p.id,
                seq=p.sort_order,
                price=p.default_price,
                price_type="normal",
            )
        )
    worker = Worker(tenant_id=tenant.id, name="张三", mobile="13800138001")
    session.add(worker)
    session.commit()

    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client):
    res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    return res.json()["data"]["access_token"]


def test_login_and_create_order(client, db_session):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    styles = client.get("/api/v1/styles", headers=headers).json()["data"]["items"]
    sizes = client.get("/api/v1/sizes", headers=headers).json()["data"]["items"]
    colors = client.get("/api/v1/colors", headers=headers).json()["data"]["items"]
    res = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "order_no": "230711",
            "customer_name": "陈姐",
            "style_id": styles[0]["id"],
            "items": [{"color_id": colors[0]["id"], "size_id": sizes[0]["id"], "qty": 100}],
        },
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["order_no"] == "230711"
    assert len(body["processes"]) == 3


def test_report_salary_and_over_plan(db_session):
    tenant = db_session.query(Tenant).first()
    style = db_session.query(Style).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990001",
            customer_name="测试",
            style_id=style.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=10)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=5,
        color_name="红",
        size_value="37",
    )
    assert result["process_completed"] == 5

    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=20,
            confirm_over_plan=False,
        )
    assert ei.value.need_confirm

    result2 = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=20,
        confirm_over_plan=True,
    )
    assert result2["process_completed"] == 25

    from app.services.salary_service import month_salary
    from app.services.nlu import handle_chat

    sal = month_salary(db_session, tenant.id, worker.id)
    assert sal["total_piece_wage"] > 0

    chat = handle_chat(db_session, tenant_id=tenant.id, text="我这个月做了多少了？", worker_id=worker.id)
    assert "暂估合计" in chat["reply"]

    chat2 = handle_chat(
        db_session,
        tenant_id=tenant.id,
        text="990001 成型 做了1双",
        worker_id=worker.id,
    )
    assert "报工成功" in chat2["reply"]
