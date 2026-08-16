"""Typed analysis planning for the workshop assistant.

LLMs may propose a semantic plan, but only this registry may resolve it into
read-only ERP queries.  The first registered finance plans deliberately cover
the existing profit snapshot/comparison journey; new domains extend the
registry instead of adding prompt-only branches.
"""

from __future__ import annotations

import re
import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.agent_policy import get_policy_bundle


AnalysisType = Literal[
    "metric_snapshot", "period_comparison", "time_series", "ranking",
    "composition", "data_table", "exception_list", "decision", "scenario", "attribution_analysis",
]
Order = Literal["asc", "desc"]


class _ConstrainedModel(BaseModel):
    """Reject surplus JSON keys so a planner cannot invent executable knobs."""

    model_config = ConfigDict(extra="forbid")


class TimeRange(_ConstrainedModel):
    year: int | None = None
    month: int | None = None
    months: int | None = Field(default=None, ge=1, le=36)


class SemanticPlan(_ConstrainedModel):
    analysis_type: AnalysisType
    metric: str | None = None
    dimension: str | None = None
    entity: str | None = None
    risk_condition: str | None = None
    columns: list[str] | None = Field(default=None, max_length=8)
    base_facts: dict[str, object] | None = None
    assumptions: dict[str, str | int | float | bool] | None = None
    calculation_method: str | None = None
    comparison_target: str | None = None
    time_range: TimeRange | None = None
    baseline: TimeRange | None = None
    time_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    order: Order | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class QueryStep(BaseModel):
    metric_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    execution_plan_id: str = Field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:16]}")
    analysis_type: AnalysisType
    semantic_metric: str
    steps: list[QueryStep]
    result_shape: AnalysisType


class PlannerOutput(_ConstrainedModel):
    """Client/trace-safe result of constrained semantic planning."""

    semantic_plan_id: str
    plan: SemanticPlan | None = None
    missing_slots: list[str] = Field(default_factory=list)


def parse_planner_json(payload: str | dict[str, object]) -> PlannerOutput:
    """Validate an LLM planner proposal against the registered JSON contract.

    The caller may only resolve ``output.plan`` when ``missing_slots`` is
    empty.  Unknown analysis types, extra keys and unregistered metrics fail
    closed rather than falling through to prompt interpretation.
    """
    try:
        raw = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_semantic_plan_json") from exc
    if not isinstance(raw, dict):
        raise ValueError("invalid_semantic_plan_json")
    try:
        plan = SemanticPlan.model_validate(raw)
    except Exception as exc:
        raise ValueError("invalid_semantic_plan_json") from exc
    missing_slots = validate_semantic_plan(plan)
    if "metric_not_allowed" in missing_slots:
        raise ValueError("unregistered_semantic_metric")
    return PlannerOutput(
        semantic_plan_id=f"sp_{uuid.uuid4().hex[:16]}", plan=plan,
        missing_slots=missing_slots,
    )


@dataclass(frozen=True)
class AnalysisSpec:
    required_slots: tuple[str, ...]
    allowed_metrics: tuple[str, ...]
    result_shape: AnalysisType


def _registry_from_policy() -> dict[AnalysisType, AnalysisSpec]:
    return {
        name: AnalysisSpec(tuple(spec.required_slots), tuple(spec.allowed_metrics), spec.result_shape)  # type: ignore[arg-type]
        for name, spec in get_policy_bundle().analysis_registry.analysis_types.items()
    }


# Kept as a public compatibility surface; its source of truth is YAML.
REGISTRY = _registry_from_policy()


def validate_semantic_plan(plan: SemanticPlan) -> list[str]:
    spec = REGISTRY[plan.analysis_type]
    missing = [slot for slot in spec.required_slots if getattr(plan, slot, None) is None]
    if plan.metric and spec.allowed_metrics and plan.metric not in spec.allowed_metrics:
        missing.append("metric_not_allowed")
    # No registered metric currently supports arbitrary filters.  Accepting
    # and then silently discarding one would turn a precise question into a
    # broader query, so fail closed until a registry entry declares support.
    if plan.filters:
        missing.append("filters_not_allowed")
    return missing


def resolve_execution_plan(plan: SemanticPlan) -> ExecutionPlan:
    """Resolve a validated plan through a tiny, deterministic metric catalog."""
    issues = validate_semantic_plan(plan)
    if issues:
        raise ValueError("invalid_semantic_plan:" + ",".join(issues))
    if plan.analysis_type == "metric_snapshot":
        assert plan.time_range
        metric_id = get_policy_bundle().metric_catalog.metrics[plan.metric].metric_id
        return ExecutionPlan(
            analysis_type=plan.analysis_type,
            semantic_metric=plan.metric,
            result_shape="metric_snapshot",
            steps=[QueryStep(metric_id=metric_id, params=plan.time_range.model_dump(exclude_none=True))],
        )
    if plan.analysis_type == "period_comparison":
        assert plan.time_range and plan.baseline and plan.metric
        return ExecutionPlan(
            analysis_type=plan.analysis_type,
            semantic_metric=plan.metric,
            result_shape="period_comparison",
            steps=[
                QueryStep(metric_id=get_policy_bundle().metric_catalog.metrics[plan.metric].metric_id, params=plan.time_range.model_dump(exclude_none=True)),
                QueryStep(metric_id=get_policy_bundle().metric_catalog.metrics[plan.metric].metric_id, params=plan.baseline.model_dump(exclude_none=True)),
            ],
        )
    if plan.analysis_type == "ranking":
        assert plan.time_range and plan.dimension and plan.order and plan.limit
        return ExecutionPlan(
            analysis_type="ranking", semantic_metric="sales_amount", result_shape="ranking",
            steps=[QueryStep(metric_id=get_policy_bundle().metric_catalog.metrics["sales_amount"].metric_id, params={
                **plan.time_range.model_dump(exclude_none=True), "order": plan.order, "limit": plan.limit,
            })],
        )
    if plan.analysis_type == "time_series":
        assert plan.time_range and plan.time_granularity == "month"
        params = plan.time_range.model_dump(exclude_none=True)
        return ExecutionPlan(
            analysis_type="time_series", semantic_metric="gross_profit_trend", result_shape="time_series",
            steps=[QueryStep(
                metric_id=get_policy_bundle().metric_catalog.metrics["gross_profit_trend"].metric_id,
                params={**params, "granularity": "month"},
            )],
        )
    if plan.analysis_type == "exception_list":
        assert plan.time_range and plan.entity and plan.risk_condition and plan.order and plan.limit
        return ExecutionPlan(
            analysis_type="exception_list", semantic_metric="delivery_risk_orders", result_shape="exception_list",
            steps=[QueryStep(
                metric_id=get_policy_bundle().metric_catalog.metrics["delivery_risk_orders"].metric_id,
                params={"limit": plan.limit},
            )],
        )
    if plan.analysis_type == "composition":
        assert plan.time_range and plan.dimension == "cost_type"
        return ExecutionPlan(
            analysis_type="composition", semantic_metric="cost_breakdown", result_shape="composition",
            steps=[QueryStep(
                metric_id=get_policy_bundle().metric_catalog.metrics["cost_breakdown"].metric_id,
                params=plan.time_range.model_dump(exclude_none=True),
            )],
        )
    if plan.analysis_type == "data_table":
        assert plan.time_range and plan.entity == "order" and plan.columns and plan.order and plan.limit
        return ExecutionPlan(
            analysis_type="data_table", semantic_metric="profit_order_details", result_shape="data_table",
            steps=[QueryStep(
                metric_id=get_policy_bundle().metric_catalog.metrics["profit_order_details"].metric_id,
                params={**plan.time_range.model_dump(exclude_none=True), "limit": plan.limit},
            )],
        )
    if plan.analysis_type == "scenario":
        assert plan.base_facts and plan.assumptions is not None and plan.calculation_method and plan.comparison_target
        lines = plan.base_facts.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError("invalid_semantic_plan:base_facts")
        return ExecutionPlan(
            analysis_type="scenario", semantic_metric="order_intake_scenario", result_shape="scenario",
            steps=[QueryStep(metric_id="analytics.order_intake", params={
                "lines": lines, **plan.assumptions,
            })],
        )
    if plan.analysis_type == "attribution_analysis":
        assert plan.time_range and plan.dimension == "order"
        return ExecutionPlan(
            analysis_type="attribution_analysis", semantic_metric="gross_profit_by_order", result_shape="attribution_analysis",
            steps=[QueryStep(metric_id="finance.profit_report", params=plan.time_range.model_dump(exclude_none=True))],
        )
    raise ValueError("unsupported_execution_plan:" + plan.analysis_type)


def match_execution_plan(plan: SemanticPlan, execution: ExecutionPlan) -> bool:
    """Semantic Match Gate before any ERP query is executed."""
    if plan.analysis_type != execution.analysis_type or execution.result_shape != REGISTRY[plan.analysis_type].result_shape:
        return False
    if plan.analysis_type == "metric_snapshot":
        if len(execution.steps) != 1 or not plan.time_range:
            return False
        expected_metric = get_policy_bundle().metric_catalog.metrics[plan.metric].metric_id
        return (
            execution.semantic_metric == plan.metric
            and execution.steps[0].metric_id == expected_metric
            and execution.steps[0].params == plan.time_range.model_dump(exclude_none=True)
        )
    if plan.analysis_type == "period_comparison":
        if len(execution.steps) != 2 or not plan.time_range or not plan.baseline:
            return False
        return (
            execution.semantic_metric == plan.metric
            and execution.steps[0].params == plan.time_range.model_dump(exclude_none=True)
            and execution.steps[1].params == plan.baseline.model_dump(exclude_none=True)
        )
    if plan.analysis_type == "ranking":
        if len(execution.steps) != 1 or not plan.time_range:
            return False
        expected = {**plan.time_range.model_dump(exclude_none=True), "order": plan.order, "limit": plan.limit}
        return (
            plan.metric == "sales_amount" and plan.dimension == "customer"
            and execution.semantic_metric == "sales_amount"
            and execution.steps[0].metric_id == "finance.customer_sales_ranking"
            and execution.steps[0].params == expected
        )
    if plan.analysis_type == "time_series":
        if len(execution.steps) != 1 or not plan.time_range:
            return False
        return (
            plan.metric == "gross_profit_trend"
            and plan.time_granularity == "month"
            and execution.semantic_metric == "gross_profit_trend"
            and execution.steps[0].metric_id == "finance.gross_profit_time_series"
            and execution.steps[0].params == {
                **plan.time_range.model_dump(exclude_none=True), "granularity": "month",
            }
        )
    if plan.analysis_type == "exception_list":
        return bool(
            len(execution.steps) == 1
            and plan.entity == "order"
            and plan.risk_condition == "delivery_risk"
            and plan.order == "asc"
            and execution.semantic_metric == "delivery_risk_orders"
            and execution.steps[0].metric_id == "analytics.delivery_risk"
            and execution.steps[0].params == {"limit": plan.limit}
        )
    if plan.analysis_type == "composition":
        return bool(
            len(execution.steps) == 1 and plan.metric == "cost_breakdown"
            and plan.dimension == "cost_type" and plan.time_range
            and execution.semantic_metric == "cost_breakdown"
            and execution.steps[0].metric_id == "finance.profit_report"
            and execution.steps[0].params == plan.time_range.model_dump(exclude_none=True)
        )
    if plan.analysis_type == "data_table":
        return bool(
            len(execution.steps) == 1 and plan.metric == "profit_order_details"
            and plan.entity == "order" and plan.columns and plan.time_range and plan.order == "desc"
            and execution.semantic_metric == "profit_order_details"
            and execution.steps[0].metric_id == "finance.profit_report"
            and execution.steps[0].params == {**plan.time_range.model_dump(exclude_none=True), "limit": plan.limit}
        )
    if plan.analysis_type == "scenario":
        return bool(
            len(execution.steps) == 1 and plan.base_facts and isinstance(plan.base_facts.get("lines"), list)
            and plan.assumptions is not None and plan.calculation_method and plan.comparison_target
            and execution.semantic_metric == "order_intake_scenario"
            and execution.steps[0].metric_id == "analytics.order_intake"
            and execution.steps[0].params == {"lines": plan.base_facts["lines"], **plan.assumptions}
        )
    if plan.analysis_type == "attribution_analysis":
        return bool(
            len(execution.steps) == 1 and plan.metric == "gross_profit_by_order" and plan.dimension == "order"
            and plan.time_range and execution.semantic_metric == "gross_profit_by_order"
            and execution.steps[0].metric_id == "finance.profit_report"
            and execution.steps[0].params == plan.time_range.model_dump(exclude_none=True)
        )
    return False


_PROFIT_RE = re.compile(r"利润|毛利|收入|成本")
_NUMBER_RE = re.compile(r"各多少|多少|合计|金额|数值|几元|几块")

# metric_snapshot 切片（Direct Metric）：单值销售额快照。
# 刻意只认「销售额/销售金额/销售总额」+ 数值或期间意图，且排除排行/占比/
# 趋势/跨期比较/最高级等其它分析原子（它们有各自的匹配分支或应留在 LLM 路径）。
_SALES_SNAPSHOT_RE = re.compile(r"销售额|销售金额|销售总额")
_SALES_SNAPSHOT_EXCLUDE_RE = re.compile(
    r"排行|Top|前\s*[一二两三四五六七八九十\d]+名?|占比|集中度|趋势|走势|归因|明细|列表|出表"
    r"|同比|环比|相比|对比|跟.*?比|与.*?比|比去年|比上月|同期"
    r"|最高|最大|最多|最好|最强|最热|居首|第一|之最|之冠|榜首|领先"
    r"|最低|最少|最小|最差|最弱|垫底|末位|之末|末尾"
)
_SALES_PERIOD_RE = re.compile(r"本月|这个月|当月|今年|本年|上年|去年|上个月|上月")

# Ranking intents beyond "销售额...排行/Top/最高": the 12-case query set
# (customer-sales-ranking-slice.md) also asks 占比/集中度/表格/前N名.
#
# 最高级（superlative）语义统一识别：正向（最大/最高/最多…）→ limit=1 + desc；
# 反向（最低/最少/最小…）→ limit=1 + asc。任何「哪个客户销售额最X」都必须
# 命中同一组词，禁止逐个词打补丁。
_RANKING_SHARE_RE = re.compile(r"(?:集中度|占比|占).*?(?:客户|销售)|客户.*?(?:集中度|占比)")
_RANKING_TABLE_RE = re.compile(r"客户销售额.*?(?:表格|列表|明细|出表)|(?:表格|列表).*?客户销售额")
_RANKING_TOP_RE = re.compile(r"(?:前\s*|Top\s*)[一二两三四五六七八九十\d]+名?.*?客户", re.I)
# 「客户销售额前3名」：前N名在客户之后（Case 2 原句），与前置式并存。
_RANKING_TOP_SUFFIX_RE = re.compile(r"客户.*?(?:前\s*|Top\s*)[一二两三四五六七八九十\d]+名?", re.I)
# 最高级词表（superlative）：正向 → 最大者；反向 → 最小者。
_SUPERLATIVE_HIGH_RE = re.compile(r"最高|最大|最多|最好|最强|最热|居首|第一|之最|之冠|第一|榜首|领先")
_SUPERLATIVE_LOW_RE = re.compile(r"最低|最少|最小|最差|最弱|垫底|末位|之末|末尾")
_SUPERLATIVE_RE = re.compile(
    r"最高|最大|最多|最好|最强|最热|居首|第一|之最|之冠|榜首|领先"
    r"|最低|最少|最小|最差|最弱|垫底|末位|之末|末尾"
)
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if value in _CN_DIGITS:
        return _CN_DIGITS[value]
    if "十" in value:  # 十 / 十二 / 二十 / 二十五
        head, _, tail = value.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return None


def _ranking_limit(text: str) -> int | None:
    limit_match = re.search(r"(?:Top\s*|前\s*)(\d+)|最高的\s*(\d+)", text, re.I)
    if limit_match:
        return int(next(value for value in limit_match.groups() if value))
    cn_match = re.search(r"(?:前\s*|Top\s*)([一二两三四五六七八九十\d]+)名?", text)
    if cn_match:
        return _cn_to_int(cn_match.group(1))
    # 「哪个客户销售额最高/最低/最多…」：任意最高级无显式 N → limit=1
    # （Case 3 语义：limit=1 + rank predicate，不是默认 10）。
    if _SUPERLATIVE_RE.search(text):
        return 1
    return None


def _match_ranking(text: str, year: int) -> SemanticPlan | None:
    ranking_hint = (
        re.search(r"(?:销售额|销售).*?(?:排行|Top)", text, re.I)
        or re.search(r"(?:排行|Top).*?(?:客户|销售额|销售)", text, re.I)
        or _RANKING_SHARE_RE.search(text)
        or _RANKING_TABLE_RE.search(text)
        or _RANKING_TOP_RE.search(text)
        or _RANKING_TOP_SUFFIX_RE.search(text)
        # 最高级语义：销售额/销售 + 最X，或最X + 客户/销售额（含「哪个客户…最高」）
        or (
            _SUPERLATIVE_RE.search(text)
            and re.search(r"客户", text)
            and re.search(r"销售额|销售", text)
        )
    )
    if not ranking_hint:
        return None
    limit = _ranking_limit(text)
    # 集中度/占比问题无显式 N 时按规则语义取前 2 名（customer_concentration.high
    # 的输入是 top2_share）；否则默认 10。
    if limit is None:
        limit = 2 if _RANKING_SHARE_RE.search(text) else 10
    # 反向最高级（最低/最少/最小…）→ 升序；其余 → 降序。
    order = "asc" if (_SUPERLATIVE_LOW_RE.search(text) and limit == 1) else "desc"
    return SemanticPlan(
        analysis_type="ranking", metric="sales_amount", dimension="customer",
        time_range=TimeRange(year=year), order=order, limit=limit,
    )


def _match_sales_snapshot(text: str, now: date) -> SemanticPlan | None:
    """metric_snapshot 切片：销售额/销售金额/销售总额 + 数值或期间意图。

    只认单一期间快照；期间取显式年月 > 「上月/去年」相对期 > 「本月/今年」
    当前期 > 默认当前年月（低风险默认 + 披露 assumption，契约 §4.4）。
    """
    if not _SALES_SNAPSHOT_RE.search(text):
        return None
    if _SALES_SNAPSHOT_EXCLUDE_RE.search(text):
        return None
    has_number_intent = bool(_NUMBER_RE.search(text))
    has_period = bool(_SALES_PERIOD_RE.search(text))
    wants_table = bool(re.search(r"表格", text))
    if not (has_number_intent or has_period or wants_table):
        return None

    year = now.year
    month: int | None = None
    explicit = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", text)
    if explicit:
        year, month = int(explicit.group(1)), int(explicit.group(2))
    elif re.search(r"上月|上个月", text):
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1
    elif re.search(r"去年|上年", text):
        year = now.year - 1
    elif re.search(r"本月|这个月|当月", text):
        year, month = now.year, now.month
    elif re.search(r"今年|本年", text):
        year = now.year
    # 无显式期间（如「销售额多少」）：默认当前年月，由 Renderer 披露。
    return SemanticPlan(
        analysis_type="metric_snapshot", metric="sales_snapshot",
        time_range=TimeRange(year=year, month=month),
    )


def plan_finance_question(question: str, *, today: date | None = None) -> SemanticPlan | None:
    """Deterministic first planner; later an LLM may fill the same schema."""
    text = question or ""
    now = today or date.today()
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else now.year
    ranking = _match_ranking(text, year)
    if ranking is not None:
        return ranking
    snapshot = _match_sales_snapshot(text, now)
    if snapshot is not None:
        return snapshot
    if re.search(r"交期风险.*(?:订单|单|列表|明细)|(?:风险订单|风险单|延期订单|逾期订单).*(?:列表|明细|哪些|查看)|(?:列出|查看).*(?:交期风险|风险订单|延期订单|逾期订单)", text):
        limit_match = re.search(r"(?:前\s*|Top\s*)(\d+)", text, re.I)
        limit = int(limit_match.group(1)) if limit_match else 10
        return SemanticPlan(
            analysis_type="exception_list", metric="delivery_risk_orders", entity="order",
            risk_condition="delivery_risk", time_range=TimeRange(year=year, month=now.month),
            order="asc", limit=limit,
        )
    if re.search(r"(?:成本|费用).*(?:构成|结构|占比)|(?:构成|结构|占比).*(?:成本|费用)", text):
        return SemanticPlan(
            analysis_type="composition", metric="cost_breakdown", dimension="cost_type",
            time_range=TimeRange(year=year, month=now.month),
        )
    if _PROFIT_RE.search(text) and re.search(r"明细|列表|出表|表格", text):
        limit_match = re.search(r"(?:前\s*|Top\s*)(\d+)", text, re.I)
        limit = int(limit_match.group(1)) if limit_match else 20
        return SemanticPlan(
            analysis_type="data_table", metric="profit_order_details", entity="order",
            columns=["order_no", "customer_name", "revenue", "total_cost", "gross_profit"],
            time_range=TimeRange(year=year, month=now.month), order="desc", limit=limit,
        )
    if re.search(r"插单|加班|外协|仿真|模拟", text):
        # Intent is recognized, but no estimate is ever invented: the user
        # must provide the candidate order facts and the assumption to test.
        return SemanticPlan(analysis_type="scenario")
    if _PROFIT_RE.search(text) and re.search(r"归因|主要由.*(?:造成|贡献)|谁.*(?:造成|贡献)", text):
        return SemanticPlan(
            analysis_type="attribution_analysis", metric="gross_profit_by_order", dimension="order",
            time_range=TimeRange(year=year, month=now.month),
        )
    if _PROFIT_RE.search(text) and re.search(r"(?:近\s*\d*\s*(?:个?月|月度)|(?:趋势|走势|曲线))", text):
        months_match = re.search(r"近\s*(\d+)\s*个?月", text)
        months = int(months_match.group(1)) if months_match else 12
        return SemanticPlan(
            analysis_type="time_series", metric="gross_profit_trend", time_range=TimeRange(
                year=year, month=now.month, months=months,
            ), time_granularity="month",
        )
    if not _PROFIT_RE.search(text):
        return None
    current = TimeRange(year=now.year, month=now.month)
    if re.search(r"环比|上月", text):
        baseline = TimeRange(year=now.year - (1 if now.month == 1 else 0), month=12 if now.month == 1 else now.month - 1)
        metric = "revenue" if "收入" in text else "total_cost" if "成本" in text else "gross_profit"
        return SemanticPlan(analysis_type="period_comparison", metric=metric, time_range=current, baseline=baseline)
    if re.search(r"同比|去年同期|去年", text):
        metric = "revenue" if "收入" in text else "total_cost" if "成本" in text else "gross_profit"
        return SemanticPlan(analysis_type="period_comparison", metric=metric, time_range=current, baseline=TimeRange(year=now.year - 1, month=now.month))
    if _NUMBER_RE.search(text):
        return SemanticPlan(analysis_type="metric_snapshot", metric="profit_overview", time_range=current)
    return None


def plan_question(question: str, *, today: date | None = None) -> PlannerOutput:
    """Current deterministic adapter for the constrained Planner contract.

    Replacing this adapter with an LLM is safe only through
    :func:`parse_planner_json`; the execution path remains identical.
    """
    text = question or ""
    # A request for a per-order receipt is intentionally not mapped to a
    # broader finance metric. It must ask for the governing order-number slot.
    if re.search(r"(?:按单号|按订单).*(?:回款|收款)|(?:回款|收款).*(?:按单号|按订单)", text) and not re.search(r"(?<!\d)\d{5,}(?!\d)", text):
        return PlannerOutput(semantic_plan_id=f"sp_{uuid.uuid4().hex[:16]}", missing_slots=["order_no"])
    plan = plan_finance_question(text, today=today)
    if not plan:
        return PlannerOutput(semantic_plan_id=f"sp_{uuid.uuid4().hex[:16]}")
    # Run even deterministic proposals through the exact constrained schema.
    return parse_planner_json(plan.model_dump())
