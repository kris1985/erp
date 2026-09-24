"""外协验收待结算、勾选对账单与结转余额。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountStatement,
    AccountStatementLine,
    AccountStatementStatus,
    OwnProduct,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PaymentStatus,
    SettlementDirection,
    SubcontractOrder,
    SubcontractReceipt,
    SupplierPayment,
)
from app.services.ap_service import ApError


ZERO = Decimal("0")
SUBCONTRACT_KIND = "subcontract"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _is_subcontract_payable(ap: Payable) -> bool:
    return bool(ap.subcontract_order_id) and not ap.purchase_order_id and ap.status != PayableStatus.void


def _collapsed(ap: Payable) -> bool:
    """历史已付款或已调账的验收，剩余未付不能拆回加工行。"""
    return _money(ap.paid_amount) > ZERO or _money(ap.adjustment) != ZERO


def _remaining(ap: Payable) -> Decimal:
    return _money(ap.amount) + _money(ap.adjustment) - _money(ap.paid_amount)


def subcontract_statements_query(db: Session, tenant_id: int, supplier_id: int):
    return select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.partner_id == supplier_id,
        AccountStatement.direction == SettlementDirection.supplier,
        AccountStatement.statement_kind == SUBCONTRACT_KIND,
        AccountStatement.status != AccountStatementStatus.void,
    )


def latest_subcontract_statement(
    db: Session, tenant_id: int, supplier_id: int
) -> AccountStatement | None:
    return db.scalar(
        subcontract_statements_query(db, tenant_id, supplier_id).order_by(AccountStatement.id.desc())
    )


def is_latest_subcontract_statement(db: Session, statement: AccountStatement) -> bool:
    if (statement.statement_kind or "period") != SUBCONTRACT_KIND:
        return False
    if statement.status == AccountStatementStatus.void:
        return False
    latest = latest_subcontract_statement(db, statement.tenant_id, statement.partner_id)
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
    """纯外加工厂未挂账单的付款算预付。兼营材料的供应商，这笔预付已在采购对账里。"""
    partner = db.get(Partner, supplier_id)
    if partner and partner.is_supplier:
        return ZERO
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
    latest = latest_subcontract_statement(db, tenant_id, supplier_id)
    if latest is not None:
        return unpaid_of_statement(db, latest)
    return _money(-prepayment_amount(db, tenant_id, supplier_id))


def _orders(db: Session, tenant_id: int, order_ids: set[int]) -> dict[int, SubcontractOrder]:
    if not order_ids:
        return {}
    rows = db.scalars(
        select(SubcontractOrder).where(
            SubcontractOrder.tenant_id == tenant_id,
            SubcontractOrder.id.in_(order_ids),
        )
    ).all()
    return {row.id: row for row in rows}


def _receipts(db: Session, receipt_ids: set[int]) -> dict[int, SubcontractReceipt]:
    if not receipt_ids:
        return {}
    rows = db.scalars(select(SubcontractReceipt).where(SubcontractReceipt.id.in_(receipt_ids))).all()
    return {row.id: row for row in rows}


def _line_amounts(line: PayableLine, receipt: SubcontractReceipt | None) -> dict:
    qty = line.qty
    price = line.unit_price
    gross = _money(Decimal(qty or 0) * Decimal(price or 0)) if qty is not None and price is not None else None
    if receipt is not None:
        shared = Decimal(receipt.shared_loss_amount or 0).quantize(Decimal("0.01"))
    elif gross is not None:
        shared = max(ZERO, _money(gross - _money(line.amount))).quantize(Decimal("0.01"))
    else:
        shared = None
    return {
        "qty": qty,
        "unit_price": price,
        "gross_amount": gross,
        "shared_loss_amount": shared,
        "amount": line.amount,
    }


def _product_images(db: Session, product_ids: set[int]) -> dict[int, str | None]:
    if not product_ids:
        return {}
    products = db.scalars(select(OwnProduct).where(OwnProduct.id.in_(product_ids))).all()
    return {product.id: product.image_url for product in products}


def list_pending_lines(
    db: Session,
    tenant_id: int,
    *,
    supplier_id: int | None = None,
    subcontract_no: str | None = None,
    product_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    query = (
        select(Payable)
        .where(
            Payable.tenant_id == tenant_id,
            Payable.subcontract_order_id.is_not(None),
            Payable.purchase_order_id.is_(None),
            Payable.status != PayableStatus.void,
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
    payables = [ap for ap in db.scalars(query).all() if _is_subcontract_payable(ap)]
    orders = _orders(db, tenant_id, {ap.subcontract_order_id for ap in payables if ap.subcontract_order_id})
    images = _product_images(db, {order.own_product_id for order in orders.values() if order.own_product_id})
    from app.services.subcontract_out_service import _linked_no

    production_nos = {order_id: _linked_no(db, order) for order_id, order in orders.items()}
    receipt_ids = {
        line.source_ref_id
        for ap in payables
        for line in ap.lines
        if line.source_type == "subcontract_receive" and line.source_ref_id
    }
    receipts = _receipts(db, receipt_ids)
    rows: list[dict] = []
    for ap in payables:
        if ap.remainder_statement_id:
            continue
        order = orders.get(ap.subcontract_order_id) if ap.subcontract_order_id else None
        header = {
            "payable_id": ap.id,
            "supplier_id": ap.supplier_id,
            "supplier_name": ap.supplier_name,
            "received_at": ap.created_at,
            "payable_date": ap.payable_date,
            "ordered_at": order.created_at if order else None,
            "subcontract_no": order.subcontract_no if order else None,
            "delivery_note_no": (ap.delivery_note_no or "").strip() or None,
            "production_no": production_nos.get(ap.subcontract_order_id) if ap.subcontract_order_id else None,
            "issued_qty": int(order.issued_qty or 0) if order else None,
            "image_url": images.get(order.own_product_id) if order and order.own_product_id else None,
        }
        if _collapsed(ap):
            remaining = _remaining(ap)
            if remaining <= ZERO:
                continue
            processes = [ln.process_name or "" for ln in ap.lines if ln.process_name]
            codes = [ln.item_code or "" for ln in ap.lines if ln.item_code]
            skus = [ln.customer_sku or "" for ln in ap.lines if ln.customer_sku]
            colors = [ln.color_name or "" for ln in ap.lines if ln.color_name]
            sizes = [ln.size_value or "" for ln in ap.lines if ln.size_value]
            units = [ln.unit_name or "" for ln in ap.lines if ln.unit_name]
            rows.append(
                {
                    **header,
                    "row_type": "remainder",
                    "line_id": None,
                    "process_name": "、".join(dict.fromkeys(processes)) or "验收剩余",
                    "item_code": "、".join(dict.fromkeys(codes)) or None,
                    "customer_sku": "、".join(dict.fromkeys(skus)) or None,
                    "color_name": "、".join(dict.fromkeys(colors)) or None,
                    "size_value": "、".join(dict.fromkeys(sizes)) or None,
                    "unit_name": "、".join(dict.fromkeys(units)) or None,
                    "qty": None,
                    "unit_price": None,
                    "gross_amount": None,
                    "shared_loss_amount": None,
                    "amount": remaining,
                }
            )
            continue
        for line in ap.lines:
            if line.statement_id:
                continue
            receipt = receipts.get(line.source_ref_id) if line.source_type == "subcontract_receive" else None
            if receipt and receipt.subcontract_order_id != ap.subcontract_order_id:
                receipt = None
            rows.append(
                {
                    **header,
                    "subcontract_no": (order.subcontract_no if order else None) or line.source_document_no,
                    "row_type": "line",
                    "line_id": line.id,
                    "process_name": line.process_name,
                    "item_code": line.item_code,
                    "customer_sku": line.customer_sku,
                    "color_name": line.color_name,
                    "size_value": line.size_value,
                    "unit_name": line.unit_name,
                    **_line_amounts(line, receipt),
                }
            )
    no_kw = (subcontract_no or "").strip().lower()
    code_kw = (product_code or "").strip().lower()
    if no_kw or code_kw:
        rows = [
            row
            for row in rows
            if (not no_kw or no_kw in str(row.get("subcontract_no") or "").lower())
            and (
                not code_kw
                or code_kw in str(row.get("item_code") or "").lower()
                or code_kw in str(row.get("customer_sku") or "").lower()
            )
        ]
    return rows


def pending_amount(rows: list[dict]) -> Decimal:
    return _money(sum((_money(row.get("amount")) for row in rows), ZERO))


def supplier_subcontract_balance(db: Session, tenant_id: int, supplier_id: int) -> dict:
    rows = list_pending_lines(db, tenant_id, supplier_id=supplier_id)
    pending = pending_amount(rows)
    carry = carry_balance(db, tenant_id, supplier_id)
    partner = db.get(Partner, supplier_id)
    name = (partner.short_name or partner.name or "").strip() if partner else ""
    return {
        "supplier_id": supplier_id,
        "supplier_name": name,
        "carry_balance": carry,
        "pending_amount": pending,
        "debt": _money(carry + pending),
    }


def _line_description(line: PayableLine) -> str:
    parts = [line.process_name or line.item_code or "外协加工"]
    if line.customer_sku:
        parts.append(line.customer_sku)
    if line.color_name:
        parts.append(line.color_name)
    if line.size_value:
        parts.append(line.size_value)
    return " / ".join(parts)


def generate_subcontract_statement(
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
        raise ApError("supplier_not_found", "外加工厂不存在")
    if not partner.is_subcontractor:
        raise ApError("not_subcontractor", "只能给外加工厂生成加工费对账单")
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
            select(Payable)
            .where(
                Payable.tenant_id == tenant_id,
                Payable.id.in_(remainder_payable_ids or [-1]),
            )
            .options(selectinload(Payable.lines))
        ).all()
    )
    if len(remainders) != len(remainder_payable_ids):
        raise ApError("payable_not_found", "有验收剩余不存在")

    for line in lines:
        ap = line.payable
        if not _is_subcontract_payable(ap) or ap.supplier_id != supplier_id:
            raise ApError("wrong_supplier", "只能勾选同一个外加工厂的验收")
        if line.statement_id or ap.remainder_statement_id or _collapsed(ap):
            raise ApError("already_statemented", "明细已进对账单，或这次验收只能整笔结算")
    for ap in remainders:
        if not _is_subcontract_payable(ap) or ap.supplier_id != supplier_id:
            raise ApError("wrong_supplier", "只能勾选同一个外加工厂的验收")
        if ap.remainder_statement_id or not _collapsed(ap):
            raise ApError("already_statemented", "这次验收不是待结算的剩余未付")
        if _remaining(ap) <= ZERO:
            raise ApError("nothing_to_statement", "这次验收已付清")

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
        statement_kind=SUBCONTRACT_KIND,
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
        notes="外协待结算勾选生成",
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
        order = db.get(SubcontractOrder, ap.subcontract_order_id) if ap.subcontract_order_id else None
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="payable_line",
                source_id=line.id,
                business_date=ap.payable_date,
                document_no=(order.subcontract_no if order else None) or line.source_document_no,
                description=_line_description(line),
                debit_amount=_money(line.amount),
                credit_amount=ZERO,
                sort_order=sort_order,
            )
        )
        line.statement_id = statement.id
        sort_order += 1
    for ap in remainders:
        order = db.get(SubcontractOrder, ap.subcontract_order_id) if ap.subcontract_order_id else None
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="payable_remainder",
                source_id=ap.id,
                business_date=ap.payable_date,
                document_no=order.subcontract_no if order else None,
                description="验收剩余未付",
                debit_amount=_remaining(ap),
                credit_amount=ZERO,
                sort_order=sort_order,
            )
        )
        ap.remainder_statement_id = statement.id
        sort_order += 1
    db.commit()
    return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)


def list_subcontract_statements(
    db: Session, tenant_id: int, *, supplier_id: int | None = None
) -> list[dict]:
    from app.services import settlement_service

    query = select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.direction == SettlementDirection.supplier,
        AccountStatement.statement_kind == SUBCONTRACT_KIND,
    )
    if supplier_id:
        query = query.where(AccountStatement.partner_id == supplier_id)
    rows = list(db.scalars(query.order_by(AccountStatement.id.desc())).all())
    latest_ids = set()
    if supplier_id:
        latest = latest_subcontract_statement(db, tenant_id, supplier_id)
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


def void_subcontract_statement(db: Session, tenant_id: int, statement_id: int) -> dict:
    from app.services import settlement_service

    statement = db.get(AccountStatement, statement_id)
    if (
        not statement
        or statement.tenant_id != tenant_id
        or (statement.statement_kind or "period") != SUBCONTRACT_KIND
    ):
        raise ApError("statement_not_found", "外协对账单不存在")
    if statement.status == AccountStatementStatus.void:
        return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)
    if not is_latest_subcontract_statement(db, statement):
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


def subcontract_line_item(db: Session, line_id: int) -> dict | None:
    line = db.get(PayableLine, line_id)
    if not line:
        return None
    ap = db.get(Payable, line.payable_id)
    if not ap or not ap.subcontract_order_id:
        return None
    order = db.get(SubcontractOrder, ap.subcontract_order_id)
    image_url = None
    if order and order.own_product_id:
        product = db.get(OwnProduct, order.own_product_id)
        image_url = product.image_url if product else None
    receipt = None
    if line.source_type == "subcontract_receive" and line.source_ref_id:
        receipt = db.get(SubcontractReceipt, line.source_ref_id)
        if receipt and receipt.subcontract_order_id != ap.subcontract_order_id:
            receipt = None
    from app.services.subcontract_out_service import _linked_no

    amounts = _line_amounts(line, receipt)
    return {
        "source_type": "subcontract_receive",
        "payable_id": ap.id,
        "source_document_no": (order.subcontract_no if order else None) or line.source_document_no,
        "delivery_note_no": (ap.delivery_note_no or "").strip() or None,
        "production_no": _linked_no(db, order) if order else None,
        "received_at": ap.created_at,
        "ordered_at": order.created_at if order else None,
        "image_url": image_url,
        "item_code": line.item_code,
        "item_name": line.item_name,
        "process_name": line.process_name,
        "customer_sku": line.customer_sku,
        "color_name": line.color_name,
        "size_value": line.size_value,
        "unit_name": line.unit_name,
        "issued_qty": int(order.issued_qty or 0) if order else None,
        "qty": amounts["qty"],
        "unit_price": amounts["unit_price"],
        "gross_amount": amounts["gross_amount"],
        "shared_loss_amount": amounts["shared_loss_amount"],
        "amount": amounts["amount"],
        "size_breakdown": (
            [{"size_value": line.size_value, "qty": _money(line.qty)}] if line.size_value else []
        ),
    }


def subcontract_remainder_item(db: Session, payable_id: int) -> dict | None:
    ap = db.scalar(
        select(Payable).where(Payable.id == payable_id).options(selectinload(Payable.lines))
    )
    if not ap or not ap.subcontract_order_id:
        return None
    order = db.get(SubcontractOrder, ap.subcontract_order_id)
    image_url = None
    if order and order.own_product_id:
        product = db.get(OwnProduct, order.own_product_id)
        image_url = product.image_url if product else None
    from app.services.subcontract_out_service import _linked_no

    return {
        "source_type": "subcontract_receive",
        "payable_id": ap.id,
        "source_document_no": order.subcontract_no if order else None,
        "delivery_note_no": (ap.delivery_note_no or "").strip() or None,
        "production_no": _linked_no(db, order) if order else None,
        "received_at": ap.created_at,
        "ordered_at": order.created_at if order else None,
        "issued_qty": int(order.issued_qty or 0) if order else None,
        "gross_amount": None,
        "shared_loss_amount": None,
        "image_url": image_url,
        "item_code": "、".join(dict.fromkeys(ln.item_code for ln in ap.lines if ln.item_code)) or None,
        "item_name": "验收剩余未付",
        "process_name": "、".join(dict.fromkeys(ln.process_name for ln in ap.lines if ln.process_name))
        or "验收剩余",
        "customer_sku": "、".join(dict.fromkeys(ln.customer_sku for ln in ap.lines if ln.customer_sku))
        or None,
        "color_name": "、".join(dict.fromkeys(ln.color_name for ln in ap.lines if ln.color_name)) or None,
        "size_value": "、".join(dict.fromkeys(ln.size_value for ln in ap.lines if ln.size_value)) or None,
        "unit_name": "、".join(dict.fromkeys(ln.unit_name for ln in ap.lines if ln.unit_name)) or None,
        "qty": None,
        "unit_price": None,
        "amount": _remaining(ap),
        "size_breakdown": [
            {"size_value": ln.size_value, "qty": _money(ln.qty)} for ln in ap.lines if ln.size_value
        ],
    }
