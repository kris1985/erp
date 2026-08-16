"""Replay metrics tests (PR #7, replay-and-release doc).

Correctness gates must hold before Fast Path grayscale: Unsupported Claim
Escape Rate = 0, Evidence Sufficiency = 100%, Claim Precision = 100%.
"""

from __future__ import annotations

from app.runtime.metrics import (
    collect_run_metrics,
    collect_trust_metrics,
    measure_escape_rate,
    measure_sufficiency,
)


class FakeSentence:
    def __init__(self, refs: list[str]) -> None:
        self.assertion_refs = refs


def test_escape_rate_zero_for_verified_binding() -> None:
    sentences = [FakeSentence(["a_rank_A", "a_share"])]
    assert measure_escape_rate(sentences, ["a_rank_A", "a_share"]) == 0.0


def test_escape_rate_detects_unverified_ref() -> None:
    sentences = [FakeSentence(["a_rank_A", "a_ghost"])]
    rate = measure_escape_rate(sentences, ["a_rank_A"])
    assert rate == 0.5


def test_escape_rate_empty_sentences_is_zero() -> None:
    assert measure_escape_rate([], ["a"]) == 0.0


def test_sufficiency_ratios() -> None:
    assert measure_sufficiency(10, 10) == 1.0
    assert measure_sufficiency(10, 7) == 0.7
    assert measure_sufficiency(0, 0) == 1.0


def test_trust_metrics_gate_holds_for_clean_run() -> None:
    # value/rank assertions all bound to existing facts -> precision 1.0
    class FakeAssertion:
        def __init__(self, assertion_id: str, fact_ref: str) -> None:
            self.assertion_id = assertion_id
            self.predicate = "value"
            self.object = {"value_fact_ref": fact_ref}

    class FakeFact:
        def __init__(self, fact_id: str) -> None:
            self.fact_id = fact_id

    assertions = [FakeAssertion("a_value_A", "f_A"), FakeAssertion("a_rank_A", "f_A")]
    facts = [FakeFact("f_A")]
    sentences = [FakeSentence(["a_value_A"])]
    metrics = collect_trust_metrics(
        assertions=assertions,
        verified_ids=["a_value_A", "a_rank_A"],
        sentences=sentences,
        facts=facts,
    )
    assert metrics.unsupported_claim_escape_rate == 0.0
    assert metrics.evidence_sufficiency_rate == 1.0
    assert metrics.claim_precision == 1.0


def test_run_metrics_collection() -> None:
    metrics = collect_run_metrics(
        input_tokens=1200, latency_ms=850, subagent_calls=0, inline_bytes=500
    )
    assert metrics.input_tokens == 1200
    assert metrics.latency_ms == 850
    assert metrics.subagent_calls == 0
    assert metrics.large_result_reinlined is False
    big = collect_run_metrics(inline_bytes=9000)
    assert big.large_result_reinlined is True
