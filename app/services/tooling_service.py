"""模具：独立档案、按码库存、到货登记并挂供应商待结算。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Department,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PurchaseOrder,
    Size,
    ToolingItem,
    ToolingLedger,
    ToolingReceipt,
    ToolingReceiptLine,
    ToolingReceiptSize,
    ToolingStock,
)
from app.services.ap_service import _refresh_ap_status


KIND_SHOE = "shoe_last"
KIND_KNIFE = "knife_die"
KIND_SOLE = "sole_mold"
KIND_HEEL = "heel_mold"
KIND_OTHER = "other_mold"
KINDS: dict[str, tuple[str, str]] = {
    KIND_SHOE: ("楦头", "双"),
    KIND_KNIFE: ("刀模", "套"),
    KIND_SOLE: ("底模", "套"),
    KIND_HEEL: ("鞋跟模具", "套"),
    KIND_OTHER: ("其它模具", "套"),
}
SOURCE_RECEIVE = "tooling_receive"
LEDGER_SOURCE_LABELS = {
    "receive": "登记到货",
    "purchase_receive": "采购到货",
    "adjust": "调整",
}


class ToolingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _supplier_name(partner: Partner) -> str:
    return (partner.short_name or partner.name or "").strip() or f"供应商#{partner.id}"


def _kind_names() -> str:
    return "、".join(label for label, _unit in KINDS.values())


def _kind_label(kind: str) -> str:
    return KINDS.get(kind, (kind, ""))[0]


def _unit_name(kind: str) -> str:
    return KINDS.get(kind, ("", "个"))[1]


def _item_title(item: ToolingItem) -> str:
    label = _kind_label(item.kind)
    name = (item.name or "").strip()
    if name:
        return f"{label} {name}"
    return label


def _load_sizes(db: Session, tenant_id: int, size_ids: set[int]) -> dict[int, Size]:
    if not size_ids:
        return {}
    rows = db.scalars(
        select(Size).where(Size.tenant_id == tenant_id, Size.id.in_(size_ids))
    ).all()
    return {row.id: row for row in rows}


_QTY_STEP = Decimal("0.1")
_QTY_MAX = Decimal("100000")
_HALF_QTY_MESSAGE = "数量只能填整数或 0.5，0.5 表示一只"


def _as_qty(value) -> Decimal:
    """到货数量只允许整数或 0.5。0.5 表示一只。"""
    try:
        raw = Decimal(str(0 if value is None else value))
    except Exception as exc:
        raise ToolingError("qty", _HALF_QTY_MESSAGE) from exc
    if raw < 0:
        raise ToolingError("qty", "数量不能为负")
    if raw > _QTY_MAX:
        raise ToolingError("qty", "数量不能超过100000")
    doubled = raw * 2
    nearest = doubled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if (doubled - nearest).copy_abs() > Decimal("0.0001"):
        raise ToolingError("qty", _HALF_QTY_MESSAGE)
    return (nearest / 2).quantize(_QTY_STEP)


def _stored_qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_QTY_STEP)


def _qty_out(value) -> int | float:
    qty = _stored_qty(value)
    if qty == qty.to_integral_value():
        return int(qty)
    return float(qty)


def _positive_sizes(sizes: list[tuple[int, Decimal | int | float | str]]) -> list[tuple[int, Decimal]]:
    merged: dict[int, Decimal] = {}
    for size_id, qty in sizes:
        parsed = _as_qty(qty)
        if parsed == 0:
            continue
        key = int(size_id)
        merged[key] = merged.get(key, Decimal("0")) + parsed
    if not merged:
        raise ToolingError("qty", "请填写到货数量")
    return list(merged.items())


def _next_receipt_no(db: Session, tenant_id: int, on: date) -> str:
    prefix = f"XT{on.strftime('%Y%m%d')}"
    existing = db.scalars(
        select(ToolingReceipt.receipt_no).where(
            ToolingReceipt.tenant_id == tenant_id,
            ToolingReceipt.receipt_no.like(f"{prefix}%"),
        )
    ).all()
    seq = len(existing) + 1
    while True:
        number = f"{prefix}{seq:03d}"
        taken = db.scalar(
            select(ToolingReceipt.id).where(
                ToolingReceipt.tenant_id == tenant_id,
                ToolingReceipt.receipt_no == number,
            )
        )
        if not taken:
            return number
        seq += 1


def _dept_stock_map(db: Session, item_ids: set[int]) -> dict[int, dict[int | None, dict[int, Decimal]]]:
    if not item_ids:
        return {}
    rows = db.scalars(
        select(ToolingStock).where(ToolingStock.tooling_item_id.in_(item_ids))
    ).all()
    out: dict[int, dict[int | None, dict[int, Decimal]]] = {}
    for row in rows:
        out.setdefault(row.tooling_item_id, {}).setdefault(row.department_id, {})[
            row.size_id
        ] = _stored_qty(row.qty)
    return out


def _item_out(
    item: ToolingItem,
    qty_by_size: dict[int, Decimal],
    department_id: int | None,
    department_name: str | None,
) -> dict:
    total = sum(qty_by_size.values(), Decimal("0"))
    price = _money(item.last_unit_price)
    return {
        "id": item.id,
        "row_key": f"{item.id}:{department_id or 0}",
        "code": item.code,
        "name": item.name,
        "kind": item.kind,
        "kind_label": _kind_label(item.kind),
        "unit_name": _unit_name(item.kind),
        "department_id": department_id,
        "department_name": department_name,
        "last_unit_price": float(price) if item.last_unit_price is not None else None,
        "total_qty": _qty_out(total),
        "amount": float(_money(total * price)),
        "sizes": {
            str(size_id): _qty_out(qty)
            for size_id, qty in qty_by_size.items()
            if _stored_qty(qty) != 0
        },
        "is_active": bool(item.is_active),
    }


def _department_names(db: Session, department_ids: set[int]) -> dict[int, str]:
    if not department_ids:
        return {}
    rows = db.scalars(select(Department).where(Department.id.in_(department_ids))).all()
    return {row.id: row.name for row in rows}


def list_items(
    db: Session,
    tenant_id: int,
    *,
    kind: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    query = select(ToolingItem).where(ToolingItem.tenant_id == tenant_id)
    if kind:
        if kind not in KINDS:
            raise ToolingError("kind", f"分类只能是{_kind_names()}")
        query = query.where(ToolingItem.kind == kind)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.where(
            (ToolingItem.code.like(like)) | (ToolingItem.name.like(like))
        )
    items = list(db.scalars(query.order_by(ToolingItem.code, ToolingItem.id)).all())
    stocks = _dept_stock_map(db, {item.id for item in items})
    names = _department_names(
        db,
        {dept_id for by_dept in stocks.values() for dept_id in by_dept if dept_id},
    )
    rows: list[dict] = []
    for item in items:
        by_dept = stocks.get(item.id) or {}
        if not by_dept:
            rows.append(_item_out(item, {}, None, None))
            continue
        ordered = sorted(
            by_dept,
            key=lambda dept_id: (dept_id is None, names.get(dept_id or 0, ""), dept_id or 0),
        )
        emitted = False
        for dept_id in ordered:
            qty = by_dept[dept_id]
            if not any(qty.values()):
                continue
            rows.append(_item_out(item, qty, dept_id, names.get(dept_id) if dept_id else None))
            emitted = True
        if not emitted:
            rows.append(_item_out(item, {}, None, None))
    return rows


def _get_item(db: Session, tenant_id: int, item_id: int) -> ToolingItem:
    item = db.get(ToolingItem, item_id)
    if not item or item.tenant_id != tenant_id:
        raise ToolingError("not_found", "模具不存在")
    return item


def _apply_delta(
    db: Session,
    item: ToolingItem,
    size_id: int,
    delta: Decimal,
    *,
    department_id: int | None,
    source_type: str,
    source_ref_id: int | None,
    notes: str | None,
    user_id: int | None,
) -> Decimal:
    dept_match = (
        ToolingStock.department_id.is_(None)
        if department_id is None
        else ToolingStock.department_id == department_id
    )
    if delta == 0:
        stock = db.scalar(
            select(ToolingStock).where(
                ToolingStock.tooling_item_id == item.id,
                ToolingStock.size_id == size_id,
                dept_match,
            )
        )
        return _stored_qty(stock.qty) if stock else Decimal("0")
    stock = db.scalar(
        select(ToolingStock).where(
            ToolingStock.tooling_item_id == item.id,
            ToolingStock.size_id == size_id,
            dept_match,
        )
    )
    if stock is None:
        stock = ToolingStock(
            tenant_id=item.tenant_id,
            tooling_item_id=item.id,
            department_id=department_id,
            size_id=size_id,
            qty=0,
        )
        db.add(stock)
        db.flush()
    delta_qty = _stored_qty(delta)
    new_qty = _stored_qty(stock.qty) + delta_qty
    if new_qty < 0:
        raise ToolingError("qty", "调整后库存不能为负")
    stock.qty = new_qty
    db.add(
        ToolingLedger(
            tenant_id=item.tenant_id,
            tooling_item_id=item.id,
            department_id=department_id,
            size_id=size_id,
            qty_delta=delta_qty,
            qty_after=new_qty,
            source_type=source_type,
            source_ref_id=source_ref_id,
            notes=(notes or "").strip() or None,
            created_by=user_id,
            created_at=datetime.now(),
        )
    )
    return new_qty


def list_use_departments(db: Session, tenant_id: int) -> list[dict]:
    rows = db.scalars(
        select(Department)
        .where(
            Department.tenant_id == tenant_id,
            Department.is_active.is_(True),
            Department.parent_id.is_(None),
            or_(Department.name.contains("开发"), Department.name.contains("生产")),
        )
        .order_by(Department.sort_order, Department.id)
    ).all()
    return [{"id": row.id, "name": row.name} for row in rows]


def resolve_production_department(db: Session, tenant_id: int) -> Department:
    """楦头/刀模固定记入生产部（优先精确名「生产部」）。"""
    rows = db.scalars(
        select(Department)
        .where(
            Department.tenant_id == tenant_id,
            Department.is_active.is_(True),
            Department.parent_id.is_(None),
            Department.name.contains("生产"),
        )
        .order_by(Department.sort_order, Department.id)
    ).all()
    if not rows:
        raise ToolingError("department", "请先在员工与部门里建立名称带「生产」的一级部门")
    exact = next((d for d in rows if (d.name or "").strip() == "生产部"), None)
    return exact or rows[0]


def _use_department(
    db: Session, tenant_id: int, department_id: int | None, *, kind: str | None = None
) -> Department:
    # 楦头、刀模：部门固定生产部，忽略前端传入
    if kind in (KIND_SHOE, KIND_KNIFE):
        return resolve_production_department(db, tenant_id)
    dept = db.get(Department, department_id) if department_id else None
    if not dept or dept.tenant_id != tenant_id or not dept.is_active:
        raise ToolingError("department", "请选择使用部门")
    if dept.parent_id is not None:
        raise ToolingError("department", "请选择一级部门")
    if "开发" not in (dept.name or "") and "生产" not in (dept.name or ""):
        raise ToolingError("department", "请选择名称带「开发」或「生产」的一级部门")
    return dept


def apply_purchase_receive_to_tooling(
    db: Session,
    tenant_id: int,
    *,
    product_code: str,
    size_id: int | None,
    qty: Decimal,
    unit_price: Decimal | None,
    po_id: int,
    po_no: str,
    user_id: int | None,
) -> None:
    """采购到货：楦头不进物料仓，直接入模具仓（生产部）；待结算仍走采购应付。"""
    code = (product_code or "").strip()
    if not code:
        raise ToolingError("code", "楦头物料缺少编号，无法入模具仓")
    if size_id is None:
        raise ToolingError("size", f"楦头 {code} 到货必须按码")
    size = db.get(Size, size_id)
    if not size or size.tenant_id != tenant_id:
        raise ToolingError("size", f"楦头 {code} 尺码不存在")
    qty_dec = _stored_qty(qty)
    if qty_dec <= 0:
        return
    dept = resolve_production_department(db, tenant_id)
    item = db.scalar(
        select(ToolingItem).where(ToolingItem.tenant_id == tenant_id, ToolingItem.code == code)
    )
    if item is None:
        item = ToolingItem(
            tenant_id=tenant_id,
            code=code,
            name=None,
            kind=KIND_SHOE,
            last_unit_price=_money(unit_price) if unit_price is not None else None,
            is_active=True,
        )
        db.add(item)
        db.flush()
    else:
        if item.kind != KIND_SHOE:
            raise ToolingError(
                "kind",
                f"编号 {code} 已是{_kind_label(item.kind)}，不能作为楦头入库",
            )
        if unit_price is not None:
            item.last_unit_price = _money(unit_price)
        item.is_active = True
    _apply_delta(
        db,
        item,
        size_id,
        qty_dec,
        department_id=dept.id,
        source_type="purchase_receive",
        source_ref_id=po_id,
        notes=f"采购到货 {po_no} {dept.name}",
        user_id=user_id,
    )


def receive(
    db: Session,
    tenant_id: int,
    *,
    kind: str,
    supplier_id: int,
    receipt_date: date | None,
    delivery_note_no: str | None,
    notes: str | None,
    lines: list[dict],
    user_id: int | None,
) -> dict:
    if kind not in KINDS:
        raise ToolingError("kind", f"请选择{_kind_names()}")
    if not lines:
        raise ToolingError("lines", "请至少填写一个编号")
    if len(lines) > 40:
        raise ToolingError("lines", "一次最多登记40个编号")
    partner = db.get(Partner, supplier_id)
    if (
        not partner
        or partner.tenant_id != tenant_id
        or not partner.is_supplier
        or not partner.is_active
    ):
        raise ToolingError("supplier", "请选择供应商")
    booked = receipt_date or date.today()
    note_no = (delivery_note_no or "").strip() or None
    remark = (notes or "").strip() or None

    prepared: list[dict] = []
    seen_codes: set[str] = set()
    all_size_ids: set[int] = set()
    for raw in lines:
        code = str(raw.get("code") or "").strip()
        if not code:
            raise ToolingError("code", "请填写编号")
        if len(code) > 50:
            raise ToolingError("code", "编号不能超过50个字")
        if code in seen_codes:
            raise ToolingError("code", f"编号 {code} 在本单重复")
        seen_codes.add(code)
        dept = _use_department(db, tenant_id, raw.get("department_id"), kind=kind)
        price = _money(raw.get("unit_price"))
        if price <= 0:
            raise ToolingError("price", f"编号 {code} 请填写单价")
        try:
            qty_rows = _positive_sizes(list(raw.get("sizes") or []))
        except ToolingError as exc:
            if exc.code == "qty" and exc.message == "请填写到货数量":
                raise ToolingError("qty", f"编号 {code} 请填写到货数量") from exc
            if exc.code == "qty":
                raise ToolingError("qty", f"编号 {code} 的{exc.message}") from exc
            raise
        all_size_ids.update(size_id for size_id, _qty in qty_rows)
        prepared.append(
            {"kind": kind, "code": code, "price": price, "sizes": qty_rows, "dept": dept}
        )

    size_map = _load_sizes(db, tenant_id, all_size_ids)
    if len(size_map) != len(all_size_ids):
        raise ToolingError("size", "有尺码不存在")

    items: list[ToolingItem] = []
    for row in prepared:
        item = db.scalar(
            select(ToolingItem).where(
                ToolingItem.tenant_id == tenant_id, ToolingItem.code == row["code"]
            )
        )
        if item is None:
            item = ToolingItem(
                tenant_id=tenant_id,
                code=row["code"],
                name=None,
                kind=row["kind"],
                last_unit_price=row["price"],
                is_active=True,
            )
            db.add(item)
            db.flush()
        else:
            if item.kind != row["kind"]:
                raise ToolingError(
                    "kind",
                    f"编号 {row['code']} 已是{_kind_label(item.kind)}，不能改成{_kind_label(row['kind'])}",
                )
            item.last_unit_price = row["price"]
            item.is_active = True
        items.append(item)

    receipt = ToolingReceipt(
        tenant_id=tenant_id,
        receipt_no=_next_receipt_no(db, tenant_id, booked),
        supplier_id=partner.id,
        supplier_name=_supplier_name(partner),
        receipt_date=booked,
        delivery_note_no=note_no,
        notes=remark,
        created_by=user_id,
        created_at=datetime.now(),
    )
    db.add(receipt)
    db.flush()

    supplier_label = _supplier_name(partner)
    payable_rows: list[tuple[ToolingItem, ToolingReceiptSize, Decimal]] = []
    amount = Decimal("0")
    for item, row in zip(items, prepared):
        price = row["price"]
        line = ToolingReceiptLine(
            tenant_id=tenant_id,
            receipt_id=receipt.id,
            department_id=row["dept"].id,
            tooling_item_id=item.id,
            unit_price=price,
        )
        db.add(line)
        db.flush()
        ledger_note = f"到货 {receipt.receipt_no} {row['dept'].name} {supplier_label} 单价 {price}"
        for size_id, qty in row["sizes"]:
            size_row = ToolingReceiptSize(
                tenant_id=tenant_id,
                line_id=line.id,
                size_id=size_id,
                qty=qty,
            )
            db.add(size_row)
            db.flush()
            payable_rows.append((item, size_row, price))
            amount += _money(qty * price)
            _apply_delta(
                db,
                item,
                size_id,
                qty,
                department_id=row["dept"].id,
                source_type="receive",
                source_ref_id=receipt.id,
                notes=ledger_note,
                user_id=user_id,
            )
    amount = _money(amount)
    codes = "、".join(row["code"] for row in prepared)
    dept_names: list[str] = []
    for row in prepared:
        if row["dept"].name not in dept_names:
            dept_names.append(row["dept"].name)
    ap_notes = f"{_kind_label(kind)} {'、'.join(dept_names)} 到货 {codes}"
    ap = Payable(
        tenant_id=tenant_id,
        supplier_id=partner.id,
        supplier_name=supplier_label,
        purchase_order_id=None,
        payable_date=booked,
        due_date=booked,
        payment_term_days=0,
        amount=amount,
        adjustment=Decimal("0"),
        paid_amount=Decimal("0"),
        status=PayableStatus.open,
        notes=ap_notes[:255],
        delivery_note_no=note_no,
    )
    db.add(ap)
    db.flush()
    for sort_order, (item, size_row, price) in enumerate(payable_rows):
        size = size_map[size_row.size_id]
        db.add(
            PayableLine(
                tenant_id=tenant_id,
                payable_id=ap.id,
                source_type=SOURCE_RECEIVE,
                source_ref_id=size_row.id,
                source_document_no=receipt.receipt_no,
                item_code=item.code,
                item_name=_item_title(item),
                size_value=size.size_value,
                unit_name=_unit_name(item.kind),
                qty=_stored_qty(size_row.qty),
                unit_price=price,
                amount=_money(_stored_qty(size_row.qty) * price),
                sort_order=sort_order,
            )
        )
    _refresh_ap_status(ap)
    receipt.payable_id = ap.id
    db.commit()
    stocks = _dept_stock_map(db, {item.id for item in items})
    seen: set[tuple[int, int]] = set()
    out_items: list[dict] = []
    for item, row in zip(items, prepared):
        key = (item.id, row["dept"].id)
        if key in seen:
            continue
        seen.add(key)
        qty = stocks.get(item.id, {}).get(row["dept"].id, {})
        out_items.append(_item_out(item, qty, row["dept"].id, row["dept"].name))
    return {
        "items": out_items,
        "receipt_id": receipt.id,
        "receipt_no": receipt.receipt_no,
        "payable_id": ap.id,
        "amount": float(amount),
        "kind": kind,
        "kind_label": _kind_label(kind),
        "departments": [{"id": row["dept"].id, "name": row["dept"].name} for row in prepared],
    }


def _stated_size_row_ids(db: Session, size_row_ids: set[int]) -> set[int]:
    if not size_row_ids:
        return set()
    rows = db.scalars(
        select(PayableLine.source_ref_id).where(
            PayableLine.source_type == SOURCE_RECEIVE,
            PayableLine.source_ref_id.in_(size_row_ids),
            PayableLine.statement_id.is_not(None),
        )
    ).all()
    return {int(row) for row in rows if row is not None}


def _ensure_receipt_editable(db: Session, receipt: ToolingReceipt) -> None:
    size_row_ids = {sz.id for line in receipt.lines for sz in line.sizes}
    if _stated_size_row_ids(db, size_row_ids):
        raise ToolingError("statemented", "已对账，不能修改")
    if not receipt.payable_id:
        return
    ap = db.get(Payable, receipt.payable_id)
    if ap and ap.remainder_statement_id:
        raise ToolingError("statemented", "已对账，不能修改")
    if ap and (ap.paid_amount or 0) > 0:
        raise ToolingError("paid", "已有付款，不能修改")


def _replay_stock(db: Session, keys: set[tuple[int, int | None, int]]) -> None:
    for item_id, department_id, size_id in keys:
        dept_match = (
            ToolingLedger.department_id.is_(None)
            if department_id is None
            else ToolingLedger.department_id == department_id
        )
        rows = db.scalars(
            select(ToolingLedger)
            .where(
                ToolingLedger.tooling_item_id == item_id,
                ToolingLedger.size_id == size_id,
                dept_match,
            )
            .order_by(ToolingLedger.id)
        ).all()
        running = Decimal("0")
        for row in rows:
            running += _stored_qty(row.qty_delta)
            if running < 0:
                raise ToolingError("qty", "修改后库存不能为负")
            row.qty_after = running
        stock_match = (
            ToolingStock.department_id.is_(None)
            if department_id is None
            else ToolingStock.department_id == department_id
        )
        stock = db.scalar(
            select(ToolingStock).where(
                ToolingStock.tooling_item_id == item_id,
                ToolingStock.size_id == size_id,
                stock_match,
            )
        )
        if stock is None:
            if running == 0:
                continue
            item = db.get(ToolingItem, item_id)
            if item is None:
                continue
            db.add(
                ToolingStock(
                    tenant_id=item.tenant_id,
                    tooling_item_id=item_id,
                    department_id=department_id,
                    size_id=size_id,
                    qty=running,
                )
            )
        else:
            stock.qty = running


def _sync_last_price(db: Session, item: ToolingItem) -> None:
    line = db.scalars(
        select(ToolingReceiptLine)
        .join(ToolingReceipt, ToolingReceipt.id == ToolingReceiptLine.receipt_id)
        .where(ToolingReceiptLine.tooling_item_id == item.id)
        .order_by(ToolingReceipt.id.desc(), ToolingReceiptLine.id.desc())
    ).first()
    if line is not None:
        item.last_unit_price = line.unit_price


def _prepare_receipt_lines(
    db: Session,
    tenant_id: int,
    *,
    kind: str,
    lines: list[dict],
) -> tuple[list[dict], list[ToolingItem], dict[int, Size]]:
    if kind not in KINDS:
        raise ToolingError("kind", f"请选择{_kind_names()}")
    if not lines:
        raise ToolingError("lines", "请至少填写一个编号")
    if len(lines) > 40:
        raise ToolingError("lines", "一次最多登记40个编号")
    prepared: list[dict] = []
    seen_codes: set[str] = set()
    all_size_ids: set[int] = set()
    for raw in lines:
        code = str(raw.get("code") or "").strip()
        if not code:
            raise ToolingError("code", "请填写编号")
        if len(code) > 50:
            raise ToolingError("code", "编号不能超过50个字")
        if code in seen_codes:
            raise ToolingError("code", f"编号 {code} 在本单重复")
        seen_codes.add(code)
        dept = _use_department(db, tenant_id, raw.get("department_id"), kind=kind)
        price = _money(raw.get("unit_price"))
        if price <= 0:
            raise ToolingError("price", f"编号 {code} 请填写单价")
        try:
            qty_rows = _positive_sizes(list(raw.get("sizes") or []))
        except ToolingError as exc:
            if exc.code == "qty" and exc.message == "请填写到货数量":
                raise ToolingError("qty", f"编号 {code} 请填写到货数量") from exc
            if exc.code == "qty":
                raise ToolingError("qty", f"编号 {code} 的{exc.message}") from exc
            raise
        all_size_ids.update(size_id for size_id, _qty in qty_rows)
        prepared.append(
            {"kind": kind, "code": code, "price": price, "sizes": qty_rows, "dept": dept}
        )
    size_map = _load_sizes(db, tenant_id, all_size_ids)
    if len(size_map) != len(all_size_ids):
        raise ToolingError("size", "有尺码不存在")
    items: list[ToolingItem] = []
    for row in prepared:
        item = db.scalar(
            select(ToolingItem).where(
                ToolingItem.tenant_id == tenant_id, ToolingItem.code == row["code"]
            )
        )
        if item is None:
            item = ToolingItem(
                tenant_id=tenant_id,
                code=row["code"],
                name=None,
                kind=row["kind"],
                last_unit_price=row["price"],
                is_active=True,
            )
            db.add(item)
            db.flush()
        else:
            if item.kind != row["kind"]:
                raise ToolingError(
                    "kind",
                    f"编号 {row['code']} 已是{_kind_label(item.kind)}，不能改成{_kind_label(row['kind'])}",
                )
            item.is_active = True
        items.append(item)
    return prepared, items, size_map


def _supplier_or_error(db: Session, tenant_id: int, supplier_id: int) -> Partner:
    partner = db.get(Partner, supplier_id)
    if (
        not partner
        or partner.tenant_id != tenant_id
        or not partner.is_supplier
        or not partner.is_active
    ):
        raise ToolingError("supplier", "请选择供应商")
    return partner


def _receipt_result(
    db: Session,
    receipt: ToolingReceipt,
    ap: Payable,
    items: list[ToolingItem],
    prepared: list[dict],
    amount: Decimal,
    kind: str,
) -> dict:
    stocks = _dept_stock_map(db, {item.id for item in items})
    seen: set[tuple[int, int]] = set()
    out_items: list[dict] = []
    for item, row in zip(items, prepared):
        key = (item.id, row["dept"].id)
        if key in seen:
            continue
        seen.add(key)
        qty = stocks.get(item.id, {}).get(row["dept"].id, {})
        out_items.append(_item_out(item, qty, row["dept"].id, row["dept"].name))
    return {
        "items": out_items,
        "receipt_id": receipt.id,
        "receipt_no": receipt.receipt_no,
        "payable_id": ap.id,
        "amount": float(amount),
        "kind": kind,
        "kind_label": _kind_label(kind),
        "departments": [{"id": row["dept"].id, "name": row["dept"].name} for row in prepared],
    }


def _write_receipt_lines(
    db: Session,
    receipt: ToolingReceipt,
    ap: Payable,
    *,
    kind: str,
    partner: Partner,
    prepared: list[dict],
    items: list[ToolingItem],
    size_map: dict[int, Size],
    user_id: int | None,
) -> Decimal:
    supplier_label = _supplier_name(partner)
    payable_rows: list[tuple[ToolingItem, ToolingReceiptSize, Decimal]] = []
    amount = Decimal("0")
    for item, row in zip(items, prepared):
        price = row["price"]
        line = ToolingReceiptLine(
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            department_id=row["dept"].id,
            tooling_item_id=item.id,
            unit_price=price,
        )
        db.add(line)
        db.flush()
        ledger_note = f"到货 {receipt.receipt_no} {row['dept'].name} {supplier_label} 单价 {price}"
        for size_id, qty in row["sizes"]:
            size_row = ToolingReceiptSize(
                tenant_id=receipt.tenant_id,
                line_id=line.id,
                size_id=size_id,
                qty=qty,
            )
            db.add(size_row)
            db.flush()
            payable_rows.append((item, size_row, price))
            amount += _money(qty * price)
            _apply_delta(
                db,
                item,
                size_id,
                qty,
                department_id=row["dept"].id,
                source_type="receive",
                source_ref_id=receipt.id,
                notes=ledger_note,
                user_id=user_id,
            )
    amount = _money(amount)
    codes = "、".join(row["code"] for row in prepared)
    dept_names: list[str] = []
    for row in prepared:
        if row["dept"].name not in dept_names:
            dept_names.append(row["dept"].name)
    ap.supplier_id = partner.id
    ap.supplier_name = supplier_label
    ap.payable_date = receipt.receipt_date
    ap.due_date = receipt.receipt_date
    ap.amount = amount
    ap.notes = f"{_kind_label(kind)} {'、'.join(dept_names)} 到货 {codes}"[:255]
    ap.delivery_note_no = receipt.delivery_note_no
    for sort_order, (item, size_row, price) in enumerate(payable_rows):
        size = size_map[size_row.size_id]
        db.add(
            PayableLine(
                tenant_id=receipt.tenant_id,
                payable_id=ap.id,
                source_type=SOURCE_RECEIVE,
                source_ref_id=size_row.id,
                source_document_no=receipt.receipt_no,
                item_code=item.code,
                item_name=_item_title(item),
                size_value=size.size_value,
                unit_name=_unit_name(item.kind),
                qty=_stored_qty(size_row.qty),
                unit_price=price,
                amount=_money(_stored_qty(size_row.qty) * price),
                sort_order=sort_order,
            )
        )
    _refresh_ap_status(ap)
    return amount


def get_receipt(db: Session, tenant_id: int, receipt_id: int) -> dict:
    receipt = db.scalar(
        select(ToolingReceipt)
        .where(ToolingReceipt.id == receipt_id, ToolingReceipt.tenant_id == tenant_id)
        .options(selectinload(ToolingReceipt.lines).selectinload(ToolingReceiptLine.sizes))
    )
    if receipt is None:
        raise ToolingError("not_found", "到货单不存在")
    item_ids = {line.tooling_item_id for line in receipt.lines}
    items = {}
    if item_ids:
        items = {
            row.id: row
            for row in db.scalars(select(ToolingItem).where(ToolingItem.id.in_(item_ids))).all()
        }
    kind = next(
        (
            items[line.tooling_item_id].kind
            for line in receipt.lines
            if line.tooling_item_id in items
        ),
        KIND_SHOE,
    )
    size_row_ids = {sz.id for line in receipt.lines for sz in line.sizes}
    lines_out = []
    for line in sorted(receipt.lines, key=lambda row: row.id):
        item = items.get(line.tooling_item_id)
        lines_out.append(
            {
                "id": line.id,
                "department_id": line.department_id,
                "code": item.code if item else "",
                "unit_price": float(_money(line.unit_price)),
                "sizes": [
                    {"size_id": sz.size_id, "qty": _qty_out(sz.qty)}
                    for sz in sorted(line.sizes, key=lambda row: row.id)
                ],
            }
        )
    return {
        "id": receipt.id,
        "receipt_no": receipt.receipt_no,
        "kind": kind,
        "kind_label": _kind_label(kind),
        "supplier_id": receipt.supplier_id,
        "supplier_name": receipt.supplier_name,
        "receipt_date": receipt.receipt_date,
        "delivery_note_no": receipt.delivery_note_no,
        "notes": receipt.notes,
        "statemented": bool(_stated_size_row_ids(db, size_row_ids)),
        "lines": lines_out,
    }


def update_receipt(
    db: Session,
    tenant_id: int,
    receipt_id: int,
    *,
    kind: str,
    supplier_id: int,
    receipt_date: date | None,
    delivery_note_no: str | None,
    notes: str | None,
    lines: list[dict],
    user_id: int | None,
) -> dict:
    receipt = db.scalar(
        select(ToolingReceipt)
        .where(ToolingReceipt.id == receipt_id, ToolingReceipt.tenant_id == tenant_id)
        .options(selectinload(ToolingReceipt.lines).selectinload(ToolingReceiptLine.sizes))
    )
    if receipt is None:
        raise ToolingError("not_found", "到货单不存在")
    _ensure_receipt_editable(db, receipt)
    partner = _supplier_or_error(db, tenant_id, supplier_id)
    prepared, items, size_map = _prepare_receipt_lines(db, tenant_id, kind=kind, lines=lines)
    booked = receipt_date or receipt.receipt_date
    old_keys = {
        (line.tooling_item_id, line.department_id, sz.size_id)
        for line in receipt.lines
        for sz in line.sizes
    }
    old_item_ids = {line.tooling_item_id for line in receipt.lines}
    ledgers = db.scalars(
        select(ToolingLedger).where(
            ToolingLedger.tenant_id == tenant_id,
            ToolingLedger.source_type == "receive",
            ToolingLedger.source_ref_id == receipt.id,
        )
    ).all()
    for row in ledgers:
        db.delete(row)
    if receipt.payable_id:
        payable_lines = db.scalars(
            select(PayableLine).where(
                PayableLine.payable_id == receipt.payable_id,
                PayableLine.source_type == SOURCE_RECEIVE,
            )
        ).all()
        for row in payable_lines:
            db.delete(row)
    for line in list(receipt.lines):
        for sz in list(line.sizes):
            db.delete(sz)
        db.delete(line)
    db.flush()
    _replay_stock(db, old_keys)

    receipt.supplier_id = partner.id
    receipt.supplier_name = _supplier_name(partner)
    receipt.receipt_date = booked
    receipt.delivery_note_no = (delivery_note_no or "").strip() or None
    receipt.notes = (notes or "").strip() or None
    ap = db.get(Payable, receipt.payable_id) if receipt.payable_id else None
    if ap is None:
        ap = Payable(
            tenant_id=tenant_id,
            supplier_id=partner.id,
            supplier_name=_supplier_name(partner),
            purchase_order_id=None,
            payable_date=booked,
            due_date=booked,
            payment_term_days=0,
            amount=Decimal("0"),
            adjustment=Decimal("0"),
            paid_amount=Decimal("0"),
            status=PayableStatus.open,
            delivery_note_no=receipt.delivery_note_no,
        )
        db.add(ap)
        db.flush()
        receipt.payable_id = ap.id
    amount = _write_receipt_lines(
        db,
        receipt,
        ap,
        kind=kind,
        partner=partner,
        prepared=prepared,
        items=items,
        size_map=size_map,
        user_id=user_id,
    )
    for item_id in old_item_ids | {item.id for item in items}:
        item = db.get(ToolingItem, item_id)
        if item is not None:
            _sync_last_price(db, item)
    db.commit()
    return _receipt_result(db, receipt, ap, items, prepared, amount, kind)


def adjust(
    db: Session,
    tenant_id: int,
    item_id: int,
    *,
    department_id: int | None,
    target_department_id: int | None,
    sizes: list[tuple[int, Decimal]],
    notes: str | None,
    user_id: int | None,
) -> dict:
    item = _get_item(db, tenant_id, item_id)
    if not sizes:
        raise ToolingError("qty", "请填写调整后的数量")
    stocks = _dept_stock_map(db, {item.id}).get(item.id, {})
    if department_id is None and target_department_id is None:
        known = [dept_id for dept_id in stocks if dept_id is not None]
        if len(known) == 1:
            department_id = known[0]
        elif len(known) > 1:
            raise ToolingError("department", "请指定使用部门")
    source_name = None
    if department_id is not None:
        source = db.get(Department, department_id)
        if not source or source.tenant_id != tenant_id:
            raise ToolingError("department", "请选择使用部门")
        source_name = source.name
    moving = target_department_id is not None and target_department_id != department_id
    target_name = source_name
    if moving:
        target = _use_department(db, tenant_id, target_department_id, kind=item.kind)
        target_name = target.name
    elif department_id is not None:
        target_department_id = department_id
    wanted: dict[int, Decimal] = {}
    for size_id, qty in sizes:
        wanted[int(size_id)] = _as_qty(qty)
    size_map = _load_sizes(db, tenant_id, set(wanted))
    if len(size_map) != len(wanted):
        raise ToolingError("size", "有尺码不存在")
    current = stocks.get(department_id, {})
    remark = (notes or "").strip() or "库存调整"
    changed = False
    if moving:
        origin = source_name or "未分部门"
        for size_id, qty in wanted.items():
            held = _stored_qty(current.get(size_id, 0))
            if held:
                changed = True
                _apply_delta(
                    db,
                    item,
                    size_id,
                    -held,
                    department_id=department_id,
                    source_type="adjust",
                    source_ref_id=None,
                    notes=f"改到{target_name} {remark}",
                    user_id=user_id,
                )
            if qty:
                changed = True
                _apply_delta(
                    db,
                    item,
                    size_id,
                    qty,
                    department_id=target_department_id,
                    source_type="adjust",
                    source_ref_id=None,
                    notes=f"从{origin}调整 {remark}",
                    user_id=user_id,
                )
        department_id = target_department_id
    else:
        for size_id, qty in wanted.items():
            delta = qty - _stored_qty(current.get(size_id, 0))
            if delta == 0:
                continue
            changed = True
            _apply_delta(
                db,
                item,
                size_id,
                delta,
                department_id=department_id,
                source_type="adjust",
                source_ref_id=None,
                notes=remark,
                user_id=user_id,
            )
    if not changed:
        raise ToolingError("qty", "数量没有变化")
    db.commit()
    db.refresh(item)
    qty = _dept_stock_map(db, {item.id}).get(item.id, {}).get(department_id, {})
    return _item_out(item, qty, department_id, target_name)


def _as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _purchase_receive_refs(db: Session, tenant_id: int, po_ids: set[int]) -> list[dict]:
    if not po_ids:
        return []
    rows = db.execute(
        select(
            Payable.purchase_order_id,
            Payable.delivery_note_no,
            Payable.created_at,
            PayableLine.item_code,
            PayableLine.size_value,
            PayableLine.qty,
        )
        .join(PayableLine, PayableLine.payable_id == Payable.id)
        .where(
            Payable.tenant_id == tenant_id,
            Payable.purchase_order_id.in_(po_ids),
            PayableLine.source_type == "purchase_receive",
        )
    ).all()
    return [
        {
            "po_id": po_id,
            "delivery_note_no": note,
            "created_at": _as_datetime(created),
            "item_code": code,
            "size_value": size_value,
            "qty": qty,
        }
        for po_id, note, created, code, size_value, qty in rows
    ]


def _match_purchase_delivery(
    row: ToolingLedger,
    item: ToolingItem,
    size_value: str | None,
    refs: list[dict],
) -> str | None:
    same_po = [ref for ref in refs if ref["po_id"] == row.source_ref_id]
    qty = _stored_qty(row.qty_delta)
    matched = [
        ref
        for ref in same_po
        if ref["item_code"] == item.code
        and ref["size_value"] == size_value
        and _stored_qty(ref["qty"]) == qty
    ]
    pool = matched or same_po
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]["delivery_note_no"]
    ledger_at = _as_datetime(row.created_at)

    def distance(ref: dict) -> float:
        created = ref["created_at"]
        if ledger_at is None or created is None:
            return float("inf")
        return abs((created - ledger_at).total_seconds())

    return min(pool, key=distance)["delivery_note_no"]


def list_ledgers(
    db: Session,
    tenant_id: int,
    item_id: int,
    *,
    department_id: int | None = None,
) -> list[dict]:
    item = _get_item(db, tenant_id, item_id)
    query = select(ToolingLedger).where(
        ToolingLedger.tenant_id == tenant_id,
        ToolingLedger.tooling_item_id == item.id,
    )
    if department_id is not None:
        query = query.where(ToolingLedger.department_id == department_id)
    rows = db.scalars(query.order_by(ToolingLedger.id.desc())).all()
    size_map = _load_sizes(db, tenant_id, {row.size_id for row in rows})
    dept_ids = {row.department_id for row in rows if row.department_id}
    departments = {}
    if dept_ids:
        departments = {
            dept.id: dept.name
            for dept in db.scalars(select(Department).where(Department.id.in_(dept_ids))).all()
        }
    receipt_ids = {row.source_ref_id for row in rows if row.source_type == "receive" and row.source_ref_id}
    receipts = {}
    if receipt_ids:
        receipts = {
            receipt.id: receipt.delivery_note_no
            for receipt in db.scalars(
                select(ToolingReceipt).where(
                    ToolingReceipt.tenant_id == tenant_id,
                    ToolingReceipt.id.in_(receipt_ids),
                )
            ).all()
        }
    po_ids = {
        row.source_ref_id for row in rows if row.source_type == "purchase_receive" and row.source_ref_id
    }
    orders = {}
    purchase_refs: list[dict] = []
    if po_ids:
        orders = {
            order.id: order.po_no
            for order in db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.id.in_(po_ids),
                )
            ).all()
        }
        purchase_refs = _purchase_receive_refs(db, tenant_id, po_ids)
    out = []
    for row in rows:
        size_value = size_map[row.size_id].size_value if row.size_id in size_map else None
        po_no = None
        delivery_note_no = None
        if row.source_type == "receive":
            delivery_note_no = receipts.get(row.source_ref_id)
        elif row.source_type == "purchase_receive":
            po_no = orders.get(row.source_ref_id)
            delivery_note_no = _match_purchase_delivery(row, item, size_value, purchase_refs)
        out.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "size_id": row.size_id,
                "size_value": size_value,
                "qty_delta": _qty_out(row.qty_delta),
                "qty_after": _qty_out(row.qty_after),
                "department_id": row.department_id,
                "department_name": departments.get(row.department_id),
                "source_type": row.source_type,
                "source_label": LEDGER_SOURCE_LABELS.get(row.source_type, row.source_type),
                "po_no": po_no,
                "delivery_note_no": delivery_note_no,
            }
        )
    return out


def _purchase_receipt_rows(
    db: Session,
    tenant_id: int,
    *,
    tooling_item_id: int | None,
) -> list[dict]:
    """采购到货入模具仓：库存已入账，入库单在采购应付上，这里按应付行补出来。"""
    item_query = select(ToolingItem).where(ToolingItem.tenant_id == tenant_id)
    if tooling_item_id:
        item_query = item_query.where(ToolingItem.id == tooling_item_id)
    items = {
        row.code: row
        for row in db.scalars(item_query).all()
        if row.code
    }
    items_by_id = {row.id: row for row in items.values()}
    if not items:
        return []
    lines = list(
        db.scalars(
            select(PayableLine)
            .join(Payable, Payable.id == PayableLine.payable_id)
            .where(
                PayableLine.tenant_id == tenant_id,
                PayableLine.source_type == "purchase_receive",
                PayableLine.item_code.in_(list(items)),
                Payable.purchase_order_id.is_not(None),
            )
            .options(selectinload(PayableLine.payable))
        ).unique().all()
    )
    if not lines:
        return []
    po_ids = {line.payable.purchase_order_id for line in lines if line.payable and line.payable.purchase_order_id}
    item_ids = {items[line.item_code].id for line in lines if line.item_code in items}
    ledgers = []
    if po_ids and item_ids:
        ledgers = list(
            db.scalars(
                select(ToolingLedger).where(
                    ToolingLedger.tenant_id == tenant_id,
                    ToolingLedger.source_type == "purchase_receive",
                    ToolingLedger.source_ref_id.in_(po_ids),
                    ToolingLedger.tooling_item_id.in_(item_ids),
                )
            ).all()
        )
    arrived = {(row.source_ref_id, row.tooling_item_id) for row in ledgers}
    dept_by_key: dict[tuple[int, int], int | None] = {}
    for row in ledgers:
        dept_by_key.setdefault((row.source_ref_id, row.tooling_item_id), row.department_id)
    dept_ids = {dept_id for dept_id in dept_by_key.values() if dept_id}
    departments = {}
    if dept_ids:
        departments = {
            row.id: row.name
            for row in db.scalars(select(Department).where(Department.id.in_(dept_ids))).all()
        }
    orders = {}
    if po_ids:
        orders = {
            row.id: row.po_no
            for row in db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.id.in_(po_ids),
                )
            ).all()
        }
    size_by_value: dict[str, Size] = {}
    for size in db.scalars(select(Size).where(Size.tenant_id == tenant_id)).all():
        size_by_value.setdefault(size.size_value, size)
    grouped: dict[tuple[int, int, Decimal], list[PayableLine]] = {}
    for line in lines:
        item = items.get(line.item_code or "")
        payable = line.payable
        if not item or not payable or not payable.purchase_order_id:
            continue
        if (payable.purchase_order_id, item.id) not in arrived:
            continue
        key = (payable.id, item.id, _money(line.unit_price))
        grouped.setdefault(key, []).append(line)
    out = []
    for (payable_id, item_id, price), group in grouped.items():
        payable = group[0].payable
        item = items_by_id[item_id]
        dept_id = dept_by_key.get((payable.purchase_order_id, item_id))
        size_qty: dict[int, Decimal] = {}
        size_value_by_id: dict[int, str] = {}
        total = Decimal("0")
        for line in group:
            qty = _stored_qty(line.qty)
            total += qty
            size = size_by_value.get(line.size_value or "")
            if size is None:
                continue
            size_qty[size.id] = size_qty.get(size.id, Decimal("0")) + qty
            size_value_by_id[size.id] = size.size_value
        size_rows = [
            {"size_id": size_id, "size_value": size_value_by_id[size_id], "qty": _qty_out(qty)}
            for size_id, qty in size_qty.items()
        ]
        size_rows.sort(
            key=lambda row: (
                size_by_value[row["size_value"]].sort_order
                if row["size_value"] in size_by_value
                else row["size_id"]
            )
        )
        out.append(
            {
                "id": -min(line.id for line in group),
                "receipt_id": -payable_id,
                "receipt_no": orders.get(payable.purchase_order_id) or group[0].source_document_no,
                "receipt_date": payable.payable_date,
                "created_at": payable.created_at,
                "department_id": dept_id,
                "department_name": departments.get(dept_id) if dept_id else None,
                "tooling_item_id": item.id,
                "code": item.code,
                "name": item.name,
                "kind": item.kind,
                "kind_label": _kind_label(item.kind),
                "supplier_id": payable.supplier_id,
                "supplier_name": payable.supplier_name,
                "unit_price": float(price),
                "delivery_note_no": payable.delivery_note_no,
                "po_no": orders.get(payable.purchase_order_id) or group[0].source_document_no,
                "notes": None,
                "total_qty": _qty_out(total),
                "amount": float(_money(total * price)),
                "sizes": size_rows,
                "payable_id": payable.id,
                "statemented": any(line.statement_id for line in group),
                "from_purchase": True,
            }
        )
    return out


def list_receipts(
    db: Session,
    tenant_id: int,
    *,
    tooling_item_id: int | None = None,
) -> list[dict]:
    query = (
        select(ToolingReceipt)
        .where(ToolingReceipt.tenant_id == tenant_id)
        .options(selectinload(ToolingReceipt.lines).selectinload(ToolingReceiptLine.sizes))
        .order_by(ToolingReceipt.id.desc())
    )
    if tooling_item_id:
        _get_item(db, tenant_id, tooling_item_id)
        query = query.where(
            ToolingReceipt.id.in_(
                select(ToolingReceiptLine.receipt_id).where(
                    ToolingReceiptLine.tooling_item_id == tooling_item_id
                )
            )
        )
    receipts = list(db.scalars(query).all())
    item_ids = {line.tooling_item_id for row in receipts for line in row.lines}
    items = {}
    if item_ids:
        items = {
            row.id: row
            for row in db.scalars(select(ToolingItem).where(ToolingItem.id.in_(item_ids))).all()
        }
    dept_ids = {line.department_id for row in receipts for line in row.lines if line.department_id}
    departments = {}
    if dept_ids:
        departments = {
            row.id: row
            for row in db.scalars(select(Department).where(Department.id.in_(dept_ids))).all()
        }
    size_ids = {sz.size_id for row in receipts for line in row.lines for sz in line.sizes}
    size_map = _load_sizes(db, tenant_id, size_ids)
    size_row_ids = {sz.id for row in receipts for line in row.lines for sz in line.sizes}
    stated = _stated_size_row_ids(db, size_row_ids)
    receipt_stated = {
        row.id: any(sz.id in stated for line in row.lines for sz in line.sizes) for row in receipts
    }
    out = []
    for row in receipts:
        for line in row.lines:
            if tooling_item_id and line.tooling_item_id != tooling_item_id:
                continue
            dept = departments.get(line.department_id)
            item = items.get(line.tooling_item_id)
            size_rows = []
            total = Decimal("0")
            for sz in sorted(
                line.sizes,
                key=lambda x: size_map[x.size_id].sort_order if x.size_id in size_map else x.size_id,
            ):
                value = size_map[sz.size_id].size_value if sz.size_id in size_map else str(sz.size_id)
                size_rows.append({"size_id": sz.size_id, "size_value": value, "qty": _qty_out(sz.qty)})
                total += _stored_qty(sz.qty)
            price = _money(line.unit_price)
            out.append(
                {
                    "id": line.id,
                    "receipt_id": row.id,
                    "receipt_no": row.receipt_no,
                    "receipt_date": row.receipt_date,
                    "created_at": row.created_at,
                    "department_id": line.department_id,
                    "department_name": dept.name if dept else None,
                    "tooling_item_id": line.tooling_item_id,
                    "code": item.code if item else None,
                    "name": item.name if item else None,
                    "kind": item.kind if item else None,
                    "kind_label": _kind_label(item.kind) if item else None,
                    "supplier_id": row.supplier_id,
                    "supplier_name": row.supplier_name,
                    "unit_price": float(price),
                    "delivery_note_no": row.delivery_note_no,
                    "po_no": None,
                    "notes": row.notes,
                    "total_qty": _qty_out(total),
                    "amount": float(_money(total * price)),
                    "sizes": size_rows,
                    "payable_id": row.payable_id,
                    "statemented": receipt_stated.get(row.id, False),
                    "from_purchase": False,
                }
            )
    out.extend(
        _purchase_receipt_rows(db, tenant_id, tooling_item_id=tooling_item_id)
    )
    out.sort(
        key=lambda row: (
            row.get("receipt_date") or date.min,
            row.get("created_at") or datetime.min,
            abs(row.get("id") or 0),
        ),
        reverse=True,
    )
    return out
