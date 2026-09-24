"""客户出货与退货待结算、勾选对账单与结转余额。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountStatement,
    AccountStatementLine,
    AccountStatementStatus,
    AfterSalesReturn,
    Color,
    OwnProduct,
    Partner,
    Payment,
    PaymentStatus,
    Receivable,
    ReceivableStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SettlementDirection,
    Shipment,
    ShipmentLine,
)
from app.services.finance_service import FinanceError


ZERO = Decimal("0")
SALES_KIND = "sales"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _remaining(ar: Receivable) -> Decimal:
    return _money(ar.amount) + _money(ar.adjustment) - _money(ar.received_amount)


def sales_statements_query(db: Session, tenant_id: int, customer_id: int):
    return select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.partner_id == customer_id,
        AccountStatement.direction == SettlementDirection.customer,
        AccountStatement.statement_kind == SALES_KIND,
        AccountStatement.status != AccountStatementStatus.void,
    )


def latest_sales_statement(
    db: Session, tenant_id: int, customer_id: int
) -> AccountStatement | None:
    return db.scalar(
        sales_statements_query(db, tenant_id, customer_id).order_by(AccountStatement.id.desc())
    )


def is_latest_sales_statement(db: Session, statement: AccountStatement) -> bool:
    if (statement.statement_kind or "period") != SALES_KIND:
        return False
    if statement.status == AccountStatementStatus.void:
        return False
    latest = latest_sales_statement(db, statement.tenant_id, statement.partner_id)
    return latest is not None and latest.id == statement.id


def statement_received_amount(db: Session, statement_id: int) -> Decimal:
    amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.statement_id == statement_id,
            Payment.status == PaymentStatus.posted,
        )
    )
    return _money(amount)


def unpaid_of_statement(db: Session, statement: AccountStatement) -> Decimal:
    return _money(statement.closing_balance) - statement_received_amount(db, statement.id)


def prepayment_amount(db: Session, tenant_id: int, customer_id: int) -> Decimal:
    """没分到应收、也没挂对账单的历史收款，作为预收。"""
    payments = list(
        db.scalars(
            select(Payment)
            .where(
                Payment.tenant_id == tenant_id,
                Payment.customer_id == customer_id,
                Payment.status == PaymentStatus.posted,
                Payment.statement_id.is_(None),
            )
            .options(selectinload(Payment.allocations))
        ).all()
    )
    total = ZERO
    for pay in payments:
        if pay.allocations:
            continue
        total += _money(pay.amount)
    return _money(total)


def carry_balance(db: Session, tenant_id: int, customer_id: int) -> Decimal:
    latest = latest_sales_statement(db, tenant_id, customer_id)
    if latest is not None:
        return unpaid_of_statement(db, latest)
    return _money(-prepayment_amount(db, tenant_id, customer_id))


def _shipments(db: Session, shipment_ids: set[int]) -> dict[int, Shipment]:
    if not shipment_ids:
        return {}
    rows = db.scalars(select(Shipment).where(Shipment.id.in_(shipment_ids))).all()
    return {row.id: row for row in rows}


def _by_id(db: Session, model, ids: set[int]) -> dict[int, object]:
    if not ids:
        return {}
    return {row.id: row for row in db.scalars(select(model).where(model.id.in_(ids))).all()}


def _sales_orders(db: Session, order_ids: set[int]) -> dict[int, SalesOrder]:
    return _by_id(db, SalesOrder, order_ids)


def _order_facts(db: Session, sales_order_ids: set[int]) -> dict[int, dict]:
    """销售单上的工厂型号、图片、颜色，出货行对不上时用来补。"""
    if not sales_order_ids:
        return {}
    lines = list(
        db.scalars(
            select(SalesOrderLine).where(SalesOrderLine.sales_order_id.in_(sales_order_ids))
        ).all()
    )
    products = _by_id(db, OwnProduct, {ln.own_product_id for ln in lines if ln.own_product_id})
    colors = _by_id(db, Color, {ln.color_id for ln in lines if ln.color_id})
    grouped: dict[int, dict] = {}
    for line in lines:
        product = products.get(line.own_product_id)
        bucket = grouped.setdefault(
            line.sales_order_id,
            {"codes": [], "image_url": None, "colors": [], "brands": [], "customer_skus": []},
        )
        if product and product.product_code and product.product_code not in bucket["codes"]:
            bucket["codes"].append(product.product_code)
        if product and product.image_url and not bucket["image_url"]:
            bucket["image_url"] = product.image_url
        color = colors.get(line.color_id) if line.color_id else None
        if color and color.name not in bucket["colors"]:
            bucket["colors"].append(color.name)
        if line.brand_name and line.brand_name not in bucket["brands"]:
            bucket["brands"].append(line.brand_name)
        if line.customer_sku and line.customer_sku not in bucket["customer_skus"]:
            bucket["customer_skus"].append(line.customer_sku)
    return grouped


def _shipment_facts(db: Session, shipment_ids: set[int]) -> dict[int, dict]:
    """按出货明细汇总工厂型号、图片和颜色。"""
    if not shipment_ids:
        return {}
    lines = list(
        db.scalars(select(ShipmentLine).where(ShipmentLine.shipment_id.in_(shipment_ids))).all()
    )
    items = _by_id(
        db,
        SalesOrderLineItem,
        {ln.sales_order_line_item_id for ln in lines if ln.sales_order_line_item_id},
    )
    sales_lines = _by_id(
        db,
        SalesOrderLine,
        {item.sales_order_line_id for item in items.values()},
    )
    products = _by_id(
        db,
        OwnProduct,
        {ln.own_product_id for ln in sales_lines.values() if ln.own_product_id},
    )
    colors = _by_id(db, Color, {ln.color_id for ln in lines if ln.color_id})
    grouped: dict[int, list[ShipmentLine]] = {}
    for line in lines:
        grouped.setdefault(line.shipment_id, []).append(line)
    facts: dict[int, dict] = {}
    for shipment_id, shipment_lines in grouped.items():
        codes: list[str] = []
        color_names: list[str] = []
        brands: list[str] = []
        customer_skus: list[str] = []
        image_url = None
        for line in shipment_lines:
            item = items.get(line.sales_order_line_item_id) if line.sales_order_line_item_id else None
            sales_line = sales_lines.get(item.sales_order_line_id) if item else None
            product = (
                products.get(sales_line.own_product_id)
                if sales_line and sales_line.own_product_id
                else None
            )
            if product and product.product_code and product.product_code not in codes:
                codes.append(product.product_code)
            if product and product.image_url and not image_url:
                image_url = product.image_url
            color = colors.get(line.color_id) if line.color_id else None
            if color and color.name not in color_names:
                color_names.append(color.name)
            if sales_line and sales_line.brand_name and sales_line.brand_name not in brands:
                brands.append(sales_line.brand_name)
            if sales_line and sales_line.customer_sku and sales_line.customer_sku not in customer_skus:
                customer_skus.append(sales_line.customer_sku)
        facts[shipment_id] = {
            "factory_model": "、".join(codes) or None,
            "image_url": image_url,
            "color_name": "、".join(color_names) or None,
            "brand_name": "、".join(brands) or None,
            "customer_sku": "、".join(customer_skus) or None,
        }
    return facts


def _refunds_by_receivable(
    db: Session, tenant_id: int, receivable_ids: set[int]
) -> dict[int, list[AfterSalesReturn]]:
    if not receivable_ids:
        return {}
    rows = db.scalars(
        select(AfterSalesReturn).where(
            AfterSalesReturn.tenant_id == tenant_id,
            AfterSalesReturn.receivable_id.in_(receivable_ids),
        )
    ).all()
    grouped: dict[int, list[AfterSalesReturn]] = {}
    for row in rows:
        if row.receivable_id:
            grouped.setdefault(row.receivable_id, []).append(row)
    return grouped


def _posted_refund(rows: list[AfterSalesReturn]) -> Decimal:
    return _money(sum((_money(row.posted_receivable_refund) for row in rows), ZERO))


def _goods_amount(ar: Receivable, posted_refund: Decimal) -> Decimal:
    """出货行金额：货款减去已收，退货另列，不在这里扣掉。"""
    return (
        _money(ar.amount)
        - _money(ar.received_amount)
        + _money(ar.adjustment)
        + _money(posted_refund)
    )


def _split_signed(amount: Decimal) -> tuple[Decimal, Decimal]:
    amount = _money(amount)
    if amount >= ZERO:
        return amount, ZERO
    return ZERO, _money(-amount)


def _display_row(
    *,
    row_type: str,
    receivable_id: int | None,
    return_id: int | None,
    customer_id: int | None,
    customer_name: str | None,
    biz_date: date | None,
    shipment_no: str | None,
    return_no: str | None,
    sales_order_no: str | None,
    ordered_at: date | None,
    factory_model: str | None,
    image_url: str | None,
    color_name: str | None,
    brand_name: str | None,
    customer_sku: str | None,
    qty: int | None,
    unit_price: Decimal | None,
    amount: Decimal,
) -> dict:
    return {
        "row_key": f"{row_type}:{receivable_id or 0}:{return_id or 0}",
        "row_type": row_type,
        "receivable_id": receivable_id,
        "return_id": return_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "biz_date": biz_date,
        "ship_date": biz_date,
        "shipment_no": shipment_no,
        "return_no": return_no,
        "sales_order_no": sales_order_no,
        "ordered_at": ordered_at,
        "factory_model": factory_model,
        "product_code": factory_model,
        "image_url": image_url,
        "color_name": color_name,
        "brand_name": brand_name,
        "customer_sku": customer_sku,
        "qty": qty,
        "unit_price": _money(unit_price) if unit_price is not None else None,
        "amount": _money(amount),
    }


def _shipment_row(
    ar: Receivable,
    shipment: Shipment | None,
    order: SalesOrder | None,
    shipment_fact: dict | None,
    order_fact: dict | None,
    amount: Decimal,
) -> dict:
    shipment_fact = shipment_fact or {}
    order_fact = order_fact or {}
    biz_date = shipment.ship_date if shipment and shipment.ship_date else ar.receivable_date
    factory_model = shipment_fact.get("factory_model") or (
        "、".join(order_fact.get("codes") or []) or None
    )
    return _display_row(
        row_type="shipment",
        receivable_id=ar.id,
        return_id=None,
        customer_id=ar.customer_id,
        customer_name=ar.customer_name,
        biz_date=biz_date,
        shipment_no=shipment.shipment_no if shipment else None,
        return_no=None,
        sales_order_no=ar.sales_order_no,
        ordered_at=order.ordered_at if order else None,
        factory_model=factory_model,
        image_url=shipment_fact.get("image_url") or order_fact.get("image_url"),
        color_name=shipment_fact.get("color_name") or (
            "、".join(order_fact.get("colors") or []) or None
        ),
        brand_name=shipment_fact.get("brand_name") or (
            "、".join(order_fact.get("brands") or []) or None
        ),
        customer_sku=shipment_fact.get("customer_sku") or (
            "、".join(order_fact.get("customer_skus") or []) or None
        ),
        qty=shipment.total_qty if shipment else None,
        unit_price=shipment.unit_price if shipment else None,
        amount=amount,
    )


def _return_qty(row: AfterSalesReturn) -> int:
    qty = int(row.return_quantity or 0) or int(row.quantity or 0)
    return -qty if qty else 0


def _return_row(
    row: AfterSalesReturn,
    image_url: str | None,
    source_line: SalesOrderLine | None = None,
) -> dict:
    amount = -_money(row.posted_receivable_refund)
    brand_name = (row.customer_brand or "").strip() or (
        source_line.brand_name if source_line else None
    )
    customer_sku = (row.customer_model or "").strip() or (
        source_line.customer_sku if source_line else None
    )
    return _display_row(
        row_type="return",
        receivable_id=row.receivable_id,
        return_id=row.id,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        biz_date=row.return_date,
        shipment_no=None,
        return_no=row.return_no,
        sales_order_no=None,
        ordered_at=None,
        factory_model=row.factory_model,
        image_url=row.product_image_url or image_url,
        color_name=row.color,
        brand_name=brand_name,
        customer_sku=customer_sku,
        qty=_return_qty(row),
        unit_price=row.unit_price,
        amount=amount,
    )


def _in_date_range(value: date | None, date_from: date | None, date_to: date | None) -> bool:
    if date_from is None and date_to is None:
        return True
    if value is None:
        return False
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    return True


def _return_still_open(row: AfterSalesReturn, ar: Receivable | None) -> bool:
    """退货还没进对账单，且对应应收没有被直接收清。"""
    if _money(row.posted_receivable_refund) <= ZERO or row.statement_id:
        return False
    if ar is None:
        return True
    if ar.status == ReceivableStatus.void:
        return False
    if ar.statement_id:
        # 只结了出货、退货单自己还没勾走时，退货仍待结算。
        return True
    return _remaining(ar) != ZERO


def list_pending_lines(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None = None,
    sales_order_no: str | None = None,
    shipment_no: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    query = select(Receivable).where(
        Receivable.tenant_id == tenant_id,
        Receivable.status != ReceivableStatus.void,
        Receivable.statement_id.is_(None),
    )
    if customer_id:
        query = query.where(Receivable.customer_id == customer_id)
    receivables = list(db.scalars(query).all())
    shipments = _shipments(db, {ar.shipment_id for ar in receivables if ar.shipment_id})
    refunds = _refunds_by_receivable(db, tenant_id, {ar.id for ar in receivables})
    order_ids = {ar.sales_order_id for ar in receivables if ar.sales_order_id}
    shipment_facts = _shipment_facts(db, set(shipments))

    return_query = select(AfterSalesReturn).where(
        AfterSalesReturn.tenant_id == tenant_id,
        AfterSalesReturn.posted_receivable_refund > 0,
        AfterSalesReturn.statement_id.is_(None),
    )
    if customer_id:
        return_query = return_query.where(AfterSalesReturn.customer_id == customer_id)
    returns = list(db.scalars(return_query).all())
    linked_receivables = _by_id(
        db,
        Receivable,
        {row.receivable_id for row in returns if row.receivable_id},
    )
    source_lines = _by_id(
        db,
        SalesOrderLine,
        {row.source_sales_order_line_id for row in returns if row.source_sales_order_line_id},
    )
    for line in source_lines.values():
        order_ids.add(line.sales_order_id)
    orders = _sales_orders(db, order_ids)
    order_facts = _order_facts(db, set(orders))
    return_products = _by_id(
        db,
        OwnProduct,
        {row.own_product_id for row in returns if row.own_product_id},
    )

    rows: list[dict] = []
    for ar in receivables:
        if _remaining(ar) == ZERO:
            continue
        posted = _posted_refund(refunds.get(ar.id, []))
        amount = _goods_amount(ar, posted)
        if amount == ZERO:
            continue
        shipment = shipments.get(ar.shipment_id) if ar.shipment_id else None
        order = orders.get(ar.sales_order_id) if ar.sales_order_id else None
        rows.append(
            _shipment_row(
                ar,
                shipment,
                order,
                shipment_facts.get(ar.shipment_id) if ar.shipment_id else None,
                order_facts.get(ar.sales_order_id) if ar.sales_order_id else None,
                amount,
            )
        )
    for row in returns:
        ar = linked_receivables.get(row.receivable_id) if row.receivable_id else None
        if not _return_still_open(row, ar):
            continue
        source = source_lines.get(row.source_sales_order_line_id) if row.source_sales_order_line_id else None
        order = orders.get(source.sales_order_id) if source else None
        product = return_products.get(row.own_product_id) if row.own_product_id else None
        item = _return_row(row, product.image_url if product else None, source)
        # 退货不展示订单号，筛选仍按来源销售单匹配。
        item["_order_no"] = order.order_no if order else None
        rows.append(item)

    order_kw = (sales_order_no or "").strip().lower()
    ship_kw = (shipment_no or "").strip().lower()
    if order_kw or ship_kw or date_from or date_to:
        rows = [
            row
            for row in rows
            if (
                not order_kw
                or order_kw in str(row.get("sales_order_no") or row.get("_order_no") or "").lower()
            )
            and (
                not ship_kw
                or ship_kw in str(row.get("shipment_no") or "").lower()
                or ship_kw in str(row.get("return_no") or "").lower()
            )
            and _in_date_range(row.get("biz_date"), date_from, date_to)
        ]
    for row in rows:
        row.pop("_order_no", None)
    rows.sort(
        key=lambda row: (
            row.get("biz_date") or date.min,
            1 if row.get("row_type") == "shipment" else 0,
            row.get("receivable_id") or 0,
            row.get("return_id") or 0,
        ),
        reverse=True,
    )
    return rows


def pending_amount(rows: list[dict]) -> Decimal:
    return _money(sum((_money(row.get("amount")) for row in rows), ZERO))


def customer_sales_balance(db: Session, tenant_id: int, customer_id: int) -> dict:
    rows = list_pending_lines(db, tenant_id, customer_id=customer_id)
    pending = pending_amount(rows)
    carry = carry_balance(db, tenant_id, customer_id)
    partner = db.get(Partner, customer_id)
    name = ""
    if partner:
        name = (partner.short_name or partner.name or "").strip()
    return {
        "customer_id": customer_id,
        "customer_name": name,
        "carry_balance": carry,
        "pending_amount": pending,
        "debt": _money(carry + pending),
    }


def sales_debt_total(db: Session, tenant_id: int) -> dict:
    customer_ids = set(
        db.scalars(
            select(Receivable.customer_id).where(
                Receivable.tenant_id == tenant_id,
                Receivable.customer_id.is_not(None),
                Receivable.status != ReceivableStatus.void,
            )
        ).all()
    )
    for customer_id in db.scalars(
        select(AccountStatement.partner_id).where(
            AccountStatement.tenant_id == tenant_id,
            AccountStatement.direction == SettlementDirection.customer,
            AccountStatement.statement_kind == SALES_KIND,
        )
    ).all():
        customer_ids.add(customer_id)
    for customer_id in db.scalars(
        select(Payment.customer_id).where(
            Payment.tenant_id == tenant_id,
            Payment.status == PaymentStatus.posted,
            Payment.statement_id.is_(None),
            Payment.customer_id.is_not(None),
        )
    ).all():
        customer_ids.add(customer_id)
    customer_ids.discard(None)
    rows = []
    total = ZERO
    for customer_id in customer_ids:
        item = customer_sales_balance(db, tenant_id, int(customer_id))
        if item["debt"] == ZERO and item["pending_amount"] == ZERO and item["carry_balance"] == ZERO:
            continue
        rows.append(item)
        total += item["debt"]
    rows.sort(key=lambda row: row["debt"], reverse=True)
    return {"debt": _money(total), "customers": rows}


def generate_sales_statement(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int,
    receivable_ids: list[int] | None = None,
    return_ids: list[int] | None = None,
    statement_no: str | None = None,
    statement_date: date | None = None,
    user_id: int | None = None,
) -> dict:
    from app.services import settlement_service

    receivable_ids = list(dict.fromkeys(receivable_ids or []))
    return_ids = list(dict.fromkeys(return_ids or []))
    if not receivable_ids and not return_ids:
        raise FinanceError("nothing_selected", "请先勾选待结算明细")
    partner = db.get(Partner, customer_id)
    if not partner or partner.tenant_id != tenant_id:
        raise FinanceError("partner_not_found", "客户不存在")
    receivables: list[Receivable] = []
    if receivable_ids:
        receivables = list(
            db.scalars(
                select(Receivable).where(
                    Receivable.tenant_id == tenant_id,
                    Receivable.id.in_(receivable_ids),
                )
            ).all()
        )
        if len(receivables) != len(set(receivable_ids)):
            raise FinanceError("receivable_not_found", "有出货不存在")
    refunds = _refunds_by_receivable(db, tenant_id, {ar.id for ar in receivables})
    shipment_amounts: dict[int, Decimal] = {}
    for ar in receivables:
        if ar.status == ReceivableStatus.void or ar.customer_id != customer_id:
            raise FinanceError("wrong_customer", "一次只能勾选同一个客户")
        if ar.statement_id:
            raise FinanceError("already_statemented", "出货已进对账单")
        amount = _goods_amount(ar, _posted_refund(refunds.get(ar.id, [])))
        if _remaining(ar) == ZERO or amount == ZERO:
            raise FinanceError("nothing_to_statement", "这张出货没有待结算金额")
        shipment_amounts[ar.id] = amount

    returns: list[AfterSalesReturn] = []
    if return_ids:
        returns = list(
            db.scalars(
                select(AfterSalesReturn).where(
                    AfterSalesReturn.tenant_id == tenant_id,
                    AfterSalesReturn.id.in_(return_ids),
                )
            ).all()
        )
        if len(returns) != len(set(return_ids)):
            raise FinanceError("return_not_found", "有退货单不存在")
    linked = _by_id(db, Receivable, {row.receivable_id for row in returns if row.receivable_id})
    return_amounts: dict[int, Decimal] = {}
    for row in returns:
        if row.customer_id != customer_id:
            raise FinanceError("wrong_customer", "一次只能勾选同一个客户")
        if row.statement_id:
            raise FinanceError("already_statemented", "退货已进对账单")
        ar = linked.get(row.receivable_id) if row.receivable_id else None
        if not _return_still_open(row, ar):
            raise FinanceError("nothing_to_statement", "退货没有待结算金额")
        return_amounts[row.id] = -_money(row.posted_receivable_refund)

    opening = carry_balance(db, tenant_id, customer_id)
    current = _money(
        sum(shipment_amounts.values(), ZERO) + sum(return_amounts.values(), ZERO)
    )
    closing = _money(opening + current)
    booked_on = statement_date or date.today()
    number = (statement_no or "").strip() or settlement_service._next_statement_no(
        db, tenant_id, SettlementDirection.customer, booked_on
    )
    if len(number) > 50:
        raise FinanceError("statement_no_invalid", "对账单号不能超过50个字")
    taken = db.scalar(
        select(AccountStatement.id).where(
            AccountStatement.tenant_id == tenant_id,
            AccountStatement.statement_no == number,
        )
    )
    if taken:
        raise FinanceError("statement_no_taken", "对账单号已存在")
    shipments = _shipments(db, {ar.shipment_id for ar in receivables if ar.shipment_id})
    statement = AccountStatement(
        tenant_id=tenant_id,
        statement_no=number,
        partner_id=customer_id,
        partner_name=partner.short_name or partner.name,
        direction=SettlementDirection.customer,
        statement_kind=SALES_KIND,
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
        notes="客户待结算勾选生成",
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
    for ar in receivables:
        shipment = shipments.get(ar.shipment_id) if ar.shipment_id else None
        debit, credit = _split_signed(shipment_amounts[ar.id])
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="receivable",
                source_id=ar.id,
                business_date=shipment.ship_date if shipment and shipment.ship_date else ar.receivable_date,
                document_no=shipment.shipment_no if shipment else ar.sales_order_no,
                description=(
                    f"销售单 {ar.sales_order_no} · 出货货款"
                    if ar.sales_order_no
                    else "出货货款"
                ),
                debit_amount=debit,
                credit_amount=credit,
                sort_order=sort_order,
            )
        )
        ar.statement_id = statement.id
        sort_order += 1
    for row in returns:
        debit, credit = _split_signed(return_amounts[row.id])
        statement.lines.append(
            AccountStatementLine(
                tenant_id=tenant_id,
                source_type="after_sales_return",
                source_id=row.id,
                business_date=row.return_date,
                document_no=row.return_no,
                description=f"退货 {row.return_no}",
                debit_amount=debit,
                credit_amount=credit,
                sort_order=sort_order,
            )
        )
        row.statement_id = statement.id
        sort_order += 1
    db.commit()
    return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)


def list_sales_statements(
    db: Session, tenant_id: int, *, customer_id: int | None = None
) -> list[dict]:
    from app.services import settlement_service

    query = select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.direction == SettlementDirection.customer,
        AccountStatement.statement_kind == SALES_KIND,
    )
    if customer_id:
        query = query.where(AccountStatement.partner_id == customer_id)
    rows = list(db.scalars(query.order_by(AccountStatement.id.desc())).all())
    latest_ids = set()
    if customer_id:
        latest = latest_sales_statement(db, tenant_id, customer_id)
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
        item["can_receive"] = item["is_latest"] and unpaid > ZERO
        item["can_void"] = item["is_latest"] and _money(item.get("settled_amount")) <= ZERO
        item["carried_to_no"] = None
        payments = db.scalars(
            select(Payment).where(
                Payment.statement_id == row.id,
                Payment.status == PaymentStatus.posted,
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
    live_by_customer: dict[int, list[dict]] = {}
    for item in out:
        if item.get("status") == AccountStatementStatus.void.value:
            continue
        live_by_customer.setdefault(item["partner_id"], []).append(item)
    for group in live_by_customer.values():
        group.sort(key=lambda item: item["id"])
        for prev, nxt in zip(group, group[1:]):
            prev["carried_to_no"] = nxt["statement_no"]
    return out


def receive_on_statement(
    db: Session,
    tenant_id: int,
    statement_id: int,
    *,
    amount: Decimal,
    payment_date: date,
    method: str = "bank",
    voucher_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict:
    from app.services import finance_service

    statement = db.get(AccountStatement, statement_id)
    if (
        not statement
        or statement.tenant_id != tenant_id
        or (statement.statement_kind or "period") != SALES_KIND
    ):
        raise FinanceError("statement_not_found", "客户对账单不存在")
    if not is_latest_sales_statement(db, statement):
        raise FinanceError("statement_not_latest", "只能收取最新一张客户对账单")
    unpaid = unpaid_of_statement(db, statement)
    if unpaid <= ZERO:
        raise FinanceError("nothing_to_receive", "这张对账单没有未收余款")
    if amount > unpaid:
        raise FinanceError("statement_over_payment", "收款超过对账单未收金额")
    return finance_service.create_payment(
        db,
        tenant_id,
        customer_id=statement.partner_id,
        customer_name=statement.partner_name,
        amount=amount,
        payment_date=payment_date,
        method=method,
        voucher_no=voucher_no,
        notes=notes,
        allocations=[],
        statement_id=statement.id,
        user_id=user_id,
    )


def void_sales_statement(db: Session, tenant_id: int, statement_id: int) -> dict:
    from app.services import settlement_service

    statement = db.get(AccountStatement, statement_id)
    if (
        not statement
        or statement.tenant_id != tenant_id
        or (statement.statement_kind or "period") != SALES_KIND
    ):
        raise FinanceError("statement_not_found", "客户对账单不存在")
    if statement.status == AccountStatementStatus.void:
        return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)
    if not is_latest_sales_statement(db, statement):
        raise FinanceError("statement_not_latest", "只能作废还没把余额交给下一张的最新对账单")
    if statement_received_amount(db, statement.id) > ZERO:
        raise FinanceError("statement_has_receipt", "对账单已有收款，须先作废收款")
    for ar in db.scalars(select(Receivable).where(Receivable.statement_id == statement.id)).all():
        ar.statement_id = None
    for row in db.scalars(
        select(AfterSalesReturn).where(AfterSalesReturn.statement_id == statement.id)
    ).all():
        row.statement_id = None
    statement.status = AccountStatementStatus.void
    db.commit()
    return settlement_service.statement_out(db, tenant_id, statement.id, with_lines=True)


def receivable_item(db: Session, receivable_id: int) -> dict | None:
    ar = db.get(Receivable, receivable_id)
    if not ar:
        return None
    shipment = db.get(Shipment, ar.shipment_id) if ar.shipment_id else None
    order = db.get(SalesOrder, ar.sales_order_id) if ar.sales_order_id else None
    shipment_fact = _shipment_facts(db, {shipment.id}).get(shipment.id) if shipment else None
    order_fact = _order_facts(db, {order.id}).get(order.id) if order else None
    posted = _posted_refund(_refunds_by_receivable(db, ar.tenant_id, {ar.id}).get(ar.id, []))
    amount = _goods_amount(ar, posted)
    if amount == ZERO:
        amount = _remaining(ar)
    return _shipment_row(ar, shipment, order, shipment_fact, order_fact, amount)


def return_item(db: Session, return_id: int) -> dict | None:
    row = db.get(AfterSalesReturn, return_id)
    if not row:
        return None
    source = (
        db.get(SalesOrderLine, row.source_sales_order_line_id)
        if row.source_sales_order_line_id
        else None
    )
    product = db.get(OwnProduct, row.own_product_id) if row.own_product_id else None
    return _return_row(row, product.image_url if product else None, source)
