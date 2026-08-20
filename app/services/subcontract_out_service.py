"""B2a：外发工序单（我们发包出去）——建单 / 发料 / 收回 / 欠数 / 损耗 / 加工费应付。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    Partner,
    Payable,
    PayableStatus,
    ProcessDefinition,
    SpecExecutionOrder,
    SubcontractIssue,
    SubcontractOrder,
    SubcontractOrderStatus,
    SubcontractReceipt,
)
from app.services.ap_service import _refresh_ap_status


class SubcontractError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


OPEN_STATUSES = (
    SubcontractOrderStatus.draft,
    SubcontractOrderStatus.issued,
    SubcontractOrderStatus.partial_received,
)


def generate_subcontract_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = f"SC{today}"
    existing = db.scalars(
        select(SubcontractOrder).where(
            SubcontractOrder.tenant_id == tenant_id,
            SubcontractOrder.subcontract_no.like(f"{prefix}%"),
        )
    ).all()
    return f"{prefix}{len(existing) + 1:02d}"


def _derive_status(order: SubcontractOrder) -> SubcontractOrderStatus:
    if order.status == SubcontractOrderStatus.cancelled:
        return order.status
    if (order.issued_qty or 0) <= 0:
        return SubcontractOrderStatus.draft
    if (order.received_qty or 0) <= 0:
        return SubcontractOrderStatus.issued
    if (order.received_qty or 0) >= (order.issued_qty or 0):
        return SubcontractOrderStatus.received
    return SubcontractOrderStatus.partial_received


def _linked_no(db: Session, order: SubcontractOrder) -> str | None:
    if order.header_id:
        h = db.get(ExecutionHeader, order.header_id)
        if h:
            return h.header_no
    if order.order_id:
        o = db.get(Order, order.order_id)
        if o:
            return o.order_no
    if order.execution_id:
        e = db.get(SpecExecutionOrder, order.execution_id)
        if e:
            return e.execution_no
    return None


def _out(db: Session, order: SubcontractOrder, *, include_flows: bool = False) -> dict[str, Any]:
    partner = db.get(Partner, order.partner_id) if order.partner_id else None
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    issued = int(order.issued_qty or 0)
    received = int(order.received_qty or 0)
    data: dict[str, Any] = {
        "id": order.id,
        "subcontract_no": order.subcontract_no,
        "partner_id": order.partner_id,
        "partner_name": (partner.short_name or partner.name) if partner else None,
        "process_id": order.process_id,
        "process_name": order.process_name,
        "order_id": order.order_id,
        "header_id": order.header_id,
        "execution_id": order.execution_id,
        "own_product_id": order.own_product_id,
        "product_code": product.product_code if product else None,
        "linked_no": _linked_no(db, order),
        "total_qty": int(order.total_qty or 0),
        "issued_qty": issued,
        "received_qty": received,
        "outstanding_qty": max(0, issued - received),
        "loss_qty": issued - received,
        "unit_price": order.unit_price,
        # 应付口径：按收回数量结算（与 receive 挂账一致）
        "payable_amount": (Decimal(received) * (order.unit_price or Decimal("0"))).quantize(
            Decimal("0.0001")
        ),
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "notes": order.notes,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
    if include_flows:
        data["issues"] = [
            {
                "id": i.id,
                "qty": int(i.qty or 0),
                "note": i.note,
                "created_by": i.created_by,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in sorted(order.issues, key=lambda x: x.id)
        ]
        data["receipts"] = [
            {
                "id": r.id,
                "qty": int(r.qty or 0),
                "defect_qty": int(r.defect_qty or 0),
                "note": r.note,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in sorted(order.receipts, key=lambda x: x.id)
        ]
    return data


def get_subcontract_order(db: Session, tenant_id: int, order_id: int) -> SubcontractOrder:
    order = db.scalar(
        select(SubcontractOrder)
        .where(SubcontractOrder.id == order_id, SubcontractOrder.tenant_id == tenant_id)
        .options(
            selectinload(SubcontractOrder.issues),
            selectinload(SubcontractOrder.receipts),
        )
    )
    if not order:
        raise SubcontractError("not_found", "外发单不存在")
    return order


def list_subcontract_orders(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = None,
    outstanding: bool = False,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    from app.schemas.common import normalize_page

    page, page_size, offset = normalize_page(page, page_size)
    q = select(SubcontractOrder).where(SubcontractOrder.tenant_id == tenant_id)
    if status:
        if status not in {s.value for s in SubcontractOrderStatus}:
            raise SubcontractError("invalid_status", "状态无效")
        q = q.where(SubcontractOrder.status == SubcontractOrderStatus(status))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(SubcontractOrder.subcontract_no.ilike(kw))
    if outstanding:
        q = q.where(SubcontractOrder.issued_qty > SubcontractOrder.received_qty)
    q = q.order_by(SubcontractOrder.id.desc())

    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = list(db.scalars(q.offset(offset).limit(page_size)).all())
    out = [_out(db, r) for r in rows]
    return out, int(total)


def create_subcontract_order(
    db: Session,
    tenant_id: int,
    *,
    partner_id: int,
    total_qty: int,
    unit_price: Decimal,
    process_id: int | None = None,
    order_id: int | None = None,
    header_id: int | None = None,
    execution_id: int | None = None,
    own_product_id: int | None = None,
    notes: str | None = None,
    created_by: int | None = None,
) -> SubcontractOrder:
    if not partner_id:
        raise SubcontractError("partner_required", "请选择外协厂")
    partner = db.get(Partner, partner_id)
    if not partner or partner.tenant_id != tenant_id:
        raise SubcontractError("partner_not_found", "外协厂不存在")
    if int(total_qty or 0) <= 0:
        raise SubcontractError("invalid_qty", "外发数量须大于 0")

    process_name = None
    if process_id:
        proc = db.get(ProcessDefinition, process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise SubcontractError("process_not_found", "工序不存在")
        process_name = proc.name

    order = SubcontractOrder(
        tenant_id=tenant_id,
        subcontract_no=generate_subcontract_no(db, tenant_id),
        partner_id=partner_id,
        process_id=process_id,
        process_name=process_name,
        order_id=order_id,
        header_id=header_id,
        execution_id=execution_id,
        own_product_id=own_product_id,
        total_qty=int(total_qty),
        issued_qty=0,
        received_qty=0,
        unit_price=Decimal(str(unit_price or 0)),
        status=SubcontractOrderStatus.draft,
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def update_subcontract_order(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    partner_id: int | None = None,
    process_id: int | None = None,
    total_qty: int | None = None,
    unit_price: Decimal | None = None,
    notes: str | None = None,
) -> SubcontractOrder:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        raise SubcontractError("not_editable", "已取消的外发单不可编辑")
    if order.status not in (SubcontractOrderStatus.draft,):
        raise SubcontractError("not_editable", "仅草稿外发单可编辑")
    if partner_id is not None:
        partner = db.get(Partner, partner_id)
        if not partner or partner.tenant_id != tenant_id:
            raise SubcontractError("partner_not_found", "外协厂不存在")
        order.partner_id = partner_id
    if process_id is not None:
        proc = db.get(ProcessDefinition, process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise SubcontractError("process_not_found", "工序不存在")
        order.process_id = proc.id
        order.process_name = proc.name
    if total_qty is not None:
        if int(total_qty) <= 0:
            raise SubcontractError("invalid_qty", "外发数量须大于 0")
        order.total_qty = int(total_qty)
    if unit_price is not None:
        order.unit_price = Decimal(str(unit_price))
    if notes is not None:
        order.notes = (notes or "").strip() or None
    db.commit()
    db.refresh(order)
    return order


def cancel_subcontract_order(db: Session, tenant_id: int, order_id: int) -> SubcontractOrder:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        return order
    if (order.issued_qty or 0) > 0 or (order.received_qty or 0) > 0:
        raise SubcontractError("not_cancellable", "已有发料/收回，不可取消")
    order.status = SubcontractOrderStatus.cancelled
    db.commit()
    db.refresh(order)
    return order


def issue_subcontract(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    qty: int,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        raise SubcontractError("cancelled", "已取消的外发单不可发料")
    if int(qty or 0) <= 0:
        raise SubcontractError("invalid_qty", "发料数量须大于 0")
    order.issued_qty = int(order.issued_qty or 0) + int(qty)
    flow = SubcontractIssue(
        tenant_id=tenant_id,
        subcontract_order_id=order.id,
        qty=int(qty),
        note=(note or "").strip() or None,
        created_by=created_by,
    )
    db.add(flow)
    order.status = _derive_status(order)
    db.commit()
    db.refresh(order)
    db.refresh(flow)
    return _out(db, order, include_flows=True)


def _create_payable_for_receive(
    db: Session,
    tenant_id: int,
    order: SubcontractOrder,
    qty: int,
) -> Payable | None:
    price = order.unit_price or Decimal("0")
    amount = (Decimal(qty) * price).quantize(Decimal("0.0001"))
    if amount <= 0:
        return None
    partner = db.get(Partner, order.partner_id) if order.partner_id else None
    supplier_name = (partner.short_name or partner.name).strip() if partner else f"外协厂#{order.partner_id}"
    term_days = max(0, int(partner.payment_term_days or 0)) if partner and partner.payment_term_days is not None else 0
    ap = Payable(
        tenant_id=tenant_id,
        supplier_id=order.partner_id,
        supplier_name=supplier_name,
        purchase_order_id=None,
        subcontract_order_id=order.id,
        payable_date=date.today(),
        due_date=date.today() + timedelta(days=term_days),
        payment_term_days=term_days,
        amount=amount,
        adjustment=Decimal("0"),
        paid_amount=Decimal("0"),
        status=PayableStatus.open,
        notes=f"外发 {order.subcontract_no} 收回挂账",
    )
    db.add(ap)
    db.flush()
    _refresh_ap_status(ap)
    return ap


def _sync_execution_progress_on_receive(
    db: Session,
    tenant_id: int,
    order: SubcontractOrder,
    qty: int,
) -> None:
    """B2a：收回后回写关联执行单对应工序完成量，并刷新执行进度（与报工同源）。"""
    if not (order.header_id or order.order_id):
        return
    if not order.process_id:
        return
    proc: OrderProcess | None = None
    if order.header_id:
        proc = db.scalar(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.header_id == order.header_id,
                OrderProcess.process_id == order.process_id,
            )
            .order_by(OrderProcess.id)
        )
    if proc is None and order.order_id:
        proc = db.scalar(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.order_id == order.order_id,
                OrderProcess.process_id == order.process_id,
            )
            .order_by(OrderProcess.id)
        )
    if proc is None:
        return

    proc.completed_qty = int(proc.completed_qty or 0) + int(qty)
    if proc.status == OrderProcessStatus.pending:
        proc.status = OrderProcessStatus.in_progress
    if int(proc.completed_qty) >= int(proc.plan_qty or 0):
        proc.status = OrderProcessStatus.completed

    # 与报工同一入口刷新执行进度（末道口径）
    from app.services.execution_service import refresh_execution_progress_for_order

    try:
        refresh_execution_progress_for_order(
            db,
            tenant_id=tenant_id,
            order_id=order.order_id,
            header_id=order.header_id,
            execution_id=order.execution_id,
        )
    except Exception:
        # 进度刷新失败不阻断收回（外发单本身已入账）
        pass


def receive_subcontract(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    qty: int,
    defect_qty: int = 0,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        raise SubcontractError("cancelled", "已取消的外发单不可收回")
    if int(qty or 0) <= 0:
        raise SubcontractError("invalid_qty", "收回数量须大于 0")
    order.received_qty = int(order.received_qty or 0) + int(qty)
    flow = SubcontractReceipt(
        tenant_id=tenant_id,
        subcontract_order_id=order.id,
        qty=int(qty),
        defect_qty=max(0, int(defect_qty or 0)),
        note=(note or "").strip() or None,
        created_by=created_by,
    )
    db.add(flow)
    _create_payable_for_receive(db, tenant_id, order, int(qty))
    _sync_execution_progress_on_receive(db, tenant_id, order, int(qty))
    order.status = _derive_status(order)
    db.commit()
    db.refresh(order)
    db.refresh(flow)
    return _out(db, order, include_flows=True)


def list_issues(db: Session, tenant_id: int, order_id: int) -> list[dict]:
    order = get_subcontract_order(db, tenant_id, order_id)
    rows = list(
        db.scalars(
            select(SubcontractIssue)
            .where(SubcontractIssue.subcontract_order_id == order.id)
            .order_by(SubcontractIssue.id.desc())
        ).all()
    )
    return [
        {
            "id": r.id,
            "subcontract_order_id": r.subcontract_order_id,
            "qty": int(r.qty or 0),
            "note": r.note,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def list_receipts(db: Session, tenant_id: int, order_id: int) -> list[dict]:
    order = get_subcontract_order(db, tenant_id, order_id)
    rows = list(
        db.scalars(
            select(SubcontractReceipt)
            .where(SubcontractReceipt.subcontract_order_id == order.id)
            .order_by(SubcontractReceipt.id.desc())
        ).all()
    )
    return [
        {
            "id": r.id,
            "subcontract_order_id": r.subcontract_order_id,
            "qty": int(r.qty or 0),
            "defect_qty": int(r.defect_qty or 0),
            "note": r.note,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
