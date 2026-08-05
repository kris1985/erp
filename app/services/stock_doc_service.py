"""领退料单：强制领料模式下占用↔已发，退料回池。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    SharedLedgerType,
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
    SupplierProduct,
)
from app.services.inventory_settings import get_inventory_by_tenant_id, has_capability
from app.services.material_service import MaterialError, adjust_shared_stock, build_kit_context


def _gen_doc_no(db: Session, tenant_id: int, doc_type: StockDocType) -> str:
    prefix = "SI" if doc_type == StockDocType.issue else "SR"
    day = date.today().strftime("%y%m%d")
    like = f"{prefix}{day}%"
    n = (
        db.scalar(
            select(func.count())
            .select_from(StockDoc)
            .where(StockDoc.tenant_id == tenant_id, StockDoc.doc_no.like(like))
        )
        or 0
    )
    return f"{prefix}{day}{int(n) + 1:03d}"


def _doc_out(db: Session, doc: StockDoc) -> dict:
    order = db.get(Order, doc.order_id)
    lines = []
    for ln in doc.lines:
        sp = db.get(SupplierProduct, ln.supplier_product_id)
        lines.append(
            {
                "id": ln.id,
                "order_material_requirement_id": ln.order_material_requirement_id,
                "supplier_product_id": ln.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "qty": ln.qty,
                "unit_cost": ln.unit_cost,
            }
        )
    return {
        "id": doc.id,
        "doc_no": doc.doc_no,
        "doc_type": doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "order_id": doc.order_id,
        "order_no": order.order_no if order else None,
        "notes": doc.notes,
        "posted_at": doc.posted_at,
        "created_at": doc.created_at,
        "lines": lines,
    }


def assert_issue_gate(db: Session, tenant_id: int, order: Order) -> None:
    """强制领料闸门：有物料需求的在制单，关键料须已领过（issued>0）。"""
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not has_capability(inv, "issue_gate") and not inv.get("issue_required"):
        return
    if order.status == OrderStatus.cancelled:
        return
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.order_id == order.id,
        )
    ).all()
    missing: list[str] = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        required = row.required_qty or Decimal("0")
        if required <= 0:
            continue
        issued = row.issued_qty or Decimal("0")
        if issued <= 0:
            sp = db.get(SupplierProduct, row.supplier_product_id)
            missing.append(sp.product_code if sp else str(row.supplier_product_id))
    if missing:
        raise MaterialError(
            "issue_required",
            f"请先领料再报工：{('、'.join(missing[:5]))}"
            + ("…" if len(missing) > 5 else ""),
        )


def create_and_post_stock_doc(
    db: Session,
    tenant_id: int,
    *,
    doc_type: str,
    order_id: int,
    lines: list[dict],
    notes: str | None = None,
    user_id: int | None = None,
) -> dict:
    """lines: [{requirement_id, qty}]，创建即过账。"""
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not has_capability(inv, "stock_docs") and not inv.get("issue_required"):
        raise MaterialError("capability_disabled", "未开通领退料单")

    try:
        dtype = StockDocType(doc_type)
    except ValueError as e:
        raise MaterialError("invalid_type", "单据类型无效") from e
    if dtype not in (StockDocType.issue, StockDocType.return_mat):
        raise MaterialError("invalid_type", "单据类型无效")
    if not lines:
        raise MaterialError("empty_lines", "请填写明细")

    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    if order.status == OrderStatus.cancelled:
        raise MaterialError("order_cancelled", "已取消订单不能领退料")

    doc = StockDoc(
        tenant_id=tenant_id,
        doc_no=_gen_doc_no(db, tenant_id, dtype),
        doc_type=dtype,
        status=StockDocStatus.posted,
        order_id=order_id,
        notes=notes,
        created_by=user_id,
        posted_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.flush()

    for item in lines:
        req_id = int(item["requirement_id"])
        qty = Decimal(str(item["qty"]))
        if qty <= 0:
            raise MaterialError("invalid_qty", "数量须大于 0")
        row = db.get(OrderMaterialRequirement, req_id)
        if not row or row.tenant_id != tenant_id or row.order_id != order_id:
            raise MaterialError("not_found", f"用料行不存在: {req_id}")
        if row.is_customer_supplied:
            raise MaterialError("customer_supplied", "客供料不走领退料单")

        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")

        if dtype == StockDocType.issue:
            available = max(Decimal("0"), arrived - issued)
            if qty > available:
                raise MaterialError(
                    "exceed_available",
                    f"可领不足（已占用 {arrived}，已发 {issued}，可领 {available}）",
                )
            row.issued_qty = issued + qty
        else:
            if qty > issued:
                raise MaterialError("exceed_issued", f"退料不能超过已发 {issued}")
            # 退料回池：减已发、减占用、加池
            row.issued_qty = issued - qty
            row.arrived_qty = arrived - qty
            adjust_shared_stock(
                db,
                tenant_id,
                row.supplier_product_id,
                qty,
                unit_cost=row.unit_price,
                ledger_type=SharedLedgerType.release_from_order,
                ref_type="stock_doc_return",
                ref_id=doc.id,
                order_id=order_id,
                user_id=user_id,
                note=f"退料单 {doc.doc_no}",
            )

        db.add(
            StockDocLine(
                tenant_id=tenant_id,
                stock_doc_id=doc.id,
                order_material_requirement_id=req_id,
                supplier_product_id=row.supplier_product_id,
                qty=qty,
                unit_cost=row.unit_price,
            )
        )

    db.commit()
    doc = db.scalar(
        select(StockDoc)
        .where(StockDoc.id == doc.id)
        .options(selectinload(StockDoc.lines))
    )
    return _doc_out(db, doc)  # type: ignore[arg-type]


def list_stock_docs(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    doc_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    q = (
        select(StockDoc)
        .where(StockDoc.tenant_id == tenant_id)
        .options(selectinload(StockDoc.lines))
        .order_by(StockDoc.id.desc())
        .limit(min(limit, 200))
    )
    if order_id:
        q = q.where(StockDoc.order_id == order_id)
    if doc_type:
        q = q.where(StockDoc.doc_type == StockDocType(doc_type))
    return [_doc_out(db, d) for d in db.scalars(q).all()]


def list_issue_candidates(db: Session, tenant_id: int, order_id: int) -> list[dict]:
    """某单可领/可退数量。"""
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    ctx = build_kit_context(db, tenant_id, include_shared=True)
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.order_id == order_id,
        )
    ).all()
    out = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        d = ctx.row_dict(row)
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        d["issuable_qty"] = max(Decimal("0"), arrived - issued)
        d["returnable_qty"] = max(Decimal("0"), issued)
        out.append(d)
    return out
