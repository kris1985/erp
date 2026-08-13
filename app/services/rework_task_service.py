"""B1b：不良 → 个人返修任务。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessAssignment,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    ReworkTask,
    ReworkTaskStatus,
    Size,
    Worker,
)


class ReworkTaskError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _task_out(db: Session, t: ReworkTask) -> dict:
    order = db.get(Order, t.order_id) if t.order_id else None
    product = db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    if product is None and getattr(t, "header_id", None):
        header = db.get(ExecutionHeader, t.header_id)
        if header and header.own_product_id:
            product = db.get(OwnProduct, header.own_product_id)
    worker = db.get(Worker, t.worker_id)
    proc = db.get(ProcessDefinition, t.process_id)
    defect = db.get(DefectEvent, t.defect_event_id)
    color = db.get(Color, t.color_id) if t.color_id else None
    size = db.get(Size, t.size_id) if t.size_id else None
    header_no = None
    if getattr(t, "header_id", None):
        header = db.get(ExecutionHeader, t.header_id)
        header_no = header.header_no if header else None
    return {
        "id": t.id,
        "defect_event_id": t.defect_event_id,
        "order_id": t.order_id,
        "header_id": getattr(t, "header_id", None),
        "order_no": order.order_no if order else None,
        "header_no": header_no,
        "product_code": product.product_code if product else None,
        "process_id": t.process_id,
        "process_name": proc.name if proc else None,
        "worker_id": t.worker_id,
        "worker_name": worker.name if worker else None,
        "color_id": t.color_id,
        "color_name": color.name if color else None,
        "size_id": t.size_id,
        "size_value": size.size_value if size else None,
        "qty": t.qty,
        "status": _enum_val(t.status),
        "note": t.note,
        "defect_type": defect.defect_type if defect else None,
        "defect_status": _enum_val(defect.status) if defect else None,
        "completed_work_log_id": t.completed_work_log_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


def _ensure_personal_assignment(
    db: Session,
    tenant_id: int,
    *,
    order: Order | None,
    header_id: int | None,
    process_def_id: int,
    worker_id: int,
) -> OrderProcess:
    if order is not None:
        op = db.scalar(
            select(OrderProcess).where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.order_id == order.id,
                OrderProcess.process_id == process_def_id,
            )
        )
    elif header_id is not None:
        from app.services.material_service import list_header_processes

        op = next(
            (
                p
                for p in list_header_processes(db, tenant_id, header_id)
                if p.process_id == process_def_id
            ),
            None,
        )
        if op is None:
            op = db.scalar(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id,
                    OrderProcess.header_id == header_id,
                    OrderProcess.process_id == process_def_id,
                )
            )
    else:
        raise ReworkTaskError("order_not_found", "生产单/执行单不存在")

    if not op:
        raise ReworkTaskError("process_not_on_order", "该生产单无此工序，无法派返修")
    ptype = op.process_type
    if hasattr(ptype, "value"):
        ptype = ptype.value
    if ptype == ProcessType.group.value or ptype == "group":
        raise ReworkTaskError("group_rework_forbidden", "集体工序不支持派返修（政策禁区）")
    exists = db.scalar(
        select(OrderProcessAssignment).where(
            OrderProcessAssignment.tenant_id == tenant_id,
            OrderProcessAssignment.order_process_id == op.id,
            OrderProcessAssignment.worker_id == worker_id,
        )
    )
    if not exists:
        db.add(
            OrderProcessAssignment(
                tenant_id=tenant_id,
                order_id=order.id if order else getattr(op, "order_id", None),
                header_id=header_id or getattr(op, "header_id", None),
                order_process_id=op.id,
                worker_id=worker_id,
                quota_qty=None,
            )
        )
        db.flush()
    return op


def create_rework_task(
    db: Session,
    tenant_id: int,
    defect_id: int,
    *,
    worker_id: int,
    process_id: int | None = None,
    qty: int | None = None,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    defect = db.get(DefectEvent, defect_id)
    if not defect or defect.tenant_id != tenant_id:
        raise ReworkTaskError("defect_not_found", "不良事件不存在")
    if defect.status == DefectEventStatus.closed:
        raise ReworkTaskError("defect_closed", "不良已关闭，无法派返修")

    worker = db.get(Worker, worker_id)
    if not worker or worker.tenant_id != tenant_id or not worker.is_active:
        raise ReworkTaskError("worker_not_found", "返修工人不存在或未启用")

    proc_id = process_id or defect.responsible_process_id or defect.found_process_id
    if not proc_id:
        raise ReworkTaskError("process_required", "请指定返修工序")
    proc = db.get(ProcessDefinition, proc_id)
    if not proc or proc.tenant_id != tenant_id:
        raise ReworkTaskError("process_not_found", "工序不存在")
    if proc.type == ProcessType.group or (hasattr(proc.type, "value") and proc.type.value == "group"):
        raise ReworkTaskError("group_rework_forbidden", "集体工序不支持派返修（政策禁区）")

    pending = db.scalar(
        select(ReworkTask).where(
            ReworkTask.tenant_id == tenant_id,
            ReworkTask.defect_event_id == defect_id,
            ReworkTask.status == ReworkTaskStatus.pending,
        )
    )
    if pending:
        raise ReworkTaskError("already_pending", f"该不良已有未完成返修任务 #{pending.id}")

    order = db.get(Order, defect.order_id) if defect.order_id else None
    if defect.order_id and (not order or order.tenant_id != tenant_id):
        raise ReworkTaskError("order_not_found", "生产单不存在")

    header_id = getattr(defect, "header_id", None)
    if not order and not header_id:
        raise ReworkTaskError("order_not_found", "生产单/执行单不存在")

    task_qty = int(qty if qty is not None else defect.qty or 1)
    if task_qty <= 0:
        raise ReworkTaskError("invalid_qty", "返修数量须大于 0")

    _ensure_personal_assignment(
        db,
        tenant_id,
        order=order,
        header_id=header_id,
        process_def_id=proc_id,
        worker_id=worker_id,
    )

    if defect.disposition != DefectDisposition.rework:
        defect.disposition = DefectDisposition.rework

    task = ReworkTask(
        tenant_id=tenant_id,
        defect_event_id=defect.id,
        order_id=order.id if order else None,
        header_id=header_id,
        process_id=proc_id,
        worker_id=worker_id,
        color_id=defect.color_id,
        size_id=defect.size_id,
        qty=task_qty,
        status=ReworkTaskStatus.pending,
        note=note,
        created_by=created_by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


def list_rework_tasks(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = "pending",
    order_no: str | None = None,
    worker_id: int | None = None,
    defect_event_id: int | None = None,
    header_id: int | None = None,
) -> list[dict]:
    q = select(ReworkTask).where(ReworkTask.tenant_id == tenant_id)
    if status:
        if status not in ReworkTaskStatus.__members__:
            raise ReworkTaskError("invalid_status", "状态无效")
        q = q.where(ReworkTask.status == ReworkTaskStatus(status))
    if worker_id:
        q = q.where(ReworkTask.worker_id == worker_id)
    if defect_event_id:
        q = q.where(ReworkTask.defect_event_id == defect_event_id)
    if header_id:
        q = q.where(ReworkTask.header_id == header_id)
    if order_no and order_no.strip():
        # outerjoin：无壳任务 order_id 为空时不被误伤；按单号筛仍只命中有壳行
        q = q.outerjoin(Order, Order.id == ReworkTask.order_id).where(
            Order.order_no.contains(order_no.strip())
        )
    rows = list(db.scalars(q.order_by(ReworkTask.id.desc())).all())
    return [_task_out(db, t) for t in rows]


def complete_rework_task(
    db: Session,
    tenant_id: int,
    task_id: int,
    *,
    work_log_id: int | None = None,
    close_defect: bool = True,
    note: str | None = None,
) -> dict:
    task = db.get(ReworkTask, task_id)
    if not task or task.tenant_id != tenant_id:
        raise ReworkTaskError("not_found", "返修任务不存在")
    if task.status != ReworkTaskStatus.pending:
        raise ReworkTaskError("not_pending", "任务已结束")
    task.status = ReworkTaskStatus.done
    task.completed_at = datetime.utcnow()
    if work_log_id:
        task.completed_work_log_id = work_log_id
    if note:
        task.note = ((task.note or "") + "；" + note).strip("；")
    if close_defect:
        defect = db.get(DefectEvent, task.defect_event_id)
        if defect and defect.status != DefectEventStatus.closed:
            defect.status = DefectEventStatus.closed
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


def cancel_rework_task(db: Session, tenant_id: int, task_id: int, *, note: str | None = None) -> dict:
    task = db.get(ReworkTask, task_id)
    if not task or task.tenant_id != tenant_id:
        raise ReworkTaskError("not_found", "返修任务不存在")
    if task.status != ReworkTaskStatus.pending:
        raise ReworkTaskError("not_pending", "任务已结束")
    task.status = ReworkTaskStatus.cancelled
    task.completed_at = datetime.utcnow()
    if note:
        task.note = ((task.note or "") + "；" + note).strip("；")
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


def try_complete_on_rework_report(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    header_id: int | None = None,
    process_def_id: int,
    worker_id: int,
    work_log_id: int | None,
    qty: int,
) -> dict | None:
    """返修报工成功后：匹配最早一条 pending 任务并完成。"""
    if qty <= 0:
        return None
    q = select(ReworkTask).where(
        ReworkTask.tenant_id == tenant_id,
        ReworkTask.process_id == process_def_id,
        ReworkTask.worker_id == worker_id,
        ReworkTask.status == ReworkTaskStatus.pending,
    )
    if order_id:
        q = q.where(ReworkTask.order_id == order_id)
    elif header_id:
        q = q.where(ReworkTask.header_id == header_id)
    else:
        return None
    task = db.scalar(q.order_by(ReworkTask.id.asc()).limit(1))
    if not task:
        return None
    return complete_rework_task(
        db,
        tenant_id,
        task.id,
        work_log_id=work_log_id,
        close_defect=True,
        note=f"返修报工自动完成×{qty}",
    )
