"""Fast Path 的 LangSmith 追踪（2026-08-17）。

背景：Fast Path（ranking / metric_snapshot）整个链路在 LangGraph 之外——
``iter_chat_sse`` 直接调用 ``run_fast_path`` 短路返回，不经过
``agent.invoke(config=run_config)``，因此主链的 LangChainTracer callback
对它不生效，LangSmith 里完全看不到 Fast Path 的 propose 输入/输出、路由
决策、执行与校验（上一轮线上 Trace 已证实：Fast Path 分支无任何 run）。

本模块提供 ``fast_path_traced`` 装饰器：用 settings 显式构造 langsmith
Client（key 在 .env，不在进程环境变量里，traceable 自动发现不到），
以独立 trace 记录 Fast Path 的关键函数。观测性必须 fail-open：任何
LangSmith 配置/网络异常都只跳过追踪，绝不阻断生产决策路径。

与本地账本的关系：``agent_trace_service``（JSON blob）保留，两者并存——
LangSmith = 实时追踪（含 LLM propose 子 run），agent_trace_service =
本地账本（result_ids / calculation_ids / versions）。
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
    """装饰 Fast Path 关键函数，使其进入 LangSmith（独立 trace）。

    fail-open 只在**装配期**生效：settings 未启用或 client 构造失败时
    原样返回原函数（不追踪）。一旦装配成功，被包装函数自身抛出的异常
    原样向上传播（那是业务异常，必须冒泡）；追踪层不做二次执行。
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
