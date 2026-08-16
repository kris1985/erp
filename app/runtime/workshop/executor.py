"""DirectMetricExecutor —— query_metric_direct 的可信执行层（Tool 内部）。

安全边界：主 Agent 有决策权（生成参数），但没有绕过业务规则的权力。Tool
不信任模型生成的参数，重新执行完整链路：

    schema 重校验 → 能力注册 → 权限/租户 → 数据执行 → evidence 校验
      → 契约校验 → 确定性渲染 → DirectArtifact

v1 注册能力（与 registry 对齐）：ranking（客户销售额排行）、metric_snapshot
（销售额快照）。新指标 = 注册 executor，不新增执行范式。

本模块替代旧的 agent_fast_path 旁路执行链：输入从「语义编译 plan」变为
「模型强类型参数」，解析层更薄；可信链（fact_builder / assertions / rules /
structural / contracts / renderer）原样复用。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import CalculationEngine, IndependentCalculationValidator
from app.runtime.contract_checker import ContractChecker
from app.runtime.contracts import (
    AnswerContract,
    Coverage,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    SnapshotValue,
    TimeScope,
    TypedAnalysisResult,
    ranking_answer_contract,
    snapshot_answer_contract,
)
from app.runtime.fact_builder import RankingFactBuilder, SnapshotFactBuilder
from app.runtime.metrics import collect_trust_metrics
from app.runtime.renderer import DeterministicRenderer
from app.runtime.rules import BusinessRuleEngine
from app.runtime.spill import ResultSpiller
from app.runtime.structural_validator import StructuralValidator
from app.runtime.workshop.presentation import PresentationBuilder
from app.runtime.workshop.request import DirectMetricRequest
from app.runtime.workshop.types import DirectArtifact
from app.services.agent_tracing import fast_path_traced

RANKING_METRIC_ID = "finance.customer_sales_ranking"
RANKING_METRIC_VERSION = "1.0.0"
SNAPSHOT_METRIC_ID = "finance.sales_snapshot"
SNAPSHOT_METRIC_VERSION = "1.0.0"
LOCAL_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai fixed offset (v1)

# metric_id → 受支持的能力描述（用于参数校验与错误文案）
SUPPORTED_DIRECT_METRICS: dict[str, str] = {
    RANKING_METRIC_ID: "客户销售额排行（dimension=customer，按销售额排序）",
    SNAPSHOT_METRIC_ID: "销售额快照（单值：期间销售额）",
}

_MAX_LIMIT = 1000


def _now_iso() -> str:
    return datetime.now(tz=LOCAL_TZ).isoformat(timespec="seconds")


def _local_now() -> datetime:
    return datetime.now(tz=LOCAL_TZ)


class DirectMetricExecutor:
    """强类型指标请求 → 归一化 DirectArtifact（确定性执行 + 可信链）。"""

    def __init__(self) -> None:
        self._assertions = AssertionBuilder()
        self._rules = BusinessRuleEngine()
        self._structural = StructuralValidator()
        self._contracts = ContractChecker()
        self._renderer = DeterministicRenderer()
        self._spiller = ResultSpiller()
        self._engine = CalculationEngine()
        self._calc_validator = IndependentCalculationValidator()

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    @fast_path_traced(name="direct_metric_execute", tags=["direct", "fast_path"])
    def execute(
        self,
        db: Session,
        *,
        tenant_id: int,
        conversation_id: str,
        permission_codes: list[str] | None,
        request: DirectMetricRequest,
    ) -> DirectArtifact:
        """完整可信链入口。任何业务失败都归一化为受控 artifact，不抛异常。"""

        # 1. 能力注册（schema 已由 pydantic 校验；此处校验业务能力）
        if request.metric_id not in SUPPORTED_DIRECT_METRICS:
            return _invalid(
                status="model_argument_error",
                reply=(
                    f"当前未能形成有效查询：指标 {request.metric_id} 不支持直接查询"
                    f"（支持：{_metric_names()}）。"
                ),
                reason_code="UNSUPPORTED_DIRECT_METRIC",
            )

        # 2. 参数语义校验（区分用户没说清 vs 模型参数错误）
        bad = self._validate_parameters(request)
        if bad is not None:
            return bad

        # 3. 权限（租户隔离由执行层 tenant_id 贯穿保证）
        from app.services import workshop_metrics

        visible = {m["id"] for m in workshop_metrics.list_metrics(permission_codes=permission_codes)}
        if request.metric_id not in visible:
            return _invalid(
                status="rejected",
                reply=(
                    "当前账号无权限查询该指标，不能给出结论。"
                    if request.metric_id == RANKING_METRIC_ID
                    else "当前账号无权限查询销售额，不能给出销售额结论。"
                ),
                reason_code="POLICY_DENIED",
            )

        # 4. 执行 + 证据校验 + 渲染（各能力独立执行器）
        handler: Callable[..., DirectArtifact] = _EXECUTORS[request.metric_id]
        return handler(self, db, tenant_id, conversation_id, permission_codes, request)

    # ------------------------------------------------------------------
    # 参数语义校验
    # ------------------------------------------------------------------

    def _validate_parameters(self, request: DirectMetricRequest) -> DirectArtifact | None:
        if request.limit is not None and (request.limit < 1 or request.limit > _MAX_LIMIT):
            return _invalid(
                status="model_argument_error",
                reply=f"当前未能形成有效查询：limit 必须为 1-{_MAX_LIMIT} 的整数。",
                reason_code="INVALID_LIMIT",
            )

        if request.metric_id == RANKING_METRIC_ID:
            dimensions = [d for d in (request.dimensions or []) if d]
            if dimensions and any(d != "customer" for d in dimensions):
                return _invalid(
                    status="model_argument_error",
                    reply="当前未能形成有效查询：销售额排行暂只支持按客户（customer）排行。",
                    reason_code="UNSUPPORTED_DIMENSION",
                )
        return None

    # ------------------------------------------------------------------
    # 执行器：ranking
    # ------------------------------------------------------------------

    def _exec_ranking(
        self,
        db: Session,
        tenant_id: int,
        conversation_id: str,
        permission_codes: list[str] | None,
        request: DirectMetricRequest,
    ) -> DirectArtifact:
        from app.services import analysis_result_store, finance_service, workshop_metrics

        year = (request.time_range.year if request.time_range else None) or date.today().year
        limit = request.limit or 10
        sort = (request.order_by[0].direction if request.order_by else "desc") or "desc"
        min_amount = request.filter_value("sales_amount", "gte")
        filters: dict[str, Any] = {}
        if min_amount is not None:
            filters["min_amount"] = min_amount
        needs_share = bool(request.include_share)

        report = finance_service.profit_report(db, tenant_id, year=year)
        totals: dict[str, Decimal] = {}
        for row in report.get("orders") or []:
            name = str(row.get("customer_name") or "未知客户")
            totals[name] = totals.get(name, Decimal("0")) + Decimal(str(row.get("revenue") or 0))
        if min_amount is not None:
            totals = {name: value for name, value in totals.items() if value > Decimal(str(min_amount))}
        all_customers = len(totals)
        items = sorted(totals.items(), key=lambda kv: kv[1], reverse=(sort != "asc"))[:limit]
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
            {"year": year, "limit": limit, "order": sort, "items": [
                {"customer_name": name, "sales_amount": str(value)} for name, value in items
            ]},
            {"year": year, "limit": limit, "order": sort, **filters},
            session_id=conversation_id,
        )
        envelope_filters: dict[str, Any] = {"year": year, "limit": limit, "order": sort}
        if min_amount is not None:
            envelope_filters["min_amount"] = str(min_amount)
        envelope = EvidenceEnvelope(
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
        )

        fact_builder = RankingFactBuilder()
        built = fact_builder.build(envelope, need_denominator=needs_share)
        if built.status != "verified":
            return _invalid(
                status="rejected",
                reply="当前证据不足以回答该问题（缺少客户总体销售额），不能硬算整体占比或集中度。",
                reason_code=built.reason_code,
            )

        facts, calculations, total_fact = self._derive_ranking(
            envelope, built.facts, needs_share, total_revenue=total_revenue
        )
        if total_fact is not None:
            facts = list(facts) + [total_fact]

        assertions = self._assertions.build(envelope=envelope, facts=facts, calculations=calculations)
        judgements = self._rules.apply_judgements(envelope=envelope, facts=facts, calculations=calculations)
        all_assertions = assertions + judgements
        contract = self._contract(request)
        verdicts = self._structural.validate(
            all_assertions, facts=facts, calculations=calculations, envelope=envelope, contract=contract
        )
        verified = [a for a, v in zip(all_assertions, verdicts) if v.status == "verified"]
        for result in self._contracts.check(verified, contract):
            if result.status != "verified":
                return _invalid(
                    status="rejected",
                    reply="回答被契约校验拦截，请重新查询。",
                    reason_code=result.reason_code,
                )

        # Presentation Spec：确定性展示语义（原始数值 + format 元数据）
        ranking_items = [
            {
                "rank": row.rank,
                "customer_name": row.entity_label,
                "sales_amount": float(row.value),
            }
            for row in (envelope.payload.rows or [])
        ]
        result = {
            "metric_id": RANKING_METRIC_ID,
            "year": year,
            "limit": limit,
            "order": sort,
            "items": ranking_items,
        }
        presentation = PresentationBuilder().build(
            metric_id=RANKING_METRIC_ID,
            result_shape="ranking",
            title=f"{year} 年客户销售额排行",
            hint=request.presentation_hint or "auto",
            items=ranking_items,
            category_key="customer_name",
            value_key="sales_amount",
            context={"year": year, "limit": limit},
            total_rows=len(ranking_items),
        ).model_dump_json_safe()
        reply = self._renderer.render_summary(verified, facts=facts, envelope=envelope)
        rule_labels = self._rule_labels(all_assertions)
        detail = self._renderer.render_explanation(
            verified, facts=facts, calculations=calculations, envelope=envelope, rules=rule_labels,
        )
        trust = collect_trust_metrics(
            assertions=all_assertions,
            verified_ids=[a.assertion_id for a in verified],
            sentences=[],
            facts=facts,
        )
        self._record_trace(
            tenant_id, conversation_id, envelope, calculations,
            result_ids=[envelope.result_id],
            calculation_ids=[c.calculation_id for c in calculations],
            outcome="direct_ranking",
        )
        return {
            "status": "success",
            "reply": reply,
            "result": result,
            "presentation": presentation,
            "detail": {"available": True, "kind": "deterministic", "content": detail},
            "trust_metrics": trust.model_dump(mode="json"),
            "evidence": [],
            "fast_path": {"active": True, "result_id": envelope.result_id, "mode": "direct"},
            "reason_code": "SUCCESS",
        }

    def _derive_ranking(
        self,
        envelope: EvidenceEnvelope,
        metric_facts: list[Fact],
        needs_share: bool,
        *,
        total_revenue: Decimal,
    ):
        """topn_total + share_of_total（独立重算通过才允许进入 assertion 构建）。"""
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
            "topn_total", numerator_inputs,
            calculation_id=f"c_{envelope.result_id}_topn",
            output_fact_id=f"{envelope.result_id}:topn_total",
        )
        calc2, share_fact = self._engine.compute(
            "share_of_total", [topn_fact, total_fact],
            calculation_id=f"c_{envelope.result_id}_share",
            output_fact_id=f"{envelope.result_id}:share",
        )
        assert self._calc_validator.verify(calc1, numerator_inputs, topn_fact).status == "verified"
        assert self._calc_validator.verify(calc2, [topn_fact, total_fact], share_fact).status == "verified"
        return metric_facts + [topn_fact, share_fact], [calc1, calc2], total_fact

    # ------------------------------------------------------------------
    # 执行器：metric_snapshot
    # ------------------------------------------------------------------

    def _exec_snapshot(
        self,
        db: Session,
        tenant_id: int,
        conversation_id: str,
        permission_codes: list[str] | None,
        request: DirectMetricRequest,
    ) -> DirectArtifact:
        from app.services import analysis_result_store, finance_service

        year = request.time_range.year if request.time_range else None
        month = request.time_range.month if request.time_range else None
        try:
            report = finance_service.profit_report(db, tenant_id, year=year, month=month)
        except Exception as exc:  # noqa: BLE001 - defensive
            return _invalid(
                status="rejected",
                reply=f"销售额查询失败：{exc}",
                reason_code="EXECUTION_ERROR",
            )
        summary = report.get("summary") or {}
        revenue = Decimal(str(summary.get("revenue") or 0))
        result_id = analysis_result_store.put_result(
            tenant_id,
            SNAPSHOT_METRIC_ID,
            {"year": year, "month": month, "revenue": str(revenue)},
            {"year": year, "month": month},
            session_id=conversation_id,
        )
        envelope = EvidenceEnvelope(
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

        fact_builder = SnapshotFactBuilder()
        built = fact_builder.build(envelope)
        if built.status != "verified":
            return _invalid(
                status="rejected",
                reply="当前证据不足以回答该问题（缺少销售额数值），不能给出销售额结论。",
                reason_code=built.reason_code,
            )

        assertions = self._assertions.build(envelope=envelope, facts=built.facts, calculations=[])
        contract = self._contract(request)
        verdicts = self._structural.validate(
            assertions, facts=built.facts, calculations=[], envelope=envelope, contract=contract
        )
        verified = [a for a, v in zip(assertions, verdicts) if v.status == "verified"]
        for result in self._contracts.check(verified, contract):
            if result.status != "verified":
                return _invalid(
                    status="rejected",
                    reply="回答被契约校验拦截，请重新查询。",
                    reason_code=result.reason_code,
                )

        # Presentation Spec：单值 KPI（保留原始数值 + format 元数据）
        value = float(revenue)
        title = f"{year} 年" + (f" {month} 月" if month else "") + "销售额"
        result = {
            "metric_id": SNAPSHOT_METRIC_ID,
            "year": year,
            "month": month,
            "value": value,
            "unit": "CNY",
        }
        presentation = PresentationBuilder().build(
            metric_id=SNAPSHOT_METRIC_ID,
            result_shape="scalar",
            title=title,
            hint=request.presentation_hint or "auto",
            value=value,
            context={"time_range": f"{year}-{month:02d}" if month else str(year)},
        ).model_dump_json_safe()
        reply = self._renderer.render_summary(verified, facts=built.facts, envelope=envelope)
        detail = self._renderer.render_explanation(
            verified, facts=built.facts, calculations=[], envelope=envelope, rules={},
        )
        trust = collect_trust_metrics(
            assertions=assertions,
            verified_ids=[a.assertion_id for a in verified],
            sentences=[],
            facts=built.facts,
        )
        self._record_trace(
            tenant_id, conversation_id, envelope, [],
            result_ids=[envelope.result_id],
            calculation_ids=[],
            outcome="direct_metric_snapshot",
        )
        return {
            "status": "success",
            "reply": reply,
            "result": result,
            "presentation": presentation,
            "detail": {"available": True, "kind": "deterministic", "content": detail},
            "trust_metrics": trust.model_dump(mode="json"),
            "evidence": [],
            "fast_path": {"active": True, "result_id": envelope.result_id, "mode": "direct"},
            "reason_code": "SUCCESS",
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _contract(request: DirectMetricRequest) -> AnswerContract:
        # direct 路径始终渲染表格卡片（可扫读）+ 一句话结论；契约按 sentence
        # 模式校验结论可追溯性（表格呈现由 presentation 结构保证）。
        if request.metric_id == RANKING_METRIC_ID:
            return ranking_answer_contract(presentation_mode="sentence")
        return snapshot_answer_contract(presentation_mode="sentence")

    @staticmethod
    def _rule_labels(assertions: list) -> dict[str, tuple[str, str]]:
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
        envelope: EvidenceEnvelope,
        calculations: list,
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
            semantic_plan_id=envelope.result_id,
            execution_plan_id=envelope.result_id,
            match_passed=True,
            result_ids=result_ids,
            calculation_ids=calculation_ids,
            approval_ids=[],
            approval_statuses=[],
            versions={
                "runtime_contract": "1.0.0",
                "renderer": "deterministic-v1",
                "prompt": "direct-tool",
            },
            outcome=outcome,
        )


def _invalid(*, status: str, reply: str, reason_code: str) -> DirectArtifact:
    return {
        "status": status,  # type: ignore[typeddict-item]
        "reply": reply,
        "result": None,
        "presentation": None,
        "detail": None,
        "trust_metrics": None,
        "evidence": [],
        "fast_path": None,
        "reason_code": reason_code,
        "clarification": reply,
        "options": [],
    }


def _metric_names() -> str:
    return "、".join(SUPPORTED_DIRECT_METRICS)


# metric_id → 执行器（注册表；新指标在此注册）
_EXECUTORS: dict[str, Callable[..., DirectArtifact]] = {
    RANKING_METRIC_ID: DirectMetricExecutor._exec_ranking,
    SNAPSHOT_METRIC_ID: DirectMetricExecutor._exec_snapshot,
}
