"""Shadow comparison tests (PR #7, replay-and-release doc).

Offline Replay -> Shadow -> grayscale: the candidate chain must match the
baseline structurally, or list concrete differences.
"""

from __future__ import annotations

from app.runtime.shadow import ShadowComparator, ShadowRun

COMPARATOR = ShadowComparator()


def run(mode: str, **overrides) -> ShadowRun:
    base = {
        "mode": mode,
        "plan": {"operations": [{"type": "ranking", "top_n": 3}]},
        "assertion_ids": ["a_value_A", "a_rank_A"],
        "sentences": ["客户 A 销售额 1,235 万元，排名第 1。"],
    }
    base.update(overrides)
    return ShadowRun(**base)


def test_identical_runs_match() -> None:
    baseline = run("baseline")
    candidate = run("candidate")
    verdict = COMPARATOR.compare(baseline, candidate)
    assert verdict.match is True
    assert verdict.differences == []


def test_plan_difference_reported() -> None:
    baseline = run("baseline")
    candidate = run("candidate", plan={"operations": [{"type": "ranking", "top_n": 10}]})
    verdict = COMPARATOR.compare(baseline, candidate)
    assert verdict.match is False
    assert "plan_differ" in verdict.differences


def test_assertion_difference_reported() -> None:
    baseline = run("baseline")
    candidate = run("candidate", assertion_ids=["a_value_A"])
    verdict = COMPARATOR.compare(baseline, candidate)
    assert "assertions_differ" in verdict.differences


def test_sentence_difference_reported() -> None:
    baseline = run("baseline")
    candidate = run("candidate", sentences=["客户 A 排名第 1。"])
    verdict = COMPARATOR.compare(baseline, candidate)
    assert "sentences_differ" in verdict.differences


def test_all_differences_are_concrete() -> None:
    baseline = run("baseline")
    candidate = run("candidate", plan={}, assertion_ids=[], sentences=[])
    verdict = COMPARATOR.compare(baseline, candidate)
    assert set(verdict.differences) == {"plan_differ", "assertions_differ", "sentences_differ"}
