"""A1b：生产单风险条规则。"""

from datetime import date, timedelta

from app.services.order_risk import compute_order_risk


def test_rush_and_material_is_red():
    r = compute_order_risk(
        status="in_progress",
        delivery_date=date.today() + timedelta(days=14),
        overall_percent=40,
        is_rush=True,
        kit_ok=False,
        kit_ready_date="2026-08-20",
        today=date(2026, 8, 9),
    )
    assert r["risk_level"] == "red"
    codes = [x["code"] for x in r["risk_reasons"]]
    assert "rush" in codes and "material" in codes and "kit_ready" in codes


def test_delivery_risk_matches_at_risk_not_green():
    today = date(2026, 8, 9)
    r = compute_order_risk(
        status="in_progress",
        delivery_date=today + timedelta(days=1),
        overall_percent=50,
        is_rush=False,
        kit_ok=True,
        today=today,
    )
    assert r["at_risk"] is True
    assert r["risk_level"] == "red"
    assert r["risk_level"] != "green"
    assert any(x["code"] == "delivery_risk" for x in r["risk_reasons"])


def test_normal_open_order_is_green():
    today = date(2026, 8, 9)
    r = compute_order_risk(
        status="confirmed",
        delivery_date=today + timedelta(days=20),
        overall_percent=30,
        is_rush=False,
        kit_ok=True,
        today=today,
    )
    assert r["at_risk"] is False
    assert r["risk_level"] == "green"
    assert r["risk_label"] == "正常"


def test_completed_is_none():
    r = compute_order_risk(
        status="completed",
        delivery_date=date(2026, 8, 1),
        overall_percent=100,
        is_rush=False,
        kit_ok=False,
        today=date(2026, 8, 9),
    )
    assert r["risk_level"] == "none"
    assert r["risk_reasons"] == []
