"""经营诊断分析：从 ERP 台账提炼可行动结论（供脚本与车间军师指标复用）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import (
    finance_service,
    material_service,
    progress_service,
    purchase_service,
    salary_service,
    schedule_engine,
)


def _dec(v: Any) -> float | int | str | None:
    if v is None:
        return None
    try:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
    except Exception:
        pass
    return v


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


def _today() -> date:
    return date.today()


def _ym(year: int | None = None, month: int | None = None) -> tuple[int, int]:
    t = _today()
    return int(year or t.year), int(month or t.month)


def _insight(severity: str, text: str, **evidence: Any) -> dict[str, Any]:
    return {"severity": severity, "text": text, "evidence": evidence or {}}


def analyze_delivery(db: Session, tenant_id: int, *, limit: int = 12) -> dict[str, Any]:
    """交期与在制：风险单、急单、瓶颈。"""
    board = progress_service.progress_board(db, tenant_id)
    orders = list(board.get("orders") or [])
    summary = board.get("summary") or {}
    bottlenecks = list(board.get("bottlenecks") or [])

    late = [o for o in orders if o.get("at_risk")]
    rush = [o for o in orders if o.get("is_rush")]
    late_rush = [o for o in late if o.get("is_rush")]
    stagnant = [
        o
        for o in orders
        if float(o.get("overall_percent") or 0) < 15 and not o.get("at_risk")
    ]

    insights: list[dict[str, Any]] = []
    if late_rush:
        insights.append(
            _insight(
                "high",
                f"有 {len(late_rush)} 张急单同时处于交期风险，应优先保交期/加资源。",
                order_nos=[o.get("order_no") for o in late_rush[:8]],
            )
        )
    if late:
        insights.append(
            _insight(
                "high" if len(late) >= 3 else "medium",
                f"交期风险单 {len(late)} 张（在制 {summary.get('open_orders') or len(orders)}）。",
                top=[
                    {
                        "order_no": o.get("order_no"),
                        "delivery_date": o.get("delivery_date"),
                        "percent": o.get("overall_percent"),
                        "bottleneck": (o.get("bottleneck") or {}).get("process_name"),
                    }
                    for o in sorted(late, key=lambda x: str(x.get("delivery_date") or ""))[:limit]
                ],
            )
        )
    if bottlenecks:
        top_bn = bottlenecks[0]
        insights.append(
            _insight(
                "medium",
                f"当前最大瓶颈在「{top_bn.get('process_name')}」：卡住 {top_bn.get('order_count')} 单，剩余 {top_bn.get('remain_qty')}。",
                bottleneck=top_bn,
            )
        )
    if stagnant[:5]:
        insights.append(
            _insight(
                "medium",
                f"有 {len(stagnant)} 张在制单进度仍低于 15%，可能未真正开工或齐套受阻。",
                order_nos=[o.get("order_no") for o in stagnant[:8]],
            )
        )
    if not insights:
        insights.append(_insight("low", "在制交期整体平稳，未见集中风险。"))

    top_progress = sorted(orders, key=lambda o: float(o.get("overall_percent") or 0))[:limit]
    chart = None
    if top_progress:
        chart = _chart(
            chart_type="bar",
            title="在制进度（偏低优先）",
            metric_id="analytics.delivery_risk",
            x=[str(o.get("order_no") or "") for o in top_progress],
            series=[{"name": "进度", "data": [float(o.get("overall_percent") or 0) for o in top_progress]}],
            unit="%",
        )

    return {
        "analysis_id": "delivery_risk",
        "title": "交期与在制诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "board_summary": summary,
            "late_count": len(late),
            "rush_count": len(rush),
            "late_rush_count": len(late_rush),
            "bottlenecks": bottlenecks[:10],
            "focus_orders": [
                {
                    "order_no": o.get("order_no"),
                    "customer_name": o.get("customer_name"),
                    "delivery_date": o.get("delivery_date"),
                    "is_rush": o.get("is_rush"),
                    "at_risk": o.get("at_risk"),
                    "overall_percent": o.get("overall_percent"),
                    "bottleneck": o.get("bottleneck"),
                }
                for o in (late or rush or orders)[:limit]
            ],
        },
        "chart": chart,
    }


def analyze_capacity(db: Session, tenant_id: int, *, days: int = 14) -> dict[str, Any]:
    """未来负荷 vs 产能，并对照近 14 日真实报工粗校准。"""
    days = max(7, min(int(days or 14), 60))
    today = _today()
    load = schedule_engine.daily_load(
        db, tenant_id, date_from=today, date_to=today + timedelta(days=days - 1)
    )
    hot = list(load.get("bottlenecks") or [])
    items = list(load.get("items") or [])

    # 近 14 日真实报工：按工序粗算日均合格
    actual_by_process: dict[str, float] = {}
    try:
        logs = salary_service.list_work_logs(
            db, tenant_id, status="confirmed", page=1, page_size=500
        )
        since = today - timedelta(days=14)
        for row in logs.get("items") or []:
            # list_work_logs may return nested; tolerate shapes
            created = str(row.get("created_at") or row.get("report_date") or "")[:10]
            if created and created < since.isoformat():
                continue
            name = str(row.get("process_name") or row.get("process") or "未知")
            actual_by_process[name] = actual_by_process.get(name, 0.0) + float(
                row.get("qualified_qty") or 0
            )
    except Exception:
        actual_by_process = {}

    insights: list[dict[str, Any]] = []
    if hot:
        by_proc: dict[str, int] = {}
        for h in hot:
            pn = str(h.get("process_name") or "")
            by_proc[pn] = by_proc.get(pn, 0) + 1
        worst = sorted(by_proc.items(), key=lambda x: -x[1])[:3]
        insights.append(
            _insight(
                "high",
                f"未来 {days} 天有 {len(hot)} 个工序日超产能；最紧："
                + "、".join([f"{n}({c}天)" for n, c in worst]),
                hot_sample=hot[:8],
            )
        )
    else:
        insights.append(_insight("low", f"未来 {days} 天排产负荷未发现超产能日。"))

    # 校准提示：设定产能 vs 近 14 日日均
    calib = []
    for it in items:
        pn = str(it.get("process_name") or "")
        cap = it.get("capacity")
        if cap is None or not pn:
            continue
        actual_daily = (actual_by_process.get(pn, 0.0) / 14.0) if pn in actual_by_process else None
        if actual_daily is None:
            continue
        ratio = actual_daily / float(cap) if float(cap) else None
        if ratio is not None and (ratio < 0.6 or ratio > 1.2):
            calib.append(
                {
                    "process_name": pn,
                    "configured_capacity": float(cap),
                    "actual_daily_avg_14d": round(actual_daily, 1),
                    "ratio": round(ratio, 2),
                }
            )
    # unique by process
    seen = set()
    calib_u = []
    for c in sorted(calib, key=lambda x: abs((x.get("ratio") or 1) - 1), reverse=True):
        if c["process_name"] in seen:
            continue
        seen.add(c["process_name"])
        calib_u.append(c)
    if calib_u:
        insights.append(
            _insight(
                "medium",
                "部分工序「设定产能」与近 14 日真实日均偏差较大，建议校准排产产能参数。",
                calibration=calib_u[:6],
            )
        )

    by_day: dict[str, float] = {}
    for it in items:
        d = str(it.get("date") or "")
        by_day[d] = by_day.get(d, 0.0) + float(it.get("load_qty") or 0)
    day_keys = sorted(by_day.keys())
    chart = None
    if day_keys:
        chart = _chart(
            chart_type="line",
            title=f"未来{days}日负荷合计",
            metric_id="analytics.capacity_load",
            x=[k[5:] if len(k) >= 10 else k for k in day_keys],
            series=[{"name": "负荷", "data": [round(by_day[k], 1) for k in day_keys]}],
            unit="双",
        )

    return {
        "analysis_id": "capacity_load",
        "title": "产能与负荷诊断",
        "as_of": today.isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "days": days,
            "over_capacity_days": len(hot),
            "hotspots": hot[:15],
            "capacity_calibration": calib_u[:10],
        },
        "chart": chart,
    }


def analyze_supply(db: Session, tenant_id: int, *, limit: int = 12) -> dict[str, Any]:
    """缺料、采购逾期、急单缺料。"""
    shortages = material_service.list_shortages(
        db, tenant_id, include_shared=True, hide_purchased=True, rush_only=False
    )
    rush_short = [r for r in shortages if r.get("is_rush")]
    open_pos = purchase_service.list_pos(db, tenant_id)
    open_status = {"ordered", "shipped", "partial_received"}
    open_pos = [p for p in open_pos if str(p.get("status") or "") in open_status]
    overdue = [p for p in open_pos if p.get("delivery_alert") == "overdue"]
    due_soon = [p for p in open_pos if p.get("delivery_alert") == "due_soon"]

    insights: list[dict[str, Any]] = []
    if rush_short:
        insights.append(
            _insight(
                "high",
                f"急单相关缺料 {len(rush_short)} 行，可能直接卡住插单开工。",
                top=[
                    {
                        "order_no": r.get("order_no"),
                        "material": r.get("supplier_product_name") or r.get("supplier_product_code"),
                        "to_buy": _dec(r.get("to_buy_qty") or r.get("shortage_qty")),
                    }
                    for r in rush_short[:limit]
                ],
            )
        )
    if shortages:
        insights.append(
            _insight(
                "medium" if len(shortages) < 20 else "high",
                f"待采缺料共 {len(shortages)} 行；优先处理待采量大的物料。",
                total=len(shortages),
            )
        )
    if overdue:
        insights.append(
            _insight(
                "high",
                f"在途采购逾期 {len(overdue)} 单，会影响齐套与交期。",
                pos=[
                    {
                        "po_no": p.get("po_no"),
                        "partner_name": p.get("partner_name"),
                        "expected_date": p.get("expected_date"),
                        "overdue_days": p.get("overdue_days"),
                    }
                    for p in overdue[:limit]
                ],
            )
        )
    elif due_soon:
        insights.append(
            _insight("medium", f"有 {len(due_soon)} 单采购即将到期，需跟催到货。")
        )
    if not insights:
        insights.append(_insight("low", "缺料与在途采购暂无明显告警。"))

    top = sorted(
        shortages,
        key=lambda r: float(r.get("to_buy_qty") or r.get("shortage_qty") or 0),
        reverse=True,
    )[:limit]
    chart = None
    if top:
        chart = _chart(
            chart_type="bar",
            title="缺料待采 Top",
            metric_id="analytics.supply_chain",
            x=[str(r.get("supplier_product_code") or r.get("supplier_product_name") or "")[:10] for r in top],
            series=[
                {
                    "name": "待采",
                    "data": [float(r.get("to_buy_qty") or r.get("shortage_qty") or 0) for r in top],
                }
            ],
        )

    return {
        "analysis_id": "supply_chain",
        "title": "缺料与采购诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "shortage_total": len(shortages),
            "rush_shortage_total": len(rush_short),
            "po_overdue": len(overdue),
            "po_due_soon": len(due_soon),
            "shortage_top": [
                {
                    "order_no": r.get("order_no"),
                    "is_rush": r.get("is_rush"),
                    "material": r.get("supplier_product_name") or r.get("supplier_product_code"),
                    "to_buy": _dec(r.get("to_buy_qty") or r.get("shortage_qty")),
                    "partner_name": r.get("partner_name"),
                }
                for r in top
            ],
        },
        "chart": chart,
    }


def _kit_priority_key(row: dict[str, Any]) -> tuple:
    return (
        0 if row.get("is_rush") and row.get("at_risk") else 1,
        0 if row.get("at_risk") else 1,
        0 if row.get("is_rush") else 1,
        str(row.get("delivery_date") or "9999"),
        int(row.get("order_id") or 0),
    )


def analyze_kit_ready(db: Session, tenant_id: int, *, limit: int = 12) -> dict[str, Any]:
    """齐套可排产：在制单按首道/整单齐套分成可排、半齐套、等料。"""
    board = progress_service.progress_board(db, tenant_id)
    board_orders = list(board.get("orders") or [])
    by_id = {int(o["id"]): o for o in board_orders if o.get("id") is not None}

    # 未排/已排都看：诊断「能不能开工」，不限于排产池
    candidates = schedule_engine.collect_candidate_orders(
        db, tenant_id, hide_scheduled=False, hide_first_kit_blocked=False
    )

    can_schedule: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    empty_bom: list[dict[str, Any]] = []

    order_ids = [int(c["order_id"]) for c in candidates]
    kit_map = material_service.order_kit_summaries(db, tenant_id, order_ids) if order_ids else {}

    for c in candidates:
        oid = int(c["order_id"])
        board_o = by_id.get(oid) or {}
        kit = kit_map.get(oid) or {}
        first_ok = bool(c.get("first_kit_ok", kit.get("first_kit_ok")))
        full_ok = bool(c.get("kit_ok", kit.get("kit_ok")))
        is_empty = bool(kit.get("empty_bom"))
        row = {
            "order_id": oid,
            "order_no": c.get("order_no"),
            "customer_name": c.get("customer_name") or board_o.get("customer_name"),
            "product_code": c.get("product_code") or board_o.get("product_code"),
            "total_qty": c.get("total_qty") or board_o.get("total_qty"),
            "delivery_date": c.get("delivery_date") or board_o.get("delivery_date"),
            "is_rush": bool(c.get("is_rush") or board_o.get("is_rush")),
            "at_risk": bool(board_o.get("at_risk")),
            "overall_percent": board_o.get("overall_percent"),
            "schedule_status": c.get("schedule_status"),
            "first_kit_ok": first_ok,
            "kit_ok": full_ok,
            "empty_bom": is_empty,
            "shortage_lines": int(kit.get("shortage_lines") or 0),
            "first_process_name": kit.get("first_process_name"),
            "verdict": (
                "empty_bom"
                if is_empty
                else (
                    "can_schedule"
                    if first_ok and full_ok
                    else ("partial" if first_ok else "blocked")
                )
            ),
        }
        if is_empty:
            empty_bom.append(row)
        elif first_ok and full_ok:
            can_schedule.append(row)
        elif first_ok:
            partial.append(row)
        else:
            blocked.append(row)

    for bucket in (can_schedule, partial, blocked, empty_bom):
        bucket.sort(key=_kit_priority_key)

    blocked_priority = [r for r in blocked if r.get("is_rush") or r.get("at_risk")] or blocked
    blocked_ids = [int(r["order_id"]) for r in blocked_priority[:limit]]
    shortage_rows: list[dict[str, Any]] = []
    if blocked_ids:
        raw = material_service.list_shortages(
            db,
            tenant_id,
            order_ids=blocked_ids,
            include_shared=True,
            hide_purchased=True,
            rush_only=False,
        )
        for r in raw[: limit * 2]:
            shortage_rows.append(
                {
                    "order_no": r.get("order_no"),
                    "is_rush": r.get("is_rush"),
                    "material": r.get("supplier_product_name") or r.get("supplier_product_code"),
                    "to_buy": _dec(r.get("to_buy_qty") or r.get("shortage_qty")),
                    "partner_name": r.get("partner_name"),
                    "purchase_status_label": r.get("purchase_status_label"),
                }
            )

    pri_can = [r for r in can_schedule if r.get("is_rush") or r.get("at_risk")]
    pri_partial = [r for r in partial if r.get("is_rush") or r.get("at_risk")]
    pri_blocked = [r for r in blocked if r.get("is_rush") or r.get("at_risk")]

    insights: list[dict[str, Any]] = []
    if pri_can:
        insights.append(
            _insight(
                "high",
                f"有 {len(pri_can)} 张急单/风险单已齐套，可立即排产开工。",
                order_nos=[r.get("order_no") for r in pri_can[:8]],
            )
        )
    elif can_schedule:
        insights.append(
            _insight(
                "medium",
                f"有 {len(can_schedule)} 张在制单整单齐套，可按交期排入方案。",
                order_nos=[r.get("order_no") for r in can_schedule[:8]],
            )
        )

    if pri_partial:
        insights.append(
            _insight(
                "medium",
                f"有 {len(pri_partial)} 张急/险单仅首道齐套：可先开工，后续工序仍缺料。",
                order_nos=[r.get("order_no") for r in pri_partial[:8]],
            )
        )
    elif partial:
        insights.append(
            _insight(
                "low",
                f"半齐套（仅首道可开工）{len(partial)} 单，注意后续缺料别卡死。",
            )
        )

    if pri_blocked:
        insights.append(
            _insight(
                "high",
                f"有 {len(pri_blocked)} 张急单/风险单首道未齐套，排产也开不了工——先催料。",
                order_nos=[r.get("order_no") for r in pri_blocked[:8]],
                shortages=shortage_rows[:8],
            )
        )
    elif blocked:
        insights.append(
            _insight(
                "medium",
                f"等料（首道未齐套）{len(blocked)} 单，勿盲目挤进排产。",
                order_nos=[r.get("order_no") for r in blocked[:8]],
            )
        )

    if empty_bom:
        insights.append(
            _insight(
                "medium",
                f"有 {len(empty_bom)} 张单无 BOM/用料快照，齐套结论不可靠，请先核对物料。",
                order_nos=[r.get("order_no") for r in empty_bom[:8]],
            )
        )

    if not insights:
        insights.append(_insight("low", "在制单齐套状态平稳，无明显可排/等料冲突。"))

    chart = _chart(
        chart_type="bar",
        title="齐套可排产分布",
        metric_id="analytics.kit_ready",
        x=["可排", "半齐套", "等料", "空BOM"],
        series=[
            {
                "name": "单数",
                "data": [len(can_schedule), len(partial), len(blocked), len(empty_bom)],
            }
        ],
        unit="单",
    )

    return {
        "analysis_id": "kit_ready",
        "title": "齐套可排产诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "counts": {
                "can_schedule": len(can_schedule),
                "partial": len(partial),
                "blocked": len(blocked),
                "empty_bom": len(empty_bom),
                "priority_can_schedule": len(pri_can),
                "priority_partial": len(pri_partial),
                "priority_blocked": len(pri_blocked),
            },
            "can_schedule": can_schedule[:limit],
            "partial": partial[:limit],
            "blocked": blocked[:limit],
            "empty_bom": empty_bom[:limit],
            "blocked_shortages": shortage_rows[:limit],
            "schedule_now_order_ids": [r["order_id"] for r in (pri_can or can_schedule)[:limit]],
            "playbook": [
                "1) 急/险 + 齐套 → generate_schedule_proposals（指定 order_ids）后人工确认",
                "2) 半齐套 → 可排首道，同时催后续缺料",
                "3) 等料急/险 → 先采购/到货，勿空排",
                "4) 空 BOM → 先补物料快照再谈齐套",
            ],
        },
        "chart": chart,
    }


def _peer_margins(db: Session, tenant_id: int, *, exclude_line_ids: set[int], limit: int = 80) -> list[float]:
    """近期已报价销售行毛利率样本（产品档案成本）。"""
    from app.models import OwnProduct, SalesOrderLine, SalesOrderLineStatus

    rows = list(
        db.scalars(
            select(SalesOrderLine)
            .where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.status != SalesOrderLineStatus.cancelled,
                SalesOrderLine.unit_price.is_not(None),
                SalesOrderLine.total_qty > 0,
            )
            .order_by(SalesOrderLine.id.desc())
            .limit(limit)
        ).all()
    )
    margins: list[float] = []
    for line in rows:
        if line.id in exclude_line_ids:
            continue
        price = float(line.unit_price or 0)
        if price <= 0:
            continue
        product = db.get(OwnProduct, line.own_product_id)
        if not product:
            continue
        unit_cost = float(product.material_cost or 0) + float(product.labor_cost or 0) + float(
            product.other_cost or 0
        )
        margins.append((price - unit_cost) / price)
    return margins


def _percentile_rank(value: float, sample: list[float]) -> float | None:
    if not sample:
        return None
    below = sum(1 for x in sample if x <= value)
    return round(below / len(sample), 3)


def analyze_order_intake(
    db: Session,
    tenant_id: int,
    *,
    lines: list[dict[str, Any]] | None = None,
    include_shared: bool = True,
    qty: int | None = None,
    delivery_date: str | date | None = None,
    is_rush: bool | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """接单/下生产前诊断：利润对比 + 缺料 + 虚拟插单交期冲击。

    可选覆盖 qty / delivery_date / is_rush / strategy 仅用于仿真，不改库。
    """
    from app.models import OwnProduct, SalesOrderLineStatus
    from app.services import sales_order_service
    from app.services.material_service import simulate_mrp_from_bom

    refs_in = lines or []
    refs: list[tuple[int, int]] = []
    overrides_by_line: dict[int, dict[str, Any]] = {}
    for item in refs_in:
        try:
            so_id = int(item.get("sales_order_id"))
            line_id = int(item.get("line_id") or item.get("sales_order_line_id"))
        except (TypeError, ValueError):
            continue
        refs.append((so_id, line_id))
        ov: dict[str, Any] = {}
        if item.get("qty") is not None:
            ov["qty"] = int(item["qty"])
        if item.get("delivery_date") is not None:
            ov["delivery_date"] = item["delivery_date"]
        if item.get("is_rush") is not None:
            ov["is_rush"] = bool(item["is_rush"])
        if ov:
            overrides_by_line[line_id] = ov
    if not refs:
        return {
            "analysis_id": "order_intake",
            "title": "接单冲击诊断",
            "as_of": _today().isoformat(),
            "summary": "未提供可分析的销售订单产品行。",
            "insights": [_insight("medium", "请传入 lines: [{sales_order_id, line_id}, …]。")],
            "data": {"verdict": "unknown", "lines": []},
            "chart": None,
        }

    # 全局覆盖（追问场景：整批同一假设）
    global_qty = int(qty) if qty is not None else None
    global_delivery: date | None = None
    if delivery_date:
        if isinstance(delivery_date, date):
            global_delivery = delivery_date
        else:
            global_delivery = date.fromisoformat(str(delivery_date)[:10])
    global_rush = bool(is_rush) if is_rush is not None else None
    hypothesis = bool(
        global_qty is not None
        or global_delivery is not None
        or global_rush is not None
        or overrides_by_line
        or strategy
    )

    so_cache: dict[int, Any] = {}
    line_rows: list[dict[str, Any]] = []
    demands_mrp: list[dict[str, Any]] = []
    intake_demands: list[schedule_engine.IntakeDemand] = []

    for so_id, line_id in refs:
        so = so_cache.get(so_id)
        if not so:
            try:
                so = sales_order_service.get_sales_order(db, tenant_id, so_id)
            except sales_order_service.SalesOrderError:
                continue
            so_cache[so_id] = so
        line = next((l for l in so.lines if l.id == line_id), None)
        if not line:
            continue
        product = db.get(OwnProduct, line.own_product_id) if line.own_product_id else None
        ov = overrides_by_line.get(line_id) or {}
        sim_qty = int(ov.get("qty") if ov.get("qty") is not None else (global_qty if global_qty is not None else line.total_qty or 0))
        dd_raw = ov.get("delivery_date") if ov.get("delivery_date") is not None else (
            global_delivery if global_delivery is not None else line.delivery_date
        )
        if isinstance(dd_raw, str) and dd_raw:
            sim_dd: date | None = date.fromisoformat(dd_raw[:10])
        elif isinstance(dd_raw, date):
            sim_dd = dd_raw
        else:
            sim_dd = None
        sim_rush = bool(ov["is_rush"]) if "is_rush" in ov else (
            bool(global_rush) if global_rush is not None else False
        )
        unit_price = float(line.unit_price) if line.unit_price is not None else None
        unit_cost = 0.0
        if product:
            unit_cost = float(product.material_cost or 0) + float(product.labor_cost or 0) + float(
                product.other_cost or 0
            )
        revenue = (unit_price or 0.0) * sim_qty
        cost = unit_cost * sim_qty
        profit = revenue - cost
        margin = (profit / revenue) if revenue > 0 else None
        status = line.status.value if hasattr(line.status, "value") else str(line.status)
        product_code = product.product_code if product else None
        line_rows.append(
            {
                "sales_order_id": so.id,
                "line_id": line.id,
                "order_no": so.order_no,
                "customer_id": so.customer_id,
                "customer_name": so.customer_name,
                "product_code": product_code,
                "own_product_id": line.own_product_id,
                "qty": sim_qty,
                "qty_order": int(line.total_qty or 0),
                "unit_price": unit_price,
                "unit_cost": round(unit_cost, 4),
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(profit, 2),
                "margin": round(margin, 4) if margin is not None else None,
                "delivery_date": sim_dd.isoformat() if sim_dd else None,
                "delivery_date_order": line.delivery_date.isoformat() if line.delivery_date else None,
                "is_rush_sim": sim_rush,
                "status": status,
                "production_order_id": line.production_order_id,
                "can_confirm": status == SalesOrderLineStatus.pending.value
                and not line.production_order_id
                and int(line.total_qty or 0) > 0,
            }
        )
        if line.own_product_id and sim_qty > 0:
            label = " · ".join(x for x in [so.order_no, product_code] if x)
            demands_mrp.append(
                {
                    "key": f"so_line:{line.id}",
                    "label": label,
                    "order_no": so.order_no,
                    "product_code": product_code,
                    "own_product_id": line.own_product_id,
                    "total_qty": sim_qty,
                    "delivery_date": sim_dd,
                    "priority_key": (
                        sim_dd.toordinal() if sim_dd else 10**9,
                        so.id,
                        line.id,
                    ),
                }
            )
            intake_demands.append(
                schedule_engine.IntakeDemand(
                    key=f"so_line:{line.id}",
                    order_no=so.order_no,
                    own_product_id=int(line.own_product_id),
                    total_qty=sim_qty,
                    delivery_date=sim_dd,
                    is_rush=sim_rush,
                    first_kit_ok=True,
                    kit_ok=True,
                )
            )

    if not line_rows:
        return {
            "analysis_id": "order_intake",
            "title": "接单冲击诊断",
            "as_of": _today().isoformat(),
            "summary": "未找到可分析的销售行。",
            "insights": [_insight("high", "销售行不存在或无权访问。")],
            "data": {"verdict": "unknown", "lines": []},
            "chart": None,
        }

    if demands_mrp:
        mrp = simulate_mrp_from_bom(
            db, tenant_id, demands_mrp, include_shared=include_shared, shortages_only=False
        )
    else:
        mrp = {"kit_ok": True, "empty_bom": True, "shortage_lines": 0, "lines": [], "skipped": []}

    tot_qty = sum(int(r["qty"]) for r in line_rows)
    tot_rev = sum(float(r["revenue"]) for r in line_rows)
    tot_cost = sum(float(r["cost"]) for r in line_rows)
    tot_profit = tot_rev - tot_cost
    tot_margin = (tot_profit / tot_rev) if tot_rev > 0 else None

    kit_ok = bool(mrp.get("kit_ok"))
    shortage_n = int(mrp.get("shortage_lines") or 0)
    empty_bom = bool(mrp.get("empty_bom"))
    mrp_lines_all = list(mrp.get("lines") or [])
    shortage_rows_raw = [
        r for r in mrp_lines_all if float(r.get("shortage_qty") or 0) > 0
    ]
    # 缺料多的在前，便于军师表格展示
    shortage_rows_raw.sort(
        key=lambda r: -float(r.get("shortage_qty") or 0),
    )
    shortage_top = [
        {
            "supplier_product_id": r.get("supplier_product_id"),
            "supplier_product_code": r.get("supplier_product_code"),
            "supplier_product_name": r.get("supplier_product_name"),
            "material": r.get("supplier_product_name") or r.get("supplier_product_code"),
            "shortage_qty": _dec(r.get("shortage_qty")),
            "required_qty": _dec(r.get("required_qty")),
            "partner_id": r.get("partner_id"),
            "partner_name": r.get("partner_name"),
        }
        for r in shortage_rows_raw
    ][:20]

    today = _today()
    material_eta = purchase_service.estimate_material_etas(
        db, tenant_id, shortage_top, as_of=today
    )
    eta_start: date | None = None
    if material_eta.get("earliest_start"):
        eta_start = date.fromisoformat(str(material_eta["earliest_start"])[:10])

    # 缺料：仿真从 ETA 开工（假设到齐后再开）；齐套则立即可开
    for d in intake_demands:
        if kit_ok or empty_bom:
            d.first_kit_ok = True
            d.kit_ok = True
            d.earliest_start = None
        else:
            # 假设 ETA 后齐套
            d.first_kit_ok = True
            d.kit_ok = True
            d.earliest_start = eta_start

    # 客户回款（取第一行客户）
    cust_id = line_rows[0].get("customer_id")
    cust_name = line_rows[0].get("customer_name")
    pay_risk = finance_service.customer_pay_risk(
        db, tenant_id, customer_id=cust_id, customer_name=cust_name
    )

    peer_sample = _peer_margins(
        db, tenant_id, exclude_line_ids={int(r["line_id"]) for r in line_rows}
    )
    peer_median = None
    if peer_sample:
        sorted_m = sorted(peer_sample)
        mid = len(sorted_m) // 2
        peer_median = (
            sorted_m[mid]
            if len(sorted_m) % 2 == 1
            else (sorted_m[mid - 1] + sorted_m[mid]) / 2
        )
    margin_vs_peers = {
        "sample_size": len(peer_sample),
        "peer_median_margin": round(peer_median, 4) if peer_median is not None else None,
        "this_margin": round(tot_margin, 4) if tot_margin is not None else None,
        "percentile": _percentile_rank(tot_margin, peer_sample) if tot_margin is not None else None,
        "delta_pp": round((tot_margin - peer_median) * 100, 2)
        if tot_margin is not None and peer_median is not None
        else None,
    }

    sim = schedule_engine.simulate_intake_demands(
        db,
        tenant_id,
        intake_demands,
        as_of=today,
        strategy_filter=strategy or None,
    )
    sim_error = sim.get("sim_error")
    proposals = list(sim.get("proposals") or [])
    primary = next((p for p in proposals if p.get("strategy") == "protect_delivery"), proposals[0] if proposals else None)
    impacts = list((primary or {}).get("impacts") or [])
    intake_orders = list((primary or {}).get("intake_orders") or [])
    peer_hit = len(impacts)
    delayed = [i for i in impacts if int(i.get("delay_days") or 0) > 0]
    self_late = any(o.get("risk") == "late" for o in intake_orders)
    self_finish = intake_orders[0].get("projected_finish") if intake_orders else None
    self_risk = intake_orders[0].get("risk") if intake_orders else None
    self_risk_label = schedule_engine.risk_label_zh(self_risk) if self_risk else None
    peer_order_nos = [str(i.get("order_no") or "") for i in impacts if i.get("order_no")]

    # 缺料 ETA 是否本身就晚于交期
    material_blocks_delivery = False
    if eta_start and line_rows:
        for r in line_rows:
            dd = r.get("delivery_date")
            if dd and eta_start > date.fromisoformat(str(dd)[:10]):
                material_blocks_delivery = True
                break

    # 裁决
    reasons: list[str] = []
    severity_flags: list[str] = []
    if tot_margin is not None and tot_margin < 0:
        severity_flags.append("loss")
        reasons.append(f"毛利为负 {tot_profit:.0f} 元（{(tot_margin or 0)*100:.1f}%）")
    elif tot_margin is not None and tot_margin < 0.08:
        severity_flags.append("thin_margin")
        reasons.append(f"毛利率 {(tot_margin or 0)*100:.1f}% 偏低")
    if margin_vs_peers.get("delta_pp") is not None and margin_vs_peers["delta_pp"] <= -5:
        severity_flags.append("below_peers")
        reasons.append(f"毛利低于厂内中位 {abs(margin_vs_peers['delta_pp']):.1f} 个百分点")

    if empty_bom:
        severity_flags.append("empty_bom")
        reasons.append("无 BOM")
    elif not kit_ok and shortage_n > 0:
        severity_flags.append("shortage")
        if eta_start:
            reasons.append(f"缺料 {shortage_n} 项，预计齐套 {eta_start.isoformat()}")
        else:
            reasons.append(f"缺料 {shortage_n} 项")
        if material_blocks_delivery:
            severity_flags.append("material_late")
            reasons.append("预计到料日已晚于交期")

    if pay_risk.get("risk") == "high":
        severity_flags.append("pay_risk")
        reasons.append(pay_risk.get("risk_label") or "回款风险高")
    elif pay_risk.get("risk") == "medium":
        severity_flags.append("pay_risk_med")
        reasons.append(pay_risk.get("risk_label") or "回款需关注")

    if sim_error == "no_route":
        severity_flags.append("no_route")
        reasons.append(sim.get("message") or "无工序路线，无法仿真")
    elif sim_error:
        severity_flags.append("sim_error")
        reasons.append(sim.get("message") or str(sim_error))
    else:
        if self_late:
            severity_flags.append("self_late")
            reasons.append(f"本单仿真完工 {self_finish or '—'}，{self_risk_label or '预计逾期'}")
        elif self_risk == "tight":
            severity_flags.append("self_tight")
            reasons.append(f"本单仿真完工 {self_finish or '—'}，交期偏紧（几乎无缓冲）")
        if delayed:
            severity_flags.append("peer_impact")
            top = "、".join(
                f"{i.get('order_no')}延{i.get('delay_days')}日" for i in delayed[:5]
            )
            if len(delayed) > 5:
                reasons.append(f"挤其它单：{top}等共{len(delayed)}张")
            else:
                reasons.append(f"挤其它单：{top}")
        elif peer_hit:
            severity_flags.append("peer_impact")
            nos = "、".join(peer_order_nos[:5])
            suffix = "等" if len(peer_order_nos) > 5 else ""
            reasons.append(f"改变其它单风险 {peer_hit} 处：{nos}{suffix}")

    if (
        "loss" in severity_flags
        or "material_late" in severity_flags
        or ("self_late" in severity_flags and "shortage" in severity_flags)
        or (
            "peer_impact" in severity_flags
            and "shortage" in severity_flags
            and "thin_margin" in severity_flags
        )
        or ("pay_risk" in severity_flags and "thin_margin" in severity_flags)
    ):
        verdict = "reject"
        verdict_label = "不建议接产"
    elif severity_flags:
        verdict = "caution"
        verdict_label = "谨慎接产"
    else:
        verdict = "accept"
        verdict_label = "建议接产"
        reasons.append("毛利/齐套/交期冲击/回款未见红灯")

    # 缺料表附预计到料日；物料行：缺料在前
    eta_by_sp = {
        int(it["supplier_product_id"]): it
        for it in (material_eta.get("items") or [])
        if it.get("supplier_product_id") is not None
    }
    for row in shortage_top:
        sp = row.get("supplier_product_id")
        try:
            sp_i = int(sp) if sp is not None else None
        except (TypeError, ValueError):
            sp_i = None
        if sp_i is not None and sp_i in eta_by_sp:
            row["eta"] = eta_by_sp[sp_i].get("eta")
            row["expected_ready_date"] = (
                eta_by_sp[sp_i].get("expected_ready_date") or row["eta"]
            )
            row["eta_source"] = eta_by_sp[sp_i].get("source")

    material_lines: list[dict[str, Any]] = []
    for r in mrp_lines_all:
        sp_id = r.get("supplier_product_id")
        try:
            sp_i = int(sp_id) if sp_id is not None else None
        except (TypeError, ValueError):
            sp_i = None
        eta_it = eta_by_sp.get(sp_i) if sp_i is not None else None
        material_lines.append(
            {
                "supplier_product_id": sp_id,
                "code": r.get("supplier_product_code") or "",
                "name": r.get("supplier_product_name") or r.get("supplier_product_code") or "",
                "required_qty": _dec(r.get("required_qty")),
                "shortage_qty": _dec(r.get("shortage_qty")),
                "expected_ready_date": (eta_it or {}).get("expected_ready_date")
                or (eta_it or {}).get("eta"),
                "partner_name": r.get("partner_name"),
            }
        )
    material_lines.sort(
        key=lambda x: (
            0 if float(x.get("shortage_qty") or 0) > 0 else 1,
            -float(x.get("shortage_qty") or 0),
            str(x.get("code") or ""),
        )
    )
    # 缺料优先展示，齐套行可截断
    material_lines_out = [
        * [x for x in material_lines if float(x.get("shortage_qty") or 0) > 0][:20],
        * [x for x in material_lines if float(x.get("shortage_qty") or 0) <= 0][:8],
    ]

    insights = [
        _insight(
            "high" if verdict == "reject" else ("medium" if verdict == "caution" else "low"),
            f"{verdict_label}：{'；'.join(reasons[:3])}",
            verdict=verdict,
        )
    ]
    if material_eta.get("earliest_start") and not kit_ok and not empty_bom:
        insights.append(
            _insight(
                "high" if material_blocks_delivery else "medium",
                f"预计齐套日 {material_eta['earliest_start']}"
                + ("，已晚于交期" if material_blocks_delivery else "，仿真自该日起开工"),
            )
        )
    elif pay_risk.get("risk") in ("high", "medium"):
        insights.append(
            _insight(
                "high" if pay_risk.get("risk") == "high" else "medium",
                f"{pay_risk.get('risk_label')}：{'；'.join(pay_risk.get('reasons') or [])}",
            )
        )
    if primary and not sim_error:
        if delayed:
            impact_txt = "、".join(
                f"{i.get('order_no')}延{i.get('delay_days')}日" for i in delayed[:5]
            )
        elif peer_order_nos:
            impact_txt = "、".join(peer_order_nos[:5]) + ("等" if len(peer_order_nos) > 5 else "")
        else:
            impact_txt = "无"
        insights.append(
            _insight(
                "high" if delayed or self_late else ("medium" if self_risk == "tight" else "low"),
                f"仿真({primary.get('strategy')})：本单 {self_finish or '—'}（{self_risk_label or '—'}）；"
                f"影响其它单 {peer_hit} 张"
                + (f"：{impact_txt}" if peer_hit else ""),
            )
        )
    insights = insights[:3]

    # 仅在「挤其它单延期」时出图（缺料/利润已有表，不再画柱）
    chart = None
    if delayed:
        chart = _chart(
            chart_type="bar",
            title="接产对其它单延期(日)",
            metric_id="analytics.order_intake",
            x=[str(i.get("order_no") or "")[:12] for i in delayed[:8]],
            series=[{"name": "延期", "data": [int(i.get("delay_days") or 0) for i in delayed[:8]]}],
            unit="日",
        )

    return {
        "analysis_id": "order_intake",
        "title": "接单冲击诊断",
        "as_of": today.isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "verdict": verdict,
            "verdict_label": verdict_label,
            "reasons": reasons[:5],
            "hypothesis": hypothesis,
            "hypothesis_note": "以下含仿真假设时未改订单；确认生产按库内原数量。"
            if hypothesis
            else None,
            "profit": {
                "qty": tot_qty,
                "revenue": round(tot_rev, 2),
                "cost": round(tot_cost, 2),
                "profit": round(tot_profit, 2),
                "margin": round(tot_margin, 4) if tot_margin is not None else None,
            },
            "margin_vs_peers": margin_vs_peers,
            "kit": {
                "kit_ok": kit_ok,
                "empty_bom": empty_bom,
                "shortage_lines": shortage_n,
                "shortage_top": shortage_top,
                "material_lines": material_lines_out,
            },
            "material_eta": material_eta,
            "customer_pay_risk": pay_risk,
            "schedule_sim": {
                "sim_error": sim_error,
                "message": sim.get("message"),
                "strategy_primary": (primary or {}).get("strategy"),
                "earliest_start": eta_start.isoformat() if eta_start else None,
                "intake_finish": self_finish,
                "intake_risk": self_risk,
                "intake_risk_label": self_risk_label,
                "intake_risk_hint": (
                    "完工日贴近交期，几乎没有缓冲"
                    if self_risk == "tight"
                    else (
                        "预计完工晚于交期"
                        if self_risk == "late"
                        else None
                    )
                ),
                "impact_count": peer_hit,
                "delayed_count": len(delayed),
                "impacted_order_nos": peer_order_nos[:12],
                "impacts": [
                    {
                        "order_no": i.get("order_no"),
                        "delay_days": i.get("delay_days"),
                        "old_risk": i.get("old_risk"),
                        "new_risk": i.get("new_risk"),
                        "old_risk_label": i.get("old_risk_label")
                        or schedule_engine.risk_label_zh(i.get("old_risk")),
                        "new_risk_label": i.get("new_risk_label")
                        or schedule_engine.risk_label_zh(i.get("new_risk")),
                        "old_finish": i.get("old_finish"),
                        "new_finish": i.get("new_finish"),
                    }
                    for i in impacts[:10]
                ],
                "proposals": [
                    {
                        "strategy": p.get("strategy"),
                        "title": p.get("title"),
                        "summary": p.get("summary"),
                        "impact_count": len(p.get("impacts") or []),
                        "impacted_order_nos": [
                            str(i.get("order_no") or "")
                            for i in (p.get("impacts") or [])
                            if i.get("order_no")
                        ][:12],
                        "intake_orders": [
                            {
                                **o,
                                "risk_label": o.get("risk_label")
                                or schedule_engine.risk_label_zh(o.get("risk")),
                            }
                            for o in (p.get("intake_orders") or [])
                        ],
                    }
                    for p in proposals
                ],
            },
            "lines": line_rows,
            "human_gate": {
                "confirm_label": "确认生产",
                "cancel_label": "取消订单",
                "note": "须界面人工点击；确认按订单原数量。",
            },
            "playbook": [
                "1) verdict",
                "2) 利润表 + 物料表（编号/名称/需求/缺口/预计到料日）+ 回款",
                "3) 交期冲击 impacts",
                "4) 人点确认生产/取消",
            ],
        },
        "chart": chart,
    }


def analyze_finance(db: Session, tenant_id: int, *, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """利润、回款、应收。"""
    y, m = _ym(year, month)
    kpi = finance_service.business_kpi(db, tenant_id, year=y, month=m)
    profit = finance_service.profit_report(db, tenant_id, year=y, month=m)
    ar_rows = finance_service.list_receivables(db, tenant_id, status="open")

    orders = list((profit.get("orders") or profit.get("items") or []))
    # tolerate shapes
    loss_orders = []
    for o in orders:
        gp = o.get("gross_profit")
        if gp is None:
            gp = o.get("profit")
        try:
            if float(gp or 0) < 0:
                loss_orders.append(o)
        except Exception:
            continue

    ar_balances = []
    for r in ar_rows:
        bal = r.get("balance")
        if bal is None:
            try:
                bal = float(r.get("amount") or 0) + float(r.get("adjustment") or 0) - float(
                    r.get("received_amount") or 0
                )
            except Exception:
                bal = 0
        if float(bal or 0) > 0.01:
            ar_balances.append({**r, "balance": float(bal)})

    ar_balances.sort(key=lambda x: -float(x.get("balance") or 0))
    ship = float(kpi.get("shipment_amount") or 0)
    pay = float(kpi.get("payment_amount") or 0)
    gp = float(kpi.get("gross_profit") or 0)
    ar = float(kpi.get("customer_ar_balance") or 0)

    insights: list[dict[str, Any]] = []
    if gp < 0:
        insights.append(_insight("high", f"{y}-{m:02d} 估毛利为负（{round(gp, 0)}），需复查亏损出货单。"))
    elif ship > 0 and gp / ship < 0.08:
        insights.append(_insight("medium", f"{y}-{m:02d} 毛利率偏低（约 {gp / ship * 100:.1f}%）。"))
    if loss_orders:
        insights.append(
            _insight(
                "high",
                f"本月有 {len(loss_orders)} 笔出货估亏，优先复盘报价与成本。",
                samples=[
                    {
                        "order_no": o.get("order_no"),
                        "customer_name": o.get("customer_name"),
                        "gross_profit": _dec(o.get("gross_profit") if o.get("gross_profit") is not None else o.get("profit")),
                    }
                    for o in loss_orders[:8]
                ],
            )
        )
    if ship > 0 and pay < ship * 0.5:
        insights.append(
            _insight(
                "medium",
                f"本月回款（{round(pay, 0)}）明显低于出货（{round(ship, 0)}），现金流可能承压。",
            )
        )
    if ar_balances[:5]:
        insights.append(
            _insight(
                "medium" if ar < ship else "high",
                f"未结应收约 {round(ar, 0)}，头部客户占用明显。",
                top_customers=[
                    {
                        "customer_name": r.get("customer_name") or r.get("partner_name"),
                        "balance": round(float(r.get("balance") or 0), 2),
                        "order_no": r.get("order_no"),
                    }
                    for r in ar_balances[:8]
                ],
            )
        )
    if not insights:
        insights.append(_insight("low", f"{y}-{m:02d} 经营指标暂无突出告警。"))

    chart = _chart(
        chart_type="bar",
        title=f"{y}-{m:02d} 经营对比",
        metric_id="analytics.finance_health",
        x=["出货", "回款", "毛利", "欠款"],
        series=[{"name": "金额", "data": [round(ship, 0), round(pay, 0), round(gp, 0), round(ar, 0)]}],
        unit="元",
    )

    return {
        "analysis_id": "finance_health",
        "title": "经营财务诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "year": y,
            "month": m,
            "kpi": {k: _dec(v) for k, v in (kpi or {}).items()},
            "loss_order_count": len(loss_orders),
            "open_ar_rows": len(ar_balances),
        },
        "chart": chart,
    }


def analyze_quality(db: Session, tenant_id: int, *, days: int = 30) -> dict[str, Any]:
    """不良热点：近 N 日报工合格/不良。"""
    days = max(7, min(int(days or 30), 90))
    since = _today() - timedelta(days=days - 1)
    logs = salary_service.list_work_logs(db, tenant_id, status="confirmed", page=1, page_size=500)
    by_process: dict[str, dict[str, float]] = {}
    total_q = 0.0
    total_d = 0.0
    for row in logs.get("items") or []:
        created = str(row.get("created_at") or "")[:10]
        if created and created < since.isoformat():
            continue
        pn = str(row.get("process_name") or "未知")
        q = float(row.get("qualified_qty") or 0)
        d = float(row.get("defect_qty") or 0)
        bucket = by_process.setdefault(pn, {"qualified": 0.0, "defect": 0.0})
        bucket["qualified"] += q
        bucket["defect"] += d
        total_q += q
        total_d += d

    rows = []
    for pn, v in by_process.items():
        tot = v["qualified"] + v["defect"]
        rate = (v["defect"] / tot * 100) if tot else 0.0
        rows.append(
            {
                "process_name": pn,
                "qualified_qty": round(v["qualified"], 1),
                "defect_qty": round(v["defect"], 1),
                "defect_rate_pct": round(rate, 2),
            }
        )
    rows.sort(key=lambda r: (-r["defect_rate_pct"], -r["defect_qty"]))

    overall_rate = (total_d / (total_q + total_d) * 100) if (total_q + total_d) else 0.0
    insights: list[dict[str, Any]] = []
    hot = [r for r in rows if r["defect_qty"] > 0 and r["defect_rate_pct"] >= 3]
    if hot:
        insights.append(
            _insight(
                "high" if hot[0]["defect_rate_pct"] >= 8 else "medium",
                f"近 {days} 日不良偏高工序：{hot[0]['process_name']}（不良率 {hot[0]['defect_rate_pct']}%）。",
                hotspots=hot[:5],
            )
        )
    insights.append(
        _insight(
            "low" if overall_rate < 2 else "medium",
            f"近 {days} 日整体不良率约 {overall_rate:.2f}%（合格 {int(total_q)} / 不良 {int(total_d)}）。",
        )
    )

    chart = None
    top = rows[:8]
    if top:
        chart = _chart(
            chart_type="bar",
            title=f"近{days}日工序不良率",
            metric_id="analytics.quality_hotspots",
            x=[r["process_name"] for r in top],
            series=[{"name": "不良率", "data": [r["defect_rate_pct"] for r in top]}],
            unit="%",
        )

    return {
        "analysis_id": "quality_hotspots",
        "title": "质量不良诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {"days": days, "overall_defect_rate_pct": round(overall_rate, 2), "by_process": rows[:20]},
        "chart": chart,
    }


def analyze_labor(db: Session, tenant_id: int, *, year_month: str | None = None) -> dict[str, Any]:
    """人效/工资：本月计件与应付。"""
    if not year_month:
        t = _today()
        year_month = f"{t.year:04d}-{t.month:02d}"
    data = salary_service.month_salary_all(db, tenant_id, year_month)
    items = list(data.get("items") or [])
    items_sorted = sorted(items, key=lambda x: float(x.get("total_wage") or x.get("payable") or 0), reverse=True)

    insights: list[dict[str, Any]] = []
    if not items_sorted:
        insights.append(_insight("low", f"{year_month} 暂无工资/计件数据。"))
    else:
        top = items_sorted[0]
        insights.append(
            _insight(
                "low",
                f"{year_month} 计件人数 {len(items_sorted)}；产出工资最高："
                f"{top.get('worker_name') or top.get('display_name') or top.get('worker_id')}。",
                top_workers=[
                    {
                        "worker": w.get("worker_name") or w.get("display_name") or w.get("worker_id"),
                        "qty": w.get("qualified_qty") or w.get("piece_qty"),
                        "total_wage": _dec(w.get("total_wage") or w.get("payable")),
                    }
                    for w in items_sorted[:8]
                ],
            )
        )
        zero = [w for w in items_sorted if float(w.get("qualified_qty") or w.get("piece_qty") or 0) <= 0]
        if zero:
            insights.append(_insight("medium", f"有 {len(zero)} 名在职员工本月尚无计件产量。"))

    chart = None
    top8 = items_sorted[:8]
    if top8:
        chart = _chart(
            chart_type="bar",
            title=f"{year_month} 工资 Top",
            metric_id="analytics.labor_efficiency",
            x=[str(w.get("worker_name") or w.get("display_name") or w.get("worker_id") or "") for w in top8],
            series=[
                {
                    "name": "应付",
                    "data": [float(w.get("total_wage") or w.get("payable") or 0) for w in top8],
                }
            ],
            unit="元",
        )

    return {
        "analysis_id": "labor_efficiency",
        "title": "人效与工资诊断",
        "as_of": _today().isoformat(),
        "summary": insights[0]["text"],
        "insights": insights,
        "data": {
            "year_month": year_month,
            "worker_count": len(items_sorted),
            "totals": {
                "piece_qty": _dec(data.get("total_qty") or data.get("grand_qty")),
                "total_wage": _dec(data.get("total_wage") or data.get("grand_total")),
            },
        },
        "chart": chart,
    }


def build_today_actions(db: Session, tenant_id: int) -> dict[str, Any]:
    """把诊断结论收敛成「今日行动清单」，并给出军师下一步工具提示。"""
    delivery = analyze_delivery(db, tenant_id)
    kit = analyze_kit_ready(db, tenant_id)
    capacity = analyze_capacity(db, tenant_id, days=14)
    supply = analyze_supply(db, tenant_id)
    finance = analyze_finance(db, tenant_id)
    quality = analyze_quality(db, tenant_id, days=14)

    actions: list[dict[str, Any]] = []
    suggested_memories: list[dict[str, str]] = []

    # 齐套可排：优先于「空谈保交期」
    kdata = kit.get("data") or {}
    kcounts = kdata.get("counts") or {}
    if int(kcounts.get("priority_can_schedule") or 0) > 0 or (
        int(kcounts.get("can_schedule") or 0) > 0
        and (int((delivery.get("data") or {}).get("late_count") or 0) > 0)
    ):
        focus = (kdata.get("can_schedule") or [])[:6]
        pri = [r for r in focus if r.get("is_rush") or r.get("at_risk")] or focus
        actions.append(
            {
                "priority": 1,
                "severity": "high",
                "title": "可排：齐套急/险单先出方案",
                "why": kit.get("summary"),
                "do": "对已齐套订单生成排产方案，采用后进草稿，人工确认落库。",
                "agent_next": ["generate_schedule_proposals", "query_metric:analytics.kit_ready"],
                "ui_path": "/admin/schedule",
                "orders": [r.get("order_no") for r in pri],
                "order_ids": [r.get("order_id") for r in pri if r.get("order_id")],
            }
        )

    if int(kcounts.get("priority_blocked") or 0) > 0:
        blocked = [r for r in (kdata.get("blocked") or []) if r.get("is_rush") or r.get("at_risk")][:6]
        actions.append(
            {
                "priority": 1,
                "severity": "high",
                "title": "等料：急/险单首道未齐套先催料",
                "why": "急单/风险单缺首道料，排进计划也开不了工。",
                "do": "按缺料行催采购/到货；齐套后再让军师出排产方案。",
                "agent_next": ["query_metric:analytics.kit_ready", "query_metric:materials.shortages"],
                "ui_path": "/admin/purchase",
                "orders": [r.get("order_no") for r in blocked],
                "shortages": (kdata.get("blocked_shortages") or [])[:6],
            }
        )
    elif int(kcounts.get("priority_partial") or 0) > 0:
        partial = [r for r in (kdata.get("partial") or []) if r.get("is_rush") or r.get("at_risk")][:6]
        actions.append(
            {
                "priority": 2,
                "severity": "medium",
                "title": "半齐套：可先开工并盯后续缺料",
                "why": "首道齐套可开工，后续工序仍缺料。",
                "do": "可排首道；同时催后续物料，避免中途断档。",
                "agent_next": ["generate_schedule_proposals", "query_metric:analytics.kit_ready"],
                "ui_path": "/admin/schedule",
                "orders": [r.get("order_no") for r in partial],
            }
        )

    # 交期 / 急单（无齐套可排结论时仍提示）
    ddata = delivery.get("data") or {}
    if int(ddata.get("late_rush_count") or 0) > 0 or int(ddata.get("late_count") or 0) > 0:
        if not any(a.get("title", "").startswith("可排") for a in actions):
            focus = ddata.get("focus_orders") or []
            actions.append(
                {
                    "priority": 1,
                    "severity": "high",
                    "title": "保交期：先处理风险单/急单",
                    "why": delivery.get("summary"),
                    "do": "打开生产订单/排产，按交期与急单重排优先级；必要时生成排产方案后人工确认。",
                    "agent_next": ["generate_schedule_proposals", "query_metric:analytics.delivery_risk"],
                    "ui_path": "/admin/schedule",
                    "orders": [o.get("order_no") for o in focus[:6] if o.get("at_risk") or o.get("is_rush")],
                }
            )

    # 负荷
    cdata = capacity.get("data") or {}
    if int(cdata.get("over_capacity_days") or 0) > 0:
        actions.append(
            {
                "priority": 2,
                "severity": "high",
                "title": "削峰：处理未来超产能工序日",
                "why": capacity.get("summary"),
                "do": "查看排产负荷，对过载工序后移非急单或加人；可先 simulate_insert / 重新出方案。",
                "agent_next": ["get_daily_load", "generate_schedule_proposals"],
                "ui_path": "/admin/schedule",
                "hotspots": (cdata.get("hotspots") or [])[:5],
            }
        )

    for row in (cdata.get("capacity_calibration") or [])[:4]:
        pn = str(row.get("process_name") or "")
        if not pn:
            continue
        suggested_memories.append(
            {
                "key": f"capacity_calib_{pn}"[:80],
                "text": (
                    f"「{pn}」设定产能 {row.get('configured_capacity')}，"
                    f"近14日实际日均约 {row.get('actual_daily_avg_14d')}（比值 {row.get('ratio')}）。"
                    "后续排产评估请参考实际产能，勿盲目按设定值。"
                ),
            }
        )
        actions.append(
            {
                "priority": 5,
                "severity": "medium",
                "title": f"校准「{pn}」产能参数",
                "why": f"设定产能与近14日实际偏差较大（比值 {row.get('ratio')}）。",
                "do": "在车间/排产设置中下调或上调该工序产能，并让军师写入长期记忆。",
                "agent_next": ["remember_user_fact", "get_schedule_settings"],
                "ui_path": "/admin/workshop-settings",
            }
        )

    # 缺料采购
    sdata = supply.get("data") or {}
    if int(sdata.get("rush_shortage_total") or 0) > 0 or int(sdata.get("po_overdue") or 0) > 0:
        actions.append(
            {
                "priority": 3,
                "severity": "high",
                "title": "齐套：催缺料与逾期采购",
                "why": supply.get("summary"),
                "do": "优先处理急单缺料行；对逾期 PO 跟催供应商到货。",
                "agent_next": ["query_metric:analytics.supply_chain", "query_metric:materials.shortages"],
                "ui_path": "/admin/purchase",
                "shortage_top": (sdata.get("shortage_top") or [])[:5],
            }
        )
    elif int(sdata.get("shortage_total") or 0) >= 10:
        actions.append(
            {
                "priority": 4,
                "severity": "medium",
                "title": "消化待采缺料清单",
                "why": supply.get("summary"),
                "do": "按待采量排序建采购或锁池。",
                "agent_next": ["query_metric:materials.shortages"],
                "ui_path": "/admin/purchase",
            }
        )

    # 财务
    fdata = finance.get("data") or {}
    if int(fdata.get("loss_order_count") or 0) > 0:
        actions.append(
            {
                "priority": 4,
                "severity": "medium",
                "title": "复盘亏损出货单",
                "why": finance.get("summary"),
                "do": "核对报价、BOM 成本与计件单价，避免继续亏本接单。",
                "agent_next": ["query_metric:analytics.finance_health", "query_metric:finance.profit_report"],
                "ui_path": "/admin/profit",
            }
        )

    # 质量
    qdata = quality.get("data") or {}
    rate = float(qdata.get("overall_defect_rate_pct") or 0)
    if rate >= 3:
        actions.append(
            {
                "priority": 4,
                "severity": "medium",
                "title": "盯不良高发工序",
                "why": quality.get("summary"),
                "do": "抽查近两周不良报工，定位工序/班组并安排返工或工艺纠正。",
                "agent_next": ["query_metric:analytics.quality_hotspots"],
                "ui_path": "/admin/work-logs",
            }
        )

    actions.sort(key=lambda a: (int(a.get("priority") or 99), 0 if a.get("severity") == "high" else 1))
    # 去重 title
    seen = set()
    uniq = []
    for a in actions:
        t = a.get("title")
        if t in seen:
            continue
        seen.add(t)
        uniq.append(a)
    actions = uniq[:8]

    if not actions:
        actions.append(
            {
                "priority": 9,
                "severity": "low",
                "title": "维持巡检",
                "why": "当前交期、负荷、缺料与经营未见高优先级告警。",
                "do": "按工作台预警巡检即可；可让军师每周跑一次周简报。",
                "agent_next": ["query_metric:analytics.weekly_brief"],
                "ui_path": "/admin",
            }
        )

    high_n = sum(1 for a in actions if a.get("severity") == "high")
    summary = (
        f"今日建议优先处理 {len(actions)} 项（其中高优先级 {high_n} 项）。"
        if high_n
        else f"今日建议关注 {len(actions)} 项例行事项。"
    )

    return {
        "analysis_id": "today_actions",
        "title": "今日行动清单",
        "as_of": _today().isoformat(),
        "summary": summary,
        "insights": [
            _insight(a.get("severity") or "medium", f"「{a.get('title')}」— {a.get('why')}")
            for a in actions[:6]
        ],
        "data": {
            "actions": actions,
            "suggested_memories": suggested_memories,
            "playbook": [
                "1) 先看齐套结论：可排急/险 → 出方案；等料急/险 → 先催料",
                "2) 负荷问题可接着 get_daily_load / generate_schedule_proposals（需人工确认）",
                "3) 产能校准结论用 remember_user_fact 写入长期记忆",
                "4) 缺料/逾期去采购页跟进",
            ],
        },
        "chart": kit.get("chart") or delivery.get("chart"),
    }


def weekly_brief(db: Session, tenant_id: int) -> dict[str, Any]:
    """周经营简报：交期 + 齐套 + 负荷 + 缺料 + 质量，并附行动清单。"""
    delivery = analyze_delivery(db, tenant_id)
    kit = analyze_kit_ready(db, tenant_id)
    capacity = analyze_capacity(db, tenant_id, days=14)
    supply = analyze_supply(db, tenant_id)
    quality = analyze_quality(db, tenant_id, days=14)
    actions = build_today_actions(db, tenant_id)
    sections = [delivery, kit, capacity, supply, quality]
    headlines = []
    for s in sections:
        for ins in s.get("insights") or []:
            if ins.get("severity") in ("high", "medium"):
                headlines.append({"domain": s["analysis_id"], **ins})
    headlines = headlines[:12]
    return {
        "analysis_id": "weekly_brief",
        "title": "车间周经营简报",
        "as_of": _today().isoformat(),
        "summary": headlines[0]["text"] if headlines else "本周关键指标平稳。",
        "insights": headlines,
        "sections": {
            "delivery": delivery,
            "kit_ready": kit,
            "capacity": capacity,
            "supply": supply,
            "quality": quality,
            "today_actions": actions,
        },
        "chart": kit.get("chart") or delivery.get("chart"),
    }


def monthly_brief(db: Session, tenant_id: int, *, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """月经营简报：财务 + 人效 + 交期概览。"""
    y, m = _ym(year, month)
    finance = analyze_finance(db, tenant_id, year=y, month=m)
    labor = analyze_labor(db, tenant_id, year_month=f"{y:04d}-{m:02d}")
    delivery = analyze_delivery(db, tenant_id)
    quality = analyze_quality(db, tenant_id, days=31)
    sections = [finance, labor, delivery, quality]
    headlines = []
    for s in sections:
        for ins in s.get("insights") or []:
            if ins.get("severity") in ("high", "medium"):
                headlines.append({"domain": s["analysis_id"], **ins})
    return {
        "analysis_id": "monthly_brief",
        "title": f"{y}-{m:02d} 月经营简报",
        "as_of": _today().isoformat(),
        "summary": headlines[0]["text"] if headlines else f"{y}-{m:02d} 经营指标平稳。",
        "insights": headlines[:12],
        "sections": {
            "finance": finance,
            "labor": labor,
            "delivery": delivery,
            "quality": quality,
        },
        "chart": finance.get("chart"),
    }


ANALYSIS_RUNNERS: dict[str, Any] = {
    "delivery_risk": analyze_delivery,
    "kit_ready": analyze_kit_ready,
    "order_intake": analyze_order_intake,
    "capacity_load": analyze_capacity,
    "supply_chain": analyze_supply,
    "finance_health": analyze_finance,
    "quality_hotspots": analyze_quality,
    "labor_efficiency": analyze_labor,
    "today_actions": build_today_actions,
    "weekly_brief": weekly_brief,
    "monthly_brief": monthly_brief,
}


def run_analysis(
    db: Session,
    tenant_id: int,
    analysis_id: str,
    *,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    params = params or {}
    fn = ANALYSIS_RUNNERS.get(analysis_id)
    if not fn:
        return {
            "error": "unknown_analysis",
            "message": f"未知分析：{analysis_id}",
            "available": list(ANALYSIS_RUNNERS.keys()),
        }
    # bind common optional params
    if analysis_id == "capacity_load":
        return fn(db, tenant_id, days=int(params.get("days") or 14))
    if analysis_id == "quality_hotspots":
        return fn(db, tenant_id, days=int(params.get("days") or 30))
    if analysis_id == "finance_health":
        return fn(db, tenant_id, year=params.get("year"), month=params.get("month"))
    if analysis_id == "labor_efficiency":
        return fn(db, tenant_id, year_month=params.get("year_month"))
    if analysis_id == "monthly_brief":
        return fn(db, tenant_id, year=params.get("year"), month=params.get("month"))
    if analysis_id == "delivery_risk":
        return fn(db, tenant_id, limit=int(params.get("limit") or 12))
    if analysis_id == "kit_ready":
        return fn(db, tenant_id, limit=int(params.get("limit") or 12))
    if analysis_id == "order_intake":
        return fn(
            db,
            tenant_id,
            lines=params.get("lines") or [],
            include_shared=bool(params.get("include_shared", True)),
            qty=params.get("qty"),
            delivery_date=params.get("delivery_date"),
            is_rush=params.get("is_rush"),
            strategy=params.get("strategy"),
        )
    if analysis_id == "supply_chain":
        return fn(db, tenant_id, limit=int(params.get("limit") or 12))
    return fn(db, tenant_id)
