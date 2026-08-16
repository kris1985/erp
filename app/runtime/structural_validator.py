"""StructuralValidator for the ranking slice (PR #4, contracts doc §P1.5).

100% deterministic structural checks only: contract licensing, metric pinning,
scope equality, evidence refs, fact existence, calculation binding, rank
consistency and coverage sufficiency.  Judgements about causality/risk/support
belong to the Semantic Grounding validator (reserved, not built in v1) and can
never override these results.

Every rejection carries a stable reason code and a recovery action, so the UI
can show exactly which assertion failed and why (contracts §P1.5).
"""

from __future__ import annotations

from app.runtime.contracts import (
    AnswerContract,
    Assertion,
    Calculation,
    EvidenceEnvelope,
    Fact,
    ValidationResult,
)
from app.runtime.coverage import check_ranking_coverage

CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
METRIC_MISMATCH = "METRIC_MISMATCH"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
EVIDENCE_REF_MISSING = "EVIDENCE_REF_MISSING"
FACT_NOT_FOUND = "FACT_NOT_FOUND"
CALCULATION_NOT_FOUND = "CALCULATION_NOT_FOUND"
CALCULATION_BINDING_MISMATCH = "CALCULATION_BINDING_MISMATCH"
RANK_MISMATCH = "RANK_MISMATCH"
COVERAGE_INSUFFICIENT = "COVERAGE_INSUFFICIENT"
STRUCTURAL_VERIFIED = "STRUCTURAL_VERIFIED"


def _reject(
    assertion_id: str,
    reason_code: str,
    *,
    evidence_refs: list[str],
) -> ValidationResult:
    return ValidationResult(
        status="rejected",
        stage="structural_claim_validation",
        reason_code=reason_code,
        assertion_id=assertion_id,
        evidence_refs=evidence_refs,
        action="remove_claim",
    )


class StructuralValidator:
    def validate(
        self,
        assertions: list[Assertion],
        *,
        facts: list[Fact],
        calculations: list[Calculation],
        envelope: EvidenceEnvelope,
        contract: AnswerContract,
    ) -> list[ValidationResult]:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        calcs_by_id = {calc.calculation_id: calc for calc in calculations}
        rows_by_entity = {row.entity_id: row for row in envelope.payload.rows}
        dimension = envelope.dimension

        results: list[ValidationResult] = []
        for assertion in assertions:
            results.append(
                self._validate_one(
                    assertion,
                    facts_by_id=facts_by_id,
                    calcs_by_id=calcs_by_id,
                    rows_by_entity=rows_by_entity,
                    envelope=envelope,
                    contract=contract,
                    dimension=dimension,
                )
            )
        return results

    def _validate_one(
        self,
        assertion: Assertion,
        *,
        facts_by_id: dict[str, Fact],
        calcs_by_id: dict[str, Calculation],
        rows_by_entity: dict[str, object],
        envelope: EvidenceEnvelope,
        contract: AnswerContract,
        dimension: str,
    ) -> ValidationResult:
        refs = assertion.evidence_refs

        if assertion.predicate not in contract.allowed_predicates:
            return _reject(assertion.assertion_id, CONTRACT_VIOLATION, evidence_refs=refs)
        if assertion.subject.metric != envelope.metric:
            return _reject(assertion.assertion_id, METRIC_MISMATCH, evidence_refs=refs)
        if assertion.subject.scope != envelope.scope:
            return _reject(assertion.assertion_id, SCOPE_MISMATCH, evidence_refs=refs)
        if envelope.result_id not in refs:
            return _reject(assertion.assertion_id, EVIDENCE_REF_MISSING, evidence_refs=refs)

        for fact_ref in assertion.fact_refs:
            if fact_ref not in facts_by_id:
                return _reject(assertion.assertion_id, FACT_NOT_FOUND, evidence_refs=refs)

        if assertion.type == "derived":
            calc = calcs_by_id.get(assertion.calculation_ref or "")
            if calc is None:
                return _reject(assertion.assertion_id, CALCULATION_NOT_FOUND, evidence_refs=refs)
            if set(calc.inputs) != set(assertion.fact_refs):
                return _reject(assertion.assertion_id, CALCULATION_BINDING_MISMATCH, evidence_refs=refs)
            value_fact = facts_by_id.get(assertion.object.get("value_fact_ref", ""))
            if value_fact is None or value_fact.calculation_id != calc.calculation_id:
                return _reject(assertion.assertion_id, CALCULATION_BINDING_MISMATCH, evidence_refs=refs)
            if calc.output_fact != value_fact.fact_id:
                return _reject(assertion.assertion_id, CALCULATION_BINDING_MISMATCH, evidence_refs=refs)

        if assertion.predicate == "rank":
            entity_id = assertion.subject.dimensions.get(dimension)
            row = rows_by_entity.get(entity_id) if entity_id else None
            if row is None or getattr(row, "rank") != assertion.object.get("rank"):
                return _reject(assertion.assertion_id, RANK_MISMATCH, evidence_refs=refs)

        if assertion.predicate == "share_of_total":
            verdict = check_ranking_coverage(envelope, need_denominator=True)
            if verdict.status != "verified":
                return _reject(assertion.assertion_id, COVERAGE_INSUFFICIENT, evidence_refs=refs)

        return ValidationResult(
            status="verified",
            stage="structural_claim_validation",
            reason_code=STRUCTURAL_VERIFIED,
            assertion_id=assertion.assertion_id,
            evidence_refs=refs,
            action="none",
        )
