"""自己产品开发：成品 + 颜色 + 供应商物料 + 工序人工 + 客户报价。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import (
    Color,
    MaterialSizeUsageTable,
    OwnProduct,
    OwnProductColor,
    OwnProductLabor,
    OwnProductMaterial,
    OwnProductOtherCost,
    OwnProductPart,
    OwnProductQuote,
    OtherCostItem,
    PartDefinition,
    Partner,
    PricingUnit,
    ProcessDefinition,
    ProcessType,
    SupplierProduct,
    Tenant,
    User,
)
from app.services.material_service import process_display_name, resolve_consume_process
from app.schemas.api import (
    ColorOut,
    OwnProductBatchQuoteExportIn,
    OwnProductCreate,
    OwnProductLaborIn,
    OwnProductLaborOut,
    OwnProductMaterialIn,
    OwnProductMaterialOut,
    OwnProductOtherCostIn,
    OwnProductOtherCostOut,
    OwnProductOut,
    OwnProductPartIn,
    OwnProductPartOut,
    OwnProductQuoteIn,
    OwnProductQuoteOut,
    OwnProductUpdate,
)
from app.schemas.common import normalize_page, ok, page_payload

router = APIRouter(prefix="/own-products", tags=["own-products"])


def _line_total(qty: Decimal, unit_price: Decimal) -> Decimal:
    return (qty * unit_price).quantize(Decimal("0.0001"))


def _material_out(
    m: OwnProductMaterial,
    sp: SupplierProduct | None,
    partner: Partner | None,
    unit: PricingUnit | None,
    color: Color | None,
    *,
    consume_process_name: str | None = None,
    consume_source: str | None = None,
    size_usage_table_name: str | None = None,
    bom_color: Color | None = None,
) -> OwnProductMaterialOut:
    return OwnProductMaterialOut(
        id=m.id,
        supplier_product_id=m.supplier_product_id,
        supplier_product_code=sp.product_code if sp else None,
        supplier_product_name=sp.name if sp else None,
        image_url=sp.image_url if sp else None,
        internal_code=sp.internal_code if sp else None,
        color_name=color.name if color else None,
        partner_name=partner.name if partner else None,
        pricing_unit_name=unit.name if unit else None,
        qty=m.qty,
        unit_price=m.unit_price,
        line_total=m.line_total,
        sort_order=m.sort_order,
        consume_process_id=getattr(m, "consume_process_id", None),
        consume_process_name=consume_process_name,
        consume_source=consume_source,
        usage_by_size=bool(getattr(m, "usage_by_size", False)),
        size_usage_table_id=getattr(m, "size_usage_table_id", None),
        size_usage_table_name=size_usage_table_name,
        loss_rate=getattr(m, "loss_rate", None) or Decimal("0"),
        loss_fixed_qty=getattr(m, "loss_fixed_qty", None) or Decimal("0"),
        bom_color_id=getattr(m, "color_id", None),
        bom_color_name=bom_color.name if bom_color else None,
    )


def _labor_out(row: OwnProductLabor, process: ProcessDefinition | None) -> OwnProductLaborOut:
    name = getattr(row, "process_name", None) or (process.name if process else None)
    ptype = "personal"
    if process and process.type is not None:
        ptype = process.type.value if hasattr(process.type, "value") else str(process.type)
    return OwnProductLaborOut(
        id=row.id,
        process_id=row.process_id,
        process_name=name,
        process_type=ptype,
        unit_price=row.unit_price,
        sort_order=row.sort_order,
        part_id=getattr(row, "part_id", None),
        is_kit_checkpoint=bool(getattr(row, "is_kit_checkpoint", False)),
    )


def _part_row_out(row: OwnProductPart, part: PartDefinition | None) -> OwnProductPartOut:
    return OwnProductPartOut(
        id=row.id,
        part_id=row.part_id,
        part_code=part.code if part else None,
        part_name=part.name if part else None,
        part_source=part.source if part else None,
        pieces_per_pair=int(row.pieces_per_pair or 1),
        sort_order=row.sort_order,
        source_supplier_product_id=row.source_supplier_product_id,
    )


def _quote_out(row: OwnProductQuote, partner: Partner | None) -> OwnProductQuoteOut:
    return OwnProductQuoteOut(
        id=row.id,
        partner_id=row.partner_id,
        partner_name=partner.name if partner else None,
        partner_short_name=partner.short_name if partner else None,
        quote_price=row.quote_price,
        sort_order=row.sort_order,
    )


def _product_out(p: OwnProduct, db: Session) -> dict:
    color_rows = list(p.colors or [])
    color_ids = [c.color_id for c in color_rows]
    colors: list[ColorOut] = []
    if color_ids:
        cmap = {
            c.id: c
            for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()
        }
        colors = [ColorOut.model_validate(cmap[i]) for i in color_ids if i in cmap]

    materials_out: list[OwnProductMaterialOut] = []
    mats = list(p.materials or [])
    sp_ids = [m.supplier_product_id for m in mats]
    sp_map: dict[int, SupplierProduct] = {}
    material_partner_map: dict[int, Partner] = {}
    unit_map: dict[int, PricingUnit] = {}
    color_map: dict[int, Color] = {}
    if sp_ids:
        sps = db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(sp_ids))).all()
        sp_map = {s.id: s for s in sps}
        partner_ids = {s.partner_id for s in sps}
        unit_ids = {s.pricing_unit_id for s in sps if s.pricing_unit_id}
        fetch_color_ids = {s.color_id for s in sps if s.color_id}
        fetch_color_ids |= {m.color_id for m in mats if getattr(m, "color_id", None)}
        if partner_ids:
            material_partner_map = {
                x.id: x for x in db.scalars(select(Partner).where(Partner.id.in_(partner_ids))).all()
            }
        if unit_ids:
            unit_map = {
                x.id: x for x in db.scalars(select(PricingUnit).where(PricingUnit.id.in_(unit_ids))).all()
            }
        if fetch_color_ids:
            color_map = {
                x.id: x for x in db.scalars(select(Color).where(Color.id.in_(fetch_color_ids))).all()
            }
    for m in mats:
        sp = sp_map.get(m.supplier_product_id)
        partner = material_partner_map.get(sp.partner_id) if sp else None
        unit = unit_map.get(sp.pricing_unit_id) if sp and sp.pricing_unit_id else None
        color = color_map.get(sp.color_id) if sp and sp.color_id else None
        bom_color = color_map.get(m.color_id) if getattr(m, "color_id", None) else None
        resolved_id, source = resolve_consume_process(
            db,
            p.tenant_id,
            bom_consume_process_id=getattr(m, "consume_process_id", None),
            supplier_product_id=m.supplier_product_id,
        )
        table_name = None
        tid = getattr(m, "size_usage_table_id", None)
        if tid:
            table = db.get(MaterialSizeUsageTable, tid)
            table_name = table.name if table else None
        materials_out.append(
            _material_out(
                m,
                sp,
                partner,
                unit,
                color,
                consume_process_name=process_display_name(db, resolved_id),
                consume_source=source,
                size_usage_table_name=table_name,
                bom_color=bom_color,
            )
        )

    labors_out: list[OwnProductLaborOut] = []
    labor_rows = list(p.labors or [])
    process_ids = [x.process_id for x in labor_rows if x.process_id]
    process_map: dict[int, ProcessDefinition] = {}
    if process_ids:
        process_map = {
            x.id: x
            for x in db.scalars(select(ProcessDefinition).where(ProcessDefinition.id.in_(process_ids))).all()
        }
    for row in labor_rows:
        labors_out.append(_labor_out(row, process_map.get(row.process_id)))

    parts_out: list[OwnProductPartOut] = []
    part_rows = list(p.parts or [])
    part_ids = [x.part_id for x in part_rows]
    part_map: dict[int, PartDefinition] = {}
    if part_ids:
        part_map = {
            x.id: x
            for x in db.scalars(select(PartDefinition).where(PartDefinition.id.in_(part_ids))).all()
        }
    for row in sorted(part_rows, key=lambda x: (x.sort_order, x.id)):
        parts_out.append(_part_row_out(row, part_map.get(row.part_id)))

    other_costs_out = [
        OwnProductOtherCostOut(
            id=row.id,
            name=row.name,
            amount=row.amount,
            sort_order=row.sort_order,
        )
        for row in sorted(p.other_costs or [], key=lambda x: (x.sort_order, x.id))
    ]

    quotes_out: list[OwnProductQuoteOut] = []
    quote_rows = list(p.quotes or [])
    quote_partner_ids = [x.partner_id for x in quote_rows]
    quote_partner_map: dict[int, Partner] = {}
    if quote_partner_ids:
        quote_partner_map = {
            x.id: x
            for x in db.scalars(select(Partner).where(Partner.id.in_(quote_partner_ids))).all()
        }
    for row in quote_rows:
        quotes_out.append(_quote_out(row, quote_partner_map.get(row.partner_id)))

    out = OwnProductOut(
        id=p.id,
        product_code=p.product_code,
        image_url=p.image_url,
        fabric=getattr(p, "fabric", None),
        lining=getattr(p, "lining", None),
        color_ids=color_ids,
        colors=colors,
        parts=parts_out,
        materials=materials_out,
        labors=labors_out,
        quotes=quotes_out,
        other_costs=other_costs_out,
        material_cost=p.material_cost or Decimal("0"),
        labor_cost=p.labor_cost or Decimal("0"),
        other_cost=p.other_cost or Decimal("0"),
        quote_price=p.quote_price,
        order_qty=int(getattr(p, "order_qty", 0) or 0),
        is_active=bool(p.is_active),
        trace_enabled=bool(getattr(p, "trace_enabled", False)),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
    return out.model_dump(mode="json")


def _get_product(db: Session, tenant_id: int, product_id: int) -> OwnProduct:
    p = db.scalar(
        select(OwnProduct)
        .where(OwnProduct.id == product_id, OwnProduct.tenant_id == tenant_id)
        .options(
            selectinload(OwnProduct.colors),
            selectinload(OwnProduct.parts),
            selectinload(OwnProduct.materials),
            selectinload(OwnProduct.labors),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
        )
    )
    if not p:
        raise HTTPException(status_code=404, detail="产品不存在")
    return p


def _ensure_colors(db: Session, tenant_id: int, color_ids: list[int]) -> None:
    if not color_ids:
        raise HTTPException(
            status_code=400,
            detail="请选择成品颜色。一色一款：每个货号绑一个颜色；同楦不同色请另建货号",
        )
    rows = db.scalars(
        select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids))
    ).all()
    if len(rows) != len(set(color_ids)):
        raise HTTPException(status_code=400, detail="存在无效颜色")


def _replace_colors(db: Session, product: OwnProduct, color_ids: list[int]) -> None:
    product.colors.clear()
    db.flush()
    for cid in color_ids:
        product.colors.append(
            OwnProductColor(tenant_id=product.tenant_id, own_product_id=product.id, color_id=cid)
        )


def _replace_materials(
    db: Session,
    product: OwnProduct,
    materials: list[OwnProductMaterialIn],
) -> Decimal:
    product.materials.clear()
    db.flush()
    total = Decimal("0")
    for i, row in enumerate(materials):
        sp = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.id == row.supplier_product_id,
                SupplierProduct.tenant_id == product.tenant_id,
            )
        )
        if not sp:
            raise HTTPException(status_code=400, detail=f"供应商产品不存在: {row.supplier_product_id}")
        qty = Decimal(row.qty or 0)
        if qty < 0:
            raise HTTPException(status_code=400, detail="用量不能为负")
        consume_pid = row.consume_process_id
        if consume_pid is not None:
            proc = db.get(ProcessDefinition, consume_pid)
            if not proc or proc.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="消耗工序不存在")
        usage_by_size = bool(getattr(row, "usage_by_size", False))
        size_table_id = getattr(row, "size_usage_table_id", None)
        if usage_by_size:
            if not size_table_id:
                raise HTTPException(status_code=400, detail="按码用量须选择用量码表")
            table = db.get(MaterialSizeUsageTable, size_table_id)
            if not table or table.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="用量码表不存在")
        else:
            size_table_id = None
        loss_rate = Decimal(getattr(row, "loss_rate", None) or 0)
        loss_fixed = Decimal(getattr(row, "loss_fixed_qty", None) or 0)
        if loss_rate < 0 or loss_fixed < 0:
            raise HTTPException(status_code=400, detail="损耗不能为负")
        bom_color_id = getattr(row, "color_id", None)
        if bom_color_id is not None:
            allowed = {c.color_id for c in (product.colors or [])}
            if int(bom_color_id) not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail="物料配色须为本款已绑颜色，或留空表示整款共用",
                )
        unit_price = Decimal(sp.unit_price or 0)
        line = _line_total(qty, unit_price)
        total += line
        product.materials.append(
            OwnProductMaterial(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                supplier_product_id=sp.id,
                qty=qty,
                unit_price=unit_price,
                line_total=line,
                sort_order=row.sort_order if row.sort_order else i,
                consume_process_id=consume_pid,
                usage_by_size=usage_by_size,
                size_usage_table_id=size_table_id,
                loss_rate=loss_rate,
                loss_fixed_qty=loss_fixed,
                color_id=int(bom_color_id) if bom_color_id is not None else None,
            )
        )
    return total.quantize(Decimal("0.0001"))


def _parse_process_type(raw: str | None) -> ProcessType:
    value = (raw or "personal").strip().lower()
    if value == ProcessType.group.value:
        return ProcessType.group
    return ProcessType.personal


def _ensure_process_by_name(
    db: Session,
    tenant_id: int,
    name: str,
    *,
    process_type: str | None = None,
) -> ProcessDefinition:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写工序名称")
    wanted = _parse_process_type(process_type)
    existing = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.name == name,
        )
    )
    if existing:
        if not existing.is_active:
            existing.is_active = True
        # 产品侧选择的类型同步到工序主数据（个人/集体影响报工）
        old_type = (
            existing.type
            if isinstance(existing.type, ProcessType)
            else ProcessType(str(existing.type))
        )
        if old_type != wanted:
            from app.models import OrderProcess, OrderProcessStatus

            open_ref = db.scalar(
                select(OrderProcess.id)
                .where(
                    OrderProcess.tenant_id == tenant_id,
                    OrderProcess.process_id == existing.id,
                    OrderProcess.status.in_(
                        (OrderProcessStatus.pending, OrderProcessStatus.in_progress)
                    ),
                )
                .limit(1)
            )
            if open_ref:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"工序「{name}」仍有在制订单，不能改为"
                        f"{'集体' if wanted == ProcessType.group else '个人'}；"
                        f"请先在工序管理或待订单完工后再改"
                    ),
                )
            existing.type = wanted
        return existing
    code = f"P{uuid.uuid4().hex[:10].upper()}"
    while db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.code == code,
        )
    ):
        code = f"P{uuid.uuid4().hex[:10].upper()}"
    process = ProcessDefinition(
        tenant_id=tenant_id,
        name=name,
        code=code,
        type=wanted,
        default_price=Decimal("0"),
        sort_order=0,
        is_active=True,
    )
    db.add(process)
    db.flush()
    return process


def _replace_parts(
    db: Session,
    product: OwnProduct,
    parts: list[OwnProductPartIn],
) -> None:
    seen: set[int] = set()
    planned: list[OwnProductPartIn] = []
    for i, row in enumerate(parts):
        pid = int(row.part_id)
        if pid in seen:
            raise HTTPException(status_code=400, detail="产品部件重复")
        seen.add(pid)
        part = db.get(PartDefinition, pid)
        if not part or part.tenant_id != product.tenant_id or not part.is_active:
            raise HTTPException(status_code=400, detail=f"部件无效或不存在: {pid}")
        pieces = int(row.pieces_per_pair or 1)
        if pieces <= 0:
            raise HTTPException(status_code=400, detail="每双件数须为正整数")
        planned.append(row)

    product.parts.clear()
    db.flush()
    for i, row in enumerate(planned):
        product.parts.append(
            OwnProductPart(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                part_id=row.part_id,
                pieces_per_pair=int(row.pieces_per_pair or 1),
                sort_order=row.sort_order if row.sort_order else i,
                source_supplier_product_id=row.source_supplier_product_id,
            )
        )


def _replace_labors(
    db: Session,
    product: OwnProduct,
    labors: list[OwnProductLaborIn],
) -> Decimal:
    from app.models import Order, OrderProcess, OrderProcessAssignment, WorkLog

    old_by_pid = {l.process_id: l for l in list(product.labors) if l.process_id}
    product_part_ids = {p.part_id for p in (product.parts or [])}
    # 先解析新清单（会 ensure 工序），再校验删除
    planned: list[tuple[ProcessDefinition, OwnProductLaborIn, Decimal]] = []
    seen: set[str] = set()
    kit_count = 0
    for i, row in enumerate(labors):
        name = (row.process_name or "").strip()
        part_id = getattr(row, "part_id", None)
        key = f"{part_id or 0}:{name.lower()}"
        if not name:
            raise HTTPException(status_code=400, detail="请填写工序名称")
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"同一部件下工序「{name}」重复" if part_id else f"整鞋工序「{name}」重复",
            )
        seen.add(key)
        if part_id is not None and part_id not in product_part_ids:
            raise HTTPException(status_code=400, detail=f"工序绑定的部件不在产品部件清单中: {part_id}")
        if bool(getattr(row, "is_kit_checkpoint", False)):
            kit_count += 1
            if part_id is not None:
                raise HTTPException(status_code=400, detail="齐套检查点须落在整鞋段工序")
        process = _ensure_process_by_name(
            db,
            product.tenant_id,
            name,
            process_type=getattr(row, "process_type", None),
        )
        unit_price = Decimal(row.unit_price or 0)
        if unit_price < 0:
            raise HTTPException(status_code=400, detail="工序价格不能为负")
        planned.append((process, row, unit_price))

    if kit_count > 1:
        raise HTTPException(status_code=400, detail="齐套检查点最多只能勾选一个")

    keep_pids = {p.id for p, _, _ in planned}
    removed = [pid for pid in old_by_pid if pid not in keep_pids]
    for pid in removed:
        old = old_by_pid[pid]
        has_log = db.scalar(
            select(WorkLog.id)
            .where(
                WorkLog.tenant_id == product.tenant_id,
                WorkLog.own_product_id == product.id,
                WorkLog.process_id == pid,
            )
            .limit(1)
        )
        if has_log:
            raise HTTPException(
                status_code=400,
                detail=f"工序「{old.process_name or pid}」已有报工，不能从本产品删除",
            )
        has_assign = db.scalar(
            select(OrderProcessAssignment.id)
            .join(OrderProcess, OrderProcess.id == OrderProcessAssignment.order_process_id)
            .join(Order, Order.id == OrderProcess.order_id)
            .where(
                Order.tenant_id == product.tenant_id,
                Order.own_product_id == product.id,
                OrderProcess.process_id == pid,
            )
            .limit(1)
        )
        if has_assign:
            raise HTTPException(
                status_code=400,
                detail=f"工序「{old.process_name or pid}」已有派工，不能从本产品删除",
            )

    product.labors.clear()
    db.flush()
    total = Decimal("0")
    for i, (process, row, unit_price) in enumerate(planned):
        total += unit_price
        product.labors.append(
            OwnProductLabor(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                part_id=getattr(row, "part_id", None),
                process_id=process.id,
                process_name=(row.process_name or "").strip(),
                unit_price=unit_price,
                sort_order=row.sort_order if row.sort_order else i,
                is_kit_checkpoint=bool(getattr(row, "is_kit_checkpoint", False)),
            )
        )
    return total.quantize(Decimal("0.0001"))


def _sync_labors_to_open_orders(db: Session, product: OwnProduct) -> dict:
    """把产品工序同步到 confirmed/in_progress 生产单与无壳执行单。

    - 已有同 process_id：更新名称/类型
    - 产品新增：追加 OrderProcess（plan_qty=总量）
    - 产品删除：仅当无报工、无派工时移除
    单价不落订单（报工时仍读产品价）。
    """
    from app.models import (
        ExecutionHeader,
        Order,
        OrderProcess,
        OrderProcessAssignment,
        OrderProcessStatus,
        OrderStatus,
        ProcessDefinition,
        SpecExecutionStatus,
        WorkLog,
    )

    labor_by_key = {
        (l.process_id, getattr(l, "part_id", None)): l for l in product.labors if l.process_id
    }
    process_defs = {
        p.id: p
        for p in db.scalars(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == product.tenant_id,
                ProcessDefinition.id.in_({k[0] for k in labor_by_key} or {0}),
            )
        ).all()
    }
    added = 0
    updated = 0
    removed = 0
    skipped_remove = 0

    def _sync_existing(existing: list, *, order_id: int | None, header_id: int | None, plan_qty: int):
        nonlocal added, updated, removed, skipped_remove
        by_key = {(op.process_id, getattr(op, "part_id", None)): op for op in existing}
        for key, labor in labor_by_key.items():
            pid, part_id = key
            pdef = process_defs.get(pid)
            ptype = pdef.type if pdef else ProcessType.personal
            if key in by_key:
                op = by_key[key]
                op.process_name = labor.process_name or op.process_name
                op.process_type = ptype
                op.part_id = part_id
                if header_id and not op.header_id:
                    op.header_id = header_id
                updated += 1
            else:
                db.add(
                    OrderProcess(
                        tenant_id=product.tenant_id,
                        order_id=order_id,
                        header_id=header_id,
                        process_id=pid,
                        process_name=labor.process_name or (pdef.name if pdef else str(pid)),
                        process_type=ptype,
                        part_id=part_id,
                        plan_qty=plan_qty,
                        status=OrderProcessStatus.pending,
                    )
                )
                added += 1
        keep = set(labor_by_key.keys())
        for op in existing:
            if (op.process_id, getattr(op, "part_id", None)) in keep:
                continue
            has_log = db.scalar(
                select(WorkLog.id)
                .where(
                    WorkLog.tenant_id == product.tenant_id,
                    WorkLog.order_process_id == op.id,
                )
                .limit(1)
            )
            has_assign = db.scalar(
                select(OrderProcessAssignment.id)
                .where(OrderProcessAssignment.order_process_id == op.id)
                .limit(1)
            )
            if has_log or has_assign or op.completed_qty or op.rework_qty:
                skipped_remove += 1
                continue
            db.delete(op)
            removed += 1

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == product.tenant_id,
                Order.own_product_id == product.id,
                Order.status.in_((OrderStatus.confirmed, OrderStatus.in_progress)),
            )
        ).all()
    )
    for order in orders:
        existing = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == product.tenant_id,
                    OrderProcess.order_id == order.id,
                )
            ).all()
        )
        _sync_existing(
            existing,
            order_id=order.id,
            header_id=getattr(existing[0], "header_id", None) if existing else None,
            plan_qty=int(order.total_qty or 0),
        )

    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == product.tenant_id,
                ExecutionHeader.own_product_id == product.id,
                ExecutionHeader.shop_order_id.is_(None),
                ExecutionHeader.status.in_(
                    (SpecExecutionStatus.confirmed, SpecExecutionStatus.cut, SpecExecutionStatus.in_progress)
                ),
            )
        ).all()
    )
    for header in headers:
        existing = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == product.tenant_id,
                    OrderProcess.header_id == header.id,
                )
            ).all()
        )
        _sync_existing(
            existing,
            order_id=None,
            header_id=header.id,
            plan_qty=int(header.total_qty or 0),
        )

    db.flush()
    return {
        "orders": len(orders),
        "headers": len(headers),
        "added": added,
        "updated": updated,
        "removed": removed,
        "skipped_remove": skipped_remove,
    }


def _ensure_other_cost_item_by_name(db: Session, tenant_id: int, name: str) -> OtherCostItem:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写其它成本项目")
    existing = db.scalar(
        select(OtherCostItem).where(
            OtherCostItem.tenant_id == tenant_id,
            OtherCostItem.name == name,
        )
    )
    if existing:
        if not existing.is_active:
            existing.is_active = True
        return existing
    item = OtherCostItem(
        tenant_id=tenant_id,
        name=name,
        sort_order=0,
        is_active=True,
    )
    db.add(item)
    db.flush()
    return item


def _replace_other_costs(
    db: Session,
    product: OwnProduct,
    other_costs: list[OwnProductOtherCostIn],
) -> Decimal:
    product.other_costs.clear()
    db.flush()
    total = Decimal("0")
    seen: set[str] = set()
    for i, row in enumerate(other_costs):
        name = (row.name or "").strip()
        key = name.lower()
        if not name:
            raise HTTPException(status_code=400, detail="请填写其它成本项目")
        if key in seen:
            raise HTTPException(status_code=400, detail=f"其它成本「{name}」重复")
        seen.add(key)
        amount = Decimal(row.amount or 0)
        if amount < 0:
            raise HTTPException(status_code=400, detail="其它成本金额不能为负")
        _ensure_other_cost_item_by_name(db, product.tenant_id, name)
        total += amount
        product.other_costs.append(
            OwnProductOtherCost(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                name=name,
                amount=amount,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )
    return total.quantize(Decimal("0.0001"))


def _replace_quotes(
    db: Session,
    product: OwnProduct,
    quotes: list[OwnProductQuoteIn],
) -> None:
    product.quotes.clear()
    db.flush()
    seen: set[int] = set()
    for i, row in enumerate(quotes):
        if row.partner_id in seen:
            raise HTTPException(status_code=400, detail="同一客户不能重复报价")
        seen.add(row.partner_id)
        partner = db.scalar(
            select(Partner).where(
                Partner.id == row.partner_id,
                Partner.tenant_id == product.tenant_id,
            )
        )
        if not partner:
            raise HTTPException(status_code=400, detail=f"客户不存在: {row.partner_id}")
        if not (partner.is_customer or partner.is_brand):
            raise HTTPException(status_code=400, detail=f"「{partner.name}」不是客户/品牌方")
        price = Decimal(row.quote_price or 0)
        if price < 0:
            raise HTTPException(status_code=400, detail="报价不能为负")
        product.quotes.append(
            OwnProductQuote(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                partner_id=partner.id,
                quote_price=price,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )


@router.get("")
def list_own_products(
    keyword: str | None = Query(None),
    active_only: bool = Query(False),
    sort_by: str = Query("date", description="date | order_qty"),
    sort_order: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page, page_size, offset = normalize_page(page, page_size)
    q = select(OwnProduct).where(OwnProduct.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(OwnProduct.is_active.is_(True))
    if keyword and keyword.strip():
        q = q.where(OwnProduct.product_code.ilike(f"%{keyword.strip()}%"))

    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0

    sort_col = OwnProduct.order_qty if sort_by == "order_qty" else OwnProduct.created_at
    order_expr = sort_col.asc() if sort_order == "asc" else sort_col.desc()

    rows = db.scalars(
        q.options(
            selectinload(OwnProduct.colors),
            selectinload(OwnProduct.parts),
            selectinload(OwnProduct.materials),
            selectinload(OwnProduct.labors),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
        )
        .order_by(order_expr, OwnProduct.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    items = [_product_out(p, db) for p in rows]
    return ok(page_payload(items, int(total), page, page_size))


@router.post("/batch-quote/export")
def export_batch_quote(
    body: OwnProductBatchQuoteExportIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.services.own_product_export import build_batch_quote_workbook

    ids = list(dict.fromkeys(int(i) for i in body.product_ids))
    if not ids:
        raise HTTPException(status_code=400, detail="请选择产品")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="单次最多导出 200 款产品")

    customer_name: str | None = None
    if body.partner_id is not None:
        partner = db.scalar(
            select(Partner).where(
                Partner.id == body.partner_id,
                Partner.tenant_id == user.tenant_id,
            )
        )
        if not partner or not (partner.is_customer or partner.is_brand):
            raise HTTPException(status_code=400, detail="客户不存在")
        customer_name = (partner.short_name or partner.name or "").strip() or None

    rows = db.scalars(
        select(OwnProduct)
        .where(
            OwnProduct.tenant_id == user.tenant_id,
            OwnProduct.id.in_(ids),
        )
        .options(
            selectinload(OwnProduct.colors),
            selectinload(OwnProduct.parts),
            selectinload(OwnProduct.materials),
            selectinload(OwnProduct.labors),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
        )
    ).all()
    by_id = {p.id: p for p in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HTTPException(status_code=400, detail=f"产品不存在: {missing[:5]}")

    items = [_product_out(by_id[i], db) for i in ids]
    tenant = db.scalar(select(Tenant).where(Tenant.id == user.tenant_id))
    company_name = (tenant.name if tenant else "") or None
    content = build_batch_quote_workbook(
        items,
        partner_id=body.partner_id,
        customer_name=customer_name,
        company_name=company_name,
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    label = customer_name or "统一报价"
    filename = f"产品报价单_{label}_{stamp}.xlsx"
    ascii_name = f"batch_quote_{stamp}.xlsx"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/{product_id}/export")
def export_own_product(
    product_id: int,
    partner_id: int | None = Query(None, description="已废弃，成本明细不再含报价"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.services.own_product_export import build_own_product_workbook

    p = _get_product(db, user.tenant_id, product_id)
    item = _product_out(p, db)
    content = build_own_product_workbook(item)
    code = (p.product_code or str(product_id)).strip()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"产品成本明细_{code}_{stamp}.xlsx"
    ascii_name = f"own_product_{product_id}_{stamp}.xlsx"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("")
def create_own_product(
    body: OwnProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    code = body.product_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写产品编号")
    exists = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == user.tenant_id, OwnProduct.product_code == code)
    )
    if exists:
        raise HTTPException(status_code=400, detail="产品编号已存在")
    _ensure_colors(db, user.tenant_id, body.color_ids)
    p = OwnProduct(
        tenant_id=user.tenant_id,
        product_code=code,
        image_url=(body.image_url or "").strip() or None,
        fabric=(body.fabric or "").strip() or None,
        lining=(body.lining or "").strip() or None,
        is_active=body.is_active,
        trace_enabled=bool(body.trace_enabled),
        material_cost=Decimal("0"),
        quote_price=Decimal(body.quote_price) if body.quote_price is not None else None,
        order_qty=max(0, int(body.order_qty or 0)),
        labor_cost=Decimal("0"),
        other_cost=Decimal("0"),
    )
    if p.quote_price is not None and p.quote_price < 0:
        raise HTTPException(status_code=400, detail="统一报价不能为负")
    db.add(p)
    db.flush()
    _replace_colors(db, p, body.color_ids)
    _replace_parts(db, p, list(body.parts or []))
    p.material_cost = _replace_materials(db, p, body.materials)
    p.labor_cost = _replace_labors(db, p, body.labors)
    p.other_cost = _replace_other_costs(db, p, body.other_costs)
    _replace_quotes(db, p, body.quotes)
    db.commit()
    p = _get_product(db, user.tenant_id, p.id)
    return ok(_product_out(p, db))


@router.get("/{product_id}/peer-actuals")
def get_own_product_peer_actuals(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A1c：批价旁同款出货实绩（只读，不阻断报价）。"""
    from app.services.peer_actuals_service import PeerActualsError, peer_actuals_for_product

    try:
        return ok(peer_actuals_for_product(db, user.tenant_id, product_id))
    except PeerActualsError as e:
        raise HTTPException(status_code=404 if e.code == "product_not_found" else 400, detail=e.message)


@router.get("/{product_id}")
def get_own_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = _get_product(db, user.tenant_id, product_id)
    return ok(_product_out(p, db))


@router.patch("/{product_id}")
def update_own_product(
    product_id: int,
    body: OwnProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = _get_product(db, user.tenant_id, product_id)
    data = body.model_dump(exclude_unset=True)
    if "product_code" in data:
        code = (data["product_code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="请填写产品编号")
        dup = db.scalar(
            select(OwnProduct).where(
                OwnProduct.tenant_id == user.tenant_id,
                OwnProduct.product_code == code,
                OwnProduct.id != product_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="产品编号已存在")
        p.product_code = code
    if "image_url" in data:
        p.image_url = (data["image_url"] or "").strip() or None
    if "fabric" in data:
        p.fabric = (data["fabric"] or "").strip() or None
    if "lining" in data:
        p.lining = (data["lining"] or "").strip() or None
    if "is_active" in data and data["is_active"] is not None:
        p.is_active = bool(data["is_active"])
    if "trace_enabled" in data and data["trace_enabled"] is not None:
        p.trace_enabled = bool(data["trace_enabled"])
    if "quote_price" in data:
        if data["quote_price"] is None:
            p.quote_price = None
        else:
            qp = Decimal(data["quote_price"])
            if qp < 0:
                raise HTTPException(status_code=400, detail="统一报价不能为负")
            p.quote_price = qp
    if "order_qty" in data and data["order_qty"] is not None:
        qty = int(data["order_qty"])
        if qty < 0:
            raise HTTPException(status_code=400, detail="订单量不能为负")
        p.order_qty = qty
    if "color_ids" in data and data["color_ids"] is not None:
        _ensure_colors(db, user.tenant_id, data["color_ids"])
        _replace_colors(db, p, data["color_ids"])
    if "parts" in data and data["parts"] is not None:
        _replace_parts(db, p, list(body.parts or []))
    if "materials" in data and data["materials"] is not None:
        p.material_cost = _replace_materials(db, p, list(body.materials or []))
    if "labors" in data and data["labors"] is not None:
        # 若同请求也改了 parts，先 flush 保证 labors 校验能看到新部件清单
        if "parts" in data and data["parts"] is not None:
            db.flush()
        p.labor_cost = _replace_labors(db, p, list(body.labors or []))
        if bool(getattr(body, "sync_labors_to_open_orders", False)):
            _sync_labors_to_open_orders(db, p)
    if "other_costs" in data and data["other_costs"] is not None:
        p.other_cost = _replace_other_costs(db, p, list(body.other_costs or []))
    if "quotes" in data and data["quotes"] is not None:
        _replace_quotes(db, p, list(body.quotes or []))
    db.commit()
    p = _get_product(db, user.tenant_id, product_id)
    return ok(_product_out(p, db))


def _own_product_delete_blockers(db: Session, tenant_id: int, product_id: int) -> list[str]:
    from app.models import Order, SalesOrderLine, TraceUnit, WorkLog

    checks = [
        ("生产订单", select(Order.id).where(
            Order.tenant_id == tenant_id, Order.own_product_id == product_id
        ).limit(1)),
        ("销售订单", select(SalesOrderLine.id).where(
            SalesOrderLine.tenant_id == tenant_id, SalesOrderLine.own_product_id == product_id
        ).limit(1)),
        ("报工记录", select(WorkLog.id).where(
            WorkLog.tenant_id == tenant_id, WorkLog.own_product_id == product_id
        ).limit(1)),
        ("捆标", select(TraceUnit.id).where(
            TraceUnit.tenant_id == tenant_id, TraceUnit.own_product_id == product_id
        ).limit(1)),
    ]
    blockers: list[str] = []
    for label, stmt in checks:
        if db.scalar(stmt):
            blockers.append(label)
    return blockers


@router.delete("/{product_id}")
def delete_own_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = _get_product(db, user.tenant_id, product_id)
    blockers = _own_product_delete_blockers(db, user.tenant_id, product_id)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"产品「{p.product_code}」仍被引用（{'、'.join(blockers)}），"
                "无法删除。可先停用该产品，或清理相关订单/报工后再删"
            ),
        )
    db.delete(p)
    db.commit()
    return ok({"deleted": True, "id": product_id})
