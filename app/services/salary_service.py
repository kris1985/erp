from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, extract, func, or_, select
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


# 报工 created_at 存 UTC；结算窗口按东八区自然日换算。
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


def _local_day_start_utc(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time()) - _LOCAL_UTC_OFFSET


def resolve_settle_window(
    year_month: str,
    settle_through: date | str | None = None,
) -> dict:
    """结算窗口：自然月 1 日～settle_through（含）；空则整月。"""
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
    period_end = through or month_end
    days_in_month = last_day
    period_days = (period_end - month_start).days + 1
    proration = (Decimal(period_days) / Decimal(days_in_month)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    utc_start = _local_day_start_utc(month_start)
    utc_end_exclusive = _local_day_start_utc(period_end + timedelta(days=1))
    return {
        "year_month": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "month_start": month_start,
        "month_end": month_end,
        "settle_through": through,
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
    row.is_locked = bool(locked)
    row.note = note
    if locked:
        window = resolve_settle_window(ym, settle_through)
        row.settle_through = window["settle_through"]
        row.locked_at = datetime.utcnow()
        row.locked_by = locked_by
        db.flush()
        from app.services import hr_service

        hr_service.mark_advances_repaid_for_month(db, tenant_id, ym)
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
        from app.services import ledger_service

        ledger_service.void_salary_month_entry(db, tenant_id, row.id)
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
    if not overview.get("is_locked"):
        raise ValueError(f"{ym} 尚未月结锁定，请锁定后再导出银行代发")

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

    proration: 提前结算时固定/底薪/保底按日折算（period_days / days_in_month）。
    """
    base_salary = Decimal(base_salary or 0)
    piece_wage = Decimal(piece_wage or 0)
    piece_qty = int(piece_qty or 0)
    overtime_pay = Decimal(overtime_pay or 0)
    proration = Decimal(proration or 1)
    if proration <= 0 or proration > 1:
        proration = Decimal("1")
    prorated_base = (base_salary * proration).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    partial_note = ""
    if proration < 1 and period_days and days_in_month:
        partial_note = f"（{period_days}/{days_in_month}天）"

    if model == SalaryModel.fixed.value:
        payable_piece = Decimal("0")
        total = prorated_base + overtime_pay
        note = f"固定工资{partial_note}" + (f"+加班费¥{overtime_pay:.2f}" if overtime_pay else "")
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
    """返回区间加班小时与分钟；有排班时按超出排班下班，否则按每日超出 8 小时。"""
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
        if day.clock_out_at and day.scheduled_out_at:
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
) -> date | str | None:
    """已锁定时以锁上截止日期为准；未锁定可用预览参数。"""
    lock = get_month_lock(db, tenant_id, year_month)
    if lock.get("is_locked") and lock.get("settle_through"):
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


def month_salary(
    db: Session,
    tenant_id: int,
    worker_id: int,
    year_month: str | None = None,
    *,
    settle_through: date | str | None = None,
    shipped_by_product: dict[int, int] | None = None,
) -> dict:
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        return {"error": "工人不存在"}

    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    through = _effective_settle_through(db, tenant_id, year_month, settle_through)
    try:
        window = resolve_settle_window(year_month, through)
    except ValueError as err:
        return {"error": str(err)}
    year_month = window["year_month"]
    utc_start = window["utc_start"]
    utc_end = window["utc_end_exclusive"]
    period_start = window["month_start"]
    period_end = window["period_end"]

    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.worker_id == worker_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.source != WorkLogSource.cut_basket,
            WorkLog.created_at >= utc_start,
            WorkLog.created_at < utc_end,
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
        if worker_share <= 0:
            continue
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
    if model == SalaryModel.fixed.value:
        overtime_rate = Decimal(worker.overtime_hourly_rate or 0)
        overtime_hours, overtime_minutes = _monthly_overtime(
            db,
            tenant_id,
            worker_id,
            date_from=period_start,
            date_to=period_end,
        )
    overtime_pay = (overtime_hours * overtime_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    settle = _settle_total(
        model=model,
        base_salary=Decimal(worker.base_salary or 0),
        piece_wage=piece_wage,
        piece_qty=piece_qty,
        overtime_pay=overtime_pay,
        proration=window["proration"],
        period_days=window["period_days"],
        days_in_month=window["days_in_month"],
    )
    # 餐补 / 住宿补：元/天 × 结算天数（与截止日期窗口一致）
    period_days = int(window["period_days"])
    meal_daily = Decimal(str(getattr(worker, "meal_allowance_daily", 0) or 0))
    housing_daily = Decimal(str(getattr(worker, "housing_allowance_daily", 0) or 0))
    meal_allowance = (meal_daily * Decimal(period_days)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    housing_allowance = (housing_daily * Decimal(period_days)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    allowance_total = meal_allowance + housing_allowance

    # 提成：结算窗口内已出货数量 × 产品对该人的提成单价
    shipped_map = shipped_by_product
    if shipped_map is None:
        shipped_map = shipped_qty_by_product(
            db, tenant_id, date_from=period_start, date_to=period_end
        )
    commission = commission_for_employee(db, tenant_id, worker_id, shipped_map)
    commission_total = Decimal(str(commission["commission_total"] or 0))

    gross_total_wage = Decimal(str(settle["total_wage"])) + allowance_total + commission_total
    settle["gross_total_wage"] = float(gross_total_wage)
    settle["loss_deduction"] = float(loss_deduction)
    settle["meal_allowance"] = float(meal_allowance)
    settle["housing_allowance"] = float(housing_allowance)
    settle["meal_allowance_daily"] = float(meal_daily)
    settle["housing_allowance_daily"] = float(housing_daily)
    settle["allowance_days"] = period_days
    settle["commission_total"] = float(commission_total)
    settle["commission_qty"] = int(commission["commission_qty"] or 0)
    settle["commissions"] = commission["commissions"]

    from app.services import hr_service

    adj = hr_service.sum_adjustments_for_worker(db, tenant_id, worker_id, year_month)
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
    if meal_allowance:
        note_bits.append(f"餐补¥{meal_allowance:.2f}（{meal_daily}/天×{period_days}）")
    if housing_allowance:
        note_bits.append(f"住宿补¥{housing_allowance:.2f}（{housing_daily}/天×{period_days}）")
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
    return {
        "worker_id": worker_id,
        "worker_name": worker.name,
        "year_month": year_month,
        "settle_through": period_end.isoformat() if window["is_partial"] else None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "proration": float(window["proration"]),
        "allowance_days": period_days,
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
        "meal_allowance_daily": settle["meal_allowance_daily"],
        "housing_allowance_daily": settle["housing_allowance_daily"],
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
            + ("（已月结锁定）" if lock["is_locked"] else "")
            + ("（已确认）" if ack else "")
        ),
    }


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
    grand_commission = Decimal("0")
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
        base_val = Decimal(str(row.get("base_salary") or 0))
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
                "overtime_pay": row.get("overtime_pay", 0),
                "meal_allowance": row.get("meal_allowance", 0),
                "housing_allowance": row.get("housing_allowance", 0),
                "allowance_days": row.get("allowance_days", window["period_days"]),
                "commission_total": row.get("commission_total", 0),
                "commission_qty": row.get("commission_qty", 0),
                "total_piece_wage": row["total_piece_wage"],
                "payable_piece_wage": row.get("payable_piece_wage", row["total_piece_wage"]),
                "gross_total_wage": row.get("gross_total_wage", row.get("total_wage", 0)),
                "loss_deduction": row.get("loss_deduction", 0),
                "reward_total": row.get("reward_total", 0),
                "penalty_total": row.get("penalty_total", 0),
                "late_deduction": row.get("late_deduction", 0),
                "advance_repay": row.get("advance_repay", 0),
                "adjustment_net": row.get("adjustment_net", 0),
                "total_wage": row.get("total_wage", row["total_piece_wage"]),
                "settle_note": row.get("settle_note"),
                "is_locked": row.get("is_locked", False),
                "acknowledged": row.get("acknowledged", False),
            }
        )
        grand_piece += Decimal(str(row["total_piece_wage"]))
        grand_payable += Decimal(str(row.get("payable_piece_wage", row["total_piece_wage"])))
        grand_total += Decimal(str(row.get("total_wage", row["total_piece_wage"])))
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
        grand_overtime += Decimal(str(row.get("overtime_pay") or 0))
        grand_meal += Decimal(str(row.get("meal_allowance") or 0))
        grand_housing += Decimal(str(row.get("housing_allowance") or 0))
        grand_commission += Decimal(str(row.get("commission_total") or 0))
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
