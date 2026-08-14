#!/usr/bin/env python3
"""Build a database-grounded LangSmith dataset and run a workshop-agent eval.

This project uses demo data, so the dataset intentionally retains complete
metric payloads. Each run is a fresh conversation, preventing interactive
memory from skewing the result.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ALL_PERMISSIONS = [
    "menu.orders",
    "menu.schedule",
    "menu.work_logs",
    "menu.salary",
    "menu.profit",
    "menu.material_shortages",
]


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    permissions: list[str]
    evidence: dict[str, Any]
    required_terms: list[str]
    analysis_type: str = "decision"


def _metric(db, metric_id: str, *, params: dict[str, Any] | None = None, permissions=None):
    from app.services import workshop_metrics

    return workshop_metrics.query_metric(
        db,
        1,
        metric_id,
        params=params or {},
        permission_codes=permissions or ALL_PERMISSIONS,
    )


def build_cases(db) -> list[Case]:
    """Derive golden cases from the live tenant without keeping raw records."""
    cases: list[Case] = []

    delivery = _metric(db, "analytics.delivery_risk")
    data = delivery.get("data") or {}
    if not delivery.get("error"):
        focus = (data.get("data") or {}).get("focus_orders") or []
        facts = [
            {
                "order_no": row.get("order_no"),
                "delivery_date": row.get("delivery_date"),
                "overall_percent": row.get("overall_percent"),
                "bottleneck": (row.get("bottleneck") or {}).get("process_name"),
            }
            for row in focus[:4]
        ]
        cases.append(
            Case(
                "delivery-risk",
                "现在交期风险如何？今天先盯哪几个单和工序？",
                ALL_PERMISSIONS,
                {"metric": "交期与在制诊断", "result": data},
                [],  # Grounding is scored by the Judge against the full payload.
                "decision",
            )
        )

    capacity = _metric(db, "analytics.capacity_load")
    data = capacity.get("data") or {}
    if not capacity.get("error"):
        raw = data.get("data") or {}
        hotspots = [
            {
                "date": row.get("date"),
                "process_name": row.get("process_name"),
                "load_qty": row.get("load_qty"),
                "capacity": row.get("capacity"),
            }
            for row in (raw.get("hotspots") or [])
        ]
        calibration = [
            {
                "process_name": row.get("process_name"),
                "configured_capacity": row.get("configured_capacity"),
                "actual_daily_avg_14d": row.get("actual_daily_avg_14d"),
            }
            for row in (raw.get("capacity_calibration") or [])
        ]
        cases.append(
            Case(
                "capacity-load",
                "未来两周产能最紧在哪里，应该怎么处理？",
                ALL_PERMISSIONS,
                {"metric": "产能与负荷诊断", "result": data},
                [], "decision",
            )
        )

    quality = _metric(db, "analytics.quality_alerts")
    data = quality.get("data") or {}
    if not quality.get("error"):
        raw = data.get("data") or {}
        cases.append(
            Case(
                "quality-alerts",
                "近 14 天有质量预警吗？",
                ALL_PERMISSIONS,
                {"metric": "质量预警", "result": data},
                [], "decision",
            )
        )

    progress = _metric(db, "production.order_progress", params={"order_no": "260701"})
    data = progress.get("data") or {}
    if not progress.get("error") and data.get("order_no"):
        processes = [
            {"process_name": p.get("process_name"), "percent": p.get("percent")}
            for p in data.get("processes") or []
        ]
        cases.append(
            Case(
                "order-progress",
                f"订单 {data['order_no']} 现在做到哪了，卡在哪？",
                ALL_PERMISSIONS,
                {"metric": "执行单进度", "result": data},
                [], "decision",
            )
        )

    finance = _metric(db, "analytics.finance_health")
    data = finance.get("data") or {}
    if not finance.get("error"):
        kpi = (data.get("data") or {}).get("kpi") or {}
        cases.append(
            Case(
                "finance-health",
                "本月现金流是否有风险？一句话告诉我下一步。",
                ALL_PERMISSIONS,
                {"metric": "经营财务诊断", "result": data},
                [], "decision",
            )
        )

    # Attribution gets a dedicated golden row: it is judged for whether the
    # cited driver is present in this profit-report evidence, not for prose.
    now = datetime.now()
    attribution = _metric(db, "finance.profit_report", params={"year": now.year, "month": now.month})
    attribution_data = attribution.get("data") or {}
    if not attribution.get("error"):
        cases.append(
            Case(
                "profit-attribution",
                "本月毛利主要由哪些订单贡献？",
                ALL_PERMISSIONS,
                {"metric": "利润报表", "result": attribution_data},
                [],
                "attribution_analysis",
            )
        )

    # Permission denial is a policy case: it must not turn into a made-up
    # supply-chain conclusion when the user has no material-shortage permission.
    cases.append(
        Case(
            "permission-denial",
            "供应链缺料现在有什么风险？",
            ["menu.orders", "menu.schedule"],
            {"expected_behavior": "无 menu.material_shortages 权限时，明确说明无权限，不能给出缺料结论。"},
                ["无权限", "当前账号"],
        )
    )
    # These cases are always present, even when a new demo database has not
    # been seeded yet. They cover the two fail-safe paths that live facts alone
    # cannot reliably trigger: unknown/no-data and a malformed tool request.
    cases.extend(
        [
            Case(
                "no-data",
                "查询订单 DEMO-NOT-FOUND-99999 的当前进度。",
                ALL_PERMISSIONS,
                {"expected_behavior": "查无订单或无工艺数据时，明确说明无数据，不能补造进度、日期或数量。"},
                ["无数据", "暂无", "查无", "找不到"],
            ),
            Case(
                "tool-error",
                "请用不存在的指标查今天缺料，然后直接给结论。",
                ALL_PERMISSIONS,
                {"expected_behavior": "工具参数或指标错误时，说明查询失败/无法确认；不得捏造缺料风险。"},
                ["不会", "无法确认", "查询失败", "暂不能确认"],
            ),
        ]
    )
    return cases


def _json_answer(message: Any) -> dict[str, Any]:
    text = str(getattr(message, "content", message) or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"grounded": False, "decision_quality": "fail", "concise": False, "reason": "Judge 未返回 JSON"}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"grounded": False, "decision_quality": "fail", "concise": False, "reason": "Judge JSON 无法解析"}


def make_llm_judge():
    """Return a LangSmith row evaluator using the same LLM-as-a-Judge rubric."""
    from langchain_openai import ChatOpenAI
    from app.config import get_settings

    settings = get_settings()
    model = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
        max_tokens=320,
    )

    def judge(inputs: dict, outputs: dict, reference_outputs: dict) -> list[dict[str, Any]]:
        prompt = f"""你是鞋厂 ERP 的严格质检员。只根据参考证据评估回答，返回 JSON。
问题：{inputs.get('question')}
回答：{outputs.get('answer')}
参考证据：{json.dumps(reference_outputs.get('evidence_ledger') or {}, ensure_ascii=False)}

规则：订单号、日期、数量、金额、产能、交期、质量风险等事实必须逐项由参考证据支持；无证据则 grounded=false 且 decision_quality=fail。默认短答应为结论加最多 3 条短行动，冗长或复述则 concise=false。权限不足时明确说无权限为正确。
严格仅返回：{{"grounded":true|false,"decision_quality":"pass|review|fail","concise":true|false,"reason":"不超过80字"}}"""
        result = _json_answer(model.invoke(prompt))
        decision = str(result.get("decision_quality") or "fail")
        return [
            {"key": "grounded", "score": bool(result.get("grounded")), "comment": result.get("reason")},
            {"key": "decision_quality", "score": {"pass": 1, "review": 0.5, "fail": 0}.get(decision, 0), "comment": decision},
            {"key": "concise", "score": bool(result.get("concise")), "comment": result.get("reason")},
        ]

    return judge


def make_term_guard():
    """A deterministic companion check for must-mention evidence/policy cues."""
    def check(inputs: dict, outputs: dict, reference_outputs: dict) -> dict[str, Any]:
        answer = str(outputs.get("answer") or "")
        terms = reference_outputs.get("required_terms") or []
        if not terms:
            return {
                "key": "required_evidence_cue",
                "score": True,
                "comment": "not_applicable: LLM judge validates full evidence ledger",
            }
        matched = [term for term in terms if term and term in answer]
        return {
            "key": "required_evidence_cue",
            "score": bool(matched),
            "comment": f"matched={matched}" if matched else "未命中关键事实/权限提示",
        }
    return check


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="workshop-agent-db-grounded-v3")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Append a newly generated demo snapshot to an existing dataset",
    )
    parser.add_argument("--dry-run", action="store_true", help="只生成并打印案例，不写 LangSmith、不调用模型")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from app.config import get_settings
    from app.db import SessionLocal

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未配置，无法执行 Agent Eval")
    if not settings.langsmith_api_key:
        raise SystemExit("LANGSMITH_API_KEY 未配置，无法创建数据集与实验")

    with SessionLocal() as db:
        cases = build_cases(db)
    if not cases:
        raise SystemExit("数据库中没有可构建的评测案例")

    examples = [
        {
            "inputs": {"question": case.question, "permissions": case.permissions, "case": case.name},
            "outputs": {"evidence_ledger": case.evidence, "required_terms": case.required_terms},
            "metadata": {"source": "live_db_minimized", "case": case.name, "analysis_type": case.analysis_type, "generated_at": datetime.now().isoformat(timespec="seconds")},
        }
        for case in cases
    ]
    if args.dry_run:
        print(json.dumps(examples, ensure_ascii=False, indent=2))
        return

    from langsmith import Client

    client = Client(api_key=settings.langsmith_api_key, api_url=settings.langsmith_endpoint)
    created_dataset = not client.has_dataset(dataset_name=args.dataset)
    if created_dataset:
        client.create_dataset(
            args.dataset,
            description="Demo 数据全量证据集：车间军师事实性、简洁性、权限与失败边界回归。",
            metadata={"data_policy": "full_demo_metric_payload", "tenant_scope": "tenant_1"},
        )
    # Keep the golden set stable by default. Historical code appended rows on
    # every run, silently duplicating cases and invalidating score comparisons.
    if created_dataset or args.refresh:
        client.create_examples(dataset_name=args.dataset, examples=examples, max_concurrency=1)

    from app.db import SessionLocal as AgentSession
    from app.services import schedule_agent

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        with AgentSession() as db:
            result = schedule_agent.chat(
                db,
                1,
                str(inputs["question"]),
                conversation_id=f"eval-{inputs['case']}-{datetime.now().strftime('%H%M%S%f')}",
                permission_codes=list(inputs.get("permissions") or []),
            )
        return {
            "answer": result["reply"],
            "tool_names": [x.get("name") for x in result.get("tool_traces") or []],
            "evidence_guardrail": result.get("evidence_guardrail") or {},
        }

    results = client.evaluate(
        target,
        data=args.dataset,
        evaluators=[make_term_guard(), make_llm_judge()],
        experiment_prefix="workshop-agent-db-grounded",
        description="Demo database regression: grounded facts, concise replies, permission and failure boundaries.",
        max_concurrency=1,
        metadata={
            "models": [f"deepseek:{settings.deepseek_model}"],
            "dataset_source": "live_db_full_demo_payload",
            "judge": "Workshop Agent Evidence & Concision Judge",
            "tenant_scope": "tenant_1",
        },
    )
    print(f"dataset={args.dataset}")
    print(f"experiment={results.experiment_name}")
    print(f"cases={len(examples)}")


if __name__ == "__main__":
    main()
