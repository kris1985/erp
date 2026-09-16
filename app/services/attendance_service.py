from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

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


def _day_payload(day: AttendanceDay | None, employee: Employee, work_date: date) -> dict:
    return {
        "eligible": True,
        "employee_id": employee.id,
        "employee_name": employee.name,
        "work_date": work_date.isoformat(),
        "clock_in_at": _local_text(day.clock_in_at) if day else None,
        "clock_out_at": _local_text(day.clock_out_at) if day else None,
        "work_minutes": int(day.work_minutes or 0) if day else 0,
        "status": day.status if day else "not_clocked",
        "next_punch_type": (
            "on_duty" if not day or not day.clock_in_at else "off_duty" if not day.clock_out_at else None
        ),
    }


def get_today(db: Session, tenant_id: int, employee_id: int) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    today = _local_date()
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date == today,
        )
    )
    return _day_payload(day, employee, today)


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
    clock_ins = [p for p in punches if p.punch_type == "on_duty"]
    clock_outs = [p for p in punches if p.punch_type == "off_duty"]
    clock_in = clock_ins[0].check_time if clock_ins else None
    clock_out = clock_outs[-1].check_time if clock_outs else None
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
    day.clock_in_at = clock_in
    day.clock_out_at = clock_out
    day.work_minutes = max(0, int((clock_out - clock_in).total_seconds() // 60)) if clock_in and clock_out else 0
    day.status = "normal" if clock_in and clock_out else "incomplete"
    day.source_provider = punches[-1].source_provider if punches else "local"
    day.raw_count = len(punches)
    day.last_sync_at = _now_utc()
    db.flush()
    return day


def clock(db: Session, tenant_id: int, employee_id: int, punch_type: str) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    if punch_type not in PUNCH_TYPES:
        raise AttendanceError("invalid_punch_type", "打卡类型无效")
    now = _now_utc()
    today = _local_date(now)
    existing = db.scalar(
        select(AttendancePunch).where(
            AttendancePunch.tenant_id == tenant_id,
            AttendancePunch.employee_id == employee_id,
            AttendancePunch.work_date == today,
            AttendancePunch.punch_type == punch_type,
            AttendancePunch.source_provider == "local",
        )
    )
    if existing:
        label = "上班" if punch_type == "on_duty" else "下班"
        raise AttendanceError("already_clocked", f"今天已完成{label}打卡")
    if punch_type == "off_duty":
        clock_in = db.scalar(
            select(AttendancePunch).where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id == employee_id,
                AttendancePunch.work_date == today,
                AttendancePunch.punch_type == "on_duty",
            )
        )
        if not clock_in:
            raise AttendanceError("clock_in_required", "请先完成上班打卡")

    db.add(
        AttendancePunch(
            tenant_id=tenant_id,
            employee_id=employee_id,
            work_date=today,
            punch_type=punch_type,
            check_time=now,
            time_result="normal",
            location_result="not_required",
            source_provider="local",
            external_corp_id="",
            external_user_id=str(employee_id),
            external_record_key=f"local:{employee_id}:{today.isoformat()}:{punch_type}",
            source_type="mobile_web",
            raw_payload={"source": "local", "punch_type": punch_type},
        )
    )
    db.flush()
    day = _rebuild_day(db, tenant_id, employee_id, today)
    db.commit()
    db.refresh(day)
    return _day_payload(day, employee, today)


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
    items = [
        {
            "id": day.id,
            "work_date": day.work_date.isoformat(),
            "department_name": department.name if department else None,
            "employee_id": employee.id,
            "employee_name": employee.name,
            "clock_in_at": _local_text(day.clock_in_at),
            "clock_out_at": _local_text(day.clock_out_at),
            "work_minutes": int(day.work_minutes or 0),
            "status": day.status,
            "source_provider": day.source_provider,
        }
        for day, employee, department in rows
    ]
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

    仅含有效报工；出勤仅计该日 status=normal 工时。
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
        AttendanceDay.status == "normal",
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
