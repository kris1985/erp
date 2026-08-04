from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    PriceType,
    Size,
    StyleProcessRoute,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Worker,
)
from app.services.order_service import get_order_by_no


class ReportError(Exception):
    def __init__(self, code: str, message: str, need_confirm: bool = False, data: dict | None = None):
        self.code = code
        self.message = message
        self.need_confirm = need_confirm
        self.data = data or {}
        super().__init__(message)


def _resolve_color(db: Session, tenant_id: int, color_name: str | None) -> Color | None:
    if not color_name:
        return None
    return db.scalar(
        select(Color).where(Color.tenant_id == tenant_id, Color.name == color_name.strip())
    )


def _resolve_size(db: Session, tenant_id: int, size_value: str | None) -> Size | None:
    if not size_value:
        return None
    value = size_value.strip().replace("码", "")
    return db.scalar(select(Size).where(Size.tenant_id == tenant_id, Size.size_value == value))


def submit_report(
    db: Session,
    *,
    tenant_id: int,
    worker_id: int,
    order_no: str,
    process_name: str,
    qualified_qty: int,
    defect_qty: int = 0,
    color_name: str | None = None,
    size_value: str | None = None,
    original_text: str | None = None,
    source: str = "manual",
    confirm_over_plan: bool = False,
) -> dict:
    if qualified_qty < 0 or defect_qty < 0:
        raise ReportError("invalid_qty", "数量不能为负")
    if qualified_qty == 0 and defect_qty == 0:
        raise ReportError("empty_qty", "请填写合格或不良数量")

    worker = db.get(Worker, worker_id)
    if not worker or worker.tenant_id != tenant_id or not worker.is_active:
        raise ReportError("worker_not_found", "工人不存在或未启用")

    order = get_order_by_no(db, tenant_id, order_no)
    if not order:
        raise ReportError("order_not_found", f"找不到订单 {order_no}")

    process = next((p for p in order.processes if p.process_name == process_name), None)
    if not process:
        # fuzzy contains
        process = next((p for p in order.processes if process_name in p.process_name), None)
    if not process:
        names = "、".join(p.process_name for p in order.processes)
        raise ReportError("process_not_found", f"订单无此工序，可选：{names}")

    color = _resolve_color(db, tenant_id, color_name)
    if color_name and not color:
        raise ReportError("color_not_found", f"颜色不存在：{color_name}")
    size = _resolve_size(db, tenant_id, size_value)
    if size_value and not size:
        raise ReportError("size_not_found", f"尺码不存在：{size_value}")

    new_completed = process.completed_qty + qualified_qty
    if new_completed > process.plan_qty and not confirm_over_plan:
        raise ReportError(
            "over_plan",
            f"{process.process_name}计划{process.plan_qty}，已完成{process.completed_qty}，"
            f"本次再报{qualified_qty}将超额，确认继续吗？",
            need_confirm=True,
            data={
                "order_no": order_no,
                "process_name": process.process_name,
                "qualified_qty": qualified_qty,
                "defect_qty": defect_qty,
                "color_name": color_name,
                "size_value": size_value,
                "worker_id": worker_id,
            },
        )

    source_enum = WorkLogSource(source) if source in WorkLogSource.__members__ else WorkLogSource.manual
    log = WorkLog(
        tenant_id=tenant_id,
        worker_id=worker_id,
        order_id=order.id,
        order_process_id=process.id,
        style_id=order.style_id,
        process_id=process.process_id,
        color_id=color.id if color else None,
        size_id=size.id if size else None,
        report_type="normal",
        qualified_qty=qualified_qty,
        defect_qty=defect_qty,
        rework_qty=0,
        original_text=original_text,
        source=source_enum,
        status=WorkLogStatus.valid,
    )
    db.add(log)

    if process.actual_start is None:
        process.actual_start = datetime.utcnow()
    process.completed_qty = new_completed
    process.defect_qty += defect_qty
    if process.status == OrderProcessStatus.pending:
        process.status = OrderProcessStatus.in_progress
    if process.completed_qty >= process.plan_qty:
        process.status = OrderProcessStatus.completed
        process.actual_end = datetime.utcnow()

    if order.status == OrderStatus.confirmed:
        order.status = OrderStatus.in_progress
    if all(p.status == OrderProcessStatus.completed for p in order.processes):
        order.status = OrderStatus.completed

    if size:
        item = next(
            (
                i
                for i in order.items
                if i.size_id == size.id and ((color is None and i.color_id is None) or (color and i.color_id == color.id))
            ),
            None,
        )
        if item is None:
            item = next((i for i in order.items if i.size_id == size.id), None)
        if item:
            item.completed_qty += qualified_qty

    route = db.scalar(
        select(StyleProcessRoute).where(
            StyleProcessRoute.tenant_id == tenant_id,
            StyleProcessRoute.style_id == order.style_id,
            StyleProcessRoute.process_id == process.process_id,
            StyleProcessRoute.price_type == PriceType.normal,
            StyleProcessRoute.is_active.is_(True),
        )
    )
    unit_price = Decimal(route.price) if route else Decimal("0")
    amount = unit_price * Decimal(qualified_qty)

    db.commit()
    db.refresh(log)

    return {
        "work_log_id": log.id,
        "order_no": order.order_no,
        "process_name": process.process_name,
        "qualified_qty": qualified_qty,
        "defect_qty": defect_qty,
        "process_completed": process.completed_qty,
        "process_plan": process.plan_qty,
        "unit_price": float(unit_price),
        "amount": float(amount),
        "message": (
            f"报工成功：{order.order_no} {process.process_name} 合格{qualified_qty}"
            + (f" 不良{defect_qty}" if defect_qty else "")
            + f"；工序累计 {process.completed_qty}/{process.plan_qty}，本次约 ¥{amount:.2f}"
        ),
    }
