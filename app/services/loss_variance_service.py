"""A2e：实耗 vs 标准损耗预警（复用 OrderMaterialRequirement 既有字段，规则扫描，不接 Agent）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderMaterialRequirement, OrderStatus, SupplierProduct

DEFAULT_THRESHOLD = Decimal("0.10")
DEFAULT_DAYS = 90
DEFAULT_ORDER_LIMIT = 300


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def scan_loss_variance(
    db: Session,
    tenant_id: int,
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    days: int = DEFAULT_DAYS,
    order_limit: int = DEFAULT_ORDER_LIMIT,
) -> list[dict[str, Any]]:
    """扫描近 N 日未取消生产单，找出「已发 > 标准应耗 ×(1+threshold)」的用料行。

    标准应耗直接复用落库的 `required_qty`（已按 qty_per_pair × 双数 ×(1+loss_rate) + loss_fixed_qty
    维护，见 `material_service.calc_required_qty[_sized]`），不重算 BOM。
    """
    th = threshold if threshold is not None else DEFAULT_THRESHOLD
    since_dt = datetime.combine(date.today() - timedelta(days=max(1, int(days or DEFAULT_DAYS))), datetime.min.time())

    order_q = (
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.status != OrderStatus.cancelled,
            Order.created_at >= since_dt,
        )
        .order_by(Order.created_at.desc())
        .limit(max(1, int(order_limit or DEFAULT_ORDER_LIMIT)))
    )
    orders = list(db.scalars(order_q).all())
    if not orders:
        return []
    order_by_id = {o.id: o for o in orders}

    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.in_(list(order_by_id.keys())),
            )
        ).all()
    )
    if not reqs:
        return []

    sp_ids = {r.supplier_product_id for r in reqs if r.supplier_product_id}
    sp_by_id: dict[int, SupplierProduct] = {}
    if sp_ids:
        for sp in db.scalars(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.id.in_(list(sp_ids)),
            )
        ).all():
            sp_by_id[sp.id] = sp

    out: list[dict[str, Any]] = []
    for row in reqs:
        order = order_by_id.get(row.order_id)
        if not order:
            continue
        required = row.required_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        if issued <= 0:
            continue
        cap = required * (Decimal("1") + th)
        if issued <= cap:
            continue
        over_qty = issued - required
        over_pct = float(over_qty / required * 100) if required > 0 else None
        sp = sp_by_id.get(row.supplier_product_id)
        out.append(
            {
                "requirement_id": row.id,
                "order_id": order.id,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "is_rush": bool(getattr(order, "is_rush", False)),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "supplier_product_id": row.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "qty_per_pair": _f(row.qty_per_pair),
                "loss_rate": _f(row.loss_rate),
                "loss_fixed_qty": _f(row.loss_fixed_qty),
                "required_qty": round(_f(required), 4),
                "issued_qty": round(_f(issued), 4),
                "over_qty": round(_f(over_qty), 4),
                "over_pct": round(over_pct, 1) if over_pct is not None else None,
                "is_customer_supplied": bool(row.is_customer_supplied),
                "consume_process_name": row.consume_process_name,
            }
        )

    out.sort(key=lambda d: d["over_qty"], reverse=True)
    return out


def loss_variance_summary(
    db: Session,
    tenant_id: int,
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    days: int = DEFAULT_DAYS,
    order_limit: int = DEFAULT_ORDER_LIMIT,
    limit: int = 20,
) -> dict[str, Any]:
    """汇总超标行：计数、涉及单数、Top 明细、人话摘要。"""
    th = threshold if threshold is not None else DEFAULT_THRESHOLD
    rows = scan_loss_variance(db, tenant_id, threshold=th, days=days, order_limit=order_limit)
    order_count = len({r["order_id"] for r in rows})
    threshold_pct = round(float(th) * 100, 1)

    if rows:
        top = rows[0]
        pct_txt = f"超{top['over_pct']:.0f}%" if top.get("over_pct") is not None else "超（标准为 0）"
        summary = (
            f"近 {days} 日发现 {len(rows)} 行用料超标准损耗 {threshold_pct:.0f}%（涉及 {order_count} 单），"
            f"最突出：{top.get('order_no') or ''} · {top.get('supplier_product_name') or top.get('supplier_product_code') or '物料'} {pct_txt}"
        )
    else:
        summary = f"近 {days} 日暂无用料超标准损耗 {threshold_pct:.0f}% 的记录"

    return {
        "as_of": date.today().isoformat(),
        "threshold_pct": threshold_pct,
        "days": int(days or DEFAULT_DAYS),
        "flagged_count": len(rows),
        "order_count": order_count,
        "summary": summary,
        "rows": rows[: max(1, int(limit or 20))],
    }
