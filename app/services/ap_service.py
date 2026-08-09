"""轻量应付：采购到货挂账、付款核销、供应商汇总。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Partner,
    Payable,
    PayableStatus,
    PaymentMethod,
    PaymentStatus,
    PurchaseOrder,
    SupplierPayment,
    SupplierPaymentAllocation,
)


class ApError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_payment_term_days(po: PurchaseOrder, partner: Partner | None) -> int:
    """生效账期：PO 覆盖 > 供应商默认 > 0（现结）。"""
    if po.payment_term_days is not None:
        return max(0, int(po.payment_term_days))
    if partner is not None and partner.payment_term_days is not None:
        return max(0, int(partner.payment_term_days))
    return 0


def payable_balance(ap: Payable) -> Decimal:
    return (ap.amount or Decimal("0")) + (ap.adjustment or Decimal("0")) - (ap.paid_amount or Decimal("0"))


def _refresh_ap_status(ap: Payable) -> None:
    if ap.status == PayableStatus.void:
        return
    bal = payable_balance(ap)
    gross = (ap.amount or Decimal("0")) + (ap.adjustment or Decimal("0"))
    paid = ap.paid_amount or Decimal("0")
    # 未定价（金额为 0）保持未结，便于事后调账
    if gross == 0 and paid == 0:
        ap.status = PayableStatus.open
        return
    if bal <= 0:
        ap.status = PayableStatus.settled
        ap.paid_amount = gross
    elif paid > 0:
        ap.status = PayableStatus.partial
    else:
        ap.status = PayableStatus.open


def create_payable_for_receive(
    db: Session,
    tenant_id: int,
    po: PurchaseOrder,
    receives: list[dict],
) -> Payable | None:
    """按本次到货 Σ(qty × unit_price) 挂一笔应付。无有效到货则返回 None。"""
    by_id = {ln.id: ln for ln in po.lines}
    amount = Decimal("0")
    has_qty = False
    for item in receives:
        ln = by_id.get(item.get("line_id"))
        if not ln:
            continue
        qty = Decimal(str(item.get("qty") or 0))
        if qty <= 0:
            continue
        has_qty = True
        price = ln.unit_price if ln.unit_price is not None else Decimal("0")
        amount += qty * Decimal(str(price))
    if not has_qty:
        return None

    partner = db.get(Partner, po.partner_id) if po.partner_id else None
    supplier_name = ""
    if partner:
        supplier_name = (partner.short_name or partner.name or "").strip()
    if not supplier_name:
        supplier_name = f"供应商#{po.partner_id}"

    payable_date = date.today()
    term_days = resolve_payment_term_days(po, partner)
    due = payable_date + timedelta(days=term_days)

    amount = amount.quantize(Decimal("0.0001"))
    ap = Payable(
        tenant_id=tenant_id,
        supplier_id=po.partner_id,
        supplier_name=supplier_name,
        purchase_order_id=po.id,
        payable_date=payable_date,
        due_date=due,
        payment_term_days=term_days,
        amount=amount,
        adjustment=Decimal("0"),
        paid_amount=Decimal("0"),
        status=PayableStatus.open,
        notes=f"PO {po.po_no} 到货挂账",
    )
    db.add(ap)
    db.flush()
    _refresh_ap_status(ap)
    return ap


def _po_no_map(db: Session, tenant_id: int, po_ids: set[int]) -> dict[int, str]:
    if not po_ids:
        return {}
    rows = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id.in_(po_ids)
        )
    ).all()
    return {p.id: p.po_no for p in rows}


def _aging_bucket(due: date | None, *, as_of: date | None = None) -> tuple[int, str]:
    """相对到期日：未到期 / 逾期分桶。"""
    today = as_of or date.today()
    if not due:
        due = today
    overdue_days = (today - due).days
    if overdue_days <= 0:
        return overdue_days, "not_due"
    if overdue_days <= 30:
        return overdue_days, "overdue_0_30"
    if overdue_days <= 60:
        return overdue_days, "overdue_31_60"
    return overdue_days, "overdue_60_plus"


def _ap_out(ap: Payable, *, po_no: str | None = None) -> dict:
    bal = payable_balance(ap)
    due = ap.due_date or ap.payable_date
    overdue_days, bucket = _aging_bucket(due)
    return {
        "id": ap.id,
        "supplier_id": ap.supplier_id,
        "supplier_name": ap.supplier_name,
        "purchase_order_id": ap.purchase_order_id,
        "po_no": po_no,
        "payable_date": ap.payable_date,
        "due_date": due,
        "payment_term_days": int(ap.payment_term_days or 0),
        "amount": ap.amount,
        "adjustment": ap.adjustment,
        "paid_amount": ap.paid_amount,
        "balance": bal,
        "status": ap.status.value if hasattr(ap.status, "value") else ap.status,
        "overdue_days": max(0, overdue_days),
        "age_bucket": bucket,
        "notes": ap.notes,
    }


def list_payables(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None = None,
    purchase_order_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
) -> list[dict]:
    q = select(Payable).where(Payable.tenant_id == tenant_id).order_by(Payable.id.desc())
    if supplier_id:
        q = q.where(Payable.supplier_id == supplier_id)
    if purchase_order_id:
        q = q.where(Payable.purchase_order_id == purchase_order_id)
    if status:
        q = q.where(Payable.status == PayableStatus(status))
    if date_from:
        q = q.where(Payable.payable_date >= date_from)
    if date_to:
        q = q.where(Payable.payable_date <= date_to)
    rows = list(db.scalars(q).all())
    nos = _po_no_map(db, tenant_id, {r.purchase_order_id for r in rows if r.purchase_order_id})
    out = [_ap_out(ap, po_no=nos.get(ap.purchase_order_id)) for ap in rows]
    kw = (keyword or "").strip().lower()
    if kw:
        out = [
            r
            for r in out
            if kw
            in " ".join(
                [
                    str(r.get("supplier_name") or ""),
                    str(r.get("po_no") or ""),
                    str(r.get("purchase_order_id") or ""),
                ]
            ).lower()
        ]
    return out


def supplier_ap_summary(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None = None,
    with_balance_only: bool = False,
) -> list[dict]:
    q = select(Payable).where(
        Payable.tenant_id == tenant_id,
        Payable.status.in_(
            [PayableStatus.open, PayableStatus.partial, PayableStatus.settled]
        ),
    )
    if supplier_id:
        q = q.where(Payable.supplier_id == supplier_id)
    rows = db.scalars(q).all()
    by_sup: dict[tuple, dict] = {}
    empty_aging = {
        "not_due": Decimal("0"),
        "overdue_0_30": Decimal("0"),
        "overdue_31_60": Decimal("0"),
        "overdue_60_plus": Decimal("0"),
    }
    for ap in rows:
        key = (ap.supplier_id, ap.supplier_name)
        slot = by_sup.setdefault(
            key,
            {
                "supplier_id": ap.supplier_id,
                "supplier_name": ap.supplier_name,
                "amount": Decimal("0"),
                "paid_amount": Decimal("0"),
                "balance": Decimal("0"),
                "aging": dict(empty_aging),
            },
        )
        bal = payable_balance(ap)
        slot["amount"] += (ap.amount or Decimal("0")) + (ap.adjustment or Decimal("0"))
        slot["paid_amount"] += ap.paid_amount or Decimal("0")
        slot["balance"] += bal
        if bal > 0:
            out = _ap_out(ap)
            bucket = out["age_bucket"]
            slot["aging"][bucket] = slot["aging"].get(bucket, Decimal("0")) + bal
    result = list(by_sup.values())
    if with_balance_only:
        result = [r for r in result if (r.get("balance") or Decimal("0")) > 0]
    result.sort(key=lambda r: r.get("balance") or Decimal("0"), reverse=True)
    return result


def adjust_payable(
    db: Session,
    tenant_id: int,
    ap_id: int,
    adjustment_delta: Decimal,
    notes: str | None = None,
) -> dict:
    ap = db.get(Payable, ap_id)
    if not ap or ap.tenant_id != tenant_id:
        raise ApError("not_found", "应付不存在")
    if ap.status == PayableStatus.void:
        raise ApError("void", "已作废应付不可调账")
    ap.adjustment = (ap.adjustment or Decimal("0")) + adjustment_delta
    if notes is not None:
        ap.notes = notes
    if payable_balance(ap) < 0:
        raise ApError("negative_balance", "调账后未付不能为负")
    _refresh_ap_status(ap)
    db.commit()
    nos = _po_no_map(db, tenant_id, {ap.purchase_order_id})
    return _ap_out(ap, po_no=nos.get(ap.purchase_order_id))


def create_supplier_payment(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None,
    supplier_name: str,
    amount: Decimal,
    payment_date: date,
    method: str = "other",
    voucher_no: str | None = None,
    notes: str | None = None,
    allocations: list[dict],
    user_id: int | None = None,
) -> dict:
    if amount <= 0:
        raise ApError("invalid_amount", "付款金额须大于 0")
    if not allocations:
        raise ApError("no_alloc", "须核销到应付")
    alloc_sum = sum((Decimal(str(a["amount"])) for a in allocations), Decimal("0"))
    if alloc_sum != amount:
        raise ApError("alloc_mismatch", "核销合计须等于付款金额")

    pay = SupplierPayment(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        amount=amount,
        payment_date=payment_date,
        method=PaymentMethod(method) if method in PaymentMethod.__members__ else PaymentMethod.other,
        voucher_no=voucher_no,
        status=PaymentStatus.posted,
        notes=notes,
        created_by=user_id,
    )
    db.add(pay)
    db.flush()

    for a in allocations:
        ap = db.get(Payable, a["payable_id"])
        if not ap or ap.tenant_id != tenant_id:
            raise ApError("ap_not_found", "应付不存在")
        if ap.status == PayableStatus.void:
            raise ApError("ap_void", "应付已作废")
        amt = Decimal(str(a["amount"]))
        if amt <= 0:
            raise ApError("invalid_alloc", "核销金额须大于 0")
        bal = payable_balance(ap)
        if amt > bal:
            raise ApError("over_alloc", f"核销超过未付（未付 {bal}）")
        ap.paid_amount = (ap.paid_amount or Decimal("0")) + amt
        _refresh_ap_status(ap)
        db.add(
            SupplierPaymentAllocation(
                tenant_id=tenant_id,
                payment_id=pay.id,
                payable_id=ap.id,
                purchase_order_id=ap.purchase_order_id,
                amount=amt,
            )
        )
    db.commit()
    return supplier_payment_out(db, tenant_id, pay.id)


def supplier_payment_out(db: Session, tenant_id: int, payment_id: int) -> dict:
    pay = db.scalar(
        select(SupplierPayment)
        .where(SupplierPayment.id == payment_id, SupplierPayment.tenant_id == tenant_id)
        .options(selectinload(SupplierPayment.allocations))
    )
    if not pay:
        raise ApError("not_found", "付款不存在")
    return {
        "id": pay.id,
        "supplier_id": pay.supplier_id,
        "supplier_name": pay.supplier_name,
        "amount": pay.amount,
        "payment_date": pay.payment_date,
        "method": pay.method.value if hasattr(pay.method, "value") else pay.method,
        "voucher_no": pay.voucher_no,
        "status": pay.status.value if hasattr(pay.status, "value") else pay.status,
        "notes": pay.notes,
        "created_at": pay.created_at,
        "allocations": [
            {
                "id": a.id,
                "payable_id": a.payable_id,
                "purchase_order_id": a.purchase_order_id,
                "amount": a.amount,
            }
            for a in pay.allocations
        ],
    }


def list_supplier_payments(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None = None,
    status: str | None = None,
    method: str | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    q = (
        select(SupplierPayment)
        .where(SupplierPayment.tenant_id == tenant_id)
        .options(selectinload(SupplierPayment.allocations))
        .order_by(SupplierPayment.id.desc())
    )
    if supplier_id:
        q = q.where(SupplierPayment.supplier_id == supplier_id)
    if status:
        q = q.where(SupplierPayment.status == PaymentStatus(status))
    if method:
        q = q.where(SupplierPayment.method == PaymentMethod(method))
    if date_from:
        q = q.where(SupplierPayment.payment_date >= date_from)
    if date_to:
        q = q.where(SupplierPayment.payment_date <= date_to)
    rows = list(db.scalars(q).all())
    out = [supplier_payment_out(db, tenant_id, p.id) for p in rows]
    kw = (keyword or "").strip().lower()
    if kw:
        out = [
            r
            for r in out
            if kw
            in " ".join(
                [
                    str(r.get("supplier_name") or ""),
                    str(r.get("voucher_no") or ""),
                    str(r.get("notes") or ""),
                ]
            ).lower()
        ]
    return out


def void_supplier_payment(
    db: Session, tenant_id: int, payment_id: int, *, user_id: int | None = None
) -> dict:
    pay = db.scalar(
        select(SupplierPayment)
        .where(SupplierPayment.id == payment_id, SupplierPayment.tenant_id == tenant_id)
        .options(selectinload(SupplierPayment.allocations))
    )
    if not pay:
        raise ApError("not_found", "付款不存在")
    if pay.status == PaymentStatus.void:
        return supplier_payment_out(db, tenant_id, payment_id)
    for a in pay.allocations:
        ap = db.get(Payable, a.payable_id)
        if ap:
            ap.paid_amount = max(Decimal("0"), (ap.paid_amount or Decimal("0")) - a.amount)
            _refresh_ap_status(ap)
    pay.status = PaymentStatus.void
    db.commit()
    return supplier_payment_out(db, tenant_id, payment_id)
