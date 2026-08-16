"""Minimal ContextProjection for the ranking slice (PR #6, contracts §3.1/§P0.1).

The projection is the only thing a model ever sees: current question,
confirmed constraints, active entities, the current evidence summary and
allowed actions.  Full history stays in the event store / checkpoint for
audit and replay; it is never replayed into the model input — State != Model
Context.

Every block records ``content_ref``, ``projection_reason``, ``source_event_id``
and ``token_cost`` so “why is this in the context” is auditable.  A token
budget clips low-priority blocks and records the truncation reason.

Cross-turn inheritance (Case 12 semantics, contracts §3.6 aggregation):
same metric_id + scope -> inherit constraints and entities; metric change ->
inherit only explicitly carried entities, never the previous evidence.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import Field

from app.runtime.contracts import RuntimeModel, SCHEMA_VERSION
from app.runtime.spill import SpilledResult

DEFAULT_TOKEN_BUDGET = 4000
# Deliberately coarse: ~2 chars per token for mixed CN/EN text.  The real
# tokenizer count is recorded by the harness; this is the projection planner's
# own estimate used for budget clipping.
CHARS_PER_TOKEN = 2


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


class ConversationState(RuntimeModel):
    """Only what is still valid for the current task (contracts §3.1)."""

    current_turn: str = ""
    last_intent: str | None = None
    confirmed_constraints: dict[str, Any] = Field(default_factory=dict)
    active_entities: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class ProjectionBlock(RuntimeModel):
    content_ref: str
    projection_reason: str
    source_event_id: str | None = None
    token_cost: int = 0
    content: str


class ContextProjection(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    turn_id: str
    blocks: list[ProjectionBlock] = Field(default_factory=list)
    original_message_count: int = 0
    projected_message_count: int = 0
    truncation_reasons: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0

    def content_refs(self) -> list[str]:
        return [block.content_ref for block in self.blocks]

    def as_messages(self, *, system_role: str = "你是鞋厂「车间军师」排产参谋，只基于提供的数据作答。") -> list[dict[str, str]]:
        """The projected model input: one system block + the question."""
        body = "\n".join(block.content for block in self.blocks)
        return [{"role": "system", "content": f"{system_role}\n{body}"}]


def update_conversation(
    prev: ConversationState,
    *,
    intent: str,
    metric_id: str,
    scope: dict[str, Any],
    entities: list[str] | None,
    prev_metric_id: str | None,
) -> ConversationState:
    """Cross-turn inheritance: same topic merges, topic change resets to
    explicitly carried entities only (Case 12)."""
    same_topic = prev_metric_id is not None and metric_id == prev_metric_id
    constraints = {**prev.confirmed_constraints, **scope} if same_topic else dict(scope)
    if entities is not None:
        active = list(entities)
    elif same_topic:
        active = list(prev.active_entities)
    else:
        active = []
    return ConversationState(
        current_turn=intent,
        last_intent=intent,
        confirmed_constraints=constraints,
        active_entities=active,
        unresolved_questions=list(prev.unresolved_questions) if same_topic else [],
    )


class ContextProjector:
    def __init__(self, token_budget: int = DEFAULT_TOKEN_BUDGET) -> None:
        self._budget = token_budget

    def project(
        self,
        *,
        question: str,
        conversation: ConversationState,
        evidence: SpilledResult | None = None,
        allowed_actions: list[str] | None = None,
        memories: list[str] | None = None,
        source_event_ids: dict[str, str] | None = None,
        turn_id: str | None = None,
    ) -> ContextProjection:
        events = source_event_ids or {}
        blocks: list[ProjectionBlock] = []
        truncation: list[str] = []

        def add(content_ref: str, reason: str, content: str) -> None:
            blocks.append(
                ProjectionBlock(
                    content_ref=content_ref,
                    projection_reason=reason,
                    source_event_id=events.get(content_ref),
                    token_cost=estimate_tokens(content),
                    content=content,
                )
            )

        # 1. current question (never clipped)
        add("user.question", "current_question", question)

        # 2. confirmed constraints
        if conversation.confirmed_constraints:
            add(
                "conversation.confirmed_constraints",
                "confirmed_constraints",
                "已确认约束：" + json.dumps(conversation.confirmed_constraints, ensure_ascii=False),
            )

        # 3. active entities
        if conversation.active_entities:
            add(
                "conversation.active_entities",
                "active_entities",
                "当前关注实体：" + "、".join(conversation.active_entities),
            )

        # 4. current evidence summary only (never historical tool results)
        if evidence is not None:
            add(
                evidence.result_id,
                "current_evidence",
                evidence.render(),
            )

        # 5. allowed actions
        if allowed_actions:
            add("policy.allowed_actions", "allowed_actions", "允许动作：" + "、".join(allowed_actions))

        # 6. necessary memories (lowest priority, clipped first)
        for memory in memories or []:
            add("memory", "required_memory", memory)

        # Token budget: clip low-priority blocks from the tail.
        original = len(blocks)
        while len(blocks) > 1 and sum(b.token_cost for b in blocks) > self._budget:
            dropped = blocks.pop()
            truncation.append(f"{dropped.content_ref}:budget_exceeded")

        return ContextProjection(
            turn_id=turn_id or f"t_{uuid.uuid4().hex[:8]}",
            blocks=blocks,
            original_message_count=original,
            projected_message_count=len(blocks),
            truncation_reasons=truncation,
            estimated_tokens=sum(b.token_cost for b in blocks),
        )
