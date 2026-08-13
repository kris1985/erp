"""排产工作日历：国定假 + 租户加班开关 + 停工日黑名单。

通过 contextvars 绑定租户 schedule cfg，供 schedule_engine 无感切换。
未绑定时行为等同 cn_holidays（仅国定假/周末）。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from typing import Any, Iterator, Optional

from app.utils import cn_holidays

_cv: ContextVar[dict[str, Any] | None] = ContextVar("schedule_calendar_cfg", default=None)


def _cfg() -> dict[str, Any]:
    return _cv.get() or {}


def _blackout_set(cfg: dict[str, Any] | None = None) -> set[date]:
    raw = (cfg or _cfg()).get("schedule_blackout_dates") or []
    out: set[date] = set()
    for item in raw:
        if isinstance(item, date):
            out.add(item)
            continue
        if isinstance(item, dict):
            s = item.get("date") or item.get("day")
        else:
            s = item
        if not s:
            continue
        try:
            out.add(date.fromisoformat(str(s)[:10]))
        except ValueError:
            continue
    return out


@contextmanager
def use_schedule_calendar(cfg: Optional[dict[str, Any]]) -> Iterator[None]:
    token = _cv.set(dict(cfg or {}))
    try:
        yield
    finally:
        _cv.reset(token)


def is_blackout(d: date) -> bool:
    return d in _blackout_set(_cfg())


def is_workday(d: date) -> bool:
    cfg = _cfg()
    if d in _blackout_set(cfg):
        return False
    if cfg.get("allow_schedule_on_non_workdays"):
        return True
    return cn_holidays.is_workday(d)


def prev_workday(d: date) -> date:
    cur = d
    guard = 0
    while not is_workday(cur):
        cur -= timedelta(days=1)
        guard += 1
        if guard > 800:
            return d
    return cur


def next_workday(d: date) -> date:
    cur = d
    guard = 0
    while not is_workday(cur):
        cur += timedelta(days=1)
        guard += 1
        if guard > 800:
            return d
    return cur


def iter_workdays(start: date, end: date) -> Iterator[date]:
    cur = start
    while cur <= end:
        if is_workday(cur):
            yield cur
        cur += timedelta(days=1)


def workday_span_ending(end: date, days: int) -> tuple[date, date]:
    days = max(1, int(days))
    end_wd = prev_workday(end)
    if days == 1:
        return end_wd, end_wd
    cur = end_wd
    for _ in range(days - 1):
        cur -= timedelta(days=1)
        cur = prev_workday(cur)
    return cur, end_wd


def workday_span_starting(start: date, days: int) -> tuple[date, date]:
    days = max(1, int(days))
    start_wd = next_workday(start)
    if days == 1:
        return start_wd, start_wd
    cur = start_wd
    for _ in range(days - 1):
        cur += timedelta(days=1)
        cur = next_workday(cur)
    return start_wd, cur


def add_workdays(d: date, n: int) -> date:
    """从 d 起前进/后退 n 个工作日。n=0 时落到最近工作日（含当天）。"""
    if n == 0:
        return next_workday(d)
    cur = d
    moved = 0
    step = 1 if n > 0 else -1
    guard = 0
    while moved < abs(n):
        cur += timedelta(days=step)
        if is_workday(cur):
            moved += 1
        guard += 1
        if guard > 800:
            return cur
    return cur


def workday_delta(start: date, end: date) -> int:
    """从 start 到 end 经过几个工作日（不含 start，含 end）。同一天为 0。"""
    if start == end:
        return 0
    if end > start:
        n = 0
        cur = start
        guard = 0
        while cur < end:
            cur += timedelta(days=1)
            if is_workday(cur):
                n += 1
            guard += 1
            if guard > 800:
                break
        return n
    return -workday_delta(end, start)
