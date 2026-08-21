"""生产批次（D25/P7 40）：开裁自动建批，批次号系统自动生成。

- 不分批（默认）：每单开裁自动一个默认批次号；
- 分批：用户自选每批双数，拆多个批次号（筐不跨批，最后一批吃余数）；
- 批次仅作排产/统计/追溯聚合维度（报工/不良/筐挂 batch_id），不建批次卡、不强制扫码。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BatchMaterialConsumption,
    ExecutionHeader,
    OrderMaterialRequirement,
    ProductionBatch,
    ProductionBatchStatus,
    SpecExecutionOrder,
    TraceUnit,
    TraceUnitType,
)


def snapshot_batch_material_consumption(
    db: Session,
    tenant_id: int,
    *,
    batch: ProductionBatch,
    size_qtys: dict[int, int],
) -> list[BatchMaterialConsumption]:
    """按生产单用料快照比例固化本批理论耗用，不改变库存实账。"""
    if not batch.header_id:
        return []
    header = db.get(ExecutionHeader, batch.header_id)
    if not header:
        return []
    size_plans = {
        int(row.size_id): int(row.total_qty or 0)
        for row in db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.header_id == header.id,
            )
        ).all()
        if row.size_id
    }
    total_batch_pairs = sum(max(0, int(q)) for q in size_qtys.values())
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header.id,
            )
        ).all()
    )
    rows: list[BatchMaterialConsumption] = []
    for req in reqs:
        if req.usage_by_size and req.size_id:
            batch_pairs = max(0, int(size_qtys.get(int(req.size_id), 0)))
            planned_pairs = max(0, int(size_plans.get(int(req.size_id), 0)))
        else:
            batch_pairs = total_batch_pairs
            planned_pairs = max(0, int(header.total_qty or 0))
        if batch_pairs <= 0 or planned_pairs <= 0:
            continue
        theoretical = (
            Decimal(req.required_qty or 0)
            * Decimal(batch_pairs)
            / Decimal(planned_pairs)
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        row = BatchMaterialConsumption(
            tenant_id=tenant_id,
            batch_id=batch.id,
            requirement_id=req.id,
            supplier_product_id=req.supplier_product_id,
            size_id=req.size_id if req.usage_by_size else None,
            batch_pairs=batch_pairs,
            planned_pairs_snapshot=planned_pairs,
            required_qty_snapshot=req.required_qty or Decimal("0"),
            theoretical_qty=theoretical,
            qty_per_pair_snapshot=req.qty_per_pair or Decimal("0"),
            loss_rate_snapshot=req.loss_rate or Decimal("0"),
            size_coeff_snapshot=req.size_coeff or Decimal("1"),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def backfill_missing_batch_material_consumptions(
    db: Session,
    tenant_id: int,
    header_id: int,
) -> int:
    """为旧裁断批次补齐耗用快照；已有任一快照的批次保持不变。"""
    batches = list(
        db.scalars(
            select(ProductionBatch).where(
                ProductionBatch.tenant_id == tenant_id,
                ProductionBatch.header_id == header_id,
            )
        ).all()
    )
    if not batches:
        return 0
    batch_ids = [batch.id for batch in batches]
    snapshotted = set(
        db.scalars(
            select(BatchMaterialConsumption.batch_id)
            .where(
                BatchMaterialConsumption.tenant_id == tenant_id,
                BatchMaterialConsumption.batch_id.in_(batch_ids),
            )
            .distinct()
        ).all()
    )
    created = 0
    for batch in batches:
        if batch.id in snapshotted:
            continue
        size_qtys = {
            int(size_id): int(qty or 0)
            for size_id, qty in db.execute(
                select(TraceUnit.size_id, func.sum(TraceUnit.qty))
                .where(
                    TraceUnit.tenant_id == tenant_id,
                    TraceUnit.batch_id == batch.id,
                    TraceUnit.unit_type == TraceUnitType.basket,
                    TraceUnit.size_id.is_not(None),
                )
                .group_by(TraceUnit.size_id)
            ).all()
            if size_id
        }
        created += len(
            snapshot_batch_material_consumption(
                db,
                tenant_id,
                batch=batch,
                size_qtys=size_qtys,
            )
        )
    return created


def list_cut_batches(db: Session, tenant_id: int, header_id: int) -> dict:
    """裁断批次及理论耗用快照；领料实账仍按生产单累计展示。"""
    from app.models import Size, SupplierProduct

    batches = list(
        db.scalars(
            select(ProductionBatch)
            .where(
                ProductionBatch.tenant_id == tenant_id,
                ProductionBatch.header_id == header_id,
            )
            .order_by(ProductionBatch.id.desc())
        ).all()
    )
    batch_ids = [b.id for b in batches]
    snapshots = list(
        db.scalars(
            select(BatchMaterialConsumption).where(
                BatchMaterialConsumption.tenant_id == tenant_id,
                BatchMaterialConsumption.batch_id.in_(batch_ids or [0]),
            )
        ).all()
    )
    by_batch: dict[int, list[dict]] = {}
    for row in snapshots:
        req = db.get(OrderMaterialRequirement, row.requirement_id)
        material = db.get(SupplierProduct, row.supplier_product_id)
        size = db.get(Size, row.size_id) if row.size_id else None
        by_batch.setdefault(row.batch_id, []).append(
            {
                "id": row.id,
                "requirement_id": row.requirement_id,
                "supplier_product_id": row.supplier_product_id,
                "material_code": material.product_code if material else None,
                "material_name": material.name if material else None,
                "size_id": row.size_id,
                "size_value": size.size_value if size else None,
                "batch_pairs": row.batch_pairs,
                "theoretical_qty": float(row.theoretical_qty),
                "required_qty_snapshot": float(row.required_qty_snapshot),
                "issued_qty_order_total": float(req.issued_qty or 0) if req else 0,
            }
        )
    return {
        "items": [
            {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "qty": batch.qty,
                "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
                "created_at": batch.created_at.isoformat() if batch.created_at else None,
                "materials": by_batch.get(batch.id, []),
            }
            for batch in batches
        ]
    }


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
    force_new: bool = False,
) -> tuple[list[ProductionBatch], list[int]]:
    """开裁建批/复用：返回 (批次列表, 筐→批次下标分配)。

    - batch_qtys 为空/None：复用该单活动批次；无则建一个默认批。
    - batch_qtys 非空：按每批双数建新批（补裁时新筐进新批），qty 回填实际分配。
    """
    caps = normalize_batch_qtys(batch_qtys)
    if caps is None:
        active = list_active_batches(db, tenant_id, header_id=header_id, order_id=order_id)
        if active and not force_new:
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
    force_new: bool = False,
) -> list[dict]:
    """dry_run 预览：本次筐应挂的批次号 + 每批实际双数/筐数（不落库）。"""
    caps = normalize_batch_qtys(batch_qtys)
    if caps is None:
        active = list_active_batches(db, tenant_id, header_id=header_id, order_id=order_id)
        total = sum(int(q) for _i, q, _s in planned)
        if active and not force_new:
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
