"""ContextProjection tests (PR #6, contracts §P0.1).

Acceptance: the model input is the projection only — current question,
confirmed constraints, active entities, current evidence summary, allowed
actions and necessary memories; historical tool results, sub-agent text and
execution state never appear; cross-turn inheritance follows Case 12.
"""

from __future__ import annotations

from app.runtime.context import (
    ContextProjector,
    ConversationState,
    estimate_tokens,
    update_conversation,
)
from app.runtime.spill import SpilledResult

PROJECTOR = ContextProjector()


def spilled(result_id: str) -> SpilledResult:
    return SpilledResult(
        result_id=result_id,
        result_schema="ranking",
        summary="4 行排名",
        preview="客户 A（第 1 名）",
        truncated=False,
        stored_bytes=120,
    )


def test_projection_excludes_history_and_execution() -> None:
    state = ConversationState(
        current_turn="customer_sales_ranking",
        last_intent="customer_sales_ranking",
        confirmed_constraints={"year": 2026},
        active_entities=["customer:A", "customer:B"],
    )
    projection = PROJECTOR.project(
        question="前两名客户占多少？",
        conversation=state,
        evidence=spilled("r_s3"),
        allowed_actions=["query_metric", "inspect_result"],
        memories=["客户厦门海丝偏好整箱出货"],
    )
    refs = projection.content_refs()
    assert "user.question" in refs
    assert "conversation.confirmed_constraints" in refs
    assert "conversation.active_entities" in refs
    assert "r_s3" in refs
    assert "policy.allowed_actions" in refs
    assert "memory" in refs
    # No historical tool results, no sub-agent text, no execution state.
    for leaked in ("r_p1", "r_s2", "execution_state", "tool_call", "sub_agent"):
        assert leaked not in refs
    reasons = {b.projection_reason for b in projection.blocks}
    assert reasons == {
        "current_question",
        "confirmed_constraints",
        "active_entities",
        "current_evidence",
        "allowed_actions",
        "required_memory",
    }


def test_every_block_is_auditable() -> None:
    state = ConversationState(confirmed_constraints={"year": 2026}, active_entities=["customer:A"])
    projection = PROJECTOR.project(question="客户销售额排行", conversation=state)
    for block in projection.blocks:
        assert block.content_ref
        assert block.projection_reason
        assert block.token_cost == estimate_tokens(block.content)
    assert projection.estimated_tokens == sum(b.token_cost for b in projection.blocks)


def test_as_messages_is_system_plus_question() -> None:
    state = ConversationState(confirmed_constraints={"year": 2026})
    projection = PROJECTOR.project(question="客户销售额排行", conversation=state)
    messages = projection.as_messages()
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    assert "2026" in messages[0]["content"]


def test_token_budget_clips_low_priority_blocks() -> None:
    tight = ContextProjector(token_budget=50)
    state = ConversationState(confirmed_constraints={"year": 2026}, active_entities=["customer:A"])
    projection = tight.project(
        question="客户销售额排行",
        conversation=state,
        memories=["记忆一" * 100, "记忆二" * 100],
    )
    # The question block is never clipped.
    assert projection.blocks[0].content_ref == "user.question"
    assert projection.truncation_reasons, "expected budget truncation"
    assert projection.original_message_count > projection.projected_message_count


def test_same_topic_inherits_constraints_and_entities() -> None:
    state = ConversationState(confirmed_constraints={"year": 2026}, active_entities=["customer:A"])
    next_state = update_conversation(
        state,
        intent="customer_sales_ranking",
        metric_id="finance.customer_sales_ranking",
        scope={"limit": 3},
        entities=None,
        prev_metric_id="finance.customer_sales_ranking",
    )
    assert next_state.confirmed_constraints == {"year": 2026, "limit": 3}
    assert next_state.active_entities == ["customer:A"]


def test_metric_change_inherits_only_carried_entities() -> None:
    """Case 12 turn 4: 指标变更 -> 只继承实体，约束重置，不继承上一轮 Evidence."""
    state = ConversationState(
        confirmed_constraints={"year": 2026}, active_entities=["customer:A", "customer:B"]
    )
    next_state = update_conversation(
        state,
        intent="payment_collection",
        metric_id="finance.payment_collection",
        scope={"month": "2026-07"},
        entities=["customer:A", "customer:B"],
        prev_metric_id="finance.customer_sales_ranking",
    )
    assert next_state.confirmed_constraints == {"month": "2026-07"}
    assert "year" not in next_state.confirmed_constraints
    assert next_state.active_entities == ["customer:A", "customer:B"]
