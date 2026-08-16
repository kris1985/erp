"""Ranking Fast Path 接入层（DoD #9，agent-runtime 系列 PR 的落地接缝）。

在可信链（PR #1-7，app/runtime/）完成后，把 ranking 查询从
「主 Agent → 工具 → LLM 总结」切换为确定性链路：

    plan_question(ranking) → RankingRequest → Resolver → Router
      → 执行(profit_report) → EvidenceEnvelope → FactBuilder
      → CalculationEngine + 独立重算 → AssertionBuilder + BusinessRule
      → StructuralValidator + ContractChecker → DeterministicRenderer

发布纪律（slice §5.1）：开关 agent_fast_path_enabled=False 时只产出观测性
RouteDecision（随响应返回、进 Trace），流量仍走现有 Agent 路径；可信链与
12-case Replay 全部通过后才允许开启开关灰度。

本模块只 import app.runtime 与现有执行层（workshop_metrics / finance_service /
analysis_result_store / analysis_plans），不触碰 DeepAgents/LangGraph。
"""

from __future__ import annotations

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
    workshop_metrics,
)
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
    TimeScope,
    TypedAnalysisResult,
    ranking_answer_contract,
)
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.metrics import collect_trust_metrics
from app.runtime.renderer import DeterministicRenderer
from app.runtime.resolver import RankingRequest, RankingResolver
from app.runtime.router import CapabilityRouter
from app.runtime.rules import BusinessRuleEngine
from app.runtime.spill import ResultSpiller
from app.runtime.structural_validator import StructuralValidator

RANKING_METRIC_ID = "finance.customer_sales_ranking"
RANKING_METRIC_VERSION = "1.0.0"
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
        if not plan or plan.analysis_type != "ranking" or planner.missing_slots:
            return FastPathOutcome(status="not_applicable")

        request = self._to_request(question, plan)
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
            db, tenant_id, year=year, limit=limit, order=sort, conversation_id=conversation_id
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
        presentation = {"type": "table", "columns": table.columns, "rows": table.rows}
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
                "detail": {"available": True, "content": detail},
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
    ) -> tuple[EvidenceEnvelope, Decimal] | dict[str, Any]:
        report = finance_service.profit_report(db, tenant_id, year=year)
        totals: dict[str, Decimal] = {}
        for row in report.get("orders") or []:
            name = str(row.get("customer_name") or "未知客户")
            totals[name] = totals.get(name, Decimal("0")) + Decimal(str(row.get("revenue") or 0))
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
                filters={"year": year, "limit": limit, "order": order},
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


# Module-level convenience used by schedule_agent.chat().
def run_fast_path(
    db: Session,
    *,
    tenant_id: int,
    question: str,
    conversation_id: str,
    permission_codes: list[str] | None,
) -> FastPathOutcome:
    return RankingFastPath().run(
        db,
        tenant_id=tenant_id,
        question=question,
        conversation_id=conversation_id,
        permission_codes=permission_codes,
    )
