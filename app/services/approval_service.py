"""Auditable human-in-the-loop state machine for irreversible agent actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models import AgentApproval
from app.services.agent_policy import get_policy_bundle

ApprovalStatus = Literal["draft", "pending_approval", "approved", "rejected", "executed", "expired"]
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_approval", "expired"},
    "pending_approval": {"approved", "rejected", "expired"},
    "approved": {"executed", "expired"},
    "rejected": set(), "executed": set(), "expired": set(),
}


def _utcnow() -> datetime:
    """UTC wall-clock value compatible with the existing naive DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class ApprovalError(ValueError):
    pass


def _require_governed_action(action: str) -> None:
    policy = get_policy_bundle().action_policy.actions.get(action)
    if policy != "approval_required":
        raise ApprovalError("action_not_approval_required")


def create_draft(
    db: Session, *, tenant_id: int, action: str, requested_by: int | None,
    evidence: list[dict[str, Any]], impact_objects: list[dict[str, Any]],
    execution_payload: dict[str, Any], expires_in_hours: int = 24,
) -> AgentApproval:
    _require_governed_action(action)
    if not evidence or not impact_objects:
        raise ApprovalError("approval_requires_evidence_and_impact_objects")
    row = AgentApproval(
        tenant_id=tenant_id, action=action, status="draft", requested_by=requested_by,
        evidence=evidence, impact_objects=impact_objects, execution_payload=execution_payload,
        expires_at=_utcnow() + timedelta(hours=max(1, min(expires_in_hours, 168))),
    )
    db.add(row)
    db.flush()
    return row


def transition(db: Session, approval: AgentApproval, *, target: ApprovalStatus, actor_id: int | None = None) -> AgentApproval:
    if approval.expires_at and approval.expires_at <= _utcnow() and approval.status not in {"executed", "rejected", "expired"}:
        approval.status = "expired"
        db.flush()
        raise ApprovalError("approval_expired")
    if target not in _TRANSITIONS.get(approval.status, set()):
        raise ApprovalError(f"invalid_approval_transition:{approval.status}:{target}")
    approval.status = target
    now = _utcnow()
    if target in {"approved", "rejected"}:
        approval.approved_by = actor_id
        approval.decided_at = now
    if target == "executed":
        approval.executed_by = actor_id
        approval.executed_at = now
    db.flush()
    return approval


def submit(db: Session, approval: AgentApproval) -> AgentApproval:
    return transition(db, approval, target="pending_approval")


def approve(db: Session, approval: AgentApproval, *, approver_id: int) -> AgentApproval:
    return transition(db, approval, target="approved", actor_id=approver_id)


def reject(db: Session, approval: AgentApproval, *, approver_id: int) -> AgentApproval:
    return transition(db, approval, target="rejected", actor_id=approver_id)


def mark_executed(db: Session, approval: AgentApproval, *, executor_id: int) -> AgentApproval:
    """A caller may invoke the real write only after this approval is approved."""
    return transition(db, approval, target="executed", actor_id=executor_id)


def expire_open_approvals(db: Session, *, now: datetime | None = None) -> int:
    now = now or _utcnow()
    rows = db.query(AgentApproval).filter(
        AgentApproval.status.in_(["draft", "pending_approval", "approved"]),
        AgentApproval.expires_at <= now,
    ).all()
    for row in rows:
        row.status = "expired"
    db.flush()
    return len(rows)
