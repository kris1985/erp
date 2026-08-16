"""Replay fixture runner for the ranking slice (replay-and-release doc).

Loads every `tests/replay/ranking/NN-name.json` fixture and asserts the
resolver reproduces the recorded expectation: compiled plan shape, stable
reason codes, or the v1 "unsupported" failure semantics.  Fixtures are added
per PR; Case 10-12 (gates) land with their implementing PRs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.runtime.contracts import dump_contract
from app.runtime.resolver import (
    ClarificationResult,
    RankingRequest,
    RankingResolver,
    ResolvedSemanticPlan,
)

REPLAY_DIR = Path(__file__).resolve().parent / "replay" / "ranking"
RESOLVER = RankingResolver()


def _fixtures() -> list[tuple[str, dict]]:
    if not REPLAY_DIR.exists():
        return []
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REPLAY_DIR.glob("*.json"))
    ]


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[f[0] for f in _fixtures()])
def test_replay_case(name: str, fixture: dict) -> None:
    v1_expected = fixture["v1_expected"]
    expected = fixture["expected"]
    result = RESOLVER.resolve(RankingRequest(**fixture["input"]))

    if v1_expected == "unsupported":
        # PR #1 resolver cannot express cross-period comparisons yet; the
        # fixture records the explicit failure semantics, not a plan.
        assert expected["status"] == "requires_clarification"
        assert isinstance(result, ClarificationResult)
        assert result.reason_code == expected["reason_code"]
        return

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
