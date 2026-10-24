"""待采购 = 总用量 − 预警。

预警与仓库同一口径：现存 + 在途 + 已采购部分的车间剩余 − 已下采购单的生产用量。
一笔生产单只能采购一次。草稿或已下单挂到这张生产单的任一用料上，整张生产单都离开待买。
材料已经完全过用、整单不再出现在待买里时，同样离开待买，并按生产用量计入仓库实际需求。
仓库的实际需求按生产单：生成过采购单，或材料已经不在待买里，上面的全部物料都按生产用量计，不用等已反馈。不按采购单数量截断，再减车间剩余。

不分码的料用消耗工序段的完工减。完工与生产进度相同：段内按最低完成率折算，不把各工序相加。
分码的料报工没有码，生产需求按该码用量全额计算，
再减车间剩余和仓库现存。车间剩余是各人最新一次清点的合计；还没人清点时按领料加、退料减。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

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
    ProcessDefinition,
    ProcessSegment,
    ProcessSizeOutput,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
    WorkLog,
    WorkLogStatus,
    WorkshopMaterialCount,
    WorkshopMaterialCountLog,
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
    reported_process, reported_segment = _reported_pairs(db, tenant_id, set(header_by_id))
    stock = _stock(db, tenant_id, supplier_ids)
    from app.services.material_service import in_transit_qty_by_pool_key

    transit_by_key = in_transit_qty_by_pool_key(db, tenant_id, include_draft=True)
    po_qty_by_req = _po_qty_by_requirement(db, tenant_id, {int(row.id) for row in reqs})
    purchased_headers = _purchased_header_ids(db, tenant_id, set(header_by_id))
    counts = _workshop_counts(db, tenant_id, supplier_ids)
    pick_return = _posted_pick_return(db, tenant_id, {int(row.id) for row in reqs})
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
        demand, plan_pairs, reported_pairs = _remaining(
            req, header, size_plan, reported_process, reported_segment
        )
        product = products.get(int(header.own_product_id)) if header.own_product_id else None
        picked, returned = pick_return.get(int(req.id), (_ZERO, _ZERO))
        net_issued = _dec(req.issued_qty)
        if picked <= 0 and returned <= 0 and net_issued > 0:
            picked = net_issued
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
        has_purchase = placed > 0 or drafted > 0
        covered_by_po = placed + drafted
        if covered_by_po > demand:
            covered_by_po = demand
        unpurchased = demand - covered_by_po
        # 这张生产单已经有草稿或已下单：整单离开待买，全部物料计入实际需求。
        if int(header.id) in purchased_headers:
            unpurchased = _ZERO
            has_purchase = True
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
                "scrap_qty": 0,
                "scrap_material_qty": "0",
                "picked_qty": _qty_text(picked),
                "returned_qty": _qty_text(returned),
                "reported_qty": _pair_num(reported_pairs),
                "qty_per_pair": _qty_text(_dec(req.qty_per_pair)),
                "required_qty": _qty_text(_dec(req.required_qty)),
                "issued_qty": _qty_text(_dec(req.issued_qty)),
                "workshop_qty": _qty_text(workshop) if counted else None,
                "demand_qty": _qty_text(demand),
                "purchased_qty": _qty_text(purchased),
                "has_purchase": has_purchase,
                "unpurchased_qty": _qty_text(unpurchased),
                "usage_by_size": bool(req.usage_by_size and req.size_id),
            }
        )

    _append_confirmed_scrap_demand(db, tenant_id, grouped, header_by_id, reqs)

    if requirement_ids is None:
        _include_headers_absent_from_buy(grouped, stock, transit_by_key)

    lines = []
    for key, bucket in grouped.items():
        supplier = bucket["supplier"]
        warehouse = stock.get(key, _ZERO)
        purchased_need = _ZERO
        purchased_workshop = _ZERO
        for order in bucket["orders"]:
            if not order.get("has_purchase"):
                continue
            # 这张生产单已生成采购单，这种物料按生产用量计入实际需求。
            purchased_need += _dec(order.get("demand_qty"))
            purchased_workshop += _dec(order.get("workshop_qty"))
        transit_qty = transit_by_key.get(key, _ZERO)
        # 与仓库预警同一口径：现存 + 在途 + 已采购部分的车间剩余 − 已下采购单的生产用量。
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
        all_orders = sorted(bucket["orders"], key=lambda row: (row["header_no"] or "", row["header_id"]))
        # 已采购的生产单整单离开待买。同一物料还要给别的单买时，不再把旧单带出来。
        orders = (
            [row for row in all_orders if _dec(row["unpurchased_qty"]) > 0]
            if only_shortage
            else all_orders
        )
        first = (orders or all_orders)[0]
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
        snapshot=True,
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
    snapshot: bool = False,
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
    if snapshot:
        db.add(
            WorkshopMaterialCountLog(
                tenant_id=tenant_id,
                header_id=header_id,
                supplier_product_id=supplier_product_id,
                size_id=size_id,
                qty=qty,
                counted_by=user_id,
            )
        )
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


def _consume_segment_ids(db: Session, tenant_id: int, process_def_ids: set[int]) -> set[int]:
    """报工工序对应的消耗工序段。物料按段归属，不按具体工序。"""
    if not process_def_ids:
        return set()
    rows = db.scalars(
        select(ProcessDefinition.segment_id).where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.id.in_(process_def_ids),
            ProcessDefinition.segment_id.is_not(None),
        )
    ).all()
    return {int(row) for row in rows}


def list_workshop_count_targets(
    db: Session,
    tenant_id: int,
    header_id: int,
    process_def_ids: set[int],
    employee_id: int | None = None,
    segment_ids: set[int] | None = None,
) -> list[dict]:
    """本次报工要清点的车间剩余：该工序所属工序段消耗的料，分码则一码一行。"""
    segment_ids = {int(item) for item in (segment_ids or set()) if int(item) > 0} or _consume_segment_ids(
        db, tenant_id, process_def_ids
    )
    if not segment_ids:
        return []
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header_id,
                OrderMaterialRequirement.consume_segment_id.in_(segment_ids),
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
    carry = (
        _carry_qty(db, tenant_id, header_id, int(employee_id), supplier_ids)
        if employee_id
        else {}
    )
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
            count_key = (header_id, key[0], key[1])
            if employee_id:
                last = carry.get(count_key)
            else:
                last = counts.get(count_key)
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


def _first_process_segment_id(db: Session, tenant_id: int) -> int | None:
    return db.scalar(
        select(ProcessSegment.id)
        .where(ProcessSegment.tenant_id == tenant_id, ProcessSegment.is_active.is_(True))
        .order_by(ProcessSegment.sort_order.asc(), ProcessSegment.id.asc())
        .limit(1)
    )


def require_workshop_counts(
    db: Session,
    tenant_id: int,
    header_id: int,
    process_def_ids: set[int],
    counts: list[dict] | None,
    user_id: int | None,
) -> None:
    """只有第一个工序段报工才清点车间剩余。后面的工序段直接报。"""
    segment_ids = _consume_segment_ids(db, tenant_id, process_def_ids)
    first_id = _first_process_segment_id(db, tenant_id)
    if first_id is None or first_id not in segment_ids:
        return
    targets = list_workshop_count_targets(
        db, tenant_id, header_id, process_def_ids, segment_ids={first_id}
    )
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


def _append_confirmed_scrap_demand(
    db: Session,
    tenant_id: int,
    grouped: dict,
    header_by_id: dict[int, ExecutionHeader],
    reqs: list[OrderMaterialRequirement],
) -> None:
    """已确认报废补料加到主生产单的用量上。不另开一行，也不增加待买。"""
    from app.services.trace_service import confirmed_scrap_requirement_qty

    extra = confirmed_scrap_requirement_qty(db, tenant_id, set(header_by_id))
    if not extra:
        return
    req_by_id = {int(row.id): row for row in reqs}
    for requirement_id, qty in extra.items():
        if qty <= 0:
            continue
        req = req_by_id.get(int(requirement_id))
        header = header_by_id.get(int(req.header_id or 0)) if req is not None else None
        if req is None or header is None:
            continue
        bucket = grouped.get(_req_key(req))
        if bucket is None:
            continue
        target = next(
            (
                order
                for order in bucket["orders"]
                if int(order.get("requirement_id") or 0) == int(req.id)
            ),
            None,
        )
        if target is None:
            continue
        # 报废双数单独给悬停层。数量保持原计划。总用量加上补料。
        # 待买仍按未采购的原用量算，补料不另列、也不抬高待采购。
        usage = (
            _dec(req.qty_per_pair)
            * _dec(req.size_coeff or 1)
            * (Decimal("1") + _dec(req.loss_rate))
        )
        pairs = qty / usage if usage > 0 else qty
        target["scrap_qty"] = _pair_num(_dec(target.get("scrap_qty")) + pairs)
        target["scrap_material_qty"] = _qty_text(_dec(target.get("scrap_material_qty")) + qty)
        target["demand_qty"] = _qty_text(_dec(target.get("demand_qty")) + qty)
        bucket["demand_qty"] += qty


def _posted_pick_return(
    db: Session,
    tenant_id: int,
    requirement_ids: set[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    """已过账领料、退料，按用料行分开。作废和未确认的不算。"""
    if not requirement_ids:
        return {}
    rows = db.execute(
        select(
            StockDocLine.order_material_requirement_id,
            StockDoc.doc_type,
            func.coalesce(func.sum(StockDocLine.qty), 0),
        )
        .join(StockDoc, StockDoc.id == StockDocLine.stock_doc_id)
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.status == StockDocStatus.posted,
            StockDoc.doc_type.in_((StockDocType.issue, StockDocType.return_mat)),
            StockDocLine.order_material_requirement_id.in_(requirement_ids),
        )
        .group_by(StockDocLine.order_material_requirement_id, StockDoc.doc_type)
    ).all()
    out: dict[int, tuple[Decimal, Decimal]] = {}
    for requirement_id, doc_type, qty in rows:
        if not requirement_id:
            continue
        picked, returned = out.get(int(requirement_id), (_ZERO, _ZERO))
        kind = doc_type.value if hasattr(doc_type, "value") else str(doc_type)
        amount = _dec(qty)
        if kind == StockDocType.return_mat.value:
            returned += amount
        else:
            picked += amount
        out[int(requirement_id)] = (picked, returned)
    return out


def _req_key(req: OrderMaterialRequirement) -> tuple[int, int | None]:
    size_id = int(req.size_id) if req.usage_by_size and req.size_id else None
    return (int(req.supplier_product_id), size_id)


def _keys_of(reqs: list[OrderMaterialRequirement], wanted: set[int]) -> set[tuple[int, int | None]]:
    return {_req_key(row) for row in reqs if int(row.id) in wanted}


def _preview_to_buy(bucket: dict, warehouse: Decimal, transit: Decimal) -> Decimal:
    purchased_need = _ZERO
    purchased_workshop = _ZERO
    for order in bucket["orders"]:
        if not order.get("has_purchase"):
            continue
        purchased_need += _dec(order.get("demand_qty"))
        purchased_workshop += _dec(order.get("workshop_qty"))
    alert = warehouse + transit + purchased_workshop - purchased_need
    unpurchased = _dec(bucket["unpurchased_qty"])
    shown_required = bucket["buy_required_qty"] if unpurchased > 0 else bucket["required_qty"]
    to_buy = shown_required - alert if unpurchased > 0 else _ZERO
    return to_buy if to_buy > 0 else _ZERO


def _rebuild_buy_totals(bucket: dict) -> None:
    bucket["unpurchased_qty"] = _ZERO
    bucket["requirement_ids"] = []
    bucket["buy_required_qty"] = _ZERO
    bucket["buy_workshop_qty"] = _ZERO
    bucket["buy_workshop_counted"] = False
    for order in bucket["orders"]:
        unpurchased = _dec(order.get("unpurchased_qty"))
        bucket["unpurchased_qty"] += unpurchased
        if unpurchased <= 0:
            continue
        bucket["requirement_ids"].append(int(order["requirement_id"]))
        bucket["buy_required_qty"] += _dec(order.get("required_qty"))
        if order.get("workshop_qty") is not None:
            bucket["buy_workshop_qty"] += _dec(order.get("workshop_qty"))
            bucket["buy_workshop_counted"] = True


def _include_headers_absent_from_buy(
    grouped: dict[tuple[int, int | None], dict],
    stock: dict[tuple[int, int | None], Decimal],
    transit_by_key: dict[tuple[int, int | None], Decimal],
) -> None:
    """整张生产单的材料都不在待买里时，按已采购计入实际需求，并不再列为待买。"""
    buying_suppliers: set[int] = set()
    for key, bucket in grouped.items():
        if _preview_to_buy(bucket, stock.get(key, _ZERO), transit_by_key.get(key, _ZERO)) > 0:
            buying_suppliers.add(int(key[0]))
    in_buy: set[int] = set()
    for key, bucket in grouped.items():
        if int(key[0]) not in buying_suppliers:
            continue
        for order in bucket["orders"]:
            if _dec(order.get("unpurchased_qty")) > 0:
                in_buy.add(int(order["header_id"]))
    for bucket in grouped.values():
        changed = False
        for order in bucket["orders"]:
            if int(order["header_id"]) in in_buy:
                continue
            if order.get("has_purchase") and _dec(order.get("unpurchased_qty")) <= 0:
                continue
            order["has_purchase"] = True
            order["unpurchased_qty"] = "0"
            changed = True
        if changed:
            _rebuild_buy_totals(bucket)


def _buy_header_ids(db: Session, tenant_id: int) -> set[int]:
    """待买明细里还列着的生产单。"""
    data = list_purchase_demand(db, tenant_id)
    ids: set[int] = set()
    for line in data["lines"]:
        if _dec(line.get("to_buy_qty")) <= 0:
            continue
        for order in line.get("orders") or []:
            if _dec(order.get("unpurchased_qty")) > 0:
                ids.add(int(order["header_id"]))
    return ids


def progress_requirement_balance(db: Session, tenant_id: int) -> dict[int, dict]:
    """生产进度仓库弹层：按列表排序优先占用仓库库存。

    需求是报工后的生产需求。已生成采购单，或材料已经不在待买里的生产单，按列表顺序占用：先扣车间剩余，再扣仓库现存量。
    后面的单看到的是前面扣完剩下的。还在待买里的不占用。
    排序与生产进度默认列表一致：拖过的按人工顺序，其余按创建时间，后开的在最后。
    """
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
                ExecutionHeader.created_at.asc(),
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
    buy_headers = _buy_header_ids(db, tenant_id)
    size_plan = _size_plan(db, tenant_id, set(header_by_id))
    reported_process, reported_segment = _reported_pairs(db, tenant_id, set(header_by_id))
    stock = _stock(db, tenant_id, supplier_ids)
    opening_stock = dict(stock)
    counts = _workshop_counts(db, tenant_id, supplier_ids)
    workshop_pool: dict[tuple[int, int | None], Decimal] = {}
    for (_hid, spid, size_id), qty in counts.items():
        key = (spid, size_id)
        workshop_pool[key] = workshop_pool.get(key, _ZERO) + qty
    warehouse_pool = dict(opening_stock)
    out: dict[int, dict] = {}
    for header in headers:
        occupies = int(header.id) not in buy_headers
        usage_by_key: dict[tuple[int, int | None], Decimal] = {}
        seen_keys: set[tuple[int, int | None]] = set()
        for req in by_header.get(int(header.id), []):
            demand, _, reported_pairs = _remaining(req, header, size_plan, reported_process, reported_segment)
            key = _req_key(req)
            own_workshop = counts.get((int(header.id), key[0], key[1]), _ZERO)
            need = demand - own_workshop
            if need < 0:
                need = _ZERO
            pool = stock.get(key, _ZERO)
            take = need if occupies and need < pool else (pool if occupies else _ZERO)
            if occupies:
                stock[key] = pool - take
            task = _remaining_task(req, header, size_plan, Decimal(reported_pairs))
            usage = _dec(req.qty_per_pair)
            total = usage * Decimal(task)
            usage_by_key[key] = usage_by_key.get(key, _ZERO) + total
            first = key not in seen_keys
            seen_keys.add(key)
            out[int(req.id)] = {
                "header_id": int(header.id),
                "demand_qty": demand,
                "shortage_qty": need - take,
                "to_buy": not occupies,
                "warehouse_qty": warehouse_pool.get(key, _ZERO) if first else _ZERO,
                "workshop_qty": workshop_pool.get(key, _ZERO) if first else _ZERO,
                "task_qty": Decimal(task),
                "usage_qty": usage,
                "total_usage_qty": total,
            }
        if not occupies:
            continue
        for key, total in usage_by_key.items():
            ws = workshop_pool.get(key, _ZERO)
            wh = warehouse_pool.get(key, _ZERO)
            ws_take = total if total < ws else ws
            left = total - ws_take
            wh_take = left if left < wh else wh
            workshop_pool[key] = ws - ws_take
            warehouse_pool[key] = wh - wh_take
    return out


def progress_header_warehouse_flags(db: Session, tenant_id: int) -> dict[int, dict]:
    """每张未完成生产单的仓库列：缺口行数，以及是否还没生成采购单。"""
    flags: dict[int, dict] = {}
    for row in progress_requirement_balance(db, tenant_id).values():
        header_id = int(row["header_id"])
        slot = flags.setdefault(header_id, {"shortage_lines": 0, "to_buy": bool(row.get("to_buy"))})
        if row.get("to_buy"):
            slot["to_buy"] = True
        if row["shortage_qty"] > 0:
            slot["shortage_lines"] += 1
    return flags


def progress_header_shortage_counts(db: Session, tenant_id: int) -> dict[int, int]:
    """每张未完成生产单里，按仓库弹层算法仍有缺口的物料行数。"""
    return {
        header_id: int(row["shortage_lines"])
        for header_id, row in progress_header_warehouse_flags(db, tenant_id).items()
    }


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
        line["warehouse_qty"] = row["warehouse_qty"]
        line["workshop_qty"] = row["workshop_qty"]
        line["task_qty"] = row["task_qty"]
        line["usage_qty"] = row["usage_qty"]
        line["total_usage_qty"] = row["total_usage_qty"]
    shortage_lines = [ln for ln in lines if _dec(ln.get("shortage_qty")) > 0]
    kit["shortage_lines"] = len(shortage_lines)
    kit["kit_ok"] = not shortage_lines and not kit.get("empty_bom")
    return kit


def _task_pairs(req: OrderMaterialRequirement, header: ExecutionHeader, size_plan: dict[int, dict[int, int]]) -> int:
    """这一条用料对应的计划双数。分码用该码计划，不分码用生产单总数。"""
    if req.usage_by_size and req.size_id:
        return int(size_plan.get(int(header.id), {}).get(int(req.size_id), 0))
    return int(header.total_qty or 0)


def _remaining_task(
    req: OrderMaterialRequirement,
    header: ExecutionHeader,
    size_plan: dict[int, dict[int, int]],
    reported_pairs: Decimal,
) -> Decimal:
    """任务数量 = 总数量 - 本消耗部门已报工。分码按该码计划占总数的比例分摊剩余双数。"""
    gross = Decimal(_task_pairs(req, header, size_plan))
    reported = reported_pairs if reported_pairs > 0 else _ZERO
    if req.usage_by_size and req.size_id:
        header_total = Decimal(int(header.total_qty or 0))
        if header_total <= 0:
            header_total = gross
        remaining = header_total - reported
        if remaining < 0:
            remaining = _ZERO
        if header_total <= 0:
            return _ZERO
        return gross * remaining / header_total
    task = gross - reported
    return task if task > 0 else _ZERO


def _open_headers(db: Session, tenant_id: int, sales_order_id: int | None) -> list[ExecutionHeader]:
    header_q = select(ExecutionHeader).where(
        ExecutionHeader.tenant_id == tenant_id,
        ExecutionHeader.status.in_(_OPEN_HEADER),
        ExecutionHeader.parent_header_id.is_(None),
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
    reported_process: dict[tuple[int, int], Decimal],
    reported_segment: dict[tuple[int, int], Decimal],
) -> tuple[Decimal, int, Decimal]:
    """返回生产需求、计划双数、报工双数。

    报工取物料消耗工序段的完工，与生产进度同一口径。没有工序段时才退回消耗工序。
    分码料的报工没有码，不能拿总双数去减某一码。生产需求保持该码的用量，
    实际还要多少只再减车间剩余和仓库现存。
    有码数时，待买里的双数是各码数量之和，不是单独一个码。
    """
    required = _dec(req.required_qty)
    usage = _dec(req.qty_per_pair) * _dec(req.size_coeff or 1) * (Decimal("1") + _dec(req.loss_rate))
    reported_pairs = _ZERO
    if req.consume_segment_id:
        reported_pairs = reported_segment.get((int(header.id), int(req.consume_segment_id)), _ZERO)
    elif req.consume_process_id:
        reported_pairs = reported_process.get((int(header.id), int(req.consume_process_id)), _ZERO)
    if req.usage_by_size and req.size_id:
        header_sizes = size_plan.get(int(header.id), {})
        plan = int(sum(header_sizes.values())) if header_sizes else int(header.total_qty or 0)
        demand = required
    else:
        plan = int(header.total_qty or 0)
        demand = required - usage * reported_pairs
    return demand, plan, reported_pairs


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


def _pair_num(value: Decimal) -> int | float:
    quantized = _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole = quantized.to_integral_value()
    if quantized == whole:
        return int(whole)
    return float(quantized)


def _counts_on_dispatched_route(proc: dict) -> bool:
    """与生产进度一致：没派到工艺路线部门的工序不参与段完工。"""
    route_ids = {int(item) for item in (proc.get("route_department_ids") or []) if int(item)}
    if proc.get("route_department_shared") or not route_ids:
        return True
    assigned = [int(item) for item in (proc.get("assigned_department_ids") or []) if int(item)]
    if not assigned:
        return True
    return any(item in route_ids for item in assigned)


def _segment_bottleneck_done(rows: list[dict]) -> Decimal:
    """与生产进度工序段「完工」一致：最大计划为段任务，最低完成率折算完工。"""
    effective = [row for row in rows if _dec(row.get("plan_qty")) > 0]
    if not effective:
        return _ZERO
    task = max(_dec(row.get("plan_qty")) for row in effective)
    if task <= 0:
        return _ZERO
    rate = min(
        min(Decimal("1"), max(_ZERO, _dec(row.get("completed_qty"))) / _dec(row.get("plan_qty")))
        for row in effective
    )
    done = min(task, task * rate)
    return done.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _segment_completed_pairs(
    db: Session,
    tenant_id: int,
    header_ids: set[int],
) -> dict[tuple[int, int], Decimal]:
    if not header_ids:
        return {}
    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.id.in_(header_ids),
            )
        ).all()
    )
    if not headers:
        return {}
    from app.services.execution_service import _headers_process_progress_batch

    progress = _headers_process_progress_batch(db, headers)
    grouped: dict[tuple[int, int], list[dict]] = {}
    for header_id, rows in progress.items():
        for row in rows:
            segment_id = row.get("segment_id")
            if not segment_id or not _counts_on_dispatched_route(row):
                continue
            grouped.setdefault((int(header_id), int(segment_id)), []).append(row)
    out: dict[tuple[int, int], Decimal] = {}
    for key, rows in grouped.items():
        done = _segment_bottleneck_done(rows)
        if done > 0:
            out[key] = done
    return out


def _reported_pairs(
    db: Session,
    tenant_id: int,
    header_ids: set[int],
) -> tuple[dict[tuple[int, int], Decimal], dict[tuple[int, int], Decimal]]:
    """工序合格报工，以及工序段完工。

    工序段与生产进度的「完工」同一口径，不把段内各工序的报工相加。
    没有工序段时，才用该消耗工序的合格报工。
    """
    if not header_ids:
        return {}, {}
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
    by_process: dict[tuple[int, int], Decimal] = {}
    for header_id, process_id, qty in rows:
        if not header_id or not process_id:
            continue
        key = (int(header_id), int(process_id))
        by_process[key] = by_process.get(key, _ZERO) + _dec(qty)
    return by_process, _segment_completed_pairs(db, tenant_id, header_ids)


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


def _carry_qty(
    db: Session,
    tenant_id: int,
    header_id: int,
    employee_id: int,
    supplier_ids: set[int],
) -> dict[tuple[int, int, int | None], Decimal]:
    """报工输入框前的数量：上次清点，加上之后本人领的，减去之后本人退的。

    领料签收时间是 UTC，清点时间是本地时间，比较前先拨回 8 小时。
    """
    if not supplier_ids:
        return {}
    latest: dict[tuple[int, int, int | None], tuple[datetime | None, int, Decimal]] = {}
    logs = db.scalars(
        select(WorkshopMaterialCountLog)
        .where(
            WorkshopMaterialCountLog.tenant_id == tenant_id,
            WorkshopMaterialCountLog.header_id == header_id,
            WorkshopMaterialCountLog.supplier_product_id.in_(supplier_ids),
            WorkshopMaterialCountLog.counted_by == employee_id,
        )
        .order_by(WorkshopMaterialCountLog.created_at, WorkshopMaterialCountLog.id)
    ).all()
    for row in logs:
        latest[_count_key(row.header_id, row.supplier_product_id, row.size_id)] = (
            row.created_at,
            int(row.id),
            _dec(row.qty),
        )
    pickups = list(
        db.scalars(
            select(WarehousePickup).where(
                WarehousePickup.tenant_id == tenant_id,
                WarehousePickup.header_id == header_id,
                WarehousePickup.picker_employee_id == employee_id,
                WarehousePickup.status == WarehousePickupStatus.signed,
                WarehousePickup.kind.in_((WarehousePickupKind.production, WarehousePickupKind.production_return)),
            )
        ).all()
    )
    lines = []
    if pickups:
        pickup_by_id = {row.id: row for row in pickups}
        lines = db.scalars(
            select(WarehousePickupLine).where(
                WarehousePickupLine.pickup_id.in_(pickup_by_id),
                WarehousePickupLine.supplier_product_id.in_(supplier_ids),
            )
        ).all()
    net: dict[tuple[int, int, int | None], Decimal] = {}
    for line in lines:
        pickup = pickup_by_id[line.pickup_id]
        moment = pickup.signed_at + timedelta(hours=8) if pickup.signed_at else None
        key = _count_key(header_id, line.supplier_product_id, line.size_id)
        counted_at = latest[key][0] if key in latest else None
        if moment is None or (counted_at is not None and moment <= counted_at):
            continue
        kind = pickup.kind.value if hasattr(pickup.kind, "value") else str(pickup.kind)
        signed = net.get(key, _ZERO)
        net[key] = signed - _dec(line.qty) if kind == "production_return" else signed + _dec(line.qty)
    out: dict[tuple[int, int, int | None], Decimal] = {}
    for key, (_, _, qty) in latest.items():
        out[key] = qty + net.get(key, _ZERO)
    for key, qty in net.items():
        if key not in out:
            out[key] = qty
    return out


def _count_key(header_id: int, supplier_product_id: int, size_id: int | None) -> tuple[int, int, int | None]:
    return (int(header_id), int(supplier_product_id), int(size_id) if size_id else None)


def _latest_count_moments(
    db: Session,
    tenant_id: int,
    supplier_ids: set[int],
    *,
    header_id: int | None = None,
) -> dict[tuple[int, int, int | None], dict[int | None, tuple[datetime | None, Decimal]]]:
    """每人最新一次清点。键 = (header, 物料, 码)；人没记下时用 None。"""
    if not supplier_ids:
        return {}
    filters = [
        WorkshopMaterialCountLog.tenant_id == tenant_id,
        WorkshopMaterialCountLog.supplier_product_id.in_(supplier_ids),
    ]
    if header_id is not None:
        filters.append(WorkshopMaterialCountLog.header_id == header_id)
    rows = db.scalars(
        select(WorkshopMaterialCountLog)
        .where(*filters)
        .order_by(WorkshopMaterialCountLog.created_at, WorkshopMaterialCountLog.id)
    ).all()
    latest: dict[tuple[int, int, int | None], dict[int | None, tuple[datetime | None, int, Decimal]]] = {}
    for row in rows:
        key = _count_key(row.header_id, row.supplier_product_id, row.size_id)
        person = int(row.counted_by) if row.counted_by else None
        bucket = latest.setdefault(key, {})
        bucket[person] = (row.created_at, int(row.id), _dec(row.qty))
    return {key: {person: (moment, qty) for person, (moment, _, qty) in people.items()} for key, people in latest.items()}


def _balance_counts(
    db: Session,
    tenant_id: int,
    supplier_ids: set[int],
    *,
    header_id: int | None = None,
) -> dict[tuple[int, int, int | None], Decimal]:
    """还没有人清点时，用领料加、退料减留下的余额。"""
    if not supplier_ids:
        return {}
    filters = [
        WorkshopMaterialCount.tenant_id == tenant_id,
        WorkshopMaterialCount.supplier_product_id.in_(supplier_ids),
    ]
    if header_id is not None:
        filters.append(WorkshopMaterialCount.header_id == header_id)
    totals: dict[tuple[int, int, int | None], Decimal] = {}
    for row in db.scalars(select(WorkshopMaterialCount).where(*filters)).all():
        key = _count_key(row.header_id, row.supplier_product_id, row.size_id)
        totals[key] = totals.get(key, _ZERO) + _dec(row.qty)
    return totals


def _pickup_delta_by_person(
    db: Session,
    tenant_id: int,
    supplier_ids: set[int],
    *,
    header_id: int | None = None,
) -> dict[tuple[int, int, int | None], list[tuple[int, datetime | None, Decimal]]]:
    """每人的领料为正、退料为负。时间已拨成本地时间。"""
    if not supplier_ids:
        return {}
    filters = [
        WarehousePickup.tenant_id == tenant_id,
        WarehousePickup.picker_employee_id.is_not(None),
        WarehousePickup.status == WarehousePickupStatus.signed,
        WarehousePickup.kind.in_((WarehousePickupKind.production, WarehousePickupKind.production_return)),
    ]
    if header_id is not None:
        filters.append(WarehousePickup.header_id == header_id)
    pickups = list(db.scalars(select(WarehousePickup).where(*filters)).all())
    if not pickups:
        return {}
    pickup_by_id = {row.id: row for row in pickups}
    lines = db.scalars(
        select(WarehousePickupLine).where(
            WarehousePickupLine.pickup_id.in_(pickup_by_id),
            WarehousePickupLine.supplier_product_id.in_(supplier_ids),
        )
    ).all()
    out: dict[tuple[int, int, int | None], list[tuple[int, datetime | None, Decimal]]] = {}
    for line in lines:
        pickup = pickup_by_id[line.pickup_id]
        if pickup.header_id is None or pickup.picker_employee_id is None:
            continue
        moment = pickup.signed_at + timedelta(hours=8) if pickup.signed_at else None
        kind = pickup.kind.value if hasattr(pickup.kind, "value") else str(pickup.kind)
        qty = _dec(line.qty)
        if kind == "production_return":
            qty = -qty
        key = _count_key(pickup.header_id, line.supplier_product_id, line.size_id)
        out.setdefault(key, []).append((int(pickup.picker_employee_id), moment, qty))
    return out


def _workshop_counts(
    db: Session,
    tenant_id: int,
    supplier_ids: set[int],
    *,
    header_id: int | None = None,
) -> dict[tuple[int, int, int | None], Decimal]:
    """每人上次清点，加上之后领的，减去之后退的，再合计。没人清点过才用领退余额。"""
    latest = _latest_count_moments(db, tenant_id, supplier_ids, header_id=header_id)
    balances = _balance_counts(db, tenant_id, supplier_ids, header_id=header_id)
    deltas = _pickup_delta_by_person(db, tenant_id, supplier_ids, header_id=header_id)
    out: dict[tuple[int, int, int | None], Decimal] = {}
    for key in set(latest) | set(balances) | set(deltas):
        people = latest.get(key) or {}
        named = {person: qty for person, (moment, qty) in people.items() if person is not None}
        if named:
            total = _ZERO
            for person, qty in named.items():
                moment = people[person][0]
                extra = sum(
                    (amount for who, signed_at, amount in deltas.get(key, []) if who == person and (moment is None or (signed_at is not None and signed_at > moment))),
                    _ZERO,
                )
                total += qty + extra
            counted_people = set(named)
            for who, _signed_at, amount in deltas.get(key, []):
                if who not in counted_people:
                    total += amount
            out[key] = total
        elif None in people:
            out[key] = people[None][1]
        elif key in deltas and key not in balances:
            out[key] = sum((amount for _who, _signed_at, amount in deltas[key]), _ZERO)
        else:
            out[key] = balances.get(key, _ZERO)
    return out


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
