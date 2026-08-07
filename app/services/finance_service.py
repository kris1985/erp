"""应收、回款核销、订单利润复盘。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductOtherCost,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Receivable,
    ReceivableStatus,
    SharedMaterialStock,
    Shipment,
    ShipmentStatus,
    WorkLog,
    WorkLogStatus,
)
from app.services.order_service import get_labor_unit_price


class FinanceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def receivable_balance(ar: Receivable) -> Decimal:
    return (ar.amount or Decimal("0")) + (ar.adjustment or Decimal("0")) - (ar.received_amount or Decimal("0"))


def _refresh_ar_status(ar: Receivable) -> None:
    if ar.status == ReceivableStatus.void:
        return
    bal = receivable_balance(ar)
    if bal <= 0:
        ar.status = ReceivableStatus.settled
        ar.received_amount = (ar.amount or Decimal("0")) + (ar.adjustment or Decimal("0"))
    elif (ar.received_amount or 0) > 0:
        ar.status = ReceivableStatus.partial
    else:
        ar.status = ReceivableStatus.open


def create_receivable_for_shipment(db: Session, tenant_id: int, sh: Shipment) -> Receivable:
    existing = db.scalar(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.shipment_id == sh.id,
            Receivable.status != ReceivableStatus.void,
        )
    )
    if existing:
        return existing
    ar = Receivable(
        tenant_id=tenant_id,
        customer_id=sh.customer_id,
        customer_name=sh.customer_name,
        order_id=sh.order_id,
        shipment_id=sh.id,
        receivable_date=sh.ship_date or date.today(),
        amount=sh.amount or Decimal("0"),
        adjustment=Decimal("0"),
        received_amount=Decimal("0"),
        status=ReceivableStatus.open,
    )
    db.add(ar)
    db.flush()
    return ar


def _ar_out(ar: Receivable, *, order_no: str | None = None) -> dict:
    bal = receivable_balance(ar)
    age_days = (date.today() - ar.receivable_date).days if ar.receivable_date else 0
    if age_days <= 30:
        bucket = "0-30"
    elif age_days <= 60:
        bucket = "31-60"
    else:
        bucket = "60+"
    return {
        "id": ar.id,
        "customer_id": ar.customer_id,
        "customer_name": ar.customer_name,
        "order_id": ar.order_id,
        "order_no": order_no,
        "shipment_id": ar.shipment_id,
        "receivable_date": ar.receivable_date,
        "amount": ar.amount,
        "adjustment": ar.adjustment,
        "received_amount": ar.received_amount,
        "balance": bal,
        "status": ar.status.value if hasattr(ar.status, "value") else ar.status,
        "age_days": age_days,
        "age_bucket": bucket,
        "notes": ar.notes,
    }


def _order_no_map(db: Session, tenant_id: int, order_ids: set[int]) -> dict[int, str]:
    if not order_ids:
        return {}
    rows = db.scalars(
        select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids))
    ).all()
    return {o.id: o.order_no for o in rows}


def list_receivables(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None = None,
    order_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
) -> list[dict]:
    q = select(Receivable).where(Receivable.tenant_id == tenant_id).order_by(Receivable.id.desc())
    if customer_id:
        q = q.where(Receivable.customer_id == customer_id)
    if order_id:
        q = q.where(Receivable.order_id == order_id)
    if status:
        q = q.where(Receivable.status == ReceivableStatus(status))
    if date_from:
        q = q.where(Receivable.receivable_date >= date_from)
    if date_to:
        q = q.where(Receivable.receivable_date <= date_to)
    rows = list(db.scalars(q).all())
    nos = _order_no_map(db, tenant_id, {r.order_id for r in rows if r.order_id})
    out = [_ar_out(ar, order_no=nos.get(ar.order_id)) for ar in rows]
    kw = (keyword or "").strip().lower()
    if kw:
        out = [
            r
            for r in out
            if kw
            in " ".join(
                [
                    str(r.get("customer_name") or ""),
                    str(r.get("order_no") or ""),
                    str(r.get("order_id") or ""),
                ]
            ).lower()
        ]
    return out


def customer_ar_summary(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None = None,
    with_balance_only: bool = False,
) -> list[dict]:
    q = select(Receivable).where(
        Receivable.tenant_id == tenant_id,
        Receivable.status.in_(
            [ReceivableStatus.open, ReceivableStatus.partial, ReceivableStatus.settled]
        ),
    )
    if customer_id:
        q = q.where(Receivable.customer_id == customer_id)
    rows = db.scalars(q).all()
    by_cust: dict[tuple, dict] = {}
    for ar in rows:
        key = (ar.customer_id, ar.customer_name)
        slot = by_cust.setdefault(
            key,
            {
                "customer_id": ar.customer_id,
                "customer_name": ar.customer_name,
                "amount": Decimal("0"),
                "received_amount": Decimal("0"),
                "balance": Decimal("0"),
                "aging": {"0-30": Decimal("0"), "31-60": Decimal("0"), "60+": Decimal("0")},
            },
        )
        bal = receivable_balance(ar)
        slot["amount"] += (ar.amount or Decimal("0")) + (ar.adjustment or Decimal("0"))
        slot["received_amount"] += ar.received_amount or Decimal("0")
        slot["balance"] += bal
        if bal > 0:
            out = _ar_out(ar)
            slot["aging"][out["age_bucket"]] += bal
    result = list(by_cust.values())
    if with_balance_only:
        result = [r for r in result if (r.get("balance") or Decimal("0")) > 0]
    result.sort(key=lambda r: r.get("balance") or Decimal("0"), reverse=True)
    return result


def adjust_receivable(
    db: Session,
    tenant_id: int,
    ar_id: int,
    adjustment_delta: Decimal,
    notes: str | None = None,
) -> dict:
    ar = db.get(Receivable, ar_id)
    if not ar or ar.tenant_id != tenant_id:
        raise FinanceError("not_found", "应收不存在")
    if ar.status == ReceivableStatus.void:
        raise FinanceError("void", "已作废应收不可调账")
    ar.adjustment = (ar.adjustment or Decimal("0")) + adjustment_delta
    if notes is not None:
        ar.notes = notes
    if receivable_balance(ar) < 0:
        raise FinanceError("negative_balance", "调账后未收不能为负")
    _refresh_ar_status(ar)
    db.commit()
    return _ar_out(ar)


def order_has_open_receivable(db: Session, tenant_id: int, order_id: int) -> bool:
    rows = db.scalars(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.order_id == order_id,
            Receivable.status.in_([ReceivableStatus.open, ReceivableStatus.partial]),
        )
    ).all()
    return any(receivable_balance(ar) > 0 for ar in rows)


def create_payment(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None,
    customer_name: str,
    amount: Decimal,
    payment_date: date,
    method: str = "other",
    voucher_no: str | None = None,
    notes: str | None = None,
    allocations: list[dict],
    user_id: int | None = None,
) -> dict:
    if amount <= 0:
        raise FinanceError("invalid_amount", "收款金额须大于 0")
    if not allocations:
        raise FinanceError("no_alloc", "须核销到应收")
    alloc_sum = sum((Decimal(str(a["amount"])) for a in allocations), Decimal("0"))
    if alloc_sum != amount:
        raise FinanceError("alloc_mismatch", "核销合计须等于收款金额")

    pay = Payment(
        tenant_id=tenant_id,
        customer_id=customer_id,
        customer_name=customer_name,
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
        ar = db.get(Receivable, a["receivable_id"])
        if not ar or ar.tenant_id != tenant_id:
            raise FinanceError("ar_not_found", "应收不存在")
        if ar.status == ReceivableStatus.void:
            raise FinanceError("ar_void", "应收已作废")
        amt = Decimal(str(a["amount"]))
        if amt <= 0:
            raise FinanceError("invalid_alloc", "核销金额须大于 0")
        bal = receivable_balance(ar)
        if amt > bal:
            raise FinanceError("over_alloc", f"核销超过未收（未收 {bal}）")
        ar.received_amount = (ar.received_amount or Decimal("0")) + amt
        _refresh_ar_status(ar)
        db.add(
            PaymentAllocation(
                tenant_id=tenant_id,
                payment_id=pay.id,
                receivable_id=ar.id,
                order_id=ar.order_id,
                amount=amt,
            )
        )
    db.commit()
    return payment_out(db, tenant_id, pay.id)


def payment_out(db: Session, tenant_id: int, payment_id: int) -> dict:
    pay = db.scalar(
        select(Payment)
        .where(Payment.id == payment_id, Payment.tenant_id == tenant_id)
        .options(selectinload(Payment.allocations))
    )
    if not pay:
        raise FinanceError("not_found", "收款不存在")
    return {
        "id": pay.id,
        "customer_id": pay.customer_id,
        "customer_name": pay.customer_name,
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
                "receivable_id": a.receivable_id,
                "order_id": a.order_id,
                "amount": a.amount,
            }
            for a in pay.allocations
        ],
    }


def list_payments(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None = None,
    status: str | None = None,
    method: str | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    q = (
        select(Payment)
        .where(Payment.tenant_id == tenant_id)
        .options(selectinload(Payment.allocations))
        .order_by(Payment.id.desc())
    )
    if customer_id:
        q = q.where(Payment.customer_id == customer_id)
    if status:
        q = q.where(Payment.status == PaymentStatus(status))
    if method:
        q = q.where(Payment.method == PaymentMethod(method))
    if date_from:
        q = q.where(Payment.payment_date >= date_from)
    if date_to:
        q = q.where(Payment.payment_date <= date_to)
    rows = list(db.scalars(q).all())
    out = [payment_out(db, tenant_id, p.id) for p in rows]
    kw = (keyword or "").strip().lower()
    if kw:
        out = [
            r
            for r in out
            if kw
            in " ".join(
                [
                    str(r.get("customer_name") or ""),
                    str(r.get("voucher_no") or ""),
                    str(r.get("notes") or ""),
                ]
            ).lower()
        ]
    return out


def void_payment(db: Session, tenant_id: int, payment_id: int, *, user_id: int | None = None) -> dict:
    pay = db.scalar(
        select(Payment)
        .where(Payment.id == payment_id, Payment.tenant_id == tenant_id)
        .options(selectinload(Payment.allocations))
    )
    if not pay:
        raise FinanceError("not_found", "收款不存在")
    if pay.status == PaymentStatus.void:
        return payment_out(db, tenant_id, payment_id)
    # 当日或 admin — caller enforces; here allow
    for a in pay.allocations:
        ar = db.get(Receivable, a.receivable_id)
        if ar:
            ar.received_amount = max(Decimal("0"), (ar.received_amount or Decimal("0")) - a.amount)
            _refresh_ar_status(ar)
    pay.status = PaymentStatus.void
    db.commit()
    return payment_out(db, tenant_id, payment_id)


def _material_cost(db: Session, tenant_id: int, order: Order) -> tuple[Decimal, str]:
    """返回 (成本, 口径)。口径来自租户 inventory.cost_basis。"""
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    basis = str(inv.get("cost_basis") or "po_received")

    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
    )

    if basis == "issued":
        cost = Decimal("0")
        for r in reqs:
            if r.is_customer_supplied:
                continue
            cost += (r.issued_qty or Decimal("0")) * (r.unit_price or Decimal("0"))
        return cost.quantize(Decimal("0.0001")), basis

    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_id == order.id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.partial_received,
                    PurchaseOrderStatus.received,
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                ]
            ),
        )
    ).all()
    cost = Decimal("0")
    has_recv = False
    for ln in lines:
        recv = ln.received_qty or Decimal("0")
        if recv > 0:
            has_recv = True
            cost += recv * (ln.unit_price or Decimal("0"))
    if has_recv:
        return cost.quantize(Decimal("0.0001")), basis

    for r in reqs:
        if r.is_customer_supplied:
            continue
        cost += (r.required_qty or Decimal("0")) * (r.unit_price or Decimal("0"))
    return cost.quantize(Decimal("0.0001")), basis


def _labor_cost(db: Session, tenant_id: int, order: Order) -> Decimal:
    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.order_id == order.id,
            WorkLog.status.in_([WorkLogStatus.valid, WorkLogStatus.corrected]),
        )
    ).all()
    total = Decimal("0")
    for log in logs:
        price = get_labor_unit_price(db, tenant_id, order.own_product_id, log.process_id) or Decimal("0")
        total += Decimal(int(log.qualified_qty or 0)) * price
    return total.quantize(Decimal("0.0001"))


def _other_cost(db: Session, tenant_id: int, order: Order, shipped_qty: int) -> Decimal:
    if order.other_cost_amount is not None:
        return Decimal(order.other_cost_amount).quantize(Decimal("0.0001"))
    others = db.scalars(
        select(OwnProductOtherCost).where(
            OwnProductOtherCost.tenant_id == tenant_id,
            OwnProductOtherCost.own_product_id == order.own_product_id,
        )
    ).all()
    per_pair = sum((o.amount or Decimal("0") for o in others), Decimal("0"))
    return (per_pair * Decimal(shipped_qty)).quantize(Decimal("0.0001"))


def order_profit(db: Session, tenant_id: int, order_id: int) -> dict:
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise FinanceError("order_not_found", "订单不存在")
    shipments = db.scalars(
        select(Shipment).where(
            Shipment.tenant_id == tenant_id,
            Shipment.order_id == order_id,
            Shipment.status == ShipmentStatus.shipped,
        )
    ).all()
    revenue = sum((s.amount or Decimal("0") for s in shipments), Decimal("0"))
    shipped_qty = sum((s.total_qty or 0 for s in shipments), 0)
    material, cost_basis = _material_cost(db, tenant_id, order)
    labor = _labor_cost(db, tenant_id, order)
    other = _other_cost(db, tenant_id, order, shipped_qty)
    gross = revenue - material - labor - other
    margin = (gross / revenue).quantize(Decimal("0.0001")) if revenue > 0 else None
    product = db.get(OwnProduct, order.own_product_id)
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "product_code": product.product_code if product else None,
        "customer_name": order.customer_name,
        "shipped_qty": shipped_qty,
        "revenue": revenue,
        "material_cost": material,
        "material_cost_basis": cost_basis,
        "labor_cost": labor,
        "other_cost": other,
        "gross_profit": gross,
        "gross_margin": margin,
        "estimated": True,
    }


def profit_report(
    db: Session,
    tenant_id: int,
    *,
    year: int | None = None,
    month: int | None = None,
    customer_id: int | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    loss_only: bool = False,
) -> dict:
    q = select(Shipment).where(
        Shipment.tenant_id == tenant_id,
        Shipment.status == ShipmentStatus.shipped,
    )
    if date_from or date_to:
        if date_from:
            q = q.where(Shipment.ship_date >= date_from)
        if date_to:
            q = q.where(Shipment.ship_date <= date_to)
    elif year and month:
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        q = q.where(Shipment.ship_date >= start, Shipment.ship_date < end)
    shipments = db.scalars(q).all()
    order_ids = {s.order_id for s in shipments}
    if customer_id:
        orders = {
            o.id: o
            for o in db.scalars(
                select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids or [0]))
            ).all()
            if o.customer_id == customer_id
        }
        order_ids = set(orders.keys())

    kw = (keyword or "").strip().lower()
    rows = []
    tot_rev = tot_mat = tot_lab = tot_oth = tot_gross = Decimal("0")
    tot_shipped = 0
    for oid in order_ids:
        order = db.get(Order, oid)
        if not order or order.tenant_id != tenant_id:
            continue
        if customer_id and order.customer_id != customer_id:
            continue
        p = order_profit(db, tenant_id, oid)
        if kw:
            hay = " ".join(
                [
                    str(p.get("order_no") or ""),
                    str(p.get("customer_name") or ""),
                    str(p.get("product_code") or ""),
                ]
            ).lower()
            if kw not in hay:
                continue
        if loss_only and (p.get("gross_profit") or Decimal("0")) >= 0:
            continue
        rows.append(p)
        tot_rev += p["revenue"]
        tot_mat += p["material_cost"]
        tot_lab += p["labor_cost"]
        tot_oth += p["other_cost"]
        tot_gross += p["gross_profit"]
        tot_shipped += int(p.get("shipped_qty") or 0)
    rows.sort(key=lambda r: str(r.get("order_no") or ""), reverse=True)
    return {
        "year": year,
        "month": month,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "orders": rows,
        "summary": {
            "shipped_qty": tot_shipped,
            "revenue": tot_rev,
            "material_cost": tot_mat,
            "labor_cost": tot_lab,
            "other_cost": tot_oth,
            "gross_profit": tot_gross,
            "gross_margin": (tot_gross / tot_rev).quantize(Decimal("0.0001")) if tot_rev > 0 else None,
            "estimated": True,
        },
    }


def business_kpi(db: Session, tenant_id: int, *, year: int | None = None, month: int | None = None) -> dict:
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

    ship_amt = db.scalar(
        select(func.coalesce(func.sum(Shipment.amount), 0)).where(
            Shipment.tenant_id == tenant_id,
            Shipment.status == ShipmentStatus.shipped,
            Shipment.ship_date >= start,
            Shipment.ship_date < end,
        )
    ) or Decimal("0")

    pay_amt = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.tenant_id == tenant_id,
            Payment.status == PaymentStatus.posted,
            Payment.payment_date >= start,
            Payment.payment_date < end,
        )
    ) or Decimal("0")

    report = profit_report(db, tenant_id, year=y, month=m)
    ar_bal = Decimal("0")
    for ar in db.scalars(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.status.in_([ReceivableStatus.open, ReceivableStatus.partial]),
        )
    ).all():
        ar_bal += receivable_balance(ar)

    return {
        "year": y,
        "month": m,
        "shipment_amount": Decimal(str(ship_amt)),
        "payment_amount": Decimal(str(pay_amt)),
        "gross_profit": report["summary"]["gross_profit"],
        "customer_ar_balance": ar_bal,
        "estimated": True,
    }
