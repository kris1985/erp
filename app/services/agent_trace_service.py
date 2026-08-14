"""Privacy-safe, replay-oriented trace records for workshop-agent runs.

LangSmith remains the optional distributed-trace backend.  This small local
ledger keeps the governance identifiers needed to replay a decision even when
that integration is disabled.  It deliberately stores identifiers and verdicts
only: prompts, user questions, raw metric payloads and model output stay out.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings


def _conn() -> sqlite3.Connection:
    path = Path(get_settings().schedule_agent_data_dir) / "agent_traces.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_run_traces (
        run_id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL,
        conversation_id TEXT NOT NULL, created_at TEXT NOT NULL,
        trace_json TEXT NOT NULL)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_run_traces_scope ON agent_run_traces(tenant_id, conversation_id, created_at)")
    conn.commit()
    return conn


def record_run(
    *,
    run_id: str,
    tenant_id: int,
    conversation_id: str,
    semantic_plan_id: str,
    execution_plan_id: str | None,
    match_passed: bool | None,
    result_ids: list[str],
    calculation_ids: list[str],
    approval_ids: list[str],
    approval_statuses: list[str],
    versions: dict[str, str],
    outcome: str,
) -> dict[str, Any]:
    """Persist the minimum identifiers and governance verdicts for one run."""
    trace = {
        "run_id": run_id,
        "semantic_plan_id": semantic_plan_id,
        "execution_plan_id": execution_plan_id,
        "match": match_passed,
        "result_ids": sorted(set(result_ids)),
        "calculation_ids": sorted(set(calculation_ids)),
        "approval_ids": sorted(set(approval_ids)),
        "approval_statuses": sorted(set(approval_statuses)),
        "versions": dict(versions),
        "outcome": outcome,
    }
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO agent_run_traces(run_id, tenant_id, conversation_id, created_at, trace_json) VALUES(?,?,?,?,?)",
            (run_id, tenant_id, conversation_id, datetime.now().isoformat(timespec="seconds"), json.dumps(trace, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return trace


def get_run(tenant_id: int, run_id: str) -> dict[str, Any]:
    """Read a tenant-scoped trace record without exposing operational payloads."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT trace_json FROM agent_run_traces WHERE run_id=? AND tenant_id=?", (run_id, tenant_id)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError("agent_trace_not_found")
    return json.loads(row["trace_json"])
