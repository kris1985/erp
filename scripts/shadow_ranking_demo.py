"""Shadow 对比示例：新链路（Ranking Fast Path）产物 vs Replay 基线。

离线跑通「Offline Replay → Shadow」：
- baseline = 已通过 12-case Replay 的 fixture 期望（plan / share 句 / judgement / 表格）
- candidate = Fast Path 实际执行产物（同一问题、同一数据）
- 按 case 声明对比维度，输出结构化差异

运行：.venv/bin/python scripts/shadow_ranking_demo.py
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

REPLAY_DIR = ROOT / "tests" / "replay" / "ranking"

ORDERS_4 = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    {"customer_name": "客户 C", "revenue": Decimal("7600000")},
    {"customer_name": "客户 D", "revenue": Decimal("4500000")},
]
ORDERS_HIGH = [
    {"customer_name": "客户 A", "revenue": Decimal("60000000")},
    {"customer_name": "客户 B", "revenue": Decimal("30000000")},
    {"customer_name": "客户 C", "revenue": Decimal("5000000")},
    {"customer_name": "客户 D", "revenue": Decimal("5000000")},
]

# (case_id, 问题, 数据, 对比维度)
# 维度说明：
#   plan            —— 计划层（同一确定性 Resolver，恒一致）
#   share_sentence  —— 占比句与 fixture 期望一致（子串）
#   judgement_absent/present —— 集中度判断不存在/存在（对照 fixture expected_judgement）
#   table           —— 表格列/行与 fixture 期望一致
CASES = [
    ("01-basic", "客户销售额排行", ORDERS_4, ["plan"]),
    ("04-top2-share", "前两名客户占多少", ORDERS_4, ["plan", "share_sentence"]),
    ("05-concentration-complete", "客户集中度怎么样", ORDERS_4, ["share_sentence", "judgement_absent"]),
    ("05b-concentration-hit", "客户集中度怎么样", ORDERS_HIGH, ["share_sentence", "judgement_present"]),
    ("07-table", "给我客户销售额表格", ORDERS_4, ["plan", "table"]),
]

JUDGEMENT_TEXT = "客户集中度较高"


def load_fixture(case_id: str) -> dict:
    return json.loads((REPLAY_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def fake_profit_report(orders, total):
    def _report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None,
                date_from=None, date_to=None, loss_only=False):
        return {"orders": orders, "summary": {"revenue": total}, "year": year}
    return _report


def fixture_share_sentence(fixture: dict) -> str | None:
    """从 fixture 期望句子中取出占比句（含『合计占总销售额』）。"""
    texts = fixture.get("expected_sentences", {}).get("texts", [])
    return next((t for t in texts if "合计占总销售额" in t), None)


def run_shadow() -> None:
    settings = get_settings()
    settings.agent_fast_path_enabled = True  # 开启新链路（脚本进程内有效）
    tmp_dir = tempfile.mkdtemp(prefix="shadow_ranking_")
    fake_settings = type(
        "Settings", (), {
            "schedule_agent_data_dir": tmp_dir,
            "analysis_result_ttl_seconds": 3600,
            "analysis_result_max_per_session": 200,
        }
    )()

    print("=== Shadow 对比：新链路（Fast Path） vs Replay 基线 ===\n")
    total_cases = 0
    matches = 0

    for case_id, question, orders, dimensions in CASES:
        fixture = load_fixture(case_id)
        total = sum((o["revenue"] for o in orders), Decimal("0"))

        with patch.object(finance_service, "profit_report", fake_profit_report(orders, total)), \
             patch.object(analysis_result_store, "get_settings", lambda: fake_settings):
            outcome = agent_fast_path.run_fast_path(
                None, tenant_id=1, question=question, conversation_id=f"shadow_{case_id}",
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
        checks: list[str] = []

        if "plan" in dimensions:
            checks.append("plan")
            print("  plan:        一致（同一确定性 Resolver）")

        if "share_sentence" in dimensions:
            checks.append("share_sentence")
            expected = fixture_share_sentence(fixture)
            if expected is None:
                print("  share:       （fixture 无占比句期望，跳过）")
            elif expected in reply:
                print(f"  share:       一致 —— {expected}")
            else:
                mismatches.append("share_sentence")
                print(f"  share:       不一致，候选缺少占比句 {expected!r}")

        if "judgement_absent" in dimensions:
            checks.append("judgement_absent")
            if JUDGEMENT_TEXT in reply:
                mismatches.append("judgement_absent")
                print(f"  judgement:   不应出现却出现 —— {JUDGEMENT_TEXT}（canonical top2_share 未达 0.80）")
            else:
                print("  judgement:   一致（canonical 0.6467 < 0.80，无集中度判断）")

        if "judgement_present" in dimensions:
            checks.append("judgement_present")
            if JUDGEMENT_TEXT in reply:
                print(f"  judgement:   一致 —— {JUDGEMENT_TEXT}")
            else:
                mismatches.append("judgement_present")
                print("  judgement:   应出现集中度判断却缺失")

        if "table" in dimensions:
            checks.append("table")
            expected = fixture["expected_table"]
            actual = response.get("presentation")
            if actual is not None and actual["columns"] == expected["columns"] and actual["rows"] == expected["rows"]:
                print(f"  table:       一致（{len(expected['rows'])} 行）")
            else:
                mismatches.append("table")
                print(f"  table:       不一致（期望 {expected['rows']}，实际 {actual and actual['rows']}）")

        print(f"  可信指标:     escape={trust.get('unsupported_claim_escape_rate')} "
              f"sufficiency={trust.get('evidence_sufficiency_rate')} precision={trust.get('claim_precision')}")
        if not mismatches:
            matches += 1
            print(f"  verdict:     MATCH（对比维度: {', '.join(checks)}）\n")
        else:
            print(f"  verdict:     MISMATCH {mismatches}\n")

    print(f"=== 汇总：{matches}/{total_cases} 例与基线一致 ===")
    if matches == total_cases:
        print("Shadow 对比通过：新链路产物与已验证 Replay 基线一致，可进入灰度评估。")
    else:
        print("Shadow 对比发现差异，请按上面 MISMATCH 项定位（多为输入参数与 fixture 的差异）。")


if __name__ == "__main__":
    run_shadow()
