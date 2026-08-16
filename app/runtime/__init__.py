"""Ranking v1 runtime: frozen contracts, minimal registry and resolver.

PR #1 scope (see docs/customer-sales-ranking-slice.md §5.2): freeze the eight
Ranking v1 payloads, wire the minimal resolver for the fixed ranking shape,
and prove the TypedResult/Evidence composition choice with serialization and
tamper tests. Nothing here changes existing agent routing yet.
"""

from app.runtime.contracts import (
    SCHEMA_VERSION,
    AnswerContract,
    Assertion,
    Calculation,
    EvidenceEnvelope,
    Fact,
    ResolvedSemanticPlan,
    TypedAnalysisResult,
    ValidationResult,
    dump_contract,
    load_contract,
    ranking_answer_contract,
)
from app.runtime.registry import MetricDefinition, MetricRegistry, RANKING_METRIC
from app.runtime.resolver import (
    ClarificationResult,
    RankingRequest,
    ResolverResult,
    RankingResolver,
)

__all__ = [
    "SCHEMA_VERSION",
    "AnswerContract",
    "Assertion",
    "Calculation",
    "EvidenceEnvelope",
    "Fact",
    "ResolvedSemanticPlan",
    "TypedAnalysisResult",
    "ValidationResult",
    "dump_contract",
    "load_contract",
    "ranking_answer_contract",
    "MetricDefinition",
    "MetricRegistry",
    "RANKING_METRIC",
    "ClarificationResult",
    "RankingRequest",
    "ResolverResult",
    "RankingResolver",
]
