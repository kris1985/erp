"""P1-7：加班可排非工作日；停工日黑名单优先。"""

from datetime import date, timedelta

from app.services import schedule_calendar as scal
from app.utils import cn_holidays


def test_blackout_blocks_even_when_overtime_allowed():
    saturday = date(2026, 8, 8)  # 周六
    assert cn_holidays.is_workday(saturday) is False
    cfg = {
        "allow_schedule_on_non_workdays": True,
        "schedule_blackout_dates": [{"date": "2026-08-08", "note": "停电"}],
    }
    with scal.use_schedule_calendar(cfg):
        assert scal.is_workday(saturday) is False
        nxt = scal.next_workday(saturday)
        assert nxt == date(2026, 8, 9)


def test_allow_non_workdays_makes_weekend_schedulable():
    saturday = date(2026, 8, 8)
    with scal.use_schedule_calendar({"allow_schedule_on_non_workdays": True}):
        assert scal.is_workday(saturday) is True
        start, end = scal.workday_span_starting(saturday, 2)
        assert start == saturday
        assert end == saturday + timedelta(days=1)


def test_default_calendar_matches_cn_holidays():
    saturday = date(2026, 8, 8)
    monday = date(2026, 8, 10)
    with scal.use_schedule_calendar({}):
        assert scal.is_workday(saturday) is False
        assert scal.is_workday(monday) is True
        assert scal.next_workday(saturday) == monday
