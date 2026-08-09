"""B2d：来料 IQC — 待检/合格/不合格/让步；合格或让步后才入池与齐套。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MaterialIqcRecord,
    MaterialIqcStatus,
    OrderMaterialRequirement,
    PurchaseOrder,
    PurchaseOrderLine,
    SharedLedgerType,
    Size,
    SupplierProduct,
)
from app.services.material_service import adjust_shared_stock


class IqcError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _record_out(db: Session, rec: MaterialIqcRecord) -> dict[str, Any]:
    sp = db.get(SupplierProduct, rec.supplier_product_id)
    size = db.get(Size, rec.size_id) if rec.size_id else None
    po = db.get(PurchaseOrder, rec.purchase_order_id)
    return {
        "id": rec.id,
        "purchase_order_id": rec.purchase_order_id,
        "po_no": po.po_no if po else None,
        "purchase_order_line_id": rec.purchase_order_line_id,
        "supplier_product_id": rec.supplier_product_id,
        "supplier_product_code": sp.product_code if sp else None,
        "supplier_product_name": sp.name if sp else None,
        "size_id": rec.size_id,
        "size_value": size.size_value if size else None,
        "order_id": rec.order_id,
        "order_material_requirement_id": rec.order_material_requirement_id,
        "qty": float(rec.qty),
        "unit_price": float(rec.unit_price) if rec.unit_price is not None else None,
        "status": _enum_val(rec.status),
        "note": rec.note,
        "created_at": rec.created_at.isoformat(timespec="seconds") if rec.created_at else None,
        "decided_at": rec.decided_at.isoformat(timespec="seconds") if rec.decided_at else None,
    }


def list_iqc(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = None,
    purchase_order_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = select(MaterialIqcRecord).where(MaterialIqcRecord.tenant_id == tenant_id)
    if status:
        q = q.where(MaterialIqcRecord.status == status)
    if purchase_order_id:
        q = q.where(MaterialIqcRecord.purchase_order_id == purchase_order_id)
    q = q.order_by(MaterialIqcRecord.id.desc()).limit(min(limit, 200))
    return [_record_out(db, r) for r in db.scalars(q).all()]


def create_pending_from_receive(
    db: Session,
    tenant_id: int,
    po: PurchaseOrder,
    line: PurchaseOrderLine,
    qty: Decimal,
    *,
    user_id: int | None = None,
) -> MaterialIqcRecord:
    rec = MaterialIqcRecord(
        tenant_id=tenant_id,
        purchase_order_id=po.id,
        purchase_order_line_id=line.id,
        supplier_product_id=line.supplier_product_id,
        size_id=getattr(line, "size_id", None),
        order_id=line.order_id,
        order_material_requirement_id=line.order_material_requirement_id,
        qty=qty,
        unit_price=line.unit_price,
        status=MaterialIqcStatus.pending,
        created_by=user_id,
    )
    db.add(rec)
    db.flush()
    return rec


def _post_to_pool(
    db: Session,
    tenant_id: int,
    rec: MaterialIqcRecord,
    *,
    user_id: int | None,
    auto_allocate: bool,
    note_suffix: str,
) -> None:
    po = db.get(PurchaseOrder, rec.purchase_order_id)
    ln = db.get(PurchaseOrderLine, rec.purchase_order_line_id)
    if not po or not ln:
        raise IqcError("not_found", "采购行不存在")

    qty = Decimal(str(rec.qty))
    open_qty = max(Decimal("0"), ln.qty - (ln.received_qty or Decimal("0")))
    alloc_cap = open_qty
    ln.received_qty = (ln.received_qty or Decimal("0")) + qty

    adjust_shared_stock(
        db,
        tenant_id,
        rec.supplier_product_id,
        qty,
        size_id=rec.size_id,
        unit_cost=rec.unit_price,
        ledger_type=SharedLedgerType.unallocated_receive,
        ref_type="iqc_receive",
        ref_id=rec.id,
        order_id=rec.order_id,
        user_id=user_id,
        note=f"PO {po.po_no} IQC{note_suffix}入池",
    )

    if auto_allocate and rec.order_material_requirement_id and alloc_cap > 0:
        req = db.get(OrderMaterialRequirement, rec.order_material_requirement_id)
        if req:
            alloc = min(qty, alloc_cap)
            if alloc > 0:
                adjust_shared_stock(
                    db,
                    tenant_id,
                    rec.supplier_product_id,
                    -alloc,
                    size_id=rec.size_id,
                    unit_cost=rec.unit_price,
                    ledger_type=SharedLedgerType.allocate_to_order,
                    ref_type="iqc_allocate",
                    ref_id=rec.id,
                    order_id=rec.order_id,
                    user_id=user_id,
                    note=f"PO {po.po_no} IQC后自动分配",
                )
                req.arrived_qty = (req.arrived_qty or Decimal("0")) + alloc

    total_recv = sum((ln.received_qty or Decimal("0") for ln in po.lines), Decimal("0"))
    if total_recv > 0 and all((x.received_qty or 0) >= x.qty for x in po.lines):
        from app.models import PurchaseOrderStatus

        po.status = PurchaseOrderStatus.received
    elif total_recv > 0:
        from app.models import PurchaseOrderStatus

        if po.status not in (PurchaseOrderStatus.received,):
            po.status = PurchaseOrderStatus.partial_received

    from app.services.ap_service import create_payable_for_receive

    create_payable_for_receive(
        db,
        tenant_id,
        po,
        [{"line_id": ln.id, "qty": float(qty)}],
    )


def decide_iqc(
    db: Session,
    tenant_id: int,
    record_id: int,
    *,
    decision: str,
    note: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """decision: pass | fail | concede"""
    from app.services.inventory_settings import get_inventory_by_tenant_id

    rec = db.scalar(
        select(MaterialIqcRecord).where(
            MaterialIqcRecord.tenant_id == tenant_id,
            MaterialIqcRecord.id == record_id,
        )
    )
    if not rec:
        raise IqcError("not_found", "IQC 记录不存在")
    if _enum_val(rec.status) != MaterialIqcStatus.pending.value:
        raise IqcError("already_decided", "已判定，不能重复操作")

    decision = (decision or "").strip().lower()
    if decision in ("pass", "passed", "ok"):
        new_status = MaterialIqcStatus.passed
        post = True
        suffix = "合格"
    elif decision in ("concede", "conceded", "concession"):
        new_status = MaterialIqcStatus.conceded
        post = True
        suffix = "让步"
    elif decision in ("fail", "failed", "reject"):
        new_status = MaterialIqcStatus.failed
        post = False
        suffix = "不合格"
    else:
        raise IqcError("invalid_decision", "判定须为 pass / fail / concede")

    rec.status = new_status
    rec.note = note
    rec.decided_by = user_id
    rec.decided_at = datetime.utcnow()

    if post:
        inv = get_inventory_by_tenant_id(db, tenant_id)
        auto_allocate = bool(inv.get("auto_allocate_on_receive", True))
        _post_to_pool(
            db,
            tenant_id,
            rec,
            user_id=user_id,
            auto_allocate=auto_allocate,
            note_suffix=suffix,
        )

    db.commit()
    db.refresh(rec)
    return _record_out(db, rec)
