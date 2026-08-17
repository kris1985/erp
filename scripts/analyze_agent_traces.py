#!/usr/bin/env python3
"""路由 trace 消费端：从 agent_traces.sqlite 聚合路由质量，失败样本回流 golden 的最后一公里。

聚合维度：
- 层分布（rules / similarity / follow_up_* / direct / none）
- 拦截（guardrail 拦截 / 路由未命中）
- 低置信（similarity 命中但置信度低于阈值）
- 失败样本明细（run_id / conversation_id / outcome / routing），--json 导出供补 golden

用法：
    python scripts/analyze_agent_traces.py                # 聚合统计
    python scripts/analyze_agent_traces.py --json         # 输出失败样本 JSON
    python scripts/analyze_agent_traces.py --limit 50     # 样本上限
    python scripts/analyze_agent_traces.py --data-dir DIR # 指定数据目录
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# 允许直接 `python scripts/analyze_agent_traces.py` 运行（repo 根进 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

# outcome 中含这些词视为被拦截（guardrail 拒绝/删行/回退）
INTERCEPT_MARKERS = (
    "unsupported_measurable_claim", "missing_tool_evidence", "rejected",
    "removed_unsupported_lines", "fallback", "fail_closed", "error",
)
# similarity 命中但置信低于此值视为低置信（弱命中，可能误路由）
LOW_CONFIDENCE_THRESHOLD = 0.20


def read_traces(data_dir: str) -> list[dict[str, Any]]:
    path = Path(data_dir) / "agent_traces.sqlite"
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT run_id, tenant_id, conversation_id, created_at, trace_json "
            "FROM agent_run_traces ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    traces: list[dict[str, Any]] = []
    for row in rows:
        try:
            trace = json.loads(row["trace_json"])
        except (TypeError, ValueError):
            continue
        trace["_run_id"] = row["run_id"]
        trace["_tenant_id"] = row["tenant_id"]
        trace["_conversation_id"] = row["conversation_id"]
        trace["_created_at"] = row["created_at"]
        traces.append(trace)
    return traces


def aggregate_trace_stats(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合：层分布 / 拦截 / 低置信 / 失败样本（纯函数，可测）。"""
    stats: dict[str, Any] = {
        "total": len(traces),
        "layer_dist": {},
        "intercepted": 0,
        "low_confidence": 0,
        "unrouted": 0,
        "samples": [],
    }
    for trace in traces:
        routing = trace.get("routing") if isinstance(trace.get("routing"), dict) else {}
        layer = str(routing.get("layer") or "none")
        stats["layer_dist"][layer] = stats["layer_dist"].get(layer, 0) + 1
        confidence = float(routing.get("confidence") or 0)
        outcome = str(trace.get("outcome") or "")
        intercepted = any(marker in outcome for marker in INTERCEPT_MARKERS) or layer == "none"
        low_confidence = layer == "similarity" and 0 < confidence < LOW_CONFIDENCE_THRESHOLD
        if layer == "none":
            stats["unrouted"] += 1
        if intercepted:
            stats["intercepted"] += 1
        if low_confidence:
            stats["low_confidence"] += 1
        if intercepted or low_confidence:
            stats["samples"].append({
                "run_id": trace.get("_run_id"),
                "tenant_id": trace.get("_tenant_id"),
                "conversation_id": trace.get("_conversation_id"),
                "created_at": trace.get("_created_at"),
                "outcome": outcome,
                "routing": routing,
            })
    return stats


def render_stats(stats: dict[str, Any]) -> str:
    lines = [
        f"trace 总数: {stats['total']}",
        "",
        "路由层分布:",
    ]
    for layer, count in sorted(stats["layer_dist"].items(), key=lambda kv: -kv[1]):
        pct = f"({count / stats['total'] * 100:.1f}%)" if stats["total"] else ""
        lines.append(f"  {layer:<24} {count:>5} {pct}")
    lines += [
        "",
        f"拦截: {stats['intercepted']}  |  低置信: {stats['low_confidence']}  |  未路由: {stats['unrouted']}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="聚合路由 trace 质量（失败样本回流 golden 的最后一公里）")
    parser.add_argument("--data-dir", default=None, help="schedule_agent 数据目录（默认取配置）")
    parser.add_argument("--limit", type=int, default=20, help="失败样本展示上限")
    parser.add_argument("--json", action="store_true", help="输出失败样本 JSON（供补 golden）")
    args = parser.parse_args()

    data_dir = args.data_dir or str(get_settings().schedule_agent_data_dir)
    traces = read_traces(data_dir)
    if not traces:
        print(f"无 trace（{data_dir}/agent_traces.sqlite 不存在或为空）")
        return
    stats = aggregate_trace_stats(traces)
    print(render_stats(stats))

    samples = stats["samples"][: args.limit]
    if args.json:
        print(json.dumps({"total": len(stats["samples"]), "samples": samples}, ensure_ascii=False, indent=2))
    else:
        print(f"\n失败样本（前 {len(samples)}/{len(stats['samples'])}）:")
        for sample in samples:
            print(f"  [{sample['created_at']}] {sample['conversation_id']} "
                  f"outcome={sample['outcome']} layer={sample['routing'].get('layer')} "
                  f"reason={sample['routing'].get('reason')}")
        if samples:
            print("\n提示: --json 导出完整样本，用于补 golden 语料（tests/test_intent_router.py 的 golden 集）")


if __name__ == "__main__":
    main()
