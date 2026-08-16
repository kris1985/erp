"""PR #1 resolver tests: deterministic binding, fixed-shape DAG,
clarification on unknown/ambiguous/underspecified input."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.registry import MetricDefinition, MetricRegistry
from app.runtime.resolver import (
    ClarificationResult,
    DEFAULT_RANKING_LIMIT,
    RankingRequest,
    RankingResolver,
    ResolvedSemanticPlan,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)


def request(**overrides) -> RankingRequest:
    base: dict = {
        "metric_id": "finance.customer_sales_ranking",
        "year": 2026,
        "as_of": AS_OF,
    }
    base.update(overrides)
    return RankingRequest(**base)


def test_basic_ranking_compiles() -> None:
    result = RankingResolver().resolve(request())
    assert isinstance(result, ResolvedSemanticPlan)
    assert result.metric.definition_version == "1.0.0"
    assert result.scope.year == 2026
    assert [op.type for op in result.operations] == ["ranking"]


def test_default_limit_is_10() -> None:
    result = RankingResolver().resolve(request(limit=None))
    assert isinstance(result, ResolvedSemanticPlan)
    assert result.operations[0].top_n == DEFAULT_RANKING_LIMIT


def test_share_shape_builds_full_dag() -> None:
    result = RankingResolver().resolve(request(limit=2, needs_share=True))
    assert isinstance(result, ResolvedSemanticPlan)
    assert [(op.type, op.operation_id) for op in result.operations] == [
        ("ranking", "op_ranking"),
        ("metric_snapshot", "op_total"),
        ("topn_total", "op_topn_total"),
        ("share_of_total", "op_share"),
    ]
    topn = result.operations[2]
    assert topn.source_ref == "op_ranking"
    assert topn.top_n == 2
    share = result.operations[3]
    assert share.numerator_ref == "op_topn_total"
    assert share.denominator_ref == "op_total"


def test_unknown_metric_requires_clarification() -> None:
    result = RankingResolver().resolve(request(metric_id="finance.net_profit"))
    assert isinstance(result, ClarificationResult)
    assert result.reason_code == "UNKNOWN_METRIC"
    assert result.field_path == "operations.op_ranking.metric"


def test_ambiguous_metric_requires_clarification() -> None:
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
    result = RankingResolver(registry).resolve(request())
    assert isinstance(result, ClarificationResult)
    assert result.reason_code == "AMBIGUOUS_METRIC"
    assert result.options == ["1.0.0", "2.0.0"]


def test_missing_year_requires_clarification() -> None:
    result = RankingResolver().resolve(request(year=None))
    assert isinstance(result, ClarificationResult)
    assert result.reason_code == "TIME_SCOPE_AMBIGUOUS"
    assert result.field_path == "scope"


def test_naive_as_of_requires_clarification() -> None:
    """H2: an as_of without a timezone is a time-scope ambiguity, and the
    plan must never hard-code a timezone that contradicts the as_of."""
    naive = datetime(2026, 8, 16, 23, 59, 59)  # no tzinfo
    result = RankingResolver().resolve(request(as_of=naive))
    assert isinstance(result, ClarificationResult)
    assert result.reason_code == "TIME_SCOPE_AMBIGUOUS"
    assert result.field_path == "as_of"


def test_timezone_derived_from_as_of_offset() -> None:
    """H2: plan.timezone reflects the as_of's real timezone (+08:00), never
    a hard-coded constant."""
    result = RankingResolver().resolve(
        request(as_of=datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone(timedelta(hours=8))))
    )
    assert isinstance(result, ResolvedSemanticPlan)
    assert result.timezone == "UTC+08:00"


def test_invalid_limit_rejected() -> None:
    result = RankingResolver().resolve(request(limit=0))
    assert isinstance(result, ClarificationResult)
    assert result.reason_code == "INVALID_LIMIT"


def test_filters_pass_through() -> None:
    result = RankingResolver().resolve(request(filters={"customer_region": "east"}))
    assert isinstance(result, ResolvedSemanticPlan)
    assert result.filters == {"customer_region": "east"}


def test_plan_serializes_to_expected_shape() -> None:
    result = RankingResolver().resolve(request(limit=3))
    assert isinstance(result, ResolvedSemanticPlan)
    dumped = result.model_dump(mode="json", exclude_none=True)
    dumped.pop("semantic_plan_id")
    assert dumped == {
        "schema_version": "1.0.0",
        "metric": {
            "metric_id": "finance.customer_sales_ranking",
            "definition_version": "1.0.0",
        },
        "dimension": "customer",
        "scope": {"year": 2026},
        "as_of": "2026-08-16T23:59:59Z",
        "timezone": "UTC",
        "filters": {},
        "operations": [
            {"operation_id": "op_ranking", "type": "ranking", "top_n": 3, "sort": "desc"}
        ],
    }
