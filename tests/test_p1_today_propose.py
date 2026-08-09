"""P1-2：今日可排 → 深链排产并自动出方案。"""

from app.services.analytics import _schedule_propose_path


def test_schedule_propose_path_with_ids():
    path = _schedule_propose_path([12, 34, "bad", None])
    assert path.startswith("/admin/schedule?")
    assert "order_ids=12,34" in path
    assert "propose=1" in path


def test_schedule_propose_path_empty():
    assert _schedule_propose_path([]) == "/admin/schedule?propose=1"
    assert _schedule_propose_path(None) == "/admin/schedule?propose=1"
