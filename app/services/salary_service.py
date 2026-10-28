from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, extract, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AttendanceDay,
    Color,
    CutOutput,
    CutOutputContribution,
    CutOutputStatus,
    DefectDisposition,
    DefectEvent,
    DefectResponsibility,
    DefectEventStatus,
    Department,
    ExecutionHeader,
    Order,
    OrderItem,
    OwnProduct,
    OwnProductCommission,
    OwnProductMgmtCommission,
    OwnProductLabor,
    ProcessDefinition,
    ReportType,
    SalaryAcknowledgement,
    SalaryModel,
    SalaryMonthLock,
    SalesOrderLine,
    SalesOrderLineItem,
    Shipment,
    ShipmentStatus,
    Size,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Employee,
)
from app.services.order_service import get_labor_unit_price


def _work_log_ref_no(db: Session, log: WorkLog) -> str | None:
    if log.order_id:
        order = db.get(Order, log.order_id)
        if order:
            return order.order_no
    if log.header_id:
        header = db.get(ExecutionHeader, log.header_id)
        if header:
            return header.header_no
    return None


def year_month_of(dt: datetime | None) -> str:
    d = dt or datetime.utcnow()
    return f"{d.year:04d}-{d.month:02d}"


# 结算窗口按东八区自然日。报废确认、裁断确认用 UTC 写入，窗口要减 8 小时。
# 报工 created_at 用数据库 NOW()，时钟跟会话时区走，过滤时再对齐。
_LOCAL_UTC_OFFSET = timedelta(hours=8)


def _parse_year_month(year_month: str) -> tuple[int, int]:
    ym = (year_month or "").strip()
    if len(ym) != 7 or ym[4] != "-":
        raise ValueError("月份格式应为 YYYY-MM")
    year_s, month_s = ym.split("-")
    if not (year_s.isdigit() and month_s.isdigit()):
        raise ValueError("月份格式应为 YYYY-MM")
    year, month = int(year_s), int(month_s)
    if not (1 <= month <= 12):
        raise ValueError("月份格式应为 YYYY-MM")
    return year, month


def _local_today() -> date:
    return (datetime.utcnow() + _LOCAL_UTC_OFFSET).date()


def _local_day_start_utc(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time()) - _LOCAL_UTC_OFFSET


def _work_log_clock_offset(db: Session) -> timedelta:
    """报工时间跟数据库 NOW() 同一时钟。NOW() 比 UTC 快多少，结算日边界就往后推多少。"""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "mysql":
        return timedelta(0)
    seconds = db.execute(text("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())")).scalar()
    return timedelta(seconds=int(seconds or 0))


def resolve_settle_window(
    year_month: str,
    settle_through: date | str | None = None,
    settle_from: date | str | None = None,
) -> dict:
    """结算窗口：自然月内 settle_from～settle_through（含）；空则从 1 日到月底。"""
    year, month = _parse_year_month(year_month)
    last_day = monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)
    through: date | None = None
    if settle_through is not None and str(settle_through).strip():
        if isinstance(settle_through, date):
            through = settle_through
        else:
            through = date.fromisoformat(str(settle_through).strip()[:10])
        if through.year != year or through.month != month:
            raise ValueError(f"截止日期须落在 {year_month} 内")
        if through < month_start or through > month_end:
            raise ValueError(f"截止日期须落在 {year_month} 内")
    period_start = month_start
    if settle_from is not None and str(settle_from).strip():
        if isinstance(settle_from, date):
            start = settle_from
        else:
            start = date.fromisoformat(str(settle_from).strip()[:10])
        if start.year != year or start.month != month:
            raise ValueError(f"开始日期须落在 {year_month} 内")
        if start < month_start or start > month_end:
            raise ValueError(f"开始日期须落在 {year_month} 内")
        period_start = start
    period_end = through or month_end
    # 当月还没过完的日子不发工资、不算补贴。已过去的月份仍算到月底。
    today = _local_today()
    if month_start <= today <= month_end and period_end > today:
        period_end = today if today >= period_start else period_start - timedelta(days=1)
    days_in_month = last_day
    if period_start > period_end:
        period_days = 0
        utc_start = _local_day_start_utc(period_start)
        utc_end_exclusive = utc_start
    else:
        period_days = (period_end - period_start).days + 1
        utc_start = _local_day_start_utc(period_start)
        utc_end_exclusive = _local_day_start_utc(period_end + timedelta(days=1))
    proration = (Decimal(period_days) / Decimal(days_in_month)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return {
        "year_month": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "month_start": month_start,
        "month_end": month_end,
        "settle_through": through,
        "period_start": period_start,
        "period_end": period_end,
        "period_days": period_days,
        "days_in_month": days_in_month,
        "proration": proration,
        "is_partial": through is not None and through < month_end,
        "utc_start": utc_start,
        "utc_end_exclusive": utc_end_exclusive,
    }


def is_month_locked(db: Session, tenant_id: int, year_month: str) -> bool:
    row = db.scalar(
        select(SalaryMonthLock).where(
            SalaryMonthLock.tenant_id == tenant_id,
            SalaryMonthLock.year_month == year_month,
            SalaryMonthLock.is_locked.is_(True),
        )
    )
    return row is not None


def get_month_lock(db: Session, tenant_id: int, year_month: str) -> dict:
    row = db.scalar(
        select(SalaryMonthLock).where(
            SalaryMonthLock.tenant_id == tenant_id,
            SalaryMonthLock.year_month == year_month,
        )
    )
    if not row:
        return {
            "year_month": year_month,
            "is_locked": False,
            "settle_through": None,
            "locked_at": None,
            "note": None,
        }
    return {
        "year_month": row.year_month,
        "is_locked": bool(row.is_locked),
        "settle_through": row.settle_through.isoformat() if row.settle_through else None,
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
        "locked_by": row.locked_by,
        "note": row.note,
    }


def set_month_lock(
    db: Session,
    tenant_id: int,
    year_month: str,
    *,
    locked: bool,
    locked_by: int | None = None,
    note: str | None = None,
    settle_through: date | str | None = None,
) -> dict:
    ym = (year_month or "").strip()
    _parse_year_month(ym)
    row = db.scalar(
        select(SalaryMonthLock).where(
            SalaryMonthLock.tenant_id == tenant_id,
            SalaryMonthLock.year_month == ym,
        )
    )
    if not row:
        row = SalaryMonthLock(tenant_id=tenant_id, year_month=ym)
        db.add(row)
    from app.services import hr_service

    deduct_advances = bool(locked) and ym == hr_service.open_advance_month(db, tenant_id)
    row.is_locked = bool(locked)
    row.note = note
    if locked:
        window = resolve_settle_window(ym, settle_through)
        row.settle_through = window["settle_through"]
        row.locked_at = datetime.utcnow()
        row.locked_by = locked_by
        db.flush()
        if deduct_advances:
            hr_service.mark_advances_repaid_for_month(
                db, tenant_id, ym, through=window["period_end"]
            )
        overview = month_salary_all(db, tenant_id, ym, settle_through=window["settle_through"])
        from app.services import ledger_service

        ledger_service.post_salary_month(
            db,
            tenant_id,
            lock_id=row.id,
            year_month=ym,
            total_wage=overview.get("total_wage") or 0,
            settle_through=window["period_end"],
            worker_count=len(overview.get("items") or []),
        )
    else:
        row.settle_through = None
        row.locked_at = None
        row.locked_by = None
        # 解锁后原确认作废，需重新签字
        acks = db.scalars(
            select(SalaryAcknowledgement).where(
                SalaryAcknowledgement.tenant_id == tenant_id,
                SalaryAcknowledgement.year_month == ym,
            )
        ).all()
        for a in acks:
            db.delete(a)
        # 解锁后预支恢复为待扣回
        from app.models import SalaryAdvance

        for adv in db.scalars(
            select(SalaryAdvance).where(
                SalaryAdvance.tenant_id == tenant_id,
                SalaryAdvance.repay_year_month == ym,
                SalaryAdvance.status == "repaid",
            )
        ).all():
            adv.status = "open"
            adv.repay_year_month = None
        from app.services import ledger_service

        ledger_service.void_salary_month_entry(db, tenant_id, row.id)
    db.commit()
    return get_month_lock(db, tenant_id, ym)


def settle_month(
    db: Session,
    tenant_id: int,
    year_month: str,
    settle_through: date | str,
    *,
    settled_by: int | None = None,
) -> dict:
    """按所选日期结算。同一月份结算过后不能再结一次。"""
    ym = (year_month or "").strip()
    _parse_year_month(ym)
    if settle_through is None or not str(settle_through).strip():
        raise ValueError("请选择结算日期")
    window = resolve_settle_window(ym, settle_through)
    from app.services import hr_service

    deduct_advances = ym == hr_service.open_advance_month(db, tenant_id)
    row = db.scalar(
        select(SalaryMonthLock).where(
            SalaryMonthLock.tenant_id == tenant_id,
            SalaryMonthLock.year_month == ym,
        )
    )
    if row and (row.settle_through or row.is_locked):
        shown = row.settle_through.isoformat() if row.settle_through else ym
        raise ValueError(f"{ym} 已结算至 {shown}，不能再次结算")
    if not row:
        row = SalaryMonthLock(tenant_id=tenant_id, year_month=ym, is_locked=False)
        db.add(row)
    row.settle_through = window["period_end"]
    row.locked_at = datetime.utcnow()
    row.locked_by = settled_by
    db.flush()
    if deduct_advances:
        hr_service.mark_advances_repaid_for_month(
            db, tenant_id, ym, through=window["period_end"]
        )
    overview = month_salary_all(db, tenant_id, ym)
    from app.services import ledger_service

    ledger_service.post_salary_month(
        db,
        tenant_id,
        lock_id=row.id,
        year_month=ym,
        total_wage=overview.get("summary", {}).get("settled_wage") or overview.get("total_wage") or 0,
        settle_through=window["period_end"],
        worker_count=len(overview.get("items") or []),
    )
    db.commit()
    return get_month_lock(db, tenant_id, ym)


def get_acknowledgement(db: Session, tenant_id: int, worker_id: int, year_month: str):
    return db.scalar(
        select(SalaryAcknowledgement).where(
            SalaryAcknowledgement.tenant_id == tenant_id,
            SalaryAcknowledgement.worker_id == worker_id,
            SalaryAcknowledgement.year_month == year_month,
        )
    )


def acknowledge_salary(
    db: Session,
    tenant_id: int,
    worker_id: int,
    *,
    year_month: str,
    confirm_name: str,
    signature_data: str | None = None,
    note: str | None = None,
    source: str = "h5",
) -> dict:
    """员工对已锁定月结电子确认（手输姓名 + 可选签迹）。"""
    ym = (year_month or "").strip()
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id or not worker.is_active:
        raise ValueError("工人不存在或未启用")
    if not is_month_locked(db, tenant_id, ym):
        raise ValueError(f"{ym} 尚未月结锁定，暂不能确认")
    name = (confirm_name or "").strip()
    if not name:
        raise ValueError("请填写确认姓名")
    if name != (worker.name or "").strip():
        raise ValueError(f"确认姓名须与档案姓名一致（{worker.name}）")

    detail = month_salary(db, tenant_id, worker_id, ym)
    if detail.get("error"):
        raise ValueError(detail["error"])
    total = Decimal(str(detail.get("total_wage") or 0)).quantize(Decimal("0.01"))

    existing = get_acknowledgement(db, tenant_id, worker_id, ym)
    if existing:
        raise ValueError("本月工资已确认，无需重复签字")

    ack = SalaryAcknowledgement(
        tenant_id=tenant_id,
        worker_id=worker_id,
        year_month=ym,
        total_wage=total,
        confirm_name=name,
        signature_data=(signature_data or None),
        source=source or "h5",
        confirmed_at=datetime.utcnow(),
        note=(note or "").strip() or None,
    )
    db.add(ack)
    db.commit()
    db.refresh(ack)
    return {
        "id": ack.id,
        "worker_id": worker_id,
        "year_month": ym,
        "total_wage": float(total),
        "confirm_name": name,
        "confirmed_at": ack.confirmed_at.isoformat() if ack.confirmed_at else None,
        "message": f"已确认 {ym} 工资 ¥{total:.2f}",
    }


def export_bank_payroll_csv(
    db: Session,
    tenant_id: int,
    year_month: str | None = None,
    *,
    department_id: int | None = None,
) -> str:
    """银行代发通用模板：户名/账号/开户行/金额/备注。需已月结锁定。"""
    import csv
    import io

    overview = month_salary_all(db, tenant_id, year_month, department_id=department_id)
    ym = overview["year_month"]
    saved_through = (overview.get("lock") or {}).get("settle_through")
    if not overview.get("is_locked") and not saved_through:
        raise ValueError(f"{ym} 尚未结算，请选择日期结算后再导出银行代发")

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    from app.services import payroll_settings as payroll_settings_service

    payday = int(payroll_settings_service.get_payroll_by_tenant_id(db, tenant_id).get("payday") or 10)
    y, m = map(int, ym.split("-"))
    settle_through = overview.get("settle_through")
    if settle_through:
        bank_remark = f"{ym}工资(截至{settle_through[5:]})·{settle_through}发"
    else:
        if m == 12:
            pay_date_label = f"{y + 1}-01-{payday:02d}"
        else:
            pay_date_label = f"{y}-{m + 1:02d}-{payday:02d}"
        bank_remark = f"{ym}工资·{pay_date_label}发"

    writer.writerow(["收款户名", "银行卡号", "开户行", "金额", "备注", "手机号", "是否已确认"])
    missing_bank = 0
    for item in overview["items"]:
        w = db.get(Employee, item["worker_id"])
        if not w:
            continue
        amount = Decimal(str(item.get("total_wage") or 0)).quantize(Decimal("0.01"))
        if amount <= 0:
            continue
        account = (getattr(w, "bank_account", None) or "").strip()
        if not account:
            missing_bank += 1
        holder = (getattr(w, "bank_account_name", None) or "").strip() or w.name
        bank = (getattr(w, "bank_name", None) or "").strip()
        ack = get_acknowledgement(db, tenant_id, w.id, ym)
        writer.writerow(
            [
                holder,
                account,
                bank,
                f"{amount:.2f}",
                bank_remark,
                w.mobile or "",
                "是" if ack else "否",
            ]
        )
    if missing_bank:
        writer.writerow([])
        writer.writerow([f"# 提示：有 {missing_bank} 人未填银行卡号，请补全后再导入网银"])
    return buf.getvalue()


def assert_month_unlocked(db: Session, tenant_id: int, year_month: str, *, action: str = "操作") -> None:
    if is_month_locked(db, tenant_id, year_month):
        from app.services.report_service import ReportError

        raise ReportError("month_locked", f"{year_month} 已月结锁定，不能{action}")


def work_log_unit_price(db: Session, tenant_id: int, log: WorkLog) -> Decimal:
    """优先报工锁价；旧数据无快照时回落产品现价。"""
    if log.unit_price is not None:
        return Decimal(log.unit_price)
    price = get_labor_unit_price(db, tenant_id, log.own_product_id, log.process_id)
    return Decimal(price or 0)


def work_log_loss_deduction(log: WorkLog) -> Decimal:
    """工资扣减 = 损失金额 × 所占百分比。"""
    if Decimal(getattr(log, "defect_qty", 0) or 0) <= 0:
        return Decimal("0")
    percent = Decimal(getattr(log, "loss_borne_percent", 0) or 0)
    amount = Decimal(getattr(log, "loss_amount", 0) or 0)
    return (amount * percent / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def lifetime_wage_and_loss(db: Session, tenant_id: int, employee_ids: list[int]) -> dict[int, dict]:
    """员工入职以来的计件工资与本人承担的损失。

    工资：有效报工计件（不含裁断筐流水，改由已确认裁断贡献计入）之和，扣损失前。
    损失：报工损失扣减 + 已确认报废中该员工的分摊。工资为 0 时比例为空。
    """
    ids = [int(i) for i in employee_ids if i]
    blank = {
        "cumulative_wage": Decimal("0.00"),
        "cumulative_loss": Decimal("0.00"),
        "loss_wage_ratio": None,
    }
    out = {i: dict(blank) for i in ids}
    if not ids:
        return out

    from app.services import reporting_settings

    rework_pays = bool(reporting_settings.get_reporting_by_tenant_id(db, tenant_id).get("rework_pays", True))
    fallback_price = (
        select(OwnProductLabor.unit_price)
        .where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id == WorkLog.own_product_id,
            OwnProductLabor.process_id == WorkLog.process_id,
        )
        .limit(1)
        .scalar_subquery()
    )
    effective_price = func.coalesce(WorkLog.unit_price, fallback_price, 0)
    bill_qty = case(
        (WorkLog.report_type == ReportType.rework, WorkLog.rework_qty if rework_pays else 0),
        else_=WorkLog.qualified_qty,
    )
    wage_expr = effective_price * func.coalesce(bill_qty, 0)
    loss_expr = case(
        (
            WorkLog.defect_qty > 0,
            func.round(
                func.coalesce(WorkLog.loss_amount, 0)
                * func.coalesce(WorkLog.loss_borne_percent, 0)
                / 100,
                2,
            ),
        ),
        else_=0,
    )
    wages: dict[int, Decimal] = {i: Decimal("0") for i in ids}
    losses: dict[int, Decimal] = {i: Decimal("0") for i in ids}
    for worker_id, wage, loss in db.execute(
        select(
            WorkLog.worker_id,
            func.coalesce(func.sum(wage_expr), 0),
            func.coalesce(func.sum(loss_expr), 0),
        )
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.worker_id.in_(ids),
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.source != WorkLogSource.cut_basket,
        )
        .group_by(WorkLog.worker_id)
    ).all():
        wages[int(worker_id)] += Decimal(str(wage or 0))
        losses[int(worker_id)] += Decimal(str(loss or 0))

    for worker_id, wage in db.execute(
        select(
            CutOutputContribution.worker_id,
            func.coalesce(func.sum(CutOutputContribution.wage), 0),
        )
        .join(CutOutput, CutOutput.id == CutOutputContribution.cut_output_id)
        .where(
            CutOutputContribution.tenant_id == tenant_id,
            CutOutputContribution.worker_id.in_(ids),
            CutOutput.status == CutOutputStatus.confirmed,
        )
        .group_by(CutOutputContribution.worker_id)
    ).all():
        wages[int(worker_id)] += Decimal(str(wage or 0))

    for worker_id, loss in db.execute(
        select(
            DefectResponsibility.worker_id,
            func.coalesce(
                func.sum(
                    case(
                        (
                            DefectResponsibility.share_amount.is_not(None),
                            DefectResponsibility.share_amount,
                        ),
                        else_=DefectEvent.loss_amount * DefectResponsibility.share_percent / 100,
                    )
                ),
                0,
            ),
        )
        .join(DefectEvent, DefectEvent.id == DefectResponsibility.defect_event_id)
        .where(
            DefectResponsibility.tenant_id == tenant_id,
            DefectResponsibility.worker_id.in_(ids),
            DefectEvent.status == DefectEventStatus.closed,
            DefectEvent.disposition == DefectDisposition.scrap,
            DefectEvent.wage_deduction_from_event.is_(True),
        )
        .group_by(DefectResponsibility.worker_id)
    ).all():
        losses[int(worker_id)] += Decimal(str(loss or 0))

    has_share = (
        select(DefectResponsibility.id)
        .where(DefectResponsibility.defect_event_id == DefectEvent.id)
        .exists()
    )
    for worker_id, loss in db.execute(
        select(
            DefectEvent.responsible_worker_id,
            func.coalesce(func.sum(DefectEvent.loss_amount), 0),
        )
        .where(
            DefectEvent.tenant_id == tenant_id,
            DefectEvent.responsible_worker_id.in_(ids),
            DefectEvent.status == DefectEventStatus.closed,
            DefectEvent.disposition == DefectDisposition.scrap,
            DefectEvent.wage_deduction_from_event.is_(True),
            ~has_share,
        )
        .group_by(DefectEvent.responsible_worker_id)
    ).all():
        losses[int(worker_id)] += Decimal(str(loss or 0))

    for employee_id in ids:
        wage = _money(wages[employee_id])
        loss = _money(losses[employee_id])
        ratio = None
        if wage > 0:
            ratio = (loss / wage * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out[employee_id] = {
            "cumulative_wage": wage,
            "cumulative_loss": loss,
            "loss_wage_ratio": ratio,
        }
    return out


def _employed_range(worker: Employee, period_start: date, period_end: date) -> tuple[date, date] | None:
    """结算窗口再收口到入职日和离职日。入职前、离职后不发固定工资，也不计请假。"""
    start, end = period_start, period_end
    hire = getattr(worker, "hire_date", None)
    left = getattr(worker, "leave_date", None)
    if hire is not None and hire > start:
        start = hire
    if left is not None and left < end:
        end = left
    if start > end:
        return None
    return start, end


def _calendar_salary_amount(base: Decimal, days_in_month: int, days: Decimal) -> Decimal:
    """月金额 ÷ 当月天数 × 出勤天数，最后四舍五入到元。

    不先把日工资四舍五入，避免 日工资 × 天数 和月金额对不上。出勤满整月时直接发月金额。
    """
    if base <= 0 or days_in_month <= 0 or days <= 0:
        return Decimal("0")
    if days == Decimal(days_in_month):
        return base
    return (base / Decimal(days_in_month) * days).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _fmt_days(days: Decimal) -> str:
    quant = Decimal(days).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if quant == quant.to_integral():
        return str(int(quant))
    return f"{quant:.1f}"


def _rest_pay_flags(day: date, rules: dict) -> dict[str, bool] | None:
    """整天休息时返回工资和补贴勾选。当天还要上班则返回 None。"""
    from app.services.attendance_rules import designated_rest_pay, is_fixed_rest_day

    if is_fixed_rest_day(day, rules):
        return {
            "pay_salary": rules.get("rest_pay_salary", True) is not False,
            "pay_meal": bool(rules.get("rest_pay_meal")),
            "pay_housing": bool(rules.get("rest_pay_housing")),
            "pay_other": bool(rules.get("rest_pay_other")),
        }
    return designated_rest_pay(day, rules)


def _missed_flag(rest: dict[str, bool] | None, halves: list[dict], key: str) -> tuple[Decimal, Decimal]:
    """休息日没勾，这一整天不算。否则只扣没勾的请假半天。同一天最多扣 1 天。"""
    if rest is not None and not rest.get(key):
        return Decimal("1"), Decimal("0")
    missed = Decimal("0")
    for half in halves:
        if not half.get(key):
            missed += Decimal("0.5")
    if missed > 1:
        missed = Decimal("1")
    return Decimal("0"), missed


def _calendar_pay_adjustments(
    pay_start: date,
    pay_end: date,
    rules: dict,
    leave_halves: list[dict],
) -> dict[str, Decimal]:
    """在职日历里，休息日和请假没勾工资或补贴的天数。不看出勤。"""
    empty = {
        "span": Decimal("0"),
        "salary_rest": Decimal("0"),
        "salary_leave": Decimal("0"),
        "meal": Decimal("0"),
        "housing": Decimal("0"),
        "other": Decimal("0"),
    }
    if pay_start > pay_end:
        return empty
    by_day: dict[date, list[dict]] = {}
    for item in leave_halves:
        by_day.setdefault(item["date"], []).append(item)
    salary_rest = salary_leave = meal = housing = other = Decimal("0")
    day = pay_start
    while day <= pay_end:
        rest = _rest_pay_flags(day, rules)
        halves = by_day.get(day, [])
        rest_part, leave_part = _missed_flag(rest, halves, "pay_salary")
        salary_rest += rest_part
        salary_leave += leave_part
        meal += sum(_missed_flag(rest, halves, "pay_meal"), Decimal("0"))
        housing += sum(_missed_flag(rest, halves, "pay_housing"), Decimal("0"))
        other += sum(_missed_flag(rest, halves, "pay_other"), Decimal("0"))
        day += timedelta(days=1)
    span = Decimal((pay_end - pay_start).days + 1)
    return {
        "span": span,
        "salary_rest": salary_rest,
        "salary_leave": salary_leave,
        "meal": meal,
        "housing": housing,
        "other": other,
    }


def _salary_model_value(worker: Employee) -> str:
    m = worker.salary_model
    return m.value if hasattr(m, "value") else str(m or SalaryModel.pure_piece.value)


def _settle_total(
    *,
    model: str,
    base_salary: Decimal,
    piece_wage: Decimal,
    piece_qty: int,
    overtime_pay: Decimal = Decimal("0"),
    proration: Decimal = Decimal("1"),
    period_days: int | None = None,
    days_in_month: int | None = None,
) -> dict:
    """按计薪模式汇总应发。

    - pure_piece: 纯计件
    - base_plus_piece: 底薪 + 全额计件
    - guaranteed_piece: 计件不足保底时发保底，超过保底时发全额计件
    - fixed: 固定工资 + 加班费
    - hourly: 历史兼容，按底薪 + 全额计件

    proration: 按月部分 = 月薪 × 实出勤 / 当月应出勤。0 表示这段没有出勤。
    """
    base_salary = Decimal(base_salary or 0)
    piece_wage = Decimal(piece_wage or 0)
    piece_qty = int(piece_qty or 0)
    overtime_pay = Decimal(overtime_pay or 0)
    if proration is None:
        proration = Decimal("1")
    else:
        proration = Decimal(proration)
    if proration < 0 or proration > 1:
        proration = Decimal("1")
    prorated_base = (base_salary * proration).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    partial_note = ""
    if period_days is not None and days_in_month:
        partial_note = f"（出勤{int(period_days)}/{int(days_in_month)}天）"

    if model == SalaryModel.fixed.value:
        payable_piece = Decimal("0")
        total = prorated_base + overtime_pay
        note = f"底薪{partial_note}" + (f"+加班费¥{overtime_pay:.2f}" if overtime_pay else "")
        settled_base = prorated_base
    elif model == SalaryModel.pure_piece.value:
        payable_piece = piece_wage
        total = piece_wage
        note = "纯计件"
        settled_base = Decimal("0")
    elif model == SalaryModel.base_plus_piece.value:
        payable_piece = piece_wage
        total = prorated_base + piece_wage
        note = f"底薪{partial_note}+计件"
        settled_base = prorated_base
    elif model == SalaryModel.guaranteed_piece.value:
        payable_piece = piece_wage
        total = max(prorated_base, piece_wage)
        if piece_wage < prorated_base:
            note = f"按保底发放{partial_note}"
        else:
            note = "按计件发放（已超过保底）"
        settled_base = prorated_base
    else:
        payable_piece = piece_wage
        total = prorated_base + piece_wage
        note = f"底薪{partial_note}+计件（计时工时未接入）"
        settled_base = prorated_base

    return {
        "base_salary": float(settled_base),
        "base_salary_full": float(base_salary),
        "proration": float(proration),
        "piece_qty": piece_qty,
        "piece_wage": float(piece_wage),
        "payable_piece_wage": float(payable_piece),
        "overtime_pay": float(overtime_pay),
        "total_wage": float(total),
        "settle_note": note,
    }


def _monthly_overtime(
    db: Session,
    tenant_id: int,
    worker_id: int,
    *,
    date_from: date,
    date_to: date,
) -> tuple[Decimal, int]:
    """返回区间加班小时与分钟。

    已配置加班时间段时，只累计这些时段的打卡时长。
    未配置时，有排班按下班后超出，否则按每日超出 8 小时。
    """
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    use_periods = bool(rules.get("overtime_periods"))
    days = db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == worker_id,
            AttendanceDay.work_date >= date_from,
            AttendanceDay.work_date <= date_to,
        )
    ).all()
    overtime_minutes = 0
    for day in days:
        if use_periods:
            overtime_minutes += int(getattr(day, "overtime_minutes", 0) or 0)
        elif day.clock_out_at and day.scheduled_out_at:
            overtime_minutes += max(0, int((day.clock_out_at - day.scheduled_out_at).total_seconds() // 60))
        else:
            overtime_minutes += max(0, int(day.work_minutes or 0) - 8 * 60)
    overtime_hours = (Decimal(overtime_minutes) / Decimal("60")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return overtime_hours, overtime_minutes


def _effective_settle_through(
    db: Session,
    tenant_id: int,
    year_month: str,
    settle_through: date | str | None = None,
    *,
    ignore_lock: bool = False,
) -> date | str | None:
    """已记下结算日时以该日为准；否则用本次预览参数。"""
    if ignore_lock:
        return settle_through
    lock = get_month_lock(db, tenant_id, year_month)
    if lock.get("settle_through"):
        return lock["settle_through"]
    return settle_through


def shipped_qty_by_product(
    db: Session,
    tenant_id: int,
    *,
    date_from: date,
    date_to: date,
) -> dict[int, int]:
    """结算窗口内已出货数量，按产品汇总（双）。"""
    shipments = db.scalars(
        select(Shipment)
        .where(
            Shipment.tenant_id == tenant_id,
            Shipment.status == ShipmentStatus.shipped,
            Shipment.ship_date.is_not(None),
            Shipment.ship_date >= date_from,
            Shipment.ship_date <= date_to,
        )
        .options(selectinload(Shipment.lines))
    ).all()
    qty_map: dict[int, int] = {}
    order_product_cache: dict[int, int | None] = {}
    soli_product_cache: dict[int, int | None] = {}
    order_item_product_cache: dict[int, int | None] = {}

    def _order_product(order_id: int | None) -> int | None:
        if not order_id:
            return None
        if order_id in order_product_cache:
            return order_product_cache[order_id]
        order = db.get(Order, order_id)
        pid = order.own_product_id if order and order.tenant_id == tenant_id else None
        order_product_cache[order_id] = pid
        return pid

    def _soli_product(soli_id: int | None) -> int | None:
        if not soli_id:
            return None
        if soli_id in soli_product_cache:
            return soli_product_cache[soli_id]
        sitem = db.get(SalesOrderLineItem, soli_id)
        pid = None
        if sitem and sitem.tenant_id == tenant_id:
            sline = db.get(SalesOrderLine, sitem.sales_order_line_id)
            if sline and sline.tenant_id == tenant_id:
                pid = sline.own_product_id
        soli_product_cache[soli_id] = pid
        return pid

    def _order_item_product(order_item_id: int | None) -> int | None:
        if not order_item_id:
            return None
        if order_item_id in order_item_product_cache:
            return order_item_product_cache[order_item_id]
        oitem = db.get(OrderItem, order_item_id)
        pid = _order_product(oitem.order_id) if oitem and oitem.tenant_id == tenant_id else None
        order_item_product_cache[order_item_id] = pid
        return pid

    for sh in shipments:
        fallback_pid = _order_product(sh.order_id)
        resolved_any = False
        for ln in sh.lines or []:
            pid = _soli_product(ln.sales_order_line_item_id)
            if pid is None:
                pid = _order_item_product(ln.order_item_id)
            if pid is None:
                pid = fallback_pid
            if pid is None:
                continue
            qty = int(ln.qty or 0)
            if qty <= 0:
                continue
            qty_map[pid] = qty_map.get(pid, 0) + qty
            resolved_any = True
        if not resolved_any and fallback_pid:
            qty = int(sh.total_qty or 0)
            if qty > 0:
                qty_map[fallback_pid] = qty_map.get(fallback_pid, 0) + qty
    return qty_map


def commission_for_employee(
    db: Session,
    tenant_id: int,
    employee_id: int,
    shipped_by_product: dict[int, int],
) -> dict:
    """按出货量 × 产品提成单价（元/双）汇总该员工提成。"""
    if not shipped_by_product:
        return {"commission_total": 0.0, "commission_qty": 0, "commissions": []}
    rows = db.scalars(
        select(OwnProductCommission).where(
            OwnProductCommission.tenant_id == tenant_id,
            OwnProductCommission.employee_id == employee_id,
            OwnProductCommission.own_product_id.in_(list(shipped_by_product.keys())),
        )
    ).all()
    rate_by_product: dict[int, Decimal] = {}
    for row in rows:
        rate_by_product[row.own_product_id] = rate_by_product.get(
            row.own_product_id, Decimal("0")
        ) + Decimal(str(row.amount or 0))
    holder = db.get(Employee, employee_id)
    title_id = getattr(holder, "job_title_id", None) if holder and holder.is_active else None
    if title_id:
        mgmt_rows = db.scalars(
            select(OwnProductMgmtCommission).where(
                OwnProductMgmtCommission.tenant_id == tenant_id,
                OwnProductMgmtCommission.job_title_id == title_id,
                OwnProductMgmtCommission.own_product_id.in_(list(shipped_by_product.keys())),
            )
        ).all()
        for row in mgmt_rows:
            rate_by_product[row.own_product_id] = rate_by_product.get(
                row.own_product_id, Decimal("0")
            ) + Decimal(str(row.amount or 0))
    details: list[dict] = []
    total = Decimal("0")
    total_qty = 0
    for pid, rate in sorted(rate_by_product.items()):
        qty = int(shipped_by_product.get(pid) or 0)
        if qty <= 0 or rate <= 0:
            continue
        amount = (rate * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        product = db.get(OwnProduct, pid)
        details.append(
            {
                "own_product_id": pid,
                "product_code": product.product_code if product else None,
                "shipped_qty": qty,
                "unit_amount": float(rate),
                "amount": float(amount),
            }
        )
        total += amount
        total_qty += qty
    return {
        "commission_total": float(total),
        "commission_qty": total_qty,
        "commissions": details,
    }


_PRESENT_STATUSES = {"normal", "late", "early", "late_early", "incomplete"}
_MONTHLY_MODELS = {
    SalaryModel.fixed.value,
    SalaryModel.base_plus_piece.value,
    SalaryModel.guaranteed_piece.value,
    SalaryModel.hourly.value,
}


def _month_attendance(
    db: Session,
    tenant_id: int,
    worker_id: int,
    month_start: date,
    month_end: date,
    period_start: date,
    period_end: date,
) -> dict:
    """当月应出勤，以及这段窗口里实际打了卡的天数。"""
    from app.services.attendance_rules import (
        designated_rest_pay,
        get_attendance_rules_by_tenant_id,
        is_attendance_workday,
        is_fixed_rest_day,
    )

    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    scheduled = 0
    fixed_rest_days = 0
    fixed_rest_in_period = 0
    designated_unpaid_days = 0
    designated_meal_days = 0
    designated_housing_days = 0
    designated_other_days = 0
    day = month_start
    while day <= month_end:
        if is_fixed_rest_day(day, rules):
            fixed_rest_days += 1
            if period_start <= day <= period_end:
                fixed_rest_in_period += 1
        elif is_attendance_workday(day, rules):
            scheduled += 1
        else:
            pay = designated_rest_pay(day, rules)
            if pay:
                if not pay["pay_salary"]:
                    designated_unpaid_days += 1
                if period_start <= day <= period_end:
                    if pay["pay_meal"]:
                        designated_meal_days += 1
                    if pay["pay_housing"]:
                        designated_housing_days += 1
                    if pay["pay_other"]:
                        designated_other_days += 1
        day += timedelta(days=1)
    attended = 0
    if period_start <= period_end:
        rows = db.scalars(
            select(AttendanceDay).where(
                AttendanceDay.tenant_id == tenant_id,
                AttendanceDay.employee_id == worker_id,
                AttendanceDay.work_date >= period_start,
                AttendanceDay.work_date <= period_end,
            )
        ).all()
        for row in rows:
            if is_attendance_workday(row.work_date, rules) and str(row.status or "") in _PRESENT_STATUSES:
                attended += 1
    pay_salary = rules.get("rest_pay_salary", True) is not False
    pay_days = scheduled if pay_salary else scheduled + fixed_rest_days
    pay_days += designated_unpaid_days
    if pay_days <= 0:
        ratio = Decimal("0")
    else:
        ratio = Decimal(attended) / Decimal(pay_days)
        if ratio > 1:
            ratio = Decimal("1")
    return {
        "attended_days": attended,
        "scheduled_days": scheduled,
        "pay_days": pay_days,
        "fixed_rest_days": fixed_rest_days,
        "fixed_rest_in_period": fixed_rest_in_period,
        "designated_meal_days": designated_meal_days,
        "designated_housing_days": designated_housing_days,
        "designated_other_days": designated_other_days,
        "rest_pay_meal": bool(rules.get("rest_pay_meal")),
        "rest_pay_housing": bool(rules.get("rest_pay_housing")),
        "rest_pay_other": bool(rules.get("rest_pay_other")),
        "proration": ratio,
    }


def _wage_bucket(payload: dict, scheduled_days: int = 0) -> dict:
    return {
        "total_wage": float(payload.get("total_wage") or 0),
        "base_salary": float(payload.get("base_salary") or 0),
        "piece_wage": float(payload.get("total_piece_wage") or payload.get("piece_wage") or 0),
        "payable_piece_wage": float(payload.get("payable_piece_wage") or 0),
        "overtime_pay": float(payload.get("overtime_pay") or 0),
        "meal_allowance": float(payload.get("meal_allowance") or 0),
        "housing_allowance": float(payload.get("housing_allowance") or 0),
        "other_allowance": float(payload.get("other_allowance") or 0),
        "meal_allowance_days": float(payload.get("meal_allowance_days") or 0),
        "housing_allowance_days": float(payload.get("housing_allowance_days") or 0),
        "other_allowance_days": float(payload.get("other_allowance_days") or 0),
        "leave_deduction": float(payload.get("leave_deduction") or 0),
        "leave_days": float(payload.get("leave_days") or 0),
        "salary_days": float(payload.get("salary_days") or 0),
        "commission_total": float(payload.get("commission_total") or 0),
        "loss_deduction": float(payload.get("loss_deduction") or 0),
        "advance_repay": float(payload.get("advance_repay") or 0),
        "attended_days": int(payload.get("attended_days") or 0),
        "scheduled_days": int(payload.get("scheduled_days") or scheduled_days or 0),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
    }


def month_salary(
    db: Session,
    tenant_id: int,
    worker_id: int,
    year_month: str | None = None,
    *,
    settle_through: date | str | None = None,
    shipped_by_product: dict[int, int] | None = None,
    settle_from: date | str | None = None,
    ignore_lock: bool = False,
    include_adjustments: bool = True,
    _split: bool = True,
) -> dict:
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        return {"error": "工人不存在"}

    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    through = _effective_settle_through(
        db, tenant_id, year_month, settle_through, ignore_lock=ignore_lock
    )
    try:
        window = resolve_settle_window(year_month, through, settle_from)
    except ValueError as err:
        return {"error": str(err)}
    year_month = window["year_month"]
    utc_start = window["utc_start"]
    utc_end = window["utc_end_exclusive"]
    # 报工落库走 NOW()。本机 MySQL 是东八区时，下午 4 点后的报工会被 UTC 日切挡住，要按同一时钟取到当天结束。
    log_clock = _work_log_clock_offset(db)
    log_start = utc_start + log_clock
    log_end = utc_end + log_clock
    period_start = window["period_start"]
    period_end = window["period_end"]

    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.worker_id == worker_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.source != WorkLogSource.cut_basket,
            WorkLog.created_at >= log_start,
            WorkLog.created_at < log_end,
        )
    ).all()

    details = []
    piece_wage = Decimal("0")
    loss_deduction = Decimal("0")
    piece_qty = Decimal("0")
    from app.services import reporting_settings

    reporting = reporting_settings.get_reporting_by_tenant_id(db, tenant_id)
    rework_pays = bool(reporting.get("rework_pays", True))
    for log in logs:
        product = db.get(OwnProduct, log.own_product_id)
        process = db.get(ProcessDefinition, log.process_id)
        report_type = log.report_type if isinstance(log.report_type, ReportType) else ReportType(str(log.report_type))
        is_rework = report_type == ReportType.rework
        qty = log.rework_qty if is_rework else log.qualified_qty
        price = work_log_unit_price(db, tenant_id, log)
        if is_rework and not rework_pays:
            price = Decimal("0")
        amount = price * Decimal(qty)
        loss = work_log_loss_deduction(log)
        piece_wage += amount
        loss_deduction += loss
        piece_qty += Decimal(str(qty or 0))
        details.append(
            {
                "work_log_id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "order_no": _work_log_ref_no(db, log),
                "product_code": product.product_code if product else None,
                "process_name": process.name if process else None,
                "segment_name": _segment_name_of(db, log),
                "report_type": report_type.value,
                "qualified_qty": log.qualified_qty,
                "defect_qty": log.defect_qty,
                "rework_qty": log.rework_qty,
                "unit_price": float(price),
                "price_locked": log.unit_price is not None,
                "amount": float(amount),
                "loss_borne_percent": int(getattr(log, "loss_borne_percent", 0) or 0),
                "loss_amount": float(Decimal(getattr(log, "loss_amount", 0) or 0)),
                "wage_deduction": float(loss),
                "net_amount": float(amount - loss),
                "rework_unpaid": bool(is_rework and not rework_pays),
            }
        )

    deduction_events = db.scalars(
        select(DefectEvent).where(
            DefectEvent.tenant_id == tenant_id,
            DefectEvent.status == DefectEventStatus.closed,
            DefectEvent.disposition == DefectDisposition.scrap,
            DefectEvent.wage_deduction_from_event.is_(True),
            DefectEvent.scrap_confirmed_at >= utc_start,
            DefectEvent.scrap_confirmed_at < utc_end,
        )
    ).all()
    for event in deduction_events:
        employee_percent = max(0, 100 - int(event.company_share_percent or 0))
        responsibility = db.scalar(
            select(DefectResponsibility).where(
                DefectResponsibility.tenant_id == tenant_id,
                DefectResponsibility.defect_event_id == event.id,
                DefectResponsibility.worker_id == worker_id,
            )
        )
        worker_share = (
            int(responsibility.share_percent or 0)
            if responsibility
            else (100 if event.responsible_worker_id == worker_id else 0)
        )
        entered_amount = responsibility.share_amount if responsibility is not None else None
        if entered_amount is not None:
            deduction = Decimal(entered_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if deduction <= 0:
                continue
        elif worker_share <= 0:
            continue
        else:
            deduction = (
                Decimal(event.loss_amount or 0) * Decimal(worker_share) / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        header = db.get(ExecutionHeader, event.header_id) if event.header_id else None
        product = db.get(OwnProduct, header.own_product_id) if header else None
        process = db.get(ProcessDefinition, event.responsible_process_id) if event.responsible_process_id else None
        loss_deduction += deduction
        details.append(
            {
                "work_log_id": None,
                "defect_event_id": event.id,
                "created_at": event.scrap_confirmed_at.isoformat() if event.scrap_confirmed_at else None,
                "order_no": header.header_no if header else None,
                "product_code": product.product_code if product else None,
                "process_name": process.name if process else None,
                "segment_name": "质量报废",
                "report_type": "scrap_deduction",
                "qualified_qty": 0,
                "defect_qty": event.qty,
                "rework_qty": 0,
                "unit_price": 0.0,
                "price_locked": True,
                "amount": 0.0,
                "loss_borne_percent": worker_share,
                "employee_share_percent": employee_percent,
                "loss_amount": float(Decimal(event.loss_amount or 0)),
                "wage_deduction": float(deduction),
                "net_amount": float(-deduction),
                "rework_unpaid": False,
            }
        )

    contributions = db.scalars(
        select(CutOutputContribution)
        .join(CutOutput, CutOutput.id == CutOutputContribution.cut_output_id)
        .where(
            CutOutputContribution.tenant_id == tenant_id,
            CutOutputContribution.worker_id == worker_id,
            CutOutput.status == CutOutputStatus.confirmed,
            CutOutput.confirmed_at >= utc_start,
            CutOutput.confirmed_at < utc_end,
        )
    ).all()
    for contribution in contributions:
        output = db.get(CutOutput, contribution.cut_output_id)
        header = db.get(ExecutionHeader, output.header_id) if output else None
        product = db.get(OwnProduct, header.own_product_id) if header else None
        process = db.get(ProcessDefinition, contribution.process_id)
        order = db.get(Order, output.order_id) if output and output.order_id else None
        ref_no = order.order_no if order else (header.header_no if header else None)
        amount = Decimal(contribution.wage or 0)
        piece_wage += amount
        piece_qty += int(contribution.credited_pairs or 0)
        details.append(
            {
                "work_log_id": None,
                "cut_output_id": contribution.cut_output_id,
                "output_no": output.output_no if output else None,
                "created_at": output.confirmed_at.isoformat() if output and output.confirmed_at else None,
                "order_no": ref_no,
                "product_code": product.product_code if product else None,
                "process_name": process.name if process else None,
                "segment_name": "裁断",
                "report_type": ReportType.normal.value,
                "qualified_qty": contribution.credited_pairs,
                "defect_qty": 0,
                "rework_qty": 0,
                "unit_price": float(contribution.unit_price or 0),
                "price_locked": True,
                "amount": float(amount),
                "loss_borne_percent": 0,
                "loss_amount": 0.0,
                "wage_deduction": 0.0,
                "net_amount": float(amount),
                "component_group": contribution.component_group,
                "rework_unpaid": False,
            }
        )

    model = _salary_model_value(worker)
    overtime_rate = Decimal("0")
    overtime_hours = Decimal("0")
    overtime_minutes = 0
    employed = _employed_range(worker, period_start, period_end)
    if employed is None:
        pay_start, pay_end = period_end + timedelta(days=1), period_end
    else:
        pay_start, pay_end = employed
    if model == SalaryModel.fixed.value:
        overtime_rate = Decimal(worker.overtime_hourly_rate or 0)
        overtime_hours, overtime_minutes = _monthly_overtime(
            db,
            tenant_id,
            worker_id,
            date_from=pay_start,
            date_to=pay_end,
        )
    overtime_pay = (overtime_hours * overtime_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    attendance = _month_attendance(
        db,
        tenant_id,
        worker_id,
        window["month_start"],
        window["month_end"],
        pay_start,
        pay_end,
    )
    from app.services.leave_service import leave_pay_in_period

    leave = leave_pay_in_period(db, tenant_id, worker_id, pay_start, pay_end)
    monthly = model in _MONTHLY_MODELS
    archive_base = Decimal(worker.base_salary or 0)
    pay_base = archive_base
    fixed_daily = Decimal("0")
    leave_deduction = Decimal("0")
    salary_rest_unpaid = Decimal("0")
    # 补贴按在职日历，不按打卡。入职前、离职后不算。休息日、请假没勾对应补贴的那天不算。
    from app.services.attendance_rules import get_attendance_rules_by_tenant_id

    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    calendar_adjust = _calendar_pay_adjustments(pay_start, pay_end, rules, leave.get("halves") or [])
    # 底薪、保底 = 月金额 ÷ 当月天数 × 本月出勤，最后四舍五入到元。
    # 本月出勤已去掉没勾工资的休息日和请假。不先把日工资四舍五入。
    calendar_floor = model in (SalaryModel.fixed.value, SalaryModel.guaranteed_piece.value)
    if calendar_floor:
        days_in_month = int(window["days_in_month"] or 0)
        counted = calendar_adjust["span"] - calendar_adjust["salary_rest"]
        if counted < 0:
            counted = Decimal("0")
        salary_paid_days = counted - calendar_adjust["salary_leave"]
        if salary_paid_days < 0:
            salary_paid_days = Decimal("0")
        pay_base = _calendar_salary_amount(archive_base, days_in_month, counted)
        paid_net = _calendar_salary_amount(archive_base, days_in_month, salary_paid_days)
        leave_deduction = pay_base - paid_net
        if leave_deduction < 0:
            leave_deduction = Decimal("0")
        salary_rest_unpaid = calendar_adjust["salary_rest"]
        fixed_daily = (
            (archive_base / Decimal(days_in_month)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if days_in_month
            else Decimal("0")
        )
    settle = _settle_total(
        model=model,
        base_salary=pay_base,
        piece_wage=piece_wage,
        piece_qty=piece_qty,
        overtime_pay=overtime_pay,
        proration=Decimal("1") if calendar_floor else (attendance["proration"] if monthly else Decimal("1")),
        period_days=None if calendar_floor else (attendance["attended_days"] if monthly else None),
        days_in_month=None if calendar_floor else (attendance["pay_days"] if monthly else None),
    )
    guarantee_leave_inside = False
    if model == SalaryModel.guaranteed_piece.value:
        floor = pay_base - leave_deduction
        if floor < 0:
            floor = Decimal("0")
        piece_amount = Decimal(str(settle["piece_wage"]))
        if piece_amount < floor:
            settle["total_wage"] = float(floor)
            settle["settle_note"] = "按保底发放"
        else:
            settle["total_wage"] = float(piece_amount)
            settle["settle_note"] = "按计件发放（已超过保底）"
        settle["base_salary"] = float(pay_base)
        settle["base_salary_full"] = float(archive_base)
        guarantee_leave_inside = True
    # 餐补 / 住宿补 / 其它补：元/天。在职日历扣除没勾补贴的休息日和请假。
    attended_days = int(attendance["attended_days"])
    meal_days = calendar_adjust["span"] - calendar_adjust["meal"]
    housing_days = calendar_adjust["span"] - calendar_adjust["housing"]
    other_days = calendar_adjust["span"] - calendar_adjust["other"]
    if meal_days < 0:
        meal_days = Decimal("0")
    if housing_days < 0:
        housing_days = Decimal("0")
    if other_days < 0:
        other_days = Decimal("0")
    meal_daily = Decimal(str(getattr(worker, "meal_allowance_daily", 0) or 0))
    housing_daily = Decimal(str(getattr(worker, "housing_allowance_daily", 0) or 0))
    other_daily = Decimal(str(getattr(worker, "other_allowance_daily", 0) or 0))
    meal_allowance = (meal_daily * Decimal(meal_days)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    housing_allowance = (housing_daily * Decimal(housing_days)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    other_allowance = (other_daily * Decimal(other_days)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    allowance_total = meal_allowance + housing_allowance + other_allowance

    # 提成：结算窗口内已出货数量 × 产品对该人的提成单价
    shipped_map = shipped_by_product
    if shipped_map is None:
        shipped_map = shipped_qty_by_product(
            db, tenant_id, date_from=period_start, date_to=period_end
        )
    commission = commission_for_employee(db, tenant_id, worker_id, shipped_map)
    commission_total = Decimal(str(commission["commission_total"] or 0))

    salary_leave_deduction = Decimal("0") if guarantee_leave_inside else leave_deduction
    gross_total_wage = Decimal(str(settle["total_wage"])) + allowance_total + commission_total - salary_leave_deduction
    settle["gross_total_wage"] = float(gross_total_wage)
    settle["loss_deduction"] = float(loss_deduction)
    settle["meal_allowance"] = float(meal_allowance)
    settle["housing_allowance"] = float(housing_allowance)
    settle["other_allowance"] = float(other_allowance)
    settle["meal_allowance_daily"] = float(meal_daily)
    settle["housing_allowance_daily"] = float(housing_daily)
    settle["other_allowance_daily"] = float(other_daily)
    settle["allowance_days"] = int(calendar_adjust["span"]) if calendar_adjust is not None else attended_days
    salary_days = Decimal("0")
    if calendar_adjust is not None:
        salary_days = calendar_adjust["span"] - calendar_adjust["salary_rest"] - calendar_adjust["salary_leave"]
        if salary_days < 0:
            salary_days = Decimal("0")
    settle["salary_days"] = float(salary_days)
    settle["meal_allowance_days"] = meal_days
    settle["housing_allowance_days"] = housing_days
    settle["other_allowance_days"] = other_days
    settle["leave_days"] = float(leave["leave_days"])
    settle["leave_unpaid_days"] = float(leave["unpaid_days"])
    settle["leave_deduction"] = float(leave_deduction)
    settle["leave_daily_rate"] = float(fixed_daily)
    settle["commission_total"] = float(commission_total)
    settle["commission_qty"] = int(commission["commission_qty"] or 0)
    settle["commissions"] = commission["commissions"]

    from app.services import hr_service

    if include_adjustments:
        adj = hr_service.sum_adjustments_for_worker(db, tenant_id, worker_id, year_month)
    else:
        adj = {
            "adjustment_net": 0,
            "reward_total": 0,
            "penalty_total": 0,
            "late_deduction": 0,
            "advance_repay": 0,
            "items": [],
        }
    adjustment_net = Decimal(str(adj["adjustment_net"]))
    settle["reward_total"] = adj["reward_total"]
    settle["penalty_total"] = adj["penalty_total"]
    settle["late_deduction"] = adj["late_deduction"]
    settle["advance_repay"] = adj["advance_repay"]
    settle["adjustment_net"] = float(adjustment_net)
    settle["adjustments"] = adj["items"]
    settle["total_wage"] = float(gross_total_wage - loss_deduction + adjustment_net)
    note_bits = [settle["settle_note"]]
    if window["is_partial"]:
        note_bits.insert(0, f"截至{period_end.isoformat()}")
    if salary_rest_unpaid:
        note_bits.append(f"休息{_fmt_days(salary_rest_unpaid)}天不发工资")
    if meal_allowance:
        note_bits.append(f"餐补¥{meal_allowance:.2f}（{meal_daily}/天×{_fmt_days(meal_days)}天）")
    if housing_allowance:
        note_bits.append(f"住宿补¥{housing_allowance:.2f}（{housing_daily}/天×{_fmt_days(housing_days)}天）")
    if other_allowance:
        note_bits.append(f"其它补¥{other_allowance:.2f}（{other_daily}/天×{_fmt_days(other_days)}天）")
    if leave_deduction:
        leave_title = "请假扣保底" if model == SalaryModel.guaranteed_piece.value else "请假扣款"
        note_bits.append(f"{leave_title}{_fmt_days(Decimal(str(leave['unpaid_days'])))}天扣¥{leave_deduction:.0f}")
    if commission_total:
        note_bits.append(f"提成¥{commission_total:.2f}")
    if loss_deduction:
        note_bits.append(f"损失扣减¥{loss_deduction:.2f}")
    if adj["reward_total"]:
        note_bits.append(f"奖励¥{adj['reward_total']:.2f}")
    if adj["penalty_total"]:
        note_bits.append(f"惩罚¥{adj['penalty_total']:.2f}")
    if adj["late_deduction"]:
        note_bits.append(f"迟到扣款¥{adj['late_deduction']:.2f}")
    if adj["advance_repay"]:
        note_bits.append(f"预支扣回¥{adj['advance_repay']:.2f}")
    settle["settle_note"] = "，".join(note_bits)

    lock = get_month_lock(db, tenant_id, year_month)
    ack = get_acknowledgement(db, tenant_id, worker_id, year_month)
    result = {
        "worker_id": worker_id,
        "worker_name": worker.name,
        "year_month": year_month,
        "settle_through": period_end.isoformat() if window["is_partial"] else None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "proration": float(window["proration"]),
        "allowance_days": settle["allowance_days"],
        "salary_days": settle["salary_days"],
        "meal_allowance_days": float(settle["meal_allowance_days"] or 0),
        "housing_allowance_days": float(settle["housing_allowance_days"] or 0),
        "other_allowance_days": float(settle["other_allowance_days"] or 0),
        "salary_model": model,
        "is_locked": lock["is_locked"],
        "acknowledged": ack is not None,
        "acknowledgement": (
            {
                "confirm_name": ack.confirm_name,
                "confirmed_at": ack.confirmed_at.isoformat() if ack.confirmed_at else None,
                "total_wage": float(ack.total_wage),
                "has_signature": bool(ack.signature_data),
            }
            if ack
            else None
        ),
        "details": details,
        "total_piece_wage": settle["piece_wage"],
        "payable_piece_wage": settle["payable_piece_wage"],
        "gross_total_wage": settle["gross_total_wage"],
        "loss_deduction": settle["loss_deduction"],
        "meal_allowance": settle["meal_allowance"],
        "housing_allowance": settle["housing_allowance"],
        "other_allowance": settle["other_allowance"],
        "meal_allowance_daily": settle["meal_allowance_daily"],
        "housing_allowance_daily": settle["housing_allowance_daily"],
        "other_allowance_daily": settle["other_allowance_daily"],
        "leave_days": settle["leave_days"],
        "leave_deduction": settle["leave_deduction"],
        "leave_daily_rate": settle["leave_daily_rate"],
        "commission_total": settle["commission_total"],
        "commission_qty": settle["commission_qty"],
        "commissions": settle["commissions"],
        "reward_total": settle["reward_total"],
        "penalty_total": settle["penalty_total"],
        "late_deduction": settle["late_deduction"],
        "advance_repay": settle["advance_repay"],
        "adjustment_net": settle["adjustment_net"],
        "adjustments": settle["adjustments"],
        "base_salary": settle["base_salary"],
        "base_salary_full": settle["base_salary_full"],
        "attended_days": attendance["attended_days"],
        "scheduled_days": attendance["scheduled_days"],
        "overtime_hours": float(overtime_hours),
        "overtime_minutes": overtime_minutes,
        "overtime_hourly_rate": float(overtime_rate),
        "overtime_pay": settle["overtime_pay"],
        "piece_qty": settle["piece_qty"],
        "total_wage": settle["total_wage"],
        "settle_note": settle["settle_note"],
        "message": (
            f"{worker.name} {year_month} {settle['settle_note']}；"
            f"计件明细 {len(details)} 条 ¥{settle['piece_wage']:.2f}，"
            f"应发合计 ¥{settle['total_wage']:.2f}"
            + (f"（已结算至 {lock['settle_through']}）" if lock.get("settle_through") else "")
            + ("（已确认）" if ack else "")
        ),
        "settled_through": lock.get("settle_through"),
    }
    if _split:
        cutoff = (
            date.fromisoformat(lock["settle_through"])
            if lock.get("settle_through")
            else (window["month_end"] if lock.get("is_locked") else None)
        )
        for row in details:
            row["settlement"] = "settled" if cutoff else "unsettled"
        if cutoff:
            settled_bucket = _wage_bucket(result)
            locked_through = cutoff
            if locked_through < window["month_end"]:
                tail = month_salary(
                    db,
                    tenant_id,
                    worker_id,
                    year_month,
                    settle_from=locked_through + timedelta(days=1),
                    ignore_lock=True,
                    include_adjustments=False,
                    _split=False,
                )
                unsettled_bucket = _wage_bucket(tail, attendance["scheduled_days"])
                if not tail.get("error"):
                    for row in tail.get("details") or []:
                        row["settlement"] = "unsettled"
                        details.append(row)
            else:
                unsettled_bucket = _wage_bucket({}, attendance["scheduled_days"])
        else:
            settled_bucket = _wage_bucket({}, attendance["scheduled_days"])
            unsettled_bucket = _wage_bucket(result)
        result["settled"] = settled_bucket
        result["unsettled"] = unsettled_bucket
        result["settled_wage"] = settled_bucket["total_wage"]
        result["unsettled_wage"] = unsettled_bucket["total_wage"]
    return result


def _accrued_amount(row: dict, key: str) -> Decimal:
    """已结算金额加上结算日之后、到今天为止的未结算金额。"""
    if row.get("settled") is not None or row.get("unsettled") is not None:
        settled = row.get("settled") or {}
        unsettled = row.get("unsettled") or {}
        return Decimal(str(settled.get(key) or 0)) + Decimal(str(unsettled.get(key) or 0))
    return Decimal(str(row.get(key) or 0))


def month_salary_all(
    db: Session,
    tenant_id: int,
    year_month: str | None = None,
    *,
    worker_id: int | None = None,
    department_id: int | None = None,
    settle_through: date | str | None = None,
) -> dict:
    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    through = _effective_settle_through(db, tenant_id, year_month, settle_through)
    window = resolve_settle_window(year_month, through)
    year_month = window["year_month"]
    q = select(Employee).where(Employee.tenant_id == tenant_id, Employee.is_active.is_(True))
    if worker_id is not None:
        q = q.where(Employee.id == worker_id)
    if department_id is not None:
        departments = db.scalars(
            select(Department).where(Department.tenant_id == tenant_id)
        ).all()
        children: dict[int, list[int]] = {}
        for department in departments:
            if department.parent_id is not None:
                children.setdefault(department.parent_id, []).append(department.id)
        department_ids: set[int] = set()
        stack = [department_id]
        while stack:
            current = stack.pop()
            if current in department_ids:
                continue
            department_ids.add(current)
            stack.extend(children.get(current, []))
        q = q.where(Employee.department_id.in_(department_ids))
    workers = db.scalars(q.order_by(Employee.id)).all()
    shipped_map = shipped_qty_by_product(
        db, tenant_id, date_from=window["month_start"], date_to=window["period_end"]
    )
    items = []
    grand_piece = Decimal("0")
    grand_payable = Decimal("0")
    grand_total = Decimal("0")
    grand_base = Decimal("0")
    grand_base_pay = Decimal("0")
    grand_fixed = Decimal("0")
    grand_guarantee = Decimal("0")
    grand_loss = Decimal("0")
    grand_reward = Decimal("0")
    grand_penalty = Decimal("0")
    grand_late = Decimal("0")
    grand_advance = Decimal("0")
    grand_adj_net = Decimal("0")
    grand_overtime = Decimal("0")
    grand_meal = Decimal("0")
    grand_housing = Decimal("0")
    grand_other = Decimal("0")
    grand_leave_days = Decimal("0")
    grand_leave_deduction = Decimal("0")
    grand_guarantee_leave = Decimal("0")
    grand_commission = Decimal("0")
    grand_settled = Decimal("0")
    grand_unsettled = Decimal("0")
    grand_qty = 0
    grand_logs = 0
    for w in workers:
        row = month_salary(
            db,
            tenant_id,
            w.id,
            year_month,
            settle_through=through,
            shipped_by_product=shipped_map,
        )
        if row.get("error"):
            continue
        model = row.get("salary_model")
        base_val = _accrued_amount(row, "base_salary")
        raw_leave = _accrued_amount(row, "leave_deduction")
        accrued_total = _accrued_amount(row, "total_wage")
        accrued_piece = _accrued_amount(row, "piece_wage")
        accrued_payable = _accrued_amount(row, "payable_piece_wage")
        accrued_meal = _accrued_amount(row, "meal_allowance")
        accrued_housing = _accrued_amount(row, "housing_allowance")
        accrued_other = _accrued_amount(row, "other_allowance")
        accrued_overtime = _accrued_amount(row, "overtime_pay")
        accrued_leave_days = _accrued_amount(row, "leave_days")
        accrued_salary_days = _accrued_amount(row, "salary_days")
        if model == SalaryModel.guaranteed_piece.value:
            fixed_leave, guarantee_leave = Decimal("0"), raw_leave
        else:
            fixed_leave, guarantee_leave = raw_leave, Decimal("0")
        if model == SalaryModel.guaranteed_piece.value:
            base_pay, fixed_pay, guarantee_pay = Decimal("0"), Decimal("0"), base_val
        elif model == SalaryModel.fixed.value:
            base_pay, fixed_pay, guarantee_pay = Decimal("0"), base_val, Decimal("0")
        elif model == SalaryModel.pure_piece.value:
            base_pay, fixed_pay, guarantee_pay = Decimal("0"), Decimal("0"), Decimal("0")
        else:
            # 底薪+计件 / 计时等：计入底薪
            base_pay, fixed_pay, guarantee_pay = base_val, Decimal("0"), Decimal("0")
        items.append(
            {
                "worker_id": w.id,
                "worker_name": w.name,
                "department_id": w.department_id,
                "department_name": (
                    db.get(Department, w.department_id).name if w.department_id else None
                ),
                "year_month": year_month,
                "salary_model": model,
                "log_count": len(row["details"]),
                "piece_qty": row.get("piece_qty", 0),
                "base_salary": float(base_val),
                "base_pay": float(base_pay),
                "fixed_pay": float(fixed_pay),
                "guarantee_pay": float(guarantee_pay),
                "overtime_hours": row.get("overtime_hours", 0),
                "overtime_hourly_rate": row.get("overtime_hourly_rate", 0),
                "overtime_pay": float(accrued_overtime),
                "meal_allowance": float(accrued_meal),
                "housing_allowance": float(accrued_housing),
                "other_allowance": float(accrued_other),
                "leave_days": float(accrued_leave_days),
                "salary_days": float(accrued_salary_days),
                "leave_deduction": float(fixed_leave),
                "guarantee_leave_deduction": float(guarantee_leave),
                "allowance_days": row.get("allowance_days", window["period_days"]),
                "commission_total": row.get("commission_total", 0),
                "commission_qty": row.get("commission_qty", 0),
                "total_piece_wage": float(accrued_piece),
                "payable_piece_wage": float(accrued_payable),
                "gross_total_wage": row.get("gross_total_wage", row.get("total_wage", 0)),
                "loss_deduction": row.get("loss_deduction", 0),
                "reward_total": row.get("reward_total", 0),
                "penalty_total": row.get("penalty_total", 0),
                "late_deduction": row.get("late_deduction", 0),
                "advance_repay": row.get("advance_repay", 0),
                "adjustment_net": row.get("adjustment_net", 0),
                "total_wage": float(accrued_total),
                "settled_wage": row.get("settled_wage", 0),
                "unsettled_wage": row.get("unsettled_wage", 0),
                "attended_days": int((row.get("settled") or {}).get("attended_days") or 0)
                + int((row.get("unsettled") or {}).get("attended_days") or 0),
                "scheduled_days": row.get("scheduled_days", 0),
                "settle_note": row.get("settle_note"),
                "is_locked": row.get("is_locked", False),
                "acknowledged": row.get("acknowledged", False),
            }
        )
        grand_piece += accrued_piece
        grand_payable += accrued_payable
        grand_total += accrued_total
        grand_base += base_val
        grand_base_pay += base_pay
        grand_fixed += fixed_pay
        grand_guarantee += guarantee_pay
        grand_loss += Decimal(str(row.get("loss_deduction") or 0))
        grand_reward += Decimal(str(row.get("reward_total") or 0))
        grand_penalty += Decimal(str(row.get("penalty_total") or 0))
        grand_late += Decimal(str(row.get("late_deduction") or 0))
        grand_advance += Decimal(str(row.get("advance_repay") or 0))
        grand_adj_net += Decimal(str(row.get("adjustment_net") or 0))
        grand_overtime += accrued_overtime
        grand_meal += accrued_meal
        grand_housing += accrued_housing
        grand_other += accrued_other
        grand_leave_days += accrued_leave_days
        grand_leave_deduction += fixed_leave
        grand_guarantee_leave += guarantee_leave
        grand_commission += Decimal(str(row.get("commission_total") or 0))
        grand_settled += Decimal(str(row.get("settled_wage") or 0))
        grand_unsettled += Decimal(str(row.get("unsettled_wage") or 0))
        grand_qty += int(row.get("piece_qty") or 0)
        grand_logs += len(row["details"])
    # 按部门分组，便于前端合并部门列
    items.sort(
        key=lambda i: (
            i.get("department_name") or "\uffff",
            i.get("worker_name") or "",
            i["worker_id"],
        )
    )
    lock = get_month_lock(db, tenant_id, year_month)
    ack_count = sum(1 for i in items if i.get("acknowledged"))
    if lock["is_locked"]:
        unacknowledged = [
            {"worker_id": i["worker_id"], "worker_name": i["worker_name"]}
            for i in items
            if not i.get("acknowledged")
        ]
        all_acknowledged = bool(items) and ack_count >= len(items)
    else:
        unacknowledged = []
        all_acknowledged = False
    from app.services import payroll_settings as payroll_settings_service

    payroll = payroll_settings_service.get_payroll_by_tenant_id(db, tenant_id)
    payday = int(payroll.get("payday") or 10)
    y, m = map(int, year_month.split("-"))
    if m == 12:
        pay_year, pay_month = y + 1, 1
    else:
        pay_year, pay_month = y, m + 1
    settle_hint = (
        f"结算截至 {window['period_end'].isoformat()}（{window['period_days']}/{window['days_in_month']} 天）"
        if window["is_partial"]
        else f"整月结算（{window['days_in_month']} 天）"
    )
    return {
        "year_month": year_month,
        "settle_through": window["settle_through"].isoformat() if window["settle_through"] else None,
        "period_start": window["month_start"].isoformat(),
        "period_end": window["period_end"].isoformat(),
        "proration": float(window["proration"]),
        "is_partial": window["is_partial"],
        "is_locked": lock["is_locked"],
        "lock": lock,
        "payroll": {
            "payday": payday,
            "pay_year_month": f"{pay_year:04d}-{pay_month:02d}",
            "hint": (
                f"{settle_hint} · 发薪日：每月 {payday} 号"
                + (
                    f"（结算月 {year_month} → {pay_year:04d}-{pay_month:02d}-{payday:02d} 实发）"
                    if not window["is_partial"]
                    else f"（提前结算日 {window['period_end'].isoformat()}）"
                )
            ),
        },
        "items": items,
        "acknowledged_count": ack_count,
        "all_acknowledged": all_acknowledged,
        "unacknowledged": unacknowledged,
        "total_piece_wage": float(grand_piece),
        "loss_deduction": float(grand_loss),
        "reward_total": float(grand_reward),
        "penalty_total": float(grand_penalty),
        "late_deduction": float(grand_late),
        "advance_repay": float(grand_advance),
        "adjustment_net": float(grand_adj_net),
        "total_wage": float(grand_total),
        "summary": {
            "count": len(items),
            "log_count": grand_logs,
            "piece_qty": grand_qty,
            "base_salary": float(grand_base),
            "base_pay": float(grand_base_pay),
            "fixed_pay": float(grand_fixed),
            "guarantee_pay": float(grand_guarantee),
            "overtime_pay": float(grand_overtime),
            "meal_allowance": float(grand_meal),
            "housing_allowance": float(grand_housing),
            "other_allowance": float(grand_other),
            "leave_days": float(grand_leave_days),
            "leave_deduction": float(grand_leave_deduction),
            "guarantee_leave_deduction": float(grand_guarantee_leave),
            "commission_total": float(grand_commission),
            "total_piece_wage": float(grand_piece),
            "payable_piece_wage": float(grand_payable),
            "loss_deduction": float(grand_loss),
            "reward_total": float(grand_reward),
            "penalty_total": float(grand_penalty),
            "late_deduction": float(grand_late),
            "advance_repay": float(grand_advance),
            "adjustment_net": float(grand_adj_net),
            "total_wage": float(grand_total),
            "settled_wage": float(grand_settled),
            "unsettled_wage": float(grand_unsettled),
        },
        "message": (
            f"{year_month} 在职工人 {len(items)} 人，"
            f"计件 ¥{grand_piece:.2f}，提成 ¥{grand_commission:.2f}，应发合计 ¥{grand_total:.2f}"
            + ("（已月结锁定）" if lock["is_locked"] else "")
            + (f"；已确认 {ack_count}/{len(items)}" if lock["is_locked"] else "")
        ),
    }


def reconcile_salary_cost(
    db: Session,
    tenant_id: int,
    year_month: str | None = None,
) -> dict:
    """工资 vs 实际人工成本对账（只读）：应发工资（月结同源）vs 当月有效报工计件总额。

    差异 root-cause buckets（符号约定：应发侧为正、人工侧为负）：
      base_salary（+）           固定/底薪部分，无对应计件
      fixed_piece_unpaid（−）    固定工资模式下未发放的计件
      guarantee_top_up（+）      保底+计件模式下补足到保底金额
      overtime_pay（+）          固定工资模式下按考勤计算的加班费
      commission（+）            按出货计入的产品提成
      loss_deduction（−）        报工记录按所占百分比计算的损失扣减
      inactive_worker_logs（−）  停用员工当月报工（发不了工资）
      other（仅当残差 ≥ 0.005 出现）
    variance.explained = buckets 合计 == 差异（容差 0.005）。
    """
    ym = year_month or year_month_of(None)
    overview = month_salary_all(db, tenant_id, ym)
    payroll_items = overview["items"]

    base_total = Decimal("0")
    piece_full_total = Decimal("0")
    piece_payable_total = Decimal("0")
    payroll_total = Decimal("0")
    fixed_piece_unpaid = Decimal("0")
    guarantee_top_up = Decimal("0")
    overtime_pay_total = Decimal("0")
    commission_total = Decimal("0")
    loss_deduction = Decimal("0")
    active_ids: set[int] = set()
    for item in payroll_items:
        worker_id = int(item["worker_id"])
        active_ids.add(worker_id)
        base = Decimal(str(item.get("base_salary") or 0))
        full = Decimal(str(item.get("total_piece_wage") or 0))
        payable = Decimal(str(item.get("payable_piece_wage") if item.get("payable_piece_wage") is not None else full))
        total = Decimal(str(item.get("total_wage") or 0))
        overtime_pay = Decimal(str(item.get("overtime_pay") or 0))
        commission_total += Decimal(str(item.get("commission_total") or 0))
        piece_full_total += full
        piece_payable_total += payable
        payroll_total += total
        loss_deduction -= Decimal(str(item.get("loss_deduction") or 0))
        model = str(item.get("salary_model") or SalaryModel.pure_piece.value)
        if model == SalaryModel.fixed.value:
            base_total += base
            overtime_pay_total += overtime_pay
            fixed_piece_unpaid -= full
        elif model == SalaryModel.base_plus_piece.value:
            base_total += base
        elif model == SalaryModel.guaranteed_piece.value:
            guarantee_top_up += max(base - full, Decimal("0"))

    year, month = map(int, ym.split("-"))
    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.source != WorkLogSource.cut_basket,
            extract("year", WorkLog.created_at) == year,
            extract("month", WorkLog.created_at) == month,
        )
    ).all()
    from app.services import reporting_settings

    reporting = reporting_settings.get_reporting_by_tenant_id(db, tenant_id)
    rework_pays = bool(reporting.get("rework_pays", True))
    labor_total = Decimal("0")
    inactive_piece = Decimal("0")
    unpaid_rework_count = 0
    unpaid_rework_amount = Decimal("0")
    for log in logs:
        rt = log.report_type if isinstance(log.report_type, ReportType) else ReportType(str(log.report_type))
        is_rework = rt == ReportType.rework
        qty = Decimal(str((log.rework_qty if is_rework else log.qualified_qty) or 0))
        if qty <= 0:
            continue
        price = work_log_unit_price(db, tenant_id, log)
        amount = price * qty
        if is_rework and not rework_pays:
            # 返修报工锁价被存为 0（report_service 返修不计薪），
            # 对账侧用参考单价还原真实人工成本（工资侧仍为 0）。
            unpaid_rework_count += 1
            ref_price = price
            if ref_price <= 0:
                ref_price = get_labor_unit_price(db, tenant_id, log.own_product_id, log.process_id) or Decimal("0")
            unpaid_rework_amount += Decimal(ref_price) * qty
            continue
        labor_total += amount
        if log.worker_id not in active_ids:
            inactive_piece += amount

    contributions = db.scalars(
        select(CutOutputContribution)
        .join(CutOutput, CutOutput.id == CutOutputContribution.cut_output_id)
        .where(
            CutOutputContribution.tenant_id == tenant_id,
            CutOutput.status == CutOutputStatus.confirmed,
            extract("year", CutOutput.confirmed_at) == year,
            extract("month", CutOutput.confirmed_at) == month,
        )
    ).all()
    for contribution in contributions:
        amount = Decimal(contribution.wage or 0)
        labor_total += amount
        if contribution.worker_id not in active_ids:
            inactive_piece += amount

    variance_amount = payroll_total - labor_total
    buckets: dict[str, Decimal] = {}
    if base_total:
        buckets["base_salary"] = base_total
    if fixed_piece_unpaid:
        buckets["fixed_piece_unpaid"] = fixed_piece_unpaid
    if guarantee_top_up:
        buckets["guarantee_top_up"] = guarantee_top_up
    if overtime_pay_total:
        buckets["overtime_pay"] = overtime_pay_total
    if commission_total:
        buckets["commission"] = commission_total
    if loss_deduction:
        buckets["loss_deduction"] = loss_deduction
    if inactive_piece:
        buckets["inactive_worker_logs"] = -inactive_piece
    bucket_sum = sum(buckets.values(), Decimal("0"))
    residual = variance_amount - bucket_sum
    if abs(residual) >= Decimal("0.005"):
        buckets["other"] = residual
    explained = abs(residual) < Decimal("0.005")
    bucket_labels = {
        "base_salary": "底薪",
        "fixed_piece_unpaid": "固定工资未发计件",
        "guarantee_top_up": "保底补足",
        "overtime_pay": "加班费",
        "commission": "提成",
        "loss_deduction": "损失扣减",
        "inactive_worker_logs": "停用员工报工",
        "other": "其他差异",
    }
    breakdown_nonzero = [
        {"key": k, "label": bucket_labels.get(k, k), "amount": round(float(v), 4)}
        for k, v in buckets.items()
        if abs(v) >= Decimal("0.005")
    ]

    rate = (variance_amount / payroll_total) if payroll_total else Decimal("0")
    return {
        "year_month": ym,
        "payroll": {
            "count": len(payroll_items),
            "total_wage": round(float(payroll_total), 2),
            "base_salary_total": round(float(base_total), 2),
            "piece_full_total": round(float(piece_full_total), 2),
            "piece_payable_total": round(float(piece_payable_total), 2),
            "no_log_workers": [i["worker_id"] for i in payroll_items if not i.get("log_count")],
        },
        "labor_cost": {
            "total": round(float(labor_total), 2),
            "inactive_workers_piece": round(float(inactive_piece), 2),
            "unpaid_rework_count": unpaid_rework_count,
            "unpaid_rework_amount": round(float(unpaid_rework_amount), 2),
        },
        "variance": {
            "amount": round(float(variance_amount), 2),
            "rate": round(float(rate), 4),
            "explained": bool(explained),
            "significant": bool(abs(variance_amount) >= Decimal("0.01")),
        },
        "breakdown_nonzero": breakdown_nonzero,
        "signature": {
            "acknowledged_count": overview["acknowledged_count"],
            "total": len(payroll_items),
            "all_acknowledged": bool(overview["all_acknowledged"]),
            "unacknowledged": overview["unacknowledged"],
        },
    }


def list_work_logs(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int | None = None,
    order_no: str | None = None,
    segment_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    worker_ids: set[int] | list[int] | None = None,
) -> dict:
    from app.schemas.common import normalize_page, page_payload

    # 兼容旧参数 limit：视为首页 page_size
    if limit is not None:
        page = 1
        page_size = limit
    page, page_size, offset = normalize_page(page, page_size, max_size=500)

    # 包月员工走考勤，不进入生产报工记录及其汇总。
    q = (
        select(WorkLog)
        .join(Employee, Employee.id == WorkLog.worker_id)
        .where(
            WorkLog.tenant_id == tenant_id,
            Employee.salary_model != SalaryModel.fixed,
        )
    )
    if worker_ids is not None:
        ids = list(worker_ids) if not isinstance(worker_ids, list) else worker_ids
        if not ids:
            payload = page_payload([], 0, page, page_size)
            payload["summary"] = {
                "unit_price_total": 0.0,
                "estimated_wage_total": 0.0,
                "qualified_qty_total": 0,
                "defect_qty_total": 0.0,
                "loss_amount_total": 0.0,
                "wage_deduction_total": 0.0,
            }
            return payload
        q = q.where(WorkLog.worker_id.in_(ids))
    if worker_id:
        q = q.where(WorkLog.worker_id == worker_id)
    if segment_id:
        q = q.where(WorkLog.segment_id == segment_id)
    # created_at 存 UTC；页面按东八区自然日筛选。
    local_utc_offset = timedelta(hours=8)
    if date_from:
        q = q.where(
            WorkLog.created_at >= datetime.combine(date_from, datetime.min.time()) - local_utc_offset
        )
    if date_to:
        q = q.where(
            WorkLog.created_at
            < datetime.combine(date_to, datetime.min.time()) - local_utc_offset + timedelta(days=1)
        )
    if status and status in WorkLogStatus.__members__:
        q = q.where(WorkLog.status == WorkLogStatus(status))
    if order_no and order_no.strip():
        needle = order_no.strip()
        q = (
            q.outerjoin(Order, Order.id == WorkLog.order_id)
            .outerjoin(ExecutionHeader, ExecutionHeader.id == WorkLog.header_id)
            .where(or_(Order.order_no == needle, ExecutionHeader.header_no == needle))
        )

    count_q = select(func.count()).select_from(q.order_by(None).subquery())
    total = db.scalar(count_q) or 0

    # 汇总基于全部筛选结果，不受当前页分页限制。旧数据未锁价时，与工资口径一致回落到产品工序价。
    filtered_ids = q.with_only_columns(WorkLog.id).order_by(None).subquery()
    fallback_price = (
        select(OwnProductLabor.unit_price)
        .where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id == WorkLog.own_product_id,
            OwnProductLabor.process_id == WorkLog.process_id,
        )
        .limit(1)
        .scalar_subquery()
    )
    effective_price = func.coalesce(WorkLog.unit_price, fallback_price, 0)
    bill_qty = case(
        (WorkLog.report_type == ReportType.rework, WorkLog.rework_qty),
        else_=WorkLog.qualified_qty,
    )
    wage_deduction = case(
        (
            WorkLog.defect_qty > 0,
            func.round(
                func.coalesce(WorkLog.loss_amount, 0)
                * func.coalesce(WorkLog.loss_borne_percent, 0)
                / 100,
                2,
            ),
        ),
        else_=0,
    )
    summary_row = db.execute(
        select(
            func.coalesce(func.sum(effective_price), 0),
            func.coalesce(
                func.sum(effective_price * func.coalesce(bill_qty, 0) - wage_deduction), 0
            ),
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
            func.coalesce(func.sum(WorkLog.loss_amount), 0),
            func.coalesce(func.sum(wage_deduction), 0),
        ).where(WorkLog.id.in_(select(filtered_ids.c.id)))
    ).one()
    summary = {
        "unit_price_total": round(float(summary_row[0] or 0), 2),
        "estimated_wage_total": round(float(summary_row[1] or 0), 2),
        "qualified_qty_total": int(summary_row[2] or 0),
        "defect_qty_total": round(float(summary_row[3] or 0), 2),
        "loss_amount_total": round(float(summary_row[4] or 0), 2),
        "wage_deduction_total": round(float(summary_row[5] or 0), 2),
    }

    # 生产报工表只列真实 WorkLog；质量报废扣款仍在工资明细中核算，不再混入报工记录。
    logs = db.scalars(q.order_by(WorkLog.id.desc())).all()

    items = []
    for log in logs:
        worker = db.get(Employee, log.worker_id)
        process = db.get(ProcessDefinition, log.process_id)
        product = db.get(OwnProduct, log.own_product_id)
        color = db.get(Color, log.color_id) if log.color_id else None
        size = db.get(Size, log.size_id) if log.size_id else None
        report_type = log.report_type.value if hasattr(log.report_type, "value") else str(log.report_type)
        group_total = None
        if log.group_detail and isinstance(log.group_detail, dict):
            group_total = log.group_detail.get("total_qty")
        items.append(
            {
                "id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "worker_id": log.worker_id,
                "worker_name": worker.name if worker else None,
                "order_no": _work_log_ref_no(db, log),
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "process_name": process.name if process else None,
                "segment_id": getattr(log, "segment_id", None),
                "segment_name": _segment_name_of(db, log),
                "report_type": report_type,
                "qualified_qty": log.qualified_qty,
                "defect_qty": round(float(log.defect_qty or 0), 2),
                "rework_qty": log.rework_qty,
                "unit_price": float(work_log_unit_price(db, tenant_id, log)),
                "loss_borne_percent": int(getattr(log, "loss_borne_percent", 0) or 0),
                "loss_amount": round(float(getattr(log, "loss_amount", 0) or 0), 2),
                "wage_deduction": float(work_log_loss_deduction(log)),
                "price_locked": log.unit_price is not None,
                "color_name": color.name if color else None,
                "size_value": size.size_value if size else None,
                "group_id": log.group_id,
                "group_total_qty": group_total,
                "source": log.source.value if hasattr(log.source, "value") else str(log.source),
                "status": log.status.value if hasattr(log.status, "value") else str(log.status),
                "original_text": log.original_text,
                "review_note": log.review_note,
            }
        )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total = len(items)
    items = items[offset : offset + page_size]
    payload = page_payload(items, int(total), page, page_size)
    payload["summary"] = summary
    return payload


def update_work_log_status(
    db: Session,
    tenant_id: int,
    work_log_id: int,
    status: str,
    review_note: str | None = None,
    reviewed_by: int | None = None,
) -> dict:
    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        return {"error": "报工记录不存在"}
    if status not in WorkLogStatus.__members__:
        return {"error": f"无效状态：{status}"}
    if is_month_locked(db, tenant_id, year_month_of(log.created_at)):
        return {"error": f"{year_month_of(log.created_at)} 已月结锁定，不能改状态"}
    log.status = WorkLogStatus(status)
    if review_note is not None:
        log.review_note = review_note
    if reviewed_by is not None:
        log.reviewed_by = reviewed_by
    db.commit()
    db.refresh(log)
    return {"id": log.id, "status": log.status.value, "review_note": log.review_note}


def update_work_log_loss(
    db: Session,
    tenant_id: int,
    work_log_id: int,
    *,
    loss_borne_percent: int,
    loss_amount: Decimal,
) -> dict:
    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        return {"error": "报工记录不存在"}
    if log.status not in (WorkLogStatus.valid, WorkLogStatus.appealed):
        return {"error": "仅有效或申诉中的报工可设置损失承担"}
    if is_month_locked(db, tenant_id, year_month_of(log.created_at)):
        return {"error": f"{year_month_of(log.created_at)} 已月结锁定，不能修改损失金额"}
    percent = int(loss_borne_percent or 0)
    amount = Decimal(str(loss_amount or 0)).quantize(Decimal("0.01"))
    if percent < 0 or percent > 100:
        return {"error": "所占百分比须在 0 至 100 之间"}
    if percent > 0 and Decimal(log.defect_qty or 0) <= 0:
        return {"error": "次品数量为 0，不能设置所占百分比"}
    if amount < 0:
        return {"error": "损失金额不能为负"}
    log.loss_borne_percent = int(percent)
    log.loss_amount = amount
    db.commit()
    db.refresh(log)
    return {
        "id": log.id,
        "loss_borne_percent": int(log.loss_borne_percent or 0),
        "loss_amount": float(log.loss_amount or 0),
        "wage_deduction": float(work_log_loss_deduction(log)),
        "message": (
            f"损失承担已更新，工资扣减 ¥{work_log_loss_deduction(log):.2f}"
            if percent > 0
            else "损失金额已保存，承担比例为 0%，当前不扣工资"
        ),
    }


def export_month_salary_csv(
    db: Session,
    tenant_id: int,
    year_month: str | None = None,
    *,
    department_id: int | None = None,
) -> str:
    """导出月结：汇总行 + 明细行，UTF-8 BOM 便于 Excel 打开。"""
    import csv
    import io

    overview = month_salary_all(db, tenant_id, year_month, department_id=department_id)
    year_month = overview["year_month"]
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["# 月结汇总", year_month])
    def _csv_money(v: object) -> str:
        try:
            n = float(v or 0)
        except (TypeError, ValueError):
            return ""
        return "" if n == 0 else f"{n:.2f}"

    writer.writerow(
        [
            "工人ID",
            "姓名",
            "部门",
            "报工条数",
            # 收入
            "固定工资",
            "底薪",
            "保底",
            "加班小时",
            "每小时加班费",
            "加班费",
            "计件",
            "提成",
            "餐补",
            "住宿补",
            "其它补",
            "奖励",
            # 扣款
            "损失扣减",
            "迟到扣款",
            "预支扣回",
            "惩罚",
            "应发合计",
        ]
    )
    for item in overview["items"]:
        writer.writerow(
            [
                item["worker_id"],
                item["worker_name"],
                item.get("department_name") or "",
                item["log_count"] or "",
                _csv_money(item.get("fixed_pay", 0)),
                _csv_money(item.get("base_pay", 0)),
                _csv_money(item.get("guarantee_pay", 0)),
                _csv_money(item.get("overtime_hours", 0)),
                _csv_money(item.get("overtime_hourly_rate", 0)),
                _csv_money(item.get("overtime_pay", 0)),
                _csv_money(item["total_piece_wage"]),
                _csv_money(item.get("commission_total", 0)),
                _csv_money(item.get("meal_allowance", 0)),
                _csv_money(item.get("housing_allowance", 0)),
                _csv_money(item.get("other_allowance", 0)),
                _csv_money(item.get("reward_total", 0)),
                _csv_money(item.get("loss_deduction", 0)),
                _csv_money(item.get("late_deduction", 0)),
                _csv_money(item.get("advance_repay", 0)),
                _csv_money(item.get("penalty_total", 0)),
                _csv_money(item.get("total_wage", item["total_piece_wage"])),
            ]
        )
    writer.writerow([])
    writer.writerow(["# 计件明细"])
    writer.writerow(
        ["工人", "时间", "订单号", "产品", "工序", "类型", "合格", "返修", "次品", "单价", "损失扣减", "实发金额"]
    )
    for item in overview["items"]:
        detail = month_salary(db, tenant_id, item["worker_id"], year_month)
        for d in detail.get("details") or []:
            writer.writerow(
                [
                    item["worker_name"],
                    d.get("created_at") or "",
                    d.get("order_no") or "",
                    d.get("product_code") or "",
                    d.get("process_name") or "",
                    d.get("report_type") or "",
                    d.get("qualified_qty") or 0,
                    d.get("rework_qty") or 0,
                    d.get("defect_qty") or 0,
                    f"{d.get('unit_price', 0):.3f}",
                    f"{d.get('wage_deduction', 0):.2f}",
                    f"{d.get('net_amount', d.get('amount', 0)):.2f}",
                ]
            )
    writer.writerow([])
    writer.writerow(["# 提成明细（按出货）"])
    writer.writerow(["工人", "产品", "出货双数", "提成单价", "提成金额"])
    for item in overview["items"]:
        detail = month_salary(db, tenant_id, item["worker_id"], year_month)
        for c in detail.get("commissions") or []:
            writer.writerow(
                [
                    item["worker_name"],
                    c.get("product_code") or "",
                    c.get("shipped_qty") or 0,
                    f"{c.get('unit_amount', 0):.2f}",
                    f"{c.get('amount', 0):.2f}",
                ]
            )
    writer.writerow([])
    writer.writerow(
        [
            "合计",
            "",
            "",
            "",
            "",
            "",
            f"{overview.get('summary', {}).get('base_pay', 0):.2f}",
            f"{overview.get('summary', {}).get('fixed_pay', 0):.2f}",
            f"{overview.get('summary', {}).get('guarantee_pay', 0):.2f}",
            "",
            "",
            f"{overview.get('summary', {}).get('overtime_pay', 0):.2f}",
            f"{overview.get('summary', {}).get('total_piece_wage', 0):.2f}",
            f"{overview.get('summary', {}).get('commission_total', 0):.2f}",
            f"{overview.get('summary', {}).get('meal_allowance', 0):.2f}",
            f"{overview.get('summary', {}).get('housing_allowance', 0):.2f}",
            f"{overview.get('summary', {}).get('other_allowance', 0):.2f}",
            f"{overview.get('summary', {}).get('reward_total', 0):.2f}",
            f"{overview.get('summary', {}).get('loss_deduction', 0):.2f}",
            f"{overview.get('summary', {}).get('late_deduction', 0):.2f}",
            f"{overview.get('summary', {}).get('advance_repay', 0):.2f}",
            f"{overview.get('summary', {}).get('penalty_total', 0):.2f}",
            f"{overview.get('total_wage', overview['total_piece_wage']):.2f}",
        ]
    )
    return buf.getvalue()


def _segment_name_of(db: Session, log: WorkLog) -> str | None:
    """工序段重构（9.1）：从 WorkLog.segment_id 查段名；null 段返回 '未分段'（D18）。"""
    seg_id = getattr(log, "segment_id", None)
    if not seg_id:
        return "未分段"
    from app.models import ProcessSegment

    seg = db.get(ProcessSegment, seg_id)
    return seg.name if seg else "未分段"
