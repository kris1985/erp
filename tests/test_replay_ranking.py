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

from app.runtime.contracts import EvidenceEnvelope, dump_contract
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.resolver import (
    ClarificationResult,
    RankingRequest,
    RankingResolver,
    ResolvedSemanticPlan,
)

REPLAY_DIR = Path(__file__).resolve().parent / "replay" / "ranking"
RESOLVER = RankingResolver()
FACT_BUILDER = RankingFactBuilder()


def _fixtures() -> list[tuple[str, dict]]:
    if not REPLAY_DIR.exists():
        return []
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REPLAY_DIR.glob("*.json"))
    ]


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[f[0] for f in _fixtures()])
def test_replay_case(name: str, fixture: dict) -> None:
    expected = fixture["expected"]

    # Evidence-chain fixture: run the gate + fact builder.
    if "evidence" in fixture:
        envelope = EvidenceEnvelope(**fixture["evidence"])
        need_denominator = bool(fixture["input"].get("needs_share", False))
        built = FACT_BUILDER.build(envelope, need_denominator=need_denominator)
        assert built.status == expected["status"], f"{name}: {built.reason_code}"
        assert built.reason_code == expected["reason_code"], name
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
