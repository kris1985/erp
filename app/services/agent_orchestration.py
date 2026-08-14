"""Bounded orchestration for the workshop assistant.

Lifecycle specialists are registry entries, never model-created agents.  This
module builds replayable child plans for the few analysis types that genuinely
need more than one domain view.  A child result is deliberately a compact
typed result plus an evidence summary; raw rows and model reasoning never
cross the controller boundary.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.analysis_plans import SemanticPlan
from app.services.agent_policy import get_policy_bundle
from app.services.lifecycle_agents import LifecycleAgentProfile, PROFILES, select_profiles


class ChildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_plan_id: str
    lifecycle_role: str
    analysis_type: str
    allowed_metric_ids: list[str]
    parent_semantic_plan: dict[str, Any]


class ChildResult(BaseModel):
    """The only payload a specialist may return to the controller."""

    model_config = ConfigDict(extra="forbid")

    child_plan_id: str
    lifecycle_role: str
    typed_result: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: list[str] = Field(default_factory=list, max_length=8)


_CROSS_DOMAIN_ROLES: dict[str, tuple[str, ...]] = {
    # A scenario can affect promise date, material availability and capacity.
    "scenario": ("order_commitment", "procurement_supply", "schedule_capacity"),
    # Decision is intentionally broad but still fixed and bounded.
    "decision": ("order_commitment", "procurement_supply", "schedule_capacity", "delivery_finance"),
}


def select_roles(question: str, plan: SemanticPlan | None) -> list[LifecycleAgentProfile]:
    """Choose registered roles from the semantic plan, with text as a tie-breaker."""
    by_id = {profile.id: profile for profile in PROFILES}
    if plan and plan.analysis_type in _CROSS_DOMAIN_ROLES:
        requested = _CROSS_DOMAIN_ROLES[plan.analysis_type]
        keyword_ids = {profile.id for profile in select_profiles(question)}
        # Scenario has a fixed maximum of three roles; decision uses only the
        # roles whose domain is actually mentioned, falling back to commitment.
        selected = [by_id[role_id] for role_id in requested if role_id in keyword_ids]
        if not selected:
            selected = [by_id[role_id] for role_id in requested[:1]]
        return selected[:3]
    if plan and plan.metric:
        metric = get_policy_bundle().metric_catalog.metrics.get(plan.metric)
        if metric:
            selected = [profile for profile in PROFILES if metric.metric_id in profile.metric_ids]
            if selected:
                return selected[:3]
    return select_profiles(question)


def build_child_plans(question: str, plan: SemanticPlan | None) -> list[ChildPlan]:
    """Return deterministic, replayable sub-plans for complex work only."""
    if not plan or plan.analysis_type not in _CROSS_DOMAIN_ROLES:
        return []
    roles = select_roles(question, plan)
    # A single domain has no coordination value and remains a normal plan.
    if len(roles) < 2:
        return []
    parent = plan.model_dump(mode="json")
    return [
        ChildPlan(
            child_plan_id=f"cp_{uuid.uuid4().hex[:16]}",
            lifecycle_role=role.id,
            analysis_type=plan.analysis_type,
            allowed_metric_ids=list(role.metric_ids),
            parent_semantic_plan=parent,
        )
        for role in roles
    ]


def sanitize_child_result(payload: dict[str, Any]) -> ChildResult:
    """Fail closed on raw data / chain-of-thought fields from a specialist."""
    forbidden = {"reasoning", "thought", "chain_of_thought", "raw_data", "rows", "result_id", "calculation_id"}
    def _contains_forbidden(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(forbidden.intersection(value)) or any(_contains_forbidden(item) for item in value.values())
        if isinstance(value, list):
            return any(_contains_forbidden(item) for item in value)
        return False

    if _contains_forbidden(payload):
        raise ValueError("child_result_contains_internal_data")
    return ChildResult.model_validate(payload)


def execute_child_plans(child_plans: list[ChildPlan], executor) -> list[ChildResult]:
    """Run a bounded executor and validate every specialist return payload."""
    return [sanitize_child_result(executor(child_plan)) for child_plan in child_plans]
