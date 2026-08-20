"""生产批次（D25/P7 40）：开裁自动建批，批次号系统自动生成。

- 不分批（默认）：每单开裁自动一个默认批次号；
- 分批：用户自选每批双数，拆多个批次号（筐不跨批，最后一批吃余数）；
- 批次仅作排产/统计/追溯聚合维度（报工/不良/筐挂 batch_id），不建批次卡、不强制扫码。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProductionBatch, ProductionBatchStatus


def _active_statuses() -> tuple:
    return (ProductionBatchStatus.open, ProductionBatchStatus.in_production)


def list_active_batches(
    db: Session, tenant_id: int, *, header_id: int | None, order_id: int | None
) -> list[ProductionBatch]:
    """生产单当前活动批次（open / in_production）。"""
    q = select(ProductionBatch).where(
        ProductionBatch.tenant_id == tenant_id,
        ProductionBatch.status.in_(_active_statuses()),
    )
    if header_id is not None:
        q = q.where(ProductionBatch.header_id == header_id)
    elif order_id is not None:
        q = q.where(ProductionBatch.order_id == order_id)
    else:
        return []
    return list(db.scalars(q.order_by(ProductionBatch.id)).all())


def normalize_batch_qtys(batch_qtys: list[int] | None) -> list[int] | None:
    """过滤非法批次双数；空/无效 → None（不分批）。"""
    if not batch_qtys:
        return None
    caps = [int(q) for q in batch_qtys if q and int(q) > 0]
    return caps or None


def plan_allocation(planned: list[tuple], caps: list[int]) -> tuple[list[int], list[int]]:
    """把按创建顺序的筐分配到各批次（唯一分配逻辑，预览与落库同源）。

    planned: [(item, qty, so_id), ...]；caps: 每批目标双数（≥1 个正数）。
    筐不跨批；先装满前批（贪心），最后一批吃余数；返回
    (assignments, actual_qtys)：与 planned 等长的批次下标 + 每批实际双数。
    """
    if not planned:
        return [], [0] * len(caps)
    if len(caps) == 1:
        total = sum(int(q) for _i, q, _s in planned)
        return [0] * len(planned), [total]
    assignments: list[int] = []
    bi = 0
    used = 0
    for _item, q, _so in planned:
        q = int(q)
        while bi < len(caps) - 1 and caps[bi] > 0 and used + q > caps[bi]:
            bi += 1
            used = 0
        assignments.append(bi)
        used += q
        if bi < len(caps) - 1 and caps[bi] > 0 and used >= caps[bi]:
            bi += 1
            used = 0
    actual = [0] * len(caps)
    for (_item, q, _so), a in zip(planned, assignments):
        actual[a] += int(q)
    return assignments, actual


def next_batch_no(
    db: Session, tenant_id: int, *, header_id: int | None, order_id: int | None
) -> str:
    """批次号：{单号}-{seq:02d}；seq 按该生产单已有批次数递增，保证同单内唯一。"""
    base = _batch_base(db, tenant_id, header_id=header_id, order_id=order_id)
    seq = _batch_count(db, tenant_id, header_id=header_id, order_id=order_id) + 1
    return f"{base}-{seq:02d}"


def create_batch(
    db: Session,
    tenant_id: int,
    *,
    header_id: int | None,
    order_id: int | None,
    product_id: int | None,
    qty: int,
    created_by: int | None = None,
) -> ProductionBatch:
    batch = ProductionBatch(
        tenant_id=tenant_id,
        batch_no=next_batch_no(db, tenant_id, header_id=header_id, order_id=order_id),
        order_id=order_id,
        header_id=header_id,
        product_id=product_id,
        qty=qty,
        status=ProductionBatchStatus.open,
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    return batch


def ensure_batches_for_cut(
    db: Session,
    tenant_id: int,
    *,
    header_id: int | None,
    order_id: int | None,
    product_id: int | None,
    batch_qtys: list[int] | None,
    planned: list[tuple],
) -> tuple[list[ProductionBatch], list[int]]:
    """开裁建批/复用：返回 (批次列表, 筐→批次下标分配)。

    - batch_qtys 为空/None：复用该单活动批次；无则建一个默认批。
    - batch_qtys 非空：按每批双数建新批（补裁时新筐进新批），qty 回填实际分配。
    """
    caps = normalize_batch_qtys(batch_qtys)
    if caps is None:
        active = list_active_batches(db, tenant_id, header_id=header_id, order_id=order_id)
        if active:
            return active, [0] * len(planned)
        total = sum(int(q) for _i, q, _s in planned)
        batch = create_batch(
            db,
            tenant_id,
            header_id=header_id,
            order_id=order_id,
            product_id=product_id,
            qty=total,
        )
        return [batch], [0] * len(planned)
    assignments, actual = plan_allocation(planned, caps)
    batches = [
        create_batch(
            db,
            tenant_id,
            header_id=header_id,
            order_id=order_id,
            product_id=product_id,
            qty=actual[i],
        )
        for i in range(len(caps))
    ]
    return batches, assignments


def batches_preview(
    db: Session,
    tenant_id: int,
    *,
    header_id: int | None,
    order_id: int | None,
    planned: list[tuple],
    batch_qtys: list[int] | None,
) -> list[dict]:
    """dry_run 预览：本次筐应挂的批次号 + 每批实际双数/筐数（不落库）。"""
    caps = normalize_batch_qtys(batch_qtys)
    if caps is None:
        active = list_active_batches(db, tenant_id, header_id=header_id, order_id=order_id)
        total = sum(int(q) for _i, q, _s in planned)
        if active:
            return [{"batch_no": b.batch_no, "qty": total, "unit_count": len(planned)} for b in active]
        return [
            {
                "batch_no": next_batch_no(db, tenant_id, header_id=header_id, order_id=order_id),
                "qty": total,
                "unit_count": len(planned),
            }
        ]
    base = _batch_base(db, tenant_id, header_id=header_id, order_id=order_id)
    existing = _batch_count(db, tenant_id, header_id=header_id, order_id=order_id)
    assignments, actual = plan_allocation(planned, caps)
    unit_counts = [0] * len(caps)
    for a in assignments:
        unit_counts[a] += 1
    return [
        {
            "batch_no": f"{base}-{int(existing) + i + 1:02d}",
            "qty": actual[i],
            "unit_count": unit_counts[i],
        }
        for i in range(len(caps))
    ]


def _batch_count(
    db: Session, tenant_id: int, *, header_id: int | None, order_id: int | None
) -> int:
    q = (
        select(func.count())
        .select_from(ProductionBatch)
        .where(ProductionBatch.tenant_id == tenant_id)
    )
    if header_id is not None:
        q = q.where(ProductionBatch.header_id == header_id)
    elif order_id is not None:
        q = q.where(ProductionBatch.order_id == order_id)
    return int(db.scalar(q) or 0)


def _batch_base(db: Session, tenant_id: int, *, header_id: int | None, order_id: int | None) -> str:
    if header_id is not None:
        from app.models import ExecutionHeader

        hdr = db.get(ExecutionHeader, header_id)
        if hdr:
            return hdr.header_no
    if order_id is not None:
        from app.models import Order

        o = db.get(Order, order_id)
        if o:
            return o.order_no
    return f"P{header_id or order_id or 0}"
