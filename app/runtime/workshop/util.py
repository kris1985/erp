"""领域层通用工具。"""

from __future__ import annotations

from typing import Any


def last_human_text(state: dict[str, Any]) -> str:
    """从 state.messages 提取最后一个 HumanMessage 文本。"""
    for message in reversed(state.get("messages") or []):
        content = getattr(message, "content", None)
        if content is None:
            continue
        mtype = getattr(message, "type", None) or message.__class__.__name__
        if mtype in ("human", "HumanMessage"):
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = "".join(parts)
                if text:
                    return text
    return ""
