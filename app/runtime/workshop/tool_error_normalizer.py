"""ToolErrorNormalizer —— 工具错误归一化（上线门槛 2）。

Pydantic 校验 / 业务异常可能在进入 Tool body 之前或之中发生，不保证生成
约定的 DirectArtifact。本 middleware 用 wrap_tool_call 包裹工具执行，把
异常统一转换为归一化 ToolMessage（artifact 契约）：

- query_metric_direct 的异常 → DirectArtifact（status=model_argument_error /
  rejected，文案不归咎用户）
- 其他工具异常 → 原样传播（由 handle_tool_errors 处理）

FinalizeMiddleware 同时兼容 artifact 与框架原始错误 ToolMessage（兜底），
本模块只降低「无 artifact」的发生率，不承担最后防线。
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.runtime.workshop.direct_tool import TOOL_NAME


class ToolErrorNormalizer(AgentMiddleware):
    """把 direct 工具的执行/校验异常归一化为 DirectArtifact ToolMessage。"""

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        if request.tool_call.get("name") != TOOL_NAME:
            return handler(request)
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001 - 归一化而非吞掉
            artifact = {
                "status": "model_argument_error",
                "reply": f"当前未能形成有效查询：{_friendly(str(exc))}",
                "presentation": None,
                "detail": None,
                "trust_metrics": None,
                "evidence": [],
                "fast_path": None,
                "reason_code": "TOOL_EXECUTION_ERROR",
                "clarification": None,
                "options": [],
            }
            tool_call_id = request.tool_call.get("id")
            return ToolMessage(
                content=json.dumps(artifact, ensure_ascii=False),
                name=TOOL_NAME,
                tool_call_id=str(tool_call_id or ""),
                status="error",
            )


def _friendly(message: str) -> str:
    """异常 → 用户可读文案（截断 + 脱敏内部路径）。"""
    text = (message or "").strip().replace("\n", " ")
    if len(text) > 160:
        text = text[:157] + "…"
    return text or "工具执行失败"
