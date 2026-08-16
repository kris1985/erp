"""FactBuilder for the ranking + metric_snapshot slices (PR #2, contracts doc §P1.1).

Raw ranking rows become ``MetricFact`` objects with deterministic ids; raw
snapshot values become a single total ``MetricFact``. Derived numbers (Top-N
total, share) belong to PR #3's Calculation Engine and are deliberately not
computed here.  Before emitting facts the builder:

1. gates on coverage (a missing population denominator blocks share-dependent
   operations, never silently assumed);
2. pins the metric definition version — an envelope whose version is unknown
   or mismatched is rejected, not guessed;
3. checks every row's unit against the registered metric unit.
"""

from __future__ import annotations

from typing import Literal

from app.runtime.contracts import EvidenceEnvelope, Fact, RuntimeModel
from app.runtime.coverage import (
    CoverageVerdict,
    check_ranking_coverage,
    check_snapshot_coverage,
)
from app.runtime.registry import MetricRegistry

METRIC_VERSION_MISMATCH = "METRIC_VERSION_MISMATCH"
UNKNOWN_METRIC = "UNKNOWN_METRIC"
UNIT_MISMATCH = "UNIT_MISMATCH"
FACTS_BUILT = "FACTS_BUILT"


class FactBuildResult(RuntimeModel):
    status: Literal["verified", "insufficient_evidence", "rejected"]
    facts: list[Fact]
    reason_code: str | None = None
    evidence_refs: list[str] = []


class RankingFactBuilder:
    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry.v1()

    def build(
        self,
        envelope: EvidenceEnvelope,
        *,
        need_denominator: bool = False,
    ) -> FactBuildResult:
        verdict = check_ranking_coverage(envelope, need_denominator=need_denominator)
        if verdict.status != "verified":
            return FactBuildResult(
                status=verdict.status,
                facts=[],
                reason_code=verdict.reason_code,
                evidence_refs=verdict.evidence_refs,
            )

        definitions = self._registry.find(envelope.metric.metric_id)
        if not definitions:
            return FactBuildResult(
                status="rejected",
                facts=[],
                reason_code=UNKNOWN_METRIC,
                evidence_refs=[envelope.result_id],
            )
        if len(definitions) > 1 or (
            definitions[0].definition_version != envelope.metric.definition_version
        ):
            return FactBuildResult(
                status="rejected",
                facts=[],
                reason_code=METRIC_VERSION_MISMATCH,
                evidence_refs=[envelope.result_id],
            )
        definition = definitions[0]

        facts: list[Fact] = []
        for row in envelope.payload.rows:
            if row.unit != definition.unit:
                return FactBuildResult(
                    status="rejected",
                    facts=[],
                    reason_code=UNIT_MISMATCH,
                    evidence_refs=[envelope.result_id],
                )
            facts.append(
                Fact(
                    fact_id=f"{envelope.result_id}:{row.entity_id}",
                    type="metric_fact",
                    name=definition.name,
                    value=row.value,
                    unit=row.unit,
                    dimensions={envelope.dimension: row.entity_id},
                    scope=envelope.scope,
                    source="metric_engine",
                    evidence_refs=[envelope.result_id],
                )
            )
        return FactBuildResult(
            status="verified",
            facts=facts,
            reason_code=FACTS_BUILT,
            evidence_refs=[envelope.result_id],
        )


class SnapshotFactBuilder:
    """Builds the single total Fact for a ``metric_snapshot`` envelope.

    The snapshot payload carries one scalar value; it becomes one metric_fact
    with no dimensions. Coverage is gated the same way (a missing value is
    insufficient evidence, never a silently assumed zero).
    """

    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry.v1()

    def build(self, envelope: EvidenceEnvelope) -> FactBuildResult:
        verdict = check_snapshot_coverage(envelope)
        if verdict.status != "verified":
            return FactBuildResult(
                status=verdict.status,
                facts=[],
                reason_code=verdict.reason_code,
                evidence_refs=verdict.evidence_refs,
            )

        definitions = self._registry.find(envelope.metric.metric_id)
        if not definitions:
            return FactBuildResult(
                status="rejected",
                facts=[],
                reason_code=UNKNOWN_METRIC,
                evidence_refs=[envelope.result_id],
            )
        if len(definitions) > 1 or (
            definitions[0].definition_version != envelope.metric.definition_version
        ):
            return FactBuildResult(
                status="rejected",
                facts=[],
                reason_code=METRIC_VERSION_MISMATCH,
                evidence_refs=[envelope.result_id],
            )
        definition = definitions[0]
        value = envelope.payload.snapshot_value
        assert value is not None  # guaranteed by TypedAnalysisResult shape
        if value.unit != definition.unit:
            return FactBuildResult(
                status="rejected",
                facts=[],
                reason_code=UNIT_MISMATCH,
                evidence_refs=[envelope.result_id],
            )
        fact = Fact(
            fact_id=f"{envelope.result_id}:total",
            type="metric_fact",
            name=definition.name,
            value=value.value,
            unit=value.unit,
            dimensions={},
            scope=envelope.scope,
            source="metric_engine",
            evidence_refs=[envelope.result_id],
        )
        return FactBuildResult(
            status="verified",
            facts=[fact],
            reason_code=FACTS_BUILT,
            evidence_refs=[envelope.result_id],
        )
