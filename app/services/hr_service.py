"""人事工资加减项：奖惩、迟到扣款自动生成。预支单独记在 salary_advances，不写入奖惩。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceDay,
    Employee,
    SalaryAdvance,
    SalaryMonthLock,
    WorkerAdjustment,
)
from app.services import attendance_rules as attendance_rules_service
from app.services.salary_service import assert_month_unlocked, is_month_locked

ADJUSTMENT_KINDS = {"reward", "penalty"}
ADJUSTMENT_CATEGORIES = {
    "full_attendance",
    "overtime",
    "late",
    "early",
    "other",
}
CATEGORY_LABELS = {
    "full_attendance": "全勤奖",
    "overtime": "加班奖",
    "late": "迟到扣款",
    "early": "早退扣款",
    "other": "其它",
}


def _ym_valid(year_month: str) -> str:
    ym = (year_month or "").strip()
    if len(ym) != 7 or ym[4] != "-":
        raise ValueError("year_month_invalid")
    year, month = ym.split("-")
    if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
        raise ValueError("year_month_invalid")
    return ym


def _money(v: Any) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _adj_payload(row: WorkerAdjustment, worker: Employee | None = None) -> dict:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "worker_name": worker.name if worker else None,
        "year_month": row.year_month,
        "kind": row.kind,
        "category": row.category,
        "category_label": CATEGORY_LABELS.get(row.category, row.category),
        "amount": float(row.amount or 0),
        "signed_amount": float(row.amount or 0) if row.kind == "reward" else -float(row.amount or 0),
        "title": row.title,
        "notes": row.notes,
        "occurred_on": row.occurred_on.isoformat() if row.occurred_on else None,
        "source": row.source,
        "advance_id": row.advance_id,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_adjustments(
    db: Session,
    tenant_id: int,
    *,
    year_month: str | None = None,
    worker_id: int | None = None,
    kind: str | None = None,
    category: str | None = None,
) -> dict:
    q = select(WorkerAdjustment).where(
        WorkerAdjustment.tenant_id == tenant_id,
        WorkerAdjustment.source != "advance",
        WorkerAdjustment.category != "advance_repay",
    )
    if year_month:
        q = q.where(WorkerAdjustment.year_month == _ym_valid(year_month))
    if worker_id is not None:
        q = q.where(WorkerAdjustment.worker_id == worker_id)
    if kind:
        q = q.where(WorkerAdjustment.kind == kind)
    if category:
        q = q.where(WorkerAdjustment.category == category)
    rows = db.scalars(q.order_by(WorkerAdjustment.id.desc())).all()
    workers = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_({r.worker_id for r in rows} or {0}),
            )
        ).all()
    }
    items = [_adj_payload(r, workers.get(r.worker_id)) for r in rows]
    reward_total = sum(i["amount"] for i in items if i["kind"] == "reward")
    penalty_total = sum(i["amount"] for i in items if i["kind"] == "penalty")
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "reward_total": round(reward_total, 2),
            "penalty_total": round(penalty_total, 2),
            "net": round(reward_total - penalty_total, 2),
        },
    }


def create_adjustment(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int,
    year_month: str,
    kind: str,
    amount: Decimal | float | int | str,
    category: str = "other",
    title: str | None = None,
    notes: str | None = None,
    occurred_on: date | None = None,
    created_by: int | None = None,
    source: str = "manual",
) -> dict:
    ym = _ym_valid(year_month)
    assert_month_unlocked(db, tenant_id, ym, action="登记奖惩")
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        raise ValueError("worker_not_found")
    if kind not in ADJUSTMENT_KINDS:
        raise ValueError("kind_invalid")
    cat = (category or "other").strip()
    if cat not in ADJUSTMENT_CATEGORIES:
        raise ValueError("category_invalid")
    money = _money(amount)
    if money <= 0:
        raise ValueError("amount_invalid")
    row = WorkerAdjustment(
        tenant_id=tenant_id,
        worker_id=worker_id,
        year_month=ym,
        kind=kind,
        category=cat,
        amount=money,
        title=(title or CATEGORY_LABELS.get(cat) or "").strip() or None,
        notes=(notes or "").strip() or None,
        occurred_on=occurred_on,
        source=source or "manual",
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _adj_payload(row, worker)


def update_adjustment(
    db: Session,
    tenant_id: int,
    adjustment_id: int,
    *,
    patch: dict,
) -> dict:
    row = db.get(WorkerAdjustment, adjustment_id)
    if not row or row.tenant_id != tenant_id:
        raise ValueError("not_found")
    if row.source != "manual":
        raise ValueError("auto_readonly")
    assert_month_unlocked(db, tenant_id, row.year_month, action="修改奖惩")
    if "kind" in patch:
        if patch["kind"] not in ADJUSTMENT_KINDS:
            raise ValueError("kind_invalid")
        row.kind = patch["kind"]
    if "category" in patch:
        cat = str(patch["category"] or "other")
        if cat not in ADJUSTMENT_CATEGORIES:
            raise ValueError("category_invalid")
        row.category = cat
    if "amount" in patch:
        money = _money(patch["amount"])
        if money <= 0:
            raise ValueError("amount_invalid")
        row.amount = money
    if "title" in patch:
        row.title = (str(patch["title"] or "").strip() or None)
    if "notes" in patch:
        row.notes = (str(patch["notes"] or "").strip() or None)
    if "occurred_on" in patch:
        raw = patch["occurred_on"]
        row.occurred_on = date.fromisoformat(raw) if raw else None
    if "year_month" in patch and patch["year_month"]:
        new_ym = _ym_valid(str(patch["year_month"]))
        assert_month_unlocked(db, tenant_id, new_ym, action="修改奖惩")
        row.year_month = new_ym
    db.commit()
    db.refresh(row)
    worker = db.get(Employee, row.worker_id)
    return _adj_payload(row, worker)


def _next_year_month(year_month: str) -> str:
    year, month = map(int, year_month.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def open_advance_month(db: Session, tenant_id: int, *, today: date | None = None) -> str:
    """未扣回预支挂在最近一期尚未结算的工资月。本月已结算则顺延到后面第一个未结算月。"""
    today = today or date.today()
    ym = f"{today.year:04d}-{today.month:02d}"
    for _ in range(24):
        row = db.scalar(
            select(SalaryMonthLock).where(
                SalaryMonthLock.tenant_id == tenant_id,
                SalaryMonthLock.year_month == ym,
            )
        )
        if not row or not (row.settle_through or row.is_locked):
            return ym
        ym = _next_year_month(ym)
    return ym


def _advance_repay_total(db: Session, tenant_id: int, worker_id: int, year_month: str) -> Decimal:
    """已归到该月的预支，加上挂在最近一期未结算工资上的待扣回。"""
    ym = _ym_valid(year_month)
    assigned = db.scalars(
        select(SalaryAdvance.amount).where(
            SalaryAdvance.tenant_id == tenant_id,
            SalaryAdvance.worker_id == worker_id,
            SalaryAdvance.repay_year_month == ym,
            SalaryAdvance.status != "void",
        )
    ).all()
    total = Decimal("0")
    for amt in assigned:
        total += Decimal(str(amt or 0))
    if ym != open_advance_month(db, tenant_id):
        return total
    year, month = map(int, ym.split("-"))
    month_end = date(year, month, monthrange(year, month)[1])
    pending = db.scalars(
        select(SalaryAdvance.amount).where(
            SalaryAdvance.tenant_id == tenant_id,
            SalaryAdvance.worker_id == worker_id,
            SalaryAdvance.status == "open",
            SalaryAdvance.repay_year_month.is_(None),
            SalaryAdvance.advanced_at <= month_end,
        )
    ).all()
    for amt in pending:
        total += Decimal(str(amt or 0))
    return total


def delete_adjustment(db: Session, tenant_id: int, adjustment_id: int) -> None:
    row = db.get(WorkerAdjustment, adjustment_id)
    if not row or row.tenant_id != tenant_id:
        raise ValueError("not_found")
    assert_month_unlocked(db, tenant_id, row.year_month, action="删除奖惩")
    db.delete(row)
    db.commit()


def sum_adjustments_for_worker(
    db: Session, tenant_id: int, worker_id: int, year_month: str
) -> dict:
    rows = db.scalars(
        select(WorkerAdjustment).where(
            WorkerAdjustment.tenant_id == tenant_id,
            WorkerAdjustment.worker_id == worker_id,
            WorkerAdjustment.year_month == year_month,
        )
    ).all()
    reward = Decimal("0")
    penalty = Decimal("0")  # 手工惩罚等（不含迟到）
    late = Decimal("0")
    by_category: dict[str, float] = {}
    items = []
    for r in rows:
        # 历史预支扣回行不再参与奖惩，工资扣回只认 salary_advances
        if r.source == "advance" or r.category == "advance_repay":
            continue
        amt = Decimal(str(r.amount or 0))
        if r.kind == "reward":
            reward += amt
        elif r.category == "late":
            late += amt
        else:
            penalty += amt
        by_category[r.category] = by_category.get(r.category, 0) + float(amt)
        items.append(_adj_payload(r))
    advance_repay = _advance_repay_total(db, tenant_id, worker_id, year_month)
    net = reward - penalty - late - advance_repay
    return {
        "reward_total": float(reward),
        "penalty_total": float(penalty),
        "late_deduction": float(late),
        "advance_repay": float(advance_repay),
        "adjustment_net": float(net),
        "by_category": by_category,
        "items": items,
    }


def _advance_payload(row: SalaryAdvance, worker: Employee | None = None) -> dict:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "worker_name": worker.name if worker else None,
        "amount": float(row.amount or 0),
        "advanced_at": row.advanced_at.isoformat() if row.advanced_at else None,
        "repay_year_month": row.repay_year_month,
        "status": row.status,
        "fund_account": row.fund_account,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "voided_at": row.voided_at.isoformat() if row.voided_at else None,
    }


def list_advances(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int | None = None,
    status: str | None = None,
) -> dict:
    q = select(SalaryAdvance).where(SalaryAdvance.tenant_id == tenant_id)
    if worker_id is not None:
        q = q.where(SalaryAdvance.worker_id == worker_id)
    scoped = db.scalars(q.order_by(SalaryAdvance.id.desc())).all()
    open_total = sum(float(r.amount or 0) for r in scoped if r.status == "open")
    repay_total = sum(float(r.amount or 0) for r in scoped if r.status != "void")
    rows = [r for r in scoped if not status or r.status == status]
    workers = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_({r.worker_id for r in rows} or {0}),
            )
        ).all()
    }
    items = [_advance_payload(r, workers.get(r.worker_id)) for r in rows]
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "open_total": round(open_total, 2),
            "repay_total": round(repay_total, 2),
        },
    }


def create_advance(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int,
    amount: Decimal | float | int | str,
    advanced_at: date | None = None,
    notes: str | None = None,
    created_by: int | None = None,
    fund_account: str | None = None,
) -> dict:
    worker = db.get(Employee, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        raise ValueError("worker_not_found")
    money = _money(amount)
    if money <= 0:
        raise ValueError("amount_invalid")
    when = advanced_at or date.today()
    adv = SalaryAdvance(
        tenant_id=tenant_id,
        worker_id=worker_id,
        amount=money,
        advanced_at=when,
        status="open",
        fund_account=fund_account,
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )
    db.add(adv)
    db.flush()
    from app.services import ledger_service

    ledger_service.post_advance(
        db,
        tenant_id,
        advance_id=adv.id,
        worker_name=worker.name,
        amount=money,
        advanced_at=when,
        fund_account=fund_account,
    )
    db.commit()
    db.refresh(adv)
    return _advance_payload(adv, worker)


def void_advance(db: Session, tenant_id: int, advance_id: int) -> dict:
    adv = db.get(SalaryAdvance, advance_id)
    if not adv or adv.tenant_id != tenant_id:
        raise ValueError("not_found")
    if adv.status == "void":
        return _advance_payload(adv, db.get(Employee, adv.worker_id))
    if adv.status == "repaid":
        raise ValueError("advance_already_repaid")
    adv.status = "void"
    adv.voided_at = datetime.utcnow()
    from app.services import ledger_service

    ledger_service.void_advance_entry(db, tenant_id, adv.id)
    db.commit()
    db.refresh(adv)
    return _advance_payload(adv, db.get(Employee, adv.worker_id))


def mark_advances_repaid_for_month(
    db: Session,
    tenant_id: int,
    year_month: str,
    *,
    through: date | None = None,
) -> int:
    """发工资结算时，把截至结算日仍未扣回的预支归到这一期。"""
    ym = _ym_valid(year_month)
    year, month = map(int, ym.split("-"))
    month_end = date(year, month, monthrange(year, month)[1])
    cutoff = through or month_end
    rows = db.scalars(
        select(SalaryAdvance).where(
            SalaryAdvance.tenant_id == tenant_id,
            SalaryAdvance.status == "open",
            or_(
                SalaryAdvance.repay_year_month.is_(None),
                SalaryAdvance.repay_year_month == ym,
            ),
            SalaryAdvance.advanced_at <= cutoff,
        )
    ).all()
    for r in rows:
        r.status = "repaid"
        r.repay_year_month = ym
    return len(rows)


def rebuild_late_deductions(
    db: Session,
    tenant_id: int,
    year_month: str,
    *,
    created_by: int | None = None,
) -> dict:
    """按考勤规则重算当月迟到/早退扣款（覆盖 source=auto_late 的自动项）。"""
    ym = _ym_valid(year_month)
    assert_month_unlocked(db, tenant_id, ym, action="重算迟到扣款")
    year, month = map(int, ym.split("-"))
    last_day = monthrange(year, month)[1]
    date_from = date(year, month, 1)
    date_to = date(year, month, last_day)

    rules = attendance_rules_service.get_attendance_rules_by_tenant_id(db, tenant_id)
    late_cfg = rules.get("late_early_deduction") or {}
    if not late_cfg.get("enabled"):
        deleted = db.execute(
            delete(WorkerAdjustment).where(
                WorkerAdjustment.tenant_id == tenant_id,
                WorkerAdjustment.year_month == ym,
                WorkerAdjustment.source == "auto_late",
            )
        )
        db.commit()
        return {"enabled": False, "cleared": deleted.rowcount or 0, "workers": 0, "total_amount": 0.0}

    db.execute(
        delete(WorkerAdjustment).where(
            WorkerAdjustment.tenant_id == tenant_id,
            WorkerAdjustment.year_month == ym,
            WorkerAdjustment.source == "auto_late",
        )
    )

    days = db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.work_date >= date_from,
            AttendanceDay.work_date <= date_to,
        )
    ).all()
    by_worker: dict[int, list[AttendanceDay]] = {}
    for d in days:
        by_worker.setdefault(d.employee_id, []).append(d)

    workers = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_(set(by_worker.keys()) or {0}),
            )
        ).all()
    }

    created = 0
    total_amount = Decimal("0")
    for worker_id, day_rows in by_worker.items():
        worker = workers.get(worker_id)
        day_wage = Decimal("0")
        if worker and worker.base_salary:
            day_wage = (Decimal(str(worker.base_salary)) / Decimal("26")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        free_used = 0
        month_total = Decimal("0")
        for day in sorted(day_rows, key=lambda x: x.work_date):
            late_m = int(day.late_minutes or 0)
            early_m = int(getattr(day, "early_leave_minutes", 0) or 0)
            if late_m <= 0 and early_m <= 0:
                continue
            result = attendance_rules_service.calc_late_early_deduction(
                rules,
                late_minutes=late_m,
                early_minutes=early_m,
                day_wage=day_wage,
                monthly_free_used=free_used,
            )
            for it in result.get("items") or []:
                if it.get("skipped") == "monthly_free":
                    free_used += 1
            amt = Decimal(str(result.get("total_amount") or 0))
            if amt > 0:
                month_total += amt
        if month_total <= 0:
            continue
        db.add(
            WorkerAdjustment(
                tenant_id=tenant_id,
                worker_id=worker_id,
                year_month=ym,
                kind="penalty",
                category="late",
                amount=month_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                title="迟到/早退扣款",
                notes="考勤规则自动生成",
                source="auto_late",
                created_by=created_by,
            )
        )
        created += 1
        total_amount += month_total

    db.commit()
    return {
        "enabled": True,
        "workers": created,
        "total_amount": float(total_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "year_month": ym,
        "is_locked": is_month_locked(db, tenant_id, ym),
    }