"""经营报告：按日期范围汇总出货、利润、损失与开发成本。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AfterSalesReturn,
    AttendanceDay,
    DefectDisposition,
    DefectEvent,
    Employee,
    Order,
    OrderStatus,
    OwnProduct,
    OwnProductCommission,
    OwnProductLabor,
    OwnProductMaterial,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
)
from app.services.attendance_rules import get_attendance_rules_by_tenant_id
from app.services.attendance_service import LOCAL_OFFSET, _local_date
from app.services.cost_analysis_service import _resolve_range, cost_analysis_report
from app.services.finance_service import (
    _enrich_order_profit_row,
    _order_line_meta,
    _sales_order_line_meta,
    order_profit,
    sales_order_profit,
)

_ZERO = Decimal("0")
_CENT = Decimal("0.01")
_RATE = Decimal("0.0001")


def _money(value: Decimal | float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return _ZERO


def _money_float(value: Decimal | float | int | str | None) -> float:
    return float(_money(value))


def _created_at_window(range_start: date, range_end: date) -> tuple[datetime, datetime]:
    """与报废记录列表相同：按东八区自然日切 created_at。"""
    start = datetime.combine(range_start, time.min) - LOCAL_OFFSET
    end = datetime.combine(range_end + timedelta(days=1), time.min) - LOCAL_OFFSET
    return start, end


def _production_loss_and_scrap(
    db: Session, tenant_id: int, *, range_start: date, range_end: date
) -> tuple[Decimal, int]:
    """生产损失（公司承担）+ 报废双数。"""
    utc_from, utc_to = _created_at_window(range_start, range_end)
    events = db.scalars(
        select(DefectEvent).where(
            DefectEvent.tenant_id == tenant_id,
            DefectEvent.created_at >= utc_from,
            DefectEvent.created_at < utc_to,
        )
    ).all()
    company_loss = _ZERO
    scrap_qty = 0
    for event in events:
        share = int(event.company_share_percent if event.company_share_percent is not None else 100)
        company_loss += _money(event.loss_amount) * Decimal(share) / Decimal(100)
        if event.disposition == DefectDisposition.scrap:
            scrap_qty += int(event.qty or 0)
    return company_loss.quantize(_CENT, rounding=ROUND_HALF_UP), scrap_qty


def _after_sales_loss(
    db: Session, tenant_id: int, *, range_start: date, range_end: date
) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(AfterSalesReturn.loss_amount), 0)).where(
            AfterSalesReturn.tenant_id == tenant_id,
            AfterSalesReturn.return_date >= range_start,
            AfterSalesReturn.return_date <= range_end,
        )
    )
    return _money(total)


def _period_order_rows(
    db: Session, tenant_id: int, *, range_start: date, range_end: date
) -> list[dict]:
    """期间出货订单：利润按期间出货双数占该单已出货双数分摊。"""
    shipments = db.scalars(
        select(Shipment).where(
            Shipment.tenant_id == tenant_id,
            Shipment.status == ShipmentStatus.shipped,
            Shipment.ship_date.is_not(None),
            Shipment.ship_date >= range_start,
            Shipment.ship_date <= range_end,
        )
    ).all()
    period_qty_order: dict[int, int] = defaultdict(int)
    period_qty_so: dict[int, int] = defaultdict(int)
    for shipment in shipments:
        qty = int(shipment.total_qty or 0)
        if shipment.order_id:
            period_qty_order[int(shipment.order_id)] += qty
        elif shipment.sales_order_id:
            period_qty_so[int(shipment.sales_order_id)] += qty

    rows: list[dict] = []
    for oid, period_qty in period_qty_order.items():
        order = db.get(Order, oid)
        if not order or order.tenant_id != tenant_id or period_qty <= 0:
            continue
        try:
            base = order_profit(db, tenant_id, oid)
            meta = _order_line_meta(db, tenant_id, order)
            row = _enrich_order_profit_row(
                db, tenant_id, base, meta=meta, allocated_unit=None
            )
        except Exception:
            continue
        rows.append(_period_order_out(row, period_qty))

    for sid, period_qty in period_qty_so.items():
        so = db.get(SalesOrder, sid)
        if not so or so.tenant_id != tenant_id or period_qty <= 0:
            continue
        try:
            base = sales_order_profit(db, tenant_id, sid)
            product_code = base.get("product_code")
            own_product_id = None
            if product_code:
                prod = db.scalar(
                    select(OwnProduct).where(
                        OwnProduct.tenant_id == tenant_id,
                        OwnProduct.product_code == product_code,
                    )
                )
                own_product_id = prod.id if prod else None
            meta = _sales_order_line_meta(db, tenant_id, so, own_product_id)
            row = _enrich_order_profit_row(
                db, tenant_id, base, meta=meta, allocated_unit=None
            )
        except Exception:
            continue
        rows.append(_period_order_out(row, period_qty))
    return rows


def _period_order_out(row: dict, period_qty: int) -> dict:
    period_profit = _share_profit(row.get("profit"), row.get("shipped_qty"), period_qty)
    return {
        "order_no": row.get("order_no"),
        "customer_name": row.get("customer_name"),
        "brand_name": row.get("brand"),
        "factory_model": row.get("factory_model") or row.get("product_code"),
        "period_qty": int(period_qty),
        "period_profit": period_profit,
    }


def _loss_orders(order_rows: list[dict]) -> list[dict]:
    """期间利润为负的出货，按客户、品牌、工厂型号汇总，亏损金额从大到小。"""
    grouped: dict[tuple, Decimal] = {}
    for row in order_rows:
        profit = row["period_profit"]
        if profit >= 0:
            continue
        key = (
            row.get("customer_name") or None,
            row.get("brand_name") or None,
            row.get("factory_model") or None,
        )
        grouped[key] = grouped.get(key, _ZERO) + (-profit)
    items = [
        {
            "customer_name": customer_name,
            "brand_name": brand_name,
            "factory_model": factory_model,
            "loss_amount": _money_float(amount),
        }
        for (customer_name, brand_name, factory_model), amount in grouped.items()
    ]
    items.sort(
        key=lambda r: (
            -Decimal(str(r["loss_amount"])),
            r.get("customer_name") or "",
            r.get("brand_name") or "",
            r.get("factory_model") or "",
        )
    )
    return items


def _share_profit(profit, shipped_qty, period_qty: int) -> Decimal:
    full_qty = int(shipped_qty or 0)
    if full_qty <= 0 or period_qty <= 0:
        return _ZERO
    share = Decimal(period_qty) / Decimal(full_qty)
    try:
        full_profit = Decimal(str(profit or 0))
    except Exception:
        full_profit = _ZERO
    return (full_profit * share).quantize(_CENT, rounding=ROUND_HALF_UP)


def _utc_at(work_date: date, hhmm: str) -> datetime | None:
    parts = str(hhmm or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return datetime.combine(work_date, time(hour, minute)) - LOCAL_OFFSET


def _billable_late_early(raw_minutes: int, grace_minutes: int) -> int:
    return max(0, int(raw_minutes) - int(grace_minutes or 0))


def _work_bounds(work_date: date, rules: dict) -> tuple[datetime | None, datetime | None]:
    starts: list[datetime] = []
    ends: list[datetime] = []
    for period in rules.get("work_periods") or []:
        if not isinstance(period, dict):
            continue
        start = _utc_at(work_date, str(period.get("start") or ""))
        end = _utc_at(work_date, str(period.get("end") or ""))
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)


def _late_early_today(db: Session, tenant_id: int, today: date) -> tuple[int, int]:
    """今日迟到/早退：人次（迟到、早退各计 1 次）与合计分钟（已扣宽限）。"""
    rules = get_attendance_rules_by_tenant_id(db, tenant_id)
    grace = int((rules.get("late_early_deduction") or {}).get("grace_minutes") or 0)
    scheduled_in, scheduled_out = _work_bounds(today, rules)
    days = db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.work_date == today,
        )
    ).all()
    if not days:
        return 0, 0
    active_ids = set(
        db.scalars(
            select(Employee.id).where(
                Employee.tenant_id == tenant_id,
                Employee.is_active.is_(True),
                Employee.id.in_([d.employee_id for d in days]),
            )
        ).all()
    )
    times = 0
    minutes = 0
    for day in days:
        if day.employee_id not in active_ids:
            continue
        late = 0
        early = 0
        if day.clock_in_at and scheduled_in and day.clock_in_at > scheduled_in:
            raw = int((day.clock_in_at - scheduled_in).total_seconds() // 60)
            late = _billable_late_early(raw, grace)
        elif int(day.late_minutes or 0) > 0:
            late = _billable_late_early(int(day.late_minutes or 0), 0)
        if day.clock_out_at and scheduled_out and day.clock_out_at < scheduled_out:
            raw = int((scheduled_out - day.clock_out_at).total_seconds() // 60)
            early = _billable_late_early(raw, grace)
        elif int(day.early_leave_minutes or 0) > 0:
            early = _billable_late_early(int(day.early_leave_minutes or 0), 0)
        if late > 0:
            times += 1
            minutes += late
        if early > 0:
            times += 1
            minutes += early
    return times, minutes


def _product_std_costs(db: Session, tenant_id: int, product_ids: list[int]) -> dict[int, dict]:
    ids = list({int(pid) for pid in product_ids if pid})
    empty = {
        "shared_material": _ZERO,
        "color_material": {},
        "labor": _ZERO,
        "commission": _ZERO,
        "quote_price": None,
    }
    if not ids:
        return {}
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.id.in_(ids))
        ).all()
    }
    materials = db.scalars(
        select(OwnProductMaterial).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id.in_(ids),
        )
    ).all()
    labors = db.scalars(
        select(OwnProductLabor).where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id.in_(ids),
        )
    ).all()
    commissions = db.scalars(
        select(OwnProductCommission).where(
            OwnProductCommission.tenant_id == tenant_id,
            OwnProductCommission.own_product_id.in_(ids),
        )
    ).all()
    out: dict[int, dict] = {pid: {**empty, "color_material": {}} for pid in ids}
    for pid, product in products.items():
        out[pid]["quote_price"] = product.quote_price
        out[pid]["commission"] = _money(product.commission_cost)
    for row in materials:
        amount = row.line_total
        if amount is None or amount == 0:
            amount = (row.qty or _ZERO) * (row.unit_price or _ZERO)
        amount = _money(amount)
        bucket = out[row.own_product_id]
        if row.color_id:
            color_map: dict = bucket["color_material"]
            color_map[int(row.color_id)] = _money(color_map.get(int(row.color_id), _ZERO) + amount)
        else:
            bucket["shared_material"] = _money(bucket["shared_material"] + amount)
    for row in labors:
        out[row.own_product_id]["labor"] = _money(
            out[row.own_product_id]["labor"] + (row.unit_price or _ZERO)
        )
    comm_by_product: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    for row in commissions:
        comm_by_product[row.own_product_id] += row.amount or _ZERO
    for pid, amount in comm_by_product.items():
        if amount:
            out[pid]["commission"] = _money(amount)
    return out


def _line_unit_profit(cost: dict, *, unit_price, color_id: int | None) -> Decimal:
    price = _money(unit_price if unit_price is not None else cost.get("quote_price"))
    material = cost.get("shared_material") or _ZERO
    if color_id:
        material += (cost.get("color_material") or {}).get(int(color_id), _ZERO)
    labor = cost.get("labor") or _ZERO
    commission = cost.get("commission") or _ZERO
    return (price - material - labor - commission).quantize(_CENT, rounding=ROUND_HALF_UP)


def _current_open_qty_and_profit(
    db: Session, tenant_id: int, today: date
) -> tuple[int, int, Decimal]:
    """未出货双数、逾期未出双数、未出货预计利润。"""
    lines = db.scalars(
        select(SalesOrderLine)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(
            SalesOrderLine.tenant_id == tenant_id,
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.status.notin_([SalesOrderStatus.draft, SalesOrderStatus.cancelled]),
            SalesOrderLine.status != SalesOrderLineStatus.cancelled,
        )
    ).all()
    line_ids = [ln.id for ln in lines]
    items_by_line: dict[int, list[SalesOrderLineItem]] = defaultdict(list)
    if line_ids:
        for item in db.scalars(
            select(SalesOrderLineItem).where(
                SalesOrderLineItem.tenant_id == tenant_id,
                SalesOrderLineItem.sales_order_line_id.in_(line_ids),
            )
        ).all():
            items_by_line[item.sales_order_line_id].append(item)
    shipped_by_line: dict[int, int] = defaultdict(int)
    missing_item_ids = [ln.id for ln in lines if ln.id not in items_by_line]
    if missing_item_ids:
        for line_id, qty in db.execute(
            select(Order.sales_order_line_id, func.coalesce(func.sum(Shipment.total_qty), 0))
            .join(Shipment, Shipment.order_id == Order.id)
            .where(
                Order.tenant_id == tenant_id,
                Order.sales_order_line_id.in_(missing_item_ids),
                Shipment.status == ShipmentStatus.shipped,
            )
            .group_by(Order.sales_order_line_id)
        ):
            if line_id is None:
                continue
            shipped_by_line[int(line_id)] += int(qty or 0)

    costs = _product_std_costs(db, tenant_id, [ln.own_product_id for ln in lines])
    unshipped = 0
    overdue = 0
    projected = _ZERO
    for line in lines:
        items = items_by_line.get(line.id) or []
        if items:
            remain_ship = sum(max(0, int(it.qty or 0) - int(it.shipped_qty or 0)) for it in items)
        else:
            remain_ship = max(0, int(line.total_qty or 0) - int(shipped_by_line.get(line.id, 0)))
        unshipped += remain_ship
        if remain_ship > 0 and line.delivery_date is not None and line.delivery_date < today:
            overdue += remain_ship
        unit_profit = _line_unit_profit(
            costs.get(line.own_product_id)
            or {
                "shared_material": _ZERO,
                "color_material": {},
                "labor": _ZERO,
                "commission": _ZERO,
                "quote_price": None,
            },
            unit_price=line.unit_price,
            color_id=line.color_id,
        )
        projected += unit_profit * Decimal(remain_ship)

    legacy_orders = db.scalars(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.sales_order_id.is_(None),
            Order.is_bridge.is_(False),
            Order.status.notin_([OrderStatus.draft, OrderStatus.cancelled]),
        )
    ).all()
    if legacy_orders:
        costs.update(_product_std_costs(db, tenant_id, [o.own_product_id for o in legacy_orders]))
        oid_list = [o.id for o in legacy_orders]
        shipped_map = dict(
            db.execute(
                select(Shipment.order_id, func.coalesce(func.sum(Shipment.total_qty), 0)).where(
                    Shipment.tenant_id == tenant_id,
                    Shipment.order_id.in_(oid_list),
                    Shipment.status == ShipmentStatus.shipped,
                ).group_by(Shipment.order_id)
            ).all()
        )
        for order in legacy_orders:
            shipped = int(shipped_map.get(order.id, 0) or 0)
            remain = max(0, int(order.total_qty or 0) - shipped)
            if remain <= 0:
                continue
            unshipped += remain
            if order.delivery_date is not None and order.delivery_date < today:
                overdue += remain
            unit_profit = _line_unit_profit(
                costs.get(order.own_product_id)
                or {
                    "shared_material": _ZERO,
                    "color_material": {},
                    "labor": _ZERO,
                    "commission": _ZERO,
                    "quote_price": None,
                },
                unit_price=order.unit_price,
                color_id=None,
            )
            projected += unit_profit * Decimal(remain)

    return unshipped, overdue, projected.quantize(_CENT, rounding=ROUND_HALF_UP)


def _current_snapshot(db: Session, tenant_id: int) -> dict:
    """按当前时刻统计，不随经营报告日期范围变化。"""
    today = _local_date()
    employee_count = int(
        db.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.is_active.is_(True),
            )
        )
        or 0
    )
    late_times, late_minutes = _late_early_today(db, tenant_id, today)
    unshipped_qty, overdue_qty, projected_profit = _current_open_qty_and_profit(
        db, tenant_id, today
    )
    return {
        "as_of": today.isoformat(),
        "employee_count": employee_count,
        "late_early_times": late_times,
        "late_early_minutes": late_minutes,
        "unshipped_qty": int(unshipped_qty),
        "projected_profit": _money_float(projected_profit),
        "overdue_qty": int(overdue_qty),
    }


def _scrap_rate(scrap_qty: int, shipped_qty: int) -> float | None:
    shipped = int(shipped_qty or 0)
    scrap = int(scrap_qty or 0)
    if shipped <= 0:
        return None
    denom = shipped + scrap
    return float((Decimal(scrap) / Decimal(denom)).quantize(_RATE, rounding=ROUND_HALF_UP))


def business_report(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """按日期范围统计经营指标。

    综合利润 = 订单利润 − 期间综合分摊总额 − 生产损失（公司） − 售后损失（公司）。
    开发支出已含在综合分摊中，不再单独扣减。
    报废率 = 报废双数 ÷ (出货双数 + 报废双数)。
    """
    range_start, range_end = _resolve_range(
        year=None, month=None, date_from=date_from, date_to=date_to
    )

    cost = {
        "dev_cost": {
            "department_id": None,
            "department_name": "开发部",
            "total_expense": 0.0,
            "shipped_qty": 0,
            "unit_cost": None,
        },
        "allocated_cost": {"total_expense": 0.0, "shipped_qty": 0, "unit_cost": None},
    }
    try:
        cost = cost_analysis_report(
            db, tenant_id, date_from=range_start, date_to=range_end
        )
    except Exception:
        pass

    allocated = cost.get("allocated_cost") or {}
    dev = cost.get("dev_cost") or {}
    shipped_qty = int(allocated.get("shipped_qty") or 0)
    allocated_total = _money(allocated.get("total_expense"))
    allocated_unit = allocated.get("unit_cost")
    dev_expense = _money(dev.get("total_expense"))
    dev_unit = dev.get("unit_cost")

    order_rows: list[dict] = []
    try:
        order_rows = _period_order_rows(
            db, tenant_id, range_start=range_start, range_end=range_end
        )
    except Exception:
        pass
    profit = sum((r["period_profit"] for r in order_rows), _ZERO).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    loss_orders = _loss_orders(order_rows)

    production_loss, scrap_qty = _production_loss_and_scrap(
        db, tenant_id, range_start=range_start, range_end=range_end
    )
    after_sales_loss = _after_sales_loss(
        db, tenant_id, range_start=range_start, range_end=range_end
    )
    comprehensive_profit = (
        profit - allocated_total - production_loss - after_sales_loss
    ).quantize(_CENT, rounding=ROUND_HALF_UP)

    snapshot = {
        "as_of": None,
        "employee_count": 0,
        "late_early_times": 0,
        "late_early_minutes": 0,
        "unshipped_qty": 0,
        "projected_profit": 0.0,
        "overdue_qty": 0,
    }
    try:
        snapshot = _current_snapshot(db, tenant_id)
    except Exception:
        pass

    return {
        "date_from": range_start.isoformat(),
        "date_to": range_end.isoformat(),
        "snapshot": snapshot,
        "shipped_qty": shipped_qty,
        "profit": _money_float(profit),
        "comprehensive_profit": _money_float(comprehensive_profit),
        "scrap_qty": scrap_qty,
        "scrap_rate": _scrap_rate(scrap_qty, shipped_qty),
        "production_loss": _money_float(production_loss),
        "after_sales_loss": _money_float(after_sales_loss),
        "dev_expense": _money_float(dev_expense),
        "dev_unit_cost": None if dev_unit is None else float(dev_unit),
        "allocated_total": _money_float(allocated_total),
        "allocated_unit_cost": None if allocated_unit is None else float(allocated_unit),
        "dev_cost": {
            "department_id": dev.get("department_id"),
            "department_name": dev.get("department_name") or "开发部",
            "total_expense": _money_float(dev_expense),
            "shipped_qty": shipped_qty,
            "unit_cost": None if dev_unit is None else float(dev_unit),
        },
        "allocated_cost": {
            "total_expense": _money_float(allocated_total),
            "shipped_qty": shipped_qty,
            "unit_cost": None if allocated_unit is None else float(allocated_unit),
        },
        "loss_orders": loss_orders,
    }
