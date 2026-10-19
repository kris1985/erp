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
    WorkshopMaterialCount,
    WorkshopMaterialCountLog,
    WorkLog,
    WorkLogGroupShare,
    WorkLogStatus,
)
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
    """按报工、签收记录上的本地时间切自然日。两端都空则不限日期。"""
    start_at = datetime.combine(start, time.min) if start else None
    end_at = datetime.combine(end + timedelta(days=1), time.min) if end else None
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
    """实际平均用量 = 总消耗物料 / 总报工双数。"""
    consumed = _ZERO
    pairs = _ZERO
    for emp_id in emp_ids:
        person_pairs = people.get(emp_id, _ZERO)
        if person_pairs <= 0:
            continue
        pairs += person_pairs
        consumed += by_emp.get(emp_id, _ZERO)
    if pairs <= 0:
        return None
    return _qty_text(consumed / pairs)


def _same_unit(qtys: list[Decimal]) -> Decimal | None:
    if not qtys:
        return None
    norms = [_dec(qty).quantize(_QTY, rounding=ROUND_HALF_UP) for qty in qtys]
    if any(norm != norms[0] for norm in norms):
        return None
    return norms[0]


def cutting_segment_id(db: Session, tenant_id: int) -> int | None:
    """裁断段。优先编码 cut；没有时用名称里带裁断、截断、裁剪或下料的启用工序段。"""
    rows = list(
        db.scalars(
            select(ProcessSegment)
            .where(
                ProcessSegment.tenant_id == tenant_id,
                ProcessSegment.is_active.is_(True),
            )
            .order_by(ProcessSegment.sort_order, ProcessSegment.id)
        ).all()
    )
    coded = next((row for row in rows if (row.code or "").strip() == "cut"), None)
    if coded is not None:
        return int(coded.id)
    named = next(
        (row for row in rows if any(word in (row.name or "") for word in ("裁断", "截断", "裁剪", "下料"))),
        None,
    )
    return int(named.id) if named is not None else None


def cut_material_usage(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    factory_model: str | None = None,
) -> dict:
    """一行是工厂型号 × 成品颜色 × 物料。颜色用来区分生产单。"""
    start, end = _resolve_range(date_from, date_to)
    payload = {
        "date_from": start.isoformat() if start else None,
        "date_to": end.isoformat() if end else None,
        "factory_model": (factory_model or "").strip() or None,
        "models": [],
    }
    cut_id = cutting_segment_id(db, tenant_id)
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
    pairs_by_product, issued_by_product, returned_by_product, colors_by_product, headers_by_product = _activity(
        db,
        tenant_id,
        cut_id=cut_id,
        utc_from=utc_from,
        utc_to=utc_to,
        allowed_ids=allowed_ids,
    )
    product_ids = {pid for pid, _color in pairs_by_product}
    product_ids |= {pid for pid, _color in issued_by_product}
    product_ids |= {pid for pid, _color in returned_by_product}
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

    bom_units = _bom_units(
        db,
        tenant_id,
        cut_id=cut_id,
        product_ids=product_ids,
        colors_by_product=colors_by_product,
    )
    supplier_ids = {spid for pid, spid in bom_units}
    supplier_ids |= {spid for lines in issued_by_product.values() for spid in lines}
    supplier_ids |= {spid for lines in returned_by_product.values() for spid in lines}
    materials = _material_labels(db, tenant_id, supplier_ids)
    employee_ids = {emp_id for people in pairs_by_product.values() for emp_id in people}
    for moved in (issued_by_product, returned_by_product):
        employee_ids |= {
            emp_id
            for lines in moved.values()
            for by_emp in lines.values()
            for emp_id in by_emp
        }
    report_usage = _report_usage(
        db,
        tenant_id,
        cut_id=cut_id,
        product_ids=product_ids,
        window_start=utc_from,
        window_end=utc_to,
    )
    employees = {
        row.id: row
        for row in db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id.in_(employee_ids or {0}),
            )
        ).all()
    }

    group_keys = set(pairs_by_product) | set(issued_by_product) | set(returned_by_product) | set(report_usage)
    color_names = _color_names(db, tenant_id, {color_id for _pid, color_id in group_keys if color_id})
    bom_rows = list(
        db.scalars(
            select(OwnProductMaterial).where(
                OwnProductMaterial.tenant_id == tenant_id,
                OwnProductMaterial.own_product_id.in_(product_ids),
                OwnProductMaterial.consume_segment_id == cut_id,
            )
        ).all()
    ) if cut_id is not None and product_ids else []
    models = []
    for product_id, color_id in sorted(
        group_keys,
        key=lambda item: (
            (products[item[0]].product_code or "").casefold() if item[0] in products else "",
            color_names.get(item[1]) or "",
            item[1] or 0,
        ),
    ):
        product = products.get(product_id)
        if product is None:
            continue
        group = (product_id, color_id)
        people = pairs_by_product.get(group, {})
        issued = issued_by_product.get(group, {})
        returned = returned_by_product.get(group, {})
        total_pairs = sum(people.values(), _ZERO)
        emp_ids = set(people)
        emp_ids |= {emp_id for by_emp in issued.values() for emp_id in by_emp}
        emp_ids |= {emp_id for by_emp in returned.values() for emp_id in by_emp}
        emp_rows = sorted(emp_ids, key=lambda emp_id: (_employee_name(employees, emp_id).casefold(), emp_id))
        scoped_bom = _bom_units_for_color(bom_rows, product_id, color_id)
        material_rows = _material_rows(
            product_id=product.id,
            material_ids={spid for _pid, spid in scoped_bom} | set(issued) | set(returned),
            bom_units=scoped_bom,
            usage=report_usage.get(group, {}),
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
                "order_color_name": color_names.get(color_id) if color_id else None,
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
    payload["models"] = _sort_models_by_latest(models)
    return payload


def _latest_detail(materials: list[dict]) -> str:
    latest = ""
    for material in materials:
        for pickup in (material.get("pickups") or {}).values():
            for record in pickup.get("records") or []:
                mark = str(record.get("sort_at") or "")
                if mark > latest:
                    latest = mark
    return latest


def _sort_models_by_latest(models: list[dict]) -> list[dict]:
    """同一工厂型号和图片留在一起，整组按最近一次领料、退料或报工倒序。"""
    for model in models:
        model["_latest"] = _latest_detail(model.get("materials") or [])
    latest_by_product: dict[tuple[str, str], str] = {}
    for model in models:
        key = ((model.get("factory_model") or "").casefold(), model.get("image_url") or "")
        if model["_latest"] > latest_by_product.get(key, ""):
            latest_by_product[key] = model["_latest"]
    models.sort(key=lambda model: ((model.get("factory_model") or "").casefold(), model.get("order_color_name") or ""))
    models.sort(key=lambda model: model["_latest"], reverse=True)
    models.sort(
        key=lambda model: latest_by_product.get(
            ((model.get("factory_model") or "").casefold(), model.get("image_url") or ""),
            "",
        ),
        reverse=True,
    )
    for model in models:
        model.pop("_latest", None)
    return models


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
) -> tuple[
    dict[tuple[int, int | None], dict[int, Decimal]],
    dict[tuple[int, int | None], dict[int, dict[int, Decimal]]],
    dict[tuple[int, int | None], dict[int, dict[int, Decimal]]],
    dict[int, set[int]],
    dict[int, set[int]],
]:
    pairs_by_product: dict[tuple[int, int | None], dict[int, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: _ZERO)
    )
    colors_by_product: dict[int, set[int]] = defaultdict(set)
    headers_by_product: dict[int, set[int]] = defaultdict(set)
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
    log_header_ids = {log.header_id for log in logs if log.header_id}
    log_headers = {}
    if log_header_ids:
        log_headers = {
            row.id: row
            for row in db.scalars(
                select(ExecutionHeader).where(
                    ExecutionHeader.tenant_id == tenant_id,
                    ExecutionHeader.id.in_(log_header_ids),
                )
            ).all()
        }
    for log in logs:
        if not log.own_product_id:
            continue
        group = (int(log.own_product_id), _finished_color(log, log_headers))
        shares = shares_by_log.get(log.id) or []
        if shares:
            for share in shares:
                qty = _dec(share.pairs)
                if qty > 0:
                    pairs_by_product[group][share.worker_id] += qty
            continue
        qty = _dec(log.qualified_qty)
        if qty > 0:
            pairs_by_product[group][log.worker_id] += qty
    for log in logs:
        if log.own_product_id and log.header_id:
            headers_by_product[int(log.own_product_id)].add(int(log.header_id))
    _remember_log_colors(db, tenant_id, logs, colors_by_product)

    issued_by_product: dict[tuple[int, int | None], dict[int, dict[int, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: _ZERO))
    )
    returned_by_product: dict[tuple[int, int | None], dict[int, dict[int, Decimal]]] = defaultdict(
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
        return pairs_by_product, issued_by_product, returned_by_product, colors_by_product, headers_by_product

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
        target = returned_by_product if kind == "production_return" else issued_by_product
        header = headers.get(pickup.header_id or 0)
        color_id = int(header.color_id) if header is not None and header.color_id else None
        target[(product_id, color_id)][line.supplier_product_id][picker_id] += qty
        if pickup.header_id:
            headers_by_product[int(product_id)].add(int(pickup.header_id))
        if color_id:
            colors_by_product[int(product_id)].add(color_id)
    return pairs_by_product, issued_by_product, returned_by_product, colors_by_product, headers_by_product


def _remember_log_colors(
    db: Session,
    tenant_id: int,
    logs: list[WorkLog],
    colors_by_product: dict[int, set[int]],
) -> None:
    """报工带了成品色就用报工的；没有则用生产单的颜色。"""
    header_ids = {log.header_id for log in logs if log.header_id and not log.color_id}
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
    for log in logs:
        if not log.own_product_id:
            continue
        color_id = log.color_id
        if color_id is None and log.header_id:
            header = headers.get(log.header_id)
            color_id = header.color_id if header is not None else None
        if color_id:
            colors_by_product[int(log.own_product_id)].add(int(color_id))


def _finished_color(log: WorkLog, headers: dict[int, ExecutionHeader]) -> int | None:
    """生产单上的成品颜色。报工自己带了颜色、生产单没有时，用报工的。"""
    header = headers.get(log.header_id or 0)
    if header is not None and header.color_id:
        return int(header.color_id)
    if log.color_id:
        return int(log.color_id)
    return None


def _color_names(db: Session, tenant_id: int, color_ids: set[int]) -> dict[int, str]:
    if not color_ids:
        return {}
    return {
        row.id: row.name
        for row in db.scalars(
            select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids))
        ).all()
        if row.name
    }


def _bom_units_for_color(
    rows: list[OwnProductMaterial],
    product_id: int,
    color_id: int | None,
) -> dict[tuple[int, int], Decimal | None]:
    """这一成品色的预算：整款共用，加上这个颜色自己的行。还不知道颜色时保留全部。"""
    grouped: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    for row in rows:
        if int(row.own_product_id) != int(product_id):
            continue
        if color_id is not None and row.color_id is not None and int(row.color_id) != int(color_id):
            continue
        grouped[(int(product_id), int(row.supplier_product_id))].append(_dec(row.qty))
    return {key: _same_unit(qtys) for key, qtys in grouped.items()}


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
    colors_by_product: dict[int, set[int]] | None = None,
) -> dict[tuple[int, int], Decimal | None]:
    """配色 BOM：知道这段时间做了哪些成品色时，只留整款共用和这些颜色的行。"""
    rows = db.scalars(
        select(OwnProductMaterial).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id.in_(product_ids),
            OwnProductMaterial.consume_segment_id == cut_id,
        )
    ).all()
    colors_by_product = colors_by_product or {}
    grouped: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    for row in rows:
        allowed = colors_by_product.get(row.own_product_id)
        if allowed and row.color_id is not None and int(row.color_id) not in allowed:
            continue
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
    usage: dict[int, dict[int, list[dict]]],
    people: dict[int, Decimal],
    labels: dict[int, dict],
    emp_ids: list[int],
) -> list[dict]:
    rows = []
    for spid in material_ids:
        label = labels.get(spid, {})
        by_emp = usage.get(spid, {})
        consumed_by_emp = {
            emp_id: sum((_dec(row["_consumed"]) for row in by_emp.get(emp_id, [])), _ZERO)
            for emp_id in emp_ids
        }
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
                "average_usage": _average_usage(emp_ids, consumed_by_emp, people),
                "pickups": _pickup_cells(emp_ids, people, by_emp),
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
        "pickups": _pickup_cells(emp_ids, people, {}),
    }


def _pickup_cells(
    emp_ids: list[int],
    people: dict[int, Decimal],
    by_emp: dict[int, list[dict]],
) -> dict[str, dict]:
    cells = {}
    for emp_id in emp_ids:
        records = by_emp.get(emp_id) or []
        pairs = people.get(emp_id, _ZERO)
        consumed = sum((_dec(row["_consumed"]) for row in records if row.get("_kind") == "report"), _ZERO)
        cells[str(emp_id)] = {
            "issued_qty": _qty_text(sum((_dec(row["_issued"]) for row in records if row.get("_kind") == "issue"), _ZERO)),
            "return_qty": _qty_text(sum((_dec(row["_returned"]) for row in records if row.get("_kind") == "return"), _ZERO)),
            "consumed_qty": _qty_text(consumed),
            "usage_per_pair": None if pairs == 0 else _qty_text(consumed / pairs),
            "records": [_public_record(row) for row in records],
        }
    return cells


def _public_record(row: dict) -> dict:
    kind = row.get("_kind") or "report"
    return {
        "kind": kind,
        "event_key": row.get("event_key") or "",
        "work_log_id": row.get("work_log_id") or 0,
        "reported_at": row["reported_at"],
        "sort_at": row.get("sort_at") or row["reported_at"],
        "header_no": row["header_no"],
        "issued_qty": _qty_text(row["_issued"]) if kind == "issue" else None,
        "opening_qty": _qty_text(row["_opening"]) if kind == "report" else None,
        "return_qty": _qty_text(row["_returned"]) if kind == "return" else None,
        "remain_qty": _qty_text(row["_remain"]),
        "consumed_qty": _qty_text(row["_consumed"]) if kind == "report" else None,
        "pairs": _qty_text(row["_pairs"]) if kind == "report" else None,
    }


def _in_window(moment: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if moment is None:
        return False
    if start is not None and moment < start:
        return False
    if end is not None and moment >= end:
        return False
    return True


def _portion(amount: Decimal, pairs: Decimal, total: Decimal) -> Decimal:
    if total <= 0 or pairs <= 0:
        return _ZERO
    return amount * pairs / total


def _report_usage(
    db: Session,
    tenant_id: int,
    *,
    cut_id: int,
    product_ids: set[int],
    window_start: datetime | None,
    window_end: datetime | None,
) -> dict[tuple[int, int | None], dict[int, dict[int, list[dict]]]]:
    """领料、退料、报工各自一条。消耗仍记在报工上。"""
    if not product_ids:
        return {}
    logs = list(
        db.scalars(
            select(WorkLog)
            .where(
                WorkLog.tenant_id == tenant_id,
                WorkLog.status == WorkLogStatus.valid,
                WorkLog.segment_id == cut_id,
                WorkLog.own_product_id.in_(product_ids),
                WorkLog.header_id.is_not(None),
            )
            .order_by(WorkLog.created_at, WorkLog.id)
        ).all()
    )
    shares_by_log: dict[int, list[WorkLogGroupShare]] = defaultdict(list)
    if logs:
        for share in db.scalars(
            select(WorkLogGroupShare).where(WorkLogGroupShare.work_log_id.in_([log.id for log in logs]))
        ).all():
            if _dec(share.pairs) > 0:
                shares_by_log[share.work_log_id].append(share)
    headers = {
        row.id: row
        for row in db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.own_product_id.in_(product_ids),
            )
        ).all()
    }
    header_ids = set(headers) | {int(log.header_id) for log in logs if log.header_id}
    movements = _header_movements(db, tenant_id, cut_id, header_ids)
    snapshots = _count_snapshots(db, tenant_id, header_ids)
    current_counts = _current_counts(db, tenant_id, header_ids)
    bom_colors = _bom_color_sets(db, tenant_id, cut_id, product_ids)
    usage: dict[tuple[int, int | None], dict[int, dict[int, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    by_header: dict[int, list[WorkLog]] = defaultdict(list)
    for log in logs:
        by_header[int(log.header_id)].append(log)
    for header_id, header_logs in by_header.items():
        header = headers.get(header_id)
        if header is None or header.own_product_id not in product_ids:
            continue
        product_id = int(header.own_product_id)
        group = (product_id, int(header.color_id) if header.color_id else None)
        supplier_ids = set(movements.get(header_id, {})) | set(current_counts.get(header_id, {}))
        supplier_ids |= {spid for hid, spid, _person in snapshots if hid == header_id}
        supplier_ids |= {
            spid for (pid, spid) in bom_colors if pid == product_id and _color_allows(bom_colors[(pid, spid)], header.color_id)
        }
        last_log_by_emp: dict[int, int] = {}
        for log in header_logs:
            for emp_id, _pairs in _participants(log, shares_by_log.get(log.id) or []):
                last_log_by_emp[int(emp_id)] = log.id
        previous_at_by_emp: dict[int, datetime | None] = {}
        opening_by_emp: dict[tuple[int, int], Decimal] = {}
        for log in header_logs:
            participants = _participants(log, shares_by_log.get(log.id) or [])
            pair_total = sum((pairs for _, pairs in participants), _ZERO)
            visible = _in_window(log.created_at, window_start, window_end)
            reported_at = log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else ""
            for spid in supplier_ids:
                if not _color_allows(bom_colors.get((product_id, spid)), header.color_id):
                    continue
                balances = current_counts.get(header_id, {}).get(spid, {})
                rows = movements.get(header_id, {}).get(spid, [])
                for emp_id, pairs in participants:
                    emp_id = int(emp_id)
                    moved = _movement_items(
                        rows,
                        previous_at_by_emp.get(emp_id),
                        log.created_at,
                        emp_id,
                    )
                    opening = opening_by_emp.get((emp_id, spid), _ZERO)
                    own_snaps = snapshots.get((header_id, spid, emp_id), [])
                    snaps = own_snaps or snapshots.get((header_id, spid, None), [])
                    if emp_id in balances:
                        current = balances[emp_id]
                    elif not own_snaps and None in balances:
                        current = balances[None]
                    else:
                        current = _ZERO
                    remain = _remain_at(
                        snaps,
                        current,
                        previous_at_by_emp.get(emp_id),
                        log.created_at,
                        has_snapshot=bool(snaps),
                        is_last=log.id == last_log_by_emp.get(emp_id),
                        opening=opening,
                    )
                    balance = opening
                    opening_by_emp[(emp_id, spid)] = remain
                    if not visible or pair_total <= 0:
                        continue
                    for index, (moved_at, moved_kind, qty) in enumerate(moved):
                        if qty <= 0:
                            continue
                        balance += qty if moved_kind != "return" else -qty
                        stamp = moved_at.strftime("%Y-%m-%d %H:%M:%S")
                        usage[group][spid][emp_id].append(
                            {
                                "_kind": "return" if moved_kind == "return" else "issue",
                                "event_key": f"{moved_kind}-{header_id}-{spid}-{emp_id}-{stamp}-{index}",
                                "work_log_id": 0,
                                "reported_at": moved_at.strftime("%Y-%m-%d %H:%M"),
                                "sort_at": f"{stamp}-1" if moved_kind == "return" else f"{stamp}-0",
                                "header_no": header.header_no,
                                "_issued": qty if moved_kind != "return" else _ZERO,
                                "_opening": _ZERO,
                                "_returned": qty if moved_kind == "return" else _ZERO,
                                "_remain": balance,
                                "_consumed": _ZERO,
                                "_pairs": _ZERO,
                            }
                        )
                    usage[group][spid][emp_id].append(
                        {
                            "_kind": "report",
                            "event_key": f"report-{log.id}-{spid}-{emp_id}",
                            "work_log_id": log.id,
                            "reported_at": reported_at,
                            "sort_at": f"{log.created_at.strftime('%Y-%m-%d %H:%M:%S')}-2" if log.created_at else reported_at,
                            "header_no": header.header_no,
                            "_issued": _ZERO,
                            "_opening": balance,
                            "_returned": _ZERO,
                            "_remain": remain,
                            "_consumed": balance - remain,
                            "_pairs": pairs,
                        }
                    )
            for emp_id, _pairs in participants:
                previous_at_by_emp[int(emp_id)] = log.created_at
        _append_unreported_movements(
            usage,
            header=header,
            product_id=product_id,
            supplier_ids=supplier_ids,
            bom_colors=bom_colors,
            rows_by_supplier=movements.get(header_id, {}),
            last_report_at=previous_at_by_emp,
            balances=opening_by_emp,
            window_start=window_start,
            window_end=window_end,
        )
    for header_id, header in headers.items():
        if header_id in by_header or header.own_product_id not in product_ids:
            continue
        product_id = int(header.own_product_id)
        supplier_ids = set(movements.get(header_id, {}))
        supplier_ids |= {
            spid for (pid, spid) in bom_colors if pid == product_id and _color_allows(bom_colors[(pid, spid)], header.color_id)
        }
        _append_unreported_movements(
            usage,
            header=header,
            product_id=product_id,
            supplier_ids=supplier_ids,
            bom_colors=bom_colors,
            rows_by_supplier=movements.get(header_id, {}),
            last_report_at={},
            balances={},
            window_start=window_start,
            window_end=window_end,
        )
    _append_unreported_order_pickups(
        db,
        tenant_id,
        cut_id,
        product_ids,
        usage,
        bom_colors,
        window_start=window_start,
        window_end=window_end,
    )
    return usage


def _append_unreported_movements(
    usage: dict,
    *,
    header: ExecutionHeader,
    product_id: int,
    supplier_ids: set[int],
    bom_colors: dict[tuple[int, int], set[int | None]],
    rows_by_supplier: dict[int, list[tuple[datetime | None, str, Decimal, int | None]]],
    last_report_at: dict[int, datetime | None],
    balances: dict[tuple[int, int], Decimal],
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    """上次报工之后，或还没有报工的领料、退料，也放进明细。领料增加剩余，退料减少。"""
    for spid in supplier_ids:
        if not _color_allows(bom_colors.get((product_id, spid)), header.color_id):
            continue
        pending: list[tuple[datetime, str, Decimal, int]] = []
        for signed_at, kind, qty, picker_id in rows_by_supplier.get(spid, []):
            if picker_id is None or qty <= 0:
                continue
            local = signed_at + timedelta(hours=8) if signed_at is not None else None
            if local is None or not _in_window(local, window_start, window_end):
                continue
            previous = last_report_at.get(int(picker_id))
            if previous is not None and local <= previous:
                continue
            pending.append((local, kind, qty, int(picker_id)))
        pending.sort(key=lambda item: (item[0], 1 if item[1] == "return" else 0))
        running = dict(balances)
        for index, (local, kind, qty, picker_id) in enumerate(pending):
            balance = running.get((picker_id, spid), _ZERO)
            balance += qty if kind != "return" else -qty
            running[(picker_id, spid)] = balance
            stamp = local.strftime("%Y-%m-%d %H:%M:%S")
            group = (product_id, int(header.color_id) if header.color_id else None)
            usage[group][spid][picker_id].append(
                {
                    "_kind": "return" if kind == "return" else "issue",
                    "event_key": f"open-{kind}-{header.id}-{spid}-{picker_id}-{stamp}-{index}",
                    "work_log_id": 0,
                    "reported_at": local.strftime("%Y-%m-%d %H:%M"),
                    "sort_at": f"{stamp}-1" if kind == "return" else f"{stamp}-0",
                    "header_no": header.header_no,
                    "_issued": qty if kind != "return" else _ZERO,
                    "_opening": _ZERO,
                    "_returned": qty if kind == "return" else _ZERO,
                    "_remain": balance,
                    "_consumed": _ZERO,
                    "_pairs": _ZERO,
                }
            )


def _append_unreported_order_pickups(
    db: Session,
    tenant_id: int,
    cut_id: int,
    product_ids: set[int],
    usage: dict,
    bom_colors: dict[tuple[int, int], set[int | None]],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    """没有生产单号、只挂在订单上的领料退料。还没报工时也能看明细。"""
    pickups = list(
        db.scalars(
            select(WarehousePickup).where(
                WarehousePickup.tenant_id == tenant_id,
                WarehousePickup.header_id.is_(None),
                WarehousePickup.order_id.is_not(None),
                WarehousePickup.kind.in_((WarehousePickupKind.production, WarehousePickupKind.production_return)),
                WarehousePickup.status == WarehousePickupStatus.signed,
                WarehousePickup.picker_employee_id.is_not(None),
            )
        ).all()
    )
    if not pickups:
        return
    orders = {
        row.id: row
        for row in db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_({row.order_id for row in pickups if row.order_id}),
                Order.own_product_id.in_(product_ids),
            )
        ).all()
    }
    pickup_by_id = {row.id: row for row in pickups if row.order_id in orders}
    if not pickup_by_id:
        return
    lines = db.scalars(
        select(WarehousePickupLine).where(WarehousePickupLine.pickup_id.in_(pickup_by_id))
    ).all()
    req_ids = {line.requirement_id for line in lines if line.requirement_id}
    cut_reqs = set()
    if req_ids:
        cut_reqs = set(
            db.scalars(
                select(OrderMaterialRequirement.id).where(
                    OrderMaterialRequirement.tenant_id == tenant_id,
                    OrderMaterialRequirement.id.in_(req_ids),
                    OrderMaterialRequirement.consume_segment_id == cut_id,
                )
            ).all()
        )
    pending: list[tuple] = []
    for line in lines:
        if line.requirement_id not in cut_reqs:
            continue
        pickup = pickup_by_id.get(line.pickup_id)
        if pickup is None or pickup.picker_employee_id is None:
            continue
        order = orders.get(pickup.order_id or 0)
        if order is None or order.own_product_id not in product_ids:
            continue
        qty = _dec(line.qty)
        if qty <= 0:
            continue
        product_id = int(order.own_product_id)
        spid = int(line.supplier_product_id)
        if not _color_allows(bom_colors.get((product_id, spid)), None):
            continue
        local = pickup.signed_at + timedelta(hours=8) if pickup.signed_at is not None else None
        if local is None or not _in_window(local, window_start, window_end):
            continue
        kind = pickup.kind.value if hasattr(pickup.kind, "value") else str(pickup.kind)
        pending.append((local, kind, qty, product_id, spid, int(pickup.picker_employee_id), pickup.id, line.id, order.order_no))
    pending.sort(key=lambda item: (item[0], 1 if item[1] == "production_return" else 0, item[6]))
    running: dict[tuple[int, int, int], Decimal] = {}
    for local, kind, qty, product_id, spid, picker_id, pickup_id, line_id, order_no in pending:
        key = (product_id, spid, picker_id)
        balance = running.get(key, _ZERO)
        returning = kind == "production_return"
        balance += -qty if returning else qty
        running[key] = balance
        stamp = local.strftime("%Y-%m-%d %H:%M:%S")
        usage[(product_id, None)][spid][picker_id].append(
            {
                "_kind": "return" if returning else "issue",
                "event_key": f"order-{kind}-{pickup_id}-{line_id}",
                "work_log_id": 0,
                "reported_at": local.strftime("%Y-%m-%d %H:%M"),
                "sort_at": f"{stamp}-1" if returning else f"{stamp}-0",
                "header_no": order_no,
                "_issued": _ZERO if returning else qty,
                "_opening": _ZERO,
                "_returned": qty if returning else _ZERO,
                "_remain": balance,
                "_consumed": _ZERO,
                "_pairs": _ZERO,
            }
        )


def _participants(log: WorkLog, shares: list[WorkLogGroupShare]) -> list[tuple[int, Decimal]]:
    if shares:
        return [(int(share.worker_id), _dec(share.pairs)) for share in shares]
    qty = _dec(log.qualified_qty)
    if qty <= 0 or not log.worker_id:
        return []
    return [(int(log.worker_id), qty)]


def _color_allows(colors: set[int | None] | None, header_color_id: int | None) -> bool:
    """没有配色约束、整款共用，或生产单颜色对得上，这条物料才挂到这次报工。"""
    if not colors or None in colors or header_color_id is None:
        return True
    return int(header_color_id) in colors


def _bom_color_sets(
    db: Session,
    tenant_id: int,
    cut_id: int,
    product_ids: set[int],
) -> dict[tuple[int, int], set[int | None]]:
    rows = db.scalars(
        select(OwnProductMaterial).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id.in_(product_ids),
            OwnProductMaterial.consume_segment_id == cut_id,
        )
    ).all()
    colors: dict[tuple[int, int], set[int | None]] = defaultdict(set)
    for row in rows:
        colors[(int(row.own_product_id), int(row.supplier_product_id))].add(
            int(row.color_id) if row.color_id is not None else None
        )
    return colors


def _header_movements(
    db: Session,
    tenant_id: int,
    cut_id: int,
    header_ids: set[int],
) -> dict[int, dict[int, list[tuple[datetime | None, str, Decimal, int | None]]]]:
    """header → 物料 → [(签收时间, 领料或退料, 数量, 领料人)]。"""
    if not header_ids:
        return {}
    pickups = list(
        db.scalars(
            select(WarehousePickup).where(
                WarehousePickup.tenant_id == tenant_id,
                WarehousePickup.header_id.in_(header_ids),
                WarehousePickup.kind.in_((WarehousePickupKind.production, WarehousePickupKind.production_return)),
                WarehousePickup.status == WarehousePickupStatus.signed,
            )
        ).all()
    )
    if not pickups:
        return {}
    pickup_by_id = {row.id: row for row in pickups}
    lines = db.scalars(
        select(WarehousePickupLine).where(WarehousePickupLine.pickup_id.in_(pickup_by_id))
    ).all()
    req_ids = {line.requirement_id for line in lines if line.requirement_id}
    cut_reqs = set()
    if req_ids:
        cut_reqs = set(
            db.scalars(
                select(OrderMaterialRequirement.id).where(
                    OrderMaterialRequirement.tenant_id == tenant_id,
                    OrderMaterialRequirement.id.in_(req_ids),
                    OrderMaterialRequirement.consume_segment_id == cut_id,
                )
            ).all()
        )
    movements: dict[int, dict[int, list[tuple[datetime | None, str, Decimal, int | None]]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        if line.requirement_id not in cut_reqs:
            continue
        pickup = pickup_by_id[line.pickup_id]
        if not pickup.header_id:
            continue
        kind = pickup.kind.value if hasattr(pickup.kind, "value") else str(pickup.kind)
        movements[int(pickup.header_id)][int(line.supplier_product_id)].append(
            (
                pickup.signed_at,
                "return" if kind == "production_return" else "issue",
                _dec(line.qty),
                int(pickup.picker_employee_id) if pickup.picker_employee_id else None,
            )
        )
    return movements


def _movement_items(
    rows: list[tuple[datetime | None, str, Decimal, int | None]],
    previous_at: datetime | None,
    reported_at: datetime | None,
    employee_id: int,
) -> list[tuple[datetime, str, Decimal]]:
    """这个人自己的领料、退料：上次报工之后，到这次报工为止。

    签收时间是 UTC，报工时间是本地时间，先拨回 8 小时再比较。
    """
    found: list[tuple[datetime, str, Decimal]] = []
    for signed_at, kind, qty, picker_id in rows:
        if picker_id != employee_id or qty <= 0:
            continue
        signed_at = signed_at + timedelta(hours=8) if signed_at is not None else None
        if signed_at is None or reported_at is None or signed_at > reported_at:
            continue
        if previous_at is not None and signed_at <= previous_at:
            continue
        found.append((signed_at, kind, qty))
    found.sort(key=lambda item: (item[0], 1 if item[1] == "return" else 0))
    return found


def _count_snapshots(
    db: Session,
    tenant_id: int,
    header_ids: set[int],
) -> dict[tuple[int, int, int | None], list[WorkshopMaterialCountLog]]:
    if not header_ids:
        return {}
    grouped: dict[tuple[int, int, int | None], list[WorkshopMaterialCountLog]] = defaultdict(list)
    rows = db.scalars(
        select(WorkshopMaterialCountLog)
        .where(
            WorkshopMaterialCountLog.tenant_id == tenant_id,
            WorkshopMaterialCountLog.header_id.in_(header_ids),
        )
        .order_by(WorkshopMaterialCountLog.created_at, WorkshopMaterialCountLog.id)
    ).all()
    for row in rows:
        person = int(row.counted_by) if row.counted_by else None
        grouped[(int(row.header_id), int(row.supplier_product_id), person)].append(row)
    return grouped


def _current_counts(
    db: Session,
    tenant_id: int,
    header_ids: set[int],
) -> dict[int, dict[int, dict[int | None, Decimal]]]:
    if not header_ids:
        return {}
    totals: dict[int, dict[int, dict[int | None, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: _ZERO))
    )
    rows = db.scalars(
        select(WorkshopMaterialCount).where(
            WorkshopMaterialCount.tenant_id == tenant_id,
            WorkshopMaterialCount.header_id.in_(header_ids),
        )
    ).all()
    for row in rows:
        person = int(row.counted_by) if row.counted_by else None
        totals[int(row.header_id)][int(row.supplier_product_id)][person] += _dec(row.qty)
    return totals


def _remain_at(
    snapshots: list[WorkshopMaterialCountLog],
    current_qty: Decimal,
    previous_at: datetime | None,
    reported_at: datetime | None,
    *,
    has_snapshot: bool,
    is_last: bool,
    opening: Decimal,
) -> Decimal:
    chosen: dict[int | None, WorkshopMaterialCountLog] = {}
    for row in snapshots:
        moment = row.created_at
        if moment is None or reported_at is None or moment > reported_at:
            continue
        if previous_at is not None and moment <= previous_at:
            continue
        chosen[row.size_id] = row
    if chosen:
        return sum((_dec(row.qty) for row in chosen.values()), _ZERO)
    if not has_snapshot and is_last:
        return current_qty
    return opening


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
