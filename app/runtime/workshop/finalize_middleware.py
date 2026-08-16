"""FinalizeMiddleware —— 统一收尾（架构定稿）。

``after_agent`` 覆盖所有路径（return_direct 短路 / 标准 agent loop）：
最后一条消息是 ToolMessage（query_metric_direct artifact）或 AIMessage，
统一归一为 UnifiedResponse。

1. artifact 解析：direct 路径按 status 分支（success / rejected /
   missing_user_input / ambiguous_user_input / model_argument_error）；
   兼容框架原始错误 ToolMessage（兜底，不假设 artifact 永远存在）。
2. 共用输出 guardrail（复用 schedule_agent.apply_evidence_guardrail）。
3. response normalization + presentation（direct 用 renderer 产物）。
4. 持久化（幂等）：record_run 按 run_id 覆盖、_save_ui_messages 覆盖写、
   _upsert_conversation upsert——三者均幂等；direct 路径追加本轮消息到
   历史（不覆盖丢历史）。失败不静默：日志 + 本地账本，不阻断响应。

边界：第一层业务验证（参数/权限/租户/数据完整性/evidence 充分性）在
DirectMetricExecutor 内（jump 之前）完成；本节点只做共用输出 guardrail
与收尾，不重新裁决业务。
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage

from app.runtime.workshop.direct_tool import TOOL_NAME
from app.runtime.workshop.util import last_human_text


def _last_message(messages: list[BaseMessage]) -> BaseMessage | None:
    return messages[-1] if messages else None


def _last_ai_reply(messages: list[BaseMessage]) -> str:
    """最后一条非空 AIMessage 文本（agent 路径）。"""
    for message in reversed(messages):
        mtype = getattr(message, "type", None) or message.__class__.__name__
        if mtype not in ("ai", "AIMessage"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def _extract_tool_evidence(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """state.messages 中 ToolMessage（不含 direct artifact 本身）→ 证据行。"""
    evidence: list[dict[str, str]] = []
    for message in messages:
        mtype = getattr(message, "type", None) or message.__class__.__name__
        if mtype not in ("tool", "ToolMessage"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = str(content)
        evidence.append(
            {
                "name": str(getattr(message, "name", None) or ""),
                "content": str(content or ""),
            }
        )
    return evidence


def _extract_direct_artifact(messages: list[BaseMessage]) -> dict[str, Any] | None:
    """最后一条 ToolMessage 若为 query_metric_direct 的 artifact JSON → 返回 dict。"""
    last = _last_message(messages)
    if last is None:
        return None
    mtype = getattr(last, "type", None) or last.__class__.__name__
    if mtype not in ("tool", "ToolMessage"):
        return None
    if getattr(last, "name", None) != TOOL_NAME:
        return None
    content = getattr(last, "content", "")
    if isinstance(content, list):
        content = str(content)
    if not isinstance(content, str) or not content:
        return None
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("status"), str):
        return data
    return None


class FinalizeMiddleware(AgentMiddleware):
    """两条执行路径共用的统一收尾节点。"""

    def after_agent(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        from app.services import schedule_agent

        context = getattr(runtime, "context", None)
        tenant_id = getattr(context, "tenant_id", None)
        if tenant_id is None:
            return None

        conversation_id = getattr(context, "conversation_id", "") or ""
        permission_codes = getattr(context, "permission_codes", None)
        question = last_human_text(state)
        messages = list(state.get("messages") or [])
        run_id = _current_run_id()

        artifact = _extract_direct_artifact(messages)
        if artifact is not None:
            response = self._finalize_direct(
                schedule_agent=schedule_agent,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                permission_codes=permission_codes,
                question=question,
                messages=messages,
                artifact=artifact,
                run_id=run_id,
                title=getattr(context, "title", None),
                state=state,
            )
        else:
            response = self._finalize_agent(
                schedule_agent=schedule_agent,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                permission_codes=permission_codes,
                question=question,
                messages=messages,
                run_id=run_id,
                title=getattr(context, "title", None),
                state=state,
            )

        return {
            "validation": response.get("evidence_guardrail"),
            "presentation": response.get("presentation"),
            "response": response,
            "evidence": response.get("evidence") or [],
        }

    # ------------------------------------------------------------------
    # direct 路径（最后一条是 artifact ToolMessage）
    # ------------------------------------------------------------------

    def _finalize_direct(
        self,
        *,
        schedule_agent: Any,
        tenant_id: int,
        conversation_id: str,
        permission_codes: list[str] | None,
        question: str,
        messages: list[BaseMessage],
        artifact: dict[str, Any],
        run_id: str,
        title: str | None,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        status = artifact.get("status")
        reply = str(artifact.get("reply") or "")
        reason_code = str(artifact.get("reason_code") or ("SUCCESS" if status == "success" else "REJECTED"))

        mode = "fast_path" if status == "success" else "fast_path_rejected"
        failure = None
        if status != "success":
            from app.runtime.workshop.fallback import fallback_action

            failure = {
                "reason_code": reason_code,
                "action": fallback_action(reason_code),
                "message": reply,
                "stage": "direct_tool",
            }

        guardrail: dict[str, Any] | None
        if status == "success":
            guardrail = {
                "passed": True,
                "reason": "direct_tool",
                "unmatched": [],
                "tool_names": [TOOL_NAME],
                "has_usable_payload": True,
            }
        else:
            guardrail = {
                "passed": False,
                "reason": reason_code,
                "unmatched": [],
                "tool_names": [],
                "has_usable_payload": False,
            }

        response: dict[str, Any] = {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "title": title,
            "reply": reply,
            "execution_mode": mode,
            "semantic_plan": None,
            "presentation": artifact.get("presentation"),
            "detail": artifact.get("detail") if isinstance(artifact.get("detail"), dict) else None,
            "trust_metrics": artifact.get("trust_metrics") if isinstance(artifact.get("trust_metrics"), dict) else None,
            "evidence": [],
            "evidence_guardrail": guardrail,
            "tool_traces": [],
            "fast_path": artifact.get("fast_path") if isinstance(artifact.get("fast_path"), dict) else None,
            "fast_path_rejection": None if status == "success" else {
                **({} if failure is None else failure),
                "reply": reply,
            },
            "fast_path_observation": None,
            "failure": failure,
            "messages": [],
            "direct_status": status,
        }

        # 持久化（幂等）：direct 路径追加本轮消息到历史，不覆盖丢历史
        self._persist_direct(
            schedule_agent=schedule_agent,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            question=question,
            reply=reply,
            presentation=response.get("presentation"),
            detail=response.get("detail"),
            run_id=run_id,
            status=status,
            title=title,
            failure=failure,
        )
        return response

    # ------------------------------------------------------------------
    # agent 路径（最后一条是 AIMessage）
    # ------------------------------------------------------------------

    def _finalize_agent(
        self,
        *,
        schedule_agent: Any,
        tenant_id: int,
        conversation_id: str,
        permission_codes: list[str] | None,
        question: str,
        messages: list[BaseMessage],
        run_id: str,
        title: str | None,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        reply = _last_ai_reply(messages)
        tool_evidence = _extract_tool_evidence(messages)
        injected = state.get("injected_evidence") or []
        if isinstance(injected, list):
            tool_evidence.extend(injected)

        reply, guardrail = schedule_agent.apply_evidence_guardrail(question, reply, tool_evidence)
        evidence = schedule_agent.build_evidence_ledger(tool_evidence, permission_codes=permission_codes)
        presentation_evidence = schedule_agent.build_evidence_ledger(
            tool_evidence, permission_codes=permission_codes, include_internal_refs=True
        )
        presentation = state.get("presentation")
        if presentation is None and question:
            presentation = schedule_agent.build_response_presentation(
                question, presentation_evidence, tenant_id=tenant_id
            )
            presentation = presentation if isinstance(presentation, dict) else None

        tool_traces: list[dict[str, Any]] = []
        for item in tool_evidence:
            tool_traces.append(
                {"name": item.get("name"), "content": str(item.get("content") or "")[:800]}
            )

        response: dict[str, Any] = {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "title": title,
            "reply": reply or "（无文本回复，请查看工具结果或重试）",
            "execution_mode": "agent",
            "semantic_plan": state.get("semantic_plan"),
            "presentation": presentation,
            "detail": None,
            "trust_metrics": None,
            "evidence": evidence,
            "evidence_guardrail": guardrail,
            "tool_traces": tool_traces[-8:],
            "fast_path": None,
            "fast_path_rejection": None,
            "fast_path_observation": (
                state.get("fast_path_observation") if isinstance(state.get("fast_path_observation"), dict) else None
            ),
            "failure": state.get("failure"),
            "messages": [],
        }

        self._persist_agent(
            schedule_agent=schedule_agent,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            messages=messages,
            question=question,
            reply=reply,
            presentation=presentation,
            tool_evidence=tool_evidence,
            guardrail=guardrail,
            run_id=run_id,
            title=title,
        )
        return response

    # ------------------------------------------------------------------
    # 持久化（幂等：record_run run_id 覆盖 / _save_ui_messages 覆盖写 /
    # _upsert_conversation upsert；失败记录日志与账本，不阻断响应）
    # ------------------------------------------------------------------

    @staticmethod
    def _persist_direct(
        *,
        schedule_agent: Any,
        tenant_id: int,
        conversation_id: str,
        question: str,
        reply: str,
        presentation: dict[str, Any] | None,
        detail: dict[str, Any] | None,
        run_id: str,
        status: str,
        title: str | None,
        failure: dict[str, Any] | None,
    ) -> None:
        import logging

        logger = logging.getLogger(__name__)
        try:
            schedule_agent._upsert_conversation(tenant_id, conversation_id, title=title)
        except Exception as exc:  # noqa: BLE001
            logger.error("conversation persist failed: %s", exc)

        # 追加本轮到历史（不覆盖丢历史）：读现有 → append → 覆盖写
        try:
            existing = _load_cached_ui_messages(schedule_agent, tenant_id, conversation_id)
            history = list(existing) if isinstance(existing, list) else []
            history.append({"role": "user", "content": question, "path": "fast_path"})
            history.append({
                "role": "assistant",
                "content": reply,
                "presentation": presentation,
                "detail": detail,
                "path": "fast_path",
                "run_id": run_id,
                "status": status,
            })
            schedule_agent._save_ui_messages(tenant_id, conversation_id, history)
        except Exception as exc:  # noqa: BLE001
            logger.error("ui_messages persist failed: %s", exc)

        try:
            schedule_agent._record_agent_trace(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=run_id,
                planner=None,
                execution_plan=None,
                tool_evidence=[],
                guardrail=None,
                outcome="direct_fast_path" if status == "success" else f"direct_{status}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("agent trace record failed: %s", exc)

    @staticmethod
    def _persist_agent(
        *,
        schedule_agent: Any,
        tenant_id: int,
        conversation_id: str,
        messages: list[BaseMessage],
        question: str,
        reply: str,
        presentation: dict[str, Any] | None,
        tool_evidence: list[dict[str, str]],
        guardrail: dict[str, Any] | None,
        run_id: str,
        title: str | None,
    ) -> None:
        import logging

        logger = logging.getLogger(__name__)
        try:
            schedule_agent._upsert_conversation(tenant_id, conversation_id, title=title)
        except Exception as exc:  # noqa: BLE001
            logger.error("conversation persist failed: %s", exc)

        try:
            ui_messages = schedule_agent._serialize_ui_messages(list(messages), permission_codes=None)
            if ui_messages:
                schedule_agent._save_ui_messages(tenant_id, conversation_id, ui_messages)
        except Exception as exc:  # noqa: BLE001
            logger.error("ui_messages persist failed: %s", exc)

        try:
            schedule_agent._record_agent_trace(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=run_id,
                planner=None,
                execution_plan=None,
                tool_evidence=tool_evidence,
                guardrail=guardrail,
                outcome="completed",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("agent trace record failed: %s", exc)


def _load_cached_ui_messages(schedule_agent: Any, tenant_id: int, conversation_id: str) -> list[dict[str, Any]] | None:
    """读 conversations.ui_messages（幂等持久化的历史源）。"""
    try:
        import json as _json
        import sqlite3
        from pathlib import Path

        path = Path(schedule_agent._data_dir()) / "conversations.sqlite"
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT ui_messages FROM conversations WHERE id=? AND tenant_id=?",
                (conversation_id, tenant_id),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return None
        data = _json.loads(row[0])
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _current_run_id() -> str:
    """从 langgraph config 取 run_id（_agent_run_config 注入）；缺省生成。"""
    import uuid

    try:
        from langgraph.config import get_config

        config = get_config()
        run_id = (config or {}).get("run_id")
        if run_id:
            return str(run_id)
    except Exception:
        pass
    return f"run_{uuid.uuid4().hex[:16]}"
