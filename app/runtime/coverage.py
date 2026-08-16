"""CoverageGate for the ranking slice (PR #2, contracts doc §P1.0).

A ``result_id`` alone never proves sufficiency: the gate checks coverage
before facts are built and before claims are validated.  Top-N rows must never
be used to infer a population denominator — a denominator is only usable when
explicitly declared (``population_complete`` or ``denominator_available``).

Acceptance (contracts §P1.0): with only Top-10 rows and no population total,
the agent may answer the Top-10 ranking but must NOT answer “overall customer
concentration”.
"""

from __future__ import annotations

from typing import Literal

from app.runtime.contracts import EvidenceEnvelope, RuntimeModel


class CoverageVerdict(RuntimeModel):
    status: Literal["verified", "insufficient_evidence", "rejected"]
    stage: Literal["metric_validation"] = "metric_validation"
    reason_code: str
    evidence_refs: list[str]


COVERAGE_SUFFICIENT = "COVERAGE_SUFFICIENT"
NO_ROWS = "NO_ROWS"
POPULATION_DENOMINATOR_UNAVAILABLE = "POPULATION_DENOMINATOR_UNAVAILABLE"


def check_ranking_coverage(
    envelope: EvidenceEnvelope,
    *,
    need_denominator: bool,
) -> CoverageVerdict:
    """Gate an envelope for the ranking slice.

    ``need_denominator=True`` is required by operations that need a population
    total (``share_of_total``, concentration judgement).  Ranking/rank/value
    claims only need rows.
    """
    refs = [envelope.result_id]
    if not envelope.payload.rows:
        return CoverageVerdict(
            status="insufficient_evidence",
            reason_code=NO_ROWS,
            evidence_refs=refs,
        )
    if need_denominator and not (
        envelope.coverage.population_complete or envelope.coverage.denominator_available
    ):
        return CoverageVerdict(
            status="insufficient_evidence",
            reason_code=POPULATION_DENOMINATOR_UNAVAILABLE,
            evidence_refs=refs,
        )
    return CoverageVerdict(
        status="verified",
        reason_code=COVERAGE_SUFFICIENT,
        evidence_refs=refs,
    )
