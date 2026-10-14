"""待采购 = 总用量 − 预警。

预警与仓库同一口径：现存 + 在途 + 已采购部分的车间剩余 − 已下单还要消耗。
一笔生产单只能采购一次。草稿或已下单挂到这张生产单的任一用料上，整张生产单都离开待买。
仓库的实际需求只算已经下单的部分。

不分码的料用消耗工序的合格报工减。分码的料报工没有码，生产需求按该码用量全额计算，
再减车间剩余和仓库现存。车间剩余按生产单：领料 +、退料 −，报工可改；没有记录按 0。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    ExecutionAllocation,
    ExecutionHeader,
    MaterialCategory,
    OrderMaterialRequirement,
    OwnProduct,
    Partner,
    PricingUnit,
    ProcessSizeOutput,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    WorkLog,
    WorkLogStatus,
    WorkshopMaterialCount,
    ReportType,
)
from app.services.material_service import is_tooling_category_name

_ZERO = Decimal("0")
_OPEN_HEADER = (
    SpecExecutionStatus.confirmed,
    SpecExecutionStatus.cut,
    SpecExecutionStatus.in_progress,
)


class PurchaseDemandError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _dec(value) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _qty_text(value: Decimal) -> str:
    text = format(_dec(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def list_purchase_demand(
    db: Session,
    tenant_id: int,
    *,
    sales_order_id: int | None = None,
    requirement_ids: set[int] | None = None,
    only_shortage: bool = True,
    skip_dismissed: bool = False,
) -> dict:
    headers = _open_headers(db, tenant_id, sales_order_id)
    header_by_id = {int(row.id): row for row in headers}
    if not header_by_id:
        return _empty()

    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement)
            .where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id.in_(header_by_id),
                OrderMaterialRequirement.is_customer_supplied.is_(False),
            )
            .order_by(OrderMaterialRequirement.id)
        ).all()
    )
    if skip_dismissed:
        reqs = [row for row in reqs if not row.purchase_dismissed]
    if requirement_ids is not None:
        wanted = {int(x) for x in requirement_ids}
        covered = _keys_of(reqs, wanted)
        reqs = [row for row in reqs if _req_key(row) in covered]
    if not reqs:
        return _empty(production_order_count=len(header_by_id))

    products = _products(db, headers)
    supplier_ids = {int(row.supplier_product_id) for row in reqs}
    suppliers = {
        int(row.id): row
        for row in db.scalars(
            select(SupplierProduct).where(SupplierProduct.id.in_(supplier_ids))
        ).all()
    }
    category_ids = {int(row.category_id) for row in suppliers.values() if row.category_id}
    categories = {}
    if category_ids:
        categories = {
            int(row.id): row.name
            for row in db.scalars(
                select(MaterialCategory).where(MaterialCategory.id.in_(category_ids))
            ).all()
        }
    reqs = [
        row
        for row in reqs
        if not is_tooling_category_name(
            categories.get(int(suppliers[int(row.supplier_product_id)].category_id))
            if suppliers.get(int(row.supplier_product_id))
            and suppliers[int(row.supplier_product_id)].category_id
            else None
        )
    ]
    if not reqs:
        return _empty(production_order_count=len(header_by_id))

    size_plan = _size_plan(db, tenant_id, set(header_by_id))
    reported = _reported_pairs(db, tenant_id, set(header_by_id))
    stock = _stock(db, tenant_id, supplier_ids)
    from app.services.material_service import in_transit_qty_by_pool_key

    transit_by_key = in_transit_qty_by_pool_key(db, tenant_id)
    po_qty_by_req = _po_qty_by_requirement(db, tenant_id, {int(row.id) for row in reqs})
    purchased_headers = _purchased_header_ids(db, tenant_id, set(header_by_id))
    counts = _workshop_counts(db, tenant_id, supplier_ids)
    colors = _colors(
        db,
        [h.color_id for h in headers] + [row.color_id for row in suppliers.values()],
    )
    sizes = _sizes(db, {row.size_id for row in reqs if row.size_id})
    partners = _partners(db, [row.partner_id for row in suppliers.values()])
    units = _units(db, [row.pricing_unit_id for row in suppliers.values()])

    grouped: dict[tuple[int, int | None], dict] = {}
    for req in reqs:
        header = header_by_id.get(int(req.header_id or 0))
        supplier = suppliers.get(int(req.supplier_product_id))
        if header is None or supplier is None:
            continue
        key = _req_key(req)
        demand, plan_pairs, reported_pairs = _remaining(req, header, size_plan, reported)
        product = products.get(int(header.own_product_id)) if header.own_product_id else None
        count_key = (int(header.id), key[0], key[1])
        counted = count_key in counts
        workshop = counts.get(count_key, _ZERO)
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "supplier_product_id": key[0],
                "size_id": key[1],
                "requirement_ids": [],
                "demand_qty": _ZERO,
                "required_qty": _ZERO,
                "unpurchased_qty": _ZERO,
                "buy_required_qty": _ZERO,
                "buy_workshop_qty": _ZERO,
                "buy_workshop_counted": False,
                "workshop_qty": _ZERO,
                "workshop_counted": False,
                "orders": [],
                "supplier": supplier,
            }
            grouped[key] = bucket
        placed, drafted = po_qty_by_req.get(int(req.id), (_ZERO, _ZERO))
        purchased = placed if placed < demand else demand
        covered_by_po = placed + drafted
        if covered_by_po > demand:
            covered_by_po = demand
        unpurchased = demand - covered_by_po
        # 这张生产单已经有草稿或已下单，整单不再进入待买。
        if int(header.id) in purchased_headers:
            unpurchased = _ZERO
        bucket["demand_qty"] += demand
        bucket["required_qty"] += _dec(req.required_qty)
        bucket["unpurchased_qty"] += unpurchased
        bucket["workshop_qty"] += workshop
        if counted:
            bucket["workshop_counted"] = True
        if unpurchased > 0:
            bucket["requirement_ids"].append(int(req.id))
            bucket["buy_required_qty"] += _dec(req.required_qty)
            bucket["buy_workshop_qty"] += workshop
            if counted:
                bucket["buy_workshop_counted"] = True
        bucket["orders"].append(
            {
                "header_id": int(header.id),
                "header_no": header.header_no,
                "requirement_id": int(req.id),
                "order_id": req.order_id,
                "sales_order_id": header.sales_order_id,
                "sales_order_line_id": header.sales_order_line_id,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "color_name": colors.get(int(header.color_id)) if header.color_id else None,
                "plan_qty": plan_pairs,
                "reported_qty": reported_pairs,
                "qty_per_pair": _qty_text(_dec(req.qty_per_pair)),
                "required_qty": _qty_text(_dec(req.required_qty)),
                "issued_qty": _qty_text(_dec(req.issued_qty)),
                "workshop_qty": _qty_text(workshop) if counted else None,
                "demand_qty": _qty_text(demand),
                "purchased_qty": _qty_text(purchased),
                "unpurchased_qty": _qty_text(unpurchased),
                "usage_by_size": bool(req.usage_by_size and req.size_id),
            }
        )

    lines = []
    for key, bucket in grouped.items():
        supplier = bucket["supplier"]
        warehouse = stock.get(key, _ZERO)
        purchased_need = _ZERO
        purchased_workshop = _ZERO
        for order in bucket["orders"]:
            purchased = _dec(order["purchased_qty"])
            if purchased <= 0:
                continue
            purchased_need += purchased
            purchased_workshop += _dec(order.get("workshop_qty"))
        transit_qty = transit_by_key.get(key, _ZERO)
        # 与仓库预警同一口径：现存 + 在途 + 已采购部分的车间剩余 − 已下单还要消耗。
        alert = warehouse + transit_qty + purchased_workshop - purchased_need
        shown_required = (
            bucket["buy_required_qty"]
            if bucket["unpurchased_qty"] > 0
            else bucket["required_qty"]
        )
        # 待采购 = 总用量 − 预警。缺口已被草稿或采购单盖满时不再买。
        to_buy = shown_required - alert if bucket["unpurchased_qty"] > 0 else _ZERO
        if to_buy < 0:
            to_buy = _ZERO
        counted = bool(bucket["buy_workshop_counted"])
        workshop = bucket["buy_workshop_qty"]
        size = sizes.get(int(key[1])) if key[1] else None
        partner = partners.get(int(supplier.partner_id)) if supplier.partner_id else None
        unit = units.get(int(supplier.pricing_unit_id)) if supplier.pricing_unit_id else None
        orders = sorted(bucket["orders"], key=lambda row: (row["header_no"] or "", row["header_id"]))
        first = orders[0]
        same_header = len({row["header_id"] for row in orders}) == 1
        image_urls = []
        for row in orders:
            url = row.get("product_image_url")
            if url and url not in image_urls:
                image_urls.append(url)
        lines.append(
            {
                "id": first["requirement_id"],
                "requirement_id": first["requirement_id"],
                "requirement_ids": bucket["requirement_ids"],
                "supplier_product_id": key[0],
                "supplier_product_code": supplier.product_code,
                "supplier_product_name": supplier.name,
                "category_name": (
                    categories.get(int(supplier.category_id)) if supplier.category_id else None
                ),
                "material_color_name": (
                    colors.get(int(supplier.color_id)) if supplier.color_id else None
                ),
                "image_url": supplier.image_url,
                "partner_id": supplier.partner_id,
                "partner_name": partner.name if partner else None,
                "pricing_unit_name": unit.name if unit else None,
                "unit_price": supplier.unit_price,
                "size_id": key[1],
                "size_value": size.size_value if size else None,
                "size_sort_order": size.sort_order if size else None,
                "header_id": first["header_id"] if same_header else None,
                "header_no": first["header_no"] if same_header else None,
                "production_order_id": first["header_id"] if same_header else None,
                "order_id": first["order_id"],
                "sales_order_id": first["sales_order_id"] if same_header else None,
                "sales_order_line_id": first["sales_order_line_id"] if same_header else None,
                "product_code": first["product_code"] if len(orders) == 1 else None,
                "product_image_url": image_urls[0] if image_urls else None,
                "product_image_urls": image_urls,
                "pair_qty": first["plan_qty"] if len(orders) == 1 else None,
                "qty_per_pair": first["qty_per_pair"] if len(orders) == 1 else None,
                "required_qty": shown_required,
                "demand_qty": bucket["demand_qty"],
                "warehouse_qty": warehouse,
                "alert_qty": alert,
                "draft_qty": _ZERO,
                "workshop_qty": workshop if counted else None,
                "workshop_counted": counted,
                "to_buy_qty": to_buy,
                "shortage_qty": to_buy,
                "net_demand": True,
                "orders": orders,
            }
        )
    lines.sort(
        key=lambda row: (
            (row.get("supplier_product_code") or "").casefold(),
            row.get("size_value") or "",
            row["supplier_product_id"],
        )
    )
    lines = [row for row in lines if _dec(row["to_buy_qty"]) > 0 or _dec(row["demand_qty"]) > 0]
    buy_lines = [row for row in lines if _dec(row["to_buy_qty"]) > 0]
    if only_shortage:
        # 同一物料只要还有码要买，待采购为 0 的码也留下，明细里照样显示。
        buying_products = {int(row["supplier_product_id"]) for row in buy_lines}
        shown = [row for row in lines if int(row["supplier_product_id"]) in buying_products]
    else:
        shown = lines
    requirement_ids_out = []
    for row in buy_lines:
        requirement_ids_out.extend(row["requirement_ids"])
    return {
        "kit_ok": not buy_lines,
        "shortage_lines": len(buy_lines),
        "to_buy_lines": len(buy_lines),
        "production_order_count": len(header_by_id),
        "lines": shown,
        "requirement_ids": requirement_ids_out,
    }


def lines_for_requirements(
    db: Session,
    tenant_id: int,
    requirement_ids: list[int],
) -> list[dict]:
    data = list_purchase_demand(
        db,
        tenant_id,
        requirement_ids={int(x) for x in requirement_ids},
        skip_dismissed=True,
    )
    return [row for row in data["lines"] if _dec(row["to_buy_qty"]) > 0]


def dismiss_purchase_demand(
    db: Session,
    tenant_id: int,
    requirement_ids: list[int],
) -> int:
    """从待买去掉这些用料。生产需求还在，只是不再列出、也不再生成采购草稿。"""
    ids = {int(x) for x in requirement_ids if int(x) > 0}
    if not ids:
        raise PurchaseDemandError("requirement_required", "请选择要删除的待买")
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.id.in_(ids),
            )
        ).all()
    )
    if not rows:
        raise PurchaseDemandError("requirement_not_found", "待买明细不存在")
    for row in rows:
        row.purchase_dismissed = True
    db.commit()
    return len(rows)


def save_workshop_count(
    db: Session,
    tenant_id: int,
    *,
    header_id: int,
    supplier_product_id: int,
    size_id: int | None,
    qty: Decimal,
    user_id: int | None,
    commit: bool = True,
) -> dict:
    row = upsert_workshop_count(
        db,
        tenant_id,
        header_id=header_id,
        supplier_product_id=supplier_product_id,
        size_id=size_id,
        qty=qty,
        user_id=user_id,
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "header_id": header_id,
        "supplier_product_id": supplier_product_id,
        "size_id": size_id,
        "qty": row.qty,
        "workshop_counted": True,
    }


def upsert_workshop_count(
    db: Session,
    tenant_id: int,
    *,
    header_id: int,
    supplier_product_id: int,
    size_id: int | None,
    qty: Decimal,
    user_id: int | None,
) -> WorkshopMaterialCount:
    if qty < 0:
        raise PurchaseDemandError("invalid_qty", "车间剩余不能为负")
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise PurchaseDemandError("header_not_found", "生产单不存在")
    product = db.get(SupplierProduct, supplier_product_id)
    if not product or product.tenant_id != tenant_id:
        raise PurchaseDemandError("material_not_found", "物料不存在")
    filters = [
        WorkshopMaterialCount.tenant_id == tenant_id,
        WorkshopMaterialCount.header_id == header_id,
        WorkshopMaterialCount.supplier_product_id == supplier_product_id,
    ]
    if size_id is None:
        filters.append(WorkshopMaterialCount.size_id.is_(None))
    else:
        filters.append(WorkshopMaterialCount.size_id == size_id)
    row = db.scalar(select(WorkshopMaterialCount).where(*filters))
    if row is None:
        row = WorkshopMaterialCount(
            tenant_id=tenant_id,
            header_id=header_id,
            supplier_product_id=supplier_product_id,
            size_id=size_id,
            qty=qty,
            counted_by=user_id,
        )
        db.add(row)
    else:
        row.qty = qty
        row.counted_by = user_id
    return row


def adjust_workshop_count(
    db: Session,
    tenant_id: int,
    *,
    header_id: int,
    supplier_product_id: int,
    size_id: int | None,
    delta: Decimal,
    user_id: int | None = None,
) -> WorkshopMaterialCount:
    """领料 +delta、退料 −delta；无台账从 0 起算，结果不小于 0。"""
    delta = _dec(delta)
    filters = [
        WorkshopMaterialCount.tenant_id == tenant_id,
        WorkshopMaterialCount.header_id == header_id,
        WorkshopMaterialCount.supplier_product_id == supplier_product_id,
    ]
    if size_id is None:
        filters.append(WorkshopMaterialCount.size_id.is_(None))
    else:
        filters.append(WorkshopMaterialCount.size_id == size_id)
    row = db.scalar(select(WorkshopMaterialCount).where(*filters))
    current = _dec(row.qty) if row is not None else _ZERO
    new_qty = current + delta
    if new_qty < 0:
        new_qty = _ZERO
    return upsert_workshop_count(
        db,
        tenant_id,
        header_id=header_id,
        supplier_product_id=supplier_product_id,
        size_id=size_id,
        qty=new_qty,
        user_id=user_id,
    )


def list_workshop_count_targets(
    db: Session,
    tenant_id: int,
    header_id: int,
    process_def_ids: set[int],
) -> list[dict]:
    """本次报工要清点的车间剩余：该工序消耗的料，分码则一码一行。"""
    if not process_def_ids:
        return []
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header_id,
                OrderMaterialRequirement.consume_process_id.in_(process_def_ids),
            )
        ).all()
    )
    if not reqs:
        return []
    supplier_ids = {int(row.supplier_product_id) for row in reqs}
    suppliers = {
        int(row.id): row
        for row in db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(supplier_ids))).all()
    }
    category_ids = {int(row.category_id) for row in suppliers.values() if row.category_id}
    categories = {}
    if category_ids:
        categories = {
            int(row.id): row.name
            for row in db.scalars(select(MaterialCategory).where(MaterialCategory.id.in_(category_ids))).all()
        }
    size_ids = {int(row.size_id) for row in reqs if row.size_id}
    sizes = {
        int(row.id): row.size_value
        for row in db.scalars(select(Size).where(Size.id.in_(size_ids))).all()
    } if size_ids else {}
    unit_ids = {int(row.pricing_unit_id) for row in suppliers.values() if row.pricing_unit_id}
    units = {
        int(row.id): row.name
        for row in db.scalars(select(PricingUnit).where(PricingUnit.id.in_(unit_ids))).all()
    } if unit_ids else {}
    counts = _workshop_counts(db, tenant_id, supplier_ids, header_id=header_id)
    grouped: dict[tuple[int, int | None], dict] = {}
    for req in reqs:
        supplier = suppliers.get(int(req.supplier_product_id))
        if supplier is None:
            continue
        category = (
            categories.get(int(supplier.category_id))
            if supplier.category_id
            else None
        )
        if is_tooling_category_name(category):
            continue
        key = _req_key(req)
        bucket = grouped.get(key)
        if bucket is None:
            size_value = sizes.get(int(key[1])) if key[1] else None
            name = supplier.name or supplier.product_code or "物料"
            label = f"{name} {size_value}码" if size_value else name
            last = counts.get((header_id, key[0], key[1]))
            bucket = {
                "supplier_product_id": key[0],
                "size_id": key[1],
                "header_id": header_id,
                "supplier_product_code": supplier.product_code,
                "supplier_product_name": supplier.name,
                "size_value": size_value,
                "unit_name": units.get(int(supplier.pricing_unit_id)) if supplier.pricing_unit_id else None,
                "label": label,
                "last_qty": _qty_text(last) if last is not None else None,
                "process_ids": [],
            }
            grouped[key] = bucket
        if req.consume_process_id and int(req.consume_process_id) not in bucket["process_ids"]:
            bucket["process_ids"].append(int(req.consume_process_id))
    return sorted(grouped.values(), key=lambda row: (row["label"], row["supplier_product_id"], row["size_id"] or 0))


def require_workshop_counts(
    db: Session,
    tenant_id: int,
    header_id: int,
    process_def_ids: set[int],
    counts: list[dict] | None,
    user_id: int | None,
) -> None:
    """报工消耗这些料时，必须带上车间剩余。写入与报工同一事务。"""
    targets = list_workshop_count_targets(db, tenant_id, header_id, process_def_ids)
    if not targets:
        return
    provided: dict[tuple[int, int | None], Decimal] = {}
    for raw in counts or []:
        if not raw:
            continue
        supplier_product_id = int(raw.get("supplier_product_id") or 0)
        size_raw = raw.get("size_id")
        size_id = int(size_raw) if size_raw else None
        if raw.get("qty") is None or raw.get("qty") == "":
            continue
        qty = _dec(raw.get("qty"))
        if qty < 0:
            raise PurchaseDemandError("invalid_qty", "车间剩余不能为负")
        provided[(supplier_product_id, size_id)] = qty
    missing = [
        row["label"]
        for row in targets
        if (int(row["supplier_product_id"]), int(row["size_id"]) if row.get("size_id") else None) not in provided
    ]
    if missing:
        raise PurchaseDemandError("workshop_count_required", "报工前请清点车间剩余：" + "、".join(missing))
    for row in targets:
        key = (int(row["supplier_product_id"]), int(row["size_id"]) if row.get("size_id") else None)
        save_workshop_count(
            db,
            tenant_id,
            header_id=header_id,
            supplier_product_id=key[0],
            size_id=key[1],
            qty=provided[key],
            user_id=user_id,
            commit=False,
        )


def record_size_output(
    db: Session,
    tenant_id: int,
    *,
    header_id: int,
    process_id: int,
    size_id: int,
    qty: int,
    work_log_id: int | None = None,
) -> None:
    if qty <= 0:
        return
    db.add(
        ProcessSizeOutput(
            tenant_id=tenant_id,
            header_id=header_id,
            process_id=process_id,
            size_id=size_id,
            qty=int(qty),
            work_log_id=work_log_id,
        )
    )


def sized_process_ids_for_header(db: Session, tenant_id: int, header_id: int) -> set[int]:
    """这张生产单上，分码料的消耗工序。"""
    rows = db.scalars(
        select(OrderMaterialRequirement.consume_process_id).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.header_id == header_id,
            OrderMaterialRequirement.usage_by_size.is_(True),
            OrderMaterialRequirement.consume_process_id.is_not(None),
        )
    ).all()
    return {int(row) for row in rows}


def _empty(production_order_count: int = 0) -> dict:
    return {
        "kit_ok": True,
        "shortage_lines": 0,
        "to_buy_lines": 0,
        "production_order_count": production_order_count,
        "lines": [],
        "requirement_ids": [],
    }


def _req_key(req: OrderMaterialRequirement) -> tuple[int, int | None]:
    size_id = int(req.size_id) if req.usage_by_size and req.size_id else None
    return (int(req.supplier_product_id), size_id)


def _keys_of(reqs: list[OrderMaterialRequirement], wanted: set[int]) -> set[tuple[int, int | None]]:
    return {_req_key(row) for row in reqs if int(row.id) in wanted}


def progress_requirement_balance(db: Session, tenant_id: int) -> dict[int, dict]:
    """生产进度仓库弹层：按列表排序优先占用仓库库存。

    需求是报工后的生产需求。缺口再减去本单车间剩余，以及前面生产单占用后剩下的仓库库存。
    排序与生产进度默认列表一致：人工顺序、加急、交期。
    """
    rush_exists = (
        select(SpecExecutionOrder.id)
        .where(
            SpecExecutionOrder.header_id == ExecutionHeader.id,
            SpecExecutionOrder.is_rush.is_(True),
        )
        .exists()
    )
    rush_rank = case((rush_exists, 1), else_=0)
    headers = list(
        db.scalars(
            select(ExecutionHeader)
            .where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.status.in_(_OPEN_HEADER),
            )
            .order_by(
                ExecutionHeader.schedule_sequence.is_(None),
                ExecutionHeader.schedule_sequence.asc(),
                rush_rank.desc(),
                ExecutionHeader.delivery_date.is_(None),
                ExecutionHeader.delivery_date.asc(),
                ExecutionHeader.id.asc(),
            )
        ).all()
    )
    header_by_id = {int(row.id): row for row in headers}
    if not header_by_id:
        return {}
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement)
            .where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id.in_(header_by_id),
                OrderMaterialRequirement.is_customer_supplied.is_(False),
            )
            .order_by(OrderMaterialRequirement.id)
        ).all()
    )
    if not reqs:
        return {}
    supplier_ids = {int(row.supplier_product_id) for row in reqs}
    suppliers = {
        int(row.id): row
        for row in db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(supplier_ids))).all()
    }
    category_ids = {int(row.category_id) for row in suppliers.values() if row.category_id}
    categories = {}
    if category_ids:
        categories = {
            int(row.id): row.name
            for row in db.scalars(select(MaterialCategory).where(MaterialCategory.id.in_(category_ids))).all()
        }
    reqs = [
        row
        for row in reqs
        if not is_tooling_category_name(
            categories.get(int(suppliers[int(row.supplier_product_id)].category_id))
            if suppliers.get(int(row.supplier_product_id)) and suppliers[int(row.supplier_product_id)].category_id
            else None
        )
    ]
    if not reqs:
        return {}
    by_header: dict[int, list[OrderMaterialRequirement]] = {}
    for row in reqs:
        by_header.setdefault(int(row.header_id or 0), []).append(row)
    size_plan = _size_plan(db, tenant_id, set(header_by_id))
    reported = _reported_pairs(db, tenant_id, set(header_by_id))
    stock = _stock(db, tenant_id, supplier_ids)
    counts = _workshop_counts(db, tenant_id, supplier_ids)
    out: dict[int, dict] = {}
    for header in headers:
        for req in by_header.get(int(header.id), []):
            demand, _, _ = _remaining(req, header, size_plan, reported)
            key = _req_key(req)
            workshop = counts.get((int(header.id), key[0], key[1]), _ZERO)
            need = demand - workshop
            if need < 0:
                need = _ZERO
            pool = stock.get(key, _ZERO)
            take = need if need < pool else pool
            stock[key] = pool - take
            out[int(req.id)] = {
                "header_id": int(header.id),
                "demand_qty": demand,
                "shortage_qty": need - take,
            }
    return out


def progress_header_shortage_counts(db: Session, tenant_id: int) -> dict[int, int]:
    """每张未完成生产单里，按仓库弹层算法仍有缺口的物料行数。"""
    counts: dict[int, int] = {}
    for row in progress_requirement_balance(db, tenant_id).values():
        header_id = int(row["header_id"])
        counts.setdefault(header_id, 0)
        if row["shortage_qty"] > 0:
            counts[header_id] += 1
    return counts


def apply_progress_material_view(db: Session, tenant_id: int, kit: dict) -> dict:
    """只改生产进度仓库弹层看到的需求和缺口，不动齐套和待采购计算。"""
    balance = progress_requirement_balance(db, tenant_id)
    lines = kit.get("lines") or []
    for line in lines:
        row = balance.get(int(line.get("id") or 0))
        if row is None:
            continue
        line["required_qty"] = row["demand_qty"]
        line["shortage_qty"] = row["shortage_qty"]
        line["kit_ok"] = row["shortage_qty"] <= 0
    shortage_lines = [ln for ln in lines if _dec(ln.get("shortage_qty")) > 0]
    kit["shortage_lines"] = len(shortage_lines)
    kit["kit_ok"] = not shortage_lines and not kit.get("empty_bom")
    return kit


def _open_headers(db: Session, tenant_id: int, sales_order_id: int | None) -> list[ExecutionHeader]:
    header_q = select(ExecutionHeader).where(
        ExecutionHeader.tenant_id == tenant_id,
        ExecutionHeader.status.in_(_OPEN_HEADER),
    )
    if sales_order_id is not None:
        allocated_header_ids = (
            select(SpecExecutionOrder.header_id)
            .join(ExecutionAllocation, ExecutionAllocation.execution_id == SpecExecutionOrder.id)
            .where(
                ExecutionAllocation.tenant_id == tenant_id,
                ExecutionAllocation.sales_order_id == sales_order_id,
                SpecExecutionOrder.header_id.is_not(None),
            )
        )
        header_q = header_q.where(
            or_(
                ExecutionHeader.sales_order_id == sales_order_id,
                ExecutionHeader.id.in_(allocated_header_ids),
            )
        )
    return list(db.scalars(header_q.order_by(ExecutionHeader.id)).all())


def _remaining(
    req: OrderMaterialRequirement,
    header: ExecutionHeader,
    size_plan: dict[int, dict[int, int]],
    reported: dict[tuple[int, int], Decimal],
) -> tuple[Decimal, int, int]:
    """返回生产需求、计划双数、报工双数。

    分码料的报工没有码，不能拿总双数去减某一码。生产需求保持该码的用量，
    实际还要多少只再减车间剩余和仓库现存。
    有码数时，待买里的双数是各码数量之和，不是单独一个码。
    """
    required = _dec(req.required_qty)
    usage = _dec(req.qty_per_pair) * _dec(req.size_coeff or 1) * (Decimal("1") + _dec(req.loss_rate))
    reported_pairs = _ZERO
    if req.consume_process_id:
        reported_pairs = reported.get((int(header.id), int(req.consume_process_id)), _ZERO)
    if req.usage_by_size and req.size_id:
        header_sizes = size_plan.get(int(header.id), {})
        plan = int(sum(header_sizes.values())) if header_sizes else int(header.total_qty or 0)
        demand = required
    else:
        plan = int(header.total_qty or 0)
        demand = required - usage * reported_pairs
        if demand < 0:
            demand = _ZERO
    return demand, plan, int(reported_pairs)


def _size_plan(db: Session, tenant_id: int, header_ids: set[int]) -> dict[int, dict[int, int]]:
    rows = db.execute(
        select(
            SpecExecutionOrder.header_id,
            SpecExecutionOrder.size_id,
            func.coalesce(func.sum(SpecExecutionOrder.total_qty), 0),
        )
        .where(
            SpecExecutionOrder.tenant_id == tenant_id,
            SpecExecutionOrder.header_id.in_(header_ids),
        )
        .group_by(SpecExecutionOrder.header_id, SpecExecutionOrder.size_id)
    ).all()
    out: dict[int, dict[int, int]] = {}
    for header_id, size_id, qty in rows:
        if header_id and size_id:
            out.setdefault(int(header_id), {})[int(size_id)] = int(qty or 0)
    return out


def _reported_pairs(db: Session, tenant_id: int, header_ids: set[int]) -> dict[tuple[int, int], Decimal]:
    rows = db.execute(
        select(
            WorkLog.header_id,
            WorkLog.process_id,
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
        )
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.header_id.in_(header_ids),
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.report_type != ReportType.rework,
        )
        .group_by(WorkLog.header_id, WorkLog.process_id)
    ).all()
    return {
        (int(header_id), int(process_id)): _dec(qty)
        for header_id, process_id, qty in rows
        if header_id and process_id
    }


def _stock(db: Session, tenant_id: int, supplier_ids: set[int]) -> dict[tuple[int, int | None], Decimal]:
    """现存 = 公用池 + 还没领出车间的占用。占用不再单独锁给某一张单。"""
    rows = db.scalars(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id.in_(supplier_ids),
        )
    ).all()
    out: dict[tuple[int, int | None], Decimal] = {}
    for row in rows:
        key = (int(row.supplier_product_id), int(row.size_id) if row.size_id else None)
        out[key] = out.get(key, _ZERO) + _dec(row.qty)
    occ_rows = db.execute(
        select(
            OrderMaterialRequirement.supplier_product_id,
            OrderMaterialRequirement.usage_by_size,
            OrderMaterialRequirement.size_id,
            func.coalesce(func.sum(OrderMaterialRequirement.arrived_qty), 0),
            func.coalesce(func.sum(OrderMaterialRequirement.issued_qty), 0),
        )
        .where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.supplier_product_id.in_(supplier_ids),
            OrderMaterialRequirement.is_customer_supplied.is_(False),
        )
        .group_by(
            OrderMaterialRequirement.supplier_product_id,
            OrderMaterialRequirement.usage_by_size,
            OrderMaterialRequirement.size_id,
        )
    ).all()
    for supplier_id, usage_by_size, size_id, arrived, issued in occ_rows:
        key = (
            int(supplier_id),
            int(size_id) if usage_by_size and size_id is not None else None,
        )
        occupied = _dec(arrived) - _dec(issued)
        if occupied > 0:
            out[key] = out.get(key, _ZERO) + occupied
    return out


_PLACED_PO = (
    PurchaseOrderStatus.ordered,
    PurchaseOrderStatus.shipped,
    PurchaseOrderStatus.partial_received,
    PurchaseOrderStatus.received,
)


def _purchased_header_ids(db: Session, tenant_id: int, header_ids: set[int]) -> set[int]:
    """已经挂过采购草稿或已下单的生产单。取消的采购单不算。"""
    if not header_ids:
        return set()
    rows = db.execute(
        select(OrderMaterialRequirement.header_id)
        .join(
            PurchaseOrderLine,
            PurchaseOrderLine.order_material_requirement_id == OrderMaterialRequirement.id,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.header_id.in_(header_ids),
            PurchaseOrder.status.in_((*_PLACED_PO, PurchaseOrderStatus.draft)),
            PurchaseOrderLine.qty > 0,
        )
        .distinct()
    ).all()
    return {int(header_id) for (header_id,) in rows if header_id}


def _po_qty_by_requirement(
    db: Session,
    tenant_id: int,
    requirement_ids: set[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    """按生产用料汇总采购数量，返回 (已下单, 草稿)。"""
    if not requirement_ids:
        return {}
    rows = db.execute(
        select(
            PurchaseOrderLine.order_material_requirement_id,
            PurchaseOrder.status,
            func.coalesce(func.sum(PurchaseOrderLine.qty), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id.in_(requirement_ids),
            PurchaseOrder.status.in_((*_PLACED_PO, PurchaseOrderStatus.draft)),
        )
        .group_by(PurchaseOrderLine.order_material_requirement_id, PurchaseOrder.status)
    ).all()
    out: dict[int, tuple[Decimal, Decimal]] = {}
    for requirement_id, status, qty in rows:
        if not requirement_id:
            continue
        placed, drafted = out.get(int(requirement_id), (_ZERO, _ZERO))
        amount = _dec(qty)
        status_value = status.value if hasattr(status, "value") else str(status)
        if status_value == PurchaseOrderStatus.draft.value:
            drafted += amount
        else:
            placed += amount
        out[int(requirement_id)] = (placed, drafted)
    return out


def _workshop_counts(
    db: Session,
    tenant_id: int,
    supplier_ids: set[int],
    *,
    header_id: int | None = None,
) -> dict[tuple[int, int, int | None], Decimal]:
    """键 = (header_id, supplier_product_id, size_id)。"""
    if not supplier_ids:
        return {}
    filters = [
        WorkshopMaterialCount.tenant_id == tenant_id,
        WorkshopMaterialCount.supplier_product_id.in_(supplier_ids),
    ]
    if header_id is not None:
        filters.append(WorkshopMaterialCount.header_id == header_id)
    rows = db.scalars(select(WorkshopMaterialCount).where(*filters)).all()
    return {
        (
            int(row.header_id),
            int(row.supplier_product_id),
            int(row.size_id) if row.size_id else None,
        ): _dec(row.qty)
        for row in rows
    }


def _products(db: Session, headers: list[ExecutionHeader]) -> dict[int, OwnProduct]:
    ids = {int(row.own_product_id) for row in headers if row.own_product_id}
    if not ids:
        return {}
    return {int(row.id): row for row in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(ids))).all()}


def _colors(db: Session, color_ids: list[int | None]) -> dict[int, str]:
    ids = {int(row) for row in color_ids if row}
    if not ids:
        return {}
    return {int(row.id): row.name for row in db.scalars(select(Color).where(Color.id.in_(ids))).all()}


def _sizes(db: Session, size_ids: set[int | None]) -> dict[int, Size]:
    ids = {int(row) for row in size_ids if row}
    if not ids:
        return {}
    return {int(row.id): row for row in db.scalars(select(Size).where(Size.id.in_(ids))).all()}


def _partners(db: Session, partner_ids: list[int | None]) -> dict[int, Partner]:
    ids = {int(row) for row in partner_ids if row}
    if not ids:
        return {}
    return {int(row.id): row for row in db.scalars(select(Partner).where(Partner.id.in_(ids))).all()}


def _units(db: Session, unit_ids: list[int | None]) -> dict[int, PricingUnit]:
    ids = {int(row) for row in unit_ids if row}
    if not ids:
        return {}
    return {int(row.id): row for row in db.scalars(select(PricingUnit).where(PricingUnit.id.in_(ids))).all()}
