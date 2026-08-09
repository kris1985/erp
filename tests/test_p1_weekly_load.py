"""P1-1：周负荷汇总 — 本周/下周超载天数。"""

from datetime import date, timedelta
from unittest.mock import patch

from app.services import schedule_engine


def test_weekly_load_aggregates_over_days():
    as_of = date(2026, 8, 10)  # Monday
    # craft fake daily_load items spanning this week + next
    fake_items = [
        {
            "date": "2026-08-10",
            "process_id": 1,
            "process_name": "针车",
            "load_qty": 1000,
            "capacity": 800,
            "utilization": 1.25,
            "over_capacity": True,
        },
        {
            "date": "2026-08-11",
            "process_id": 1,
            "process_name": "针车",
            "load_qty": 700,
            "capacity": 800,
            "utilization": 0.875,
            "over_capacity": False,
        },
        {
            "date": "2026-08-17",
            "process_id": 2,
            "process_name": "成型",
            "load_qty": 900,
            "capacity": 800,
            "utilization": 1.125,
            "over_capacity": True,
        },
        {
            "date": "2026-08-18",
            "process_id": 2,
            "process_name": "成型",
            "load_qty": 850,
            "capacity": 800,
            "utilization": 1.062,
            "over_capacity": True,
        },
    ]

    def fake_daily(db, tenant_id, *, date_from, date_to, include_draft_orders=True):
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "items": [r for r in fake_items if date_from.isoformat() <= r["date"] <= date_to.isoformat()],
            "bottlenecks": [],
            "engine_version": "test",
        }

    with (
        patch("app.services.schedule_engine.schedule_settings.get_schedule_by_tenant_id", return_value={"load_warn_utilization": 0.9}),
        patch("app.services.schedule_engine.daily_load", side_effect=fake_daily),
    ):
        out = schedule_engine.weekly_load(None, 1, weeks=2, as_of=as_of)  # type: ignore[arg-type]

    assert out["items"][0]["label"] == "本周"
    assert out["items"][0]["over_days"] == 1
    assert out["items"][0]["week_start"] == "2026-08-10"
    assert "针车" in out["items"][0]["over_process_names"]
    assert out["items"][1]["label"] == "下周"
    assert out["items"][1]["over_days"] == 2
    assert out["items"][1]["week_start"] == "2026-08-17"
