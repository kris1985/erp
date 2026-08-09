"""A2f：计件/成本异常核对（月底对账初筛）。

只做「高亮」，不重做工资引擎：直接复用 work_logs / order_processes / own_product_labors /
salary_service 的月结锁定信息计算异常原因，不改任何计薪口径。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Order,
    OrderProcess,
    OwnProduct,
    ProcessDefinition,
    ReportType,
    WorkLog,
    WorkLogStatus,
    Worker,
)
from app.services.order_service import get_labor_unit_price
from app.services.salary_service import is_month_locked, year_month_of

# 锁价与工序现价比值超出此区间视为「单价异常」
PRICE_RATIO_LOW = Decimal("0.5")
PRICE_RATIO_HIGH = Decimal("2.0")

REASON_LABELS = {
    "qty_over_plan": "单笔超计划",
    "process_over_plan": "工序累计超计划",
    "price_outlier": "单价异常",
    "void_in_locked_month": "已锁定月作废",
}


def _report_type(log: WorkLog) -> ReportType:
    return log.report_type if isinstance(log.report_type, ReportType) else ReportType(str(log.report_type))


def _price_reference(db: Session, tenant_id: int, log: WorkLog) -> Decimal | None:
    """工序当前参考单价：产品工序报价优先，否则工序默认价。"""
    ref = get_labor_unit_price(db, tenant_id, log.own_product_id, log.process_id)
    if ref and ref > 0:
        return ref
    proc = db.get(ProcessDefinition, log.process_id)
    if proc and proc.default_price and proc.default_price > 0:
        return Decimal(str(proc.default_price))
    return None


def list_anomalies(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """返回时间窗内异常报工行（月底核对用）。

    规则（均可解释，非黑盒）：
    1. qty_over_plan：单笔合格/计件数量本身就超过该工序计划量（多半是数据录入错）
    2. process_over_plan：该工序累计完成量已超计划量（复用 order_processes.completed_qty，
       不重算）；代表行取该工序范围内最新一笔正常有效报工
    3. price_outlier：报工锁定单价偏离当前工序参考单价（产品工序报价/工序默认价）超过
       0.5～2.0 倍区间
    4. void_in_locked_month：该报工已作废，但所在月份当前处于月结锁定 —— 提示核实是否
       已经发放工资却又作废
    """
    q = select(WorkLog).where(WorkLog.tenant_id == tenant_id)
    if date_from:
        q = q.where(WorkLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(
            WorkLog.created_at < datetime.combine(date_to, datetime.min.time()) + timedelta(days=1)
        )
    logs = db.scalars(q.order_by(WorkLog.id.asc())).all()

    process_cache: dict[int, OrderProcess | None] = {}
    # order_process_id -> 该工序范围内最新一笔正常有效报工 id（累计超量的代表行）
    latest_over_log_id: dict[int, int] = {}
    reasons_by_log: dict[int, list[dict[str, str]]] = {}

    for log in logs:
        reasons: list[dict[str, str]] = []
        rt = _report_type(log)
        is_rework = rt == ReportType.rework
        is_void = log.status == WorkLogStatus.void
        qty = int((log.rework_qty if is_rework else log.qualified_qty) or 0)

        op_id = log.order_process_id
        if op_id not in process_cache:
            process_cache[op_id] = db.get(OrderProcess, op_id)
        order_process = process_cache[op_id]
        plan_qty = int(order_process.plan_qty) if order_process and order_process.plan_qty else 0

        if not is_void and not is_rework and plan_qty:
            if qty > plan_qty:
                reasons.append(
                    {
                        "code": "qty_over_plan",
                        "text": f"单笔报工 {qty} 件超过该工序计划量 {plan_qty} 件",
                    }
                )
            if order_process and int(order_process.completed_qty or 0) > plan_qty:
                prev_id = latest_over_log_id.get(op_id)
                if prev_id is None or log.id > prev_id:
                    latest_over_log_id[op_id] = log.id

        if not is_void and log.unit_price is not None:
            ref_price = _price_reference(db, tenant_id, log)
            if ref_price:
                locked_price = Decimal(str(log.unit_price))
                ratio = locked_price / ref_price
                if ratio < PRICE_RATIO_LOW or ratio > PRICE_RATIO_HIGH:
                    reasons.append(
                        {
                            "code": "price_outlier",
                            "text": (
                                f"锁定单价 ¥{locked_price:.2f} 偏离工序现价 ¥{ref_price:.2f}"
                                f"（{ratio:.2f}x）"
                            ),
                        }
                    )

        if is_void and is_month_locked(db, tenant_id, year_month_of(log.created_at)):
            reasons.append(
                {
                    "code": "void_in_locked_month",
                    "text": "所在月份已月结锁定，但该笔报工已作废，请核实是否已发工资",
                }
            )

        if reasons:
            reasons_by_log[log.id] = reasons

    for op_id, log_id in latest_over_log_id.items():
        order_process = process_cache.get(op_id)
        if not order_process:
            continue
        reasons_by_log.setdefault(log_id, []).append(
            {
                "code": "process_over_plan",
                "text": (
                    f"该工序累计已报 {order_process.completed_qty} 件，超过计划量 "
                    f"{order_process.plan_qty} 件"
                ),
            }
        )

    if not reasons_by_log:
        return {
            "items": [],
            "total": 0,
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
            "summary": {},
            "message": "无异常报工，月底核对干净",
        }

    by_id = {log.id: log for log in logs}
    items: list[dict[str, Any]] = []
    for log_id, reasons in reasons_by_log.items():
        log = by_id[log_id]
        rt = _report_type(log)
        is_rework = rt == ReportType.rework
        order = db.get(Order, log.order_id)
        worker = db.get(Worker, log.worker_id)
        product = db.get(OwnProduct, log.own_product_id)
        process = db.get(ProcessDefinition, log.process_id)
        items.append(
            {
                "work_log_id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "worker_id": log.worker_id,
                "worker_name": worker.name if worker else None,
                "order_no": order.order_no if order else None,
                "product_code": product.product_code if product else None,
                "process_name": process.name if process else None,
                "report_type": rt.value,
                "qty": int((log.rework_qty if is_rework else log.qualified_qty) or 0),
                "unit_price": float(log.unit_price) if log.unit_price is not None else None,
                "status": log.status.value if hasattr(log.status, "value") else str(log.status),
                "reasons": reasons,
                "reason_codes": [r["code"] for r in reasons],
            }
        )

    items.sort(key=lambda x: x["work_log_id"], reverse=True)
    codes_count: dict[str, int] = {}
    for it in items:
        for c in it["reason_codes"]:
            codes_count[c] = codes_count.get(c, 0) + 1

    summary_text = "；".join(f"{REASON_LABELS.get(k, k)} {v}" for k, v in codes_count.items())
    return {
        "items": items,
        "total": len(items),
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "summary": codes_count,
        "message": f"共 {len(items)} 条异常报工待核对（{summary_text}）",
    }
