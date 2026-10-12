"""裁断用料：按工厂型号汇总裁断段已签收领料和有效合格报工。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductMaterial,
    PricingUnit,
    ProcessSegment,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
    WorkLog,
    WorkLogGroupShare,
    WorkLogStatus,
)
from app.services.attendance_service import LOCAL_OFFSET

_QTY = Decimal("0.0001")
_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _qty_text(value: Decimal) -> str:
    quantized = _dec(value).quantize(_QTY, rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _window(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """与经营报告相同：按东八区自然日切时间。两端都空则不限日期。"""
    start_at = datetime.combine(start, time.min) - LOCAL_OFFSET if start else None
    end_at = datetime.combine(end + timedelta(days=1), time.min) - LOCAL_OFFSET if end else None
    return start_at, end_at


def _resolve_range(date_from: date | None, date_to: date | None) -> tuple[date | None, date | None]:
    if not date_from and not date_to:
        return None, None
    start = date_from or date_to
    end = date_to or date_from
    assert start is not None and end is not None
    if end < start:
        start, end = end, start
    return start, end


def _like_contains(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def _budget_text(unit: Decimal | None, on_bom: bool) -> str | None:
    """预算用量就是 BOM 单双用量。多条用量不一致、或不在 BOM 上时为空。"""
    if not on_bom or unit is None:
        return None
    return _qty_text(unit)


def _average_usage(emp_ids: list[int], by_emp: dict[int, Decimal], people: dict[int, Decimal]) -> str | None:
    """平均用量 = 有报工的人，其每双用量的平均数。没有报工的人不进平均。"""
    rates = []
    for emp_id in emp_ids:
        pairs = people.get(emp_id, _ZERO)
        if pairs <= 0:
            continue
        rates.append(by_emp.get(emp_id, _ZERO) / pairs)
    if not rates:
        return None
    return _qty_text(sum(rates, _ZERO) / Decimal(len(rates)))


def _same_unit(qtys: list[Decimal]) -> Decimal | None:
    if not qtys:
        return None
    norms = [_dec(qty).quantize(_QTY, rounding=ROUND_HALF_UP) for qty in qtys]
    if any(norm != norms[0] for norm in norms):
        return None
    return norms[0]


def cut_material_usage(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    factory_model: str | None = None,
) -> dict:
    """一行是工厂型号 × 物料。员工列只含这段日期里有裁断领料或裁断报工的人。"""
    start, end = _resolve_range(date_from, date_to)
    payload = {
        "date_from": start.isoformat() if start else None,
        "date_to": end.isoformat() if end else None,
        "factory_model": (factory_model or "").strip() or None,
        "models": [],
    }
    cut_id = db.scalar(
        select(ProcessSegment.id).where(
            ProcessSegment.tenant_id == tenant_id,
            ProcessSegment.code == "cut",
        )
    )
    if cut_id is None:
        return payload

    keyword = (factory_model or "").strip()
    allowed_ids: set[int] | None = None
    if keyword:
        allowed_ids = set(
            db.scalars(
                select(OwnProduct.id).where(
                    OwnProduct.tenant_id == tenant_id,
                    func.lower(OwnProduct.product_code).like(_like_contains(keyword), escape="\\"),
                )
            ).all()
        )
        if not allowed_ids:
            return payload

    utc_from, utc_to = _window(start, end)
    pairs_by_product, picked_by_product = _activity(
        db,
        tenant_id,
        cut_id=cut_id,
        utc_from=utc_from,
        utc_to=utc_to,
        allowed_ids=allowed_ids,
    )
    product_ids = set(pairs_by_product) | set(picked_by_product)
    if not product_ids:
        return payload

    products = {
        row.id: row
        for row in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_(product_ids),
            )
        ).all()
    }
    product_ids = {pid for pid in product_ids if pid in products}
    if not product_ids:
        return payload

    bom_units = _bom_units(db, tenant_id, cut_id=cut_id, product_ids=product_ids)
    supplier_ids = {spid for pid, spid in bom_units} | {
        spid for lines in picked_by_product.values() for spid in lines
    }
    materials = _material_labels(db, tenant_id, supplier_ids)
    employee_ids = {emp_id for people in pairs_by_product.values() for emp_id in people}
    employee_ids |= {
        emp_id
        for lines in picked_by_product.values()
        for by_emp in lines.values()
        for emp_id in by_emp
    }
    employees = {
        row.id: row
        for row in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_(employee_ids or {0}),
            )
        ).all()
    }

    models = []
    for product in sorted(products.values(), key=lambda row: (row.product_code or "").casefold()):
        if product.id not in product_ids:
            continue
        people = pairs_by_product.get(product.id, {})
        picked = picked_by_product.get(product.id, {})
        total_pairs = sum(people.values(), _ZERO)
        emp_ids = set(people) | {emp_id for by_emp in picked.values() for emp_id in by_emp}
        emp_rows = sorted(emp_ids, key=lambda emp_id: (_employee_name(employees, emp_id).casefold(), emp_id))
        material_ids = {spid for (pid, spid) in bom_units if pid == product.id} | set(picked)
        material_rows = _material_rows(
            product_id=product.id,
            material_ids=material_ids,
            bom_units=bom_units,
            picked=picked,
            people=people,
            labels=materials,
            emp_ids=emp_rows,
        )
        if not material_rows:
            material_rows = [_blank_material(emp_rows, people)]
        models.append(
            {
                "own_product_id": product.id,
                "factory_model": product.product_code,
                "image_url": product.image_url,
                "total_pairs": _qty_text(total_pairs),
                "employees": [
                    {
                        "id": emp_id,
                        "name": _employee_name(employees, emp_id),
                        "pairs": _qty_text(people.get(emp_id, _ZERO)),
                    }
                    for emp_id in emp_rows
                ],
                "materials": material_rows,
            }
        )
    payload["models"] = models
    return payload


def _employee_name(employees: dict[int, Employee], emp_id: int) -> str:
    row = employees.get(emp_id)
    if row and row.name:
        return row.name
    return f"员工{emp_id}"


def _activity(
    db: Session,
    tenant_id: int,
    *,
    cut_id: int,
    utc_from: datetime | None,
    utc_to: datetime | None,
    allowed_ids: set[int] | None,
) -> tuple[dict[int, dict[int, Decimal]], dict[int, dict[int, dict[int, Decimal]]]]:
    pairs_by_product: dict[int, dict[int, Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    log_filters = [
        WorkLog.tenant_id == tenant_id,
        WorkLog.status == WorkLogStatus.valid,
        WorkLog.segment_id == cut_id,
    ]
    if utc_from is not None:
        log_filters.append(WorkLog.created_at >= utc_from)
    if utc_to is not None:
        log_filters.append(WorkLog.created_at < utc_to)
    logs = db.scalars(select(WorkLog).where(*log_filters)).all()
    if allowed_ids is not None:
        logs = [log for log in logs if log.own_product_id in allowed_ids]
    log_ids = [log.id for log in logs]
    shares_by_log: dict[int, list[WorkLogGroupShare]] = defaultdict(list)
    if log_ids:
        for share in db.scalars(
            select(WorkLogGroupShare).where(WorkLogGroupShare.work_log_id.in_(log_ids))
        ).all():
            shares_by_log[share.work_log_id].append(share)
    for log in logs:
        shares = shares_by_log.get(log.id) or []
        if shares:
            for share in shares:
                qty = _dec(share.pairs)
                if qty > 0:
                    pairs_by_product[log.own_product_id][share.worker_id] += qty
            continue
        qty = _dec(log.qualified_qty)
        if qty > 0:
            pairs_by_product[log.own_product_id][log.worker_id] += qty

    picked_by_product: dict[int, dict[int, dict[int, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: _ZERO))
    )
    pickup_filters = [
        WarehousePickup.tenant_id == tenant_id,
        WarehousePickup.kind.in_(
            (WarehousePickupKind.production, WarehousePickupKind.production_return)
        ),
        WarehousePickup.status == WarehousePickupStatus.signed,
        WarehousePickup.picker_employee_id.is_not(None),
    ]
    if utc_from is not None:
        pickup_filters.append(WarehousePickup.signed_at >= utc_from)
    if utc_to is not None:
        pickup_filters.append(WarehousePickup.signed_at < utc_to)
    pickups = db.scalars(select(WarehousePickup).where(*pickup_filters)).all()
    if not pickups:
        return pairs_by_product, picked_by_product

    pickup_by_id = {row.id: row for row in pickups}
    lines = db.scalars(
        select(WarehousePickupLine).where(WarehousePickupLine.pickup_id.in_(pickup_by_id))
    ).all()
    req_ids = {line.requirement_id for line in lines if line.requirement_id}
    requirements = {}
    if req_ids:
        requirements = {
            row.id: row
            for row in db.scalars(
                select(OrderMaterialRequirement).where(
                    OrderMaterialRequirement.tenant_id == tenant_id,
                    OrderMaterialRequirement.id.in_(req_ids),
                    OrderMaterialRequirement.consume_segment_id == cut_id,
                )
            ).all()
        }
    header_ids = {row.header_id for row in pickups if row.header_id}
    order_ids = {row.order_id for row in pickups if row.order_id}
    headers = {}
    if header_ids:
        headers = {
            row.id: row
            for row in db.scalars(
                select(ExecutionHeader).where(
                    ExecutionHeader.tenant_id == tenant_id,
                    ExecutionHeader.id.in_(header_ids),
                )
            ).all()
        }
    orders = {}
    if order_ids:
        orders = {
            row.id: row
            for row in db.scalars(
                select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids))
            ).all()
        }

    for line in lines:
        req = requirements.get(line.requirement_id or 0)
        if req is None:
            continue
        qty = _dec(line.qty)
        if qty <= 0:
            continue
        pickup = pickup_by_id[line.pickup_id]
        product_id = _product_id(pickup, headers, orders)
        if product_id is None:
            continue
        if allowed_ids is not None and product_id not in allowed_ids:
            continue
        picker_id = pickup.picker_employee_id
        if picker_id is None:
            continue
        kind = pickup.kind.value if hasattr(pickup.kind, "value") else str(pickup.kind)
        signed_qty = -qty if kind == "production_return" else qty
        picked_by_product[product_id][line.supplier_product_id][picker_id] += signed_qty
    return pairs_by_product, picked_by_product


def _product_id(pickup: WarehousePickup, headers: dict[int, ExecutionHeader], orders: dict[int, Order]) -> int | None:
    if pickup.header_id and pickup.header_id in headers:
        return headers[pickup.header_id].own_product_id
    if pickup.order_id and pickup.order_id in orders:
        return orders[pickup.order_id].own_product_id
    return None


def _bom_units(
    db: Session,
    tenant_id: int,
    *,
    cut_id: int,
    product_ids: set[int],
) -> dict[tuple[int, int], Decimal | None]:
    rows = db.scalars(
        select(OwnProductMaterial).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id.in_(product_ids),
            OwnProductMaterial.consume_segment_id == cut_id,
        )
    ).all()
    grouped: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    for row in rows:
        grouped[(row.own_product_id, row.supplier_product_id)].append(_dec(row.qty))
    return {key: _same_unit(qtys) for key, qtys in grouped.items()}


def _material_labels(db: Session, tenant_id: int, supplier_ids: set[int]) -> dict[int, dict]:
    if not supplier_ids:
        return {}
    products = db.scalars(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.id.in_(supplier_ids),
        )
    ).all()
    color_ids = {row.color_id for row in products if row.color_id}
    unit_ids = {row.pricing_unit_id for row in products if row.pricing_unit_id}
    colors = {}
    if color_ids:
        colors = {
            row.id: row.name
            for row in db.scalars(select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids))).all()
        }
    units = {}
    if unit_ids:
        units = {
            row.id: row.name
            for row in db.scalars(
                select(PricingUnit).where(PricingUnit.tenant_id == tenant_id, PricingUnit.id.in_(unit_ids))
            ).all()
        }
    return {
        row.id: {
            "material_code": row.product_code,
            "material_name": row.name,
            "image_url": row.image_url or None,
            "color_name": colors.get(row.color_id) if row.color_id else None,
            "unit_name": units.get(row.pricing_unit_id) if row.pricing_unit_id else None,
        }
        for row in products
    }


def _material_rows(
    *,
    product_id: int,
    material_ids: set[int],
    bom_units: dict[tuple[int, int], Decimal | None],
    picked: dict[int, dict[int, Decimal]],
    people: dict[int, Decimal],
    labels: dict[int, dict],
    emp_ids: list[int],
) -> list[dict]:
    rows = []
    for spid in material_ids:
        label = labels.get(spid, {})
        by_emp = picked.get(spid, {})
        on_bom = (product_id, spid) in bom_units
        unit = bom_units.get((product_id, spid)) if on_bom else None
        rows.append(
            {
                "supplier_product_id": spid,
                "material_code": label.get("material_code"),
                "material_name": label.get("material_name"),
                "image_url": label.get("image_url"),
                "color_name": label.get("color_name"),
                "unit_name": label.get("unit_name"),
                "on_bom": on_bom,
                "budget_qty": _budget_text(unit, on_bom),
                "average_usage": _average_usage(emp_ids, by_emp, people),
                "pickups": _pickup_cells(emp_ids, by_emp, people),
            }
        )
    rows.sort(key=lambda row: ((row["material_code"] or "\uffff").casefold(), (row["material_name"] or "").casefold()))
    return rows


def _blank_material(emp_ids: list[int], people: dict[int, Decimal]) -> dict:
    return {
        "supplier_product_id": None,
        "material_code": None,
        "material_name": None,
        "image_url": None,
        "color_name": None,
        "unit_name": None,
        "on_bom": False,
        "budget_qty": None,
        "average_usage": _average_usage(emp_ids, {}, people),
        "pickups": _pickup_cells(emp_ids, {}, people),
    }


def _pickup_cells(
    emp_ids: list[int],
    by_emp: dict[int, Decimal],
    people: dict[int, Decimal],
) -> dict[str, dict]:
    cells = {}
    for emp_id in emp_ids:
        qty = by_emp.get(emp_id, _ZERO)
        pairs = people.get(emp_id, _ZERO)
        cells[str(emp_id)] = {
            "qty": _qty_text(qty),
            "usage_per_pair": None if pairs == 0 else _qty_text(qty / pairs),
        }
    return cells


def factory_model_options(db: Session, tenant_id: int) -> list[dict]:
    rows = db.execute(
        select(OwnProduct.product_code, OwnProduct.image_url).where(
            OwnProduct.tenant_id == tenant_id,
            OwnProduct.is_active.is_(True),
        )
    ).all()
    options = []
    for code, image_url in rows:
        name = (code or "").strip()
        if not name:
            continue
        options.append({"factory_model": name, "image_url": image_url or None})
    options.sort(key=lambda row: row["factory_model"].casefold())
    return options
