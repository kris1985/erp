import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceDay,
    AttendancePunch,
    Color,
    Department,
    Employee,
    OwnProduct,
    ProcessDefinition,
    ReportType,
    WorkLog,
    WorkLogStatus,
)
from app.schemas.common import normalize_page, page_payload
from app.services.salary_service import work_log_loss_deduction, work_log_unit_price


LOCAL_OFFSET = timedelta(hours=8)
PUNCH_TYPES = {"on_duty", "off_duty"}


class AttendanceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _now_utc() -> datetime:
    # 数据库沿用项目现有的无时区 UTC 存储约定。
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_date(value: datetime | None = None) -> date:
    return ((value or _now_utc()) + LOCAL_OFFSET).date()


def _local_text(value: datetime | None) -> str | None:
    return (value + LOCAL_OFFSET).strftime("%Y-%m-%d %H:%M:%S") if value else None


def _require_employee(db: Session, tenant_id: int, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee or employee.tenant_id != tenant_id or not employee.is_active:
        raise AttendanceError("employee_not_found", "员工不存在或未启用")
    return employee


def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    chord = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lng / 2) ** 2
    return 2 * radius * asin(sqrt(chord))


def _clock_site(db: Session, tenant_id: int) -> dict:
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    site = get_attendance_rules_by_tenant_id(db, tenant_id).get("clock_site") or {}
    return {
        "latitude": site.get("latitude"),
        "longitude": site.get("longitude"),
        "radius_meters": int(site.get("radius_meters") or 300),
        "configured": site.get("latitude") is not None and site.get("longitude") is not None,
    }


def _require_inside(site: dict, latitude: float | None, longitude: float | None) -> tuple[float, float]:
    if not site.get("configured"):
        raise AttendanceError("clock_site_missing", "工厂还没设置打卡地点")
    if latitude is None or longitude is None:
        raise AttendanceError("location_required", "请开启定位后再打卡")
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        raise AttendanceError("location_required", "定位无效")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise AttendanceError("location_required", "定位无效")
    radius = int(site.get("radius_meters") or 300)
    meters = distance_meters(float(site["latitude"]), float(site["longitude"]), lat, lng)
    if meters > radius:
        shown = f"{int(round(meters))} 米" if meters < 1000 else f"{meters / 1000:.1f} 公里"
        raise AttendanceError("out_of_range", f"距离厂区 {shown}，超出 {radius} 米范围")
    return lat, lng


def _hm_minutes(value: str) -> int:
    hour, minute = str(value or "00:00").split(":")[:2]
    return int(hour) * 60 + int(minute)


def _minutes_to_hm(minutes: int) -> str:
    minutes = max(0, min(23 * 60 + 59, int(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _window_state(now_hm: str, start: str, end: str) -> str:
    now = _hm_minutes(now_hm)
    if now < _hm_minutes(start):
        return "early"
    if now > _hm_minutes(end):
        return "late"
    return "open"


# 应到之后还能打上班的分钟数；下班提前开放的分钟数。
CLOCK_IN_LATE_MINUTES = 30
CLOCK_OUT_LEAD_MINUTES = 30


def _window_bounds(slots: list[dict]) -> list[dict]:
    """按打卡规则里每一段的上班、下班时间切窗口。

    时段起止来自规则里的上下班、加班配置，不写死某一套班次。
    上班收到该段上班时间后 30 分钟，过了就记缺卡。
    下班从该段下班时间前 30 分钟才开放。
    相邻两段从空隙中点切开；时段短于这两段窗口时，在中点切开。
    """
    bounded = []
    for index, slot in enumerate(slots):
        start = _hm_minutes(slot["start"])
        end = _hm_minutes(slot["end"])
        if end <= start:
            end = min(23 * 60 + 59, start + 60)
        prev_end = _hm_minutes(slots[index - 1]["end"]) if index else None
        next_start = _hm_minutes(slots[index + 1]["start"]) if index + 1 < len(slots) else None
        on_from = (prev_end + start) // 2 if prev_end is not None else max(0, start - 60)
        off_to = (end + next_start) // 2 if next_start is not None else min(23 * 60 + 59, end + 60)
        if prev_end is not None and on_from > start:
            on_from = start
        on_to = min(start + CLOCK_IN_LATE_MINUTES, end, off_to)
        off_from = max(end - CLOCK_OUT_LEAD_MINUTES, start)
        if off_from < on_to:
            mid = (start + end) // 2
            on_to = mid
            off_from = mid
        if on_to < on_from:
            on_to = on_from
        if off_to < off_from:
            off_to = off_from
        bounded.append({
            **slot,
            "on_from": _minutes_to_hm(on_from),
            "on_to": _minutes_to_hm(on_to),
            "off_from": _minutes_to_hm(off_from),
            "off_to": _minutes_to_hm(off_to),
        })
    return bounded


def _side_action(slot: dict, side: str, now_hm: str, is_today: bool) -> dict:
    punch_type = "on_duty" if side == "on" else "off_duty"
    punched = slot.get("clock_in_at") if side == "on" else slot.get("clock_out_at")
    window_from = slot["on_from"] if side == "on" else slot["off_from"]
    window_to = slot["on_to"] if side == "on" else slot["off_to"]
    side_label = "上班" if side == "on" else "下班"
    window_text = f"{side_label}打卡时间 {window_from}–{window_to}"
    state = _window_state(now_hm, window_from, window_to)
    action = {
        "slot_id": slot["id"],
        "punch_type": punch_type,
        "update": False,
        "enabled": False,
        "label": side_label,
        "reason": window_text,
    }
    if not is_today:
        action["label"] = "已打卡" if punched else "—"
        action["reason"] = "过去的日期只能查看"
        return action
    if punched:
        action["label"] = "已打卡"
        return action
    if side == "off" and not slot.get("clock_in_at"):
        action["label"] = "先上班"
        action["reason"] = f"请先完成{slot['label']}上班打卡"
        return action
    if state == "open":
        action["enabled"] = True
        action["label"] = f"{side_label}打卡"
        return action
    if state == "early":
        action["label"] = f"{window_from}后"
        return action
    action["label"] = "已过时间"
    return action


def _decorate_slots(slots: list[dict], punches: list[AttendancePunch], now_hm: str, is_today: bool) -> list[dict]:
    decorated = []
    for slot in _window_bounds(slots):
        decorated.append({
            **slot,
            "on_action": _side_action(slot, "on", now_hm, is_today),
            "off_action": _side_action(slot, "off", now_hm, is_today),
        })
    return decorated


def _schedule_slots(rules: dict, work_date: date) -> list[dict]:
    from app.services.attendance_rules import (
        apply_designated_rest_to_slots,
        is_base_rest_day,
        merge_attendance_rules,
    )

    cfg = merge_attendance_rules(rules)
    if is_base_rest_day(work_date, cfg):
        return []
    slots: list[dict] = []
    periods = cfg.get("work_periods") or []
    for index, period in enumerate(periods):
        total = len(periods)
        if total == 1:
            label = "上下班"
        elif total == 2:
            label = "上午" if index == 0 else "下午"
        else:
            label = ""
        slots.append({
            "id": f"work:{index}",
            "kind": "work",
            "label": label,
            "start": period["start"],
            "end": period["end"],
        })
    overtimes = cfg.get("overtime_periods") or []
    for index, period in enumerate(overtimes):
        slots.append({
            "id": f"overtime:{index}",
            "kind": "overtime",
            "label": "加班" if len(overtimes) == 1 else f"加班{index + 1}",
            "start": period["start"],
            "end": period["end"],
        })
    return apply_designated_rest_to_slots(work_date, slots, cfg.get("designated_rest_ranges"))


def _slot_id_of(punch: AttendancePunch) -> str:
    return punch.schedule_id or "work:0"


def _hm_utc(work_date: date, value: str) -> datetime | None:
    text = str(value or "").strip()
    if ":" not in text:
        return None
    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return datetime.combine(work_date, time(hour, minute)) - LOCAL_OFFSET


def _pair(rows: list) -> tuple:
    """一段内最早上班、最晚下班，以及这一段的分钟数。"""
    ons = [row for row in rows if getattr(row, "punch_type", None) == "on_duty"]
    offs = [row for row in rows if getattr(row, "punch_type", None) == "off_duty"]
    clock_in = min(ons, key=lambda row: row.check_time) if ons else None
    clock_out = max(offs, key=lambda row: row.check_time) if offs else None
    minutes = 0
    if clock_in and clock_out and clock_out.check_time > clock_in.check_time:
        minutes = int((clock_out.check_time - clock_in.check_time).total_seconds() // 60)
    return clock_in, clock_out, minutes


def _segment_payload(label: str, start: str, end: str, clock_in, clock_out, minutes: int) -> dict:
    return {
        "label": label,
        "start": start,
        "end": end,
        "clock_in_at": _local_text(clock_in.check_time) if clock_in else None,
        "clock_out_at": _local_text(clock_out.check_time) if clock_out else None,
        "minutes": minutes,
    }


def summarize_attendance(rules: dict | None, work_date: date, punches: list) -> dict:
    """按班次段合计出勤，并对照作息判断缺卡、迟到、早退。

    正班分钟是各正班段「上班到下班」之和，加班段单独累计，中间空档不计入。
    正班段缺任一侧记缺卡；加班段只有打过卡才要求成对。
    迟到、早退按正班段起止时间，超出宽限才计入。
    """
    from app.services.attendance_rules import merge_attendance_rules

    cfg = merge_attendance_rules(rules)
    slots = _schedule_slots(cfg, work_date)
    grouped: dict[str, list] = {}
    for punch in punches:
        grouped.setdefault(_slot_id_of(punch), []).append(punch)
    grace = int((cfg.get("late_early_deduction") or {}).get("grace_minutes") or 0)
    segments: list[dict] = []
    work_total = 0
    overtime_total = 0
    missing = False
    late_minutes = 0
    early_minutes = 0
    known: set[str] = set()
    for slot in slots:
        known.add(slot["id"])
        rows = grouped.get(slot["id"], [])
        clock_in, clock_out, minutes = _pair(rows)
        if slot["kind"] == "overtime":
            overtime_total += minutes
        else:
            work_total += minutes
        required = slot["kind"] == "work" or bool(rows)
        if required and (clock_in is None or clock_out is None):
            missing = True
        if slot["kind"] == "work" and clock_in is not None:
            start_at = _hm_utc(work_date, slot["start"])
            if start_at and clock_in.check_time > start_at:
                raw = int((clock_in.check_time - start_at).total_seconds() // 60)
                late_minutes += max(0, raw - grace)
        if slot["kind"] == "work" and clock_out is not None:
            end_at = _hm_utc(work_date, slot["end"])
            if end_at and clock_out.check_time < end_at:
                raw = int((end_at - clock_out.check_time).total_seconds() // 60)
                early_minutes += max(0, raw - grace)
        if rows or slot["kind"] == "work":
            segments.append(
                _segment_payload(slot["label"], slot["start"], slot["end"], clock_in, clock_out, minutes)
            )
    for slot_id, rows in grouped.items():
        if slot_id in known or not rows:
            continue
        clock_in, clock_out, minutes = _pair(rows)
        if str(slot_id).startswith("overtime:"):
            overtime_total += minutes
        else:
            work_total += minutes
        if clock_in is None or clock_out is None:
            missing = True
        segments.append(_segment_payload(slot_id, "", "", clock_in, clock_out, minutes))
    if missing:
        status = "missing"
    elif late_minutes and early_minutes:
        status = "late_early"
    elif late_minutes:
        status = "late"
    elif early_minutes:
        status = "early"
    elif punches:
        status = "normal"
    else:
        status = "incomplete"
    earliest_in = None
    latest_out = None
    for punch in punches:
        if punch.punch_type == "on_duty" and (earliest_in is None or punch.check_time < earliest_in):
            earliest_in = punch.check_time
        if punch.punch_type == "off_duty" and (latest_out is None or punch.check_time > latest_out):
            latest_out = punch.check_time
    return {
        "work_minutes": work_total,
        "overtime_minutes": overtime_total,
        "status": status,
        "late_minutes": late_minutes,
        "early_minutes": early_minutes,
        "segments": segments,
        "clock_in_at": earliest_in,
        "clock_out_at": latest_out,
    }


def _punch_rows(db: Session, tenant_id: int, employee_id: int, work_date: date) -> list[AttendancePunch]:
    return list(
        db.scalars(
            select(AttendancePunch)
            .where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id == employee_id,
                AttendancePunch.work_date == work_date,
            )
            .order_by(AttendancePunch.check_time.asc())
        ).all()
    )


def _attach_slots(slots: list[dict], punches: list[AttendancePunch]) -> list[dict]:
    attached = []
    for slot in slots:
        matched = [punch for punch in punches if _slot_id_of(punch) == slot["id"]]
        clock_in = next((punch for punch in matched if punch.punch_type == "on_duty"), None)
        clock_outs = [punch for punch in matched if punch.punch_type == "off_duty"]
        clock_out = clock_outs[-1] if clock_outs else None
        attached.append({
            **slot,
            "clock_in_at": _local_text(clock_in.check_time) if clock_in else None,
            "clock_out_at": _local_text(clock_out.check_time) if clock_out else None,
        })
    return attached


def _next_action(slots: list[dict], punches: list[AttendancePunch], now_hm: str, is_today: bool) -> dict | None:
    if not is_today:
        return None
    decorated = slots if slots and "on_action" in slots[0] else _decorate_slots(slots, punches, now_hm, is_today)
    for slot in decorated:
        for action in (slot["on_action"], slot["off_action"]):
            if action.get("enabled"):
                label = f"{slot['label']}{action['label']}" if slot.get("label") else action["label"]
                return {
                    "update": False,
                    "slot_id": action["slot_id"],
                    "punch_type": action["punch_type"],
                    "label": label,
                }
    return None


def _day_status(slots: list[dict], punches: list[AttendancePunch], work_date: date, today: date) -> str:
    required = [slot for slot in slots if slot["kind"] == "work"]
    started_overtime = [
        slot for slot in slots
        if slot["kind"] == "overtime" and (slot.get("clock_in_at") or slot.get("clock_out_at"))
    ]

    def complete(slot: dict) -> bool:
        return bool(slot.get("clock_in_at") and slot.get("clock_out_at"))

    if not required and not punches:
        return "rest"
    pending = [slot for slot in required + started_overtime if not complete(slot)]
    if required and not pending and all(complete(slot) for slot in started_overtime):
        return "done"
    if punches:
        return "partial"
    if work_date < today and required:
        return "missing"
    return "open"


def _compose_day(
    db: Session,
    tenant_id: int,
    employee: Employee,
    work_date: date,
    *,
    rules: dict | None = None,
    punches: list[AttendancePunch] | None = None,
    site: dict | None = None,
) -> dict:
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    today = _local_date()
    rules = rules if rules is not None else get_attendance_rules_by_tenant_id(db, tenant_id)
    punches = punches if punches is not None else _punch_rows(db, tenant_id, employee.id, work_date)
    site = site if site is not None else _clock_site(db, tenant_id)
    now_hm = (_now_utc() + LOCAL_OFFSET).strftime("%H:%M")
    is_today = work_date == today
    slots = _decorate_slots(_attach_slots(_schedule_slots(rules, work_date), punches), punches, now_hm, is_today)
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == employee.id,
            AttendanceDay.work_date == work_date,
        )
    )
    status = _day_status(slots, punches, work_date, today)
    next_action = _next_action(slots, punches, now_hm, is_today)
    return {
        "eligible": True,
        "employee_id": employee.id,
        "employee_name": employee.name,
        "work_date": work_date.isoformat(),
        "is_today": is_today,
        "is_rest": status == "rest",
        "clock_in_at": _local_text(day.clock_in_at) if day else None,
        "clock_out_at": _local_text(day.clock_out_at) if day else None,
        "work_minutes": int(day.work_minutes or 0) if day else 0,
        "status": day.status if day and day.status != "not_clocked" else status,
        "day_status": status,
        "next_punch_type": next_action["punch_type"] if next_action else None,
        "next_action": next_action,
        "update_action": None,
        "slots": slots,
        "clock_site": site,
    }


def get_today(db: Session, tenant_id: int, employee_id: int) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    return _compose_day(db, tenant_id, employee, _local_date())


def get_day(db: Session, tenant_id: int, employee_id: int, work_date: date) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    return _compose_day(db, tenant_id, employee, work_date)


def get_calendar(db: Session, tenant_id: int, employee_id: int, month: str) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    try:
        year_text, month_text = str(month).split("-")
        year, month_number = int(year_text), int(month_text)
        if not 1 <= month_number <= 12:
            raise ValueError
    except ValueError:
        raise AttendanceError("invalid_month", "月份格式应为 YYYY-MM")
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    last_day = calendar.monthrange(year, month_number)[1]
    start = date(year, month_number, 1)
    end = date(year, month_number, last_day)
    punches = list(
        db.scalars(
            select(AttendancePunch).where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id == employee_id,
                AttendancePunch.work_date >= start,
                AttendancePunch.work_date <= end,
            )
        ).all()
    )
    grouped: dict[date, list[AttendancePunch]] = {}
    for punch in punches:
        grouped.setdefault(punch.work_date, []).append(punch)
    today = _local_date()
    days = []
    for day_number in range(1, last_day + 1):
        current = date(year, month_number, day_number)
        day_punches = grouped.get(current, [])
        slots = _attach_slots(_schedule_slots(rules, current), day_punches)
        days.append({
            "date": current.isoformat(),
            "day": day_number,
            "status": _day_status(slots, day_punches, current, today),
            "is_today": current == today,
        })
    return {"month": f"{year:04d}-{month_number:02d}", "today": today.isoformat(), "days": days}


def _rebuild_day(db: Session, tenant_id: int, employee_id: int, work_date: date) -> AttendanceDay:
    punches = db.scalars(
        select(AttendancePunch)
        .where(
            AttendancePunch.tenant_id == tenant_id,
            AttendancePunch.employee_id == employee_id,
            AttendancePunch.work_date == work_date,
        )
        .order_by(AttendancePunch.check_time.asc())
    ).all()
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    summary = summarize_attendance(get_attendance_rules_by_tenant_id(db, tenant_id), work_date, punches)
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date == work_date,
        )
    )
    if not day:
        day = AttendanceDay(tenant_id=tenant_id, employee_id=employee_id, work_date=work_date)
        db.add(day)
    day.clock_in_at = summary["clock_in_at"]
    day.clock_out_at = summary["clock_out_at"]
    day.work_minutes = summary["work_minutes"]
    day.overtime_minutes = int(summary.get("overtime_minutes") or 0)
    day.status = summary["status"]
    day.late_minutes = summary["late_minutes"]
    day.early_leave_minutes = summary["early_minutes"]
    day.source_provider = punches[-1].source_provider if punches else "local"
    day.raw_count = len(punches)
    day.last_sync_at = _now_utc()
    db.flush()
    return day


def clock(
    db: Session,
    tenant_id: int,
    employee_id: int,
    punch_type: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    slot_id: str | None = None,
    update: bool = False,
) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    if punch_type not in PUNCH_TYPES:
        raise AttendanceError("invalid_punch_type", "打卡类型无效")
    site = _clock_site(db, tenant_id)
    lat, lng = _require_inside(site, latitude, longitude)
    now = _now_utc()
    today = _local_date(now)
    if update:
        raise AttendanceError("update_disabled", "打卡记录不能修改")
    detail = _compose_day(db, tenant_id, employee, today, site=site)
    punches = _punch_rows(db, tenant_id, employee_id, today)
    action = detail.get("next_action") or {}
    target_slot = slot_id or action.get("slot_id")
    target_type = punch_type if slot_id else (action.get("punch_type") or punch_type)
    if not target_slot:
        raise AttendanceError("already_clocked", "今天的班次都已打卡")
    slot = next((item for item in detail["slots"] if item["id"] == target_slot), None)
    if slot is None:
        raise AttendanceError("invalid_slot", "没有这个打卡时段")
    side_action = slot["on_action"] if target_type == "on_duty" else slot["off_action"]
    if not side_action.get("enabled"):
        raise AttendanceError("outside_window", side_action.get("reason") or "不在该时段的打卡时间")
    matched = [punch for punch in punches if _slot_id_of(punch) == target_slot and punch.punch_type == target_type]
    if matched:
        side = "上班" if target_type == "on_duty" else "下班"
        name = f"{slot['label']}" if slot.get("label") else ""
        raise AttendanceError("already_clocked", f"{name}已完成{side}打卡")
    if target_type == "off_duty" and not slot.get("clock_in_at"):
        raise AttendanceError("clock_in_required", f"请先完成{slot['label']}上班打卡")

    db.add(
        AttendancePunch(
            tenant_id=tenant_id,
            employee_id=employee_id,
            work_date=today,
            punch_type=target_type,
            check_time=now,
            scheduled_time=None,
            time_result="normal",
            location_result="inside",
            source_provider="local",
            external_corp_id="",
            external_user_id=str(employee_id),
            external_record_key=f"local:{employee_id}:{today.isoformat()}:{target_slot}:{target_type}",
            schedule_id=target_slot,
            source_type="mobile_web",
            location_method="gps",
            latitude=Decimal(str(round(lat, 6))),
            longitude=Decimal(str(round(lng, 6))),
            raw_payload={
                "source": "local",
                "punch_type": target_type,
                "slot_id": target_slot,
                "latitude": lat,
                "longitude": lng,
            },
        )
    )
    db.flush()
    _rebuild_day(db, tenant_id, employee_id, today)
    db.commit()
    return _compose_day(db, tenant_id, employee, today, site=site)


def list_records(
    db: Session,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page, page_size, offset = normalize_page(page, page_size, max_size=500)
    q = (
        select(AttendanceDay, Employee, Department)
        .join(Employee, Employee.id == AttendanceDay.employee_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(
            AttendanceDay.tenant_id == tenant_id,
            Employee.tenant_id == tenant_id,
        )
    )
    if employee_id:
        q = q.where(AttendanceDay.employee_id == employee_id)
    if department_id:
        q = q.where(Employee.department_id == department_id)
    if date_from:
        q = q.where(AttendanceDay.work_date >= date_from)
    if date_to:
        q = q.where(AttendanceDay.work_date <= date_to)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.execute(
        q.order_by(AttendanceDay.work_date.desc(), AttendanceDay.id.desc()).offset(offset).limit(page_size)
    ).all()
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    bucket: dict[tuple[int, date], list[AttendancePunch]] = {}
    if rows:
        employee_ids = {employee.id for _, employee, _ in rows}
        work_dates = {day.work_date for day, _, _ in rows}
        punch_rows = db.scalars(
            select(AttendancePunch).where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id.in_(employee_ids),
                AttendancePunch.work_date.in_(work_dates),
            )
        ).all()
        for punch in punch_rows:
            bucket.setdefault((punch.employee_id, punch.work_date), []).append(punch)
    items = []
    for day, employee, department in rows:
        punches = bucket.get((employee.id, day.work_date), [])
        if punches:
            summary = summarize_attendance(rules, day.work_date, punches)
            work_minutes = summary["work_minutes"]
            status = summary["status"]
            segments = summary["segments"]
        else:
            work_minutes = int(day.work_minutes or 0)
            status = day.status
            segments = []
        items.append(
            {
                "id": day.id,
                "work_date": day.work_date.isoformat(),
                "department_name": department.name if department else None,
                "employee_id": employee.id,
                "employee_name": employee.name,
                "work_minutes": work_minutes,
                "segments": segments,
                "status": status,
                "source_provider": day.source_provider,
            }
        )
    return page_payload(items, int(total), page, page_size)


EFFICIENCY_DECIMALS = 3


def _efficiency_per_hour(qualified_qty: Decimal | float | int, work_minutes: int) -> float | None:
    """出勤工时>0 时返回数量/小时；否则无法计算。"""
    if work_minutes <= 0:
        return None
    hours = work_minutes / 60.0
    if hours <= 0:
        return None
    return round(float(qualified_qty or 0) / hours, EFFICIENCY_DECIMALS)


def _bill_qty(log: WorkLog) -> Decimal:
    if log.report_type == ReportType.rework:
        return Decimal(str(log.rework_qty or 0))
    return Decimal(str(log.qualified_qty or 0))


def _apply_rowspans(items: list[dict], group_key: str, span_key: str, index_key: str) -> None:
    """为连续相同 group_key 的行写入 rowspan / 行内序号。"""
    i = 0
    n = len(items)
    while i < n:
        key = items[i][group_key]
        j = i + 1
        while j < n and items[j][group_key] == key:
            j += 1
        span = j - i
        for offset in range(span):
            row = items[i + offset]
            row[span_key] = span if offset == 0 else 0
            row[index_key] = offset
        i = j


def list_daily_stats(
    db: Session,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    department_id: int | None = None,
    work_date: date | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict:
    """报工统计：按报工考勤日期单日查询。部门→工序→员工→工厂型号。

    仅含有效报工；出勤计该日已打卡的合计工时（含迟到、早退、部分缺卡）。
    - 个人效率 = 该工序下个人合计数量 ÷ 个人出勤小时
    - 单款效率 = 该型号数量 ÷ 个人出勤小时
    - 单款平均效率 = 该工序该型号合计数量 ÷ 做过该型号的员工出勤人时合计
    - 单人平均效率 = 工序合计数量 ÷ 工序内出勤人时合计（双/人/小时）
    - 工序多人效率 = 单人平均效率 × 工序人数（双/{N}人/小时）
    """
    day = work_date or _local_date()
    date_from = day
    date_to = day

    allowed_ids: set[int] | None = None
    if employee_id or department_id:
        emp_q = select(Employee.id).where(Employee.tenant_id == tenant_id)
        if employee_id:
            emp_q = emp_q.where(Employee.id == employee_id)
        if department_id:
            emp_q = emp_q.where(Employee.department_id == department_id)
        allowed_ids = set(db.scalars(emp_q).all())
        if not allowed_ids:
            payload = page_payload([], 0, page, page_size)
            payload["summary"] = {
                "work_date": day.isoformat(),
                "work_minutes_total": 0,
                "qty_total": 0.0,
                "wage_total": 0.0,
                "loss_total": 0.0,
            }
            return payload

    utc_from = datetime.combine(date_from, datetime.min.time()) - LOCAL_OFFSET
    utc_to_exclusive = datetime.combine(date_to, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)
    wl_q = select(WorkLog).where(
        WorkLog.tenant_id == tenant_id,
        WorkLog.status == WorkLogStatus.valid,
        WorkLog.created_at >= utc_from,
        WorkLog.created_at < utc_to_exclusive,
    )
    if allowed_ids is not None:
        wl_q = wl_q.where(WorkLog.worker_id.in_(allowed_ids))
    work_logs = db.scalars(wl_q).all()
    if not work_logs:
        payload = page_payload([], 0, page, page_size)
        payload["summary"] = {
            "work_date": day.isoformat(),
            "work_minutes_total": 0,
            "qty_total": 0.0,
            "wage_total": 0.0,
            "loss_total": 0.0,
        }
        return payload

    worker_ids = {log.worker_id for log in work_logs}
    process_ids = {log.process_id for log in work_logs}
    product_ids = {log.own_product_id for log in work_logs}
    color_ids = {log.color_id for log in work_logs if log.color_id}

    employees = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(Employee.tenant_id == tenant_id, Employee.id.in_(worker_ids))
        ).all()
    }
    dept_ids = {e.department_id for e in employees.values() if e.department_id}
    departments = {
        d.id: d
        for d in db.scalars(select(Department).where(Department.id.in_(dept_ids))).all()
    } if dept_ids else {}
    processes = {
        p.id: p
        for p in db.scalars(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == tenant_id,
                ProcessDefinition.id.in_(process_ids),
            )
        ).all()
    }
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.id.in_(product_ids))
        ).all()
    }
    colors = {
        c.id: c
        for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()
    } if color_ids else {}

    att_q = select(AttendanceDay).where(
        AttendanceDay.tenant_id == tenant_id,
        AttendanceDay.employee_id.in_(worker_ids),
        AttendanceDay.work_date >= date_from,
        AttendanceDay.work_date <= date_to,
        AttendanceDay.work_minutes > 0,
    )
    attendance_minutes: dict[int, int] = {}
    for att_day in db.scalars(att_q).all():
        attendance_minutes[att_day.employee_id] = attendance_minutes.get(att_day.employee_id, 0) + int(
            att_day.work_minutes or 0
        )

    # leaf key -> aggregate
    leaves: dict[tuple, dict] = {}
    for log in work_logs:
        emp = employees.get(log.worker_id)
        if not emp:
            continue
        process = processes.get(log.process_id)
        product = products.get(log.own_product_id)
        color = colors.get(log.color_id) if log.color_id else None
        price = work_log_unit_price(db, tenant_id, log).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        qty = _bill_qty(log)
        loss = work_log_loss_deduction(log)
        wage = (price * qty - loss).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        dept_id = emp.department_id or 0
        dept_name = departments[dept_id].name if dept_id and dept_id in departments else "未分配部门"
        process_id = log.process_id
        process_name = process.name if process else f"工序#{process_id}"
        process_sort = int(process.sort_order) if process and process.sort_order is not None else 0
        product_id = log.own_product_id
        product_code = product.product_code if product else f"#{product_id}"
        color_id = log.color_id or 0
        color_name = color.name if color else None
        key = (dept_id, process_id, emp.id, product_id, color_id, str(price))
        row = leaves.get(key)
        if not row:
            row = {
                "department_id": dept_id,
                "department_name": dept_name,
                "process_id": process_id,
                "process_name": process_name,
                "process_sort": process_sort,
                "employee_id": emp.id,
                "employee_name": emp.name,
                "product_id": product_id,
                "product_code": product_code,
                "color_id": color_id or None,
                "color_name": color_name,
                "unit_price": float(price),
                "qty": Decimal("0"),
                "wage": Decimal("0"),
                "loss": Decimal("0"),
            }
            leaves[key] = row
        row["qty"] += qty
        row["wage"] += wage
        row["loss"] += loss

    # employee totals within process; process totals; model totals within process
    emp_process_qty: dict[tuple[int, int], Decimal] = {}
    process_qty: dict[int, Decimal] = {}
    process_emp_ids: dict[int, set[int]] = {}
    process_minutes: dict[int, int] = {}
    process_product_qty: dict[tuple[int, int], Decimal] = {}
    process_product_emp_ids: dict[tuple[int, int], set[int]] = {}

    for row in leaves.values():
        eid = row["employee_id"]
        pid = row["process_id"]
        product_id = row["product_id"]
        emp_process_qty[(pid, eid)] = emp_process_qty.get((pid, eid), Decimal("0")) + row["qty"]
        process_qty[pid] = process_qty.get(pid, Decimal("0")) + row["qty"]
        process_emp_ids.setdefault(pid, set()).add(eid)
        pp_key = (pid, product_id)
        process_product_qty[pp_key] = process_product_qty.get(pp_key, Decimal("0")) + row["qty"]
        process_product_emp_ids.setdefault(pp_key, set()).add(eid)

    for pid, eids in process_emp_ids.items():
        process_minutes[pid] = sum(attendance_minutes.get(eid, 0) for eid in eids)

    process_product_minutes: dict[tuple[int, int], int] = {
        key: sum(attendance_minutes.get(eid, 0) for eid in eids)
        for key, eids in process_product_emp_ids.items()
    }

    items: list[dict] = []
    for row in sorted(
        leaves.values(),
        key=lambda r: (
            r["department_name"],
            r["process_sort"],
            r["process_name"],
            r["employee_name"],
            r["product_code"],
            r["color_name"] or "",
        ),
    ):
        eid = row["employee_id"]
        pid = row["process_id"]
        product_id = row["product_id"]
        minutes = int(attendance_minutes.get(eid, 0))
        emp_qty = emp_process_qty[(pid, eid)]
        p_qty = process_qty[pid]
        p_minutes = int(process_minutes.get(pid, 0))
        n_people = len(process_emp_ids.get(pid, set())) or 1
        pp_key = (pid, product_id)
        model_avg_eff = _efficiency_per_hour(
            process_product_qty[pp_key],
            int(process_product_minutes.get(pp_key, 0)),
        )
        model_eff = _efficiency_per_hour(row["qty"], minutes)
        personal_eff = _efficiency_per_hour(emp_qty, minutes)
        avg_eff = _efficiency_per_hour(p_qty, p_minutes)
        process_eff = round(avg_eff * n_people, EFFICIENCY_DECIMALS) if avg_eff is not None else None
        items.append(
            {
                "department_id": row["department_id"],
                "department_name": row["department_name"],
                "process_id": pid,
                "process_name": row["process_name"],
                "employee_id": eid,
                "employee_name": row["employee_name"],
                "work_minutes": minutes,
                "product_code": row["product_code"],
                "color_name": row["color_name"],
                "unit_price": row["unit_price"],
                "qty": float(row["qty"]),
                "wage": float(row["wage"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "loss": float(row["loss"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "personal_efficiency": personal_eff,
                "model_efficiency": model_eff,
                "model_avg_efficiency": model_avg_eff,
                "avg_efficiency": avg_eff,
                "process_efficiency": process_eff,
                "process_worker_count": n_people,
                "_dept_key": f"d:{row['department_id']}",
                "_process_key": f"d:{row['department_id']}|p:{pid}",
                "_emp_key": f"d:{row['department_id']}|p:{pid}|e:{eid}",
            }
        )

    _apply_rowspans(items, "_dept_key", "_dept_span", "_dept_index")
    _apply_rowspans(items, "_process_key", "_process_span", "_process_index")
    _apply_rowspans(items, "_emp_key", "_emp_span", "_emp_index")

    page, page_size, offset = normalize_page(page, page_size, max_size=2000)
    total = len(items)
    page_items = items[offset : offset + page_size]
    # 分页可能截断合并组：当前页内重算 span
    _apply_rowspans(page_items, "_dept_key", "_dept_span", "_dept_index")
    _apply_rowspans(page_items, "_process_key", "_process_span", "_process_index")
    _apply_rowspans(page_items, "_emp_key", "_emp_span", "_emp_index")

    work_minutes_total = sum(attendance_minutes.get(eid, 0) for eid in worker_ids)
    qty_total = sum((Decimal(str(r["qty"])) for r in leaves.values()), Decimal("0"))
    wage_total = sum((r["wage"] for r in leaves.values()), Decimal("0"))
    loss_total = sum((r["loss"] for r in leaves.values()), Decimal("0"))

    payload = page_payload(page_items, total, page, page_size)
    payload["summary"] = {
        "work_date": day.isoformat(),
        "work_minutes_total": work_minutes_total,
        "qty_total": float(qty_total),
        "wage_total": float(wage_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "loss_total": float(loss_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }
    return payload
