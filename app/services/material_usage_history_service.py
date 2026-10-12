"""产品物料用量流水：只有用量数字变了才落历史。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Employee,
    MaterialUsageHistory,
    OwnProduct,
    OwnProductMaterial,
    ProcessSegment,
    SupplierProduct,
)
from app.services.cut_material_usage_service import cut_material_usage

_QTY = Decimal("0.0001")


class MaterialUsageApplyError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_QTY, rounding=ROUND_HALF_UP)


def _qty_text(value: Decimal) -> str:
    text = format(_qty(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def snapshot_material_qty(lines) -> list[dict]:
    return [
        {
            "supplier_product_id": int(row.supplier_product_id),
            "color_id": row.color_id,
            "consume_segment_id": row.consume_segment_id,
            "qty": _qty(row.qty),
        }
        for row in list(lines or [])
    ]


def record_material_qty_changes(
    db: Session,
    product: OwnProduct,
    old_lines: list[dict],
    *,
    changed_by: int | None,
    source: str,
) -> None:
    """按物料对照保存前的用量。数量没变不落流水；同一物料相同的旧值到新值只记一条。"""
    old_by_supplier: dict[int, list[Decimal]] = {}
    for previous in old_lines:
        old_by_supplier.setdefault(int(previous["supplier_product_id"]), []).append(_qty(previous["qty"]))
    new_by_supplier: dict[int, list] = {}
    for row in product.materials:
        new_by_supplier.setdefault(int(row.supplier_product_id), []).append(row)
    supplier_ids = set(old_by_supplier) | set(new_by_supplier)
    labels = _labels(db, product.tenant_id, supplier_ids)
    seen: set[tuple] = set()
    for supplier_id in supplier_ids:
        old_pool = list(old_by_supplier.get(supplier_id, []))
        changed: list[tuple] = []
        for row in new_by_supplier.get(supplier_id, []):
            new_qty = _qty(row.qty)
            if new_qty in old_pool:
                old_pool.remove(new_qty)
                continue
            changed.append((row, new_qty))
        for index, (row, new_qty) in enumerate(changed):
            old_qty = old_pool[index] if index < len(old_pool) else None
            if old_qty is None:
                if new_qty <= 0:
                    continue
            elif old_qty == new_qty:
                continue
            key = (supplier_id, old_qty, new_qty)
            if key in seen:
                continue
            seen.add(key)
            label = labels.get(supplier_id, {})
            db.add(
                _history_row(
                    product,
                    supplier_product_id=supplier_id,
                    material_code=label.get("material_code"),
                    material_name=label.get("material_name"),
                    old_qty=old_qty,
                    new_qty=new_qty,
                    changed_by=changed_by,
                    source=source,
                )
            )


def apply_cut_average(
    db: Session,
    tenant_id: int,
    *,
    own_product_id: int,
    supplier_product_id: int,
    date_from: date | None,
    date_to: date | None,
    changed_by: int | None,
) -> dict:
    product = _product(db, tenant_id, own_product_id)
    report = cut_material_usage(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        factory_model=product.product_code,
    )
    material = _report_material(report, product.id, supplier_product_id)
    if material is None or not material.get("on_bom"):
        raise MaterialUsageApplyError("该物料不在产品裁断用料上")
    average = material.get("average_usage")
    if average is None:
        raise MaterialUsageApplyError("没有可应用的实际平均用量")
    return _overwrite_cut_lines(
        db,
        product,
        supplier_product_id=supplier_product_id,
        new_qty=_qty(average),
        changed_by=changed_by,
        source="cut_average",
    )


def restore_material_usage(
    db: Session,
    tenant_id: int,
    *,
    history_id: int,
    changed_by: int | None,
) -> dict:
    row = db.get(MaterialUsageHistory, history_id)
    if row is None or row.tenant_id != tenant_id:
        raise MaterialUsageApplyError("用量历史不存在")
    product = _product(db, tenant_id, row.own_product_id)
    return _overwrite_cut_lines(
        db,
        product,
        supplier_product_id=row.supplier_product_id,
        new_qty=_qty(row.new_qty),
        changed_by=changed_by,
        source="history_restore",
    )


def list_material_usage_history(
    db: Session,
    tenant_id: int,
    *,
    own_product_id: int,
    supplier_product_id: int,
    limit: int = 30,
) -> list[MaterialUsageHistory]:
    rows = list(
        db.scalars(
            select(MaterialUsageHistory)
            .where(
                MaterialUsageHistory.tenant_id == tenant_id,
                MaterialUsageHistory.own_product_id == own_product_id,
                MaterialUsageHistory.supplier_product_id == supplier_product_id,
            )
            .order_by(MaterialUsageHistory.changed_at.desc(), MaterialUsageHistory.id.desc())
            .limit(max(limit * 3, limit))
        ).all()
    )
    return _dedupe_history(rows)[:limit]


def _dedupe_history(rows: list[MaterialUsageHistory]) -> list[MaterialUsageHistory]:
    """用量没变的流水不返回。连续重复的同一组旧值到新值只留最早一条。"""
    kept: list[MaterialUsageHistory] = []
    for row in reversed(rows):
        old = None if row.old_qty is None else _qty(row.old_qty)
        new = _qty(row.new_qty)
        if old is not None and old == new:
            continue
        if kept:
            prev = kept[-1]
            prev_old = None if prev.old_qty is None else _qty(prev.old_qty)
            if prev_old == old and _qty(prev.new_qty) == new:
                continue
        kept.append(row)
    kept.reverse()
    return kept


def changed_by_names(db: Session, rows: list[MaterialUsageHistory]) -> dict[int, str]:
    emp_ids = {row.changed_by for row in rows if row.changed_by}
    if not emp_ids:
        return {}
    return {
        emp.id: emp.name
        for emp in db.scalars(select(Employee).where(Employee.id.in_(list(emp_ids)))).all()
        if emp.name
    }


def _overwrite_cut_lines(
    db: Session,
    product: OwnProduct,
    *,
    supplier_product_id: int,
    new_qty: Decimal,
    changed_by: int | None,
    source: str,
) -> dict:
    cut_id = db.scalar(
        select(ProcessSegment.id).where(
            ProcessSegment.tenant_id == product.tenant_id,
            ProcessSegment.code == "cut",
        )
    )
    if cut_id is None:
        raise MaterialUsageApplyError("没有裁断工序段")
    lines = list(
        db.scalars(
            select(OwnProductMaterial).where(
                OwnProductMaterial.tenant_id == product.tenant_id,
                OwnProductMaterial.own_product_id == product.id,
                OwnProductMaterial.supplier_product_id == supplier_product_id,
                OwnProductMaterial.consume_segment_id == cut_id,
            )
        ).all()
    )
    if not lines:
        raise MaterialUsageApplyError("该物料不在产品裁断用料上")
    changed = [row for row in lines if _qty(row.qty) != new_qty]
    if not changed:
        return {"changed": False, "qty": _qty_text(new_qty), "line_count": len(lines)}
    label = _labels(db, product.tenant_id, {supplier_product_id}).get(supplier_product_id, {})
    old_values = {_qty(row.qty) for row in changed}
    for row in changed:
        row.qty = new_qty
        row.line_total = (new_qty * Decimal(row.unit_price or 0)).quantize(_QTY, rounding=ROUND_HALF_UP)
    for old_qty in old_values:
        db.add(
            _history_row(
                product,
                supplier_product_id=supplier_product_id,
                material_code=label.get("material_code"),
                material_name=label.get("material_name"),
                old_qty=old_qty,
                new_qty=new_qty,
                changed_by=changed_by,
                source=source,
            )
        )
    db.flush()
    total = db.scalar(
        select(func.coalesce(func.sum(OwnProductMaterial.line_total), 0)).where(
            OwnProductMaterial.tenant_id == product.tenant_id,
            OwnProductMaterial.own_product_id == product.id,
        )
    )
    product.material_cost = Decimal(total or 0).quantize(_QTY, rounding=ROUND_HALF_UP)
    return {
        "changed": True,
        "qty": _qty_text(new_qty),
        "old_qty": _qty_text(next(iter(old_values))) if len(old_values) == 1 else None,
        "line_count": len(lines),
    }


def _history_row(
    product: OwnProduct,
    *,
    supplier_product_id: int,
    material_code: str | None,
    material_name: str | None,
    old_qty: Decimal | None,
    new_qty: Decimal,
    changed_by: int | None,
    source: str,
) -> MaterialUsageHistory:
    return MaterialUsageHistory(
        tenant_id=product.tenant_id,
        own_product_id=product.id,
        product_code=product.product_code,
        supplier_product_id=supplier_product_id,
        material_code=material_code,
        material_name=material_name,
        old_qty=old_qty,
        new_qty=new_qty,
        changed_by=changed_by,
        source=source,
    )


def _labels(db: Session, tenant_id: int, supplier_ids: set[int]) -> dict[int, dict]:
    if not supplier_ids:
        return {}
    rows = db.scalars(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.id.in_(supplier_ids),
        )
    ).all()
    return {
        row.id: {"material_code": row.product_code, "material_name": row.name}
        for row in rows
    }


def _product(db: Session, tenant_id: int, own_product_id: int) -> OwnProduct:
    product = db.get(OwnProduct, own_product_id)
    if product is None or product.tenant_id != tenant_id:
        raise MaterialUsageApplyError("产品不存在")
    return product


def _report_material(report: dict, own_product_id: int, supplier_product_id: int) -> dict | None:
    for model in report.get("models") or []:
        if model.get("own_product_id") != own_product_id:
            continue
        for material in model.get("materials") or []:
            if material.get("supplier_product_id") == supplier_product_id:
                return material
    return None
