"""生产单列表：服务端排序 + 状态统计。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderStatus, OwnProduct, Size, Tenant
from app.services.order_service import count_orders_by_status, list_orders


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
    tenant = Tenant(name="排序厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="红", code="R")
    size = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    p_b = OwnProduct(tenant_id=tenant.id, product_code="B款", quote_price=Decimal("1"))
    p_a = OwnProduct(tenant_id=tenant.id, product_code="A款", quote_price=Decimal("1"))
    db.add_all([color, size, p_b, p_a])
    db.flush()
    o1 = Order(
        tenant_id=tenant.id,
        order_no="O-2",
        customer_name="客",
        own_product_id=p_b.id,
        style_id=p_b.id,
        total_qty=10,
        delivery_date=date.today() + timedelta(days=5),
        status=OrderStatus.confirmed,
        is_rush=False,
    )
    o2 = Order(
        tenant_id=tenant.id,
        order_no="O-1",
        customer_name="客",
        own_product_id=p_a.id,
        style_id=p_a.id,
        total_qty=30,
        delivery_date=date.today() + timedelta(days=2),
        status=OrderStatus.in_progress,
        is_rush=False,
    )
    o3 = Order(
        tenant_id=tenant.id,
        order_no="O-RUSH",
        customer_name="客",
        own_product_id=p_a.id,
        style_id=p_a.id,
        total_qty=5,
        delivery_date=date.today() + timedelta(days=9),
        status=OrderStatus.confirmed,
        is_rush=True,
    )
    db.add_all([o1, o2, o3])
    db.commit()
    return tenant


def test_sort_product_code_and_qty(db):
    tenant = _seed(db)
    rows, _ = list_orders(db, tenant.id, sort_by="product_code", sort_order="asc")
    # 急单仍置顶，其后按货号
    assert rows[0].order_no == "O-RUSH"
    assert [r.order_no for r in rows[1:]] == ["O-1", "O-2"]

    rows, _ = list_orders(db, tenant.id, sort_by="total_qty", sort_order="desc")
    assert rows[0].order_no == "O-RUSH"
    assert [r.total_qty for r in rows[1:]] == [30, 10]


def test_sort_delivery_and_status_stats(db):
    tenant = _seed(db)
    rows, _ = list_orders(db, tenant.id, sort_by="delivery_date", sort_order="asc")
    assert rows[0].order_no == "O-RUSH"
    assert [r.order_no for r in rows[1:]] == ["O-1", "O-2"]

    st = count_orders_by_status(db, tenant.id)
    assert st["total"] == 3
    assert st["by_status"]["confirmed"] == 2
    assert st["by_status"]["in_progress"] == 1
