from __future__ import annotations

from datetime import date, datetime

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Order,
    OrderStatus,
    OwnProduct,
    OwnProductQuote,
    Partner,
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


def _serialize_line(db: Session, tenant_id: int, line: SalesOrderLine) -> dict:
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
            }
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
        "sort_order": line.sort_order if line.sort_order is not None else 0,
        "line_no": (line.sort_order if line.sort_order is not None else 0) + 1,
        "color_summary": line_color.name if line_color else "—",
        "status": line.status.value if hasattr(line.status, "value") else str(line.status),
        "production_order_id": line.production_order_id,
        "production_order_no": prod_order.order_no if prod_order else None,
        "production_order_status": (
            prod_order.status.value if prod_order and hasattr(prod_order.status, "value") else None
        ),
        "items": items_out,
    }


def serialize_sales_order(db: Session, tenant_id: int, so: SalesOrder) -> dict:
    return {
        "id": so.id,
        "order_no": so.order_no,
        "customer_id": so.customer_id,
        "customer_name": so.customer_name,
        "ordered_at": so.ordered_at,
        "status": so.status.value if hasattr(so.status, "value") else str(so.status),
        "notes": so.notes,
        "brand_logo_url": getattr(so, "brand_logo_url", None),
        "notes_image_url": getattr(so, "notes_image_url", None),
        "created_at": so.created_at,
        "lines": [_serialize_line(db, tenant_id, ln) for ln in so.lines],
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
                color_id=None,
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
        if any(l.production_order_id for l in so.lines):
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
    if line.production_order_id or line.status == SalesOrderLineStatus.in_production:
        raise SalesOrderError("line_confirmed", "已下生产的明细不可编辑")
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
    "pending_confirm",  # 待确认
    "pending_production",  # 待生产
    "in_progress",  # 生产中
    "completed",  # 已完成
    "cancelled",  # 已取消
)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def line_display_status(
    *,
    order_status: str,
    line_status: str,
    production_order_id: int | None,
    production_order_status: str | None,
) -> str:
    """明细行展示状态，与前端 lineStatusLabel 对齐。"""
    if order_status == "cancelled" or line_status == "cancelled":
        return "cancelled"
    if order_status == "completed" or line_status == "completed":
        return "completed"
    if production_order_status == "completed":
        return "completed"
    if production_order_status == "cancelled":
        return "cancelled"
    if production_order_status == "in_progress":
        return "in_progress"
    if production_order_id or line_status == "in_production":
        return "pending_production"
    return "pending_confirm"


def order_display_status(
    so: SalesOrder,
    prod_status_by_id: dict[int, str | None],
) -> str:
    """订单展示状态：终态用订单头；否则按明细聚合（生产中 > 待生产 > 待确认）。"""
    so_st = _enum_val(so.status)
    if so_st == "cancelled":
        return "cancelled"
    if so_st == "completed":
        return "completed"
    has_in_progress = False
    has_pending_prod = False
    for line in so.lines or []:
        ds = line_display_status(
            order_status=so_st,
            line_status=_enum_val(line.status),
            production_order_id=line.production_order_id,
            production_order_status=prod_status_by_id.get(line.production_order_id)
            if line.production_order_id
            else None,
        )
        if ds == "in_progress":
            has_in_progress = True
        elif ds == "pending_production":
            has_pending_prod = True
    if has_in_progress:
        return "in_progress"
    if has_pending_prod:
        return "pending_production"
    return "pending_confirm"


def _normalize_display_status(status: str | None) -> str | None:
    """兼容旧订单头状态筛选值。"""
    if not status:
        return None
    legacy = {
        "draft": "pending_confirm",
        "confirmed": "pending_production",
    }
    key = legacy.get(status, status)
    if key not in DISPLAY_STATUS_KEYS:
        raise SalesOrderError("invalid_status", f"无效状态：{status}")
    return key


def _sales_order_ids_with_production(tenant_id: int):
    return (
        select(SalesOrderLine.sales_order_id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            (SalesOrderLine.production_order_id.isnot(None))
            | (SalesOrderLine.status == SalesOrderLineStatus.in_production),
        )
        .distinct()
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
    if key == "in_progress":
        return q.where(SalesOrder.id.in_(in_prog))
    if key == "pending_production":
        return q.where(SalesOrder.id.in_(has_prod), ~SalesOrder.id.in_(in_prog))
    # pending_confirm
    return q.where(~SalesOrder.id.in_(has_prod))


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
    has_prod = (SalesOrderLine.production_order_id.isnot(None)) | (
        SalesOrderLine.status == SalesOrderLineStatus.in_production
    )
    if key == "in_progress":
        return q.where(SalesOrderLine.id.in_(in_prog_line))
    if key == "pending_production":
        return q.where(has_prod, ~SalesOrderLine.id.in_(in_prog_line))
    return q.where(~has_prod)


def count_sales_orders_by_status(db: Session, tenant_id: int) -> dict:
    """按展示状态统计订单数量（与列表状态标签一致）。"""
    orders = list(
        db.scalars(
            select(SalesOrder)
            .where(SalesOrder.tenant_id == tenant_id)
            .options(selectinload(SalesOrder.lines))
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

    counts = {k: 0 for k in DISPLAY_STATUS_KEYS}
    for so in orders:
        counts[order_display_status(so, prod_status_by_id)] += 1
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
) -> Order:
    if line.production_order_id:
        raise SalesOrderError("line_confirmed", "该产品行已下生产")
    if not line.items:
        raise SalesOrderError("empty_items", "产品行色码明细不能为空")
    items = [
        OrderItemIn(color_id=line.color_id, size_id=i.size_id, qty=i.qty) for i in line.items
    ]
    try:
        prod = create_order(
            db,
            tenant_id,
            OrderCreate(
                customer_id=so.customer_id,
                customer_name=so.customer_name,
                own_product_id=line.own_product_id,
                delivery_date=line.delivery_date,
                unit_price=line.unit_price,
                notes=line.notes,
                items=items,
            ),
            created_by=created_by,
            sales_order_id=so.id,
            sales_order_line_id=line.id,
            commit=False,
        )
    except OrderError as e:
        raise SalesOrderError(e.code, e.message) from e
    line.production_order_id = prod.id
    line.status = SalesOrderLineStatus.in_production
    return prod


def _sync_sales_order_status(so: SalesOrder) -> None:
    if not so.lines:
        return
    if all(l.production_order_id for l in so.lines):
        so.status = SalesOrderStatus.confirmed


def delete_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    line_id: int,
) -> SalesOrder:
    """删除待确认（未下生产）的产品明细行。"""
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_editable", "已完成或已取消的订单不可删行")
    line = next((ln for ln in so.lines if ln.id == line_id), None)
    if not line:
        raise SalesOrderError("line_not_found", "产品行不存在")
    if line.production_order_id or line.status == SalesOrderLineStatus.in_production:
        raise SalesOrderError("line_confirmed", "已下生产的明细不可删除")
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
    if any(l.production_order_id for l in so.lines):
        raise SalesOrderError(
            "has_production",
            f"订单 {so.order_no} 已有产品行下生产，不可取消；请先处理生产单",
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
    if not refs:
        raise SalesOrderError("empty_lines", "请选择产品行")
    so_cache: dict[int, SalesOrder] = {}
    count = 0
    for sales_order_id, line_id in refs:
        so = so_cache.get(sales_order_id)
        if not so:
            so = get_sales_order(db, tenant_id, sales_order_id)
            so_cache[sales_order_id] = so
        if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
            raise SalesOrderError("not_confirmable", f"订单 {so.order_no} 不可下生产")
        line = next((l for l in so.lines if l.id == line_id), None)
        if not line:
            raise SalesOrderError("line_not_found", "销售订单产品行不存在")
        _create_production_for_line(db, tenant_id, so, line, created_by=created_by)
        count += 1
    for so in so_cache.values():
        _sync_sales_order_status(so)
    db.commit()
    return count


def confirm_sales_order_line(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    line_id: int,
    *,
    created_by: int | None,
) -> SalesOrder:
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_confirmable", "当前销售订单状态不可下生产")
    line = next((l for l in so.lines if l.id == line_id), None)
    if not line:
        raise SalesOrderError("line_not_found", "销售订单产品行不存在")
    _create_production_for_line(db, tenant_id, so, line, created_by=created_by)
    _sync_sales_order_status(so)
    db.commit()
    return get_sales_order(db, tenant_id, so.id)


def confirm_sales_order(
    db: Session,
    tenant_id: int,
    sales_order_id: int,
    *,
    created_by: int | None,
) -> SalesOrder:
    so = get_sales_order(db, tenant_id, sales_order_id)
    if so.status in (SalesOrderStatus.completed, SalesOrderStatus.cancelled):
        raise SalesOrderError("not_confirmable", "当前销售订单状态不可下生产")
    if not so.lines:
        raise SalesOrderError("empty_lines", "无产品行，无法确认")

    for line in sorted(so.lines, key=lambda x: (x.sort_order, x.id)):
        if line.production_order_id:
            continue
        _create_production_for_line(db, tenant_id, so, line, created_by=created_by)

    _sync_sales_order_status(so)
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
        if line.production_order_id:
            skipped.append(
                {
                    "sales_order_id": so.id,
                    "line_id": line.id,
                    "order_no": so.order_no,
                    "reason": "已下生产，请查生产单齐套",
                    "production_order_id": line.production_order_id,
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
                "own_product_id": line.own_product_id,
                "total_qty": int(line.total_qty),
                "size_qtys": size_qtys,
                "delivery_date": line.delivery_date,
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
            "所选行均已下生产或无数量，无法模拟；已下生产请查生产单齐套",
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
    return result
