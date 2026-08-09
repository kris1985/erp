"""车间军师指标白名单。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    Size,
    Tenant,
)
from app.permissions import all_permission_codes
from app.services import workshop_metrics


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
    tenant = Tenant(name="指标厂")
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    ct = ProcessDefinition(
        tenant_id=tenant.id, name="裁断", code="CT", default_price=Decimal("0.3"), sort_order=1
    )
    session.add(ct)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="M1", is_active=True)
    session.add(product)
    session.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="MO-M1",
        customer_name="客",
        own_product_id=product.id,
        total_qty=100,
        delivery_date=date.today() + timedelta(days=10),
        status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    size = session.scalar(select(Size).where(Size.tenant_id == tenant.id))
    assert size is not None
    session.add(
        OrderItem(tenant_id=tenant.id, order_id=order.id, size_id=size.id, qty=100, completed_qty=0)
    )
    session.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=ct.id,
            process_name="裁断",
            process_type=ProcessType.personal,
            plan_qty=100,
            status=OrderProcessStatus.pending,
        )
    )
    session.commit()
    yield session, tenant.id, order.order_no
    session.close()


def test_list_metrics_respects_permissions():
    all_codes = all_permission_codes()
    full = workshop_metrics.list_metrics(permission_codes=all_codes)
    assert any(m["id"] == "finance.profit_report" for m in full)
    assert any(m["id"] == "materials.shortages" for m in full)

    limited = workshop_metrics.list_metrics(permission_codes=["menu.orders", "menu.schedule"])
    ids = {m["id"] for m in limited}
    assert "production.open_orders_board" in ids
    assert "schedule.daily_load" in ids
    assert "finance.profit_report" not in ids


def test_query_order_progress(db):
    session, tenant_id, order_no = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "production.order_progress",
        params={"order_no": order_no},
        permission_codes=["menu.orders"],
    )
    assert res.get("metric_id") == "production.order_progress"
    assert res["data"]["order_no"] == order_no


def test_query_forbidden_without_perm(db):
    session, tenant_id, _ = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "finance.profit_report",
        permission_codes=["menu.orders"],
    )
    assert res.get("error") == "forbidden"


def test_today_actions_metric_orders_or_schedule(db):
    session, tenant_id, _ = db
    by_orders = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.today_actions",
        permission_codes=["menu.orders"],
    )
    assert by_orders.get("metric_id") == "analytics.today_actions"
    analysis = by_orders.get("data") or {}
    assert (analysis.get("data") or {}).get("top3")

    by_schedule = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.today_actions",
        permission_codes=["menu.schedule"],
    )
    assert by_schedule.get("metric_id") == "analytics.today_actions"

    denied = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.today_actions",
        permission_codes=["menu.work_logs"],
    )
    assert denied.get("error") == "forbidden"


def test_unknown_metric(db):
    session, tenant_id, _ = db
    res = workshop_metrics.query_metric(
        session, tenant_id, "no.such.metric", permission_codes=all_permission_codes()
    )
    assert res.get("error") == "unknown_metric"


def test_extract_charts_from_payload():
    charts = workshop_metrics.extract_charts(
        {
            "metric_id": "x",
            "chart": {
                "type": "bar",
                "title": "t",
                "metric_id": "x",
                "x": ["a"],
                "series": [{"name": "n", "data": [1]}],
            },
        }
    )
    assert len(charts) == 1
    assert charts[0]["type"] == "bar"
    assert workshop_metrics.extract_charts("not-json") == []
    assert workshop_metrics.extract_charts({"charts": [{"type": "pie"}, "skip"]}) == [{"type": "pie"}]


def test_order_progress_includes_chart(db):
    session, tenant_id, order_no = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "production.order_progress",
        params={"order_no": order_no},
        permission_codes=["menu.orders"],
    )
    chart = res.get("chart")
    assert isinstance(chart, dict)
    assert chart.get("type") == "bar"
    assert chart.get("metric_id") == "production.order_progress"
    assert chart.get("x")
    assert chart.get("series")
