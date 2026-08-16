"""Shadow comparison for the ranking slice (PR #7, replay-and-release doc).

Offline Replay -> Shadow -> grayscale: before switching production traffic,
the new chain runs beside the old one and the two artifacts are compared.
The comparator is structural — plan, assertion ids, sentences — so a Shadow
run either matches or produces a list of concrete differences, never a vague
“answer quality” score.
"""

from __future__ import annotations

from typing import Any, Literal

from app.runtime.contracts import RuntimeModel


class ShadowRun(RuntimeModel):
    mode: Literal["baseline", "candidate"]
    plan: dict[str, Any]  # dump_contract(ResolvedSemanticPlan) minus ids
    assertion_ids: list[str]
    sentences: list[str]
    input_tokens: int = 0
    latency_ms: int = 0


class ShadowVerdict(RuntimeModel):
    match: bool
    differences: list[str] = []


class ShadowComparator:
    def compare(self, baseline: ShadowRun, candidate: ShadowRun) -> ShadowVerdict:
        differences: list[str] = []
        if baseline.plan != candidate.plan:
            differences.append("plan_differ")
        if baseline.assertion_ids != candidate.assertion_ids:
            differences.append("assertions_differ")
        if baseline.sentences != candidate.sentences:
            differences.append("sentences_differ")
        return ShadowVerdict(match=not differences, differences=differences)
