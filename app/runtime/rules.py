"""Business Rule Registry + rule engine for the ranking slice (PR #5,
contracts doc §P1.4).

v1 implements exactly one registered rule —
``customer_concentration.high@1.0.0`` — and no generic rule platform.  The
rule engine only carries deterministic business policy (threshold /
classification); attribution, root-cause and open diagnosis stay out of the
registry.  A judgement is produced only when the evidence is a complete
population (or an explicit denominator is available) AND the canonical
``top2_share`` meets the threshold — canonical values only, so a rendered
80.0% never trips an ``>= 0.80`` rule that canonical 0.7996 does not meet.

Without an applicable rule the engine stays silent: numeric facts may be
stated, but no deterministic business judgement is invented.
"""

from __future__ import annotations

from decimal import Decimal

from app.runtime.contracts import (
    Assertion,
    AssertionSubject,
    Calculation,
    EvidenceEnvelope,
    Fact,
    MetricRef,
    RuntimeModel,
)
from app.runtime.coverage import check_ranking_coverage


class BusinessRule(RuntimeModel):
    rule_id: str
    version: str
    metric: MetricRef
    input_fact: str  # derived fact name this rule reads (e.g. "share_of_total")
    threshold: Decimal  # canonical threshold
    output_judgement: str
    description: str


CONCENTRATION_HIGH = BusinessRule(
    rule_id="customer_concentration.high",
    version="1.0.0",
    metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
    input_fact="share_of_total",
    threshold=Decimal("0.80"),
    output_judgement="客户集中度较高",
    description="完整总体下前两名占比 >= 0.80 判定客户集中度较高",
)


class RuleRegistry:
    def __init__(self, rules: list[BusinessRule] | None = None) -> None:
        self._rules: dict[str, BusinessRule] = {
            rule_ref(rule): rule for rule in (rules if rules is not None else [CONCENTRATION_HIGH])
        }

    def get(self, rule_ref: str) -> BusinessRule | None:
        return self._rules.get(rule_ref)

    def rules_for(self, metric: MetricRef, input_fact: str) -> list[BusinessRule]:
        return [
            rule
            for rule in self._rules.values()
            if rule.metric == metric and rule.input_fact == input_fact
        ]

    @classmethod
    def ranking_v1(cls) -> "RuleRegistry":
        return cls([CONCENTRATION_HIGH])


def rule_ref(rule: BusinessRule) -> str:
    return f"{rule.rule_id}@{rule.version}"


class BusinessRuleEngine:
    """Applies registered deterministic rules to the verified fact set."""

    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self._registry = registry or RuleRegistry.ranking_v1()

    def apply_judgements(
        self,
        *,
        envelope: EvidenceEnvelope,
        facts: list[Fact],
        calculations: list[Calculation],
    ) -> list[Assertion]:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        judgements: list[Assertion] = []

        for calculation in calculations:
            if calculation.definition != "share_of_total":
                continue
            share_fact = facts_by_id.get(calculation.output_fact)
            if share_fact is None:  # pragma: no cover - chain incomplete
                continue
            rules = self._registry.rules_for(envelope.metric, calculation.definition)
            for rule in rules:
                if self._evaluate(envelope, rule, share_fact):
                    judgements.append(
                        self._build_judgement(envelope, rule, share_fact)
                    )
        return judgements

    @staticmethod
    def _evaluate(
        envelope: EvidenceEnvelope,
        rule: BusinessRule,
        share_fact: Fact,
    ) -> bool:
        # Evidence must prove the population: a Top-N without a denominator
        # can never produce a concentration judgement (Case 10 gate).
        verdict = check_ranking_coverage(envelope, need_denominator=True)
        if verdict.status != "verified":
            return False
        # Canonical comparison only.
        return share_fact.value >= rule.threshold

    @staticmethod
    def _build_judgement(
        envelope: EvidenceEnvelope,
        rule: BusinessRule,
        share_fact: Fact,
    ) -> Assertion:
        return Assertion(
            assertion_id="a_concentration",
            type="judgement",
            predicate="classification",
            claim_strength="rule_supported",
            subject=AssertionSubject(metric=envelope.metric, scope=envelope.scope),
            object={"classification": rule.output_judgement},
            fact_refs=[share_fact.fact_id],
            rule_ref=rule_ref(rule),
            evidence_refs=[envelope.result_id],
            confidence=1.0,
        )
