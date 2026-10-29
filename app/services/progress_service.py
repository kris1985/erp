from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    ProcessSegment,
    WorkLog,
    WorkLogStatus,
)

from app.services.order_service import get_order_by_no


def order_progress(db: Session, tenant_id: int, order_no: str) -> dict:
    order = get_order_by_no(db, tenant_id, order_no)
    if not order:
        return {"error": f"找不到订单 {order_no}"}

    processes = []
    for p in sorted(order.processes, key=lambda x: x.id):
        pct = round(100 * p.completed_qty / p.plan_qty, 1) if p.plan_qty else 0
        processes.append(
            {
                "process_name": p.process_name,
                "plan_qty": p.plan_qty,
                "completed_qty": p.completed_qty,
                "defect_qty": p.defect_qty,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "percent": pct,
            }
        )

    overall = 0.0
    if processes:
        overall = round(sum(p["percent"] for p in processes) / len(processes), 1)

    lines = [f"订单 {order.order_no}（{order.customer_name}）总进度约 {overall}%"]
    for p in processes:
        lines.append(f"- {p['process_name']}: {p['completed_qty']}/{p['plan_qty']} ({p['percent']}%)")

    return {
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "status": order.status.value if hasattr(order.status, "value") else order.status,
        "total_qty": order.total_qty,
        "overall_percent": overall,
        "processes": processes,
        "message": "\n".join(lines),
    }


def today_output(
    db: Session,
    tenant_id: int,
    *,
    worker_ids: set[int] | list[int] | None = None,
) -> dict:
    today = datetime.utcnow().date()
    filters = [
        WorkLog.tenant_id == tenant_id,
        WorkLog.status == WorkLogStatus.valid,
        func.date(WorkLog.created_at) == today,
    ]
    if worker_ids is not None:
        ids = list(worker_ids) if not isinstance(worker_ids, list) else worker_ids
        if not ids:
            return {
                "date": today.isoformat(),
                "total_qualified": 0,
                "total_defect": 0,
                "by_process": [],
                "message": "今日暂无报工记录",
            }
        filters.append(WorkLog.worker_id.in_(ids))
    rows = db.execute(
        select(
            OrderProcess.process_name,
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
        )
        .join(OrderProcess, OrderProcess.id == WorkLog.order_process_id)
        .where(*filters)
        .group_by(OrderProcess.process_name)
    ).all()

    items = [
        {"process_name": name, "qualified_qty": int(q), "defect_qty": round(float(d), 2)}
        for name, q, d in rows
    ]
    total_q = sum(i["qualified_qty"] for i in items)
    total_d = sum(i["defect_qty"] for i in items)
    lines = [f"今日总产量：合格 {total_q}，不良 {total_d}"]
    for i in items:
        lines.append(f"- {i['process_name']}: 合格{i['qualified_qty']} 不良{i['defect_qty']}")

    return {
        "date": today.isoformat(),
        "total_qualified": total_q,
        "total_defect": total_d,
        "by_process": items,
        "message": "\n".join(lines) if items else "今日暂无报工记录",
    }


def slowest_orders(db: Session, tenant_id: int, limit: int = 5) -> dict:
    orders = db.scalars(
        select(Order)
        .where(Order.tenant_id == tenant_id)
        .options(selectinload(Order.processes))
        .order_by(Order.id.desc())
        .limit(50)
    ).all()
    ranked = []
    for order in orders:
        if not order.processes:
            continue
        pct = sum(
            (p.completed_qty / p.plan_qty * 100) if p.plan_qty else 0 for p in order.processes
        ) / len(order.processes)
        ranked.append((pct, order))
    ranked.sort(key=lambda x: x[0])
    top = ranked[:limit]
    lines = ["进度最慢订单："]
    items = []
    for pct, order in top:
        items.append(
            {"order_no": order.order_no, "percent": round(pct, 1), "customer_name": order.customer_name}
        )
        lines.append(f"- {order.order_no} {order.customer_name}: {pct:.1f}%")
    return {"items": items, "message": "\n".join(lines) if items else "暂无订单"}


def _segment_name(db, tenant_id: int, p: OrderProcess) -> str | None:
    """工序段重构（8.1）：段名（null=未分段 D18）。"""
    seg_id = getattr(p, "segment_id", None)
    if not seg_id:
        return "未分段"
    from app.models import ProcessSegment

    seg = db.get(ProcessSegment, int(seg_id))
    return seg.name if seg and seg.tenant_id == tenant_id else "未分段"


def _process_percent(p: OrderProcess) -> float:
    if not p.plan_qty:
        return 0.0
    return round(100 * p.completed_qty / p.plan_qty, 1)


def _is_completed(p: OrderProcess) -> bool:
    status = p.status.value if hasattr(p.status, "value") else str(p.status)
    return status == OrderProcessStatus.completed.value


def _bottleneck_process(processes: list[OrderProcess]) -> dict | None:
    """未完成工序中进度最低者；并列取剩余量最大。"""
    open_procs = [p for p in processes if not _is_completed(p)]
    if not open_procs:
        return None
    open_procs.sort(key=lambda p: (_process_percent(p), -(p.plan_qty - p.completed_qty)))
    p = open_procs[0]
    return {
        "process_name": p.process_name,
        "plan_qty": p.plan_qty,
        "completed_qty": p.completed_qty,
        "remain_qty": max(0, p.plan_qty - p.completed_qty),
        "percent": _process_percent(p),
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
    }


def progress_board(
    db: Session,
    tenant_id: int,
    *,
    order_ids: set[int] | list[int] | None = None,
    worker_ids: set[int] | list[int] | None = None,
) -> dict:
    """主管进度看板：今日产量 + 在制订单 + 工序瓶颈。"""
    today = today_output(db, tenant_id, worker_ids=worker_ids)
    open_statuses = (OrderStatus.confirmed, OrderStatus.in_progress)
    q = (
        select(Order)
        .where(Order.tenant_id == tenant_id, Order.status.in_(open_statuses))
        .options(selectinload(Order.processes))
        .order_by(Order.is_rush.desc(), Order.id.desc())
    )
    if order_ids is not None:
        ids = list(order_ids) if not isinstance(order_ids, list) else order_ids
        if not ids:
            return {
                "today": today,
                "summary": {
                    "open_orders": 0,
                    "at_risk_orders": 0,
                    "rush_orders": 0,
                    "bottleneck_processes": 0,
                },
                "orders": [],
                "bottlenecks": [],
                "charts": _board_charts(db, tenant_id, []),
            }
        q = q.where(Order.id.in_(ids))
    orders = db.scalars(q).all()

    order_rows = []
    bottleneck_agg: dict[str, dict] = {}
    at_risk = 0
    rush_count = 0
    soon = date.today() + timedelta(days=3)

    for order in orders:
        processes = sorted(order.processes, key=lambda x: x.id)
        pcts = [_process_percent(p) for p in processes]
        overall = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
        bottleneck = _bottleneck_process(processes)
        product = db.get(OwnProduct, order.own_product_id)
        delivery = order.delivery_date
        risk = bool(delivery and delivery <= soon and overall < 90)
        if risk:
            at_risk += 1
        is_rush = bool(getattr(order, "is_rush", False))
        if is_rush:
            rush_count += 1

        if bottleneck:
            name = bottleneck["process_name"]
            agg = bottleneck_agg.setdefault(
                name,
                {"process_name": name, "order_count": 0, "remain_qty": 0},
            )
            agg["order_count"] += 1
            agg["remain_qty"] += bottleneck["remain_qty"]

        order_rows.append(
            {
                "id": order.id,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "product_code": product.product_code if product else None,
                "total_qty": order.total_qty,
                "delivery_date": delivery.isoformat() if delivery else None,
                "status": order.status.value if hasattr(order.status, "value") else str(order.status),
                "overall_percent": overall,
                "bottleneck": bottleneck,
                "at_risk": risk,
                "is_rush": is_rush,
                "rush_reason": getattr(order, "rush_reason", None),
                "processes": [
                    {
                        "process_name": p.process_name,
                        "plan_qty": p.plan_qty,
                        "completed_qty": p.completed_qty,
                        "remain_qty": max(0, p.plan_qty - p.completed_qty),
                        "percent": _process_percent(p),
                        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                        # 工序段重构（8.1/D17）：段快照（null=未分段 D18）
                        "segment_id": getattr(p, "segment_id", None),
                        "segment_name": _segment_name(db, tenant_id, p),
                    }
                    for p in processes
                ],
            }
        )

    # 急单置顶，其次按进度/交期
    order_rows.sort(
        key=lambda r: (
            0 if r.get("is_rush") else 1,
            r["overall_percent"],
            r["delivery_date"] or "9999",
        )
    )

    bottlenecks = sorted(
        bottleneck_agg.values(),
        key=lambda x: (-x["order_count"], -x["remain_qty"]),
    )

    charts = _board_charts(db, tenant_id, order_rows)

    return {
        "today": today,
        "summary": {
            "open_orders": len(order_rows),
            "at_risk_orders": at_risk,
            "rush_orders": rush_count,
            "bottleneck_processes": len(bottlenecks),
            "today_qualified": today["total_qualified"],
            "today_defect": today["total_defect"],
        },
        "orders": order_rows,
        "bottlenecks": bottlenecks,
        "charts": charts,
        "message": (
            f"在制 {len(order_rows)} 单，急单 {rush_count}，交期风险 {at_risk} 单；"
            f"今日合格 {today['total_qualified']} / 不良 {today['total_defect']}"
        ),
    }


def _log_day(when: datetime | date | None) -> date | None:
    """与报工列表上的时间同一天，不再把日期换算到另一个时区。"""
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.date()
    return when


def _last_segments_by_route(db: Session, tenant_id: int) -> tuple[dict[int, int], dict[int, int]]:
    """每张单工艺路线里 sort_order 最大的工序段。有执行单头按头，否则按生产单。"""
    rows = db.execute(
        select(
            OrderProcess.header_id,
            OrderProcess.order_id,
            OrderProcess.segment_id,
            ProcessSegment.sort_order,
        )
        .join(ProcessSegment, ProcessSegment.id == OrderProcess.segment_id)
        .where(
            OrderProcess.tenant_id == tenant_id,
            OrderProcess.segment_id.is_not(None),
            ProcessSegment.tenant_id == tenant_id,
        )
    ).all()
    by_header: dict[int, tuple[tuple[int, int], int]] = {}
    by_order: dict[int, tuple[tuple[int, int], int]] = {}
    for header_id, order_id, segment_id, sort_order in rows:
        rank = (int(sort_order or 0), int(segment_id))
        sid = int(segment_id)
        if header_id:
            hid = int(header_id)
            prev = by_header.get(hid)
            if prev is None or rank > prev[0]:
                by_header[hid] = (rank, sid)
        elif order_id:
            oid = int(order_id)
            prev = by_order.get(oid)
            if prev is None or rank > prev[0]:
                by_order[oid] = (rank, sid)
    return (
        {key: value[1] for key, value in by_header.items()},
        {key: value[1] for key, value in by_order.items()},
    )


def _last_segment_trend(db: Session, tenant_id: int, start: date, today: date) -> list[dict]:
    """近 14 日产量。

    只认每张单最后一个工序段。同一工序当天的报工相加，再取各工序的最小值，
    这才是当天做完的双数。前面的工序段报了也不算产量；最后一段当天没报工就是 0。
    """
    by_header, by_order = _last_segments_by_route(db, tenant_id)
    by_day: dict[str, dict[str, int]] = {}
    if by_header or by_order:
        segment_id = func.coalesce(WorkLog.segment_id, OrderProcess.segment_id)
        logs = db.execute(
            select(
                WorkLog.header_id,
                WorkLog.order_id,
                segment_id,
                WorkLog.process_id,
                WorkLog.created_at,
                WorkLog.qualified_qty,
                WorkLog.defect_qty,
            )
            .join(OrderProcess, OrderProcess.id == WorkLog.order_process_id)
            .where(
                WorkLog.tenant_id == tenant_id,
                WorkLog.status == WorkLogStatus.valid,
                WorkLog.created_at >= datetime.combine(start, time.min),
                WorkLog.created_at < datetime.combine(today + timedelta(days=1), time.min),
            )
        ).all()
        # (day, route, process) -> 该工序当天合格/不良
        per_process: dict[tuple, dict[str, int]] = {}
        for header_id, order_id, seg_id, process_id, created_at, qualified, defect in logs:
            if seg_id is None:
                continue
            if header_id and int(header_id) in by_header:
                route = ("h", int(header_id))
                last_id = by_header[int(header_id)]
            elif order_id and int(order_id) in by_order:
                route = ("o", int(order_id))
                last_id = by_order[int(order_id)]
            else:
                continue
            if int(seg_id) != last_id:
                continue
            day = _log_day(created_at)
            if day is None or day < start or day > today:
                continue
            slot = per_process.setdefault((day.isoformat(), route, int(process_id or 0)), {"q": 0, "d": 0})
            slot["q"] += int(qualified or 0)
            slot["d"] += int(defect or 0)

        grouped: dict[tuple, list[dict[str, int]]] = {}
        for (day_key, route, _process_id), slot in per_process.items():
            grouped.setdefault((day_key, route), []).append(slot)
        for (day_key, _route), slots in grouped.items():
            reported = [slot for slot in slots if slot["q"] > 0]
            bucket = by_day.setdefault(day_key, {"qualified": 0, "defect": 0})
            if reported:
                bucket["qualified"] += min(slot["q"] for slot in reported)
            bucket["defect"] += sum(slot["d"] for slot in slots)

    trend = []
    for i in range((today - start).days + 1):
        key = (start + timedelta(days=i)).isoformat()
        row = by_day.get(key, {"qualified": 0, "defect": 0})
        trend.append({"date": key, "qualified": row["qualified"], "defect": row["defect"]})
    return trend


def _segment_daily_series(db: Session, tenant_id: int, start: date, today: date) -> dict:
    """近 N 日各工序段按天完工产量。

    口径与生产单工序段一致：段内各工序当天合格分别合计后取最小，
    当天没报的工序不参与；再把各生产单相加。
    """
    dates = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]
    segment_id_col = func.coalesce(WorkLog.segment_id, OrderProcess.segment_id)
    logs = db.execute(
        select(
            WorkLog.header_id,
            WorkLog.order_id,
            segment_id_col,
            WorkLog.process_id,
            WorkLog.created_at,
            WorkLog.qualified_qty,
        )
        .join(OrderProcess, OrderProcess.id == WorkLog.order_process_id)
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.created_at >= datetime.combine(start, time.min),
            WorkLog.created_at < datetime.combine(today + timedelta(days=1), time.min),
            WorkLog.qualified_qty > 0,
        )
    ).all()

    # day -> segment_id -> header_key -> process_id -> qty
    day_process: dict[str, dict[int, dict[str, dict[int, int]]]] = {}
    segment_ids: set[int] = set()
    for header_id, order_id, seg_id, process_id, created_at, qualified in logs:
        if seg_id is None:
            continue
        day = _log_day(created_at)
        if day is None or day < start or day > today:
            continue
        sid = int(seg_id)
        segment_ids.add(sid)
        header_key = f"h:{int(header_id)}" if header_id else f"o:{int(order_id or 0)}"
        pid = int(process_id or 0)
        bucket = (
            day_process.setdefault(day.isoformat(), {})
            .setdefault(sid, {})
            .setdefault(header_key, {})
        )
        bucket[pid] = bucket.get(pid, 0) + int(qualified or 0)

    segment_meta: dict[int, tuple[str, int]] = {}
    if segment_ids:
        for seg in db.scalars(
            select(ProcessSegment).where(
                ProcessSegment.tenant_id == tenant_id,
                ProcessSegment.id.in_(segment_ids),
            )
        ).all():
            segment_meta[int(seg.id)] = (
                seg.name or f"段{seg.id}",
                int(getattr(seg, "sort_order", None) or 999999),
            )

    ordered_segments = sorted(
        segment_ids,
        key=lambda sid: (segment_meta.get(sid, ("", 999999))[1], segment_meta.get(sid, ("", 0))[0], sid),
    )
    series = []
    for sid in ordered_segments:
        name, _sort = segment_meta.get(sid, (f"段{sid}", 999999))
        data = []
        for day_key in dates:
            completed = 0
            for process_map in (day_process.get(day_key, {}).get(sid) or {}).values():
                totals = [qty for qty in process_map.values() if qty > 0]
                if totals:
                    completed += min(totals)
            data.append(completed)
        series.append(
            {
                "segment_id": sid,
                "segment_name": name,
                "data": data,
            }
        )
    return {"dates": dates, "series": series}


def _board_charts(db: Session, tenant_id: int, open_order_rows: list[dict]) -> dict:
    """产量趋势、各段按天产量、交期风险分布。"""
    today = date.today()
    days = 14
    start = today - timedelta(days=days - 1)
    trend = _last_segment_trend(db, tenant_id, start, today)
    segment_daily = _segment_daily_series(db, tenant_id, start, today)

    # 交期风险分布（在制单）
    buckets = {
        "overdue": 0,
        "within_3_days": 0,
        "within_7_days": 0,
        "later": 0,
        "no_date": 0,
    }
    for row in open_order_rows:
        dd = row.get("delivery_date")
        if not dd:
            buckets["no_date"] += 1
            continue
        try:
            delivery = date.fromisoformat(dd)
        except ValueError:
            buckets["no_date"] += 1
            continue
        delta = (delivery - today).days
        if delta < 0:
            buckets["overdue"] += 1
        elif delta <= 3:
            buckets["within_3_days"] += 1
        elif delta <= 7:
            buckets["within_7_days"] += 1
        else:
            buckets["later"] += 1

    delivery_risk = [
        {"key": "overdue", "label": "已逾期", "count": buckets["overdue"]},
        {"key": "within_3_days", "label": "3天内", "count": buckets["within_3_days"]},
        {"key": "within_7_days", "label": "4–7天", "count": buckets["within_7_days"]},
        {"key": "later", "label": "7天以上", "count": buckets["later"]},
        {"key": "no_date", "label": "无交期", "count": buckets["no_date"]},
    ]

    return {
        "trend": trend,
        "segment_daily": segment_daily,
        "delivery_risk": delivery_risk,
    }
