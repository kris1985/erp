"""PR #1 contract tests: serialization round-trip, schema versioning,
compatible reads, frozen payloads and the EvidenceEnvelope composition spike.

The composition choice (contracts doc §3.5) is decided here: the envelope owns
all evidence meta; the payload carries none and rejects extra keys, so a
tampered copy can never smuggle a second authoritative meta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.runtime.contracts import (
    SCHEMA_VERSION,
    AnswerContract,
    Assertion,
    Calculation,
    Coverage,
    DisplaySpec,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    OperationSpec,
    ResolvedSemanticPlan,
    RoundingPolicy,
    TimeScope,
    TypedAnalysisResult,
    ValidationResult,
    dump_contract,
    load_contract,
    ranking_answer_contract,
)
from app.runtime.registry import MetricDefinition, RANKING_METRIC

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)


def make_envelope() -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_001",
        metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
        scope=TimeScope(year=2026),
        dimension="customer",
        operation="ranking",
        coverage=Coverage(
            type="complete_population",
            requested=10,
            returned=4,
            population_complete=True,
            population_size=4,
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        authority="metric_engine",
        payload=TypedAnalysisResult(
            result_type="ranking",
            rows=[
                {
                    "entity_id": "customer:A",
                    "entity_label": "客户 A",
                    "value": Decimal("12350000"),
                    "unit": "CNY",
                    "rank": 1,
                }
            ],
            execution_ref="metric_exec_9328",
        ),
    )


def make_fact() -> Fact:
    return Fact(
        fact_id="f_customer_a_sales",
        type="metric_fact",
        name="customer_sales",
        value=Decimal("12350000"),
        unit="CNY",
        display=DisplaySpec(scale=4, format="thousands"),
        dimensions={"customer": "customer:A"},
        scope=TimeScope(year=2026),
        evidence_refs=["r_001"],
    )


def make_calculation() -> Calculation:
    return Calculation(
        calculation_id="c_top2_share",
        definition="share_of_total",
        inputs=["f_customer_1", "f_customer_2", "f_total_sales"],
        output_fact="f_top2_share",
        formula="(input[0].value + input[1].value) / input[2].value",
        rounding=RoundingPolicy(precision=4, mode="half_up"),
    )


def make_assertion() -> Assertion:
    return Assertion(
        assertion_id="c_rank_a",
        type="fact",
        predicate="rank",
        claim_strength="deterministic",
        subject={
            "metric": {"metric_id": "finance.customer_sales_ranking", "definition_version": "1.0.0"},
            "dimensions": {"customer": "customer:A"},
            "scope": {"year": 2026},
        },
        object={"rank": 1, "value_fact_ref": "f_customer_a_sales"},
        fact_refs=["f_customer_a_sales"],
        evidence_refs=["r_001"],
    )


def make_plan() -> ResolvedSemanticPlan:
    return ResolvedSemanticPlan(
        semantic_plan_id="sp_test",
        metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
        dimension="customer",
        scope=TimeScope(year=2026),
        as_of=AS_OF,
        operations=[
            OperationSpec(operation_id="op_ranking", type="ranking", top_n=10, sort="desc")
        ],
    )


ALL_CONTRACTS = {
    "ResolvedSemanticPlan": make_plan(),
    "TypedAnalysisResult": make_envelope().payload,
    "EvidenceEnvelope": make_envelope(),
    "Fact": make_fact(),
    "Calculation": make_calculation(),
    "Assertion": make_assertion(),
    "AnswerContract": ranking_answer_contract(),
    "ValidationResult": ValidationResult(
        status="rejected",
        stage="metric_validation",
        reason_code="TIME_SCOPE_MISMATCH",
        assertion_id="c_sales_2026",
        expected={"year": 2026},
        actual={"year": 2025},
        evidence_refs=["r_001"],
        action="replan",
    ),
}


@pytest.mark.parametrize("name", sorted(ALL_CONTRACTS))
def test_roundtrip_all_contracts(name: str) -> None:
    obj = ALL_CONTRACTS[name]
    dumped = dump_contract(obj)
    assert dumped["schema_version"] == SCHEMA_VERSION, name
    restored = load_contract(type(obj), dumped)
    assert restored == obj, name


def test_dump_is_stable_json_mode() -> None:
    dumped = dump_contract(make_envelope())
    assert dumped["payload"]["rows"][0]["value"] == "12350000"  # Decimal -> str
    assert "month" not in dumped["scope"]  # exclude_none deterministic dump


def test_extra_keys_rejected() -> None:
    dumped = dump_contract(make_envelope())
    dumped["surplus_knob"] = True
    with pytest.raises(ValidationError):
        load_contract(EvidenceEnvelope, dumped)


def test_missing_required_field_rejected() -> None:
    dumped = dump_contract(make_envelope())
    del dumped["result_id"]
    with pytest.raises(ValidationError):
        load_contract(EvidenceEnvelope, dumped)


def test_frozen_after_construction() -> None:
    envelope = make_envelope()
    with pytest.raises(ValidationError):
        envelope.result_id = "r_mutated"  # type: ignore[misc]


def test_envelope_composition_payload_has_no_meta() -> None:
    """Spike conclusion: meta lives only in the envelope."""
    payload_dump = dump_contract(make_envelope().payload)
    for meta_field in ("metric", "scope", "coverage", "freshness"):
        assert meta_field not in payload_dump, f"payload must not carry {meta_field}"


def test_envelope_payload_cannot_smuggle_meta() -> None:
    """Tamper test: adding meta to the payload is rejected, not ignored."""
    dumped = dump_contract(make_envelope().payload)
    dumped["metric"] = {"metric_id": "hacked", "definition_version": "9.9.9"}
    with pytest.raises(ValidationError):
        load_contract(TypedAnalysisResult, dumped)


def test_envelope_operation_result_type_mismatch() -> None:
    payload = make_envelope().payload
    with pytest.raises(ValidationError):
        EvidenceEnvelope(
            result_id="r_bad",
            metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
            scope=TimeScope(year=2026),
            dimension="customer",
            operation="ranking",
            coverage=Coverage(type="top_n", requested=10, returned=3),
            freshness=Freshness(queried_at=AS_OF),
            payload=payload.model_copy(update={"result_type": "metric_snapshot"}),
        )


def test_derived_fact_requires_calculation() -> None:
    with pytest.raises(ValidationError):
        Fact(
            fact_id="f_bad",
            type="derived_metric",
            name="top2_share",
            value=Decimal("0.8161"),
            unit="ratio",
            scope=TimeScope(year=2026),
            # missing calculation_id and inputs
        )
    with pytest.raises(ValidationError):
        Fact(
            fact_id="f_bad2",
            type="metric_fact",
            name="customer_sales",
            value=Decimal("1"),
            unit="CNY",
            scope=TimeScope(year=2026),
            calculation_id="c_should_not_be_here",
        )


def test_judgement_assertion_requires_rule() -> None:
    with pytest.raises(ValidationError):
        Assertion(
            assertion_id="c_bad",
            type="judgement",
            predicate="classification",
            claim_strength="rule_supported",
            subject={
                "metric": {"metric_id": "finance.customer_sales_ranking", "definition_version": "1.0.0"},
                "scope": {"year": 2026},
            },
            object={"classification": "high_concentration"},
            fact_refs=["f_top2_share"],
            # missing rule_ref
        )


def test_classification_predicate_requires_judgement_type() -> None:
    with pytest.raises(ValidationError):
        Assertion(
            assertion_id="c_bad2",
            type="fact",
            predicate="classification",
            claim_strength="deterministic",
            subject={
                "metric": {"metric_id": "finance.customer_sales_ranking", "definition_version": "1.0.0"},
                "scope": {"year": 2026},
            },
            object={"classification": "high_concentration"},
            fact_refs=["f_top2_share"],
            rule_ref="customer_concentration.high@1.0.0",
        )


def test_plan_dag_rejects_missing_ref() -> None:
    with pytest.raises(ValidationError):
        ResolvedSemanticPlan(
            semantic_plan_id="sp_bad",
            metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
            dimension="customer",
            scope=TimeScope(year=2026),
            as_of=AS_OF,
            operations=[
                OperationSpec(
                    operation_id="op_topn_total",
                    type="topn_total",
                    top_n=10,
                    source_ref="op_ranking",  # missing sibling
                )
            ],
        )


def test_plan_dag_requires_at_least_one_operation() -> None:
    with pytest.raises(ValidationError):
        ResolvedSemanticPlan(
            semantic_plan_id="sp_empty",
            metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
            dimension="customer",
            scope=TimeScope(year=2026),
            as_of=AS_OF,
            operations=[],
        )


def test_ranking_contract_template_licenses_only_ranking() -> None:
    contract = ranking_answer_contract()
    assert contract.answer_type == "ranking"
    assert "classification" in contract.allowed_predicates
    assert "profit" in contract.forbidden_claims
    assert "payment" in contract.forbidden_claims


def test_metric_definition_registered_version() -> None:
    assert RANKING_METRIC.metric_id == "finance.customer_sales_ranking"
    assert RANKING_METRIC.definition_version == "1.0.0"
    assert MetricDefinition(
        metric_id="x",
        definition_version="1.0.0",
        name="x",
        unit="CNY",
        aggregation="sum",
        time_semantics="natural_year",
        granularity="year",
    )
