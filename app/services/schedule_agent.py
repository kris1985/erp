"""排产 Agent（L3）：DeepAgents + DeepSeek；只能调规则引擎工具，禁止臆造数据。"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator, Literal, Optional

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.agent_policy import get_policy_bundle
from app.db import SessionLocal
from app.services import agent_orchestration, agent_trace_service, analysis_plans, analysis_result_store, lifecycle_agents, schedule_engine, schedule_service, schedule_settings, workshop_metrics


WORKSHOP_AGENT_PROMPT_VERSION = "1.0.0"
EVIDENCE_GUARDRAIL_VERSION = "1.0.0"

SYSTEM_PROMPT = """你是鞋厂「车间军师」（排产参谋 + 经营问数 + 诊断分析）。你只出主意、不下指令落库；只能通过工具获取事实与方案，禁止编造订单号、日期、数量、金额、产能或风险。

硬性规则：
1. 任何涉及订单/交期/负荷/插单/方案/产量/缺料/库存/应收/回款/利润/质量/人效的结论，必须先调用对应工具；工具结果是唯一真相源。
2. 不要猜测缺失字段；缺参数就追问用户。
3. 排产方案对用户讲策略名与风险（可带方案编号）；问数时工具调用用 metric_id，对用户只说 list_metrics 里的中文 name（如「今日工序产量」「执行单进度」），禁止在答复里甩英文 id（如 production.today_output、analytics.quality_alerts）。
4. 诊断优先 analytics.*。接单/生产分析必须 query_metric(analytics.order_intake)，params 带 lines；用户改交期/数量/急单/日产能时用同一 lines 加 qty/delivery_date/is_rush/strategy/default_daily_capacity 重查，禁止口头改数。答复极简：裁决一句话 → **解释为何**（引用毛利对比、码段偏离、争料、实耗偏差、缺料与预计齐套日、交期冲击被影响单号、回款余额/平均回款天数）→ 最多 3 条可执行建议。风险只用中文标签（risk_label / intake_risk_label）：余量充足、交期偏紧、预计逾期、缺料卡住、产能不足；每条建议以标签开头。默认不重复输出利润明细表与物料明细表；但用户要「数据列表 / 明细 / 出表 / 表格」时，必须用 Markdown 表格呈现。empty_bom=true 时明确「未建 BOM，不能确认可开裁」。缺料时说「预计到料日/预计齐套日」，禁止写 ETA。capacity_configured=false 时须说明「未校验产能」，并提示可在假设中填日产能后重算；若 capacity_from_hypothesis=true 须说明「按假设日产能校验、未写入排产设置」。确认生产/取消须界面 HITL。
5. 其它诊断：今日行动、齐套可排、本周简报、交期风险、产能负荷、供应链、经营健康、质量热点、质量预警、人效、本月简报（工具侧对应 today_actions / kit_ready / … / quality_alerts 等）。「可排」用 generate_schedule_proposals（提醒人工确认）；产能校准 suggested_memories 用 remember_user_fact。讲「今日行动 / 今日 3 件事」时：只陈述 data.top3（最多 3 条），每条必须引用该条 evidence.facts 与 order_nos；禁止编造未出现在 evidence 中的单号、日期、数量；不要把完整 actions 清单当主答复。讲质量抽检时优先查「质量预警」（analytics.quality_alerts，款×工序突增），可辅以「质量热点」；讲损耗超标时先看今日行动是否含损耗超标项，有则只引用其 evidence，没有则如实说没有——禁止编造领料实耗。方案对比须点明各方案的延期风险与负荷含义，并提醒人工确认后落库。
6. 你不能确认落库、不能改派工/工资/交期/采购/核销；只能建议用户在系统里操作；排产路径仍是「采用方案→进草稿→人工确认」。
7. 若工具报错、无权限或无数据，如实说明（用中文说「无工艺路线」等，不要甩 sim_error=no_route），不要补造。特别是用户问供应链/缺料/库存，若当前可用指标里没有对应项或工具返回无权限，直接说明「当前账号无权限查询供应链缺料数据，不能给出风险结论」；不要改查今日行动、齐套、交期等不等价指标来代答，也不要把无权限说成数据为空或工具故障。
8. 多轮沿用已确认约束；长期偏好用 remember_user_fact。
9. 默认输出「扫读短答」，除非用户明确要求周报、数据列表、明细、对比、出表、表格或展开说明：
   - 先给不超过 1 句的结论（直接回答，不复述问题，不寒暄）。
   - 接着最多 3 个短条目；每条只写「动作/判断 + 最关键的一项证据」，单条尽量不超过一行。
   - 总计默认不超过 6 行、约 220 个中文字符；不重复工具过程、指标定义、免责声明或同一数字。
   - 需要更多背景时，结尾只留一句「可继续展开 ××」，不要先把完整解释、表格和备选方案全贴出。
   - 用户要求「数据列表 / 明细 / 出表 / 表格」时，先给一句结论，再用标准 Markdown 表格（表头和内容都用中文）；只保留回答问题所需列，通常不超过 6 列、20 行。无数据、无权限或工具错误时不造空表，直接说明原因。
   - 只有用户明确说「详细 / 展开 / 周报 / 对比 / 出表」时，才放宽篇幅；即使展开，也先给结论摘要。
   面向车间师傅/厂长：不出现英文字段名、metric_id、snake_case、JSON key。
10. 问数先 list_metrics 再 query_metric；不要编造 metric_id。建议下一步时说中文动作（如「可再查今日工序产量，或按执行单号查进度」），不要写英文指标名。
11. 工具若返回 chart，前端会画图；你只解释结论，不要编造图表或 ```chart 代码块。
12. 严禁向用户输出思考过程、工具计划、重试过程、内部字段、函数名或“让我/我先/我需要核对”等工作草稿。工具调用由界面的「决策过程」展示；你的最终答复只能是经核验后的业务结论、依据和建议。
13. 对于系统已自动补齐的只读诊断数据，必须在同一轮直接利用这些数据作答；不得把「查看明细 / 展开 KPI / 按客户核对」写成需要用户点击的“继续分析”。只有确实缺少用户提供的必要条件（例如未给出的单号、日期范围），或下一步涉及写入、审批、线下协同，才提出追问或待办。
"""


# Prompt rules reduce hallucinations but are not a production guardrail.  This
# deliberately small, deterministic check sits on the egress path: a response
# that makes a measurable claim not present in a tool result is replaced by a
# safe retry message.  It is intentionally conservative; it does not attempt
# to judge the quality of a recommendation (that is the offline LLM judge's
# job).
_FACT_QUESTION_RE = re.compile(
    r"订单|交期|负荷|产能|产量|缺料|库存|应收|回款|利润|金额|质量|人效|齐套|风险|排产|进度"
)
_DATE_RE = re.compile(r"\d{4}\s*[年/-]\s*\d{1,2}(?:\s*[月/-]\s*\d{1,2})?(?:\s*日)?")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{4,}(?!\d)")
_MEASURE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|双|件|元|万元|天|小时|箱|次)")
_SAFE_UNCERTAINTY_RE = re.compile(r"无权限|无数据|暂不能确认|无法确认|请重新查询|查询失败")
_CAPABILITY_BOUNDARY_RE = re.compile(
    r"未提供.*(?:指标|接口)|当前可用.*(?:指标|问数)|仅有.*(?:指标|查询)|"
    r"不支持按.*查询|无法按.*查询|按.*维度返回|需提供具体单号"
)
_GUARDRAIL_FALLBACK = "暂不能确认这项事实结论：查询证据不完整，请重新查询后再判断。"
_EVIDENCE_FIELD_LABELS = {
    "order_no": "订单", "process_name": "工序", "delivery_date": "交期",
    "overall_percent": "进度", "material_name": "物料", "item_name": "物料",
    "date": "日期", "load_qty": "负荷", "capacity": "产能",
    "shipment_amount": "出货金额", "payment_amount": "回款金额",
    "customer_ar_balance": "应收余额", "qty": "数量", "shortage_qty": "缺口",
    "revenue": "收入", "material_cost": "材料成本", "labor_cost": "人工成本",
    "other_cost": "其它成本", "total_cost": "成本合计", "gross_profit": "毛利",
    "customer_name": "客户", "sales_amount": "销售额",
}
_CHART_REQUEST_RE = re.compile(r"图表|看图|趋势|曲线|柱状图|负荷图|甘特")
_FINANCE_DIAGNOSIS_RE = re.compile(r"回款|应收|现金流|催收|经营\s*KPI|经营健康|利润|毛利|收入|成本|销售额|销售|客户")
_PROFIT_OVERVIEW_RE = re.compile(r"利润|毛利|收入|成本")
_WEEKLY_BRIEF_RE = re.compile(r"(?:本周|这周).*(?:简报|周报)|(?:简报|周报).*(?:交期|齐套|负荷|缺料|质量)")
_NUMBER_ONLY_RE = re.compile(r"各多少|多少|合计|金额|数值|几元|几块")
_PERIOD_COMPARE_RE = re.compile(r"同比|环比|上月|去年同期|去年")
_ORDER_NO_RE = re.compile(r"(?<!\d)\d{5,}(?!\d)")
_EXCEPTION_LIST_RE = re.compile(r"交期风险.*(?:订单|单|列表|明细)|(?:风险订单|风险单|延期订单|逾期订单).*(?:列表|明细|哪些|查看)|(?:列出|查看).*(?:交期风险|风险订单|延期订单|逾期订单)")
_MISSING_SLOT_LABELS = {"order_no": "订单号", "time_range": "查询时间范围", "metric": "指标"}
_MISSING_SLOT_LABELS.update({
    "base_facts": "待仿真的订单/款号与数量", "assumptions": "假设条件（如日产能、加班或外协）",
    "calculation_method": "计算方式", "comparison_target": "对比目标",
})


def _missing_slots_reply(slots: list[str]) -> str:
    labels = "、".join(_MISSING_SLOT_LABELS.get(slot, slot) for slot in slots)
    return f"请补充{labels}后再查询。"


def _auto_diagnostic_metric_ids(
    question: str,
    *,
    permission_codes: list[str] | None = None,
    profiles: list[lifecycle_agents.LifecycleAgentProfile] | None = None,
) -> list[str]:
    """Select a small, read-only diagnostic bundle before the model starts.

    This is intentionally a capability, not a collection of UI-specific
    follow-ups: a cash-collection question always needs the same three views
    (cash received, open receivables, and business KPI).  We never infer a
    missing order number or trigger a write action here.
    """
    text = question or ""
    exception_plan = analysis_plans.plan_question(text).plan
    if exception_plan and exception_plan.analysis_type == "exception_list":
        visible = {metric["id"] for metric in workshop_metrics.list_metrics(permission_codes=permission_codes)}
        specialist_allowed = lifecycle_agents.allowed_metric_ids(profiles or [])
        if specialist_allowed is not None:
            visible &= set(specialist_allowed)
        return ["analytics.delivery_risk"] if "analytics.delivery_risk" in visible else []
    if not _FINANCE_DIAGNOSIS_RE.search(text):
        return []
    # An order-level payment request needs an order number.  Do not disguise
    # that missing input as an automatic drill-down.
    if re.search(r"按单号|按订单|某.*订单", text) and not _ORDER_NO_RE.search(text):
        return []

    # Do not let adjacent finance data hijack the answer.  A user asking for
    # income / cost / gross profit needs the profit report first; cash flow is
    # deliberately not auto-added to that narrow question.
    finance_plan = analysis_plans.plan_finance_question(text)
    requested = (
        ["finance.customer_sales_ranking"]
        if finance_plan and finance_plan.analysis_type == "ranking"
        else ["finance.gross_profit_time_series"]
        if finance_plan and finance_plan.analysis_type == "time_series"
        else ["finance.profit_report"]
        if finance_plan and finance_plan.analysis_type == "composition"
        else ["finance.profit_report"]
        if finance_plan and finance_plan.analysis_type == "data_table"
        else ["finance.profit_report"]
        if finance_plan and finance_plan.analysis_type == "attribution_analysis"
        else
        ["finance.profit_report", "finance.business_kpi"]
        if _PROFIT_OVERVIEW_RE.search(text)
        else [
            "finance.payments_this_month",
            "finance.receivables_open",
            "finance.business_kpi",
        ]
    )
    visible = {
        metric["id"]
        for metric in workshop_metrics.list_metrics(permission_codes=permission_codes)
    }
    specialist_allowed = lifecycle_agents.allowed_metric_ids(profiles or [])
    if specialist_allowed is not None:
        visible &= set(specialist_allowed)
    return [metric_id for metric_id in requested if metric_id in visible]


def _comparison_periods(question: str, today: date) -> list[dict[str, int]]:
    """Return only the comparison periods explicitly asked for."""
    text = question or ""
    periods: list[dict[str, int]] = []
    if re.search(r"环比|上月", text):
        periods.append({"year": today.year - (1 if today.month == 1 else 0), "month": 12 if today.month == 1 else today.month - 1})
    if re.search(r"同比|去年同期|去年", text):
        periods.append({"year": today.year - 1, "month": today.month})
    return periods


def _run_auto_diagnostic_bundle(
    tenant_id: int,
    question: str,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
    profiles: list[lifecycle_agents.LifecycleAgentProfile] | None = None,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str,
    analysis_plans.PlannerOutput, analysis_plans.ExecutionPlan | None,
]:
    """Execute safe preflight reads and return trace/evidence/chart/context.

    The compact context is injected as an internal system message.  It gives
    the agent complete data on the first turn while the UI receives the same
    evidence events as ordinary tool calls.
    """
    planner = _plan_semantic_question(question)
    metric_ids = _auto_diagnostic_metric_ids(
        question, permission_codes=permission_codes, profiles=profiles
    )
    if not metric_ids:
        return [{
            "name": "semantic_plan",
            "content": json.dumps(planner.model_dump(), ensure_ascii=False),
        }], [], [], "", planner, None

    today = date.today()
    period = {"year": today.year, "month": today.month}
    semantic_plan = planner.plan
    execution_plan = None
    if semantic_plan:
        try:
            candidate = analysis_plans.resolve_execution_plan(semantic_plan)
            if analysis_plans.match_execution_plan(semantic_plan, candidate):
                execution_plan = candidate
        except ValueError:
            execution_plan = None
    query_jobs: list[tuple[str, dict[str, Any]]] = []
    if execution_plan and all(step.metric_id in metric_ids for step in execution_plan.steps):
        query_jobs = [(step.metric_id, dict(step.params)) for step in execution_plan.steps]
    else:
        for metric_id in metric_ids:
            params = period if metric_id in {
                "finance.payments_this_month", "finance.business_kpi", "finance.profit_report"
            } else {}
            param_sets = [params]
            if metric_id == "finance.profit_report" and _PERIOD_COMPARE_RE.search(question or ""):
                param_sets = [period, *_comparison_periods(question, today)]
            query_jobs.extend((metric_id, query_params) for query_params in param_sets)
    traces: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for metric_id, query_params in query_jobs:
            result = workshop_metrics.query_metric(
                db, tenant_id, metric_id, params=query_params, permission_codes=permission_codes
            )
            if not result.get("error"):
                result_id = analysis_result_store.put_result(
                    tenant_id, metric_id, result, query_params, session_id=conversation_id,
                )
                result["_result"] = {"result_id": result_id, "metric_id": metric_id}
            result["_evidence"] = {
                "metric_id": metric_id,
                "filters": query_params,
                "queried_at": _now_iso(),
                "automatic": True,
            }
            content = json.dumps(result, ensure_ascii=False, default=str)
            trace = {"name": "query_metric", "content": content[:800]}
            traces.append(trace)
            evidence.append({"name": "query_metric", "content": content})
            charts.extend(workshop_metrics.extract_charts(content))
            context_rows.append(result)

    diagnosis_name = "利润结构与经营 KPI" if _PROFIT_OVERVIEW_RE.search(question or "") else "回款、未结应收与经营 KPI"
    answer_focus = (
        "用户问的是利润概况，首句必须直接回答收入、成本、毛利；未被询问的回款/现金流不得替代主结论。"
        if _PROFIT_OVERVIEW_RE.search(question or "")
        else "用户问的是回款/应收或现金流，首句必须直接回答该问题。"
    )
    context = (
        f"【系统已自动完成只读诊断】以下是本轮已核验的{diagnosis_name}数据。{answer_focus}"
        "请直接基于这些数据回答原问题；不要重复查询这些指标，也不要把可由这些数据回答的内容作为“继续分析”。"
        "若仍缺少用户必须提供的单号、日期范围，或下一步属于写入/审批/线下协同，才明确说明。\n"
        + (f"已通过语义计划校验：{semantic_plan.model_dump_json()}\n" if semantic_plan and execution_plan else "")
        + json.dumps(context_rows, ensure_ascii=False, default=str)
    )
    traces.insert(0, {
        "name": "semantic_plan",
        "content": json.dumps({
            "semantic_plan_id": planner.semantic_plan_id,
            "missing_slots": planner.missing_slots,
            "plan": semantic_plan.model_dump() if semantic_plan else None,
        }, ensure_ascii=False),
    })
    return traces, evidence, charts, context, planner, execution_plan


_CHILD_ROLE_METRICS = {
    "warehouse_stock": "analytics.kit_ready",
    "procurement_supply": "analytics.supply_chain",
    "schedule_capacity": "analytics.capacity_load",
    "production_quality": "analytics.quality_alerts",
    "delivery_finance": "analytics.finance_health",
}
_CHILD_INTERNAL_KEYS = {"reasoning", "thought", "chain_of_thought", "raw_data", "rows", "result_id", "calculation_id"}


def _redact_child_payload(value: Any) -> Any:
    """Drop internal references before a metric response becomes a child summary."""
    if isinstance(value, dict):
        return {
            key: _redact_child_payload(item)
            for key, item in value.items() if key not in _CHILD_INTERNAL_KEYS
        }
    if isinstance(value, list):
        # Fact extraction is bounded below; retaining at most eight records
        # avoids passing a disguised raw result through a specialist result.
        return [_redact_child_payload(item) for item in value[:8]]
    return value


def _execute_child_plans(
    tenant_id: int, child_plans: list[agent_orchestration.ChildPlan], *,
    permission_codes: list[str] | None = None,
) -> list[agent_orchestration.ChildResult]:
    """Run each bounded specialist as a read-only metric summary.

    The database response is reduced inside this function.  The controller and
    model receive only the validated ``ChildResult`` (metric/status/facts),
    never rows, raw payloads, result IDs, or model reasoning.
    """
    if not child_plans:
        return []
    visible_metrics = {item["id"] for item in workshop_metrics.list_metrics(permission_codes=permission_codes)}

    def metric_for(child_plan: agent_orchestration.ChildPlan) -> tuple[str | None, dict[str, Any]]:
        parent = child_plan.parent_semantic_plan
        if child_plan.lifecycle_role == "order_commitment":
            base_facts = parent.get("base_facts") if isinstance(parent, dict) else None
            lines = base_facts.get("lines") if isinstance(base_facts, dict) else None
            if isinstance(lines, list) and lines:
                assumptions = parent.get("assumptions") if isinstance(parent, dict) else None
                return "analytics.order_intake", {"lines": lines, **(assumptions if isinstance(assumptions, dict) else {})}
            return "analytics.delivery_risk", {"limit": 5}
        return _CHILD_ROLE_METRICS.get(child_plan.lifecycle_role), {}

    def executor(child_plan: agent_orchestration.ChildPlan) -> dict[str, Any]:
        metric_id, params = metric_for(child_plan)
        base = {"child_plan_id": child_plan.child_plan_id, "lifecycle_role": child_plan.lifecycle_role}
        if not metric_id or metric_id not in child_plan.allowed_metric_ids:
            return {**base, "typed_result": {"status": "not_configured"}, "evidence_summary": []}
        if metric_id not in visible_metrics:
            return {**base, "typed_result": {"metric_id": metric_id, "status": "forbidden"}, "evidence_summary": ["当前角色无权限读取该诊断"]}
        with SessionLocal() as db:
            result = workshop_metrics.query_metric(
                db, tenant_id, metric_id, params=params, permission_codes=permission_codes
            )
        if result.get("error"):
            return {**base, "typed_result": {"metric_id": metric_id, "status": str(result["error"])}, "evidence_summary": [str(result.get("message") or "诊断查询失败")[:120]]}
        cards = build_evidence_ledger([{
            "name": "query_metric", "content": json.dumps(_redact_child_payload(result), ensure_ascii=False, default=str),
        }], permission_codes=permission_codes)
        facts = [str(fact)[:160] for card in cards for fact in (card.get("facts") or [])][:3]
        return {
            **base,
            "typed_result": {"metric_id": metric_id, "status": "ok", "fact_count": len(facts)},
            "evidence_summary": facts,
        }

    return agent_orchestration.execute_child_plans(child_plans, executor)


def _child_results_context(results: list[agent_orchestration.ChildResult]) -> str:
    if not results:
        return ""
    return "【固定角色子诊断摘要】\n" + json.dumps(
        [result.model_dump() for result in results], ensure_ascii=False
    ) + "\n只能依据这些摘要作答；不要要求或推断子角色的原始数据。"


def select_response_charts(question: str, charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return at most one chart, and only when the user explicitly asks for it."""
    if not _CHART_REQUEST_RE.search(question or ""):
        return []
    text = question or ""
    preferred: tuple[str, ...] = ()
    if re.search(r"产能|负荷|瓶颈", text):
        preferred = ("analytics.capacity_load", "schedule.daily_load")
    elif re.search(r"交期|进度|在制", text):
        preferred = ("analytics.delivery_risk", "production.order_progress")
    elif re.search(r"缺料|采购|物料", text):
        preferred = ("analytics.supply_chain", "materials.shortages")
    for metric_id in preferred:
        matched = next((chart for chart in charts if chart.get("metric_id") == metric_id), None)
        if matched:
            return [matched]
    return charts[:1]


def _evidence_facts(value: Any, *, limit: int = 8) -> list[str]:
    """Extract a small, business-readable fact list from a tool payload."""
    facts: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if len(facts) >= limit or depth > 5:
            return
        if isinstance(node, dict):
            for key, val in node.items():
                if key in {"_evidence", "chart", "charts", "error", "message"}:
                    continue
                if key in _EVIDENCE_FIELD_LABELS and isinstance(val, (str, int, float)) and val != "":
                    line = f"{_EVIDENCE_FIELD_LABELS[key]}：{val}"
                    if line not in facts:
                        facts.append(line)
                if isinstance(val, (dict, list)):
                    walk(val, depth + 1)
        elif isinstance(node, list):
            for item in node[:10]:
                walk(item, depth + 1)

    walk(value)
    return facts


def build_evidence_ledger(
    tool_evidence: list[Any], *, permission_codes: list[str] | None = None,
    include_internal_refs: bool = False,
) -> list[dict[str, Any]]:
    """Create client-safe, business-facing evidence cards from tool results.

    No raw JSON, model prompt, or hidden fields are returned. The evidence is
    inherently permission-scoped because it is derived only from tools already
    executed with the current user's permission set.
    """
    names = {item["id"]: item["name"] for item in workshop_metrics.list_metrics(permission_codes=permission_codes)}
    cards: list[dict[str, Any]] = []
    for index, item in enumerate(tool_evidence[-8:], start=1):
        name = str(item.get("name") or "查询") if isinstance(item, dict) else "查询"
        content = item.get("content") if isinstance(item, dict) else item
        try:
            payload = json.loads(str(content or ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        meta = payload.get("_evidence") if isinstance(payload.get("_evidence"), dict) else {}
        result_meta = payload.get("_result") if isinstance(payload.get("_result"), dict) else {}
        metric_id = str(meta.get("metric_id") or payload.get("metric_id") or "")
        error = payload.get("error")
        if error:
            cards.append({
                "id": f"E{index}", "source": names.get(metric_id) or "查询结果",
                "status": "无可用数据", "facts": [], "filters": meta.get("filters") or {},
                "queried_at": meta.get("queried_at"),
            })
            continue
        data = payload.get("data", payload)
        as_of = data.get("as_of") if isinstance(data, dict) else None
        card = {
            "id": f"E{index}",
            "source": names.get(metric_id) or ("排产规则引擎" if name != "query_metric" else "指标查询"),
            "status": "已核验",
            # A ranking needs both the dimension and value for every visible
            # row; the default compact fact limit would otherwise turn Top 10
            # into a misleading Top 4 in the typed presentation.
            "facts": _evidence_facts(
                data,
                limit=24 if metric_id == "finance.customer_sales_ranking" else 8,
            ),
            "filters": meta.get("filters") or {},
            "as_of": as_of,
            "queried_at": meta.get("queried_at"),
        }
        if include_internal_refs and result_meta.get("result_id"):
            card["result_id"] = result_meta["result_id"]
        cards.append(card)
    return cards


def _normalise_evidence(value: Any) -> str:
    """Convert tool output to a comparison-friendly evidence ledger."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return re.sub(r"\s+", "", str(value or ""))


def _evidence_status(tool_evidence: list[Any]) -> tuple[list[str], bool]:
    """Return tool names and whether a tool produced a usable fact payload."""
    names: list[str] = []
    has_usable_payload = False
    for item in tool_evidence:
        name = ""
        content = item
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            content = item.get("content")
        if name:
            names.append(name)
        try:
            decoded = json.loads(str(content or ""))
        except (TypeError, json.JSONDecodeError):
            has_usable_payload = has_usable_payload or bool(str(content or "").strip())
            continue
        if isinstance(decoded, dict) and decoded.get("error"):
            continue
        # A normal metric response can legitimately contain an empty list; it
        # is still evidence for an honest "none found" answer.
        has_usable_payload = True
    return names, has_usable_payload


def validate_evidence_guardrail(
    question: str, reply: str, tool_evidence: list[Any]
) -> dict[str, Any]:
    """Check that high-risk answers have tool evidence and cited values exist.

    The returned object is suitable for a trace/evaluation record and contains
    no raw evidence, so it can safely be returned to the API client.
    """
    reply = (reply or "").strip()
    raw_evidence = [
        item.get("content", "") if isinstance(item, dict) else item for item in tool_evidence
    ]
    evidence = _normalise_evidence("\n".join(str(item or "") for item in raw_evidence))
    tool_names, has_usable_payload = _evidence_status(tool_evidence)
    high_risk = bool(_FACT_QUESTION_RE.search(question or ""))
    if not high_risk or _SAFE_UNCERTAINTY_RE.search(reply):
        return {
            "passed": True,
            "reason": "not_applicable_safe_uncertainty_or_capability_boundary",
            "unmatched": [],
            "tool_names": tool_names,
            "has_usable_payload": has_usable_payload,
        }
    if _CAPABILITY_BOUNDARY_RE.search(reply) and evidence:
        return {
            "passed": True,
            "reason": "tool_supported_capability_boundary",
            "unmatched": [],
            "tool_names": tool_names,
            "has_usable_payload": has_usable_payload,
        }
    if not evidence:
        return {
            "passed": False,
            "reason": "missing_tool_evidence",
            "unmatched": [],
            "tool_names": tool_names,
            "has_usable_payload": False,
        }

    claims = set(_DATE_RE.findall(reply)) | set(_LONG_NUMBER_RE.findall(reply)) | set(_MEASURE_RE.findall(reply))
    def supported(claim: str) -> bool:
        normalized = _normalise_evidence(claim)
        if normalized in evidence:
            return True
        # Metric JSON commonly stores a percentage as a bare number (65),
        # while the user-facing reply correctly renders it as 65%.
        numeric = re.match(r"\d+(?:\.\d+)?", normalized)
        return bool(numeric and numeric.group(0) in evidence)

    unmatched = sorted(claim for claim in claims if not supported(claim))
    if unmatched:
        return {
            "passed": False,
            "reason": "unsupported_measurable_claim",
            "unmatched": unmatched,
            "tool_names": tool_names,
            "has_usable_payload": has_usable_payload,
        }
    return {
        "passed": True,
        "reason": "supported",
        "unmatched": [],
        "tool_names": tool_names,
        "has_usable_payload": has_usable_payload,
    }


def _remove_unsupported_lines(reply: str, claims: list[str]) -> str:
    """Drop only lines containing unsupported measurable claims, not the answer."""
    if not claims:
        return reply
    keep = [
        line for line in reply.splitlines()
        if not any(claim in line for claim in claims)
    ]
    return "\n".join(keep).strip()


def apply_evidence_guardrail(
    question: str, reply: str, tool_evidence: list[Any]
) -> tuple[str, dict[str, Any]]:
    verdict = validate_evidence_guardrail(question, reply, tool_evidence)
    if verdict["passed"]:
        return reply, verdict
    if verdict["reason"] == "unsupported_measurable_claim":
        trimmed = _remove_unsupported_lines(reply, verdict["unmatched"])
        if trimmed:
            verdict["action"] = "removed_unsupported_lines"
            return trimmed, verdict
    verdict["action"] = "fallback"
    return _GUARDRAIL_FALLBACK, verdict


ActionKind = Literal[
    "ai_followup", "navigate_form", "create_draft", "offline_task", "await_input"
]


class SuggestedAction(BaseModel):
    """A client-safe next step. Action type is always classified server-side."""

    type: ActionKind
    title: str
    owner_role: str | None = None
    completion_signal: str | None = None
    target_path: str | None = None
    followup_prompt: str | None = None


def _classify_action(text: str) -> SuggestedAction:
    """Map plain-language recommendations to a stable UI behavior, not case-by-case UI rules."""
    title = re.sub(r"^[【\[]?[^：:\]]+[】\]]?[：:]\s*", "", (text or "").strip())[:120]
    if re.search(r"回填|填写.*(?:系统|采购单)|更新.*(?:到料|交期)|录入.*(?:到料|交期)", title):
        return SuggestedAction(
            type="navigate_form",
            title=title,
            owner_role="采购",
            completion_signal="采购单已回填预计到料日",
            target_path="/admin/purchase?tab=orders",
        )
    if re.search(r"草稿|生成.*(?:采购|排产)|创建.*(?:采购|排产)", title):
        return SuggestedAction(
            type="create_draft",
            title=title,
            completion_signal="人工确认后创建草稿",
        )
    if re.search(r"等待|待.*(?:回复|到料|回填)|到料后|回复后", title):
        return SuggestedAction(
            type="await_input",
            title=title,
            completion_signal="外部信息回填后可继续",
        )
    if re.search(
        r"线下|联系|沟通|催.*(?:料|供应商|客户)|供应商|客户确认|电话|"
        r"(?:与|向).{1,24}(?:确认|沟通|联系|催收|协商|跟进)",
        title,
    ):
        return SuggestedAction(
            type="offline_task",
            title=title,
            owner_role="采购" if "供应商" in title or "料" in title else "业务",
            completion_signal="在系统回填外部确认结果",
        )
    return SuggestedAction(type="ai_followup", title=title, followup_prompt=title)


def _extract_todos(reply: str) -> list[SuggestedAction]:
    """Return only short, user-visible suggested actions from the final reply."""
    todos: list[str] = []
    for line in (reply or "").splitlines():
        text = line.strip().lstrip("-• ").strip()
        if re.match(r"^(?:裁决|解释为何|关键事实|关键依据)\s*[:：]", text):
            continue
        if re.search(r"建议|优先|需|请|确认|评估|催|回填|等待|生成|创建|联系", text) and len(text) <= 100:
            if text not in todos:
                todos.append(text)
    return [_classify_action(text) for text in todos[:3]]


class DecisionSummary(BaseModel):
    decision: str = Field(description="不超过 48 字的直接裁决")
    reason: str = Field(description="不超过 80 字的关键原因")
    facts: list[str] = Field(default_factory=list, description="最多 3 条可由证据支持的事实")
    actions: list[SuggestedAction] = Field(default_factory=list, description="最多 3 条下一步动作")


def _fact_value(facts: list[str], label: str) -> str | None:
    matched = next((fact for fact in facts if fact.startswith(f"{label}：")), None)
    return matched.split("：", 1)[1] if matched else None


def _result_item(tenant_id: int | None, result_id: str | None, path: str, label: str) -> dict[str, Any] | None:
    if not tenant_id or not result_id:
        return None
    try:
        value, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.{path}")
    except ValueError:
        return None
    return {"label": label, "value": value, "unit": "元", "ref": f"{result_id}.{path}"}


def build_response_presentation(
    question: str, evidence: list[dict[str, Any]], *, tenant_id: int | None = None
) -> dict[str, Any] | None:
    """Choose a small, typed UI payload from verified evidence only.

    The model never supplies values for a presentation.  More shapes can be
    added without changing the chat container; unsupported questions keep the
    normal decision rendering.
    """
    ranking_cards = [card for card in evidence if card.get("source") == "客户销售额排行"]
    if ranking_cards:
        result_id = ranking_cards[0].get("result_id")
        rows = []
        if tenant_id and result_id:
            try:
                total, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.total")
                for index in range(int(total)):
                    name, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.items[{index}].customer_name")
                    amount, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.items[{index}].sales_amount")
                    rows.append({"label": name, "value": amount, "unit": "元", "ref": f"{result_id}.data.items[{index}].sales_amount"})
            except ValueError:
                rows = []
        if not rows:
            facts = list(ranking_cards[0].get("facts") or [])
            for index, fact in enumerate(facts):
                if fact.startswith("客户："):
                    value = next((item.split("：", 1)[1] for item in facts[index + 1:] if item.startswith("销售额：")), None)
                    if value is not None: rows.append({"label": fact.split("：", 1)[1], "value": value, "unit": "元"})
        if rows:
            return {"type": "ranking", "title": "客户销售额排行", "items": rows}
    trend = next((card for card in evidence if card.get("source") == "毛利月度趋势"), None)
    if trend:
        result_id = trend.get("result_id")
        items = []
        if tenant_id and result_id:
            try:
                stored, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.items")
                items = [
                    {"label": row["period"], "value": row["gross_profit"], "unit": "元",
                     "ref": f"{result_id}.data.items[{index}].gross_profit"}
                    for index, row in enumerate(stored) if isinstance(row, dict)
                ]
            except ValueError:
                items = []
        if items:
            return {"type": "time_series", "title": "毛利月度趋势", "items": items}
    if _EXCEPTION_LIST_RE.search(question or ""):
        delivery = next((card for card in evidence if card.get("source") == "交期在制诊断"), None)
        result_id = delivery.get("result_id") if delivery else None
        items = []
        if tenant_id and result_id:
            try:
                rows, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.data.focus_orders")
                for index, row in enumerate(rows):
                    if not isinstance(row, dict) or not row.get("at_risk"):
                        continue
                    items.append({
                        "label": str(row.get("order_no") or "未知订单"),
                        "value": row.get("overall_percent") or 0,
                        "unit": "%",
                        "detail": f"交期 {row.get('delivery_date') or '未提供'}",
                        "ref": f"{result_id}.data.data.focus_orders[{index}].overall_percent",
                    })
            except ValueError:
                items = []
        if items:
            return {"type": "exception_list", "title": "交期风险订单", "items": items}
    if re.search(r"(?:成本|费用).*(?:构成|结构|占比)|(?:构成|结构|占比).*(?:成本|费用)", question or ""):
        report = next((card for card in evidence if card.get("source") == "利润报表"), None)
        result_id = report.get("result_id") if report else None
        items = []
        if tenant_id and result_id:
            try:
                total, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.summary.total_cost")
                if float(total or 0) > 0:
                    for label, field in [("材料", "material_cost"), ("人工", "labor_cost"), ("其它", "other_cost")]:
                        value, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.summary.{field}")
                        calc = analysis_result_store.calculate(
                            tenant_id, "share", [f"{result_id}.data.summary.{field}", f"{result_id}.data.summary.total_cost"], precision=1,
                        )
                        items.append({"label": label, "value": value, "unit": "元", "share": calc["value"], "share_ref": f"{calc['calculation_id']}.value"})
            except ValueError:
                items = []
        if items:
            return {"type": "composition", "title": "成本构成", "items": items}
    if _PROFIT_OVERVIEW_RE.search(question or "") and re.search(r"明细|列表|出表|表格", question or ""):
        report = next((card for card in evidence if card.get("source") == "利润报表"), None)
        result_id = report.get("result_id") if report else None
        rows = []
        columns = [
            ("订单", "order_no"), ("客户", "customer_name"), ("收入", "revenue"),
            ("成本", "total_cost"), ("毛利", "gross_profit"),
        ]
        if tenant_id and result_id:
            try:
                stored, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.orders")
                for index, row in enumerate(stored):
                    if not isinstance(row, dict):
                        continue
                    rows.append({key: row.get(key) for _label, key in columns} | {
                        "refs": {key: f"{result_id}.data.orders[{index}].{key}" for _label, key in columns},
                    })
            except ValueError:
                rows = []
        if rows:
            return {"type": "data_table", "title": "利润订单明细", "columns": [label for label, _key in columns], "keys": [key for _label, key in columns], "rows": rows}
    if _PROFIT_OVERVIEW_RE.search(question or "") and re.search(r"归因|主要由.*(?:造成|贡献)|谁.*(?:造成|贡献)", question or ""):
        report = next((card for card in evidence if card.get("source") == "利润报表"), None)
        result_id = report.get("result_id") if report else None
        items = []
        if tenant_id and result_id:
            try:
                orders, _ = analysis_result_store.read_ref(tenant_id, f"{result_id}.data.orders")
                ranked = sorted(enumerate(orders), key=lambda item: float((item[1] or {}).get("gross_profit") or 0), reverse=True)
                for index, row in ranked[:5]:
                    if isinstance(row, dict):
                        items.append({"label": row.get("order_no") or "未知订单", "value": row.get("gross_profit") or 0, "unit": "元", "ref": f"{result_id}.data.orders[{index}].gross_profit"})
            except ValueError:
                items = []
        if items:
            return {"type": "attribution_analysis", "title": "毛利主要贡献订单", "items": items}
    if not _PROFIT_OVERVIEW_RE.search(question or ""):
        return None
    if _PERIOD_COMPARE_RE.search(question or ""):
        reports = [card for card in evidence if card.get("source") == "利润报表"]
        if len(reports) < 2:
            return None
        label, field = ("收入", "收入") if "收入" in question else ("成本", "成本合计") if "成本" in question else ("毛利", "毛利")
        current = reports[0]
        previous = reports[1]
        ref_path = {"收入": "data.summary.revenue", "成本合计": "data.summary.total_cost", "毛利": "data.summary.gross_profit"}[field]
        current_item = _result_item(tenant_id, current.get("result_id"), ref_path, label)
        previous_item = _result_item(tenant_id, previous.get("result_id"), ref_path, label)
        current_value = current_item["value"] if current_item else _fact_value(list(current.get("facts") or []), field)
        previous_value = previous_item["value"] if previous_item else _fact_value(list(previous.get("facts") or []), field)
        if current_value is None or previous_value is None:
            return None
        try:
            now_num, prev_num = float(current_value), float(previous_value)
        except ValueError:
            return None
        delta = now_num - prev_num
        rate = None if prev_num == 0 else delta / abs(prev_num) * 100
        delta_ref = rate_ref = None
        if tenant_id and current_item and previous_item:
            try:
                difference = analysis_result_store.calculate(
                    tenant_id, "subtract", [current_item["ref"], previous_item["ref"]], precision=2
                )
                delta = float(difference["value"])
                delta_ref = f"{difference['calculation_id']}.value"
                if prev_num != 0:
                    ratio = analysis_result_store.calculate(
                        tenant_id, "ratio", [delta_ref, previous_item["ref"]], precision=1
                    )
                    rate = float(ratio["value"])
                    rate_ref = f"{ratio['calculation_id']}.value"
            except ValueError:
                pass
        current_filter, previous_filter = current.get("filters") or {}, previous.get("filters") or {}
        current_payload = {"label": f"{current_filter.get('year')}年{current_filter.get('month')}月", "value": current_value, "unit": "元"}
        previous_payload = {"label": f"{previous_filter.get('year')}年{previous_filter.get('month')}月", "value": previous_value, "unit": "元"}
        if current_item: current_payload["ref"] = current_item["ref"]
        if previous_item: previous_payload["ref"] = previous_item["ref"]
        comparison = {
            "type": "period_comparison",
            "title": f"{label}{'环比' if re.search(r'环比|上月', question) else '同比'}",
            "label": label,
            "current": current_payload,
            "previous": previous_payload,
            "delta": str(round(delta, 2)),
            "rate": None if rate is None else str(round(rate, 1)),
        }
        if delta_ref: comparison["delta_ref"] = delta_ref
        if rate_ref: comparison["rate_ref"] = rate_ref
        return comparison
    if not _NUMBER_ONLY_RE.search(question or ""):
        return None
    report = next((card for card in evidence if card.get("source") == "利润报表"), None)
    facts = [fact for card in evidence if card.get("source") == "利润报表" for fact in (card.get("facts") or [])]
    result_id = report.get("result_id") if report else None
    items = [
        _result_item(tenant_id, result_id, "data.summary.revenue", "收入") or {"label": "收入", "value": _fact_value(facts, "收入"), "unit": "元"},
        _result_item(tenant_id, result_id, "data.summary.total_cost", "成本") or {"label": "成本", "value": _fact_value(facts, "成本合计"), "unit": "元"},
        _result_item(tenant_id, result_id, "data.summary.gross_profit", "毛利") or {"label": "毛利", "value": _fact_value(facts, "毛利"), "unit": "元"},
    ]
    if any(item["value"] is None for item in items):
        return None
    return {
        "type": "metric_snapshot",
        "title": "本月利润概况",
        "items": items,
    }


def _capability_boundary_summary(raw_reply: str) -> DecisionSummary | None:
    """Keep a useful, grounded answer when the evidence explains a data capability limit."""
    clean = raw_reply.replace("**", "")
    if not ("回款" in clean and _CAPABILITY_BOUNDARY_RE.search(clean)):
        return None
    has_open_receivable_by_order = bool(re.search(r"未结应收.*(?:单号|订单号)", clean, re.S))
    has_monthly_payment = "本月回款" in clean
    facts: list[str] = []
    if has_monthly_payment:
        facts.append("“本月回款”仅支持按年月汇总，不能作为单号回款流水。")
    if has_open_receivable_by_order:
        facts.append("“未结应收”可按客户和单号辅助核对未回款情况。")
    return DecisionSummary(
        decision="当前无法按单号直接查询回款流水",
        reason="现有指标未提供按单号维度的回款明细，不能据此确认某订单已回多少。",
        facts=facts[:2],
        actions=[SuggestedAction(
            type="await_input",
            title="等待输入需核对的订单号后，用未结应收辅助核对",
            completion_signal="输入订单号并完成未结应收查询",
        )],
    )


def _direct_profit_number_summary(
    question: str, evidence: list[dict[str, Any]]
) -> DecisionSummary | None:
    """Answer a narrow profit-number question without model editorial drift."""
    if not (_PROFIT_OVERVIEW_RE.search(question or "") and _NUMBER_ONLY_RE.search(question or "")):
        return None
    facts = [
        fact for card in evidence if card.get("source") == "利润报表"
        for fact in (card.get("facts") or [])
    ]
    values: dict[str, float] = {}
    for label in ("收入", "成本合计", "毛利"):
        matched = next((fact for fact in facts if fact.startswith(f"{label}：")), None)
        if not matched:
            return None
        try:
            values[label] = float(matched.split("：", 1)[1].replace(",", ""))
        except ValueError:
            return None
    def amount(value: float) -> str:
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")

    return DecisionSummary(
        decision=(
            f"本月收入 {amount(values['收入'])} 元，成本 {amount(values['成本合计'])} 元，"
            f"毛利 {amount(values['毛利'])} 元。"
        ),
        reason="",
        facts=[],
        actions=[],
    )


def build_decision_summary(question: str, raw_reply: str, evidence: list[dict[str, Any]]) -> DecisionSummary:
    """Convert a verbose agent result into the single-screen decision contract."""
    capability_summary = _capability_boundary_summary(raw_reply)
    if capability_summary:
        return capability_summary
    direct_profit_summary = _direct_profit_number_summary(question, evidence)
    if direct_profit_summary:
        return direct_profit_summary
    evidence_text = json.dumps(evidence, ensure_ascii=False)
    prompt = (
        "你是鞋厂 ERP 的回答编辑。仅根据原始回答和依据，生成简短决策摘要。"
        "禁止展示思考过程、工具名、内部字段；不得新增事实。"
        "若问题问收入、成本、利润或毛利，decision/reason 必须优先给出利润结构，"
        "不得用回款或现金流替代答案；除非用户询问，否则不要把它写为主结论。"
        "facts/actions 各最多3条，适合首屏阅读。actions 只写 title，不要擅自声明已执行。严格只返回 JSON："
        '{"decision":"","reason":"","facts":[],"actions":[{"title":""}]}。\n'
        f"问题：{question}\n原始回答：{raw_reply}\n依据：{evidence_text}"
    )
    try:
        result = _make_model().invoke(prompt)
        text = _content_to_text(result.content)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            payload = json.loads(match.group(0))
            payload["actions"] = [
                _classify_action(item.get("title", "") if isinstance(item, dict) else str(item))
                for item in (payload.get("actions") or [])
            ]
            return DecisionSummary.model_validate(payload)
    except Exception:
        pass
    # Provider-safe fallback: only parse final labelled sections. Never use
    # the opening text, which is commonly an agent work draft.
    clean = raw_reply.replace("**", "")
    decisions = list(re.finditer(r"裁决\s*[:：]\s*([^\n]+)", clean))
    decision = decisions[-1].group(1).strip()[:80] if decisions else "暂不能确认"
    reason_match = re.search(r"解释为何\s*[:：]?\s*\n?([^\n]+)", clean)
    reason = reason_match.group(1).strip()[:120] if reason_match else "请查看依据后确认。"
    fact_section = re.search(r"关键事实\s*[:：](.*?)(?:\n\s*(?:用户问|从仿真|最小可执行|裁决)[:：])", clean, re.S)
    facts = []
    if fact_section:
        facts = [line.strip().lstrip("-•1234567890.、 ") for line in fact_section.group(1).splitlines() if line.strip()][:3]
    actions = _extract_todos(clean)
    return DecisionSummary(decision=decision, reason=reason, facts=facts, actions=actions)


_TOOL_STAGE_LABELS = {
    "query_metric": "已核对业务数据",
    "get_daily_load": "已核对工序负荷",
    "get_schedule_pool": "已核对待排订单",
    "generate_schedule_proposals": "已生成排产方案",
    "simulate_insert_order": "已完成插单仿真",
    "get_schedule_settings": "已读取排产规则",
}


def _stream_safe_reply(reply: str, *, width: int = 24):
    """Progressively deliver an already-guarded answer, never model scratchpad."""
    for start in range(0, len(reply), width):
        yield reply[start : start + width]
        # A tiny pacing interval lets EventSource/fetch paint visible progress.
        time.sleep(0.012)


_session_locks: dict[tuple[int, str], tuple[threading.Lock, int]] = {}
_session_locks_guard = threading.Lock()
_RESULT_ID_RE = re.compile(r"\br_[0-9a-f]{16}\b")
_CALCULATION_ID_RE = re.compile(r"\bc_[0-9a-f]{16}\b")
_APPROVAL_ID_RE = re.compile(r'"approval_id"\s*:\s*"([^"]+)"')
_APPROVAL_STATUS_RE = re.compile(r'"(?:approval_)?status"\s*:\s*"([^"]+)"')


@contextmanager
def _conversation_lock(tenant_id: int, conversation_id: str, *, timeout: float = 180):
    """Serialize one conversation, while unrelated tenants/sessions run freely."""
    key = (tenant_id, conversation_id)
    with _session_locks_guard:
        existing = _session_locks.get(key)
        lock, users = existing if existing else (threading.Lock(), 0)
        _session_locks[key] = (lock, users + 1)
    acquired = lock.acquire(timeout=timeout)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
        with _session_locks_guard:
            current = _session_locks.get(key)
            if current:
                current_lock, users = current
                if users <= 1:
                    _session_locks.pop(key, None)
                else:
                    _session_locks[key] = (current_lock, users - 1)


def _record_agent_trace(
    *, tenant_id: int, conversation_id: str, run_id: str,
    planner: analysis_plans.PlannerOutput, execution_plan: analysis_plans.ExecutionPlan | None,
    tool_evidence: list[dict[str, Any]], guardrail: dict[str, Any] | None, outcome: str,
) -> None:
    """Write a fail-open replay ledger after the run has all produced IDs."""
    try:
        serialized = "\n".join(str(item.get("content") or "") for item in tool_evidence)
        agent_trace_service.record_run(
            run_id=run_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            semantic_plan_id=planner.semantic_plan_id,
            execution_plan_id=execution_plan.execution_plan_id if execution_plan else None,
            match_passed=(analysis_plans.match_execution_plan(planner.plan, execution_plan)
                          if planner.plan and execution_plan else None),
            result_ids=_RESULT_ID_RE.findall(serialized),
            calculation_ids=_CALCULATION_ID_RE.findall(serialized),
            approval_ids=_APPROVAL_ID_RE.findall(serialized),
            approval_statuses=_APPROVAL_STATUS_RE.findall(serialized),
            versions={
                **get_policy_bundle().versions,
                "prompt": WORKSHOP_AGENT_PROMPT_VERSION,
                "calculation_engine": analysis_result_store.CALCULATION_ENGINE_VERSION,
                "evidence_guardrail": EVIDENCE_GUARDRAIL_VERSION,
            },
            outcome=outcome if not guardrail else f"{outcome}:{guardrail.get('reason', 'unknown')}",
        )
    except Exception:
        # Trace persistence must never make a governed read path unavailable.
        pass


def _attach_plan_trace_metadata(
    run_config: dict[str, Any], planner: analysis_plans.PlannerOutput,
    execution_plan: analysis_plans.ExecutionPlan | None,
) -> None:
    """Enrich the optional LangSmith root trace before model execution."""
    metadata = run_config.setdefault("metadata", {})
    metadata["semantic_plan_id"] = planner.semantic_plan_id
    metadata["execution_plan_id"] = execution_plan.execution_plan_id if execution_plan else None
    metadata["semantic_match"] = (
        analysis_plans.match_execution_plan(planner.plan, execution_plan)
        if planner.plan and execution_plan else None
    )


def agent_available() -> dict[str, Any]:
    s = get_settings()
    enabled = bool(s.schedule_agent_enabled) and bool(s.deepseek_api_key)
    return {
        "enabled": enabled,
        "model": s.deepseek_model if enabled else None,
        "reason": None if enabled else "未配置 DEEPSEEK_API_KEY 或已关闭 SCHEDULE_AGENT_ENABLED",
        "tracing_enabled": bool(s.langsmith_tracing and s.langsmith_api_key),
    }


def _agent_run_config(
    *,
    tenant_id: int,
    conversation_id: str,
    thread_id: str,
    transport: str,
) -> tuple[str, dict[str, Any]]:
    """为每轮咨询建立稳定 run_id；LangSmith 未配置或不可用时保持业务链路可用。"""
    run_uuid = uuid.uuid4()
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "run_id": run_uuid,
        "run_name": "workshop_agent_chat",
        "tags": ["workshop-agent", transport],
        "metadata": {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "transport": transport,
            "agent": "schedule-assistant",
            "policy_versions": get_policy_bundle().versions,
            "runtime_versions": {
                "prompt": WORKSHOP_AGENT_PROMPT_VERSION,
                "calculation_engine": analysis_result_store.CALCULATION_ENGINE_VERSION,
                "evidence_guardrail": EVIDENCE_GUARDRAIL_VERSION,
            },
        },
    }

    settings = get_settings()
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return str(run_uuid), config

    try:
        from langchain_core.tracers.langchain import LangChainTracer
        from langsmith import Client

        client = Client(
            api_key=settings.langsmith_api_key,
            api_url=settings.langsmith_endpoint.rstrip("/"),
        )
        config["callbacks"] = [
            LangChainTracer(client=client, project_name=settings.langsmith_project)
        ]
    except Exception:
        # 可观测性必须 fail-open，不能因第三方配置问题阻断生产决策路径。
        pass
    return str(run_uuid), config


def _data_dir() -> Path:
    s = get_settings()
    p = Path(s.schedule_agent_data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache
def _checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = _data_dir() / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


@lru_cache
def _store():
    from langgraph.store.sqlite import SqliteStore

    path = _data_dir() / "memory.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store


def _memory_ns(tenant_id: int) -> tuple[str, str]:
    return ("schedule_agent", f"tenant_{tenant_id}")


def list_memories(tenant_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    store = _store()
    items = store.search(_memory_ns(tenant_id), limit=limit)
    out: list[dict[str, Any]] = []
    for it in items:
        val = it.value if hasattr(it, "value") else it
        if isinstance(val, dict):
            out.append(
                {
                    "key": getattr(it, "key", None),
                    "text": val.get("text"),
                    "updated_at": val.get("updated_at"),
                }
            )
    return out


def remember_fact(tenant_id: int, key: str, text: str) -> dict[str, Any]:
    store = _store()
    key = (key or "").strip()[:80] or f"fact_{uuid.uuid4().hex[:8]}"
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("empty_memory")
    payload = {"text": text, "updated_at": date.today().isoformat()}
    store.put(_memory_ns(tenant_id), key, payload)
    return {"key": key, **payload}


def _build_tools(
    tenant_id: int,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
    allowed_metric_ids: set[str] | None = None,
):
    """每个工具独立 Session，避免 LangGraph 并行调工具时共用 FastAPI 请求 Session 打乱 pymysql 包序。"""
    perms = list(permission_codes or [])

    @contextmanager
    def _session() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @tool
    def get_schedule_pool(
        hide_scheduled: bool = True,
        hide_first_kit_blocked: bool = False,
    ) -> str:
        """查看待排池订单（含齐套、优先级）。"""
        with _session() as db:
            items = schedule_engine.collect_candidate_orders(
                db,
                tenant_id,
                hide_scheduled=hide_scheduled,
                hide_first_kit_blocked=hide_first_kit_blocked,
            )
            return json.dumps({"items": items, "total": len(items)}, ensure_ascii=False)

    @tool
    def get_schedule_settings() -> str:
        """读取租户排产规则：默认工期、粗产能、风险阈值。"""
        with _session() as db:
            cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
            return json.dumps(cfg, ensure_ascii=False)

    @tool
    def get_daily_load(days: int = 14) -> str:
        """查看从今天起 N 天的工序日负荷与瓶颈。"""
        days = max(1, min(int(days or 14), 60))
        today = date.today()
        with _session() as db:
            data = schedule_engine.daily_load(
                db, tenant_id, date_from=today, date_to=today + timedelta(days=days)
            )
            return json.dumps(data, ensure_ascii=False)

    @tool
    def generate_schedule_proposals(order_ids: Optional[list[int]] = None) -> str:
        """用规则引擎生成 2～3 套排产方案（含风险）。可指定 order_ids，否则用待排池。"""
        with _session() as db:
            props = schedule_engine.generate_proposals(
                db, tenant_id, order_ids=order_ids or None, hide_scheduled=True
            )
            return json.dumps(props, ensure_ascii=False)

    @tool
    def simulate_insert_order(order_id: int) -> str:
        """插单仿真：返回保交期/保现场/折中三套方案及影响清单。"""
        with _session() as db:
            try:
                props = schedule_engine.simulate_insert(db, tenant_id, int(order_id))
            except ValueError as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)
            return json.dumps({"proposals": props}, ensure_ascii=False)

    @tool
    def create_draft_from_proposal_json(proposal_json: str, note: str = "") -> str:
        """将某套方案写入排产草稿（未确认，不会改现场派工）。传入完整 proposal 对象 JSON。"""
        try:
            proposal = json.loads(proposal_json)
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid_json"}, ensure_ascii=False)
        with _session() as db:
            try:
                draft = schedule_service.create_draft_from_proposal(
                    db, tenant_id, proposal, note=note or None, auto_assign=True
                )
            except schedule_service.ScheduleError as e:
                return json.dumps({"error": e.code, "message": e.message}, ensure_ascii=False)
            return json.dumps(
                {
                    "draft_id": draft.get("id"),
                    "status": draft.get("status"),
                    "note": draft.get("note"),
                },
                ensure_ascii=False,
            )

    @tool
    def list_metrics() -> str:
        """列出当前用户有权查询的只读指标。每项含 id（仅供 query_metric）与 name（对用户说话时用中文 name，禁止把 id 念给用户）。"""
        items = workshop_metrics.list_metrics(permission_codes=perms)
        if allowed_metric_ids is not None:
            items = [item for item in items if item["id"] in allowed_metric_ids]
        return json.dumps({"items": items, "total": len(items)}, ensure_ascii=False)

    @tool
    def query_metric(metric_id: str, params_json: str = "{}") -> str:
        """按白名单 metric_id 查询指标。params_json 为 JSON 对象字符串，如 {\"order_no\":\"MO1\"} 或 {\"year\":2026,\"month\":8}。"""
        try:
            if allowed_metric_ids is not None and metric_id not in allowed_metric_ids:
                return json.dumps(
                    {"error": "specialist_scope", "message": "该指标不在本轮业务角色的查询范围内"},
                    ensure_ascii=False,
                )
            params = json.loads(params_json or "{}")
            if not isinstance(params, dict):
                return json.dumps({"error": "invalid_params", "message": "params_json 须为对象"}, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid_params", "message": "params_json 不是合法 JSON"}, ensure_ascii=False)
        with _session() as db:
            result = workshop_metrics.query_metric(
                db,
                tenant_id,
                metric_id,
                params=params,
                permission_codes=perms,
            )
            # Preserve the query scope with the result. This is consumed by
            # the Evidence Ledger, never rendered as raw JSON to the user.
            result["_evidence"] = {
                "metric_id": metric_id,
                "filters": params,
                "queried_at": _now_iso(),
            }
            if not result.get("error"):
                result["_result"] = {
                    "result_id": analysis_result_store.put_result(
                        tenant_id, metric_id, result, params, session_id=conversation_id,
                    ),
                    "metric_id": metric_id,
                }
            return json.dumps(result, ensure_ascii=False, default=str)

    @tool
    def calculate(operation: str, inputs_json: str, precision: int = 2) -> str:
        """对已核验 result_id 字段做受限计算。inputs_json 只能是字段引用数组，禁止填写数字。"""
        try:
            inputs = json.loads(inputs_json)
            if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
                raise ValueError("inputs_json 必须是字段引用数组")
            result = analysis_result_store.calculate(  # type: ignore[arg-type]
                tenant_id, operation, inputs, precision=precision, session_id=conversation_id,
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except (ValueError, json.JSONDecodeError) as e:
            return json.dumps({"error": "invalid_calculation", "message": str(e)}, ensure_ascii=False)

    @tool
    def inspect_result(result_id: str, fields_json: str = "[]", limit: int = 20) -> str:
        """查看已核验结果的字段目录或少量指定字段。不得读取未引用的大明细。"""
        try:
            fields = json.loads(fields_json or "[]")
            if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
                raise ValueError("fields_json 必须是字段名数组")
            result = analysis_result_store.inspect_result(
                tenant_id, result_id, fields, limit, session_id=conversation_id,
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except (ValueError, json.JSONDecodeError) as e:
            return json.dumps({"error": "invalid_result_inspection", "message": str(e)}, ensure_ascii=False)

    @tool
    def remember_user_fact(key: str, text: str) -> str:
        """保存长期记忆（厂规偏好、产能约定等）。"""
        try:
            row = remember_fact(tenant_id, key, text)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps(row, ensure_ascii=False)

    @tool
    def list_user_facts() -> str:
        """列出本租户已保存的长期记忆。"""
        return json.dumps({"items": list_memories(tenant_id)}, ensure_ascii=False)

    return [
        get_schedule_pool,
        get_schedule_settings,
        get_daily_load,
        generate_schedule_proposals,
        simulate_insert_order,
        create_draft_from_proposal_json,
        list_metrics,
        query_metric,
        calculate,
        remember_user_fact,
        list_user_facts,
    ]


def _make_model() -> ChatOpenAI:
    s = get_settings()
    if not s.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    return ChatOpenAI(
        model=s.deepseek_model or "deepseek-chat",
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url or "https://api.deepseek.com",
        temperature=0,
        # 军师默认是高频决策辅助，不让单次回答占满阅读区；工具调用仍可多轮完成。
        max_tokens=2048,
    )


def _plan_semantic_question(question: str) -> analysis_plans.PlannerOutput:
    """Ask the model for schema-constrained JSON, then validate it locally.

    The deterministic adapter is deliberately a fail-closed availability
    fallback; it never grants a metric or query parameter outside the same
    policy registry.
    """
    fallback = analysis_plans.plan_question(question)
    if fallback.missing_slots:
        return fallback
    registry = {
        name: {
            "required_slots": spec.required_slots,
            "allowed_metrics": spec.allowed_metrics,
        }
        for name, spec in analysis_plans.REGISTRY.items()
        if spec.allowed_metrics
    }
    try:
        structured = _make_model().with_structured_output(analysis_plans.SemanticPlan)
        proposal = structured.invoke([
            ("system", "你是 ERP 语义计划器。仅输出 JSON；仅能使用如下注册项。无法确定则输出一个已注册类型并留下缺失 slot，不得编造指标。\n" + json.dumps(registry, ensure_ascii=False)),
            ("human", question),
        ])
        raw = proposal.model_dump() if isinstance(proposal, BaseModel) else proposal
        return analysis_plans.parse_planner_json(raw)
    except Exception:
        return fallback


def _build_agent(
    tenant_id: int,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
    profiles: list[lifecycle_agents.LifecycleAgentProfile] | None = None,
):
    from deepagents import FilesystemPermission, create_deep_agent

    memories = list_memories(tenant_id, limit=30)
    mem_block = ""
    if memories:
        lines = [f"- [{m.get('key')}] {m.get('text')}" for m in memories if m.get("text")]
        mem_block = "\n\n已知长期记忆：\n" + "\n".join(lines)

    allowed = lifecycle_agents.allowed_metric_ids(profiles or [])
    metrics = workshop_metrics.list_metrics(permission_codes=permission_codes)
    if allowed is not None:
        metrics = [metric for metric in metrics if metric["id"] in allowed]
    if metrics:
        metric_lines = [f"- {m['id']}：{m['name']}（{m['description']}）" for m in metrics]
        mem_block += "\n\n当前可用问数指标：\n" + "\n".join(metric_lines)
    if profiles:
        mem_block += "\n\n本轮协作业务角色：\n" + "\n".join(
            f"- {profile.name}：{profile.description}" for profile in profiles
        )
        mem_block += (
            "\n\n协作规则：你是总军师。必须用 task 工具把本轮涉及的每个业务角色"
            "分别委派给同名子军师；收到各子军师的最终业务摘要后再汇总。"
            "不要自己替子军师做其职责范围内的数据核对，也不要向用户展示内部推理。"
        )

    readonly_tool_names = {
        "get_schedule_pool", "get_schedule_settings", "get_daily_load", "list_metrics",
        "query_metric", "calculate", "inspect_result", "list_user_facts",
    }
    subagents = []
    for profile in profiles or []:
        specialist_tools = [
            tool_item for tool_item in _build_tools(
                tenant_id,
                conversation_id=conversation_id,
                permission_codes=permission_codes,
                allowed_metric_ids=set(profile.metric_ids),
            )
            if getattr(tool_item, "name", "") in readonly_tool_names
        ]
        subagents.append({
            "name": profile.id,
            "description": f"{profile.name}：{profile.description}",
            "system_prompt": (
                f"你是鞋厂 ERP 的{profile.name}。只处理：{profile.description}。"
                "只能使用分配给你的只读工具和指标；不得写入、创建草稿或保存记忆。"
                "完成后只返回业务核对摘要：结论、最多三条已核验事实、需要总军师协调的事项。"
                "不得输出思考过程、原始 JSON、工具参数或内部字段。"
            ),
            "tools": specialist_tools,
            "permissions": [FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny")],
        })

    return create_deep_agent(
        model=_make_model(),
        tools=_build_tools(
            tenant_id,
            conversation_id=conversation_id,
            permission_codes=permission_codes,
            allowed_metric_ids=allowed,
        ),
        system_prompt=SYSTEM_PROMPT + mem_block,
        checkpointer=_checkpointer(),
        store=_store(),
        # 禁用文件系统读写，避免幻觉式翻盘外文件；execute 在非沙箱 backend 下也会失败
        permissions=[
            FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
        ],
        subagents=subagents or None,
        name=f"workshop-agent-t{tenant_id}",
    )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


@lru_cache
def _catalog_conn() -> sqlite3.Connection:
    path = _data_dir() / "conversations.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_conv_tenant_updated "
        "ON conversations(tenant_id, updated_at DESC)"
    )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "ui_messages" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN ui_messages TEXT")
    conn.commit()
    return conn


def _thread_id(tenant_id: int, conversation_id: str) -> str:
    return f"t{tenant_id}:{conversation_id}"


def _auto_title(message: str) -> str:
    text = " ".join((message or "").strip().split())
    if not text:
        return "新对话"
    return text if len(text) <= 28 else text[:28] + "…"


def _upsert_conversation(tenant_id: int, conversation_id: str, *, title: str | None = None) -> dict[str, Any]:
    conn = _catalog_conn()
    now = _now_iso()
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if row:
        new_title = title if title is not None else row["title"]
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND tenant_id=?",
            (new_title, now, conversation_id, tenant_id),
        )
        conn.commit()
        return {
            "id": conversation_id,
            "title": new_title,
            "created_at": row["created_at"],
            "updated_at": now,
        }
    use_title = title or "新对话"
    conn.execute(
        "INSERT INTO conversations(id, tenant_id, title, created_at, updated_at) VALUES(?,?,?,?,?)",
        (conversation_id, tenant_id, use_title, now, now),
    )
    conn.commit()
    return {
        "id": conversation_id,
        "title": use_title,
        "created_at": now,
        "updated_at": now,
    }


def list_conversations(tenant_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    conn = _catalog_conn()
    limit = max(1, min(int(limit or 100), 200))
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations "
        "WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def rename_conversation(tenant_id: int, conversation_id: str, title: str) -> dict[str, Any]:
    title = " ".join((title or "").strip().split())
    if not title:
        raise ValueError("empty_title")
    title = title[:60]
    conn = _catalog_conn()
    row = conn.execute(
        "SELECT id FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if not row:
        raise ValueError("not_found")
    return _upsert_conversation(tenant_id, conversation_id, title=title)


def delete_conversation(tenant_id: int, conversation_id: str) -> dict[str, Any]:
    conn = _catalog_conn()
    cur = conn.execute(
        "DELETE FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    )
    conn.commit()
    if cur.rowcount <= 0:
        raise ValueError("not_found")
    try:
        _checkpointer().delete_thread(_thread_id(tenant_id, conversation_id))
    except Exception:
        # 目录已删即可；checkpoint 缺失不阻断
        pass
    return {"id": conversation_id, "deleted": True}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _serialize_ui_messages(
    raw_messages: list[Any], *, permission_codes: list[str] | None = None
) -> list[dict[str, Any]]:
    """仅输出用户/助手可见消息；工具调用收拢到下一条助手消息的 tools/charts。"""
    out: list[dict[str, Any]] = []
    pending_tools: list[dict[str, Any]] = []
    pending_charts: list[dict[str, Any]] = []
    question = ""
    for m in raw_messages:
        mtype = getattr(m, "type", None) or m.__class__.__name__
        name = getattr(m, "name", None)
        if mtype in ("tool", "ToolMessage"):
            content = _content_to_text(getattr(m, "content", ""))
            pending_tools.append(
                {
                    "name": name,
                    "content": content[:600],
                }
            )
            for c in workshop_metrics.extract_charts(content):
                pending_charts.append(c)
            continue
        if mtype in ("human", "HumanMessage", "user"):
            text = _content_to_text(getattr(m, "content", "")).strip()
            if text:
                out.append({"role": "user", "content": text, "tools": [], "charts": []})
                question = text
            pending_tools = []
            pending_charts = []
            continue
        if mtype in ("ai", "AIMessage", "assistant"):
            text = _content_to_text(getattr(m, "content", "")).strip()
            # 跳过纯 tool_call 中间步（无文本）
            tool_calls = getattr(m, "tool_calls", None) or []
            if not text and tool_calls:
                continue
            if text or pending_tools or pending_charts:
                safe_text, _ = apply_evidence_guardrail(
                    question, text or "（已调用工具）", [t["content"] for t in pending_tools]
                )
                out.append(
                    {
                        "role": "assistant",
                        "content": safe_text,
                        "tools": pending_tools[-8:],
                        "charts": select_response_charts(question, pending_charts),
                        "evidence": build_evidence_ledger(
                            pending_tools, permission_codes=permission_codes
                        ),
                    }
                )
            pending_tools = []
            pending_charts = []
    return out


def _load_raw_thread_messages(
    tenant_id: int,
    conversation_id: str,
    *,
    permission_codes: list[str] | None = None,
) -> list[Any]:
    """从 LangGraph 状态还原完整 messages（含 deepagents 增量快照）。

    注意：不可只用 checkpointer.get_tuple().channel_values['messages']，
    增量快照下该字段常为空。
    """
    config = {"configurable": {"thread_id": _thread_id(tenant_id, conversation_id)}}
    try:
        agent = _build_agent(tenant_id, permission_codes=permission_codes)
        st = agent.get_state(config)
        vals = getattr(st, "values", None) or {}
        raw = list(vals.get("messages") or [])
        if raw:
            return raw
    except Exception:
        pass
    # 兜底：旧版完整快照仍可能写在 channel_values
    try:
        tup = _checkpointer().get_tuple(config)
        if tup and tup.checkpoint:
            channel_values = tup.checkpoint.get("channel_values") or {}
            return list(channel_values.get("messages") or [])
    except Exception:
        pass
    return []


def _save_ui_messages(tenant_id: int, conversation_id: str, messages: list[dict[str, Any]]) -> None:
    conn = _catalog_conn()
    conn.execute(
        "UPDATE conversations SET ui_messages=?, updated_at=? WHERE id=? AND tenant_id=?",
        (json.dumps(messages, ensure_ascii=False), _now_iso(), conversation_id, tenant_id),
    )
    conn.commit()


def _read_cached_ui_messages(row: Any) -> list[dict[str, Any]] | None:
    raw = None
    try:
        raw = row["ui_messages"]
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def get_conversation_messages(
    tenant_id: int, conversation_id: str, *, permission_codes: list[str] | None = None
) -> dict[str, Any]:
    conn = _catalog_conn()
    meta = conn.execute(
        "SELECT id, title, created_at, updated_at, ui_messages FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if not meta:
        raise ValueError("not_found")

    cached = _read_cached_ui_messages(meta)
    if cached is not None:
        ui_messages = cached
    else:
        raw = _load_raw_thread_messages(tenant_id, conversation_id)
        ui_messages = _serialize_ui_messages(raw, permission_codes=permission_codes)
        if ui_messages:
            try:
                _save_ui_messages(tenant_id, conversation_id, ui_messages)
            except Exception:
                pass

    return {
        "id": meta["id"],
        "title": meta["title"],
        "created_at": meta["created_at"],
        "updated_at": meta["updated_at"],
        "messages": ui_messages,
        "model": get_settings().deepseek_model,
    }


def _refresh_ui_message_cache(
    tenant_id: int,
    conversation_id: str,
    *,
    permission_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    raw = _load_raw_thread_messages(
        tenant_id, conversation_id, permission_codes=permission_codes
    )
    ui_messages = _serialize_ui_messages(raw, permission_codes=permission_codes)
    if ui_messages:
        try:
            _save_ui_messages(tenant_id, conversation_id, ui_messages)
        except Exception:
            pass
    return ui_messages


def chat(
    db: Session,
    tenant_id: int,
    message: str,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
) -> dict[str, Any]:
    """多轮对话。conversation_id 为空则新建。

    注意：`db` 参数保留以兼容 API 签名；工具查询使用独立 Session，不复用请求 Session。
    """
    _ = db  # 工具侧自建 Session，避免与 LangGraph 并行执行冲突
    status = agent_available()
    if not status["enabled"]:
        raise RuntimeError(status["reason"] or "agent_disabled")

    message = (message or "").strip()
    if not message:
        raise ValueError("empty_message")
    profiles = lifecycle_agents.select_profiles(message)
    display_profiles = list(profiles)

    is_new = not (conversation_id or "").strip()
    conv_id = (conversation_id or "").strip() or uuid.uuid4().hex
    thread_id = _thread_id(tenant_id, conv_id)
    run_id, run_config = _agent_run_config(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        thread_id=thread_id,
        transport="sync",
    )
    preflight_traces, preflight_evidence, _preflight_charts, preflight_context, planner, execution_plan = _run_auto_diagnostic_bundle(
        tenant_id, message, conversation_id=conv_id, permission_codes=permission_codes, profiles=profiles
    )
    _attach_plan_trace_metadata(run_config, planner, execution_plan)
    resolved_profiles = agent_orchestration.select_roles(message, planner.plan)
    # Keep the roles already shown to the user unless semantic planning can
    # produce an equally broad specialist set.  A planner fallback must never
    # strand visible cards in "waiting".
    profiles = resolved_profiles if len(resolved_profiles) >= 2 else display_profiles
    child_plans = agent_orchestration.build_child_plans(message, planner.plan)
    if not child_plans and len(profiles) >= 2:
        parent = (planner.plan or analysis_plans.SemanticPlan(analysis_type="decision")).model_dump(mode="json")
        child_plans = [
            agent_orchestration.ChildPlan(
                child_plan_id=f"cp_{uuid.uuid4().hex[:16]}",
                lifecycle_role=profile.id,
                analysis_type=str(parent["analysis_type"]),
                allowed_metric_ids=list(profile.metric_ids),
                parent_semantic_plan=parent,
            )
            for profile in profiles
        ]
    if planner.missing_slots:
        title = _auto_title(message) if is_new else None
        meta = _upsert_conversation(tenant_id, conv_id, title=title)
        reply = _missing_slots_reply(planner.missing_slots)
        _record_agent_trace(
            tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=planner,
            execution_plan=execution_plan, tool_evidence=preflight_evidence,
            guardrail=None, outcome="missing_slots",
        )
        return {
            "conversation_id": conv_id, "run_id": run_id, "title": meta["title"], "reply": reply,
            "tool_traces": preflight_traces[-8:], "semantic_plan": planner.model_dump(),
            "missing_slots": planner.missing_slots,
            "evidence_guardrail": {"passed": True, "reason": "missing_slots", "unmatched": [], "tool_names": [], "has_usable_payload": False},
            "evidence": [], "presentation": None, "lifecycle_agents": lifecycle_agents.public_profiles(profiles),
            "child_plans": [plan.model_dump() for plan in child_plans],
            "model": get_settings().deepseek_model, "messages": [],
        }
    child_results = _execute_child_plans(
        tenant_id, child_plans, permission_codes=permission_codes,
    )
    agent_messages: list[dict[str, str]] = [{"role": "user", "content": message}]
    if preflight_context:
        agent_messages.insert(0, {"role": "system", "content": preflight_context})
    child_context = _child_results_context(child_results)
    if child_context:
        agent_messages.insert(0, {"role": "system", "content": child_context})

    with _conversation_lock(tenant_id, conv_id) as acquired:
        if not acquired:
            raise RuntimeError("agent_busy")
        agent = _build_agent(
            tenant_id, conversation_id=conv_id, permission_codes=permission_codes, profiles=profiles
        )
        result = agent.invoke(
            {"messages": agent_messages},
            config=run_config,
        )

    messages = result.get("messages") if isinstance(result, dict) else None
    reply = ""
    tool_traces: list[dict[str, Any]] = []
    child_evidence = [{"name": "child_agent", "content": json.dumps(result.model_dump(), ensure_ascii=False)} for result in child_results]
    tool_evidence: list[dict[str, Any]] = [*preflight_evidence, *child_evidence]
    tool_traces.extend(preflight_traces)
    if messages:
        for m in messages:
            mtype = getattr(m, "type", None) or m.__class__.__name__
            if mtype == "tool" or mtype == "ToolMessage":
                content = _content_to_text(getattr(m, "content", ""))
                tool_evidence.append({"name": getattr(m, "name", None), "content": content})
                tool_traces.append(
                    {
                        "name": getattr(m, "name", None),
                        "content": content[:800],
                    }
                )
        last = messages[-1]
        reply = _content_to_text(getattr(last, "content", "")).strip()

    reply, guardrail = apply_evidence_guardrail(message, reply, tool_evidence)
    _record_agent_trace(
        tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=planner,
        execution_plan=execution_plan, tool_evidence=tool_evidence,
        guardrail=guardrail, outcome="completed",
    )

    title = _auto_title(message) if is_new else None
    meta = _upsert_conversation(tenant_id, conv_id, title=title)
    evidence = build_evidence_ledger(tool_evidence, permission_codes=permission_codes)
    presentation_evidence = build_evidence_ledger(
        tool_evidence, permission_codes=permission_codes, include_internal_refs=True,
    )
    ui_messages = _serialize_ui_messages(
        list(messages or []), permission_codes=permission_codes
    )
    if ui_messages:
        try:
            _save_ui_messages(tenant_id, conv_id, ui_messages)
        except Exception:
            pass

    return {
        "conversation_id": conv_id,
        "run_id": run_id,
        "title": meta["title"],
        "reply": reply or "（无文本回复，请查看工具结果或重试）",
        "tool_traces": tool_traces[-8:],
        "semantic_plan": planner.model_dump(),
        "evidence_guardrail": guardrail,
        "evidence": evidence,
        "presentation": build_response_presentation(message, presentation_evidence, tenant_id=tenant_id),
        "lifecycle_agents": lifecycle_agents.public_profiles(profiles),
        "child_plans": [plan.model_dump() for plan in child_plans],
        "child_results": [result.model_dump() for result in child_results],
        "model": get_settings().deepseek_model,
        "messages": ui_messages,
    }


def _sse_pack(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _weekly_brief_reply(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Render the existing deterministic weekly aggregate without an LLM round-trip."""
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    insights = [str(item.get("text") or "") for item in data.get("insights") or [] if item.get("text")][:4]
    actions = ((data.get("sections") or {}).get("today_actions") or {}).get("data", {}).get("top3", [])
    todos = [_classify_action(str(action.get("title") or "")) for action in actions if action.get("title")][:3]
    parts = [f"**{data.get('summary') or '本周关键指标平稳。'}**"]
    if insights:
        parts.append("重点：\n" + "\n".join(f"- {item}" for item in insights))
    return "\n\n".join(parts), todos


def _agent_activity(profiles: list[lifecycle_agents.LifecycleAgentProfile], question: str, status: str) -> list[dict[str, str]]:
    """Public, user-facing status only; no chain-of-thought or raw tool payloads."""
    subject = re.sub(r"\s+", " ", question or "").strip()
    if len(subject) > 52:
        subject = f"{subject[:51]}…"
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "task": f"正在处理：{subject}" if status == "running" else f"等待总军师委派：{subject}" if status == "pending" else f"已完成核对：{subject}",
            "status": status,
        }
        for profile in profiles
    ]


def iter_chat_sse(
    tenant_id: int,
    message: str,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
):
    """SSE 事件流：阶段、证据、待办与最终回答。"""
    status = agent_available()
    if not status["enabled"]:
        yield _sse_pack({"type": "error", "message": status["reason"] or "agent_disabled"})
        return

    message = (message or "").strip()
    if not message:
        yield _sse_pack({"type": "error", "message": "empty_message"})
        return
    profiles = lifecycle_agents.select_profiles(message)
    display_profiles = list(profiles)

    is_new = not (conversation_id or "").strip()
    conv_id = (conversation_id or "").strip() or uuid.uuid4().hex
    thread_id = _thread_id(tenant_id, conv_id)
    run_id, run_config = _agent_run_config(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        thread_id=thread_id,
        transport="sse",
    )
    title = _auto_title(message) if is_new else None
    # 先落目录，流式过程中前端就能绑定 conversation_id
    meta = _upsert_conversation(tenant_id, conv_id, title=title)
    model_name = get_settings().deepseek_model

    yield _sse_pack(
        {
            "type": "meta",
            "conversation_id": conv_id,
            "run_id": run_id,
            "title": meta["title"],
            "model": model_name,
            "lifecycle_agents": lifecycle_agents.public_profiles(profiles),
        }
    )
    # Weekly brief is a fixed business report, not an open-ended research task.
    # Use the existing rule aggregate so it does not incur several model rounds.
    if _WEEKLY_BRIEF_RE.search(message):
        yield _sse_pack({"type": "agent_stage", "status": "running", "label": "总军师正在汇总本周规则诊断"})
        with SessionLocal() as report_db:
            report = workshop_metrics.query_metric(
                report_db, tenant_id, "analytics.weekly_brief", params={}, permission_codes=permission_codes,
            )
        if report.get("error"):
            yield _sse_pack({"type": "error", "message": str(report.get("message") or "周简报查询失败")})
            return
        reply, todos = _weekly_brief_reply(report)
        evidence = build_evidence_ledger(
            [{"name": "query_metric", "content": json.dumps(report, ensure_ascii=False, default=str)}],
            permission_codes=permission_codes,
        )
        yield _sse_pack({"type": "evidence", "items": evidence})
        yield _sse_pack({"type": "todo", "items": todos})
        yield _sse_pack({"type": "agent_stage", "status": "done", "label": "总军师已完成本周经营简报"})
        for chunk in _stream_safe_reply(reply):
            yield _sse_pack({"type": "token", "text": chunk})
        _record_agent_trace(
            tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=None,
            execution_plan=None, tool_evidence=[{"name": "query_metric", "content": json.dumps(report, ensure_ascii=False, default=str)}],
            guardrail=None, outcome="weekly_brief_rule_aggregate",
        )
        yield _sse_pack({
            "type": "done", "conversation_id": conv_id, "run_id": run_id, "title": meta["title"],
            "reply": reply, "tool_traces": [{"name": "query_metric", "content": "已生成车间周简报"}],
            "evidence": evidence, "todos": todos, "charts": [], "model": model_name,
        })
        return
    role_names = "、".join(p.name for p in profiles) or "综合分析"
    yield _sse_pack({"type": "agent_stage", "status": "running", "label": "总军师正在拆解问题与安排协作"})
    if profiles:
        # 这些是可被 DeepAgents task 工具实际调度的子军师；先显示等待委派，
        # 后续 task 调用/回传时会更新为处理中或已完成。
        yield _sse_pack({"type": "agent_activity", "items": _agent_activity(profiles, message, "pending")})
    yield _sse_pack({"type": "agent_stage", "status": "running", "label": f"总军师正在协调：{role_names}"})

    preflight_traces, preflight_evidence, preflight_charts, preflight_context, planner, execution_plan = _run_auto_diagnostic_bundle(
        tenant_id, message, conversation_id=conv_id, permission_codes=permission_codes, profiles=profiles
    )
    _attach_plan_trace_metadata(run_config, planner, execution_plan)
    resolved_profiles = agent_orchestration.select_roles(message, planner.plan)
    profiles = resolved_profiles if len(resolved_profiles) >= 2 else display_profiles
    child_plans = agent_orchestration.build_child_plans(message, planner.plan)
    if not child_plans and len(profiles) >= 2:
        parent = (planner.plan or analysis_plans.SemanticPlan(analysis_type="decision")).model_dump(mode="json")
        child_plans = [
            agent_orchestration.ChildPlan(
                child_plan_id=f"cp_{uuid.uuid4().hex[:16]}", lifecycle_role=profile.id,
                analysis_type=str(parent["analysis_type"]), allowed_metric_ids=list(profile.metric_ids),
                parent_semantic_plan=parent,
            )
            for profile in profiles
        ]
    agent_states = {item["id"]: item for item in _agent_activity(profiles, message, "pending")}
    if child_plans:
        child_role_ids = {plan.lifecycle_role for plan in child_plans}
        for role_id in child_role_ids:
            if role_id in agent_states:
                agent_states[role_id] = {
                    **agent_states[role_id], "status": "running",
                    "last_update": "正在调用本岗位的只读分析工具",
                }
        yield _sse_pack({"type": "agent_activity", "items": list(agent_states.values())})
        yield _sse_pack({"type": "agent_stage", "status": "running", "label": "总军师正在启动各岗位子任务"})
    # Each isolated specialist query gets its own DB session and runs in
    # parallel.  Yield after *each* future completes so the UI removes only
    # that finished worker, rather than making all cards disappear at once.
    child_results: list[agent_orchestration.ChildResult] = []
    if child_plans:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=min(3, len(child_plans))) as pool:
            futures = [
                pool.submit(
                    _execute_child_plans, tenant_id, [child_plan], permission_codes=permission_codes,
                )
                for child_plan in child_plans
            ]
            for future in as_completed(futures):
                results = future.result()
                child_results.extend(results)
                for result in results:
                    role_id = result.lifecycle_role
                    if role_id in agent_states:
                        summary = "；".join(result.evidence_summary[:2]) or "已完成业务核对，等待总军师汇总"
                        agent_states[role_id] = {
                            **agent_states[role_id], "status": "done", "last_update": summary[:220],
                        }
                yield _sse_pack({"type": "agent_activity", "items": list(agent_states.values())})
        yield _sse_pack({"type": "agent_stage", "status": "running", "label": "总军师正在汇总各岗位子任务结果"})
    task_calls: dict[str, str] = {}
    yield _sse_pack({
        "type": "orchestration",
        "lifecycle_agents": lifecycle_agents.public_profiles(profiles),
        "child_plans": [plan.model_dump() for plan in child_plans],
        "child_results": [result.model_dump() for result in child_results],
    })
    if planner.missing_slots:
        reply = _missing_slots_reply(planner.missing_slots)
        _record_agent_trace(
            tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=planner,
            execution_plan=execution_plan, tool_evidence=preflight_evidence,
            guardrail=None, outcome="missing_slots",
        )
        yield _sse_pack({
            "type": "missing_slots", "semantic_plan_id": planner.semantic_plan_id,
            "missing_slots": planner.missing_slots, "message": reply,
        })
        yield _sse_pack({
            "type": "done", "conversation_id": conv_id, "run_id": run_id, "title": meta["title"],
            "reply": reply, "tool_traces": preflight_traces[-8:], "semantic_plan": planner.model_dump(),
            "missing_slots": planner.missing_slots, "evidence": [], "todos": [], "charts": [],
            "model": model_name, "child_plans": [plan.model_dump() for plan in child_plans],
        })
        return
    if preflight_traces:
        yield _sse_pack({"type": "agent_stage", "status": "running", "label": "正在自动补齐回款与应收数据"})
        for trace, item in zip(preflight_traces, preflight_evidence):
            yield _sse_pack({"type": "tool", **trace})
            cards = build_evidence_ledger([item], permission_codes=permission_codes)
            if cards:
                yield _sse_pack({"type": "evidence", "items": cards})
        yield _sse_pack({"type": "agent_stage", "status": "done", "label": "回款、应收与经营数据已补齐"})
    if planner.missing_slots:
        yield _sse_pack({
            "type": "missing_slots", "semantic_plan_id": planner.semantic_plan_id,
            "missing_slots": planner.missing_slots,
        })

    session_lock = _conversation_lock(tenant_id, conv_id)
    acquired = session_lock.__enter__()
    if not acquired:
        session_lock.__exit__(None, None, None)
        yield _sse_pack({"type": "error", "message": "军师忙碌，请稍后再试"})
        return

    reply_parts: list[str] = []
    tool_traces: list[dict[str, Any]] = list(preflight_traces)
    child_evidence = [{"name": "child_agent", "content": json.dumps(result.model_dump(), ensure_ascii=False)} for result in child_results]
    tool_evidence: list[dict[str, Any]] = [*preflight_evidence, *child_evidence]
    charts: list[dict[str, Any]] = list(preflight_charts)
    try:
        agent = _build_agent(
            tenant_id, conversation_id=conv_id, permission_codes=permission_codes, profiles=profiles
        )
        agent_messages: list[dict[str, str]] = [{"role": "user", "content": message}]
        if preflight_context:
            agent_messages.insert(0, {"role": "system", "content": preflight_context})
        child_context = _child_results_context(child_results)
        if child_context:
            agent_messages.insert(0, {"role": "system", "content": child_context})
        for item in agent.stream(
            {"messages": agent_messages},
            config=run_config,
            stream_mode="messages",
        ):
            msg = item[0] if isinstance(item, tuple) and len(item) >= 1 else item
            mtype = getattr(msg, "type", None) or msg.__class__.__name__
            name = getattr(msg, "name", None)

            # DeepAgents exposes delegation as native `task` tool calls.  These
            # events deliberately show only the delegated business task and
            # final specialist summary, never hidden reasoning or raw data.
            for call in getattr(msg, "tool_calls", None) or []:
                if not isinstance(call, dict) or call.get("name") != "task":
                    continue
                args = call.get("args") or {}
                role_id = str(args.get("subagent_type") or args.get("name") or "")
                if role_id not in agent_states:
                    continue
                task_calls[str(call.get("id") or "")] = role_id
                task = str(args.get("description") or args.get("task") or agent_states[role_id]["task"])
                agent_states[role_id] = {
                    **agent_states[role_id], "status": "running", "task": task[:180],
                    "last_update": "已接受总军师委派，正在核对业务数据",
                }
                yield _sse_pack({
                    "type": "agent_stage", "status": "running",
                    "label": f"总军师正在委派：{agent_states[role_id]['name']}"
                })
                yield _sse_pack({"type": "agent_activity", "items": list(agent_states.values())})

            if mtype in ("tool", "ToolMessage"):
                content = _content_to_text(getattr(msg, "content", ""))
                if str(name or "") == "task":
                    role_id = task_calls.get(str(getattr(msg, "tool_call_id", "") or ""))
                    if role_id and role_id in agent_states:
                        summary = re.sub(r"\s+", " ", content).strip()[:220]
                        agent_states[role_id] = {
                            **agent_states[role_id], "status": "done",
                            "last_update": summary or "子军师已完成业务核对",
                        }
                        yield _sse_pack({
                            "type": "agent_stage", "status": "running",
                            "label": f"总军师正在汇总：{agent_states[role_id]['name']}的核对结果"
                        })
                        yield _sse_pack({"type": "agent_activity", "items": list(agent_states.values())})
                trace = {
                    "name": name,
                    "content": content[:800],
                }
                tool_traces.append(trace)
                tool_evidence.append({"name": name, "content": content})
                yield _sse_pack({"type": "tool", **trace})
                cards = build_evidence_ledger(
                    [{"name": name, "content": content}], permission_codes=permission_codes
                )
                if cards:
                    yield _sse_pack({"type": "evidence", "items": cards})
                yield _sse_pack({
                    "type": "agent_stage",
                    "status": "done",
                    "label": f"总军师{_TOOL_STAGE_LABELS.get(str(name or ""), "已完成业务核对")}",
                })
                for c in workshop_metrics.extract_charts(content):
                    charts.append(c)
                continue

            # 流式 token：仅 AIMessageChunk，避免完整 AIMessage 回放重复
            cls_name = msg.__class__.__name__
            if cls_name != "AIMessageChunk" and mtype != "AIMessageChunk":
                continue
            text = _content_to_text(getattr(msg, "content", ""))
            if not text:
                continue
            reply_parts.append(text)

        reply = "".join(reply_parts).strip()
        if not reply:
            # 回退读 checkpoint 最终消息
            try:
                detail = get_conversation_messages(
                    tenant_id, conv_id, permission_codes=permission_codes
                )
                msgs = detail.get("messages") or []
                for m in reversed(msgs):
                    if m.get("role") == "assistant" and (m.get("content") or "").strip():
                        reply = str(m["content"]).strip()
                        if not charts and m.get("charts"):
                            charts = list(m.get("charts") or [])
                        break
            except Exception:
                pass
        if not reply:
            reply = "（无文本回复，请查看工具结果或重试）"
        raw_reply = reply
        reply, guardrail = apply_evidence_guardrail(message, reply, tool_evidence)
        _record_agent_trace(
            tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=planner,
            execution_plan=execution_plan, tool_evidence=tool_evidence,
            guardrail=guardrail, outcome="completed",
        )
        evidence = build_evidence_ledger(tool_evidence, permission_codes=permission_codes)
        charts = select_response_charts(message, charts)
        summary = build_decision_summary(message, reply, evidence)
        presentation = build_response_presentation(
            message,
            build_evidence_ledger(tool_evidence, permission_codes=permission_codes, include_internal_refs=True),
            tenant_id=tenant_id,
        )
        summary_reason = summary.reason or "；".join(summary.facts[:2])
        summary_text = "\n\n".join(
            part for part in [
                f"**{summary.decision}**",
                summary_reason,
            ] if part
        )
        reply, summary_guardrail = apply_evidence_guardrail(message, summary_text, tool_evidence)
        todos = [action.model_dump() for action in summary.actions[:3]]
        yield _sse_pack({"type": "summary", "summary": summary.model_dump()})
        if presentation:
            yield _sse_pack({"type": "presentation", "presentation": presentation})
        if todos:
            yield _sse_pack({"type": "todo", "items": todos})
        yield _sse_pack({"type": "agent_stage", "status": "done", "label": "证据校验完成，正在生成结论"})
        # Do not release unverified tokens before the final evidence check.
        if reply:
            for chunk in _stream_safe_reply(reply):
                yield _sse_pack({"type": "token", "text": chunk})
        for chart in charts:
            yield _sse_pack({"type": "chart", "chart": chart})

        _upsert_conversation(tenant_id, conv_id, title=None)
        try:
            _refresh_ui_message_cache(
                tenant_id, conv_id, permission_codes=permission_codes
            )
        except Exception:
            pass
        yield _sse_pack(
            {
                "type": "done",
                "conversation_id": conv_id,
                "run_id": run_id,
                "title": meta["title"],
                "reply": reply,
                "tool_traces": tool_traces[-8:],
                "semantic_plan": planner.model_dump(),
                "evidence_guardrail": guardrail,
                "summary_guardrail": summary_guardrail,
                "presentation": presentation,
                "evidence": evidence,
                "todos": todos,
                "detail": {"available": bool(raw_reply), "content": raw_reply},
                "lifecycle_agents": lifecycle_agents.public_profiles(profiles),
                "child_plans": [plan.model_dump() for plan in child_plans],
                "child_results": [result.model_dump() for result in child_results],
                "charts": charts[-6:],
                "model": model_name,
            }
        )
    except Exception as e:
        _record_agent_trace(
            tenant_id=tenant_id, conversation_id=conv_id, run_id=run_id, planner=planner,
            execution_plan=execution_plan, tool_evidence=tool_evidence,
            guardrail=None, outcome="error",
        )
        yield _sse_pack({"type": "error", "message": f"agent_error: {e}"})
    finally:
        session_lock.__exit__(None, None, None)
