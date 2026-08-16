"""query_metric_direct —— 强类型、return_direct 的确定性指标工具。

- 强类型参数（DirectMetricRequest）：function calling 的 API 层保证结构，
  主模型一次调用同时完成意图识别、指标选择、时间解析、继承与参数编译。
- return_direct=True：工具执行完成（成功/受控拒绝/参数错误）直接进入
  after_agent 统一收尾，不回到主模型重新解释（避免二次模型调用把已正确的
  指标结果解释错）。
- 可信链在 Tool 内（DirectMetricExecutor）：不信任模型参数，重校验。
- 输出：归一化 DirectArtifact（JSON ToolMessage.content）。

调用约束（DirectToolCallPolicy 强制执行）：query_metric_direct 必须独占
调用——同一 AIMessage 中不得与其他工具混合，避免 return_direct 短路时
其他工具（尤其写操作）已并行产生副作用。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool

from app.runtime.workshop.executor import DirectMetricExecutor
from app.runtime.workshop.request import DirectMetricRequest

TOOL_NAME = "query_metric_direct"

_TOOL_DESCRIPTION = (
    "直接指标查询（确定性、一次命中、有证据校验）。"
    "当问题能精确映射到单个已注册指标且参数明确时调用："
    "指标 ID、维度、时间范围、筛选、排序、条数都由你从用户问题中解析并给出。"
    "支持指标：finance.customer_sales_ranking（客户销售额排行，dimension=customer，按销售额排序）、"
    "finance.sales_snapshot（销售额快照，单值）。"
    "规则：1) 必须独占调用——同一轮输出中不得再调用任何其他工具；"
    "2) 用户使用承接表达（那/再看/换成/只看/前十/上月呢）时，继承上一轮成功查询的未修改参数；"
    "3) 不适用于需要多步探索、跨指标比较或归因分析的复杂问题（改用 query_metric）。"
)


def build_query_metric_direct(
    *,
    tenant_id: int,
    conversation_id: str,
    permission_codes: list[str] | None,
) -> StructuredTool:
    """在 _build_tools 闭包内构造 direct 工具（上下文经闭包捕获）。"""

    def _run(**_kwargs: Any) -> str:
        from app.db import SessionLocal

        request = DirectMetricRequest.model_validate(_kwargs)
        with SessionLocal() as db:
            artifact = DirectMetricExecutor().execute(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                permission_codes=permission_codes,
                request=request,
            )
        return json.dumps(artifact, ensure_ascii=False, default=str)

    return StructuredTool.from_function(
        func=_run,
        name=TOOL_NAME,
        description=_TOOL_DESCRIPTION,
        args_schema=DirectMetricRequest,
        return_direct=True,
    )
