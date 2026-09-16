"""生产效率报表：单款平均效率矩阵（日期 × 工序）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceDay,
    Employee,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ReportType,
    WorkLog,
    WorkLogStatus,
)
from app.services.attendance_service import (
    EFFICIENCY_DECIMALS,
    LOCAL_OFFSET,
    _efficiency_per_hour,
    _local_date,
)
from app.services.salary_service import work_log_loss_deduction
from app.services.segment_service import ensure_default_segments


def _bill_qty(log: WorkLog) -> Decimal:
    if log.report_type == ReportType.rework:
        return Decimal(str(log.rework_qty or 0))
    return Decimal(str(log.qualified_qty or 0))


def _pooled_person_efficiency(
    process_id: int,
    cell_qty: dict[tuple[date, int], Decimal],
    cell_emps: dict[tuple[date, int], set[int]],
    attendance_minutes: dict[tuple[int, date], int],
) -> float | None:
    """期间加权单人效率：工序总产量 ÷ 工序总出勤人时。"""
    total_qty = Decimal("0")
    total_minutes = 0
    for (day, pid), qty in cell_qty.items():
        if pid != process_id:
            continue
        total_qty += qty
        for eid in cell_emps.get((day, pid), set()):
            total_minutes += attendance_minutes.get((eid, day), 0)
    return _efficiency_per_hour(total_qty, total_minutes)


def _pooled_team_efficiency(
    process_id: int,
    cell_qty: dict[tuple[date, int], Decimal],
    cell_emps: dict[tuple[date, int], set[int]],
    attendance_minutes: dict[tuple[int, date], int],
) -> float | None:
    """期间加权产线吞吐：工序总产量 ÷ 工序总产线工时（人时合计 ÷ 当日人数）。"""
    total_qty = Decimal("0")
    total_line_minutes = 0.0
    for (day, pid), qty in cell_qty.items():
        if pid != process_id:
            continue
        emps = cell_emps.get((day, pid), set())
        n = len(emps)
        if n <= 0:
            continue
        minutes = sum(attendance_minutes.get((eid, day), 0) for eid in emps)
        if minutes <= 0:
            continue
        total_qty += qty
        total_line_minutes += minutes / n
    if total_line_minutes <= 0:
        return None
    return round(float(total_qty) / (total_line_minutes / 60.0), EFFICIENCY_DECIMALS)


def model_avg_efficiency_matrix(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    product_codes: list[str] | None = None,
) -> dict:
    """单款平均效率：行=日期（倒序），列=工序段→工序，值=双/人/小时。

    单元格口径与考勤报工日志一致：
    该日该工序（可选限工厂型号）合计报工数量 ÷ 做过该工序(×型号)的员工出勤人时。
    """
    ensure_default_segments(db, tenant_id)
    today = _local_date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=6)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    codes = [c.strip() for c in (product_codes or []) if c and c.strip()]
    product_ids: set[int] | None = None
    resolved_codes: list[str] = []
    if codes:
        products = db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.product_code.in_(codes),
            )
        ).all()
        product_ids = {p.id for p in products}
        resolved_codes = [p.product_code for p in products]
        # 保持用户输入顺序
        order = {c: i for i, c in enumerate(codes)}
        resolved_codes.sort(key=lambda c: order.get(c, 999))
        if not product_ids:
            return {
                "unit": "双/人/小时",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "product_codes": codes,
                "columns": [],
                "rows": [],
                "averages": {},
            }

    segments = db.scalars(
        select(ProcessSegment)
        .where(ProcessSegment.tenant_id == tenant_id, ProcessSegment.is_active.is_(True))
        .order_by(ProcessSegment.sort_order.asc(), ProcessSegment.id.asc())
    ).all()
    processes = db.scalars(
        select(ProcessDefinition)
        .where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.is_active.is_not(False),
        )
        .order_by(ProcessDefinition.sort_order.asc(), ProcessDefinition.id.asc())
    ).all()

    columns = []
    process_ids_ordered: list[int] = []
    assigned_ids: set[int] = set()
    for seg in segments:
        seg_processes = [p for p in processes if p.segment_id == seg.id]
        if not seg_processes:
            continue
        columns.append(
            {
                "segment_id": seg.id,
                "segment_code": seg.code,
                "segment_name": seg.name,
                "processes": [
                    {"process_id": p.id, "process_name": p.name, "process_code": p.code}
                    for p in seg_processes
                ],
            }
        )
        process_ids_ordered.extend(p.id for p in seg_processes)
        assigned_ids.update(p.id for p in seg_processes)

    # 无段 / 段已停用 / 段不存在 → 挂到「未分段」，避免整表只剩日期列
    unsegmented = [p for p in processes if p.id not in assigned_ids]
    if unsegmented:
        columns.append(
            {
                "segment_id": 0,
                "segment_code": "unassigned",
                "segment_name": "未分段",
                "processes": [
                    {"process_id": p.id, "process_name": p.name, "process_code": p.code}
                    for p in unsegmented
                ],
            }
        )
        process_ids_ordered.extend(p.id for p in unsegmented)

    utc_from = datetime.combine(date_from, datetime.min.time()) - LOCAL_OFFSET
    utc_to_exclusive = datetime.combine(date_to, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)
    wl_q = select(WorkLog).where(
        WorkLog.tenant_id == tenant_id,
        WorkLog.status == WorkLogStatus.valid,
        WorkLog.created_at >= utc_from,
        WorkLog.created_at < utc_to_exclusive,
    )
    if product_ids is not None:
        wl_q = wl_q.where(WorkLog.own_product_id.in_(product_ids))
    work_logs = db.scalars(wl_q).all()

    # (work_date, process_id) -> qty / employee ids
    cell_qty: dict[tuple[date, int], Decimal] = {}
    cell_emps: dict[tuple[date, int], set[int]] = {}
    for log in work_logs:
        work_date = (log.created_at + LOCAL_OFFSET).date() if log.created_at else None
        if work_date is None or work_date < date_from or work_date > date_to:
            continue
        key = (work_date, log.process_id)
        cell_qty[key] = cell_qty.get(key, Decimal("0")) + _bill_qty(log)
        cell_emps.setdefault(key, set()).add(log.worker_id)

    worker_ids = {eid for eids in cell_emps.values() for eid in eids}
    attendance_minutes: dict[tuple[int, date], int] = {}
    if worker_ids:
        for att in db.scalars(
            select(AttendanceDay).where(
                AttendanceDay.tenant_id == tenant_id,
                AttendanceDay.employee_id.in_(worker_ids),
                AttendanceDay.work_date >= date_from,
                AttendanceDay.work_date <= date_to,
                AttendanceDay.status == "normal",
            )
        ).all():
            attendance_minutes[(att.employee_id, att.work_date)] = int(att.work_minutes or 0)

    rows = []
    # 仅展示有报工的日期（倒序）
    work_dates = sorted({d for d, _ in cell_qty.keys()}, reverse=True)
    for day in work_dates:
        if day < date_from or day > date_to:
            continue
        values: dict[str, float | None] = {}
        for pid in process_ids_ordered:
            key = (day, pid)
            qty = cell_qty.get(key, Decimal("0"))
            minutes = sum(attendance_minutes.get((eid, day), 0) for eid in cell_emps.get(key, set()))
            values[str(pid)] = _efficiency_per_hour(qty, minutes)
        rows.append({"work_date": day.isoformat(), "values": values})

    averages: dict[str, float | None] = {}
    for pid in process_ids_ordered:
        averages[str(pid)] = _pooled_person_efficiency(
            pid, cell_qty, cell_emps, attendance_minutes
        )

    return {
        "unit": "双/人/小时",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "product_codes": resolved_codes if codes else [],
        "columns": columns,
        "rows": rows,
        "averages": averages,
    }


def person_avg_efficiency_matrix(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """单人平均效率：行=日期（倒序），列=工序段→工序，值=双/人/小时。

    口径与报工考勤日志「单人平均效率」一致：
    该日该工序合计报工数量 ÷ 该工序出勤人时合计（不限工厂型号）。
    """
    result = model_avg_efficiency_matrix(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        product_codes=None,
    )
    result.pop("product_codes", None)
    return result


def process_team_efficiency_matrix(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """工序多人效率：行=日期（倒序），列=工序段→工序，值=双/小时。

    口径：单人平均效率 × 该日该工序报工人数。
    单元格为 {efficiency, workers}，多人时前端展示「效率/N人」。
    """
    base = model_avg_efficiency_matrix(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        product_codes=None,
    )
    date_from_d = date.fromisoformat(base["date_from"])
    date_to_d = date.fromisoformat(base["date_to"])
    utc_from = datetime.combine(date_from_d, datetime.min.time()) - LOCAL_OFFSET
    utc_to_exclusive = (
        datetime.combine(date_to_d, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)
    )
    work_logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.created_at >= utc_from,
            WorkLog.created_at < utc_to_exclusive,
        )
    ).all()
    cell_emps: dict[tuple[date, int], set[int]] = {}
    for log in work_logs:
        work_date = (log.created_at + LOCAL_OFFSET).date() if log.created_at else None
        if work_date is None or work_date < date_from_d or work_date > date_to_d:
            continue
        cell_emps.setdefault((work_date, log.process_id), set()).add(log.worker_id)

    rows = []
    for row in base["rows"]:
        day = date.fromisoformat(row["work_date"])
        values: dict[str, dict | None] = {}
        for pid_str, person_eff in (row.get("values") or {}).items():
            n = len(cell_emps.get((day, int(pid_str)), set()))
            if person_eff is None or n <= 0:
                values[pid_str] = None
            else:
                values[pid_str] = {
                    "efficiency": round(float(person_eff) * n, EFFICIENCY_DECIMALS),
                    "workers": n,
                }
        rows.append({"work_date": row["work_date"], "values": values})

    # 复用 base 查询的产量；cell_emps 已在上方按日统计
    cell_qty: dict[tuple[date, int], Decimal] = {}
    for log in work_logs:
        work_date = (log.created_at + LOCAL_OFFSET).date() if log.created_at else None
        if work_date is None or work_date < date_from_d or work_date > date_to_d:
            continue
        key = (work_date, log.process_id)
        cell_qty[key] = cell_qty.get(key, Decimal("0")) + _bill_qty(log)

    worker_ids = {eid for eids in cell_emps.values() for eid in eids}
    attendance_minutes: dict[tuple[int, date], int] = {}
    if worker_ids:
        for att in db.scalars(
            select(AttendanceDay).where(
                AttendanceDay.tenant_id == tenant_id,
                AttendanceDay.employee_id.in_(worker_ids),
                AttendanceDay.work_date >= date_from_d,
                AttendanceDay.work_date <= date_to_d,
                AttendanceDay.status == "normal",
            )
        ).all():
            attendance_minutes[(att.employee_id, att.work_date)] = int(att.work_minutes or 0)

    process_ids = {int(pid_str) for row in rows for pid_str in row["values"]}
    averages: dict[str, float | None] = {}
    for pid in process_ids:
        averages[str(pid)] = _pooled_team_efficiency(
            pid, cell_qty, cell_emps, attendance_minutes
        )

    return {
        "unit": "双/小时",
        "date_from": base["date_from"],
        "date_to": base["date_to"],
        "columns": base["columns"],
        "rows": rows,
        "averages": averages,
    }


def personal_output_matrix(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    segment_id: int | None = None,
    include_inactive: bool = False,
) -> dict:
    """个人效率：行=日期（倒序），列=工序→(员工效率双/小时, 损失元)。

    员工效率 = 该日该工序报工数量 ÷ 该员工当日出勤人时。
    按工序段切换；默认不显示离职（is_active=False）员工。
    仅展示所选段内有报工的日期。
    """
    ensure_default_segments(db, tenant_id)
    today = _local_date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=6)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    segments = db.scalars(
        select(ProcessSegment)
        .where(ProcessSegment.tenant_id == tenant_id, ProcessSegment.is_active.is_(True))
        .order_by(ProcessSegment.sort_order.asc(), ProcessSegment.id.asc())
    ).all()
    segment_list = [
        {"segment_id": s.id, "segment_code": s.code, "segment_name": s.name} for s in segments
    ]
    if not segments:
        return {
            "unit": "双/小时",
            "loss_unit": "元",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "segments": [],
            "segment_id": None,
            "columns": [],
            "rows": [],
            "averages": {},
        }

    active_seg = next((s for s in segments if s.id == segment_id), None) or segments[0]
    processes = db.scalars(
        select(ProcessDefinition)
        .where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.segment_id == active_seg.id,
            ProcessDefinition.is_active.is_not(False),
        )
        .order_by(ProcessDefinition.sort_order.asc(), ProcessDefinition.id.asc())
    ).all()
    process_ids = {p.id for p in processes}

    utc_from = datetime.combine(date_from, datetime.min.time()) - LOCAL_OFFSET
    utc_to_exclusive = datetime.combine(date_to, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)
    wl_q = select(WorkLog).where(
        WorkLog.tenant_id == tenant_id,
        WorkLog.status == WorkLogStatus.valid,
        WorkLog.created_at >= utc_from,
        WorkLog.created_at < utc_to_exclusive,
    )
    if process_ids:
        wl_q = wl_q.where(WorkLog.process_id.in_(process_ids))
    else:
        return {
            "unit": "双/小时",
            "loss_unit": "元",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "segments": segment_list,
            "segment_id": active_seg.id,
            "columns": [],
            "rows": [],
            "averages": {},
        }
    work_logs = db.scalars(wl_q).all()

    # (day, process_id, employee_id) -> qty / loss
    cell_qty: dict[tuple[date, int, int], Decimal] = {}
    cell_loss: dict[tuple[date, int, int], Decimal] = {}
    process_workers: dict[int, set[int]] = {p.id: set() for p in processes}
    for log in work_logs:
        work_date = (log.created_at + LOCAL_OFFSET).date() if log.created_at else None
        if work_date is None or work_date < date_from or work_date > date_to:
            continue
        if log.process_id not in process_ids:
            continue
        key = (work_date, log.process_id, log.worker_id)
        cell_qty[key] = cell_qty.get(key, Decimal("0")) + _bill_qty(log)
        cell_loss[key] = cell_loss.get(key, Decimal("0")) + work_log_loss_deduction(log)
        process_workers[log.process_id].add(log.worker_id)

    worker_ids = {wid for wids in process_workers.values() for wid in wids}
    employees: dict[int, Employee] = {}
    if worker_ids:
        emp_q = select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.id.in_(worker_ids),
        )
        if not include_inactive:
            emp_q = emp_q.where(Employee.is_active.is_(True))
        employees = {e.id: e for e in db.scalars(emp_q).all()}

    attendance_minutes: dict[tuple[int, date], int] = {}
    if worker_ids:
        for att in db.scalars(
            select(AttendanceDay).where(
                AttendanceDay.tenant_id == tenant_id,
                AttendanceDay.employee_id.in_(worker_ids),
                AttendanceDay.work_date >= date_from,
                AttendanceDay.work_date <= date_to,
                AttendanceDay.status == "normal",
            )
        ).all():
            attendance_minutes[(att.employee_id, att.work_date)] = int(att.work_minutes or 0)

    columns = []
    for proc in processes:
        workers = sorted(
            (employees[wid] for wid in process_workers.get(proc.id, set()) if wid in employees),
            key=lambda e: (e.name or "", e.id),
        )
        if not workers:
            continue
        wcols = []
        for emp in workers:
            qty_key = f"p{proc.id}_e{emp.id}_qty"
            loss_key = f"p{proc.id}_e{emp.id}_loss"
            wcols.append(
                {
                    "employee_id": emp.id,
                    "employee_name": emp.name,
                    "is_active": bool(emp.is_active),
                    "qty_key": qty_key,
                    "loss_key": loss_key,
                }
            )
        columns.append(
            {
                "process_id": proc.id,
                "process_name": proc.name,
                "process_code": proc.code,
                "workers": wcols,
            }
        )

    work_dates = sorted({d for d, _, _ in cell_qty.keys()}, reverse=True)
    rows = []
    for day in work_dates:
        values: dict[str, float | None] = {}
        for proc in columns:
            for w in proc["workers"]:
                key = (day, proc["process_id"], w["employee_id"])
                qty = cell_qty.get(key)
                loss = cell_loss.get(key)
                minutes = attendance_minutes.get((w["employee_id"], day), 0)
                values[w["qty_key"]] = (
                    _efficiency_per_hour(qty, minutes) if qty is not None else None
                )
                values[w["loss_key"]] = float(loss) if loss is not None and loss > 0 else (
                    float(loss) if loss is not None else None
                )
                # 无报工时两项都为 None；有报工损失为 0 也显示 0 或空——线框空损失格，0 显示为空
                if qty is not None and (loss is None or loss == 0):
                    values[w["loss_key"]] = None
        # 若该日在当前列上全空（员工被过滤），仍保留有报工日
        if any(v is not None for v in values.values()):
            rows.append({"work_date": day.isoformat(), "values": values})

    averages: dict[str, float | None] = {}
    for proc in columns:
        for w in proc["workers"]:
            qty_key = w["qty_key"]
            loss_key = w["loss_key"]
            total_qty = Decimal("0")
            total_minutes = 0
            for (day, pid, eid), qty in cell_qty.items():
                if pid != proc["process_id"] or eid != w["employee_id"]:
                    continue
                total_qty += qty
                total_minutes += attendance_minutes.get((eid, day), 0)
            averages[qty_key] = _efficiency_per_hour(total_qty, total_minutes)
            loss_nums = [
                r["values"][loss_key]
                for r in rows
                if r["values"].get(loss_key) is not None
            ]
            averages[loss_key] = round(sum(loss_nums), 2) if loss_nums else None

    return {
        "unit": "双/小时",
        "loss_unit": "元",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "segments": segment_list,
        "segment_id": active_seg.id,
        "columns": columns,
        "rows": rows,
        "averages": averages,
    }


def recent_reported_products(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """近期有报工的工厂型号，按最近报工时间倒序。"""
    today = _local_date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=89)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    utc_from = datetime.combine(date_from, datetime.min.time()) - LOCAL_OFFSET
    utc_to_exclusive = datetime.combine(date_to, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)

    rows = db.execute(
        select(
            OwnProduct.id,
            OwnProduct.product_code,
            func.max(WorkLog.created_at).label("last_reported_at"),
        )
        .join(WorkLog, WorkLog.own_product_id == OwnProduct.id)
        .where(
            OwnProduct.tenant_id == tenant_id,
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.own_product_id.is_not(None),
            WorkLog.created_at >= utc_from,
            WorkLog.created_at < utc_to_exclusive,
        )
        .group_by(OwnProduct.id, OwnProduct.product_code)
        .order_by(func.max(WorkLog.created_at).desc(), OwnProduct.id.asc())
    ).all()

    items = []
    for pid, code, last_at in rows:
        if not code:
            continue
        last_iso = None
        if last_at is not None:
            last_iso = last_at.isoformat() if hasattr(last_at, "isoformat") else str(last_at)
        items.append(
            {
                "product_id": pid,
                "product_code": code,
                "last_reported_at": last_iso,
            }
        )
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "items": items,
    }
