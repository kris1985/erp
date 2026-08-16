"""DirectMetricExecutor —— 强类型可信执行层测试（Unified DeepAgent 主路径）。

覆盖：ranking/snapshot 成功执行、权限拒绝、未注册指标、limit 越界、
artifact 契约（status/reply/presentation）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.runtime.workshop.executor import DirectMetricExecutor
from app.runtime.workshop.request import DirectMetricRequest
from app.services import analysis_result_store, finance_service, workshop_metrics

FAKE_ORDERS = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    {"customer_name": "客户 C", "revenue": Decimal("7600000")},
    {"customer_name": "客户 D", "revenue": Decimal("4500000")},
]
TOTAL = Decimal("34250000")


def fake_profit_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None, date_from=None, date_to=None, loss_only=False):
    return {"orders": FAKE_ORDERS, "summary": {"revenue": TOTAL}, "year": year}


@pytest.fixture(autouse=True)
def _fake_report(monkeypatch):
    monkeypatch.setattr(finance_service, "profit_report", fake_profit_report)


@pytest.fixture(autouse=True)
def _tmp_result_store(monkeypatch, tmp_path):
    def fake_settings():
        return type(
            "Settings",
            (),
            {
                "schedule_agent_data_dir": str(tmp_path),
                "analysis_result_ttl_seconds": 3600,
                "analysis_result_max_per_session": 200,
            },
        )()

    monkeypatch.setattr(analysis_result_store, "get_settings", fake_settings)


def _visible_metrics(monkeypatch, ids: list[str]) -> None:
    items = [{"id": mid, "name": mid, "description": mid} for mid in ids]
    monkeypatch.setattr(workshop_metrics, "list_metrics", lambda permission_codes=None: items)


def _exec(monkeypatch, request: DirectMetricRequest, *, tenant_id: int = 1, perms: list[str] | None = None, visible: list[str] | None = None) -> dict:
    _visible_metrics(monkeypatch, visible if visible is not None else ["finance.customer_sales_ranking", "finance.sales_snapshot"])
    return DirectMetricExecutor().execute(
        None,
        tenant_id=tenant_id,
        conversation_id="c1",
        permission_codes=perms or [],
        request=request,
    )


def test_ranking_success(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.customer_sales_ranking",
        dimensions=["customer"],
        time_range={"year": 2026},
        order_by=[{"field": "value", "direction": "desc"}],
        limit=3,
    ))
    assert artifact["status"] == "success"
    assert artifact["reason_code"] == "SUCCESS"
    assert artifact["presentation"]["type"] == "ranking"
    assert artifact["presentation"]["recommended_visual"] == "horizontal_bar"
    assert len(artifact["presentation"]["items"]) == 3
    assert artifact["presentation"]["items"][0]["customer_name"] == "客户 A"
    assert artifact["result"]["items"][0]["sales_amount"] == 12350000.0
    assert "客户 A" in artifact["reply"]


def test_ranking_share_derivation(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.customer_sales_ranking",
        dimensions=["customer"],
        time_range={"year": 2026},
        limit=2,
        include_share=True,
    ))
    assert artifact["status"] == "success"
    assert artifact["trust_metrics"]["verified_assertions"] >= 1


def test_snapshot_success(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.sales_snapshot",
        time_range={"year": 2026, "month": 8},
    ))
    assert artifact["status"] == "success"
    assert artifact["presentation"]["type"] == "metric"
    assert artifact["presentation"]["recommended_visual"] == "kpi"
    assert artifact["presentation"]["value"] == 34250000.0
    assert artifact["presentation"]["format"]["style"] == "currency"
    assert artifact["presentation"]["format"]["scale_label"] == "万元"
    assert artifact["result"]["value"] == 34250000.0


def test_permission_denied(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.sales_snapshot", time_range={"year": 2026},
    ), visible=[])
    assert artifact["status"] == "rejected"
    assert artifact["reason_code"] == "POLICY_DENIED"


def test_unsupported_metric_model_error(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="analytics.not_registered", time_range={"year": 2026},
    ))
    assert artifact["status"] == "model_argument_error"
    assert artifact["reason_code"] == "UNSUPPORTED_DIRECT_METRIC"
    assert "未能形成有效查询" in artifact["reply"]


def test_invalid_limit_model_error(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.customer_sales_ranking",
        dimensions=["customer"],
        time_range={"year": 2026},
        limit=99999,
    ))
    assert artifact["status"] == "model_argument_error"
    assert artifact["reason_code"] == "INVALID_LIMIT"


def test_unsupported_dimension_model_error(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.customer_sales_ranking",
        dimensions=["product"],
        time_range={"year": 2026},
    ))
    assert artifact["status"] == "model_argument_error"
    assert artifact["reason_code"] == "UNSUPPORTED_DIMENSION"


def test_min_amount_filter_applied(monkeypatch) -> None:
    artifact = _exec(monkeypatch, DirectMetricRequest(
        metric_id="finance.customer_sales_ranking",
        dimensions=["customer"],
        time_range={"year": 2026},
        filters=[{"field": "sales_amount", "operator": "gte", "value": 10000000}],
    ))
    assert artifact["status"] == "success"
    items = artifact["presentation"]["items"]
    # min_amount=1000万 滤掉客户 B（980万）
    assert len(items) == 1
    assert items[0]["customer_name"] == "客户 A"
