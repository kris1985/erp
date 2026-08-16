"""WorkshopContext —— run-scoped 不可变上下文（context_schema）。

经 ``create_deep_agent(context_schema=...)`` 注入；middleware 通过
``runtime.context`` 读取。tenant_id / conversation_id / permission_codes
是每轮请求的执行上下文；跨轮工作产物（semantic_plan 等）走 state
（checkpoint 持久化）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkshopContext:
    tenant_id: int
    conversation_id: str
    permission_codes: list[str] | None = None
    title: str | None = None
    transport: str = "sync"
    extra: dict[str, Any] = field(default_factory=dict)
