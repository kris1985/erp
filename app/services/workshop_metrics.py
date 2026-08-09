"""车间军师只读指标白名单：生产 / 排产负荷 / 采购 / 仓库 / 财务。

大模型只能通过 metric_id 查询，禁止自由 SQL。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.models import PurchaseOrderStatus
from app.services import (
    finance_service,
    material_service,
    progress_service,
    purchase_service,
    schedule_engine,
)

# 指标 → 所需菜单权限（空=登录即可；需全部满足）
MetricRunner = Callable[[Session, int, dict[str, Any]], dict[str, Any]]


def _dec(v: Any) -> float | int | str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _trim_rows(rows: list[dict], *, limit: int = 40) -> tuple[list[dict], int]:
    total = len(rows)
    return rows[: max(1, limit)], total


def _chart(
    *,
    chart_type: str,
    title: str,
    metric_id: str,
    x: list[Any],
    series: list[dict[str, Any]],
    unit: str | None = None,
) -> dict[str, Any]:
    return {
        "type": chart_type,
        "title": title,
        "metric_id": metric_id,
        "x": x,
        "series": series,
        "unit": unit,
    }


def extract_charts(payload: Any) -> list[dict[str, Any]]:
    """从指标/工具 JSON 中提取 chart / charts。"""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    if isinstance(payload.get("chart"), dict):
        out.append(payload["chart"])
    charts = payload.get("charts")
    if isinstance(charts, list):
        out.extend([c for c in charts if isinstance(c, dict)])
    return out


def _metric_today_output(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    data = progress_service.today_output(db, tenant_id)
    items = list(data.get("by_process") or [])
    chart = None
    if items:
        chart = _chart(
            chart_type="bar",
            title=f"今日工序产量（{data.get('date') or ''}）",
            metric_id="production.today_output",
            x=[str(i.get("process_name") or "") for i in items],
            series=[
                {"name": "合格", "data": [int(i.get("qualified_qty") or 0) for i in items]},
                {"name": "不良", "data": [int(i.get("defect_qty") or 0) for i in items]},
            ],
            unit="双",
        )
    return {"metric_id": "production.today_output", "data": data, "chart": chart}


def _metric_order_progress(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    order_no = str(params.get("order_no") or "").strip()
    if not order_no:
        return {"error": "missing_param", "message": "需要参数 order_no"}
    data = progress_service.order_progress(db, tenant_id, order_no)
    procs = list(data.get("processes") or [])
    chart = None
    if procs:
        chart = _chart(
            chart_type="bar",
            title=f"{order_no} 工序进度",
            metric_id="production.order_progress",
            x=[str(p.get("process_name") or "") for p in procs],
            series=[{"name": "完成%", "data": [float(p.get("percent") or 0) for p in procs]}],
            unit="%",
        )
    return {"metric_id": "production.order_progress", "data": data, "chart": chart}


def _metric_progress_board(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    board = progress_service.progress_board(db, tenant_id)
    orders = list(board.get("orders") or [])
    trimmed, total = _trim_rows(orders, limit=int(params.get("limit") or 30))
    chart = None
    if trimmed:
        top = trimmed[:12]
        chart = _chart(
            chart_type="bar",
            title="在制订单进度",
            metric_id="production.open_orders_board",
            x=[str(o.get("order_no") or "") for o in top],
            series=[{"name": "进度", "data": [float(o.get("overall_percent") or 0) for o in top]}],
            unit="%",
        )
    return {
        "metric_id": "production.open_orders_board",
        "data": {
            "summary": board.get("summary"),
            "bottlenecks": board.get("bottlenecks"),
            "orders": trimmed,
            "orders_total": total,
            "orders_truncated": total > len(trimmed),
        },
        "chart": chart,
    }


def _metric_late_rush(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    board = progress_service.progress_board(db, tenant_id)
    orders = list(board.get("orders") or [])
    late = [o for o in orders if o.get("at_risk")]
    rush = [o for o in orders if o.get("is_rush")]
    late_t, late_n = _trim_rows(late)
    rush_t, rush_n = _trim_rows(rush)
    late_ids = {o.get("order_id") or o.get("order_no") for o in late}
    rush_ids = {o.get("order_id") or o.get("order_no") for o in rush}
    flagged = late_ids | rush_ids
    other_n = max(0, len(orders) - len(flagged))
    chart = _chart(
        chart_type="pie",
        title="风险单构成",
        metric_id="production.late_rush_orders",
        x=["交期风险", "急单", "其它在制"],
        series=[
            {
                "name": "单数",
                "data": [
                    {"name": "交期风险", "value": late_n},
                    {"name": "急单", "value": rush_n},
                    {"name": "其它在制", "value": other_n},
                ],
            }
        ],
        unit="单",
    )
    return {
        "metric_id": "production.late_rush_orders",
        "data": {
            "summary": board.get("summary"),
            "at_risk_count": late_n,
            "rush_count": rush_n,
            "at_risk_orders": late_t,
            "rush_orders": rush_t,
        },
        "chart": chart,
    }


def _metric_process_bottlenecks(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    board = progress_service.progress_board(db, tenant_id)
    bots = list(board.get("bottlenecks") or [])
    chart = None
    if bots:
        chart = _chart(
            chart_type="bar",
            title="工序瓶颈剩余量",
            metric_id="production.process_bottlenecks",
            x=[str(b.get("process_name") or "") for b in bots[:15]],
            series=[{"name": "剩余", "data": [int(b.get("remain_qty") or 0) for b in bots[:15]]}],
            unit="双",
        )
    return {
        "metric_id": "production.process_bottlenecks",
        "data": {
            "bottlenecks": bots,
            "summary": board.get("summary"),
        },
        "chart": chart,
    }


def _metric_schedule_load(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    days = max(1, min(int(params.get("days") or 14), 60))
    today = date.today()
    data = schedule_engine.daily_load(
        db, tenant_id, date_from=today, date_to=today + timedelta(days=days)
    )
    items = list(data.get("items") or [])
    trimmed, total = _trim_rows(items, limit=60)
    # 按日汇总负荷
    by_day: dict[str, float] = {}
    for it in items:
        d = str(it.get("date") or "")
        by_day[d] = by_day.get(d, 0.0) + float(it.get("load_qty") or 0)
    day_keys = sorted(by_day.keys())
    chart = None
    if day_keys:
        chart = _chart(
            chart_type="line",
            title=f"排产日负荷（{days}天）",
            metric_id="schedule.daily_load",
            x=[k[5:] if len(k) >= 10 else k for k in day_keys],
            series=[{"name": "负荷", "data": [round(by_day[k], 2) for k in day_keys]}],
            unit="双",
        )
    return {
        "metric_id": "schedule.daily_load",
        "data": {
            "date_from": data.get("date_from"),
            "date_to": data.get("date_to"),
            "bottlenecks": data.get("bottlenecks") or [],
            "items": trimmed,
            "items_total": total,
            "engine_version": data.get("engine_version"),
        },
        "chart": chart,
    }


def _metric_shortages(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    rush_only = bool(params.get("rush_only") or False)
    rows = material_service.list_shortages(
        db,
        tenant_id,
        include_shared=True,
        hide_purchased=True,
        rush_only=rush_only,
        keyword=(str(params["keyword"]).strip() if params.get("keyword") else None),
        order_no=(str(params["order_no"]).strip() if params.get("order_no") else None),
    )
    slim = [
        {
            "order_no": r.get("order_no"),
            "is_rush": r.get("is_rush"),
            "supplier_product_code": r.get("supplier_product_code"),
            "supplier_product_name": r.get("supplier_product_name"),
            "partner_name": r.get("partner_name"),
            "required_qty": _dec(r.get("required_qty")),
            "shortage_qty": _dec(r.get("shortage_qty")),
            "to_buy_qty": _dec(r.get("to_buy_qty")),
            "in_transit_qty": _dec(r.get("in_transit_qty")),
            "pool_qty": _dec(r.get("pool_qty")),
            "purchase_status": r.get("purchase_status"),
        }
        for r in rows
    ]
    trimmed, total = _trim_rows(slim)
    chart = None
    if trimmed:
        top = trimmed[:12]
        chart = _chart(
            chart_type="bar",
            title="缺料待采量（Top）",
            metric_id="materials.shortages",
            x=[str(r.get("supplier_product_code") or r.get("supplier_product_name") or "") for r in top],
            series=[{"name": "待采", "data": [float(r.get("to_buy_qty") or r.get("shortage_qty") or 0) for r in top]}],
        )
    return {
        "metric_id": "materials.shortages",
        "data": {"items": trimmed, "total": total, "truncated": total > len(trimmed)},
        "chart": chart,
    }


def _metric_open_pos(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    open_status = {
        PurchaseOrderStatus.ordered.value,
        PurchaseOrderStatus.shipped.value,
        PurchaseOrderStatus.partial_received.value,
    }
    rows = purchase_service.list_pos(db, tenant_id)
    rows = [r for r in rows if str(r.get("status") or "") in open_status]
    alert = params.get("delivery_alert")
    if alert:
        rows = [r for r in rows if r.get("delivery_alert") == alert]
    slim = [
        {
            "po_no": r.get("po_no"),
            "partner_name": r.get("partner_name"),
            "status": r.get("status"),
            "expected_date": r.get("expected_date"),
            "delivery_alert": r.get("delivery_alert"),
            "overdue_days": r.get("overdue_days"),
            "summary_total_qty": _dec(r.get("summary_total_qty")),
            "summary_total_amount": _dec(r.get("summary_total_amount")),
        }
        for r in rows
    ]
    trimmed, total = _trim_rows(slim)
    overdue_n = sum(1 for r in slim if r.get("delivery_alert") == "overdue")
    due_soon = sum(1 for r in slim if r.get("delivery_alert") == "due_soon")
    normal_n = max(0, total - overdue_n - due_soon)
    chart = _chart(
        chart_type="pie",
        title="在途采购交期状态",
        metric_id="purchase.open_pos",
        x=["逾期", "即将到期", "正常"],
        series=[
            {
                "name": "单数",
                "data": [
                    {"name": "逾期", "value": overdue_n},
                    {"name": "即将到期", "value": due_soon},
                    {"name": "正常", "value": normal_n},
                ],
            }
        ],
        unit="单",
    )
    return {
        "metric_id": "purchase.open_pos",
        "data": {
            "items": trimmed,
            "total": total,
            "overdue_count": overdue_n,
            "truncated": total > len(trimmed),
        },
        "chart": chart,
    }


def _metric_shared_pool(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    rows = material_service.list_shared_stocks(db, tenant_id)
    # 优先展示有余额或占用的
    rows = sorted(
        rows,
        key=lambda r: (
            -(float(r.get("qty") or 0) + float(r.get("occupied_qty") or 0)),
            str(r.get("supplier_product_code") or ""),
        ),
    )
    slim = [
        {
            "supplier_product_code": r.get("supplier_product_code"),
            "supplier_product_name": r.get("supplier_product_name"),
            "category_name": r.get("category_name"),
            "pool_qty": _dec(r.get("qty")),
            "occupied_qty": _dec(r.get("occupied_qty")),
            "in_transit_qty": _dec(r.get("in_transit_qty")),
            "avg_unit_cost": _dec(r.get("avg_unit_cost")),
        }
        for r in rows
    ]
    trimmed, total = _trim_rows(slim, limit=50)
    chart = None
    if trimmed:
        top = trimmed[:12]
        chart = _chart(
            chart_type="bar",
            title="库存池余额（Top）",
            metric_id="inventory.shared_pool",
            x=[str(r.get("supplier_product_code") or "") for r in top],
            series=[
                {"name": "池余额", "data": [float(r.get("pool_qty") or 0) for r in top]},
                {"name": "占用", "data": [float(r.get("occupied_qty") or 0) for r in top]},
            ],
        )
    return {
        "metric_id": "inventory.shared_pool",
        "data": {"items": trimmed, "total": total, "truncated": total > len(trimmed)},
        "chart": chart,
    }


def _metric_receivables_open(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    open_rows = finance_service.list_receivables(db, tenant_id, status="open")
    partial_rows = finance_service.list_receivables(db, tenant_id, status="partial")
    rows = open_rows + partial_rows
    rows.sort(key=lambda r: (-float(r.get("balance") or 0), -(r.get("age_days") or 0)))
    slim = [
        {
            "customer_name": r.get("customer_name"),
            "order_no": r.get("order_no"),
            "amount": _dec(r.get("amount")),
            "received_amount": _dec(r.get("received_amount")),
            "balance": _dec(r.get("balance")),
            "age_days": r.get("age_days"),
            "age_bucket": r.get("age_bucket"),
            "status": r.get("status"),
        }
        for r in rows
    ]
    total_balance = sum(float(r.get("balance") or 0) for r in slim)
    trimmed, total = _trim_rows(slim)
    # 按客户汇总余额
    by_cust: dict[str, float] = {}
    for r in slim:
        name = str(r.get("customer_name") or "未知")
        by_cust[name] = by_cust.get(name, 0.0) + float(r.get("balance") or 0)
    top_cust = sorted(by_cust.items(), key=lambda x: -x[1])[:10]
    chart = None
    if top_cust:
        chart = _chart(
            chart_type="bar",
            title="未结应收（按客户）",
            metric_id="finance.receivables_open",
            x=[c[0] for c in top_cust],
            series=[{"name": "余额", "data": [round(c[1], 2) for c in top_cust]}],
            unit="元",
        )
    return {
        "metric_id": "finance.receivables_open",
        "data": {
            "total_balance": round(total_balance, 2),
            "items": trimmed,
            "total": total,
            "truncated": total > len(trimmed),
        },
        "chart": chart,
    }


def _metric_payments_month(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    year = int(params.get("year") or today.year)
    month = int(params.get("month") or today.month)
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    rows = finance_service.list_payments(
        db, tenant_id, status="posted", date_from=start, date_to=end
    )
    slim = [
        {
            "customer_name": r.get("customer_name"),
            "payment_date": r.get("payment_date"),
            "amount": _dec(r.get("amount")),
            "method": r.get("method"),
            "voucher_no": r.get("voucher_no"),
        }
        for r in rows
    ]
    total_amount = sum(float(r.get("amount") or 0) for r in slim)
    trimmed, total = _trim_rows(slim)
    by_day: dict[str, float] = {}
    for r in slim:
        d = str(r.get("payment_date") or "")[:10]
        if not d:
            continue
        by_day[d] = by_day.get(d, 0.0) + float(r.get("amount") or 0)
    day_keys = sorted(by_day.keys())
    chart = None
    if day_keys:
        chart = _chart(
            chart_type="bar",
            title=f"{year}-{month:02d} 回款",
            metric_id="finance.payments_this_month",
            x=[k[5:] if len(k) >= 10 else k for k in day_keys],
            series=[{"name": "回款", "data": [round(by_day[k], 2) for k in day_keys]}],
            unit="元",
        )
    elif trimmed:
        by_cust: dict[str, float] = {}
        for r in trimmed:
            name = str(r.get("customer_name") or "未知")
            by_cust[name] = by_cust.get(name, 0.0) + float(r.get("amount") or 0)
        top = sorted(by_cust.items(), key=lambda x: -x[1])[:10]
        chart = _chart(
            chart_type="bar",
            title=f"{year}-{month:02d} 回款（按客户）",
            metric_id="finance.payments_this_month",
            x=[c[0] for c in top],
            series=[{"name": "回款", "data": [round(c[1], 2) for c in top]}],
            unit="元",
        )
    return {
        "metric_id": "finance.payments_this_month",
        "data": {
            "year": year,
            "month": month,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "total_amount": round(total_amount, 2),
            "items": trimmed,
            "total": total,
            "truncated": total > len(trimmed),
        },
        "chart": chart,
    }


def _metric_profit(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    year = int(params.get("year") or today.year)
    month = int(params.get("month") or today.month)
    report = finance_service.profit_report(db, tenant_id, year=year, month=month)
    orders = list(report.get("orders") or [])
    trimmed, total = _trim_rows(orders, limit=30)
    summary = report.get("summary") or {}
    chart = _chart(
        chart_type="bar",
        title=f"{year}-{month:02d} 利润结构",
        metric_id="finance.profit_report",
        x=["收入", "材料", "人工", "其它成本", "毛利"],
        series=[
            {
                "name": "金额",
                "data": [
                    float(summary.get("revenue") or 0),
                    float(summary.get("material_cost") or 0),
                    float(summary.get("labor_cost") or 0),
                    float(summary.get("other_cost") or 0),
                    float(summary.get("gross_profit") or 0),
                ],
            }
        ],
        unit="元",
    )
    return {
        "metric_id": "finance.profit_report",
        "data": {
            "year": year,
            "month": month,
            "summary": summary,
            "orders": trimmed,
            "orders_total": total,
            "truncated": total > len(trimmed),
        },
        "chart": chart,
    }


def _metric_business_kpi(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    year = int(params.get("year") or today.year)
    month = int(params.get("month") or today.month)
    kpi = finance_service.business_kpi(db, tenant_id, year=year, month=month)
    chart = _chart(
        chart_type="bar",
        title=f"{year}-{month:02d} 经营 KPI",
        metric_id="finance.business_kpi",
        x=["出货额", "回款", "毛利", "应收余额"],
        series=[
            {
                "name": "金额",
                "data": [
                    float(kpi.get("shipment_amount") or 0),
                    float(kpi.get("payment_amount") or 0),
                    float(kpi.get("gross_profit") or 0),
                    float(kpi.get("customer_ar_balance") or 0),
                ],
            }
        ],
        unit="元",
    )
    return {
        "metric_id": "finance.business_kpi",
        "data": {"year": year, "month": month, "kpi": kpi},
        "chart": chart,
    }


def _metric_analytics_delivery(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_delivery(db, tenant_id, limit=int(params.get("limit") or 12))
    return {"metric_id": "analytics.delivery_risk", "data": result, "chart": result.get("chart")}


def _metric_analytics_kit_ready(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_kit_ready(db, tenant_id, limit=int(params.get("limit") or 12))
    return {"metric_id": "analytics.kit_ready", "data": result, "chart": result.get("chart")}


def _metric_analytics_order_intake(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_order_intake(
        db,
        tenant_id,
        lines=params.get("lines") or [],
        include_shared=bool(params.get("include_shared", True)),
        qty=params.get("qty"),
        delivery_date=params.get("delivery_date"),
        is_rush=params.get("is_rush"),
        strategy=params.get("strategy"),
        default_daily_capacity=params.get("default_daily_capacity"),
    )
    return {"metric_id": "analytics.order_intake", "data": result, "chart": result.get("chart")}


def _metric_analytics_capacity(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_capacity(db, tenant_id, days=int(params.get("days") or 14))
    return {"metric_id": "analytics.capacity_load", "data": result, "chart": result.get("chart")}


def _metric_analytics_supply(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_supply(db, tenant_id, limit=int(params.get("limit") or 12))
    return {"metric_id": "analytics.supply_chain", "data": result, "chart": result.get("chart")}


def _metric_analytics_finance(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_finance(
        db, tenant_id, year=params.get("year"), month=params.get("month")
    )
    return {"metric_id": "analytics.finance_health", "data": result, "chart": result.get("chart")}


def _metric_analytics_quality(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_quality(db, tenant_id, days=int(params.get("days") or 30))
    return {"metric_id": "analytics.quality_hotspots", "data": result, "chart": result.get("chart")}


def _metric_analytics_quality_alerts(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.list_quality_alerts(
        db,
        tenant_id,
        days=int(params.get("days") or 14),
        limit=int(params.get("limit") or 5),
    )
    return {"metric_id": "analytics.quality_alerts", "data": result, "chart": result.get("chart")}


def _metric_analytics_labor(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.analyze_labor(db, tenant_id, year_month=params.get("year_month"))
    return {"metric_id": "analytics.labor_efficiency", "data": result, "chart": result.get("chart")}


def _metric_analytics_today_actions(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.build_today_actions(db, tenant_id)
    return {"metric_id": "analytics.today_actions", "data": result, "chart": result.get("chart")}


def _metric_analytics_weekly(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.weekly_brief(db, tenant_id)
    return {"metric_id": "analytics.weekly_brief", "data": result, "chart": result.get("chart")}


def _metric_analytics_monthly(db: Session, tenant_id: int, params: dict[str, Any]) -> dict[str, Any]:
    from app.services import analytics

    result = analytics.monthly_brief(
        db, tenant_id, year=params.get("year"), month=params.get("month")
    )
    return {"metric_id": "analytics.monthly_brief", "data": result, "chart": result.get("chart")}


METRIC_CATALOG: list[dict[str, Any]] = [
    {
        "id": "production.today_output",
        "name": "今日工序产量",
        "domain": "production",
        "description": "今日有效报工合格/不良，按工序汇总",
        "params": [],
        "permissions": ["menu.work_logs"],
        "run": _metric_today_output,
    },
    {
        "id": "production.order_progress",
        "name": "生产单进度",
        "domain": "production",
        "description": "指定生产单各工序完成进度",
        "params": [{"name": "order_no", "required": True, "type": "string"}],
        "permissions": ["menu.orders"],
        "run": _metric_order_progress,
    },
    {
        "id": "production.open_orders_board",
        "name": "在制进度看板",
        "domain": "production",
        "description": "在制订单进度摘要、风险与瓶颈",
        "params": [{"name": "limit", "required": False, "type": "int"}],
        "permissions": ["menu.orders"],
        "run": _metric_progress_board,
    },
    {
        "id": "production.late_rush_orders",
        "name": "延期风险与急单",
        "domain": "production",
        "description": "交期风险单与急单列表",
        "params": [],
        "permissions": ["menu.orders"],
        "run": _metric_late_rush,
    },
    {
        "id": "production.process_bottlenecks",
        "name": "工序瓶颈",
        "domain": "production",
        "description": "剩余量大的瓶颈工序",
        "params": [],
        "permissions": ["menu.orders"],
        "run": _metric_process_bottlenecks,
    },
    {
        "id": "schedule.daily_load",
        "name": "排产日负荷",
        "domain": "schedule",
        "description": "未来 N 天工序负荷与超产能瓶颈",
        "params": [{"name": "days", "required": False, "type": "int"}],
        "permissions": ["menu.schedule"],
        "run": _metric_schedule_load,
    },
    {
        "id": "materials.shortages",
        "name": "材料缺料",
        "domain": "purchase",
        "description": "待采/缺料清单（可按急单、单号过滤）",
        "params": [
            {"name": "rush_only", "required": False, "type": "bool"},
            {"name": "order_no", "required": False, "type": "string"},
            {"name": "keyword", "required": False, "type": "string"},
        ],
        "permissions": ["menu.material_shortages"],
        "run": _metric_shortages,
    },
    {
        "id": "purchase.open_pos",
        "name": "在途采购单",
        "domain": "purchase",
        "description": "已下单/在途/部分到货的采购单及逾期提示",
        "params": [{"name": "delivery_alert", "required": False, "type": "string"}],
        "permissions": ["menu.purchase_orders"],
        "run": _metric_open_pos,
    },
    {
        "id": "inventory.shared_pool",
        "name": "库存池余额",
        "domain": "inventory",
        "description": "共享材料池余额、占用、在途",
        "params": [],
        "permissions": ["menu.shared_materials"],
        "run": _metric_shared_pool,
    },
    {
        "id": "finance.receivables_open",
        "name": "未结应收",
        "domain": "finance",
        "description": "未结清应收余额与账龄",
        "params": [],
        "permissions": ["menu.receivables"],
        "run": _metric_receivables_open,
    },
    {
        "id": "finance.payments_this_month",
        "name": "本月回款",
        "domain": "finance",
        "description": "指定年月已过账回款合计与明细",
        "params": [
            {"name": "year", "required": False, "type": "int"},
            {"name": "month", "required": False, "type": "int"},
        ],
        "permissions": ["menu.payments"],
        "run": _metric_payments_month,
    },
    {
        "id": "finance.profit_report",
        "name": "利润报表",
        "domain": "finance",
        "description": "指定年月出货利润汇总与订单明细",
        "params": [
            {"name": "year", "required": False, "type": "int"},
            {"name": "month", "required": False, "type": "int"},
        ],
        "permissions": ["menu.profit"],
        "run": _metric_profit,
    },
    {
        "id": "finance.business_kpi",
        "name": "经营 KPI",
        "domain": "finance",
        "description": "出货额、回款、毛利、应收余额等经营指标",
        "params": [
            {"name": "year", "required": False, "type": "int"},
            {"name": "month", "required": False, "type": "int"},
        ],
        "permissions": ["menu.profit"],
        "run": _metric_business_kpi,
    },
    # —— 诊断分析（Python analytics，供车间军师问诊）——
    {
        "id": "analytics.delivery_risk",
        "name": "交期在制诊断",
        "domain": "analytics",
        "description": "交期风险、急单、瓶颈与停滞单结论",
        "params": [{"name": "limit", "required": False, "type": "int"}],
        "permissions": ["menu.orders"],
        "run": _metric_analytics_delivery,
    },
    {
        "id": "analytics.kit_ready",
        "name": "齐套可排产诊断",
        "domain": "analytics",
        "description": "在制单按齐套分成可排/半齐套/等料，并给排产下一步",
        "params": [{"name": "limit", "required": False, "type": "int"}],
        "permissions": ["menu.orders"],
        "run": _metric_analytics_kit_ready,
    },
    {
        "id": "analytics.order_intake",
        "name": "接单冲击诊断",
        "domain": "analytics",
        "description": "销售行下生产前：利润对比、缺料、虚拟插单交期冲击；可覆盖 qty/delivery_date/is_rush/default_daily_capacity 做假设仿真",
        "params": [
            {"name": "lines", "required": True, "type": "array"},
            {"name": "include_shared", "required": False, "type": "bool"},
            {"name": "qty", "required": False, "type": "int"},
            {"name": "delivery_date", "required": False, "type": "string"},
            {"name": "is_rush", "required": False, "type": "bool"},
            {"name": "strategy", "required": False, "type": "string"},
            {"name": "default_daily_capacity", "required": False, "type": "int"},
        ],
        "permissions": ["menu.sales_orders"],
        "run": _metric_analytics_order_intake,
    },
    {
        "id": "analytics.capacity_load",
        "name": "产能负荷诊断",
        "domain": "analytics",
        "description": "未来负荷超产能点与产能校准提示",
        "params": [{"name": "days", "required": False, "type": "int"}],
        "permissions": ["menu.schedule"],
        "run": _metric_analytics_capacity,
    },
    {
        "id": "analytics.supply_chain",
        "name": "缺料采购诊断",
        "domain": "analytics",
        "description": "缺料、急单缺料、采购逾期结论",
        "params": [{"name": "limit", "required": False, "type": "int"}],
        "permissions": ["menu.material_shortages"],
        "run": _metric_analytics_supply,
    },
    {
        "id": "analytics.finance_health",
        "name": "经营财务诊断",
        "domain": "analytics",
        "description": "毛利、亏损单、回款与应收结论",
        "params": [
            {"name": "year", "required": False, "type": "int"},
            {"name": "month", "required": False, "type": "int"},
        ],
        "permissions": ["menu.profit"],
        "run": _metric_analytics_finance,
    },
    {
        "id": "analytics.quality_hotspots",
        "name": "质量不良诊断",
        "domain": "analytics",
        "description": "近 N 日工序不良率热点",
        "params": [{"name": "days", "required": False, "type": "int"}],
        "permissions": ["menu.work_logs"],
        "run": _metric_analytics_quality,
    },
    {
        "id": "analytics.quality_alerts",
        "name": "质量预警（浅层）",
        "domain": "analytics",
        "description": "款×工序近 N 日不良率突增（vs 同工序均值）；chip + 抽检建议，非 ML",
        "params": [
            {"name": "days", "required": False, "type": "int"},
            {"name": "limit", "required": False, "type": "int"},
        ],
        "permissions": ["menu.work_logs"],
        "run": _metric_analytics_quality_alerts,
    },
    {
        "id": "analytics.labor_efficiency",
        "name": "人效工资诊断",
        "domain": "analytics",
        "description": "月度计件/工资人效结论",
        "params": [{"name": "year_month", "required": False, "type": "string"}],
        "permissions": ["menu.salary"],
        "run": _metric_analytics_labor,
    },
    {
        "id": "analytics.today_actions",
        "name": "今日行动清单",
        "domain": "analytics",
        "description": "交期/齐套/负荷/缺料/经营收敛成可执行行动与军师下一步（含 top3+evidence）",
        "params": [],
        "permissions": ["menu.orders", "menu.schedule"],
        "permissions_mode": "any",
        "run": _metric_analytics_today_actions,
    },
    {
        "id": "analytics.weekly_brief",
        "name": "车间周简报",
        "domain": "analytics",
        "description": "交期+齐套+负荷+缺料+质量综合周报（含行动清单）",
        "params": [],
        "permissions": ["menu.orders"],
        "run": _metric_analytics_weekly,
    },
    {
        "id": "analytics.monthly_brief",
        "name": "经营月简报",
        "domain": "analytics",
        "description": "财务+人效+交期+质量综合月报",
        "params": [
            {"name": "year", "required": False, "type": "int"},
            {"name": "month", "required": False, "type": "int"},
        ],
        "permissions": ["menu.profit"],
        "run": _metric_analytics_monthly,
    },
]

_METRIC_BY_ID: dict[str, dict[str, Any]] = {m["id"]: m for m in METRIC_CATALOG}


def _has_perms(
    user_perms: set[str],
    required: list[str],
    *,
    mode: str = "all",
) -> bool:
    if not required:
        return True
    if mode == "any":
        return any(p in user_perms for p in required)
    return all(p in user_perms for p in required)


def list_metrics(*, permission_codes: Optional[list[str] | set[str]] = None) -> list[dict[str, Any]]:
    perms = set(permission_codes or [])
    out: list[dict[str, Any]] = []
    for m in METRIC_CATALOG:
        mode = str(m.get("permissions_mode") or "all")
        if not _has_perms(perms, list(m.get("permissions") or []), mode=mode):
            continue
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "domain": m["domain"],
                "description": m["description"],
                "params": m.get("params") or [],
            }
        )
    return out


def query_metric(
    db: Session,
    tenant_id: int,
    metric_id: str,
    *,
    params: Optional[dict[str, Any]] = None,
    permission_codes: Optional[list[str] | set[str]] = None,
) -> dict[str, Any]:
    mid = (metric_id or "").strip()
    meta = _METRIC_BY_ID.get(mid)
    if not meta:
        return {
            "error": "unknown_metric",
            "message": f"未知指标：{mid}",
            "available": [m["id"] for m in list_metrics(permission_codes=permission_codes)],
        }
    perms = set(permission_codes or [])
    required = list(meta.get("permissions") or [])
    mode = str(meta.get("permissions_mode") or "all")
    if not _has_perms(perms, required, mode=mode):
        need = " 或 ".join(required) if mode == "any" else ", ".join(required)
        return {
            "error": "forbidden",
            "message": f"无权限查询 {mid}，需要：{need}",
        }
    runner: MetricRunner = meta["run"]
    try:
        return runner(db, tenant_id, dict(params or {}))
    except Exception as e:
        return {"error": "query_failed", "message": str(e), "metric_id": mid}
