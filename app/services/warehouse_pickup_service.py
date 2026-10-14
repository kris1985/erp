"""物料仓当场领料：仓管开单后出示二维码，领料人用手机扫码确认后才出库。"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    OwnProduct,
    SharedLedgerType,
    SharedMaterialLedger,
    SpecExecutionStatus,
    StockDoc,
    StockDocStatus,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
)
from app.schemas.common import normalize_page, page_payload
from app.services.material_service import MaterialError, _shared_avg_cost, _shared_qty, adjust_shared_stock
from app.services.misc_material_pickup_service import search_materials
from app.services.stock_doc_service import (
    confirm_stock_doc,
    list_issue_candidates,
    submit_stock_doc,
    void_stock_doc,
)

_STATUS_LABELS = {
    "pending": "待确认",
    "signed": "已确认",
    "cancelled": "已取消",
}


class WarehousePickupError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _qty_text(qty: Decimal | None) -> str:
    text = format(qty or Decimal("0"), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _parse_qty(raw) -> Decimal:
    try:
        qty = Decimal(str(raw if raw is not None else ""))
    except Exception as exc:
        raise WarehousePickupError("invalid_qty", "数量须大于 0") from exc
    if qty <= 0:
        raise WarehousePickupError("invalid_qty", "数量须大于 0")
    return qty


_KIND_LABELS = {
    "dev": "开发部领料",
    "aux": "生产领辅料耗材",
    "production": "生产领主料",
    "dev_return": "开发部退料",
    "aux_return": "生产退辅料",
    "production_return": "生产退主料",
}
_POOL_KINDS = {
    "dev": (SharedLedgerType.dev_issue, "开发部领料"),
    "aux": (SharedLedgerType.aux_issue, "生产领辅料耗材"),
}
_POOL_RETURNS = {
    "dev_return": (SharedLedgerType.dev_return, SharedLedgerType.dev_issue, "开发部退料"),
    "aux_return": (SharedLedgerType.aux_return, SharedLedgerType.aux_issue, "生产退辅料"),
}
_RETURN_KINDS = frozenset(_POOL_RETURNS) | {"production_return"}
_DOC_PREFIX = {
    "dev": "DV",
    "aux": "AX",
    "dev_return": "DR",
    "aux_return": "AR",
    "production_return": "PR",
}


def _slip_name(kind: str) -> str:
    return "退料单" if kind in _RETURN_KINDS else "领料单"


def _gen_doc_no(db: Session, tenant_id: int, kind: WarehousePickupKind) -> str:
    prefix = _DOC_PREFIX.get(_enum_value(kind), "PD")
    day = date.today().strftime("%y%m%d")
    like = f"{prefix}{day}%"
    n = (
        db.scalar(
            select(func.count())
            .select_from(WarehousePickup)
            .where(WarehousePickup.tenant_id == tenant_id, WarehousePickup.doc_no.like(like))
        )
        or 0
    )
    return f"{prefix}{day}{int(n) + 1:03d}"


def _load(db: Session, tenant_id: int, pickup_id: int) -> WarehousePickup | None:
    return db.scalar(
        select(WarehousePickup)
        .where(WarehousePickup.id == pickup_id, WarehousePickup.tenant_id == tenant_id)
        .options(selectinload(WarehousePickup.lines))
    )


def _line_dict(line: WarehousePickupLine) -> dict:
    return {
        "id": line.id,
        "supplier_product_id": line.supplier_product_id,
        "size_id": line.size_id,
        "size_value": line.size_value or "",
        "requirement_id": line.requirement_id,
        "material_name": line.material_name,
        "material_code": line.material_code or "",
        "unit_name": line.unit_name or "",
        "qty": _qty_text(line.qty),
    }


def _row_dict(row: WarehousePickup, *, with_signature: bool = False, with_token: bool = False) -> dict:
    lines = sorted(row.lines or [], key=lambda item: item.id or 0)
    kind = _enum_value(row.kind)
    status = _enum_value(row.status) or "pending"
    data = {
        "id": row.id,
        "doc_no": row.doc_no,
        "kind": kind,
        "kind_label": _KIND_LABELS.get(kind, kind),
        "status": status,
        "status_label": _STATUS_LABELS.get(status, status),
        "sign_token": row.sign_token or "",
        "header_id": row.header_id,
        "header_no": row.header_no or "",
        "order_id": row.order_id,
        "stock_doc_id": row.stock_doc_id,
        "notes": row.notes or "",
        "picker_employee_id": row.picker_employee_id,
        "picker_name": row.picker_name or "",
        "line_count": len(lines),
        "lines": [_line_dict(line) for line in lines],
        "created_at": _iso(row.created_at),
        "signed_at": _iso(row.signed_at),
    }
    if not with_token:
        data.pop("sign_token", None)
    if with_signature:
        data["signature_data"] = row.signature_data or ""
    return data


def search_production_headers(db: Session, tenant_id: int, keyword: str, *, limit: int = 20) -> dict:
    text = (keyword or "").strip()
    stmt = (
        select(ExecutionHeader, OwnProduct.product_code, Color.name)
        .join(OwnProduct, OwnProduct.id == ExecutionHeader.own_product_id)
        .outerjoin(Color, Color.id == ExecutionHeader.color_id)
        .where(
            ExecutionHeader.tenant_id == tenant_id,
            ExecutionHeader.status != SpecExecutionStatus.cancelled,
        )
        .order_by(ExecutionHeader.id.desc())
        .limit(min(max(int(limit or 20), 1), 30))
    )
    if text:
        like = f"%{text}%"
        stmt = stmt.where(
            or_(
                ExecutionHeader.header_no.ilike(like),
                OwnProduct.product_code.ilike(like),
            )
        )
    rows = db.execute(stmt).all()
    return {
        "items": [
            {
                "header_id": header.id,
                "header_no": header.header_no,
                "product_code": product_code or "",
                "color_name": color_name or "",
                "total_qty": int(header.total_qty or 0),
            }
            for header, product_code, color_name in rows
        ]
    }


def preview_production(db: Session, tenant_id: int, header_no: str) -> dict:
    text = (header_no or "").strip()
    if not text:
        raise WarehousePickupError("header_required", "请输入生产单号")
    header = db.scalar(
        select(ExecutionHeader).where(
            ExecutionHeader.tenant_id == tenant_id,
            ExecutionHeader.header_no == text,
        )
    )
    if not header:
        like = f"%{text}%"
        matches = list(
            db.scalars(
                select(ExecutionHeader)
                .where(
                    ExecutionHeader.tenant_id == tenant_id,
                    ExecutionHeader.header_no.ilike(like),
                    ExecutionHeader.status != SpecExecutionStatus.cancelled,
                )
                .order_by(ExecutionHeader.id.desc())
                .limit(8)
            ).all()
        )
        if not matches:
            raise WarehousePickupError("header_not_found", "找不到这张生产单")
        if len(matches) > 1:
            return {
                "ambiguous": True,
                "matches": [
                    {
                        "header_id": row.id,
                        "header_no": row.header_no,
                        "total_qty": int(row.total_qty or 0),
                    }
                    for row in matches
                ],
            }
        header = matches[0]
    if header.status == SpecExecutionStatus.cancelled:
        raise WarehousePickupError("header_cancelled", "生产单已取消")
    try:
        candidates = list_issue_candidates(db, tenant_id, header_id=header.id)
    except MaterialError as exc:
        raise WarehousePickupError(exc.code, exc.message) from exc
    lines = []
    for row in candidates.get("lines") or []:
        lines.append(
            {
                "requirement_id": row.get("id"),
                "supplier_product_id": row.get("supplier_product_id"),
                "material_name": row.get("supplier_product_name") or "",
                "material_code": row.get("supplier_product_code") or "",
                "color_name": row.get("color_name") or "",
                "unit_name": row.get("pricing_unit_name") or "",
                "required_qty": _qty_text(row.get("required_qty")),
                "issued_qty": _qty_text(row.get("issued_qty")),
                "pool_qty": _qty_text(row.get("pool_qty")),
                "max_issue_qty": _qty_text(row.get("max_issue_qty")),
                "returnable_qty": _qty_text(row.get("returnable_qty")),
            }
        )
    return {
        "ambiguous": False,
        "header_id": header.id,
        "header_no": header.header_no,
        "order_id": candidates.get("order_id"),
        "total_qty": int(header.total_qty or 0),
        "lines": lines,
    }


def _positive_lines(lines: list[dict]) -> list[dict]:
    kept = []
    for raw in lines or []:
        qty_raw = raw.get("qty")
        if qty_raw is None or str(qty_raw).strip() in ("", "0", "0.0"):
            continue
        kept.append(raw)
    if not kept:
        raise WarehousePickupError("lines_required", "请至少填写一种物料的数量")
    if len(kept) > 40:
        raise WarehousePickupError("too_many_lines", "一次最多 40 种物料")
    return kept


def _insert_pending(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    kind: WarehousePickupKind,
    notes: str | None,
    lines: list[dict],
    header_id: int | None = None,
    header_no: str | None = None,
    order_id: int | None = None,
) -> WarehousePickup:
    row = WarehousePickup(
        tenant_id=tenant_id,
        doc_no=_gen_doc_no(db, tenant_id, kind),
        kind=kind,
        status=WarehousePickupStatus.pending,
        sign_token=secrets.token_urlsafe(18),
        header_id=header_id,
        header_no=header_no,
        order_id=order_id,
        notes=notes,
        created_by=user_id,
    )
    db.add(row)
    db.flush()
    for item in lines:
        db.add(
            WarehousePickupLine(
                tenant_id=tenant_id,
                pickup_id=row.id,
                supplier_product_id=int(item["supplier_product_id"]),
                size_id=item.get("size_id"),
                size_value=item.get("size_value") or None,
                requirement_id=item.get("requirement_id"),
                material_name=item["material_name"],
                material_code=item.get("material_code"),
                unit_name=item.get("unit_name"),
                qty=item["qty"],
            )
        )
    db.flush()
    return row


def _note(raw: str | None) -> str | None:
    text = (raw or "").strip() or None
    if text and len(text) > 255:
        raise WarehousePickupError("notes_too_long", "备注不能超过 255 字")
    return text


def _line_size(db: Session, tenant_id: int, raw: dict) -> tuple[int | None, str | None]:
    from app.models import Size

    value = raw.get("size_id")
    if value in (None, "", 0, "0"):
        return None, None
    size = db.get(Size, int(value))
    if not size or size.tenant_id != tenant_id:
        raise WarehousePickupError("size_not_found", "尺码不存在")
    return size.id, size.size_value


def _resolve_dev_lines(db: Session, tenant_id: int, lines: list[dict]) -> list[dict]:
    resolved = []
    seen: set[tuple[int, int | None]] = set()
    for raw in _positive_lines(lines):
        product_id = raw.get("supplier_product_id")
        if not product_id:
            raise WarehousePickupError("product_required", "请从物料仓选择物料")
        product = db.get(SupplierProduct, int(product_id))
        if not product or product.tenant_id != tenant_id or not product.is_active:
            raise WarehousePickupError("product_not_found", "物料不存在或已停用")
        size_id, size_value = _line_size(db, tenant_id, raw)
        key = (product.id, size_id)
        label = (product.name or "").strip() or product.product_code
        if size_value:
            label = f"{label} {size_value}"
        if key in seen:
            raise WarehousePickupError("duplicate_material", f"{label} 已在这张单里")
        seen.add(key)
        qty = _parse_qty(raw.get("qty"))
        stock = _shared_qty(db, tenant_id, product.id, size_id)
        if qty > stock:
            raise WarehousePickupError(
                "insufficient_shared",
                f"{label} 库存不足（现有 {_qty_text(stock)}）",
            )
        from app.models import PricingUnit

        unit_name = None
        if product.pricing_unit_id:
            unit = db.get(PricingUnit, product.pricing_unit_id)
            if unit and unit.tenant_id == tenant_id:
                unit_name = unit.name
        resolved.append(
            {
                "supplier_product_id": product.id,
                "size_id": size_id,
                "size_value": size_value,
                "material_name": (product.name or "").strip() or product.product_code,
                "material_code": product.product_code,
                "unit_name": unit_name,
                "qty": qty,
            }
        )
    return resolved


def _create_pool_pickup(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    kind: WarehousePickupKind,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    resolved = _resolve_dev_lines(db, tenant_id, lines)
    row = _insert_pending(
        db,
        tenant_id,
        user_id,
        kind=kind,
        notes=_note(notes),
        lines=resolved,
    )
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row, with_token=True)


def create_dev_pickup(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    return _create_pool_pickup(
        db, tenant_id, user_id, kind=WarehousePickupKind.dev, lines=lines, notes=notes
    )


def _reject_non_auxiliary(db: Session, tenant_id: int, lines: list[dict]) -> None:
    """生产领辅料只允许「是否辅料」分类下的物料。"""
    from app.models import MaterialCategory, SupplierProduct

    for raw in _positive_lines(lines):
        product_id = raw.get("supplier_product_id")
        if not product_id:
            continue
        product = db.get(SupplierProduct, int(product_id))
        if not product or product.tenant_id != tenant_id:
            continue
        cat = db.get(MaterialCategory, product.category_id) if product.category_id else None
        if cat is None or cat.tenant_id != tenant_id or not cat.is_auxiliary:
            label = (product.name or "").strip() or product.product_code
            raise WarehousePickupError("not_auxiliary", f"{label} 不是辅料分类，不能领辅料")


def create_aux_pickup(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    _reject_non_auxiliary(db, tenant_id, lines)
    return _create_pool_pickup(
        db, tenant_id, user_id, kind=WarehousePickupKind.aux, lines=lines, notes=notes
    )


def _size_filter(column, size_id: int | None):
    if size_id is None:
        return column.is_(None)
    return column == size_id


def _ledger_qty_sum(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None,
    ledger_type: SharedLedgerType,
) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(SharedMaterialLedger.qty_delta), 0)).where(
            SharedMaterialLedger.tenant_id == tenant_id,
            SharedMaterialLedger.supplier_product_id == supplier_product_id,
            SharedMaterialLedger.ledger_type == ledger_type,
            _size_filter(SharedMaterialLedger.size_id, size_id),
        )
    )
    return Decimal(str(total or 0))


def _pending_pool_return_qty(
    db: Session,
    tenant_id: int,
    kind: WarehousePickupKind,
    supplier_product_id: int,
    size_id: int | None,
    *,
    exclude_pickup_id: int | None = None,
) -> Decimal:
    filters = [
        WarehousePickup.tenant_id == tenant_id,
        WarehousePickup.kind == kind,
        WarehousePickup.status == WarehousePickupStatus.pending,
        WarehousePickupLine.supplier_product_id == supplier_product_id,
        _size_filter(WarehousePickupLine.size_id, size_id),
    ]
    if exclude_pickup_id:
        filters.append(WarehousePickup.id != exclude_pickup_id)
    total = db.scalar(
        select(func.coalesce(func.sum(WarehousePickupLine.qty), 0))
        .select_from(WarehousePickupLine)
        .join(WarehousePickup, WarehousePickup.id == WarehousePickupLine.pickup_id)
        .where(*filters)
    )
    return Decimal(str(total or 0))


def pool_returnable_qty(
    db: Session,
    tenant_id: int,
    kind: str,
    supplier_product_id: int,
    size_id: int | None,
    *,
    exclude_pickup_id: int | None = None,
) -> Decimal:
    spec = _POOL_RETURNS.get(kind)
    if not spec:
        raise WarehousePickupError("invalid_kind", "退料类型无效")
    return_type, issue_type, _label = spec
    issued = -_ledger_qty_sum(db, tenant_id, supplier_product_id, size_id, issue_type)
    returned = _ledger_qty_sum(db, tenant_id, supplier_product_id, size_id, return_type)
    pending = _pending_pool_return_qty(
        db,
        tenant_id,
        WarehousePickupKind(kind),
        supplier_product_id,
        size_id,
        exclude_pickup_id=exclude_pickup_id,
    )
    return max(Decimal("0"), issued - returned - pending)


def quote_pool_returnable(db: Session, tenant_id: int, kind: str, lines: list[dict]) -> dict:
    if kind not in _POOL_RETURNS:
        raise WarehousePickupError("invalid_kind", "退料类型无效")
    quoted = []
    for raw in lines or []:
        product_id = raw.get("supplier_product_id")
        if not product_id:
            continue
        size_id, _size_value = _line_size(db, tenant_id, raw)
        qty = pool_returnable_qty(db, tenant_id, kind, int(product_id), size_id)
        quoted.append(
            {
                "supplier_product_id": int(product_id),
                "size_id": size_id,
                "returnable_qty": _qty_text(qty),
            }
        )
    return {"lines": quoted}


def _resolve_return_lines(db: Session, tenant_id: int, kind: str, lines: list[dict]) -> list[dict]:
    resolved = []
    seen: set[tuple[int, int | None]] = set()
    for raw in _positive_lines(lines):
        product_id = raw.get("supplier_product_id")
        if not product_id:
            raise WarehousePickupError("product_required", "请从物料仓选择物料")
        product = db.get(SupplierProduct, int(product_id))
        if not product or product.tenant_id != tenant_id or not product.is_active:
            raise WarehousePickupError("product_not_found", "物料不存在或已停用")
        size_id, size_value = _line_size(db, tenant_id, raw)
        key = (product.id, size_id)
        label = (product.name or "").strip() or product.product_code
        if size_value:
            label = f"{label} {size_value}"
        if key in seen:
            raise WarehousePickupError("duplicate_material", f"{label} 已在这张单里")
        seen.add(key)
        qty = _parse_qty(raw.get("qty"))
        returnable = pool_returnable_qty(db, tenant_id, kind, product.id, size_id)
        if qty > returnable:
            raise WarehousePickupError(
                "exceed_returnable",
                f"{label} 可退 {_qty_text(returnable)}，本次 {_qty_text(qty)}",
            )
        from app.models import PricingUnit

        unit_name = None
        if product.pricing_unit_id:
            unit = db.get(PricingUnit, product.pricing_unit_id)
            if unit and unit.tenant_id == tenant_id:
                unit_name = unit.name
        resolved.append(
            {
                "supplier_product_id": product.id,
                "size_id": size_id,
                "size_value": size_value,
                "material_name": (product.name or "").strip() or product.product_code,
                "material_code": product.product_code,
                "unit_name": unit_name,
                "qty": qty,
            }
        )
    return resolved


def _create_pool_return(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    kind: WarehousePickupKind,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    resolved = _resolve_return_lines(db, tenant_id, _enum_value(kind), lines)
    row = _insert_pending(
        db,
        tenant_id,
        user_id,
        kind=kind,
        notes=_note(notes),
        lines=resolved,
    )
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row, with_token=True)


def create_dev_return(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    return _create_pool_return(
        db, tenant_id, user_id, kind=WarehousePickupKind.dev_return, lines=lines, notes=notes
    )


def create_aux_return(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    return _create_pool_return(
        db, tenant_id, user_id, kind=WarehousePickupKind.aux_return, lines=lines, notes=notes
    )


def _prepare_production_lines(db: Session, tenant_id: int, header_no: str, lines: list[dict]) -> tuple[dict, list[dict]]:
    preview = preview_production(db, tenant_id, header_no)
    if preview.get("ambiguous"):
        raise WarehousePickupError("header_ambiguous", "匹配到多张生产单，请输入完整单号")
    by_req = {int(row["requirement_id"]): row for row in preview["lines"] if row.get("requirement_id")}
    prepared = []
    seen: set[int] = set()
    for raw in _positive_lines(lines):
        requirement_id = raw.get("requirement_id")
        if not requirement_id:
            raise WarehousePickupError("requirement_required", "生产领主料须按生产单物料填写")
        requirement_id = int(requirement_id)
        row = by_req.get(requirement_id)
        if not row:
            raise WarehousePickupError("requirement_not_found", "物料不在这张生产单上")
        if requirement_id in seen:
            raise WarehousePickupError("duplicate_material", f"{row['material_name']} 重复了")
        seen.add(requirement_id)
        qty = _parse_qty(raw.get("qty"))
        max_issue = Decimal(str(row["max_issue_qty"] or "0"))
        if qty > max_issue:
            raise WarehousePickupError(
                "insufficient_shared",
                f"{row['material_name']} 可领 {_qty_text(max_issue)}，本次 {_qty_text(qty)}",
            )
        prepared.append(
            {
                "requirement_id": requirement_id,
                "supplier_product_id": int(row["supplier_product_id"]),
                "material_name": row["material_name"] or row["material_code"] or "物料",
                "material_code": row["material_code"] or None,
                "unit_name": row["unit_name"] or None,
                "qty": qty,
            }
        )
    return preview, prepared


def create_production_pickup(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    header_no: str,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    preview, prepared = _prepare_production_lines(db, tenant_id, header_no, lines)
    row = _insert_pending(
        db,
        tenant_id,
        user_id,
        kind=WarehousePickupKind.production,
        notes=_note(notes),
        lines=prepared,
        header_id=int(preview["header_id"]),
        header_no=preview["header_no"],
        order_id=preview.get("order_id"),
    )
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row, with_token=True)


def _pending_production_return_qty(
    db: Session,
    tenant_id: int,
    requirement_id: int,
    *,
    exclude_pickup_id: int | None = None,
) -> Decimal:
    filters = [
        WarehousePickup.tenant_id == tenant_id,
        WarehousePickup.kind == WarehousePickupKind.production_return,
        WarehousePickup.status == WarehousePickupStatus.pending,
        WarehousePickupLine.requirement_id == requirement_id,
    ]
    if exclude_pickup_id:
        filters.append(WarehousePickup.id != exclude_pickup_id)
    total = db.scalar(
        select(func.coalesce(func.sum(WarehousePickupLine.qty), 0))
        .select_from(WarehousePickupLine)
        .join(WarehousePickup, WarehousePickup.id == WarehousePickupLine.pickup_id)
        .where(*filters)
    )
    return Decimal(str(total or 0))


def _prepare_production_return_lines(
    db: Session,
    tenant_id: int,
    header_no: str,
    lines: list[dict],
    *,
    exclude_pickup_id: int | None = None,
) -> tuple[dict, list[dict]]:
    preview = preview_production(db, tenant_id, header_no)
    if preview.get("ambiguous"):
        raise WarehousePickupError("header_ambiguous", "匹配到多张生产单，请输入完整单号")
    by_req = {int(row["requirement_id"]): row for row in preview["lines"] if row.get("requirement_id")}
    prepared = []
    seen: set[int] = set()
    for raw in _positive_lines(lines):
        requirement_id = raw.get("requirement_id")
        if not requirement_id:
            raise WarehousePickupError("requirement_required", "生产退主料须按生产单物料填写")
        requirement_id = int(requirement_id)
        row = by_req.get(requirement_id)
        if not row:
            raise WarehousePickupError("requirement_not_found", "物料不在这张生产单上")
        if requirement_id in seen:
            raise WarehousePickupError("duplicate_material", f"{row['material_name']} 重复了")
        seen.add(requirement_id)
        qty = _parse_qty(raw.get("qty"))
        pending = _pending_production_return_qty(
            db, tenant_id, requirement_id, exclude_pickup_id=exclude_pickup_id
        )
        max_return = max(Decimal("0"), Decimal(str(row.get("returnable_qty") or "0")) - pending)
        if qty > max_return:
            raise WarehousePickupError(
                "exceed_returnable",
                f"{row['material_name']} 可退 {_qty_text(max_return)}，本次 {_qty_text(qty)}",
            )
        prepared.append(
            {
                "requirement_id": requirement_id,
                "supplier_product_id": int(row["supplier_product_id"]),
                "material_name": row["material_name"] or row["material_code"] or "物料",
                "material_code": row["material_code"] or None,
                "unit_name": row["unit_name"] or None,
                "qty": qty,
            }
        )
    return preview, prepared


def create_production_return(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    header_no: str,
    lines: list[dict],
    notes: str | None = None,
) -> dict:
    preview, prepared = _prepare_production_return_lines(db, tenant_id, header_no, lines)
    row = _insert_pending(
        db,
        tenant_id,
        user_id,
        kind=WarehousePickupKind.production_return,
        notes=_note(notes),
        lines=prepared,
        header_id=int(preview["header_id"]),
        header_no=preview["header_no"],
        order_id=preview.get("order_id"),
    )
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row, with_token=True)


def list_pickups(
    db: Session,
    tenant_id: int,
    *,
    kind: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page, page_size, offset = normalize_page(page, page_size)
    filters = [WarehousePickup.tenant_id == tenant_id]
    if kind in _KIND_LABELS:
        filters.append(WarehousePickup.kind == WarehousePickupKind(kind))
    if status in {item.value for item in WarehousePickupStatus}:
        filters.append(WarehousePickup.status == WarehousePickupStatus(status))
    total = db.scalar(select(func.count()).select_from(WarehousePickup).where(*filters)) or 0
    rows = db.scalars(
        select(WarehousePickup)
        .where(*filters)
        .options(selectinload(WarehousePickup.lines))
        .order_by(WarehousePickup.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return page_payload([_row_dict(row) for row in rows], int(total), page, page_size)


def get_pickup(db: Session, tenant_id: int, pickup_id: int) -> dict:
    row = _load(db, tenant_id, pickup_id)
    if not row:
        raise WarehousePickupError("not_found", "领料记录不存在")
    return _row_dict(row, with_signature=True, with_token=True)


def get_by_token(db: Session, tenant_id: int, token: str) -> dict:
    text = (token or "").strip()
    if not text:
        raise WarehousePickupError("not_found", "领料单不存在")
    row = db.scalar(
        select(WarehousePickup)
        .where(WarehousePickup.tenant_id == tenant_id, WarehousePickup.sign_token == text)
        .options(selectinload(WarehousePickup.lines))
    )
    if not row:
        raise WarehousePickupError("not_found", "领料单不存在或已失效")
    return _row_dict(row, with_signature=True, with_token=True)


def sign_url(origin: str, token: str) -> str:
    base = (origin or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise WarehousePickupError("origin_required", "无法生成确认二维码")
    return f"{base}/pickup-sign/{token}"


def make_sign_qr(origin: str, token: str) -> dict:
    import base64
    import io

    import qrcode

    url = sign_url(origin, token)
    image = qrcode.make(url)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"sign_url": url, "qr_png": f"data:image/png;base64,{encoded}"}


def _lock(db: Session, tenant_id: int, token: str) -> WarehousePickup:
    text = (token or "").strip()
    row = db.scalar(
        select(WarehousePickup)
        .where(WarehousePickup.tenant_id == tenant_id, WarehousePickup.sign_token == text)
        .options(selectinload(WarehousePickup.lines))
        .with_for_update()
    )
    if not row:
        raise WarehousePickupError("not_found", "领料单不存在或已失效")
    return row


def _post_pool(
    db: Session,
    tenant_id: int,
    row: WarehousePickup,
    user_id: int,
    *,
    ledger_type: SharedLedgerType,
    note_prefix: str,
) -> None:
    for line in row.lines:
        stock = _shared_qty(db, tenant_id, line.supplier_product_id, line.size_id)
        if line.qty > stock:
            label = line.material_name or line.material_code or "物料"
            if line.size_value:
                label = f"{label} {line.size_value}"
            raise WarehousePickupError(
                "insufficient_shared",
                f"{label} 库存不足（现有 {_qty_text(stock)}）",
            )
    try:
        for line in row.lines:
            adjust_shared_stock(
                db,
                tenant_id,
                line.supplier_product_id,
                -line.qty,
                size_id=line.size_id,
                unit_cost=_shared_avg_cost(
                    db, tenant_id, line.supplier_product_id, line.size_id
                ),
                note=f"{note_prefix} {row.doc_no} {line.material_name or ''}",
                user_id=user_id,
                ledger_type=ledger_type,
                ref_type="warehouse_pickup",
                ref_id=row.id,
            )
    except MaterialError as exc:
        db.rollback()
        if exc.code == "insufficient_shared":
            raise WarehousePickupError("insufficient_shared", "公用库存不足") from exc
        raise WarehousePickupError(exc.code, exc.message) from exc


def _post_production(db: Session, tenant_id: int, row: WarehousePickup, user_id: int) -> None:
    if row.stock_doc_id:
        doc = db.get(StockDoc, row.stock_doc_id)
        if doc and doc.status == StockDocStatus.posted:
            return
        if doc and doc.status == StockDocStatus.pending:
            try:
                confirm_stock_doc(db, tenant_id, doc.id, user_id=user_id)
            except MaterialError as exc:
                db.rollback()
                try:
                    void_stock_doc(db, tenant_id, doc.id, user_id=user_id)
                except MaterialError:
                    db.rollback()
                raise WarehousePickupError(exc.code, exc.message) from exc
            return
    issue_lines = [
        {"requirement_id": line.requirement_id, "qty": line.qty}
        for line in row.lines
        if line.requirement_id
    ]
    if not issue_lines or not row.header_id:
        raise WarehousePickupError("lines_required", "这张生产领主料单没有物料")
    try:
        pending = submit_stock_doc(
            db,
            tenant_id,
            doc_type="issue",
            header_id=int(row.header_id),
            lines=issue_lines,
            notes=row.notes or f"物料仓生产领主料 {row.header_no or ''}",
            user_id=user_id,
        )
    except MaterialError as exc:
        db.rollback()
        raise WarehousePickupError(exc.code, exc.message) from exc
    row.stock_doc_id = int(pending["id"])
    db.commit()
    try:
        confirm_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
    except MaterialError as exc:
        db.rollback()
        try:
            void_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
        except MaterialError:
            db.rollback()
        raise WarehousePickupError(exc.code, exc.message) from exc


def _post_pool_return(
    db: Session,
    tenant_id: int,
    row: WarehousePickup,
    user_id: int,
    *,
    ledger_type: SharedLedgerType,
    note_prefix: str,
) -> None:
    kind = _enum_value(row.kind)
    for line in row.lines:
        returnable = pool_returnable_qty(
            db,
            tenant_id,
            kind,
            line.supplier_product_id,
            line.size_id,
            exclude_pickup_id=row.id,
        )
        if line.qty > returnable:
            label = line.material_name or line.material_code or "物料"
            if line.size_value:
                label = f"{label} {line.size_value}"
            raise WarehousePickupError(
                "exceed_returnable",
                f"{label} 可退 {_qty_text(returnable)}，本次 {_qty_text(line.qty)}",
            )
    try:
        for line in row.lines:
            adjust_shared_stock(
                db,
                tenant_id,
                line.supplier_product_id,
                line.qty,
                size_id=line.size_id,
                unit_cost=_shared_avg_cost(
                    db, tenant_id, line.supplier_product_id, line.size_id
                ),
                note=f"{note_prefix} {row.doc_no} {line.material_name or ''}",
                user_id=user_id,
                ledger_type=ledger_type,
                ref_type="warehouse_pickup",
                ref_id=row.id,
            )
    except MaterialError as exc:
        db.rollback()
        raise WarehousePickupError(exc.code, exc.message) from exc


def _post_production_return(db: Session, tenant_id: int, row: WarehousePickup, user_id: int) -> None:
    if row.stock_doc_id:
        doc = db.get(StockDoc, row.stock_doc_id)
        if doc and doc.status == StockDocStatus.posted:
            return
        if doc and doc.status == StockDocStatus.pending:
            try:
                confirm_stock_doc(db, tenant_id, doc.id, user_id=user_id)
            except MaterialError as exc:
                db.rollback()
                try:
                    void_stock_doc(db, tenant_id, doc.id, user_id=user_id)
                except MaterialError:
                    db.rollback()
                raise WarehousePickupError(exc.code, exc.message) from exc
            return
    issue_lines = [
        {"requirement_id": line.requirement_id, "qty": line.qty}
        for line in row.lines
        if line.requirement_id
    ]
    if not issue_lines or not row.header_id:
        raise WarehousePickupError("lines_required", "这张生产退主料单没有物料")
    _prepare_production_return_lines(
        db,
        tenant_id,
        row.header_no or "",
        issue_lines,
        exclude_pickup_id=row.id,
    )
    try:
        pending = submit_stock_doc(
            db,
            tenant_id,
            doc_type="return_mat",
            header_id=int(row.header_id),
            lines=issue_lines,
            notes=row.notes or f"物料仓生产退主料 {row.header_no or ''}",
            user_id=user_id,
        )
    except MaterialError as exc:
        db.rollback()
        raise WarehousePickupError(exc.code, exc.message) from exc
    row.stock_doc_id = int(pending["id"])
    db.commit()
    try:
        confirm_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
    except MaterialError as exc:
        db.rollback()
        try:
            void_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
        except MaterialError:
            db.rollback()
        raise WarehousePickupError(exc.code, exc.message) from exc


def sign_pickup(db: Session, tenant_id: int, token: str, employee: Employee) -> dict:
    if not employee.is_active or employee.tenant_id != tenant_id:
        raise WarehousePickupError("picker_not_found", "找不到这位确认人")
    row = _lock(db, tenant_id, token)
    kind = _enum_value(row.kind)
    status = _enum_value(row.status)
    if status == "signed":
        raise WarehousePickupError("already_signed", f"这张{_slip_name(kind)}已经确认")
    if status != "pending":
        raise WarehousePickupError("not_pending", f"这张{_slip_name(kind)}已取消")
    pool = _POOL_KINDS.get(kind)
    pool_return = _POOL_RETURNS.get(kind)
    if pool:
        ledger_type, note_prefix = pool
        _post_pool(
            db,
            tenant_id,
            row,
            employee.id,
            ledger_type=ledger_type,
            note_prefix=note_prefix,
        )
    elif pool_return:
        ledger_type, _issue_type, note_prefix = pool_return
        _post_pool_return(
            db,
            tenant_id,
            row,
            employee.id,
            ledger_type=ledger_type,
            note_prefix=note_prefix,
        )
    elif kind == "production_return":
        _post_production_return(db, tenant_id, row, employee.id)
    else:
        _post_production(db, tenant_id, row, employee.id)
    row.picker_employee_id = employee.id
    row.picker_name = employee.name
    row.status = WarehousePickupStatus.signed
    row.signed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row, with_signature=True)


def cancel_pickup(db: Session, tenant_id: int, user_id: int, pickup_id: int) -> dict:
    row = db.scalar(
        select(WarehousePickup)
        .where(WarehousePickup.id == pickup_id, WarehousePickup.tenant_id == tenant_id)
        .options(selectinload(WarehousePickup.lines))
        .with_for_update()
    )
    if not row:
        raise WarehousePickupError("not_found", "领料记录不存在")
    status = _enum_value(row.status)
    if status == "signed":
        done = "入库" if _enum_value(row.kind) in _RETURN_KINDS else "出库"
        raise WarehousePickupError("already_signed", f"已经确认{done}，不能取消")
    if status == "pending" and row.stock_doc_id:
        doc = db.get(StockDoc, row.stock_doc_id)
        if doc and doc.status == StockDocStatus.pending:
            try:
                void_stock_doc(db, tenant_id, doc.id, user_id=user_id)
            except MaterialError as exc:
                db.rollback()
                raise WarehousePickupError(exc.code, exc.message) from exc
    if status != "cancelled":
        row.status = WarehousePickupStatus.cancelled
        db.commit()
    loaded = _load(db, tenant_id, row.id)
    return _row_dict(loaded or row)


def search_dev_materials(db: Session, tenant_id: int, keyword: str) -> list[dict]:
    text = (keyword or "").strip()
    if not text:
        return []
    return search_materials(db, tenant_id, text)
