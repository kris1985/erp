"""Presentation Spec —— 后端展示语义协议（前端只做视觉）。

边界（架构定稿）：后端决定「数据语义与推荐展示类型」，前端决定「视觉样式
与交互」。后端输出类型化 PresentationSpec（schema_version=1.0），不输出
HTML/React 卡片；前端组件注册表渲染，未知类型降级通用表格 → 确定性 reply。

Type 选择采用确定性规则（不交给前端猜、不写大量 if metric_id ==）：

    无维度 + 单值                       → metric
    无维度 + 当前值/对比值               → metric_delta
    时间维度 + 连续周期                  → timeseries
    非时间维度 + 排序 + limit            → ranking
    多列明细或二维结果                   → table
    多个同口径指标对比                   → comparison
    多个相互独立的结果区块               → sections

用户可经 presentation_hint 提示展示方式，但后端必须校验适用性
（例如单个标量不能被渲染为趋势图）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PresentationType = Literal[
    "metric", "metric_delta", "table", "ranking", "timeseries", "comparison", "sections"
]

PresentationHint = Literal["auto", "metric", "table", "ranking", "line", "bar"]

FormatStyle = Literal["currency", "number", "percent", "date", "string"]


class FormatSpec(BaseModel):
    """数值呈现元数据（前端据此决定千分位/单位/小数位，不硬编码）。"""

    style: FormatStyle = "number"
    scale: int = 1
    scale_label: str = ""
    precision: int = 2


class ColumnSpec(BaseModel):
    key: str
    label: str
    data_type: Literal["string", "number", "date", "boolean"] = "string"
    unit: str | None = None
    format: FormatSpec | None = None


class PaginationSpec(BaseModel):
    total: int
    returned: int
    truncated: bool


class PresentationSpec(BaseModel):
    """所有展示类型的统一外壳。"""

    schema_version: Literal["1.0"] = "1.0"
    type: PresentationType
    title: str
    # 推荐展示（前端可降级：桌面横向条形图 / 移动端列表 / 用户切表格）
    recommended_visual: Literal["line", "bar", "horizontal_bar", "table", "kpi"] | None = None
    # 通用字段
    value: float | int | None = None
    unit: str | None = None
    format: FormatSpec | None = None
    context: dict[str, Any] | None = None
    # metric_delta
    comparison: dict[str, Any] | None = None
    # table
    columns: list[ColumnSpec] | None = None
    rows: list[dict[str, Any]] | None = None
    pagination: PaginationSpec | None = None
    # ranking
    category_key: str | None = None
    value_key: str | None = None
    items: list[dict[str, Any]] | None = None
    # timeseries
    x: ColumnSpec | None = None
    series: list[dict[str, Any]] | None = None
    points: list[dict[str, Any]] | None = None
    # sections
    sections: list[dict[str, Any]] | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


# ------------------------------------------------------------------ 展示元数据

class MetricPresentationMeta(BaseModel):
    """指标 Registry 的展示元数据（deterministic 规则源，不写 if metric_id）。"""

    unit: str = ""
    default_format: FormatStyle = "number"
    default_scale: int = 1
    scale_label: str = ""
    precision: int = 2
    # query shape → presentation type 的映射
    presentation_rules: dict[str, str] = Field(default_factory=dict)


# 内置注册指标（与 executor.SUPPORTED_DIRECT_METRICS 对齐；权威定义在
# workshop_metrics Registry，这里是展示语义层）
METRIC_PRESENTATION_META: dict[str, MetricPresentationMeta] = {
    "finance.customer_sales_ranking": MetricPresentationMeta(
        unit="CNY",
        default_format="currency",
        default_scale=10000,
        scale_label="万元",
        precision=1,
        presentation_rules={
            "ranking": "ranking",
            "detail": "table",
        },
    ),
    "finance.sales_snapshot": MetricPresentationMeta(
        unit="CNY",
        default_format="currency",
        default_scale=10000,
        scale_label="万元",
        precision=1,
        presentation_rules={
            "scalar": "metric",
            "time_series": "timeseries",
        },
    ),
}


class PresentationBuilder:
    """envelope/result shape → PresentationSpec（确定性规则）。"""

    def __init__(self, meta: MetricPresentationMeta | None = None) -> None:
        self._meta = meta

    # ------------------------------------------------------------------

    def build(
        self,
        *,
        metric_id: str,
        result_shape: str,
        title: str,
        hint: PresentationHint = "auto",
        value: float | int | None = None,
        unit: str | None = None,
        columns: list[dict[str, Any]] | None = None,
        rows: list[dict[str, Any]] | None = None,
        items: list[dict[str, Any]] | None = None,
        category_key: str | None = None,
        value_key: str | None = None,
        context: dict[str, Any] | None = None,
        total_rows: int | None = None,
    ) -> PresentationSpec:
        meta = self._meta or METRIC_PRESENTATION_META.get(metric_id) or MetricPresentationMeta()
        fmt = FormatSpec(
            style=meta.default_format,
            scale=meta.default_scale,
            scale_label=meta.scale_label,
            precision=meta.precision,
        )
        unit = unit or meta.unit

        # 1. user hint：先校验适用性（不适用则忽略，回退确定性规则）
        hinted = self._resolve_hint(hint, result_shape)
        if hinted is not None:
            return self._build_type(hinted, title=title, value=value, unit=unit, fmt=fmt,
                                    columns=columns, rows=rows, items=items,
                                    category_key=category_key, value_key=value_key,
                                    context=context, total_rows=total_rows)

        # 2. 确定性规则：query/result shape → type
        rule_type = meta.presentation_rules.get(result_shape)
        if rule_type is not None:
            return self._build_type(rule_type, title=title, value=value, unit=unit, fmt=fmt,
                                    columns=columns, rows=rows, items=items,
                                    category_key=category_key, value_key=value_key,
                                    context=context, total_rows=total_rows)

        # 3. 兜底：有明细 → table；有排序 items → ranking；否则 metric
        if rows:
            return self._build_type("table", title=title, value=value, unit=unit, fmt=fmt,
                                    columns=columns, rows=rows, items=items,
                                    category_key=category_key, value_key=value_key,
                                    context=context, total_rows=total_rows)
        if items:
            return self._build_type("ranking", title=title, value=value, unit=unit, fmt=fmt,
                                    columns=columns, rows=rows, items=items,
                                    category_key=category_key, value_key=value_key,
                                    context=context, total_rows=total_rows)
        return self._build_type("metric", title=title, value=value, unit=unit, fmt=fmt,
                                columns=columns, rows=rows, items=items,
                                category_key=category_key, value_key=value_key,
                                context=context, total_rows=total_rows)

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_hint(hint: PresentationHint, result_shape: str) -> PresentationType | None:
        """用户 hint 与结果形状的适用性校验（标量不能被渲染为趋势图）。"""
        mapping: dict[str, PresentationType] = {
            "metric": "metric",
            "table": "table",
            "ranking": "ranking",
        }
        if hint == "line":
            return "timeseries" if result_shape in ("time_series", "timeseries") else None
        if hint == "bar":
            return "ranking" if result_shape == "ranking" else None
        if hint in ("auto",):
            return None
        # metric hint 只适用于标量
        if hint == "metric" and result_shape != "scalar":
            return None
        return mapping.get(hint)

    def _build_type(
        self,
        type_: PresentationType,
        *,
        title: str,
        value: float | int | None,
        unit: str | None,
        fmt: FormatSpec,
        columns: list[dict[str, Any]] | None,
        rows: list[dict[str, Any]] | None,
        items: list[dict[str, Any]] | None,
        category_key: str | None,
        value_key: str | None,
        context: dict[str, Any] | None,
        total_rows: int | None,
    ) -> PresentationSpec:
        spec = PresentationSpec(
            type=type_,
            title=title,
            value=value,
            unit=unit,
            format=fmt,
            context=context,
        )
        if type_ == "metric":
            spec.recommended_visual = "kpi"
        elif type_ == "metric_delta":
            spec.recommended_visual = "kpi"
        elif type_ == "table":
            spec.recommended_visual = "table"
            spec.columns = [ColumnSpec.model_validate(c) for c in (columns or [])]
            spec.rows = [dict(r) for r in (rows or [])]
            if total_rows is not None:
                spec.pagination = PaginationSpec(
                    total=total_rows, returned=len(rows or []), truncated=total_rows > len(rows or [])
                )
        elif type_ == "ranking":
            spec.recommended_visual = "horizontal_bar"
            spec.category_key = category_key
            spec.value_key = value_key
            spec.items = [dict(item) for item in (items or [])]
        elif type_ == "timeseries":
            spec.recommended_visual = "line"
        elif type_ == "comparison":
            spec.recommended_visual = "bar"
        elif type_ == "sections":
            spec.recommended_visual = "table"
        return spec
