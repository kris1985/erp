"""AU-I1：规格执行单合单（可产色码 + 分配）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    ExecutionAllocation,
    ExecutionHeader,
    Order,
    OrderItem,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    ProcessDefinition,
    PartDefinition,
    FgLedger,
    SalesLineLaborAllocation,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    WorkLog,
    WorkLogStatus,
)
from app.services.material_service import MaterialError


class ExecutionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def generate_header_no(db: Session, tenant_id: int) -> str:
    """人见执行单号：XE-YYYYMMDD-####。"""
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"XE-{today}-"
    last = db.scalar(
        select(ExecutionHeader.header_no)
        .where(
            ExecutionHeader.tenant_id == tenant_id,
            ExecutionHeader.header_no.like(f"{prefix}%"),
        )
        .order_by(ExecutionHeader.id.desc())
        .limit(1)
    )
    seq = 1
    if last and last.startswith(prefix):
        # 头号无尺码后缀；旧独立码明细也可能占 XE- 前缀，取纯 #### 段
        try:
            tail = last[len(prefix) :]
            seq = int(tail.split("-")[0]) + 1
        except ValueError:
            seq = 1
    # 与码明细号空间错开：同时看 SpecExecutionOrder 里裸 XE-####（无后缀）
    last_xe = db.scalar(
        select(SpecExecutionOrder.execution_no)
        .where(
            SpecExecutionOrder.tenant_id == tenant_id,
            SpecExecutionOrder.execution_no.like(f"{prefix}%"),
        )
        .order_by(SpecExecutionOrder.id.desc())
        .limit(1)
    )
    if last_xe and last_xe.startswith(prefix):
        try:
            tail = last_xe[len(prefix) :]
            seq = max(seq, int(tail.split("-")[0]) + 1)
        except ValueError:
            pass
    return f"{prefix}{seq:04d}"


def generate_execution_no(db: Session, tenant_id: int) -> str:
    """兼容旧路径：独立码明细号（无头时）。有头时用 size_execution_no。"""
    return generate_header_no(db, tenant_id)


def size_execution_no(header_no: str, size_value: str | None, size_id: int) -> str:
    tag = (size_value or "").strip() or str(size_id)
    return f"{header_no}-{tag}"


def _ratios(qtys: list[int]) -> list[Decimal]:
    total = sum(qtys)
    if total <= 0:
        raise ExecutionError("empty_qty", "合单数量须为正")
    out: list[Decimal] = []
    acc = Decimal("0")
    for i, q in enumerate(qtys):
        if i == len(qtys) - 1:
            r = (Decimal("1") - acc).quantize(Decimal("0.00000001"))
        else:
            r = (Decimal(q) / Decimal(total)).quantize(Decimal("0.00000001"))
            acc += r
        out.append(r)
    return out


def list_producible(
    db: Session,
    *,
    tenant_id: int,
    own_product_id: int | None = None,
    kit_ready_only: bool = False,
) -> list[dict]:
    """按款色码聚合可产剩余（confirmed 销售、未取消行）。"""
    q = (
        select(SalesOrderLineItem, SalesOrderLine, SalesOrder, OwnProduct)
        .join(SalesOrderLine, SalesOrderLine.id == SalesOrderLineItem.sales_order_line_id)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .join(OwnProduct, OwnProduct.id == SalesOrderLine.own_product_id)
        .where(
            SalesOrderLineItem.tenant_id == tenant_id,
            SalesOrder.status == SalesOrderStatus.confirmed,
            SalesOrderLine.status != SalesOrderLineStatus.cancelled,
        )
    )
    if own_product_id is not None:
        q = q.where(SalesOrderLine.own_product_id == own_product_id)

    rows = db.execute(q).all()
    buckets: dict[tuple, dict] = {}
    for item, line, so, product in rows:
        remaining = int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0)
        if remaining <= 0:
            continue
        color_id = item.color_id if item.color_id is not None else line.color_id
        key = (line.own_product_id, color_id, item.size_id)
        bucket = buckets.get(key)
        if not bucket:
            color = db.get(Color, color_id) if color_id else None
            size = db.get(Size, item.size_id)
            bucket = {
                "own_product_id": line.own_product_id,
                "product_code": product.product_code,
                "product_image_url": product.image_url,
                "color_id": color_id,
                "color_name": color.name if color else None,
                "size_id": item.size_id,
                "size_value": size.size_value if size else None,
                "size_sort_order": int(size.sort_order or 0) if size else 0,
                "remaining_qty": 0,
                "sources": [],
                "kit_hint": "unknown",
            }
            buckets[key] = bucket
        bucket["remaining_qty"] += remaining
        bucket["sources"].append(
            {
                "sales_order_id": so.id,
                "sales_order_no": so.order_no,
                "sales_order_line_id": line.id,
                "sales_order_line_item_id": item.id,
                "customer_name": so.customer_name,
                "delivery_date": line.delivery_date.isoformat()
                if line.delivery_date
                else (so.ordered_at.isoformat() if so.ordered_at else None),
                "qty": int(item.qty or 0),
                "allocated_qty": int(getattr(item, "allocated_qty", 0) or 0),
                "remaining_qty": remaining,
            }
        )

    from app.services.material_service import estimate_sku_kit_hint

    out = []
    for bucket in buckets.values():
        bucket["kit_hint"] = estimate_sku_kit_hint(
            db,
            tenant_id,
            own_product_id=int(bucket["own_product_id"]),
            qty=int(bucket["remaining_qty"]),
            size_id=int(bucket["size_id"]) if bucket.get("size_id") else None,
            color_id=int(bucket["color_id"]) if bucket.get("color_id") else None,
        )
        if kit_ready_only and bucket["kit_hint"] != "ready":
            continue
        out.append(bucket)

    return sorted(
        out,
        key=lambda x: (x["product_code"] or "", x["color_name"] or "", x["size_value"] or ""),
    )


def create_execution(
    db: Session,
    *,
    tenant_id: int,
    items: list[dict],
    created_by: int | None = None,
    notes: str | None = None,
    delivery_date: date | None = None,
    commit: bool = True,
    header_id: int | None = None,
) -> SpecExecutionOrder:
    """合单/码明细：必须带分配；生成执行单头（若无）+ 码明细；K4-B 不再写桥接生产单。"""
    if not items:
        raise ExecutionError("empty_items", "合单须至少一条分配")

    resolved: list[tuple[SalesOrderLineItem, SalesOrderLine, SalesOrder, int]] = []
    for row in items:
        lid = int(row.get("sales_order_line_item_id") or row.get("line_item_id") or 0)
        qty = int(row.get("qty") or 0)
        if lid <= 0 or qty <= 0:
            raise ExecutionError("invalid_item", "分配行 line_item_id/qty 无效")
        item = db.get(SalesOrderLineItem, lid)
        if not item or item.tenant_id != tenant_id:
            raise ExecutionError("line_item_not_found", f"色码行不存在：{lid}")
        line = db.get(SalesOrderLine, item.sales_order_line_id)
        if not line or line.tenant_id != tenant_id:
            raise ExecutionError("line_not_found", f"销售行不存在：{item.sales_order_line_id}")
        so = db.get(SalesOrder, line.sales_order_id)
        if not so or so.tenant_id != tenant_id:
            raise ExecutionError("sales_order_not_found", "销售单不存在")
        if so.status != SalesOrderStatus.confirmed:
            raise ExecutionError("sales_not_confirmed", f"销售单未确认：{so.order_no}")
        remaining = int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0)
        if qty > remaining:
            raise ExecutionError(
                "over_remaining",
                f"色码行 {lid} 剩余可产 {remaining}，无法分配 {qty}",
            )
        resolved.append((item, line, so, qty))

    # 同规格
    first_item, first_line, _, _ = resolved[0]
    product_id = first_line.own_product_id
    color_id = first_item.color_id if first_item.color_id is not None else first_line.color_id
    size_id = first_item.size_id
    for item, line, _, _ in resolved[1:]:
        cid = item.color_id if item.color_id is not None else line.color_id
        if line.own_product_id != product_id or cid != color_id or item.size_id != size_id:
            raise ExecutionError("spec_mismatch", "合单须同款同色同码")

    product = db.get(OwnProduct, product_id)
    if not product or product.tenant_id != tenant_id or not product.is_active:
        raise ExecutionError("product_not_found", "产品不存在或未启用")

    qtys = [q for _, _, _, q in resolved]
    total = sum(qtys)
    ratios = _ratios(qtys)

    size = db.get(Size, size_id)
    header: ExecutionHeader | None = None
    appending = header_id is not None
    if header_id is not None:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise ExecutionError("header_not_found", "生产单不存在")
        if header.own_product_id != product_id:
            raise ExecutionError("header_product_mismatch", "码明细须与生产单同款")
        peers = list(header.size_lines or [])
        if not peers:
            peers = list(
                db.scalars(
                    select(SpecExecutionOrder).where(
                        SpecExecutionOrder.tenant_id == tenant_id,
                        SpecExecutionOrder.header_id == header.id,
                    )
                ).all()
            )
        if any(execution_is_started(db, sl) for sl in peers):
            raise ExecutionError("header_started", "已开裁禁止并入；请另开新单走排产")
        header_no = header.header_no
        if delivery_date and (header.delivery_date is None or delivery_date < header.delivery_date):
            header.delivery_date = delivery_date
    else:
        header_no = generate_header_no(db, tenant_id)
        header = ExecutionHeader(
            tenant_id=tenant_id,
            header_no=header_no,
            own_product_id=product_id,
            color_id=color_id,
            sales_order_id=resolved[0][2].id if len({r[2].id for r in resolved}) == 1 else None,
            sales_order_line_id=resolved[0][1].id if len({r[1].id for r in resolved}) == 1 else None,
            total_qty=total,
            completed_qty=0,
            status=SpecExecutionStatus.confirmed,
            delivery_date=delivery_date,
            notes=notes,
            created_by=created_by,
            shop_order_id=None,
        )
        db.add(header)
        db.flush()

    execution_no = size_execution_no(header_no, size.size_value if size else None, size_id)
    # 防撞：同头同码已存在则退回序号号
    exists = db.scalar(
        select(SpecExecutionOrder.id).where(
            SpecExecutionOrder.tenant_id == tenant_id,
            SpecExecutionOrder.execution_no == execution_no,
        )
    )
    if exists:
        execution_no = f"{generate_header_no(db, tenant_id)}-{size.size_value if size else size_id}"

    execution = SpecExecutionOrder(
        tenant_id=tenant_id,
        execution_no=execution_no,
        header_id=header.id,
        own_product_id=product_id,
        color_id=color_id,
        size_id=size_id,
        total_qty=total,
        completed_qty=0,
        status=SpecExecutionStatus.confirmed,
        delivery_date=delivery_date,
        notes=notes,
        created_by=created_by,
        shop_order_id=None,
    )
    db.add(execution)
    db.flush()

    for (item, line, so, qty), ratio in zip(resolved, ratios):
        db.add(
            ExecutionAllocation(
                tenant_id=tenant_id,
                execution_id=execution.id,
                sales_order_id=so.id,
                sales_order_line_id=line.id,
                sales_order_line_item_id=item.id,
                qty=qty,
                ratio=ratio,
                produced_qty_est=0,
            )
        )
        item.allocated_qty = int(getattr(item, "allocated_qty", 0) or 0) + qty

    stamped: set[int] = set()
    for _item, line, _so, _qty in resolved:
        if line.id in stamped:
            continue
        stamped.add(line.id)
        line.execution_header_id = header.id

    # K4-B：不再 create_order；同头多码追加时抬总量 + 工序计划量 + 刷新用料
    if appending:
        header.total_qty = int(header.total_qty or 0) + total

    from app.services.material_service import (
        ensure_header_processes,
        ensure_material_snapshot_for_header,
        refresh_from_bom_for_header,
    )

    try:
        ensure_header_processes(
            db, tenant_id=tenant_id, header=header, delivery_date=delivery_date
        )
        if appending:
            refresh_from_bom_for_header(db, tenant_id, header, keep_progress=True)
        else:
            ensure_material_snapshot_for_header(db, tenant_id, header)
    except MaterialError as e:
        raise ExecutionError(e.code, e.message) from e

    if commit:
        db.commit()
        db.refresh(execution)
    return execution


def _source_delivery(line: SalesOrderLine, so: SalesOrder) -> date | None:
    raw = line.delivery_date or so.ordered_at
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def create_style_header(
    db: Session,
    *,
    tenant_id: int,
    items: list[dict],
    created_by: int | None = None,
    notes: str | None = None,
    delivery_date: date | None = None,
    supplement: bool = False,
    max_delivery_gap_days: int | None = None,
    commit: bool = True,
) -> ExecutionHeader:
    """同款同色合单：不同尺码挂同一执行单头；同码多客户写分配。补码走新单不改已开工单。"""
    if not items:
        raise ExecutionError("empty_items", "须至少一条分配")

    resolved: list[tuple[SalesOrderLineItem, SalesOrderLine, SalesOrder, int]] = []
    for row in items:
        lid = int(row.get("sales_order_line_item_id") or row.get("line_item_id") or 0)
        qty = int(row.get("qty") or 0)
        if lid <= 0 or qty <= 0:
            raise ExecutionError("invalid_item", "分配行 line_item_id/qty 无效")
        item = db.get(SalesOrderLineItem, lid)
        if not item or item.tenant_id != tenant_id:
            raise ExecutionError("line_item_not_found", f"色码行不存在：{lid}")
        line = db.get(SalesOrderLine, item.sales_order_line_id)
        if not line or line.tenant_id != tenant_id:
            raise ExecutionError("line_not_found", f"销售行不存在：{item.sales_order_line_id}")
        so = db.get(SalesOrder, line.sales_order_id)
        if not so or so.tenant_id != tenant_id:
            raise ExecutionError("sales_order_not_found", "销售单不存在")
        if so.status != SalesOrderStatus.confirmed:
            raise ExecutionError("sales_not_confirmed", f"销售单未确认：{so.order_no}")
        remaining = int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0)
        if qty > remaining:
            raise ExecutionError(
                "over_remaining",
                f"色码行 {lid} 剩余可产 {remaining}，无法分配 {qty}",
            )
        resolved.append((item, line, so, qty))

    first_item, first_line, _, _ = resolved[0]
    product_id = first_line.own_product_id
    color_id = first_item.color_id if first_item.color_id is not None else first_line.color_id
    for item, line, _, _ in resolved[1:]:
        cid = item.color_id if item.color_id is not None else line.color_id
        if line.own_product_id != product_id or cid != color_id:
            raise ExecutionError("style_mismatch", "须同款同色；不同尺码可挂同一生产单")

    deliveries = [d for d in (_source_delivery(line, so) for _, line, so, _ in resolved) if d]
    if max_delivery_gap_days is not None and deliveries:
        span = (max(deliveries) - min(deliveries)).days
        if span > int(max_delivery_gap_days):
            raise ExecutionError(
                "delivery_window",
                f"交期相差 {span} 天，超过允许的 {int(max_delivery_gap_days)} 天",
            )

    note = (notes or "").strip() or None
    if supplement:
        note = note or "补码新单"
        if "补码" not in note:
            note = f"补码新单 · {note}"

    effective_delivery = delivery_date or (min(deliveries) if deliveries else None)

    by_size: dict[int, list[tuple[SalesOrderLineItem, SalesOrderLine, SalesOrder, int]]] = {}
    for row in resolved:
        by_size.setdefault(int(row[0].size_id), []).append(row)
    size_ids = list(by_size.keys())
    sizes = {
        s.id: s
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids or [0]))).all()
    }
    ordered_size_ids = sorted(
        size_ids,
        key=lambda sid: (int(getattr(sizes.get(sid), "sort_order", 0) or 0), sid),
    )

    header_id: int | None = None
    try:
        for sid in ordered_size_ids:
            payload = [
                {"sales_order_line_item_id": item.id, "qty": qty}
                for item, _line, _so, qty in by_size[sid]
            ]
            exe = create_execution(
                db,
                tenant_id=tenant_id,
                items=payload,
                created_by=created_by,
                notes=note,
                delivery_date=effective_delivery,
                commit=False,
                header_id=header_id,
            )
            header_id = exe.header_id
        if not header_id:
            raise ExecutionError("empty_items", "未生成生产单")
        header = get_execution_header(db, tenant_id, int(header_id))
        if commit:
            db.commit()
            db.refresh(header)
        return header
    except Exception:
        if commit:
            db.rollback()
        raise


def create_execution_from_sales_line(
    db: Session,
    *,
    tenant_id: int,
    sales_order: SalesOrder,
    line: SalesOrderLine,
    created_by: int | None = None,
    commit: bool = False,
) -> ExecutionHeader:
    """确认生产：一产品行 → 一执行单头 + 多码明细（遗留/测试用；日常请走排产确认）。"""
    if getattr(line, "execution_header_id", None) or line.production_order_id:
        raise ExecutionError("line_confirmed", "该产品行已下生产/已有生产单")
    items = [it for it in (line.items or []) if int(it.qty or 0) > 0]
    if not items:
        raise ExecutionError("empty_items", "产品行色码明细不能为空")

    product = db.get(OwnProduct, line.own_product_id)
    if not product or product.tenant_id != tenant_id or not product.is_active:
        raise ExecutionError("product_not_found", "产品不存在或未启用")

    header_no = generate_header_no(db, tenant_id)
    total_qty = sum(int(it.qty or 0) for it in items)
    header = ExecutionHeader(
        tenant_id=tenant_id,
        header_no=header_no,
        own_product_id=line.own_product_id,
        color_id=line.color_id,
        sales_order_id=sales_order.id,
        sales_order_line_id=line.id,
        total_qty=total_qty,
        completed_qty=0,
        status=SpecExecutionStatus.confirmed,
        delivery_date=line.delivery_date,
        notes=line.notes,
        created_by=created_by,
        shop_order_id=None,
    )
    db.add(header)
    db.flush()

    line.production_order_id = None
    line.execution_header_id = header.id
    line.status = SalesOrderLineStatus.in_production

    for it in items:
        size = db.get(Size, it.size_id)
        color_id = it.color_id if it.color_id is not None else line.color_id
        qty = int(it.qty)
        exe = SpecExecutionOrder(
            tenant_id=tenant_id,
            execution_no=size_execution_no(header_no, size.size_value if size else None, it.size_id),
            header_id=header.id,
            own_product_id=line.own_product_id,
            color_id=color_id,
            size_id=it.size_id,
            total_qty=qty,
            completed_qty=0,
            status=SpecExecutionStatus.confirmed,
            delivery_date=line.delivery_date,
            shop_order_id=None,
            notes=line.notes,
            created_by=created_by,
        )
        db.add(exe)
        db.flush()
        db.add(
            ExecutionAllocation(
                tenant_id=tenant_id,
                execution_id=exe.id,
                sales_order_id=sales_order.id,
                sales_order_line_id=line.id,
                sales_order_line_item_id=it.id,
                qty=qty,
                ratio=Decimal("1.00000000"),
                produced_qty_est=0,
            )
        )
        it.allocated_qty = int(getattr(it, "allocated_qty", 0) or 0) + qty

    db.flush()
    from app.services.material_service import (
        ensure_header_processes,
        ensure_material_snapshot_for_header,
    )

    try:
        ensure_header_processes(
            db, tenant_id=tenant_id, header=header, delivery_date=line.delivery_date
        )
        ensure_material_snapshot_for_header(db, tenant_id, header)
    except MaterialError as e:
        raise ExecutionError(e.code, e.message) from e

    if commit:
        db.commit()
        db.refresh(header)
    return header


HEADER_SORT_FIELDS = {
    "execution_no": ExecutionHeader.header_no,
    "product_code": "product_code",
    "progress": "progress",
    "delivery_date": ExecutionHeader.delivery_date,
    "created_at": ExecutionHeader.created_at,
    "is_rush": "is_rush",
}


def _nulls_last(column, *, asc: bool = True):
    """MySQL-compatible NULLS LAST."""
    return column.is_(None).asc(), column.asc() if asc else column.desc()


def _header_rush_exists():
    return (
        select(SpecExecutionOrder.id)
        .where(
            SpecExecutionOrder.header_id == ExecutionHeader.id,
            SpecExecutionOrder.is_rush.is_(True),
        )
        .exists()
    )


def get_execution_header(db: Session, tenant_id: int, header_id: int) -> ExecutionHeader:
    row = db.scalar(
        select(ExecutionHeader)
        .where(ExecutionHeader.id == header_id, ExecutionHeader.tenant_id == tenant_id)
        .options(selectinload(ExecutionHeader.size_lines).selectinload(SpecExecutionOrder.allocations))
    )
    if not row:
        raise ExecutionError("header_not_found", "生产单不存在")
    return row


def list_execution_headers(
    db: Session,
    *,
    tenant_id: int,
    status: str | None = None,
    q: str | None = None,
    is_rush: bool | None = None,
    delivery_from: date | None = None,
    delivery_to: date | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int = 50,
) -> list[ExecutionHeader]:
    stmt = select(ExecutionHeader).where(ExecutionHeader.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ExecutionHeader.status == status)
    if delivery_from is not None:
        stmt = stmt.where(ExecutionHeader.delivery_date >= delivery_from)
    if delivery_to is not None:
        stmt = stmt.where(ExecutionHeader.delivery_date <= delivery_to)
    rush_exists = _header_rush_exists()
    if is_rush is not None:
        stmt = stmt.where(rush_exists if is_rush else ~rush_exists)
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        product_match = (
            select(OwnProduct.id)
            .where(
                OwnProduct.id == ExecutionHeader.own_product_id,
                OwnProduct.product_code.ilike(like),
            )
            .exists()
        )
        header_so_match = (
            select(SalesOrder.id)
            .where(
                SalesOrder.id == ExecutionHeader.sales_order_id,
                or_(
                    SalesOrder.order_no.ilike(like),
                    SalesOrder.customer_name.ilike(like),
                ),
            )
            .exists()
        )
        alloc_so_match = (
            select(SpecExecutionOrder.id)
            .join(
                ExecutionAllocation,
                ExecutionAllocation.execution_id == SpecExecutionOrder.id,
            )
            .join(SalesOrder, SalesOrder.id == ExecutionAllocation.sales_order_id)
            .where(
                SpecExecutionOrder.header_id == ExecutionHeader.id,
                or_(
                    SalesOrder.order_no.ilike(like),
                    SalesOrder.customer_name.ilike(like),
                ),
            )
            .exists()
        )
        stmt = stmt.where(
            or_(
                ExecutionHeader.header_no.ilike(like),
                product_match,
                header_so_match,
                alloc_so_match,
            )
        )
    sb = (sort_by or "").strip()
    asc = (sort_order or "desc").strip().lower() == "asc"
    if sb and sb not in HEADER_SORT_FIELDS:
        raise ExecutionError("invalid_sort", f"不支持的排序字段：{sb}")
    if sb == "product_code":
        stmt = stmt.outerjoin(OwnProduct, ExecutionHeader.own_product_id == OwnProduct.id)

    rush_rank = case((rush_exists, 1), else_=0)
    order_clauses = []
    if sb != "is_rush":
        order_clauses.append(rush_rank.desc())
    if not sb:
        order_clauses.extend(_nulls_last(ExecutionHeader.delivery_date, asc=True))
    elif sb == "product_code":
        order_clauses.extend(_nulls_last(OwnProduct.product_code, asc=asc))
    elif sb == "is_rush":
        order_clauses.append(rush_rank.asc() if asc else rush_rank.desc())
    elif sb == "progress":
        progress_key = case(
            (
                ExecutionHeader.total_qty > 0,
                (ExecutionHeader.completed_qty * 10000) / ExecutionHeader.total_qty,
            ),
            else_=0,
        )
        order_clauses.append(progress_key.asc() if asc else progress_key.desc())
    elif sb in ("delivery_date", "created_at", "execution_no"):
        order_clauses.extend(_nulls_last(HEADER_SORT_FIELDS[sb], asc=asc))
    else:
        col = HEADER_SORT_FIELDS[sb]
        order_clauses.append(col.asc() if asc else col.desc())
    order_clauses.append(ExecutionHeader.id.desc())
    stmt = (
        stmt.options(selectinload(ExecutionHeader.size_lines))
        .order_by(*order_clauses)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def header_out(db: Session, header: ExecutionHeader, *, include_kit: bool = True) -> dict:
    return _headers_out_batch(db, [header], include_kit=include_kit)[header.id]


def _headers_out_batch(
    db: Session,
    headers: list[ExecutionHeader],
    *,
    include_kit: bool = False,
) -> dict[int, dict]:
    """批量序列化生产单头，一次查询所有关联数据，避免 N+1。"""
    if not headers:
        return {}
    tenant_id = headers[0].tenant_id
    header_ids = [h.id for h in headers]

    # 1. 关联基础表：款 / 颜色 / 销售单
    product_ids = {h.own_product_id for h in headers if h.own_product_id}
    color_ids = {h.color_id for h in headers if h.color_id}
    so_ids = {h.sales_order_id for h in headers if h.sales_order_id}
    products = {
        int(p.id): p
        for p in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(list(product_ids)))).all()
    } if product_ids else {}
    colors = {
        int(c.id): c
        for c in db.scalars(select(Color).where(Color.id.in_(list(color_ids)))).all()
    } if color_ids else {}
    sos = {
        int(s.id): s
        for s in db.scalars(select(SalesOrder).where(SalesOrder.id.in_(list(so_ids)))).all()
    } if so_ids else {}

    # 2. 码明细（含分配）+ 尺码 + 分配关联销售单
    size_lines = list(
        db.scalars(
            select(SpecExecutionOrder)
            .where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.header_id.in_(header_ids),
            )
            .order_by(SpecExecutionOrder.id)
        ).all()
    )
    sl_by_header: dict[int, list[SpecExecutionOrder]] = {}
    for sl in size_lines:
        sl_by_header.setdefault(int(sl.header_id or 0), []).append(sl)
    size_ids = {int(sl.size_id) for sl in size_lines if sl.size_id}
    sizes = {
        int(s.id): s
        for s in db.scalars(select(Size).where(Size.id.in_(list(size_ids)))).all()
    } if size_ids else {}

    sl_ids = [sl.id for sl in size_lines]
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id.in_(sl_ids))
            .order_by(ExecutionAllocation.id)
        ).all()
    ) if sl_ids else []
    alloc_by_exec: dict[int, list[ExecutionAllocation]] = {}
    for a in allocs:
        alloc_by_exec.setdefault(int(a.execution_id), []).append(a)
    alloc_so_ids = {int(a.sales_order_id) for a in allocs if a.sales_order_id}
    alloc_sos = {
        int(s.id): s
        for s in db.scalars(
            select(SalesOrder).where(SalesOrder.id.in_(list(alloc_so_ids)))
        ).all()
    } if alloc_so_ids else {}

    # 3. 聚合：计件产量 + 出库
    produced_by_exec: dict[int, int] = {}
    shipped_by_exec: dict[int, int] = {}
    if sl_ids:
        produced_rows = db.execute(
            select(
                SalesLineLaborAllocation.execution_id,
                func.coalesce(func.sum(SalesLineLaborAllocation.qty_share), 0),
            )
            .where(
                SalesLineLaborAllocation.tenant_id == tenant_id,
                SalesLineLaborAllocation.execution_id.in_(sl_ids),
            )
            .group_by(SalesLineLaborAllocation.execution_id)
        ).all()
        produced_by_exec = {int(eid): int(qty or 0) for eid, qty in produced_rows}
        shipped_rows = db.execute(
            select(
                FgLedger.execution_id,
                func.coalesce(func.sum(FgLedger.qty), 0),
            )
            .where(
                FgLedger.tenant_id == tenant_id,
                FgLedger.execution_id.in_(sl_ids),
                FgLedger.direction == "out",
            )
            .group_by(FgLedger.execution_id)
        ).all()
        shipped_by_exec = {int(eid): int(qty or 0) for eid, qty in shipped_rows}

    # 4. 工序进度（批量）
    proc_progress = _headers_process_progress_batch(db, headers)

    out: dict[int, dict] = {}
    for h in headers:
        product = products.get(int(h.own_product_id)) if h.own_product_id else None
        color = colors.get(int(h.color_id)) if h.color_id else None
        so = sos.get(int(h.sales_order_id)) if h.sales_order_id else None
        h_sl = sl_by_header.get(h.id, [])
        size_out = []
        alloc_out: list[dict] = []
        for exe in h_sl:
            size = sizes.get(int(exe.size_id)) if exe.size_id else None
            size_out.append(
                {
                    "id": exe.id,
                    "execution_no": exe.execution_no,
                    "size_id": exe.size_id,
                    "size_value": size.size_value if size else None,
                    "total_qty": exe.total_qty,
                    "completed_qty": exe.completed_qty,
                    "status": exe.status.value
                    if hasattr(exe.status, "value")
                    else str(exe.status),
                    "is_rush": bool(getattr(exe, "is_rush", False)),
                }
            )
            for a in alloc_by_exec.get(int(exe.id), []):
                so_a = alloc_sos.get(int(a.sales_order_id)) if a.sales_order_id else None
                alloc_out.append(
                    {
                        "id": a.id,
                        "execution_id": exe.id,
                        "size_value": size.size_value if size else None,
                        "sales_order_id": a.sales_order_id,
                        "sales_order_no": so_a.order_no if so_a else None,
                        "customer_name": so_a.customer_name if so_a else None,
                        "sales_order_line_id": a.sales_order_line_id,
                        "sales_order_line_item_id": a.sales_order_line_item_id,
                        "qty": a.qty,
                        "ratio": float(a.ratio),
                        "produced_qty_est": a.produced_qty_est,
                    }
                )
        execution_ids = [int(exe.id) for exe in h_sl if exe.id]
        scheduled_qty = sum(int(exe.total_qty or 0) for exe in h_sl)
        estimated_done_qty = sum(int(exe.completed_qty or 0) for exe in h_sl)
        produced_qty = sum(produced_by_exec.get(eid, 0) for eid in execution_ids)
        shipped_qty = sum(shipped_by_exec.get(eid, 0) for eid in execution_ids)
        wip_qty = max(0, estimated_done_qty - produced_qty)
        customers: list[str] = []
        sales_order_nos: list[str] = []
        seen_c: set[str] = set()
        seen_s: set[str] = set()
        for a in alloc_out:
            cn = a.get("customer_name")
            sn = a.get("sales_order_no")
            if cn and cn not in seen_c:
                seen_c.add(cn)
                customers.append(str(cn))
            if sn and sn not in seen_s:
                seen_s.add(sn)
                sales_order_nos.append(str(sn))
        if so:
            if so.customer_name and so.customer_name not in seen_c:
                customers.insert(0, so.customer_name)
            if so.order_no and so.order_no not in seen_s:
                sales_order_nos.insert(0, so.order_no)
        kit = None
        if include_kit:
            try:
                from app.services.material_service import MaterialError, get_header_kit

                raw = get_header_kit(db, tenant_id, h.id)
                kit = {
                    "kit_ok": bool(raw.get("kit_ok")),
                    "shortage_lines": raw.get("shortage_lines"),
                    "empty_bom": bool(raw.get("empty_bom")),
                    "first_kit_ok": bool(raw.get("first_kit_ok")),
                    "header_id": raw.get("header_id"),
                    "header_no": raw.get("header_no"),
                    "shop_order_id": raw.get("shop_order_id"),
                }
            except MaterialError:
                kit = None
        out[h.id] = {
            "id": h.id,
            "header_no": h.header_no,
            "execution_no": h.header_no,
            "own_product_id": h.own_product_id,
            "product_code": product.product_code if product else None,
            "product_image_url": product.image_url if product else None,
            "trace_enabled": bool(product.trace_enabled) if product else False,
            "color_id": h.color_id,
            "color_name": color.name if color else None,
            "sales_order_id": h.sales_order_id,
            "sales_order_no": so.order_no if so else None,
            "customers": customers,
            "sales_order_nos": sales_order_nos,
            "sales_order_line_id": h.sales_order_line_id,
            "total_qty": h.total_qty,
            "completed_qty": h.completed_qty,
            "scheduled_qty": scheduled_qty,
            "wip_qty": wip_qty,
            "produced_qty": produced_qty,
            "shipped_qty": shipped_qty,
            "progress_kind": {"wip": "estimated", "produced": "exact", "shipped": "exact"},
            "status": h.status.value if hasattr(h.status, "value") else str(h.status),
            "delivery_date": h.delivery_date.isoformat() if h.delivery_date else None,
            "shop_order_id": h.shop_order_id,
            "notes": h.notes,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "kit": kit,
            "size_lines": size_out,
            "size_summary": "、".join(
                f"{s['size_value'] or s['size_id']}×{s['total_qty']}" for s in size_out
            )
            or "—",
            "allocations": alloc_out,
            "process_progress": proc_progress.get(h.id, []),
        }
    return out



def _header_process_progress(db: Session, header: ExecutionHeader) -> list[dict]:
    """生产单列表用：按工序的完成双数（复用详情工序进度查询，含壳回退）。"""
    procs = header_processes_out(db, header)["items"]
    return [
        {
            "process_id": p["process_id"],
            "process_name": p["process_name"],
            "label": p["label"],
            "plan_qty": p["plan_qty"],
            "completed_qty": p["completed_qty"],
            "status": p["status"],
            "is_current": p["is_current"],
            "is_done": p["is_done"],
        }
        for p in procs
    ]


def _headers_process_progress_batch(
    db: Session, headers: list[ExecutionHeader]
) -> dict[int, list[dict]]:
    """批量查多个生产单的工序进度：header_id -> [工序...]，含壳回退。"""
    if not headers:
        return {}
    tenant_id = headers[0].tenant_id
    header_ids = [h.id for h in headers]
    shop_order_ids = {int(h.shop_order_id) for h in headers if h.shop_order_id}
    procs_by_header: dict[int, list[OrderProcess]] = {}
    if header_ids:
        for op in db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.header_id.in_(header_ids),
            )
            .order_by(OrderProcess.id)
        ).all():
            procs_by_header.setdefault(int(op.header_id or 0), []).append(op)
    # 壳回退：header 下无工序但挂生产单（shop_order_id）时查生产单工序
    fallback_ids = [
        int(h.shop_order_id)
        for h in headers
        if h.shop_order_id and not procs_by_header.get(h.id)
    ]
    fallback_procs: dict[int, list[OrderProcess]] = {}
    if fallback_ids:
        for op in db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.order_id.in_(fallback_ids),
            )
            .order_by(OrderProcess.id)
        ).all():
            fallback_procs.setdefault(int(op.order_id or 0), []).append(op)
        for h in headers:
            if h.shop_order_id and not procs_by_header.get(h.id):
                procs_by_header[h.id] = fallback_procs.get(int(h.shop_order_id), [])
    part_ids = {int(p.part_id) for procs in procs_by_header.values() for p in procs if p.part_id}
    parts: dict[int, PartDefinition] = {}
    if part_ids:
        parts = {
            int(x.id): x
            for x in db.scalars(
                select(PartDefinition).where(PartDefinition.id.in_(list(part_ids)))
            ).all()
        }
    out: dict[int, list[dict]] = {}
    for h in headers:
        procs = procs_by_header[h.id]
        current_id = None
        for proc in procs:
            if not _process_is_done(proc):
                current_id = proc.id
                break
        all_done = bool(procs) and current_id is None
        items = []
        for proc in procs:
            part = parts.get(int(proc.part_id)) if proc.part_id else None
            part_name = part.name if part else None
            is_current = (not all_done) and proc.id == current_id
            items.append(
                {
                    "process_id": proc.process_id,
                    "process_name": proc.process_name,
                    "label": _process_label(proc.process_name, part_name),
                    "plan_qty": int(proc.plan_qty or 0),
                    "completed_qty": int(proc.completed_qty or 0),
                    "status": proc.status.value
                    if hasattr(proc.status, "value")
                    else str(proc.status),
                    "is_current": is_current,
                    "is_done": _process_is_done(proc),
                }
            )
        out[h.id] = items
    return out


def _process_is_done(proc: OrderProcess) -> bool:
    status = proc.status.value if hasattr(proc.status, "value") else str(proc.status or "")
    if status == "completed":
        return True
    plan = int(proc.plan_qty or 0)
    done = int(proc.completed_qty or 0)
    return plan > 0 and done >= plan


def _process_label(process_name: str, part_name: str | None) -> str:
    if part_name:
        return f"{part_name}·{process_name}"
    return process_name


def header_processes_out(db: Session, header: ExecutionHeader) -> dict:
    """执行单工序进度：当前道=路线上第一个未完成；全完成则 all_done。"""
    from app.services.material_service import list_header_processes

    procs = list_header_processes(db, header.tenant_id, header.id)
    if not procs and header.shop_order_id:
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(
                    OrderProcess.tenant_id == header.tenant_id,
                    OrderProcess.order_id == int(header.shop_order_id),
                )
                .order_by(OrderProcess.id)
            ).all()
        )
    part_ids = {int(p.part_id) for p in procs if p.part_id}
    parts: dict[int, PartDefinition] = {}
    if part_ids:
        parts = {
            int(x.id): x
            for x in db.scalars(select(PartDefinition).where(PartDefinition.id.in_(list(part_ids)))).all()
        }
    # 工艺定额（派工出入估算用）
    pid_set = {int(p.process_id) for p in procs if p.process_id}
    proc_defs: dict[int, ProcessDefinition] = {}
    if pid_set:
        proc_defs = {
            int(x.id): x
            for x in db.scalars(select(ProcessDefinition).where(ProcessDefinition.id.in_(list(pid_set)))).all()
        }
    # 派工：工序 → 工人名（执行单工序表"派工"列）
    proc_ids = [int(p.id) for p in procs if p.id]
    assign_names: dict[int, list[str]] = {}
    if proc_ids:
        from app.models import OrderProcessAssignment

        rows = db.execute(
            select(OrderProcessAssignment.worker_id, OrderProcessAssignment.order_process_id)
            .where(OrderProcessAssignment.order_process_id.in_(proc_ids))
        ).all()
        wid_set = {int(r[0]) for r in rows if r[0]}
        wname = {}
        if wid_set:
            wname = {
                int(w.id): w.name
                for w in db.scalars(select(Employee).where(Employee.id.in_(list(wid_set)))).all()
            }
        for r in rows:
            assign_names.setdefault(int(r[1]), []).append(wname.get(int(r[0]), str(r[0])))
    current_id = None
    for proc in procs:
        if not _process_is_done(proc):
            current_id = proc.id
            break
    all_done = bool(procs) and current_id is None
    items = []
    for proc in procs:
        part = parts.get(int(proc.part_id)) if proc.part_id else None
        part_name = part.name if part else None
        items.append(
            {
                "id": proc.id,
                "order_process_id": proc.id,
                "process_id": proc.process_id,
                "process_name": proc.process_name,
                "part_id": proc.part_id,
                "part_name": part_name,
                "label": _process_label(proc.process_name, part_name),
                "status": proc.status.value if hasattr(proc.status, "value") else str(proc.status),
                "plan_qty": int(proc.plan_qty or 0),
                "completed_qty": int(proc.completed_qty or 0),
                "rework_qty": int(proc.rework_qty or 0),
                "assignee_names": assign_names.get(int(proc.id), []),
                "per_worker_capacity": (
                    proc_defs[int(proc.process_id)].per_worker_capacity
                    if proc.process_id and int(proc.process_id) in proc_defs
                    else None
                ),
                "standard_workers": (
                    proc_defs[int(proc.process_id)].standard_workers
                    if proc.process_id and int(proc.process_id) in proc_defs
                    else None
                ),
                "start_date": proc.start_date.isoformat() if proc.start_date else None,
                "end_date": proc.end_date.isoformat() if proc.end_date else None,
                "is_current": (not all_done) and proc.id == current_id,
                "is_done": _process_is_done(proc),
            }
        )
    current = next((x for x in items if x["is_current"]), None)
    return {
        "items": items,
        "all_done": all_done,
        "current_process_id": current_id,
        "current_process_name": current["label"] if current else None,
    }


def _enforce_cut_first_kit(
    db: Session,
    tenant_id: int,
    header: ExecutionHeader,
    *,
    dry_run: bool,
    skip_kit_reason: str | None,
) -> dict | None:
    """开裁：有首道用料且不齐套时，未写原因不得开。空 BOM 不挡测试/无料单。"""
    from app.services.material_service import MaterialError, get_header_kit

    try:
        kit = get_header_kit(db, tenant_id, header.id)
    except MaterialError:
        kit = {"first_kit_ok": True, "empty_bom": True}
    if dry_run:
        return kit
    if kit.get("first_kit_ok") or kit.get("empty_bom"):
        return kit
    reason = (skip_kit_reason or "").strip()
    if len(reason) < 2:
        raise ExecutionError(
            "first_kit_blocked",
            "首道不齐套不能开裁。厂里偶尔会先裁已到的料，请填写原因后再开。",
        )
    extra = f"开裁缺料原因：{reason}"
    header.notes = f"{header.notes}\n{extra}".strip() if header.notes else extra
    db.flush()
    return kit


def cut_cards_for_header(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    mode: str | None = None,
    commit: bool = True,
    skip_kit_reason: str | None = None,
) -> dict:
    """执行单开裁：认 header 色码明细；桥接壳可选。"""
    from app.services.trace_service import TraceError, preview_or_create_cut_cards

    header = get_execution_header(db, tenant_id, header_id)
    if header.status == SpecExecutionStatus.cancelled:
        raise ExecutionError("header_cancelled", "生产单已取消，不能开裁")
    kit = _enforce_cut_first_kit(
        db, tenant_id, header, dry_run=dry_run, skip_kit_reason=skip_kit_reason
    )
    try:
        data = preview_or_create_cut_cards(
            db,
            tenant_id=tenant_id,
            header_id=header.id,
            order_id=header.shop_order_id,
            dry_run=dry_run,
            bundle_size=bundle_size,
            only_missing=only_missing,
            mode=mode or "basket_bundles",
            execution_id=None,
            commit=commit,
        )
    except TraceError as e:
        raise ExecutionError(e.code, e.message) from e
    data["header_id"] = header.id
    data["header_no"] = header.header_no
    data["execution_no"] = header.header_no
    if kit:
        data["first_kit_ok"] = bool(kit.get("first_kit_ok"))
        data["empty_bom"] = bool(kit.get("empty_bom"))
        data["first_process_name"] = kit.get("first_process_name")
    return data


def get_execution(db: Session, tenant_id: int, execution_id: int) -> SpecExecutionOrder:
    row = db.scalar(
        select(SpecExecutionOrder)
        .where(
            SpecExecutionOrder.id == execution_id,
            SpecExecutionOrder.tenant_id == tenant_id,
        )
        .options(selectinload(SpecExecutionOrder.allocations))
    )
    if not row:
        raise ExecutionError("not_found", "生产单不存在")
    return row


def list_executions(
    db: Session,
    *,
    tenant_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[SpecExecutionOrder]:
    q = select(SpecExecutionOrder).where(SpecExecutionOrder.tenant_id == tenant_id)
    if status:
        q = q.where(SpecExecutionOrder.status == status)
    q = q.order_by(SpecExecutionOrder.id.desc()).limit(limit)
    return list(db.scalars(q).all())


def allocation_sources_for_execution(db: Session, execution_id: int) -> list[dict]:
    """筐打印用：销售来源清单（SO-A 30 / SO-B 20）。"""
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution_id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    out: list[dict] = []
    for a in allocs:
        so = db.get(SalesOrder, a.sales_order_id)
        out.append(
            {
                "sales_order_id": a.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "customer_name": so.customer_name if so else None,
                "qty": int(a.qty),
                "ratio": float(a.ratio),
                "label": f"{so.order_no if so else a.sales_order_id} {int(a.qty)}",
            }
        )
    return out


def cut_cards_for_execution(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    mode: str | None = None,
    commit: bool = True,
    skip_kit_reason: str | None = None,
) -> dict:
    """执行单开裁：有桥接壳走生产单；无壳认 header（K4-C）。"""
    from app.services.trace_service import TraceError, preview_or_create_cut_cards

    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        raise ExecutionError("execution_cancelled", "生产单已取消，不能开裁")
    if not execution.shop_order_id and not execution.header_id:
        raise ExecutionError("no_shop_order", "无桥接单且无生产单头，不能开裁")
    kit = None
    if execution.header_id:
        header = get_execution_header(db, tenant_id, int(execution.header_id))
        kit = _enforce_cut_first_kit(
            db, tenant_id, header, dry_run=dry_run, skip_kit_reason=skip_kit_reason
        )
    try:
        if execution.shop_order_id:
            data = preview_or_create_cut_cards(
                db,
                tenant_id=tenant_id,
                order_id=int(execution.shop_order_id),
                dry_run=dry_run,
                bundle_size=bundle_size,
                only_missing=only_missing,
                mode=mode or "basket_bundles",
                execution_id=execution.id,
                commit=commit,
            )
        else:
            data = preview_or_create_cut_cards(
                db,
                tenant_id=tenant_id,
                header_id=int(execution.header_id),
                order_id=None,
                dry_run=dry_run,
                bundle_size=bundle_size,
                only_missing=only_missing,
                mode=mode or "basket_bundles",
                execution_id=execution.id,
                commit=commit,
            )
    except TraceError as e:
        raise ExecutionError(e.code, e.message) from e
    data["execution_id"] = execution.id
    data["execution_no"] = execution.execution_no
    if not data.get("allocation_sources"):
        data["allocation_sources"] = allocation_sources_for_execution(db, execution.id)
    if kit:
        data["first_kit_ok"] = bool(kit.get("first_kit_ok"))
        data["empty_bom"] = bool(kit.get("empty_bom"))
        data["first_process_name"] = kit.get("first_process_name")
    return data


def list_header_trace_units(db: Session, tenant_id: int, header_id: int) -> dict:
    """派工/打印：按执行单头列追溯单元（与订单 trace-units 同形）。"""
    from app.models import PartDefinition, TraceUnit

    header = get_execution_header(db, tenant_id, header_id)
    units = list(
        db.scalars(
            select(TraceUnit)
            .where(TraceUnit.tenant_id == tenant_id, TraceUnit.header_id == header.id)
            .order_by(TraceUnit.id.desc())
        ).all()
    )
    part_ids = {u.part_id for u in units if u.part_id}
    part_map = {
        p.id: p
        for p in db.scalars(select(PartDefinition).where(PartDefinition.id.in_(part_ids or [0]))).all()
    }
    code_by_id = {u.id: u.code for u in units}
    exe_ids = {int(u.execution_id) for u in units if getattr(u, "execution_id", None)}
    alloc_by_exe: dict[int, list] = {
        eid: allocation_sources_for_execution(db, eid) for eid in exe_ids
    }
    exe_no_by_id = {
        e.id: e.execution_no
        for e in db.scalars(
            select(SpecExecutionOrder).where(SpecExecutionOrder.id.in_(exe_ids or [0]))
        ).all()
    }
    items = []
    for u in units:
        color = db.get(Color, u.color_id) if u.color_id else None
        size = db.get(Size, u.size_id) if u.size_id else None
        part = part_map.get(u.part_id) if u.part_id else None
        ut = u.unit_type.value if hasattr(u.unit_type, "value") else str(u.unit_type)
        eid = getattr(u, "execution_id", None)
        items.append(
            {
                "id": u.id,
                "code": u.code,
                "qty": u.qty,
                "unit_type": ut,
                "parent_id": u.parent_id,
                "parent_code": code_by_id.get(u.parent_id) if u.parent_id else None,
                "part_id": u.part_id,
                "part_name": part.name if part else None,
                "part_code": part.code if part else None,
                "color_id": u.color_id,
                "color_name": color.name if color else None,
                "size_id": u.size_id,
                "size_value": size.size_value if size else None,
                "status": u.status.value if hasattr(u.status, "value") else str(u.status),
                "received_at": u.received_at.isoformat() if getattr(u, "received_at", None) else None,
                "execution_id": eid,
                "execution_no": exe_no_by_id.get(int(eid)) if eid else None,
                "header_id": header.id,
                "header_no": header.header_no,
                "allocation_sources": alloc_by_exe.get(int(eid), []) if eid else [],
            }
        )
    return {"items": items}


def _progress_basis_qty(db: Session, order: Order) -> tuple[int, str | None]:
    """在制预估基数：优先末道整款工序 completed_qty（无则全体工序末道）。"""
    procs = list(order.processes or [])
    if not procs:
        procs = list(
            db.scalars(select(OrderProcess).where(OrderProcess.order_id == order.id)).all()
        )
    if not procs:
        return 0, None
    style = [p for p in procs if getattr(p, "part_id", None) is None]
    pool = style or procs

    def _key(p: OrderProcess) -> tuple[int, int]:
        pd = db.get(ProcessDefinition, p.process_id)
        return (int(pd.sort_order) if pd else 0, int(p.id))

    last = max(pool, key=_key)
    return int(last.completed_qty or 0), last.process_name


def _progress_basis_qty_for_header(db: Session, tenant_id: int, header_id: int) -> tuple[int, str | None]:
    """无桥接壳：末道工序完成量取自 header 挂的 OrderProcess。"""
    from app.services.material_service import list_header_processes

    procs = list_header_processes(db, tenant_id, header_id)
    if not procs:
        return 0, None
    style = [p for p in procs if getattr(p, "part_id", None) is None]
    pool = style or procs

    def _key(p: OrderProcess) -> tuple[int, int]:
        pd = db.get(ProcessDefinition, p.process_id)
        return (int(pd.sort_order) if pd else 0, int(p.id))

    last = max(pool, key=_key)
    return int(last.completed_qty or 0), last.process_name


def split_produced_by_ratio(completed: int, ratios: list[Decimal]) -> list[int]:
    """按 ratio 分摊；末行吃余数，保证合计=completed。"""
    if completed < 0:
        raise ExecutionError("invalid_progress", "产量不能为负")
    if not ratios:
        return []
    out: list[int] = []
    acc = 0
    for i, r in enumerate(ratios):
        if i == len(ratios) - 1:
            out.append(completed - acc)
        else:
            q = int((Decimal(completed) * Decimal(r)).to_integral_value(rounding=ROUND_DOWN))
            if q < 0:
                q = 0
            out.append(q)
            acc += q
    return out


def refresh_execution_header_progress(
    db: Session,
    *,
    tenant_id: int,
    header_id: int | None,
) -> ExecutionHeader | None:
    """码明细完工回写后，汇总执行单头 completed_qty / status。"""
    if not header_id:
        return None
    header = db.get(ExecutionHeader, int(header_id))
    if not header or header.tenant_id != tenant_id:
        return None
    if header.status == SpecExecutionStatus.cancelled:
        return header

    lines = list(
        db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.header_id == header.id,
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
            )
        ).all()
    )
    if not lines:
        return header

    completed = sum(int(x.completed_qty or 0) for x in lines)
    total = sum(int(x.total_qty or 0) for x in lines)
    header.completed_qty = completed
    # 头总量以明细合计为准（防止头表滞后）
    if total > 0:
        header.total_qty = total

    line_states = {
        (x.status.value if hasattr(x.status, "value") else str(x.status)) for x in lines
    }
    if completed >= total > 0:
        header.status = SpecExecutionStatus.completed
    elif (
        completed > 0
        or SpecExecutionStatus.in_progress.value in line_states
        or SpecExecutionStatus.completed.value in line_states
    ):
        header.status = SpecExecutionStatus.in_progress
    elif SpecExecutionStatus.cut.value in line_states:
        header.status = SpecExecutionStatus.cut
    elif header.status == SpecExecutionStatus.completed:
        header.status = SpecExecutionStatus.confirmed
    return header


def refresh_execution_progress(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
) -> SpecExecutionOrder:
    """按末道工序回写执行进度，并 ratio 预估销售产量（勾平）。无桥接壳时认 header 工序。"""
    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        return execution

    if execution.shop_order_id:
        order = db.get(Order, execution.shop_order_id)
        if not order or order.tenant_id != tenant_id:
            return execution
        raw, _basis_name = _progress_basis_qty(db, order)
    elif execution.header_id:
        raw, _basis_name = _progress_basis_qty_for_header(
            db, tenant_id, int(execution.header_id)
        )
    else:
        return execution

    completed = min(raw, int(execution.total_qty or 0))
    execution.completed_qty = completed

    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    qtys = split_produced_by_ratio(completed, [Decimal(a.ratio) for a in allocs])
    for a, q in zip(allocs, qtys):
        a.produced_qty_est = q

    has_log = False
    if execution.header_id:
        has_log = (
            db.scalar(
                select(WorkLog.id).where(
                    WorkLog.tenant_id == tenant_id,
                    WorkLog.header_id == int(execution.header_id),
                    WorkLog.status == WorkLogStatus.valid,
                ).limit(1)
            )
            is not None
        )
    if completed >= int(execution.total_qty or 0) > 0:
        execution.status = SpecExecutionStatus.completed
    elif completed > 0 or has_log:
        execution.status = SpecExecutionStatus.in_progress
    elif execution.status == SpecExecutionStatus.completed:
        # 作废回滚后产量下降：退出 completed
        execution.status = SpecExecutionStatus.in_progress
    refresh_execution_header_progress(
        db, tenant_id=tenant_id, header_id=getattr(execution, "header_id", None)
    )
    return execution


def refresh_execution_progress_for_order(
    db: Session,
    *,
    tenant_id: int,
    order_id: int | None = None,
    execution_id: int | None = None,
    header_id: int | None = None,
    size_id: int | None = None,
) -> SpecExecutionOrder | None:
    """报工/作废后：按 order / header / 显式 execution_id 刷新进度。"""
    eid = execution_id
    if eid is None and header_id:
        q = (
            select(SpecExecutionOrder)
            .where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.header_id == int(header_id),
                SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
            )
            .order_by(SpecExecutionOrder.id.desc())
        )
        if size_id:
            q = q.where(SpecExecutionOrder.size_id == int(size_id))
        row = db.scalar(q.limit(1))
        if not row:
            return None
        eid = row.id
    elif eid is None and order_id:
        row = db.scalar(
            select(SpecExecutionOrder)
            .where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.shop_order_id == order_id,
                SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
            )
            .order_by(SpecExecutionOrder.id.desc())
            .limit(1)
        )
        if not row:
            return None
        eid = row.id
    if eid is None:
        return None
    return refresh_execution_progress(db, tenant_id=tenant_id, execution_id=int(eid))


def execution_is_started(db: Session, execution: SpecExecutionOrder) -> bool:
    """已开工：状态在制/完成、有完成量、或已开裁挂筐。"""
    st = execution.status.value if hasattr(execution.status, "value") else str(execution.status)
    if st in (
        SpecExecutionStatus.cut.value,
        SpecExecutionStatus.in_progress.value,
        SpecExecutionStatus.completed.value,
    ):
        return True
    if int(execution.completed_qty or 0) > 0:
        return True
    unit_id = db.scalar(
        select(TraceUnit.id).where(TraceUnit.execution_id == execution.id).limit(1)
    )
    return unit_id is not None


def _sync_bridge_shop_qty(
    db: Session,
    *,
    tenant_id: int,
    execution: SpecExecutionOrder,
    total_qty: int,
    user_id: int | None = None,
) -> None:
    """未开工改量：同步桥接生产单数量与材料需求。"""
    if not execution.shop_order_id:
        return
    shop = db.get(Order, execution.shop_order_id)
    if not shop or shop.tenant_id != tenant_id:
        return
    shop.total_qty = int(total_qty)
    items = list(shop.items or [])
    if not items:
        items = list(
            db.scalars(select(OrderItem).where(OrderItem.order_id == shop.id)).all()
        )
    matched = False
    for it in items:
        if int(it.size_id or 0) == int(execution.size_id or 0) and (
            it.color_id is None or int(it.color_id) == int(execution.color_id or 0)
        ):
            it.qty = int(total_qty)
            matched = True
            break
    if not matched and items:
        items[0].qty = int(total_qty)
    from app.services.material_service import sync_requirements_after_qty_change

    sync_requirements_after_qty_change(db, tenant_id, shop, user_id=user_id)


def change_execution_qty(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    items: list[dict],
    notes: str | None = None,
    dry_run: bool = False,
    commit: bool = True,
    user_id: int | None = None,
) -> dict:
    """未开工执行单改量：替换分配 qty、重算 ratio、回写 allocated 与桥接单。

    已开工一律拒绝（减产/停产 → I3-M4；补码 → create_supplement_execution）。
    """
    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        raise ExecutionError("execution_cancelled", "生产单已取消，不能改量")
    if execution_is_started(db, execution):
        raise ExecutionError(
            "started_block",
            "已开工不可改量；减产/停产走回滚；客户补码请新建生产单",
        )
    if not items:
        raise ExecutionError("empty_items", "改量须至少一条分配")

    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    if not allocs:
        raise ExecutionError("no_allocations", "生产单无分配行")

    by_item = {int(a.sales_order_line_item_id): a for a in allocs}
    resolved: list[tuple[ExecutionAllocation, SalesOrderLineItem, int]] = []
    seen: set[int] = set()
    for row in items:
        lid = int(row.get("sales_order_line_item_id") or row.get("line_item_id") or 0)
        qty = int(row.get("qty") or 0)
        if lid <= 0 or qty <= 0:
            raise ExecutionError("invalid_item", "分配行 line_item_id/qty 无效")
        if lid in seen:
            raise ExecutionError("duplicate_item", f"重复分配行：{lid}")
        seen.add(lid)
        alloc = by_item.get(lid)
        if not alloc:
            raise ExecutionError(
                "alloc_not_found",
                f"分配行不在本生产单：{lid}（改量不可换来源；补码请开新单）",
            )
        item = db.get(SalesOrderLineItem, lid)
        if not item or item.tenant_id != tenant_id:
            raise ExecutionError("line_item_not_found", f"色码行不存在：{lid}")
        # 先释放本执行单占用再校验剩余
        freed = int(alloc.qty)
        remaining = int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0) + freed
        if qty > remaining:
            raise ExecutionError(
                "over_remaining",
                f"色码行 {lid} 可改至上限 {remaining}，无法设为 {qty}",
            )
        resolved.append((alloc, item, qty))

    if set(by_item) != seen:
        missing = sorted(set(by_item) - seen)
        raise ExecutionError(
            "incomplete_items",
            f"须提交全部现有分配行（缺少 {missing}）；删来源请取消重排",
        )

    old_total = int(execution.total_qty or 0)
    new_qtys = [q for _, _, q in resolved]
    new_total = sum(new_qtys)
    new_ratios = _ratios(new_qtys)
    preview = {
        "execution_id": execution.id,
        "execution_no": execution.execution_no,
        "old_total_qty": old_total,
        "new_total_qty": new_total,
        "started": False,
        "items": [
            {
                "sales_order_line_item_id": int(alloc.sales_order_line_item_id),
                "old_qty": int(alloc.qty),
                "new_qty": qty,
                "old_ratio": float(alloc.ratio),
                "new_ratio": float(ratio),
            }
            for (alloc, _, qty), ratio in zip(resolved, new_ratios)
        ],
    }
    if dry_run:
        return {"dry_run": True, **preview}

    for (alloc, item, qty), ratio in zip(resolved, new_ratios):
        delta = qty - int(alloc.qty)
        item.allocated_qty = int(getattr(item, "allocated_qty", 0) or 0) + delta
        alloc.qty = qty
        alloc.ratio = ratio
    execution.total_qty = new_total
    if notes:
        execution.notes = notes
    _sync_bridge_shop_qty(
        db,
        tenant_id=tenant_id,
        execution=execution,
        total_qty=new_total,
        user_id=user_id,
    )
    if commit:
        db.commit()
        db.refresh(execution)
    return {
        "dry_run": False,
        **preview,
        "execution": execution_out(db, execution),
    }


def change_execution_size(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    size_id: int,
    commit: bool = True,
) -> SpecExecutionOrder:
    """禁止无痕改码：已开工硬拦；未开工引导取消重排。"""
    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        raise ExecutionError("execution_cancelled", "生产单已取消")
    if int(size_id) == int(execution.size_id or 0):
        return execution
    if execution_is_started(db, execution):
        raise ExecutionError(
            "size_change_blocked",
            "已开工禁止改码；客户补码请新建生产单",
        )
    raise ExecutionError(
        "size_change_unstarted",
        "未开工改码请取消后重排；禁止直接改尺码字段",
    )


def create_supplement_execution(
    db: Session,
    *,
    tenant_id: int,
    items: list[dict],
    created_by: int | None = None,
    notes: str | None = None,
    delivery_date: date | None = None,
    commit: bool = True,
) -> SpecExecutionOrder:
    """补码路径：在可产剩余上新建执行单（不改已有已开工单）。"""
    note = (notes or "").strip() or "补码新单"
    if "补码" not in note:
        note = f"补码新单 · {note}"
    return create_execution(
        db,
        tenant_id=tenant_id,
        items=items,
        created_by=created_by,
        notes=note,
        delivery_date=delivery_date,
        commit=commit,
    )


def _execution_units(db: Session, execution: SpecExecutionOrder) -> list[TraceUnit]:
    units = list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.tenant_id == execution.tenant_id,
                TraceUnit.execution_id == execution.id,
            )
        ).all()
    )
    if units or not execution.shop_order_id:
        return units
    return list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.tenant_id == execution.tenant_id,
                TraceUnit.order_id == execution.shop_order_id,
            )
        ).all()
    )


def _unit_has_report(db: Session, unit_id: int) -> bool:
    n = db.scalar(
        select(func.count())
        .select_from(TraceUnitLog)
        .where(
            TraceUnitLog.trace_unit_id == unit_id,
            TraceUnitLog.action == TraceUnitAction.report,
        )
    )
    return int(n or 0) > 0


def _halt_floor_and_voidables(db: Session, execution: SpecExecutionOrder) -> dict:
    """已入库/已出货必须保留；未报工 open 可作废；其余在制卡住计入下限。"""
    units = _execution_units(db, execution)
    finished_qty = 0
    stuck_qty = 0
    voidable: list[dict] = []
    stuck: list[dict] = []
    finished: list[dict] = []
    for u in units:
        st = u.status.value if hasattr(u.status, "value") else str(u.status)
        brief = {
            "trace_unit_id": u.id,
            "code": u.code,
            "qty": int(u.qty or 0),
            "status": st,
            "unit_type": u.unit_type.value if hasattr(u.unit_type, "value") else str(u.unit_type),
        }
        if st in (TraceUnitStatus.warehoused.value, TraceUnitStatus.shipped.value):
            finished_qty += int(u.qty or 0)
            finished.append(brief)
            continue
        if st == TraceUnitStatus.scrapped.value:
            continue
        if st == TraceUnitStatus.open.value and not _unit_has_report(db, u.id):
            voidable.append(brief)
            continue
        stuck_qty += int(u.qty or 0)
        stuck.append({**brief, "reason": "已报工/在制，停产前请先处理"})
    floor = finished_qty + stuck_qty
    return {
        "floor_qty": floor,
        "finished_qty": finished_qty,
        "stuck_qty": stuck_qty,
        "voidable": voidable,
        "stuck": stuck,
        "finished": finished,
        "voidable_qty": sum(int(x["qty"]) for x in voidable),
    }


def simulate_halt(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    target_total_qty: int | None = None,
    void_open_units: bool = True,
) -> dict:
    """已开工停产/减产仿真：释放可产、料、未报工筐（确认前不落库）。"""
    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        raise ExecutionError("execution_cancelled", "生产单已取消")
    if not execution_is_started(db, execution):
        raise ExecutionError(
            "not_started",
            "未开工请用改量或取消；停产回滚仅用于已开工",
        )

    meta = _halt_floor_and_voidables(db, execution)
    old_total = int(execution.total_qty or 0)
    floor = int(meta["floor_qty"])
    if target_total_qty is None:
        # 全停：保留已完+卡住；作废 voidable 后目标=floor
        new_total = floor
    else:
        new_total = int(target_total_qty)
    if new_total < floor:
        raise ExecutionError(
            "below_floor",
            f"目标数量不能低于已完工/在制下限 {floor}（含不可作废载体）",
        )
    if new_total > old_total:
        raise ExecutionError("cannot_increase", "停产/减产不能增产；补码请开新单")

    will_void = list(meta["voidable"]) if void_open_units else []
    # 若不作废 voidable，则它们也必须计入目标下限
    if not void_open_units:
        voidable_qty = int(meta["voidable_qty"])
        floor2 = floor + voidable_qty
        if new_total < floor2:
            raise ExecutionError(
                "below_floor",
                f"未勾选作废未报工筐时，目标不能低于 {floor2}",
            )

    release_qty = old_total - new_total
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    # 按原 ratio 缩到 new_total
    if new_total <= 0:
        new_alloc_qtys = [0 for _ in allocs]
    elif old_total <= 0:
        new_alloc_qtys = [0 for _ in allocs]
    else:
        raw = [int(a.qty) * new_total / old_total for a in allocs]
        new_alloc_qtys = [int(x) for x in raw]
        drift = new_total - sum(new_alloc_qtys)
        if allocs and drift != 0:
            new_alloc_qtys[-1] = max(0, new_alloc_qtys[-1] + drift)

    pool_releases = []
    for a, nq in zip(allocs, new_alloc_qtys):
        old_q = int(a.qty)
        freed = old_q - nq
        if freed > 0:
            so = db.get(SalesOrder, a.sales_order_id)
            pool_releases.append(
                {
                    "sales_order_line_item_id": a.sales_order_line_item_id,
                    "sales_order_no": so.order_no if so else None,
                    "old_qty": old_q,
                    "new_qty": nq,
                    "release_qty": freed,
                }
            )

    terminal = new_total == 0 and floor == 0
    warning = (
        f"将从 {old_total} 减至 {new_total}，释放可产 {release_qty}；"
        f"作废未报工载体 {len(will_void)} 个；"
        + ("生产单将取消并尝试释放料占用。" if terminal else "将同步桥接单数量并重算材料需求。")
    )
    return {
        "execution_id": execution.id,
        "execution_no": execution.execution_no,
        "old_total_qty": old_total,
        "new_total_qty": new_total,
        "floor_qty": floor,
        "release_qty": release_qty,
        "void_open_units": void_open_units,
        "will_void": will_void,
        "stuck": meta["stuck"],
        "finished": meta["finished"],
        "pool_releases": pool_releases,
        "will_cancel_execution": terminal,
        "warning": warning,
    }


def confirm_halt(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    target_total_qty: int | None = None,
    void_open_units: bool = True,
    notes: str | None = None,
    commit: bool = True,
    user_id: int | None = None,
) -> dict:
    """确认停产/减产：落分配释放、作废未报工筐、同步料。"""
    preview = simulate_halt(
        db,
        tenant_id=tenant_id,
        execution_id=execution_id,
        target_total_qty=target_total_qty,
        void_open_units=void_open_units,
    )
    execution = get_execution(db, tenant_id, execution_id)
    # 再校验 floor（防并发）
    meta = _halt_floor_and_voidables(db, execution)
    new_total = int(preview["new_total_qty"])
    if new_total < int(meta["floor_qty"]):
        raise ExecutionError("below_floor", f"下限已变为 {meta['floor_qty']}，请重新仿真")

    voided = []
    if void_open_units:
        from app.services.trace_service import TraceError, void_trace_unit

        for row in preview["will_void"]:
            try:
                u = void_trace_unit(
                    db,
                    tenant_id=tenant_id,
                    unit_id=int(row["trace_unit_id"]),
                    note=notes or "停产作废未报工载体",
                    commit=False,
                )
                voided.append({"trace_unit_id": u.id, "code": u.code, "qty": int(u.qty or 0)})
            except TraceError as e:
                raise ExecutionError(e.code, e.message) from e

    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    old_total = int(execution.total_qty or 0)
    if new_total <= 0:
        new_alloc_qtys = [0 for _ in allocs]
        new_ratios = [Decimal("0") for _ in allocs]
    else:
        raw = [int(a.qty) * new_total / old_total for a in allocs] if old_total else [0] * len(allocs)
        new_alloc_qtys = [int(x) for x in raw]
        drift = new_total - sum(new_alloc_qtys)
        if allocs and drift != 0:
            new_alloc_qtys[-1] = max(0, new_alloc_qtys[-1] + drift)
        positive = [q for q in new_alloc_qtys if q > 0]
        if positive:
            ratios = _ratios(positive)
            ri = 0
            new_ratios = []
            for q in new_alloc_qtys:
                if q > 0:
                    new_ratios.append(ratios[ri])
                    ri += 1
                else:
                    new_ratios.append(Decimal("0"))
        else:
            new_ratios = [Decimal("0") for _ in allocs]

    for a, nq, ratio in zip(allocs, new_alloc_qtys, new_ratios):
        freed = int(a.qty) - int(nq)
        item = db.get(SalesOrderLineItem, a.sales_order_line_item_id)
        if item and freed > 0:
            item.allocated_qty = max(0, int(getattr(item, "allocated_qty", 0) or 0) - freed)
        a.qty = int(nq)
        a.ratio = ratio

    execution.total_qty = new_total
    if notes:
        execution.notes = ((execution.notes or "") + "；" + notes).strip("；")

    material_release: dict | list | None = None
    if new_total == 0 and int(meta["floor_qty"]) == 0:
        execution.status = SpecExecutionStatus.cancelled
        if execution.shop_order_id:
            shop = db.get(Order, execution.shop_order_id)
            if shop and shop.tenant_id == tenant_id:
                shop.total_qty = 0
                for it in list(shop.items or []) or list(
                    db.scalars(select(OrderItem).where(OrderItem.order_id == shop.id)).all()
                ):
                    it.qty = 0
                from app.services.material_service import (
                    release_unused_arrived_to_pool,
                    sync_requirements_after_qty_change,
                )

                sync_requirements_after_qty_change(db, tenant_id, shop, user_id=user_id)
                if shop.status != OrderStatus.cancelled:
                    shop.status = OrderStatus.cancelled
                    material_release = release_unused_arrived_to_pool(
                        db,
                        tenant_id,
                        shop,
                        user_id=user_id,
                        note=notes or f"生产单 {execution.execution_no} 停产释放",
                    )
    else:
        if new_total > 0 and new_total <= int(execution.completed_qty or 0):
            execution.status = SpecExecutionStatus.completed
        _sync_bridge_shop_qty(
            db,
            tenant_id=tenant_id,
            execution=execution,
            total_qty=new_total,
            user_id=user_id,
        )

    if commit:
        db.commit()
        db.refresh(execution)

    return {
        **preview,
        "voided": voided,
        "material_release": material_release,
        "execution": execution_out(db, execution),
    }


def cancel_execution(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    commit: bool = True,
) -> SpecExecutionOrder:
    execution = get_execution(db, tenant_id, execution_id)
    if execution.status == SpecExecutionStatus.cancelled:
        return execution
    if int(execution.completed_qty or 0) > 0:
        raise ExecutionError("has_progress", "已有产量，不能取消")
    if execution.shop_order_id:
        active = (
            db.scalar(
                select(func.count())
                .select_from(TraceUnit)
                .where(
                    TraceUnit.tenant_id == tenant_id,
                    TraceUnit.order_id == execution.shop_order_id,
                    TraceUnit.status != TraceUnitStatus.scrapped,
                )
            )
            or 0
        )
        if int(active) > 0:
            raise ExecutionError("has_trace_units", "已有开裁码，不能取消")

    for alloc in execution.allocations or []:
        item = db.get(SalesOrderLineItem, alloc.sales_order_line_item_id)
        if item:
            item.allocated_qty = max(0, int(getattr(item, "allocated_qty", 0) or 0) - int(alloc.qty))
    execution.status = SpecExecutionStatus.cancelled
    if commit:
        db.commit()
        db.refresh(execution)
    return execution


def execution_out(db: Session, execution: SpecExecutionOrder) -> dict:
    product = db.get(OwnProduct, execution.own_product_id)
    color = db.get(Color, execution.color_id) if execution.color_id else None
    size = db.get(Size, execution.size_id)
    allocs = list(execution.allocations or [])
    if not allocs:
        allocs = list(
            db.scalars(
                select(ExecutionAllocation).where(ExecutionAllocation.execution_id == execution.id)
            ).all()
        )
    alloc_out = []
    for a in allocs:
        so = db.get(SalesOrder, a.sales_order_id)
        item = db.get(SalesOrderLineItem, a.sales_order_line_item_id)
        alloc_out.append(
            {
                "id": a.id,
                "sales_order_id": a.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "sales_order_line_id": a.sales_order_line_id,
                "sales_order_line_item_id": a.sales_order_line_item_id,
                "qty": a.qty,
                "ratio": float(a.ratio),
                "produced_qty_est": a.produced_qty_est,
                "labor_cost": getattr(item, "labor_cost", None) or 0,
                "progress_kind": "estimated",
            }
        )
    kit = None
    if execution.shop_order_id:
        try:
            from app.services.material_service import MaterialError, get_order_kit

            kit = get_order_kit(db, execution.tenant_id, int(execution.shop_order_id))
            kit = {
                "kit_ok": bool(kit.get("kit_ok")),
                "shortage_lines": kit.get("shortage_lines"),
                "empty_bom": bool(kit.get("empty_bom")),
                "first_kit_ok": bool(kit.get("first_kit_ok")),
            }
        except MaterialError:
            kit = None
    header = (
        db.get(ExecutionHeader, execution.header_id)
        if getattr(execution, "header_id", None)
        else None
    )
    return {
        "id": execution.id,
        "execution_no": execution.execution_no,
        "header_id": getattr(execution, "header_id", None),
        "header_no": header.header_no if header else None,
        "own_product_id": execution.own_product_id,
        "product_code": product.product_code if product else None,
        "color_id": execution.color_id,
        "color_name": color.name if color else None,
        "size_id": execution.size_id,
        "size_value": size.size_value if size else None,
        "total_qty": execution.total_qty,
        "completed_qty": execution.completed_qty,
        "progress_kind": "estimated",
        "status": execution.status.value
        if hasattr(execution.status, "value")
        else str(execution.status),
        "started": execution_is_started(db, execution),
        "delivery_date": execution.delivery_date.isoformat() if execution.delivery_date else None,
        "is_rush": bool(getattr(execution, "is_rush", False)),
        "rush_reason": getattr(execution, "rush_reason", None),
        "shop_order_id": execution.shop_order_id,
        "notes": execution.notes,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "kit": kit,
        "allocations": alloc_out,
        "allocation_sources": [
            {
                "sales_order_id": a["sales_order_id"],
                "sales_order_no": a["sales_order_no"],
                "qty": a["qty"],
                "ratio": a["ratio"],
                "label": f"{a['sales_order_no'] or a['sales_order_id']} {a['qty']}",
            }
            for a in alloc_out
        ],
    }
