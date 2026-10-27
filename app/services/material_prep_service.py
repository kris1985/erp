"""按生产单备第一工序段物料：扣仓库现存量，并绑定一张空闲备料码。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    MaterialPrep,
    MaterialPrepLine,
    MaterialPrepQr,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    PricingUnit,
    ProcessSegment,
    SpecExecutionStatus,
    SharedLedgerType,
    SharedMaterialLedger,
    StockDoc,
    StockDocStatus,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
)
from app.services.material_service import MaterialError, adjust_shared_stock, is_tooling_requirement

QR_COUNT = 10
_QTY = Decimal("0.0001")


class MaterialPrepError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value: Decimal) -> Decimal:
    return _dec(value).quantize(_QTY, rounding=ROUND_HALF_UP)


def _qty_text(value: Decimal) -> str:
    text = f"{_money(value):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _status_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _header(db: Session, tenant_id: int, header_id: int) -> ExecutionHeader:
    row = db.get(ExecutionHeader, header_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialPrepError("header_not_found", "生产单不存在")
    if _status_value(row.status) == SpecExecutionStatus.cancelled.value:
        raise MaterialPrepError("header_cancelled", "生产单已取消")
    return row


def _requirements(db: Session, tenant_id: int, header: ExecutionHeader) -> list[OrderMaterialRequirement]:
    conds = [OrderMaterialRequirement.header_id == header.id]
    if header.shop_order_id:
        conds.append(OrderMaterialRequirement.order_id == header.shop_order_id)
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            or_(*conds),
        )
    ).all()
    seen: set[int] = set()
    out: list[OrderMaterialRequirement] = []
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(row)
    return out


def _first_segment(db: Session, tenant_id: int, header: ExecutionHeader) -> tuple[int | None, str]:
    """路线里排序最靠前的工序段。没有段时，未标注物料算第一段。"""
    conds = [OrderProcess.header_id == header.id]
    if header.shop_order_id:
        conds.append(OrderProcess.order_id == header.shop_order_id)
    procs = db.scalars(
        select(OrderProcess).where(OrderProcess.tenant_id == tenant_id, or_(*conds))
    ).all()
    seg_ids = {int(row.segment_id) for row in procs if row.segment_id}
    if not seg_ids:
        return None, ""
    segments = db.scalars(select(ProcessSegment).where(ProcessSegment.id.in_(seg_ids))).all()
    sorts = {int(row.id): int(row.sort_order or 0) for row in segments}
    names = {int(row.id): row.name for row in segments}
    ranked = [row for row in procs if row.segment_id]
    ranked.sort(key=lambda row: (sorts.get(int(row.segment_id), 0), int(row.id)))
    seg_id = int(ranked[0].segment_id)
    return seg_id, names.get(seg_id, "")


def _in_first_segment(row: OrderMaterialRequirement, segment_id: int | None) -> bool:
    current = int(row.consume_segment_id) if row.consume_segment_id else None
    if segment_id is None:
        return current is None
    return current is None or current == segment_id


def _per_pair(required: Decimal, total_qty: int, rows: list[OrderMaterialRequirement]) -> Decimal:
    if total_qty > 0:
        return required / Decimal(total_qty)
    per = Decimal("0")
    for row in rows:
        per += _dec(row.qty_per_pair) * (Decimal("1") + _dec(row.loss_rate))
    return per


def _split(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    usable = [_dec(item) if _dec(item) > 0 else Decimal("0") for item in weights]
    base = sum(usable, Decimal("0"))
    if base <= 0:
        usable = [Decimal("1")] * len(weights)
        base = Decimal(len(weights))
    parts: list[Decimal] = []
    used = Decimal("0")
    for index, weight in enumerate(usable):
        if index == len(usable) - 1:
            part = _money(total - used)
            if part < 0:
                part = Decimal("0")
        else:
            part = _money(total * weight / base)
            used += part
        parts.append(part if part > 0 else Decimal("0"))
    return parts


def _product_meta(db: Session, product_ids: set[int]) -> dict[int, dict]:
    if not product_ids:
        return {}
    products = db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(product_ids))).all()
    color_ids = {int(row.color_id) for row in products if row.color_id}
    unit_ids = {int(row.pricing_unit_id) for row in products if row.pricing_unit_id}
    colors = {}
    units = {}
    if color_ids:
        colors = {int(row.id): row.name for row in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()}
    if unit_ids:
        units = {
            int(row.id): row.name
            for row in db.scalars(select(PricingUnit).where(PricingUnit.id.in_(unit_ids))).all()
        }
    return {
        int(row.id): {
            "material_code": row.product_code,
            "material_name": row.name or row.product_code,
            "color_name": colors.get(int(row.color_id)) if row.color_id else "",
            "image_url": row.image_url or "",
            "unit_name": units.get(int(row.pricing_unit_id)) if row.pricing_unit_id else "",
        }
        for row in products
    }


def preview_materials(db: Session, tenant_id: int, header_id: int) -> dict:
    header = _header(db, tenant_id, header_id)
    segment_id, segment_name = _first_segment(db, tenant_id, header)
    groups: dict[int, dict] = {}
    for row in _requirements(db, tenant_id, header):
        if is_tooling_requirement(db, row):
            continue
        if not _in_first_segment(row, segment_id):
            continue
        bucket = groups.setdefault(
            int(row.supplier_product_id),
            {"rows": [], "required": Decimal("0"), "customer_supplied": True},
        )
        bucket["rows"].append(row)
        bucket["required"] += _dec(row.required_qty)
        if not row.is_customer_supplied:
            bucket["customer_supplied"] = False
    meta = _product_meta(db, set(groups))
    lines = []
    total_qty = int(header.total_qty or 0)
    for product_id, bucket in groups.items():
        info = meta.get(product_id, {})
        per = _per_pair(bucket["required"], total_qty, bucket["rows"])
        lines.append(
            {
                "supplier_product_id": product_id,
                "material_code": info.get("material_code") or "",
                "material_name": info.get("material_name") or "物料",
                "color_name": info.get("color_name") or "",
                "image_url": info.get("image_url") or "",
                "unit_name": info.get("unit_name") or "",
                "qty_per_pair": _qty_text(per),
                "customer_supplied": bool(bucket["customer_supplied"]),
            }
        )
    lines.sort(key=lambda item: (item["material_code"], item["material_name"]))
    return {
        "header_id": header.id,
        "header_no": header.header_no,
        "total_qty": total_qty,
        "segment_id": segment_id,
        "segment_name": segment_name,
        "lines": lines,
    }


def _order_row(header: ExecutionHeader, product_code: str, color_name: str, prepared: int) -> dict:
    return {
        "header_id": header.id,
        "header_no": header.header_no,
        "product_code": product_code,
        "color_name": color_name,
        "total_qty": int(header.total_qty or 0),
        "prepared_pairs": prepared,
        "status": _status_value(header.status),
    }


def list_orders(db: Session, tenant_id: int) -> list[dict]:
    # 与手机生产进度「未完成」同一套顺序：排产拖拽优先，没排过的按开单时间。
    from app.services import execution_service

    total = execution_service.count_execution_headers(db, tenant_id=tenant_id, status="active")
    headers = execution_service.list_execution_headers(
        db,
        tenant_id=tenant_id,
        status="active",
        offset=0,
        limit=max(int(total), 1),
    )
    if not headers:
        return []
    header_ids = [int(row.id) for row in headers]
    prepared_rows = db.execute(
        select(MaterialPrep.header_id, func.coalesce(func.sum(MaterialPrep.pairs), 0))
        .where(
            MaterialPrep.tenant_id == tenant_id,
            MaterialPrep.header_id.in_(header_ids),
            MaterialPrep.status.in_(("pending", "signed")),
        )
        .group_by(MaterialPrep.header_id)
    ).all()
    prepared = {int(header_id): int(qty or 0) for header_id, qty in prepared_rows}
    product_ids = {int(row.own_product_id) for row in headers if row.own_product_id}
    color_ids = {int(row.color_id) for row in headers if row.color_id}
    products = {}
    colors = {}
    if product_ids:
        products = {
            int(row.id): row.product_code
            for row in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(product_ids))).all()
        }
    if color_ids:
        colors = {int(row.id): row.name for row in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()}
    return [
        _order_row(
            row,
            products.get(int(row.own_product_id), "") if row.own_product_id else "",
            colors.get(int(row.color_id), "") if row.color_id else "",
            prepared.get(int(row.id), 0),
        )
        for row in headers
    ]


def ensure_qrs(db: Session, tenant_id: int) -> list[MaterialPrepQr]:
    rows = db.scalars(
        select(MaterialPrepQr)
        .where(MaterialPrepQr.tenant_id == tenant_id)
        .order_by(MaterialPrepQr.slot)
    ).all()
    have = {int(row.slot) for row in rows}
    for slot in range(1, QR_COUNT + 1):
        if slot in have:
            continue
        db.add(
            MaterialPrepQr(
                tenant_id=tenant_id,
                slot=slot,
                token=secrets.token_urlsafe(18),
            )
        )
    if len(have) < QR_COUNT:
        db.flush()
        rows = db.scalars(
            select(MaterialPrepQr)
            .where(MaterialPrepQr.tenant_id == tenant_id)
            .order_by(MaterialPrepQr.slot)
        ).all()
    return list(rows)


def _occupied_map(db: Session, tenant_id: int) -> dict[int, MaterialPrep]:
    rows = db.scalars(
        select(MaterialPrep)
        .where(
            MaterialPrep.tenant_id == tenant_id,
            MaterialPrep.status == "pending",
        )
        .options(selectinload(MaterialPrep.lines))
    ).all()
    return {int(row.qr_id): row for row in rows}


def _qr_material_lines(prep: MaterialPrep | None) -> list[dict]:
    if not prep:
        return []
    lines = []
    for line in prep.lines:
        if _dec(line.actual_qty) <= 0:
            continue
        lines.append(
            {
                "id": line.id,
                "material_code": line.material_code or "",
                "material_name": line.material_name,
                "color_name": line.color_name or "",
                "actual_qty": _qty_text(line.actual_qty),
                "unit_name": line.unit_name or "",
                "customer_supplied": bool(line.customer_supplied),
            }
        )
    return lines


def sign_url(origin: str, token: str) -> str:
    base = (origin or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise MaterialPrepError("origin_required", "无法生成备料码")
    return f"{base}/prep-sign/{token}"


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


def list_qrs(db: Session, tenant_id: int, origin: str = "") -> list[dict]:
    rows = ensure_qrs(db, tenant_id)
    db.commit()
    occupied = _occupied_map(db, tenant_id)
    out = []
    for row in rows:
        prep = occupied.get(int(row.id))
        item = {
            "id": row.id,
            "slot": int(row.slot),
            "occupied": prep is not None,
            "header_no": prep.header_no if prep else "",
            "doc_no": prep.doc_no if prep else "",
            "pairs": int(prep.pairs or 0) if prep else 0,
            "lines": _qr_material_lines(prep),
            "sign_url": "",
            "qr_png": "",
        }
        if origin:
            try:
                item.update(make_sign_qr(origin, row.token))
            except MaterialPrepError:
                pass
        out.append(item)
    return out


def _lock_free_qr(db: Session, tenant_id: int) -> MaterialPrepQr:
    rows = db.scalars(
        select(MaterialPrepQr)
        .where(MaterialPrepQr.tenant_id == tenant_id)
        .order_by(MaterialPrepQr.slot)
        .with_for_update()
    ).all()
    if len(rows) < QR_COUNT:
        rows = ensure_qrs(db, tenant_id)
        rows = db.scalars(
            select(MaterialPrepQr)
            .where(MaterialPrepQr.tenant_id == tenant_id)
            .order_by(MaterialPrepQr.slot)
            .with_for_update()
        ).all()
    occupied = set(_occupied_map(db, tenant_id))
    for row in rows:
        if int(row.id) not in occupied:
            return row
    raise MaterialPrepError("qr_busy", "10 个备料码都在使用，等领料人扫码确认后再备")


def _line_dict(line: MaterialPrepLine) -> dict:
    return {
        "id": line.id,
        "supplier_product_id": line.supplier_product_id,
        "material_code": line.material_code or "",
        "material_name": line.material_name,
        "color_name": line.color_name or "",
        "image_url": line.image_url or "",
        "unit_name": line.unit_name or "",
        "qty": _qty_text(line.qty),
        "actual_qty": _qty_text(line.actual_qty),
        "customer_supplied": bool(line.customer_supplied),
    }


def _slip_dict(db: Session, row: MaterialPrep, *, with_qr: bool = False, origin: str = "") -> dict:
    qr = db.get(MaterialPrepQr, row.qr_id)
    data = {
        "id": row.id,
        "doc_no": row.doc_no,
        "header_id": row.header_id,
        "header_no": row.header_no,
        "pairs": int(row.pairs or 0),
        "status": row.status,
        "slot": int(qr.slot) if qr else None,
        "picker_name": row.picker_name or "",
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "lines": [_line_dict(line) for line in row.lines],
    }
    if with_qr and qr and origin:
        try:
            data.update(make_sign_qr(origin, qr.token))
        except MaterialPrepError:
            data["sign_url"] = ""
            data["qr_png"] = ""
    return data


def create_prep(
    db: Session,
    tenant_id: int,
    user_id: int,
    *,
    header_id: int,
    pairs: int,
    lines: list[dict],
    origin: str = "",
) -> dict:
    if int(pairs) <= 0:
        raise MaterialPrepError("invalid_pairs", "双数须大于 0")
    header = _header(db, tenant_id, header_id)
    preview = preview_materials(db, tenant_id, header.id)
    catalog = {int(item["supplier_product_id"]): item for item in preview["lines"]}
    if not catalog:
        name = preview["segment_name"] or "第一工序段"
        raise MaterialPrepError("no_materials", f"{name}没有可备的物料")
    wanted: dict[int, Decimal] = {}
    for item in lines:
        product_id = int(item["supplier_product_id"])
        actual = _money(_dec(item.get("actual_qty")))
        if product_id not in catalog:
            raise MaterialPrepError("material_not_in_segment", "有物料不在第一工序段")
        if product_id in wanted:
            raise MaterialPrepError("duplicate_material", "物料重复了")
        if actual < 0:
            raise MaterialPrepError("invalid_qty", "实际数量不能小于 0")
        wanted[product_id] = actual
    if not any(qty > 0 for qty in wanted.values()):
        raise MaterialPrepError("lines_required", "请至少填写一种物料的实际数量")

    groups: dict[int, list[OrderMaterialRequirement]] = {}
    segment_id, _segment_name = _first_segment(db, tenant_id, header)
    for row in _requirements(db, tenant_id, header):
        if is_tooling_requirement(db, row) or not _in_first_segment(row, segment_id):
            continue
        groups.setdefault(int(row.supplier_product_id), []).append(row)

    issue_lines: list[dict] = []
    prep_lines: list[MaterialPrepLine] = []
    pair_count = int(pairs)
    for product_id, actual in wanted.items():
        info = catalog[product_id]
        calculated = _money(_dec(info["qty_per_pair"]) * Decimal(pair_count))
        prep_lines.append(
            MaterialPrepLine(
                tenant_id=tenant_id,
                supplier_product_id=product_id,
                material_code=info["material_code"] or None,
                material_name=info["material_name"],
                color_name=info["color_name"] or None,
                image_url=info["image_url"] or None,
                unit_name=info["unit_name"] or None,
                qty=calculated,
                actual_qty=actual,
                customer_supplied=bool(info["customer_supplied"]),
            )
        )
        if actual <= 0 or info["customer_supplied"]:
            continue
        stock_rows = [row for row in groups.get(product_id, []) if not row.is_customer_supplied]
        parts = _split(actual, [_dec(row.required_qty) for row in stock_rows])
        for row, part in zip(stock_rows, parts):
            if part <= 0:
                continue
            issue_lines.append({"requirement_id": row.id, "qty": part, "pairs": pair_count})

    qr = _lock_free_qr(db, tenant_id)
    prep = MaterialPrep(
        tenant_id=tenant_id,
        doc_no=f"BL{secrets.token_hex(4).upper()}",
        header_id=header.id,
        header_no=header.header_no,
        pairs=pair_count,
        qr_id=qr.id,
        status="pending",
        created_by=user_id,
        lines=prep_lines,
    )
    db.add(prep)
    db.flush()

    if issue_lines:
        from app.services.stock_doc_service import confirm_stock_doc, submit_stock_doc, void_stock_doc

        try:
            pending = submit_stock_doc(
                db,
                tenant_id,
                doc_type="issue",
                header_id=header.id,
                lines=issue_lines,
                notes=f"备料 {header.header_no} {pair_count}双",
                user_id=user_id,
            )
        except MaterialError as exc:
            db.rollback()
            raise MaterialPrepError(exc.code, exc.message) from exc
        prep.stock_doc_id = int(pending["id"])
        db.commit()
        try:
            confirm_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
        except MaterialError as exc:
            db.rollback()
            try:
                void_stock_doc(db, tenant_id, int(pending["id"]), user_id=user_id)
            except MaterialError:
                db.rollback()
            failed = db.get(MaterialPrep, prep.id)
            if failed and failed.status == "pending":
                failed.status = "cancelled"
                db.commit()
            raise MaterialPrepError(exc.code, exc.message) from exc
    else:
        db.commit()

    saved = _load(db, tenant_id, prep.id)
    if saved.stock_doc_id:
        record_prep_pickup(db, tenant_id, saved)
        db.commit()
    return _slip_dict(db, saved, with_qr=True, origin=origin)


def _naive_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def record_prep_pickup(db: Session, tenant_id: int, prep: MaterialPrep) -> bool:
    """把已过账的备料写进领退记录。库存仍只走备料出库单，这里不再扣一次。"""
    if not prep.stock_doc_id or prep.status == "cancelled":
        return False
    exists = db.scalar(
        select(WarehousePickup.id).where(
            WarehousePickup.tenant_id == tenant_id,
            WarehousePickup.stock_doc_id == prep.stock_doc_id,
            WarehousePickup.kind == WarehousePickupKind.prep,
        )
    )
    if exists:
        return False
    doc = db.get(StockDoc, prep.stock_doc_id)
    if not doc or doc.tenant_id != tenant_id or doc.status == StockDocStatus.void:
        return False
    lines: list[WarehousePickupLine] = []
    for line in prep.lines or []:
        qty = _money(_dec(line.actual_qty))
        if line.customer_supplied or qty <= 0:
            continue
        lines.append(
            WarehousePickupLine(
                tenant_id=tenant_id,
                supplier_product_id=int(line.supplier_product_id),
                material_name=(line.material_name or "")[:100],
                material_code=line.material_code,
                unit_name=line.unit_name,
                qty=qty,
            )
        )
    if not lines:
        return False
    db.add(
        WarehousePickup(
            tenant_id=tenant_id,
            doc_no=doc.doc_no,
            kind=WarehousePickupKind.prep,
            status=WarehousePickupStatus.signed,
            header_id=prep.header_id,
            header_no=prep.header_no,
            order_id=doc.order_id,
            stock_doc_id=doc.id,
            notes=(doc.notes or f"备料 {prep.header_no} {prep.pairs}双")[:255],
            picker_employee_id=prep.picker_employee_id,
            picker_name=prep.picker_name,
            signed_at=_naive_utc(prep.signed_at or doc.posted_at),
            created_by=prep.created_by,
            lines=lines,
        )
    )
    return True


def sync_prep_pickups(db: Session, tenant_id: int) -> None:
    """补上已经备过、但领退记录里还没有的单。"""
    preps = db.scalars(
        select(MaterialPrep)
        .where(
            MaterialPrep.tenant_id == tenant_id,
            MaterialPrep.stock_doc_id.is_not(None),
            MaterialPrep.status.in_(("pending", "signed")),
        )
        .options(selectinload(MaterialPrep.lines))
    ).all()
    wrote = False
    for prep in preps:
        wrote = record_prep_pickup(db, tenant_id, prep) or wrote
    if wrote:
        db.commit()


def _touch_prep_pickup(db: Session, tenant_id: int, prep: MaterialPrep) -> None:
    if not prep.stock_doc_id:
        return
    row = db.scalar(
        select(WarehousePickup).where(
            WarehousePickup.tenant_id == tenant_id,
            WarehousePickup.stock_doc_id == prep.stock_doc_id,
            WarehousePickup.kind == WarehousePickupKind.prep,
        )
    )
    if not row:
        return
    if prep.status == "cancelled":
        row.status = WarehousePickupStatus.cancelled
        return
    row.picker_employee_id = prep.picker_employee_id
    row.picker_name = prep.picker_name
    if prep.signed_at:
        row.signed_at = _naive_utc(prep.signed_at)


def _load(db: Session, tenant_id: int, prep_id: int) -> MaterialPrep:
    row = db.scalar(
        select(MaterialPrep)
        .where(MaterialPrep.id == prep_id, MaterialPrep.tenant_id == tenant_id)
        .options(selectinload(MaterialPrep.lines))
    )
    if not row:
        raise MaterialPrepError("not_found", "备料单不存在")
    return row


def _return_issued_to_occupied(db: Session, tenant_id: int, prep: MaterialPrep, user_id: int | None) -> None:
    """取消占用：已扣数量退回仓库，并扣回车间存量。"""
    if not prep.stock_doc_id:
        return
    from app.models import StockDoc, StockDocStatus
    from app.services.purchase_demand_service import adjust_workshop_count

    doc = db.scalar(
        select(StockDoc)
        .where(StockDoc.id == prep.stock_doc_id, StockDoc.tenant_id == tenant_id)
        .options(selectinload(StockDoc.lines))
    )
    if not doc or doc.status == StockDocStatus.void:
        return
    if doc.status != StockDocStatus.posted:
        doc.status = StockDocStatus.void
        return
    for line in doc.lines:
        row = db.get(OrderMaterialRequirement, line.order_material_requirement_id)
        if not row or row.tenant_id != tenant_id:
            raise MaterialPrepError("not_found", "用料行不存在")
        qty = _money(_dec(line.qty))
        issued = _dec(row.issued_qty)
        if qty > issued:
            raise MaterialPrepError("exceed_issued", "已发数量不够退回占用量")
        row.issued_qty = _money(issued - qty)
        size_id = int(row.size_id) if getattr(row, "usage_by_size", False) and row.size_id else None
        header_id = int(row.header_id or prep.header_id)
        adjust_workshop_count(
            db,
            tenant_id,
            header_id=header_id,
            supplier_product_id=int(row.supplier_product_id),
            size_id=size_id,
            delta=-qty,
            user_id=user_id,
        )
    db.flush()
    # 备料扣库时从公用库存划走的数量，取消后加回仓库并记一笔流水。
    # 只退当初划走的部分；本来就在这张单占用里的数量，不加进公用库存。
    taken = db.scalars(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.tenant_id == tenant_id,
            SharedMaterialLedger.ref_id == doc.id,
            SharedMaterialLedger.ref_type.in_(("stock_doc_issue_alloc", "stock_doc_issue")),
            SharedMaterialLedger.ledger_type.in_((SharedLedgerType.allocate_to_order, SharedLedgerType.prep)),
        )
    ).all()
    pool_back: dict[tuple[int, int | None], Decimal] = {}
    for item in taken:
        if item.qty_delta >= 0:
            continue
        key = (int(item.supplier_product_id), item.size_id)
        pool_back[key] = pool_back.get(key, Decimal("0")) + (-_dec(item.qty_delta))
    lines_by_key: dict[tuple[int, int | None], list[OrderMaterialRequirement]] = {}
    for line in doc.lines:
        row = db.get(OrderMaterialRequirement, line.order_material_requirement_id)
        if not row:
            continue
        size_id = int(row.size_id) if getattr(row, "usage_by_size", False) and row.size_id else None
        lines_by_key.setdefault((int(row.supplier_product_id), size_id), []).append(row)
    for key, qty in pool_back.items():
        if qty <= 0:
            continue
        left = qty
        for row in lines_by_key.get(key, []):
            if left <= 0:
                break
            spare = _dec(row.arrived_qty) - _dec(row.issued_qty)
            take = min(left, spare) if spare > 0 else Decimal("0")
            if take <= 0:
                continue
            row.arrived_qty = _money(_dec(row.arrived_qty) - take)
            left -= take
        product_id, size_id = key
        adjust_shared_stock(
            db,
            tenant_id,
            product_id,
            qty,
            size_id=size_id,
            ledger_type=SharedLedgerType.prep_cancel,
            ref_type="material_prep",
            ref_id=prep.id,
            user_id=user_id,
            note="取消备料占用，数量退回仓库",
        )
    note = "取消占用，数量退回仓库"
    doc.notes = f"{doc.notes}；{note}"[:255] if doc.notes else note
    doc.status = StockDocStatus.void


def release_qr(db: Session, tenant_id: int, slot: int, user_id: int | None = None) -> dict:
    qr = db.scalar(
        select(MaterialPrepQr)
        .where(MaterialPrepQr.tenant_id == tenant_id, MaterialPrepQr.slot == int(slot))
        .with_for_update()
    )
    if not qr:
        raise MaterialPrepError("not_found", "备料码不存在")
    prep = db.scalar(
        select(MaterialPrep)
        .where(
            MaterialPrep.tenant_id == tenant_id,
            MaterialPrep.qr_id == qr.id,
            MaterialPrep.status == "pending",
        )
        .options(selectinload(MaterialPrep.lines))
        .order_by(MaterialPrep.id.desc())
        .limit(1)
        .with_for_update()
    )
    if not prep:
        raise MaterialPrepError("not_occupied", "这张备料码没有占用")
    _return_issued_to_occupied(db, tenant_id, prep, user_id)
    prep.status = "cancelled"
    _touch_prep_pickup(db, tenant_id, prep)
    db.commit()
    return {"slot": int(qr.slot), "occupied": False}


def get_by_token(db: Session, tenant_id: int, token: str) -> dict:
    text = (token or "").strip()
    qr = db.scalar(select(MaterialPrepQr).where(MaterialPrepQr.token == text))
    if not qr or qr.tenant_id != tenant_id:
        raise MaterialPrepError("not_found", "备料码不存在")
    row = db.scalar(
        select(MaterialPrep)
        .where(MaterialPrep.tenant_id == tenant_id, MaterialPrep.qr_id == qr.id)
        .options(selectinload(MaterialPrep.lines))
        .order_by(MaterialPrep.id.desc())
        .limit(1)
    )
    if not row:
        raise MaterialPrepError("not_bound", "这张备料码还没有绑定物料")
    return _slip_dict(db, row)


def sign_prep(db: Session, tenant_id: int, token: str, employee: Employee) -> dict:
    if not employee.is_active or employee.tenant_id != tenant_id:
        raise MaterialPrepError("picker_not_found", "找不到这位领料人")
    text = (token or "").strip()
    qr = db.scalar(
        select(MaterialPrepQr).where(MaterialPrepQr.token == text).with_for_update()
    )
    if not qr or qr.tenant_id != tenant_id:
        raise MaterialPrepError("not_found", "备料码不存在")
    row = db.scalar(
        select(MaterialPrep)
        .where(
            MaterialPrep.tenant_id == tenant_id,
            MaterialPrep.qr_id == qr.id,
            MaterialPrep.status == "pending",
        )
        .options(selectinload(MaterialPrep.lines))
        .order_by(MaterialPrep.id.desc())
        .limit(1)
    )
    if not row:
        latest = db.scalar(
            select(MaterialPrep)
            .where(MaterialPrep.tenant_id == tenant_id, MaterialPrep.qr_id == qr.id)
            .options(selectinload(MaterialPrep.lines))
            .order_by(MaterialPrep.id.desc())
            .limit(1)
        )
        if latest and latest.status == "signed":
            raise MaterialPrepError("already_signed", "这张备料已经确认过领料人")
        raise MaterialPrepError("not_bound", "这张备料码还没有绑定物料")
    row.status = "signed"
    row.picker_employee_id = employee.id
    row.picker_name = employee.name
    row.signed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_prep_pickup(db, tenant_id, row)
    _touch_prep_pickup(db, tenant_id, row)
    db.commit()
    saved = _load(db, tenant_id, row.id)
    return _slip_dict(db, saved)
