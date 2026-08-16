"""AssertionBuilder for the ranking + metric_snapshot slices (PR #4, §P1.3).

The main chain derives assertions mechanically from the Typed Result and the
calculation chain — never by asking the LLM to re-read the answer afterwards.
Predicates follow the analysis atom, not the user's phrasing:

- ranking: one ``value`` + one ``rank`` assertion per ranking row;
- metric_snapshot: one ``value`` assertion for the scalar total (no rank);
- one ``share_of_total`` assertion per registered ``share_of_total``
  calculation (derived claim, bound to its calculation);
- ``classification`` (judgement) is left to PR #5's business rule.

``entity_label`` selects a single row (Case 6: “厦门海丝排第几?”).  Assertion
ids are deterministic so the same input replays to the same trace.
"""

from __future__ import annotations

from app.runtime.contracts import (
    Assertion,
    AssertionSubject,
    Calculation,
    EvidenceEnvelope,
    Fact,
)


class AssertionBuilder:
    def build(
        self,
        *,
        envelope: EvidenceEnvelope,
        facts: list[Fact],
        calculations: list[Calculation],
        entity_label: str | None = None,
    ) -> list[Assertion]:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        assertions: list[Assertion] = []
        dimension = envelope.dimension

        if envelope.operation == "metric_snapshot":
            snapshot = envelope.payload.snapshot_value
            if snapshot is not None:
                fact = facts_by_id.get(f"{envelope.result_id}:total")
                if fact is not None:
                    assertions.append(
                        Assertion(
                            assertion_id="a_snapshot_value",
                            type="fact",
                            predicate="value",
                            claim_strength="deterministic",
                            subject=AssertionSubject(
                                metric=envelope.metric,
                                scope=envelope.scope,
                            ),
                            object={"value_fact_ref": fact.fact_id, "unit": fact.unit},
                            fact_refs=[fact.fact_id],
                            evidence_refs=[envelope.result_id],
                        )
                    )
            return assertions

        for row in envelope.payload.rows:
            if entity_label is not None and row.entity_label != entity_label:
                continue
            fact = facts_by_id.get(f"{envelope.result_id}:{row.entity_id}")
            if fact is None:  # pragma: no cover - caller must build facts first
                continue
            subject = AssertionSubject(
                metric=envelope.metric,
                dimensions={dimension: row.entity_id},
                scope=envelope.scope,
            )
            assertions.append(
                Assertion(
                    assertion_id=f"a_value_{row.entity_id}",
                    type="fact",
                    predicate="value",
                    claim_strength="deterministic",
                    subject=subject,
                    object={"value_fact_ref": fact.fact_id, "unit": fact.unit},
                    fact_refs=[fact.fact_id],
                    evidence_refs=[envelope.result_id],
                )
            )
            assertions.append(
                Assertion(
                    assertion_id=f"a_rank_{row.entity_id}",
                    type="fact",
                    predicate="rank",
                    claim_strength="deterministic",
                    subject=subject,
                    object={"rank": row.rank, "value_fact_ref": fact.fact_id},
                    fact_refs=[fact.fact_id],
                    evidence_refs=[envelope.result_id],
                )
            )

        for calculation in calculations:
            if calculation.definition != "share_of_total":
                continue
            numerator_ref, denominator_ref = calculation.inputs
            share_fact = facts_by_id.get(calculation.output_fact)
            if share_fact is None:  # pragma: no cover - calculation chain incomplete
                continue
            subject = AssertionSubject(
                metric=envelope.metric,
                scope=envelope.scope,
            )
            assertions.append(
                Assertion(
                    assertion_id="a_share",
                    type="derived",
                    predicate="share_of_total",
                    claim_strength="deterministic",
                    subject=subject,
                    object={
                        "value_fact_ref": share_fact.fact_id,
                        "numerator_ref": numerator_ref,
                        "denominator_ref": denominator_ref,
                    },
                    fact_refs=[numerator_ref, denominator_ref],
                    calculation_ref=calculation.calculation_id,
                    evidence_refs=[envelope.result_id],
                )
            )
        return assertions
