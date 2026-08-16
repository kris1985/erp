"""Business Rule Registry + rule engine tests (PR #5, contracts §P1.4).

Acceptance: “客户集中度较高” comes only from the registered rule on a
complete population with canonical top2_share >= 0.80; no rule -> numeric
facts only, no invented judgement; canonical 0.7996 never trips >= 0.80 even
though it renders as 80.0%; missing population denominator blocks judgement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.runtime.calculation import CalculationEngine
from app.runtime.contracts import (
    Calculation,
    Coverage,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    RoundingPolicy,
    TimeScope,
)
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.rules import (
    BusinessRule,
    BusinessRuleEngine,
    CONCENTRATION_HIGH,
    RuleRegistry,
    rule_ref,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
METRIC = MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0")
SCOPE = TimeScope(year=2026)
ENGINE = CalculationEngine()
RULE_ENGINE = BusinessRuleEngine()


def envelope(
    *,
    rows: list[dict],
    coverage: Coverage | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_005",
        metric=METRIC,
        scope=SCOPE,
        dimension="customer",
        operation="ranking",
        coverage=coverage
        or Coverage(
            type="complete_population",
            requested=len(rows),
            returned=len(rows),
            population_complete=True,
            population_size=len(rows),
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        payload={"result_type": "ranking", "rows": rows, "execution_ref": "metric_exec_9305"},
    )


def share_chain(
    rows: list[dict],
    total: str,
    coverage: Coverage | None = None,
) -> tuple[EvidenceEnvelope, list[Fact], list[Calculation]]:
    env = envelope(rows=rows, coverage=coverage)
    built = RankingFactBuilder().build(env)
    top2 = built.facts[:2]
    total_fact = Fact(
        fact_id="f_total_sales",
        type="metric_fact",
        name="客户销售额",
        value=Decimal(total),
        unit="CNY",
        scope=SCOPE,
        evidence_refs=["r_005_total"],
    )
    _, top2_fact = ENGINE.compute(
        "topn_total", top2, calculation_id="c_top2_total", output_fact_id="c_top2_total"
    )
    calc, share_fact = ENGINE.compute(
        "share_of_total",
        [top2_fact, total_fact],
        calculation_id="c_top2_share",
        output_fact_id="c_top2_share",
    )
    return env, built.facts + [top2_fact, share_fact, total_fact], [calc]


HIGH_ROWS = [
    {"entity_id": "customer:A", "entity_label": "客户 A", "value": "60000000", "unit": "CNY", "rank": 1},
    {"entity_id": "customer:B", "entity_label": "客户 B", "value": "30000000", "unit": "CNY", "rank": 2},
    {"entity_id": "customer:C", "entity_label": "客户 C", "value": "5000000", "unit": "CNY", "rank": 3},
    {"entity_id": "customer:D", "entity_label": "客户 D", "value": "5000000", "unit": "CNY", "rank": 4},
]  # top2 = 0.90

MID_ROWS = [
    {"entity_id": "customer:A", "entity_label": "客户 A", "value": "12350000", "unit": "CNY", "rank": 1},
    {"entity_id": "customer:B", "entity_label": "客户 B", "value": "9800000", "unit": "CNY", "rank": 2},
    {"entity_id": "customer:C", "entity_label": "客户 C", "value": "7600000", "unit": "CNY", "rank": 3},
    {"entity_id": "customer:D", "entity_label": "客户 D", "value": "4500000", "unit": "CNY", "rank": 4},
]  # top2 = 0.6467

BORDER_ROWS = [
    {"entity_id": "customer:A", "entity_label": "客户 A", "value": "7996000", "unit": "CNY", "rank": 1},
    {"entity_id": "customer:B", "entity_label": "客户 B", "value": "0", "unit": "CNY", "rank": 2},
    {"entity_id": "customer:C", "entity_label": "客户 C", "value": "0", "unit": "CNY", "rank": 3},
]  # top2 / total = 0.7996 (renders as 80.0%)


def test_rule_hit_produces_judgement() -> None:
    env, facts, calcs = share_chain(HIGH_ROWS, "100000000")
    judgements = RULE_ENGINE.apply_judgements(envelope=env, facts=facts, calculations=calcs)
    assert len(judgements) == 1
    j = judgements[0]
    assert j.type == "judgement"
    assert j.predicate == "classification"
    assert j.claim_strength == "rule_supported"
    assert j.rule_ref == "customer_concentration.high@1.0.0"
    assert j.object == {"classification": "客户集中度较高"}
    assert j.fact_refs == ["c_top2_share"]
    assert j.evidence_refs == ["r_005"]
    assert j.confidence == 1.0


def test_no_rule_hit_states_facts_without_judgement() -> None:
    env, facts, calcs = share_chain(MID_ROWS, "34250000")
    judgements = RULE_ENGINE.apply_judgements(envelope=env, facts=facts, calculations=calcs)
    assert judgements == []


def test_canonical_boundary_below_threshold_no_judgement() -> None:
    """0.7996 canonical must NOT hit >= 0.80 even though it renders as 80.0%."""
    env, facts, calcs = share_chain(BORDER_ROWS, "10000000")
    share_fact = next(f for f in facts if f.fact_id == "c_top2_share")
    assert share_fact.value == Decimal("0.799600000000")
    assert share_fact.value < Decimal("0.80")
    judgements = RULE_ENGINE.apply_judgements(envelope=env, facts=facts, calculations=calcs)
    assert judgements == []


def test_exactly_threshold_hits() -> None:
    rows = [
        {"entity_id": "customer:A", "entity_label": "客户 A", "value": "8000000", "unit": "CNY", "rank": 1},
        {"entity_id": "customer:B", "entity_label": "客户 B", "value": "0", "unit": "CNY", "rank": 2},
        {"entity_id": "customer:C", "entity_label": "客户 C", "value": "0", "unit": "CNY", "rank": 3},
    ]
    env, facts, calcs = share_chain(rows, "10000000")
    judgements = RULE_ENGINE.apply_judgements(envelope=env, facts=facts, calculations=calcs)
    assert len(judgements) == 1


def test_missing_denominator_blocks_judgement() -> None:
    """Case 10 semantics: Top-N without population total -> no judgement,
    regardless of the share value."""
    top3_only = Coverage(
        type="top_n",
        requested=10,
        returned=3,
        population_complete=False,
        denominator_available=False,
    )
    env, facts, calcs = share_chain(HIGH_ROWS, "100000000", coverage=top3_only)
    judgements = RULE_ENGINE.apply_judgements(envelope=env, facts=facts, calculations=calcs)
    assert judgements == []


def test_registry_lookup_and_versioning() -> None:
    registry = RuleRegistry()
    assert registry.get("customer_concentration.high@1.0.0") is CONCENTRATION_HIGH
    assert registry.get("customer_concentration.high@2.0.0") is None
    assert registry.rules_for(METRIC, "share_of_total") == [CONCENTRATION_HIGH]
    assert registry.rules_for(METRIC, "period_change") == []
    # A threshold change must be a new rule version, never an in-place edit.
    v2 = CONCENTRATION_HIGH.model_copy(
        update={"version": "2.0.0", "threshold": Decimal("0.90")}
    )
    registry2 = RuleRegistry([CONCENTRATION_HIGH, v2])
    assert registry2.get("customer_concentration.high@2.0.0") is v2
    assert rule_ref(v2) == "customer_concentration.high@2.0.0"
