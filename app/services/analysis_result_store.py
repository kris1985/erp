"""Tenant- and session-scoped evidence results for typed agent presentations."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings


CalculationOperation = Literal[
    "sum", "subtract", "divide", "ratio", "average", "min", "max",
    "rank", "yoy", "mom", "moving_average", "share",
]

# Increment whenever the restricted operation semantics or lineage contract
# changes.  Agent traces retain this alongside policy and prompt versions.
CALCULATION_ENGINE_VERSION = "1.0.0"

_RESULT_FIELD_REF_RE = re.compile(
    r"r_[0-9a-f]{16}\.(?:[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)*$"
)
_CALCULATION_VALUE_REF_RE = re.compile(r"c_[0-9a-f]{16}\.value$")


def _now() -> datetime:
    return datetime.now()


def _settings_value(name: str, default: int) -> int:
    return int(getattr(get_settings(), name, default))


def _conn() -> sqlite3.Connection:
    path = Path(get_settings().schedule_agent_data_dir) / "analysis_results.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS analysis_results (
        id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL, session_id TEXT,
        metric_id TEXT NOT NULL, filters_json TEXT NOT NULL, payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS analysis_calculations (
        id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL, session_id TEXT,
        operation TEXT NOT NULL, inputs_json TEXT NOT NULL, value REAL NOT NULL,
        precision INTEGER NOT NULL DEFAULT 2, created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL)"""
    )
    # Existing developer databases predate the lifecycle columns. SQLite has
    # no portable ADD COLUMN IF NOT EXISTS, so make this migration idempotent.
    for table, columns in {
        "analysis_results": {
            "session_id": "TEXT", "expires_at": "TEXT",
        },
        "analysis_calculations": {
            "session_id": "TEXT", "precision": "INTEGER NOT NULL DEFAULT 2", "expires_at": "TEXT",
        },
    }.items():
        known = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in known:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    # Backfill is intentionally finite: legacy records expire from this point
    # instead of becoming permanent evidence.
    fallback_expiry = (_now() + timedelta(seconds=_settings_value("analysis_result_ttl_seconds", 3600))).isoformat(timespec="seconds")
    conn.execute("UPDATE analysis_results SET expires_at=? WHERE expires_at IS NULL", (fallback_expiry,))
    conn.execute("UPDATE analysis_calculations SET expires_at=? WHERE expires_at IS NULL", (fallback_expiry,))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_results_scope ON analysis_results(tenant_id, session_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_calculations_scope ON analysis_calculations(tenant_id, session_id, created_at)")
    conn.commit()
    return conn


def _cleanup(conn: sqlite3.Connection, *, tenant_id: int, session_id: str | None) -> None:
    now = _now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM analysis_results WHERE expires_at <= ?", (now,))
    conn.execute("DELETE FROM analysis_calculations WHERE expires_at <= ?", (now,))
    maximum = max(1, _settings_value("analysis_result_max_per_session", 200))
    scope = "tenant_id=? AND session_id IS ?"
    params = (tenant_id, session_id)
    for table in ("analysis_results", "analysis_calculations"):
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE {scope} ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
            (*params, maximum),
        ).fetchall()
        if rows:
            conn.executemany(f"DELETE FROM {table} WHERE id=?", [(row["id"],) for row in rows])


def put_result(
    tenant_id: int, metric_id: str, payload: dict[str, Any], filters: dict[str, Any], *,
    session_id: str | None = None, ttl_seconds: int | None = None,
) -> str:
    result_id = f"r_{uuid.uuid4().hex[:16]}"
    created = _now()
    ttl = max(1, ttl_seconds if ttl_seconds is not None else _settings_value("analysis_result_ttl_seconds", 3600))
    conn = _conn()
    try:
        _cleanup(conn, tenant_id=tenant_id, session_id=session_id)
        conn.execute(
            """INSERT INTO analysis_results
            (id, tenant_id, session_id, metric_id, filters_json, payload_json, created_at, expires_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (result_id, tenant_id, session_id, metric_id, json.dumps(filters, ensure_ascii=False, default=str),
             json.dumps(payload, ensure_ascii=False, default=str), created.isoformat(timespec="seconds"),
             (created + timedelta(seconds=ttl)).isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()
    return result_id


def _get_result(tenant_id: int, result_id: str, *, session_id: str | None = None) -> dict[str, Any]:
    conn = _conn()
    try:
        _cleanup(conn, tenant_id=tenant_id, session_id=session_id)
        query, params = "SELECT * FROM analysis_results WHERE id=? AND tenant_id=?", [result_id, tenant_id]
        if session_id is not None:
            query += " AND session_id=?"
            params.append(session_id)
        row = conn.execute(query, params).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise ValueError("unknown_result_ref")
    return {"metric_id": row["metric_id"], "filters": json.loads(row["filters_json"]), "payload": json.loads(row["payload_json"]), "session_id": row["session_id"]}


def _get_calculation(tenant_id: int, calculation_id: str, *, session_id: str | None = None) -> dict[str, Any]:
    conn = _conn()
    try:
        _cleanup(conn, tenant_id=tenant_id, session_id=session_id)
        query, params = "SELECT * FROM analysis_calculations WHERE id=? AND tenant_id=?", [calculation_id, tenant_id]
        if session_id is not None:
            query += " AND session_id=?"
            params.append(session_id)
        row = conn.execute(query, params).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise ValueError("unknown_result_ref")
    return {"operation": row["operation"], "inputs": json.loads(row["inputs_json"]), "value": row["value"], "precision": row["precision"], "created_at": row["created_at"], "session_id": row["session_id"]}


def _read_payload_path(payload: Any, path: str) -> Any:
    value = payload
    for part in path.split("."):
        matched = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?", part)
        if not matched or not isinstance(value, dict) or matched.group(1) not in value:
            raise ValueError("unknown_result_field")
        value = value[matched.group(1)]
        if matched.group(2) is not None:
            index = int(matched.group(2))
            if not isinstance(value, list) or index >= len(value):
                raise ValueError("unknown_result_field")
            value = value[index]
    return value


def read_ref(tenant_id: int, ref: str, *, session_id: str | None = None) -> tuple[Any, dict[str, Any]]:
    """Read a constrained dotted field reference, including array indexes."""
    result_id, sep, path = (ref or "").partition(".")
    if not sep or not path:
        raise ValueError("invalid_result_ref")
    if result_id.startswith("c_"):
        if path != "value":
            raise ValueError("unknown_result_field")
        calculation = _get_calculation(tenant_id, result_id, session_id=session_id)
        return calculation["value"], {"ref": ref, "calculation_id": result_id, "operation": calculation["operation"], "inputs": calculation["inputs"]}
    if not result_id.startswith("r_"):
        raise ValueError("invalid_result_ref")
    record = _get_result(tenant_id, result_id, session_id=session_id)
    return _read_payload_path(record["payload"], path), {"ref": ref, "metric_id": record["metric_id"], "filters": record["filters"]}


def _schema(value: Any, path: str = "") -> list[dict[str, str]]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in _schema(child, f"{path}.{key}".strip("."))]
    if isinstance(value, list):
        return _schema(value[0], f"{path}[]") if value else [{"field": path, "type": "array"}]
    return [{"field": path, "type": type(value).__name__}]


def inspect_result(tenant_id: int, result_id: str, fields: list[str] | None = None, limit: int = 20, *, session_id: str | None = None) -> dict[str, Any]:
    """Return schema plus an explicitly requested, bounded subset of a result."""
    if not isinstance(fields or [], list) or len(fields or []) > 20 or not 1 <= int(limit) <= 100:
        raise ValueError("invalid_result_inspection")
    record = _get_result(tenant_id, result_id, session_id=session_id)
    selected: dict[str, Any] = {}
    for field in fields or []:
        if not isinstance(field, str):
            raise ValueError("invalid_result_inspection")
        value = _read_payload_path(record["payload"], field)
        selected[field] = value[:int(limit)] if isinstance(value, list) else value
    return {"metric_id": record["metric_id"], "filters": record["filters"], "schema": _schema(record["payload"]), "fields": selected}


def resolve_ref(tenant_id: int, ref: str, *, session_id: str | None = None) -> tuple[Any, dict[str, Any]]:
    if not isinstance(ref, str) or not (
        _RESULT_FIELD_REF_RE.fullmatch(ref) or _CALCULATION_VALUE_REF_RE.fullmatch(ref)
    ):
        # This gate is deliberately before any read: a model cannot smuggle a
        # literal amount, date, percentage, expression, or arbitrary field
        # through the calculation engine.
        raise ValueError("invalid_calculation_input_ref")
    value, lineage = read_ref(tenant_id, ref, session_id=session_id)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("non_numeric_result_field")
    return value, lineage


def _compute(operation: CalculationOperation, nums: list[float]) -> float:
    if operation == "sum": return sum(nums)
    if operation == "subtract" and len(nums) == 2: return nums[0] - nums[1]
    if operation == "divide" and len(nums) == 2 and nums[1] != 0: return nums[0] / nums[1]
    if operation == "ratio" and len(nums) == 2 and nums[1] != 0: return nums[0] / nums[1] * 100
    if operation in {"yoy", "mom"} and len(nums) == 2 and nums[1] != 0: return (nums[0] - nums[1]) / abs(nums[1]) * 100
    if operation == "share" and len(nums) == 2 and nums[1] != 0: return nums[0] / nums[1] * 100
    if operation in {"average", "moving_average"}: return sum(nums) / len(nums)
    if operation == "rank": return float(1 + sum(value > nums[0] for value in nums[1:]))
    if operation == "min": return min(nums)
    if operation == "max": return max(nums)
    raise ValueError("invalid_calculation_operation")


def calculate(tenant_id: int, operation: CalculationOperation, inputs: list[str], *, precision: int = 2, session_id: str | None = None) -> dict[str, Any]:
    if not isinstance(inputs, list) or not inputs or len(inputs) > 100:
        raise ValueError("invalid_calculation_inputs")
    values, lineage = zip(*(resolve_ref(tenant_id, ref, session_id=session_id) for ref in inputs))
    bounded_precision = max(0, min(6, int(precision)))
    rounded = round(_compute(operation, [float(value) for value in values]), bounded_precision)
    calculation_id, created = f"c_{uuid.uuid4().hex[:16]}", _now()
    ttl = _settings_value("analysis_result_ttl_seconds", 3600)
    conn = _conn()
    try:
        _cleanup(conn, tenant_id=tenant_id, session_id=session_id)
        conn.execute("""INSERT INTO analysis_calculations
            (id, tenant_id, session_id, operation, inputs_json, value, precision, created_at, expires_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (
            calculation_id, tenant_id, session_id, operation, json.dumps(list(lineage), ensure_ascii=False), rounded,
            bounded_precision, created.isoformat(timespec="seconds"), (created + timedelta(seconds=ttl)).isoformat(timespec="seconds"),
        ))
        conn.commit()
    finally:
        conn.close()
    return {"calculation_id": calculation_id, "value": rounded, "operation": operation, "formula": operation, "inputs": list(lineage), "precision": bounded_precision, "executed_at": created.isoformat(timespec="seconds")}


def replay_calculation(tenant_id: int, calculation_id: str, *, session_id: str | None = None) -> dict[str, Any]:
    """Re-run a persisted formula against its recorded field lineage."""
    calculation = _get_calculation(tenant_id, calculation_id, session_id=session_id)
    refs = [item["ref"] for item in calculation["inputs"]]
    replay = calculate(tenant_id, calculation["operation"], refs, precision=calculation["precision"], session_id=session_id)
    return {"source_calculation_id": calculation_id, "replayed_calculation_id": replay["calculation_id"], "value": replay["value"], "matches": replay["value"] == calculation["value"], "formula": calculation["operation"], "inputs": calculation["inputs"], "precision": calculation["precision"], "executed_at": calculation["created_at"]}
