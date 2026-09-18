"""综合成本分析：按部门 × 按日汇总开支（固定工资 / 提成 / 计件 / 物料进出 / 其它开支）。"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    DailyExpense,
    DailyExpenseLine,
    Department,
    Employee,
    Order,
    OrderItem,
    OwnProductCommission,
    PaymentStatus,
    SalesOrderLine,
    SalesOrderLineItem,
    Shipment,
    ShipmentStatus,
    StockDoc,
    StockDocStatus,
    StockDocType,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.salary_service import month_salary_all

CATEGORY_ORDER = ("fixed_salary", "commission", "piecework", "material", "other")
CATEGORY_LABELS = {
    "fixed_salary": "固定工资",
    "commission": "提成",
    "piecework": "计件",
    "material": "物料进出",
    "other": "其它开支",
}
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


def _money(value: Decimal | float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return _ZERO


def _local_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    return (value + LOCAL_OFFSET).date()


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


def _dept_id(employee: Employee | None) -> int | None:
    if employee and employee.department_id:
        return int(employee.department_id)
    return None


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
                "other",
                line.amount,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _collect_material(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    utc_from = datetime.combine(range_start, datetime.min.time()) - LOCAL_OFFSET
    utc_to = datetime.combine(range_end + timedelta(days=1), datetime.min.time()) - LOCAL_OFFSET
    docs = db.scalars(
        select(StockDoc)
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.status == StockDocStatus.posted,
            StockDoc.posted_at.is_not(None),
            StockDoc.posted_at >= utc_from,
            StockDoc.posted_at < utc_to,
        )
        .options(selectinload(StockDoc.lines))
    ).all()
    creator_ids = {d.created_by for d in docs if d.created_by}
    creators = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_(creator_ids or {0}),
            )
        ).all()
    }
    for doc in docs:
        day = _local_day(doc.posted_at)
        creator = creators.get(doc.created_by) if doc.created_by else None
        dept = _dept_id(creator)
        total = _ZERO
        for line in doc.lines or []:
            total += _money(Decimal(str(line.qty or 0)) * Decimal(str(line.unit_cost or 0)))
        if total == 0:
            continue
        doc_type = doc.doc_type.value if hasattr(doc.doc_type, "value") else str(doc.doc_type)
        if doc_type == StockDocType.return_mat.value or doc_type == "return_mat":
            total = -total
        _add(
            bucket,
            day,
            dept,
            "material",
            total,
            range_start=range_start,
            range_end=range_end,
            root_map=root_map,
        )


def _pay_date_for_settle_month(year_month: str, payday: int) -> date:
    """结算月工资的发薪日：次月 payday 号（与工资页口径一致）。"""
    y, m = map(int, year_month.split("-"))
    day = max(1, min(int(payday or 10), 28))
    if m == 12:
        return date(y + 1, 1, day)
    return date(y, m + 1, day)


def _settle_months_paying_in_range(
    range_start: date, range_end: date, payday: int
) -> list[tuple[str, date]]:
    """发薪日落在筛选区间内的结算月列表。"""
    # 发薪=次月，故从筛选起始月的上月起扫
    if range_start.month == 1:
        cursor = date(range_start.year - 1, 12, 1)
    else:
        cursor = date(range_start.year, range_start.month - 1, 1)
    end_cursor = date(range_end.year, range_end.month, 1)
    out: list[tuple[str, date]] = []
    while cursor <= end_cursor:
        ym = f"{cursor.year:04d}-{cursor.month:02d}"
        pay_date = _pay_date_for_settle_month(ym, payday)
        if range_start <= pay_date <= range_end:
            out.append((ym, pay_date))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return out


def _collect_piecework(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    """计件工资按发薪日记入（结算月 → 次月发薪日），不按报工日拆天。"""
    from app.services import payroll_settings as payroll_settings_service

    payday = int(payroll_settings_service.get_payroll_by_tenant_id(db, tenant_id).get("payday") or 10)
    for year_month, pay_date in _settle_months_paying_in_range(range_start, range_end, payday):
        overview = month_salary_all(db, tenant_id, year_month)
        for item in overview.get("items") or []:
            piece = _money(item.get("payable_piece_wage"))
            if piece == 0:
                piece = _money(item.get("total_piece_wage"))
            if piece == 0:
                continue
            _add(
                bucket,
                pay_date,
                item.get("department_id"),
                "piecework",
                piece,
                range_start=range_start,
                range_end=range_end,
                root_map=root_map,
            )


def _shipment_product_qty(db: Session, tenant_id: int, shipment: Shipment) -> dict[int, int]:
    """单笔出货按产品汇总双数。"""
    qty_map: dict[int, int] = {}
    lines = list(shipment.lines or [])
    if not lines:
        if shipment.order_id:
            order = db.get(Order, shipment.order_id)
            if order and order.tenant_id == tenant_id and order.own_product_id:
                qty_map[order.own_product_id] = int(shipment.total_qty or 0)
        return qty_map
    for line in lines:
        pid = None
        if line.sales_order_line_item_id:
            sitem = db.get(SalesOrderLineItem, line.sales_order_line_item_id)
            if sitem and sitem.tenant_id == tenant_id:
                sline = db.get(SalesOrderLine, sitem.sales_order_line_id)
                if sline and sline.tenant_id == tenant_id:
                    pid = sline.own_product_id
        if pid is None and line.order_item_id:
            item = db.get(OrderItem, line.order_item_id)
            if item and item.tenant_id == tenant_id:
                order = db.get(Order, item.order_id)
                pid = order.own_product_id if order else None
        if pid is None and shipment.order_id:
            order = db.get(Order, shipment.order_id)
            pid = order.own_product_id if order and order.tenant_id == tenant_id else None
        if not pid:
            continue
        qty_map[pid] = qty_map.get(pid, 0) + int(line.qty or 0)
    return qty_map


def _collect_commission(
    db: Session,
    tenant_id: int,
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    range_start: date,
    range_end: date,
    root_map: dict[int, int],
) -> None:
    shipments = db.scalars(
        select(Shipment)
        .where(
            Shipment.tenant_id == tenant_id,
            Shipment.status == ShipmentStatus.shipped,
            Shipment.ship_date.is_not(None),
            Shipment.ship_date >= range_start,
            Shipment.ship_date <= range_end,
        )
        .options(selectinload(Shipment.lines))
    ).all()
    product_ids: set[int] = set()
    per_day_product: list[tuple[date, dict[int, int]]] = []
    for sh in shipments:
        if not sh.ship_date:
            continue
        qty_map = _shipment_product_qty(db, tenant_id, sh)
        if not qty_map:
            continue
        product_ids.update(qty_map.keys())
        per_day_product.append((sh.ship_date, qty_map))
    if not product_ids:
        return
    commissions = db.scalars(
        select(OwnProductCommission).where(
            OwnProductCommission.tenant_id == tenant_id,
            OwnProductCommission.own_product_id.in_(product_ids),
            OwnProductCommission.employee_id.is_not(None),
        )
    ).all()
    if not commissions:
        return
    emp_ids = {c.employee_id for c in commissions if c.employee_id}
    employees = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(Employee.tenant_id == tenant_id, Employee.id.in_(emp_ids))
        ).all()
    }
    rates: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    for row in commissions:
        if not row.employee_id:
            continue
        rates[row.own_product_id].append(
            (row.employee_id, Decimal(str(row.amount or 0)))
        )
    for ship_day, qty_map in per_day_product:
        for pid, qty in qty_map.items():
            if qty <= 0:
                continue
            for employee_id, rate in rates.get(pid, []):
                if rate <= 0:
                    continue
                emp = employees.get(employee_id)
                amount = (rate * Decimal(qty)).quantize(_CENT, rounding=ROUND_HALF_UP)
                _add(
                    bucket,
                    ship_day,
                    _dept_id(emp),
                    "commission",
                    amount,
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
    """固定工资（含底薪/保证/加班/补贴/加减项，不含提成与计件）记在结算期末日。"""
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


def _purge_production_material(
    bucket: dict[date, dict[int, dict[str, Decimal]]],
    *,
    dept_name: dict[int, str],
) -> None:
    """生产部物料进出完全去掉：不展示、不参与任何汇总/分摊计算。"""
    for day_map in bucket.values():
        for dept_id, cats in day_map.items():
            if (dept_name.get(dept_id) or "").strip() != "生产部":
                continue
            cats.pop("material", None)


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
    _collect_material(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_piecework(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_commission(
        db, tenant_id, bucket, range_start=range_start, range_end=range_end, root_map=root_map
    )
    _collect_fixed_salary(
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
    _purge_production_material(bucket, dept_name=dept_name)

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

    headers: list[dict] = []
    visible_keys: list[tuple[int, str]] = []
    for dept_id in ordered_dept_ids:
        children = []
        name = dept_name.get(dept_id) or ""
        for cat in CATEGORY_ORDER:
            total = col_totals.get(dept_id, {}).get(cat, _ZERO)
            if total == 0:
                continue
            children.append({"key": cat, "label": CATEGORY_LABELS[cat]})
            visible_keys.append((dept_id, cat))
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


def _dev_cost_kpi(
    *,
    col_totals: dict[int, dict[str, Decimal]],
    dept_rows: list[Department],
    root_map: dict[int, int],
    shipped_qty: int,
) -> dict:
    """开发成本 = 开发部期间全部费用 ÷ 期间出货双数。"""
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
