"""综合成本分析：按部门 × 按日汇总开支（固定工资 / 报销类型 / 仓库领料 / 辅料耗材 / 模具对账 / 复版进账）。"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountStatement,
    AccountStatementStatus,
    DailyExpense,
    DailyExpenseLine,
    Department,
    PayableLine,
    PaymentStatus,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    SampleRemake,
    Shipment,
    ShipmentStatus,
    SupplierProduct,
    ToolingItem,
    ToolingReceiptLine,
    ToolingReceiptSize,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupStatus,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.expense_service import DEFAULT_CATEGORIES, _category_label
from app.services.salary_service import month_salary_all

FIXED_SALARY = "fixed_salary"
PICKUP_LABEL = "仓库领料"
AUX_LABEL = "辅料耗材"
REMAKE_LABEL = "复版收费"
SOLE_MOLD_LABEL = "底模"
HEEL_MOLD_LABEL = "鞋跟模具"
SHOE_LAST_LABEL = "楦头"
OTHER_MOLD_LABEL = "其它模具"
TOOLING_COST_LABELS = (SOLE_MOLD_LABEL, HEEL_MOLD_LABEL, SHOE_LAST_LABEL, OTHER_MOLD_LABEL)
_TOOLING_KIND_LABEL = {
    "sole_mold": SOLE_MOLD_LABEL,
    "heel_mold": HEEL_MOLD_LABEL,
    "shoe_last": SHOE_LAST_LABEL,
    "other_mold": OTHER_MOLD_LABEL,
}
CATEGORY_LABELS = {
    FIXED_SALARY: "固定工资",
    PICKUP_LABEL: "仓库领料",
    AUX_LABEL: "辅料耗材",
    REMAKE_LABEL: "复版收费",
    SOLE_MOLD_LABEL: SOLE_MOLD_LABEL,
    HEEL_MOLD_LABEL: HEEL_MOLD_LABEL,
    SHOE_LAST_LABEL: SHOE_LAST_LABEL,
    OTHER_MOLD_LABEL: OTHER_MOLD_LABEL,
}
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


def _money(value: Decimal | float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return _ZERO


def _resolve_range(
    *,
    year: int | None,
    month: int | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    if date_from or date_to:
        start = date_from or date_to
        end = date_to or date_from
        assert start is not None and end is not None
        if end < start:
            start, end = end, start
        return start, end
    from datetime import timezone as _tz

    today = (datetime.now(_tz.utc).replace(tzinfo=None) + LOCAL_OFFSET).date()
    y = year or today.year
    if month:
        last = monthrange(y, month)[1]
        return date(y, month, 1), date(y, month, last)
    return date(y, 1, 1), date(y, 12, 31)


def _months_touching(start: date, end: date) -> list[str]:
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


def _root_dept_map(db: Session, tenant_id: int) -> dict[int, int]:
    """任意部门 → 一级部门（沿 parent_id 上溯到根）。"""
    depts = list(
        db.scalars(select(Department).where(Department.tenant_id == tenant_id)).all()
    )
    by_id = {d.id: d for d in depts}
    cache: dict[int, int] = {}

    def _root_of(dept_id: int) -> int:
        if dept_id in cache:
            return cache[dept_id]
        path: list[int] = []
        cur = dept_id
        while cur in by_id and by_id[cur].parent_id is not None:
            if cur in path:
                break
            path.append(cur)
            parent = by_id[cur].parent_id
            if parent is None:
                break
            if parent in cache:
                cur = cache[parent]
                break
            if parent not in by_id:
                break
            cur = parent
        for node in path:
            cache[node] = cur
        cache[dept_id] = cur
        return cur

    for d in depts:
        _root_of(d.id)
    return cache


def _expense_category_key(category: str | None) -> str:
    """报销类型列键：与报销页同一套中文名；冒号改全角，避免和单元格 key 分隔符冲突。"""
    label = _category_label(category)
    if not label or label == "—":
        label = "其它"
    return label.replace(":", "：")


def _expense_category_order(keys: set[str]) -> list[str]:
    """预设报销类型在前，自定义类型按名称排在「其它」之前。"""
    known = [name for name in DEFAULT_CATEGORIES if name in keys]
    custom = sorted(key for key in keys if key not in DEFAULT_CATEGORIES)
    if "其它" in known:
        idx = known.index("其它")
        return known[:idx] + custom + known[idx:]
    return known + custom


def _add(
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    day: date | None,
    department_id: int | None,
    category: str,
    amount: Decimal | float | int | str | None,
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    """无部门归属的脏数据直接丢弃；子部门归并到一级部门。"""
    money = _money(amount)
    if money == 0 or day is None or not department_id:
        return
    if day < range_start or day > range_end:
        return
    raw = int(department_id)
    dept = root_map.get(raw, raw)
    bucket[day][dept][category] += money


def _collect_other(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    rows = db.scalars(
        select(DailyExpense)
        .where(
            DailyExpense.tenant_id == tenant_id,
            DailyExpense.status == PaymentStatus.posted,
            DailyExpense.id.in_(
                select(DailyExpenseLine.expense_id).where(
                    DailyExpenseLine.tenant_id == tenant_id,
                    DailyExpenseLine.occurred_on >= range_start,
                    DailyExpenseLine.occurred_on <= range_end,
                )
            ),
        )
        .options(selectinload(DailyExpense.lines))
    ).all()
    for row in rows:
        dept = row.department_id
        if not dept:
            continue
        for line in row.lines or []:
            if line.occurred_on is None:
                continue
            _add(
                bucket,
                line.occurred_on,
                dept,
                _expense_category_key(line.category),
                line.amount,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _collect_fixed_salary(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    """固定工资（含底薪/保证/加班/补贴/加减项，不含提成与计件）记在结算期末日。计件、提成不进成本分析。"""
    for year_month in _months_touching(range_start, range_end):
        overview = month_salary_all(db, tenant_id, year_month)
        items = overview.get("items") or []
        # period_end 在 summary / settle 窗口；与 ledger 一致用月末或 settle_through
        period_end_raw = (overview.get("period_end") or overview.get("settle_through")
                          or f"{year_month}-01")
        if isinstance(period_end_raw, date):
            post_day = period_end_raw
        else:
            try:
                post_day = date.fromisoformat(str(period_end_raw)[:10])
            except ValueError:
                y, m = map(int, year_month.split("-"))
                post_day = date(y, m, monthrange(y, m)[1])
        for item in items:
            fixed = (
                _money(item.get("fixed_pay"))
                + _money(item.get("base_pay"))
                + _money(item.get("guarantee_pay"))
                + _money(item.get("overtime_pay"))
                + _money(item.get("meal_allowance"))
                + _money(item.get("housing_allowance"))
                + _money(item.get("other_allowance"))
                - _money(item.get("leave_deduction"))
                + _money(item.get("adjustment_net"))
            )
            if fixed == 0:
                continue
            _add(
                bucket,
                post_day,
                item.get("department_id"),
                "fixed_salary",
                fixed,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _local_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    return (value + LOCAL_OFFSET).date()


def _department_named(db: Session, tenant_id: int, name: str) -> Department | None:
    rows = list(
        db.scalars(
            select(Department)
            .where(Department.tenant_id == tenant_id, Department.name == name)
            .order_by(Department.id)
        ).all()
    )
    roots = [row for row in rows if row.parent_id is None]
    return (roots or rows or [None])[0]


def _collect_pool_pickups(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    kind: WarehousePickupKind,
    ledger_type: SharedLedgerType,
    department_name: str,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
    amount_sign: Decimal = Decimal("1"),
    category: str = PICKUP_LABEL,
) -> None:
    """已确认的仓库直接扣池领料或退回，按库存均价记入指定部门。退料金额为负。"""
    dept = _department_named(db, tenant_id, department_name)
    if dept is None:
        return
    start_at = datetime.combine(range_start, datetime.min.time()) - LOCAL_OFFSET
    end_at = datetime.combine(range_end, datetime.min.time()) - LOCAL_OFFSET + timedelta(days=1)
    pickups = list(
        db.scalars(
            select(WarehousePickup)
            .where(
                WarehousePickup.tenant_id == tenant_id,
                WarehousePickup.kind == kind,
                WarehousePickup.status == WarehousePickupStatus.signed,
                WarehousePickup.signed_at.is_not(None),
                WarehousePickup.signed_at >= start_at,
                WarehousePickup.signed_at < end_at,
            )
            .options(selectinload(WarehousePickup.lines))
        ).all()
    )
    if not pickups:
        return
    pickup_ids = [row.id for row in pickups]
    ledgers = list(
        db.scalars(
            select(SharedMaterialLedger).where(
                SharedMaterialLedger.tenant_id == tenant_id,
                SharedMaterialLedger.ledger_type == ledger_type,
                SharedMaterialLedger.ref_type == "warehouse_pickup",
                SharedMaterialLedger.ref_id.in_(pickup_ids),
            )
        ).all()
    )
    ledger_cost: dict[tuple[int, int, int | None], Decimal | None] = {}
    for row in ledgers:
        if row.ref_id is None:
            continue
        ledger_cost[(int(row.ref_id), int(row.supplier_product_id), row.size_id)] = row.unit_cost

    missing_products: set[int] = set()
    for pickup in pickups:
        for line in pickup.lines or []:
            key = (int(pickup.id), int(line.supplier_product_id), line.size_id)
            if ledger_cost.get(key) is None:
                missing_products.add(int(line.supplier_product_id))
    stock_cost: dict[tuple[int, int | None], Decimal] = {}
    product_price: dict[int, Decimal] = {}
    if missing_products:
        stocks = db.scalars(
            select(SharedMaterialStock).where(
                SharedMaterialStock.tenant_id == tenant_id,
                SharedMaterialStock.supplier_product_id.in_(missing_products),
            )
        ).all()
        for stock in stocks:
            stock_cost[(int(stock.supplier_product_id), stock.size_id)] = Decimal(
                str(stock.avg_unit_cost or 0)
            )
        products = db.scalars(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.id.in_(missing_products),
            )
        ).all()
        for product in products:
            product_price[int(product.id)] = Decimal(str(product.unit_price or 0))

    for pickup in pickups:
        day = _local_day(pickup.signed_at)
        for line in pickup.lines or []:
            key = (int(pickup.id), int(line.supplier_product_id), line.size_id)
            unit = ledger_cost.get(key)
            if unit is None:
                unit = stock_cost.get((int(line.supplier_product_id), line.size_id))
            if unit is None:
                unit = product_price.get(int(line.supplier_product_id), _ZERO)
            amount = (
                Decimal(str(line.qty or 0)) * Decimal(str(unit or 0)) * amount_sign
            ).quantize(_CENT, rounding=ROUND_HALF_UP)
            _add(
                bucket,
                day,
                dept.id,
                category,
                amount,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _dev_department(db: Session, tenant_id: int) -> Department | None:
    return _department_named(db, tenant_id, "开发部")


def _collect_sample_remakes(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    """复版记录是客户进账，按数量 × 样品单价记入开发部，金额为负。"""
    dev = _dev_department(db, tenant_id)
    if dev is None:
        return
    remakes = list(
        db.scalars(
            select(SampleRemake)
            .where(
                SampleRemake.tenant_id == tenant_id,
                SampleRemake.remake_date >= range_start,
                SampleRemake.remake_date <= range_end,
            )
            .options(selectinload(SampleRemake.lines))
        ).all()
    )
    for remake in remakes:
        for line in remake.lines or []:
            amount = (
                Decimal(int(line.qty or 0)) * Decimal(str(line.unit_price or 0))
            ).quantize(_CENT, rounding=ROUND_HALF_UP)
            if amount == 0:
                continue
            _add(
                bucket,
                remake.remake_date,
                dev.id,
                REMAKE_LABEL,
                -amount,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _collect_tooling_statements(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    """已生成对账单的底模、鞋跟模具、楦头、其它模具记入开发部。刀模不进开发成本。"""
    dev = _dev_department(db, tenant_id)
    if dev is None:
        return
    rows = db.execute(
        select(
            AccountStatement.statement_date,
            ToolingItem.kind,
            PayableLine.amount,
        )
        .join(PayableLine, PayableLine.statement_id == AccountStatement.id)
        .join(ToolingReceiptSize, ToolingReceiptSize.id == PayableLine.source_ref_id)
        .join(ToolingReceiptLine, ToolingReceiptLine.id == ToolingReceiptSize.line_id)
        .join(ToolingItem, ToolingItem.id == ToolingReceiptLine.tooling_item_id)
        .where(
            AccountStatement.tenant_id == tenant_id,
            AccountStatement.status != AccountStatementStatus.void,
            PayableLine.tenant_id == tenant_id,
            PayableLine.source_type == "tooling_receive",
            ToolingItem.tenant_id == tenant_id,
            ToolingItem.kind.in_(tuple(_TOOLING_KIND_LABEL)),
            AccountStatement.statement_date >= range_start,
            AccountStatement.statement_date <= range_end,
        )
    ).all()
    for statement_date, kind, amount in rows:
        label = _TOOLING_KIND_LABEL.get(kind)
        if not label:
            continue
        _add(
            bucket,
            statement_date,
            dev.id,
            label,
            amount,
            range_start=range_start,
            range_end=range_end,
            root_map=root_map,
        )


def cost_analysis_report(
    db: Session,
    tenant_id: int,
    *,
    year: int | None = None,
    month: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    if not any([year, month, date_from, date_to]):
        range_start, range_end = _unbounded_date_span(db, tenant_id)
    else:
        range_start, range_end = _resolve_range(
            year=year, month=month, date_from=date_from, date_to=date_to
        )
    root_map = _root_dept_map(db, tenant_id)
    bucket: dict[date, dict[int, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: _ZERO))
    )
    _collect_other(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_fixed_salary(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_pool_pickups(
        db,
        tenant_id,
        bucket,
        kind=WarehousePickupKind.dev,
        ledger_type=SharedLedgerType.dev_issue,
        department_name="开发部",
        range_start=range_start,
        range_end=range_end,
        root_map=root_map,
    )
    _collect_pool_pickups(
        db,
        tenant_id,
        bucket,
        kind=WarehousePickupKind.aux,
        ledger_type=SharedLedgerType.aux_issue,
        department_name="生产部",
        range_start=range_start,
        range_end=range_end,
        root_map=root_map,
        category=AUX_LABEL,
    )
    _collect_pool_pickups(
        db,
        tenant_id,
        bucket,
        kind=WarehousePickupKind.dev_return,
        ledger_type=SharedLedgerType.dev_return,
        department_name="开发部",
        range_start=range_start,
        range_end=range_end,
        root_map=root_map,
        amount_sign=Decimal("-1"),
    )
    _collect_pool_pickups(
        db,
        tenant_id,
        bucket,
        kind=WarehousePickupKind.aux_return,
        ledger_type=SharedLedgerType.aux_return,
        department_name="生产部",
        range_start=range_start,
        range_end=range_end,
        root_map=root_map,
        amount_sign=Decimal("-1"),
        category=AUX_LABEL,
    )
    _collect_sample_remakes(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_tooling_statements(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )

    dept_rows = list(
        db.scalars(
            select(Department)
            .where(Department.tenant_id == tenant_id)
            .order_by(Department.sort_order, Department.id)
        ).all()
    )
    dept_name = {d.id: d.name for d in dept_rows}

    # 部门列：仅一级部门；整列无数据的二级表头不显示
    col_totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    for day_map in bucket.values():
        for dept_id, cats in day_map.items():
            for cat, amount in cats.items():
                col_totals[dept_id][cat] += amount

    # 表头只出一级部门（parent_id 为空）
    ordered_dept_ids = [
        d.id for d in dept_rows if d.parent_id is None and d.id in col_totals
    ]

    present_expense_keys = {
        cat
        for cats in col_totals.values()
        for cat in cats
        if cat
        not in {
            FIXED_SALARY,
            PICKUP_LABEL,
            AUX_LABEL,
            REMAKE_LABEL,
            *TOOLING_COST_LABELS,
        }
    }
    expense_order = _expense_category_order(present_expense_keys)

    headers: list[dict] = []
    visible_keys: list[tuple[int, str]] = []
    for dept_id in ordered_dept_ids:
        children: list[dict] = []
        name = dept_name.get(dept_id) or ""
        totals = col_totals.get(dept_id, {})
        if totals.get(FIXED_SALARY, _ZERO) != 0:
            children.append({"key": FIXED_SALARY, "label": CATEGORY_LABELS[FIXED_SALARY]})
            visible_keys.append((dept_id, FIXED_SALARY))
        if totals.get(PICKUP_LABEL, _ZERO) != 0:
            children.append({"key": PICKUP_LABEL, "label": PICKUP_LABEL})
            visible_keys.append((dept_id, PICKUP_LABEL))
        if totals.get(AUX_LABEL, _ZERO) != 0:
            children.append({"key": AUX_LABEL, "label": AUX_LABEL})
            visible_keys.append((dept_id, AUX_LABEL))
        for label in TOOLING_COST_LABELS:
            if totals.get(label, _ZERO) == 0:
                continue
            children.append({"key": label, "label": label})
            visible_keys.append((dept_id, label))
        for cat in expense_order:
            if totals.get(cat, _ZERO) == 0:
                continue
            children.append({"key": cat, "label": cat})
            visible_keys.append((dept_id, cat))
        if totals.get(REMAKE_LABEL, _ZERO) != 0:
            children.append({"key": REMAKE_LABEL, "label": REMAKE_LABEL})
            visible_keys.append((dept_id, REMAKE_LABEL))
        if not children:
            continue
        headers.append(
            {
                "department_id": dept_id,
                "department_name": name or f"部门#{dept_id}",
                "children": children,
            }
        )

    rows: list[dict] = []
    summary_values: dict[str, float] = {}
    for day in sorted(bucket.keys(), reverse=True):
        values: dict[str, float] = {}
        has_any = False
        for dept_id, cat in visible_keys:
            cell_key = f"{dept_id}:{cat}"
            amount = bucket[day].get(dept_id, {}).get(cat, _ZERO)
            if amount != 0:
                has_any = True
            values[cell_key] = float(amount)
            summary_values[cell_key] = round(
                summary_values.get(cell_key, 0.0) + float(amount), 2
            )
        if has_any:
            rows.append({"date": day.isoformat(), "values": values})

    shipped_qty = _period_shipped_qty(
        db, tenant_id, range_start=range_start, range_end=range_end
    )

    return {
        "date_from": range_start.isoformat(),
        "date_to": range_end.isoformat(),
        "year": year,
        "month": month,
        "category_labels": CATEGORY_LABELS,
        "headers": headers,
        "rows": rows,
        "summary": summary_values,
        "rent_cost": _category_share_kpi(col_totals, "房租", shipped_qty),
        "utility_cost": _category_share_kpi(col_totals, "水电", shipped_qty),
        "fixed_salary_cost": _category_share_kpi(col_totals, FIXED_SALARY, shipped_qty),
        "aux_material_cost": _category_share_kpi(col_totals, AUX_LABEL, shipped_qty),
        "dev_cost": _dev_cost_kpi(
            col_totals=col_totals,
            dept_rows=dept_rows,
            root_map=root_map,
            shipped_qty=shipped_qty,
        ),
        "allocated_cost": _allocated_cost_kpi(
            col_totals=col_totals,
            shipped_qty=shipped_qty,
        ),
    }


def _period_shipped_qty(
    db: Session, tenant_id: int, *, range_start: date, range_end: date
) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Shipment.total_qty), 0)).where(
                Shipment.tenant_id == tenant_id,
                Shipment.status == ShipmentStatus.shipped,
                Shipment.ship_date.is_not(None),
                Shipment.ship_date >= range_start,
                Shipment.ship_date <= range_end,
            )
        )
        or 0
    )


def _unit_cost(total_expense: Decimal, shipped_qty: int) -> float | None:
    if shipped_qty <= 0:
        return None
    return float(
        (total_expense / Decimal(shipped_qty)).quantize(_CENT, rounding=ROUND_HALF_UP)
    )


def _category_share_kpi(
    col_totals: dict[int, dict[str, Decimal]],
    category: str,
    shipped_qty: int,
) -> dict:
    """某一类费用总额 ÷ 期间出货双数。"""
    total = _ZERO
    for cats in col_totals.values():
        total += cats.get(category, _ZERO)
    qty = int(shipped_qty or 0)
    return {
        "total_expense": float(total),
        "shipped_qty": qty,
        "unit_cost": _unit_cost(total, qty),
    }


def _dev_cost_kpi(
    *,
    col_totals: dict[int, dict[str, Decimal]],
    dept_rows: list[Department],
    root_map: dict[int, int],
    shipped_qty: int,
) -> dict:
    """开发成本 = 开发部期间全部费用（含对账后的底模、楦头、其它模具；复版进账为负）÷ 期间出货双数。"""
    # 按名称找开发部（含子部门时归到一级）
    dev_raw_ids = [d.id for d in dept_rows if (d.name or "").strip() == "开发部"]
    dev_root_ids = {root_map.get(i, i) for i in dev_raw_ids}
    total_expense = _ZERO
    department_id = None
    department_name = "开发部"
    for dept_id in sorted(dev_root_ids):
        department_id = dept_id
        for amount in col_totals.get(dept_id, {}).values():
            total_expense += amount
        for d in dept_rows:
            if d.id == dept_id:
                department_name = d.name
                break

    qty = int(shipped_qty or 0)
    return {
        "department_id": department_id,
        "department_name": department_name,
        "total_expense": float(total_expense),
        "shipped_qty": qty,
        "unit_cost": _unit_cost(total_expense, qty),
    }


def _allocated_cost_kpi(
    *,
    col_totals: dict[int, dict[str, Decimal]],
    shipped_qty: int,
) -> dict:
    """综合分摊 = 期间全部费用（不含计件、提成）÷ 期间出货双数。"""
    exclude = {"piecework", "commission"}
    total_expense = _ZERO
    for cats in col_totals.values():
        for cat, amount in cats.items():
            if cat in exclude:
                continue
            total_expense += amount
    qty = int(shipped_qty or 0)
    return {
        "total_expense": float(total_expense),
        "shipped_qty": qty,
        "unit_cost": _unit_cost(total_expense, qty),
    }


def _unbounded_date_span(db: Session, tenant_id: int) -> tuple[date, date]:
    """全历史口径的实际日期跨度：取业务最早日～今天，避免扫百年空月。"""
    from datetime import timezone as _tz

    today = (datetime.now(_tz.utc).replace(tzinfo=None) + LOCAL_OFFSET).date()
    candidates: list[date] = []
    ship_min = db.scalar(
        select(func.min(Shipment.ship_date)).where(
            Shipment.tenant_id == tenant_id,
            Shipment.status == ShipmentStatus.shipped,
            Shipment.ship_date.is_not(None),
        )
    )
    if ship_min:
        candidates.append(ship_min)
    expense_min = db.scalar(
        select(func.min(DailyExpense.expense_date)).where(
            DailyExpense.tenant_id == tenant_id,
            DailyExpense.expense_date.is_not(None),
        )
    )
    if expense_min:
        candidates.append(expense_min)
    pickup_min = db.scalar(
        select(func.min(WarehousePickup.signed_at)).where(
            WarehousePickup.tenant_id == tenant_id,
            WarehousePickup.kind.in_(
                (
                    WarehousePickupKind.dev,
                    WarehousePickupKind.aux,
                    WarehousePickupKind.dev_return,
                    WarehousePickupKind.aux_return,
                )
            ),
            WarehousePickup.status == WarehousePickupStatus.signed,
            WarehousePickup.signed_at.is_not(None),
        )
    )
    if pickup_min:
        candidates.append((pickup_min + LOCAL_OFFSET).date())
    remake_min = db.scalar(
        select(func.min(SampleRemake.remake_date)).where(SampleRemake.tenant_id == tenant_id)
    )
    if remake_min:
        candidates.append(remake_min)
    # 发薪落在次月，往前多留一个月以免漏掉边界结算月
    start = min(candidates) if candidates else date(today.year, 1, 1)
    start = date(start.year, start.month, 1)
    if start.month == 1:
        start = date(start.year - 1, 12, 1)
    else:
        start = date(start.year, start.month - 1, 1)
    return start, today


def allocated_cost_unbounded(db: Session, tenant_id: int) -> dict:
    """综合分摊（不含日期段）：全历史费用 ÷ 全历史出货双数。"""
    date_from, date_to = _unbounded_date_span(db, tenant_id)
    return cost_analysis_report(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
    )["allocated_cost"]
