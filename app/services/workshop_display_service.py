"""车间投屏专用聚合：昨日产量、焦点订单、工序水位、待料。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    ProcessDefinition,
    SalesOrder,
    SpecExecutionStatus,
    Tenant,
    WorkLog,
    WorkLogStatus,
)
from app.services import material_service
from app.services.progress_service import _bottleneck_process, _process_percent


def _day_output(db: Session, tenant_id: int, day: date) -> dict:
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
            func.date(WorkLog.created_at) == day,
        )
        .group_by(OrderProcess.process_name)
    ).all()
    by_process = [
        {"process_name": name, "qualified_qty": int(q), "defect_qty": int(d)} for name, q, d in rows
    ]
    total_q = sum(i["qualified_qty"] for i in by_process)
    total_d = sum(i["defect_qty"] for i in by_process)
    return {
        "date": day.isoformat(),
        "total_qualified": total_q,
        "total_defect": total_d,
        "by_process": by_process,
    }


def _delivery_label(delivery: date | None, today: date) -> str:
    if not delivery:
        return "—"
    delta = (delivery - today).days
    if delta < 0:
        return f"逾期 {abs(delta)} 天"
    if delta == 0:
        return "今天交"
    if delta == 1:
        return "明天交"
    if delta <= 7:
        return f"D-{delta}"
    return delivery.isoformat()


def _signal(
    *,
    is_rush: bool,
    at_risk: bool,
    material_blocked: bool,
) -> str:
    if is_rush:
        return "rush"
    if at_risk:
        return "delivery_risk"
    if material_blocked:
        return "material_block"
    return "normal"


def workshop_display(db: Session, tenant_id: int) -> dict:
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    soon = today + timedelta(days=2)

    tenant = db.get(Tenant, tenant_id)
    factory_name = tenant.name if tenant else "车间看板"

    yesterday_out = _day_output(db, tenant_id, yesterday)
    today_out = _day_output(db, tenant_id, today)
    y_q = yesterday_out["total_qualified"]
    y_d = yesterday_out["total_defect"]
    defect_rate = round(100 * y_d / (y_q + y_d), 1) if (y_q + y_d) > 0 else 0.0

    open_statuses = (OrderStatus.confirmed, OrderStatus.in_progress)
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.tenant_id == tenant_id, Order.status.in_(open_statuses))
            .options(selectinload(Order.processes))
            .order_by(Order.is_rush.desc(), Order.id.desc())
        ).all()
    )

    product_ids = {o.own_product_id for o in orders if o.own_product_id}
    products = {}
    if product_ids:
        for p in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(product_ids))).all():
            products[p.id] = p

    header_by_shop: dict[int, ExecutionHeader] = {}
    shop_ids = [o.id for o in orders]
    if shop_ids:
        for h in db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.shop_order_id.in_(shop_ids),
            )
        ).all():
            if h.shop_order_id:
                header_by_shop[int(h.shop_order_id)] = h

    remain_by_process: dict[str, int] = {}
    focus_rows: list[dict] = []
    material_blocks: list[dict] = []
    rush_count = 0
    material_blocked_count = 0

    for order in orders:
        header = header_by_shop.get(order.id)
        display_no = header.header_no if header else order.order_no
        processes = sorted(order.processes, key=lambda x: x.id)
        pcts = [_process_percent(p) for p in processes]
        overall = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
        bottleneck = _bottleneck_process(processes)
        product = products.get(order.own_product_id)
        delivery = order.delivery_date
        is_rush = bool(getattr(order, "is_rush", False))
        if is_rush:
            rush_count += 1

        at_risk = bool(delivery and delivery <= soon and overall < 90)

        kit = material_service.order_kit_summary(db, tenant_id, order.id)
        material_blocked = (not kit.get("empty_bom")) and (not kit.get("kit_ok"))
        if material_blocked:
            material_blocked_count += 1
            shortage_lines = int(kit.get("shortage_lines") or 0)
            material_blocks.append(
                {
                    "order_id": order.id,
                    "order_no": display_no,
                    "shop_order_no": order.order_no,
                    "header_id": header.id if header else None,
                    "header_no": header.header_no if header else None,
                    "product_code": product.product_code if product else None,
                    "shortage_lines": shortage_lines,
                    "label": f"齐套不足（缺 {shortage_lines} 项）" if shortage_lines else "齐套不足",
                    "is_rush": is_rush,
                }
            )

        for p in processes:
            status = p.status.value if hasattr(p.status, "value") else str(p.status)
            if status == OrderProcessStatus.completed.value:
                continue
            remain = max(0, int(p.plan_qty or 0) - int(p.completed_qty or 0))
            if remain <= 0:
                continue
            remain_by_process[p.process_name] = remain_by_process.get(p.process_name, 0) + remain

        signal = _signal(is_rush=is_rush, at_risk=at_risk, material_blocked=material_blocked)
        focus_rows.append(
            {
                "id": order.id,
                "order_no": display_no,
                "shop_order_no": order.order_no,
                "header_id": header.id if header else None,
                "header_no": header.header_no if header else None,
                "customer_name": order.customer_name,
                "product_code": product.product_code if product else None,
                "delivery_date": delivery.isoformat() if delivery else None,
                "delivery_label": _delivery_label(delivery, today),
                "overall_percent": overall,
                "bottleneck": bottleneck,
                "at_risk": at_risk,
                "is_rush": is_rush,
                "material_blocked": material_blocked,
                "signal": signal,
                "sort_delivery": delivery.isoformat() if delivery else "9999-99-99",
            }
        )

    # K4-C：无桥接壳的执行单头也进焦点（与订单并列）
    open_header_statuses = (
        SpecExecutionStatus.confirmed,
        SpecExecutionStatus.cut,
        SpecExecutionStatus.in_progress,
    )
    header_only = list(
        db.scalars(
            select(ExecutionHeader)
            .where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.shop_order_id.is_(None),
                ExecutionHeader.status.in_(open_header_statuses),
            )
            .options(selectinload(ExecutionHeader.size_lines))
            .order_by(ExecutionHeader.id.desc())
        ).all()
    )
    header_product_ids = {h.own_product_id for h in header_only if h.own_product_id} - set(products)
    if header_product_ids:
        for p in db.scalars(select(OwnProduct).where(OwnProduct.id.in_(header_product_ids))).all():
            products[p.id] = p

    for header in header_only:
        processes = material_service.list_header_processes(db, tenant_id, header.id)
        processes = sorted(processes, key=lambda x: x.id)
        pcts = [_process_percent(p) for p in processes]
        overall = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
        bottleneck = _bottleneck_process(processes)
        product = products.get(header.own_product_id)
        delivery = header.delivery_date
        size_lines = list(header.size_lines or [])
        is_rush = any(bool(getattr(sl, "is_rush", False)) for sl in size_lines)
        if is_rush:
            rush_count += 1
        at_risk = bool(delivery and delivery <= soon and overall < 90)

        try:
            kit = material_service.get_header_kit(db, tenant_id, header.id)
        except material_service.MaterialError:
            kit = {"empty_bom": True, "kit_ok": True, "shortage_lines": 0}
        material_blocked = (not kit.get("empty_bom")) and (not kit.get("kit_ok"))
        if material_blocked:
            material_blocked_count += 1
            shortage_lines = int(kit.get("shortage_lines") or 0)
            material_blocks.append(
                {
                    "order_id": None,
                    "order_no": header.header_no,
                    "shop_order_no": None,
                    "header_id": header.id,
                    "header_no": header.header_no,
                    "product_code": product.product_code if product else None,
                    "shortage_lines": shortage_lines,
                    "label": f"齐套不足（缺 {shortage_lines} 项）" if shortage_lines else "齐套不足",
                    "is_rush": is_rush,
                }
            )

        for p in processes:
            status = p.status.value if hasattr(p.status, "value") else str(p.status)
            if status == OrderProcessStatus.completed.value:
                continue
            remain = max(0, int(p.plan_qty or 0) - int(p.completed_qty or 0))
            if remain <= 0:
                continue
            remain_by_process[p.process_name] = remain_by_process.get(p.process_name, 0) + remain

        so = db.get(SalesOrder, header.sales_order_id) if header.sales_order_id else None
        signal = _signal(is_rush=is_rush, at_risk=at_risk, material_blocked=material_blocked)
        focus_rows.append(
            {
                "id": header.id,
                "order_no": header.header_no,
                "shop_order_no": None,
                "header_id": header.id,
                "header_no": header.header_no,
                "customer_name": so.customer_name if so else None,
                "product_code": product.product_code if product else None,
                "delivery_date": delivery.isoformat() if delivery else None,
                "delivery_label": _delivery_label(delivery, today),
                "overall_percent": overall,
                "bottleneck": bottleneck,
                "at_risk": at_risk,
                "is_rush": is_rush,
                "material_blocked": material_blocked,
                "signal": signal,
                "sort_delivery": delivery.isoformat() if delivery else "9999-99-99",
            }
        )

    focus_rows.sort(
        key=lambda r: (
            0 if r["is_rush"] else 1,
            0 if r["at_risk"] else 1,
            0 if r["material_blocked"] else 1,
            r["sort_delivery"],
            r["overall_percent"],
        )
    )
    for r in focus_rows:
        r.pop("sort_delivery", None)

    material_blocks.sort(key=lambda x: (0 if x["is_rush"] else 1, x["order_no"]))
    material_blocks = material_blocks[:5]

    defs = list(
        db.scalars(
            select(ProcessDefinition)
            .where(ProcessDefinition.tenant_id == tenant_id, ProcessDefinition.is_active.is_(True))
            .order_by(ProcessDefinition.sort_order.asc(), ProcessDefinition.id.asc())
        ).all()
    )
    y_by_name = {i["process_name"]: i["qualified_qty"] for i in yesterday_out["by_process"]}

    ordered_names: list[str] = []
    seen: set[str] = set()
    for d in defs:
        if d.name not in seen:
            ordered_names.append(d.name)
            seen.add(d.name)
    for name in sorted(remain_by_process.keys()):
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)
    for name in sorted(y_by_name.keys()):
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)

    process_levels = []
    max_remain = max(remain_by_process.values(), default=0)
    for name in ordered_names:
        remain = int(remain_by_process.get(name, 0))
        process_levels.append(
            {
                "process_name": name,
                "remain_qty": remain,
                "yesterday_qualified": int(y_by_name.get(name, 0)),
                "is_bottleneck": remain > 0 and remain == max_remain,
            }
        )
    # 无在制剩余时取消堵点标记
    if max_remain <= 0:
        for row in process_levels:
            row["is_bottleneck"] = False

    return {
        "factory_name": factory_name,
        "as_of": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": {
            "yesterday_qualified": y_q,
            "yesterday_defect": y_d,
            "yesterday_defect_rate": defect_rate,
            "rush_orders": rush_count,
            "material_blocked_orders": material_blocked_count,
            "today_reported": {
                "qualified": today_out["total_qualified"],
                "defect": today_out["total_defect"],
                "date": today_out["date"],
            },
        },
        "focus_orders": focus_rows,
        "process_levels": process_levels,
        "material_blocks": material_blocks,
    }
