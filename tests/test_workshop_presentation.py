"""PresentationBuilder —— 展示语义确定性规则测试。

验证：metric/metric_delta/table/ranking/timeseries 类型选择、用户 hint
适用性校验（标量不能渲染为趋势图）、format 元数据、原始数值保留。
"""

from __future__ import annotations

from app.runtime.workshop.presentation import PresentationBuilder


def test_scalar_metric() -> None:
    spec = PresentationBuilder().build(
        metric_id="finance.sales_snapshot",
        result_shape="scalar",
        title="本月销售额",
        value=12586000,
        context={"time_range": "2026-08"},
    )
    assert spec.type == "metric"
    assert spec.recommended_visual == "kpi"
    assert spec.value == 12586000
    assert spec.format.style == "currency"
    assert spec.format.scale == 10000
    assert spec.format.scale_label == "万元"
    assert spec.unit == "CNY"


def test_ranking() -> None:
    items = [
        {"rank": 1, "customer_name": "华东鞋服", "sales_amount": 2350000},
        {"rank": 2, "customer_name": "华南鞋业", "sales_amount": 1980000},
    ]
    spec = PresentationBuilder().build(
        metric_id="finance.customer_sales_ranking",
        result_shape="ranking",
        title="本月客户销售额 Top 2",
        items=items,
        category_key="customer_name",
        value_key="sales_amount",
        total_rows=2,
    )
    assert spec.type == "ranking"
    assert spec.recommended_visual == "horizontal_bar"
    assert spec.category_key == "customer_name"
    assert spec.items[0]["sales_amount"] == 2350000  # 原始数值，非格式化字符串


def test_table() -> None:
    spec = PresentationBuilder().build(
        metric_id="finance.customer_sales_ranking",
        result_shape="detail",
        title="客户销售明细",
        columns=[
            {"key": "customer_name", "label": "客户", "data_type": "string"},
            {"key": "sales_amount", "label": "销售额", "data_type": "number", "unit": "CNY"},
        ],
        rows=[{"customer_name": "华东鞋服", "sales_amount": 2350000}],
        total_rows=128,
    )
    assert spec.type == "table"
    assert spec.pagination is not None
    assert spec.pagination.total == 128
    assert spec.pagination.returned == 1
    assert spec.pagination.truncated is True
    assert spec.columns[1].unit == "CNY"


def test_hint_line_on_scalar_rejected() -> None:
    """用户 hint=line 但结果是标量 → 校验不适用，回退确定性规则。"""
    spec = PresentationBuilder().build(
        metric_id="finance.sales_snapshot",
        result_shape="scalar",
        title="本月销售额",
        hint="line",
        value=12586000,
    )
    assert spec.type == "metric"  # 不被渲染为趋势图
    assert spec.recommended_visual == "kpi"


def test_hint_ranking_valid() -> None:
    spec = PresentationBuilder().build(
        metric_id="finance.customer_sales_ranking",
        result_shape="ranking",
        title="客户排行",
        hint="ranking",
        items=[{"rank": 1, "customer_name": "A", "sales_amount": 1}],
        category_key="customer_name",
        value_key="sales_amount",
    )
    assert spec.type == "ranking"


def test_unknown_metric_falls_back_to_metric() -> None:
    spec = PresentationBuilder().build(
        metric_id="analytics.unknown",
        result_shape="scalar",
        title="未知指标",
        value=42,
    )
    assert spec.type == "metric"
    assert spec.format.style == "number"  # 默认元数据


def test_schema_version_pinned() -> None:
    spec = PresentationBuilder().build(
        metric_id="finance.sales_snapshot", result_shape="scalar", title="t", value=1,
    )
    assert spec.schema_version == "1.0"
