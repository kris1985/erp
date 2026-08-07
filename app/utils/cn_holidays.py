"""中国法定节假日 / 调休（国务院办公厅安排）。

覆盖已公布年份；未收录年份仅按周六日判断休班。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# (start, end, label)
_HOLIDAY_RANGES: list[tuple[date, date, str]] = [
    # 2025 国办发明电〔2024〕12号
    (date(2025, 1, 1), date(2025, 1, 1), "元旦"),
    (date(2025, 1, 28), date(2025, 2, 4), "春节"),
    (date(2025, 4, 4), date(2025, 4, 6), "清明"),
    (date(2025, 5, 1), date(2025, 5, 5), "劳动节"),
    (date(2025, 5, 31), date(2025, 6, 2), "端午"),
    (date(2025, 10, 1), date(2025, 10, 8), "国庆中秋"),
    # 2026 国办发明电〔2025〕7号
    (date(2026, 1, 1), date(2026, 1, 3), "元旦"),
    (date(2026, 2, 15), date(2026, 2, 23), "春节"),
    (date(2026, 4, 4), date(2026, 4, 6), "清明"),
    (date(2026, 5, 1), date(2026, 5, 5), "劳动节"),
    (date(2026, 6, 19), date(2026, 6, 21), "端午"),
    (date(2026, 9, 25), date(2026, 9, 27), "中秋"),
    (date(2026, 10, 1), date(2026, 10, 7), "国庆"),
]

# 调休上班日
_MAKEUP_WORKDAYS: set[date] = {
    # 2025
    date(2025, 1, 26),
    date(2025, 2, 8),
    date(2025, 4, 27),
    date(2025, 9, 28),
    date(2025, 10, 11),
    # 2026
    date(2026, 1, 4),
    date(2026, 2, 14),
    date(2026, 2, 28),
    date(2026, 5, 9),
    date(2026, 9, 20),
    date(2026, 10, 10),
}


def _holiday_label(d: date) -> Optional[str]:
    for start, end, label in _HOLIDAY_RANGES:
        if start <= d <= end:
            return label
    return None


def day_info(d: date) -> dict:
    """单日休班信息。"""
    weekend = d.weekday() >= 5
    holiday = _holiday_label(d)
    makeup = d in _MAKEUP_WORKDAYS

    if holiday:
        return {
            "is_weekend": weekend,
            "is_holiday": True,
            "is_off": True,
            "is_makeup_workday": False,
            "label": holiday,
        }
    if makeup:
        return {
            "is_weekend": weekend,
            "is_holiday": False,
            "is_off": False,
            "is_makeup_workday": True,
            "label": "班",
        }
    if weekend:
        return {
            "is_weekend": True,
            "is_holiday": False,
            "is_off": True,
            "is_makeup_workday": False,
            "label": "休",
        }
    return {
        "is_weekend": False,
        "is_holiday": False,
        "is_off": False,
        "is_makeup_workday": False,
        "label": None,
    }


def day_meta_range(date_from: date, date_to: date) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cur = date_from
    while cur <= date_to:
        out[cur.isoformat()] = day_info(cur)
        cur += timedelta(days=1)
    return out


def is_workday(d: date) -> bool:
    """是否计产工作日（跳过法定假/周末休，保留调休上班）。"""
    return not bool(day_info(d).get("is_off"))


def prev_workday(d: date) -> date:
    cur = d
    while not is_workday(cur):
        cur -= timedelta(days=1)
    return cur


def next_workday(d: date) -> date:
    cur = d
    while not is_workday(cur):
        cur += timedelta(days=1)
    return cur


def add_workdays(start: date, n: int) -> date:
    """从 start 起向前推 n 个工作日（n=0 返回 start 或其后最近工作日）。"""
    if n < 0:
        return sub_workdays(start, -n)
    cur = next_workday(start)
    for _ in range(n):
        cur += timedelta(days=1)
        cur = next_workday(cur)
    return cur


def sub_workdays(end: date, n: int) -> date:
    """从 end 起向后推 n 个工作日（n=0 返回 end 或其前最近工作日）。"""
    if n < 0:
        return add_workdays(end, -n)
    cur = prev_workday(end)
    for _ in range(n):
        cur -= timedelta(days=1)
        cur = prev_workday(cur)
    return cur


def workday_span_ending(end: date, days: int) -> tuple[date, date]:
    """以 end（或其前最近工作日）为完工日，占用 days 个工作日的 [start, end] 闭区间。"""
    days = max(1, int(days))
    end_wd = prev_workday(end)
    if days == 1:
        return end_wd, end_wd
    start_wd = sub_workdays(end_wd, days - 1)
    return start_wd, end_wd


def workday_span_starting(start: date, days: int) -> tuple[date, date]:
    """以 start（或其后最近工作日）为开工日，占用 days 个工作日的 [start, end] 闭区间。"""
    days = max(1, int(days))
    start_wd = next_workday(start)
    if days == 1:
        return start_wd, start_wd
    end_wd = add_workdays(start_wd, days - 1)
    return start_wd, end_wd


def iter_workdays(date_from: date, date_to: date):
    cur = date_from
    while cur <= date_to:
        if is_workday(cur):
            yield cur
        cur += timedelta(days=1)
