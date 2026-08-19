from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Order, OrderProcess, OrderProcessStatus, OrderStatus, OwnProduct, WorkLog, WorkLogStatus
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
        {"process_name": name, "qualified_qty": int(q), "defect_qty": int(d)} for name, q, d in rows
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


def _board_charts(db: Session, tenant_id: int, open_order_rows: list[dict]) -> dict:
    """产量趋势、工序对比、交期风险分布。"""
    today = date.today()
    days = 14
    start = today - timedelta(days=days - 1)

    # 日产量趋势
    trend_rows = db.execute(
        select(
            func.date(WorkLog.created_at),
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
        )
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            func.date(WorkLog.created_at) >= start,
        )
        .group_by(func.date(WorkLog.created_at))
    ).all()
    by_day = {}
    for d, q, defect in trend_rows:
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]
        by_day[key] = {"qualified": int(q), "defect": int(defect)}

    trend = []
    for i in range(days):
        d = start + timedelta(days=i)
        key = d.isoformat()
        row = by_day.get(key, {"qualified": 0, "defect": 0})
        trend.append({"date": key, "qualified": row["qualified"], "defect": row["defect"]})

    # 近 7 日分工序产量（产能对比）
    week_start = today - timedelta(days=6)
    process_rows = db.execute(
        select(
            OrderProcess.process_name,
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
        )
        .join(OrderProcess, OrderProcess.id == WorkLog.order_process_id)
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            func.date(WorkLog.created_at) >= week_start,
        )
        .group_by(OrderProcess.process_name)
        .order_by(func.coalesce(func.sum(WorkLog.qualified_qty), 0).desc())
    ).all()
    process_bars = [
        {"process_name": name, "qualified_qty": int(q)} for name, q in process_rows
    ]

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
        "process_bars": process_bars,
        "delivery_risk": delivery_risk,
    }
