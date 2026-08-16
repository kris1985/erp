"""DirectToolCallPolicy —— query_metric_direct 独占调用策略（上线阻断项）。

问题：return_direct 工具的退出判定（_make_tools_to_model_edge）基于
「最后 AIMessage 的全部 client-side tool_calls 是否 return_direct」。
模型若在同一 AIMessage 中混合调用 query_metric_direct 与其他工具
（尤其写操作工具），LangGraph 会**执行全部工具**后回模型——direct 的
短路语义被破坏，且其他工具可能已并行产生副作用。

策略（after_model，model 节点之后、tools 节点之前）：
- direct 出现且是唯一调用 → 放行（正常执行 + return_direct 短路）
- direct 与其他工具混合 → 拒绝执行本轮全部 calls：
    第一次违规 → 注入策略消息 + jump_to="model" 让模型重新生成（预算内）
    再次违规（同 run 计数 ≥ 上限）→ jump_to="end" 受控拒绝（不执行任何工具）

注意：jump_to="model" 会再消耗一次模型调用；由 ToolCallLimitMiddleware /
recursion_limit 双重封顶，杜绝无界循环。
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import SystemMessage

from app.runtime.workshop.direct_tool import TOOL_NAME

_MAX_POLICY_RETRIES = 1  # 最多允许模型重新生成一次


class DirectToolCallPolicy(AgentMiddleware):
    """query_metric_direct 必须独占调用。"""

    @hook_config(can_jump_to=["model", "end"])
    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        tool_calls = _last_ai_tool_calls(state)
        if not tool_calls:
            return None
        direct_calls = [call for call in tool_calls if call.get("name") == TOOL_NAME]
        if not direct_calls:
            return None  # 本轮回合未调用 direct → 放行

        if len(tool_calls) == 1:
            return None  # direct 独占 → 放行（执行后 return_direct 短路）

        # 违规：direct 与其他工具混合。计数，决定重试或拒绝。
        attempts = int(state.get("_direct_policy_attempts") or 0) + 1
        if attempts <= _MAX_POLICY_RETRIES:
            return {
                "_direct_policy_attempts": attempts,
                "jump_to": "model",
                "messages": [
                    SystemMessage(
                        "策略：query_metric_direct 必须独占调用，同一轮输出中不得"
                        "与其他工具混合。请重新生成唯一的 query_metric_direct 调用"
                        "（或改用 query_metric 走探索路径）。"
                    )
                ],
            }

        # 超过重试上限：受控拒绝（不执行任何工具）
        return {
            "_direct_policy_attempts": attempts,
            "jump_to": "end",
            "messages": [
                SystemMessage(
                    "本轮工具调用违反独占策略且重试超限，已终止执行。"
                )
            ],
        }


def _last_ai_tool_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    """最后一条 AIMessage 的 tool_calls（空列表表示无）。"""
    for message in reversed(state.get("messages") or []):
        mtype = getattr(message, "type", None) or message.__class__.__name__
        if mtype not in ("ai", "AIMessage"):
            continue
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            return [dict(call) for call in calls if isinstance(call, dict)]
        return []
    return []
