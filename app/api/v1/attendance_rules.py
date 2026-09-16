"""租户考勤规则。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Tenant, Employee
from app.schemas.common import ok
from app.services import attendance_rules

router = APIRouter(prefix="/attendance-rules", tags=["attendance-rules"])


class TimePeriodIn(BaseModel):
    start: str
    end: str


class DeductTierIn(BaseModel):
    up_to_minutes: int | None = None
    deduct_type: str
    amount: float | None = None
    day_fraction: float | None = None


class DeductRuleIn(BaseModel):
    mode: str | None = None
    fixed_amount: float | None = None
    amount_per_minute: float | None = None
    round_up_minutes: bool | None = None
    tiers: list[DeductTierIn] | None = None
    daily_cap_amount: float | None = None


class LateEarlyDeductionIn(DeductRuleIn):
    enabled: bool | None = None
    grace_minutes: int | None = None
    monthly_free_times: int | None = None
    count_late_and_early_separate: bool | None = None
    same_rule_for_early: bool | None = None
    early: DeductRuleIn | None = None


class AttendanceRulesPatchIn(BaseModel):
    rest_day_mode: str | None = Field(default=None, description="weekly | monthly")
    weekly_rest_days: list[int] | None = None
    monthly_rest_days: list[int] | None = None
    work_periods: list[TimePeriodIn] | None = None
    overtime_periods: list[TimePeriodIn] | None = None
    special_holidays: list[TimePeriodIn] | None = None
    special_overtimes: list[TimePeriodIn] | None = None
    late_early_deduction: LateEarlyDeductionIn | None = None


def _validate_deduct_rule(rule: dict[str, Any], *, label: str) -> None:
    mode = rule.get("mode")
    if mode is not None and mode not in attendance_rules._DEDUCT_MODES:
        raise HTTPException(status_code=400, detail=f"{label}扣款模式无效")
    if "fixed_amount" in rule and rule["fixed_amount"] is not None and float(rule["fixed_amount"]) < 0:
        raise HTTPException(status_code=400, detail=f"{label}固定金额不能为负")
    if "amount_per_minute" in rule and rule["amount_per_minute"] is not None and float(rule["amount_per_minute"]) < 0:
        raise HTTPException(status_code=400, detail=f"{label}每分钟金额不能为负")
    if "daily_cap_amount" in rule and rule["daily_cap_amount"] is not None and float(rule["daily_cap_amount"]) < 0:
        raise HTTPException(status_code=400, detail=f"{label}单日封顶不能为负")
    tiers = rule.get("tiers")
    if tiers is None:
        return
    if mode == "tiered" and not tiers:
        raise HTTPException(status_code=400, detail=f"{label}阶梯模式至少配置一档")
    prev = 0
    for i, tier in enumerate(tiers):
        dtype = tier.get("deduct_type")
        if dtype not in attendance_rules._DEDUCT_TYPES:
            raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 档扣款类型无效")
        up = tier.get("up_to_minutes")
        if up is not None:
            if int(up) <= prev:
                raise HTTPException(status_code=400, detail=f"{label}阶梯分钟须递增")
            prev = int(up)
        if dtype == "amount" and float(tier.get("amount") or 0) < 0:
            raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 档金额不能为负")
        if dtype == "day_fraction":
            frac = float(tier.get("day_fraction") or 0)
            if frac <= 0 or frac > 1:
                raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 档日薪比例须在 0–1 之间")


def _validate_late_early(cfg: dict[str, Any]) -> None:
    if "grace_minutes" in cfg and cfg["grace_minutes"] is not None and int(cfg["grace_minutes"]) < 0:
        raise HTTPException(status_code=400, detail="宽限分钟不能为负")
    if "monthly_free_times" in cfg and cfg["monthly_free_times"] is not None and int(cfg["monthly_free_times"]) < 0:
        raise HTTPException(status_code=400, detail="每月免费次数不能为负")
    _validate_deduct_rule(cfg, label="迟到")
    early = cfg.get("early")
    if isinstance(early, dict):
        _validate_deduct_rule(early, label="早退")


def _validate_patch(patch: dict) -> None:
    mode = patch.get("rest_day_mode")
    if mode is not None and mode not in ("weekly", "monthly"):
        raise HTTPException(status_code=400, detail="休息日模式须为 weekly 或 monthly")

    def _check_time_periods(key: str, label: str) -> None:
        items = patch.get(key)
        if items is None:
            return
        for i, item in enumerate(items):
            start = str(item.get("start") or "").strip()
            end = str(item.get("end") or "").strip()
            if not attendance_rules._normalize_time(start) or not attendance_rules._normalize_time(end):
                raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 段须为 HH:mm")
            if start >= end:
                raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 段开始须早于结束")

    def _check_datetime_periods(key: str, label: str) -> None:
        items = patch.get(key)
        if items is None:
            return
        for i, item in enumerate(items):
            start = attendance_rules._normalize_datetime_hour(item.get("start"))
            end = attendance_rules._normalize_datetime_hour(item.get("end"))
            if not start or not end:
                raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 段须精确到小时（YYYY-MM-DD HH:00）")
            if start >= end:
                raise HTTPException(status_code=400, detail=f"{label}第 {i + 1} 段开始须早于结束")

    if "weekly_rest_days" in patch:
        days = patch["weekly_rest_days"] or []
        if any(not isinstance(d, int) or d < 1 or d > 7 for d in days):
            raise HTTPException(status_code=400, detail="每周休息日须为 1–7（周一至周日）")
    if "monthly_rest_days" in patch:
        days = patch["monthly_rest_days"] or []
        if any(not isinstance(d, int) or d < 1 or d > 31 for d in days):
            raise HTTPException(status_code=400, detail="每月休息日须为 1–31")

    _check_time_periods("work_periods", "上下班时间段")
    _check_time_periods("overtime_periods", "加班时间段")
    _check_datetime_periods("special_holidays", "特殊放假")
    _check_datetime_periods("special_overtimes", "特殊加班")

    if "late_early_deduction" in patch and patch["late_early_deduction"] is not None:
        _validate_late_early(patch["late_early_deduction"])


def _dump_nested(patch: dict) -> dict:
    for key in ("work_periods", "overtime_periods", "special_holidays", "special_overtimes"):
        if key in patch and patch[key] is not None:
            patch[key] = [dict(p) if not isinstance(p, dict) else p for p in patch[key]]
    led = patch.get("late_early_deduction")
    if isinstance(led, dict):
        if led.get("tiers") is not None:
            led["tiers"] = [dict(t) if not isinstance(t, dict) else t for t in led["tiers"]]
        early = led.get("early")
        if isinstance(early, dict) and early.get("tiers") is not None:
            early["tiers"] = [dict(t) if not isinstance(t, dict) else t for t in early["tiers"]]
    return patch


@router.get("")
def get_attendance_rules(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.attendance_rules")),
):
    tenant = db.get(Tenant, user.tenant_id)
    return ok(attendance_rules.get_attendance_rules_for_tenant(tenant))


@router.patch("")
def patch_attendance_rules(
    body: AttendanceRulesPatchIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.attendance_rules.write")),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    patch = _dump_nested(patch)
    _validate_patch(patch)
    try:
        return ok(attendance_rules.save_attendance_rules_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
