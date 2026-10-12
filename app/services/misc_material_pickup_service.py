"""不跟生产单的领料：从物料色卡选择，到货后整单确认并扣公用库存。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    MaterialCategory,
    MiscMaterialPickup,
    MiscMaterialPickupLine,
    MiscMaterialPickupStatus,
    Partner,
    PricingUnit,
    SharedLedgerType,
    SupplierProduct,
)
from app.schemas.common import normalize_page, page_payload
from app.services.material_service import MaterialError, _shared_qty, adjust_shared_stock


class PickupError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _status_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _qty_text(qty: Decimal | None) -> str:
    text = format(qty or Decimal("0"), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _gen_doc_no(db: Session, tenant_id: int) -> str:
    day = date.today().strftime("%y%m%d")
    like = f"MP{day}%"
    n = (
        db.scalar(
            select(func.count())
            .select_from(MiscMaterialPickup)
            .where(MiscMaterialPickup.tenant_id == tenant_id, MiscMaterialPickup.doc_no.like(like))
        )
        or 0
    )
    return f"MP{day}{int(n) + 1:03d}"


def _load(db: Session, tenant_id: int, pickup_id: int) -> MiscMaterialPickup | None:
    return db.scalar(
        select(MiscMaterialPickup)
        .where(MiscMaterialPickup.id == pickup_id, MiscMaterialPickup.tenant_id == tenant_id)
        .options(selectinload(MiscMaterialPickup.lines))
    )


def _get_owned(db: Session, tenant_id: int, pickup_id: int, user_id: int) -> MiscMaterialPickup:
    row = _load(db, tenant_id, pickup_id)
    if not row:
        raise PickupError("not_found", "领料记录不存在")
    if row.requested_by != user_id:
        raise PickupError("forbidden", "只能处理自己提交的领料")
    return row


def _product(db: Session, tenant_id: int, product_id: int) -> SupplierProduct:
    product = db.get(SupplierProduct, product_id)
    if not product or product.tenant_id != tenant_id or not product.is_active:
        raise PickupError("product_not_found", "物料不存在或已停用")
    return product


def _unit_name(db: Session, product: SupplierProduct) -> str | None:
    if not product.pricing_unit_id:
        return None
    unit = db.get(PricingUnit, product.pricing_unit_id)
    return unit.name if unit and unit.tenant_id == product.tenant_id else None


def _line_dict(line: MiscMaterialPickupLine) -> dict:
    return {
        "id": line.id,
        "supplier_product_id": line.supplier_product_id,
        "material_name": line.material_name,
        "material_code": line.material_code or "",
        "unit_name": line.unit_name or "",
        "qty": _qty_text(line.qty),
    }


def _row_dict(row: MiscMaterialPickup) -> dict:
    lines = sorted(row.lines or [], key=lambda item: item.id or 0)
    return {
        "id": row.id,
        "doc_no": row.doc_no,
        "notes": row.notes or "",
        "status": _status_value(row.status),
        "line_count": len(lines),
        "lines": [_line_dict(line) for line in lines],
        "created_at": _iso(row.created_at),
        "received_at": _iso(row.received_at),
    }


def search_materials(db: Session, tenant_id: int, keyword: str, *, limit: int = 20) -> list[dict]:
    text = (keyword or "").strip()
    query = (
        select(SupplierProduct, Partner, Color, MaterialCategory, PricingUnit)
        .join(Partner, Partner.id == SupplierProduct.partner_id)
        .outerjoin(Color, Color.id == SupplierProduct.color_id)
        .outerjoin(MaterialCategory, MaterialCategory.id == SupplierProduct.category_id)
        .outerjoin(PricingUnit, PricingUnit.id == SupplierProduct.pricing_unit_id)
        .where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.is_active.is_(True),
        )
    )
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(
                SupplierProduct.product_code.ilike(like),
                SupplierProduct.name.ilike(like),
                SupplierProduct.internal_code.ilike(like),
                Partner.name.ilike(like),
                Color.name.ilike(like),
                MaterialCategory.name.ilike(like),
            )
        )
    rows = db.execute(
        query.order_by(SupplierProduct.id.desc()).limit(max(1, min(limit, 30)))
    ).all()
    out = []
    for product, partner, color, category, unit in rows:
        out.append(
            {
                "id": product.id,
                "product_code": product.product_code,
                "name": product.name or "",
                "image_url": product.image_url or "",
                "color_name": color.name if color else "",
                "category_name": category.name if category else "",
                "partner_name": partner.name if partner else "",
                "unit_name": unit.name if unit else "",
                "stock_qty": _qty_text(_shared_qty(db, tenant_id, product.id, None)),
            }
        )
    return out


def list_pickups(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    page, page_size, offset = normalize_page(page, page_size)
    filters = (
        MiscMaterialPickup.tenant_id == tenant_id,
        MiscMaterialPickup.requested_by == user_id,
    )
    total = db.scalar(select(func.count()).select_from(MiscMaterialPickup).where(*filters)) or 0
    pending = (
        db.scalar(
            select(func.count())
            .select_from(MiscMaterialPickup)
            .where(*filters, MiscMaterialPickup.status == MiscMaterialPickupStatus.pending)
        )
        or 0
    )
    rows = db.scalars(
        select(MiscMaterialPickup)
        .where(*filters)
        .options(selectinload(MiscMaterialPickup.lines))
        .order_by(MiscMaterialPickup.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    data = page_payload([_row_dict(row) for row in rows], int(total), page, page_size)
    data["pending_count"] = int(pending)
    return data


def _resolve_line(db: Session, tenant_id: int, raw: dict) -> dict:
    try:
        qty = Decimal(str(raw.get("qty") if raw.get("qty") is not None else ""))
    except Exception as exc:
        raise PickupError("invalid_qty", "数量须大于 0") from exc
    if qty <= 0:
        raise PickupError("invalid_qty", "数量须大于 0")
    product_id = raw.get("supplier_product_id")
    if not product_id:
        raise PickupError("product_required", "请从物料色卡选择物料")
    product = _product(db, tenant_id, int(product_id))
    name = (product.name or "").strip() or product.product_code
    code = product.product_code
    unit_name = _unit_name(db, product)
    if len(name) > 100:
        raise PickupError("name_too_long", "物料名称不能超过 100 字")
    identity = f"id:{product.id}"
    return {
        "identity": identity,
        "supplier_product_id": product.id,
        "material_name": name,
        "material_code": code or None,
        "unit_name": unit_name,
        "qty": qty,
    }


def create_pickup(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    if not lines:
        raise PickupError("lines_required", "请至少添加一种物料")
    if len(lines) > 30:
        raise PickupError("too_many_lines", "一次最多领 30 种物料")
    note = (notes or "").strip() or None
    if note and len(note) > 255:
        raise PickupError("notes_too_long", "备注不能超过 255 字")
    resolved = []
    seen: set[str] = set()
    for raw in lines:
        item = _resolve_line(db, tenant_id, raw)
        if item["identity"] in seen:
            raise PickupError("duplicate_material", f"{item['material_name']} 已在这张领料单里")
        seen.add(item["identity"])
        resolved.append(item)
    row = MiscMaterialPickup(
        tenant_id=tenant_id,
        doc_no=_gen_doc_no(db, tenant_id),
        notes=note,
        status=MiscMaterialPickupStatus.pending,
        requested_by=user_id,
    )
    db.add(row)
    db.flush()
    for item in resolved:
        db.add(
            MiscMaterialPickupLine(
                tenant_id=tenant_id,
                pickup_id=row.id,
                supplier_product_id=item["supplier_product_id"],
                material_name=item["material_name"],
                material_code=item["material_code"],
                unit_name=item["unit_name"],
                qty=item["qty"],
            )
        )
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded) if loaded else _row_dict(row)


def receive_pickup(db: Session, tenant_id: int, pickup_id: int, user_id: int) -> dict:
    row = _get_owned(db, tenant_id, pickup_id, user_id)
    if row.status != MiscMaterialPickupStatus.pending:
        raise PickupError("invalid_status", "只有待领取的记录可以确认")
    doc_no = row.doc_no
    deductions = [
        (line.material_name, line.supplier_product_id, Decimal(line.qty))
        for line in row.lines
        if line.supplier_product_id
    ]
    for material_name, product_id, qty in deductions:
        try:
            adjust_shared_stock(
                db,
                tenant_id,
                int(product_id),
                -qty,
                note=f"非生产领料 {doc_no} {material_name}",
                user_id=user_id,
                ledger_type=SharedLedgerType.misc_issue,
                ref_type="misc_material_pickup",
                ref_id=pickup_id,
            )
        except MaterialError as exc:
            db.rollback()
            if exc.code == "insufficient_shared":
                raise PickupError(
                    "insufficient_shared",
                    f"{material_name} 公用库存不足，到货后再确认领取",
                ) from exc
            raise PickupError(exc.code, exc.message) from exc
    row = _get_owned(db, tenant_id, pickup_id, user_id)
    row.status = MiscMaterialPickupStatus.received
    row.received_by = user_id
    row.received_at = datetime.now(timezone.utc)
    db.commit()
    loaded = _load(db, tenant_id, pickup_id)
    return _row_dict(loaded or row)


def cancel_pickup(db: Session, tenant_id: int, pickup_id: int, user_id: int) -> dict:
    row = _get_owned(db, tenant_id, pickup_id, user_id)
    if row.status != MiscMaterialPickupStatus.pending:
        raise PickupError("invalid_status", "只有待领取的记录可以取消")
    row.status = MiscMaterialPickupStatus.cancelled
    db.commit()
    db.refresh(row)
    return _row_dict(row)
