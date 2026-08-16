"""Replay fixture runner for the metric_snapshot slice (replay-and-release doc).

Loads every `tests/replay/metric_snapshot/NN-name.json` fixture and asserts:

- resolver fixtures (no ``evidence`` field): the recorded plan or
  clarification verdict (SnapshotResolver);
- evidence-chain fixtures (with ``evidence`` field): CoverageGate ->
  SnapshotFactBuilder -> Assertions -> StructuralValidator -> ContractChecker
  -> DeterministicRenderer, each stage asserted against the fixture's recorded
  expectations.

Snapshot slices have no derived calculations (a scalar total needs none), so
fixtures carry no ``expected_calculations``; the trusted-chain gates
(escape rate = 0, sufficiency = 100%, precision = 100%) still apply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.runtime.assertions import AssertionBuilder
from app.runtime.contract_checker import ContractChecker
from app.runtime.contracts import EvidenceEnvelope, Fact, dump_contract, snapshot_answer_contract
from app.runtime.fact_builder import SnapshotFactBuilder
from app.runtime.metrics import collect_trust_metrics
from app.runtime.renderer import DeterministicRenderer, RenderedTable
from app.runtime.resolver import (
    ClarificationResult,
    ResolvedSemanticPlan,
    SnapshotRequest,
    SnapshotResolver,
)
from app.runtime.structural_validator import StructuralValidator

REPLAY_DIR = Path(__file__).resolve().parent / "replay" / "metric_snapshot"
RESOLVER = SnapshotResolver()
FACT_BUILDER = SnapshotFactBuilder()
ASSERTION_BUILDER = AssertionBuilder()
STRUCTURAL = StructuralValidator()
CONTRACT_CHECKER = ContractChecker()
RENDERER = DeterministicRenderer()
CONTRACT = snapshot_answer_contract()


def _fixtures() -> list[tuple[str, dict]]:
    if not REPLAY_DIR.exists():
        return []
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REPLAY_DIR.glob("*.json"))
    ]


def _verified_assertions(
    fixture: dict,
    facts: list[Fact],
    envelope: EvidenceEnvelope,
) -> tuple[list, list]:
    assertions = ASSERTION_BUILDER.build(
        envelope=envelope,
        facts=facts,
        calculations=[],
    )
    all_assertions = assertions
    verdicts = STRUCTURAL.validate(
        all_assertions,
        facts=facts,
        calculations=[],
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

    if "evidence" in fixture:
        envelope = EvidenceEnvelope(**fixture["evidence"])
        built = FACT_BUILDER.build(envelope)
        assert built.status == expected["status"], f"{name}: {built.reason_code}"
        assert built.reason_code == expected["reason_code"], name

        verified, all_assertions = _verified_assertions(fixture, built.facts, envelope)
        _assert_trust_metrics(fixture, verified, all_assertions, built.facts)

        if "expected_assertions" in fixture:
            _assert_expected_assertions(fixture, all_assertions)
        if "expected_sentences" in fixture or "expected_table" in fixture:
            _assert_rendered(fixture, verified, built.facts, envelope)
        return

    # Resolver fixture: reproduce the recorded plan or clarification.
    result = RESOLVER.resolve(SnapshotRequest(**fixture["input"]))

    if expected["status"] == "compiled":
        assert isinstance(result, ResolvedSemanticPlan), (
            f"{name}: expected compiled plan, got {result.reason_code}"
        )
        actual = dump_contract(result)
        actual.pop("semantic_plan_id")
        assert actual == expected["plan"], name
        assert expected["reason_code"] is None
    elif expected["status"] in ("requires_clarification", "unsupported"):
        assert isinstance(result, ClarificationResult), name
        assert result.status == expected["status"], name
        assert result.reason_code == expected["reason_code"], name
    else:  # pragma: no cover - guards against typo'd fixture status
        raise AssertionError(f"{name}: unknown expected.status {expected['status']!r}")


def _assert_trust_metrics(
    fixture: dict,
    verified: list,
    all_assertions: list,
    facts: list[Fact],
) -> None:
    """Every evidence fixture enforces the DoD correctness gates (replay doc):
    Unsupported Claim Escape Rate = 0, Evidence Sufficiency = 100%,
    Claim Precision = 100%."""
    mode = fixture.get("presentation_mode", "sentence")
    contract = snapshot_answer_contract(presentation_mode=mode)
    envelope = EvidenceEnvelope(**fixture["evidence"])
    output = RENDERER.render(
        verified,
        facts=facts,
        envelope=envelope,
        contract=contract,
    )
    sentences = output if isinstance(output, list) else []
    trust = collect_trust_metrics(
        assertions=all_assertions,
        verified_ids=[a.assertion_id for a in verified],
        sentences=sentences,
        facts=facts,
    )
    assert trust.unsupported_claim_escape_rate == 0.0, (
        f"{fixture['case_id']}: unsupported claim escaped"
    )
    assert trust.evidence_sufficiency_rate == 1.0
    assert trust.claim_precision == 1.0


def _assert_expected_assertions(fixture: dict, all_assertions: list) -> None:
    by_id = {a.assertion_id: a for a in all_assertions}
    for spec in fixture["expected_assertions"]:
        assertion = by_id.get(spec["assertion_id"])
        assert assertion is not None, f"missing assertion {spec['assertion_id']}"
        assert assertion.predicate == spec["predicate"]


def _assert_rendered(
    fixture: dict,
    verified: list,
    facts: list[Fact],
    envelope: EvidenceEnvelope,
) -> None:
    mode = fixture.get("presentation_mode", "sentence")
    contract = snapshot_answer_contract(presentation_mode=mode)
    output = RENDERER.render(
        verified,
        facts=facts,
        envelope=envelope,
        contract=contract,
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
