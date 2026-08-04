from datetime import datetime
from decimal import Decimal

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.models import (
    Order,
    PriceType,
    ProcessDefinition,
    Style,
    StyleProcessRoute,
    WorkLog,
    WorkLogStatus,
    Worker,
)


def month_salary(db: Session, tenant_id: int, worker_id: int, year_month: str | None = None) -> dict:
    worker = db.get(Worker, worker_id)
    if not worker or worker.tenant_id != tenant_id:
        return {"error": "工人不存在"}

    if not year_month:
        now = datetime.utcnow()
        year_month = f"{now.year:04d}-{now.month:02d}"
    year, month = map(int, year_month.split("-"))

    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.worker_id == worker_id,
            WorkLog.status == WorkLogStatus.valid,
            extract("year", WorkLog.created_at) == year,
            extract("month", WorkLog.created_at) == month,
        )
    ).all()

    details = []
    total = Decimal("0")
    for log in logs:
        order = db.get(Order, log.order_id)
        style = db.get(Style, log.style_id)
        process = db.get(ProcessDefinition, log.process_id)
        route = db.scalar(
            select(StyleProcessRoute).where(
                StyleProcessRoute.tenant_id == tenant_id,
                StyleProcessRoute.style_id == log.style_id,
                StyleProcessRoute.process_id == log.process_id,
                StyleProcessRoute.price_type == PriceType.normal,
                StyleProcessRoute.is_active.is_(True),
            )
        )
        price = Decimal(route.price) if route else Decimal("0")
        amount = price * Decimal(log.qualified_qty)
        total += amount
        details.append(
            {
                "work_log_id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "order_no": order.order_no if order else None,
                "style_name": style.style_name if style else None,
                "process_name": process.name if process else None,
                "qualified_qty": log.qualified_qty,
                "defect_qty": log.defect_qty,
                "unit_price": float(price),
                "amount": float(amount),
            }
        )

    return {
        "worker_id": worker_id,
        "worker_name": worker.name,
        "year_month": year_month,
        "details": details,
        "total_piece_wage": float(total),
        "message": f"{worker.name} {year_month} 计件明细共 {len(details)} 条，暂估合计 ¥{total:.2f}",
    }
