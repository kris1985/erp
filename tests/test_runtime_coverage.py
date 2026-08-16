"""CoverageGate unit tests (PR #2, contracts doc §P1.0).

Acceptance: with only Top-N rows and no population total, the agent may
answer the ranking but must NOT answer overall concentration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.runtime.contracts import (
    Coverage,
    EvidenceEnvelope,
    Freshness,
    MetricRef,
    TimeScope,
    TypedAnalysisResult,
)
from app.runtime.coverage import (
    COVERAGE_SUFFICIENT,
    NO_ROWS,
    POPULATION_DENOMINATOR_UNAVAILABLE,
    check_ranking_coverage,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
METRIC = MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0")


def envelope(*, coverage: Coverage, rows: int = 3) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_test",
        metric=METRIC,
        scope=TimeScope(year=2026),
        dimension="customer",
        operation="ranking",
        coverage=coverage,
        freshness=Freshness(queried_at=AS_OF),
        payload=TypedAnalysisResult(
            result_type="ranking",
            rows=[
                {
                    "entity_id": f"customer:{i}",
                    "entity_label": f"客户 {i}",
                    "value": Decimal("1000000"),
                    "unit": "CNY",
                    "rank": i,
                }
                for i in range(1, rows + 1)
            ],
            execution_ref="metric_exec_test",
        ),
    )


TOP3_NO_DENOM = Coverage(
    type="top_n",
    requested=10,
    returned=3,
    population_complete=False,
    denominator_available=False,
)
COMPLETE = Coverage(
    type="complete_population",
    requested=4,
    returned=4,
    population_complete=True,
    population_size=4,
    denominator_available=True,
)
DENOM_AVAILABLE = Coverage(
    type="top_n",
    requested=10,
    returned=3,
    population_complete=False,
    denominator_available=True,
)


def test_topn_without_denominator_can_answer_ranking() -> None:
    """Acceptance: Top-10 rows without total -> ranking is answerable."""
    verdict = check_ranking_coverage(envelope(coverage=TOP3_NO_DENOM), need_denominator=False)
    assert verdict.status == "verified"
    assert verdict.reason_code == COVERAGE_SUFFICIENT


def test_topn_without_denominator_cannot_answer_concentration() -> None:
    """Acceptance: same evidence must NOT answer overall concentration."""
    verdict = check_ranking_coverage(envelope(coverage=TOP3_NO_DENOM), need_denominator=True)
    assert verdict.status == "insufficient_evidence"
    assert verdict.reason_code == POPULATION_DENOMINATOR_UNAVAILABLE


def test_complete_population_provides_denominator() -> None:
    verdict = check_ranking_coverage(envelope(coverage=COMPLETE), need_denominator=True)
    assert verdict.status == "verified"


def test_explicit_denominator_flag_is_trusted() -> None:
    verdict = check_ranking_coverage(envelope(coverage=DENOM_AVAILABLE), need_denominator=True)
    assert verdict.status == "verified"


def test_no_rows_is_insufficient_even_without_denominator() -> None:
    verdict = check_ranking_coverage(envelope(coverage=COMPLETE, rows=0), need_denominator=False)
    assert verdict.status == "insufficient_evidence"
    assert verdict.reason_code == NO_ROWS


def test_verdict_records_evidence_refs() -> None:
    verdict = check_ranking_coverage(envelope(coverage=TOP3_NO_DENOM), need_denominator=True)
    assert verdict.evidence_refs == ["r_test"]
    assert verdict.stage == "metric_validation"
