"""P1-6：合批推荐引擎 — 只荐组，不落库；采纳走 create_merge_batch。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Color, Order, OrderStatus, OwnProduct
from app.services import material_service, schedule_settings
from app.services.merge_batch_service import _active_member_order_ids, _order_color_ids


def _open_statuses() -> tuple[OrderStatus, ...]:
    return (OrderStatus.confirmed, OrderStatus.in_progress)


def _delivery(o: Order) -> date | None:
    d = o.delivery_date
    if d is None:
        return None
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def _color_key(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    require_same_color: bool,
) -> tuple[str, int | None]:
    """Return grouping key + locked color_id (if any). Multi-color orders skipped when same-color required."""
    ids = _order_color_ids(db, order_id, tenant_id)
    concrete = {c for c in ids if c is not None}
    if require_same_color:
        if len(concrete) != 1:
            return ("__skip__", None)
        cid = next(iter(concrete))
        return (f"c:{cid}", cid)
    if len(concrete) == 1:
        cid = next(iter(concrete))
        return (f"c:{cid}", cid)
    if not concrete:
        return ("c:none", None)
    return ("c:multi", None)


def _cluster_by_delivery_window(
    rows: list[dict[str, Any]],
    window_days: int,
) -> list[list[dict[str, Any]]]:
    """Greedy clusters: sorted by delivery, each cluster span ≤ window_days."""
    dated = [r for r in rows if r.get("delivery_date")]
    undated = [r for r in rows if not r.get("delivery_date")]
    dated.sort(key=lambda r: (r["delivery_date"], r["order_id"]))
    clusters: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_start: date | None = None
    for r in dated:
        d: date = r["delivery_date"]
        if not cur:
            cur = [r]
            cur_start = d
            continue
        assert cur_start is not None
        if (d - cur_start).days <= window_days:
            cur.append(r)
        else:
            clusters.append(cur)
            cur = [r]
            cur_start = d
    if cur:
        clusters.append(cur)
    # undated alone never form a window cluster with dated; group all undated together if ≥2
    if len(undated) >= 2:
        clusters.append(undated)
    elif len(undated) == 1 and clusters:
        # attach single undated to last cluster only if window is unrestricted (0)
        if window_days <= 0:
            clusters[-1].extend(undated)
    return clusters


def suggest_merge_batches(
    db: Session,
    tenant_id: int,
    *,
    delivery_window_days: int | None = None,
    require_same_color: bool | None = None,
    min_qty: int | None = None,
    require_first_kit: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """
    推荐可合批组：同款 +（可选）同色 + 交期窗 + 首道齐套 + 最小合计双数。
    不写库；采纳请 POST /merge-batches。
    """
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    window = int(cfg["merge_delivery_window_days"] if delivery_window_days is None else delivery_window_days)
    window = max(0, window)
    same_color = (
        bool(cfg["merge_require_same_color"]) if require_same_color is None else bool(require_same_color)
    )
    min_q = int(cfg["merge_min_qty"] if min_qty is None else min_qty)
    min_q = max(0, min_q)

    orders = list(
        db.scalars(
            select(Order)
            .where(Order.tenant_id == tenant_id, Order.status.in_(_open_statuses()))
            .order_by(Order.delivery_date, Order.id)
        ).all()
    )
    if not orders:
        return {
            "params": {
                "merge_delivery_window_days": window,
                "merge_require_same_color": same_color,
                "merge_min_qty": min_q,
                "require_first_kit": require_first_kit,
            },
            "items": [],
            "skipped": {"already_in_batch": 0, "not_kit": 0, "color": 0, "no_product": 0},
        }

    order_ids = [o.id for o in orders]
    busy = _active_member_order_ids(db, tenant_id, order_ids)
    free = [o for o in orders if o.id not in busy]
    skipped_busy = len(orders) - len(free)

    for o in free:
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id)

    product_ids = {o.own_product_id for o in free if o.own_product_id}
    product_map = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.id.in_(product_ids))
        ).all()
    } if product_ids else {}

    color_ids: set[int] = set()
    candidates: list[dict[str, Any]] = []
    skipped_kit = 0
    skipped_color = 0
    skipped_product = 0

    for o in free:
        if not o.own_product_id:
            skipped_product += 1
            continue
        summary = ctx.summary_for_order(o.id)
        first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
        if require_first_kit and not first_ok:
            skipped_kit += 1
            continue
        ck, locked = _color_key(db, tenant_id, o.id, require_same_color=same_color)
        if ck == "__skip__":
            skipped_color += 1
            continue
        if locked is not None:
            color_ids.add(locked)
        product = product_map.get(o.own_product_id)
        candidates.append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "customer_name": o.customer_name,
                "own_product_id": o.own_product_id,
                "product_code": product.product_code if product else None,
                "total_qty": int(o.total_qty or 0),
                "delivery_date": _delivery(o),
                "color_id": locked,
                "color_key": ck,
                "first_kit_ok": first_ok,
                "kit_ok": bool(summary.get("kit_ok")),
            }
        )

    color_map = {
        c.id: c.name
        for c in db.scalars(select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids))).all()
    } if color_ids else {}

    # group by product + color_key
    buckets: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in candidates:
        key = (int(row["own_product_id"]), str(row["color_key"]))
        buckets.setdefault(key, []).append(row)

    items: list[dict[str, Any]] = []
    for (product_id, _ck), rows in buckets.items():
        for cluster in _cluster_by_delivery_window(rows, window):
            if len(cluster) < 2:
                continue
            total_qty = sum(int(r["total_qty"]) for r in cluster)
            if total_qty < min_q:
                continue
            deliveries = [r["delivery_date"] for r in cluster if r["delivery_date"]]
            d_min = min(deliveries) if deliveries else None
            d_max = max(deliveries) if deliveries else None
            color_id = cluster[0].get("color_id")
            # if multi-color allowed and cluster mixed, color_id may vary — clear if not unique
            cids = {r.get("color_id") for r in cluster}
            if len(cids) != 1:
                color_id = None
            product = product_map.get(product_id)
            items.append(
                {
                    "own_product_id": product_id,
                    "product_code": product.product_code if product else None,
                    "color_id": color_id,
                    "color_name": color_map.get(color_id) if color_id else None,
                    "order_count": len(cluster),
                    "total_qty": total_qty,
                    "delivery_from": d_min.isoformat() if d_min else None,
                    "delivery_to": d_max.isoformat() if d_max else None,
                    "delivery_span_days": (d_max - d_min).days if d_min and d_max else None,
                    "require_same_color": same_color,
                    "orders": [
                        {
                            "order_id": r["order_id"],
                            "order_no": r["order_no"],
                            "customer_name": r["customer_name"],
                            "total_qty": r["total_qty"],
                            "delivery_date": r["delivery_date"].isoformat() if r["delivery_date"] else None,
                            "first_kit_ok": r["first_kit_ok"],
                            "kit_ok": r["kit_ok"],
                        }
                        for r in cluster
                    ],
                    "order_ids": [r["order_id"] for r in cluster],
                }
            )

    items.sort(key=lambda x: (-x["total_qty"], x.get("delivery_from") or "9999", -x["order_count"]))
    items = items[: max(1, min(200, limit))]

    return {
        "params": {
            "merge_delivery_window_days": window,
            "merge_require_same_color": same_color,
            "merge_min_qty": min_q,
            "require_first_kit": require_first_kit,
        },
        "items": items,
        "skipped": {
            "already_in_batch": skipped_busy,
            "not_kit": skipped_kit,
            "color": skipped_color,
            "no_product": skipped_product,
        },
    }
