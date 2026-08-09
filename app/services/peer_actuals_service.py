"""A1c：批价旁同类（同款）出货实绩 — 实耗 / 实毛利中位与四分位。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OwnProduct, Order, Shipment, ShipmentStatus


class PeerActualsError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """p ∈ [0, 100]；线性插值四分位。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 6)
    rank = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    val = sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
    return round(val, 6)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return _percentile(s, 50)


def _dist(vals: list[float]) -> dict[str, float | None]:
    s = sorted(vals)
    avg = round(sum(s) / len(s), 6) if s else None
    return {
        "median": _median(s) if s else None,
        "p25": _percentile(s, 25),
        "p75": _percentile(s, 75),
        "avg": avg,
    }


def _collect_shipped_samples(
    db: Session,
    tenant_id: int,
    own_product_id: int,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    from app.services import finance_service

    shipments = list(
        db.scalars(
            select(Shipment)
            .where(
                Shipment.tenant_id == tenant_id,
                Shipment.status == ShipmentStatus.shipped,
            )
            .order_by(Shipment.ship_date.desc(), Shipment.id.desc())
            .limit(300)
        ).all()
    )
    seen: set[int] = set()
    samples: list[dict[str, Any]] = []
    for sh in shipments:
        oid = int(sh.order_id)
        if oid in seen:
            continue
        order = db.get(Order, oid)
        if not order or order.tenant_id != tenant_id:
            continue
        if int(order.own_product_id or 0) != int(own_product_id):
            continue
        seen.add(oid)
        try:
            p = finance_service.order_profit(db, tenant_id, oid)
        except Exception:
            continue
        shipped = float(p.get("shipped_qty") or 0)
        if shipped <= 0:
            continue
        total_cost = (
            float(p.get("material_cost") or 0)
            + float(p.get("labor_cost") or 0)
            + float(p.get("other_cost") or 0)
        )
        unit_cost = total_cost / shipped
        gm = p.get("gross_margin")
        gm_f = float(gm) if gm is not None else None
        samples.append(
            {
                "order_id": oid,
                "order_no": p.get("order_no"),
                "shipped_qty": int(shipped),
                "unit_cost": round(unit_cost, 6),
                "gross_margin": round(gm_f, 6) if gm_f is not None else None,
                "ship_date": sh.ship_date.isoformat() if sh.ship_date else None,
            }
        )
        if len(samples) >= limit:
            break
    return samples


def peer_actuals_for_product(db: Session, tenant_id: int, own_product_id: int) -> dict[str, Any]:
    product = db.get(OwnProduct, own_product_id)
    if not product or product.tenant_id != tenant_id:
        raise PeerActualsError("product_not_found", "产品不存在")

    card = (
        float(product.material_cost or 0)
        + float(product.labor_cost or 0)
        + float(product.other_cost or 0)
    )
    samples = _collect_shipped_samples(db, tenant_id, own_product_id)
    unit_costs = [float(s["unit_cost"]) for s in samples]
    margins = [float(s["gross_margin"]) for s in samples if s.get("gross_margin") is not None]

    cost_dist = _dist(unit_costs)
    margin_dist = _dist(margins)

    delta = None
    delta_pct = None
    med = cost_dist.get("median")
    if med is not None and card > 0:
        delta = round(float(med) - card, 4)
        delta_pct = round(delta / card * 100, 1)

    available = len(samples) > 0
    return {
        "own_product_id": product.id,
        "product_code": product.product_code,
        "peer_scope": "same_sku",
        "peer_scope_label": "同款已出货生产单",
        "available": available,
        "empty_reason": None if available else "这款还没有出货记录，暂时只有档案成本可参考",
        "card_unit_cost": round(card, 4),
        "card_material": round(float(product.material_cost or 0), 4),
        "card_labor": round(float(product.labor_cost or 0), 4),
        "card_other": round(float(product.other_cost or 0), 4),
        "quote_price": float(product.quote_price) if product.quote_price is not None else None,
        "sample_size": len(samples),
        "sample_orders": samples,
        "actual_unit_cost": cost_dist,
        "delta_vs_card": {
            "median": delta,
            "median_pct": delta_pct,
        },
        "actual_gross_margin": margin_dist,
        "definitions": {
            "peer": "v1：同一货号的已出货生产单（最多 12 单，按出货日近→远）",
            "unit_cost": "实际花费/双=(材料+计件人工+其它)/出货双数，同利润估算口径",
            "gross_margin": "出货收入减上述成本后再除以收入（估算，非决算）",
            "median": "多半水平：排序后正中间；偶数取中间两值平均。多数区间为去掉高低两端后的常见范围",
        },
        "advisory_only": True,
        "note": "数字来自已出货生产单的估算成本，不是财务决算；只帮批价对照，不改报价。",
    }
