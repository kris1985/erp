"""Calculation Engine + independent validator tests (PR #3, contracts §P1.1).

Acceptance: every derived number replays formula, inputs, rounding and source
query; tampering with the output, any input, the formula or the rounding
policy fails with a stable reason code; canonical values are never distorted
by display rounding (0.7996 must not hit an >= 0.80 rule just because it
renders as 80.0%).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.runtime.calculation import (
    CALCULATION_MISMATCH,
    CALCULATION_VERIFIED,
    DIVISION_BY_ZERO,
    CalculationEngine,
    CalculationError,
    IndependentCalculationValidator,
    INPUT_LINEAGE_MISMATCH,
    NO_INPUT_FACTS,
    ROUNDING_POLICY_MISMATCH,
    UNIT_MISMATCH,
    UNKNOWN_CALCULATION_DEFINITION,
)
from app.runtime.contracts import Calculation, Fact, RoundingPolicy, TimeScope

ENGINE = CalculationEngine()
VALIDATOR = IndependentCalculationValidator()
SCOPE = TimeScope(year=2026)


def row_fact(fact_id: str, value: str, unit: str = "CNY") -> Fact:
    return Fact(
        fact_id=fact_id,
        type="metric_fact",
        name="客户销售额",
        value=Decimal(value),
        unit=unit,
        dimensions={"customer": fact_id.split(":")[-1]},
        scope=SCOPE,
        evidence_refs=[fact_id.split(":")[0]],
    )


def top2_rows() -> list[Fact]:
    return [row_fact("r_004:customer:A", "12350000"), row_fact("r_004:customer:B", "9800000")]


def total_fact() -> Fact:
    return Fact(
        fact_id="f_total_sales",
        type="metric_fact",
        name="客户销售额",
        value=Decimal("34250000"),
        unit="CNY",
        scope=SCOPE,
        evidence_refs=["r_004_total"],
    )


def build_share_chain() -> tuple:
    calculation, total_fact_out = ENGINE.compute(
        "topn_total",
        top2_rows(),
        calculation_id="c_top2_total",
        output_fact_id="c_top2_total",
    )
    share_calc, share_fact = ENGINE.compute(
        "share_of_total",
        [total_fact_out, total_fact()],
        calculation_id="c_top2_share",
        output_fact_id="c_top2_share",
    )
    return calculation, total_fact_out, share_calc, share_fact


# --------------------------------------------------------------------------
# Generate side
# --------------------------------------------------------------------------


def test_topn_total_sums_inputs() -> None:
    calculation, fact = ENGINE.compute(
        "topn_total", top2_rows(), calculation_id="c1", output_fact_id="f_top2_total"
    )
    assert fact.value == Decimal("22150000")
    assert fact.unit == "CNY"
    assert fact.type == "derived_metric"
    assert fact.calculation_id == "c1"
    assert fact.inputs == ["r_004:customer:A", "r_004:customer:B"]
    assert fact.evidence_refs == ["r_004"]  # union of input evidence
    assert fact.display.format == "currency"
    assert calculation.formula == "sum(inputs)"


def test_topn_total_empty_inputs_fails() -> None:
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute("topn_total", [], calculation_id="c", output_fact_id="f")
    assert exc.value.reason_code == NO_INPUT_FACTS


def test_topn_total_unit_mismatch_fails() -> None:
    rows = [row_fact("r:a", "1", "CNY"), row_fact("r:b", "1", "USD")]
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute("topn_total", rows, calculation_id="c", output_fact_id="f")
    assert exc.value.reason_code == UNIT_MISMATCH


def test_share_computes_canonical_ratio() -> None:
    _, total, _, share = build_share_chain()
    assert share.value == Decimal("0.646715328467")
    assert share.unit == "ratio"
    assert share.display.format == "percent"
    assert share.display.scale == 1
    assert share.calculation_id == "c_top2_share"
    assert share.inputs == ["c_top2_total", "f_total_sales"]
    assert share.evidence_refs == ["r_004", "r_004_total"]  # union across chain


def test_share_division_by_zero_fails() -> None:
    zero_total = total_fact().model_copy(update={"value": Decimal("0")})
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute(
            "share_of_total",
            [top2_rows()[0], zero_total],
            calculation_id="c",
            output_fact_id="f",
        )
    assert exc.value.reason_code == DIVISION_BY_ZERO


def test_share_requires_two_inputs() -> None:
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute(
            "share_of_total", [top2_rows()[0]], calculation_id="c", output_fact_id="f"
        )
    assert exc.value.reason_code == INPUT_LINEAGE_MISMATCH


def test_share_unit_mismatch_fails() -> None:
    numerator = top2_rows()[0]
    denominator = total_fact().model_copy(update={"unit": "USD"})
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute(
            "share_of_total", [numerator, denominator], calculation_id="c", output_fact_id="f"
        )
    assert exc.value.reason_code == UNIT_MISMATCH


def test_unknown_definition_fails() -> None:
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute("period_change", top2_rows(), calculation_id="c", output_fact_id="f")
    assert exc.value.reason_code == UNKNOWN_CALCULATION_DEFINITION


def test_engine_rejects_cross_scope_inputs() -> None:
    """H1: a 2026 numerator over a 2025 denominator is semantic poison — the
    engine must refuse to build the derived fact."""
    numerator = top2_rows()[0]
    denominator = total_fact().model_copy(update={"scope": TimeScope(year=2025)})
    with pytest.raises(CalculationError) as exc:
        ENGINE.compute(
            "share_of_total", [numerator, denominator], calculation_id="c", output_fact_id="f"
        )
    assert exc.value.reason_code == "TIME_SCOPE_MISMATCH"


def test_validator_rejects_cross_scope_inputs() -> None:
    """H1: the independent validator also refuses cross-scope inputs."""
    numerator = top2_rows()[0]
    denominator = total_fact().model_copy(update={"scope": TimeScope(year=2025)})
    share_calc = Calculation(
        calculation_id="c_cross",
        definition="share_of_total",
        inputs=["r_004:customer:A", "f_total_sales"],
        output_fact="f_fake",
        formula="numerator / denominator",
        rounding=RoundingPolicy(precision=12, mode="half_up"),
    )
    fake = Fact(
        fact_id="f_fake",
        type="derived_metric",
        name="share_of_total",
        value=Decimal("1"),
        unit="ratio",
        scope=SCOPE,
        calculation_id="c_cross",
        inputs=["r_004:customer:A", "f_total_sales"],
    )
    verdict = VALIDATOR.verify(share_calc, [numerator, denominator], fake)
    assert verdict.status == "rejected"
    assert verdict.reason_code == "TIME_SCOPE_MISMATCH"


# --------------------------------------------------------------------------
# Verify side (independent recompute)
# --------------------------------------------------------------------------


def test_validator_accepts_untampered_chain() -> None:
    calc, total, share_calc, share = build_share_chain()
    assert VALIDATOR.verify(calc, top2_rows(), total).status == "verified"
    assert VALIDATOR.verify(share_calc, [total, total_fact()], share).status == "verified"


def test_tampered_output_fails() -> None:
    calc, total, share_calc, share = build_share_chain()
    tampered = share.model_copy(update={"value": Decimal("0.9999")})
    verdict = VALIDATOR.verify(share_calc, [total, total_fact()], tampered)
    assert verdict.status == "rejected"
    assert verdict.reason_code == CALCULATION_MISMATCH
    assert verdict.stage == "calculation_validation"
    assert verdict.action == "recalculate"
    assert verdict.expected == {"value": "0.646715328467"}
    assert verdict.actual == {"value": "0.9999"}


def test_tampered_input_fails() -> None:
    calc, total, share_calc, share = build_share_chain()
    swapped_total = total_fact().model_copy(update={"value": Decimal("99999999")})
    verdict = VALIDATOR.verify(share_calc, [total, swapped_total], share)
    assert verdict.reason_code == CALCULATION_MISMATCH


def test_tampered_formula_fails() -> None:
    _, total, share_calc, share = build_share_chain()
    tampered = share_calc.model_copy(update={"formula": "numerator * denominator"})
    verdict = VALIDATOR.verify(tampered, [total, total_fact()], share)
    assert verdict.reason_code == "FORMULA_MISMATCH"


def test_tampered_rounding_policy_fails() -> None:
    _, total, share_calc, share = build_share_chain()
    tampered = share_calc.model_copy(
        update={"rounding": RoundingPolicy(precision=2, mode="half_up")}
    )
    verdict = VALIDATOR.verify(tampered, [total, total_fact()], share)
    assert verdict.reason_code == ROUNDING_POLICY_MISMATCH


def test_lineage_mismatch_fails() -> None:
    _, total, share_calc, share = build_share_chain()
    tampered = share_calc.model_copy(update={"inputs": ["some_other_fact"]})
    verdict = VALIDATOR.verify(tampered, [total, total_fact()], share)
    assert verdict.reason_code == INPUT_LINEAGE_MISMATCH


def test_validator_reports_division_by_zero() -> None:
    zero_total = total_fact().model_copy(update={"value": Decimal("0")})
    share_calc = Calculation(
        calculation_id="c_zero",
        definition="share_of_total",
        inputs=["c_top2_total", "f_total_sales"],
        output_fact="f_fake",
        formula="numerator / denominator",
        rounding=RoundingPolicy(precision=12, mode="half_up"),
    )
    numerator = row_fact("c_top2_total", "12350000")
    fake = Fact(
        fact_id="f_fake",
        type="derived_metric",
        name="share_of_total",
        value=Decimal("1"),
        unit="ratio",
        scope=SCOPE,
        calculation_id="c_zero",
        inputs=["c_top2_total", "f_total_sales"],
    )
    verdict = VALIDATOR.verify(share_calc, [numerator, zero_total], fake)
    assert verdict.status == "rejected"
    assert verdict.reason_code == DIVISION_BY_ZERO


def test_validator_verified_metadata() -> None:
    calc, total, _, _ = build_share_chain()
    verdict = VALIDATOR.verify(calc, top2_rows(), total)
    assert verdict.status == "verified"
    assert verdict.reason_code == CALCULATION_VERIFIED
    assert verdict.stage == "calculation_validation"


# --------------------------------------------------------------------------
# Canonical vs display
# --------------------------------------------------------------------------


def test_canonical_value_not_distorted_by_display() -> None:
    """0.7996 canonical must not hit an >= 0.80 rule even if displayed 80.0%."""
    numerator = row_fact("r:c1", "7996000")
    denominator = row_fact("r:c2", "10000000", unit="CNY")
    _, fact = ENGINE.compute(
        "share_of_total",
        [numerator, denominator],
        calculation_id="c_canonical",
        output_fact_id="f_canonical",
    )
    assert fact.value == Decimal("0.799600000000")
    assert fact.value < Decimal("0.80")  # business rules read canonical
    # display says scale=1 percent -> would render 80.0%, but canonical stays put
    assert fact.display.scale == 1
    assert fact.display.format == "percent"
