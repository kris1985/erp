"""B2b：生产单配码装箱 + 箱唛数据 + 验箱。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    ExecutionHeader,
    Order,
    OrderItem,
    OwnProduct,
    PackingCarton,
    PackingCartonLine,
    PackingMode,
    PackingPlan,
    PackingPlanStatus,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentStatus,
    Size,
    SpecExecutionOrder,
    TraceUnit,
    TraceUnitType,
)


class PackingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _header_item_pool(db: Session, header: ExecutionHeader) -> list[dict[str, Any]]:
    lines = list(
        db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.header_id == header.id,
                SpecExecutionOrder.tenant_id == header.tenant_id,
            )
        ).all()
    )
    pool: list[dict[str, Any]] = []
    for sl in lines:
        qty = int(sl.total_qty or 0)
        if qty <= 0 or not sl.size_id:
            continue
        pool.append(
            {
                "color_id": sl.color_id if sl.color_id is not None else header.color_id,
                "size_id": int(sl.size_id),
                "qty": qty,
            }
        )
    if not pool:
        raise PackingError("no_items", "执行单无色码数量，无法装箱")
    return pool


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
    order = db.get(Order, plan.order_id) if plan and plan.order_id else None
    header = (
        db.get(ExecutionHeader, plan.header_id)
        if plan and getattr(plan, "header_id", None)
        else None
    )
    product = db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    customer_name = order.customer_name if order else None
    order_no = order.order_no if order else None
    if header:
        if product is None:
            product = db.get(OwnProduct, header.own_product_id)
        so = db.get(SalesOrder, header.sales_order_id) if header.sales_order_id else None
        if so:
            customer_name = customer_name or so.customer_name
        order_no = order_no or header.header_no
    shipment = db.get(Shipment, c.shipment_id) if getattr(c, "shipment_id", None) else None
    if shipment:
        customer_name = customer_name or shipment.customer_name
        if product is None and shipment.sales_order_id:
            sline = db.scalar(
                select(SalesOrderLine)
                .where(SalesOrderLine.sales_order_id == shipment.sales_order_id)
                .order_by(SalesOrderLine.sort_order, SalesOrderLine.id)
                .limit(1)
            )
            if sline:
                product = db.get(OwnProduct, sline.own_product_id)
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
        "shipment_id": getattr(c, "shipment_id", None),
        "verified_at": c.verified_at.isoformat() if c.verified_at else None,
        "lines": lines_out,
        "order_id": order.id if order else None,
        "order_no": order_no,
        "sales_order_no": shipment.sales_order_no if shipment else None,
        "customer_name": customer_name,
        "product_code": product.product_code if product else None,
        "carton_count": len(plan.cartons) if plan and plan.cartons is not None else None,
    }


def _plan_out(db: Session, plan: PackingPlan) -> dict[str, Any]:
    order = db.get(Order, plan.order_id) if plan.order_id else None
    header = db.get(ExecutionHeader, plan.header_id) if getattr(plan, "header_id", None) else None
    product = None
    customer_name = None
    order_no = None
    if order:
        product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
        customer_name = order.customer_name
        order_no = order.order_no
    if header:
        if product is None:
            product = db.get(OwnProduct, header.own_product_id)
        so = db.get(SalesOrder, header.sales_order_id) if header.sales_order_id else None
        if so:
            customer_name = customer_name or so.customer_name
        order_no = order_no or header.header_no
    cartons = [
        _carton_out(db, c, plan=plan)
        for c in sorted(plan.cartons or [], key=lambda x: x.seq)
    ]
    return {
        "id": plan.id,
        "order_id": plan.order_id,
        "basket_id": getattr(plan, "basket_id", None),
        "execution_id": getattr(plan, "execution_id", None),
        "header_id": getattr(plan, "header_id", None),
        "order_no": order_no,
        "header_no": header.header_no if header else None,
        "customer_name": customer_name,
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
    order_id: int | None = None,
    *,
    header_id: int | None = None,
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

    order: Order | None = None
    header: ExecutionHeader | None = None
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise PackingError("header_not_found", "执行单不存在")
        pool = _header_item_pool(db, header)
        code_prefix = header.header_no
        order_id = header.shop_order_id
    elif order_id:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise PackingError("order_not_found", "生产单不存在")
        pool = _item_pool(db, order)
        code_prefix = order.order_no
        from app.services.material_service import resolve_header_for_order

        header = resolve_header_for_order(db, tenant_id, order_id)
        header_id = header.id if header else None
    else:
        raise PackingError("missing_ref", "请指定执行单或生产单")

    expected_total = sum(int(r["qty"]) for r in pool)
    packed = (
        _pack_single_size(pool, pairs_per_carton)
        if mode == PackingMode.single_size.value
        else _pack_mixed(pool, pairs_per_carton)
    )
    packed_total = sum(sum(int(x["qty"]) for x in box) for box in packed)
    if packed_total != expected_total:
        raise PackingError("pack_mismatch", "装箱合计与色码不一致")

    if replace_draft:
        old_q = select(PackingPlan).where(
            PackingPlan.tenant_id == tenant_id,
            PackingPlan.basket_id.is_(None),
            PackingPlan.status == PackingPlanStatus.draft,
        )
        if header_id:
            old_q = old_q.where(PackingPlan.header_id == header_id)
        else:
            old_q = old_q.where(PackingPlan.order_id == order_id)
        olds = list(db.scalars(old_q).all())
        for old in olds:
            db.delete(old)
        db.flush()

    plan = PackingPlan(
        tenant_id=tenant_id,
        order_id=order_id,
        basket_id=None,
        execution_id=None,
        header_id=header_id,
        mode=PackingMode(mode),
        pairs_per_carton=pairs_per_carton,
        status=PackingPlanStatus.draft,
        note=note,
        created_by=created_by,
    )
    db.add(plan)
    db.flush()

    for i, box in enumerate(packed, start=1):
        code = f"CTN-{code_prefix}-{i:04d}"
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


def list_packing_plans(
    db: Session,
    tenant_id: int,
    order_id: int | None = None,
    header_id: int | None = None,
) -> list[dict[str, Any]]:
    q = (
        select(PackingPlan)
        .where(PackingPlan.tenant_id == tenant_id, PackingPlan.basket_id.is_(None))
        .options(selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines))
        .order_by(PackingPlan.id.desc())
    )
    if header_id:
        q = q.where(PackingPlan.header_id == header_id)
    elif order_id:
        q = q.where(PackingPlan.order_id == order_id)
    else:
        return []
    rows = list(db.scalars(q).all())
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


def _load_plan(db: Session, plan_id: int) -> PackingPlan | None:
    return db.scalar(
        select(PackingPlan)
        .where(PackingPlan.id == plan_id)
        .options(selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines))
    )


def create_basket_prepack(
    db: Session,
    tenant_id: int,
    basket_id: int,
    *,
    mode: str = PackingMode.single_size.value,
    pairs_per_carton: int = 12,
    note: str | None = None,
    created_by: int | None = None,
    replace_draft: bool = True,
    commit: bool = True,
) -> dict[str, Any]:
    """AU-I2：按筐预装箱（池=筐色码数量）。"""
    if mode not in PackingMode.__members__:
        raise PackingError("invalid_mode", "装箱规则无效（单码/混码）")
    if pairs_per_carton <= 0:
        raise PackingError("invalid_capacity", "每箱双数须大于 0")

    basket = db.get(TraceUnit, basket_id)
    if not basket or basket.tenant_id != tenant_id:
        raise PackingError("basket_not_found", "流转卡不存在")
    ut = _enum_val(basket.unit_type)
    if ut != TraceUnitType.basket.value:
        raise PackingError("not_basket", "仅流转卡(筐)可预装箱")
    qty = int(basket.qty or 0)
    if qty <= 0 or not basket.size_id:
        raise PackingError("invalid_qty", "筐数量/尺码无效，无法预装")
    # K4-E：无壳筐允许仅挂 header_id
    if not basket.order_id and not getattr(basket, "header_id", None):
        raise PackingError("no_order", "筐未关联执行单/生产单，无法预装")

    pool = [{"color_id": basket.color_id, "size_id": int(basket.size_id), "qty": qty}]
    packed = (
        _pack_single_size(pool, pairs_per_carton)
        if mode == PackingMode.single_size.value
        else _pack_mixed(pool, pairs_per_carton)
    )
    packed_total = sum(sum(int(x["qty"]) for x in box) for box in packed)
    if packed_total != qty:
        raise PackingError("pack_mismatch", "预装箱合计与筐数量不一致")

    if replace_draft:
        olds = list(
            db.scalars(
                select(PackingPlan).where(
                    PackingPlan.tenant_id == tenant_id,
                    PackingPlan.basket_id == basket_id,
                    PackingPlan.status == PackingPlanStatus.draft,
                )
            ).all()
        )
        for old in olds:
            db.delete(old)
        db.flush()

    code_prefix = (basket.code or f"B{basket.id}").strip()
    plan = PackingPlan(
        tenant_id=tenant_id,
        order_id=basket.order_id,
        basket_id=basket.id,
        execution_id=getattr(basket, "execution_id", None),
        header_id=getattr(basket, "header_id", None),
        mode=PackingMode(mode),
        pairs_per_carton=pairs_per_carton,
        status=PackingPlanStatus.draft,
        note=note or f"筐预装 {code_prefix}",
        created_by=created_by,
    )
    db.add(plan)
    db.flush()

    for i, box in enumerate(packed, start=1):
        carton = PackingCarton(
            tenant_id=tenant_id,
            plan_id=plan.id,
            seq=i,
            code=f"CTN-{code_prefix}-{i:04d}",
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

    if commit:
        db.commit()
    else:
        db.flush()
    plan = _load_plan(db, plan.id)
    assert plan is not None
    return _plan_out(db, plan)


def list_basket_prepack_plans(db: Session, tenant_id: int, basket_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PackingPlan)
            .where(PackingPlan.tenant_id == tenant_id, PackingPlan.basket_id == basket_id)
            .options(selectinload(PackingPlan.cartons).selectinload(PackingCarton.lines))
            .order_by(PackingPlan.id.desc())
        ).all()
    )
    return [_plan_out(db, p) for p in rows]


def assert_basket_prepack_ready(db: Session, tenant_id: int, basket: TraceUnit) -> PackingPlan:
    """直发前：须有挂本筐的草稿预装，且箱合计=筐数量。"""
    plan = db.scalar(
        select(PackingPlan)
        .where(
            PackingPlan.tenant_id == tenant_id,
            PackingPlan.basket_id == basket.id,
            PackingPlan.status == PackingPlanStatus.draft,
        )
        .options(selectinload(PackingPlan.cartons))
        .order_by(PackingPlan.id.desc())
    )
    if not plan or not plan.cartons:
        raise PackingError("prepack_required", "请先按筐完成预装箱后再直发")
    packed = sum(int(c.total_qty or 0) for c in plan.cartons)
    need = int(basket.qty or 0)
    if packed != need:
        raise PackingError(
            "prepack_qty_mismatch",
            f"预装箱合计 {packed} 与筐数量 {need} 不一致，请重做预装",
        )
    return plan


def settle_basket_prepack(
    db: Session,
    plan: PackingPlan,
    shipments: list[dict[str, Any]],
) -> dict[str, Any]:
    """直发/出货后：预装落成（确认计划，箱挂出货单；不新造箱）。"""
    if not shipments:
        raise PackingError("no_shipments", "无出货单可落成预装")
    remaining = {int(s["id"]): int(s.get("total_qty") or 0) for s in shipments}
    order_ids = [int(s["id"]) for s in shipments]
    cartons = sorted(plan.cartons or [], key=lambda c: c.seq)
    for carton in cartons:
        needy = [sid for sid in order_ids if remaining.get(sid, 0) > 0]
        if not needy:
            carton.shipment_id = order_ids[-1]
            continue
        qty = int(carton.total_qty or 0)
        fit = [sid for sid in needy if qty <= remaining[sid]]
        target = fit[0] if fit else needy[0]
        carton.shipment_id = target
        remaining[target] = remaining.get(target, 0) - qty

    plan.status = PackingPlanStatus.confirmed
    nos = [str(s.get("sales_order_no") or s.get("shipment_no") or s["id"]) for s in shipments]
    suffix = "；落成出货 " + " / ".join(nos)
    plan.note = ((plan.note or "") + suffix)[:255]
    db.flush()
    return {
        "plan_id": plan.id,
        "status": PackingPlanStatus.confirmed.value,
        "carton_count": len(cartons),
        "shipment_ids": [c.shipment_id for c in cartons],
        "cartons": [
            {"id": c.id, "code": c.code, "seq": c.seq, "total_qty": c.total_qty, "shipment_id": c.shipment_id}
            for c in cartons
        ],
    }


def ensure_shipment_packing_cartons(
    db: Session,
    tenant_id: int,
    shipment_id: int,
    *,
    pairs_per_carton: int | None = None,
) -> list[dict[str, Any]]:
    """手工/销售出货无预装时：按出货明细落成简易箱唛（一箱或按容量拆箱）。"""
    existing = list_shipment_packing_cartons(db, tenant_id, shipment_id, auto_ensure=False)
    if existing:
        return existing

    sh = db.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id, Shipment.tenant_id == tenant_id)
        .options(selectinload(Shipment.lines))
    )
    if not sh:
        raise PackingError("shipment_not_found", "出货单不存在")
    if sh.status != ShipmentStatus.shipped:
        raise PackingError("shipment_not_shipped", "仅已出货单可落成箱唛")
    lines = [ln for ln in (sh.lines or []) if int(ln.qty or 0) > 0 and ln.size_id]
    if not lines:
        raise PackingError("empty_lines", "出货单无色码明细，无法装箱")

    cap = int(pairs_per_carton or 0)
    if cap <= 0:
        cap = max(int(sh.total_qty or 0), 1)

    plan = PackingPlan(
        tenant_id=tenant_id,
        order_id=sh.order_id,
        basket_id=None,
        execution_id=None,
        mode=PackingMode.mixed,
        pairs_per_carton=cap,
        status=PackingPlanStatus.confirmed,
        note=f"销售出货落成 {sh.shipment_no}",
    )
    db.add(plan)
    db.flush()

    # 按色码行拆箱：每行凑满 cap；不足则尾箱
    seq = 0
    for ln in lines:
        remain = int(ln.qty)
        while remain > 0:
            take = min(cap, remain)
            seq += 1
            code = f"CTN-{sh.shipment_no}-{seq:04d}"
            # 防撞
            clash = db.scalar(
                select(PackingCarton.id).where(
                    PackingCarton.tenant_id == tenant_id,
                    PackingCarton.code == code,
                )
            )
            if clash:
                code = f"CTN-{sh.shipment_no}-{seq:04d}-{plan.id}"
            carton = PackingCarton(
                tenant_id=tenant_id,
                plan_id=plan.id,
                seq=seq,
                code=code,
                total_qty=take,
                shipment_id=sh.id,
            )
            db.add(carton)
            db.flush()
            db.add(
                PackingCartonLine(
                    tenant_id=tenant_id,
                    carton_id=carton.id,
                    color_id=ln.color_id,
                    size_id=ln.size_id,
                    qty=take,
                )
            )
            remain -= take

    db.flush()
    return list_shipment_packing_cartons(db, tenant_id, shipment_id, auto_ensure=False)


def list_shipment_packing_cartons(
    db: Session, tenant_id: int, shipment_id: int, *, auto_ensure: bool = True
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PackingCarton)
            .where(
                PackingCarton.tenant_id == tenant_id,
                PackingCarton.shipment_id == shipment_id,
            )
            .options(selectinload(PackingCarton.lines), selectinload(PackingCarton.plan))
            .order_by(PackingCarton.seq, PackingCarton.id)
        ).all()
    )
    if rows:
        return [_carton_out(db, c) for c in rows]
    if not auto_ensure:
        return []
    sh = db.get(Shipment, shipment_id)
    if not sh or sh.tenant_id != tenant_id or sh.status != ShipmentStatus.shipped:
        return []
    # 已出货但无箱：自动落成（手工销售出货）
    try:
        out = ensure_shipment_packing_cartons(db, tenant_id, shipment_id)
        db.commit()
        return out
    except PackingError:
        return []
