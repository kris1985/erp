"""统一 Response Layer（架构定稿 §2.3/§9 P3）。

两个分支（FastPath / DeepAgent）都写入同一 ConversationState；本模块是
**唯一的** guardrail + evidence 折叠点：

- ``apply_response_guardrail``：对最终 reply 跑 guardrail（复用
  schedule_agent.apply_evidence_guardrail，一套语义），失败 → 显式
  EVIDENCE_FAILED → fail_closed（不静默放行）。
- ``fold_evidence``：把分支产物（result_ids / facts）折叠为
  state.evidence 统一结构。

移除 FastPath 硬编码 ``evidence_guardrail: passed``——guardrail 只在此处
执行，两分支无两套语义。
"""

from __future__ import annotations

from typing import Any

from app.runtime.orchestration.state import ConversationState, EvidenceItem, Failure


def apply_response_guardrail(state: ConversationState) -> dict[str, Any]:
    """对最终 reply 跑 guardrail（唯一入口）。

    - FastPath：reply 来自 verified assertions（确定性，通常通过），但仍过
      guardrail（数字必须能在证据中找到）——不再硬编码 passed。
    - DeepAgent：reply 来自 agent 输出，guardrail 校验数字可追溯性。

    失败 → EVIDENCE_FAILED → fail_closed；成功 → 返回 guardrail 结果。
    """
    from app.services.schedule_agent import apply_evidence_guardrail

    execution = state.get("execution_result") or {}
    payload = execution.get("payload") or {}
    reply = str(payload.get("reply") or "")
    evidence = state.get("evidence") or []
    question = state.get("question", "")

    if not reply:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="guardrail",
        )}

    tool_evidence = [
        {"name": item.get("source", ""), "content": _evidence_content(item)}
        for item in evidence
    ]
    try:
        guarded, guardrail = apply_evidence_guardrail(question, reply, tool_evidence)
    except Exception:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="guardrail",
        )}

    if not guardrail.get("passed", False):
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="guardrail",
            message=guardrail.get("reason") or "回答未通过证据校验",
        )}

    return {"_guardrail": guardrail, "execution_result": {
        **(execution),
        "payload": {**payload, "reply": guarded},
    }}


def fold_evidence(state: ConversationState) -> dict[str, Any]:
    """把分支产物折叠为 state.evidence 统一结构。

    FastPath：execution_result.result_ids + payload.facts → evidence 条目
    （facts 携带数字，供 guardrail 校验可追溯性）。
    DeepAgent：从 execution_result 或 state 已有证据折叠。
    """
    execution = state.get("execution_result") or {}
    result_ids = execution.get("result_ids") or []
    if not result_ids:
        return {}

    payload = execution.get("payload") or {}
    facts = payload.get("facts") or []
    existing = {item.get("id") for item in (state.get("evidence") or [])}
    items: list[EvidenceItem] = []
    for result_id in result_ids:
        if result_id in existing:
            continue
        items.append(EvidenceItem(
            id=result_id,
            source=str((state.get("route") or {}).get("capability") or "analysis"),
            status="已核验",
            facts=[str(f) for f in facts],
        ))
    return {"evidence": (state.get("evidence") or []) + items}


def _evidence_content(item: EvidenceItem) -> str:
    """把 evidence 条目转回 tool_evidence 的 content 形态（供 guardrail 校验）。"""
    import json

    return json.dumps({"result_id": item.get("id"), "source": item.get("source")}, ensure_ascii=False)
