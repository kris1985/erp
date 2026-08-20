from __future__ import annotations

from datetime import date, datetime

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    OwnProductQuote,
    Partner,
    SalesBizMode,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
)
from app.schemas.api import OrderCreate, OrderItemIn, SalesOrderCreate, SalesOrderLineIn, SalesOrderUpdate
from app.services.order_service import OrderError, _resolve_customer, create_order, generate_order_no


class SalesOrderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def generate_sales_order_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = f"SO{today}"
    existing = db.scalars(
        select(SalesOrder).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.order_no.like(f"{prefix}%"),
        )
    ).all()
    seq = len(existing) + 1
    return f"{prefix}{seq:02d}"


def _resolve_brand(db: Session, tenant_id: int, brand_id: int | None, brand_name: str | None) -> tuple[int | None, str | None]:
    if brand_id:
        p = db.get(Partner, brand_id)
        if not p or p.tenant_id != tenant_id or not p.is_active:
            raise SalesOrderError("brand_not_found", "品牌不存在或未启用")
        name = (brand_name or "").strip() or p.short_name or p.name
        return p.id, name
    name = (brand_name or "").strip() or None
    return None, name


def _resolve_biz_mode(value: str | None) -> SalesBizMode:
    """B1d：业务形态校验；空回默认自产自销。"""
    if value in (None, ""):
        return SalesBizMode.self_produce
    if value not in {m.value for m in SalesBizMode}:
        raise SalesOrderError("invalid_biz_mode", f"业务形态无效: {value}")
    return SalesBizMode(value)


def _line_total_qty(items: list) -> int:
    return sum(int(i.qty) for i in items if int(i.qty) > 0)


def _ensure_line_color(
    db: Session, tenant_id: int, own_product_id: int, color_id: int | None
) -> None:
    if not color_id:
        raise SalesOrderError("missing_color", "请选择颜色")
    color = db.get(Color, color_id)
    if not color or color.tenant_id != tenant_id:
        raise SalesOrderError("invalid_color", "颜色不存在")
    product = db.scalar(
        select(OwnProduct)
        .where(OwnProduct.id == own_product_id, OwnProduct.tenant_id == tenant_id)
        .options(selectinload(OwnProduct.colors))
    )
    if not product:
        raise SalesOrderError("invalid_product", "产品不存在")
    allowed = {c.color_id for c in (product.colors or [])}
    if allowed and color_id not in allowed:
        raise SalesOrderError("invalid_color", "颜色与产品不匹配")


def _resolve_line_unit_price(
    db: Session,
    tenant_id: int,
    own_product_id: int,
    customer_id: int | None,
    unit_price: Decimal | None,
) -> Decimal | None:
    if unit_price is not None:
        return Decimal(unit_price).quantize(Decimal("0.01"))
    product = db.get(OwnProduct, own_product_id)
    if not product:
        return None
    if customer_id:
        q = db.scalar(
            select(OwnProductQuote).where(
                OwnProductQuote.tenant_id == tenant_id,
                OwnProductQuote.own_product_id == own_product_id,
                OwnProductQuote.partner_id == customer_id,
            )
        )
        if q and q.quote_price is not None:
            return Decimal(q.quote_price).quantize(Decimal("0.01"))
    if product.quote_price is not None:
        return Decimal(product.quote_price).quantize(Decimal("0.01"))
    return None


def _line_sum_item_field(line: SalesOrderLine, field: str) -> int:
    return sum(int(getattr(it, field, 0) or 0) for it in (line.items or []))


def _line_wip_qty(db: Session, tenant_id: int, line: SalesOrderLine) -> int:
    """在制预估：分配表 produced_qty_est 合计 − 已产（不低于 0）。"""
    from app.models import ExecutionAllocation

    item_ids = [int(it.id) for it in (line.items or []) if it.id]
    if not item_ids:
        return 0
    est = db.scalar(
        select(func.coalesce(func.sum(ExecutionAllocation.produced_qty_est), 0)).where(
            ExecutionAllocation.tenant_id == tenant_id,
            ExecutionAllocation.sales_order_line_item_id.in_(item_ids),
        )
    )
    produced = _line_sum_item_field(line, "produced_qty")
    return max(0, int(est or 0) - produced)


def _serialize_line(
    db: Session,
    tenant_id: int,
    line: SalesOrderLine,
    include_process_progress: bool = False,
) -> dict:
    product = db.get(OwnProduct, line.own_product_id)
    prod_order = db.get(Order, line.production_order_id) if line.production_order_id else None
    line_color = db.get(Color, line.color_id) if line.color_id else None
    items_out = []
    for item in line.items:
        size = db.get(Size, item.size_id)
        items_out.append(
            {
                "id": item.id,
                "color_id": line.color_id,
                "color_name": line_color.name if line_color else None,
                "size_id": item.size_id,
                "size_value": size.size_value if size else None,
                "qty": item.qty,
                "allocated_qty": int(getattr(item, "allocated_qty", 0) or 0),
                "produced_qty": int(getattr(item, "produced_qty", 0) or 0),
                "shipped_qty": int(getattr(item, "shipped_qty", 0) or 0),
                "labor_cost": getattr(item, "labor_cost", None) or 0,
            }
        )
    so = line.sales_order
    so_st = (
        so.status.value
        if so is not None and hasattr(so.status, "value")
        else (str(so.status) if so is not None else "draft")
    )
    shipped_fully, shipped_partial = _line_ship_flags(line)
    allocated_qty = _line_allocated_qty(line)
    produced_qty = _line_sum_item_field(line, "produced_qty")
    shipped_qty = _line_sum_item_field(line, "shipped_qty")
    wip_qty = _line_wip_qty(db, tenant_id, line)
    qty = _line_sum_item_field(line, "qty")
    header = (
        db.get(ExecutionHeader, line.execution_header_id)
        if getattr(line, "execution_header_id", None)
        else None
    )
    execution_status = _enum_val(header.status) if header else None
    display = line_display_status(
        order_status=so_st,
        line_status=line.status.value if hasattr(line.status, "value") else str(line.status),
        production_order_id=line.production_order_id,
        production_order_status=(
            prod_order.status.value if prod_order and hasattr(prod_order.status, "value") else None
        ),
        shipped_fully=shipped_fully,
        shipped_partial=shipped_partial,
        execution_header_id=getattr(line, "execution_header_id", None),
        allocated_qty=allocated_qty,
        execution_status=execution_status,
        qty=qty,
        produced_qty=produced_qty,
        shipped_qty=shipped_qty,
        wip_qty=wip_qty,
    )
    return {
        "id": line.id,
        "own_product_id": line.own_product_id,
        "product_code": product.product_code if product else None,
        "product_image_url": product.image_url if product else None,
        "color_id": line.color_id,
        "color_name": line_color.name if line_color else None,
        "fabric": line.fabric,
        "lining": line.lining,
        "customer_sku": line.customer_sku,
        "brand_id": line.brand_id,
        "brand_name": line.brand_name,
        "delivery_date": line.delivery_date,
        "unit_price": line.unit_price,
        "notes": line.notes,
        "total_qty": line.total_qty,
        "allocated_qty": allocated_qty,
        "produced_qty": produced_qty,
        "shipped_qty": shipped_qty,
        "wip_qty": wip_qty,
        "sort_order": line.sort_order if line.sort_order is not None else 0,
        "line_no": (line.sort_order if line.sort_order is not None else 0) + 1,
        "color_summary": line_color.name if line_color else "—",
        "status": line.status.value if hasattr(line.status, "value") else str(line.status),
        "display_status": display,
        "production_order_id": line.production_order_id,
        "production_order_no": prod_order.order_no if prod_order else None,
        "production_order_status": (
            prod_order.status.value if prod_order and hasattr(prod_order.status, "value") else None
        ),
        "execution_header_id": getattr(line, "execution_header_id", None),
        "execution_status": execution_status,
        "items": items_out,
        "process_progress": _line_process_progress(db, tenant_id, line)
        if include_process_progress
        else [],
    }


def _line_process_progress(
    db: Session,
    tenant_id: int,
    line: SalesOrderLine,
) -> list[dict]:
    """行工序进度：按执行单头（K4-B）或生产单查 OrderProcess。"""
    process_filters = [OrderProcess.tenant_id == tenant_id]
    header_id = getattr(line, "execution_header_id", None)
    if header_id:
        process_filters.append(OrderProcess.header_id == header_id)
    elif line.production_order_id:
        process_filters.append(OrderProcess.order_id == line.production_order_id)
    else:
        return []
    processes = db.scalars(
        select(OrderProcess).where(*process_filters).order_by(OrderProcess.id)
    ).all()
    return [
        {
            "process_id": proc.process_id,
            "process_name": proc.process_name,
            "plan_qty": int(proc.plan_qty or 0),
            "completed_qty": int(proc.completed_qty or 0),
            "status": _enum_val(proc.status),
        }
        for proc in processes
    ]


def serialize_sales_order(
    db: Session,
    tenant_id: int,
    so: SalesOrder,
    *,
    include_process_progress: bool = False,
) -> dict:
    lines_out = [
        _serialize_line(
            db,
            tenant_id,
            ln,
            include_process_progress=include_process_progress,
        )
        for ln in so.lines
    ]
    prod_status_by_id: dict[int, str | None] = {}
    exe_status_by_header_id: dict[int, str] = {}
    for ln, row in zip(so.lines or [], lines_out):
        if ln.production_order_id and row.get("production_order_status"):
            prod_status_by_id[ln.production_order_id] = row["production_order_status"]
        hid = getattr(ln, "execution_header_id", None)
        if hid and row.get("execution_status"):
            exe_status_by_header_id[int(hid)] = str(row["execution_status"])
    return {
        "id": so.id,
        "order_no": so.order_no,
        "customer_id": so.customer_id,
        "customer_name": so.customer_name,
        "ordered_at": so.ordered_at,
        "biz_mode": (
            so.biz_mode.value if hasattr(so.biz_mode, "value") else str(so.biz_mode or "")
        ) or SalesBizMode.self_produce.value,
        "status": so.status.value if hasattr(so.status, "value") else str(so.status),
        "display_status": order_display_status(
            so, prod_status_by_id, exe_status_by_header_id=exe_status_by_header_id
        ),
        "notes": so.notes,
        "brand_logo_url": getattr(so, "brand_logo_url", None),
        "notes_image_url": getattr(so, "notes_image_url", None),
        "created_at": so.created_at,
        "lines": lines_out,
    }


def get_sales_order(db: Session, tenant_id: int, sales_order_id: int) -> SalesOrder:
    so = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == sales_order_id, SalesOrder.tenant_id == tenant_id)
        .options(
            selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items),
        )
    )
    if not so:
        raise SalesOrderError("not_found", "销售订单不存在")
    return so


def _line_fields_from_in(
    db: Session,
    tenant_id: int,
    so: SalesOrder,
    row: SalesOrderLineIn,
) -> tuple[dict, list]:
    if not row.items:
        raise SalesOrderError("empty_items", "产品行码数不能为空")
    positive_items = [i for i in row.items if int(i.qty) > 0]
    if not positive_items:
        raise SalesOrderError("empty_items", "请至少填写一个码数数量")
    _ensure_line_color(db, tenant_id, row.own_product_id, row.color_id)
    brand_id, brand_name = _resolve_brand(db, tenant_id, row.brand_id, row.brand_name)
    total_qty = _line_total_qty(positive_items)
    unit_price = _resolve_line_unit_price(
        db, tenant_id, row.own_product_id, so.customer_id, row.unit_price
    )
    product = db.get(OwnProduct, row.own_product_id)
    fabric = (row.fabric or "").strip() or None
    lining = (row.lining or "").strip() or None
    if fabric is None and product is not None:
        fabric = (getattr(product, "fabric", None) or "").strip() or None
    if lining is None and product is not None:
        lining = (getattr(product, "lining", None) or "").strip() or None
    fields = dict(
        own_product_id=row.own_product_id,
        color_id=row.color_id,
        fabric=fabric,
        lining=lining,
        customer_sku=(row.customer_sku or "").strip() or None,
        brand_id=brand_id,
        brand_name=brand_name,
        delivery_date=row.delivery_date,
        unit_price=unit_price,
        notes=(row.notes or "").strip() or None,
        total_qty=total_qty,
    )
    return fields, positive_items


def _replace_line_items(
    db: Session,
    tenant_id: int,
    line: SalesOrderLine,
    positive_items: list,
) -> None:
    line.items.clear()
    db.flush()
    for item in positive_items:
        db.add(
            SalesOrderLineItem(
                tenant_id=tenant_id,
                sales_order_line_id=line.id,
                color_id=line.color_id,
                size_id=item.size_id,
                qty=item.qty,
            )
        )


def _apply_lines(
    db: Session,
    tenant_id: int,
    so: SalesOrder,
    lines: list[SalesOrderLineIn],
) -> None:
    if not lines:
        raise SalesOrderError("empty_lines", "请至少添加一个产品行")
    so.lines.clear()
    db.flush()
    for idx, row in enumerate(lines):
        fields, positive_items = _line_fields_from_in(db, tenant_id, so, row)
        line = SalesOrderLine(
            tenant_id=tenant_id,
            sales_order_id=so.id,
            status=SalesOrderLineStatus.pending,
            sort_order=idx,
            **fields,
        )
        db.add(line)
        db.flush()
        _replace_line_items(db, tenant_id, line, positive_items)


def create_sales_order(
    db: Session,
    tenant_id: int,
    payload: SalesOrderCreate,
    *,
    created_by: int | None,
) -> SalesOrder:
    try:
        cust_id, cust_name = _resolve_customer(
            db,
            tenant_id,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
        )
    except OrderError as e:
        raise SalesOrderError(e.code, e.message) from e
    order_no = (payload.order_no or "").strip() or generate_sales_order_no(db, tenant_id)
    exists = db.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.order_no == order_no)
    )
    if exists:
        raise SalesOrderError("duplicate_order_no", f"销售订单号已存在: {order_no}")

    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_id=cust_id,
        customer_name=cust_name,
        ordered_at=payload.ordered_at or date.today(),
        status=SalesOrderStatus.draft,
        notes=(payload.notes or "").strip() or None,
        brand_logo_url=(getattr(payload, "brand_logo_url", None) or "").strip() or None,
        notes_image_url=(getattr(payload, "notes_image_url", None) or "").strip() or None,
        biz_mode=_resolve_biz_mode(getattr(payload, "biz_mode", None)),
        created_by=created_by,
    )
    db.add(so)
    db.flush()
    if payload.lines:
        _apply_lines(db, tenant_id, so, payload.lines)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def update_sales_order(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    payload: SalesOrderUpdate,
) -> SalesOrder:
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_editable", "已完成或已取消的订单不可编辑")
    if so.status != SalesOrderStatus.draft and payload.lines is not None:
        raise SalesOrderError("not_editable", "仅草稿状态可改明细")
    data = payload.model_dump(exclude_unset=True)
    if "lines" in data and data["lines"] is not None:
        if any(l.production_order_id or getattr(l, "execution_header_id", None) for l in so.lines):
            raise SalesOrderError("has_production", "已有产品行下生产，不可整单替换明细")
        # 必须传 Pydantic 行对象；dict 的 .items 是方法会炸
        _apply_lines(db, tenant_id, so, payload.lines or [])
    if "order_no" in data:
        order_no = (data["order_no"] or "").strip()
        if not order_no:
            raise SalesOrderError("empty_order_no", "订单号不能为空")
        if order_no != so.order_no:
            exists = db.scalar(
                select(SalesOrder).where(
                    SalesOrder.tenant_id == tenant_id,
                    SalesOrder.order_no == order_no,
                    SalesOrder.id != so.id,
                )
            )
            if exists:
                raise SalesOrderError("duplicate_order_no", f"销售订单号已存在: {order_no}")
            so.order_no = order_no
    if "customer_id" in data or "customer_name" in data:
        try:
            cust_id, cust_name = _resolve_customer(
                db,
                tenant_id,
                customer_id=data.get("customer_id", so.customer_id),
                customer_name=data.get("customer_name", so.customer_name),
            )
        except OrderError as e:
            raise SalesOrderError(e.code, e.message) from e
        so.customer_id = cust_id
        so.customer_name = cust_name
    if "ordered_at" in data and data["ordered_at"] is not None:
        so.ordered_at = data["ordered_at"]
    if "notes" in data:
        raw = data["notes"]
        so.notes = (str(raw).strip() if raw is not None else "") or None
    if "brand_logo_url" in data:
        raw = data["brand_logo_url"]
        so.brand_logo_url = (str(raw).strip() if raw is not None else "") or None
    if "notes_image_url" in data:
        raw = data["notes_image_url"]
        so.notes_image_url = (str(raw).strip() if raw is not None else "") or None
    if "biz_mode" in data and data["biz_mode"] is not None:
        so.biz_mode = _resolve_biz_mode(data["biz_mode"])
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def add_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    payload: SalesOrderLineIn,
) -> SalesOrder:
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_editable", "已完成或已取消的订单不可增行")
    if so.status != SalesOrderStatus.draft:
        raise SalesOrderError("not_editable", "仅草稿状态可增行")
    fields, positive_items = _line_fields_from_in(db, tenant_id, so, payload)
    insert_before_id = payload.insert_before_line_id
    if insert_before_id is not None:
        target = next((ln for ln in so.lines if ln.id == insert_before_id), None)
        if not target:
            raise SalesOrderError("line_not_found", "插入位置对应的明细不存在")
        at = target.sort_order if target.sort_order is not None else 0
        for ln in so.lines:
            cur = ln.sort_order if ln.sort_order is not None else 0
            if cur >= at:
                ln.sort_order = cur + 1
        new_sort = at
    else:
        max_so = max(
            ((ln.sort_order if ln.sort_order is not None else 0) for ln in so.lines),
            default=-1,
        )
        new_sort = max_so + 1
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        status=SalesOrderLineStatus.pending,
        sort_order=new_sort,
        **fields,
    )
    db.add(line)
    db.flush()
    _replace_line_items(db, tenant_id, line, positive_items)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def update_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    line_id: int,
    payload: SalesOrderLineIn,
) -> SalesOrder:
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_editable", "已完成或已取消的订单不可改行")
    line = next((ln for ln in so.lines if ln.id == line_id), None)
    if not line:
        raise SalesOrderError("line_not_found", "产品行不存在")
    if (
        line.production_order_id
        or getattr(line, "execution_header_id", None)
        or _line_allocated_qty(line) > 0
        or line.status == SalesOrderLineStatus.in_production
    ):
        raise SalesOrderError("line_confirmed", "已排进生产单的明细不可编辑")
    fields, positive_items = _line_fields_from_in(db, tenant_id, so, payload)
    for k, v in fields.items():
        setattr(line, k, v)
    _replace_line_items(db, tenant_id, line, positive_items)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


ORDER_SORT_FIELDS = frozenset({"order_no", "customer_name", "ordered_at", "id"})
LINE_SORT_FIELDS = frozenset(
    {
        "line_no",
        "sort_order",
        "product_code",
        "customer_sku",
        "total_qty",
        "unit_price",
        "line_total",
        "delivery_date",
    }
)


def _order_nulls_last(column, *, asc: bool = True):
    """MySQL-compatible NULLS LAST (IS NULL sort key + column direction)."""
    return column.is_(None).asc(), column.asc() if asc else column.desc()


PRODUCT_LINE_SORT_COLUMNS = {
    "line_no": lambda: SalesOrderLine.sort_order,
    "sort_order": lambda: SalesOrderLine.sort_order,
    "product_code": lambda: OwnProduct.product_code,
    "customer_sku": lambda: SalesOrderLine.customer_sku,
    "total_qty": lambda: SalesOrderLine.total_qty,
    "unit_price": lambda: SalesOrderLine.unit_price,
    "line_total": lambda: SalesOrderLine.unit_price * SalesOrderLine.total_qty,
    "delivery_date": lambda: SalesOrderLine.delivery_date,
    "order_no": lambda: SalesOrder.order_no,
    "customer_name": lambda: SalesOrder.customer_name,
    "ordered_at": lambda: SalesOrder.ordered_at,
}


def _line_agg_expr(sort_by: str):
    if sort_by in ("line_no", "sort_order"):
        return func.min(SalesOrderLine.sort_order)
    if sort_by == "product_code":
        return func.min(OwnProduct.product_code)
    if sort_by == "customer_sku":
        return func.min(SalesOrderLine.customer_sku)
    if sort_by == "total_qty":
        return func.min(SalesOrderLine.total_qty)
    if sort_by == "unit_price":
        return func.min(SalesOrderLine.unit_price)
    if sort_by == "line_total":
        return func.min(SalesOrderLine.unit_price * SalesOrderLine.total_qty)
    if sort_by == "delivery_date":
        return func.min(SalesOrderLine.delivery_date)
    return None


def _sort_lines_within_orders(
    db: Session,
    rows: list[SalesOrder],
    sort_by: str,
    *,
    asc: bool,
) -> None:
    if sort_by not in LINE_SORT_FIELDS:
        return
    product_codes: dict[int, str] = {}
    if sort_by == "product_code":
        product_ids = {ln.own_product_id for so in rows for ln in so.lines}
        if product_ids:
            for p in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(product_ids))):
                product_codes[p.id] = p.product_code

    def line_key(ln: SalesOrderLine):
        if sort_by in ("line_no", "sort_order"):
            return ln.sort_order if ln.sort_order is not None else 0
        if sort_by == "product_code":
            return product_codes.get(ln.own_product_id) or ""
        if sort_by == "customer_sku":
            return ln.customer_sku or ""
        if sort_by == "total_qty":
            return ln.total_qty or 0
        if sort_by == "unit_price":
            return float(ln.unit_price) if ln.unit_price is not None else float("-inf")
        if sort_by == "line_total":
            if ln.unit_price is None:
                return float("-inf")
            return float(ln.unit_price) * (ln.total_qty or 0)
        if sort_by == "delivery_date":
            return ln.delivery_date or date.min
        return ""

    reverse = not asc
    for so in rows:
        so.lines.sort(key=line_key, reverse=reverse)


def _serialize_flat_line_row(db: Session, tenant_id: int, line: SalesOrderLine, so: SalesOrder) -> dict:
    ser = _serialize_line(db, tenant_id, line)
    qty = line.total_qty or 0
    price = line.unit_price
    line_total = float(price * qty) if price is not None and qty else None
    return {
        **ser,
        "_key": f"{so.id}-{line.id}",
        "sales_order_id": so.id,
        "sales_order_line_id": line.id,
        "order_no": so.order_no,
        "customer_name": so.customer_name,
        "ordered_at": so.ordered_at,
        "order_status": so.status.value if hasattr(so.status, "value") else str(so.status),
        "line_status": ser["status"],
        "line_total": line_total,
    }


def list_sales_order_product_lines(
    db: Session,
    tenant_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    product_code: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> tuple[list[dict], int]:
    from app.schemas.common import normalize_page

    page, page_size, offset = normalize_page(page, page_size)
    sb = (sort_by or "line_no").strip()
    asc = (sort_order or "asc").strip().lower() == "asc"
    sort_col = PRODUCT_LINE_SORT_COLUMNS.get(sb, PRODUCT_LINE_SORT_COLUMNS["line_no"])()

    q = (
        select(SalesOrderLine)
        .join(SalesOrder, SalesOrderLine.sales_order_id == SalesOrder.id)
        .join(OwnProduct, SalesOrderLine.own_product_id == OwnProduct.id)
        .where(SalesOrderLine.tenant_id == tenant_id)
        .options(
            selectinload(SalesOrderLine.items),
            selectinload(SalesOrderLine.sales_order),
        )
    )
    if status:
        q = _apply_line_display_status_filter(q, status, tenant_id)
    if product_code and product_code.strip():
        pc = f"%{product_code.strip()}%"
        q = q.where(OwnProduct.product_code.ilike(pc))

    # 序号排序时按订单号分组，便于同一订单内连续看行序
    if sb in ("line_no", "sort_order"):
        q = q.order_by(
            SalesOrder.order_no.asc() if asc else SalesOrder.order_no.desc(),
            sort_col.asc() if asc else sort_col.desc(),
            SalesOrderLine.id.asc(),
        )
    else:
        q = q.order_by(*_order_nulls_last(sort_col, asc=asc), SalesOrderLine.id.asc())

    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    lines = list(db.scalars(q.offset(offset).limit(page_size)).all())
    items = [
        _serialize_flat_line_row(db, tenant_id, line, line.sales_order)
        for line in lines
        if line.sales_order is not None
    ]
    return items, int(total)


# 与前端 lineStatusLabel 一致的展示状态（非订单头枚举）
DISPLAY_STATUS_KEYS = (
    "pending_confirm",  # 待确认（草稿）
    "pending_schedule",  # 待排产（已接单、尚未进执行单）
    "pending_production",  # 已排产（有执行单/分配，尚未开工）· 兼容旧筛选项
    "in_progress",  # 生产中
    "completed",  # 已完成
    "cancelled",  # 已取消
)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _line_allocated_qty(line: SalesOrderLine) -> int:
    return sum(int(getattr(it, "allocated_qty", 0) or 0) for it in (line.items or []))


def _line_has_execution(line: SalesOrderLine) -> bool:
    return bool(
        line.production_order_id
        or getattr(line, "execution_header_id", None)
        or _line_allocated_qty(line) > 0
        or _enum_val(line.status) == "in_production"
    )


def line_display_status(
    *,
    order_status: str,
    line_status: str,
    production_order_id: int | None,
    production_order_status: str | None,
    shipped_fully: bool = False,
    shipped_partial: bool = False,
    execution_header_id: int | None = None,
    allocated_qty: int = 0,
    execution_status: str | None = None,
    qty: int = 0,
    produced_qty: int = 0,
    shipped_qty: int = 0,
    wip_qty: int = 0,
) -> str:
    """明细行展示状态，与 lifecycle-status-flow 数量推导对齐。

    库内枚举较粗；列表徽章认数量 + 执行单状态。
    `confirmed` 执行单 = 已排产 planned；`cut`/`in_progress` = 生产中。
    """
    if order_status == "cancelled" or line_status == "cancelled":
        return "cancelled"
    if order_status == "completed" or line_status == "completed" or shipped_fully:
        return "completed"
    if qty > 0 and shipped_qty >= qty:
        return "completed"
    if production_order_status == "completed":
        return "completed"
    if production_order_status == "cancelled":
        return "cancelled"
    if shipped_partial or shipped_qty > 0:
        return "in_progress"
    if produced_qty > 0 and (qty <= 0 or shipped_qty < qty):
        return "in_progress"
    exe = execution_status or production_order_status
    if exe in ("cut", "in_progress", "suspended", "completed") or wip_qty > 0:
        return "in_progress"
    if production_order_status == "in_progress":
        return "in_progress"
    scheduled = bool(
        production_order_id
        or execution_header_id
        or allocated_qty > 0
        or line_status == "in_production"
    )
    if scheduled:
        return "pending_production"  # 已排产（仅 planned / 部分排产）
    if order_status == "confirmed":
        return "pending_schedule"  # 待排产
    return "pending_confirm"


def _line_ship_flags(line: SalesOrderLine) -> tuple[bool, bool]:
    items = [it for it in (line.items or []) if int(it.qty or 0) > 0]
    if not items:
        return False, False
    fully = all(int(getattr(it, "shipped_qty", 0) or 0) >= int(it.qty or 0) for it in items)
    partial = any(int(getattr(it, "shipped_qty", 0) or 0) > 0 for it in items)
    return fully, partial and not fully


def order_display_status(
    so: SalesOrder,
    prod_status_by_id: dict[int, str | None],
    *,
    exe_status_by_header_id: dict[int, str] | None = None,
) -> str:
    """订单展示状态：终态用订单头；否则按明细聚合。"""
    so_st = _enum_val(so.status)
    if so_st == "cancelled":
        return "cancelled"
    if so_st == "completed":
        return "completed"
    has_in_progress = False
    has_scheduled = False
    has_pending_schedule = False
    has_completed_line = False
    active_lines = 0
    exe_map = exe_status_by_header_id or {}
    for line in so.lines or []:
        if _enum_val(line.status) == "cancelled":
            continue
        active_lines += 1
        shipped_fully, shipped_partial = _line_ship_flags(line)
        hid = getattr(line, "execution_header_id", None)
        ds = line_display_status(
            order_status=so_st,
            line_status=_enum_val(line.status),
            production_order_id=line.production_order_id,
            production_order_status=prod_status_by_id.get(line.production_order_id)
            if line.production_order_id
            else None,
            shipped_fully=shipped_fully,
            shipped_partial=shipped_partial,
            execution_header_id=hid,
            allocated_qty=_line_allocated_qty(line),
            execution_status=exe_map.get(int(hid)) if hid else None,
            qty=_line_sum_item_field(line, "qty"),
            produced_qty=_line_sum_item_field(line, "produced_qty"),
            shipped_qty=_line_sum_item_field(line, "shipped_qty"),
        )
        if ds == "in_progress":
            has_in_progress = True
        elif ds == "pending_production":
            has_scheduled = True
        elif ds == "pending_schedule":
            has_pending_schedule = True
        elif ds == "completed":
            has_completed_line = True
    if has_in_progress:
        return "in_progress"
    if has_scheduled:
        return "pending_production"
    if has_pending_schedule:
        return "pending_schedule"
    if active_lines and has_completed_line and not has_scheduled and not has_pending_schedule:
        return "completed"
    return "pending_confirm"


def _normalize_display_status(status: str | None) -> str | None:
    """兼容旧订单头状态筛选值。"""
    if not status:
        return None
    legacy = {
        "draft": "pending_confirm",
        "confirmed": "pending_schedule",
        "pending_production": "pending_production",
    }
    key = legacy.get(status, status)
    if key not in DISPLAY_STATUS_KEYS:
        raise SalesOrderError("invalid_status", f"无效状态：{status}")
    return key


def _sales_order_ids_with_production(tenant_id: int):
    """已排进执行单/旧生产单的销售单（含仅有 allocated 的）。"""
    allocated_line_ids = (
        select(SalesOrderLineItem.sales_order_line_id)
        .where(
            SalesOrderLineItem.tenant_id == tenant_id,
            SalesOrderLineItem.allocated_qty > 0,
        )
        .distinct()
    )
    return (
        select(SalesOrderLine.sales_order_id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            (SalesOrderLine.production_order_id.isnot(None))
            | (SalesOrderLine.execution_header_id.isnot(None))
            | (SalesOrderLine.status == SalesOrderLineStatus.in_production)
            | (SalesOrderLine.id.in_(allocated_line_ids)),
        )
        .distinct()
    )


def _sales_order_ids_pending_schedule(tenant_id: int):
    """已接单且尚未排进执行单。"""
    has_prod = _sales_order_ids_with_production(tenant_id)
    return (
        select(SalesOrder.id)
        .where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.status == SalesOrderStatus.confirmed,
            ~SalesOrder.id.in_(has_prod),
        )
    )


def _sales_order_ids_in_progress(tenant_id: int):
    return (
        select(SalesOrderLine.sales_order_id)
        .join(Order, SalesOrderLine.production_order_id == Order.id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            Order.status == OrderStatus.in_progress,
        )
        .distinct()
    )


def _apply_order_display_status_filter(q, status: str, tenant_id: int):
    key = _normalize_display_status(status)
    assert key is not None
    if key == "cancelled":
        return q.where(SalesOrder.status == SalesOrderStatus.cancelled)
    if key == "completed":
        return q.where(SalesOrder.status == SalesOrderStatus.completed)
    q = q.where(
        SalesOrder.status.notin_(
            [SalesOrderStatus.completed, SalesOrderStatus.cancelled]
        )
    )
    in_prog = _sales_order_ids_in_progress(tenant_id)
    has_prod = _sales_order_ids_with_production(tenant_id)
    pending_sched = _sales_order_ids_pending_schedule(tenant_id)
    if key == "in_progress":
        return q.where(SalesOrder.id.in_(in_prog))
    if key == "pending_production":
        return q.where(SalesOrder.id.in_(has_prod), ~SalesOrder.id.in_(in_prog))
    if key == "pending_schedule":
        return q.where(SalesOrder.id.in_(pending_sched))
    # pending_confirm：草稿且未排产
    return q.where(
        SalesOrder.status == SalesOrderStatus.draft,
        ~SalesOrder.id.in_(has_prod),
    )


def _apply_line_display_status_filter(q, status: str, tenant_id: int):
    """产品视图：按明细展示状态筛选。"""
    key = _normalize_display_status(status)
    assert key is not None
    if key == "cancelled":
        return q.where(
            (SalesOrder.status == SalesOrderStatus.cancelled)
            | (SalesOrderLine.status == SalesOrderLineStatus.cancelled)
        )
    if key == "completed":
        return q.where(
            (SalesOrder.status == SalesOrderStatus.completed)
            | (SalesOrderLine.status == SalesOrderLineStatus.completed)
            | (
                SalesOrderLine.production_order_id.isnot(None)
                & SalesOrderLine.production_order_id.in_(
                    select(Order.id).where(Order.status == OrderStatus.completed)
                )
            )
        )
    q = q.where(
        SalesOrder.status.notin_(
            [SalesOrderStatus.completed, SalesOrderStatus.cancelled]
        ),
        SalesOrderLine.status.notin_(
            [SalesOrderLineStatus.completed, SalesOrderLineStatus.cancelled]
        ),
    )
    in_prog_line = (
        select(SalesOrderLine.id)
        .join(Order, SalesOrderLine.production_order_id == Order.id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            Order.status == OrderStatus.in_progress,
        )
    )
    allocated_line_ids = (
        select(SalesOrderLineItem.sales_order_line_id)
        .where(
            SalesOrderLineItem.tenant_id == tenant_id,
            SalesOrderLineItem.allocated_qty > 0,
        )
        .distinct()
    )
    has_prod = (
        (SalesOrderLine.production_order_id.isnot(None))
        | (SalesOrderLine.execution_header_id.isnot(None))
        | (SalesOrderLine.status == SalesOrderLineStatus.in_production)
        | (SalesOrderLine.id.in_(allocated_line_ids))
    )
    if key == "in_progress":
        return q.where(SalesOrderLine.id.in_(in_prog_line))
    if key == "pending_production":
        return q.where(has_prod, ~SalesOrderLine.id.in_(in_prog_line))
    if key == "pending_schedule":
        return q.where(
            SalesOrder.status == SalesOrderStatus.confirmed,
            ~has_prod,
        )
    return q.where(SalesOrder.status == SalesOrderStatus.draft, ~has_prod)


def count_sales_orders_by_status(db: Session, tenant_id: int) -> dict:
    """按展示状态统计订单数量（与列表状态标签一致）。"""
    orders = list(
        db.scalars(
            select(SalesOrder)
            .where(SalesOrder.tenant_id == tenant_id)
            .options(
                selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items)
            )
        ).all()
    )
    prod_ids = {
        ln.production_order_id
        for so in orders
        for ln in (so.lines or [])
        if ln.production_order_id
    }
    prod_status_by_id: dict[int, str | None] = {}
    if prod_ids:
        for po in db.scalars(select(Order).where(Order.id.in_(prod_ids))).all():
            prod_status_by_id[po.id] = _enum_val(po.status)
    header_ids = {
        int(ln.execution_header_id)
        for so in orders
        for ln in (so.lines or [])
        if getattr(ln, "execution_header_id", None)
    }
    exe_status_by_header_id: dict[int, str] = {}
    if header_ids:
        for hdr in db.scalars(select(ExecutionHeader).where(ExecutionHeader.id.in_(header_ids))).all():
            exe_status_by_header_id[hdr.id] = _enum_val(hdr.status)

    counts = {k: 0 for k in DISPLAY_STATUS_KEYS}
    for so in orders:
        counts[order_display_status(so, prod_status_by_id, exe_status_by_header_id=exe_status_by_header_id)] += 1
    return {"total": len(orders), "by_status": counts}


def list_sales_orders(
    db: Session,
    tenant_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    customer_id: int | None = None,
    status: str | None = None,
    product_code: str | None = None,
    biz_mode: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> tuple[list[SalesOrder], int]:
    from app.schemas.common import normalize_page

    page, page_size, offset = normalize_page(page, page_size)
    sb = (sort_by or "id").strip()
    asc = (sort_order or "desc").strip().lower() == "asc"

    q = (
        select(SalesOrder)
        .where(SalesOrder.tenant_id == tenant_id)
        .options(
            selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items),
        )
    )
    if customer_id:
        q = q.where(SalesOrder.customer_id == customer_id)
    if status:
        q = _apply_order_display_status_filter(q, status, tenant_id)
    if biz_mode:
        _resolve_biz_mode(biz_mode)  # 校验
        q = q.where(SalesOrder.biz_mode == SalesBizMode(biz_mode))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(
            (SalesOrder.order_no.ilike(kw)) | (SalesOrder.customer_name.ilike(kw))
        )
    if product_code and product_code.strip():
        pc = f"%{product_code.strip()}%"
        line_match = (
            select(SalesOrderLine.sales_order_id)
            .join(OwnProduct, SalesOrderLine.own_product_id == OwnProduct.id)
            .where(
                SalesOrderLine.tenant_id == tenant_id,
                OwnProduct.product_code.ilike(pc),
            )
            .distinct()
        )
        q = q.where(SalesOrder.id.in_(line_match))

    if sb in LINE_SORT_FIELDS:
        agg = _line_agg_expr(sb)
        line_sq = select(
            SalesOrderLine.sales_order_id.label("so_id"),
            agg.label("sort_val"),
        ).where(SalesOrderLine.tenant_id == tenant_id)
        if sb == "product_code":
            line_sq = line_sq.join(OwnProduct, SalesOrderLine.own_product_id == OwnProduct.id)
        line_sq = line_sq.group_by(SalesOrderLine.sales_order_id).subquery()
        q = q.outerjoin(line_sq, SalesOrder.id == line_sq.c.so_id)
        sort_col = line_sq.c.sort_val
        q = q.order_by(*_order_nulls_last(sort_col, asc=asc), SalesOrder.id.desc())
    else:
        sort_map = {
            "order_no": SalesOrder.order_no,
            "customer_name": SalesOrder.customer_name,
            "ordered_at": SalesOrder.ordered_at,
            "id": SalesOrder.id,
        }
        sort_col = sort_map.get(sb, SalesOrder.id)
        q = q.order_by(sort_col.asc() if asc else sort_col.desc())

    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = list(db.scalars(q.offset(offset).limit(page_size)).all())
    if sb in LINE_SORT_FIELDS:
        _sort_lines_within_orders(db, rows, sb, asc=asc)
    else:
        for so in rows:
            so.lines.sort(key=lambda ln: (ln.sort_order if ln.sort_order is not None else 0, ln.id))
    return rows, int(total)


def _create_production_for_line(
    db: Session,
    tenant_id: int,
    so: SalesOrder,
    line: SalesOrderLine,
    *,
    created_by: int | None,
) -> "ExecutionHeader":
    """（遗留）一产品行 → 一执行单。正确路径请走排产确认；测试/运维可显式调用。"""
    from app.models import ExecutionHeader  # noqa: F401
    from app.services.execution_service import ExecutionError, create_execution_from_sales_line

    if line.production_order_id or getattr(line, "execution_header_id", None):
        raise SalesOrderError("line_confirmed", "该产品行已排进生产单")
    if not line.items:
        raise SalesOrderError("empty_items", "产品行色码明细不能为空")
    try:
        header = create_execution_from_sales_line(
            db,
            tenant_id=tenant_id,
            sales_order=so,
            line=line,
            created_by=created_by,
            commit=False,
        )
    except ExecutionError as e:
        raise SalesOrderError(e.code, e.message) from e
    return header


def _accept_sales_order(so: SalesOrder) -> None:
    """确认接单：订单 → confirmed；不创建执行单。"""
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_confirmable", "当前销售订单状态不可确认接单")
    if not so.lines:
        raise SalesOrderError("empty_lines", "无产品行，无法确认接单")
    if so.status == SalesOrderStatus.draft:
        so.status = SalesOrderStatus.confirmed


def _sync_sales_order_status(so: SalesOrder) -> None:
    """接单后保持 confirmed；兼容旧数据：已有执行单但头仍草稿时抬到 confirmed。"""
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        return
    if so.status == SalesOrderStatus.draft and any(
        getattr(l, "execution_header_id", None) or l.production_order_id for l in (so.lines or [])
    ):
        so.status = SalesOrderStatus.confirmed


def delete_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    line_id: int,
) -> SalesOrder:
    """删除未排进执行单的产品明细行。"""
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_editable", "已完成或已取消的订单不可删行")
    line = next((ln for ln in so.lines if ln.id == line_id), None)
    if not line:
        raise SalesOrderError("line_not_found", "产品行不存在")
    if (
        line.production_order_id
        or getattr(line, "execution_header_id", None)
        or _line_allocated_qty(line) > 0
        or line.status == SalesOrderLineStatus.in_production
    ):
        raise SalesOrderError("line_confirmed", "已排进生产单的明细不可删除")
    db.delete(line)
    db.flush()
    db.refresh(so)
    for idx, ln in enumerate(
        sorted(so.lines, key=lambda x: (x.sort_order if x.sort_order is not None else 0, x.id))
    ):
        ln.sort_order = idx
    _sync_sales_order_status(so)
    db.commit()
    return get_sales_order(db, tenant_id, sales_order_id)


def cancel_sales_order(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
) -> SalesOrder:
    """取消销售订单：状态改为已取消（记录仍保留，与删除明细不同）。"""
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status == SalesOrderStatus.cancelled:
        raise SalesOrderError("already_cancelled", "订单已取消")
    if so.status == SalesOrderStatus.completed:
        raise SalesOrderError("not_cancellable", "已完成的订单不可取消")
    if any(
        l.production_order_id
        or getattr(l, "execution_header_id", None)
        or _line_allocated_qty(l) > 0
        for l in so.lines
    ):
        raise SalesOrderError(
            "has_production",
            f"订单 {so.order_no} 已有产品行排进生产单，不可取消；请先处理生产单",
        )
    so.status = SalesOrderStatus.cancelled
    for line in so.lines:
        if line.status != SalesOrderLineStatus.completed:
            line.status = SalesOrderLineStatus.cancelled
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def confirm_sales_order_lines_batch(
    db: Session,
    tenant_id: int,
    refs: list[tuple[int, int]],
    *,
    created_by: int | None,
) -> int:
    """批量确认接单（按涉及的销售单去重）；不创建执行单。"""
    if not refs:
        raise SalesOrderError("empty_lines", "请选择产品行")
    so_cache: dict[int, SalesOrder] = {}
    for sales_order_id, line_id in refs:
        so = so_cache.get(sales_order_id)
        if not so:
            so = get_sales_order(db, tenant_id, sales_order_id)
            so_cache[sales_order_id] = so
        line = next((l for l in so.lines if l.id == line_id), None)
        if not line:
            raise SalesOrderError("line_not_found", "销售订单产品行不存在")
        _accept_sales_order(so)
    db.commit()
    return len(so_cache)


def confirm_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    line_id: int,
    *,
    created_by: int | None,
) -> SalesOrder:
    """确认接单（行入口）：将所属销售单置为 confirmed，不创建执行单。"""
    so = get_sales_order(db, tenant_id, sales_order_id)
    line = next((l for l in so.lines if l.id == line_id), None)
    if not line:
        raise SalesOrderError("line_not_found", "销售订单产品行不存在")
    _accept_sales_order(so)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def confirm_sales_order(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    *,
    created_by: int | None,
) -> SalesOrder:
    """确认接单：订单 → confirmed；色码进入待排产，不创建执行单。"""
    so = get_sales_order(db, tenant_id, sales_order_id)
    _accept_sales_order(so)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def simulate_sales_order_lines_mrp(
    db: Session,
    tenant_id: int,
    refs: list[tuple[int, int]],
    *,
    include_shared: bool | None = True,
    shortages_only: bool = False,
) -> dict:
    """销售订单产品行模拟 MRP：BOM 展开 + 剩余池承诺，只算不锁。"""
    from app.services.material_service import simulate_mrp_from_bom

    if not refs:
        raise SalesOrderError("empty_lines", "请选择产品行")

    so_cache: dict[int, SalesOrder] = {}
    demands: list[dict] = []
    skipped: list[dict] = []
    for sales_order_id, line_id in refs:
        so = so_cache.get(sales_order_id)
        if not so:
            so = get_sales_order(db, tenant_id, sales_order_id)
            so_cache[sales_order_id] = so
        line = next((l for l in so.lines if l.id == line_id), None)
        if not line:
            raise SalesOrderError("line_not_found", "销售订单产品行不存在")
        if line.production_order_id or getattr(line, "execution_header_id", None):
            skipped.append(
                {
                    "sales_order_id": so.id,
                    "line_id": line.id,
                    "order_no": so.order_no,
                    "reason": "已排进生产单，请在生产单看齐套",
                    "production_order_id": line.production_order_id,
                    "execution_header_id": getattr(line, "execution_header_id", None),
                }
            )
            continue
        if not line.own_product_id or int(line.total_qty or 0) <= 0:
            skipped.append(
                {
                    "sales_order_id": so.id,
                    "line_id": line.id,
                    "order_no": so.order_no,
                    "reason": "无产品或数量",
                }
            )
            continue
        product = db.get(OwnProduct, line.own_product_id)
        product_code = product.product_code if product else None
        product_image_url = product.image_url if product else None
        label = " · ".join(
            x for x in [so.order_no, product_code, (line.brand_name or None)] if x
        )
        size_qtys: dict[int, int] = {}
        for it in line.items or []:
            if not it.size_id:
                continue
            sid = int(it.size_id)
            size_qtys[sid] = size_qtys.get(sid, 0) + int(it.qty or 0)
        demands.append(
            {
                "key": f"so_line:{line.id}",
                "label": label,
                "order_no": so.order_no,
                "product_code": product_code,
                    "product_image_url": product_image_url,
                    "own_product_id": line.own_product_id,
                    "total_qty": int(line.total_qty),
                    "size_qtys": size_qtys,
                    "color_id": line.color_id,
                "delivery_date": line.delivery_date,
                "sales_order_id": so.id,
                "sales_order_line_id": line.id,
                "priority_key": (
                    line.delivery_date.toordinal() if line.delivery_date else 10**9,
                    so.id,
                    line.sort_order if line.sort_order is not None else 0,
                    line.id,
                ),
            }
        )

    if not demands and skipped:
        raise SalesOrderError(
            "nothing_to_simulate",
            "所选行均已排进生产单或无数量；已排产请在生产单看齐套",
        )
    if not demands:
        raise SalesOrderError("empty_lines", "请选择可模拟的产品行")

    result = simulate_mrp_from_bom(
        db,
        tenant_id,
        demands,
        include_shared=include_shared,
        shortages_only=shortages_only,
    )
    result["skipped"] = skipped
    result["source"] = "demand"
    result["locked"] = False
    return result


def _collect_pending_schedule_line_refs(
    db: Session,
    tenant_id: int,
    *,
    sales_order_id: int | None = None,
) -> list[tuple[int, int]]:
    """已接单、尚未排进执行单的产品行。"""
    q = (
        select(SalesOrderLine)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            SalesOrder.status == SalesOrderStatus.confirmed,
            SalesOrderLine.status != SalesOrderLineStatus.cancelled,
            SalesOrderLine.production_order_id.is_(None),
            SalesOrderLine.execution_header_id.is_(None),
        )
        .options(selectinload(SalesOrderLine.items))
    )
    if sales_order_id is not None:
        q = q.where(SalesOrderLine.sales_order_id == sales_order_id)
    lines = list(db.scalars(q).all())
    refs: list[tuple[int, int]] = []
    for line in lines:
        if _line_allocated_qty(line) > 0:
            continue
        if int(line.total_qty or 0) <= 0:
            continue
        refs.append((int(line.sales_order_id), int(line.id)))
    return refs


def _demand_draft_qty_by_key(
    db: Session, tenant_id: int
) -> dict[tuple[int, int | None], Decimal]:
    """已有需求备料草稿占用（同料同码）。"""
    from app.models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus

    existing_draft = db.execute(
        select(
            PurchaseOrderLine.supplier_product_id,
            PurchaseOrderLine.size_id,
            func.coalesce(func.sum(PurchaseOrderLine.qty), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status == PurchaseOrderStatus.draft,
            PurchaseOrderLine.sales_order_id.isnot(None),
            PurchaseOrderLine.order_material_requirement_id.is_(None),
        )
        .group_by(PurchaseOrderLine.supplier_product_id, PurchaseOrderLine.size_id)
    ).all()
    return {
        (int(sp), int(sz) if sz is not None else None): Decimal(str(qty or 0))
        for sp, sz, qty in existing_draft
    }


def _annotate_demand_cover(db: Session, tenant_id: int, result: dict) -> dict:
    """把草稿扣进待买，给界面一根覆盖口径。"""
    draft_by_key = _demand_draft_qty_by_key(db, tenant_id)
    to_buy_lines = 0
    for row in result.get("lines") or []:
        sp_id = int(row["supplier_product_id"])
        size_id = int(row["size_id"]) if row.get("size_id") is not None else None
        draft = draft_by_key.get((sp_id, size_id), Decimal("0"))
        shortage = Decimal(str(row.get("shortage_qty") or 0))
        to_buy = max(Decimal("0"), shortage - draft)
        row["draft_qty"] = draft
        row["to_buy_qty"] = to_buy
        if to_buy > 0:
            to_buy_lines += 1
    result["to_buy_lines"] = to_buy_lines
    return result


def list_demand_shortages(
    db: Session,
    tenant_id: int,
    *,
    sales_order_id: int | None = None,
    include_shared: bool | None = True,
) -> dict:
    """需求缺料：认销售、只读不锁。覆盖已接单未排产行。"""
    refs = _collect_pending_schedule_line_refs(
        db, tenant_id, sales_order_id=sales_order_id
    )
    if not refs:
        return {
            "source": "demand",
            "locked": False,
            "kit_ok": True,
            "empty_bom": False,
            "shortage_lines": 0,
            "to_buy_lines": 0,
            "demand_count": 0,
            "lines": [],
            "skipped": [],
            "refs": [],
        }
    result = simulate_sales_order_lines_mrp(
        db,
        tenant_id,
        refs,
        include_shared=include_shared,
        shortages_only=True,
    )
    result["refs"] = [{"sales_order_id": a, "line_id": b} for a, b in refs]
    return _annotate_demand_cover(db, tenant_id, result)


def create_demand_purchase_drafts(
    db: Session,
    tenant_id: int,
    refs: list[tuple[int, int]],
    *,
    include_shared: bool | None = True,
    user_id: int | None = None,
) -> list[dict]:
    """按需求缺料生成采购草稿：挂 sales_order_id，不写用料行、不锁池。"""
    from app.models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus, SupplierProduct
    from app.services.purchase_service import _po_out, generate_po_no, get_po, new_public_token

    mrp = simulate_sales_order_lines_mrp(
        db,
        tenant_id,
        refs,
        include_shared=include_shared,
        shortages_only=True,
    )
    draft_by_key = _demand_draft_qty_by_key(db, tenant_id)

    line_so_map: dict[int, tuple[int, str]] = {}
    for sales_order_id, line_id in refs:
        so = get_sales_order(db, tenant_id, sales_order_id)
        line_so_map[line_id] = (so.id, so.order_no)

    by_partner: dict[int, list[dict]] = {}
    for row in mrp.get("lines") or []:
        shortage = Decimal(str(row.get("shortage_qty") or 0))
        if shortage <= 0:
            continue
        sp_id = int(row["supplier_product_id"])
        size_id = int(row["size_id"]) if row.get("size_id") is not None else None
        already = draft_by_key.get((sp_id, size_id), Decimal("0"))
        need = shortage - already
        if need <= 0:
            continue
        partner_id = row.get("partner_id")
        if not partner_id:
            raise SalesOrderError(
                "no_supplier",
                f"物料 {row.get('supplier_product_code') or sp_id} 无供应商，无法建需求采购",
            )
        # 取首个来源销售行
        so_id = None
        so_line_id = None
        so_nos: list[str] = []
        for src in row.get("sources") or []:
            key = str(src.get("key") or "")
            if key.startswith("so_line:"):
                try:
                    lid = int(key.split(":", 1)[1])
                except ValueError:
                    continue
                if lid in line_so_map:
                    so_id, so_no = line_so_map[lid]
                    so_line_id = lid
                    if so_no not in so_nos:
                        so_nos.append(so_no)
        by_partner.setdefault(int(partner_id), []).append(
            {
                "supplier_product_id": sp_id,
                "size_id": size_id,
                "buy_qty": need,
                "unit_price": row.get("unit_price") or Decimal("0"),
                "sales_order_id": so_id,
                "sales_order_line_id": so_line_id,
                "sales_order_nos": so_nos,
            }
        )

    if not by_partner:
        raise SalesOrderError("no_shortage", "没有要买的料（可能已有草稿覆盖）")

    created: list[dict] = []
    for partner_id, rows in by_partner.items():
        nos = sorted({n for r in rows for n in (r.get("sales_order_nos") or []) if n})
        note = "需求备料（销售）" + (f"：{'/'.join(nos)}" if nos else "")
        po = PurchaseOrder(
            tenant_id=tenant_id,
            po_no=generate_po_no(db, tenant_id),
            public_token=new_public_token(),
            partner_id=partner_id,
            status=PurchaseOrderStatus.draft,
            notes=note,
            created_by=user_id,
        )
        db.add(po)
        db.flush()
        for r in rows:
            sp = db.get(SupplierProduct, r["supplier_product_id"])
            price = (
                sp.unit_price
                if sp and sp.unit_price is not None
                else Decimal(str(r.get("unit_price") or 0))
            )
            db.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=po.id,
                    supplier_product_id=r["supplier_product_id"],
                    order_id=None,
                    order_material_requirement_id=None,
                    sales_order_id=r.get("sales_order_id"),
                    sales_order_line_id=r.get("sales_order_line_id"),
                    qty=r["buy_qty"],
                    unit_price=price,
                    size_id=r.get("size_id"),
                )
            )
        db.flush()
        created.append(_po_out(db, get_po(db, tenant_id, po.id)))
    db.commit()
    return created
