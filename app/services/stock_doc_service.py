"""领退料单：车间提报 → 仓管确认过账；同一订单可多次领/退。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    SharedLedgerType,
    SpecExecutionStatus,
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
    SupplierProduct,
)
from app.services.inventory_settings import get_inventory_by_tenant_id, has_capability
from app.services.material_service import (
    MaterialError,
    _shared_qty,
    adjust_shared_stock,
    allocate_from_pool,
    build_kit_context,
)


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


def _owner_filters(*, order_id: int | None = None, header_id: int | None = None) -> list:
    if header_id:
        return [StockDoc.header_id == header_id]
    if order_id:
        return [StockDoc.order_id == order_id]
    return []


def _issue_seq_for_owner(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    header_id: int | None = None,
    before_doc_id: int | None = None,
) -> int:
    """非作废领料单序号（含待确认），用于首领/补领标签。"""
    q = (
        select(func.count())
        .select_from(StockDoc)
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == StockDocType.issue,
            StockDoc.status != StockDocStatus.void,
            *_owner_filters(order_id=order_id, header_id=header_id),
        )
    )
    if before_doc_id is not None:
        q = q.where(StockDoc.id < before_doc_id)
    return int(db.scalar(q) or 0)


def _pending_qty_map(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    header_id: int | None = None,
    doc_type: StockDocType,
) -> dict[int, Decimal]:
    """待确认单中，按用料行汇总已占用的申请数量。"""
    rows = db.execute(
        select(StockDocLine.order_material_requirement_id, func.coalesce(func.sum(StockDocLine.qty), 0))
        .join(StockDoc, StockDoc.id == StockDocLine.stock_doc_id)
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == doc_type,
            StockDoc.status == StockDocStatus.pending,
            *_owner_filters(order_id=order_id, header_id=header_id),
        )
        .group_by(StockDocLine.order_material_requirement_id)
    ).all()
    return {int(rid): Decimal(str(qty)) for rid, qty in rows if rid is not None}


def _doc_out(db: Session, doc: StockDoc) -> dict:
    order = db.get(Order, doc.order_id) if doc.order_id else None
    header = db.get(ExecutionHeader, doc.header_id) if getattr(doc, "header_id", None) else None
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
                "image_url": sp.image_url if sp else None,
                "qty": ln.qty,
                "unit_cost": ln.unit_cost,
            }
        )
    doc_type = doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type
    status = doc.status.value if hasattr(doc.status, "value") else doc.status
    issue_kind = None
    issue_seq = None
    if doc_type == "issue" or doc.doc_type == StockDocType.issue:
        prior = _issue_seq_for_owner(
            db,
            doc.tenant_id,
            order_id=doc.order_id,
            header_id=getattr(doc, "header_id", None),
            before_doc_id=doc.id,
        )
        issue_seq = prior + 1
        issue_kind = "首领" if issue_seq == 1 else f"补领#{issue_seq}"
    return {
        "id": doc.id,
        "doc_no": doc.doc_no,
        "doc_type": doc_type,
        # 方向：退料=入库，领料=出库（后续采购入库等同 in）
        "direction": "in" if doc_type == "return_mat" else "out",
        "issue_kind": issue_kind,
        "issue_seq": issue_seq,
        "status": status,
        "order_id": doc.order_id,
        "execution_id": getattr(doc, "execution_id", None),
        "header_id": getattr(doc, "header_id", None),
        "order_no": order.order_no if order else None,
        "header_no": header.header_no if header else None,
        "notes": doc.notes,
        "posted_at": doc.posted_at,
        "created_at": doc.created_at,
        "created_by": doc.created_by,
        "lines": lines,
    }


def _load_doc(db: Session, tenant_id: int, doc_id: int) -> StockDoc:
    doc = db.scalar(
        select(StockDoc)
        .where(StockDoc.id == doc_id, StockDoc.tenant_id == tenant_id)
        .options(selectinload(StockDoc.lines))
    )
    if not doc:
        raise MaterialError("not_found", "单据不存在")
    return doc


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


def assert_issue_gate_for_header(db: Session, tenant_id: int, header_id: int) -> None:
    """K4-B：无桥接壳时按 header 用料行做领料闸门。"""
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not has_capability(inv, "issue_gate") and not inv.get("issue_required"):
        return
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.header_id == header_id,
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


def _assert_cap(db: Session, tenant_id: int) -> None:
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not has_capability(inv, "stock_docs") and not inv.get("issue_required"):
        raise MaterialError("capability_disabled", "未开通领退料")


def _prepare_lines(
    db: Session,
    tenant_id: int,
    dtype: StockDocType,
    lines: list[dict],
    *,
    order_id: int | None = None,
    header_id: int | None = None,
    pending_extra: dict[int, Decimal] | None = None,
) -> list[tuple[OrderMaterialRequirement, Decimal]]:
    pending_map = (
        pending_extra
        if pending_extra is not None
        else _pending_qty_map(db, tenant_id, order_id=order_id, header_id=header_id, doc_type=dtype)
    )
    prepared: list[tuple[OrderMaterialRequirement, Decimal]] = []
    for item in lines:
        req_id = int(item["requirement_id"])
        qty = Decimal(str(item["qty"]))
        if qty <= 0:
            raise MaterialError("invalid_qty", "数量须大于 0")
        row = db.get(OrderMaterialRequirement, req_id)
        if not row or row.tenant_id != tenant_id:
            raise MaterialError("not_found", f"用料行不存在: {req_id}")
        if order_id is not None:
            if row.order_id != order_id:
                raise MaterialError("not_found", f"用料行不存在: {req_id}")
        elif header_id is not None:
            if int(row.header_id or 0) != int(header_id):
                raise MaterialError("not_found", f"用料行不存在: {req_id}")
        else:
            raise MaterialError("missing_ref", "请指定执行单或生产单")
        if row.is_customer_supplied:
            raise MaterialError("customer_supplied", "客供料不走领退料单")

        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        pending_qty = pending_map.get(req_id, Decimal("0"))

        if dtype == StockDocType.issue:
            available = max(Decimal("0"), arrived - issued)
            pool = _shared_qty(db, tenant_id, row.supplier_product_id)
            headroom = available + pool - pending_qty
            if qty > headroom:
                sp = db.get(SupplierProduct, row.supplier_product_id)
                code = sp.product_code if sp else str(row.supplier_product_id)
                raise MaterialError(
                    "pool_insufficient",
                    f"{code} 库存不足（占用可发 {available}，池 {pool}，待确认 {pending_qty}，本次 {qty}）",
                )
        else:
            returnable = max(Decimal("0"), issued - pending_qty)
            if qty > returnable:
                raise MaterialError(
                    "exceed_issued",
                    f"退料不能超过可退 {returnable}（已发 {issued}，待确认退 {pending_qty}）",
                )
        prepared.append((row, qty))
    return prepared


def submit_stock_doc(
    db: Session,
    tenant_id: int,
    *,
    doc_type: str,
    lines: list[dict],
    order_id: int | None = None,
    header_id: int | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict:
    """车间提报：生成待确认单据，不改库存。K4-F 认 header_id（无壳）。"""
    _assert_cap(db, tenant_id)
    try:
        dtype = StockDocType(doc_type)
    except ValueError as e:
        raise MaterialError("invalid_type", "单据类型无效") from e
    if dtype not in (StockDocType.issue, StockDocType.return_mat):
        raise MaterialError("invalid_type", "单据类型无效")
    if not lines:
        raise MaterialError("empty_lines", "请填写明细")

    from app.services.material_service import resolve_execution_id_for_order, resolve_header_for_order

    header: ExecutionHeader | None = None
    order: Order | None = None
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise MaterialError("header_not_found", "执行单不存在")
        if header.status == SpecExecutionStatus.cancelled:
            raise MaterialError("header_cancelled", "已取消执行单不能领退料")
        order_id = header.shop_order_id
        if order_id:
            order = db.get(Order, order_id)
    elif order_id:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise MaterialError("order_not_found", "订单不存在")
        if order.status == OrderStatus.cancelled:
            raise MaterialError("order_cancelled", "已取消订单不能领退料")
        header = resolve_header_for_order(db, tenant_id, order_id)
        header_id = header.id if header else None
    else:
        raise MaterialError("missing_ref", "请指定执行单或生产单")

    if order and order.status == OrderStatus.cancelled:
        raise MaterialError("order_cancelled", "已取消订单不能领退料")

    prior_issues = _issue_seq_for_owner(
        db, tenant_id, order_id=order_id, header_id=header_id
    )
    final_notes = notes
    if dtype == StockDocType.issue and prior_issues > 0 and not (notes or "").strip():
        final_notes = f"补领#{prior_issues + 1}"
    elif dtype == StockDocType.issue and prior_issues > 0 and notes and "补领" not in notes:
        final_notes = f"补领#{prior_issues + 1} · {notes}"

    prepared = _prepare_lines(
        db, tenant_id, dtype, lines, order_id=order_id, header_id=header_id
    )

    exe_id = None
    if order_id:
        exe_id = resolve_execution_id_for_order(db, tenant_id, order_id)

    doc = StockDoc(
        tenant_id=tenant_id,
        doc_no=_gen_doc_no(db, tenant_id, dtype),
        doc_type=dtype,
        status=StockDocStatus.pending,
        order_id=order_id,
        execution_id=exe_id,
        header_id=header_id,
        notes=final_notes,
        created_by=user_id,
        posted_at=None,
    )
    db.add(doc)
    db.flush()

    for row, qty in prepared:
        db.add(
            StockDocLine(
                tenant_id=tenant_id,
                stock_doc_id=doc.id,
                order_material_requirement_id=row.id,
                supplier_product_id=row.supplier_product_id,
                qty=qty,
                unit_cost=row.unit_price,
            )
        )

    db.commit()
    return _doc_out(db, _load_doc(db, tenant_id, doc.id))


def confirm_stock_doc(
    db: Session,
    tenant_id: int,
    doc_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """仓管确认：过账扣发/退回，状态变已过账。"""
    _assert_cap(db, tenant_id)
    doc = _load_doc(db, tenant_id, doc_id)
    if doc.status != StockDocStatus.pending:
        raise MaterialError("invalid_status", "仅待确认单据可过账")

    dtype = doc.doc_type
    owner_order_id = doc.order_id
    owner_header_id = getattr(doc, "header_id", None)

    if owner_order_id:
        order = db.get(Order, owner_order_id)
        if not order or order.tenant_id != tenant_id:
            raise MaterialError("order_not_found", "订单不存在")
        if order.status == OrderStatus.cancelled:
            raise MaterialError("order_cancelled", "已取消订单不能过账")
    elif owner_header_id:
        header = db.get(ExecutionHeader, owner_header_id)
        if not header or header.tenant_id != tenant_id:
            raise MaterialError("header_not_found", "执行单不存在")
        if header.status == SpecExecutionStatus.cancelled:
            raise MaterialError("header_cancelled", "已取消执行单不能过账")
    else:
        raise MaterialError("missing_ref", "单据未关联执行单或生产单")

    # 确认时不计本单自己的 pending（即将过账）
    pending_map = _pending_qty_map(
        db, tenant_id, order_id=owner_order_id, header_id=owner_header_id, doc_type=dtype
    )
    for ln in doc.lines:
        rid = ln.order_material_requirement_id
        if rid is not None:
            pending_map[rid] = max(Decimal("0"), pending_map.get(rid, Decimal("0")) - Decimal(str(ln.qty)))

    prepared = _prepare_lines(
        db,
        tenant_id,
        dtype,
        [{"requirement_id": ln.order_material_requirement_id, "qty": ln.qty} for ln in doc.lines],
        order_id=owner_order_id,
        header_id=owner_header_id,
        pending_extra=pending_map,
    )

    from app.services.material_service import allocate_from_pool_for_header

    for row, qty in prepared:
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")

        if dtype == StockDocType.issue:
            available = max(Decimal("0"), arrived - issued)
            if qty > available:
                need_alloc = qty - available
                if owner_header_id and not owner_order_id:
                    allocate_from_pool_for_header(
                        db,
                        tenant_id,
                        int(owner_header_id),
                        row.id,
                        need_alloc,
                        user_id=user_id,
                        commit=False,
                        ref_type="stock_doc_issue_alloc",
                        ref_id=doc.id,
                        note=f"领料自动归属 {doc.doc_no}",
                    )
                else:
                    allocate_from_pool(
                        db,
                        tenant_id,
                        owner_order_id,
                        row.id,
                        need_alloc,
                        user_id=user_id,
                        commit=False,
                        ref_type="stock_doc_issue_alloc",
                        ref_id=doc.id,
                        note=f"领料自动归属 {doc.doc_no}",
                    )
                db.refresh(row)
                arrived = row.arrived_qty or Decimal("0")
                issued = row.issued_qty or Decimal("0")
                available = max(Decimal("0"), arrived - issued)
            if qty > available:
                raise MaterialError(
                    "exceed_available",
                    f"库存不足（已占用 {arrived}，已发 {issued}，本次可用 {available}）",
                )
            row.issued_qty = issued + qty
        else:
            row.issued_qty = issued - qty
            row.arrived_qty = arrived - qty
            adjust_shared_stock(
                db,
                tenant_id,
                row.supplier_product_id,
                qty,
                size_id=row.size_id if getattr(row, "usage_by_size", False) else None,
                unit_cost=row.unit_price,
                ledger_type=SharedLedgerType.release_from_order,
                ref_type="stock_doc_return",
                ref_id=doc.id,
                order_id=owner_order_id,
                user_id=user_id,
                note=f"退料单 {doc.doc_no}",
            )

    doc.status = StockDocStatus.posted
    doc.posted_at = datetime.now(timezone.utc)
    db.commit()
    return _doc_out(db, _load_doc(db, tenant_id, doc.id))


def void_stock_doc(
    db: Session,
    tenant_id: int,
    doc_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """作废待确认单（未过账）。"""
    _assert_cap(db, tenant_id)
    doc = _load_doc(db, tenant_id, doc_id)
    if doc.status != StockDocStatus.pending:
        raise MaterialError("invalid_status", "仅待确认单据可作废")
    doc.status = StockDocStatus.void
    db.commit()
    return _doc_out(db, _load_doc(db, tenant_id, doc.id))


def create_and_post_stock_doc(
    db: Session,
    tenant_id: int,
    *,
    doc_type: str,
    lines: list[dict],
    order_id: int | None = None,
    header_id: int | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict:
    """兼容：提报并立即过账（测试 / 管理快捷）。"""
    doc = submit_stock_doc(
        db,
        tenant_id,
        doc_type=doc_type,
        order_id=order_id,
        header_id=header_id,
        lines=lines,
        notes=notes,
        user_id=user_id,
    )
    return confirm_stock_doc(db, tenant_id, doc["id"], user_id=user_id)


def list_stock_docs(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    header_id: int | None = None,
    doc_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.schemas.common import normalize_page, page_payload

    page, page_size, offset = normalize_page(page, page_size)
    filters = [StockDoc.tenant_id == tenant_id]
    if header_id:
        filters.append(StockDoc.header_id == header_id)
    elif order_id:
        filters.append(StockDoc.order_id == order_id)
    if doc_type:
        filters.append(StockDoc.doc_type == StockDocType(doc_type))
    if status:
        filters.append(StockDoc.status == StockDocStatus(status))
    total = int(db.scalar(select(func.count()).select_from(StockDoc).where(*filters)) or 0)
    rows = db.scalars(
        select(StockDoc)
        .where(*filters)
        .options(selectinload(StockDoc.lines))
        .order_by(StockDoc.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return page_payload([_doc_out(db, d) for d in rows], total, page, page_size)


def list_issue_candidates(
    db: Session,
    tenant_id: int,
    order_id: int | None = None,
    header_id: int | None = None,
) -> dict:
    """某单可领/可退。领料上限 = 已占用可发 + 池 − 待确认领；退料 = 已发 − 待确认退。"""
    order: Order | None = None
    header: ExecutionHeader | None = None
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise MaterialError("header_not_found", "执行单不存在")
        order_id = header.shop_order_id
        if order_id:
            order = db.get(Order, order_id)
    elif order_id:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise MaterialError("order_not_found", "订单不存在")
        from app.services.material_service import resolve_header_for_order

        header = resolve_header_for_order(db, tenant_id, order_id)
        header_id = header.id if header else None
    else:
        raise MaterialError("missing_ref", "请指定执行单或生产单")

    ctx = build_kit_context(db, tenant_id, include_shared=True)
    req_filters = [OrderMaterialRequirement.tenant_id == tenant_id]
    if header_id:
        req_filters.append(OrderMaterialRequirement.header_id == header_id)
    else:
        req_filters.append(OrderMaterialRequirement.order_id == order_id)
    rows = db.scalars(select(OrderMaterialRequirement).where(*req_filters)).all()
    prior_issues = _issue_seq_for_owner(db, tenant_id, order_id=order_id, header_id=header_id)
    pending_issue = _pending_qty_map(
        db, tenant_id, order_id=order_id, header_id=header_id, doc_type=StockDocType.issue
    )
    pending_return = _pending_qty_map(
        db, tenant_id, order_id=order_id, header_id=header_id, doc_type=StockDocType.return_mat
    )
    out = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        d = ctx.row_dict(row)
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        required = row.required_qty or Decimal("0")
        pool = _shared_qty(db, tenant_id, row.supplier_product_id)
        issuable = max(Decimal("0"), arrived - issued)
        pending_i = pending_issue.get(row.id, Decimal("0"))
        pending_r = pending_return.get(row.id, Decimal("0"))
        remain_need = max(Decimal("0"), required - issued)
        max_issue = max(Decimal("0"), issuable + pool - pending_i)
        d["issuable_qty"] = issuable
        d["pool_qty"] = pool
        d["pending_issue_qty"] = pending_i
        d["pending_return_qty"] = pending_r
        d["max_issue_qty"] = max_issue
        d["remain_need_qty"] = remain_need
        d["returnable_qty"] = max(Decimal("0"), issued - pending_r)
        out.append(d)
    return {
        "order_id": order_id,
        "order_no": order.order_no if order else None,
        "header_id": header_id,
        "header_no": header.header_no if header else None,
        "issue_seq_next": prior_issues + 1,
        "issue_kind_next": "首领" if prior_issues == 0 else f"补领#{prior_issues + 1}",
        "lines": out,
    }
