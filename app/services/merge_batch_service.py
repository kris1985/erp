"""B2f：合批 L1+L2 — 组批、汇总色码、合批流转卡数据。领料/报工仍分生产单。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    MergeBatch,
    MergeBatchMember,
    MergeBatchStatus,
    Order,
    OrderItem,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    Size,
)


class MergeBatchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _order_color_ids(db: Session, order_id: int, tenant_id: int) -> set[int | None]:
    rows = db.scalars(
        select(OrderItem.color_id).where(
            OrderItem.tenant_id == tenant_id,
            OrderItem.order_id == order_id,
            OrderItem.qty > 0,
        )
    ).all()
    return set(rows)


def _assert_orders_for_batch(
    db: Session,
    tenant_id: int,
    orders: list[Order],
    *,
    require_same_color: bool,
    expected_product_id: int | None = None,
) -> tuple[int, int | None]:
    if len(orders) < 1:
        raise MergeBatchError("empty", "请至少选择一张生产单")
    product_ids = {o.own_product_id for o in orders}
    if len(product_ids) != 1:
        raise MergeBatchError("diff_product", "不同款无法组成合批")
    product_id = next(iter(product_ids))
    if expected_product_id is not None and product_id != expected_product_id:
        raise MergeBatchError("diff_product", "成员必须与合批同款")

    for o in orders:
        st = _enum_val(o.status)
        if st == OrderStatus.cancelled.value:
            raise MergeBatchError("cancelled", f"生产单 {o.order_no} 已取消，不能合批")

    color_ids: set[int | None] = set()
    for o in orders:
        color_ids |= _order_color_ids(db, o.id, tenant_id)

    locked_color: int | None = None
    if require_same_color:
        concrete = {c for c in color_ids if c is not None}
        if len(concrete) > 1:
            raise MergeBatchError(
                "diff_color",
                "默认同色：所选生产单含多种颜色，请去掉异色单或勾选「允许多色」",
            )
        if concrete:
            locked_color = next(iter(concrete))
    return product_id, locked_color


def _active_member_order_ids(db: Session, tenant_id: int, order_ids: list[int]) -> dict[int, str]:
    """order_id → batch_no for orders already in an open batch."""
    if not order_ids:
        return {}
    rows = db.execute(
        select(MergeBatchMember.order_id, MergeBatch.batch_no)
        .join(MergeBatch, MergeBatch.id == MergeBatchMember.batch_id)
        .where(
            MergeBatchMember.tenant_id == tenant_id,
            MergeBatchMember.order_id.in_(order_ids),
            MergeBatch.status == MergeBatchStatus.open,
        )
    ).all()
    return {int(r[0]): str(r[1]) for r in rows}


def _next_batch_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = f"MB-{today}-"
    last = db.scalar(
        select(MergeBatch.batch_no)
        .where(MergeBatch.tenant_id == tenant_id, MergeBatch.batch_no.like(f"{prefix}%"))
        .order_by(MergeBatch.id.desc())
        .limit(1)
    )
    seq = 1
    if last and last.startswith(prefix):
        try:
            seq = int(last.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:03d}"


def _size_summary(db: Session, tenant_id: int, order_ids: list[int]) -> list[dict[str, Any]]:
    if not order_ids:
        return []
    rows = db.execute(
        select(
            OrderItem.color_id,
            OrderItem.size_id,
            func.sum(OrderItem.qty).label("qty"),
        )
        .where(
            OrderItem.tenant_id == tenant_id,
            OrderItem.order_id.in_(order_ids),
            OrderItem.qty > 0,
        )
        .group_by(OrderItem.color_id, OrderItem.size_id)
    ).all()
    color_ids = {r[0] for r in rows if r[0]}
    size_ids = {r[1] for r in rows if r[1]}
    colors = {
        c.id: c
        for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()
    } if color_ids else {}
    sizes = {
        s.id: s
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids))).all()
    } if size_ids else {}

    out: list[dict[str, Any]] = []
    for color_id, size_id, qty in rows:
        c = colors.get(color_id) if color_id else None
        s = sizes.get(size_id) if size_id else None
        out.append(
            {
                "color_id": color_id,
                "color_name": c.name if c else None,
                "size_id": size_id,
                "size_value": s.size_value if s else None,
                "qty": int(qty or 0),
            }
        )
    out.sort(
        key=lambda x: (
            x.get("color_name") or "",
            (sizes.get(x["size_id"]).sort_order if x.get("size_id") and sizes.get(x["size_id"]) else 0),
            x.get("size_value") or "",
        )
    )
    return out


def _member_out(db: Session, order: Order) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
        "total_qty": int(order.total_qty or 0),
        "status": _enum_val(order.status),
        "is_rush": bool(order.is_rush),
    }


def _process_summary(db: Session, tenant_id: int, order_ids: list[int]) -> list[dict[str, Any]]:
    if not order_ids:
        return []
    ord_col = func.min(OrderProcess.id).label("ord")
    rows = db.execute(
        select(
            OrderProcess.process_id,
            OrderProcess.process_name,
            ord_col,
            func.sum(OrderProcess.plan_qty).label("plan_qty"),
        )
        .where(
            OrderProcess.tenant_id == tenant_id,
            OrderProcess.order_id.in_(order_ids),
        )
        .group_by(OrderProcess.process_id, OrderProcess.process_name)
        .order_by(ord_col)
    ).all()
    return [
        {
            "process_id": r[0],
            "process_name": r[1],
            "plan_qty": int(r[3] or 0),
        }
        for r in rows
    ]


def serialize_batch(db: Session, batch: MergeBatch) -> dict[str, Any]:
    members = list(
        db.scalars(
            select(MergeBatchMember)
            .where(
                MergeBatchMember.tenant_id == batch.tenant_id,
                MergeBatchMember.batch_id == batch.id,
            )
            .order_by(MergeBatchMember.id)
        ).all()
    )
    order_ids = [m.order_id for m in members]
    orders = {
        o.id: o
        for o in db.scalars(
            select(Order).where(Order.tenant_id == batch.tenant_id, Order.id.in_(order_ids))
        ).all()
    } if order_ids else {}
    product = db.get(OwnProduct, batch.own_product_id)
    color = db.get(Color, batch.color_id) if batch.color_id else None
    size_rows = _size_summary(db, batch.tenant_id, order_ids)
    total_qty = sum(r["qty"] for r in size_rows)
    member_list = [_member_out(db, orders[m.order_id]) for m in members if m.order_id in orders]
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "own_product_id": batch.own_product_id,
        "product_code": product.product_code if product else None,
        "color_id": batch.color_id,
        "color_name": color.name if color else None,
        "status": _enum_val(batch.status),
        "note": batch.note,
        "created_at": batch.created_at.isoformat(timespec="seconds") if batch.created_at else None,
        "member_count": len(member_list),
        "total_qty": total_qty,
        "members": member_list,
        "size_summary": size_rows,
        "processes": _process_summary(db, batch.tenant_id, order_ids),
    }


def create_merge_batch(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    require_same_color: bool = True,
    note: str | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    ids = sorted({int(x) for x in order_ids if x})
    if len(ids) < 2:
        raise MergeBatchError("need_two", "合批至少需要两张生产单")

    orders = list(
        db.scalars(select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(ids))).all()
    )
    if len(orders) != len(ids):
        raise MergeBatchError("not_found", "部分生产单不存在或不属于本租户")

    product_id, locked_color = _assert_orders_for_batch(
        db, tenant_id, orders, require_same_color=require_same_color
    )

    busy = _active_member_order_ids(db, tenant_id, ids)
    if busy:
        sample = next(iter(busy.items()))
        raise MergeBatchError(
            "already_in_batch",
            f"生产单已在合批 {sample[1]} 中，请先移出再组批",
        )

    batch = MergeBatch(
        tenant_id=tenant_id,
        batch_no=_next_batch_no(db, tenant_id),
        own_product_id=product_id,
        color_id=locked_color if require_same_color else None,
        status=MergeBatchStatus.open,
        note=note,
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    for oid in ids:
        db.add(MergeBatchMember(tenant_id=tenant_id, batch_id=batch.id, order_id=oid))
    db.commit()
    db.refresh(batch)
    return serialize_batch(db, batch)


def get_merge_batch(db: Session, tenant_id: int, batch_id: int) -> dict[str, Any]:
    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")
    return serialize_batch(db, batch)


def list_merge_batches(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = None,
    own_product_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = select(MergeBatch).where(MergeBatch.tenant_id == tenant_id)
    if status:
        q = q.where(MergeBatch.status == status)
    if own_product_id:
        q = q.where(MergeBatch.own_product_id == own_product_id)
    q = q.order_by(MergeBatch.id.desc()).limit(min(limit, 200))
    batches = list(db.scalars(q).all())
    return [serialize_batch(db, b) for b in batches]


def add_members(
    db: Session,
    tenant_id: int,
    batch_id: int,
    order_ids: list[int],
    *,
    require_same_color: bool = True,
) -> dict[str, Any]:
    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")
    if _enum_val(batch.status) != MergeBatchStatus.open.value:
        raise MergeBatchError("closed", "合批已关闭或作废，不能加成员")

    ids = sorted({int(x) for x in order_ids if x})
    if not ids:
        raise MergeBatchError("empty", "请选择要加入的生产单")

    existing = {
        m.order_id
        for m in db.scalars(
            select(MergeBatchMember).where(
                MergeBatchMember.tenant_id == tenant_id,
                MergeBatchMember.batch_id == batch_id,
            )
        ).all()
    }
    new_ids = [i for i in ids if i not in existing]
    if not new_ids:
        return serialize_batch(db, batch)

    orders = list(
        db.scalars(select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(new_ids))).all()
    )
    if len(orders) != len(new_ids):
        raise MergeBatchError("not_found", "部分生产单不存在")

    # 校验：新成员 + 现有成员整体同款/同色
    all_member_ids = list(existing) + new_ids
    all_orders = list(
        db.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(all_member_ids))
        ).all()
    )
    _assert_orders_for_batch(
        db,
        tenant_id,
        all_orders,
        require_same_color=require_same_color,
        expected_product_id=batch.own_product_id,
    )

    busy = _active_member_order_ids(db, tenant_id, new_ids)
    if busy:
        sample = next(iter(busy.items()))
        raise MergeBatchError("already_in_batch", f"生产单已在合批 {sample[1]} 中")

    for oid in new_ids:
        db.add(MergeBatchMember(tenant_id=tenant_id, batch_id=batch.id, order_id=oid))

    if require_same_color and batch.color_id is None:
        _, locked = _assert_orders_for_batch(
            db, tenant_id, all_orders, require_same_color=True, expected_product_id=batch.own_product_id
        )
        batch.color_id = locked

    db.commit()
    db.refresh(batch)
    return serialize_batch(db, batch)


def remove_member(db: Session, tenant_id: int, batch_id: int, order_id: int) -> dict[str, Any]:
    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")
    if _enum_val(batch.status) != MergeBatchStatus.open.value:
        raise MergeBatchError("closed", "合批已关闭或作废，不能移出成员")

    member = db.scalar(
        select(MergeBatchMember).where(
            MergeBatchMember.tenant_id == tenant_id,
            MergeBatchMember.batch_id == batch_id,
            MergeBatchMember.order_id == order_id,
        )
    )
    if not member:
        raise MergeBatchError("not_member", "该生产单不在本合批中")

    remaining = (
        db.scalar(
            select(func.count())
            .select_from(MergeBatchMember)
            .where(
                MergeBatchMember.tenant_id == tenant_id,
                MergeBatchMember.batch_id == batch_id,
                MergeBatchMember.order_id != order_id,
            )
        )
        or 0
    )
    if remaining < 1:
        raise MergeBatchError("last_member", "至少保留一张生产单；若要解散请作废合批")

    db.delete(member)
    db.commit()
    db.refresh(batch)
    return serialize_batch(db, batch)


def void_batch(db: Session, tenant_id: int, batch_id: int) -> dict[str, Any]:
    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")
    batch.status = MergeBatchStatus.void
    db.commit()
    db.refresh(batch)
    return serialize_batch(db, batch)


def preview_or_create_merge_cut_cards(
    db: Session,
    tenant_id: int,
    batch_id: int,
    *,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
) -> dict[str, Any]:
    """B2h-R5b：合批一次给所有成员开裁生码；码仍分挂各生产单。"""
    from app.services.trace_service import TraceError, preview_or_create_cut_cards

    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")
    if _enum_val(batch.status) != MergeBatchStatus.open.value:
        raise MergeBatchError("closed", "合批已关闭或作废，不能开裁打主码")

    members = list(
        db.scalars(
            select(MergeBatchMember)
            .where(
                MergeBatchMember.tenant_id == tenant_id,
                MergeBatchMember.batch_id == batch_id,
            )
            .order_by(MergeBatchMember.id)
        ).all()
    )
    if not members:
        raise MergeBatchError("empty", "合批无成员")

    order_results: list[dict[str, Any]] = []
    total_to_create = 0
    total_created = 0
    created_all: list[dict[str, Any]] = []

    try:
        for m in members:
            order = db.get(Order, m.order_id)
            if not order or order.tenant_id != tenant_id:
                raise MergeBatchError("not_found", f"成员生产单 {m.order_id} 不存在")
            try:
                data = preview_or_create_cut_cards(
                    db,
                    tenant_id=tenant_id,
                    order_id=order.id,
                    dry_run=dry_run,
                    bundle_size=bundle_size,
                    only_missing=only_missing,
                    commit=False,
                )
            except TraceError as e:
                raise MergeBatchError(e.code, f"{order.order_no}：{e.message}") from e
            order_results.append(
                {
                    "order_id": data["order_id"],
                    "order_no": data["order_no"],
                    "lines": data["lines"],
                    "to_create": data["to_create"],
                    "created": data.get("created") or [],
                }
            )
            total_to_create += int(data.get("to_create") or 0)
            created = data.get("created") or []
            total_created += len(created)
            for c in created:
                created_all.append({**c, "order_id": order.id, "order_no": order.order_no})

        if not dry_run and total_created:
            db.commit()
            for c in created_all:
                from app.models import TraceUnit

                u = db.get(TraceUnit, c["id"])
                if u:
                    db.refresh(u)
                    c["code"] = u.code
        elif not dry_run:
            db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "batch_id": batch.id,
        "batch_no": batch.batch_no,
        "strategy": {"bundle_size": bundle_size},
        "members": order_results,
        "to_create": total_to_create,
        "created_count": total_created if not dry_run else 0,
        "created": created_all if not dry_run else [],
        "print_path": f"/admin/merge-batches/print/{batch.id}?mode=main-codes",
    }


def list_merge_batch_trace_units(
    db: Session, tenant_id: int, batch_id: int
) -> dict[str, Any]:
    """合批主码打印：按成员列出捆标。"""
    from app.models import TraceUnit

    batch = db.scalar(
        select(MergeBatch).where(MergeBatch.tenant_id == tenant_id, MergeBatch.id == batch_id)
    )
    if not batch:
        raise MergeBatchError("not_found", "合批不存在")

    members = list(
        db.scalars(
            select(MergeBatchMember)
            .where(
                MergeBatchMember.tenant_id == tenant_id,
                MergeBatchMember.batch_id == batch_id,
            )
            .order_by(MergeBatchMember.id)
        ).all()
    )
    out_members: list[dict[str, Any]] = []
    total_units = 0
    for m in members:
        order = db.get(Order, m.order_id)
        if not order:
            continue
        units = list(
            db.scalars(
                select(TraceUnit)
                .where(
                    TraceUnit.tenant_id == tenant_id,
                    TraceUnit.order_id == order.id,
                )
                .order_by(TraceUnit.id)
            ).all()
        )
        items = []
        for u in units:
            color = db.get(Color, u.color_id) if u.color_id else None
            size = db.get(Size, u.size_id) if u.size_id else None
            st = _enum_val(u.status)
            items.append(
                {
                    "id": u.id,
                    "code": u.code,
                    "qty": u.qty,
                    "color_id": u.color_id,
                    "color_name": color.name if color else None,
                    "size_id": u.size_id,
                    "size_value": size.size_value if size else None,
                    "status": st,
                }
            )
        total_units += len(items)
        out_members.append(
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "units": items,
            }
        )

    product = db.get(OwnProduct, batch.own_product_id) if batch.own_product_id else None
    return {
        "batch_id": batch.id,
        "batch_no": batch.batch_no,
        "product_code": product.product_code if product else None,
        "member_count": len(out_members),
        "unit_count": total_units,
        "members": out_members,
    }
