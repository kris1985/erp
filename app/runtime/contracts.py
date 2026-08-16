"""Ranking v1 runtime contracts (frozen payloads).

The eight core payloads frozen in the improvement plan
(docs/agent-runtime-improvement-plan.md §2.1). Ranking-first: fields exist
because the ``customer_sales_ranking`` slice needs them, not as a general BI
IR.  Every payload carries ``schema_version`` so old traces stay replayable;
unknown keys are rejected and missing required fields fail closed.

Composition choice (PR #1 spike, see contracts doc §3.5): the
``EvidenceEnvelope`` holds all evidence meta and composes the
``TypedAnalysisResult`` payload.  Semantic meta (metric / scope / coverage /
unit) has exactly one authoritative home — the envelope — and the payload
cannot smuggle a second copy: it has no such fields and rejects extra keys.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0.0"


class RuntimeModel(BaseModel):
    """Shared contract behaviour: frozen, strict shape, no surplus keys."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
    )


def dump_contract(obj: BaseModel) -> dict[str, Any]:
    """Deterministic JSON-mode dump used for Trace and fixtures (no nulls)."""
    return obj.model_dump(mode="json", exclude_none=True)


_T = TypeVar("_T", bound=BaseModel)


def load_contract(model: type[_T], payload: dict[str, Any] | str) -> _T:
    """Validate a serialized contract; unknown keys / missing fields fail."""
    return model.model_validate(payload)


# --------------------------------------------------------------------------
# 1. ResolvedSemanticPlan — deterministic, executable, replayable plan
# --------------------------------------------------------------------------


class OperationSpec(RuntimeModel):
    """One node of the v1 fixed-shape DAG. Ref fields are validated to exist
    among sibling operations (see ResolvedSemanticPlan._dag_valid)."""

    operation_id: str
    type: Literal["ranking", "metric_snapshot", "topn_total", "share_of_total"]
    top_n: int | None = None
    sort: Literal["desc", "asc"] | None = None
    source_ref: str | None = None  # topn_total -> ranking operation
    numerator_ref: str | None = None  # share_of_total -> topn_total
    denominator_ref: str | None = None  # share_of_total -> metric_snapshot


class ResolvedSemanticPlan(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    semantic_plan_id: str
    metric: MetricRef
    dimension: str
    scope: TimeScope
    as_of: datetime
    timezone: str = "Asia/Shanghai"
    filters: dict[str, Any] = Field(default_factory=dict)
    operations: list[OperationSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dag_valid(self) -> "ResolvedSemanticPlan":
        ids = {op.operation_id for op in self.operations}
        if not ids:
            raise ValueError("resolved plan must contain at least one operation")
        for op in self.operations:
            for ref in (op.source_ref, op.numerator_ref, op.denominator_ref):
                if ref is not None and ref not in ids:
                    raise ValueError(f"operation ref {ref!r} not found in plan")
        return self


# --------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------


class MetricRef(RuntimeModel):
    """A metric pinned to an exact definition version (contracts doc §3.3)."""

    metric_id: str
    definition_version: str


class TimeScope(RuntimeModel):
    """v1 scope: year-level. ``month`` is reserved for the metric_snapshot
    slice and must stay None for ranking v1 (validated by the resolver)."""

    year: int | None = None
    month: int | None = None


class Coverage(RuntimeModel):
    """First-class coverage contract, not display metadata (contracts §3.3).

    v1 gates: complete_population / top_n / truncated / unknown participate in
    validation; sample / partial_period are reserved and not built out.
    """

    type: Literal[
        "complete_population", "top_n", "sample", "partial_period", "truncated", "unknown"
    ]
    requested: int | None = None
    returned: int | None = None
    population_complete: bool = False
    population_size: int | None = None
    denominator_available: bool = False


class Freshness(RuntimeModel):
    queried_at: datetime


class DisplaySpec(RuntimeModel):
    """Presentation hint only; business rules must read canonical values."""

    scale: int = 0
    format: Literal["plain", "percent", "currency", "thousands"] = "plain"


# --------------------------------------------------------------------------
# 2. TypedAnalysisResult — "what execution produced" (data evidence only)
# --------------------------------------------------------------------------


class RankingRow(RuntimeModel):
    entity_id: str
    entity_label: str
    value: Decimal
    unit: str
    rank: int


class TypedAnalysisResult(RuntimeModel):
    """Payload half of the envelope. No metric/scope/coverage here on purpose:
    they live only in the EvidenceEnvelope (single source of truth)."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    result_type: Literal["ranking"]
    rows: list[RankingRow] = Field(default_factory=list)
    execution_ref: str


# --------------------------------------------------------------------------
# 3. EvidenceEnvelope — composition: evidence meta + typed payload
# --------------------------------------------------------------------------


class EvidenceEnvelope(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    result_id: str
    metric: MetricRef
    scope: TimeScope
    dimension: str
    operation: Literal["ranking"]
    coverage: Coverage
    freshness: Freshness
    authority: Literal["metric_engine"] = "metric_engine"
    filters: dict[str, Any] = Field(default_factory=dict)
    payload: TypedAnalysisResult

    @model_validator(mode="after")
    def _shape_matches(self) -> "EvidenceEnvelope":
        if self.operation != self.payload.result_type:
            raise ValueError("envelope.operation must equal payload.result_type")
        return self


# --------------------------------------------------------------------------
# 4. Fact — raw metric rows and derived numbers (contracts doc §P1.1)
# --------------------------------------------------------------------------


class Fact(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    fact_id: str
    type: Literal["metric_fact", "derived_metric"]
    name: str
    value: Decimal
    unit: str
    display: DisplaySpec = Field(default_factory=DisplaySpec)
    dimensions: dict[str, str] = Field(default_factory=dict)
    scope: TimeScope
    source: str = "metric_engine"
    evidence_refs: list[str] = Field(default_factory=list)
    calculation_id: str | None = None
    inputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derived_requires_calculation(self) -> "Fact":
        if self.type == "derived_metric":
            if not self.calculation_id:
                raise ValueError("derived_metric requires calculation_id")
            if not self.inputs:
                raise ValueError("derived_metric requires inputs")
        elif self.calculation_id is not None:
            raise ValueError("metric_fact must not carry calculation_id")
        return self


# --------------------------------------------------------------------------
# 5. Calculation — derivation definition, replayed not trusted (contracts §P1.1)
# --------------------------------------------------------------------------


class RoundingPolicy(RuntimeModel):
    precision: int = 4
    mode: Literal["half_up", "half_even", "truncate"] = "half_up"


class Calculation(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    calculation_id: str
    definition: Literal["topn_total", "share_of_total"]
    inputs: list[str] = Field(default_factory=list)  # fact_ids
    output_fact: str
    formula: str
    rounding: RoundingPolicy = Field(default_factory=RoundingPolicy)


# --------------------------------------------------------------------------
# 6. Assertion — Trace semantics use Claim terminology (plan §2.1)
# --------------------------------------------------------------------------


class AssertionSubject(RuntimeModel):
    metric: MetricRef
    dimensions: dict[str, str] = Field(default_factory=dict)
    scope: TimeScope


class Assertion(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    assertion_id: str  # claim_id in Trace
    type: Literal["fact", "derived", "judgement"]  # recommendation reserved
    predicate: Literal["value", "rank", "share_of_total", "classification"]
    claim_strength: Literal[
        "deterministic", "rule_supported", "analytical", "hypothesis"
    ]
    subject: AssertionSubject
    object: dict[str, Any]  # e.g. {"rank": 1, "value_fact_ref": "f_customer_a"}
    fact_refs: list[str] = Field(default_factory=list)
    calculation_ref: str | None = None
    rule_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None

    @model_validator(mode="after")
    def _binding_consistency(self) -> "Assertion":
        if self.type == "derived" and not self.calculation_ref:
            raise ValueError("derived assertion requires calculation_ref")
        if self.type == "judgement" and not self.rule_ref:
            raise ValueError("judgement assertion requires rule_ref")
        if self.type in ("fact", "derived") and not self.fact_refs:
            raise ValueError("fact/derived assertion requires fact_refs")
        if self.predicate == "classification" and self.type != "judgement":
            raise ValueError("classification predicate requires judgement type")
        return self


# --------------------------------------------------------------------------
# 7. AnswerContract — thin licensing policy (slice doc §2.3, contracts §P1.2)
# --------------------------------------------------------------------------


class AnswerContract(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    answer_type: Literal["ranking"]
    required_assertion_ids: list[str] = Field(default_factory=list)
    allowed_predicates: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    presentation_mode: Literal["sentence", "table"] = "sentence"


def ranking_answer_contract(
    *,
    presentation_mode: Literal["sentence", "table"] = "sentence",
    required_assertion_ids: list[str] | None = None,
) -> AnswerContract:
    """Thin template for the ranking slice. Validators only execute the
    policy; they never hard-code business permissions like profit/payment."""
    return AnswerContract(
        answer_type="ranking",
        required_assertion_ids=list(required_assertion_ids or []),
        allowed_predicates=["value", "rank", "share_of_total", "classification"],
        forbidden_claims=["profit", "payment", "growth"],
        presentation_mode=presentation_mode,
    )


# --------------------------------------------------------------------------
# 8. ValidationResult — locatable, actionable failure (contracts §P1.5)
# --------------------------------------------------------------------------


class ValidationResult(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    status: Literal[
        "verified", "partially_verified", "insufficient_evidence", "rejected"
    ]
    stage: Literal[
        "plan_validation",
        "metric_validation",
        "calculation_validation",
        "structural_claim_validation",
        "semantic_grounding_validation",
        "output_gate",
    ]
    reason_code: str
    assertion_id: str | None = None
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    action: Literal[
        "replan", "refetch", "recalculate", "remove_claim", "human_review", "none"
    ] = "none"
