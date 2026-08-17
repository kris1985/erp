"""B2c：生产单变更版本 — qty/交期变更留痕；无实质变化不留痕；复用 sync_requirements_after_qty_change。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Employee,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    Size,
    Tenant,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services import order_service, rbac_service
from app.services.order_change_service import list_order_change_logs


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


def _seed(db):
    tenant = Tenant(name="变更厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    color2 = Color(tenant_id=tenant.id, name="白", code="WH")
    size37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    size38 = Size(tenant_id=tenant.id, size_value="38", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="BC-01", quote_price=Decimal("80"))
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        sort_order=1,
        type=ProcessType.personal,
    )
    user = Employee(
        tenant_id=tenant.id,
        username="pmc1",
        name="跟单小李",
    )
    db.add_all([color, color2, size37, size38, product, zc])
    db.flush()
    db.add(user)
    db.flush()
    rbac_service.set_employee_roles(db, user, ["manager"])
    from app.models import OwnProductLabor

    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=zc.id,
            process_name="针车",
            unit_price=Decimal("1.5"),
            sort_order=1,
        )
    )
    db.flush()

    order = order_service.create_order(
        db,
        tenant.id,
        OrderCreate(
            order_no="BC-001",
            customer_name="测试客户",
            own_product_id=product.id,
            delivery_date=date.today() + timedelta(days=10),
            items=[
                OrderItemIn(color_id=color.id, size_id=size37.id, qty=100),
                OrderItemIn(color_id=color.id, size_id=size38.id, qty=100),
            ],
        ),
        created_by=user.id,
    )
    return {
        "tenant": tenant,
        "color": color,
        "color2": color2,
        "size37": size37,
        "size38": size38,
        "product": product,
        "user": user,
        "order": order,
    }


def test_qty_and_delivery_change_creates_version(db):
    ctx = _seed(db)
    order = ctx["order"]

    # 无变化时不应有历史
    assert list_order_change_logs(db, ctx["tenant"].id, order.id) == []

    new_delivery = date.today() + timedelta(days=20)
    order_service.update_order(
        db,
        ctx["tenant"].id,
        order.id,
        delivery_date=new_delivery,
        items=[
            OrderItemIn(color_id=ctx["color"].id, size_id=ctx["size37"].id, qty=120),
            OrderItemIn(color_id=ctx["color"].id, size_id=ctx["size38"].id, qty=100),
            OrderItemIn(color_id=ctx["color2"].id, size_id=ctx["size37"].id, qty=50),
        ],
        changed_by=ctx["user"].id,
    )

    logs = list_order_change_logs(db, ctx["tenant"].id, order.id)
    assert len(logs) == 1
    log = logs[0]
    assert log["version_no"] == 1
    assert "qty" in log["change_type"]
    assert "delivery_date" in log["change_type"]
    assert log["created_by_name"] == "跟单小李"
    assert log["before"]["total_qty"] == 200
    assert log["after"]["total_qty"] == 270
    assert log["before"]["delivery_date"] != log["after"]["delivery_date"]
    assert "总数 200→270" in log["summary"]
    assert "交期" in log["summary"]

    # 数据库中订单确实已更新
    refreshed = order_service.get_order(db, ctx["tenant"].id, order.id)
    assert refreshed.total_qty == 270
    assert refreshed.delivery_date == new_delivery


def test_non_meaningful_change_does_not_create_version(db):
    ctx = _seed(db)
    order = ctx["order"]

    order_service.update_order(
        db,
        ctx["tenant"].id,
        order.id,
        notes="改个备注",
        is_rush=True,
        rush_reason="客户催货",
        changed_by=ctx["user"].id,
    )

    assert list_order_change_logs(db, ctx["tenant"].id, order.id) == []


def test_multiple_changes_increment_version(db):
    ctx = _seed(db)
    order = ctx["order"]

    order_service.update_order(
        db,
        ctx["tenant"].id,
        order.id,
        items=[
            OrderItemIn(color_id=ctx["color"].id, size_id=ctx["size37"].id, qty=150),
            OrderItemIn(color_id=ctx["color"].id, size_id=ctx["size38"].id, qty=100),
        ],
        changed_by=ctx["user"].id,
    )
    order_service.update_order(
        db,
        ctx["tenant"].id,
        order.id,
        delivery_date=date.today() + timedelta(days=30),
        changed_by=ctx["user"].id,
    )

    logs = list_order_change_logs(db, ctx["tenant"].id, order.id)
    assert [l["version_no"] for l in logs] == [2, 1]
    assert logs[0]["change_type"] == "delivery_date"
    assert logs[1]["change_type"] == "qty"
