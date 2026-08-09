"""A2b：质量预警浅层（款×工序不良率突增）测试。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    ReportType,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Worker,
)
from app.permissions import all_permission_codes
from app.services import analytics, workshop_metrics


def _make_order_process(session, tenant_id, order_id, process):
    op = OrderProcess(
        tenant_id=tenant_id,
        order_id=order_id,
        process_id=process.id,
        process_name=process.name,
        process_type=ProcessType.personal,
        plan_qty=1000,
        status=OrderProcessStatus.in_progress,
    )
    session.add(op)
    session.flush()
    return op


def _log(session, *, tenant_id, worker_id, order_id, order_process_id, own_product_id, process_id, qualified, defect):
    session.add(
        WorkLog(
            tenant_id=tenant_id,
            worker_id=worker_id,
            order_id=order_id,
            order_process_id=order_process_id,
            own_product_id=own_product_id,
            process_id=process_id,
            qualified_qty=qualified,
            defect_qty=defect,
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
        )
    )


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

    tenant = Tenant(name="质量预警厂")
    session.add(tenant)
    session.flush()

    process = ProcessDefinition(
        tenant_id=tenant.id, name="车帮", code="CB", default_price=Decimal("0.5"), sort_order=1
    )
    session.add(process)
    session.flush()

    worker = Worker(tenant_id=tenant.id, name="工人甲")
    session.add(worker)
    session.flush()

    product_a = OwnProduct(tenant_id=tenant.id, product_code="A1", is_active=True)
    product_b = OwnProduct(tenant_id=tenant.id, product_code="B1", is_active=True)
    product_c = OwnProduct(tenant_id=tenant.id, product_code="C1", is_active=True)
    session.add_all([product_a, product_b, product_c])
    session.flush()

    order_a = Order(
        tenant_id=tenant.id,
        order_no="QA-A1",
        customer_name="客A",
        own_product_id=product_a.id,
        total_qty=1000,
        delivery_date=date.today() + timedelta(days=20),
    )
    order_b = Order(
        tenant_id=tenant.id,
        order_no="QA-B1",
        customer_name="客A",
        own_product_id=product_b.id,
        total_qty=1000,
        delivery_date=date.today() + timedelta(days=20),
    )
    order_c = Order(
        tenant_id=tenant.id,
        order_no="QA-C1",
        customer_name="客A",
        own_product_id=product_c.id,
        total_qty=1000,
        delivery_date=date.today() + timedelta(days=20),
    )
    session.add_all([order_a, order_b, order_c])
    session.flush()

    op_a = _make_order_process(session, tenant.id, order_a.id, process)
    op_b = _make_order_process(session, tenant.id, order_b.id, process)
    op_c = _make_order_process(session, tenant.id, order_c.id, process)

    # A / C：正常波动，不良率低（2%、1.5%）
    _log(
        session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_id=order_a.id,
        order_process_id=op_a.id,
        own_product_id=product_a.id,
        process_id=process.id,
        qualified=980,
        defect=20,
    )
    _log(
        session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_id=order_c.id,
        order_process_id=op_c.id,
        own_product_id=product_c.id,
        process_id=process.id,
        qualified=985,
        defect=15,
    )
    # B：明显突增（20%），应命中预警
    _log(
        session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_id=order_b.id,
        order_process_id=op_b.id,
        own_product_id=product_b.id,
        process_id=process.id,
        qualified=800,
        defect=200,
    )
    session.commit()
    yield session, tenant.id, {"product_b_code": "B1", "process_name": "车帮"}
    session.close()


def test_list_quality_alerts_detects_spike(db):
    session, tenant_id, ctx = db
    res = analytics.list_quality_alerts(session, tenant_id, days=30)
    assert res["analysis_id"] == "quality_alerts"
    assert res.get("summary")
    data = res.get("data") or {}
    alerts = data.get("alerts") or []
    assert 1 <= len(alerts) <= 5
    top = alerts[0]
    assert top["product_code"] == ctx["product_b_code"]
    assert top["process_name"] == ctx["process_name"]
    assert top["defect_rate_pct"] > top["baseline_rate_pct"]
    assert top["chip_label"]
    assert ctx["product_b_code"] in top["chip_label"]
    assert top["suggestion"]
    assert top["severity"] in ("high", "medium")
    # A/C 未突增，不应混进结果
    codes = {a["product_code"] for a in alerts}
    assert "A1" not in codes
    assert "C1" not in codes


def test_list_quality_alerts_limit_and_bounds(db):
    session, tenant_id, _ = db
    res = analytics.list_quality_alerts(session, tenant_id, days=30, limit=1)
    alerts = (res.get("data") or {}).get("alerts") or []
    assert len(alerts) <= 1
    # limit 下限保护（<2 强制拉到 2，但候选数不足时仍以候选数为准）
    res2 = analytics.list_quality_alerts(session, tenant_id, days=30, limit=0)
    alerts2 = (res2.get("data") or {}).get("alerts") or []
    assert isinstance(alerts2, list)


def test_list_quality_alerts_empty_when_no_worklogs():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="空厂")
    session.add(tenant)
    session.commit()
    try:
        res = analytics.list_quality_alerts(session, tenant.id, days=14)
        assert res["analysis_id"] == "quality_alerts"
        data = res.get("data") or {}
        assert data.get("alerts") == []
        assert data.get("count") == 0
    finally:
        session.close()


def test_today_actions_includes_quality_alert_evidence(db):
    session, tenant_id, ctx = db
    res = analytics.build_today_actions(session, tenant_id)
    actions = (res.get("data") or {}).get("actions") or []
    quality_action = next((a for a in actions if a.get("id") == "quality_watch"), None)
    assert quality_action is not None
    facts = " ".join(quality_action.get("evidence", {}).get("facts") or [])
    assert ctx["product_b_code"] in facts
    extra = quality_action.get("evidence", {}).get("extra") or {}
    assert extra.get("quality_alerts")


def test_metric_catalog_includes_quality_alerts():
    ids = {m["id"] for m in workshop_metrics.list_metrics(permission_codes=all_permission_codes())}
    assert "analytics.quality_alerts" in ids


def test_query_quality_alerts_metric(db):
    session, tenant_id, ctx = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.quality_alerts",
        params={"days": 30},
        permission_codes=all_permission_codes(),
    )
    assert res.get("metric_id") == "analytics.quality_alerts"
    data = res.get("data", {}).get("data") or {}
    alerts = data.get("alerts") or []
    assert alerts
    assert alerts[0]["product_code"] == ctx["product_b_code"]


def test_query_quality_alerts_metric_forbidden_without_permission(db):
    session, tenant_id, _ = db
    res = workshop_metrics.query_metric(
        session,
        tenant_id,
        "analytics.quality_alerts",
        permission_codes=set(),
    )
    assert res.get("error") == "forbidden"
