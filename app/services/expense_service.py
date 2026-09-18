"""日常开支：公司内部费用流水记账（单头 + 明细）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import DailyExpense, DailyExpenseLine, Department, Employee, PaymentStatus

# 旧版固定编码 → 中文（仅用于展示兼容）
_LEGACY_CATEGORY_LABELS: dict[str, str] = {
    "airfare": "飞机票",
    "train": "火车票",
    "taxi": "的士费",
    "lodging": "住宿费",
    "meals": "餐饮费",
    "gift": "礼品费",
    "activity": "活动费",
    "telecom": "通讯费",
    "allowance": "补助",
    "dev_purchase": "开发采购",
    "other": "其它",
    "office": "办公",
    "utilities": "水电物业",
    "rent": "租金",
    "travel": "差旅",
    "entertainment": "招待",
    "logistics": "物流运费",
    "maintenance": "维修保养",
}

DEFAULT_CATEGORIES: list[str] = [
    "办公",
    "通讯费",
    "补助",
    "维修保养",
    "飞机票",
    "火车票",
    "的士费",
    "住宿费",
    "餐饮费",
    "礼品费",
    "活动费",
    "开发采购",
    "其它",
]

_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ["", "拾", "佰", "仟"]
_CN_SECTIONS = ["", "万", "亿"]


def amount_to_cn(amount: Decimal | float | int | str) -> str:
    """金额转中文大写，如 123.45 → 壹佰贰拾叁元肆角伍分。"""
    try:
        money = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        money = Decimal("0.00")
    if money < 0:
        money = -money
        sign = "负"
    else:
        sign = ""
    if money == 0:
        return "零圆"

    yuan = int(money)
    fen = int((money - yuan) * 100)
    parts: list[str] = []

    def _section(n: int) -> str:
        if n == 0:
            return ""
        s = ""
        zero = False
        for i, unit in enumerate(_CN_UNITS):
            d = n % 10
            n //= 10
            if d == 0:
                if s:
                    zero = True
            else:
                if zero:
                    s = _CN_DIGITS[0] + s
                    zero = False
                s = _CN_DIGITS[d] + unit + s
            if n == 0:
                break
        return s

    if yuan == 0:
        parts.append("零圆")
    else:
        sections: list[str] = []
        sec_i = 0
        n = yuan
        while n > 0:
            sec = n % 10000
            n //= 10000
            if sec:
                sections.append(_section(sec) + _CN_SECTIONS[sec_i])
            elif sections:
                sections.append("")
            sec_i += 1
        text = ""
        need_zero = False
        for sec in reversed(sections):
            if not sec:
                need_zero = True
                continue
            if need_zero and not text.endswith(_CN_DIGITS[0]):
                text += _CN_DIGITS[0]
            text += sec
            need_zero = False
        parts.append(text + "圆")

    jiao = fen // 10
    fen_d = fen % 10
    if jiao == 0 and fen_d == 0:
        if yuan > 0:
            parts.append("整")
    else:
        if jiao:
            parts.append(_CN_DIGITS[jiao] + "角")
        elif yuan > 0 and fen_d:
            parts.append(_CN_DIGITS[0])
        if fen_d:
            parts.append(_CN_DIGITS[fen_d] + "分")
    return sign + "".join(parts)


def _money(amount: Decimal | float | int | str) -> Decimal:
    try:
        money = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise ValueError("amount_invalid") from err
    if money <= 0:
        raise ValueError("amount_invalid")
    return money


def _category_valid(category: str | None) -> str:
    text = (category or "").strip()
    if not text:
        raise ValueError("category_required")
    if len(text) > 100:
        raise ValueError("category_too_long")
    return text


def _category_label(category: str | None) -> str:
    cat = (category or "").strip()
    if not cat:
        return "—"
    return _LEGACY_CATEGORY_LABELS.get(cat, cat)


def _resolve_department(db: Session, tenant_id: int, department_id: int | None) -> Department:
    if not department_id:
        raise ValueError("department_required")
    dept = db.scalars(
        select(Department).where(Department.tenant_id == tenant_id, Department.id == department_id)
    ).first()
    if not dept:
        raise ValueError("department_not_found")
    return dept


def _resolve_employee(db: Session, tenant_id: int, employee_id: int | None) -> Employee:
    if not employee_id:
        raise ValueError("employee_required")
    emp = db.scalars(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.id == employee_id)
    ).first()
    if not emp:
        raise ValueError("employee_not_found")
    return emp


def _line_payload(line: DailyExpenseLine) -> dict:
    cat = line.category or ""
    return {
        "id": line.id,
        "sort_order": int(line.sort_order or 0),
        "category": cat,
        "category_label": _category_label(cat),
        "category_image_urls": list(line.category_image_urls or []),
        "occurred_on": line.occurred_on.isoformat() if line.occurred_on else None,
        "amount": float(line.amount or 0),
        "description": line.description,
        "invoice_urls": list(line.invoice_urls or []),
        "receipt_urls": list(line.receipt_urls or []),
    }


def _expense_payload(
    row: DailyExpense,
    *,
    creator: Employee | None = None,
    department: Department | None = None,
    employee: Employee | None = None,
    include_lines: bool = True,
) -> dict:
    status = row.status.value if isinstance(row.status, PaymentStatus) else str(row.status or "")
    lines = [_line_payload(l) for l in (row.lines or [])] if include_lines else []
    amount = float(row.amount or 0)
    return {
        "id": row.id,
        "department_id": row.department_id,
        "department_name": department.name if department else None,
        "employee_id": row.employee_id,
        "employee_name": employee.name if employee else None,
        "reason": row.reason,
        "expense_date": row.expense_date.isoformat() if row.expense_date else None,
        "amount": amount,
        "amount_cn": amount_to_cn(amount),
        "fund_account": row.fund_account,
        "status": status,
        "line_count": len(row.lines or []) if include_lines else None,
        "lines": lines,
        "created_by": row.created_by,
        "created_by_name": creator.name if creator else None,
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds") if row.created_at else None,
        "voided_at": row.voided_at.isoformat(sep=" ", timespec="seconds") if row.voided_at else None,
    }


def _lookup_maps(
    db: Session,
    tenant_id: int,
    rows: list[DailyExpense],
) -> tuple[dict[int, Employee], dict[int, Department], dict[int, Employee]]:
    creator_ids = {r.created_by for r in rows if r.created_by}
    employee_ids = {r.employee_id for r in rows if r.employee_id}
    department_ids = {r.department_id for r in rows if r.department_id}
    all_emp_ids = creator_ids | employee_ids
    employees = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_(all_emp_ids or {0}),
            )
        ).all()
    }
    departments = {
        d.id: d
        for d in db.scalars(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.id.in_(department_ids or {0}),
            )
        ).all()
    }
    creators = {i: employees[i] for i in creator_ids if i in employees}
    reimbursers = {i: employees[i] for i in employee_ids if i in employees}
    return creators, departments, reimbursers


def list_category_suggestions(db: Session, tenant_id: int) -> dict:
    """返回费用类型建议：历史优先，再补默认项。"""
    q = (
        select(DailyExpenseLine.category)
        .join(DailyExpense, DailyExpense.id == DailyExpenseLine.expense_id)
        .where(
            DailyExpenseLine.tenant_id == tenant_id,
            DailyExpense.tenant_id == tenant_id,
            DailyExpenseLine.category.is_not(None),
            DailyExpenseLine.category != "",
        )
        .order_by(DailyExpenseLine.id.desc())
    )
    seen: list[str] = []
    for raw in db.scalars(q).all():
        label = _category_label(str(raw))
        if label and label not in seen:
            seen.append(label)
        if len(seen) >= 50:
            break
    for item in DEFAULT_CATEGORIES:
        if item not in seen:
            seen.append(item)
    return {"items": seen}


def list_expenses(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
) -> dict:
    q = (
        select(DailyExpense)
        .where(DailyExpense.tenant_id == tenant_id)
        .options(selectinload(DailyExpense.lines))
    )
    if date_from is not None or date_to is not None:
        line_q = select(DailyExpenseLine.expense_id).where(DailyExpenseLine.tenant_id == tenant_id)
        if date_from is not None:
            line_q = line_q.where(DailyExpenseLine.occurred_on >= date_from)
        if date_to is not None:
            line_q = line_q.where(DailyExpenseLine.occurred_on <= date_to)
        q = q.where(DailyExpense.id.in_(line_q))
    if department_id:
        q = q.where(DailyExpense.department_id == department_id)
    if employee_id:
        q = q.where(DailyExpense.employee_id == employee_id)
    if status:
        try:
            st = PaymentStatus(status)
        except ValueError as err:
            raise ValueError("status_invalid") from err
        q = q.where(DailyExpense.status == st)
    if category:
        cat = (category or "").strip()
        if cat:
            legacy_codes = [k for k, v in _LEGACY_CATEGORY_LABELS.items() if v == cat]
            candidates = list({cat, *legacy_codes})
            q = q.where(
                DailyExpense.id.in_(
                    select(DailyExpenseLine.expense_id).where(
                        DailyExpenseLine.tenant_id == tenant_id,
                        DailyExpenseLine.category.in_(candidates),
                    )
                )
            )
    rows = db.scalars(q.order_by(DailyExpense.created_at.desc(), DailyExpense.id.desc())).all()
    creators, departments, reimbursers = _lookup_maps(db, tenant_id, list(rows))
    items = [
        _expense_payload(
            r,
            creator=creators.get(r.created_by) if r.created_by else None,
            department=departments.get(r.department_id) if r.department_id else None,
            employee=reimbursers.get(r.employee_id) if r.employee_id else None,
        )
        for r in rows
    ]
    posted_total = sum(i["amount"] for i in items if i["status"] == PaymentStatus.posted.value)
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "posted_total": round(posted_total, 2),
            "posted_total_cn": amount_to_cn(posted_total),
        },
    }


def get_expense(db: Session, tenant_id: int, expense_id: int) -> dict:
    row = db.scalars(
        select(DailyExpense)
        .where(DailyExpense.tenant_id == tenant_id, DailyExpense.id == expense_id)
        .options(selectinload(DailyExpense.lines))
    ).first()
    if not row:
        raise ValueError("not_found")
    creators, departments, reimbursers = _lookup_maps(db, tenant_id, [row])
    return _expense_payload(
        row,
        creator=creators.get(row.created_by) if row.created_by else None,
        department=departments.get(row.department_id) if row.department_id else None,
        employee=reimbursers.get(row.employee_id) if row.employee_id else None,
    )


def create_expense(
    db: Session,
    tenant_id: int,
    *,
    department_id: int,
    employee_id: int,
    reason: str | None,
    lines: list[dict],
    created_by: int | None = None,
    fund_account: str | None = None,
) -> dict:
    if not lines:
        raise ValueError("lines_required")
    dept = _resolve_department(db, tenant_id, department_id)
    emp = _resolve_employee(db, tenant_id, employee_id)

    def _urls(raw_list: object) -> list[str]:
        return [str(u).strip() for u in (raw_list or []) if str(u).strip()][:9]

    parsed_lines: list[tuple[str, list[str], date, Decimal, str | None, list[str], list[str]]] = []
    for raw in lines:
        cat = _category_valid(raw.get("category"))
        occurred = raw.get("occurred_on")
        if not isinstance(occurred, date):
            raise ValueError("occurred_on_required")
        money = _money(raw.get("amount"))
        desc = (raw.get("description") or "").strip() or None
        cat_images = _urls(raw.get("category_image_urls"))
        # 兼容旧字段 attachment_urls → 归入收据
        invoices = _urls(raw.get("invoice_urls"))
        receipts = _urls(raw.get("receipt_urls"))
        if not invoices and not receipts:
            receipts = _urls(raw.get("attachment_urls"))
        parsed_lines.append((cat, cat_images, occurred, money, desc, invoices, receipts))

    total = sum((m for _, _, _, m, _, _, _ in parsed_lines), Decimal("0")).quantize(Decimal("0.01"))
    expense_date = min(d for _, _, d, _, _, _, _ in parsed_lines)
    header = DailyExpense(
        tenant_id=tenant_id,
        kind="daily",
        department_id=dept.id,
        employee_id=emp.id,
        reason=(reason or "").strip() or None,
        expense_date=expense_date,
        amount=total,
        fund_account=fund_account,
        status=PaymentStatus.posted,
        created_by=created_by,
    )
    db.add(header)
    db.flush()
    for i, (cat, cat_images, occurred, money, desc, invoices, receipts) in enumerate(parsed_lines):
        db.add(
            DailyExpenseLine(
                tenant_id=tenant_id,
                expense_id=header.id,
                sort_order=i,
                category=cat,
                category_image_urls=cat_images or None,
                occurred_on=occurred,
                amount=money,
                description=desc,
                invoice_urls=invoices or None,
                receipt_urls=receipts or None,
            )
        )
    from app.services import ledger_service

    ledger_service.post_daily_expense(
        db,
        tenant_id,
        expense_id=header.id,
        amount=total,
        expense_date=expense_date,
        reason=header.reason,
        employee_name=emp.name,
        fund_account=fund_account,
    )
    db.commit()
    return get_expense(db, tenant_id, header.id)


def void_expense(db: Session, tenant_id: int, expense_id: int) -> dict:
    row = db.scalars(
        select(DailyExpense)
        .where(DailyExpense.tenant_id == tenant_id, DailyExpense.id == expense_id)
        .options(selectinload(DailyExpense.lines))
    ).first()
    if not row:
        raise ValueError("not_found")
    creators, departments, reimbursers = _lookup_maps(db, tenant_id, [row])
    payload_kw = dict(
        creator=creators.get(row.created_by) if row.created_by else None,
        department=departments.get(row.department_id) if row.department_id else None,
        employee=reimbursers.get(row.employee_id) if row.employee_id else None,
    )
    if row.status == PaymentStatus.void:
        return _expense_payload(row, **payload_kw)
    row.status = PaymentStatus.void
    row.voided_at = datetime.utcnow()
    from app.services import ledger_service

    ledger_service.void_daily_expense_entry(db, tenant_id, row.id)
    db.commit()
    db.refresh(row)
    return _expense_payload(row, **payload_kw)
