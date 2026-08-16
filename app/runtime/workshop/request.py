"""DirectMetricRequest —— query_metric_direct 的强类型参数（Tool args schema）。

主 Agent 通过 function calling 生成此结构；Tool 内 pydantic 重新校验（不信任
主 Agent 参数）。字段语义对齐指标注册表（Registry 是事实源，prompt 只放索引）。

v1 注册能力：finance.customer_sales_ranking（ranking）、finance.sales_snapshot
（metric_snapshot）。新指标接入 = Registry 注册 + 本模块扩展，不新增执行范式。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.runtime.contracts import RuntimeModel


class TimeRange(RuntimeModel):
    """查询期间（缺省字段不限制）。"""

    year: int | None = None
    month: int | None = None
    day: int | None = None


class OrderBy(RuntimeModel):
    field: str = "value"
    direction: Literal["asc", "desc"] = "desc"


class MetricFilter(RuntimeModel):
    field: str
    operator: Literal["gte", "lte", "eq", "gt", "lt", "in"] = "eq"
    value: float | int | str


class DirectMetricRequest(RuntimeModel):
    """强类型指标查询请求。"""

    metric_id: str
    dimensions: list[str] = Field(default_factory=list)
    time_range: TimeRange | None = None
    filters: list[MetricFilter] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = None
    include_share: bool = False
    comparison: Literal["period_top_n", "fixed_cohort"] | None = None
    presentation_hint: Literal["auto", "metric", "table", "ranking", "line", "bar"] | None = None

    def filter_value(self, field: str, operator: str | None = None) -> Any:
        """按字段取第一个匹配的 filter 值。"""
        for item in self.filters or []:
            if item.field != field:
                continue
            if operator is not None and item.operator != operator:
                continue
            return item.value
        return None
