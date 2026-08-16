"""Result Spill tests (PR #6, slice §P0.3).

Acceptance: large results never enter the model context in full — the model
sees result_id + schema + summary + preview + truncated; detail stays readable
by the same result_id; front-end/Trace can tell “truncated” from “empty”.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.runtime.contracts import (
    Coverage,
    EvidenceEnvelope,
    Freshness,
    MetricRef,
    TimeScope,
)
from app.runtime.spill import ResultSpiller, SPILL_DEFAULT_MAX_PREVIEW_ROWS

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
METRIC = MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0")
SCOPE = TimeScope(year=2026)


def make_envelope(rows: int = 8) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_big",
        metric=METRIC,
        scope=SCOPE,
        dimension="customer",
        operation="ranking",
        coverage=Coverage(
            type="top_n",
            requested=10,
            returned=rows,
            population_complete=True,
            population_size=rows,
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        payload={
            "result_type": "ranking",
            "rows": [
                {
                    "entity_id": f"customer:{i}",
                    "entity_label": f"客户 {i}",
                    "value": str(1000000 * (rows - i + 1)),
                    "unit": "CNY",
                    "rank": i,
                }
                for i in range(1, rows + 1)
            ],
            "execution_ref": "metric_exec_big",
        },
    )


def test_spill_previews_bounded_rows() -> None:
    spiller = ResultSpiller()
    spilled = spiller.spill(make_envelope(rows=8))
    assert spilled.result_id == "r_big"
    assert spilled.result_schema == "ranking"
    assert spilled.truncated is True  # 8 rows > default preview of 5
    assert spilled.preview.count("第") == SPILL_DEFAULT_MAX_PREVIEW_ROWS
    assert "共 8 行" in spilled.preview
    assert spilled.stored_bytes > 0


def test_small_result_not_truncated() -> None:
    spilled = ResultSpiller().spill(make_envelope(rows=3))
    assert spilled.truncated is False


def test_spill_render_is_model_facing_only() -> None:
    spilled = ResultSpiller().spill(make_envelope(rows=4))
    rendered = spilled.render()
    assert spilled.result_id in rendered
    # The model never sees raw rows/values in the spill text.
    assert "12350000" not in rendered


def test_detail_remains_addressable_by_result_id() -> None:
    spilled = ResultSpiller().spill(make_envelope(rows=4))
    assert spilled.result_id == "r_big"  # same id the store persists under
