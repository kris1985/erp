"""FactBuilder unit tests (PR #2, contracts doc §P1.1).

Rows become MetricFacts with deterministic ids; derived numbers stay out of
scope (PR #3).  Unit and metric-definition-version are pinned before emit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.runtime.contracts import (
    Coverage,
    EvidenceEnvelope,
    Freshness,
    MetricRef,
    TimeScope,
    TypedAnalysisResult,
)
from app.runtime.fact_builder import (
    FACTS_BUILT,
    METRIC_VERSION_MISMATCH,
    RankingFactBuilder,
    UNIT_MISMATCH,
    UNKNOWN_METRIC,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
BUILDER = RankingFactBuilder()


def envelope(
    *,
    metric: MetricRef | None = None,
    rows: list[dict] | None = None,
    coverage: Coverage | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_001",
        metric=metric
        or MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
        scope=TimeScope(year=2026),
        dimension="customer",
        operation="ranking",
        coverage=coverage
        or Coverage(
            type="complete_population",
            requested=2,
            returned=2,
            population_complete=True,
            population_size=2,
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        payload=TypedAnalysisResult(
            result_type="ranking",
            rows=rows
            or [
                {
                    "entity_id": "customer:A",
                    "entity_label": "客户 A",
                    "value": Decimal("12350000"),
                    "unit": "CNY",
                    "rank": 1,
                },
                {
                    "entity_id": "customer:B",
                    "entity_label": "客户 B",
                    "value": Decimal("9800000"),
                    "unit": "CNY",
                    "rank": 2,
                },
            ],
            execution_ref="metric_exec_001",
        ),
    )


def test_rows_become_metric_facts() -> None:
    result = BUILDER.build(envelope())
    assert result.status == "verified"
    assert result.reason_code == FACTS_BUILT
    assert len(result.facts) == 2
    first = result.facts[0]
    assert first.type == "metric_fact"
    assert first.name == "客户销售额"
    assert first.value == Decimal("12350000")
    assert first.unit == "CNY"
    assert first.dimensions == {"customer": "customer:A"}
    assert first.scope.year == 2026
    assert first.evidence_refs == ["r_001"]
    assert first.calculation_id is None  # raw rows are not derived


def test_fact_ids_are_deterministic() -> None:
    a = BUILDER.build(envelope()).facts
    b = BUILDER.build(envelope()).facts
    assert [f.fact_id for f in a] == [f.fact_id for f in b] == [
        "r_001:customer:A",
        "r_001:customer:B",
    ]


def test_insufficient_coverage_blocks_facts() -> None:
    top3_only = Coverage(
        type="top_n",
        requested=10,
        returned=3,
        population_complete=False,
        denominator_available=False,
    )
    result = BUILDER.build(envelope(coverage=top3_only), need_denominator=True)
    assert result.status == "insufficient_evidence"
    assert result.facts == []


def test_unit_mismatch_rejected() -> None:
    bad = envelope()
    row = bad.payload.rows[0].model_copy(update={"unit": "USD"})
    bad = bad.model_copy(update={"payload": bad.payload.model_copy(update={"rows": [row]})})
    result = BUILDER.build(bad)
    assert result.status == "rejected"
    assert result.reason_code == UNIT_MISMATCH


def test_unknown_metric_rejected() -> None:
    result = BUILDER.build(
        envelope(metric=MetricRef(metric_id="finance.net_profit", definition_version="1.0.0"))
    )
    assert result.status == "rejected"
    assert result.reason_code == UNKNOWN_METRIC


def test_definition_version_mismatch_rejected() -> None:
    result = BUILDER.build(
        envelope(
            metric=MetricRef(
                metric_id="finance.customer_sales_ranking", definition_version="9.9.9"
            )
        )
    )
    assert result.status == "rejected"
    assert result.reason_code == METRIC_VERSION_MISMATCH


def test_builder_rejects_unregistered_multi_version() -> None:
    from app.runtime.registry import MetricDefinition, MetricRegistry

    registry = MetricRegistry(
        [
            MetricDefinition(
                metric_id="finance.customer_sales_ranking",
                definition_version="1.0.0",
                name="客户销售额 v1",
                unit="CNY",
                aggregation="sum",
                time_semantics="natural_year",
                granularity="year",
            ),
            MetricDefinition(
                metric_id="finance.customer_sales_ranking",
                definition_version="2.0.0",
                name="客户销售额 v2",
                unit="CNY",
                aggregation="sum",
                time_semantics="natural_year",
                granularity="year",
            ),
        ]
    )
    result = RankingFactBuilder(registry).build(envelope())
    assert result.status == "rejected"
    assert result.reason_code == METRIC_VERSION_MISMATCH
