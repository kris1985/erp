"""Replay/Shadow metrics for the ranking slice (PR #7, replay-and-release doc).

Correctness gates (all must hold for the Fast Path grayscale):

- Unsupported Claim Escape Rate = 0: every assertion ref bound to a rendered
  sentence must be a *verified* assertion;
- Evidence Sufficiency Rate = 100%: every assertion rides on sufficient
  evidence (structural checks guarantee this; the collector measures it);
- Claim Precision = 100%: every numeric assertion binds to an existing fact
  (unbound assertions cannot pass the StructuralValidator).

Efficiency is collected per run (tokens / latency / subagent / inline bytes)
so the PR #1 baseline sampling can be compared in Shadow.
"""

from __future__ import annotations

from typing import Any

from app.runtime.contracts import Assertion, Fact, RuntimeModel


class RunMetrics(RuntimeModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    subagent_calls: int = 0
    result_inline_bytes: int = 0
    large_result_reinlined: bool = False


class TrustMetrics(RuntimeModel):
    total_assertions: int = 0
    verified_assertions: int = 0
    unsupported_claim_escape_rate: float = 0.0  # must be 0.0
    evidence_sufficiency_rate: float = 1.0  # must be 1.0
    claim_precision: float = 1.0  # must be 1.0


def measure_escape_rate(
    sentences: list[Any],
    verified_assertion_ids: list[str],
) -> float:
    """Fraction of sentence-bound assertion refs not in the verified set."""
    bound = [ref for sentence in sentences for ref in sentence.assertion_refs]
    if not bound:
        return 0.0
    verified = set(verified_assertion_ids)
    escapes = [ref for ref in bound if ref not in verified]
    return len(escapes) / len(bound)


def measure_sufficiency(total_assertions: int, verified_assertions: int) -> float:
    if total_assertions == 0:
        return 1.0
    return verified_assertions / total_assertions


NUMERIC_PREDICATES = {"value", "rank", "share_of_total"}


def measure_claim_precision(assertions: list[Assertion], facts: list[Fact]) -> float:
    """Fraction of numeric assertions (value/rank/share) that bind to an
    existing fact.  Judgement assertions carry no numeric value and are not
    counted."""
    facts_by_id = {fact.fact_id: fact for fact in facts}
    numeric = [a for a in assertions if a.predicate in NUMERIC_PREDICATES]
    if not numeric:
        return 1.0
    matched = sum(
        1 for assertion in numeric if assertion.object.get("value_fact_ref") in facts_by_id
    )
    return matched / len(numeric)


def collect_trust_metrics(
    *,
    assertions: list[Assertion],
    verified_ids: list[str],
    sentences: list[Any],
    facts: list[Fact],
) -> TrustMetrics:
    verified_set = set(verified_ids)
    return TrustMetrics(
        total_assertions=len(assertions),
        verified_assertions=len(verified_ids),
        unsupported_claim_escape_rate=measure_escape_rate(sentences, verified_ids),
        evidence_sufficiency_rate=measure_sufficiency(len(assertions), len(verified_ids)),
        claim_precision=measure_claim_precision(
            [a for a in assertions if a.assertion_id in verified_set], facts
        ),
    )


def collect_run_metrics(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    subagent_calls: int = 0,
    inline_bytes: int = 0,
) -> RunMetrics:
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        subagent_calls=subagent_calls,
        result_inline_bytes=inline_bytes,
        large_result_reinlined=inline_bytes > 4096,
    )
