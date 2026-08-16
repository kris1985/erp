"""LangSmith 追踪（Tool-first Direct Path 架构定稿）。

Fast Path 已进入 DeepAgent 图内（query_metric_direct 工具），LangGraph 的
LangChainTracer 自动建立 root run（workshop-agent run）；工具执行本身就是
子 run。本模块提供 ``fast_path_traced`` 装饰器，让 FastPath 内部关键函数
创建**继承当前 run tree 的子 span**——当调用发生在 active run 上下文内
（LangChainTracer 挂载时）自动嵌套；无 active run（如脚本单独调用）时
作为独立 trace。

不再显式创建独立 root trace（旧旁路时代的行为）。可观测性必须 fail-open：
任何 LangSmith 配置/网络异常都只跳过追踪，绝不阻断生产决策路径。

与本地账本的关系：``agent_trace_service``（JSON blob，run_id 幂等覆盖）
保留，两者并存——LangSmith = 实时追踪，本地账本 = result_ids / versions。
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from app.config import get_settings

_F = TypeVar("_F", bound=Callable[..., Any])


def fast_path_traced(
    name: str,
    *,
    run_type: str = "chain",
    tags: list[str] | None = None,
) -> Callable[[_F], _F]:
    """装饰 Fast Path 关键函数：继承当前 run tree 的子 span（fail-open）。

    - active run 上下文内调用 → 自动成为当前 run 的子 span（单 root run）；
    - 无 active run → 独立 trace（保持可观测）；
    - settings 未启用 / client 构造失败 → 原样返回原函数（不追踪）。
    """

    def decorator(func: _F) -> _F:
        settings = get_settings()
        if not (settings.langsmith_tracing and settings.langsmith_api_key):
            return func

        try:
            from langsmith import Client, traceable

            client = Client(
                api_key=settings.langsmith_api_key,
                api_url=settings.langsmith_endpoint.rstrip("/"),
            )
        except Exception:
            return func

        traced = traceable(
            name=name,
            run_type=run_type,
            client=client,
            project_name=settings.langsmith_project,
            tags=tags or [],
        )(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return traced(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
