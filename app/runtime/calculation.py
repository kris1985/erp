"""Calculation Engine + independent validator for the ranking slice (PR #3).

Generation and validation are separate code paths (contracts doc §P1.1): the
engine produces derived facts from *registered* definitions; the validator
recomputes from the same registered definition — never from the engine's own
output — so a tampered output, input, formula or rounding policy fails with a
stable reason code.

Canonical values are full-precision Decimals (fixed scale per definition);
display rounding never touches them, so a business rule reading canonical
0.7996 never hits an ``>= 0.80`` threshold even if rendered as 80.0%.

v1 registers exactly two definitions (slice doc §2.3): ``topn_total`` and
``share_of_total``. New calculations extend the registry — the engine does not
change.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from functools import reduce
from operator import add
from typing import Literal

from app.runtime.contracts import (
    Calculation,
    DisplaySpec,
    Fact,
    RoundingPolicy,
    RuntimeModel,
    TimeScope,
    ValidationResult,
)

DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
NO_INPUT_FACTS = "NO_INPUT_FACTS"
INPUT_LINEAGE_MISMATCH = "INPUT_LINEAGE_MISMATCH"
UNIT_MISMATCH = "UNIT_MISMATCH"
UNKNOWN_CALCULATION_DEFINITION = "UNKNOWN_CALCULATION_DEFINITION"
FORMULA_MISMATCH = "FORMULA_MISMATCH"
ROUNDING_POLICY_MISMATCH = "ROUNDING_POLICY_MISMATCH"
CALCULATION_MISMATCH = "CALCULATION_MISMATCH"
CALCULATION_VERIFIED = "CALCULATION_VERIFIED"

RATIO_SCALE = Decimal("0.000000000001")  # canonical ratio precision: 12 dp


class CalculationError(Exception):
    """Raised by the engine's generate side with a stable reason code."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CalculationDefinition:
    """One registered calculation: generation and verification are two
    independent code paths over the same inputs."""

    definition_id: str
    formula: str
    allowed_rounding: RoundingPolicy
    output_name: str
    output_scale: Decimal  # canonical scale for the output value
    output_unit: str
    output_display: DisplaySpec

    # Generate side.
    def compute(self, inputs: list[Fact]) -> Decimal:  # pragma: no cover - overridden
        raise NotImplementedError

    # Independent verification side (recomputes, never trusts engine output).
    def verify(self, inputs: list[Fact]) -> Decimal:  # pragma: no cover - overridden
        raise NotImplementedError

    def _check_inputs(self, inputs: list[Fact], *, expected_count: int | None) -> None:
        if not inputs:
            raise CalculationError(NO_INPUT_FACTS, "no input facts")
        if expected_count is not None and len(inputs) != expected_count:
            raise CalculationError(
                INPUT_LINEAGE_MISMATCH,
                f"{self.definition_id} expects {expected_count} inputs, got {len(inputs)}",
            )


class TopNTotalDefinition(CalculationDefinition):
    def __init__(self) -> None:
        super().__init__(
            definition_id="topn_total",
            formula="sum(inputs)",
            allowed_rounding=RoundingPolicy(precision=0, mode="half_up"),
            output_name="topn_total",
            output_scale=Decimal("1"),
            output_unit="",  # unit mirrors the input rows (validated below)
            output_display=DisplaySpec(scale=0, format="currency"),
        )

    def _check_units(self, inputs: list[Fact]) -> str:
        self._check_inputs(inputs, expected_count=None)
        unit = inputs[0].unit
        if any(f.unit != unit for f in inputs):
            raise CalculationError(UNIT_MISMATCH, "topn_total inputs must share one unit")
        return unit

    def compute(self, inputs: list[Fact]) -> Decimal:
        self._check_units(inputs)
        return sum((f.value for f in inputs), Decimal("0"))

    def verify(self, inputs: list[Fact]) -> Decimal:
        self._check_units(inputs)
        # Second, independent recompute path (fold instead of builtin sum).
        return reduce(add, (f.value for f in inputs))


class ShareOfTotalDefinition(CalculationDefinition):
    def __init__(self) -> None:
        super().__init__(
            definition_id="share_of_total",
            formula="numerator / denominator",
            allowed_rounding=RoundingPolicy(precision=12, mode="half_up"),
            output_name="share_of_total",
            output_scale=RATIO_SCALE,
            output_unit="ratio",
            output_display=DisplaySpec(scale=1, format="percent"),
        )

    def _inputs(self, inputs: list[Fact]) -> tuple[Fact, Fact]:
        self._check_inputs(inputs, expected_count=2)
        numerator, denominator = inputs[0], inputs[1]
        if numerator.unit != denominator.unit:
            raise CalculationError(UNIT_MISMATCH, "numerator and denominator must share a unit")
        if denominator.value == 0:
            raise CalculationError(DIVISION_BY_ZERO, "denominator is zero")
        return numerator, denominator

    def compute(self, inputs: list[Fact]) -> Decimal:
        numerator, denominator = self._inputs(inputs)
        with localcontext() as ctx:
            ctx.prec = 40
            return (numerator.value / denominator.value).quantize(RATIO_SCALE, rounding=ROUND_HALF_UP)

    def verify(self, inputs: list[Fact]) -> Decimal:
        numerator, denominator = self._inputs(inputs)
        # Second, independent recompute path with its own division.
        with localcontext() as ctx:
            ctx.prec = 40
            ratio = denominator.value ** -1 * numerator.value
            return ratio.quantize(RATIO_SCALE, rounding=ROUND_HALF_UP)


class CalculationRegistry:
    def __init__(self, definitions: list[CalculationDefinition] | None = None) -> None:
        self._by_id: dict[str, CalculationDefinition] = {
            definition.definition_id: definition
            for definition in (definitions if definitions is not None else [TopNTotalDefinition(), ShareOfTotalDefinition()])
        }

    def get(self, definition_id: str) -> CalculationDefinition:
        try:
            return self._by_id[definition_id]
        except KeyError as exc:
            raise CalculationError(UNKNOWN_CALCULATION_DEFINITION, definition_id) from exc

    def definitions(self) -> list[CalculationDefinition]:
        return list(self._by_id.values())

    @classmethod
    def ranking_v1(cls) -> "CalculationRegistry":
        return cls([TopNTotalDefinition(), ShareOfTotalDefinition()])


class CalculationEngine:
    """Generate side: registered definitions only, deterministic outputs."""

    def __init__(self, registry: CalculationRegistry | None = None) -> None:
        self._registry = registry or CalculationRegistry.ranking_v1()

    def compute(
        self,
        definition_id: str,
        inputs: list[Fact],
        *,
        calculation_id: str,
        output_fact_id: str,
    ) -> tuple[Calculation, Fact]:
        definition = self._registry.get(definition_id)
        value = definition.compute(inputs)
        if definition.output_unit == "":
            unit = inputs[0].unit
        else:
            unit = definition.output_unit
        evidence_refs = sorted({ref for fact in inputs for ref in fact.evidence_refs})
        scope = inputs[0].scope
        calculation = Calculation(
            calculation_id=calculation_id,
            definition=definition.definition_id,
            inputs=[fact.fact_id for fact in inputs],
            output_fact=output_fact_id,
            formula=definition.formula,
            rounding=definition.allowed_rounding,
        )
        fact = Fact(
            fact_id=output_fact_id,
            type="derived_metric",
            name=definition.output_name,
            value=value,
            unit=unit,
            display=definition.output_display,
            scope=scope,
            source="calculation_engine",
            evidence_refs=evidence_refs,
            calculation_id=calculation_id,
            inputs=[fact.fact_id for fact in inputs],
        )
        return calculation, fact


class IndependentCalculationValidator:
    """Verify side: recomputes from the registered definition and checks
    lineage, formula, rounding policy, units and the claimed canonical value."""

    def __init__(self, registry: CalculationRegistry | None = None) -> None:
        self._registry = registry or CalculationRegistry.ranking_v1()

    def verify(
        self,
        calculation: Calculation,
        inputs: list[Fact],
        claimed_output: Fact,
    ) -> ValidationResult:
        refs = [claimed_output.fact_id]

        try:
            definition = self._registry.get(calculation.definition)
        except CalculationError as exc:
            return self._reject(exc.reason_code, claimed_output, refs)

        if set(calculation.inputs) != {fact.fact_id for fact in inputs}:
            return self._reject(INPUT_LINEAGE_MISMATCH, claimed_output, refs)
        if calculation.formula != definition.formula:
            return self._reject(FORMULA_MISMATCH, claimed_output, refs)
        if calculation.rounding != definition.allowed_rounding:
            return self._reject(ROUNDING_POLICY_MISMATCH, claimed_output, refs)

        try:
            expected = definition.verify(inputs)
        except CalculationError as exc:
            return self._reject(exc.reason_code, claimed_output, refs)

        expected_unit = definition.output_unit if definition.output_unit else inputs[0].unit
        if claimed_output.unit != expected_unit:
            return self._reject(UNIT_MISMATCH, claimed_output, refs)
        if claimed_output.value != expected:
            return ValidationResult(
                status="rejected",
                stage="calculation_validation",
                reason_code=CALCULATION_MISMATCH,
                assertion_id=None,
                expected={"value": str(expected)},
                actual={"value": str(claimed_output.value)},
                evidence_refs=refs,
                action="recalculate",
            )
        if claimed_output.display != definition.output_display:
            return self._reject(ROUNDING_POLICY_MISMATCH, claimed_output, refs)
        return ValidationResult(
            status="verified",
            stage="calculation_validation",
            reason_code=CALCULATION_VERIFIED,
            evidence_refs=refs,
            action="none",
        )

    @staticmethod
    def _reject(
        reason_code: str,
        claimed_output: Fact,
        refs: list[str],
    ) -> ValidationResult:
        return ValidationResult(
            status="rejected",
            stage="calculation_validation",
            reason_code=reason_code,
            assertion_id=claimed_output.fact_id,
            evidence_refs=refs,
            action="recalculate",
        )
