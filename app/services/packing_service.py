"""B2b：生产单配码装箱 + 箱唛数据 + 验箱。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Order,
    OrderItem,
    OwnProduct,
    PackingCarton,
    PackingCartonLine,
    PackingMode,
    PackingPlan,
    PackingPlanStatus,
    Size,
)


class PackingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _item_pool(db: Session, order: Order) -> list[dict[str, Any]]:
    items = list(
        db.scalars(
            select(OrderItem).where(
                OrderItem.tenant_id == order.tenant_id,
                OrderItem.order_id == order.id,
            )
        ).all()
    )
    pool: list[dict[str, Any]] = []
    for it in items:
        qty = int(it.qty or 0)
        if qty <= 0 or not it.size_id:
            continue
        pool.append(
            {
                "color_id": it.color_id,
                "size_id": int(it.size_id),
                "qty": qty,
            }
        )
    if not pool:
        raise PackingError("no_items", "生产单无色码数量，无法装箱")
    return pool


def _pack_single_size(pool: list[dict[str, Any]], capacity: int) -> list[list[dict[str, Any]]]:
    cartons: list[list[dict[str, Any]]] = []
    for row in pool:
        left = int(row["qty"])
        while left > 0:
            take = min(capacity, left)
            cartons.append(
                [{"color_id": row["color_id"], "size_id": row["size_id"], "qty": take}]
            )
            left -= take
    return cartons


def _pack_mixed(pool: list[dict[str, Any]], capacity: int) -> list[list[dict[str, Any]]]:
    remaining = [{"color_id": r["color_id"], "size_id": r["size_id"], "qty": int(r["qty"])} for r in pool]
    cartons: list[list[dict[str, Any]]] = []
    while any(r["qty"] > 0 for r in remaining):
        space = capacity
        box: list[dict[str, Any]] = []
        for r in remaining:
            if space <= 0:
                break
            if r["qty"] <= 0:
                continue
            take = min(space, r["qty"])
            box.append({"color_id": r["color_id"], "size_id": r["size_id"], "qty": take})
            r["qty"] -= take
            space -= take
        if not box:
            break
        cartons.append(box)
    return cartons


def _carton_out(db: Session, c: PackingCarton, *, plan: PackingPlan | None = None) -> dict[str, Any]:
    plan = plan or db.get(PackingPlan, c.plan_id)
    order = db.get(Order, plan.order_id) if plan else None
    product = db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    lines_out = []
    for ln in sorted(c.lines or [], key=lambda x: (x.size_id or 0, x.id)):
        color = db.get(Color, ln.color_id) if ln.color_id else None
        size = db.get(Size, ln.size_id) if ln.size_id else None
        lines_out.append(
            {
                "id": ln.id,
                "color_id": ln.color_id,
                "color_name": color.name if color else None,
                "size_id": ln.size_id,
                "size_value": size.size_value if size else None,
                "qty": ln.qty,
            }
        )
    return {
        "id": c.id,
        "plan_id": c.plan_id,
        "seq": c.seq,
        "code": c.code,
        "total_qty": c.total_qty,
        "verified_at": c.verified_at.isoformat() if c.verified_at else None,
        "lines": lines_out,
        "order_id": order.id if order else None,
        "order_no": order.order_no if order else None,
        "customer_name": order.customer_name if order else None,
        "product_code": product.product_code if product else None,
        "carton_count": len(plan.cartons) if plan and plan.cartons is not None else None,
    }


def _plan_out(db: Session, plan: PackingPlan) -> dict[str, Any]:
    order = db.get(Order, plan.order_id)
    product = db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    cartons = [
        _carton_out(db, c, plan=plan)
        for c in sorted(plan.cartons or [], key=lambda x: x.seq)
    ]
    return {
        "id": plan.id,
        "order_id": plan.order_id,
        "order_no": order.order_no if order else None,
        "customer_name": order.customer_name if order else None,
        "product_code": product.product_code if product else None,
        "mode": _enum_val(plan.mode),
        "pairs_per_carton": plan.pairs_per_carton,
        "status": _enum_val(plan.status),
        "note": plan.note,
        "carton_count": len(cartons),
        "total_qty": sum(int(c["total_qty"] or 0) for c in cartons),
        "cartons": cartons,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def create_packing_plan(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    mode: str,
    pairs_per_carton: int,
    note: str | None = None,
    created_by: int | None = None,
    replace_draft: bool = True,
) -> dict[str, Any]:
    if mode not in PackingMode.__members__:
        raise PackingError("invalid_mode", "装箱规则无效（单码/混码）")
    if pairs_per_carton <= 0:
        raise PackingError("invalid_capacity", "每箱双数须大于 0")

    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise PackingError("order_not_found", "生产单不存在")

    pool = _item_pool(db, order)
    expected_total = sum(int(r["qty"]) for r in pool)
    packed = (
        _pack_single_size(pool, pairs_per_carton)
        if mode == PackingMode.single_size.value
        else _pack_mixed(pool, pairs_per_carton)
    )
    packed_total = sum(sum(int(x["qty"]) for x in box) for box in packed)
    if packed_total != expected_total:
        raise PackingError("pack_mismatch", "装箱合计与生产单色码不一致")

    if replace_draft:
        olds = list(
            db.scalars(
                select(PackingPlan).where(
                    PackingPlan.tenant_id == tenant_id,
                    PackingPlan.order_id == order_id,
                    PackingPlan.status == PackingPlanStatus.draft,
                )
            ).all()
        )
        for old in olds:
            db.delete(old)
        db.flush()

    plan = PackingPlan(
        tenant_id=tenant_id,
        order_id=order_id,
        mode=PackingMode(mode),
        pairs_per_carton=pairs_per_carton,
        status=PackingPlanStatus.draft,
        note=note,
        created_by=created_by,
    )
    db.add(plan)
    db.flush()

    for i, box in enumerate(packed, start=1):
        code = f"CTN-{order.order_no}-{i:04d}"
        carton = PackingCarton(
            tenant_id=tenant_id,
            plan_id=plan.id,
            seq=i,
            code=code,
            total_qty=sum(int(x["qty"]) for x in box),
        )
        db.add(carton)
        db.flush()
        for ln in box:
            db.add(
                PackingCartonLine(
                    tenant_id=tenant_id,
                    carton_id=carton.id,
                    color_id=ln["color_id"],
                    size_id=ln["size_id"],
                    qty=int(ln["qty"]),
                )
            )

    db.commit()
    plan = db.scalar(
        select(PackingPlan)
        .where(PackingPlan.id == plan.id)
        .options(
            selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines),
        )
    )
    return _plan_out(db, plan)


def list_packing_plans(db: Session, tenant_id: int, order_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PackingPlan)
            .where(PackingPlan.tenant_id == tenant_id, PackingPlan.order_id == order_id)
            .options(selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines))
            .order_by(PackingPlan.id.desc())
        ).all()
    )
    return [_plan_out(db, p) for p in rows]


def get_packing_plan(db: Session, tenant_id: int, plan_id: int) -> dict[str, Any]:
    plan = db.scalar(
        select(PackingPlan)
        .where(PackingPlan.tenant_id == tenant_id, PackingPlan.id == plan_id)
        .options(selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines))
    )
    if not plan:
        raise PackingError("not_found", "装箱计划不存在")
    return _plan_out(db, plan)


def get_packing_carton(db: Session, tenant_id: int, carton_id: int) -> dict[str, Any]:
    carton = db.scalar(
        select(PackingCarton)
        .where(PackingCarton.tenant_id == tenant_id, PackingCarton.id == carton_id)
        .options(selectinload(PackingCarton.lines), selectinload(PackingCarton.plan))
    )
    if not carton:
        raise PackingError("not_found", "箱不存在")
    plan = carton.plan
    if plan:
        # ensure carton_count
        plan = db.scalar(
            select(PackingPlan)
            .where(PackingPlan.id == plan.id)
            .options(selectinload(PackingPlan.cartons))
        )
    return _carton_out(db, carton, plan=plan)


def get_packing_carton_by_code(db: Session, code: str) -> PackingCarton | None:
    code = (code or "").strip()
    if not code:
        return None
    return db.scalar(
        select(PackingCarton)
        .where(PackingCarton.code == code)
        .options(selectinload(PackingCarton.lines), selectinload(PackingCarton.plan))
    )


def verify_packing_carton(
    db: Session,
    tenant_id: int,
    carton_id: int,
    *,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    carton = db.scalar(
        select(PackingCarton)
        .where(PackingCarton.tenant_id == tenant_id, PackingCarton.id == carton_id)
        .options(selectinload(PackingCarton.lines))
    )
    if not carton:
        raise PackingError("not_found", "箱不存在")

    expected: dict[tuple[int | None, int], int] = {}
    for ln in carton.lines or []:
        key = (ln.color_id, int(ln.size_id))
        expected[key] = expected.get(key, 0) + int(ln.qty)

    scanned: dict[tuple[int | None, int], int] = {}
    for raw in lines or []:
        try:
            size_id = int(raw.get("size_id"))
            qty = int(raw.get("qty") or 0)
        except (TypeError, ValueError):
            raise PackingError("invalid_line", "验箱明细无效") from None
        if qty < 0:
            raise PackingError("invalid_qty", "验箱数量不能为负")
        if qty == 0:
            continue
        color_id = raw.get("color_id")
        color_id = int(color_id) if color_id is not None else None
        key = (color_id, size_id)
        scanned[key] = scanned.get(key, 0) + qty

    scanned_total = sum(scanned.values())
    expected_total = sum(expected.values())
    if scanned_total > expected_total:
        raise PackingError("over_pack", f"超箱：实扫 {scanned_total} 双，本箱计划 {expected_total} 双")

    extras = []
    for key, qty in scanned.items():
        exp = expected.get(key, 0)
        if qty > exp:
            size = db.get(Size, key[1])
            color = db.get(Color, key[0]) if key[0] else None
            label = f"{color.name if color else '—'} {size.size_value if size else key[1]}"
            extras.append(f"{label} 多 {(qty - exp)}")
    if extras:
        raise PackingError("wrong_size", "错码/超量：" + "；".join(extras))

    missing = []
    for key, qty in expected.items():
        got = scanned.get(key, 0)
        if got != qty:
            size = db.get(Size, key[1])
            color = db.get(Color, key[0]) if key[0] else None
            label = f"{color.name if color else '—'} {size.size_value if size else key[1]}"
            missing.append(f"{label} 计划{qty}实扫{got}")
    if missing:
        raise PackingError("mismatch", "与计划不符：" + "；".join(missing))

    carton.verified_at = datetime.utcnow()
    db.commit()
    db.refresh(carton)
    return get_packing_carton(db, tenant_id, carton.id)
