"""采购到货待结算、勾选对账单与结转余额。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountStatement,
    AccountStatementLine,
    AccountStatementStatus,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PaymentStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    SettlementDirection,
    SupplierPayment,
    SupplierProduct,
)
from app.services.ap_service import ApError


ZERO = Decimal("0")
PURCHASE_KIND = "purchase"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _is_purchase_payable(ap: Payable) -> bool:
    if ap.subcontract_order_id or ap.status == PayableStatus.void:
        return False
    if ap.purchase_order_id:
        return True
    return any(line.source_type == "purchase_return" for line in ap.lines)


def _collapsed(ap: Payable) -> bool:
    """历史已付款或已调账的到货，剩余未付不能拆回物料行。"""
    paid = _money(ap.paid_amount)
    adjustment = _money(ap.adjustment)
    return paid > ZERO or adjustment != ZERO


def _remaining(ap: Payable) -> Decimal:
    return _money(ap.amount) + _money(ap.adjustment) - _money(ap.paid_amount)


def purchase_statements_query(db: Session, tenant_id: int, supplier_id: int):
    return select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.partner_id == supplier_id,
        AccountStatement.direction == SettlementDirection.supplier,
        AccountStatement.statement_kind == PURCHASE_KIND,
        AccountStatement.status != AccountStatementStatus.void,
    )


def latest_purchase_statement(
    db: Session, tenant_id: int, supplier_id: int
) -> AccountStatement | None:
    return db.scalar(
        purchase_statements_query(db, tenant_id, supplier_id).order_by(AccountStatement.id.desc())
    )


def is_latest_purchase_statement(db: Session, statement: AccountStatement) -> bool:
    if (statement.statement_kind or "period") != PURCHASE_KIND:
        return False
    if statement.status == AccountStatementStatus.void:
        return False
    latest = latest_purchase_statement(db, statement.tenant_id, statement.partner_id)
    return latest is not None and latest.id == statement.id


def statement_paid_amount(db: Session, statement_id: int) -> Decimal:
    amount = db.scalar(
        select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(
            SupplierPayment.statement_id == statement_id,
            SupplierPayment.status == PaymentStatus.posted,
        )
    )
    return _money(amount)


def unpaid_of_statement(db: Session, statement: AccountStatement) -> Decimal:
    return _money(statement.closing_balance) - statement_paid_amount(db, statement.id)


def prepayment_amount(db: Session, tenant_id: int, supplier_id: int) -> Decimal:
    """没分到应付、也没挂对账单的历史付款，作为预付。"""
    payments = list(
        db.scalars(
            select(SupplierPayment)
            .where(
                SupplierPayment.tenant_id == tenant_id,
                SupplierPayment.supplier_id == supplier_id,
                SupplierPayment.status == PaymentStatus.posted,
                SupplierPayment.statement_id.is_(None),
            )
            .options(selectinload(SupplierPayment.allocations))
        ).all()
    )
    total = ZERO
    for pay in payments:
        if pay.allocations:
            continue
        total += _money(pay.amount)
    return _money(total)


def carry_balance(db: Session, tenant_id: int, supplier_id: int) -> Decimal:
    latest = latest_purchase_statement(db, tenant_id, supplier_id)
    if latest is not None:
        return unpaid_of_statement(db, latest)
    return _money(-prepayment_amount(db, tenant_id, supplier_id))


def _purchase_orders(db: Session, tenant_id: int, po_ids: set[int]) -> dict[int, PurchaseOrder]:
    if not po_ids:
        return {}
    rows = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.id.in_(po_ids),
        )
    ).all()
    return {row.id: row for row in rows}


def _receive_facts(db: Session, tenant_id: int, line_ids: set[int]) -> dict[int, dict]:
    """采购行订购数量，以及物料图片。"""
    if not line_ids:
        return {}
    lines = db.scalars(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.id.in_(line_ids),
        )
    ).all()
    product_ids = {ln.supplier_product_id for ln in lines}
    images: dict[int, str | None] = {}
    if product_ids:
        products = db.scalars(
            select(SupplierProduct).where(SupplierProduct.id.in_(product_ids))
        ).all()
        images = {product.id: product.image_url for product in products}
    return {
        ln.id: {"order_qty": ln.qty, "image_url": images.get(ln.supplier_product_id)}
        for ln in lines
    }


def list_pending_lines(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None = None,
    po_no: str | None = None,
    delivery_note_no: str | None = None,
    item_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    return_payable_ids = select(PayableLine.payable_id).where(
        PayableLine.tenant_id == tenant_id,
        PayableLine.source_type == "purchase_return",
    )
    query = (
        select(Payable)
        .where(
            Payable.tenant_id == tenant_id,
            Payable.subcontract_order_id.is_(None),
            Payable.status != PayableStatus.void,
            or_(Payable.purchase_order_id.is_not(None), Payable.id.in_(return_payable_ids)),
        )
        .options(selectinload(Payable.lines))
        .order_by(Payable.payable_date.desc(), Payable.id.desc())
    )
    if supplier_id:
        query = query.where(Payable.supplier_id == supplier_id)
    if date_from:
        query = query.where(Payable.payable_date >= date_from)
    if date_to:
        query = query.where(Payable.payable_date <= date_to)
    payables = [ap for ap in db.scalars(query).all() if _is_purchase_payable(ap)]
    orders = _purchase_orders(db, tenant_id, {ap.purchase_order_id for ap in payables if ap.purchase_order_id})
    ref_ids = {
        ln.source_ref_id
        for ap in payables
        for ln in ap.lines
        if ln.source_type == "purchase_receive" and ln.source_ref_id
    }
    facts = _receive_facts(db, tenant_id, ref_ids)
    return_product_ids = {
        ln.supplier_product_id
        for ap in payables
        for ln in ap.lines
        if ln.source_type == "purchase_return" and ln.supplier_product_id
    }
    return_products = {}
    if return_product_ids:
        return_products = {
            product.id: product
            for product in db.scalars(
                select(SupplierProduct).where(SupplierProduct.id.in_(return_product_ids))
            ).all()
        }
    rows: list[dict] = []
    for ap in payables:
        if ap.remainder_statement_id:
            continue
        is_return = any(ln.source_type == "purchase_return" for ln in ap.lines)
        po = orders.get(ap.purchase_order_id) if ap.purchase_order_id else None
        row_po_no = None if is_return else (po.po_no if po else None)
        header = {
            "payable_id": ap.id,
            "supplier_id": ap.supplier_id,
            "supplier_name": ap.supplier_name,
            "received_at": ap.created_at,
            "payable_date": ap.payable_date,
            "ordered_at": None if is_return else (po.ordered_at if po else None),
            "po_no": row_po_no,
            "delivery_note_no": None if is_return else ap.delivery_note_no,
        }
        if _collapsed(ap):
            remaining = _remaining(ap)
            if remaining <= ZERO:
                continue
            names = [ln.item_name or ln.item_code or "" for ln in ap.lines]
            colors = [ln.color_name or "" for ln in ap.lines if ln.color_name]
            sizes = [ln.size_value or "" for ln in ap.lines if ln.size_value]
            units = [ln.unit_name or "" for ln in ap.lines if ln.unit_name]
            first_fact = next((facts.get(ln.source_ref_id) for ln in ap.lines if ln.source_ref_id), None)
            rows.append(
                {
                    **header,
                    "row_type": "remainder",
                    "source_type": "purchase_receive",
                    "line_id": None,
                    "image_url": (first_fact or {}).get("image_url"),
                    "item_code": None,
                    "item_name": "、".join(n for n in names if n) or "到货剩余",
                    "color_name": "、".join(dict.fromkeys(colors)) or None,
                    "size_value": "、".join(dict.fromkeys(sizes)) or None,
                    "unit_name": "、".join(dict.fromkeys(units)) or None,
                    "order_qty": None,
                    "qty": None,
                    "unit_price": None,
                    "amount": remaining,
                }
            )
            continue
        for line in ap.lines:
            if line.statement_id:
                continue
            is_line_return = line.source_type == "purchase_return"
            fact = {} if is_line_return else (facts.get(line.source_ref_id) or {})
            product = return_products.get(line.supplier_product_id) if is_line_return else None
            rows.append(
                {
                    **header,
                    "po_no": None if is_line_return else (row_po_no or line.source_document_no),
                    "row_type": "line",
                    "source_type": line.source_type,
                    "line_id": line.id,
                    "image_url": product.image_url if is_line_return and product else fact.get("image_url"),
                    "item_code": line.item_code,
                    "item_name": line.item_name,
                    "color_name": line.color_name,
                    "size_value": line.size_value,
                    "unit_name": line.unit_name,
                    "order_qty": None if is_line_return else fact.get("order_qty"),
                    "qty": line.qty,
                    "unit_price": line.unit_price,
                    "amount": line.amount,
                }
            )
    po_kw = (po_no or "").strip().lower()
    note_kw = (delivery_note_no or "").strip().lower()
    code_kw = (item_code or "").strip().lower()
    if po_kw or note_kw or code_kw:
        rows = [
            row
            for row in rows
            if (not po_kw or po_kw in str(row.get("po_no") or "").lower())
            and (not note_kw or note_kw in str(row.get("delivery_note_no") or "").lower())
            and (not code_kw or code_kw in str(row.get("item_code") or "").lower())
        ]
    return rows


def pending_amount(rows: list[dict]) -> Decimal:
    return _money(sum((_money(row.get("amount")) for row in rows), ZERO))


def supplier_purchase_balance(db: Session, tenant_id: int, supplier_id: int) -> dict:
    rows = list_pending_lines(db, tenant_id, supplier_id=supplier_id)
    pending = pending_amount(rows)
    carry = carry_balance(db, tenant_id, supplier_id)
    partner = db.get(Partner, supplier_id)
    name = ""
    if partner:
        name = (partner.short_name or partner.name or "").strip()
    return {
        "supplier_id": supplier_id,
        "supplier_name": name,
        "carry_balance": carry,
        "pending_amount": pending,
        "debt": _money(carry + pending),
    }


def purchase_debt_total(db: Session, tenant_id: int) -> dict:
    supplier_ids = set(
        db.scalars(
            select(Payable.supplier_id).where(
                Payable.tenant_id == tenant_id,
                Payable.purchase_order_id.is_not(None),
                Payable.subcontract_order_id.is_(None),
                Payable.supplier_id.is_not(None),
            )
        ).all()
    )
    for supplier_id in db.scalars(
        select(SupplierPayment.supplier_id).where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.status == PaymentStatus.posted,
            SupplierPayment.statement_id.is_(None),
            SupplierPayment.supplier_id.is_not(None),
        )
    ).all():
        partner = db.get(Partner, supplier_id)
        if partner and partner.is_supplier and not partner.is_subcontractor:
            supplier_ids.add(supplier_id)
    supplier_ids.update(
        db.scalars(
            select(Payable.supplier_id)
            .join(PayableLine, PayableLine.payable_id == Payable.id)
            .where(
                Payable.tenant_id == tenant_id,
                PayableLine.source_type == "purchase_return",
                Payable.supplier_id.is_not(None),
            )
        ).all()
    )
    supplier_ids.discard(None)
    rows = []
    total = ZERO
    for supplier_id in supplier_ids:
        partner = db.get(Partner, supplier_id)
        if partner and partner.is_subcontractor and not partner.is_supplier:
            continue
        item = supplier_purchase_balance(db, tenant_id, int(supplier_id))
        if item["debt"] == ZERO and item["pending_amount"] == ZERO and item["carry_balance"] == ZERO:
            continue
        rows.append(item)
        total += item["debt"]
    rows.sort(key=lambda row: row["debt"], reverse=True)
    return {"debt": _money(total), "suppliers": rows}


def _line_description(line: PayableLine, delivery_note_no: str | None) -> str:
    parts = [line.item_name or line.item_code or "物料"]
    if line.color_name:
        parts.append(line.color_name)
    if line.size_value:
        parts.append(line.size_value)
    text = " / ".join(parts)
    if delivery_note_no:
        text = f"{text} · 送货单 {delivery_note_no}"
    return text


def generate_purchase_statement(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int,
    line_ids: list[int],
    remainder_payable_ids: list[int],
    statement_no: str | None = None,
    statement_date: date | None = None,
    user_id: int | None = None,
) -> dict:
    from app.services import settlement_service

    partner = db.get(Partner, supplier_id)
    if not partner or partner.tenant_id != tenant_id:
        raise ApError("supplier_not_found", "供应商不存在")
    if partner.is_subcontractor and not partner.is_supplier:
        raise ApError("not_purchase_supplier", "外协加工费不在采购对账单中结算")
    line_ids = list(dict.fromkeys(line_ids or []))
    remainder_payable_ids = list(dict.fromkeys(remainder_payable_ids or []))
    if not line_ids and not remainder_payable_ids:
        raise ApError("empty_selection", "请先勾选待结算明细")

    lines = list(
        db.scalars(
            select(PayableLine)
            .where(PayableLine.tenant_id == tenant_id, PayableLine.id.in_(line_ids or [-1]))
            .options(selectinload(PayableLine.payable))
        ).all()
    )
    if len(lines) != len(line_ids):
        raise ApError("line_not_found", "有待结算明细不存在")
    remainders = list(
        db.scalars(
            select(Payable).where(
                Payable.tenant_id == tenant_id,
                Payable.id.in_(remainder_payable_ids or [-1]),
            ).options(selectinload(Payable.lines))
        ).all()
    )
    if len(remainders) != len(remainder_payable_ids):
        raise ApError("payable_not_found", "有到货剩余不存在")

    for line in lines:
        ap = line.payable
        if not _is_purchase_payable(ap) or ap.supplier_id != supplier_id:
            raise ApError("wrong_supplier", "只能勾选同一个供应商的采购到货")
        if line.statement_id or ap.remainder_statement_id or _collapsed(ap):
            raise ApError("already_statemented", "明细已进对账单，或这张到货只能整笔结算")
    for ap in remainders:
        if not _is_purchase_payable(ap) or ap.supplier_id != supplier_id:
            raise ApError("wrong_supplier", "只能勾选同一个供应商的采购到货")
        if ap.remainder_statement_id or not _collapsed(ap):
            raise ApError("already_statemented", "这张到货不是待结算的剩余未付")
        if _remaining(ap) <= ZERO:
            raise ApError("nothing_to_statement", "这张到货已付清")

    opening = carry_balance(db, tenant_id, supplier_id)
    current = sum((_money(line.amount) for line in lines), ZERO)
    current += sum((_remaining(ap) for ap in remainders), ZERO)
    current = _money(current)
    closing = _money(opening + current)
    booked_on = statement_date or date.today()
    number = (statement_no or "").strip() or settlement_service._next_statement_no(
        db, tenant_id, SettlementDirection.supplier, booked_on
    )
    if len(number) > 50:
        raise ApError("statement_no_invalid", "对账单号不能超过50个字")
    taken = db.scalar(
        select(AccountStatement.id).where(
            AccountStatement.tenant_id == tenant_id,
            AccountStatement.statement_no == number,
        )
    )
    if taken:
        raise ApError("statement_no_taken", "对账单号已存在")
    statement = AccountStatement(
        tenant_id=tenant_id,
        statement_no=number,
        partner_id=supplier_id,
        partner_name=partner.short_name or partner.name,
        direction=SettlementDirection.supplier,
        statement_kind=PURCHASE_KIND,
        period_start=booked_on,
        period_end=booked_on,
        statement_date=booked_on,
        due_date=booked_on,
        opening_balance=opening,
        current_amount=current,
        adjustment_amount=ZERO,
        period_settlement_amount=ZERO,
        closing_balance=closing,
        status=AccountStatementStatus.confirmed,
        confirmed_at=datetime.now(),
        created_by=user_id,
        notes="采购待结算勾选生成",
    )
    db.add(statement)
    db.flush()
    sort_order = 0
    if opening != ZERO:
        debit = opening if opening > ZERO else ZERO
        credit = -opening if opening < ZERO else ZERO
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="opening_balance",
                source_id=None,
                business_date=booked_on,
                document_no=None,
                description="上期余额",
                debit_amount=_money(debit),
                credit_amount=_money(credit),
                sort_order=sort_order,
            )
        )
        sort_order += 1
    for line in lines:
        ap = line.payable
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="payable_line",
                source_id=line.id,
                business_date=ap.payable_date,
                document_no=line.source_document_no,
                description=_line_description(line, ap.delivery_note_no),
                debit_amount=_money(line.amount),
                credit_amount=ZERO,
                sort_order=sort_order,
            )
        )
        line.statement_id = statement.id
        sort_order += 1
    for ap in remainders:
        po = db.get(PurchaseOrder, ap.purchase_order_id) if ap.purchase_order_id else None
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="payable_remainder",
                source_id=ap.id,
                business_date=ap.payable_date,
                document_no=po.po_no if po else None,
                description="到货剩余未付",
                debit_amount=_remaining(ap),
                credit_amount=ZERO,
                sort_order=sort_order,
            )
        )
        ap.remainder_statement_id = statement.id
        sort_order += 1
    db.commit()
    return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)


def list_purchase_statements(
    db: Session, tenant_id: int, *, supplier_id: int | None = None
) -> list[dict]:
    from app.services import settlement_service

    query = select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.direction == SettlementDirection.supplier,
        AccountStatement.statement_kind == PURCHASE_KIND,
    )
    if supplier_id:
        query = query.where(AccountStatement.partner_id == supplier_id)
    rows = list(db.scalars(query.order_by(AccountStatement.id.desc())).all())
    latest_ids = set()
    if supplier_id:
        latest = latest_purchase_statement(db, tenant_id, supplier_id)
        if latest:
            latest_ids.add(latest.id)
    else:
        seen = set()
        for row in rows:
            if row.status == AccountStatementStatus.void or row.partner_id in seen:
                continue
            seen.add(row.partner_id)
            latest_ids.add(row.id)
    out = []
    for row in rows:
        item = settlement_service.statement_out(db, tenant_id, row.id, with_lines=True)
        unpaid = unpaid_of_statement(db, row) if row.status != AccountStatementStatus.void else ZERO
        item["unpaid_amount"] = unpaid
        item["is_latest"] = row.id in latest_ids and row.status != AccountStatementStatus.void
        item["can_pay"] = item["is_latest"] and unpaid > ZERO
        item["can_void"] = item["is_latest"] and _money(item.get("settled_amount")) <= ZERO
        item["carried_to_no"] = None
        payments = db.scalars(
            select(SupplierPayment).where(
                SupplierPayment.statement_id == row.id,
                SupplierPayment.status == PaymentStatus.posted,
            )
        ).all()
        item["payments"] = [
            {
                "id": pay.id,
                "amount": pay.amount,
                "payment_date": pay.payment_date,
                "voucher_no": pay.voucher_no,
                "notes": pay.notes,
                "method": pay.method.value if hasattr(pay.method, "value") else pay.method,
            }
            for pay in payments
        ]
        out.append(item)
    live_by_supplier: dict[int, list[dict]] = {}
    for item in out:
        if item.get("status") == AccountStatementStatus.void.value:
            continue
        live_by_supplier.setdefault(item["partner_id"], []).append(item)
    for group in live_by_supplier.values():
        group.sort(key=lambda item: item["id"])
        for prev, nxt in zip(group, group[1:]):
            prev["carried_to_no"] = nxt["statement_no"]
    return out


def void_purchase_statement(db: Session, tenant_id: int, statement_id: int) -> dict:
    from app.services import settlement_service

    statement = db.get(AccountStatement, statement_id)
    if (
        not statement
        or statement.tenant_id != tenant_id
        or (statement.statement_kind or "period") != PURCHASE_KIND
    ):
        raise ApError("statement_not_found", "采购对账单不存在")
    if statement.status == AccountStatementStatus.void:
        return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)
    if not is_latest_purchase_statement(db, statement):
        raise ApError("statement_not_latest", "只能作废还没把余额交给下一张的最新对账单")
    if statement_paid_amount(db, statement.id) > ZERO:
        raise ApError("statement_has_payment", "对账单已有付款，须先作废付款")
    for line in db.scalars(select(PayableLine).where(PayableLine.statement_id == statement.id)).all():
        line.statement_id = None
    for ap in db.scalars(select(Payable).where(Payable.remainder_statement_id == statement.id)).all():
        ap.remainder_statement_id = None
    statement.status = AccountStatementStatus.void
    db.commit()
    return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)


def update_delivery_note(
    db: Session, tenant_id: int, payable_id: int, delivery_note_no: str | None
) -> dict:
    ap = db.get(Payable, payable_id)
    if not ap or ap.tenant_id != tenant_id or not ap.purchase_order_id or not _is_purchase_payable(ap):
        raise ApError("not_found", "采购到货不存在")
    if ap.remainder_statement_id:
        raise ApError("already_statemented", "已进对账单的送货单号不能修改")
    linked = db.scalar(
        select(func.count())
        .select_from(PayableLine)
        .where(PayableLine.payable_id == ap.id, PayableLine.statement_id.is_not(None))
    )
    if linked:
        raise ApError("already_statemented", "已进对账单的送货单号不能修改")
    ap.delivery_note_no = (delivery_note_no or "").strip() or None
    db.commit()
    return {"id": ap.id, "delivery_note_no": ap.delivery_note_no}


def _line_visuals(db: Session, line: PayableLine) -> tuple[str | None, Decimal | None]:
    if line.source_type == "purchase_return":
        product = db.get(SupplierProduct, line.supplier_product_id) if line.supplier_product_id else None
        return (product.image_url if product else None), None
    if not line.source_ref_id:
        return None, None
    po_line = db.get(PurchaseOrderLine, line.source_ref_id)
    if not po_line:
        return None, None
    image_url = None
    if po_line.supplier_product_id:
        product = db.get(SupplierProduct, po_line.supplier_product_id)
        image_url = product.image_url if product else None
    return image_url, po_line.qty


def payable_line_item(db: Session, line_id: int) -> dict | None:
    line = db.get(PayableLine, line_id)
    if not line:
        return None
    ap = db.get(Payable, line.payable_id)
    po = db.get(PurchaseOrder, ap.purchase_order_id) if ap and ap.purchase_order_id else None
    image_url, order_qty = _line_visuals(db, line)
    return {
        "source_type": line.source_type,
        "payable_id": ap.id if ap else None,
        "source_document_no": line.source_document_no,
        "received_at": ap.created_at if ap else None,
        "ordered_at": po.ordered_at if po else None,
        "image_url": image_url,
        "item_code": line.item_code,
        "item_name": line.item_name,
        "process_name": None,
        "customer_sku": None,
        "color_name": line.color_name,
        "size_value": line.size_value,
        "unit_name": line.unit_name,
        "order_qty": _money(order_qty) if order_qty is not None else None,
        "qty": _money(line.qty),
        "unit_price": _money(line.unit_price),
        "amount": _money(line.amount),
        "size_breakdown": (
            [{"size_value": line.size_value, "qty": _money(line.qty)}] if line.size_value else []
        ),
        "delivery_note_no": ap.delivery_note_no if ap else None,
    }


def remainder_item(db: Session, payable_id: int) -> dict | None:
    ap = db.scalar(
        select(Payable).where(Payable.id == payable_id).options(selectinload(Payable.lines))
    )
    if not ap:
        return None
    po = db.get(PurchaseOrder, ap.purchase_order_id) if ap.purchase_order_id else None
    first = next((ln for ln in ap.lines if ln.source_ref_id), None)
    image_url = _line_visuals(db, first)[0] if first else None
    return {
        "source_type": "purchase_receive",
        "payable_id": ap.id,
        "source_document_no": po.po_no if po else None,
        "received_at": ap.created_at,
        "ordered_at": po.ordered_at if po else None,
        "image_url": image_url,
        "item_code": None,
        "item_name": "到货剩余未付",
        "process_name": None,
        "customer_sku": None,
        "color_name": "、".join(dict.fromkeys(ln.color_name for ln in ap.lines if ln.color_name)) or None,
        "size_value": "、".join(dict.fromkeys(ln.size_value for ln in ap.lines if ln.size_value)) or None,
        "unit_name": "、".join(dict.fromkeys(ln.unit_name for ln in ap.lines if ln.unit_name)) or None,
        "order_qty": None,
        "qty": None,
        "unit_price": None,
        "amount": _remaining(ap),
        "size_breakdown": [
            {"size_value": ln.size_value, "qty": _money(ln.qty)} for ln in ap.lines if ln.size_value
        ],
        "delivery_note_no": ap.delivery_note_no,
    }
