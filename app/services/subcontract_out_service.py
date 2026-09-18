"""B2a：外发工序单（我们发包出去）——建单 / 发料 / 验收 / 报废 / 加工费应付。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    DefectEvent,
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    OwnProductLabor,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    ProcessDefinition,
    SalesOrderLine,
    SettlementDirection,
    SpecExecutionOrder,
    Size,
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


def _selected_route_processes(
    db: Session,
    *,
    tenant_id: int,
    header: ExecutionHeader,
    order_process_ids: list[int],
) -> list[OrderProcess]:
    selected_ids = list(dict.fromkeys(int(value) for value in order_process_ids))
    if not selected_ids:
        raise SubcontractError("process_required", "请从生产单工艺路由中选择工序")
    owner_filters = [OrderProcess.header_id == header.id]
    if header.shop_order_id:
        owner_filters.append(OrderProcess.order_id == int(header.shop_order_id))
    from sqlalchemy import or_

    rows = list(
        db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.id.in_(selected_ids),
                or_(*owner_filters),
            )
            .order_by(OrderProcess.id)
        ).all()
    )
    if len(rows) != len(selected_ids):
        raise SubcontractError("process_not_found", "所选工序不属于当前生产单工艺路由")
    return rows


def suggest_subcontract_material_unit_price(
    db: Session,
    *,
    tenant_id: int,
    header_id: int | None,
    order_process_ids: list[int] | None,
) -> dict:
    """外发材料单价 = 外发第一道工序累计物料 + 该工序之前本厂工资，单位元/双。"""
    zero = Decimal("0.0000")
    empty = {
        "material_unit_price": zero,
        "material_amount": zero,
        "labor_amount": zero,
        "order_process_id": None,
        "process_id": None,
        "process_name": None,
    }
    if not header_id or not order_process_ids:
        return empty
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        return empty
    route_rows = _selected_route_processes(
        db,
        tenant_id=tenant_id,
        header=header,
        order_process_ids=order_process_ids,
    )
    from app.services.trace_service import calculate_defect_loss_quote

    quote = calculate_defect_loss_quote(
        db,
        tenant_id=tenant_id,
        header_id=header.id,
        order_process_id=int(route_rows[0].id),
    )
    material_pair = (Decimal(str(quote.get("material_per_piece") or 0)) * Decimal("2")).quantize(Decimal("0.0001"))
    labor_pair = (
        Decimal(str(quote.get("labor_before_process_per_piece") or 0)) * Decimal("2")
    ).quantize(Decimal("0.0001"))
    return {
        "material_unit_price": (material_pair + labor_pair).quantize(Decimal("0.0001")),
        "material_amount": material_pair,
        "labor_amount": labor_pair,
        "order_process_id": int(route_rows[0].id),
        "process_id": int(route_rows[0].process_id) if route_rows[0].process_id else None,
        "process_name": route_rows[0].process_name,
    }


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


def _subcontract_loss_units(
    db: Session,
    order: SubcontractOrder,
) -> tuple[Decimal, Decimal, Decimal]:
    """外发显示的废品损失按报废数量乘工价计算。"""
    del db
    material_unit = Decimal("0")
    labor_unit = Decimal(order.unit_price or 0)
    material_unit = material_unit.quantize(Decimal("0.0001"))
    labor_unit = labor_unit.quantize(Decimal("0.0001"))
    return material_unit, labor_unit, (material_unit + labor_unit).quantize(Decimal("0.0001"))


def _linked_defect_qty(db: Session, order: SubcontractOrder) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(DefectEvent.qty), 0)).where(
                DefectEvent.tenant_id == order.tenant_id,
                DefectEvent.subcontract_order_id == order.id,
            )
        )
        or 0
    )


def _out(db: Session, order: SubcontractOrder, *, include_flows: bool = False) -> dict[str, Any]:
    partner = db.get(Partner, order.partner_id) if order.partner_id else None
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    issued = int(order.issued_qty or 0)
    received = int(order.received_qty or 0)
    defect_qty = _linked_defect_qty(db, order)
    shared_loss_amount = sum(
        (Decimal(receipt.shared_loss_amount or 0) for receipt in order.receipts),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    material_loss_unit, labor_loss_unit, loss_unit = _subcontract_loss_units(db, order)
    loss_amount = (Decimal(defect_qty) * loss_unit).quantize(Decimal("0.01"))
    issue_count = len(order.issues)
    receipt_count = len(order.receipts)
    order_process_ids = [int(value) for value in (order.order_process_ids or [])]
    data: dict[str, Any] = {
        "id": order.id,
        "subcontract_no": order.subcontract_no,
        "partner_id": order.partner_id,
        "partner_name": (partner.short_name or partner.name) if partner else None,
        "process_id": order.process_id,
        "process_name": order.process_name,
        "order_process_ids": order_process_ids,
        "order_id": order.order_id,
        "header_id": order.header_id,
        "execution_id": order.execution_id,
        "own_product_id": order.own_product_id,
        "product_code": product.product_code if product else None,
        "linked_no": _linked_no(db, order),
        "total_qty": int(order.total_qty or 0),
        "issued_qty": issued,
        "received_qty": received,
        "issue_count": issue_count,
        "receipt_count": receipt_count,
        "outstanding_qty": max(0, issued - received),
        "loss_qty": defect_qty,
        "qualified_qty": received,
        "material_loss_amount": (Decimal(defect_qty) * material_loss_unit).quantize(Decimal("0.01")),
        "labor_loss_amount": (Decimal(defect_qty) * labor_loss_unit).quantize(Decimal("0.01")),
        "loss_unit_amount": loss_unit,
        "loss_amount": loss_amount,
        "shared_loss_amount": shared_loss_amount,
        "company_loss_amount": max(Decimal("0"), loss_amount - shared_loss_amount).quantize(Decimal("0.01")),
        "remaining_shared_loss_amount": max(Decimal("0"), loss_amount - shared_loss_amount).quantize(Decimal("0.01")),
        "unit_price": order.unit_price,
        "material_unit_price": order.material_unit_price,
        "subcontract_unit_consumption": order.subcontract_unit_consumption,
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
        "processing_fee": (Decimal(received) * (order.unit_price or Decimal("0"))).quantize(
            Decimal("0.0001")
        ),
        # 应付 = 完工加工费 - 外加工厂分担损失。
        "payable_amount": max(
            Decimal("0"),
            Decimal(received) * (order.unit_price or Decimal("0")) - shared_loss_amount,
        ).quantize(Decimal("0.0001")),
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "notes": order.notes,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
    if include_flows:
        selected_process_ids = [int(value) for value in (order.order_process_ids or [])]
        route_rows = list(
            db.scalars(
                select(OrderProcess)
                .where(
                    OrderProcess.tenant_id == order.tenant_id,
                    OrderProcess.id.in_(selected_process_ids),
                )
                .order_by(OrderProcess.id)
            ).all()
        ) if selected_process_ids else []
        labor_process_ids = {int(row.process_id) for row in route_rows if row.process_id}
        if not labor_process_ids and order.process_id:
            labor_process_ids.add(int(order.process_id))
        labor_rows = list(
            db.scalars(
                select(OwnProductLabor)
                .where(
                    OwnProductLabor.tenant_id == order.tenant_id,
                    OwnProductLabor.own_product_id == order.own_product_id,
                    OwnProductLabor.process_id.in_(labor_process_ids),
                )
                .order_by(OwnProductLabor.sort_order, OwnProductLabor.id)
            ).all()
        ) if order.own_product_id and labor_process_ids else []
        labor_by_key = {
            (int(row.process_id), int(row.part_id) if row.part_id else None): row
            for row in labor_rows
            if row.process_id
        }
        process_requirements = []
        for route in route_rows:
            labor = labor_by_key.get(
                (int(route.process_id), int(route.part_id) if route.part_id else None)
            ) or labor_by_key.get((int(route.process_id), None))
            process_requirements.append({
                "process_name": route.process_name,
                "requirement_note": labor.requirement_note if labor else None,
            })
        if not process_requirements and labor_rows:
            process_requirements = [
                {
                    "process_name": row.process_name,
                    "requirement_note": row.requirement_note,
                }
                for row in labor_rows
            ]
        data["process_requirements"] = process_requirements
        if order.header_id:
            try:
                from app.services import execution_service

                flow_card = execution_service.flow_card_out(db, order.tenant_id, int(order.header_id))
                data["product_image_url"] = flow_card.get("product_image_url")
                data["color_name"] = flow_card.get("color_name")
                data["work_requirements"] = flow_card.get("work_requirements") or []
            except Exception:
                data["product_image_url"] = product.image_url if product else None
                data["color_name"] = None
                data["work_requirements"] = []
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
                "shared_loss_amount": Decimal(r.shared_loss_amount or 0),
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
    partner_id: int | None = None,
    header_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
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
    if partner_id:
        q = q.where(SubcontractOrder.partner_id == int(partner_id))
    if header_id:
        q = q.where(SubcontractOrder.header_id == int(header_id))
    if date_from:
        q = q.where(SubcontractOrder.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.where(
            SubcontractOrder.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )
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
    material_unit_price: Decimal = Decimal("0"),
    subcontract_unit_consumption: Decimal = Decimal("0"),
    delivery_date: date | None = None,
    process_id: int | None = None,
    order_process_ids: list[int] | None = None,
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
    selected_order_process_ids: list[int] = []
    if order_process_ids is not None:
        if not header_id:
            raise SubcontractError("header_required", "请先选择生产单")
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise SubcontractError("header_not_found", "生产单不存在")
        route_rows = _selected_route_processes(
            db,
            tenant_id=tenant_id,
            header=header,
            order_process_ids=order_process_ids,
        )
        selected_order_process_ids = [int(row.id) for row in route_rows]
        process_id = int(route_rows[0].process_id)
        process_name = "、".join(
            dict.fromkeys(row.process_name for row in route_rows if row.process_name)
        )[:255]
        order_id = header.shop_order_id
        own_product_id = header.own_product_id
        if Decimal(str(material_unit_price or 0)) <= 0:
            material_unit_price = suggest_subcontract_material_unit_price(
                db,
                tenant_id=tenant_id,
                header_id=header.id,
                order_process_ids=selected_order_process_ids,
            )["material_unit_price"]
    elif process_id:
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
        order_process_ids=selected_order_process_ids,
        order_id=order_id,
        header_id=header_id,
        execution_id=execution_id,
        own_product_id=own_product_id,
        total_qty=int(total_qty),
        # 新建即表示已发出，不再需要单独登记发料。
        issued_qty=int(total_qty),
        received_qty=0,
        unit_price=Decimal(str(unit_price or 0)),
        material_unit_price=Decimal(str(material_unit_price or 0)),
        subcontract_unit_consumption=Decimal(str(subcontract_unit_consumption or 0)),
        delivery_date=delivery_date,
        status=SubcontractOrderStatus.issued,
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
    order_process_ids: list[int] | None = None,
    header_id: int | None = None,
    total_qty: int | None = None,
    unit_price: Decimal | None = None,
    material_unit_price: Decimal | None = None,
    subcontract_unit_consumption: Decimal | None = None,
    delivery_date: date | None = None,
    notes: str | None = None,
) -> SubcontractOrder:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        raise SubcontractError("not_editable", "已取消的外发单不可编辑")
    if order.receipts:
        raise SubcontractError("not_editable", "已有完工记录，外发单不可编辑")
    if partner_id is not None:
        partner = db.get(Partner, partner_id)
        if not partner or partner.tenant_id != tenant_id:
            raise SubcontractError("partner_not_found", "外协厂不存在")
        order.partner_id = partner_id
    if header_id is not None:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise SubcontractError("header_not_found", "生产单不存在")
        order.header_id = header.id
        order.order_id = header.shop_order_id
        order.own_product_id = header.own_product_id
    if order_process_ids is not None:
        if not order.header_id:
            raise SubcontractError("header_required", "请先选择生产单")
        header = db.get(ExecutionHeader, int(order.header_id))
        route_rows = _selected_route_processes(
            db,
            tenant_id=tenant_id,
            header=header,
            order_process_ids=order_process_ids,
        )
        order.order_process_ids = [int(row.id) for row in route_rows]
        order.process_id = int(route_rows[0].process_id)
        order.process_name = "、".join(
            dict.fromkeys(row.process_name for row in route_rows if row.process_name)
        )[:255]
    elif process_id is not None:
        proc = db.get(ProcessDefinition, process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise SubcontractError("process_not_found", "工序不存在")
        order.process_id = proc.id
        order.process_name = proc.name
    if total_qty is not None:
        if int(total_qty) <= 0:
            raise SubcontractError("invalid_qty", "外发数量须大于 0")
        order.total_qty = int(total_qty)
        order.issued_qty = int(total_qty)
    if unit_price is not None:
        order.unit_price = Decimal(str(unit_price))
    if material_unit_price is not None:
        order.material_unit_price = Decimal(str(material_unit_price))
    if subcontract_unit_consumption is not None:
        order.subcontract_unit_consumption = Decimal(str(subcontract_unit_consumption))
    if delivery_date is not None:
        order.delivery_date = delivery_date
    if notes is not None:
        order.notes = (notes or "").strip() or None
    db.commit()
    db.refresh(order)
    return order


def cancel_subcontract_order(db: Session, tenant_id: int, order_id: int) -> SubcontractOrder:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        return order
    if order.issues or order.receipts:
        raise SubcontractError("not_cancellable", "已有发料/收回，不可取消")
    order.status = SubcontractOrderStatus.cancelled
    db.commit()
    db.refresh(order)
    return order


def delete_subcontract_order(db: Session, tenant_id: int, order_id: int) -> None:
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.issues or order.receipts:
        raise SubcontractError("not_deletable", "已有发料或收回记录，不能删除")
    linked_payable = db.scalar(
        select(Payable.id).where(
            Payable.tenant_id == tenant_id,
            Payable.subcontract_order_id == order.id,
        )
    )
    if linked_payable:
        raise SubcontractError("not_deletable", "已关联应付单，不能删除")
    db.delete(order)
    db.commit()


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
    shared_loss_amount: Decimal = Decimal("0"),
    receipt_id: int | None = None,
) -> Payable | None:
    price = order.unit_price or Decimal("0")
    amount = max(
        Decimal("0"),
        Decimal(qty) * price - Decimal(shared_loss_amount or 0),
    ).quantize(Decimal("0.0001"))
    if amount <= 0:
        return None
    partner = db.get(Partner, order.partner_id) if order.partner_id else None
    supplier_name = (partner.short_name or partner.name).strip() if partner else f"外协厂#{order.partner_id}"
    term_days = max(0, int(partner.payment_term_days or 0)) if partner and partner.payment_term_days is not None else 0
    payable_date = date.today()
    if partner:
        from app.services import settlement_service

        due_date = settlement_service.effective_due_date(
            db,
            tenant_id,
            partner.id,
            SettlementDirection.supplier,
            business_date=payable_date,
            fallback_term_days=term_days,
        )
    else:
        due_date = payable_date
    ap = Payable(
        tenant_id=tenant_id,
        supplier_id=order.partner_id,
        supplier_name=supplier_name,
        purchase_order_id=None,
        subcontract_order_id=order.id,
        payable_date=payable_date,
        due_date=due_date,
        payment_term_days=term_days,
        amount=amount,
        adjustment=Decimal("0"),
        paid_amount=Decimal("0"),
        status=PayableStatus.open,
        notes=f"外发 {order.subcontract_no} 验收挂账",
    )
    db.add(ap)
    db.flush()
    execution = db.get(SpecExecutionOrder, order.execution_id) if order.execution_id else None
    header = db.get(ExecutionHeader, order.header_id) if order.header_id else None
    if not header and execution and execution.header_id:
        header = db.get(ExecutionHeader, execution.header_id)
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    if not product and execution:
        product = db.get(OwnProduct, execution.own_product_id)
    if not product and header:
        product = db.get(OwnProduct, header.own_product_id)
    sales_line = (
        db.get(SalesOrderLine, header.sales_order_line_id)
        if header and header.sales_order_line_id
        else None
    )
    color_id = execution.color_id if execution and execution.color_id else header.color_id if header else None
    color = db.get(Color, color_id) if color_id else None
    size = db.get(Size, execution.size_id) if execution and execution.size_id else None
    db.add(
        PayableLine(
            tenant_id=tenant_id,
            payable_id=ap.id,
            source_type="subcontract_receive",
            source_ref_id=receipt_id or order.id,
            source_document_no=order.subcontract_no,
            item_code=(product.product_code if product else None),
            item_name=(product.product_code if product else None),
            process_name=order.process_name,
            customer_sku=(sales_line.customer_sku if sales_line else None),
            color_name=(color.name if color else None),
            size_value=(size.size_value if size else None),
            unit_name="双",
            qty=Decimal(qty),
            unit_price=price,
            amount=amount,
            sort_order=0,
        )
    )
    _refresh_ap_status(ap)
    # 总账只认付款登记，外发挂账不入账
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
    if not order.process_id and not order.order_process_ids:
        return
    procs: list[OrderProcess] = []
    selected_ids = [int(value) for value in (order.order_process_ids or [])]
    if selected_ids:
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(
                    OrderProcess.tenant_id == tenant_id,
                    OrderProcess.id.in_(selected_ids),
                )
                .order_by(OrderProcess.id)
            ).all()
        )
    elif order.header_id:
        proc = db.scalar(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.header_id == order.header_id,
                OrderProcess.process_id == order.process_id,
            )
            .order_by(OrderProcess.id)
        )
        if proc:
            procs = [proc]
    if not procs and order.order_id:
        proc = db.scalar(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.order_id == order.order_id,
                OrderProcess.process_id == order.process_id,
            )
            .order_by(OrderProcess.id)
        )
        if proc:
            procs = [proc]
    if not procs:
        return

    for proc in procs:
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
    shared_loss_amount: Decimal = Decimal("0"),
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    del defect_qty  # 废品改由报废记录同步到外发，验收不再录入或写回报废。
    order = get_subcontract_order(db, tenant_id, order_id)
    if order.status == SubcontractOrderStatus.cancelled:
        raise SubcontractError("cancelled", "已取消的外发单不可验收")
    if int(qty or 0) <= 0:
        raise SubcontractError("invalid_qty", "验收数量须大于 0")
    outstanding = max(0, int(order.issued_qty or 0) - int(order.received_qty or 0))
    if int(qty) > outstanding:
        raise SubcontractError("qty_exceeds_outstanding", f"本次验收不能超过待验收数量 {outstanding}")
    _, _, loss_unit = _subcontract_loss_units(db, order)
    loss_amount = (Decimal(_linked_defect_qty(db, order)) * loss_unit).quantize(Decimal("0.01"))
    already_shared = sum(
        (Decimal(receipt.shared_loss_amount or 0) for receipt in order.receipts),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    remaining_shareable = max(Decimal("0"), loss_amount - already_shared)
    normalized_shared_loss = Decimal(shared_loss_amount or 0).quantize(Decimal("0.01"))
    if normalized_shared_loss < 0:
        raise SubcontractError("invalid_shared_loss", "分担损失不能小于 0")
    if normalized_shared_loss > remaining_shareable:
        raise SubcontractError("shared_loss_exceeds_loss", "分担损失不能大于损失金额")
    order.received_qty = int(order.received_qty or 0) + int(qty)
    flow = SubcontractReceipt(
        tenant_id=tenant_id,
        subcontract_order_id=order.id,
        qty=int(qty),
        defect_qty=0,
        shared_loss_amount=normalized_shared_loss,
        note=(note or "").strip() or None,
        created_by=created_by,
    )
    db.add(flow)
    db.flush()
    _create_payable_for_receive(
        db,
        tenant_id,
        order,
        int(qty),
        shared_loss_amount=normalized_shared_loss,
        receipt_id=flow.id,
    )
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
    _material_loss_unit, _labor_loss_unit, loss_unit = _subcontract_loss_units(db, order)
    work_price = Decimal(order.unit_price or 0)
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
            "qualified_qty": int(r.qty or 0),
            "loss_amount": (
                Decimal(int(r.defect_qty or 0)) * loss_unit
            ).quantize(Decimal("0.01")),
            "shared_loss_amount": Decimal(r.shared_loss_amount or 0).quantize(Decimal("0.01")),
            "company_loss_amount": max(
                Decimal("0"),
                Decimal(int(r.defect_qty or 0)) * loss_unit - Decimal(r.shared_loss_amount or 0),
            ).quantize(Decimal("0.01")),
            "payable_amount": (
                Decimal(int(r.qty or 0)) * work_price - Decimal(r.shared_loss_amount or 0)
            ).quantize(Decimal("0.01")),
            "note": r.note,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
