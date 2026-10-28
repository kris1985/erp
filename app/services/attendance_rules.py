"""租户考勤规则：休息日、上下班时段、迟到早退扣款。"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME_MINUTE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T]([01]\d|2[0-3]):([0-5]\d)")
_DATETIME_HOUR_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T]([01]\d|2[0-3]):00$")

_DEDUCT_MODES = ("fixed_amount", "per_minute", "tiered")
_DEDUCT_TYPES = ("amount", "day_fraction", "half_day", "full_day")

_DEFAULT_TIERS: list[dict[str, Any]] = [
    {"up_to_minutes": 15, "deduct_type": "amount", "amount": 10, "day_fraction": None},
    {"up_to_minutes": 30, "deduct_type": "amount", "amount": 20, "day_fraction": None},
    {"up_to_minutes": 60, "deduct_type": "day_fraction", "amount": None, "day_fraction": 0.5},
    {"up_to_minutes": None, "deduct_type": "full_day", "amount": None, "day_fraction": None},
]

_DEFAULT_DEDUCT_RULE: dict[str, Any] = {
    "mode": "tiered",
    "fixed_amount": 20,
    "amount_per_minute": 1,
    "round_up_minutes": True,
    "tiers": deepcopy(_DEFAULT_TIERS),
    "daily_cap_amount": None,
}

DEFAULT_LATE_EARLY_DEDUCTION: dict[str, Any] = {
    # 总开关
    "enabled": False,
    # 宽限分钟：不超过不算迟到/早退
    "grace_minutes": 5,
    # 每月免费次数（宽限外仍不扣的次数；迟到与早退合计）
    "monthly_free_times": 0,
    # 同日迟到+早退是否分别计次/扣款
    "count_late_and_early_separate": True,
    # 早退是否与迟到共用同一套扣款规则
    "same_rule_for_early": True,
    **deepcopy(_DEFAULT_DEDUCT_RULE),
    # same_rule_for_early=false 时使用
    "early": deepcopy(_DEFAULT_DEDUCT_RULE),
}

DEFAULT_ATTENDANCE_RULES: dict[str, Any] = {
    # weekly | monthly 二选一
    "rest_day_mode": "weekly",
    # 1=周一 … 7=周日
    "weekly_rest_days": [6, 7],
    # 每月几号休息，1–31
    "monthly_rest_days": [],
    # 固定休息日：默认照发工资（不扣）；餐补、住宿补、其它补默认不算
    "rest_pay_salary": True,
    "rest_pay_meal": False,
    "rest_pay_housing": False,
    "rest_pay_other": False,
    # 指定休息，闭区间 YYYY-MM-DD HH:mm，可多段。盖住的时段不打卡。
    "designated_rest_ranges": [],
    # 上下班时段 HH:mm，可多段
    "work_periods": [
        {"start": "08:00", "end": "12:00"},
        {"start": "13:30", "end": "17:30"},
    ],
    # 加班时段 HH:mm，可多段。工作日打卡后按实际时长计加班费。
    "overtime_periods": [],
    "special_holidays": [],
    "special_overtimes": [],
    # 迟到 / 早退扣工资
    "late_early_deduction": deepcopy(DEFAULT_LATE_EARLY_DEDUCTION),
    # 手机打卡地点。纬度经度都为空时不能打卡。坐标用 WGS84，与手机定位一致。
    "clock_site": {"latitude": None, "longitude": None, "radius_meters": 300},
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def default_attendance_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_ATTENDANCE_RULES)


def _parse_rest_bound(value: Any, *, is_end: bool) -> datetime | None:
    """只填日期时，开始按 00:00，结束按 23:59。"""
    if value is None:
        return None
    text = str(value).strip().replace("T", " ")
    if _DATE_RE.match(text):
        text = f"{text} {'23:59' if is_end else '00:00'}"
    elif len(text) >= 16:
        text = text[:16]
    if not _DATETIME_MINUTE_RE.match(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _normalize_rest_bound(value: Any, *, is_end: bool) -> str | None:
    parsed = _parse_rest_bound(value, is_end=is_end)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def _range_pay_flag(item: dict[str, Any], key: str, default: bool) -> bool:
    if key not in item or item.get(key) is None:
        return default
    return bool(item.get(key))


def _normalize_rest_ranges(raw: Any) -> list[dict[str, Any]]:
    """闭区间，精确到分钟。开始等于结束表示这一分钟休息。

    每段自带工资、餐补、住宿补、其它补。工资默认勾选，补贴默认不勾。
    """
    out: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        start = _normalize_rest_bound(item.get("start"), is_end=False)
        end = _normalize_rest_bound(item.get("end"), is_end=True)
        if not start or not end or start > end:
            continue
        out.append({
            "start": start,
            "end": end,
            "pay_salary": _range_pay_flag(item, "pay_salary", True),
            "pay_meal": _range_pay_flag(item, "pay_meal", False),
            "pay_housing": _range_pay_flag(item, "pay_housing", False),
            "pay_other": _range_pay_flag(item, "pay_other", False),
        })
    return out


def _rest_blocks(ranges: list[Any] | None) -> list[tuple[datetime, datetime]]:
    """休息区间转成左闭右开，结束分钟包含在内。"""
    blocks: list[tuple[datetime, datetime]] = []
    for item in ranges or []:
        if not isinstance(item, dict):
            continue
        start = _parse_rest_bound(item.get("start"), is_end=False)
        end = _parse_rest_bound(item.get("end"), is_end=True)
        if start is None or end is None or start > end:
            continue
        blocks.append((start, end + timedelta(minutes=1)))
    return blocks


def _subtract_blocks(
    start: datetime,
    end: datetime,
    blocks: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    pieces = [(start, end)]
    for block_start, block_end in blocks:
        nxt: list[tuple[datetime, datetime]] = []
        for piece_start, piece_end in pieces:
            if block_end <= piece_start or block_start >= piece_end:
                nxt.append((piece_start, piece_end))
                continue
            if block_start > piece_start:
                nxt.append((piece_start, min(block_start, piece_end)))
            if block_end < piece_end:
                nxt.append((max(block_end, piece_start), piece_end))
        pieces = [(left, right) for left, right in nxt if right > left]
    return pieces


def apply_designated_rest_to_slots(
    work_date: date,
    slots: list[dict[str, Any]],
    ranges: list[Any] | None,
) -> list[dict[str, Any]]:
    """从班次里挖掉指定休息。一段被从中间切开时拆成多段。"""
    blocks = _rest_blocks(ranges)
    if not blocks:
        return slots
    out: list[dict[str, Any]] = []
    for slot in slots:
        try:
            start = datetime.strptime(f"{work_date.isoformat()} {slot['start']}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{work_date.isoformat()} {slot['end']}", "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        pieces = _subtract_blocks(start, end, blocks)
        if len(pieces) == 1 and pieces[0] == (start, end):
            out.append(slot)
            continue
        for index, (piece_start, piece_end) in enumerate(pieces):
            out.append({
                **slot,
                "id": slot["id"] if len(pieces) == 1 else f"{slot['id']}+{index}",
                "start": piece_start.strftime("%H:%M"),
                "end": piece_end.strftime("%H:%M"),
            })
    return out


def _normalize_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not _TIME_RE.match(text):
        return None
    return text


def _normalize_datetime_hour(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("T", " ")
    # YYYY-MM-DD HH:mm → 精确到小时
    if len(text) >= 13 and text[10] == " ":
        hm = text[11:16]
        if _TIME_RE.match(hm):
            text = f"{text[:11]}{hm[:2]}:00"
    if not _DATETIME_HOUR_RE.match(text):
        return None
    return text


def _normalize_periods(raw: Any, *, kind: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        if kind == "time":
            start = _normalize_time(item.get("start"))
            end = _normalize_time(item.get("end"))
        else:
            start = _normalize_datetime_hour(item.get("start"))
            end = _normalize_datetime_hour(item.get("end"))
        if not start or not end:
            continue
        if start >= end:
            continue
        out.append({"start": start, "end": end})
    return out


def _normalize_int_list(raw: Any, *, lo: int, hi: int) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item in _as_list(raw):
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n < lo or n > hi or n in seen:
            continue
        seen.add(n)
        out.append(n)
    out.sort()
    return out


def _to_nonneg_int(value: Any, default: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, n)


def _to_nonneg_float(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, n)


def _to_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _normalize_tiers(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        deduct_type = item.get("deduct_type")
        if deduct_type not in _DEDUCT_TYPES:
            continue
        up_raw = item.get("up_to_minutes")
        if up_raw is None or up_raw == "" or str(up_raw).lower() in ("null", "none", "及以上", "+"):
            up_to: int | None = None
        else:
            try:
                up_to = max(1, int(up_raw))
            except (TypeError, ValueError):
                continue
        amount = _to_optional_float(item.get("amount"))
        day_fraction = _to_optional_float(item.get("day_fraction"))
        if day_fraction is not None and day_fraction > 1:
            day_fraction = 1.0
        if deduct_type == "amount" and amount is None:
            amount = 0.0
        if deduct_type == "day_fraction" and day_fraction is None:
            day_fraction = 0.5
        if deduct_type == "half_day":
            day_fraction = 0.5
        if deduct_type == "full_day":
            day_fraction = 1.0
        out.append(
            {
                "up_to_minutes": up_to,
                "deduct_type": deduct_type,
                "amount": amount,
                "day_fraction": day_fraction,
            }
        )
    # 有上限的档按分钟升序；「及以上」放最后
    bounded = sorted([t for t in out if t["up_to_minutes"] is not None], key=lambda t: t["up_to_minutes"])
    unbounded = [t for t in out if t["up_to_minutes"] is None]
    return bounded + unbounded[:1]


def _normalize_deduct_rule(raw: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(fallback or _DEFAULT_DEDUCT_RULE)
    src = _as_dict(raw)
    mode = src.get("mode")
    if mode in _DEDUCT_MODES:
        base["mode"] = mode
    if "fixed_amount" in src:
        base["fixed_amount"] = _to_nonneg_float(src.get("fixed_amount"), base["fixed_amount"])
    if "amount_per_minute" in src:
        base["amount_per_minute"] = _to_nonneg_float(src.get("amount_per_minute"), base["amount_per_minute"])
    if "round_up_minutes" in src:
        base["round_up_minutes"] = bool(src.get("round_up_minutes"))
    if "tiers" in src:
        tiers = _normalize_tiers(src.get("tiers"))
        base["tiers"] = tiers or deepcopy(_DEFAULT_TIERS)
    if "daily_cap_amount" in src:
        base["daily_cap_amount"] = _to_optional_float(src.get("daily_cap_amount"))
    return base


def merge_late_early_deduction(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = deepcopy(DEFAULT_LATE_EARLY_DEDUCTION)
    src = _as_dict(stored)
    if "enabled" in src:
        out["enabled"] = bool(src.get("enabled"))
    if "grace_minutes" in src:
        out["grace_minutes"] = _to_nonneg_int(src.get("grace_minutes"), out["grace_minutes"])
    if "monthly_free_times" in src:
        out["monthly_free_times"] = _to_nonneg_int(src.get("monthly_free_times"), out["monthly_free_times"])
    if "count_late_and_early_separate" in src:
        out["count_late_and_early_separate"] = bool(src.get("count_late_and_early_separate"))
    if "same_rule_for_early" in src:
        out["same_rule_for_early"] = bool(src.get("same_rule_for_early"))

    rule = _normalize_deduct_rule(src, _DEFAULT_DEDUCT_RULE)
    out["mode"] = rule["mode"]
    out["fixed_amount"] = rule["fixed_amount"]
    out["amount_per_minute"] = rule["amount_per_minute"]
    out["round_up_minutes"] = rule["round_up_minutes"]
    out["tiers"] = rule["tiers"]
    out["daily_cap_amount"] = rule["daily_cap_amount"]

    early_src = src.get("early") if "early" in src else out.get("early")
    out["early"] = _normalize_deduct_rule(early_src, _DEFAULT_DEDUCT_RULE)
    return out


def _normalize_clock_site(raw: Any) -> dict[str, Any]:
    src = _as_dict(raw)
    radius = _to_nonneg_int(src.get("radius_meters"), 300)
    radius = min(500, max(5, radius))

    def coord(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return None

    latitude = coord(src.get("latitude"))
    longitude = coord(src.get("longitude"))
    if (
        latitude is None
        or longitude is None
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return {"latitude": None, "longitude": None, "radius_meters": radius}
    return {"latitude": latitude, "longitude": longitude, "radius_meters": radius}


def merge_attendance_rules(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = default_attendance_rules()
    src = _as_dict(stored)
    mode = src.get("rest_day_mode")
    if mode in ("weekly", "monthly"):
        out["rest_day_mode"] = mode
    if "weekly_rest_days" in src:
        out["weekly_rest_days"] = _normalize_int_list(src.get("weekly_rest_days"), lo=1, hi=7)
    if "monthly_rest_days" in src:
        out["monthly_rest_days"] = _normalize_int_list(src.get("monthly_rest_days"), lo=1, hi=31)
    for flag in ("rest_pay_salary", "rest_pay_meal", "rest_pay_housing", "rest_pay_other"):
        if flag in src and src.get(flag) is not None:
            out[flag] = bool(src.get(flag))
    if "designated_rest_ranges" in src:
        out["designated_rest_ranges"] = _normalize_rest_ranges(src.get("designated_rest_ranges"))
    if "work_periods" in src:
        out["work_periods"] = _normalize_periods(src.get("work_periods"), kind="time")
    if "overtime_periods" in src:
        out["overtime_periods"] = _normalize_periods(src.get("overtime_periods"), kind="time")
    # 例外日期已取消，历史配置不再参与打卡和交期。
    out["special_holidays"] = []
    out["special_overtimes"] = []
    if "late_early_deduction" in src:
        out["late_early_deduction"] = merge_late_early_deduction(_as_dict(src.get("late_early_deduction")))
    if "clock_site" in src:
        out["clock_site"] = _normalize_clock_site(src.get("clock_site"))
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_attendance_rules_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_attendance_rules(_as_dict(settings.get("attendance_rules")) if settings else None)


def get_attendance_rules_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_attendance_rules_for_tenant(tenant)


def _is_fixed_rest_day(d: date, cfg: dict[str, Any]) -> bool:
    if cfg.get("rest_day_mode") == "monthly":
        return d.day in set(cfg.get("monthly_rest_days") or [])
    return d.isoweekday() in set(cfg.get("weekly_rest_days") or [])


def is_fixed_rest_day(d: date, rules: dict[str, Any] | None = None) -> bool:
    """每周或每月固定休息日，不含指定休息。"""
    return _is_fixed_rest_day(d, merge_attendance_rules(rules))


def _period_slots(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, period in enumerate(cfg.get("work_periods") or []):
        slots.append({
            "id": f"work:{index}",
            "kind": "work",
            "label": "",
            "start": period["start"],
            "end": period["end"],
        })
    for index, period in enumerate(cfg.get("overtime_periods") or []):
        slots.append({
            "id": f"overtime:{index}",
            "kind": "overtime",
            "label": "",
            "start": period["start"],
            "end": period["end"],
        })
    return slots


def _range_covers_day(d: date, ranges: list[Any] | None) -> bool:
    day_start = datetime.combine(d, time.min)
    day_end = day_start + timedelta(days=1)
    return not _subtract_blocks(day_start, day_end, _rest_blocks(ranges))


def is_base_rest_day(d: date, rules: dict[str, Any] | None = None) -> bool:
    """固定休息日，或指定休息盖住全天 / 当天全部班次。"""
    cfg = merge_attendance_rules(rules)
    if _is_fixed_rest_day(d, cfg):
        return True
    ranges = cfg.get("designated_rest_ranges") or []
    if not ranges:
        return False
    if _range_covers_day(d, ranges):
        return True
    raw = _period_slots(cfg)
    return bool(raw) and not apply_designated_rest_to_slots(d, raw, ranges)


def _range_overlaps_day(item: dict[str, Any], d: date) -> bool:
    start = _parse_rest_bound(item.get("start"), is_end=False)
    end = _parse_rest_bound(item.get("end"), is_end=True)
    if start is None or end is None or start > end:
        return False
    day_start = datetime.combine(d, time.min)
    day_end = day_start + timedelta(days=1)
    return start < day_end and end + timedelta(minutes=1) > day_start


def designated_rest_pay(d: date, rules: dict[str, Any] | None = None) -> dict[str, bool] | None:
    """指定休息盖住、当天不上班时，返回这一天的工资和补贴勾选。

    固定休息日、以及只休掉部分班次仍要上班的日子，返回 None。
    多段叠在同一天时：任一段勾了工资就不扣；餐补、住宿补、其它补有一段勾选即计入。
    """
    cfg = merge_attendance_rules(rules)
    if _is_fixed_rest_day(d, cfg) or not is_base_rest_day(d, cfg):
        return None
    ranges = [
        item
        for item in cfg.get("designated_rest_ranges") or []
        if isinstance(item, dict) and _range_overlaps_day(item, d)
    ]
    if not ranges:
        return None
    return {
        "pay_salary": any(item.get("pay_salary", True) is not False for item in ranges),
        "pay_meal": any(bool(item.get("pay_meal")) for item in ranges),
        "pay_housing": any(bool(item.get("pay_housing")) for item in ranges),
        "pay_other": any(bool(item.get("pay_other")) for item in ranges),
    }


def is_attendance_workday(d: date, rules: dict[str, Any] | None = None) -> bool:
    """固定休息日，以及被指定休息盖住的整天，都不出勤。"""
    return not is_base_rest_day(d, rules)


def next_attendance_workday(d: date, rules: dict[str, Any] | None = None) -> date:
    cfg = merge_attendance_rules(rules)
    cur = d
    for _ in range(800):
        if is_attendance_workday(cur, cfg):
            return cur
        cur += timedelta(days=1)
    return d


def _clock_periods(cfg: dict[str, Any]) -> list[tuple[time, time]]:
    periods: list[tuple[time, time]] = []
    for item in cfg.get("work_periods") or []:
        if not isinstance(item, dict):
            continue
        start = _normalize_time(item.get("start"))
        end = _normalize_time(item.get("end"))
        if not start or not end or start >= end:
            continue
        sh, sm = (int(part) for part in start.split(":"))
        eh, em = (int(part) for part in end.split(":"))
        periods.append((time(sh, sm), time(eh, em)))
    periods.sort()
    return periods


def attendance_workday_minutes(rules: dict[str, Any] | None = None) -> int:
    """一个出勤日的上下班分钟数，不含加班。"""
    total = 0
    for start, end in _clock_periods(merge_attendance_rules(rules)):
        total += (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return total


def attendance_work_slots(day: date, rules: dict[str, Any] | None = None) -> list[tuple[datetime, datetime]]:
    """当天可排产的上下班时段。休息日为空；指定休息从班次里挖掉。"""
    cfg = merge_attendance_rules(rules)
    if not is_attendance_workday(day, cfg):
        return []
    raw = [
        {"id": str(index), "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
        for index, (start, end) in enumerate(_clock_periods(cfg))
    ]
    slots = apply_designated_rest_to_slots(day, raw, cfg.get("designated_rest_ranges"))
    out: list[tuple[datetime, datetime]] = []
    for slot in slots:
        try:
            sh, sm = (int(part) for part in str(slot["start"]).split(":"))
            eh, em = (int(part) for part in str(slot["end"]).split(":"))
        except (TypeError, ValueError):
            continue
        begin = datetime.combine(day, time(sh, sm))
        finish = datetime.combine(day, time(eh, em))
        if finish > begin:
            out.append((begin, finish))
    out.sort()
    return out


def next_attendance_work_moment(moment: datetime, rules: dict[str, Any] | None = None) -> datetime:
    """落到下一个还开着的上下班时刻。正好下班则顺延到下一班。"""
    cfg = merge_attendance_rules(rules)
    cursor = moment.replace(second=0, microsecond=0)
    for _ in range(800):
        for start, end in attendance_work_slots(cursor.date(), cfg):
            if cursor < start:
                return start
            if start <= cursor < end:
                return cursor
        cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min)
    return moment.replace(second=0, microsecond=0)


def add_attendance_work_minutes(
    start: datetime,
    minutes: int,
    rules: dict[str, Any] | None = None,
) -> datetime:
    """从 start 起占用若干上班分钟，跳过午休、下班后和休息日。"""
    cfg = merge_attendance_rules(rules)
    left = max(0, int(minutes))
    if left <= 0:
        return start.replace(second=0, microsecond=0)
    cursor = next_attendance_work_moment(start, cfg)
    guard = 0
    while left > 0 and guard < 800:
        moved = False
        for slot_start, slot_end in attendance_work_slots(cursor.date(), cfg):
            if slot_end <= cursor:
                continue
            begin = cursor if cursor > slot_start else slot_start
            if begin >= slot_end:
                continue
            room = int((slot_end - begin).total_seconds() // 60)
            if room <= 0:
                continue
            take = room if room < left else left
            cursor = begin + timedelta(minutes=take)
            left -= take
            moved = True
            if left <= 0:
                return cursor
        cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min)
        if not moved:
            guard += 1
    return cursor


def attendance_span_starting(
    start: date,
    days: int,
    rules: dict[str, Any] | None = None,
) -> tuple[date, date]:
    """从 start 起占用 days 个考勤生产日的闭区间。"""
    cfg = merge_attendance_rules(rules)
    days = max(1, int(days))
    start_wd = next_attendance_workday(start, cfg)
    if days == 1:
        return start_wd, start_wd
    cur = start_wd
    counted = 1
    guard = 0
    while counted < days:
        cur += timedelta(days=1)
        if is_attendance_workday(cur, cfg):
            counted += 1
        guard += 1
        if guard > 800:
            break
    return start_wd, cur


def save_attendance_rules_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("attendance_rules")))
    for key in DEFAULT_ATTENDANCE_RULES:
        if key in patch:
            current[key] = patch[key]
    merged = merge_attendance_rules(current)
    settings["attendance_rules"] = merged
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.commit()
    db.refresh(tenant)
    return get_attendance_rules_for_tenant(tenant)


def _billable_minutes(minutes: int, grace_minutes: int, *, round_up: bool) -> int:
    excess = max(0, int(minutes) - int(grace_minutes))
    if excess <= 0:
        return 0
    if round_up:
        return excess
    return excess


def _pick_tier(tiers: list[dict[str, Any]], minutes: int) -> dict[str, Any] | None:
    if minutes <= 0 or not tiers:
        return None
    for tier in tiers:
        up = tier.get("up_to_minutes")
        if up is None or minutes <= int(up):
            return tier
    return tiers[-1]


def _deduct_from_rule(
    rule: dict[str, Any],
    minutes: int,
    *,
    grace_minutes: int,
    day_wage: Decimal,
) -> dict[str, Any]:
    """按单次迟到/早退分钟数计算扣款（不含月免次）。"""
    round_up = bool(rule.get("round_up_minutes", True))
    billable = _billable_minutes(minutes, grace_minutes, round_up=round_up)
    if billable <= 0:
        return {
            "minutes": minutes,
            "billable_minutes": 0,
            "amount": 0.0,
            "day_fraction": 0.0,
            "skipped": "within_grace",
        }

    mode = rule.get("mode") or "tiered"
    amount = Decimal("0")
    day_fraction = Decimal("0")
    detail: dict[str, Any] = {"mode": mode, "billable_minutes": billable}

    if mode == "fixed_amount":
        amount = Decimal(str(rule.get("fixed_amount") or 0))
    elif mode == "per_minute":
        units = billable
        if round_up:
            units = max(1, billable)
        amount = Decimal(str(rule.get("amount_per_minute") or 0)) * Decimal(units)
    else:
        tier = _pick_tier(list(rule.get("tiers") or []), billable)
        detail["tier"] = tier
        if tier:
            dtype = tier.get("deduct_type")
            if dtype == "amount":
                amount = Decimal(str(tier.get("amount") or 0))
            elif dtype == "day_fraction":
                day_fraction = Decimal(str(tier.get("day_fraction") or 0))
                amount = (day_wage * day_fraction).quantize(Decimal("0.01"))
            elif dtype == "half_day":
                day_fraction = Decimal("0.5")
                amount = (day_wage * day_fraction).quantize(Decimal("0.01"))
            elif dtype == "full_day":
                day_fraction = Decimal("1")
                amount = day_wage

    cap = rule.get("daily_cap_amount")
    capped = False
    if cap is not None and amount > Decimal(str(cap)):
        amount = Decimal(str(cap))
        capped = True

    return {
        "minutes": minutes,
        "billable_minutes": billable,
        "amount": float(amount),
        "day_fraction": float(day_fraction),
        "capped": capped,
        **detail,
    }


def calc_late_early_deduction(
    rules: dict[str, Any],
    *,
    late_minutes: int = 0,
    early_minutes: int = 0,
    day_wage: Decimal | float | int = 0,
    monthly_free_used: int = 0,
) -> dict[str, Any]:
    """
    按配置计算单日迟到/早退扣款预览。

    monthly_free_used: 本月已使用的免费次数（不含本次）。
    返回金额单位为元；day_fraction 类扣款依赖传入的 day_wage（日薪基数）。
    """
    cfg = merge_late_early_deduction(_as_dict(rules.get("late_early_deduction") if rules else None))
    if not cfg.get("enabled"):
        return {"enabled": False, "total_amount": 0.0, "items": []}

    wage = Decimal(str(day_wage or 0))
    grace = int(cfg.get("grace_minutes") or 0)
    free_left = max(0, int(cfg.get("monthly_free_times") or 0) - int(monthly_free_used or 0))
    separate = bool(cfg.get("count_late_and_early_separate", True))
    same_early = bool(cfg.get("same_rule_for_early", True))
    late_rule = cfg
    early_rule = cfg if same_early else _normalize_deduct_rule(cfg.get("early"), _DEFAULT_DEDUCT_RULE)

    events: list[tuple[str, int, dict[str, Any]]] = []
    if late_minutes > 0:
        events.append(("late", int(late_minutes), late_rule))
    if early_minutes > 0:
        events.append(("early", int(early_minutes), early_rule))

    if not separate and events:
        # 合并为一次：取较大分钟，用迟到规则（或共用规则）
        kind = "late_or_early"
        mins = max(m for _, m, _ in events)
        events = [(kind, mins, late_rule)]

    items: list[dict[str, Any]] = []
    total = Decimal("0")
    for kind, mins, rule in events:
        billable = _billable_minutes(mins, grace, round_up=bool(rule.get("round_up_minutes", True)))
        if billable <= 0:
            items.append({"kind": kind, "minutes": mins, "amount": 0.0, "skipped": "within_grace"})
            continue
        if free_left > 0:
            free_left -= 1
            items.append({"kind": kind, "minutes": mins, "amount": 0.0, "skipped": "monthly_free"})
            continue
        one = _deduct_from_rule(rule, mins, grace_minutes=grace, day_wage=wage)
        one["kind"] = kind
        items.append(one)
        total += Decimal(str(one.get("amount") or 0))

    # 若分别计次但配置了单日封顶在各自规则上，已在单项处理；
    # 这里再给一个合计封顶：取迟到规则的 daily_cap（共用时一致）
    cap = late_rule.get("daily_cap_amount")
    if not separate and cap is not None and total > Decimal(str(cap)):
        total = Decimal(str(cap))

    return {
        "enabled": True,
        "grace_minutes": grace,
        "total_amount": float(total),
        "items": items,
    }
