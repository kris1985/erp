"""Replay fixture runner for the ranking slice (replay-and-release doc).

Loads every `tests/replay/ranking/NN-name.json` fixture and asserts:

- resolver fixtures (no ``evidence`` field): the recorded plan or
  clarification verdict;
- evidence-chain fixtures (with ``evidence`` field): CoverageGate ->
  FactBuilder -> Calculation chain -> Assertions -> BusinessRule judgements ->
  StructuralValidator -> ContractChecker -> DeterministicRenderer, each stage
  asserted against the fixture's recorded expectations.

Fixtures are added per PR; Case 10-12 gates block Fast Path grayscale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import CalculationEngine, IndependentCalculationValidator
from app.runtime.contract_checker import ContractChecker
from app.runtime.contracts import EvidenceEnvelope, Fact, dump_contract, ranking_answer_contract
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.renderer import DeterministicRenderer, RenderedSentence, RenderedTable
from app.runtime.resolver import (
    ClarificationResult,
    RankingRequest,
    RankingResolver,
    ResolvedSemanticPlan,
)
from app.runtime.rules import BusinessRuleEngine
from app.runtime.structural_validator import StructuralValidator

REPLAY_DIR = Path(__file__).resolve().parent / "replay" / "ranking"
RESOLVER = RankingResolver()
FACT_BUILDER = RankingFactBuilder()
ENGINE = CalculationEngine()
CALC_VALIDATOR = IndependentCalculationValidator()
ASSERTION_BUILDER = AssertionBuilder()
RULE_ENGINE = BusinessRuleEngine()
STRUCTURAL = StructuralValidator()
CONTRACT_CHECKER = ContractChecker()
RENDERER = DeterministicRenderer()
CONTRACT = ranking_answer_contract()


def _fixtures() -> list[tuple[str, dict]]:
    if not REPLAY_DIR.exists():
        return []
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REPLAY_DIR.glob("*.json"))
    ]


def _run_calculation_chain(fixture: dict, facts: list[Fact]) -> tuple[list[Fact], list]:
    """Reproduce the recorded derivation chain (Case 4/5 etc.): metric facts ->
    topn_total -> share_of_total, each asserted against the fixture value and
    re-verified by the independent validator.  Returns (all_facts incl.
    derived, calculations)."""
    specs = fixture["expected_calculations"]
    outputs: dict[str, Fact] = {fact.fact_id: fact for fact in facts}
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
        verdict = CALC_VALIDATOR.verify(calculation, inputs, fact)
        assert verdict.status == "verified", f"{key}: {verdict.reason_code}"
        calculations.append(calculation)
        outputs[spec["output_fact_id"]] = fact
    return list(outputs.values()), calculations


def _verified_assertions(
    fixture: dict,
    facts: list[Fact],
    calculations: list,
    envelope: EvidenceEnvelope,
) -> tuple[list, list]:
    """Build assertions + rule judgements, run StructuralValidator and
    ContractChecker, return (verified_assertions, all_assertions)."""
    assertions = ASSERTION_BUILDER.build(
        envelope=envelope,
        facts=facts,
        calculations=calculations,
        entity_label=fixture.get("entity_label"),
    )
    judgements = RULE_ENGINE.apply_judgements(
        envelope=envelope, facts=facts, calculations=calculations
    )
    all_assertions = assertions + judgements
    verdicts = STRUCTURAL.validate(
        all_assertions,
        facts=facts,
        calculations=calculations,
        envelope=envelope,
        contract=CONTRACT,
    )
    verified = [a for a, v in zip(all_assertions, verdicts) if v.status == "verified"]
    for result in CONTRACT_CHECKER.check(verified, CONTRACT):
        assert result.status == "verified", f"contract: {result.reason_code}"
    return verified, all_assertions


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[f[0] for f in _fixtures()])
def test_replay_case(name: str, fixture: dict) -> None:
    expected = fixture["expected"]

    # Evidence-chain fixture: run the full trusted chain.
    if "evidence" in fixture:
        envelope = EvidenceEnvelope(**fixture["evidence"])
        need_denominator = bool(fixture["input"].get("needs_share", False))
        built = FACT_BUILDER.build(envelope, need_denominator=need_denominator)
        assert built.status == expected["status"], f"{name}: {built.reason_code}"
        assert built.reason_code == expected["reason_code"], name

        facts, calculations = built.facts, []
        if "expected_calculations" in fixture:
            facts, calculations = _run_calculation_chain(fixture, built.facts)

        verified, all_assertions = _verified_assertions(fixture, facts, calculations, envelope)

        if "expected_assertions" in fixture:
            _assert_expected_assertions(fixture, all_assertions)
        if "expected_judgement" in fixture:
            _assert_expected_judgement(fixture, judgements(all_assertions))
        if "expected_sentences" in fixture or "expected_table" in fixture:
            _assert_rendered(fixture, verified, facts, envelope)
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


def _assert_expected_assertions(fixture: dict, all_assertions: list) -> None:
    by_id = {a.assertion_id: a for a in all_assertions}
    for spec in fixture["expected_assertions"]:
        assertion = by_id.get(spec["assertion_id"])
        assert assertion is not None, f"missing assertion {spec['assertion_id']}"
        assert assertion.predicate == spec["predicate"]
        if "rank" in spec:
            assert assertion.object["rank"] == spec["rank"]


def judgements(assertions: list) -> list:
    return [a for a in assertions if a.type == "judgement"]


def _assert_expected_judgement(fixture: dict, judgement_list: list) -> None:
    expected = fixture["expected_judgement"]
    if expected is None:
        assert judgement_list == [], f"expected no judgement, got {judgement_list}"
        return
    assert len(judgement_list) == 1
    judgement = judgement_list[0]
    assert judgement.rule_ref == expected["rule_ref"]
    assert judgement.object["classification"] == expected["classification"]


def _assert_rendered(
    fixture: dict,
    verified: list,
    facts: list[Fact],
    envelope: EvidenceEnvelope,
) -> None:
    mode = fixture.get("presentation_mode", "sentence")
    contract = ranking_answer_contract(presentation_mode=mode)
    output = RENDERER.render(
        verified,
        facts=facts,
        envelope=envelope,
        contract=contract,
        entity_label=fixture.get("entity_label"),
    )
    if "expected_sentences" in fixture:
        assert isinstance(output, list)
        assert [s.text for s in output] == fixture["expected_sentences"]["texts"]
        for sentence in output:
            assert sentence.assertion_refs, f"unbound sentence: {sentence.text}"
    if "expected_table" in fixture:
        assert isinstance(output, RenderedTable)
        assert output.columns == fixture["expected_table"]["columns"]
        assert output.rows == fixture["expected_table"]["rows"]


def test_replay_dir_has_fixtures() -> None:
    assert _fixtures(), f"no fixtures under {REPLAY_DIR}"
