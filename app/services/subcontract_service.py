"""B1d：承接外包（来料加工/承揽针车）——客供损耗对账。

复用 A2e「实耗 vs 标准损耗」口径，补上家口径：
- 上家来料 = requirement.arrived_qty（B1a 累计到货）
- 我方实耗 = requirement.issued_qty（发车间/领料累计）
- 成品产出 = WorkLog.qualified_qty（交回上家的产量）

规则（v1，只读扫描不建表）：
- 损耗 = 实耗 − 产出（下限 0）
- 在途 = 来料 − 实耗（下限 0）
- 超标准 = 实耗 − 标准应耗（required_qty，已含 BOM 损耗）
- 超阈值（实耗 > 标准应耗 ×(1+threshold)）→ 进今日行动
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    SalesBizMode,
    SalesOrder,
    WorkLog,
    WorkLogStatus,
)

DEFAULT_THRESHOLD = Decimal("0.10")
DEFAULT_ORDER_LIMIT = 300


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def scan_subcontract_loss(
    db: Session,
    tenant_id: int,
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    order_limit: int = DEFAULT_ORDER_LIMIT,
) -> list[dict[str, Any]]:
    """扫描承接外包单的客供料，输出超标准损耗的行（按业务主体聚合）。"""
    th = threshold if threshold is not None else DEFAULT_THRESHOLD

    sos = list(
        db.scalars(
            select(SalesOrder)
            .where(
                SalesOrder.tenant_id == tenant_id,
                SalesOrder.biz_mode == SalesBizMode.subcontract_in,
            )
            .order_by(SalesOrder.id.desc())
            .limit(max(1, int(order_limit or DEFAULT_ORDER_LIMIT)))
        ).all()
    )
    if not sos:
        return []
    so_ids = [so.id for so in sos]
    so_by_id = {so.id: so for so in sos}

    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.sales_order_id.in_(so_ids),
            )
        ).all()
    )
    header_ids = [h.id for h in headers]

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.sales_order_id.in_(so_ids),
            )
        ).all()
    )
    order_ids = [o.id for o in orders]

    req_conds = []
    if header_ids:
        req_conds.append(OrderMaterialRequirement.header_id.in_(header_ids))
    if order_ids:
        req_conds.append(OrderMaterialRequirement.order_id.in_(order_ids))
    reqs = (
        list(
            db.scalars(
                select(OrderMaterialRequirement).where(
                    OrderMaterialRequirement.tenant_id == tenant_id,
                    OrderMaterialRequirement.is_customer_supplied.is_(True),
                    or_(*req_conds),
                )
            ).all()
        )
        if req_conds
        else []
    )

    log_conds = []
    if header_ids:
        log_conds.append(WorkLog.header_id.in_(header_ids))
    if order_ids:
        log_conds.append(WorkLog.order_id.in_(order_ids))
    logs = (
        list(
            db.scalars(
                select(WorkLog).where(
                    WorkLog.tenant_id == tenant_id,
                    WorkLog.status.in_([WorkLogStatus.valid, WorkLogStatus.corrected]),
                    or_(*log_conds),
                )
            ).all()
        )
        if log_conds
        else []
    )

    def _group_key(header_id: int | None, order_id: int | None) -> tuple[str, int | None]:
        return ("h", header_id) if header_id else ("o", order_id)

    groups: dict[tuple[str, int | None], dict[str, Any]] = {}
    for h in headers:
        groups[("h", h.id)] = {"header": h, "order": None, "so": so_by_id.get(h.sales_order_id)}
    for o in orders:
        groups[("o", o.id)] = {"header": None, "order": o, "so": so_by_id.get(o.sales_order_id)}

    for r in reqs:
        g = groups.get(_group_key(getattr(r, "header_id", None), r.order_id))
        if g is None:
            continue
        g["arrived"] = (g.get("arrived", Decimal("0"))) + (r.arrived_qty or Decimal("0"))
        g["issued"] = (g.get("issued", Decimal("0"))) + (r.issued_qty or Decimal("0"))
        g["required"] = (g.get("required", Decimal("0"))) + (r.required_qty or Decimal("0"))

    for lg in logs:
        g = groups.get(_group_key(getattr(lg, "header_id", None), lg.order_id))
        if g is None:
            continue
        g["output"] = (g.get("output", 0)) + int(lg.qualified_qty or 0)

    out: list[dict[str, Any]] = []
    for g in groups.values():
        arrived = g.get("arrived", Decimal("0"))
        issued = g.get("issued", Decimal("0"))
        required = g.get("required", Decimal("0"))
        output = int(g.get("output", 0))
        loss = max(Decimal("0"), issued - Decimal(output))
        in_transit = max(Decimal("0"), arrived - issued)
        over_std = issued - required

        if required > 0 and over_std > required * th:
            flagged = True
            over_pct = float(over_std / required * 100)
        elif required <= 0 and over_std > 0:
            flagged = True
            over_pct = None
        else:
            continue

        so = g.get("so")
        h = g.get("header")
        o = g.get("order")
        order_no = so.order_no if so else (h.header_no if h else (o.order_no if o else None))
        customer_name = so.customer_name if so else (o.customer_name if o else None)
        out.append(
            {
                "order_id": o.id if o else None,
                "header_id": h.id if h else None,
                "sales_order_id": so.id if so else None,
                "order_no": order_no,
                "customer_name": customer_name,
                "arrived_qty": round(_f(arrived), 4),
                "issued_qty": round(_f(issued), 4),
                "required_qty": round(_f(required), 4),
                "output_qty": output,
                "loss_qty": round(_f(loss), 4),
                "in_transit_qty": round(_f(in_transit), 4),
                "over_std_qty": round(_f(over_std), 4),
                "over_pct": round(over_pct, 1) if over_pct is not None else None,
            }
        )

    out.sort(key=lambda d: d["over_std_qty"], reverse=True)
    return out


def subcontract_loss_summary(
    db: Session,
    tenant_id: int,
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    order_limit: int = DEFAULT_ORDER_LIMIT,
    limit: int = 20,
) -> dict[str, Any]:
    """承接外包客供损耗对账汇总：计数、涉及单数、Top 明细、人话摘要。"""
    th = threshold if threshold is not None else DEFAULT_THRESHOLD
    rows = scan_subcontract_loss(db, tenant_id, threshold=th, order_limit=order_limit)
    order_count = len({r.get("order_no") for r in rows if r.get("order_no")})
    threshold_pct = round(float(th) * 100, 1)

    if rows:
        top = rows[0]
        pct_txt = f"超{top['over_pct']:.0f}%" if top.get("over_pct") is not None else "超标（标准为 0）"
        summary = (
            f"承接外包发现 {len(rows)} 单客供料超标准损耗 {threshold_pct:.0f}%（涉及 {order_count} 单），"
            f"最突出：{top.get('order_no') or ''} · 上家 {top.get('customer_name') or ''} {pct_txt}"
        )
    else:
        summary = f"承接外包暂无客供料超标准损耗 {threshold_pct:.0f}% 的记录"

    return {
        "as_of": date.today().isoformat(),
        "threshold_pct": threshold_pct,
        "flagged_count": len(rows),
        "order_count": order_count,
        "summary": summary,
        "rows": rows[: max(1, int(limit or 20))],
    }
