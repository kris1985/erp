from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Order, OrderProcess, WorkLog, WorkLogStatus
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


def today_output(db: Session, tenant_id: int) -> dict:
    today = datetime.utcnow().date()
    rows = db.execute(
        select(
            OrderProcess.process_name,
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
        )
        .join(OrderProcess, OrderProcess.id == WorkLog.order_process_id)
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.status == WorkLogStatus.valid,
            func.date(WorkLog.created_at) == today,
        )
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
        items.append({"order_no": order.order_no, "percent": round(pct, 1), "customer_name": order.customer_name})
        lines.append(f"- {order.order_no} {order.customer_name}: {pct:.1f}%")
    return {"items": items, "message": "\n".join(lines) if items else "暂无订单"}
