"""AU-I2：成品仓 + 筐入库。"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    Employee,
    ExecutionAllocation,
    ExecutionHeader,
    FgLedger,
    FgStock,
    OwnProduct,
    ProcessSegment,
    ReportType,
    SalesLineLaborAllocation,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    TraceUnitType,
    WorkLog,
    WorkLogStatus,
)
from app.services.execution_service import split_produced_by_ratio
from app.services.shop_floor_settings import get_shop_floor_by_tenant_id


class FgError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def get_or_create_fg_stock(
    db: Session,
    *,
    tenant_id: int,
    own_product_id: int,
    color_id: int | None,
    size_id: int,
) -> FgStock:
    row = db.scalar(
        select(FgStock).where(
            FgStock.tenant_id == tenant_id,
            FgStock.own_product_id == own_product_id,
            FgStock.color_id == color_id if color_id is not None else FgStock.color_id.is_(None),
            FgStock.size_id == size_id,
        )
    )
    if row:
        return row
    row = FgStock(
        tenant_id=tenant_id,
        own_product_id=own_product_id,
        color_id=color_id,
        size_id=size_id,
        qty=0,
    )
    db.add(row)
    db.flush()
    return row


def list_fg_stocks(
    db: Session,
    *,
    tenant_id: int,
    q: str | None = None,
    only_positive: bool = False,
    limit: int = 200,
) -> list[dict]:
    stmt = select(FgStock).where(FgStock.tenant_id == tenant_id)
    if only_positive:
        stmt = stmt.where(FgStock.qty > 0)
    rows = list(db.scalars(stmt.order_by(FgStock.id.desc()).limit(limit)).all())
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        product = db.get(OwnProduct, r.own_product_id)
        color = db.get(Color, r.color_id) if r.color_id else None
        size = db.get(Size, r.size_id)
        product_code = product.product_code if product else None
        color_name = color.name if color else None
        size_value = size.size_value if size else None
        if needle:
            hay = " ".join(
                str(x or "") for x in (product_code, color_name, size_value, r.own_product_id)
            ).lower()
            if needle not in hay:
                continue
        out.append(
            {
                "id": r.id,
                "own_product_id": r.own_product_id,
                "product_code": product_code,
                "color_id": r.color_id,
                "color_name": color_name,
                "size_id": r.size_id,
                "size_value": size_value,
                "qty": int(r.qty or 0),
                "updated_at": r.updated_at.isoformat(sep=" ", timespec="seconds")
                if r.updated_at
                else None,
            }
        )
    return out


def list_fg_cartons(
    db: Session,
    *,
    tenant_id: int,
    q: str | None = None,
    limit: int = 500,
    status: str = "in_stock",
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """成品仓实物账：一箱一行；可查询当前库存或按箱出库记录。"""
    from app.models import (
        Employee,
        ExecutionHeader,
        Order,
        PackingCarton,
        PackingPlan,
        SalesOrderLine,
        Shipment,
    )
    from sqlalchemy.orm import selectinload

    shipped = status == "shipped"
    carton_stmt = (
        select(PackingCarton)
        .where(
            PackingCarton.tenant_id == tenant_id,
            PackingCarton.warehoused_at.is_not(None),
            PackingCarton.shipment_id.is_not(None) if shipped else PackingCarton.shipment_id.is_(None),
        )
        .options(
            selectinload(PackingCarton.lines),
            selectinload(PackingCarton.plan),
        )
    )
    if shipped:
        carton_stmt = carton_stmt.join(Shipment, Shipment.id == PackingCarton.shipment_id)
        if date_from:
            carton_stmt = carton_stmt.where(Shipment.created_at >= datetime.combine(date_from, time.min))
        if date_to:
            carton_stmt = carton_stmt.where(Shipment.created_at <= datetime.combine(date_to, time.max))
        carton_stmt = carton_stmt.order_by(Shipment.created_at.desc(), PackingCarton.id.desc())
    else:
        carton_stmt = carton_stmt.order_by(PackingCarton.warehoused_at.desc(), PackingCarton.id.desc())

    cartons = list(
        db.scalars(
            carton_stmt.limit(max(limit * 2, limit))
        ).all()
    )
    needle = (q or "").strip().lower()
    items: list[dict] = []
    summary_map: dict[tuple, dict] = {}
    for carton in cartons:
        plan = carton.plan or db.get(PackingPlan, carton.plan_id)
        sales_line_id = carton.sales_order_line_id or (plan.sales_order_line_id if plan else None)
        sales_line = db.get(SalesOrderLine, sales_line_id) if sales_line_id else None
        sales_order_id = carton.sales_order_id or (
            sales_line.sales_order_id if sales_line else (plan.sales_order_id if plan else None)
        )
        sales_order = db.get(SalesOrder, sales_order_id) if sales_order_id else None
        shipment = db.get(Shipment, carton.shipment_id) if carton.shipment_id else None
        shipped_by = db.get(Employee, shipment.created_by) if shipment and shipment.created_by else None
        header = db.get(ExecutionHeader, plan.header_id) if plan and plan.header_id else None
        order = db.get(Order, plan.order_id) if plan and plan.order_id else None
        own_product_id = (
            sales_line.own_product_id
            if sales_line
            else (header.own_product_id if header else (order.own_product_id if order else None))
        )
        product = db.get(OwnProduct, own_product_id) if own_product_id else None
        customer_id = carton.customer_id or (sales_order.customer_id if sales_order else None)
        customer_name = carton.customer_name or (sales_order.customer_name if sales_order else None)
        brand_id = carton.brand_id or (sales_line.brand_id if sales_line else None)
        brand_name = carton.brand_name or (sales_line.brand_name if sales_line else None)
        customer_sku = carton.customer_sku or (sales_line.customer_sku if sales_line else None)
        product_code = product.product_code if product else None
        product_image_url = product.image_url if product else None
        fabric = (sales_line.fabric if sales_line else None) or (product.fabric if product else None)
        lining = (sales_line.lining if sales_line else None) or (product.lining if product else None)

        lines: list[dict] = []
        assortment_parts: list[tuple[int, str, int]] = []
        for line in sorted(carton.lines or [], key=lambda row: (row.size_id or 0, row.id)):
            color = db.get(Color, line.color_id) if line.color_id else None
            size = db.get(Size, line.size_id) if line.size_id else None
            size_value = size.size_value if size else str(line.size_id or "-")
            qty = int(line.qty or 0)
            lines.append({
                "color_id": line.color_id,
                "color_name": color.name if color else None,
                "size_id": line.size_id,
                "size_value": size_value,
                "qty": qty,
            })
            assortment_parts.append((int(size.sort_order or 0) if size else 0, size_value, qty))
        assortment_parts.sort(key=lambda row: (row[0], row[1]))
        assortment = " / ".join(f"{size_value}×{qty}" for _, size_value, qty in assortment_parts)
        color_names = list(dict.fromkeys(
            str(line["color_name"]) for line in lines if line.get("color_name")
        ))
        if not color_names and sales_line and sales_line.color_id:
            sales_color = db.get(Color, sales_line.color_id)
            if sales_color:
                color_names.append(sales_color.name)
        color_name = " / ".join(color_names) or None
        search_text = " ".join(str(value or "") for value in (
            carton.code, customer_name, brand_name, customer_sku, product_code,
            sales_order.order_no if sales_order else None, assortment,
            color_name, fabric, lining,
            shipment.shipment_no if shipment else None,
            shipped_by.name if shipped_by else None,
        )).lower()
        if needle and needle not in search_text:
            continue

        row = {
            "id": carton.id,
            "code": carton.code,
            "total_qty": int(carton.total_qty or 0),
            "warehoused_at": carton.warehoused_at.isoformat(sep=" ", timespec="seconds"),
            "customer_id": customer_id,
            "customer_name": customer_name,
            "brand_id": brand_id,
            "brand_name": brand_name,
            "customer_sku": customer_sku,
            "sales_order_id": sales_order_id,
            "sales_order_no": sales_order.order_no if sales_order else None,
            "sales_order_line_id": sales_line_id,
            "own_product_id": own_product_id,
            "product_code": product_code,
            "product_image_url": product_image_url,
            "color_name": color_name,
            "fabric": fabric,
            "lining": lining,
            "assortment": assortment,
            "lines": lines,
            "shipment_id": shipment.id if shipment else None,
            "shipment_no": shipment.shipment_no if shipment else None,
            "shipped_at": shipment.created_at.isoformat(sep=" ", timespec="seconds")
            if shipment and shipment.created_at else None,
            "shipped_by": shipped_by.name if shipped_by else None,
        }
        items.append(row)

        summary_key = (
            customer_id or 0,
            customer_name or "",
            brand_id or 0,
            brand_name or "",
            customer_sku or "",
            own_product_id or 0,
            product_code or "",
        )
        summary = summary_map.setdefault(summary_key, {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "brand_id": brand_id,
            "brand_name": brand_name,
            "customer_sku": customer_sku,
            "own_product_id": own_product_id,
            "product_code": product_code,
            "carton_count": 0,
            "qty": 0,
        })
        summary["carton_count"] += 1
        summary["qty"] += int(carton.total_qty or 0)
        if len(items) >= limit:
            break

    summaries = sorted(
        summary_map.values(),
        key=lambda row: (
            str(row["customer_name"] or ""),
            str(row["brand_name"] or ""),
            str(row["product_code"] or ""),
        ),
    )
    return {
        "items": items,
        "summaries": summaries,
        "carton_count": len(items),
        "qty": sum(int(row["total_qty"]) for row in items),
    }


def list_fg_ledgers(
    db: Session,
    *,
    tenant_id: int,
    fg_stock_id: int,
    limit: int = 100,
) -> list[dict]:
    stock = db.get(FgStock, fg_stock_id)
    if not stock or stock.tenant_id != tenant_id:
        raise FgError("fg_not_found", "成品仓结存不存在")
    rows = list(
        db.scalars(
            select(FgLedger)
            .where(FgLedger.tenant_id == tenant_id, FgLedger.fg_stock_id == fg_stock_id)
            .order_by(FgLedger.id.desc())
            .limit(limit)
        ).all()
    )
    out = []
    for r in rows:
        unit = db.get(TraceUnit, r.trace_unit_id) if r.trace_unit_id else None
        execution = db.get(SpecExecutionOrder, r.execution_id) if r.execution_id else None
        out.append(
            {
                "id": r.id,
                "direction": r.direction,
                "qty": int(r.qty or 0),
                "ref_type": r.ref_type,
                "ref_id": r.ref_id,
                "note": r.note,
                "trace_unit_id": r.trace_unit_id,
                "trace_unit_code": unit.code if unit else None,
                "execution_id": r.execution_id,
                "execution_no": execution.execution_no if execution else None,
                "order_id": r.order_id,
                "created_at": r.created_at.isoformat(sep=" ", timespec="seconds")
                if r.created_at
                else None,
            }
        )
    return out


def warehouse_basket(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    note: str | None = None,
    created_by: int | None = None,
    commit: bool = True,
) -> dict:
    """筐成品入库：FG++、筐 warehoused、按 ratio 写精确 produced_qty。"""
    unit = db.get(TraceUnit, trace_unit_id)
    if not unit or unit.tenant_id != tenant_id:
        raise FgError("trace_not_found", "追溯单元不存在")
    if _enum_val(unit.unit_type) != TraceUnitType.basket.value:
        raise FgError("not_basket", "仅流转卡(筐)可入库")
    st = _enum_val(unit.status)
    if st == TraceUnitStatus.warehoused.value:
        raise FgError("already_warehoused", "该筐已入库")
    if st == TraceUnitStatus.shipped.value:
        raise FgError("already_shipped", "该筐已出货/直发")
    if st in (TraceUnitStatus.scrapped.value, TraceUnitStatus.split.value):
        raise FgError("invalid_status", "已作废/拆分的筐不能入库")
    from app.services.trace_service import carrier_available_qty

    qty = int(unit.qty or 0)
    avail = carrier_available_qty(db, unit)
    if avail <= 0:
        raise FgError(
            "no_available_qty",
            "可用数为 0（返修冻结或已报废）；返修完成后再入库",
        )
    if avail < qty:
        raise FgError(
            "rework_frozen",
            f"有未关闭返修冻结 {qty - avail} 双，可用 {avail}；请先完成返修再入库",
        )
    if qty <= 0:
        raise FgError("invalid_qty", "筐数量无效")

    stock = get_or_create_fg_stock(
        db,
        tenant_id=tenant_id,
        own_product_id=unit.own_product_id,
        color_id=unit.color_id,
        size_id=int(unit.size_id),
    )
    stock.qty = int(stock.qty or 0) + qty
    ledger = FgLedger(
        tenant_id=tenant_id,
        fg_stock_id=stock.id,
        direction="in",
        qty=qty,
        order_id=unit.order_id,
        execution_id=getattr(unit, "execution_id", None),
        trace_unit_id=unit.id,
        ref_type="warehouse",
        ref_id=unit.id,
        note=note or "筐完工入库",
        created_by=created_by,
    )
    db.add(ledger)

    unit.status = TraceUnitStatus.warehoused
    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            action=TraceUnitAction.warehouse,
            qty=qty,
            note=note or "成品入库",
        )
    )

    produced_splits: list[dict] = []
    labor_splits: list[dict] = []
    eid = getattr(unit, "execution_id", None)
    if eid:
        produced_splits = _apply_exact_produced(
            db, tenant_id=tenant_id, execution_id=int(eid), qty=qty,
            sales_order_id=getattr(unit, "sales_order_id", None),
        )
        execution = db.get(SpecExecutionOrder, int(eid))
        if execution:
            labor_splits = allocate_labor_cost_for_basket(
                db,
                tenant_id=tenant_id,
                unit=unit,
                execution=execution,
                produced_splits=produced_splits,
                ref_type="warehouse",
                created_by=created_by,
            )

    if commit:
        db.commit()
        db.refresh(unit)
        db.refresh(stock)
        db.refresh(ledger)

    return {
        "trace_unit_id": unit.id,
        "code": unit.code,
        "qty": qty,
        "status": TraceUnitStatus.warehoused.value,
        "fg_stock_id": stock.id,
        "fg_qty": int(stock.qty or 0),
        "ledger_id": ledger.id,
        "execution_id": eid,
        "produced_splits": produced_splits,
        "labor_splits": labor_splits,
        "progress_kind": "exact",
    }


def direct_ship_basket(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    raise FgError("carton_required", "出货必须按箱唛操作，框码不支持直发")
    """筐完工直发：同一事务内虚拟入/出，并按执行分配拆销售出货。"""
    if not get_shop_floor_by_tenant_id(db, tenant_id).get("allow_direct_ship", False):
        raise FgError("direct_ship_disabled", "当前工厂未开启直发")
    unit = db.get(TraceUnit, trace_unit_id)
    if not unit or unit.tenant_id != tenant_id:
        raise FgError("trace_not_found", "追溯单元不存在")
    if _enum_val(unit.unit_type) != TraceUnitType.basket.value:
        raise FgError("not_basket", "仅流转卡(筐)可直发")
    status = _enum_val(unit.status)
    if status == TraceUnitStatus.shipped.value:
        raise FgError("already_shipped", "该筐已出货/直发")
    if status == TraceUnitStatus.warehoused.value:
        raise FgError("already_warehoused", "已入库的筐请从成品仓出货")
    if status in (TraceUnitStatus.scrapped.value, TraceUnitStatus.split.value):
        raise FgError("invalid_status", "已作废/拆分的筐不能直发")
    qty = int(unit.qty or 0)
    if qty <= 0:
        raise FgError("invalid_qty", "筐数量无效")
    execution_id = getattr(unit, "execution_id", None)
    if not execution_id:
        raise FgError("no_execution", "直发须关联生产单及销售分配")

    execution = db.get(SpecExecutionOrder, execution_id)
    if not execution or execution.tenant_id != tenant_id:
        raise FgError("execution_not_found", "生产单不存在")
    allocations = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    if getattr(unit, "sales_order_id", None) is not None:
        # 合单分筐：本筐直发只落自己销售订单的出货/应收
        allocations = [
            a for a in allocations
            if int(a.sales_order_id or 0) == int(unit.sales_order_id)
        ]
    if not allocations:
        raise FgError("no_allocations", "生产单无分配，禁止无比例直发")

    from app.services.packing_service import PackingError, assert_basket_prepack_ready, settle_basket_prepack

    try:
        prepack = assert_basket_prepack_ready(db, tenant_id, unit)
    except PackingError as e:
        raise FgError(e.code, e.message) from e

    stock = get_or_create_fg_stock(
        db,
        tenant_id=tenant_id,
        own_product_id=unit.own_product_id,
        color_id=unit.color_id,
        size_id=int(unit.size_id),
    )
    # 两笔流水保留直发的库存轨迹；结存必须不变。
    db.add_all([
        FgLedger(tenant_id=tenant_id, fg_stock_id=stock.id, direction="in", qty=qty,
                 order_id=unit.order_id, execution_id=execution.id, trace_unit_id=unit.id,
                 ref_type="direct_ship_virtual_in", ref_id=unit.id,
                 note=note or "直发虚拟入库", created_by=created_by),
        FgLedger(tenant_id=tenant_id, fg_stock_id=stock.id, direction="out", qty=qty,
                 order_id=unit.order_id, execution_id=execution.id, trace_unit_id=unit.id,
                 ref_type="direct_ship_virtual_out", ref_id=unit.id,
                 note=note or "直发虚拟出库", created_by=created_by),
    ])
    # 先标记终态，使执行单完成量计算包含当前筐；后续任一步失败会随事务回滚。
    unit.status = TraceUnitStatus.shipped
    produced_splits = _apply_exact_produced(
        db, tenant_id=tenant_id, execution_id=execution.id, qty=qty,
        terminal_statuses=(TraceUnitStatus.warehoused, TraceUnitStatus.shipped),
        sales_order_id=getattr(unit, "sales_order_id", None),
    )
    labor_splits = allocate_labor_cost_for_basket(
        db,
        tenant_id=tenant_id,
        unit=unit,
        execution=execution,
        produced_splits=produced_splits,
        ref_type="direct_ship",
        created_by=created_by,
    )

    from app.services.shipment_service import create_direct_shipments

    shipments = create_direct_shipments(
        db, tenant_id=tenant_id, execution=execution, allocations=allocations,
        qtys=[int(row["qty"]) for row in produced_splits], user_id=created_by, note=note,
    )
    try:
        prepack_settle = settle_basket_prepack(db, prepack, shipments)
    except PackingError as e:
        raise FgError(e.code, e.message) from e
    db.add(TraceUnitLog(tenant_id=tenant_id, trace_unit_id=unit.id,
                        action=TraceUnitAction.ship, qty=qty, note=note or "筐完工直发"))
    db.commit()
    db.refresh(unit)
    db.refresh(stock)
    return {
        "trace_unit_id": unit.id, "code": unit.code, "qty": qty,
        "status": TraceUnitStatus.shipped.value, "fg_stock_id": stock.id,
        "fg_qty": int(stock.qty or 0), "execution_id": execution.id,
        "produced_splits": produced_splits, "labor_splits": labor_splits,
        "shipments": shipments,
        "prepack": prepack_settle,
        "progress_kind": "exact",
    }


def ship_warehoused_basket(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    raise FgError("carton_required", "出货必须按箱唛操作，框码不支持出货")
    """已入库筐从 FG 出货：扣成品仓、按分配拆销售出货、落成预装（产量/人工已在入库写过）。"""
    unit = db.get(TraceUnit, trace_unit_id)
    if not unit or unit.tenant_id != tenant_id:
        raise FgError("trace_not_found", "追溯单元不存在")
    if _enum_val(unit.unit_type) != TraceUnitType.basket.value:
        raise FgError("not_basket", "仅流转卡(筐)可从成品仓出货")
    status = _enum_val(unit.status)
    if status == TraceUnitStatus.shipped.value:
        raise FgError("already_shipped", "该筐已出货/直发")
    if status != TraceUnitStatus.warehoused.value:
        raise FgError("not_warehoused", "仅已入库的筐可从成品仓出货")
    qty = int(unit.qty or 0)
    if qty <= 0:
        raise FgError("invalid_qty", "筐数量无效")
    execution_id = getattr(unit, "execution_id", None)
    if not execution_id:
        raise FgError("no_execution", "出货须关联生产单及销售分配")

    execution = db.get(SpecExecutionOrder, execution_id)
    if not execution or execution.tenant_id != tenant_id:
        raise FgError("execution_not_found", "生产单不存在")
    if execution.status == SpecExecutionStatus.cancelled:
        raise FgError("execution_cancelled", "生产单已取消")
    allocations = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    if getattr(unit, "sales_order_id", None) is not None:
        # 合单分筐：从 FG 出货也只落自己销售订单的出货/应收
        allocations = [
            a for a in allocations
            if int(a.sales_order_id or 0) == int(unit.sales_order_id)
        ]
    if not allocations:
        raise FgError("no_allocations", "生产单无分配，禁止无比例出货")

    from app.services.packing_service import PackingError, assert_basket_prepack_ready, settle_basket_prepack

    try:
        prepack = assert_basket_prepack_ready(db, tenant_id, unit)
    except PackingError as e:
        raise FgError(e.code, e.message) from e

    stock = get_or_create_fg_stock(
        db,
        tenant_id=tenant_id,
        own_product_id=unit.own_product_id,
        color_id=unit.color_id,
        size_id=int(unit.size_id),
    )
    on_hand = int(stock.qty or 0)
    if on_hand < qty:
        raise FgError("fg_insufficient", f"成品仓不足：结存 {on_hand}，本筐 {qty}")

    stock.qty = on_hand - qty
    db.add(
        FgLedger(
            tenant_id=tenant_id,
            fg_stock_id=stock.id,
            direction="out",
            qty=qty,
            order_id=unit.order_id,
            execution_id=execution.id,
            trace_unit_id=unit.id,
            ref_type="fg_ship",
            ref_id=unit.id,
            note=note or "成品仓出货",
            created_by=created_by,
        )
    )
    unit.status = TraceUnitStatus.shipped

    ship_qtys = split_produced_by_ratio(qty, [Decimal(a.ratio) for a in allocations])
    produced_splits = []
    for a, share in zip(allocations, ship_qtys):
        so = db.get(SalesOrder, a.sales_order_id)
        item = db.get(SalesOrderLineItem, a.sales_order_line_item_id)
        produced_splits.append(
            {
                "sales_order_id": a.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "sales_order_line_item_id": a.sales_order_line_item_id,
                "qty": int(share),
                "produced_qty": int(getattr(item, "produced_qty", 0) or 0) if item else None,
            }
        )

    from app.services.shipment_service import create_direct_shipments

    shipments = create_direct_shipments(
        db,
        tenant_id=tenant_id,
        execution=execution,
        allocations=allocations,
        qtys=ship_qtys,
        user_id=created_by,
        note=note or f"生产单 {execution.execution_no} 成品仓出货",
    )
    try:
        prepack_settle = settle_basket_prepack(db, prepack, shipments)
    except PackingError as e:
        raise FgError(e.code, e.message) from e

    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            action=TraceUnitAction.ship,
            qty=qty,
            note=note or "成品仓出货",
        )
    )
    db.commit()
    db.refresh(unit)
    db.refresh(stock)
    return {
        "trace_unit_id": unit.id,
        "code": unit.code,
        "qty": qty,
        "status": TraceUnitStatus.shipped.value,
        "fg_stock_id": stock.id,
        "fg_qty": int(stock.qty or 0),
        "execution_id": execution.id,
        "produced_splits": produced_splits,
        "shipments": shipments,
        "prepack": prepack_settle,
        "progress_kind": "exact",
    }


def _apply_exact_produced(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    qty: int,
    terminal_statuses: tuple[TraceUnitStatus, ...] = (TraceUnitStatus.warehoused,),
    sales_order_id: int | None = None,
    completed_source: str = "baskets",
) -> list[dict]:
    execution = db.get(SpecExecutionOrder, execution_id)
    if not execution or execution.tenant_id != tenant_id:
        raise FgError("execution_not_found", "生产单不存在")
    if execution.status == SpecExecutionStatus.cancelled:
        raise FgError("execution_cancelled", "生产单已取消")

    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    if sales_order_id is not None:
        # 合单分筐：本筐只记自己销售订单的产量（其余订单由兄弟筐记）
        allocs = [a for a in allocs if int(a.sales_order_id or 0) == int(sales_order_id)]
    if not allocs:
        raise FgError("no_allocations", "生产单无分配，禁止无比例入库分摊")

    shares = split_produced_by_ratio(qty, [Decimal(a.ratio) for a in allocs])
    out: list[dict] = []
    for a, share in zip(allocs, shares):
        item = db.get(SalesOrderLineItem, a.sales_order_line_item_id)
        if item:
            item.produced_qty = int(getattr(item, "produced_qty", 0) or 0) + int(share)
        a.produced_qty_est = max(0, int(a.produced_qty_est or 0) - int(share))
        so = db.get(SalesOrder, a.sales_order_id)
        out.append(
            {
                "sales_order_id": a.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "sales_order_line_item_id": a.sales_order_line_item_id,
                "qty": int(share),
                "produced_qty": int(getattr(item, "produced_qty", 0) or 0) if item else None,
                "produced_qty_est": int(a.produced_qty_est or 0),
            }
        )

    from sqlalchemy import func

    db.flush()
    if completed_source == "add":
        # 按箱入库：直接累加本色码产量
        total = int(execution.total_qty or 0)
        new_c = int(execution.completed_qty or 0) + int(qty)
        execution.completed_qty = min(total, new_c) if total > 0 else new_c
        wh_qty = int(execution.completed_qty or 0)
    else:
        wh_qty = int(
            db.scalar(
                select(func.coalesce(func.sum(TraceUnit.qty), 0)).where(
                    TraceUnit.tenant_id == tenant_id,
                    TraceUnit.execution_id == execution.id,
                    TraceUnit.unit_type == TraceUnitType.basket,
                    TraceUnit.status.in_(terminal_statuses),
                )
            )
            or 0
        )
        execution.completed_qty = max(int(execution.completed_qty or 0), wh_qty)
    if wh_qty >= int(execution.total_qty or 0) > 0:
        execution.status = SpecExecutionStatus.completed
    elif wh_qty > 0:
        execution.status = SpecExecutionStatus.in_progress

    from app.services.execution_service import refresh_execution_header_progress

    refresh_execution_header_progress(
        db, tenant_id=tenant_id, header_id=getattr(execution, "header_id", None)
    )
    return out


def warehouse_carton(
    db: Session,
    *,
    tenant_id: int,
    carton_id: int,
    note: str | None = None,
    created_by: int | None = None,
    commit: bool = True,
) -> dict:
    """按箱成品入库：各色码 FG++，挂生产单时按码写精确 produced_qty。"""
    from datetime import datetime, timezone

    from app.models import ExecutionHeader, PackingCarton, PackingPlan, SalesOrderLine
    from sqlalchemy.orm import selectinload

    carton = db.scalar(
        select(PackingCarton)
        .where(PackingCarton.id == carton_id, PackingCarton.tenant_id == tenant_id)
        .options(selectinload(PackingCarton.lines), selectinload(PackingCarton.plan))
    )
    if not carton:
        raise FgError("carton_not_found", "箱不存在")
    if getattr(carton, "warehoused_at", None):
        raise FgError("already_warehoused", "该箱已入库")
    if not getattr(carton, "reported_work_log_id", None):
        raise FgError("carton_not_reported", "该箱尚未包装报工，请先扫箱唛报工")
    lines = list(carton.lines or [])
    if not lines:
        raise FgError("empty_carton", "箱内无色码明细")
    plan = carton.plan or db.get(PackingPlan, carton.plan_id)
    if not plan or plan.tenant_id != tenant_id:
        raise FgError("plan_not_found", "装箱计划不存在")

    # 老箱码可能生成于归属快照字段上线前；入库时补齐并冻结客户/品牌身份。
    source_line = db.get(SalesOrderLine, plan.sales_order_line_id) if plan.sales_order_line_id else None
    source_order = db.get(SalesOrder, source_line.sales_order_id) if source_line else None
    if source_line:
        carton.sales_order_id = carton.sales_order_id or source_line.sales_order_id
        carton.sales_order_line_id = carton.sales_order_line_id or source_line.id
        carton.brand_id = carton.brand_id or source_line.brand_id
        carton.brand_name = carton.brand_name or source_line.brand_name
        carton.customer_sku = carton.customer_sku or source_line.customer_sku
    if source_order:
        carton.customer_id = carton.customer_id or source_order.customer_id
        carton.customer_name = carton.customer_name or source_order.customer_name

    header = (
        db.get(ExecutionHeader, plan.header_id)
        if getattr(plan, "header_id", None)
        else None
    )
    order = None
    if plan.order_id:
        from app.models import Order

        order = db.get(Order, plan.order_id)
    own_product_id = None
    sales_order_id = None
    if header:
        own_product_id = header.own_product_id
        sales_order_id = carton.sales_order_id or plan.sales_order_id or header.sales_order_id
    elif order:
        own_product_id = order.own_product_id
    if not own_product_id:
        raise FgError("no_product", "无法确定工厂型号，禁止入库")

    size_execs: dict[int, SpecExecutionOrder] = {}
    if header:
        for seo in db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.header_id == header.id,
                SpecExecutionOrder.tenant_id == tenant_id,
            )
        ).all():
            if seo.size_id:
                size_execs[int(seo.size_id)] = seo

    line_results: list[dict] = []
    produced_splits: list[dict] = []
    for ln in sorted(lines, key=lambda x: (x.size_id or 0, x.id)):
        qty = int(ln.qty or 0)
        if qty <= 0:
            continue
        size_id = int(ln.size_id)
        color_id = ln.color_id
        if color_id is None and header is not None:
            color_id = header.color_id
        stock = get_or_create_fg_stock(
            db,
            tenant_id=tenant_id,
            own_product_id=int(own_product_id),
            color_id=color_id,
            size_id=size_id,
        )
        stock.qty = int(stock.qty or 0) + qty
        seo = size_execs.get(size_id)
        ledger = FgLedger(
            tenant_id=tenant_id,
            fg_stock_id=stock.id,
            direction="in",
            qty=qty,
            order_id=plan.order_id,
            execution_id=seo.id if seo else None,
            trace_unit_id=None,
            ref_type="carton_warehouse",
            ref_id=carton.id,
            note=note or f"箱入库 {carton.code}",
            created_by=created_by,
        )
        db.add(ledger)
        size = db.get(Size, size_id)
        line_results.append(
            {
                "size_id": size_id,
                "size_value": size.size_value if size else None,
                "qty": qty,
                "fg_stock_id": stock.id,
                "fg_qty": int(stock.qty or 0),
                "ledger_id": ledger.id,
                "execution_id": seo.id if seo else None,
            }
        )
        if seo:
            produced_splits.extend(
                _apply_exact_produced(
                    db,
                    tenant_id=tenant_id,
                    execution_id=int(seo.id),
                    qty=qty,
                    sales_order_id=sales_order_id,
                    completed_source="add",
                )
            )

    if not line_results:
        raise FgError("invalid_qty", "箱数量无效")

    carton.warehoused_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if commit:
        db.commit()
        db.refresh(carton)

    return {
        "carton_id": carton.id,
        "code": carton.code,
        "total_qty": int(carton.total_qty or 0),
        "warehoused_at": carton.warehoused_at.isoformat() if carton.warehoused_at else None,
        "lines": line_results,
        "produced_splits": produced_splits,
        "progress_kind": "exact",
    }


def ship_warehoused_carton(
    db: Session,
    *,
    tenant_id: int,
    carton_id: int,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    """扫码按箱出库：扣成品仓，并用同一箱色码生成、确认销售出货单。"""
    from datetime import datetime, timezone

    from sqlalchemy.orm import selectinload

    from app.models import (
        ExecutionHeader,
        Order,
        PackingCarton,
        PackingPlan,
        SalesOrderLine,
        SalesOrderLineItem,
    )
    from app.services import shipment_service

    carton = db.scalar(
        select(PackingCarton)
        .where(PackingCarton.id == carton_id, PackingCarton.tenant_id == tenant_id)
        .options(selectinload(PackingCarton.lines), selectinload(PackingCarton.plan))
    )
    if not carton:
        raise FgError("carton_not_found", "箱不存在")
    if carton.shipment_id:
        raise FgError("already_shipped", "该箱已出库，请勿重复扫描")
    if not carton.warehoused_at:
        raise FgError("carton_not_warehoused", "该箱尚未入库，禁止出库")
    if not carton.reported_work_log_id:
        raise FgError("carton_not_reported", "该箱尚未包装报工，禁止出库")

    plan = carton.plan or db.get(PackingPlan, carton.plan_id)
    if not plan or plan.tenant_id != tenant_id:
        raise FgError("plan_not_found", "装箱计划不存在")
    header = db.get(ExecutionHeader, plan.header_id) if plan.header_id else None
    order = db.get(Order, plan.order_id) if plan.order_id else None
    own_product_id = header.own_product_id if header else (order.own_product_id if order else None)
    if not own_product_id:
        raise FgError("no_product", "箱唛无法确定产品，禁止出库")

    carton_lines = [ln for ln in carton.lines or [] if int(ln.qty or 0) > 0]
    if not carton_lines:
        raise FgError("empty_carton", "箱内无色码明细")

    shipment_lines: list[dict] = []
    sales_order_id = (
        carton.sales_order_id
        or plan.sales_order_id
        or (header.sales_order_id if header else None)
        or (order.sales_order_id if order else None)
    )
    if sales_order_id:
        sales_line_stmt = select(SalesOrderLine).where(
            SalesOrderLine.tenant_id == tenant_id,
            SalesOrderLine.sales_order_id == sales_order_id,
            SalesOrderLine.own_product_id == own_product_id,
        )
        source_line_id = carton.sales_order_line_id or plan.sales_order_line_id
        if source_line_id:
            sales_line_stmt = sales_line_stmt.where(SalesOrderLine.id == source_line_id)
        sales_lines = list(db.scalars(sales_line_stmt).all())
        sales_line_ids = [row.id for row in sales_lines]
        sales_items = list(
            db.scalars(
                select(SalesOrderLineItem).where(
                    SalesOrderLineItem.tenant_id == tenant_id,
                    SalesOrderLineItem.sales_order_line_id.in_(sales_line_ids),
                )
            ).all()
        ) if sales_line_ids else []
        for line in carton_lines:
            color_id = line.color_id if line.color_id is not None else (header.color_id if header else None)
            matches = [
                item for item in sales_items
                if item.size_id == line.size_id
                and (item.color_id if item.color_id is not None else next(
                    (sl.color_id for sl in sales_lines if sl.id == item.sales_order_line_id), None
                )) == color_id
            ]
            if len(matches) != 1:
                raise FgError("ambiguous_sales_source", "箱内色码无法唯一对应销售明细，请在后台拆箱处理")
            shipment_lines.append(
                {"sales_order_line_item_id": matches[0].id, "qty": int(line.qty)}
            )
    elif order:
        item_index = {(item.color_id, item.size_id): item for item in order.items}
        for line in carton_lines:
            color_id = line.color_id if line.color_id is not None else None
            item = item_index.get((color_id, line.size_id))
            if not item:
                raise FgError("item_not_found", "箱内色码无法对应生产单明细")
            shipment_lines.append({"order_item_id": item.id, "qty": int(line.qty)})
    else:
        raise FgError("no_sales_source", "箱唛没有销售来源，禁止出库")

    # 先在当前事务扣减每个色码成品库存；create_shipment(confirm=True) 会一并提交。
    ledger_rows: list[dict] = []
    for line in carton_lines:
        color_id = line.color_id if line.color_id is not None else (header.color_id if header else None)
        stock = get_or_create_fg_stock(
            db,
            tenant_id=tenant_id,
            own_product_id=int(own_product_id),
            color_id=color_id,
            size_id=int(line.size_id),
        )
        qty = int(line.qty)
        if int(stock.qty or 0) < qty:
            raise FgError("fg_insufficient", f"成品仓不足：箱码 {carton.code} 有 {qty} 双，库存仅 {stock.qty or 0}")
        stock.qty = int(stock.qty or 0) - qty
        ledger = FgLedger(
            tenant_id=tenant_id,
            fg_stock_id=stock.id,
            direction="out",
            qty=qty,
            order_id=plan.order_id,
            execution_id=None,
            trace_unit_id=None,
            ref_type="carton_ship",
            ref_id=carton.id,
            note=note or f"扫码箱出库 {carton.code}",
            created_by=created_by,
        )
        db.add(ledger)
        ledger_rows.append({"fg_stock_id": stock.id, "size_id": line.size_id, "qty": qty})

    try:
        shipment = shipment_service.create_shipment(
            db,
            tenant_id,
            sales_order_id=sales_order_id,
            order_id=None if sales_order_id else order.id,
            lines=shipment_lines,
            notes=note or f"扫箱唛出库 {carton.code}",
            user_id=created_by,
            confirm=False,
        )
    except shipment_service.ShipmentError as exc:
        db.rollback()
        raise FgError(exc.code, exc.message) from exc

    carton = db.get(PackingCarton, carton_id)
    carton.shipment_id = int(shipment["id"])
    carton.verified_at = carton.verified_at or datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    try:
        shipment = shipment_service.confirm_shipment(db, tenant_id, carton.shipment_id)
    except shipment_service.ShipmentError as exc:
        # create_shipment 的现有契约会提交草稿；确认若失败，保留草稿与箱关联，
        # 但恢复本次尚未正式过账的成品扣减，避免库存账先走。
        for row in ledger_rows:
            stock = db.get(FgStock, row["fg_stock_id"])
            if stock:
                stock.qty = int(stock.qty or 0) + int(row["qty"])
        for ledger in list(
            db.scalars(
                select(FgLedger).where(
                    FgLedger.tenant_id == tenant_id,
                    FgLedger.ref_type == "carton_ship",
                    FgLedger.ref_id == carton.id,
                )
            ).all()
        ):
            db.delete(ledger)
        carton.shipment_id = None
        db.commit()
        raise FgError(exc.code, exc.message) from exc
    return {
        "carton_id": carton.id,
        "code": carton.code,
        "shipment_id": carton.shipment_id,
        "shipment_no": shipment.get("shipment_no"),
        "total_qty": int(carton.total_qty or 0),
        "status": "shipped",
        "ledgers": ledger_rows,
    }


def ship_warehoused_cartons(
    db: Session,
    *,
    tenant_id: int,
    carton_ids: list[int],
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    """批量按箱出库；先统一校验箱状态，再逐箱走正式出库链路。"""
    from app.models import PackingCarton

    ids = list(dict.fromkeys(int(value) for value in carton_ids if int(value) > 0))
    if not ids:
        raise FgError("cartons_required", "请至少选择一个在库箱码")
    if len(ids) > 100:
        raise FgError("too_many_cartons", "单次批量出库最多选择 100 箱")

    cartons = {
        row.id: row
        for row in db.scalars(
            select(PackingCarton).where(
                PackingCarton.tenant_id == tenant_id,
                PackingCarton.id.in_(ids),
            )
        ).all()
    }
    errors: list[str] = []
    for carton_id in ids:
        carton = cartons.get(carton_id)
        if not carton:
            errors.append(f"箱ID {carton_id} 不存在")
        elif carton.shipment_id:
            errors.append(f"{carton.code} 已出库")
        elif not carton.warehoused_at:
            errors.append(f"{carton.code} 尚未入库")
        elif not carton.reported_work_log_id:
            errors.append(f"{carton.code} 尚未包装报工")
    if errors:
        raise FgError("batch_precheck_failed", "；".join(errors[:5]))

    results: list[dict] = []
    failed: list[dict] = []
    for carton_id in ids:
        try:
            results.append(
                ship_warehoused_carton(
                    db,
                    tenant_id=tenant_id,
                    carton_id=carton_id,
                    note=note or "成品仓批量按箱出库",
                    created_by=created_by,
                )
            )
        except FgError as exc:
            failed.append({"carton_id": carton_id, "code": exc.code, "message": exc.message})
            break

    return {
        "requested_count": len(ids),
        "success_count": len(results),
        "failed_count": len(failed),
        "total_qty": sum(int(row.get("total_qty") or 0) for row in results),
        "shipments": results,
        "failed": failed,
    }


def split_money_by_ratio(amount: Decimal, ratios: list[Decimal]) -> list[Decimal]:
    """按 ratio 分摊金额（分）；末行吃余，保证合计=amount。"""
    amount = Decimal(amount or 0).quantize(Decimal("0.01"))
    if not ratios:
        return []
    if amount <= 0:
        return [Decimal("0.00") for _ in ratios]
    out: list[Decimal] = []
    acc = Decimal("0.00")
    for i, r in enumerate(ratios):
        if i == len(ratios) - 1:
            out.append((amount - acc).quantize(Decimal("0.01")))
        else:
            share = (amount * Decimal(r)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if share < 0:
                share = Decimal("0.00")
            out.append(share)
            acc += share
    return out


def shop_order_piecework_total(db: Session, tenant_id: int, shop_order_id: int) -> Decimal:
    """桥接生产单计件总额（锁价 × 计件量）；与工资账同源口径，不含 void。"""
    logs = list(
        db.scalars(
            select(WorkLog).where(
                WorkLog.tenant_id == tenant_id,
                WorkLog.order_id == shop_order_id,
                WorkLog.status.in_([WorkLogStatus.valid, WorkLogStatus.corrected]),
            )
        ).all()
    )
    total = Decimal("0.00")
    for log in logs:
        price = Decimal(log.unit_price or 0)
        rt = _enum_val(log.report_type)
        if rt == ReportType.rework.value:
            qty = int(log.rework_qty or 0)
        else:
            qty = int(log.qualified_qty or 0)
        if qty <= 0 or price <= 0:
            continue
        total += (Decimal(qty) * price).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def header_piecework_total(db: Session, tenant_id: int, header_id: int) -> Decimal:
    """K4-B 无桥接执行单计件总额，口径与桥接单路径相同。"""
    logs = list(
        db.scalars(
            select(WorkLog).where(
                WorkLog.tenant_id == tenant_id,
                WorkLog.header_id == header_id,
                WorkLog.status.in_([WorkLogStatus.valid, WorkLogStatus.corrected]),
            )
        ).all()
    )
    total = Decimal("0.00")
    for log in logs:
        price = Decimal(log.unit_price or 0)
        qty = int(log.rework_qty or 0) if _enum_val(log.report_type) == ReportType.rework.value else int(log.qualified_qty or 0)
        if qty > 0 and price > 0:
            total += (Decimal(qty) * price).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def execution_piecework_total(db: Session, tenant_id: int, execution: SpecExecutionOrder) -> Decimal:
    if execution.shop_order_id:
        return shop_order_piecework_total(db, tenant_id, int(execution.shop_order_id))
    if execution.header_id:
        return header_piecework_total(db, tenant_id, int(execution.header_id))
    return Decimal("0.00")


def allocate_labor_cost_for_basket(
    db: Session,
    *,
    tenant_id: int,
    unit: TraceUnit,
    execution: SpecExecutionOrder,
    produced_splits: list[dict],
    ref_type: str,
    created_by: int | None = None,
) -> list[dict]:
    """筐入库/直发：把执行单计件成本按剩余池切一刀，再按分配 ratio 摊到销售色码。"""
    if not produced_splits:
        return []
    basket_qty = int(unit.qty or 0)
    if basket_qty <= 0:
        return []

    source_total = execution_piecework_total(db, tenant_id, execution)
    already = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(SalesLineLaborAllocation.labor_amount), 0)).where(
                SalesLineLaborAllocation.tenant_id == tenant_id,
                SalesLineLaborAllocation.execution_id == execution.id,
            )
        )
        or 0
    ).quantize(Decimal("0.01"))
    pool_remaining = (source_total - already).quantize(Decimal("0.01"))
    if pool_remaining <= 0:
        return []

    terminal_qty = int(
        db.scalar(
            select(func.coalesce(func.sum(TraceUnit.qty), 0)).where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.execution_id == execution.id,
                TraceUnit.unit_type == TraceUnitType.basket,
                TraceUnit.status.in_(
                    (TraceUnitStatus.warehoused, TraceUnitStatus.shipped)
                ),
                TraceUnit.id != unit.id,
            )
        )
        or 0
    )
    remaining_qty = max(0, int(execution.total_qty or 0) - terminal_qty)
    if remaining_qty <= 0:
        remaining_qty = basket_qty

    if remaining_qty == basket_qty:
        basket_pool = pool_remaining
    else:
        basket_pool = (
            pool_remaining * Decimal(basket_qty) / Decimal(remaining_qty)
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if basket_pool > pool_remaining:
            basket_pool = pool_remaining
    if basket_pool <= 0:
        return []

    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == execution.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    if getattr(unit, "sales_order_id", None) is not None:
        # 合单分筐：本筐人工成本只归集到自己的销售订单
        allocs = [
            a for a in allocs
            if int(a.sales_order_id or 0) == int(unit.sales_order_id)
        ]
    if not allocs:
        return []
    money_shares = split_money_by_ratio(basket_pool, [Decimal(a.ratio) for a in allocs])
    qty_by_item = {int(r["sales_order_line_item_id"]): int(r["qty"]) for r in produced_splits}

    out: list[dict] = []
    for a, money in zip(allocs, money_shares):
        if money <= 0 and qty_by_item.get(int(a.sales_order_line_item_id), 0) <= 0:
            continue
        item = db.get(SalesOrderLineItem, a.sales_order_line_item_id)
        if item:
            item.labor_cost = Decimal(getattr(item, "labor_cost", 0) or 0) + money
        row = SalesLineLaborAllocation(
            tenant_id=tenant_id,
            sales_order_id=a.sales_order_id,
            sales_order_line_item_id=a.sales_order_line_item_id,
            execution_id=execution.id,
            shop_order_id=execution.shop_order_id,
            trace_unit_id=unit.id,
            qty_share=int(qty_by_item.get(int(a.sales_order_line_item_id), 0)),
            ratio=Decimal(a.ratio),
            source_labor_amount=basket_pool,
            labor_amount=money,
            ref_type=ref_type,
            created_by=created_by,
        )
        db.add(row)
        so = db.get(SalesOrder, a.sales_order_id)
        out.append(
            {
                "sales_order_id": a.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "sales_order_line_item_id": a.sales_order_line_item_id,
                "qty_share": row.qty_share,
                "ratio": float(a.ratio),
                "labor_amount": money,
                "labor_cost": Decimal(getattr(item, "labor_cost", 0) or 0) if item else money,
                "source_labor_amount": basket_pool,
                "shop_order_piecework_total": source_total,
            }
        )
    db.flush()
    return out


def list_execution_labor_allocations(
    db: Session, *, tenant_id: int, execution_id: int
) -> dict:
    execution = db.get(SpecExecutionOrder, execution_id)
    if not execution or execution.tenant_id != tenant_id:
        raise FgError("execution_not_found", "生产单不存在")
    rows = list(
        db.scalars(
            select(SalesLineLaborAllocation)
            .where(
                SalesLineLaborAllocation.tenant_id == tenant_id,
                SalesLineLaborAllocation.execution_id == execution_id,
            )
            .order_by(SalesLineLaborAllocation.id)
        ).all()
    )
    source_total = execution_piecework_total(db, tenant_id, execution)
    allocated = sum((Decimal(r.labor_amount or 0) for r in rows), Decimal("0")).quantize(
        Decimal("0.01")
    )
    items = []
    for r in rows:
        so = db.get(SalesOrder, r.sales_order_id)
        items.append(
            {
                "id": r.id,
                "sales_order_id": r.sales_order_id,
                "sales_order_no": so.order_no if so else None,
                "sales_order_line_item_id": r.sales_order_line_item_id,
                "trace_unit_id": r.trace_unit_id,
                "qty_share": r.qty_share,
                "ratio": float(r.ratio),
                "labor_amount": r.labor_amount,
                "source_labor_amount": r.source_labor_amount,
                "ref_type": r.ref_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return {
        "execution_id": execution.id,
        "execution_no": execution.execution_no,
        "shop_order_id": execution.shop_order_id,
        "shop_order_piecework_total": source_total,
        "allocated_labor_total": allocated,
        "unallocated_labor": (source_total - allocated).quantize(Decimal("0.01")),
        "items": items,
    }


def _route_process_counts(row: dict) -> bool:
    """与生产进度一致：没派到工艺路线部门的工序不参与完工。"""
    route_ids = {int(item) for item in (row.get("route_department_ids") or []) if int(item)}
    if row.get("route_department_shared") or not route_ids:
        return True
    assigned = [int(item) for item in (row.get("assigned_department_ids") or []) if int(item)]
    if not assigned:
        return True
    return any(item in route_ids for item in assigned)


def _last_segment_finished(progress: list[dict], sorts: dict[int, int]) -> bool:
    """工艺路线里最后一个有工序的工序段，完工不少于计划才进成品仓。"""
    groups: dict[int, list[dict]] = {}
    for row in progress:
        segment_id = row.get("segment_id")
        if not segment_id or not _route_process_counts(row):
            continue
        groups.setdefault(int(segment_id), []).append(row)
    if not groups:
        return False
    last_id = max(groups, key=lambda sid: (sorts.get(sid, 0), sid))
    effective = [row for row in groups[last_id] if float(row.get("plan_qty") or 0) > 0]
    if not effective:
        return False
    return all(
        float(row.get("completed_qty") or 0) + 1e-6 >= float(row.get("plan_qty") or 0)
        for row in effective
    )


def _segment_bottleneck_done(rows: list[dict]) -> float:
    """与生产进度一致：段内按最低完成率折算完工双数。"""
    effective = [row for row in rows if float(row.get("plan_qty") or 0) > 0]
    if not effective:
        return 0.0
    plan = max(float(row.get("plan_qty") or 0) for row in effective)
    if plan <= 0:
        return 0.0
    rate = min(
        min(1.0, max(0.0, float(row.get("completed_qty") or 0)) / float(row.get("plan_qty") or 1))
        for row in effective
    )
    return min(plan, plan * rate)


def _last_segment_done_pairs(progress: list[dict], sorts: dict[int, int]) -> float:
    """最后一个有工序的工序段已经做完的双数。没做完的不能入成品仓。"""
    groups: dict[int, list[dict]] = {}
    for row in progress:
        segment_id = row.get("segment_id")
        if not segment_id or not _route_process_counts(row):
            continue
        groups.setdefault(int(segment_id), []).append(row)
    if not groups:
        return 0.0
    last_id = max(groups, key=lambda sid: (sorts.get(sid, 0), sid))
    return _segment_bottleneck_done(groups[last_id])


def _pair_total_for_cartons(total_pairs: int, cartons: int, order_cartons: int) -> int:
    if total_pairs <= 0 or cartons <= 0 or order_cartons <= 0:
        return 0
    if cartons >= order_cartons:
        return total_pairs
    exact = total_pairs * cartons
    target = exact // order_cartons
    if exact % order_cartons * 2 >= order_cartons:
        target += 1
    return min(total_pairs, target)


def _max_cartons_for_pairs(total_pairs: int, order_cartons: int, limit_pairs: float) -> int:
    """箱数换成的双数不能超过已完工双数。"""
    if total_pairs <= 0 or order_cartons <= 0 or limit_pairs <= 0:
        return 0
    best = 0
    lo = 0
    hi = order_cartons
    while lo <= hi:
        mid = (lo + hi) // 2
        if _pair_total_for_cartons(total_pairs, mid, order_cartons) <= limit_pairs + 1e-6:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fmt_pairs(value: float) -> str:
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _allocate_size_cartons(size_qty: dict[int, int], cartons: int, order_cartons: int) -> dict[int, int]:
    """按箱数从各码计划里拆出双数。"""
    weights = [(int(size_id), int(qty or 0)) for size_id, qty in size_qty.items() if int(qty or 0) > 0]
    if order_cartons <= 0 or cartons <= 0 or not weights:
        return {}
    if cartons >= order_cartons:
        return {size_id: qty for size_id, qty in weights}
    bases = [qty * cartons // order_cartons for _, qty in weights]
    fracs = [qty * cartons % order_cartons for _, qty in weights]
    total = sum(qty for _, qty in weights)
    exact = total * cartons
    target = min(total, exact // order_cartons + (1 if exact % order_cartons * 2 >= order_cartons else 0))
    leftover = target - sum(bases)
    order = sorted(range(len(weights)), key=lambda i: (fracs[i], weights[i][1]), reverse=True)
    for index in order:
        if leftover <= 0:
            break
        room = weights[index][1] - bases[index]
        if room <= 0:
            continue
        take = min(room, leftover)
        bases[index] += take
        leftover -= take
    return {weights[i][0]: bases[i] for i in range(len(weights)) if bases[i] > 0}


def _warehouse_stock(
    db: Session,
    tenant_id: int,
    lines_by_header: dict[int, list[SalesOrderLine]],
    finished_ids: set[int] | None = None,
    done_pairs_by_header: dict[int, float] | None = None,
) -> dict[int, dict | None]:
    """各生产单还在成品仓的箱数和各码双数。没有销售色码时返回 None，调用方沿用生产码数。"""
    line_header: dict[int, int] = {}
    for header_id, lines in lines_by_header.items():
        for line in lines:
            line_header[int(line.id)] = int(header_id)
    if not line_header:
        return {int(header_id): None for header_id in lines_by_header}
    items = list(
        db.scalars(
            select(SalesOrderLineItem).where(
                SalesOrderLineItem.tenant_id == tenant_id,
                SalesOrderLineItem.sales_order_line_id.in_(line_header),
            )
        ).all()
    )
    line_pairs: dict[int, int] = {}
    line_shipped_pairs: dict[int, int] = {}
    line_plan_sizes: dict[int, dict[int, int]] = {}
    line_unshipped_sizes: dict[int, dict[int, int]] = {}
    headers_with_items: set[int] = set()
    for item in items:
        header_id = line_header.get(int(item.sales_order_line_id))
        if header_id is None:
            continue
        headers_with_items.add(header_id)
        line_id = int(item.sales_order_line_id)
        size_id = int(item.size_id)
        plan_qty = int(item.qty or 0)
        shipped_qty = int(item.shipped_qty or 0)
        line_pairs[line_id] = line_pairs.get(line_id, 0) + plan_qty
        line_shipped_pairs[line_id] = line_shipped_pairs.get(line_id, 0) + shipped_qty
        plan_bucket = line_plan_sizes.setdefault(line_id, {})
        plan_bucket[size_id] = plan_bucket.get(size_id, 0) + plan_qty
        left = max(0, plan_qty - shipped_qty)
        if left:
            left_bucket = line_unshipped_sizes.setdefault(line_id, {})
            left_bucket[size_id] = left_bucket.get(size_id, 0) + left
    result: dict[int, dict | None] = {}
    for header_id, lines in lines_by_header.items():
        header_id = int(header_id)
        if header_id not in headers_with_items:
            result[header_id] = None
            continue
        finished = finished_ids is None or header_id in finished_ids
        orders_out: list[dict] = []
        header_sizes: dict[int, int] = {}
        header_cartons = 0
        grouped_lines: dict[int, list[SalesOrderLine]] = {}
        for line in lines:
            grouped_lines.setdefault(int(line.sales_order_id), []).append(line)
        drafts: list[dict] = []
        for sales_order_id, order_lines in grouped_lines.items():
            order_cartons = sum(max(0, int(line.carton_qty or 0)) for line in order_lines)
            plan_sizes: dict[int, int] = {}
            unshipped_sizes: dict[int, int] = {}
            plan_pairs = 0
            shipped_pairs = 0
            intake_cartons = 0
            for line in order_lines:
                line_id = int(line.id)
                intake_cartons += max(0, int(line.fg_intake_carton_qty or 0))
                plan_pairs += line_pairs.get(line_id, 0)
                shipped_pairs += line_shipped_pairs.get(line_id, 0)
                for size_id, qty in line_plan_sizes.get(line_id, {}).items():
                    plan_sizes[size_id] = plan_sizes.get(size_id, 0) + qty
                for size_id, qty in line_unshipped_sizes.get(line_id, {}).items():
                    unshipped_sizes[size_id] = unshipped_sizes.get(size_id, 0) + qty
            if order_cartons <= 0 or plan_pairs <= 0:
                continue
            drafts.append(
                {
                    "sales_order_id": sales_order_id,
                    "order_cartons": order_cartons,
                    "plan_pairs": plan_pairs,
                    "intake_cartons": intake_cartons,
                    "shipped_pairs": shipped_pairs,
                    "plan_sizes": plan_sizes,
                    "unshipped_sizes": unshipped_sizes,
                }
            )
        if not finished:
            room = float((done_pairs_by_header or {}).get(header_id, 0) or 0)
            for draft in sorted(drafts, key=lambda item: int(item["sales_order_id"])):
                allowed = _max_cartons_for_pairs(int(draft["plan_pairs"]), int(draft["order_cartons"]), room)
                draft["intake_cartons"] = min(int(draft["intake_cartons"]), allowed)
                room = max(
                    0.0,
                    room
                    - _pair_total_for_cartons(
                        int(draft["plan_pairs"]),
                        int(draft["intake_cartons"]),
                        int(draft["order_cartons"]),
                    ),
                )
        for draft in drafts:
            order_cartons = int(draft["order_cartons"])
            plan_pairs = int(draft["plan_pairs"])
            intake_cartons = int(draft["intake_cartons"])
            shipped_pairs = int(draft["shipped_pairs"])
            plan_sizes = draft["plan_sizes"]
            unshipped_sizes = draft["unshipped_sizes"]
            sales_order_id = int(draft["sales_order_id"])
            shipped_cartons_est = min(order_cartons, shipped_pairs * order_cartons // plan_pairs)
            released = order_cartons if finished else min(order_cartons, intake_cartons)
            warehouse_cartons = max(0, released - shipped_cartons_est)
            raw_sizes = _allocate_size_cartons(plan_sizes, warehouse_cartons, order_cartons)
            order_sizes = {
                size_id: min(qty, unshipped_sizes.get(size_id, 0))
                for size_id, qty in raw_sizes.items()
                if min(qty, unshipped_sizes.get(size_id, 0)) > 0
            }
            if not order_sizes:
                continue
            for size_id, qty in order_sizes.items():
                header_sizes[size_id] = header_sizes.get(size_id, 0) + qty
            header_cartons += warehouse_cartons
            orders_out.append(
                {
                    "sales_order_id": sales_order_id,
                    "sizes": order_sizes,
                    "cartons": warehouse_cartons,
                }
            )
        result[header_id] = {
            "sizes": header_sizes,
            "cartons": header_cartons,
            "orders": orders_out,
        }
    return result


def _defective_snapshot(header: ExecutionHeader) -> tuple[dict[int, int], int]:
    raw = header.fg_defective_sizes or {}
    sizes: dict[int, int] = {}
    if isinstance(raw, dict):
        for key, qty in raw.items():
            try:
                sizes[int(key)] = max(0, int(qty or 0))
            except (TypeError, ValueError):
                continue
    return sizes, max(0, int(header.fg_defective_carton_qty or 0))


def _split_warehouse(header: ExecutionHeader, position: dict | None) -> tuple[dict[int, int], int, dict[int, int], int]:
    """在仓数量拆成待出货和次品。次品只扣已标记的箱数，后来退回的仍算待出货。"""
    if not position:
        return {}, 0, {}, 0
    warehouse = {int(size_id): max(0, int(qty or 0)) for size_id, qty in (position.get("sizes") or {}).items()}
    warehouse_cartons = max(0, int(position.get("cartons") or 0))
    marked, marked_cartons = _defective_snapshot(header)
    # 旧数据只记了次品时间、没记箱数时，当时在仓的都算次品。
    if header.fg_defective_at and not marked and marked_cartons <= 0:
        return {}, 0, {size_id: qty for size_id, qty in warehouse.items() if qty}, warehouse_cartons
    defective = {
        size_id: min(qty, marked.get(size_id, 0))
        for size_id, qty in warehouse.items()
        if min(qty, marked.get(size_id, 0)) > 0
    }
    pending = {
        size_id: qty - defective.get(size_id, 0)
        for size_id, qty in warehouse.items()
        if qty - defective.get(size_id, 0) > 0
    }
    defective_cartons = min(warehouse_cartons, marked_cartons)
    return pending, max(0, warehouse_cartons - defective_cartons), defective, defective_cartons


def list_finished_orders(
    db: Session,
    *,
    tenant_id: int,
    q: str | None = None,
    status: str = "in_stock",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
) -> dict:
    """成品仓 / 出库记录：按生产单，列与订单管理一致。"""
    from app.services.execution_service import _headers_process_progress_batch

    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.parent_header_id.is_(None),
                ExecutionHeader.status != SpecExecutionStatus.cancelled,
            )
        ).all()
    )
    if status == "shipped":
        headers = [h for h in headers if h.fg_shipped_at and not h.fg_defective_at]
        if date_from:
            headers = [h for h in headers if h.fg_shipped_at and h.fg_shipped_at.date() >= date_from]
        if date_to:
            headers = [h for h in headers if h.fg_shipped_at and h.fg_shipped_at.date() <= date_to]
    elif status == "defective":
        headers = [h for h in headers if h.fg_defective_at]
    if not headers:
        return {"items": [], "total": 0, "sizes": []}

    sorts = {
        int(seg.id): int(seg.sort_order or 0)
        for seg in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }
    progress = _headers_process_progress_batch(db, headers)
    finished_ids = {
        int(h.id) for h in headers if _last_segment_finished(progress.get(h.id) or [], sorts)
    }
    done_pairs = {
        int(h.id): _last_segment_done_pairs(progress.get(h.id) or [], sorts) for h in headers
    }
    if status != "shipped":
        intake_ids = {
            int(header_id)
            for header_id in db.scalars(
                select(SalesOrderLine.execution_header_id).where(
                    SalesOrderLine.tenant_id == tenant_id,
                    SalesOrderLine.execution_header_id.in_([int(h.id) for h in headers] or [0]),
                    SalesOrderLine.fg_intake_carton_qty > 0,
                )
            ).all()
            if header_id
        }
        if status == "defective":
            headers = [h for h in headers if int(h.id) in finished_ids or int(h.id) in intake_ids]
            headers = _headers_in_bucket(db, tenant_id, headers, "defective", finished_ids, done_pairs)
        else:
            headers = [h for h in headers if int(h.id) in finished_ids or int(h.id) in intake_ids]
            headers = _headers_in_bucket(db, tenant_id, headers, "pending", finished_ids, done_pairs)
    headers.sort(
        key=lambda h: (
            (h.fg_defective_at if status == "defective" else h.fg_shipped_at) or h.created_at or datetime.min,
            h.id,
        ),
        reverse=True,
    )
    headers = headers[:limit]
    return _finished_order_rows(
        db,
        tenant_id,
        headers,
        q,
        warehouse_only=status != "shipped",
        stock_view="defective" if status == "defective" else ("pending" if status != "shipped" else None),
        finished_ids=finished_ids if status != "shipped" else None,
        done_pairs_by_header=done_pairs if status != "shipped" else None,
    )


def _lines_by_header(
    db: Session, tenant_id: int, headers: list[ExecutionHeader]
) -> dict[int, list[SalesOrderLine]]:
    header_ids = [int(h.id) for h in headers]
    if not header_ids:
        return {}
    sales_lines = list(
        db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.execution_header_id.in_(header_ids),
            )
        ).all()
    )
    linked_ids = {int(h.sales_order_line_id) for h in headers if h.sales_order_line_id}
    missing = linked_ids - {int(line.id) for line in sales_lines}
    if missing:
        sales_lines.extend(
            db.scalars(
                select(SalesOrderLine).where(
                    SalesOrderLine.tenant_id == tenant_id,
                    SalesOrderLine.id.in_(missing),
                )
            ).all()
        )
    grouped: dict[int, list[SalesOrderLine]] = {}
    for line in sales_lines:
        if line.execution_header_id:
            grouped.setdefault(int(line.execution_header_id), []).append(line)
    for header in headers:
        if header.sales_order_line_id and int(header.id) not in grouped:
            match = next((line for line in sales_lines if int(line.id) == int(header.sales_order_line_id)), None)
            if match:
                grouped.setdefault(int(header.id), []).append(match)
    return grouped


def _headers_in_bucket(
    db: Session,
    tenant_id: int,
    headers: list[ExecutionHeader],
    bucket: str,
    finished_ids: set[int] | None = None,
    done_pairs_by_header: dict[int, float] | None = None,
) -> list[ExecutionHeader]:
    """待出货看退回后还没标次品的数量；次品只看已标记的数量。"""
    if not headers:
        return []
    stock = _warehouse_stock(
        db,
        tenant_id,
        _lines_by_header(db, tenant_id, headers),
        finished_ids,
        done_pairs_by_header,
    )
    kept: list[ExecutionHeader] = []
    for header in headers:
        position = stock.get(int(header.id))
        pending, _pending_cartons, defective, _defective_cartons = _split_warehouse(header, position)
        if bucket == "defective":
            if sum(defective.values()) > 0:
                kept.append(header)
            continue
        if sum(pending.values()) > 0 or (position is None and not header.fg_shipped_at and not header.fg_defective_at):
            kept.append(header)
    return kept


def _finished_order_rows(
    db: Session,
    tenant_id: int,
    headers: list[ExecutionHeader],
    q: str | None,
    warehouse_only: bool = False,
    stock_view: str | None = None,
    finished_ids: set[int] | None = None,
    done_pairs_by_header: dict[int, float] | None = None,
) -> dict:
    header_ids = [int(h.id) for h in headers]
    if not header_ids:
        return {"items": [], "total": 0, "sizes": []}
    products = {
        int(p.id): p
        for p in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_({int(h.own_product_id) for h in headers}),
            )
        ).all()
    }
    colors = {
        int(c.id): c.name
        for c in db.scalars(
            select(Color).where(
                Color.tenant_id == tenant_id,
                Color.id.in_({int(h.color_id) for h in headers if h.color_id}),
            )
        ).all()
    } if any(h.color_id for h in headers) else {}
    size_lines = list(
        db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.header_id.in_(header_ids),
            )
        ).all()
    )
    size_names = {
        int(s.id): s.size_value
        for s in db.scalars(
            select(Size).where(Size.id.in_({int(line.size_id) for line in size_lines} or {0}))
        ).all()
    }
    sales_lines = list(
        db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.execution_header_id.in_(header_ids),
            )
        ).all()
    )
    linked_ids = {int(h.sales_order_line_id) for h in headers if h.sales_order_line_id}
    missing = linked_ids - {int(line.id) for line in sales_lines}
    if missing:
        sales_lines.extend(
            db.scalars(
                select(SalesOrderLine).where(
                    SalesOrderLine.tenant_id == tenant_id,
                    SalesOrderLine.id.in_(missing),
                )
            ).all()
        )
    lines_by_header: dict[int, list[SalesOrderLine]] = {}
    for line in sales_lines:
        if line.execution_header_id:
            lines_by_header.setdefault(int(line.execution_header_id), []).append(line)
    for header in headers:
        if header.sales_order_line_id and int(header.id) not in lines_by_header:
            match = next((line for line in sales_lines if int(line.id) == int(header.sales_order_line_id)), None)
            if match:
                lines_by_header.setdefault(int(header.id), []).append(match)
    order_ids = {int(line.sales_order_id) for line in sales_lines}
    orders = {
        int(order.id): order
        for order in db.scalars(
            select(SalesOrder).where(SalesOrder.id.in_(order_ids or {0}))
        ).all()
    } if order_ids else {}
    shipper_ids = {int(h.fg_shipped_by) for h in headers if h.fg_shipped_by}
    shippers = {
        int(emp.id): emp.name
        for emp in db.scalars(select(Employee).where(Employee.id.in_(shipper_ids or {0}))).all()
    } if shipper_ids else {}
    sizes_by_header: dict[int, dict[int, int]] = {}
    for line in size_lines:
        if not line.header_id:
            continue
        bucket = sizes_by_header.setdefault(int(line.header_id), {})
        bucket[int(line.size_id)] = bucket.get(int(line.size_id), 0) + int(line.total_qty or 0)
    stock_by_header = (
        _warehouse_stock(db, tenant_id, lines_by_header, finished_ids, done_pairs_by_header)
        if warehouse_only
        else {}
    )
    extra_size_ids = {
        int(size_id)
        for position in stock_by_header.values()
        if position
        for size_id in position["sizes"]
    }
    missing_sizes = extra_size_ids - set(size_names)
    if missing_sizes:
        for size in db.scalars(select(Size).where(Size.id.in_(missing_sizes))).all():
            size_names[int(size.id)] = size.size_value

    needle = (q or "").strip().lower()
    items = []
    size_catalog: dict[int, str] = {}
    for header in headers:
        lines = sorted(lines_by_header.get(int(header.id), []), key=lambda line: int(line.sort_order or 0))
        related_orders = [orders[int(line.sales_order_id)] for line in lines if int(line.sales_order_id) in orders]
        product = products.get(int(header.own_product_id))
        order_nos = list(dict.fromkeys(order.order_no for order in related_orders if order.order_no))
        customers = list(dict.fromkeys(order.customer_name for order in related_orders if order.customer_name))
        brands = list(dict.fromkeys((line.brand_name or "").strip() for line in lines if (line.brand_name or "").strip()))
        skus = list(dict.fromkeys((line.customer_sku or "").strip() for line in lines if (line.customer_sku or "").strip()))
        fabrics = list(dict.fromkeys((line.fabric or "").strip() for line in lines if (line.fabric or "").strip()))
        linings = list(dict.fromkeys((line.lining or "").strip() for line in lines if (line.lining or "").strip()))
        notes = list(dict.fromkeys((line.notes or "").strip() for line in lines if (line.notes or "").strip()))
        if not notes and (header.notes or "").strip():
            notes = [(header.notes or "").strip()]
        product_code = product.product_code if product else ""
        row_sizes = [
            {
                "size_id": size_id,
                "size_value": size_names.get(size_id) or str(size_id),
                "qty": qty,
            }
            for size_id, qty in sorted(
                sizes_by_header.get(int(header.id), {}).items(),
                key=lambda item: size_names.get(item[0]) or "",
            )
            if qty
        ]
        carton_qty = sum(int(line.carton_qty or 0) for line in lines)
        if warehouse_only:
            position = stock_by_header.get(int(header.id))
            if position is None:
                if header.fg_shipped_at:
                    continue
            else:
                pending_sizes, pending_cartons, defective_sizes, defective_cartons = _split_warehouse(header, position)
                shown = defective_sizes if stock_view == "defective" else pending_sizes
                shown_cartons = defective_cartons if stock_view == "defective" else pending_cartons
                row_sizes = [
                    {
                        "size_id": size_id,
                        "size_value": size_names.get(size_id) or str(size_id),
                        "qty": qty,
                    }
                    for size_id, qty in sorted(
                        shown.items(),
                        key=lambda item: size_names.get(item[0]) or "",
                    )
                    if qty
                ]
                carton_qty = int(shown_cartons)
                if not row_sizes:
                    continue
        slices = [(lines, row_sizes, carton_qty, None)]
        if warehouse_only:
            position = stock_by_header.get(int(header.id))
            order_parts = list((position or {}).get("orders") or [])
            if order_parts:
                budget = {int(size["size_id"]): int(size["qty"]) for size in row_sizes}
                slices = []
                for part in order_parts:
                    part_lines = [
                        line for line in lines if int(line.sales_order_id) == int(part["sales_order_id"])
                    ]
                    taken: dict[int, int] = {}
                    for size_id, qty in (part.get("sizes") or {}).items():
                        allow = budget.get(int(size_id), 0)
                        use = min(int(qty), allow)
                        if use <= 0:
                            continue
                        taken[int(size_id)] = use
                        budget[int(size_id)] = allow - use
                    if not taken:
                        continue
                    part_pairs = sum(int(qty) for qty in (part.get("sizes") or {}).values())
                    taken_pairs = sum(taken.values())
                    part_cartons = int(part.get("cartons") or 0)
                    if part_pairs and taken_pairs < part_pairs:
                        part_cartons = max(1, int(round(part_cartons * taken_pairs / part_pairs)))
                    part_row = [
                        {
                            "size_id": size_id,
                            "size_value": size_names.get(size_id) or str(size_id),
                            "qty": qty,
                        }
                        for size_id, qty in sorted(taken.items(), key=lambda item: size_names.get(item[0]) or "")
                    ]
                    slices.append((part_lines or lines, part_row, part_cartons, int(part["sales_order_id"])))
        for slice_lines, slice_sizes, slice_cartons, sales_order_id in slices:
            slice_orders = [orders[int(line.sales_order_id)] for line in slice_lines if int(line.sales_order_id) in orders]
            slice_order_nos = list(dict.fromkeys(order.order_no for order in slice_orders if order.order_no))
            slice_customers = list(dict.fromkeys(order.customer_name for order in slice_orders if order.customer_name))
            slice_brands = list(dict.fromkeys((line.brand_name or "").strip() for line in slice_lines if (line.brand_name or "").strip()))
            slice_skus = list(dict.fromkeys((line.customer_sku or "").strip() for line in slice_lines if (line.customer_sku or "").strip()))
            slice_fabrics = list(dict.fromkeys((line.fabric or "").strip() for line in slice_lines if (line.fabric or "").strip()))
            slice_linings = list(dict.fromkeys((line.lining or "").strip() for line in slice_lines if (line.lining or "").strip()))
            slice_notes = list(dict.fromkeys((line.notes or "").strip() for line in slice_lines if (line.notes or "").strip()))
            if not slice_notes and (header.notes or "").strip():
                slice_notes = [(header.notes or "").strip()]
            ordered_at = min((order.ordered_at for order in slice_orders if order.ordered_at), default=None)
            item = {
                "id": int(header.id),
                "sales_order_id": sales_order_id,
                "row_key": f"{int(header.id)}-{sales_order_id or 0}",
                "header_no": header.header_no,
                "order_no": "、".join(slice_order_nos) or header.header_no,
                "customer_name": "、".join(slice_customers),
                "ordered_at": ordered_at.isoformat() if ordered_at else None,
                "sort_no": int(slice_lines[0].sort_order or 0) + 1 if slice_lines else 1,
                "product_code": product_code,
                "product_image_url": product.image_url if product else None,
                "color_name": colors.get(int(header.color_id)) if header.color_id else None,
                "fabric": "、".join(slice_fabrics),
                "lining": "、".join(slice_linings),
                "brand_name": "、".join(slice_brands),
                "customer_sku": "、".join(slice_skus),
                "lines": slice_sizes,
                "carton_qty": slice_cartons,
                "total_qty": sum(int(size["qty"]) for size in slice_sizes) or int(header.total_qty or 0),
                "delivery_date": header.delivery_date.isoformat() if header.delivery_date else None,
                "notes": "、".join(slice_notes),
                "defective_at": header.fg_defective_at.isoformat(sep=" ", timespec="seconds") if header.fg_defective_at else None,
                "shipped_at": header.fg_shipped_at.isoformat(sep=" ", timespec="seconds") if header.fg_shipped_at else None,
                "shipped_by": shippers.get(int(header.fg_shipped_by)) if header.fg_shipped_by else None,
            }
            if needle:
                blob = " ".join(
                    str(part or "")
                    for part in (
                        item["header_no"],
                        item["order_no"],
                        item["customer_name"],
                        item["product_code"],
                        item["brand_name"],
                        item["customer_sku"],
                        item["color_name"],
                        item["notes"],
                    )
                ).lower()
                if needle not in blob:
                    continue
            for size in slice_sizes:
                size_catalog[int(size["size_id"])] = str(size["size_value"])
            items.append(item)
    sizes = [
        {"id": size_id, "value": value}
        for size_id, value in sorted(size_catalog.items(), key=lambda item: item[1], reverse=False)
    ]
    sizes.sort(key=lambda item: item["value"])
    return {"items": items, "total": len(items), "sizes": sizes}


def mark_finished_defective(
    db: Session, *, tenant_id: int, header_id: int, employee_id: int | None
) -> dict:
    """把当前待出货数量放入次品。已退回、尚未标记的数量仍留在待出货。"""
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id or header.parent_header_id:
        raise FgError("not_found", "生产单不存在")
    from app.services.execution_service import _headers_process_progress_batch

    sorts = {
        int(seg.id): int(seg.sort_order or 0)
        for seg in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }
    progress = _headers_process_progress_batch(db, [header])
    if not _last_segment_finished(progress.get(header.id) or [], sorts):
        raise FgError("not_finished", "最后一个工序段尚未完工，不能放入次品")
    sales_lines = _lines_by_header(db, tenant_id, [header]).get(int(header.id), [])
    position = _warehouse_stock(db, tenant_id, {int(header.id): sales_lines}).get(int(header.id))
    pending, pending_cartons, defective, defective_cartons = _split_warehouse(header, position)
    if sum(pending.values()) <= 0:
        raise FgError("not_in_stock", "没有待出货数量，不能放入次品")
    merged = dict(defective)
    for size_id, qty in pending.items():
        merged[int(size_id)] = merged.get(int(size_id), 0) + int(qty)
    header.fg_defective_sizes = {str(size_id): int(qty) for size_id, qty in merged.items() if qty}
    header.fg_defective_carton_qty = int(defective_cartons) + int(pending_cartons)
    if not header.fg_defective_at:
        header.fg_defective_at = datetime.now().replace(microsecond=0)
    header.fg_defective_by = employee_id
    from app.services.execution_service import sync_production_close_status

    sync_production_close_status(db, tenant_id, [int(header.id)])
    db.commit()
    rows = _finished_order_rows(
        db, tenant_id, [header], None, warehouse_only=True, stock_view="defective"
    )
    return rows["items"][0] if rows["items"] else {"id": int(header.id)}


def _intake_header(db: Session, tenant_id: int, header_id: int) -> ExecutionHeader:
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id or header.parent_header_id:
        raise FgError("not_found", "生产单不存在")
    if str(header.status) in {"cancelled", "ExecutionStatus.cancelled"} or getattr(header.status, "value", None) == "cancelled":
        raise FgError("cancelled", "生产单已取消")
    return header


def _intake_lines(db: Session, tenant_id: int, header: ExecutionHeader) -> list[SalesOrderLine]:
    sales_lines = list(
        db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.execution_header_id == header.id,
            )
        ).all()
    )
    if header.sales_order_line_id and all(int(line.id) != int(header.sales_order_line_id) for line in sales_lines):
        extra = db.get(SalesOrderLine, int(header.sales_order_line_id))
        if extra and extra.tenant_id == tenant_id:
            sales_lines.append(extra)
    return sales_lines


def _header_finish_state(db: Session, tenant_id: int, header: ExecutionHeader) -> tuple[bool, float]:
    from app.services.execution_service import _headers_process_progress_batch

    sorts = {
        int(seg.id): int(seg.sort_order or 0)
        for seg in db.scalars(select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)).all()
    }
    progress = _headers_process_progress_batch(db, [header]).get(header.id) or []
    return _last_segment_finished(progress, sorts), _last_segment_done_pairs(progress, sorts)


def fg_intake_sources(db: Session, *, tenant_id: int, header_id: int) -> dict:
    """合单按订单号列出可入成品仓的箱数。"""
    header = _intake_header(db, tenant_id, header_id)
    lines = _intake_lines(db, tenant_id, header)
    order_ids = {int(line.sales_order_id) for line in lines}
    orders = {
        int(order.id): order
        for order in db.scalars(
            select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id.in_(order_ids or {0}))
        ).all()
    } if order_ids else {}
    finished, done_pairs = _header_finish_state(db, tenant_id, header)
    grouped: dict[int, list[SalesOrderLine]] = {}
    for line in lines:
        grouped.setdefault(int(line.sales_order_id), []).append(line)
    stats = []
    for sales_order_id, order_lines in grouped.items():
        order = orders.get(sales_order_id)
        carton_qty = sum(max(0, int(line.carton_qty or 0)) for line in order_lines)
        intake_qty = sum(max(0, int(line.fg_intake_carton_qty or 0)) for line in order_lines)
        plan_pairs = sum(max(0, int(line.total_qty or 0)) for line in order_lines)
        stats.append(
            {
                "sales_order_id": sales_order_id,
                "order_no": order.order_no if order else "",
                "customer_name": order.customer_name if order else "",
                "carton_qty": carton_qty,
                "intake_carton_qty": intake_qty,
                "plan_pairs": plan_pairs,
                "intake_pairs": _pair_total_for_cartons(plan_pairs, intake_qty, carton_qty),
            }
        )
    rows = []
    for stat in stats:
        other_pairs = sum(item["intake_pairs"] for item in stats if item["sales_order_id"] != stat["sales_order_id"])
        room = max(0.0, done_pairs - other_pairs)
        allowed = _max_cartons_for_pairs(int(stat["plan_pairs"]), int(stat["carton_qty"]), room)
        rows.append(
            {
                "sales_order_id": stat["sales_order_id"],
                "order_no": stat["order_no"],
                "customer_name": stat["customer_name"],
                "carton_qty": stat["carton_qty"],
                "intake_carton_qty": stat["intake_carton_qty"],
                "remain_carton_qty": max(0, allowed - int(stat["intake_carton_qty"])),
            }
        )
    rows.sort(key=lambda row: row["order_no"])
    return {
        "header_id": int(header.id),
        "header_no": header.header_no,
        "finished": finished,
        "done_pairs": float(done_pairs),
        "orders": rows,
    }


def intake_finished_cartons(
    db: Session, *, tenant_id: int, header_id: int, orders: list[dict]
) -> dict:
    """未完工时按订单号把箱数放入成品仓。完工后的数量本来就会进待出货。"""
    header = _intake_header(db, tenant_id, header_id)
    finished, done_pairs = _header_finish_state(db, tenant_id, header)
    if finished:
        raise FgError("already_finished", "最后工序段已完工，未出数量已在待出货")
    lines = _intake_lines(db, tenant_id, header)
    grouped: dict[int, list[SalesOrderLine]] = {}
    for line in lines:
        grouped.setdefault(int(line.sales_order_id), []).append(line)
    added = 0
    seen: set[int] = set()
    for row in orders:
        sales_order_id = int(row["sales_order_id"])
        cartons = int(row.get("carton_qty") or 0)
        if cartons < 0:
            raise FgError("invalid_cartons", "箱数不能为负")
        if cartons == 0:
            continue
        if sales_order_id in seen:
            raise FgError("duplicate_order", "订单重复")
        seen.add(sales_order_id)
        order_lines = sorted(grouped.get(sales_order_id) or [], key=lambda line: int(line.sort_order or 0))
        if not order_lines:
            raise FgError("order_not_found", "订单不在这张生产单里")
        capacity = [
            (line, max(0, int(line.carton_qty or 0) - int(line.fg_intake_carton_qty or 0)))
            for line in order_lines
        ]
        remain = sum(cap for _, cap in capacity)
        if cartons > remain:
            raise FgError("over_cartons", "超过该订单剩余箱数")
        left = cartons
        for line, cap in capacity:
            if left <= 0:
                break
            take = min(cap, left)
            line.fg_intake_carton_qty = int(line.fg_intake_carton_qty or 0) + take
            left -= take
        added += cartons
    if added <= 0:
        raise FgError("empty", "请填写箱数")
    projected_pairs = 0
    for sales_order_id, order_lines in grouped.items():
        carton_qty = sum(max(0, int(line.carton_qty or 0)) for line in order_lines)
        intake_qty = sum(max(0, int(line.fg_intake_carton_qty or 0)) for line in order_lines)
        plan_pairs = sum(max(0, int(line.total_qty or 0)) for line in order_lines)
        projected_pairs += _pair_total_for_cartons(plan_pairs, intake_qty, carton_qty)
    if projected_pairs > done_pairs + 1e-6:
        db.rollback()
        raise FgError("over_done", f"已完工 {_fmt_pairs(done_pairs)} 双，入仓不能超过完工数量")
    db.commit()
    return fg_intake_sources(db, tenant_id=tenant_id, header_id=header_id)


def ship_finished_order(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    employee_id: int | None,
    sales_order_id: int | None = None,
) -> dict:
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id or header.parent_header_id:
        raise FgError("not_found", "生产单不存在")

    ship_note = f"成品仓出货 {header.header_no}"
    from app.services.execution_service import _headers_process_progress_batch

    sorts = {
        int(seg.id): int(seg.sort_order or 0)
        for seg in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }
    progress = _headers_process_progress_batch(db, [header])
    finished = _last_segment_finished(progress.get(header.id) or [], sorts)
    from app.services import shipment_service

    sales_lines = list(
        db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.execution_header_id == header.id,
            )
        ).all()
    )
    if header.sales_order_line_id and all(int(line.id) != int(header.sales_order_line_id) for line in sales_lines):
        extra = db.get(SalesOrderLine, int(header.sales_order_line_id))
        if extra and extra.tenant_id == tenant_id:
            sales_lines.append(extra)
    if not sales_lines and header.sales_order_id:
        sales_lines = list(
            db.scalars(
                select(SalesOrderLine).where(
                    SalesOrderLine.tenant_id == tenant_id,
                    SalesOrderLine.sales_order_id == header.sales_order_id,
                    SalesOrderLine.own_product_id == header.own_product_id,
                )
            ).all()
        )
    line_order = {int(line.id): int(line.sales_order_id) for line in sales_lines}
    items = list(
        db.scalars(
            select(SalesOrderLineItem).where(
                SalesOrderLineItem.tenant_id == tenant_id,
                SalesOrderLineItem.sales_order_line_id.in_(line_order or {0}),
            )
        ).all()
    ) if line_order else []
    stock = _warehouse_stock(
        db,
        tenant_id,
        {int(header.id): sales_lines},
        {int(header.id)} if finished else set(),
        {int(header.id): _last_segment_done_pairs(progress.get(header.id) or [], sorts)},
    ).get(int(header.id))
    pending_sizes, _pending_cartons, _defective_sizes, _defective_cartons = _split_warehouse(header, stock)
    orders = list((stock or {}).get("orders") or [])
    if sales_order_id is not None:
        orders = [part for part in orders if int(part.get("sales_order_id") or 0) == int(sales_order_id)]
    budget = {int(size_id): int(qty) for size_id, qty in pending_sizes.items()}
    items_by_order: dict[int, list] = {}
    for item in items:
        items_by_order.setdefault(line_order[int(item.sales_order_line_id)], []).append(item)
    plan: list[tuple[int, list[dict], int]] = []
    for part in orders:
        taken: dict[int, int] = {}
        for size_id, qty in (part.get("sizes") or {}).items():
            use = min(int(qty), budget.get(int(size_id), 0))
            if use <= 0:
                continue
            taken[int(size_id)] = use
            budget[int(size_id)] -= use
        if not taken:
            continue
        remain = dict(taken)
        ship_lines: list[dict] = []
        for item in items_by_order.get(int(part["sales_order_id"]), []):
            size_left = remain.get(int(item.size_id), 0)
            backlog = max(0, int(item.qty or 0) - int(item.shipped_qty or 0))
            qty = min(backlog, size_left)
            if qty <= 0:
                continue
            remain[int(item.size_id)] = size_left - qty
            ship_lines.append({"sales_order_line_item_id": int(item.id), "qty": qty})
        if not ship_lines:
            continue
        part_pairs = sum(int(qty) for qty in (part.get("sizes") or {}).values()) or 1
        taken_pairs = sum(int(row["qty"]) for row in ship_lines)
        cartons = int(part.get("cartons") or 0)
        if taken_pairs < part_pairs:
            cartons = max(1, int(round(cartons * taken_pairs / part_pairs))) if taken_pairs else 0
        plan.append((int(part["sales_order_id"]), ship_lines, cartons))
    if not plan:
        if not finished:
            raise FgError("not_finished", "尚未入成品仓，不能出货")
        raise FgError("nothing_to_ship", "没有可出数量")
    if not header.fg_shipped_at:
        header.fg_shipped_at = datetime.now().replace(microsecond=0)
        header.fg_shipped_by = employee_id
    shipment_ids: list[int] = []
    try:
        for order_id, lines, cartons in plan:
            created = shipment_service.create_shipment(
                db,
                tenant_id,
                sales_order_id=order_id,
                lines=lines,
                notes=ship_note,
                user_id=employee_id,
                confirm=True,
                ignore_produced_gate=True,
                bypass_process_gate=True,
                carton_qty=cartons,
            )
            shipment_ids.append(int(created["id"]))
    except shipment_service.ShipmentError as exc:
        db.rollback()
        raise FgError(exc.code, exc.message) from exc
    rows = _finished_order_rows(db, tenant_id, [header], None)
    data = rows["items"][0] if rows["items"] else {"id": int(header.id)}
    data["shipment_id"] = shipment_ids[0]
    data["shipment_ids"] = shipment_ids
    return data
