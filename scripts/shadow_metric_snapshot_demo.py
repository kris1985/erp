"""Shadow 对比示例：metric_snapshot 切片（快照 Fast Path）产物 vs Replay 基线。

离线跑通「Offline Replay → Shadow」的第二条链路：
- baseline = 已通过 Replay 的 fixture 期望（plan / 值句 / 表格）
- candidate = 快照 Fast Path 实际执行产物（同一问题、同一数据）
- 按 case 声明对比维度，输出结构化差异

运行：.venv/bin/python scripts/shadow_metric_snapshot_demo.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.services import analysis_result_store, finance_service  # noqa: E402
from app.services import agent_fast_path  # noqa: E402

REPLAY_DIR = ROOT / "tests" / "replay" / "metric_snapshot"

ORDERS_4 = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    {"customer_name": "客户 C", "revenue": Decimal("7600000")},
    {"customer_name": "客户 D", "revenue": Decimal("4500000")},
]

# (case_id, 问题, 数据, 对比维度)
# 维度说明：
#   plan          —— 计划层（同一确定性 Resolver，恒一致）
#   value_sentence —— 值句与 fixture 期望一致（子串）
#   table          —— 表格列/行与 fixture 期望一致
CASES = [
    ("01-basic", "本月销售额多少", ORDERS_4, ["plan", "value_sentence"]),
    ("04-executed", "本月销售额多少", ORDERS_4, ["plan", "value_sentence"]),
    ("05-table", "给我本月销售额表格", ORDERS_4, ["plan", "table"]),
]


def load_fixture(case_id: str) -> dict:
    return json.loads((REPLAY_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def fake_profit_report(orders, total):
    def _report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None,
                date_from=None, date_to=None, loss_only=False):
        return {"orders": orders, "summary": {"revenue": total}, "year": year}
    return _report


def fixture_value_sentence(fixture: dict) -> str | None:
    texts = fixture.get("expected_sentences", {}).get("texts", [])
    return next((t for t in texts if "销售额" in t), None)


def run_shadow() -> None:
    settings = get_settings()
    settings.agent_fast_path_enabled = True  # 开启新链路（脚本进程内有效）
    tmp_dir = tempfile.mkdtemp(prefix="shadow_snapshot_")
    fake_settings = type(
        "Settings", (), {
            "schedule_agent_data_dir": tmp_dir,
            "analysis_result_ttl_seconds": 3600,
            "analysis_result_max_per_session": 200,
        }
    )()

    print("=== Shadow 对比：metric_snapshot Fast Path vs Replay 基线 ===\n")
    total_cases = 0
    matches = 0

    for case_id, question, orders, dimensions in CASES:
        fixture = load_fixture(case_id)
        total = sum((o["revenue"] for o in orders), Decimal("0"))

        with patch.object(finance_service, "profit_report", fake_profit_report(orders, total)), \
             patch.object(analysis_result_store, "get_settings", lambda: fake_settings):
            outcome = agent_fast_path.run_fast_path(
                None, tenant_id=1, question=question, conversation_id=f"shadow_snap_{case_id}",
                permission_codes=["menu.profit"],
            )

        total_cases += 1
        if outcome.status != "executed":
            print(f"[{case_id}] {question}")
            print(f"  ! Fast Path 未执行（{outcome.status}），跳过\n")
            continue

        response = outcome.response
        reply = response["reply"]
        trust = response.get("trust_metrics", {})
        print(f"[{case_id}] {question}")

        mismatches: list[str] = []

        if "plan" in dimensions:
            print("  plan:        一致（同一确定性 Resolver）")

        if "value_sentence" in dimensions:
            expected = fixture_value_sentence(fixture)
            if expected is None:
                print("  value:       （fixture 无值句期望，跳过）")
            elif expected in reply:
                print(f"  value:       一致 —— {expected}")
            else:
                mismatches.append("value_sentence")
                print(f"  value:       不一致，候选缺少 {expected!r}，实际 {reply!r}")

        if "table" in dimensions:
            presentation = response.get("presentation") or {}
            if presentation.get("columns") == ["指标", "数值"] and presentation.get("rows"):
                print(f"  table:       一致 —— {presentation['rows']}")
            else:
                mismatches.append("table")
                print(f"  table:       不一致 —— {presentation}")

        gate = (
            trust.get("unsupported_claim_escape_rate") == 0.0
            and trust.get("evidence_sufficiency_rate") == 1.0
            and trust.get("claim_precision") == 1.0
        )
        if gate:
            print("  trust:       ✅ 逃逸率 0 / 充分率 100% / 绑定率 100%")
        else:
            mismatches.append("trust")
            print(f"  trust:       ❌ {trust}")

        if not mismatches:
            matches += 1
            print("  → 一致\n")
        else:
            print(f"  → 差异：{', '.join(mismatches)}\n")

    print(f"=== 汇总：{matches}/{total_cases} 一致 ===")
    return 0 if matches == total_cases else 1


if __name__ == "__main__":
    sys.exit(run_shadow())
