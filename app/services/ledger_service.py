"""总账经营流水：一笔业务一行（正=进，负=出）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessLedgerEntry, PaymentMethod

BIZ_TYPE_LABELS: dict[str, str] = {
    "payment": "收款登记",
    "supplier_payment": "付款登记",
    "salary": "工资",
    "daily_expense": "日常开支",
    "advance": "预支",
    # 历史挂账类（不再新写入，仅兼容旧流水展示）
    "shipment": "出货(挂账)",
    "payable": "采购挂账",
}

# 总账口径：只认真实收付，不以出货/采购挂账入账
CASH_BIZ_TYPES = ("payment", "supplier_payment", "salary", "daily_expense", "advance")


FUND_ACCOUNT_LABELS: dict[str, str] = {
    PaymentMethod.bank.value: "银行",
    PaymentMethod.cash.value: "现金",
    PaymentMethod.wechat.value: "微信",
    PaymentMethod.alipay.value: "支付宝",
    PaymentMethod.other.value: "其它",
}

SOURCE_SHIPMENT = "shipment"
SOURCE_PAYMENT = "payment"
SOURCE_PAYABLE = "payable"
SOURCE_SUPPLIER_PAYMENT = "supplier_payment"
SOURCE_SALARY_MONTH = "salary_month"
SOURCE_DAILY_EXPENSE = "daily_expense"
SOURCE_ADVANCE = "advance"


def fund_account_label(code: str | None) -> str | None:
    if not code:
        return None
    return FUND_ACCOUNT_LABELS.get(code, code)


def normalize_fund_account(raw: str | None) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip()
    if not code:
        return None
    if code in PaymentMethod.__members__:
        return code
    if code in {m.value for m in PaymentMethod}:
        return code
    return PaymentMethod.other.value


def _money(amount: Decimal | float | int | str) -> Decimal:
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _split_amounts(biz_type: str, amount: float) -> tuple[float, float, float]:
    """拆成 进帐 / 计件提成 / 出账（绝对值；工资走计件提成列）。"""
    money = float(amount or 0)
    if money > 0:
        return round(money, 2), 0.0, 0.0
    if money < 0:
        abs_m = round(abs(money), 2)
        if biz_type == "salary":
            return 0.0, abs_m, 0.0
        return 0.0, 0.0, abs_m
    return 0.0, 0.0, 0.0


def _entry_out(row: BusinessLedgerEntry, *, balance: float | None = None) -> dict:
    amount = float(row.amount or 0)
    amount_in, amount_piece, amount_out = _split_amounts(row.biz_type or "", amount)
    return {
        "id": row.id,
        "entry_date": row.entry_date.isoformat() if row.entry_date else None,
        "biz_type": row.biz_type,
        "biz_type_label": BIZ_TYPE_LABELS.get(row.biz_type, row.biz_type),
        "summary": row.summary,
        "amount": amount,
        "amount_in": amount_in,
        "amount_piece": amount_piece,
        "amount_out": amount_out,
        "balance": None if balance is None else round(float(balance), 2),
        "fund_account": row.fund_account,
        "fund_account_label": fund_account_label(row.fund_account),
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "year_month": row.year_month,
        "status": row.status,
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds") if row.created_at else None,
        "voided_at": row.voided_at.isoformat(sep=" ", timespec="seconds") if row.voided_at else None,
    }


def _find_by_source(
    db: Session, tenant_id: int, source_type: str, source_id: int
) -> BusinessLedgerEntry | None:
    return db.scalar(
        select(BusinessLedgerEntry).where(
            BusinessLedgerEntry.tenant_id == tenant_id,
            BusinessLedgerEntry.source_type == source_type,
            BusinessLedgerEntry.source_id == source_id,
        )
    )


def upsert_entry(
    db: Session,
    tenant_id: int,
    *,
    entry_date: date,
    biz_type: str,
    summary: str,
    amount: Decimal | float | int | str,
    source_type: str,
    source_id: int,
    source_no: str | None = None,
    fund_account: str | None = None,
    year_month: str | None = None,
    commit: bool = False,
) -> BusinessLedgerEntry:
    """写入或复活一条流水（同一来源唯一）。不主动 commit，除非 commit=True。"""
    money = _money(amount)
    row = _find_by_source(db, tenant_id, source_type, source_id)
    if row is None:
        row = BusinessLedgerEntry(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
        )
        db.add(row)
    row.entry_date = entry_date
    row.biz_type = biz_type
    row.summary = (summary or "").strip()[:255] or BIZ_TYPE_LABELS.get(biz_type, biz_type)
    row.amount = money
    row.fund_account = normalize_fund_account(fund_account)
    row.source_no = (source_no or "").strip()[:80] or None
    row.year_month = year_month
    row.status = "posted"
    row.voided_at = None
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def void_by_source(
    db: Session,
    tenant_id: int,
    source_type: str,
    source_id: int,
    *,
    commit: bool = False,
) -> BusinessLedgerEntry | None:
    row = _find_by_source(db, tenant_id, source_type, source_id)
    if not row:
        return None
    if row.status == "void":
        return row
    row.status = "void"
    row.voided_at = datetime.now()
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


# ── 业务挂钩（金额符号：正=进，负=出）────────────────────────────────


def post_shipment(
    db: Session,
    tenant_id: int,
    *,
    shipment_id: int,
    shipment_no: str,
    customer_name: str,
    amount: Decimal | float | int | str,
    ship_date: date,
) -> BusinessLedgerEntry:
    money = abs(_money(amount))
    return upsert_entry(
        db,
        tenant_id,
        entry_date=ship_date,
        biz_type="shipment",
        summary=f"出货 {shipment_no} · {customer_name} · 应收账款增加",
        amount=money,
        source_type=SOURCE_SHIPMENT,
        source_id=shipment_id,
        source_no=shipment_no,
    )


def void_shipment_entry(db: Session, tenant_id: int, shipment_id: int) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_SHIPMENT, shipment_id)


def post_payment(
    db: Session,
    tenant_id: int,
    *,
    payment_id: int,
    customer_name: str,
    amount: Decimal | float | int | str,
    payment_date: date,
    fund_account: str | None = None,
    voucher_no: str | None = None,
) -> BusinessLedgerEntry:
    money = abs(_money(amount))
    acct = fund_account_label(normalize_fund_account(fund_account)) or "资金账户"
    ref = voucher_no or f"SK-{payment_id}"
    return upsert_entry(
        db,
        tenant_id,
        entry_date=payment_date,
        biz_type="payment",
        summary=f"收款登记 {ref} · {customer_name} · {acct}增加",
        amount=money,
        source_type=SOURCE_PAYMENT,
        source_id=payment_id,
        source_no=ref,
        fund_account=fund_account,
    )


def void_payment_entry(db: Session, tenant_id: int, payment_id: int) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_PAYMENT, payment_id)


def post_payable(
    db: Session,
    tenant_id: int,
    *,
    payable_id: int,
    supplier_name: str,
    amount: Decimal | float | int | str,
    payable_date: date,
    source_no: str | None = None,
) -> BusinessLedgerEntry:
    money = -abs(_money(amount))
    ref = source_no or f"YF-{payable_id}"
    return upsert_entry(
        db,
        tenant_id,
        entry_date=payable_date,
        biz_type="payable",
        summary=f"采购挂账 {ref} · {supplier_name} · 应付账款增加",
        amount=money,
        source_type=SOURCE_PAYABLE,
        source_id=payable_id,
        source_no=ref,
    )


def void_payable_entry(db: Session, tenant_id: int, payable_id: int) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_PAYABLE, payable_id)


def post_supplier_payment(
    db: Session,
    tenant_id: int,
    *,
    payment_id: int,
    supplier_name: str,
    amount: Decimal | float | int | str,
    payment_date: date,
    fund_account: str | None = None,
    voucher_no: str | None = None,
) -> BusinessLedgerEntry:
    money = -abs(_money(amount))
    acct = fund_account_label(normalize_fund_account(fund_account)) or "资金账户"
    ref = voucher_no or f"FK-{payment_id}"
    return upsert_entry(
        db,
        tenant_id,
        entry_date=payment_date,
        biz_type="supplier_payment",
        summary=f"付款登记 {ref} · {supplier_name} · {acct}减少",
        amount=money,
        source_type=SOURCE_SUPPLIER_PAYMENT,
        source_id=payment_id,
        source_no=ref,
        fund_account=fund_account,
    )


def void_supplier_payment_entry(
    db: Session, tenant_id: int, payment_id: int
) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_SUPPLIER_PAYMENT, payment_id)


def post_daily_expense(
    db: Session,
    tenant_id: int,
    *,
    expense_id: int,
    amount: Decimal | float | int | str,
    expense_date: date,
    reason: str | None = None,
    employee_name: str | None = None,
    fund_account: str | None = None,
) -> BusinessLedgerEntry:
    money = -abs(_money(amount))
    who = employee_name or "—"
    why = (reason or "").strip() or "日常开支"
    acct = fund_account_label(normalize_fund_account(fund_account))
    tail = f" · {acct}减少" if acct else ""
    return upsert_entry(
        db,
        tenant_id,
        entry_date=expense_date,
        biz_type="daily_expense",
        summary=f"日常开支 #{expense_id} · {who} · {why}{tail}",
        amount=money,
        source_type=SOURCE_DAILY_EXPENSE,
        source_id=expense_id,
        source_no=f"EXP-{expense_id}",
        fund_account=fund_account,
    )


def void_daily_expense_entry(
    db: Session, tenant_id: int, expense_id: int
) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_DAILY_EXPENSE, expense_id)


def post_advance(
    db: Session,
    tenant_id: int,
    *,
    advance_id: int,
    worker_name: str,
    amount: Decimal | float | int | str,
    advanced_at: date,
    fund_account: str | None = None,
) -> BusinessLedgerEntry:
    money = -abs(_money(amount))
    acct = fund_account_label(normalize_fund_account(fund_account))
    tail = f" · {acct}减少" if acct else ""
    return upsert_entry(
        db,
        tenant_id,
        entry_date=advanced_at,
        biz_type="advance",
        summary=f"预支发放 #{advance_id} · {worker_name}{tail}",
        amount=money,
        source_type=SOURCE_ADVANCE,
        source_id=advance_id,
        source_no=f"ADV-{advance_id}",
        fund_account=fund_account,
    )


def void_advance_entry(db: Session, tenant_id: int, advance_id: int) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_ADVANCE, advance_id)


def post_salary_month(
    db: Session,
    tenant_id: int,
    *,
    lock_id: int,
    year_month: str,
    total_wage: Decimal | float | int | str,
    settle_through: date | None = None,
    worker_count: int = 0,
) -> BusinessLedgerEntry:
    money = -abs(_money(total_wage))
    entry_date = settle_through or date.fromisoformat(f"{year_month}-01")
    if settle_through is None:
        # 用月末日
        y, m = map(int, year_month.split("-"))
        from calendar import monthrange

        entry_date = date(y, m, monthrange(y, m)[1])
    who = f"{worker_count} 人" if worker_count else "全员"
    return upsert_entry(
        db,
        tenant_id,
        entry_date=entry_date,
        biz_type="salary",
        summary=f"工资月结 {year_month} · {who}应发合计",
        amount=money,
        source_type=SOURCE_SALARY_MONTH,
        source_id=lock_id,
        source_no=f"SAL-{year_month}",
        year_month=year_month,
    )


def void_salary_month_entry(
    db: Session, tenant_id: int, lock_id: int
) -> BusinessLedgerEntry | None:
    return void_by_source(db, tenant_id, SOURCE_SALARY_MONTH, lock_id)


def list_entries(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    biz_type: str | None = None,
    status: str | None = "posted",
    include_void: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> dict:
    from app.schemas.common import normalize_page

    q = select(BusinessLedgerEntry).where(BusinessLedgerEntry.tenant_id == tenant_id)
    if date_from is not None:
        q = q.where(BusinessLedgerEntry.entry_date >= date_from)
    if date_to is not None:
        q = q.where(BusinessLedgerEntry.entry_date <= date_to)
    if biz_type:
        q = q.where(BusinessLedgerEntry.biz_type == biz_type)
    if status:
        q = q.where(BusinessLedgerEntry.status == status)
    elif not include_void:
        q = q.where(BusinessLedgerEntry.status == "posted")
    # 先按时间正序算余额，再倒序展示（最新在上）
    rows = list(
        db.scalars(
            q.order_by(BusinessLedgerEntry.entry_date.asc(), BusinessLedgerEntry.id.asc())
        ).all()
    )
    running = 0.0
    items_asc: list[dict] = []
    for r in rows:
        amount = float(r.amount or 0)
        bal = None
        if r.status == "posted":
            running += amount
            bal = running
        items_asc.append(_entry_out(r, balance=bal))
    items_all = list(reversed(items_asc))
    inflow = sum(i["amount_in"] for i in items_all if i["status"] == "posted")
    piece = sum(i["amount_piece"] for i in items_all if i["status"] == "posted")
    outflow = sum(i["amount_out"] for i in items_all if i["status"] == "posted")
    total = len(items_all)
    if page is not None or page_size is not None:
        page, page_size, offset = normalize_page(page or 1, page_size or 20)
        items = items_all[offset : offset + page_size]
    else:
        page, page_size = 1, total or 20
        items = items_all
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "count": total,
            "inflow": round(inflow, 2),
            "piece": round(piece, 2),
            "outflow": round(-outflow, 2),
            "net": round(inflow - piece - outflow, 2),
            "balance": round(running, 2),
        },
        "biz_types": [{"value": k, "label": BIZ_TYPE_LABELS[k]} for k in CASH_BIZ_TYPES],
        "fund_accounts": [{"value": k, "label": v} for k, v in FUND_ACCOUNT_LABELS.items()],
    }


def export_csv(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    biz_type: str | None = None,
    include_void: bool = False,
) -> str:
    import csv
    import io

    data = list_entries(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        biz_type=biz_type,
        status=None if include_void else "posted",
        include_void=include_void,
    )
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["日期", "类型", "摘要", "进帐金额", "计件/提成", "出账金额", "余额", "来源单号", "状态"])
    for i in data["items"]:
        bal = i.get("balance")
        writer.writerow(
            [
                i.get("entry_date") or "",
                i.get("biz_type_label") or "",
                i.get("summary") or "",
                f"{i.get('amount_in', 0):.2f}" if i.get("amount_in") else "",
                f"{i.get('amount_piece', 0):.2f}" if i.get("amount_piece") else "",
                f"{i.get('amount_out', 0):.2f}" if i.get("amount_out") else "",
                f"{bal:.2f}" if bal is not None else "",
                i.get("source_no") or "",
                "已作废" if i.get("status") == "void" else "正常",
            ]
        )
    s = data["summary"]
    writer.writerow([])
    writer.writerow(
        [
            "合计笔数",
            s["count"],
            "进帐",
            f"{s['inflow']:.2f}",
            "计件/提成",
            f"{s.get('piece', 0):.2f}",
            "出账",
            f"{abs(s['outflow']):.2f}",
            "余额",
            f"{s.get('balance', s['net']):.2f}",
        ]
    )
    return buf.getvalue()


def _enum_val(v) -> str | None:
    if v is None:
        return None
    return v.value if hasattr(v, "value") else str(v)


def backfill_tenant(db: Session, tenant_id: int) -> dict[str, int]:
    """从既有收付单据幂等补齐总账；作废历史出货/采购挂账流水。"""
    from app.models import (
        DailyExpense,
        Employee,
        Payment,
        PaymentStatus,
        SalaryAdvance,
        SalaryMonthLock,
        SupplierPayment,
    )

    counts = {
        "voided_accrual": 0,
        "payment": 0,
        "supplier_payment": 0,
        "daily_expense": 0,
        "advance": 0,
        "salary": 0,
    }

    # 出货/采购挂账不再计入：作废已有 posted 流水
    for row in db.scalars(
        select(BusinessLedgerEntry).where(
            BusinessLedgerEntry.tenant_id == tenant_id,
            BusinessLedgerEntry.biz_type.in_(("shipment", "payable")),
            BusinessLedgerEntry.status == "posted",
        )
    ).all():
        row.status = "void"
        row.voided_at = datetime.now()
        counts["voided_accrual"] += 1

    # 收款登记
    for pay in db.scalars(select(Payment).where(Payment.tenant_id == tenant_id)).all():
        post_payment(
            db,
            tenant_id,
            payment_id=pay.id,
            customer_name=pay.customer_name or "",
            amount=pay.amount or 0,
            payment_date=pay.payment_date,
            fund_account=_enum_val(pay.method),
            voucher_no=pay.voucher_no,
        )
        if pay.status == PaymentStatus.void:
            void_payment_entry(db, tenant_id, pay.id)
        counts["payment"] += 1

    # 付款登记
    for pay in db.scalars(
        select(SupplierPayment).where(SupplierPayment.tenant_id == tenant_id)
    ).all():
        post_supplier_payment(
            db,
            tenant_id,
            payment_id=pay.id,
            supplier_name=pay.supplier_name or "",
            amount=pay.amount or 0,
            payment_date=pay.payment_date,
            fund_account=_enum_val(pay.method),
            voucher_no=pay.voucher_no,
        )
        if pay.status == PaymentStatus.void:
            void_supplier_payment_entry(db, tenant_id, pay.id)
        counts["supplier_payment"] += 1

    # 日常开支
    emp_ids = set()
    expenses = list(
        db.scalars(select(DailyExpense).where(DailyExpense.tenant_id == tenant_id)).all()
    )
    for e in expenses:
        if e.employee_id:
            emp_ids.add(e.employee_id)
    emp_names: dict[int, str] = {}
    if emp_ids:
        emp_names = {
            r.id: r.name
            for r in db.scalars(
                select(Employee).where(Employee.tenant_id == tenant_id, Employee.id.in_(emp_ids))
            ).all()
        }
    for row in expenses:
        post_daily_expense(
            db,
            tenant_id,
            expense_id=row.id,
            amount=row.amount or 0,
            expense_date=row.expense_date,
            reason=row.reason,
            employee_name=emp_names.get(row.employee_id) if row.employee_id else None,
            fund_account=row.fund_account,
        )
        if row.status == PaymentStatus.void:
            void_daily_expense_entry(db, tenant_id, row.id)
        counts["daily_expense"] += 1

    # 预支
    advances = list(
        db.scalars(select(SalaryAdvance).where(SalaryAdvance.tenant_id == tenant_id)).all()
    )
    adv_emp_ids = {a.worker_id for a in advances if a.worker_id}
    adv_names: dict[int, str] = {}
    if adv_emp_ids:
        adv_names = {
            r.id: r.name
            for r in db.scalars(
                select(Employee).where(
                    Employee.tenant_id == tenant_id, Employee.id.in_(adv_emp_ids)
                )
            ).all()
        }
    for adv in advances:
        post_advance(
            db,
            tenant_id,
            advance_id=adv.id,
            worker_name=adv_names.get(adv.worker_id) or f"#{adv.worker_id}",
            amount=adv.amount or 0,
            advanced_at=adv.advanced_at,
            fund_account=adv.fund_account,
        )
        if adv.status == "void":
            void_advance_entry(db, tenant_id, adv.id)
        counts["advance"] += 1

    # 工资月结（仅当前仍锁定的月份）
    from app.services.salary_service import month_salary_all

    for lock in db.scalars(
        select(SalaryMonthLock).where(
            SalaryMonthLock.tenant_id == tenant_id,
            SalaryMonthLock.is_locked.is_(True),
        )
    ).all():
        overview = month_salary_all(
            db,
            tenant_id,
            lock.year_month,
            settle_through=lock.settle_through,
        )
        post_salary_month(
            db,
            tenant_id,
            lock_id=lock.id,
            year_month=lock.year_month,
            total_wage=overview.get("total_wage") or 0,
            settle_through=lock.settle_through,
            worker_count=len(overview.get("items") or []),
        )
        counts["salary"] += 1

    db.flush()
    return counts



def backfill_all_tenants(db: Session) -> list[dict]:
    from app.models import Tenant

    results = []
    for t in db.scalars(select(Tenant).order_by(Tenant.id)).all():
        counts = backfill_tenant(db, t.id)
        results.append({"tenant_id": t.id, "tenant_name": t.name, "counts": counts})
    return results
