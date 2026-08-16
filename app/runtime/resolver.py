"""Minimal resolver for the ranking slice (PR #1).

Turns a structurally-validated ``RankingRequest`` (the shape a future
semantic parser must produce) into a ``ResolvedSemanticPlan`` with the fixed
ranking shape, or a ``ClarificationResult`` when the registry cannot resolve
uniquely.  This is a *deterministic* resolver: LLMs may propose, but only this
registry binds metric/dimension/scope (contracts doc §4).

Fixed v1 shape (slice doc §2.3)::

    op_ranking (ranking, top_n, sort)
        └─ op_topn_total (topn_total, source_ref=op_ranking)   [when needs_share]
        └─ op_share (share_of_total, numerator_ref=op_topn_total,
                     denominator_ref=op_total)                  [when needs_share]
    op_total (metric_snapshot)                                  [when needs_share]

``needs_share`` is the composition dependency used by cases like
“前两名客户占多少?” and the concentration gate (Case 5/10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Union

from pydantic import Field

from app.runtime.contracts import (
    MetricRef,
    OperationSpec,
    ResolvedSemanticPlan,
    RuntimeModel,
    TimeScope,
)
from app.runtime.registry import MetricRegistry

DEFAULT_RANKING_LIMIT = 10


class RankingRequest(RuntimeModel):
    """Structured intent input for v1 (what a parser must resolve to).

    Only the fields the ranking slice actually needs: metric, dimension,
    year-level scope, sort, limit and the composition flag.  ``comparison``
    carries a cross-period intent when present — v1 has no such capability and
    resolves it to an explicit ``unsupported`` (Case 9), never to a silent
    substitute.
    """

    metric_id: str
    dimension: str = "customer"
    year: int | None = None
    as_of: datetime
    limit: int | None = None
    sort: Literal["desc", "asc"] = "desc"
    filters: dict = Field(default_factory=dict)
    needs_share: bool = False
    comparison: Literal["period_top_n", "fixed_cohort"] | None = None


class ClarificationResult(RuntimeModel):
    """Single-field compiler outcome for v1 (contracts doc §4.3/§4.4):
    ``requires_clarification`` for missing/ambiguous input,
    ``unsupported`` when the system has no capability for the intent."""

    status: Literal["requires_clarification", "unsupported"] = "requires_clarification"
    field_path: str
    reason_code: str
    question: str
    options: list[str] = Field(default_factory=list)


ResolverResult = Union[ResolvedSemanticPlan, ClarificationResult]


class RankingResolver:
    """Deterministic resolver over the v1 metric registry."""

    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry.ranking_v1()

    @property
    def registry(self) -> MetricRegistry:
        return self._registry

    def resolve(self, request: RankingRequest) -> ResolverResult:
        comparison = self._resolve_comparison(request.comparison)
        if comparison is not None:
            return comparison
        metric = self._resolve_metric(request.metric_id)
        if isinstance(metric, ClarificationResult):
            return metric
        scope = self._resolve_scope(request.year)
        if isinstance(scope, ClarificationResult):
            return scope
        limit = request.limit if request.limit is not None else DEFAULT_RANKING_LIMIT
        if limit < 1:
            return ClarificationResult(
                field_path="limit",
                reason_code="INVALID_LIMIT",
                question="排行数量必须至少为 1，请确认要前几名？",
                options=[],
            )
        operations = self._build_operations(
            limit=limit,
            sort=request.sort,
            needs_share=request.needs_share,
        )
        return ResolvedSemanticPlan(
            semantic_plan_id=f"sp_{uuid.uuid4().hex[:16]}",
            metric=metric,
            dimension=request.dimension,
            scope=scope,
            as_of=request.as_of,
            timezone="Asia/Shanghai",
            filters=dict(request.filters or {}),
            operations=operations,
        )

    @staticmethod
    def _resolve_comparison(
        comparison: Literal["period_top_n", "fixed_cohort"] | None,
    ) -> ClarificationResult | None:
        """Cross-period comparison is explicitly unsupported in v1 (Case 9):
        return the failure semantics, never a silent same-period substitute."""
        if comparison is None:
            return None
        return ClarificationResult(
            status="unsupported",
            field_path="comparison",
            reason_code="UNSUPPORTED_ANALYSIS_TYPE",
            question="当前只能查询单一期间的排行，暂不支持跨期结构对比。",
            options=[],
        )

    def _resolve_metric(self, metric_id: str) -> MetricRef | ClarificationResult:
        found = self._registry.find(metric_id)
        if not found:
            return ClarificationResult(
                field_path="operations.op_ranking.metric",
                reason_code="UNKNOWN_METRIC",
                question=f"未注册指标 {metric_id}，请从指标目录中选择。",
                options=[d.metric_id for d in self._registry.definitions()],
            )
        if len(found) > 1:
            return ClarificationResult(
                field_path="operations.op_ranking.metric",
                reason_code="AMBIGUOUS_METRIC",
                question=f"指标 {metric_id} 存在多个版本，请确认口径。",
                options=[d.definition_version for d in found],
            )
        return MetricRef(
            metric_id=found[0].metric_id,
            definition_version=found[0].definition_version,
        )

    @staticmethod
    def _resolve_scope(year: int | None) -> TimeScope | ClarificationResult:
        if year is None:
            return ClarificationResult(
                field_path="scope",
                reason_code="TIME_SCOPE_AMBIGUOUS",
                question="未指定查询年份，请问要查询哪一年的排行？",
                options=[],
            )
        return TimeScope(year=year)

    @staticmethod
    def _build_operations(
        *,
        limit: int,
        sort: Literal["desc", "asc"],
        needs_share: bool,
    ) -> list[OperationSpec]:
        ops = [
            OperationSpec(
                operation_id="op_ranking",
                type="ranking",
                top_n=limit,
                sort=sort,
            )
        ]
        if needs_share:
            ops.append(
                OperationSpec(
                    operation_id="op_total",
                    type="metric_snapshot",
                )
            )
            ops.append(
                OperationSpec(
                    operation_id="op_topn_total",
                    type="topn_total",
                    top_n=limit,
                    source_ref="op_ranking",
                )
            )
            ops.append(
                OperationSpec(
                    operation_id="op_share",
                    type="share_of_total",
                    numerator_ref="op_topn_total",
                    denominator_ref="op_total",
                )
            )
        return ops
