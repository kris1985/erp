"""租户考勤规则：休息日、上下班/加班时段、特殊放假与特殊加班、迟到早退扣款。"""

from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
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
    # 上下班时段 HH:mm，可多段
    "work_periods": [
        {"start": "08:00", "end": "12:00"},
        {"start": "13:30", "end": "17:30"},
    ],
    # 加班时段 HH:mm，可多段
    "overtime_periods": [],
    # 特殊放假，精确到小时：YYYY-MM-DD HH:00
    "special_holidays": [],
    # 特殊加班，精确到年月日小时
    "special_overtimes": [],
    # 迟到 / 早退扣工资
    "late_early_deduction": deepcopy(DEFAULT_LATE_EARLY_DEDUCTION),
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def default_attendance_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_ATTENDANCE_RULES)


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
    if "work_periods" in src:
        out["work_periods"] = _normalize_periods(src.get("work_periods"), kind="time")
    if "overtime_periods" in src:
        out["overtime_periods"] = _normalize_periods(src.get("overtime_periods"), kind="time")
    if "special_holidays" in src:
        out["special_holidays"] = _normalize_periods(src.get("special_holidays"), kind="datetime")
    if "special_overtimes" in src:
        out["special_overtimes"] = _normalize_periods(src.get("special_overtimes"), kind="datetime")
    if "late_early_deduction" in src:
        out["late_early_deduction"] = merge_late_early_deduction(_as_dict(src.get("late_early_deduction")))
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
