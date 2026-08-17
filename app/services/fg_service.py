"""AU-I2：成品仓 + 筐入库。"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    ExecutionAllocation,
    FgLedger,
    FgStock,
    OwnProduct,
    ReportType,
    SalesLineLaborAllocation,
    SalesOrder,
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
            db, tenant_id=tenant_id, execution_id=int(eid), qty=qty
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
