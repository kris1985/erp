"""Ranking + metric_snapshot Fast Path 接入层（DoD #9 / metric_snapshot 切片）。

在可信链（PR #1-7，app/runtime/）完成后，把 ranking / metric_snapshot 查询
从「主 Agent → 工具 → LLM 总结」切换为确定性链路：

    plan_question(...) → Request → Resolver → Router
      → 执行(profit_report) → EvidenceEnvelope → FactBuilder
      → CalculationEngine + 独立重算 → AssertionBuilder + BusinessRule
      → StructuralValidator + ContractChecker → DeterministicRenderer

发布纪律（slice §5.1）：开关 agent_fast_path_enabled=False 时只产出观测性
RouteDecision（随响应返回、进 Trace），流量仍走现有 Agent 路径；可信链与
Replay 全部通过后才允许开启开关灰度。

本模块只 import app.runtime 与现有执行层（workshop_metrics / finance_service /
analysis_result_store / analysis_plans），不触碰 DeepAgents/LangGraph。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import (
    analysis_plans,
    analysis_result_store,
    finance_service,
    semantic_compiler,
    workshop_metrics,
)
from app.services.agent_tracing import fast_path_traced
from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import (
    CalculationEngine,
    IndependentCalculationValidator,
)
from app.runtime.contract_checker import ContractChecker
from app.runtime.contracts import (
    AnswerContract,
    Coverage,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    ResolvedSemanticPlan,
    SnapshotValue,
    TimeScope,
    TypedAnalysisResult,
    ranking_answer_contract,
    snapshot_answer_contract,
)
from app.runtime.fact_builder import RankingFactBuilder, SnapshotFactBuilder
from app.runtime.metrics import collect_trust_metrics
from app.runtime.renderer import DeterministicRenderer
from app.runtime.resolver import RankingRequest, RankingResolver, SnapshotRequest, SnapshotResolver
from app.runtime.router import CapabilityRouter
from app.runtime.rules import BusinessRuleEngine
from app.runtime.spill import ResultSpiller
from app.runtime.structural_validator import StructuralValidator

RANKING_METRIC_ID = "finance.customer_sales_ranking"
RANKING_METRIC_VERSION = "1.0.0"
SNAPSHOT_METRIC_ID = "finance.sales_snapshot"
SNAPSHOT_METRIC_VERSION = "1.0.0"
LOCAL_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai fixed offset (v1)

_SHARE_RE = re.compile(r"占|集中度|占比")
_TABLE_RE = re.compile(r"表格|出表|明细表|列表")


@dataclass
class FastPathOutcome:
    status: Literal["not_applicable", "observational", "executed", "rejected"]
    response: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None
    rejection: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now(tz=LOCAL_TZ).isoformat(timespec="seconds")


def _local_now() -> datetime:
    return datetime.now(tz=LOCAL_TZ)


class RankingFastPath:
    """Deterministic ranking answer path, wired to the existing data layer."""

    def __init__(self) -> None:
        self._resolver = RankingResolver()
        self._router = CapabilityRouter()
        self._fact_builder = RankingFactBuilder()
        self._engine = CalculationEngine()
        self._calc_validator = IndependentCalculationValidator()
        self._assertions = AssertionBuilder()
        self._rules = BusinessRuleEngine()
        self._structural = StructuralValidator()
        self._contracts = ContractChecker()
        self._renderer = DeterministicRenderer()
        self._spiller = ResultSpiller()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(
        self,
        db: Session,
        *,
        tenant_id: int,
        question: str,
        conversation_id: str,
        permission_codes: list[str] | None,
    ) -> FastPathOutcome:
        planner = analysis_plans.plan_question(question)
        plan = planner.plan
        request: RankingRequest | None = None
        if plan and plan.analysis_type == "ranking" and not planner.missing_slots:
            request = self._to_request(question, plan)
        else:
            # 跨轮继承（Compiler）：turn2 追问（「只显示top3」「大于500万的」
            # 「上月呢」）由 LLM propose + 确定性校验判定，继承上轮排行上下文。
            # 正则枚举已废除；无历史/判新问题/LLM 不可用都不猜测。
            verdict = semantic_compiler.resolve_inheritance(
                question, tenant_id=tenant_id, conversation_id=conversation_id
            )
            if verdict.status == "inherited":
                request = RankingRequest(
                    metric_id=RANKING_METRIC_ID,
                    dimension="customer",
                    year=verdict.year or date.today().year,
                    as_of=_local_now(),
                    limit=verdict.limit or 10,
                    sort="desc",
                    filters={
                        **({"min_amount": verdict.min_amount} if verdict.min_amount is not None else {}),
                    },
                )
            elif verdict.status == "requires_clarification":
                return FastPathOutcome(
                    status="observational",
                    observation={"inheritance": verdict.__dict__},
                )
            elif verdict.status == "unavailable":
                # LLM propose 不可用：无法判定继承 → 明确失败，不静默掉进
                # LLM 主链假装能回答（无 LLM 时主链同样不可用）。
                return FastPathOutcome(
                    status="observational",
                    observation={
                        "inheritance": verdict.__dict__,
                        "unavailable": True,
                    },
                )
        if request is None:
            return FastPathOutcome(status="not_applicable")

        plan_result = self._resolver.resolve(request)
        enabled = bool(get_settings().agent_fast_path_enabled)

        if not isinstance(plan_result, ResolvedSemanticPlan):
            # Clarification / unsupported: never a fast-path answer.
            return FastPathOutcome(
                status="observational",
                observation={
                    "decision": self._router.route(plan_result, fast_path_enabled=enabled).model_dump(),
                    "clarification": plan_result.model_dump(),
                },
            )

        decision = self._router.route(plan_result, fast_path_enabled=enabled)
        if not decision.fast_path_active:
            # Observational mode: record the route decision, keep the agent path.
            return FastPathOutcome(
                status="observational",
                observation={"decision": decision.model_dump()},
            )

        return self._execute(db, tenant_id, question, conversation_id, permission_codes, plan_result, decision.model_dump())

    # ------------------------------------------------------------------
    # Plan shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_request(question: str, plan: analysis_plans.SemanticPlan) -> RankingRequest:
        year = (plan.time_range.year if plan.time_range else None) or date.today().year
        needs_share = bool(_SHARE_RE.search(question or ""))
        return RankingRequest(
            metric_id=RANKING_METRIC_ID,
            dimension="customer",
            year=year,
            as_of=_local_now(),
            limit=plan.limit,
            sort=plan.order or "desc",
            needs_share=needs_share,
        )

    # ------------------------------------------------------------------
    # Execution + trusted chain
    # ------------------------------------------------------------------

    def _execute(
        self,
        db: Session,
        tenant_id: int,
        question: str,
        conversation_id: str,
        permission_codes: list[str] | None,
        plan: ResolvedSemanticPlan,
        decision: dict[str, Any],
    ) -> FastPathOutcome:
        visible = {m["id"] for m in workshop_metrics.list_metrics(permission_codes=permission_codes)}
        if RANKING_METRIC_ID not in visible:
            return FastPathOutcome(
                status="rejected",
                rejection={
                    "reply": "当前账号无权限查询客户销售额排行，不能给出排行结论。",
                    "reason_code": "POLICY_DENIED",
                    "decision": decision,
                },
            )

        year = plan.scope.year if plan.scope else None
        limit = next((op.top_n for op in plan.operations if op.type == "ranking"), 10) or 10
        sort = next((op.sort for op in plan.operations if op.type == "ranking"), "desc") or "desc"
        needs_share = any(op.type == "share_of_total" for op in plan.operations)

        envelope, total_revenue = self._execute_ranking(
            db, tenant_id, year=year, limit=limit, order=sort, conversation_id=conversation_id,
            filters=dict(plan.filters or {}),
        )
        if isinstance(envelope, dict):  # execution error
            return FastPathOutcome(
                status="rejected",
                rejection={"reply": str(envelope.get("error") or "查询失败"), "decision": decision},
            )

        built = self._fact_builder.build(envelope, need_denominator=needs_share)
        if built.status != "verified":
            return FastPathOutcome(
                status="rejected",
                rejection={
                    "reply": "当前证据不足以回答该问题（缺少客户总体销售额），不能硬算整体占比或集中度。",
                    "reason_code": built.reason_code,
                    "decision": decision,
                    "evidence_refs": built.evidence_refs,
                },
            )

        facts, calculations, total_fact = self._derive(
            envelope, built.facts, needs_share, total_revenue=total_revenue
        )
        if total_fact is not None:
            facts = list(facts) + [total_fact]

        assertions = self._assertions.build(envelope=envelope, facts=facts, calculations=calculations)
        judgements = self._rules.apply_judgements(envelope=envelope, facts=facts, calculations=calculations)
        all_assertions = assertions + judgements
        verdicts = self._structural.validate(
            all_assertions, facts=facts, calculations=calculations, envelope=envelope, contract=self._contract(question)
        )
        verified = [a for a, v in zip(all_assertions, verdicts) if v.status == "verified"]
        for result in self._contracts.check(verified, self._contract(question)):
            if result.status != "verified":
                return FastPathOutcome(
                    status="rejected",
                    rejection={
                        "reply": "回答被契约校验拦截，请重新查询。",
                        "reason_code": result.reason_code,
                        "decision": decision,
                    },
                )

        # 表格卡片始终生成（可扫读），主回复用一句结论，折叠区放中文依据说明
        # （技术溯源由服务端 Trace 承担，不暴露内部标识符给用户）。
        table = self._renderer.render_table(verified, facts=facts, envelope=envelope)
        year = plan.scope.year if plan.scope else None
        limit = next((op.top_n for op in plan.operations if op.type == "ranking"), 10) or 10
        # year/limit 随 presentation 持久化：跨轮继承（Compiler）从结构化字段
        # 读取上轮上下文，不靠从回复文本抠数字。
        presentation = {
            "type": "table",
            "columns": table.columns,
            "rows": table.rows,
            "analysis_type": "ranking",
            "year": year,
            "limit": limit,
        }
        reply = self._renderer.render_summary(verified, facts=facts, envelope=envelope)
        rule_labels = self._rule_labels(all_assertions)
        detail = self._renderer.render_explanation(
            verified,
            facts=facts,
            calculations=calculations,
            envelope=envelope,
            rules=rule_labels,
        )

        trust = collect_trust_metrics(
            assertions=all_assertions,
            verified_ids=[a.assertion_id for a in verified],
            sentences=[],
            facts=facts,
        )
        self._record_trace(
            tenant_id, conversation_id, plan, envelope, calculations, decision,
            result_ids=[envelope.result_id],
            calculation_ids=[c.calculation_id for c in calculations],
            outcome="fast_path_ranking",
        )
        return FastPathOutcome(
            status="executed",
            response={
                "conversation_id": conversation_id,
                "run_id": f"fp_{uuid.uuid4().hex[:16]}",
                "title": None,
                "reply": reply,
                "fast_path": {**decision, "active": True, "result_id": envelope.result_id},
                "assertion_ids": sorted(a.assertion_id for a in verified),
                "semantic_plan": plan.model_dump(mode="json"),
                "presentation": presentation,
                "detail": {"available": True, "kind": "deterministic", "content": detail},
                "trust_metrics": trust.model_dump(mode="json"),
                "lifecycle_agents": [],
                "child_plans": [],
                "messages": [],
            },
        )

    # ------------------------------------------------------------------
    # Derivation chain
    # ------------------------------------------------------------------

    def _derive(
        self,
        envelope: EvidenceEnvelope,
        metric_facts: list[Fact],
        needs_share: bool,
        *,
        total_revenue: Decimal,
    ):
        """Build topn_total + share_of_total when the plan needs them,
        verifying each derived fact independently before it may proceed.
        The denominator is the population total from the execution layer —
        never a sum of the truncated top-N rows."""
        if not needs_share:
            return metric_facts, [], None
        top_n = len(envelope.payload.rows)
        numerator_inputs = metric_facts[:top_n]
        total_fact = Fact(
            fact_id=f"{envelope.result_id}:total",
            type="metric_fact",
            name="客户销售额",
            value=total_revenue,
            unit="CNY",
            scope=envelope.scope,
            source="metric_engine",
            evidence_refs=[envelope.result_id],
        )
        calc1, topn_fact = self._engine.compute(
            "topn_total",
            numerator_inputs,
            calculation_id=f"c_{envelope.result_id}_topn",
            output_fact_id=f"{envelope.result_id}:topn_total",
        )
        calc2, share_fact = self._engine.compute(
            "share_of_total",
            [topn_fact, total_fact],
            calculation_id=f"c_{envelope.result_id}_share",
            output_fact_id=f"{envelope.result_id}:share",
        )
        # Independent recomputation must pass before any assertion is built.
        assert self._calc_validator.verify(calc1, numerator_inputs, topn_fact).status == "verified"
        assert self._calc_validator.verify(calc2, [topn_fact, total_fact], share_fact).status == "verified"
        return metric_facts + [topn_fact, share_fact], [calc1, calc2], total_fact

    # ------------------------------------------------------------------
    # Data execution (existing metric + denominator)
    # ------------------------------------------------------------------

    def _execute_ranking(
        self,
        db: Session,
        tenant_id: int,
        *,
        year: int | None,
        limit: int,
        order: str,
        conversation_id: str,
        filters: dict | None = None,
    ) -> tuple[EvidenceEnvelope, Decimal] | dict[str, Any]:
        filters = filters or {}
        report = finance_service.profit_report(db, tenant_id, year=year)
        totals: dict[str, Decimal] = {}
        for row in report.get("orders") or []:
            name = str(row.get("customer_name") or "未知客户")
            totals[name] = totals.get(name, Decimal("0")) + Decimal(str(row.get("revenue") or 0))
        min_amount = Decimal(str(filters.get("min_amount") or 0))
        if min_amount > 0:
            totals = {name: value for name, value in totals.items() if value > min_amount}
        all_customers = len(totals)
        items = sorted(totals.items(), key=lambda kv: kv[1], reverse=(order != "asc"))[:limit]
        population_complete = all_customers <= limit
        rows = [
            {
                "entity_id": name,
                "entity_label": name,
                "value": value,
                "unit": "CNY",
                "rank": index,
            }
            for index, (name, value) in enumerate(items, start=1)
        ]
        summary = report.get("summary") or {}
        total_revenue = Decimal(str(summary.get("revenue") or 0))
        result_id = analysis_result_store.put_result(
            tenant_id,
            RANKING_METRIC_ID,
            {"year": year, "limit": limit, "order": order, "items": [
                {"customer_name": name, "sales_amount": str(value)} for name, value in items
            ]},
            {"year": year, "limit": limit, "order": order},
            session_id=conversation_id,
        )
        envelope_filters: dict[str, Any] = {"year": year, "limit": limit, "order": order}
        if min_amount > 0:
            envelope_filters["min_amount"] = str(min_amount)
        return (
            EvidenceEnvelope(
                result_id=result_id,
                metric=MetricRef(metric_id=RANKING_METRIC_ID, definition_version=RANKING_METRIC_VERSION),
                scope=TimeScope(year=year),
                dimension="customer",
                operation="ranking",
                coverage=Coverage(
                    type="complete_population" if population_complete else "top_n",
                    requested=limit,
                    returned=len(rows),
                    population_complete=population_complete,
                    population_size=all_customers,
                    denominator_available=total_revenue > 0,
                ),
                freshness=Freshness(queried_at=_local_now()),
                authority="metric_engine",
                filters=envelope_filters,
                payload=TypedAnalysisResult(result_type="ranking", rows=rows, execution_ref=f"exec_{result_id}"),
            ),
            total_revenue,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _contract(question: str) -> AnswerContract:
        wants_table = bool(_TABLE_RE.search(question or ""))
        return ranking_answer_contract(presentation_mode="table" if wants_table else "sentence")

    @staticmethod
    def _rule_labels(assertions: list) -> dict[str, tuple[str, str]]:
        """rule_ref -> (判断文案, 阈值)，供前端中文依据展示。"""
        from app.runtime.rules import RuleRegistry

        registry = RuleRegistry()
        labels: dict[str, tuple[str, str]] = {}
        for assertion in assertions:
            if not assertion.rule_ref:
                continue
            rule = registry.get(assertion.rule_ref)
            if rule is not None:
                labels[assertion.rule_ref] = (rule.output_judgement, str(rule.threshold))
        return labels

    @staticmethod
    def _record_trace(
        tenant_id: int,
        conversation_id: str,
        plan: ResolvedSemanticPlan,
        envelope: EvidenceEnvelope,
        calculations: list,
        decision: dict[str, Any],
        *,
        result_ids: list[str],
        calculation_ids: list[str],
        outcome: str,
    ) -> None:
        from app.services.agent_trace_service import record_run

        record_run(
            run_id=f"fp_{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            semantic_plan_id=plan.semantic_plan_id,
            execution_plan_id=plan.semantic_plan_id,
            match_passed=True,
            result_ids=result_ids,
            calculation_ids=calculation_ids,
            approval_ids=[],
            approval_statuses=[],
            versions={
                "runtime_contract": "1.0.0",
                "route_rule": decision.get("rule_id") or "",
                "renderer": "deterministic-v1",
                "prompt": "fast-path",
            },
            outcome=outcome,
        )


class MetricSnapshotFastPath:
    """Deterministic metric_snapshot answer path (Direct Metric, §4.1 next slice).

    Answers single-value questions like “本月销售额多少”: one scalar from
    profit_report's summary.revenue, through the same trusted chain as the
    ranking path — CoverageGate -> SnapshotFactBuilder -> AssertionBuilder ->
    StructuralValidator + ContractChecker -> DeterministicRenderer.
    """

    def __init__(self) -> None:
        self._resolver = SnapshotResolver()
        self._router = CapabilityRouter()
        self._fact_builder = SnapshotFactBuilder()
        self._assertions = AssertionBuilder()
        self._structural = StructuralValidator()
        self._contracts = ContractChecker()
        self._renderer = DeterministicRenderer()
        self._spiller = ResultSpiller()

    def run(
        self,
        db: Session,
        *,
        tenant_id: int,
        question: str,
        conversation_id: str,
        permission_codes: list[str] | None,
    ) -> FastPathOutcome:
        planner = analysis_plans.plan_question(question)
        plan = planner.plan
        request: SnapshotRequest | None = None
        if plan and plan.analysis_type == "metric_snapshot" and plan.metric == "sales_snapshot" and not planner.missing_slots:
            request = self._to_request(question, plan)
        else:
            # 期间切换追问（如「上月呢」）：继承上轮快照轮次并切换期间。
            request = self._detect_period_followup(
                question, tenant_id=tenant_id, conversation_id=conversation_id
            )
        if request is None:
            return FastPathOutcome(status="not_applicable")

        plan_result = self._resolver.resolve(request)
        enabled = bool(get_settings().agent_fast_path_enabled)

        if not isinstance(plan_result, ResolvedSemanticPlan):
            return FastPathOutcome(
                status="observational",
                observation={
                    "decision": self._router.route(plan_result, fast_path_enabled=enabled).model_dump(),
                    "clarification": plan_result.model_dump(),
                },
            )

        decision = self._router.route(plan_result, fast_path_enabled=enabled)
        if not decision.fast_path_active:
            return FastPathOutcome(
                status="observational",
                observation={"decision": decision.model_dump()},
            )

        return self._execute(db, tenant_id, question, conversation_id, permission_codes, plan_result, decision.model_dump())

    # ------------------------------------------------------------------
    # Plan shaping + period-switch follow-up
    # ------------------------------------------------------------------

    @staticmethod
    def _to_request(question: str, plan: analysis_plans.SemanticPlan) -> SnapshotRequest:
        tr = plan.time_range
        return SnapshotRequest(
            metric_id=SNAPSHOT_METRIC_ID,
            year=tr.year if tr else None,
            month=tr.month if tr else None,
            as_of=_local_now(),
        )

    def _detect_period_followup(
        self,
        question: str,
        *,
        tenant_id: int,
        conversation_id: str,
    ) -> SnapshotRequest | None:
        """「上月呢」「去年呢」这类省略主语的期间切换追问：仅当会话历史中有
        Fast Path 快照轮次时才继承（同主题扩展，contracts §3.6），否则交给
        LLM 路径。返回继承上轮期间并切换后的 SnapshotRequest。"""
        text = question or ""
        if not re.search(r"呢|上月|上个月|去年|今年|这个月|本月", text):
            return None
        if not re.search(r"^(?:那|这)?(?:上月|上个月|去年|今年|这个月|本月|上一个月).{0,4}$", text):
            return None
        inherited = self._inherited_period(tenant_id, conversation_id)
        if inherited is None:
            return None  # 无快照上下文，不猜测
        year, month = self._switch_period(text, *inherited)
        return SnapshotRequest(
            metric_id=SNAPSHOT_METRIC_ID,
            year=year,
            month=month,
            as_of=_local_now(),
        )

    @staticmethod
    def _switch_period(text: str, year: int, month: int | None) -> tuple[int, int | None]:
        """按追问词切换期间：上月 → 上一个月（跨年回绕）；去年 → 前一年；
        今年/本月/这个月 → 当前自然月；否则保持。"""
        if re.search(r"上月|上个月", text):
            if month is None:
                return year, month
            if month == 1:
                return year - 1, 12
            return year, month - 1
        if re.search(r"去年", text):
            return year - 1, month
        if re.search(r"今年", text):
            return date.today().year, None
        if re.search(r"本月|这个月", text):
            today = date.today()
            return today.year, today.month
        return year, month

    @staticmethod
    def _inherited_period(tenant_id: int, conversation_id: str) -> tuple[int, int | None] | None:
        """从 ui_messages 最后一条 fast_path 快照回复解析期间；无快照上下文
        返回 None。只读短连接，不触碰 schedule_agent 的共享连接。"""
        try:
            import sqlite3
            from pathlib import Path

            path = Path(get_settings().schedule_agent_data_dir) / "conversations.sqlite"
            conn = sqlite3.connect(str(path))
            try:
                row = conn.execute(
                    "SELECT ui_messages FROM conversations WHERE id=? AND tenant_id=?",
                    (conversation_id, tenant_id),
                ).fetchone()
            finally:
                conn.close()
            if not row or not row[0]:
                return None
            messages = json.loads(row[0])
            for message in reversed(messages):
                if message.get("role") == "assistant" and message.get("path") == "fast_path":
                    content = str(message.get("content") or "")
                    year_match = re.search(r"(20\d{2})\s*年", content)
                    if year_match:
                        year = int(year_match.group(1))
                        month_match = re.search(r"年\s*(\d{1,2})\s*月", content)
                        return year, (int(month_match.group(1)) if month_match else None)
                    return date.today().year, date.today().month  # 有快照轮次但无期间 → 当前月
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # Execution + trusted chain
    # ------------------------------------------------------------------

    def _execute(
        self,
        db: Session,
        tenant_id: int,
        question: str,
        conversation_id: str,
        permission_codes: list[str] | None,
        plan: ResolvedSemanticPlan,
        decision: dict[str, Any],
    ) -> FastPathOutcome:
        visible = {m["id"] for m in workshop_metrics.list_metrics(permission_codes=permission_codes)}
        if SNAPSHOT_METRIC_ID not in visible:
            return FastPathOutcome(
                status="rejected",
                rejection={
                    "reply": "当前账号无权限查询销售额，不能给出销售额结论。",
                    "reason_code": "POLICY_DENIED",
                    "decision": decision,
                },
            )

        year = plan.scope.year if plan.scope else None
        month = plan.scope.month if plan.scope else None
        envelope = self._execute_snapshot(
            db, tenant_id, year=year, month=month, conversation_id=conversation_id
        )
        if isinstance(envelope, dict):  # execution error
            return FastPathOutcome(
                status="rejected",
                rejection={"reply": str(envelope.get("error") or "查询失败"), "decision": decision},
            )

        built = self._fact_builder.build(envelope)
        if built.status != "verified":
            return FastPathOutcome(
                status="rejected",
                rejection={
                    "reply": "当前证据不足以回答该问题（缺少销售额数值），不能给出销售额结论。",
                    "reason_code": built.reason_code,
                    "decision": decision,
                    "evidence_refs": built.evidence_refs,
                },
            )

        assertions = self._assertions.build(envelope=envelope, facts=built.facts, calculations=[])
        all_assertions = assertions
        verdicts = self._structural.validate(
            all_assertions, facts=built.facts, calculations=[], envelope=envelope, contract=self._contract(question)
        )
        verified = [a for a, v in zip(all_assertions, verdicts) if v.status == "verified"]
        for result in self._contracts.check(verified, self._contract(question)):
            if result.status != "verified":
                return FastPathOutcome(
                    status="rejected",
                    rejection={
                        "reply": "回答被契约校验拦截，请重新查询。",
                        "reason_code": result.reason_code,
                        "decision": decision,
                    },
                )

        # 表格卡片始终生成（可扫读），主回复用一句结论，折叠区放中文依据说明。
        table = self._renderer.render_table(verified, facts=built.facts, envelope=envelope)
        year = plan.scope.year if plan.scope else None
        month = plan.scope.month if plan.scope else None
        title = f"{year} 年" + (f" {month} 月" if month else "") + "销售额"
        # analysis_type 随 presentation 持久化：跨轮继承据此区分轮次类型。
        presentation = {
            "type": "table",
            "title": title,
            "columns": table.columns,
            "rows": table.rows,
            "analysis_type": "metric_snapshot",
            "year": year,
            "month": month,
        }
        reply = self._renderer.render_summary(verified, facts=built.facts, envelope=envelope)
        detail = self._renderer.render_explanation(
            verified,
            facts=built.facts,
            calculations=[],
            envelope=envelope,
            rules={},
        )

        trust = collect_trust_metrics(
            assertions=all_assertions,
            verified_ids=[a.assertion_id for a in verified],
            sentences=[],
            facts=built.facts,
        )
        RankingFastPath._record_trace(
            tenant_id, conversation_id, plan, envelope, [], decision,
            result_ids=[envelope.result_id],
            calculation_ids=[],
            outcome="fast_path_metric_snapshot",
        )
        return FastPathOutcome(
            status="executed",
            response={
                "conversation_id": conversation_id,
                "run_id": f"fp_{uuid.uuid4().hex[:16]}",
                "title": None,
                "reply": reply,
                "fast_path": {**decision, "active": True, "result_id": envelope.result_id},
                "assertion_ids": sorted(a.assertion_id for a in verified),
                "semantic_plan": plan.model_dump(mode="json"),
                "presentation": presentation,
                "detail": {"available": True, "kind": "deterministic", "content": detail},
                "trust_metrics": trust.model_dump(mode="json"),
                "lifecycle_agents": [],
                "child_plans": [],
                "messages": [],
            },
        )

    # ------------------------------------------------------------------
    # Data execution (existing metric + snapshot value)
    # ------------------------------------------------------------------

    def _execute_snapshot(
        self,
        db: Session,
        tenant_id: int,
        *,
        year: int | None,
        month: int | None,
        conversation_id: str,
    ) -> EvidenceEnvelope | dict[str, Any]:
        try:
            report = finance_service.profit_report(db, tenant_id, year=year, month=month)
        except Exception as exc:  # pragma: no cover - defensive
            return {"error": f"销售额查询失败：{exc}"}
        summary = report.get("summary") or {}
        revenue = Decimal(str(summary.get("revenue") or 0))
        result_id = analysis_result_store.put_result(
            tenant_id,
            SNAPSHOT_METRIC_ID,
            {"year": year, "month": month, "revenue": str(revenue)},
            {"year": year, "month": month},
            session_id=conversation_id,
        )
        return EvidenceEnvelope(
            result_id=result_id,
            metric=MetricRef(metric_id=SNAPSHOT_METRIC_ID, definition_version=SNAPSHOT_METRIC_VERSION),
            scope=TimeScope(year=year, month=month),
            dimension="",
            operation="metric_snapshot",
            coverage=Coverage(
                type="complete_population",
                population_complete=True,
                population_size=1,
                denominator_available=revenue > 0,
            ),
            freshness=Freshness(queried_at=_local_now()),
            authority="metric_engine",
            filters={"year": year, "month": month},
            payload=TypedAnalysisResult(
                result_type="metric_snapshot",
                snapshot_value=SnapshotValue(value=revenue, unit="CNY"),
                execution_ref=f"exec_{result_id}",
            ),
        )

    @staticmethod
    def _contract(question: str) -> AnswerContract:
        wants_table = bool(_TABLE_RE.search(question or ""))
        return snapshot_answer_contract(presentation_mode="table" if wants_table else "sentence")


@fast_path_traced(name="run_fast_path", tags=["fast_path"])
def run_fast_path(
    db: Session,
    *,
    tenant_id: int,
    question: str,
    conversation_id: str,
    permission_codes: list[str] | None,
) -> FastPathOutcome:
    """Dispatch to the licensed fast path for this question.

    Ranking first (existing slice), then metric_snapshot. Each path returns
    ``not_applicable`` when the question is outside its licensed scope, so the
    dispatcher falls through to the next path or to the LLM agent path.
    """
    ranking = RankingFastPath().run(
        db,
        tenant_id=tenant_id,
        question=question,
        conversation_id=conversation_id,
        permission_codes=permission_codes,
    )
    if ranking.status != "not_applicable":
        return ranking
    return MetricSnapshotFastPath().run(
        db,
        tenant_id=tenant_id,
        question=question,
        conversation_id=conversation_id,
        permission_codes=permission_codes,
    )
