"""AssertionBuilder + StructuralValidator tests (PR #4, contracts §P1.3/§P1.5).

Acceptance: every verifiable claim answers “which facts, which
calculation/rule, which evidence result”; structural checks are 100%
deterministic; a profit-flavoured claim cannot leak through the ranking
contract (Case 11 semantics).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import CalculationEngine
from app.runtime.contracts import (
    Assertion,
    AssertionSubject,
    Calculation,
    Coverage,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    RoundingPolicy,
    TimeScope,
    ValidationResult,
    ranking_answer_contract,
)
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.structural_validator import (
    CALCULATION_BINDING_MISMATCH,
    CALCULATION_NOT_FOUND,
    CONTRACT_VIOLATION,
    COVERAGE_INSUFFICIENT,
    EVIDENCE_REF_MISSING,
    FACT_NOT_FOUND,
    METRIC_MISMATCH,
    RANK_MISMATCH,
    SCOPE_MISMATCH,
    STRUCTURAL_VERIFIED,
    StructuralValidator,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
METRIC = MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0")
SCOPE = TimeScope(year=2026)
BUILDER = AssertionBuilder()
STRUCTURAL = StructuralValidator()
CONTRACT = ranking_answer_contract()
ENGINE = CalculationEngine()
FACT_BUILDER = RankingFactBuilder()


def envelope(
    *,
    rows: list[dict] | None = None,
    coverage: Coverage | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_004",
        metric=METRIC,
        scope=SCOPE,
        dimension="customer",
        operation="ranking",
        coverage=coverage
        or Coverage(
            type="complete_population",
            requested=4,
            returned=4,
            population_complete=True,
            population_size=4,
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        payload={
            "result_type": "ranking",
            "rows": rows
            or [
                {"entity_id": "customer:A", "entity_label": "客户 A", "value": "12350000", "unit": "CNY", "rank": 1},
                {"entity_id": "customer:B", "entity_label": "客户 B", "value": "9800000", "unit": "CNY", "rank": 2},
                {"entity_id": "customer:C", "entity_label": "客户 C", "value": "7600000", "unit": "CNY", "rank": 3},
            ],
            "execution_ref": "metric_exec_9304",
        },
    )


def build_chain() -> tuple[EvidenceEnvelope, list[Fact], list[Calculation]]:
    env = envelope()
    built = FACT_BUILDER.build(env)
    top2 = [built.facts[0], built.facts[1]]
    total = Fact(
        fact_id="f_total_sales",
        type="metric_fact",
        name="客户销售额",
        value=Decimal("34250000"),
        unit="CNY",
        scope=SCOPE,
        evidence_refs=["r_004_total"],
    )
    _, top2_fact = ENGINE.compute(
        "topn_total", top2, calculation_id="c_top2_total", output_fact_id="c_top2_total"
    )
    calc, share_fact = ENGINE.compute(
        "share_of_total",
        [top2_fact, total],
        calculation_id="c_top2_share",
        output_fact_id="c_top2_share",
    )
    all_facts = built.facts + [top2_fact, share_fact, total]
    return env, all_facts, [calc]


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------


def test_builder_generates_value_and_rank_per_row() -> None:
    env, facts, _ = build_chain()
    assertions = BUILDER.build(envelope=env, facts=facts, calculations=[])
    assert [a.predicate for a in assertions] == [
        "value", "rank", "value", "rank", "value", "rank",
    ]
    rank_a = next(a for a in assertions if a.assertion_id == "a_rank_customer:A")
    assert rank_a.object == {"rank": 1, "value_fact_ref": "r_004:customer:A"}
    assert rank_a.type == "fact"
    assert rank_a.claim_strength == "deterministic"
    assert rank_a.subject.metric == METRIC
    assert rank_a.subject.dimensions == {"customer": "customer:A"}
    assert rank_a.subject.scope == SCOPE
    assert rank_a.evidence_refs == ["r_004"]


def test_builder_generates_share_assertion_bound_to_calculation() -> None:
    env, facts, calcs = build_chain()
    assertions = BUILDER.build(envelope=env, facts=facts, calculations=calcs)
    share = next(a for a in assertions if a.predicate == "share_of_total")
    assert share.assertion_id == "a_share"
    assert share.type == "derived"
    assert share.object == {
        "value_fact_ref": "c_top2_share",
        "numerator_ref": "c_top2_total",
        "denominator_ref": "f_total_sales",
    }
    assert share.fact_refs == ["c_top2_total", "f_total_sales"]
    assert share.calculation_ref == "c_top2_share"
    assert share.evidence_refs == ["r_004"]


def test_builder_entity_label_selects_single_row() -> None:
    env = envelope(
        rows=[
            {"entity_id": "customer:A", "entity_label": "客户 A", "value": "1", "unit": "CNY", "rank": 1},
            {"entity_id": "customer:XM", "entity_label": "厦门海丝", "value": "2", "unit": "CNY", "rank": 2},
        ]
    )
    built = FACT_BUILDER.build(env)
    assertions = BUILDER.build(
        envelope=env, facts=built.facts, calculations=[], entity_label="厦门海丝"
    )
    assert [a.assertion_id for a in assertions] == [
        "a_value_customer:XM",
        "a_rank_customer:XM",
    ]
    assert assertions[1].object == {"rank": 2, "value_fact_ref": "r_004:customer:XM"}


def test_builder_assertion_ids_are_deterministic() -> None:
    env, facts, calcs = build_chain()
    a1 = BUILDER.build(envelope=env, facts=facts, calculations=calcs)
    a2 = BUILDER.build(envelope=env, facts=facts, calculations=calcs)
    assert [a.assertion_id for a in a1] == [a.assertion_id for a in a2]


# --------------------------------------------------------------------------
# Structural validator
# --------------------------------------------------------------------------


def test_validator_accepts_clean_chain() -> None:
    env, facts, calcs = build_chain()
    assertions = BUILDER.build(envelope=env, facts=facts, calculations=calcs)
    verdicts = STRUCTURAL.validate(
        assertions, facts=facts, calculations=calcs, envelope=env, contract=CONTRACT
    )
    assert len(verdicts) == len(assertions)
    for verdict in verdicts:
        assert verdict.status == "verified"
        assert verdict.reason_code == STRUCTURAL_VERIFIED
        assert verdict.stage == "structural_claim_validation"


def test_contract_violation_on_unlicensed_predicate() -> None:
    """A predicate inside the enum but not licensed by the (thin) contract is
    rejected with CONTRACT_VIOLATION — the validator only executes the policy."""
    env, facts, _ = build_chain()
    restricted = ranking_answer_contract()
    restricted = restricted.model_copy(
        update={"allowed_predicates": ["value", "rank"]}
    )
    assertion = Assertion(
        assertion_id="a_share_unlicensed",
        type="derived",
        predicate="share_of_total",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={
            "value_fact_ref": "c_top2_share",
            "numerator_ref": "c_top2_total",
            "denominator_ref": "f_total_sales",
        },
        fact_refs=["c_top2_total", "f_total_sales"],
        calculation_ref="c_top2_share",
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=restricted
    )
    assert verdicts[0].reason_code == CONTRACT_VIOLATION


def test_profit_metric_claim_rejected_as_metric_mismatch() -> None:
    """Case 11 semantics: a profit-flavoured claim cannot ride the ranking
    contract — its metric is not the ranking metric, so it is rejected."""
    env, facts, _ = build_chain()
    profit = Assertion(
        assertion_id="a_profit",
        type="fact",
        predicate="value",
        claim_strength="deterministic",
        subject=AssertionSubject(
            metric=MetricRef(metric_id="finance.net_profit", definition_version="1.0.0"),
            dimensions={"customer": "customer:A"},
            scope=SCOPE,
        ),
        object={"value_fact_ref": "f_profit_a"},
        fact_refs=["f_profit_a"],
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [profit], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].status == "rejected"
    assert verdicts[0].reason_code == METRIC_MISMATCH


def test_scope_mismatch_rejected() -> None:
    env, facts, _ = build_chain()
    assertion = Assertion(
        assertion_id="a_wrong_year",
        type="fact",
        predicate="value",
        claim_strength="deterministic",
        subject=AssertionSubject(
            metric=METRIC, dimensions={"customer": "customer:A"}, scope=TimeScope(year=2025)
        ),
        object={"value_fact_ref": "r_004:customer:A"},
        fact_refs=["r_004:customer:A"],
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == SCOPE_MISMATCH


def test_missing_fact_rejected() -> None:
    env, facts, _ = build_chain()
    assertion = Assertion(
        assertion_id="a_ghost",
        type="fact",
        predicate="value",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, dimensions={"customer": "customer:A"}, scope=SCOPE),
        object={"value_fact_ref": "ghost_fact"},
        fact_refs=["ghost_fact"],
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == FACT_NOT_FOUND


def test_missing_evidence_ref_rejected() -> None:
    env, facts, _ = build_chain()
    assertion = Assertion(
        assertion_id="a_no_evidence",
        type="fact",
        predicate="value",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, dimensions={"customer": "customer:A"}, scope=SCOPE),
        object={"value_fact_ref": "r_004:customer:A"},
        fact_refs=["r_004:customer:A"],
        evidence_refs=["r_other"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == EVIDENCE_REF_MISSING


def test_rank_mismatch_rejected() -> None:
    env, facts, _ = build_chain()
    assertion = Assertion(
        assertion_id="a_rank_wrong",
        type="fact",
        predicate="rank",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, dimensions={"customer": "customer:A"}, scope=SCOPE),
        object={"rank": 99, "value_fact_ref": "r_004:customer:A"},
        fact_refs=["r_004:customer:A"],
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == RANK_MISMATCH


def test_derived_missing_calculation_rejected() -> None:
    env, facts, _ = build_chain()
    share_fact = next(f for f in facts if f.fact_id == "c_top2_share")
    assertion = Assertion(
        assertion_id="a_share_bad",
        type="derived",
        predicate="share_of_total",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={
            "value_fact_ref": "c_top2_share",
            "numerator_ref": "c_top2_total",
            "denominator_ref": "f_total_sales",
        },
        fact_refs=["c_top2_total", "f_total_sales"],
        calculation_ref="c_does_not_exist",
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=[], envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == CALCULATION_NOT_FOUND


def test_derived_binding_mismatch_rejected() -> None:
    env, facts, calcs = build_chain()
    assertion = Assertion(
        assertion_id="a_share_bad",
        type="derived",
        predicate="share_of_total",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={
            "value_fact_ref": "c_top2_share",
            "numerator_ref": "c_top2_total",
            "denominator_ref": "f_total_sales",
        },
        fact_refs=["c_top2_total"],  # denominator dropped -> binding mismatch
        calculation_ref="c_top2_share",
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion], facts=facts, calculations=calcs, envelope=env, contract=CONTRACT
    )
    assert verdicts[0].reason_code == CALCULATION_BINDING_MISMATCH


def test_share_without_denominator_rejected_by_coverage() -> None:
    top3_only = Coverage(
        type="top_n",
        requested=10,
        returned=3,
        population_complete=False,
        denominator_available=False,
    )
    env = envelope(coverage=top3_only)
    built = FACT_BUILDER.build(env)
    top_fact = Fact(
        fact_id="c_top",
        type="derived_metric",
        name="topn_total",
        value=Decimal("22150000"),
        unit="CNY",
        scope=SCOPE,
        calculation_id="c_top",
        inputs=[f.fact_id for f in built.facts],
    )
    total_fact = Fact(
        fact_id="f_total",
        type="metric_fact",
        name="客户销售额",
        value=Decimal("34250000"),
        unit="CNY",
        scope=SCOPE,
    )
    share_fact = Fact(
        fact_id="c_share",
        type="derived_metric",
        name="share_of_total",
        value=Decimal("0.5"),
        unit="ratio",
        scope=SCOPE,
        calculation_id="c_share",
        inputs=["c_top", "f_total"],
    )
    assertion = Assertion(
        assertion_id="a_share",
        type="derived",
        predicate="share_of_total",
        claim_strength="deterministic",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={
            "value_fact_ref": "c_share",
            "numerator_ref": "c_top",
            "denominator_ref": "f_total",
        },
        fact_refs=["c_top", "f_total"],
        calculation_ref="c_share",
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        [assertion],
        facts=built.facts + [top_fact, total_fact, share_fact],
        calculations=[
            Calculation(
                calculation_id="c_share",
                definition="share_of_total",
                inputs=["c_top", "f_total"],
                output_fact="c_share",
                formula="numerator / denominator",
                rounding=RoundingPolicy(precision=12, mode="half_up"),
            )
        ],
        envelope=env,
        contract=CONTRACT,
    )
    assert verdicts[0].status == "rejected"
    assert verdicts[0].reason_code == COVERAGE_INSUFFICIENT


def test_validator_rejects_all_or_none_per_assertion() -> None:
    """One bad assertion must not poison the verdicts of the good ones."""
    env, facts, calcs = build_chain()
    good = BUILDER.build(envelope=env, facts=facts, calculations=calcs)
    restricted = ranking_answer_contract().model_copy(
        update={"allowed_predicates": ["value", "rank", "share_of_total"]}
    )
    bad = Assertion(
        assertion_id="a_bad",
        type="judgement",
        predicate="classification",
        claim_strength="rule_supported",
        subject=AssertionSubject(metric=METRIC, dimensions={"customer": "customer:A"}, scope=SCOPE),
        object={"classification": "high_concentration"},
        fact_refs=["r_004:customer:A"],
        rule_ref="customer_concentration.high@1.0.0",
        evidence_refs=["r_004"],
    )
    verdicts = STRUCTURAL.validate(
        good + [bad], facts=facts, calculations=calcs, envelope=env, contract=restricted
    )
    by_id = {v.assertion_id: v for v in verdicts}
    assert all(v.status == "verified" for a in good for v in [by_id[a.assertion_id]])
    assert by_id["a_bad"].reason_code == CONTRACT_VIOLATION
