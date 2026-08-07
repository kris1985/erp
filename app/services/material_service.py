"""订单用料快照、齐套、发车间、公用库存。"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    MaterialCategory,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OrderStatus,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    SupplierProduct,
    MaterialRelease,
)

ORDERED_PO_STATUSES = {
    PurchaseOrderStatus.ordered,
    PurchaseOrderStatus.shipped,
    PurchaseOrderStatus.partial_received,
    PurchaseOrderStatus.received,
}


class MaterialError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def calc_required_qty(qty_per_pair: Decimal, total_qty: int, loss_rate: Decimal) -> Decimal:
    return (qty_per_pair * Decimal(total_qty) * (Decimal("1") + loss_rate)).quantize(Decimal("0.0001"))


def resolve_consume_process(
    db: Session,
    tenant_id: int,
    *,
    bom_consume_process_id: int | None,
    supplier_product_id: int,
) -> tuple[int | None, str]:
    """解析消耗工序：(process_id, source)。

    优先级：BOM 覆盖 > 物料分类默认 > unlabeled（运行时算进首道）。
    """
    if bom_consume_process_id:
        proc = db.get(ProcessDefinition, bom_consume_process_id)
        if proc and proc.tenant_id == tenant_id:
            return proc.id, "bom"
    sp = db.get(SupplierProduct, supplier_product_id)
    if sp and sp.tenant_id == tenant_id and sp.category_id:
        cat = db.get(MaterialCategory, sp.category_id)
        if (
            cat
            and cat.tenant_id == tenant_id
            and cat.default_consume_process_id
        ):
            proc = db.get(ProcessDefinition, cat.default_consume_process_id)
            if proc and proc.tenant_id == tenant_id:
                return proc.id, "category"
    return None, "unlabeled"


def process_display_name(db: Session, process_id: int | None) -> str | None:
    if not process_id:
        return None
    proc = db.get(ProcessDefinition, process_id)
    return proc.name if proc else None


def first_order_process(db: Session, tenant_id: int, order_id: int) -> OrderProcess | None:
    """首道 = 建单时按产品路线写入的第一道（OrderProcess.id 升序）。"""
    return db.scalar(
        select(OrderProcess)
        .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order_id)
        .order_by(OrderProcess.id)
        .limit(1)
    )


def row_in_process_scope(
    row: OrderMaterialRequirement,
    process_id: int,
    *,
    first_process_id: int | None,
) -> bool:
    """工序齐套过滤：首道含 unlabeled；其它工序仅匹配显式归属。"""
    cid = getattr(row, "consume_process_id", None)
    if first_process_id is not None and process_id == first_process_id:
        return cid is None or cid == first_process_id
    return cid == process_id


def apply_consume_snapshot(
    db: Session,
    tenant_id: int,
    row: OrderMaterialRequirement,
    *,
    bom_consume_process_id: int | None,
    supplier_product_id: int,
) -> str:
    """把解析结果写入订单用料快照，返回 source。"""
    pid, source = resolve_consume_process(
        db,
        tenant_id,
        bom_consume_process_id=bom_consume_process_id,
        supplier_product_id=supplier_product_id,
    )
    row.consume_process_id = pid
    row.consume_process_name = process_display_name(db, pid)
    return source


def ensure_material_snapshot(db: Session, tenant_id: int, order: Order) -> list[OrderMaterialRequirement]:
    """若尚无用料行，从产品 BOM 生成快照。"""
    existing = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.order_id == order.id,
        )
    ).all()
    if existing:
        return list(existing)
    return refresh_from_bom(db, tenant_id, order, keep_progress=False)


def refresh_from_bom(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    keep_progress: bool = True,
) -> list[OrderMaterialRequirement]:
    materials = db.scalars(
        select(OwnProductMaterial)
        .where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id == order.own_product_id,
        )
        .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
    ).all()

    by_sp: dict[int, OrderMaterialRequirement] = {}
    if keep_progress:
        for row in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all():
            by_sp[row.supplier_product_id] = row

    kept_ids: set[int] = set()
    result: list[OrderMaterialRequirement] = []
    for i, m in enumerate(materials):
        req = calc_required_qty(m.qty, order.total_qty, Decimal("0"))
        bom_pid = getattr(m, "consume_process_id", None)
        if m.supplier_product_id in by_sp and keep_progress:
            row = by_sp[m.supplier_product_id]
            row.qty_per_pair = m.qty
            row.unit_price = m.unit_price
            row.required_qty = calc_required_qty(m.qty, order.total_qty, row.loss_rate)
            row.sort_order = m.sort_order if m.sort_order is not None else i
            apply_consume_snapshot(
                db,
                tenant_id,
                row,
                bom_consume_process_id=bom_pid,
                supplier_product_id=m.supplier_product_id,
            )
            kept_ids.add(row.id)
            result.append(row)
        else:
            row = OrderMaterialRequirement(
                tenant_id=tenant_id,
                order_id=order.id,
                supplier_product_id=m.supplier_product_id,
                qty_per_pair=m.qty,
                loss_rate=Decimal("0"),
                unit_price=m.unit_price or Decimal("0"),
                required_qty=req,
                arrived_qty=Decimal("0"),
                issued_qty=Decimal("0"),
                is_customer_supplied=False,
                sort_order=m.sort_order if m.sort_order is not None else i,
            )
            apply_consume_snapshot(
                db,
                tenant_id,
                row,
                bom_consume_process_id=bom_pid,
                supplier_product_id=m.supplier_product_id,
            )
            db.add(row)
            result.append(row)

    if keep_progress:
        for row in by_sp.values():
            if row.id and row.id not in kept_ids and row.arrived_qty == 0 and row.issued_qty == 0:
                # 仅删除无进度且不在新 BOM 的行
                if row.supplier_product_id not in {m.supplier_product_id for m in materials}:
                    db.delete(row)

    db.flush()
    return result


def recalculate_required(db: Session, tenant_id: int, order: Order) -> list[OrderMaterialRequirement]:
    rows = ensure_material_snapshot(db, tenant_id, order)
    for row in rows:
        row.required_qty = calc_required_qty(row.qty_per_pair, order.total_qty, row.loss_rate)
    db.flush()
    return rows


def _shared_qty(db: Session, tenant_id: int, supplier_product_id: int) -> Decimal:
    stock = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == supplier_product_id,
        )
    )
    return stock.qty if stock else Decimal("0")


def _shared_avg_cost(db: Session, tenant_id: int, supplier_product_id: int) -> Decimal:
    stock = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == supplier_product_id,
        )
    )
    return stock.avg_unit_cost if stock else Decimal("0")


def ordered_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status.in_(list(ORDERED_PO_STATUSES)),
        )
    ).all()
    return sum((ln.qty for ln in lines), Decimal("0"))


def in_transit_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    """在途 = 已下单/在运采购行的未收量（只认 PO 实收，不跟 arrived 混算）。"""
    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    total = Decimal("0")
    for ln in lines:
        open_qty = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
        if open_qty > 0:
            total += open_qty
    return total


def draft_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    """采购草稿占用（不进齐套，但占用待采购数量，避免重复下单）。"""
    val = db.scalar(
        select(func.coalesce(func.sum(PurchaseOrderLine.qty), 0))
        .select_from(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status == PurchaseOrderStatus.draft,
        )
    )
    return Decimal(str(val or 0))


def resolve_include_shared(
    db: Session,
    tenant_id: int,
    include_shared: bool | None = None,
) -> bool:
    """显式入参优先；否则读租户 kit_include_unallocated_pool。"""
    if include_shared is not None:
        return bool(include_shared)
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    return bool(inv.get("kit_include_unallocated_pool", True))


OPEN_KIT_STATUSES = {
    OrderStatus.draft,
    OrderStatus.confirmed,
    OrderStatus.in_progress,
}


def _pool_need(row: OrderMaterialRequirement) -> Decimal:
    """相对已占用（arrived），还差多少才齐套（不含池）。"""
    if row.is_customer_supplied:
        return Decimal("0")
    required = row.required_qty or Decimal("0")
    arrived = row.arrived_qty or Decimal("0")
    return max(Decimal("0"), required - arrived)


def _order_kit_priority(order: Order) -> tuple:
    """急单优先，交期早优先，同交期 id 小优先。"""
    rush = 0 if getattr(order, "is_rush", False) else 1
    dd = order.delivery_date.toordinal() if order.delivery_date else 10**9
    return (rush, dd, order.id or 0)


def build_pool_credits(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool,
    focus_order_ids: set[int] | None = None,
) -> tuple[dict[tuple[int, int], Decimal], dict[int, Decimal]]:
    """按 SKU 把未分配池拆成各用料行的可承诺量，禁止多单重复吃满池。

    返回:
      credits[(order_id, req_id)] -> 本行可计入齐套的池数量
      pool_by_sp[supplier_product_id] -> 池余额
    """
    stocks = db.scalars(
        select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
    ).all()
    pool_by_sp = {s.supplier_product_id: (s.qty or Decimal("0")) for s in stocks}
    credits: dict[tuple[int, int], Decimal] = {}
    if not include_shared:
        return credits, pool_by_sp

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    orders.sort(key=_order_kit_priority)
    order_by_id = {o.id: o for o in orders}

    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.in_([o.id for o in orders] or [-1]),
            )
        ).all()
    )
    by_sp: dict[int, list[OrderMaterialRequirement]] = {}
    for row in reqs:
        if row.order_id not in order_by_id:
            continue
        by_sp.setdefault(row.supplier_product_id, []).append(row)

    for sp_id, rows in by_sp.items():
        remaining = pool_by_sp.get(sp_id, Decimal("0"))
        rows.sort(key=lambda r: _order_kit_priority(order_by_id[r.order_id]))
        for row in rows:
            need = _pool_need(row)
            credit = min(need, remaining) if need > 0 and remaining > 0 else Decimal("0")
            credits[(row.order_id, row.id)] = credit
            remaining -= credit

    if focus_order_ids:
        # 确保焦点订单的行即使 need=0 也有 key（便于调试）；无需改算法
        pass
    return credits, pool_by_sp


def kit_row_dict(
    db: Session,
    tenant_id: int,
    row: OrderMaterialRequirement,
    *,
    include_shared: bool = True,
    shared_credit: Decimal | None = None,
    pool_qty: Decimal | None = None,
) -> dict:
    """单行齐套投影。shared_credit 应由 build_pool_credits 传入，避免每行独吞整池。"""
    sp = db.get(SupplierProduct, row.supplier_product_id)
    partner = db.get(Partner, sp.partner_id) if sp and sp.partner_id else None
    ordered = ordered_qty_for_requirement(db, tenant_id, row.id)
    draft_qty = draft_qty_for_requirement(db, tenant_id, row.id)
    pool = (
        pool_qty
        if pool_qty is not None
        else (_shared_qty(db, tenant_id, row.supplier_product_id) if include_shared else Decimal("0"))
    )
    arrived = row.arrived_qty or Decimal("0")
    required = row.required_qty or Decimal("0")
    if shared_credit is None:
        # 兼容单行调用：不给池信用（避免独吞）；调用方应走 KitContext
        credit = Decimal("0")
    else:
        credit = shared_credit if include_shared else Decimal("0")
    if row.is_customer_supplied:
        shortage = max(Decimal("0"), required - arrived)
        credit = Decimal("0")
    else:
        shortage = max(Decimal("0"), required - arrived - credit)
    in_transit = in_transit_qty_for_requirement(db, tenant_id, row.id)
    to_buy = max(Decimal("0"), shortage - draft_qty - in_transit)
    if to_buy <= 0 and in_transit > 0:
        purchase_status = "ordered"
        purchase_status_label = "已下单在途"
    elif to_buy <= 0 and draft_qty > 0:
        purchase_status = "draft"
        purchase_status_label = "草稿已建"
    elif draft_qty > 0 or in_transit > 0:
        purchase_status = "partial"
        purchase_status_label = "部分已采"
    else:
        purchase_status = "open"
        purchase_status_label = "待采购"
    kit_ok = shortage <= 0
    consume_pid = getattr(row, "consume_process_id", None)
    consume_name = getattr(row, "consume_process_name", None) or process_display_name(db, consume_pid)
    return {
        "id": row.id,
        "order_id": row.order_id,
        "supplier_product_id": row.supplier_product_id,
        "supplier_product_code": sp.product_code if sp else None,
        "supplier_product_name": sp.name if sp else None,
        "image_url": sp.image_url if sp else None,
        "partner_id": sp.partner_id if sp else None,
        "partner_name": partner.name if partner else None,
        "pricing_unit_id": sp.pricing_unit_id if sp else None,
        "qty_per_pair": row.qty_per_pair,
        "loss_rate": row.loss_rate,
        "unit_price": row.unit_price,
        "required_qty": required,
        "ordered_qty": ordered,
        "draft_qty": draft_qty,
        "arrived_qty": arrived,
        "in_transit_qty": in_transit,
        "pool_qty": pool if include_shared else Decimal("0"),
        "shared_credit_qty": credit,
        # 兼容旧前端列：展示本单可计入齐套的池承诺，而非整池
        "shared_qty": credit,
        "shortage_qty": shortage,
        "to_buy_qty": to_buy,
        "purchase_status": purchase_status,
        "purchase_status_label": purchase_status_label,
        "issued_qty": row.issued_qty or Decimal("0"),
        "is_customer_supplied": bool(row.is_customer_supplied),
        "kit_ok": kit_ok,
        "sort_order": row.sort_order,
        "notes": row.notes,
        "consume_process_id": consume_pid,
        "consume_process_name": consume_name,
        "consume_unlabeled": consume_pid is None,
    }


class KitContext:
    """租户级齐套上下文：一次建池承诺，多处复用（列表/缺料/看板）。"""

    def __init__(
        self,
        db: Session,
        tenant_id: int,
        *,
        include_shared: bool,
        credits: dict[tuple[int, int], Decimal],
        pool_by_sp: dict[int, Decimal],
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.include_shared = include_shared
        self.credits = credits
        self.pool_by_sp = pool_by_sp

    def row_dict(self, row: OrderMaterialRequirement) -> dict:
        return kit_row_dict(
            self.db,
            self.tenant_id,
            row,
            include_shared=self.include_shared,
            shared_credit=self.credits.get((row.order_id, row.id), Decimal("0")),
            pool_qty=self.pool_by_sp.get(row.supplier_product_id, Decimal("0")),
        )

    def summary_for_order(self, order_id: int, rows: list[OrderMaterialRequirement] | None = None) -> dict:
        if rows is None:
            rows = list(
                self.db.scalars(
                    select(OrderMaterialRequirement).where(
                        OrderMaterialRequirement.tenant_id == self.tenant_id,
                        OrderMaterialRequirement.order_id == order_id,
                    )
                ).all()
            )
        if not rows:
            return {
                "kit_ok": True,
                "empty_bom": True,
                "shortage_lines": 0,
                "include_shared": self.include_shared,
                "first_kit_ok": True,
                "first_process_id": None,
                "first_process_name": None,
            }
        shortage = 0
        for row in rows:
            if not self.row_dict(row)["kit_ok"]:
                shortage += 1
        first = first_order_process(self.db, self.tenant_id, order_id)
        first_id = first.process_id if first else None
        first_name = first.process_name if first else None
        first_shortage = 0
        if first_id is not None:
            for row in rows:
                if not row_in_process_scope(row, first_id, first_process_id=first_id):
                    continue
                if not self.row_dict(row)["kit_ok"]:
                    first_shortage += 1
            first_kit_ok = first_shortage == 0
        else:
            # 无工序：首道齐套退化为整单
            first_kit_ok = shortage == 0
        return {
            "kit_ok": shortage == 0,
            "empty_bom": False,
            "shortage_lines": shortage,
            "include_shared": self.include_shared,
            "first_kit_ok": first_kit_ok,
            "first_process_id": first_id,
            "first_process_name": first_name,
        }


def build_kit_context(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool | None = None,
) -> KitContext:
    resolved = resolve_include_shared(db, tenant_id, include_shared)
    credits, pool_by_sp = build_pool_credits(db, tenant_id, include_shared=resolved)
    return KitContext(
        db,
        tenant_id,
        include_shared=resolved,
        credits=credits,
        pool_by_sp=pool_by_sp,
    )


def get_order_kit(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    include_shared: bool | None = True,
) -> dict:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.material_requirements))
    )
    if not order:
        raise MaterialError("order_not_found", "订单不存在")
    rows = ensure_material_snapshot(db, tenant_id, order)
    db.flush()
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    lines = [ctx.row_dict(r) for r in rows]
    lines.sort(key=lambda x: (x["sort_order"], x["id"]))
    empty_bom = len(lines) == 0
    kit_ok = empty_bom or all(x["kit_ok"] for x in lines)

    first = first_order_process(db, tenant_id, order.id)
    first_id = first.process_id if first else None
    first_name = first.process_name if first else None

    processes = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order.id)
            .order_by(OrderProcess.id)
        ).all()
    )
    by_process: list[dict] = []
    for p in processes:
        scoped = [r for r in rows if row_in_process_scope(r, p.process_id, first_process_id=first_id)]
        if not scoped and p.process_id != first_id:
            # 无归属到该工序的料：视为齐套（不挡分段排产）
            by_process.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "kit_ok": True,
                    "shortage_lines": 0,
                    "line_count": 0,
                    "is_first": first_id is not None and p.process_id == first_id,
                }
            )
            continue
        shortage_n = 0
        for r in scoped:
            if not ctx.row_dict(r)["kit_ok"]:
                shortage_n += 1
        # 首道若无显式料行，unlabeled 已计入 scoped；空 BOM 已在上面 empty_bom
        by_process.append(
            {
                "process_id": p.process_id,
                "process_name": p.process_name,
                "kit_ok": shortage_n == 0,
                "shortage_lines": shortage_n,
                "line_count": len(scoped),
                "is_first": first_id is not None and p.process_id == first_id,
            }
        )

    if first_id is not None:
        first_kit_ok = next((x["kit_ok"] for x in by_process if x["is_first"]), kit_ok)
    else:
        first_kit_ok = kit_ok

    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "empty_bom": empty_bom,
        "kit_ok": kit_ok,
        "first_kit_ok": first_kit_ok,
        "first_process_id": first_id,
        "first_process_name": first_name,
        "by_process": by_process,
        "include_shared": ctx.include_shared,
        "lines": lines,
    }


def list_shortages(
    db: Session,
    tenant_id: int,
    *,
    order_ids: list[int] | None = None,
    include_shared: bool | None = True,
    keyword: str | None = None,
    partner_id: int | None = None,
    order_no: str | None = None,
    rush_only: bool = False,
    hide_purchased: bool = True,
) -> list[dict]:
    """缺料/待采购列表。与订单齐套共用 KitContext（池承诺不重复占用）。"""
    q = select(Order).where(Order.tenant_id == tenant_id)
    if order_ids:
        q = q.where(Order.id.in_(order_ids))
    else:
        q = q.where(Order.status.in_(list(OPEN_KIT_STATUSES)))
    if order_no and order_no.strip():
        q = q.where(Order.order_no.contains(order_no.strip()))
    if rush_only:
        q = q.where(Order.is_rush.is_(True))
    orders = list(db.scalars(q).all())
    orders.sort(key=_order_kit_priority)
    for order in orders:
        ensure_material_snapshot(db, tenant_id, order)
    db.flush()
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    kw = (keyword or "").strip().lower()
    out: list[dict] = []
    for order in orders:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
        for row in reqs:
            d = ctx.row_dict(row)
            if d["is_customer_supplied"]:
                continue
            if d["shortage_qty"] <= 0:
                continue
            if hide_purchased and d["to_buy_qty"] <= 0:
                continue
            if partner_id is not None and d.get("partner_id") != partner_id:
                continue
            if kw:
                hay = " ".join(
                    [
                        str(d.get("supplier_product_code") or ""),
                        str(d.get("supplier_product_name") or ""),
                        str(d.get("partner_name") or ""),
                        str(order.order_no or ""),
                    ]
                ).lower()
                if kw not in hay:
                    continue
            d["order_no"] = order.order_no
            d["is_rush"] = bool(getattr(order, "is_rush", False))
            out.append(d)
    db.commit()
    return out


def patch_requirement(
    db: Session,
    tenant_id: int,
    req_id: int,
    *,
    loss_rate: Decimal | None = None,
    qty_per_pair: Decimal | None = None,
    is_customer_supplied: bool | None = None,
    notes: str | None = None,
    arrived_qty: Decimal | None = None,
    consume_process_id: int | None = None,
    clear_consume_process: bool = False,
) -> dict:
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    order = db.get(Order, row.order_id)
    if not order:
        raise MaterialError("order_not_found", "订单不存在")
    if loss_rate is not None:
        row.loss_rate = loss_rate
    if qty_per_pair is not None:
        row.qty_per_pair = qty_per_pair
    if is_customer_supplied is not None:
        row.is_customer_supplied = is_customer_supplied
    if notes is not None:
        row.notes = notes
    if arrived_qty is not None:
        if arrived_qty < 0:
            raise MaterialError("invalid_qty", "已到数量不能为负")
        row.arrived_qty = arrived_qty
    if clear_consume_process:
        row.consume_process_id = None
        row.consume_process_name = None
    elif consume_process_id is not None:
        proc = db.get(ProcessDefinition, consume_process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise MaterialError("invalid_process", "消耗工序不存在")
        row.consume_process_id = proc.id
        row.consume_process_name = proc.name
    row.required_qty = calc_required_qty(row.qty_per_pair, order.total_qty, row.loss_rate)
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def add_requirement(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    supplier_product_id: int,
    qty_per_pair: Decimal = Decimal("1"),
    loss_rate: Decimal = Decimal("0"),
    is_customer_supplied: bool = False,
) -> dict:
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    sp = db.get(SupplierProduct, supplier_product_id)
    if not sp or sp.tenant_id != tenant_id:
        raise MaterialError("product_not_found", "供应商产品不存在")
    row = OrderMaterialRequirement(
        tenant_id=tenant_id,
        order_id=order_id,
        supplier_product_id=supplier_product_id,
        qty_per_pair=qty_per_pair,
        loss_rate=loss_rate,
        unit_price=sp.unit_price or Decimal("0"),
        required_qty=calc_required_qty(qty_per_pair, order.total_qty, loss_rate),
        is_customer_supplied=is_customer_supplied,
    )
    apply_consume_snapshot(
        db,
        tenant_id,
        row,
        bom_consume_process_id=None,
        supplier_product_id=supplier_product_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def delete_requirement(db: Session, tenant_id: int, req_id: int) -> None:
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    if (row.arrived_qty or 0) > 0 or (row.issued_qty or 0) > 0:
        raise MaterialError("has_progress", "已有到货/发车间，不能删除")
    linked = db.scalar(
        select(PurchaseOrderLine.id).where(
            PurchaseOrderLine.order_material_requirement_id == req_id,
        )
    )
    if linked:
        raise MaterialError("has_po", "已关联采购行，不能删除")
    db.delete(row)
    db.commit()


def adjust_shared_stock(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    qty_delta: Decimal,
    *,
    unit_cost: Decimal | None = None,
    note: str | None = None,
    user_id: int | None = None,
    ledger_type: SharedLedgerType = SharedLedgerType.adjust,
    ref_type: str | None = None,
    ref_id: int | None = None,
    order_id: int | None = None,
) -> SharedMaterialStock:
    stock = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == supplier_product_id,
        )
    )
    if not stock:
        stock = SharedMaterialStock(
            tenant_id=tenant_id,
            supplier_product_id=supplier_product_id,
            qty=Decimal("0"),
            avg_unit_cost=Decimal("0"),
        )
        db.add(stock)
        db.flush()

    new_qty = (stock.qty or Decimal("0")) + qty_delta
    if new_qty < 0:
        raise MaterialError("insufficient_shared", "库存池不足")

    if qty_delta > 0 and unit_cost is not None:
        old_val = (stock.qty or Decimal("0")) * (stock.avg_unit_cost or Decimal("0"))
        new_val = old_val + qty_delta * unit_cost
        stock.avg_unit_cost = (new_val / new_qty).quantize(Decimal("0.0001")) if new_qty else Decimal("0")
    stock.qty = new_qty

    db.add(
        SharedMaterialLedger(
            tenant_id=tenant_id,
            supplier_product_id=supplier_product_id,
            ledger_type=ledger_type,
            qty_delta=qty_delta,
            unit_cost=unit_cost,
            balance_after=new_qty,
            ref_type=ref_type,
            ref_id=ref_id,
            order_id=order_id,
            note=note,
            created_by=user_id,
        )
    )
    db.flush()
    return stock


def release_to_workshop(
    db: Session,
    tenant_id: int,
    order_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    deduct_shared: bool = False,
    user_id: int | None = None,
) -> dict:
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    if inv.get("issue_required") or inv.get("capabilities", {}).get("stock_docs"):
        raise MaterialError("use_stock_docs", "已开通强制领料，请使用领退料单")

    if qty <= 0:
        raise MaterialError("invalid_qty", "发车间数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id or row.order_id != order_id:
        raise MaterialError("not_found", "用料行不存在")

    if deduct_shared:
        adjust_shared_stock(
            db,
            tenant_id,
            row.supplier_product_id,
            -qty,
            ledger_type=SharedLedgerType.issue_to_order,
            ref_type="material_release",
            order_id=order_id,
            user_id=user_id,
            note="发车间扣公用库存",
        )

    row.issued_qty = (row.issued_qty or Decimal("0")) + qty
    rel = MaterialRelease(
        tenant_id=tenant_id,
        order_id=order_id,
        order_material_requirement_id=requirement_id,
        qty=qty,
        deduct_shared=deduct_shared,
        created_by=user_id,
    )
    db.add(rel)
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def list_shared_stocks(db: Session, tenant_id: int) -> list[dict]:
    """库存池列表：池余额 + 已占用(未发) + 采购在途。"""
    stocks = db.scalars(
        select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
    ).all()
    # 各 SKU 在订单上的占用/已发汇总
    occ_rows = db.execute(
        select(
            OrderMaterialRequirement.supplier_product_id,
            func.coalesce(func.sum(OrderMaterialRequirement.arrived_qty), 0),
            func.coalesce(func.sum(OrderMaterialRequirement.issued_qty), 0),
        )
        .where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.is_customer_supplied.is_(False),
        )
        .group_by(OrderMaterialRequirement.supplier_product_id)
    ).all()
    arrived_by_sp = {int(r[0]): Decimal(str(r[1] or 0)) for r in occ_rows}
    issued_by_sp = {int(r[0]): Decimal(str(r[2] or 0)) for r in occ_rows}

    # 采购在途：已下单/在运/部分收货的未收量（按 SKU）
    in_transit_by_sp = in_transit_qty_by_supplier_product(db, tenant_id)

    out = []
    seen: set[int] = set()
    for s in stocks:
        sp_id = s.supplier_product_id
        seen.add(sp_id)
        sp = db.get(SupplierProduct, sp_id)
        arrived = arrived_by_sp.get(sp_id, Decimal("0"))
        issued = issued_by_sp.get(sp_id, Decimal("0"))
        occupied = max(Decimal("0"), arrived - issued)  # 已分给订单、尚未发出
        pool = s.qty or Decimal("0")
        cat = None
        if sp and sp.category_id:
            cat = db.get(MaterialCategory, sp.category_id)
        out.append(
            {
                "id": s.id,
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "partner_id": sp.partner_id if sp else None,
                "category_id": sp.category_id if sp else None,
                "category_name": cat.name if cat else None,
                "qty": pool,  # 兼容旧字段 = 池余额
                "pool_qty": pool,
                "occupied_qty": occupied,
                "in_transit_qty": in_transit_by_sp.get(sp_id, Decimal("0")),
                "avg_unit_cost": s.avg_unit_cost,
                "updated_at": s.updated_at,
            }
        )

    # 有占用或在途、但池表尚无行的 SKU 也展示
    extra_ids = set(arrived_by_sp.keys()) | set(in_transit_by_sp.keys())
    for sp_id in extra_ids:
        if sp_id in seen:
            continue
        arrived = arrived_by_sp.get(sp_id, Decimal("0"))
        issued = issued_by_sp.get(sp_id, Decimal("0"))
        occupied = max(Decimal("0"), arrived - issued)
        transit = in_transit_by_sp.get(sp_id, Decimal("0"))
        if occupied <= 0 and transit <= 0:
            continue
        sp = db.get(SupplierProduct, sp_id)
        cat = None
        if sp and sp.category_id:
            cat = db.get(MaterialCategory, sp.category_id)
        out.append(
            {
                "id": None,
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "partner_id": sp.partner_id if sp else None,
                "category_id": sp.category_id if sp else None,
                "category_name": cat.name if cat else None,
                "qty": Decimal("0"),
                "pool_qty": Decimal("0"),
                "occupied_qty": occupied,
                "in_transit_qty": transit,
                "avg_unit_cost": Decimal("0"),
                "updated_at": None,
            }
        )
    out.sort(key=lambda x: (x.get("supplier_product_code") or ""))
    return out


_LEDGER_LABELS = {
    "unallocated_receive": "采购入池",
    "receive_surplus": "超收入池",
    "allocate_to_order": "锁料到单",
    "issue_to_order": "发车间扣池",
    "release_from_order": "退回库存池",
    "adjust": "库存调整",
}


def list_shared_ledgers(
    db: Session,
    tenant_id: int,
    *,
    supplier_product_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """库存池出入流水。"""
    q = (
        select(SharedMaterialLedger)
        .where(SharedMaterialLedger.tenant_id == tenant_id)
        .order_by(SharedMaterialLedger.id.desc())
        .limit(min(limit, 500))
    )
    if supplier_product_id:
        q = q.where(SharedMaterialLedger.supplier_product_id == supplier_product_id)
    rows = list(db.scalars(q).all())
    out = []
    for ln in rows:
        sp = db.get(SupplierProduct, ln.supplier_product_id)
        order = db.get(Order, ln.order_id) if ln.order_id else None
        lt = ln.ledger_type.value if hasattr(ln.ledger_type, "value") else str(ln.ledger_type)
        out.append(
            {
                "id": ln.id,
                "supplier_product_id": ln.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "ledger_type": lt,
                "ledger_type_label": _LEDGER_LABELS.get(lt, lt),
                "qty_delta": ln.qty_delta,
                "unit_cost": ln.unit_cost,
                "balance_after": ln.balance_after,
                "ref_type": ln.ref_type,
                "ref_id": ln.ref_id,
                "order_id": ln.order_id,
                "order_no": order.order_no if order else None,
                "note": ln.note,
                "created_at": ln.created_at,
            }
        )
    return out


def allocate_from_pool(
    db: Session,
    tenant_id: int,
    order_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
    commit: bool = True,
    ref_type: str = "manual_allocate",
    ref_id: int | None = None,
    note: str | None = None,
) -> dict:
    """从库存池硬分配到订单占用（arrived）。"""
    if qty <= 0:
        raise MaterialError("invalid_qty", "分配数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id or row.order_id != order_id:
        raise MaterialError("not_found", "用料行不存在")
    if row.is_customer_supplied:
        raise MaterialError("customer_supplied", "客供料不从库存池分配")
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    if order.status == OrderStatus.cancelled:
        raise MaterialError("order_cancelled", "已取消订单不能分配")

    adjust_shared_stock(
        db,
        tenant_id,
        row.supplier_product_id,
        -qty,
        unit_cost=row.unit_price,
        ledger_type=SharedLedgerType.allocate_to_order,
        ref_type=ref_type,
        ref_id=ref_id if ref_id is not None else order_id,
        order_id=order_id,
        user_id=user_id,
        note=note or f"分配到订单 {order.order_no}",
    )
    row.arrived_qty = (row.arrived_qty or Decimal("0")) + qty
    if commit:
        db.commit()
    else:
        db.flush()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def deallocate_to_pool(
    db: Session,
    tenant_id: int,
    order_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
) -> dict:
    """将订单未发占用回收到库存池。"""
    if qty <= 0:
        raise MaterialError("invalid_qty", "回收数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id or row.order_id != order_id:
        raise MaterialError("not_found", "用料行不存在")
    if row.is_customer_supplied:
        raise MaterialError("customer_supplied", "客供料不走库存池回收")
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")

    arrived = row.arrived_qty or Decimal("0")
    issued = row.issued_qty or Decimal("0")
    reusable = max(Decimal("0"), arrived - issued)
    if qty > reusable:
        raise MaterialError(
            "exceed_reusable",
            f"可回收数量不足（已占用 {arrived}，已发 {issued}，可回收 {reusable}）",
        )

    adjust_shared_stock(
        db,
        tenant_id,
        row.supplier_product_id,
        qty,
        unit_cost=row.unit_price,
        ledger_type=SharedLedgerType.release_from_order,
        ref_type="manual_deallocate",
        ref_id=order_id,
        order_id=order_id,
        user_id=user_id,
        note=f"手动回收自订单 {order.order_no}",
    )
    row.arrived_qty = arrived - qty
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def list_allocate_candidates(
    db: Session,
    tenant_id: int,
    *,
    keyword: str | None = None,
) -> list[dict]:
    """可从池分配的行：有缺口且池有货；以及有可回收占用的行。"""
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    orders.sort(key=_order_kit_priority)
    order_by_id = {o.id: o for o in orders}
    for order in orders:
        ensure_material_snapshot(db, tenant_id, order)
    db.flush()

    stocks = {
        s.supplier_product_id: (s.qty or Decimal("0"))
        for s in db.scalars(
            select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
        ).all()
    }
    kw = (keyword or "").strip().lower()
    out: list[dict] = []
    for order in orders:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
        for row in reqs:
            if row.is_customer_supplied:
                continue
            need = _pool_need(row)
            pool = stocks.get(row.supplier_product_id, Decimal("0"))
            arrived = row.arrived_qty or Decimal("0")
            issued = row.issued_qty or Decimal("0")
            reusable = max(Decimal("0"), arrived - issued)
            if need <= 0 and reusable <= 0:
                continue
            if need > 0 and pool <= 0 and reusable <= 0:
                continue
            sp = db.get(SupplierProduct, row.supplier_product_id)
            d = {
                "id": row.id,
                "order_id": order.id,
                "order_no": order.order_no,
                "is_rush": bool(getattr(order, "is_rush", False)),
                "delivery_date": order.delivery_date,
                "supplier_product_id": row.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "required_qty": row.required_qty or Decimal("0"),
                "arrived_qty": arrived,
                "issued_qty": issued,
                "need_qty": need,
                "pool_qty": pool,
                "allocatable_qty": min(need, pool) if need > 0 and pool > 0 else Decimal("0"),
                "reusable_qty": reusable,
            }
            if kw:
                hay = " ".join(
                    [
                        str(d.get("supplier_product_code") or ""),
                        str(d.get("supplier_product_name") or ""),
                        str(order.order_no or ""),
                    ]
                ).lower()
                if kw not in hay:
                    continue
            out.append(d)
    return out


def stock_reconcile_report(db: Session, tenant_id: int) -> dict:
    """按物料对账：库存池 + 订单未发占用 + PO 在途。

    说明：切仓前「直接挂 arrived」的占用不会出现在池流水里，属正常历史；
    账面解释量 = pool + occupancy；实物盘点需另行对照。
    """
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    open_orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    open_ids = [o.id for o in open_orders]

    # occupancy & anomalies by SKU
    occupancy: dict[int, Decimal] = {}
    anomaly_rows: list[dict] = []
    if open_ids:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.in_(open_ids),
            )
        ).all()
        order_no = {o.id: o.order_no for o in open_orders}
        for row in reqs:
            if row.is_customer_supplied:
                continue
            arrived = row.arrived_qty or Decimal("0")
            issued = row.issued_qty or Decimal("0")
            if arrived < issued:
                sp = db.get(SupplierProduct, row.supplier_product_id)
                anomaly_rows.append(
                    {
                        "type": "arrived_lt_issued",
                        "order_id": row.order_id,
                        "order_no": order_no.get(row.order_id),
                        "requirement_id": row.id,
                        "supplier_product_id": row.supplier_product_id,
                        "supplier_product_code": sp.product_code if sp else None,
                        "arrived_qty": arrived,
                        "issued_qty": issued,
                        "message": "已占用小于已发，数据异常",
                    }
                )
            reusable = max(Decimal("0"), arrived - issued)
            if reusable > 0:
                occupancy[row.supplier_product_id] = (
                    occupancy.get(row.supplier_product_id, Decimal("0")) + reusable
                )

    # pool
    stocks = {
        s.supplier_product_id: s
        for s in db.scalars(
            select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
        ).all()
    }

    # in-transit by SKU (all open PO lines, not only linked to req)
    transit: dict[int, Decimal] = {}
    po_lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    for ln in po_lines:
        open_qty = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
        if open_qty > 0:
            transit[ln.supplier_product_id] = transit.get(ln.supplier_product_id, Decimal("0")) + open_qty

    sp_ids = set(stocks.keys()) | set(occupancy.keys()) | set(transit.keys())
    lines: list[dict] = []
    for sp_id in sorted(sp_ids):
        sp = db.get(SupplierProduct, sp_id)
        pool_qty = stocks[sp_id].qty if sp_id in stocks else Decimal("0")
        occ = occupancy.get(sp_id, Decimal("0"))
        tr = transit.get(sp_id, Decimal("0"))
        lines.append(
            {
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "pool_qty": pool_qty,
                "order_occupancy_qty": occ,
                "in_transit_qty": tr,
                "book_total_qty": pool_qty + occ,
                "avg_unit_cost": stocks[sp_id].avg_unit_cost if sp_id in stocks else None,
            }
        )

    lines.sort(key=lambda x: (x.get("supplier_product_code") or "", x["supplier_product_id"]))
    return {
        "inventory": inv,
        "summary": {
            "sku_count": len(lines),
            "pool_total": sum((x["pool_qty"] for x in lines), Decimal("0")),
            "occupancy_total": sum((x["order_occupancy_qty"] for x in lines), Decimal("0")),
            "in_transit_total": sum((x["in_transit_qty"] for x in lines), Decimal("0")),
            "anomaly_count": len(anomaly_rows),
            "open_order_count": len(open_orders),
        },
        "lines": lines,
        "anomalies": anomaly_rows,
        "notes": [
            "订单占用 = 未取消/在制单上 max(已占用 − 已发，0)；切仓前直接挂单的占用也计入，不一定有对应入池流水。",
            "账面解释量 = 池余额 + 订单占用；不含在途。在途单独列示，便于跟采购对账。",
            "实物盘点请用账面解释量对照仓库实数；差异用库存池「调整」处理。",
        ],
    }


def order_kit_summary(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    include_shared: bool | None = None,
    ctx: KitContext | None = None,
) -> dict:
    """单订单齐套摘要；与列表/缺料/看板共用同一套池承诺。"""
    context = ctx or build_kit_context(db, tenant_id, include_shared=include_shared)
    return context.summary_for_order(order_id)


def order_kit_summaries(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    include_shared: bool | None = None,
) -> dict[int, dict]:
    if not order_ids:
        return {}
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    return {oid: ctx.summary_for_order(oid) for oid in order_ids}


def order_ids_matching_kit(
    db: Session,
    tenant_id: int,
    *,
    kit_ok: bool,
    include_shared: bool | None = None,
) -> set[int]:
    """用于订单列表齐套筛选：与徽章同一算法。"""
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    # 已完成/取消：无缺料行视为齐套=true（筛选「缺料」不含它们）
    closed = list(
        db.scalars(
            select(Order.id).where(
                Order.tenant_id == tenant_id,
                Order.status.in_([OrderStatus.completed, OrderStatus.cancelled]),
            )
        ).all()
    )
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    matched: set[int] = set()
    for o in orders:
        summary = ctx.summary_for_order(o.id)
        if bool(summary.get("kit_ok")) == bool(kit_ok):
            matched.add(o.id)
    if kit_ok:
        matched.update(int(x) for x in closed)
    return matched


def release_unused_arrived_to_pool(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    user_id: int | None = None,
    note: str | None = None,
) -> list[dict]:
    """将订单未发占用（arrived − issued）释放回库存池。"""
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
    )
    released: list[dict] = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        unused = max(Decimal("0"), arrived - issued)
        if unused <= 0:
            continue
        adjust_shared_stock(
            db,
            tenant_id,
            row.supplier_product_id,
            unused,
            unit_cost=row.unit_price,
            ledger_type=SharedLedgerType.release_from_order,
            ref_type="order",
            ref_id=order.id,
            order_id=order.id,
            user_id=user_id,
            note=note or f"订单 {order.order_no} 释放未发占用",
        )
        row.arrived_qty = arrived - unused
        released.append(
            {
                "requirement_id": row.id,
                "supplier_product_id": row.supplier_product_id,
                "qty": unused,
            }
        )
    db.flush()
    return released


def sync_requirements_after_qty_change(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    user_id: int | None = None,
) -> dict:
    """改量后重算需求；已占用超过新需求的部分释放回池（不低于已发量）。"""
    rows = recalculate_required(db, tenant_id, order)
    released: list[dict] = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        required = row.required_qty or Decimal("0")
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        floor = issued
        target = max(required, floor)
        if arrived > target:
            excess = arrived - target
            adjust_shared_stock(
                db,
                tenant_id,
                row.supplier_product_id,
                excess,
                unit_cost=row.unit_price,
                ledger_type=SharedLedgerType.release_from_order,
                ref_type="order_qty_change",
                ref_id=order.id,
                order_id=order.id,
                user_id=user_id,
                note=f"订单 {order.order_no} 改量释放超额占用",
            )
            row.arrived_qty = target
            released.append(
                {
                    "requirement_id": row.id,
                    "supplier_product_id": row.supplier_product_id,
                    "qty": excess,
                }
            )
    db.flush()
    return {"released": released, "requirement_count": len(rows)}


def free_pool_after_production_credits(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool,
) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """生产单池承诺之后的剩余可用池。

    返回:
      pool_by_sp: 库存池余额（原值）
      free_by_sp: 扣除未结生产单承诺后的剩余（销售算料从此取）
    """
    credits, pool_by_sp = build_pool_credits(db, tenant_id, include_shared=include_shared)
    committed: dict[int, Decimal] = {}
    if include_shared and credits:
        req_ids = [rid for (_, rid) in credits.keys()]
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(OrderMaterialRequirement.id.in_(req_ids or [-1]))
        ).all()
        sp_by_id = {r.id: r.supplier_product_id for r in reqs}
        for (_, rid), credit in credits.items():
            sp_id = sp_by_id.get(rid)
            if sp_id is None:
                continue
            committed[sp_id] = committed.get(sp_id, Decimal("0")) + credit
    free_by_sp = {
        sp_id: max(Decimal("0"), (pool_by_sp.get(sp_id) or Decimal("0")) - committed.get(sp_id, Decimal("0")))
        for sp_id in set(pool_by_sp) | set(committed)
    }
    return pool_by_sp, free_by_sp


def in_transit_qty_by_supplier_product(db: Session, tenant_id: int) -> dict[int, Decimal]:
    """按 SKU 汇总采购在途（已下单/在运/部分收货的未收量）。"""
    transit_rows = db.execute(
        select(
            PurchaseOrderLine.supplier_product_id,
            PurchaseOrderLine.qty,
            PurchaseOrderLine.received_qty,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    in_transit_by_sp: dict[int, Decimal] = {}
    for sp_id, qty, recv in transit_rows:
        open_qty = Decimal(str(qty or 0)) - Decimal(str(recv or 0))
        if open_qty > 0:
            sid = int(sp_id)
            in_transit_by_sp[sid] = in_transit_by_sp.get(sid, Decimal("0")) + open_qty
    return in_transit_by_sp


def simulate_mrp_from_bom(
    db: Session,
    tenant_id: int,
    demands: list[dict],
    *,
    include_shared: bool | None = True,
    shortages_only: bool = False,
) -> dict:
    """销售算料：BOM 展开后按库存池剩余 + 采购在途实时算缺口；不写库、不锁池。

    demands 每项:
      key, label, order_no, product_code, own_product_id, total_qty,
      delivery_date (optional), priority_key (optional tuple-like)
    """
    resolved = resolve_include_shared(db, tenant_id, include_shared)
    empty = {
        "locked": False,
        "include_shared": resolved,
        "empty_bom": True,
        "kit_ok": True,
        "shortage_lines": 0,
        "demand_count": 0,
        "lines": [],
    }
    if not demands:
        return empty

    pool_by_sp, free_by_sp = free_pool_after_production_credits(
        db, tenant_id, include_shared=resolved
    )
    in_transit_by_sp = in_transit_qty_by_supplier_product(db, tenant_id)
    remaining_pool = dict(free_by_sp) if resolved else {}
    remaining_transit = dict(in_transit_by_sp)

    # 展开 BOM → 需求行，按交期优先覆盖（先池后在途；多需求不重复占满）
    expanded: list[dict] = []
    for d in demands:
        own_product_id = int(d["own_product_id"])
        total_qty = int(d.get("total_qty") or 0)
        if total_qty <= 0:
            continue
        materials = db.scalars(
            select(OwnProductMaterial)
            .where(
                OwnProductMaterial.tenant_id == tenant_id,
                OwnProductMaterial.own_product_id == own_product_id,
            )
            .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
        ).all()
        for i, m in enumerate(materials):
            required = calc_required_qty(m.qty, total_qty, Decimal("0"))
            expanded.append(
                {
                    "key": d.get("key"),
                    "label": d.get("label"),
                    "order_no": d.get("order_no"),
                    "product_code": d.get("product_code"),
                    "own_product_id": own_product_id,
                    "supplier_product_id": m.supplier_product_id,
                    "qty_per_pair": m.qty,
                    "unit_price": m.unit_price or Decimal("0"),
                    "required_qty": required,
                    "sort_order": m.sort_order if m.sort_order is not None else i,
                    "delivery_date": d.get("delivery_date"),
                    "priority_key": d.get("priority_key")
                    or (
                        d.get("delivery_date").toordinal()
                        if getattr(d.get("delivery_date"), "toordinal", None)
                        else 10**9,
                        d.get("key") or "",
                    ),
                }
            )

    if not expanded:
        return {**empty, "demand_count": len(demands)}

    expanded.sort(key=lambda x: (x["priority_key"], x["sort_order"], x["supplier_product_id"]))

    merged: dict[int, dict] = {}
    for row in expanded:
        sp_id = row["supplier_product_id"]
        need = row["required_qty"]
        left = need
        pool_credit = Decimal("0")
        transit_credit = Decimal("0")
        if resolved and left > 0:
            pool_credit = min(left, remaining_pool.get(sp_id, Decimal("0")))
            remaining_pool[sp_id] = remaining_pool.get(sp_id, Decimal("0")) - pool_credit
            left -= pool_credit
        if left > 0:
            transit_credit = min(left, remaining_transit.get(sp_id, Decimal("0")))
            remaining_transit[sp_id] = remaining_transit.get(sp_id, Decimal("0")) - transit_credit
            left -= transit_credit
        shortage = max(Decimal("0"), left)
        covered = pool_credit + transit_credit

        bucket = merged.get(sp_id)
        if not bucket:
            sp = db.get(SupplierProduct, sp_id)
            partner = db.get(Partner, sp.partner_id) if sp and sp.partner_id else None
            bucket = {
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "partner_id": sp.partner_id if sp else None,
                "partner_name": partner.name if partner else None,
                "qty_per_pair": row["qty_per_pair"],
                "unit_price": row["unit_price"],
                "required_qty": Decimal("0"),
                "pool_qty": pool_by_sp.get(sp_id, Decimal("0")) if resolved else Decimal("0"),
                "free_pool_qty": free_by_sp.get(sp_id, Decimal("0")) if resolved else Decimal("0"),
                "in_transit_qty": in_transit_by_sp.get(sp_id, Decimal("0")),
                "shared_qty": Decimal("0"),
                "pool_credit_qty": Decimal("0"),
                "transit_credit_qty": Decimal("0"),
                "shortage_qty": Decimal("0"),
                "sort_order": row["sort_order"],
                "sources": [],
            }
            merged[sp_id] = bucket

        bucket["required_qty"] += need
        bucket["pool_credit_qty"] += pool_credit
        bucket["transit_credit_qty"] += transit_credit
        bucket["shared_qty"] += covered
        bucket["shortage_qty"] += shortage
        bucket["sources"].append(
            {
                "key": row["key"],
                "label": row["label"],
                "order_no": row["order_no"],
                "product_code": row["product_code"],
                "required_qty": need,
                "pool_credit_qty": pool_credit,
                "transit_credit_qty": transit_credit,
                "shared_qty": covered,
                "shortage_qty": shortage,
            }
        )

    lines = list(merged.values())
    lines.sort(key=lambda x: (x["sort_order"], x["supplier_product_id"]))
    if shortages_only:
        lines = [x for x in lines if x["shortage_qty"] > 0]

    shortage_n = sum(1 for x in lines if x["shortage_qty"] > 0)
    return {
        "locked": False,
        "include_shared": resolved,
        "empty_bom": False,
        "kit_ok": shortage_n == 0,
        "shortage_lines": shortage_n,
        "demand_count": len(demands),
        "lines": lines,
    }
