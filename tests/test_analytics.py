"""经营诊断 analytics 基础测试。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
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
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    Tenant,
)
from app.services import analytics, workshop_metrics
from app.permissions import all_permission_codes


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
    tenant = Tenant(name="分析厂")
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    ct = ProcessDefinition(
        tenant_id=tenant.id, name="裁断", code="CT", default_price=Decimal("0.3"), sort_order=1
    )
    session.add(ct)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="A1", is_active=True)
    session.add(product)
    session.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="AN-1",
        customer_name="客A",
        own_product_id=product.id,
        total_qty=100,
        delivery_date=date.today() - timedelta(days=1),
        status=OrderStatus.confirmed,
        is_rush=True,
    )
    session.add(order)
    session.flush()
    size = session.query(Size).filter(Size.tenant_id == tenant.id).one()
    session.add(
        OrderItem(tenant_id=tenant.id, order_id=order.id, size_id=size.id, qty=100, completed_qty=10)
    )
    session.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=ct.id,
            process_name="裁断",
            process_type=ProcessType.personal,
            plan_qty=100,
            completed_qty=10,
            status=OrderProcessStatus.in_progress,
        )
    )
    product.material_cost = Decimal("10")
    product.labor_cost = Decimal("5")
    product.other_cost = Decimal("1")
    session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=ct.id,
            process_name="裁断",
            unit_price=Decimal("0.3"),
            sort_order=0,
        )
    )
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-AN-1",
        customer_name="客A",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    session.add(so)
    session.flush()
    so_line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=50,
        unit_price=Decimal("30"),
        delivery_date=date.today() + timedelta(days=10),
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    session.add(so_line)
    session.commit()
    yield session, tenant.id, {"sales_order_id": so.id, "line_id": so_line.id}
    session.close()


def test_analyze_delivery(db):
    session, tenant_id, _ = db
    res = analytics.analyze_delivery(session, tenant_id)
    assert res["analysis_id"] == "delivery_risk"
    assert res.get("summary")
    assert isinstance(res.get("insights"), list)
    assert res["insights"]


def test_weekly_brief(db):
    session, tenant_id, _ = db
    res = analytics.weekly_brief(session, tenant_id)
    assert res["analysis_id"] == "weekly_brief"
    assert "sections" in res
    assert "today_actions" in res["sections"]


def test_today_actions(db):
    session, tenant_id, _ = db
    res = analytics.build_today_actions(session, tenant_id)
    assert res["analysis_id"] == "today_actions"
    assert res.get("summary")
    actions = (res.get("data") or {}).get("actions") or []
    assert actions
    assert actions[0].get("title")
    assert "suggested_memories" in (res.get("data") or {})
    assert "playbook" in (res.get("data") or {})


def test_kit_ready(db):
    session, tenant_id, _ = db
    res = analytics.analyze_kit_ready(session, tenant_id)
    assert res["analysis_id"] == "kit_ready"
    assert res.get("summary")
    counts = (res.get("data") or {}).get("counts") or {}
    assert "can_schedule" in counts
    assert "blocked" in counts
    assert "partial" in counts
    assert "empty_bom" in counts
    # fixture 订单无 BOM → 应落入 empty_bom
    assert int(counts.get("empty_bom") or 0) >= 1


def test_order_intake(db):
    session, tenant_id, refs = db
    res = analytics.analyze_order_intake(
        session,
        tenant_id,
        lines=[{"sales_order_id": refs["sales_order_id"], "line_id": refs["line_id"]}],
    )
    assert res["analysis_id"] == "order_intake"
    data = res.get("data") or {}
    assert data.get("verdict") in ("accept", "caution", "reject", "unknown")
    assert data.get("profit")
    assert data.get("human_gate")
    assert data.get("margin_vs_peers") is not None
    assert "schedule_sim" in data
    assert data["schedule_sim"].get("sim_error") is None
    assert (data.get("profit") or {}).get("qty") == 50
    assert "无法" not in (res.get("summary") or "")
    assert "精确插单" not in (res.get("summary") or "")
    assert "material_eta" in data
    assert "customer_pay_risk" in data
    assert data["customer_pay_risk"].get("risk") in ("low", "medium", "high", "unknown")


def test_order_intake_qty_override(db):
    session, tenant_id, refs = db
    base = analytics.analyze_order_intake(
        session,
        tenant_id,
        lines=[{"sales_order_id": refs["sales_order_id"], "line_id": refs["line_id"]}],
    )
    alt = analytics.analyze_order_intake(
        session,
        tenant_id,
        lines=[{"sales_order_id": refs["sales_order_id"], "line_id": refs["line_id"]}],
        qty=200,
    )
    assert (alt.get("data") or {}).get("hypothesis") is True
    assert (alt.get("data") or {}).get("profit", {}).get("qty") == 200
    assert (base.get("data") or {}).get("profit", {}).get("qty") == 50


def test_metric_catalog_includes_analytics():
    ids = {m["id"] for m in workshop_metrics.list_metrics(permission_codes=all_permission_codes())}
    assert "analytics.delivery_risk" in ids
    assert "analytics.kit_ready" in ids
    assert "analytics.order_intake" in ids
    assert "analytics.today_actions" in ids
    assert "analytics.weekly_brief" in ids
    assert "analytics.monthly_brief" in ids


def test_query_analytics_delivery_metric(db):
    session, tenant_id, _ = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.delivery_risk",
        permission_codes=all_permission_codes(),
    )
    assert res.get("metric_id") == "analytics.delivery_risk"
    assert res.get("data", {}).get("analysis_id") == "delivery_risk"


def test_query_order_intake_metric(db):
    session, tenant_id, refs = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.order_intake",
        params={"lines": [{"sales_order_id": refs["sales_order_id"], "line_id": refs["line_id"]}]},
        permission_codes=all_permission_codes(),
    )
    assert res.get("metric_id") == "analytics.order_intake"
    assert res.get("data", {}).get("analysis_id") == "order_intake"
