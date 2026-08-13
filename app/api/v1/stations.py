import io
from datetime import date

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_worker, require_roles
from app.db import get_db
from app.models import (
    Color,
    Order,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessStatus,
    OrderStatus,
    ProcessDefinition,
    Size,
    Station,
    User,
    WorkLog,
    WorkLogStatus,
    Worker,
)
from app.schemas.api import StationCreate, StationOut, StationReportCandidate, StationReportSku, StationUpdate
from app.schemas.common import ok
from app.services.assignment_service import worker_can_report_remaining

router = APIRouter(prefix="/stations", tags=["stations"])


def _station_out(db: Session, s: Station, request: Request | None = None) -> dict:
    process = db.get(ProcessDefinition, s.process_id)
    scan_path = f"/scan/{s.code}"
    return StationOut(
        id=s.id,
        code=s.code,
        name=s.name,
        process_id=s.process_id,
        process_name=process.name if process else None,
        process_type=(
            process.type.value if process and hasattr(process.type, "value") else (str(process.type) if process else None)
        ),
        location=s.location,
        is_active=s.is_active,
        scan_path=scan_path,
    ).model_dump()


@router.get("")
def list_stations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Station).where(Station.tenant_id == user.tenant_id).order_by(Station.id.desc())
    ).all()
    return ok({"items": [_station_out(db, s) for s in rows], "total": len(rows)})


@router.post("")
def create_station(
    body: StationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    code = body.code.strip().upper()
    exists = db.scalar(select(Station).where(Station.tenant_id == user.tenant_id, Station.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="工位编码已存在")
    process = db.get(ProcessDefinition, body.process_id)
    if not process or process.tenant_id != user.tenant_id:
        raise HTTPException(status_code=400, detail="工序不存在")
    s = Station(
        tenant_id=user.tenant_id,
        code=code,
        name=body.name.strip(),
        process_id=body.process_id,
        location=body.location,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(_station_out(db, s))


@router.patch("/{station_id}")
def update_station(
    station_id: int,
    body: StationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    s = db.get(Station, station_id)
    if not s or s.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工位不存在")
    data = body.model_dump(exclude_unset=True)
    if "process_id" in data:
        process = db.get(ProcessDefinition, data["process_id"])
        if not process or process.tenant_id != user.tenant_id:
            raise HTTPException(status_code=400, detail="工序不存在")
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return ok(_station_out(db, s))


def _get_active_station_by_code(db: Session, code: str) -> Station:
    s = db.scalar(select(Station).where(Station.code == code.strip().upper(), Station.is_active.is_(True)))
    if not s:
        s = db.scalar(select(Station).where(Station.code == code.strip(), Station.is_active.is_(True)))
    if not s:
        raise HTTPException(status_code=404, detail="工位不存在或已停用")
    return s


@router.get("/by-code/{code}")
def get_station_by_code(code: str, db: Session = Depends(get_db)):
    """扫码页公开读取工位信息（报工仍需登录）。"""
    return ok(_station_out(db, _get_active_station_by_code(db, code)))


@router.get("/by-code/{code}/report-candidates")
def station_report_candidates(
    code: str,
    db: Session = Depends(get_db),
    worker: Worker = Depends(get_current_worker),
):
    """扫码报工候选单：仅派给当前工人且仍有剩余配额的同工序在制单，最近报工优先。"""
    from app.models import ExecutionHeader, SalesOrder, SpecExecutionOrder, SpecExecutionStatus

    station = _get_active_station_by_code(db, code)
    if station.tenant_id != worker.tenant_id:
        raise HTTPException(status_code=404, detail="工位不存在或已停用")

    open_order_status = (OrderStatus.confirmed, OrderStatus.in_progress)
    open_process_status = (OrderProcessStatus.pending, OrderProcessStatus.in_progress)
    open_header_status = (SpecExecutionStatus.confirmed, SpecExecutionStatus.in_progress)

    rows = db.execute(
        select(Order, OrderProcess)
        .join(OrderProcess, OrderProcess.order_id == Order.id)
        .join(
            OrderProcessAssignment,
            OrderProcessAssignment.order_process_id == OrderProcess.id,
        )
        .where(
            Order.tenant_id == worker.tenant_id,
            Order.status.in_(open_order_status),
            OrderProcess.process_id == station.process_id,
            OrderProcess.status.in_(open_process_status),
            OrderProcessAssignment.worker_id == worker.id,
        )
        .distinct()
    ).all()

    # K4-C：无桥接壳执行单工序（OrderProcess.header_id）
    header_rows = db.execute(
        select(ExecutionHeader, OrderProcess)
        .join(OrderProcess, OrderProcess.header_id == ExecutionHeader.id)
        .join(
            OrderProcessAssignment,
            OrderProcessAssignment.order_process_id == OrderProcess.id,
        )
        .where(
            ExecutionHeader.tenant_id == worker.tenant_id,
            ExecutionHeader.status.in_(open_header_status),
            OrderProcess.order_id.is_(None),
            OrderProcess.process_id == station.process_id,
            OrderProcess.status.in_(open_process_status),
            OrderProcessAssignment.worker_id == worker.id,
        )
        .distinct()
    ).all()

    # 配额用尽（含收回剩余锁到已报）的不进候选
    filtered: list[tuple[Order, OrderProcess, int | None]] = []
    filtered_headers: list[tuple[ExecutionHeader, OrderProcess, int | None]] = []
    seen_process: set[int] = set()
    for order, process in rows:
        if process.id in seen_process:
            continue
        seen_process.add(process.id)
        can_report, remaining = worker_can_report_remaining(db, process.id, worker.id)
        if not can_report:
            continue
        filtered.append((order, process, remaining))

    for header, process in header_rows:
        if process.id in seen_process:
            continue
        seen_process.add(process.id)
        can_report, remaining = worker_can_report_remaining(db, process.id, worker.id)
        if not can_report:
            continue
        filtered_headers.append((header, process, remaining))

    last_by_order: dict[int, object] = {}
    last_sku_by_order: dict[int, tuple[str | None, str | None]] = {}
    if filtered:
        order_ids = [o.id for o, _, _ in filtered]
        logs = db.scalars(
            select(WorkLog)
            .where(
                WorkLog.tenant_id == worker.tenant_id,
                WorkLog.worker_id == worker.id,
                WorkLog.process_id == station.process_id,
                WorkLog.order_id.in_(order_ids),
                WorkLog.status == WorkLogStatus.valid,
            )
            .order_by(WorkLog.created_at.desc())
        ).all()
        for log in logs:
            if log.order_id not in last_by_order:
                last_by_order[log.order_id] = log.created_at
                color = db.get(Color, log.color_id) if log.color_id else None
                size = db.get(Size, log.size_id) if log.size_id else None
                last_sku_by_order[log.order_id] = (
                    color.name if color else None,
                    size.size_value if size else None,
                )

    last_by_header: dict[int, object] = {}
    last_sku_by_header: dict[int, tuple[str | None, str | None]] = {}
    if filtered_headers:
        header_ids = [h.id for h, _, _ in filtered_headers]
        hlogs = db.scalars(
            select(WorkLog)
            .where(
                WorkLog.tenant_id == worker.tenant_id,
                WorkLog.worker_id == worker.id,
                WorkLog.process_id == station.process_id,
                WorkLog.header_id.in_(header_ids),
                WorkLog.status == WorkLogStatus.valid,
            )
            .order_by(WorkLog.created_at.desc())
        ).all()
        for log in hlogs:
            hid = int(log.header_id)
            if hid not in last_by_header:
                last_by_header[hid] = log.created_at
                color = db.get(Color, log.color_id) if log.color_id else None
                size = db.get(Size, log.size_id) if log.size_id else None
                last_sku_by_header[hid] = (
                    color.name if color else None,
                    size.size_value if size else None,
                )

    items: list[StationReportCandidate] = []
    order_meta: dict[int, Order] = {}
    header_meta: dict[int, ExecutionHeader] = {}
    for order, process, remaining in filtered:
        order_meta[order.id] = order
        sku_items: list[StationReportSku] = []
        for it in order.items or []:
            color = db.get(Color, it.color_id) if it.color_id else None
            size = db.get(Size, it.size_id) if it.size_id else None
            sku_items.append(
                StationReportSku(
                    color_id=it.color_id,
                    color_name=color.name if color else None,
                    size_id=it.size_id,
                    size_value=size.size_value if size else None,
                    qty=it.qty,
                )
            )
        last_color, last_size = last_sku_by_order.get(order.id, (None, None))
        items.append(
            StationReportCandidate(
                order_id=order.id,
                order_no=order.order_no,
                header_id=None,
                customer_name=order.customer_name,
                plan_qty=process.plan_qty,
                completed_qty=process.completed_qty,
                status=order.status.value if hasattr(order.status, "value") else str(order.status),
                process_status=(
                    process.status.value if hasattr(process.status, "value") else str(process.status)
                ),
                assigned_to_me=True,
                last_reported_at=last_by_order.get(order.id),
                items=sku_items,
                last_color_name=last_color,
                last_size_value=last_size,
                remaining_quota=remaining,
            )
        )

    for header, process, remaining in filtered_headers:
        header_meta[header.id] = header
        sku_items = []
        exe_rows = list(
            db.scalars(
                select(SpecExecutionOrder)
                .where(
                    SpecExecutionOrder.header_id == header.id,
                    SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
                )
                .order_by(SpecExecutionOrder.id)
            ).all()
        )
        for exe in exe_rows:
            color = db.get(Color, exe.color_id or header.color_id) if (exe.color_id or header.color_id) else None
            size = db.get(Size, exe.size_id) if exe.size_id else None
            sku_items.append(
                StationReportSku(
                    color_id=exe.color_id or header.color_id,
                    color_name=color.name if color else None,
                    size_id=exe.size_id,
                    size_value=size.size_value if size else None,
                    qty=int(exe.total_qty or 0),
                )
            )
        so = db.get(SalesOrder, header.sales_order_id) if header.sales_order_id else None
        last_color, last_size = last_sku_by_header.get(header.id, (None, None))
        items.append(
            StationReportCandidate(
                order_id=None,
                order_no=header.header_no,
                header_id=header.id,
                customer_name=so.customer_name if so else None,
                plan_qty=process.plan_qty,
                completed_qty=process.completed_qty,
                status=header.status.value if hasattr(header.status, "value") else str(header.status),
                process_status=(
                    process.status.value if hasattr(process.status, "value") else str(process.status)
                ),
                assigned_to_me=True,
                last_reported_at=last_by_header.get(header.id),
                items=sku_items,
                last_color_name=last_color,
                last_size_value=last_size,
                remaining_quota=remaining,
            )
        )

    def _sort_key(c: StationReportCandidate):
        last = c.last_reported_at
        last_ts = 0.0
        if last is not None:
            last_ts = last.timestamp() if hasattr(last, "timestamp") else 0.0
        if c.header_id and c.header_id in header_meta:
            h = header_meta[c.header_id]
            delivery = h.delivery_date or date.max
            created = h.created_at
            tie = c.header_id
        else:
            o = order_meta[c.order_id]
            delivery = o.delivery_date or date.max
            created = o.created_at
            tie = c.order_id or 0
        return (
            0 if last is not None else 1,
            -last_ts,
            delivery,
            created,
            tie,
        )

    items.sort(key=_sort_key)
    payload = [i.model_dump(mode="json") for i in items]
    return ok(
        {
            "items": payload,
            "total": len(payload),
            "default_order_no": payload[0]["order_no"] if payload else None,
            "station": _station_out(db, station),
        }
    )


def _qr_png_bytes(url: str) -> bytes:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/by-code/{code}/qr.png")
def station_qr_png_by_code(code: str, request: Request, db: Session = Depends(get_db)):
    """公开二维码图（方便打印预览；内容为扫码页 URL）。"""
    s = db.scalar(select(Station).where(Station.code == code.strip().upper(), Station.is_active.is_(True)))
    if not s:
        raise HTTPException(status_code=404, detail="工位不存在或已停用")
    base = str(request.base_url).rstrip("/")
    url = f"{base}/scan/{s.code}"
    return Response(
        content=_qr_png_bytes(url),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="station_{s.code}.png"'},
    )


@router.get("/{station_id}/qr.png")
def station_qr_png(
    station_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = db.get(Station, station_id)
    if not s or s.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工位不存在")
    base = str(request.base_url).rstrip("/")
    url = f"{base}/scan/{s.code}"
    return Response(
        content=_qr_png_bytes(url),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="station_{s.code}.png"'},
    )


@router.get("/{station_id}/qr-url")
def station_qr_url(
    station_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = db.get(Station, station_id)
    if not s or s.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工位不存在")
    base = str(request.base_url).rstrip("/")
    return ok({"url": f"{base}/scan/{s.code}", "code": s.code, "scan_path": f"/scan/{s.code}"})
