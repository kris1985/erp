"""领退料单：车间提报 → 仓管确认过账；同一订单可多次领/退。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ExecutionHeader,
    Employee,
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    PricingUnit,
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
    is_tooling_requirement,
    skips_stock_issue_requirement,
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
    """非作废领料单序号（含待确认），供内部排序与追溯使用。"""
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
        req = db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
        unit = db.get(PricingUnit, sp.pricing_unit_id) if sp and sp.pricing_unit_id else None
        effective_per_pair = Decimal("0")
        if req:
            effective_per_pair = (
                (req.qty_per_pair or Decimal("0"))
                * (getattr(req, "size_coeff", None) or Decimal("1"))
                * (Decimal("1") + (req.loss_rate or Decimal("0")))
            )
        lines.append(
            {
                "id": ln.id,
                "order_material_requirement_id": ln.order_material_requirement_id,
                "supplier_product_id": ln.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "qty": ln.qty,
                "pairs": getattr(ln, "pairs", None),
                "unit_cost": ln.unit_cost,
                "qty_per_pair": req.qty_per_pair if req else None,
                "loss_rate": req.loss_rate if req else None,
                "effective_qty_per_pair": effective_per_pair,
                "derived_pairs": (
                    (Decimal(str(ln.qty)) / effective_per_pair).quantize(Decimal("0.01"))
                    if effective_per_pair > 0
                    else None
                ),
                "pricing_unit_name": unit.name if unit else None,
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
        issue_kind = "补料" if list(getattr(doc, "defect_event_ids", None) or []) else "领料"
    creator = db.get(Employee, doc.created_by) if doc.created_by else None
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
        "defect_event_ids": list(getattr(doc, "defect_event_ids", None) or []),
        "notes": doc.notes,
        "posted_at": doc.posted_at,
        "created_at": doc.created_at,
        "created_by": doc.created_by,
        "created_by_name": creator.name if creator else None,
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


def assert_issue_gate(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    force: bool = False,
    consume_segment_id: int | None = None,
) -> None:
    """强制领料闸门：有物料需求的在制单，关键料须已领过（issued>0）。"""
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not force and not has_capability(inv, "issue_gate") and not inv.get("issue_required"):
        return
    if order.status == OrderStatus.cancelled:
        return
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.order_id == order.id,
        )
    ).all()
    if consume_segment_id is not None:
        first_segment_id = _first_process_segment_id(db, tenant_id)
        rows = [
            row
            for row in rows
            if row.consume_segment_id == consume_segment_id
            or (consume_segment_id == first_segment_id and row.consume_segment_id is None)
        ]
    missing: list[str] = []
    for row in rows:
        if skips_stock_issue_requirement(db, row):
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


def assert_issue_gate_for_header(
    db: Session,
    tenant_id: int,
    header_id: int,
    *,
    force: bool = False,
    consume_segment_id: int | None = None,
) -> None:
    """K4-B：无桥接壳时按 header 用料行做领料闸门。"""
    inv = get_inventory_by_tenant_id(db, tenant_id)
    if not force and not has_capability(inv, "issue_gate") and not inv.get("issue_required"):
        return
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.header_id == header_id,
        )
    ).all()
    if consume_segment_id is not None:
        first_segment_id = _first_process_segment_id(db, tenant_id)
        rows = [
            row
            for row in rows
            if row.consume_segment_id == consume_segment_id
            or (consume_segment_id == first_segment_id and row.consume_segment_id is None)
        ]
    missing: list[str] = []
    for row in rows:
        if skips_stock_issue_requirement(db, row):
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


def assert_posted_issue_for_header(
    db: Session,
    tenant_id: int,
    header_id: int,
    *,
    consume_segment_id: int | None = None,
) -> None:
    """工序段工作台只要求该段已有一次实际过账，允许物料分日、分批领取。"""
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise MaterialError("header_not_found", "生产单不存在")
    req_q = select(OrderMaterialRequirement).where(
        OrderMaterialRequirement.tenant_id == tenant_id,
        OrderMaterialRequirement.header_id == header_id,
    )
    req_rows = list(db.scalars(req_q).all())
    if consume_segment_id is not None:
        first_segment_id = _first_process_segment_id(db, tenant_id)
        req_rows = [
            row
            for row in req_rows
            if row.consume_segment_id == consume_segment_id
            or (consume_segment_id == first_segment_id and row.consume_segment_id is None)
        ]
    issuable = [
        row
        for row in req_rows
        if not skips_stock_issue_requirement(db, row)
        and (row.required_qty or Decimal("0")) > 0
    ]
    if not issuable:
        return
    owner = [StockDoc.header_id == header_id]
    if header.shop_order_id:
        owner.append(StockDoc.order_id == header.shop_order_id)
    q = (
        select(StockDoc.id)
        .join(StockDocLine, StockDocLine.stock_doc_id == StockDoc.id)
        .join(
            OrderMaterialRequirement,
            OrderMaterialRequirement.id == StockDocLine.order_material_requirement_id,
        )
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == StockDocType.issue,
            StockDoc.status == StockDocStatus.posted,
            or_(*owner),
        )
    )
    if consume_segment_id is not None:
        first_segment_id = _first_process_segment_id(db, tenant_id)
        segment_scope = [OrderMaterialRequirement.consume_segment_id == consume_segment_id]
        if consume_segment_id == first_segment_id:
            segment_scope.append(OrderMaterialRequirement.consume_segment_id.is_(None))
        q = q.where(or_(*segment_scope))
    exists = db.scalar(q.limit(1))
    if exists is None:
        raise MaterialError("issue_required", "请先领料；仓库确认过账后即可报工")


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
            raise MaterialError("missing_ref", "请指定生产单")
        if row.is_customer_supplied:
            raise MaterialError("customer_supplied", "客供料不走领退料单")
        if is_tooling_requirement(db, row):
            raise MaterialError("tooling", "模具楦头为循环工装，不走领退料单")

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
    defect_event_ids: list[int] | None = None,
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
            raise MaterialError("header_not_found", "生产单不存在")
        if header.status == SpecExecutionStatus.cancelled:
            raise MaterialError("header_cancelled", "已取消生产单不能领退料")
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
        raise MaterialError("missing_ref", "请指定生产单")

    if order and order.status == OrderStatus.cancelled:
        raise MaterialError("order_cancelled", "已取消订单不能领退料")

    prepared = _prepare_lines(
        db, tenant_id, dtype, lines, order_id=order_id, header_id=header_id
    )
    pairs_by_requirement = {
        int(item["requirement_id"]): int(item["pairs"])
        for item in lines
        if item.get("pairs") is not None and int(item["pairs"]) > 0
    }

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
        defect_event_ids=sorted({int(value) for value in (defect_event_ids or []) if int(value) > 0}) or None,
        notes=notes,
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
                pairs=pairs_by_requirement.get(row.id),
                unit_cost=row.unit_price,
            )
        )

    db.commit()
    return _doc_out(db, _load_doc(db, tenant_id, doc.id))


def list_defect_material_docs(db: Session, tenant_id: int, defect_id: int) -> list[dict]:
    """返回包含指定不良记录的补料单。JsonType 跨 SQLite/MySQL，故在同租户补料单内过滤。"""
    docs = db.scalars(
        select(StockDoc)
        .where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == StockDocType.issue,
        )
        .options(selectinload(StockDoc.lines))
        .order_by(StockDoc.id.desc())
    ).all()
    return [
        _doc_out(db, doc)
        for doc in docs
        if defect_id in {int(value) for value in (getattr(doc, "defect_event_ids", None) or [])}
    ]


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
            raise MaterialError("header_not_found", "生产单不存在")
        if header.status == SpecExecutionStatus.cancelled:
            raise MaterialError("header_cancelled", "已取消生产单不能过账")
    else:
        raise MaterialError("missing_ref", "单据未关联生产单")

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
    production_started = False
    if dtype == StockDocType.issue and owner_header_id:
        from app.services.execution_service import start_cutting_from_issue

        transition = start_cutting_from_issue(
            db, tenant_id, int(owner_header_id), commit=False
        )
        production_started = bool(transition.get("changed"))
    db.commit()
    result = _doc_out(db, _load_doc(db, tenant_id, doc.id))
    result["production_started"] = production_started
    return result


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
    issue_kind: str | None = None,
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
    # 补料单=挂了不良来源；普通领料不混入补料列表。
    if issue_kind == "replenish":
        filters.append(StockDoc.doc_type == StockDocType.issue)
        filters.append(StockDoc.defect_event_ids.is_not(None))
    elif issue_kind == "issue":
        filters.append(StockDoc.defect_event_ids.is_(None))
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


def _first_process_segment_id(db: Session, tenant_id: int) -> int | None:
    from app.models import ProcessSegment

    return db.scalar(
        select(ProcessSegment.id)
        .where(ProcessSegment.tenant_id == tenant_id, ProcessSegment.is_active.is_(True))
        .order_by(ProcessSegment.sort_order.asc(), ProcessSegment.id.asc())
        .limit(1)
    )


def _suggested_qty_for_pairs(
    row: OrderMaterialRequirement,
    *,
    pairs: int,
    total_qty: int,
    remain_need: Decimal,
    max_issue: Decimal,
) -> Decimal:
    """按双数估算本次领料：有整单总量时按需求比例；否则按单耗×双数×(1+损耗)。不超过剩余需求/可发。"""
    if pairs <= 0:
        return Decimal("0")
    required = row.required_qty or Decimal("0")
    if total_qty > 0 and required > 0:
        suggested = (required * Decimal(pairs) / Decimal(total_qty)).quantize(Decimal("0.0001"))
    else:
        qty_per_pair = row.qty_per_pair or Decimal("0")
        loss_rate = row.loss_rate or Decimal("0")
        coeff = getattr(row, "size_coeff", None) or Decimal("1")
        suggested = (qty_per_pair * coeff * Decimal(pairs) * (Decimal("1") + loss_rate)).quantize(
            Decimal("0.0001")
        )
    if remain_need > 0:
        suggested = min(suggested, remain_need)
    if max_issue > 0:
        suggested = min(suggested, max_issue)
    return max(Decimal("0"), suggested)


def list_issue_candidates(
    db: Session,
    tenant_id: int,
    order_id: int | None = None,
    header_id: int | None = None,
    *,
    consume_segment_id: int | None = None,
    pairs: int | None = None,
) -> dict:
    """某单可领/可退。领料上限 = 已占用可发 + 池 − 待确认领；退料 = 已发 − 待确认退。

    consume_segment_id：只出该工序段物料；若该段为租户首段，另含未标注段的料。
    pairs：按双数给出 suggested_qty（前端填「本次」用）。
    """
    order: Order | None = None
    header: ExecutionHeader | None = None
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise MaterialError("header_not_found", "生产单不存在")
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
        raise MaterialError("missing_ref", "请指定生产单")

    total_qty = int(header.total_qty if header else (order.total_qty if order else 0) or 0)
    first_segment_id = _first_process_segment_id(db, tenant_id)
    include_unlabeled = bool(
        consume_segment_id is not None and first_segment_id is not None and consume_segment_id == first_segment_id
    )

    ctx = build_kit_context(db, tenant_id, include_shared=True)
    req_filters = [OrderMaterialRequirement.tenant_id == tenant_id]
    if header_id:
        req_filters.append(OrderMaterialRequirement.header_id == header_id)
    else:
        req_filters.append(OrderMaterialRequirement.order_id == order_id)
    rows = list(db.scalars(select(OrderMaterialRequirement).where(*req_filters)).all())
    if consume_segment_id is not None:
        filtered = []
        for row in rows:
            sid = getattr(row, "consume_segment_id", None)
            if sid == consume_segment_id or (include_unlabeled and sid is None):
                filtered.append(row)
        rows = filtered

    prior_issues = _issue_seq_for_owner(db, tenant_id, order_id=order_id, header_id=header_id)
    pending_issue = _pending_qty_map(
        db, tenant_id, order_id=order_id, header_id=header_id, doc_type=StockDocType.issue
    )
    pending_return = _pending_qty_map(
        db, tenant_id, order_id=order_id, header_id=header_id, doc_type=StockDocType.return_mat
    )
    out = []
    for row in rows:
        if skips_stock_issue_requirement(db, row):
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
        if pairs is not None:
            d["suggested_qty"] = _suggested_qty_for_pairs(
                row,
                pairs=int(pairs),
                total_qty=total_qty,
                remain_need=remain_need,
                max_issue=max_issue,
            )
        out.append(d)
    return {
        "order_id": order_id,
        "order_no": order.order_no if order else None,
        "header_id": header_id,
        "header_no": header.header_no if header else None,
        "total_qty": total_qty,
        "consume_segment_id": consume_segment_id,
        "include_unlabeled": include_unlabeled,
        "issue_seq_next": prior_issues + 1,
        "issue_kind_next": "领料",
        "lines": out,
    }
