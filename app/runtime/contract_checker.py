"""AnswerContract enforcement (PR #5, contracts doc §P1.2).

The contract is the licensing policy: the checker only executes it, it never
hard-codes business permissions.  v1 checks:

- ``required_assertion_ids``: the final answer must contain these assertions,
  otherwise the answer is incomplete (MISSING_REQUIRED_ASSERTION);
- ``forbidden_claims``: an assertion whose metric belongs to a forbidden
  business domain is rejected (FORBIDDEN_CLAIM) — e.g. a profit claim under
  the ranking contract, which is Case 11's contract-level gate;
- predicate licensing stays in the StructuralValidator (CONTRACT_VIOLATION).
"""

from __future__ import annotations

from app.runtime.contracts import (
    AnswerContract,
    Assertion,
    ValidationResult,
)
from app.runtime.registry import MetricRegistry

MISSING_REQUIRED_ASSERTION = "MISSING_REQUIRED_ASSERTION"
FORBIDDEN_CLAIM = "FORBIDDEN_CLAIM"
CONTRACT_OK = "CONTRACT_OK"


def _reject(reason_code: str, assertion_id: str | None, action: str) -> ValidationResult:
    return ValidationResult(
        status="rejected",
        stage="structural_claim_validation",
        reason_code=reason_code,
        assertion_id=assertion_id,
        action=action,
    )


class ContractChecker:
    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry.ranking_v1()

    def check(
        self,
        assertions: list[Assertion],
        contract: AnswerContract,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        assertion_ids = {a.assertion_id for a in assertions}

        for required in contract.required_assertion_ids:
            if required not in assertion_ids:
                results.append(
                    _reject(MISSING_REQUIRED_ASSERTION, required, "refetch")
                )

        for assertion in assertions:
            domain = self._metric_domain(assertion.subject.metric.metric_id)
            if domain in contract.forbidden_claims:
                results.append(
                    _reject(FORBIDDEN_CLAIM, assertion.assertion_id, "remove_claim")
                )

        if not results:
            results.append(
                ValidationResult(
                    status="verified",
                    stage="structural_claim_validation",
                    reason_code=CONTRACT_OK,
                    action="none",
                )
            )
        return results

    def _metric_domain(self, metric_id: str) -> str | None:
        definitions = self._registry.find(metric_id)
        if len(definitions) == 1:
            return definitions[0].domain
        return None  # unknown/ambiguous metrics are caught elsewhere
