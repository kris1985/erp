"""采购退货：库存池勾选，确认后减可用库存，并在供应商待结算记负数行。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PricingUnit,
    SharedLedgerType,
    Size,
    SupplierProduct,
)
from app.services.ap_service import ApError
from app.services.material_service import _get_shared_stock, adjust_shared_stock


ZERO = Decimal("0")
RETURN_SOURCE = "purchase_return"
PoolKey = tuple[int, int | None]


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _cent(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _key(supplier_product_id: int, size_id: int | None) -> PoolKey:
    return (int(supplier_product_id), int(size_id) if size_id is not None else None)


def returnable_qty(pool_qty: Decimal) -> Decimal:
    """可退数量就是库存池可用数。不要求有送货单或到货记录。"""
    pool = _money(pool_qty)
    return pool if pool > ZERO else ZERO


def returnable_fields(pool_qty: Decimal) -> dict:
    return {"returnable_qty": returnable_qty(pool_qty)}


def _line_specs(lines: list[dict]) -> list[dict]:
    if not lines:
        raise ApError("empty_selection", "请先勾选物料")
    specs = []
    seen: set[PoolKey] = set()
    for raw in lines:
        sp_id = raw.get("supplier_product_id")
        if not sp_id:
            raise ApError("product_not_found", "物料不存在")
        size_id = raw.get("size_id")
        size_id = int(size_id) if size_id is not None else None
        key = _key(int(sp_id), size_id)
        if key in seen:
            raise ApError("duplicate_line", "同一物料尺码不能重复退货")
        seen.add(key)
        qty = raw.get("qty")
        raw_price = raw.get("unit_price")
        specs.append(
            {
                "supplier_product_id": int(sp_id),
                "size_id": size_id,
                "key": key,
                "qty": _cent(qty) if qty is not None else None,
                "unit_price": _cent(raw_price) if raw_price is not None else None,
            }
        )
    return specs


def _prepare(db: Session, tenant_id: int, lines: list[dict], *, with_qty: bool) -> tuple[Partner, list[dict]]:
    specs = _line_specs(lines)
    prepared = []
    supplier_id: int | None = None
    for spec in specs:
        product = db.get(SupplierProduct, spec["supplier_product_id"])
        if not product or product.tenant_id != tenant_id:
            raise ApError("product_not_found", "物料不存在")
        if not product.partner_id:
            raise ApError("supplier_missing", "物料没有供应商")
        if supplier_id is None:
            supplier_id = int(product.partner_id)
        elif int(product.partner_id) != supplier_id:
            raise ApError("mixed_supplier", "一次只能退同一个供应商")
        catalog_price = _cent(product.unit_price)
        price = spec["unit_price"] if spec["unit_price"] is not None else catalog_price
        if price < ZERO:
            raise ApError("invalid_price", "单价不能为负")
        stock = _get_shared_stock(db, tenant_id, spec["supplier_product_id"], spec["size_id"])
        pool = stock.qty if stock else ZERO
        cap = returnable_qty(pool)
        qty = spec["qty"]
        if with_qty:
            if qty is None or qty <= ZERO:
                raise ApError("invalid_qty", "退货数量须大于 0")
            if qty > cap:
                raise ApError("qty_exceeds_returnable", "退货数量不能超过可退数量")
        prepared.append(
            {
                **spec,
                "product": product,
                "unit_price": price,
                "returnable_qty": cap,
                "qty": qty if with_qty else cap,
            }
        )
    partner = db.get(Partner, supplier_id) if supplier_id else None
    if not partner or partner.tenant_id != tenant_id:
        raise ApError("supplier_not_found", "供应商不存在")
    return partner, prepared


def _supplier_name(partner: Partner) -> str:
    return (partner.short_name or partner.name or "").strip() or f"供应商#{partner.id}"


def _snapshot(db: Session, product: SupplierProduct, size_id: int | None) -> dict:
    color = db.get(Color, product.color_id) if product.color_id else None
    size = db.get(Size, size_id) if size_id else None
    unit = db.get(PricingUnit, product.pricing_unit_id) if product.pricing_unit_id else None
    return {
        "item_code": product.product_code,
        "item_name": product.name,
        "color_name": color.name if color else None,
        "size_value": size.size_value if size else None,
        "unit_name": unit.name if unit else None,
        "image_url": product.image_url,
    }


def quote_purchase_return(db: Session, tenant_id: int, lines: list[dict]) -> dict:
    partner, prepared = _prepare(db, tenant_id, lines, with_qty=False)
    out = []
    for row in prepared:
        snap = _snapshot(db, row["product"], row["size_id"])
        out.append(
            {
                "supplier_product_id": row["supplier_product_id"],
                "size_id": row["size_id"],
                "supplier_id": partner.id,
                "supplier_name": _supplier_name(partner),
                "returnable_qty": row["returnable_qty"],
                "unit_price": row["unit_price"],
                **snap,
            }
        )
    return {"supplier_id": partner.id, "supplier_name": _supplier_name(partner), "lines": out}


def create_purchase_return(
    db: Session,
    tenant_id: int,
    lines: list[dict],
    *,
    note: str | None = None,
    user_id: int | None = None,
) -> dict:
    partner, prepared = _prepare(db, tenant_id, lines, with_qty=True)
    text = (note or "").strip() or None
    if text and len(text) > 255:
        raise ApError("note_too_long", "备注不能超过255个字")
    today = date.today()
    amount = ZERO
    for row in prepared:
        amount += _cent(-(row["qty"] * row["unit_price"]))
    payable = Payable(
        tenant_id=tenant_id,
        supplier_id=partner.id,
        supplier_name=_supplier_name(partner),
        purchase_order_id=None,
        payable_date=today,
        due_date=today,
        payment_term_days=0,
        amount=amount,
        adjustment=ZERO,
        paid_amount=ZERO,
        status=PayableStatus.open,
        notes=text,
        delivery_note_no=None,
    )
    db.add(payable)
    db.flush()
    line_ids: list[int] = []
    for sort_order, row in enumerate(prepared):
        snap = _snapshot(db, row["product"], row["size_id"])
        qty = row["qty"]
        price = row["unit_price"]
        line_amount = _cent(-(qty * price))
        line = PayableLine(
            tenant_id=tenant_id,
            payable_id=payable.id,
            source_type=RETURN_SOURCE,
            source_ref_id=None,
            source_document_no=None,
            supplier_product_id=row["supplier_product_id"],
            size_id=row["size_id"],
            item_code=snap["item_code"],
            item_name=snap["item_name"],
            color_name=snap["color_name"],
            size_value=snap["size_value"],
            unit_name=snap["unit_name"],
            qty=-qty,
            unit_price=price,
            amount=line_amount,
            sort_order=sort_order,
        )
        db.add(line)
        db.flush()
        line_ids.append(line.id)
        adjust_shared_stock(
            db,
            tenant_id,
            row["supplier_product_id"],
            -qty,
            size_id=row["size_id"],
            unit_cost=price,
            note=text,
            user_id=user_id,
            ledger_type=SharedLedgerType.purchase_return,
            ref_type=RETURN_SOURCE,
            ref_id=line.id,
        )
    db.commit()
    return {"payable_id": payable.id, "line_ids": line_ids, "amount": amount}


def void_purchase_return_lines(
    db: Session,
    tenant_id: int,
    line_ids: list[int],
    *,
    user_id: int | None = None,
) -> dict:
    ids = list(dict.fromkeys(int(line_id) for line_id in (line_ids or []) if line_id))
    if not ids:
        raise ApError("empty_selection", "请先勾选退货明细")
    lines = list(
        db.scalars(
            select(PayableLine)
            .where(PayableLine.tenant_id == tenant_id, PayableLine.id.in_(ids))
            .options(selectinload(PayableLine.payable))
        ).all()
    )
    if len(lines) != len(ids):
        raise ApError("line_not_found", "有退货明细不存在")
    for line in lines:
        payable = line.payable
        if (
            line.source_type != RETURN_SOURCE
            or not payable
            or payable.tenant_id != tenant_id
            or payable.status == PayableStatus.void
        ):
            raise ApError("not_return_line", "只能作废退货行")
        if line.statement_id or _money(payable.paid_amount) > ZERO or _money(payable.adjustment) != ZERO:
            raise ApError("already_statemented", "已经进对账单的退货不能作废")
        if not line.supplier_product_id:
            raise ApError("product_not_found", "退货行缺少物料")

    by_payable: dict[int, list[PayableLine]] = {}
    for line in lines:
        by_payable.setdefault(line.payable_id, []).append(line)
    for group in by_payable.values():
        payable = group[0].payable
        note = (payable.notes or "").strip()
        void_note = f"作废采购退货：{note}" if note else "作废采购退货"
        void_ids = {line.id for line in group}
        remaining = [line for line in payable.lines if line.id not in void_ids]
        for line in group:
            adjust_shared_stock(
                db,
                tenant_id,
                int(line.supplier_product_id),
                -_money(line.qty),
                size_id=line.size_id,
                note=void_note[:255],
                user_id=user_id,
                ledger_type=SharedLedgerType.purchase_return,
                ref_type=RETURN_SOURCE,
                ref_id=line.id,
            )
        if remaining:
            for line in group:
                db.delete(line)
            payable.amount = _money(sum((_money(item.amount) for item in remaining), ZERO))
        else:
            db.delete(payable)
    db.commit()
    return {"voided_line_ids": ids}
