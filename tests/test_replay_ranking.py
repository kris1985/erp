"""Replay fixture runner for the ranking slice (replay-and-release doc).

Loads every `tests/replay/ranking/NN-name.json` fixture and asserts:

- resolver fixtures (no ``evidence`` field): the recorded plan or
  clarification verdict;
- evidence-chain fixtures (with ``evidence`` field): the CoverageGate +
  FactBuilder verdict recorded in ``expected`` (Case 5/10 gates).

Fixtures are added per PR; Case 10-12 gates block Fast Path grayscale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import CalculationEngine, IndependentCalculationValidator
from app.runtime.contracts import EvidenceEnvelope, Fact, dump_contract, ranking_answer_contract
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.resolver import (
    ClarificationResult,
    RankingRequest,
    RankingResolver,
    ResolvedSemanticPlan,
)
from app.runtime.structural_validator import StructuralValidator

REPLAY_DIR = Path(__file__).resolve().parent / "replay" / "ranking"
RESOLVER = RankingResolver()
FACT_BUILDER = RankingFactBuilder()
ENGINE = CalculationEngine()
VALIDATOR = IndependentCalculationValidator()
ASSERTION_BUILDER = AssertionBuilder()
STRUCTURAL = StructuralValidator()
CONTRACT = ranking_answer_contract()


def _fixtures() -> list[tuple[str, dict]]:
    if not REPLAY_DIR.exists():
        return []
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REPLAY_DIR.glob("*.json"))
    ]


def _run_calculation_chain(fixture: dict, facts: list[Fact]) -> tuple[list, list]:
    """Reproduce the recorded derivation chain (Case 4 etc.): metric facts ->
    topn_total -> share_of_total, each asserted against the fixture value and
    re-verified by the independent validator.  Returns (derived_facts,
    calculations) so assertion fixtures can reuse the chain."""
    specs = fixture["expected_calculations"]
    outputs: dict[str, Fact] = {}
    for fact in facts:
        outputs[fact.fact_id] = fact
    total_fact = Fact(**specs["total_fact"])
    outputs[total_fact.fact_id] = total_fact
    calculations: list = []

    for key, spec in specs.items():
        if key == "total_fact":
            continue
        inputs = [outputs[fact_id] for fact_id in spec["inputs"]]
        calculation, fact = ENGINE.compute(
            spec["definition"],
            inputs,
            calculation_id=f"{spec['output_fact_id']}_calc",
            output_fact_id=spec["output_fact_id"],
        )
        assert str(fact.value) == spec["value"], f"{key}: {fact.value}"
        verdict = VALIDATOR.verify(calculation, inputs, fact)
        assert verdict.status == "verified", f"{key}: {verdict.reason_code}"
        calculations.append(calculation)
        outputs[spec["output_fact_id"]] = fact
    return list(outputs.values()), calculations


def _run_assertion_chain(fixture: dict, facts: list[Fact]) -> None:
    """Build assertions (Case 6 etc.), assert the recorded ids/predicates and
    require every assertion to pass structural validation."""
    derived, calculations = ([], [])
    if "expected_calculations" in fixture:
        derived, calculations = _run_calculation_chain(fixture, facts)
    all_facts = list(facts) + [f for f in derived if f not in facts]
    assertions = ASSERTION_BUILDER.build(
        envelope=EvidenceEnvelope(**fixture["evidence"]),
        facts=all_facts,
        calculations=calculations,
        entity_label=fixture.get("entity_label"),
    )
    by_id = {a.assertion_id: a for a in assertions}
    for spec in fixture["expected_assertions"]:
        assertion = by_id.get(spec["assertion_id"])
        assert assertion is not None, f"missing assertion {spec['assertion_id']}"
        assert assertion.predicate == spec["predicate"]
        if "rank" in spec:
            assert assertion.object["rank"] == spec["rank"]
    envelope = EvidenceEnvelope(**fixture["evidence"])
    verdicts = STRUCTURAL.validate(
        assertions,
        facts=all_facts,
        calculations=calculations,
        envelope=envelope,
        contract=CONTRACT,
    )
    for verdict in verdicts:
        assert verdict.status == "verified", f"{verdict.assertion_id}: {verdict.reason_code}"


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[f[0] for f in _fixtures()])
def test_replay_case(name: str, fixture: dict) -> None:
    expected = fixture["expected"]

    # Evidence-chain fixture: run the gate + fact builder (+ calculation/assertion chains).
    if "evidence" in fixture:
        envelope = EvidenceEnvelope(**fixture["evidence"])
        need_denominator = bool(fixture["input"].get("needs_share", False))
        built = FACT_BUILDER.build(envelope, need_denominator=need_denominator)
        assert built.status == expected["status"], f"{name}: {built.reason_code}"
        assert built.reason_code == expected["reason_code"], name
        if "expected_calculations" in fixture:
            _run_calculation_chain(fixture, built.facts)
        if "expected_assertions" in fixture:
            _run_assertion_chain(fixture, built.facts)
        return

    # Resolver fixture: reproduce the recorded plan or clarification.
    result = RESOLVER.resolve(RankingRequest(**fixture["input"]))

    if expected["status"] == "compiled":
        assert isinstance(result, ResolvedSemanticPlan), (
            f"{name}: expected compiled plan, got {result.reason_code}"
        )
        actual = dump_contract(result)
        actual.pop("semantic_plan_id")
        assert actual == expected["plan"], name
        assert expected["reason_code"] is None
    elif expected["status"] == "requires_clarification":
        assert isinstance(result, ClarificationResult), name
        assert result.reason_code == expected["reason_code"], name
    else:  # pragma: no cover - guards against typo'd fixture status
        raise AssertionError(f"{name}: unknown expected.status {expected['status']!r}")


def test_replay_dir_has_fixtures() -> None:
    assert _fixtures(), f"no fixtures under {REPLAY_DIR}"
