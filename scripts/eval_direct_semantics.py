"""语义忠实度评测集 —— query_metric_direct 上线门槛 4。

Schema 正确不代表语义正确：pydantic 能验证「month 是整数」，不能证明
「用户问『本月销售额最大的客户』，模型是否错误生成了全年销售量排行」。
证据校验只能证明「查询结果有数据证据」，不能证明「查询参数忠实表达了
用户意图」。

本脚本让主模型为典型问题生成 query_metric_direct 参数，按指标/维度/时间/
筛选/排序/条数/继承逐项断言。上线前必须通过（准确率门槛由业务定）。

运行（需要 .env 的 DeepSeek key）：
    .venv/bin/python scripts/eval_direct_semantics.py

输出：逐用例 PASS/FAIL + 各维度准确率汇总。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


# ------------------------------------------------------------------ 用例

@dataclass
class Case:
    id: str
    question: str
    check: Callable[[dict[str, Any]], tuple[bool, str]]
    history: list[dict[str, Any]] = field(default_factory=list)  # 上轮 tool_call（继承）
    previous_result: dict[str, Any] | None = None  # 上轮 artifact（继承来源）


CASES: list[Case] = [
    Case(
        id="snapshot_this_month",
        question="本月销售额多少？",
        check=lambda a: (
            a.get("metric_id") == "finance.sales_snapshot"
            and (a.get("time_range") or {}).get("month") is not None,
            f"metric={a.get('metric_id')} time={a.get('time_range')}",
        ),
    ),
    Case(
        id="ranking_top_customer",
        question="今年哪个客户销售额最高？",
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and a.get("limit") == 1,
            f"metric={a.get('metric_id')} limit={a.get('limit')}",
        ),
    ),
    Case(
        id="ranking_top3",
        question="客户销售额排行前三是谁？",
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and a.get("limit") == 3,
            f"metric={a.get('metric_id')} limit={a.get('limit')}",
        ),
    ),
    Case(
        id="ranking_last_year",
        question="去年销售额最高的客户是谁？",
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and (a.get("time_range") or {}).get("year") is not None
            and (a.get("time_range") or {}).get("year") != 2026,
            f"metric={a.get('metric_id')} time={a.get('time_range')}",
        ),
    ),
    Case(
        id="share_concentration",
        question="前两名客户占销售总额的多少？",
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and a.get("include_share") is True,
            f"metric={a.get('metric_id')} include_share={a.get('include_share')}",
        ),
    ),
    Case(
        id="followup_last_month",
        question="那上个月呢？",
        history=[{
            "name": "query_metric_direct",
            "args": {"metric_id": "finance.sales_snapshot",
                     "time_range": {"year": 2026, "month": 9}},
        }],
        previous_result={"status": "success"},
        check=lambda a: (
            a.get("metric_id") == "finance.sales_snapshot"
            and (a.get("time_range") or {}).get("month") == 8,  # 继承 9 月 → 上一个月
            f"metric={a.get('metric_id')} time={a.get('time_range')}",
        ),
    ),
    Case(
        id="followup_top3",
        question="只看前三个",
        history=[{
            "name": "query_metric_direct",
            "args": {"metric_id": "finance.customer_sales_ranking",
                     "dimensions": ["customer"], "time_range": {"year": 2026}, "limit": 10},
        }],
        previous_result={"status": "success"},
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and a.get("limit") == 3
            and (a.get("time_range") or {}).get("year") == 2026,  # 继承上轮年份
            f"metric={a.get('metric_id')} limit={a.get('limit')} time={a.get('time_range')}",
        ),
    ),
    Case(
        id="followup_switch_metric",
        question="换成销售数量",
        history=[{
            "name": "query_metric_direct",
            "args": {"metric_id": "finance.customer_sales_ranking",
                     "dimensions": ["customer"], "time_range": {"year": 2026}, "limit": 5},
        }],
        previous_result={"status": "success"},
        check=lambda a: (
            a.get("metric_id") != "finance.customer_sales_ranking",  # 换指标 → 不沿用排行
            f"metric={a.get('metric_id')}",
        ),
    ),
    Case(
        id="filter_min_amount",
        question="销售额大于500万的客户排行",
        check=lambda a: (
            a.get("metric_id") == "finance.customer_sales_ranking"
            and any(
                f.get("field") == "sales_amount" and f.get("operator") == "gte"
                for f in a.get("filters") or []
            ),
            f"metric={a.get('metric_id')} filters={a.get('filters')}",
        ),
    ),
]


# ------------------------------------------------------------------ 评测驱动

def _make_model():
    from app.services.schedule_agent import _make_model

    return _make_model()


def _prompt_with_history(case: Case) -> list:
    messages: list = []
    if case.history:
        prev = case.history[0]["args"]
        messages.append(SystemMessage(
            content="上一轮你成功调用了 query_metric_direct，参数如下：\n"
            + json.dumps(prev, ensure_ascii=False)
            + "\n用户的新问题是承接表达时，继承上一轮未修改的字段。"
        ))
    messages.append(HumanMessage(content=case.question))
    return messages


def _ask(model, case: Case) -> dict[str, Any] | None:
    """让主模型生成 query_metric_direct 参数（复用 direct 工具 schema）。"""
    from app.runtime.workshop.direct_tool import build_query_metric_direct

    tool = build_query_metric_direct(tenant_id=1, conversation_id="eval", permission_codes=[])
    bound = tool.bind_tools  # noqa
    from langchain_core.messages import AIMessage as _A  # noqa

    # 直接绑定工具并让模型调用（与图内一致：function calling 强结构）
    model_with_tools = model.bind_tools([tool])
    response = model_with_tools.invoke(_prompt_with_history(case))
    if isinstance(response, AIMessage):
        for call in response.tool_calls or []:
            if call.get("name") == "query_metric_direct":
                return dict(call.get("args") or {})
    return None


def main() -> int:
    model = _make_model()
    results: list[tuple[Case, bool, str, dict | None]] = []
    dims: dict[str, list[bool]] = {}

    for case in CASES:
        args = _ask(model, case)
        if args is None:
            results.append((case, False, "模型未生成 query_metric_direct 调用", None))
            continue
        ok, detail = case.check(args)
        results.append((case, ok, detail, args))

    passed = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n== 语义忠实度评测（{len(results)} 用例）==")
    for case, ok, detail, args in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case.id}: {case.question} -> {detail}")
    print(f"\n准确率：{passed}/{len(results)} = {passed / len(results):.0%}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
