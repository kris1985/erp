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
