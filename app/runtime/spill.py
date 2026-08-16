"""Result Spill for the ranking slice (PR #6, slice §P0.3).

Large tool results never enter the model context in full.  A spill keeps the
complete payload in the Result Store (existing ``analysis_result_store.py``
owns persistence and permissioned reads) and hands the model only
``result_id + schema + summary + preview + truncated``.  Detail stays readable
on demand through the same ``result_id``.
"""

from __future__ import annotations

import json
from typing import Literal

from app.runtime.contracts import EvidenceEnvelope, RuntimeModel, SCHEMA_VERSION, dump_contract

SPILL_DEFAULT_MAX_INLINE_BYTES = 4096
SPILL_DEFAULT_MAX_PREVIEW_ROWS = 5


class SpilledResult(RuntimeModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    result_id: str
    result_schema: str
    summary: str
    preview: str
    truncated: bool
    stored_bytes: int

    def render(self) -> str:
        return (
            f"结果 {self.result_id}（{self.result_schema}，{self.stored_bytes} 字节"
            + ("，已裁剪" if self.truncated else "")
            + f"）：{self.summary}。预览：{self.preview}"
        )


class ResultSpiller:
    """Deterministic spill: the model sees a bounded summary of a result."""

    def __init__(
        self,
        max_inline_bytes: int = SPILL_DEFAULT_MAX_INLINE_BYTES,
        max_preview_rows: int = SPILL_DEFAULT_MAX_PREVIEW_ROWS,
    ) -> None:
        self._max_inline_bytes = max_inline_bytes
        self._max_preview_rows = max_preview_rows

    def spill(self, envelope: EvidenceEnvelope) -> SpilledResult:
        full = dump_contract(envelope)
        stored_bytes = len(json.dumps(full, ensure_ascii=False, separators=(",", ":")))
        rows = envelope.payload.rows
        preview_rows = rows[: self._max_preview_rows]
        preview = "；".join(
            f"{row.entity_label}（第 {row.rank} 名）" for row in preview_rows
        )
        if len(rows) > len(preview_rows):
            preview += f"；…共 {len(rows)} 行"
        truncated = stored_bytes > self._max_inline_bytes or len(rows) > self._max_preview_rows
        summary = (
            f"{len(rows)} 行排名，{envelope.metric.metric_id} "
            f"@{envelope.metric.definition_version}，"
            f"{envelope.scope.year or ''}{'年' if envelope.scope.year else ''}"
        ).strip()
        return SpilledResult(
            result_id=envelope.result_id,
            result_schema="ranking",
            summary=summary,
            preview=preview,
            truncated=truncated,
            stored_bytes=stored_bytes,
        )
