from datetime import datetime
from decimal import Decimal

from sqlalchemy import extract, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    ExecutionHeader,
    Order,
    OwnProduct,
    ProcessDefinition,
    ReportType,
    SalaryAcknowledgement,
    SalaryModel,
    SalaryMonthLock,
    Size,
    WorkLog,
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
        return {"year_month": year_month, "is_locked": False, "locked_at": None, "note": None}
    return {
        "year_month": row.year_month,
        "is_locked": bool(row.is_locked),
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
) -> dict:
    ym = (year_month or "").strip()
    if len(ym) != 7 or ym[4] != "-":
        raise ValueError("月份格式应为 YYYY-MM")
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
        row.locked_at = datetime.utcnow()
        row.locked_by = locked_by
    else:
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


def export_bank_payroll_csv(db: Session, tenant_id: int, year_month: str | None = None) -> str:
    """银行代发通用模板：户名/账号/开户行/金额/备注。需已月结锁定。"""
    import csv
    import io

    overview = month_salary_all(db, tenant_id, year_month)
    ym = overview["year_month"]
    if not overview.get("is_locked"):
        raise ValueError(f"{ym} 尚未月结锁定，请锁定后再导出银行代发")

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
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
                f"{ym}工资",
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


def _salary_model_value(worker: Employee) -> str:
    m = worker.salary_model
    return m.value if hasattr(m, "value") else str(m or SalaryModel.pure_piece.value)


def _settle_total(
    *,
    model: str,
    base_salary: Decimal,
    base_quota: int,
    piece_wage: Decimal,
    piece_qty: int,
) -> dict:
    """按计薪模式汇总应发。

    - pure_piece: 纯计件
    - base_plus_piece: 有定额则定额内由底薪覆盖、超额按计件比例发放；无定额则底薪+全额计件
    - fixed: 仅底薪
    - hourly: 暂无工时，按底薪+全额计件（与底薪无定额相同）
    """
    base_salary = Decimal(base_salary or 0)
    base_quota = int(base_quota or 0)
    piece_wage = Decimal(piece_wage or 0)
    piece_qty = int(piece_qty or 0)

    if model == SalaryModel.fixed.value:
        payable_piece = Decimal("0")
        total = base_salary
        note = "固定工资"
    elif model == SalaryModel.pure_piece.value:
        payable_piece = piece_wage
        total = piece_wage
        note = "纯计件"
    elif model == SalaryModel.base_plus_piece.value:
        if base_quota > 0 and piece_qty > 0:
            excess_qty = max(0, piece_qty - base_quota)
            ratio = Decimal(excess_qty) / Decimal(piece_qty)
            payable_piece = (piece_wage * ratio).quantize(Decimal("0.01"))
            total = base_salary + payable_piece
            note = f"底薪+超额计件（定额{base_quota}，计件量{piece_qty}，超额{excess_qty}）"
        else:
            payable_piece = piece_wage
            total = base_salary + piece_wage
            note = "底薪+全额计件"
    else:
        # hourly 等：先按底薪+计件，避免算不出数
        payable_piece = piece_wage
        total = base_salary + piece_wage
        note = "底薪+计件（计时工时未接入）"

    return {
        "base_salary": float(base_salary),
        "base_quota": base_quota,
        "piece_qty": piece_qty,
        "piece_wage": float(piece_wage),
        "payable_piece_wage": float(payable_piece),
        "total_wage": float(total),
        "settle_note": note,
    }


def month_salary(db: Session, tenant_id: int, worker_id: int, year_month: str | None = None) -> dict:
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        return {"error": "工人不存在"}

    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    year, month = map(int, year_month.split("-"))

    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.worker_id == worker_id,
            WorkLog.status == WorkLogStatus.valid,
            extract("year", WorkLog.created_at) == year,
            extract("month", WorkLog.created_at) == month,
        )
    ).all()

    details = []
    piece_wage = Decimal("0")
    piece_qty = 0
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
        piece_wage += amount
        piece_qty += int(qty or 0)
        details.append(
            {
                "work_log_id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "order_no": _work_log_ref_no(db, log),
                "product_code": product.product_code if product else None,
                "process_name": process.name if process else None,
                "report_type": report_type.value,
                "qualified_qty": log.qualified_qty,
                "defect_qty": log.defect_qty,
                "rework_qty": log.rework_qty,
                "unit_price": float(price),
                "price_locked": log.unit_price is not None,
                "amount": float(amount),
                "rework_unpaid": bool(is_rework and not rework_pays),
            }
        )

    model = _salary_model_value(worker)
    settle = _settle_total(
        model=model,
        base_salary=Decimal(worker.base_salary or 0),
        base_quota=int(worker.base_quota or 0),
        piece_wage=piece_wage,
        piece_qty=piece_qty,
    )

    lock = get_month_lock(db, tenant_id, year_month)
    ack = get_acknowledgement(db, tenant_id, worker_id, year_month)
    return {
        "worker_id": worker_id,
        "worker_name": worker.name,
        "year_month": year_month,
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
        "base_salary": settle["base_salary"],
        "base_quota": settle["base_quota"],
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
) -> dict:
    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    q = select(Employee).where(Employee.tenant_id == tenant_id, Employee.is_active.is_(True))
    if worker_id is not None:
        q = q.where(Employee.id == worker_id)
    workers = db.scalars(q.order_by(Employee.id)).all()
    items = []
    grand_piece = Decimal("0")
    grand_payable = Decimal("0")
    grand_total = Decimal("0")
    grand_base = Decimal("0")
    grand_qty = 0
    grand_logs = 0
    for w in workers:
        row = month_salary(db, tenant_id, w.id, year_month)
        if row.get("error"):
            continue
        items.append(
            {
                "worker_id": w.id,
                "worker_name": w.name,
                "year_month": year_month,
                "salary_model": row.get("salary_model"),
                "log_count": len(row["details"]),
                "piece_qty": row.get("piece_qty", 0),
                "base_salary": row.get("base_salary", 0),
                "base_quota": row.get("base_quota", 0),
                "total_piece_wage": row["total_piece_wage"],
                "payable_piece_wage": row.get("payable_piece_wage", row["total_piece_wage"]),
                "total_wage": row.get("total_wage", row["total_piece_wage"]),
                "settle_note": row.get("settle_note"),
                "is_locked": row.get("is_locked", False),
                "acknowledged": row.get("acknowledged", False),
            }
        )
        grand_piece += Decimal(str(row["total_piece_wage"]))
        grand_payable += Decimal(str(row.get("payable_piece_wage", row["total_piece_wage"])))
        grand_total += Decimal(str(row.get("total_wage", row["total_piece_wage"])))
        grand_base += Decimal(str(row.get("base_salary") or 0))
        grand_qty += int(row.get("piece_qty") or 0)
        grand_logs += len(row["details"])
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
    return {
        "year_month": year_month,
        "is_locked": lock["is_locked"],
        "lock": lock,
        "items": items,
        "acknowledged_count": ack_count,
        "all_acknowledged": all_acknowledged,
        "unacknowledged": unacknowledged,
        "total_piece_wage": float(grand_piece),
        "total_wage": float(grand_total),
        "summary": {
            "count": len(items),
            "log_count": grand_logs,
            "piece_qty": grand_qty,
            "base_salary": float(grand_base),
            "total_piece_wage": float(grand_piece),
            "payable_piece_wage": float(grand_payable),
            "total_wage": float(grand_total),
        },
        "message": (
            f"{year_month} 在职工人 {len(items)} 人，"
            f"计件 ¥{grand_piece:.2f}，应发合计 ¥{grand_total:.2f}"
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
      quota_reduction（−）       底薪+计件模式下定额内折算扣减
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
    quota_reduction = Decimal("0")
    active_ids: set[int] = set()
    for item in payroll_items:
        worker_id = int(item["worker_id"])
        active_ids.add(worker_id)
        base = Decimal(str(item.get("base_salary") or 0))
        full = Decimal(str(item.get("total_piece_wage") or 0))
        payable = Decimal(str(item.get("payable_piece_wage") if item.get("payable_piece_wage") is not None else full))
        total = Decimal(str(item.get("total_wage") or 0))
        base_total += base
        piece_full_total += full
        piece_payable_total += payable
        payroll_total += total
        model = str(item.get("salary_model") or SalaryModel.pure_piece.value)
        if model == SalaryModel.fixed.value:
            fixed_piece_unpaid -= full
        elif model == SalaryModel.base_plus_piece.value:
            quota_reduction -= full - payable

    year, month = map(int, ym.split("-"))
    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
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
        qty = int((log.rework_qty if is_rework else log.qualified_qty) or 0)
        if qty <= 0:
            continue
        price = work_log_unit_price(db, tenant_id, log)
        amount = price * Decimal(qty)
        if is_rework and not rework_pays:
            # 返修报工锁价被存为 0（report_service 返修不计薪），
            # 对账侧用参考单价还原真实人工成本（工资侧仍为 0）。
            unpaid_rework_count += 1
            ref_price = price
            if ref_price <= 0:
                ref_price = get_labor_unit_price(db, tenant_id, log.own_product_id, log.process_id) or Decimal("0")
            unpaid_rework_amount += Decimal(ref_price) * Decimal(qty)
            continue
        labor_total += amount
        if log.worker_id not in active_ids:
            inactive_piece += amount

    variance_amount = payroll_total - labor_total
    buckets: dict[str, Decimal] = {}
    if base_total:
        buckets["base_salary"] = base_total
    if fixed_piece_unpaid:
        buckets["fixed_piece_unpaid"] = fixed_piece_unpaid
    if quota_reduction:
        buckets["quota_reduction"] = quota_reduction
    if inactive_piece:
        buckets["inactive_worker_logs"] = -inactive_piece
    bucket_sum = sum(buckets.values(), Decimal("0"))
    residual = variance_amount - bucket_sum
    if abs(residual) >= Decimal("0.005"):
        buckets["other"] = residual
    explained = abs(residual) < Decimal("0.005")
    breakdown_nonzero = [
        {"key": k, "amount": round(float(v), 4)}
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

    q = select(WorkLog).where(WorkLog.tenant_id == tenant_id)
    if worker_ids is not None:
        ids = list(worker_ids) if not isinstance(worker_ids, list) else worker_ids
        if not ids:
            return page_payload([], 0, page, page_size)
        q = q.where(WorkLog.worker_id.in_(ids))
    if worker_id:
        q = q.where(WorkLog.worker_id == worker_id)
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
    logs = db.scalars(q.order_by(WorkLog.id.desc()).offset(offset).limit(page_size)).all()

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
                "process_name": process.name if process else None,
                "report_type": report_type,
                "qualified_qty": log.qualified_qty,
                "defect_qty": log.defect_qty,
                "rework_qty": log.rework_qty,
                "unit_price": float(work_log_unit_price(db, tenant_id, log)),
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
    return page_payload(items, int(total), page, page_size)


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


def export_month_salary_csv(db: Session, tenant_id: int, year_month: str | None = None) -> str:
    """导出月结：汇总行 + 明细行，UTF-8 BOM 便于 Excel 打开。"""
    import csv
    import io

    overview = month_salary_all(db, tenant_id, year_month)
    year_month = overview["year_month"]
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["# 月结汇总", year_month])
    writer.writerow(
        ["工人ID", "姓名", "计薪方式", "报工条数", "计件量", "底薪", "计件全额", "计件应发", "应发合计"]
    )
    for item in overview["items"]:
        writer.writerow(
            [
                item["worker_id"],
                item["worker_name"],
                item.get("salary_model") or "",
                item["log_count"],
                item.get("piece_qty") or 0,
                f"{item.get('base_salary', 0):.2f}",
                f"{item['total_piece_wage']:.2f}",
                f"{item.get('payable_piece_wage', item['total_piece_wage']):.2f}",
                f"{item.get('total_wage', item['total_piece_wage']):.2f}",
            ]
        )
    writer.writerow([])
    writer.writerow(["# 计件明细"])
    writer.writerow(
        ["工人", "时间", "订单号", "产品", "工序", "类型", "合格", "返修", "不良", "单价", "金额"]
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
                    f"{d.get('amount', 0):.2f}",
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
            "",
            "",
            "",
            f"{overview['total_piece_wage']:.2f}",
            f"{overview.get('total_wage', overview['total_piece_wage']):.2f}",
        ]
    )
    return buf.getvalue()
