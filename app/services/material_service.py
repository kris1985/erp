"""订单用料快照、齐套、发车间、公用库存。"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    ExecutionHeader,
    MaterialCategory,
    MaterialSizeUsageCoeff,
    MaterialSizeUsageTable,
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessAssignment,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    PricingUnit,
    ProcessDefinition,
    ProcessSegment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SalesBizMode,
    SalesOrder,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    Size,
    SpecExecutionStatus,
    SupplierProduct,
    MaterialRelease,
)

from app.services.segment_service import ensure_default_segments

# 池/库存键：(supplier_product_id, size_id)；未按码 size_id=None


def sales_order_biz_mode(db: Session, sales_order_id: int | None) -> SalesBizMode | None:
    """B1d：读取销售单业务形态；空=未知（按自产处理）。"""
    if not sales_order_id:
        return None
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return None
    bm = getattr(so, "biz_mode", None)
    if bm is None:
        return None
    if hasattr(bm, "value"):
        return SalesBizMode(bm.value)
    return SalesBizMode(str(bm))


def is_subcontract_in_sales_order(db: Session, sales_order_id: int | None) -> bool:
    return sales_order_biz_mode(db, sales_order_id) == SalesBizMode.subcontract_in


def mark_requirements_customer_supplied(rows: list[OrderMaterialRequirement]) -> None:
    """B1d：承接外包用料全标客供（上家供料）。"""
    for row in rows:
        row.is_customer_supplied = True
        if (getattr(row, "customer_chase_status", None) or "") not in (
            "open",
            "chased",
            "cleared",
        ):
            row.customer_chase_status = "open"


def filter_bom_for_colorway(materials, color_id: int | None):
    """BOM 按配色展开：空色（整款共用）∪ 本色。

    color_id 为空时保留全部行，兼容未记下配色的旧单。
    """
    rows = list(materials)
    if color_id is None:
        return rows
    cid = int(color_id)
    return [
        m
        for m in rows
        if getattr(m, "color_id", None) is None or int(m.color_id) == cid
    ]


def colorway_id_from_order(db: Session, order: Order) -> int | None:
    """生产单配色：色码明细若只含一种色则用之，否则空（全行展开）。"""
    items = list(getattr(order, "items", None) or [])
    if not items:
        items = list(
            db.scalars(
                select(OrderItem).where(
                    OrderItem.tenant_id == order.tenant_id,
                    OrderItem.order_id == order.id,
                )
            ).all()
        )
    ids = {int(it.color_id) for it in items if it.color_id is not None}
    if len(ids) == 1:
        return next(iter(ids))
    return None
PoolKey = tuple[int, int | None]

ORDERED_PO_STATUSES = {
    PurchaseOrderStatus.ordered,
    PurchaseOrderStatus.shipped,
    PurchaseOrderStatus.partial_received,
    PurchaseOrderStatus.received,
}


class MaterialError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def calc_required_qty(
    qty_per_pair: Decimal,
    total_qty: int,
    loss_rate: Decimal,
    loss_fixed_qty: Decimal = Decimal("0"),
) -> Decimal:
    """未按码：单耗 × 总双 × (1+%) + 固定损耗。"""
    base = qty_per_pair * Decimal(total_qty) * (Decimal("1") + (loss_rate or Decimal("0")))
    return (base + (loss_fixed_qty or Decimal("0"))).quantize(Decimal("0.0001"))


def calc_required_qty_sized(
    qty_per_pair: Decimal,
    size_qty: int,
    size_coeff: Decimal,
    loss_rate: Decimal,
    loss_fixed_qty: Decimal = Decimal("0"),
) -> Decimal:
    """按码：单耗 × 该码双数 × 系数 × (1+%) + 固定损耗（展开时仅首码行带固定量）。"""
    base = (
        qty_per_pair
        * Decimal(size_qty)
        * (size_coeff or Decimal("1"))
        * (Decimal("1") + (loss_rate or Decimal("0")))
    )
    return (base + (loss_fixed_qty or Decimal("0"))).quantize(Decimal("0.0001"))


def _pool_key(supplier_product_id: int, size_id: int | None) -> PoolKey:
    return (int(supplier_product_id), int(size_id) if size_id is not None else None)


def _req_pool_key(row: OrderMaterialRequirement) -> PoolKey:
    size_id = row.size_id if getattr(row, "usage_by_size", False) else None
    return _pool_key(row.supplier_product_id, size_id)


def _req_match_key(supplier_product_id: int, size_id: int | None) -> PoolKey:
    return _pool_key(supplier_product_id, size_id)


def order_size_qty_map(order: Order, db: Session | None = None) -> dict[int, int]:
    """生产单按 size_id 汇总双数（多色同码合并）。"""
    items = list(getattr(order, "items", None) or [])
    if not items and db is not None and order.id:
        items = list(
            db.scalars(
                select(OrderItem).where(
                    OrderItem.tenant_id == order.tenant_id,
                    OrderItem.order_id == order.id,
                )
            ).all()
        )
    out: dict[int, int] = {}
    for it in items:
        if not it.size_id:
            continue
        out[int(it.size_id)] = out.get(int(it.size_id), 0) + int(it.qty or 0)
    return out


def load_size_coeff_map(
    db: Session, tenant_id: int, table_id: int
) -> dict[int, Decimal]:
    rows = db.scalars(
        select(MaterialSizeUsageCoeff).where(
            MaterialSizeUsageCoeff.tenant_id == tenant_id,
            MaterialSizeUsageCoeff.table_id == table_id,
        )
    ).all()
    return {int(r.size_id): Decimal(str(r.coeff or 1)) for r in rows}


def size_labels(db: Session, size_ids: set[int] | list[int]) -> dict[int, str]:
    ids = [int(x) for x in size_ids if x]
    if not ids:
        return {}
    return {
        s.id: s.size_value
        for s in db.scalars(select(Size).where(Size.id.in_(ids))).all()
    }


DEFAULT_SIZE_USAGE_TABLE_NAME = "大底通用"
# 需要「建议按码」并默认挂「大底通用」的分类（BOM 行仍可改）
# 包装/内里/面料等不挂；旧名兼容拆分前数据
DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES = frozenset(
    {"大底", "中底", "鞋垫", "鞋底中底", "鞋垫内里"}
)
# 80% 鞋厂默认分类 → 消耗工序（BOM 可覆盖；仅在分类未设置时写入）
# 旧名保留映射，避免历史数据补工序时落空
DEFAULT_CATEGORY_CONSUME_PROCESS: dict[str, str] = {
    "皮料": "裁断",
    "面料网布": "裁断",
    "超纤革": "裁断",
    "内里": "裁断",
    "鞋垫": "成型",
    "大底": "成型",
    "中底": "成型",
    "泡棉海绵": "裁断",
    "五金扣": "针车",
    "拉链": "针车",
    "线材": "针车",
    "补强胶膜": "裁断",
    "胶水化工": "成型",
    "鞋带魔术贴": "成型",
    "装饰件": "成型",
    "包装材料": "包装",
    "模具楦头": "成型",
    "其他辅料": "成型",
    # 兼容旧种子名
    "鞋底中底": "成型",
    "鞋垫内里": "成型",
}
DEFAULT_CATEGORY_CONSUME_FALLBACK = "成型"

# 基础资料「导入常用分类」用的默认清单（约覆盖 80% 中小鞋厂）
DEFAULT_MATERIAL_CATEGORIES: list[str] = [
    "皮料",
    "面料网布",
    "超纤革",
    "内里",
    "鞋垫",
    "大底",
    "中底",
    "泡棉海绵",
    "五金扣",
    "拉链",
    "线材",
    "补强胶膜",
    "胶水化工",
    "鞋带魔术贴",
    "装饰件",
    "包装材料",
    "模具楦头",
    "其他辅料",
]

# 旧合并名 → (就地改名目标, 另需新建的半边)
_LEGACY_CATEGORY_SPLITS: list[tuple[str, str, str]] = [
    ("鞋底中底", "大底", "中底"),
    ("鞋垫内里", "鞋垫", "内里"),
]


def split_legacy_material_categories(db: Session, tenant_id: int) -> dict[str, int]:
    """把旧合并分类拆开：就地改名 + 补另一半。返回 {renamed, created, deactivated}。"""
    by_name = {
        c.name: c
        for c in db.scalars(
            select(MaterialCategory).where(MaterialCategory.tenant_id == tenant_id)
        ).all()
    }
    renamed = 0
    created = 0
    deactivated = 0
    max_sort = max((c.sort_order for c in by_name.values()), default=-1)

    def _product_count(category_id: int) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(SupplierProduct)
                .where(
                    SupplierProduct.tenant_id == tenant_id,
                    SupplierProduct.category_id == category_id,
                )
            )
            or 0
        )

    for old_name, rename_to, sibling in _LEGACY_CATEGORY_SPLITS:
        old = by_name.get(old_name)
        if old:
            target = by_name.get(rename_to)
            if not target:
                old.name = rename_to
                by_name[rename_to] = old
                by_name.pop(old_name, None)
                renamed += 1
            elif target.id != old.id:
                # 目标名已被空壳占用时：删空壳，旧类就地改名（保留已挂物料）
                if _product_count(target.id) == 0:
                    db.delete(target)
                    db.flush()
                    by_name.pop(rename_to, None)
                    old.name = rename_to
                    by_name[rename_to] = old
                    by_name.pop(old_name, None)
                    renamed += 1
                elif old.is_active:
                    old.is_active = False
                    deactivated += 1
        if sibling not in by_name:
            max_sort += 1
            row = MaterialCategory(
                tenant_id=tenant_id,
                name=sibling,
                sort_order=max_sort,
                is_active=True,
            )
            db.add(row)
            db.flush()
            by_name[sibling] = row
            created += 1

    if renamed or created or deactivated:
        db.flush()
    return {"renamed": renamed, "created": created, "deactivated": deactivated}


def ensure_default_category_consume_processes(db: Session, tenant_id: int) -> int:
    """给未设置默认消耗工序的分类补上常用映射（不覆盖已有值）。返回更新条数。"""
    procs = {
        p.name: p
        for p in db.scalars(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == tenant_id,
                ProcessDefinition.is_active.is_(True),
            )
        ).all()
    }
    if not procs:
        return 0
    fallback = procs.get(DEFAULT_CATEGORY_CONSUME_FALLBACK) or next(
        (
            p
            for p in db.scalars(
                select(ProcessDefinition)
                .where(ProcessDefinition.tenant_id == tenant_id)
                .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
            ).all()
        ),
        None,
    )
    if not fallback:
        return 0

    updated = 0
    cats = db.scalars(
        select(MaterialCategory).where(MaterialCategory.tenant_id == tenant_id)
    ).all()
    for cat in cats:
        if cat.default_consume_process_id:
            continue
        want = DEFAULT_CATEGORY_CONSUME_PROCESS.get(cat.name)
        proc = procs.get(want) if want else None
        if not proc:
            proc = fallback
        cat.default_consume_process_id = proc.id
        updated += 1
    if updated:
        db.flush()
    return updated


def ensure_default_category_consume_segments(db: Session, tenant_id: int) -> int:
    """给未设置默认消耗段的分类补上常用映射（不覆盖已有值）。返回更新条数。

    工序段重构 4.4：段为主键；旧工序字段两期过渡保留（D20）。
    映射沿用 DEFAULT_CATEGORY_CONSUME_PROCESS（分类→工序名），取其工序归属段。
    """
    ensure_default_segments(db, tenant_id)
    fallback = db.scalar(
        select(ProcessSegment)
        .where(ProcessSegment.tenant_id == tenant_id)
        .order_by(ProcessSegment.sort_order, ProcessSegment.id)
    )
    if not fallback:
        return 0

    updated = 0
    cats = db.scalars(
        select(MaterialCategory).where(MaterialCategory.tenant_id == tenant_id)
    ).all()
    for cat in cats:
        if cat.default_consume_segment_id:
            continue
        want = DEFAULT_CATEGORY_CONSUME_PROCESS.get(cat.name)
        seg = None
        if want:
            proc = db.scalar(
                select(ProcessDefinition).where(
                    ProcessDefinition.tenant_id == tenant_id,
                    ProcessDefinition.name == want,
                    ProcessDefinition.is_active.is_(True),
                )
            )
            if proc and proc.segment_id:
                seg = db.get(ProcessSegment, proc.segment_id)
        if not seg:
            seg = fallback
        cat.default_consume_segment_id = seg.id
        updated += 1
    if updated:
        db.flush()
    return updated


def ensure_default_size_usage_table(
    db: Session,
    tenant_id: int,
    *,
    fill_all_sizes: bool = True,
    link_suggest_categories: bool = True,
) -> MaterialSizeUsageTable:
    """确保租户有「大底通用」码表（缺尺码系数补 1），并可挂到建议按码分类。"""
    table = db.scalar(
        select(MaterialSizeUsageTable).where(
            MaterialSizeUsageTable.tenant_id == tenant_id,
            MaterialSizeUsageTable.name == DEFAULT_SIZE_USAGE_TABLE_NAME,
        )
    )
    created = False
    if not table:
        table = MaterialSizeUsageTable(
            tenant_id=tenant_id,
            name=DEFAULT_SIZE_USAGE_TABLE_NAME,
            notes="大底/中底/鞋垫共用；全码系数默认 1，大码可微调",
        )
        db.add(table)
        db.flush()
        created = True

    if fill_all_sizes:
        existing = {
            c.size_id
            for c in db.scalars(
                select(MaterialSizeUsageCoeff).where(
                    MaterialSizeUsageCoeff.tenant_id == tenant_id,
                    MaterialSizeUsageCoeff.table_id == table.id,
                )
            ).all()
        }
        sizes = db.scalars(
            select(Size).where(Size.tenant_id == tenant_id).order_by(Size.sort_order, Size.id)
        ).all()
        for sz in sizes:
            if sz.id in existing:
                continue
            db.add(
                MaterialSizeUsageCoeff(
                    tenant_id=tenant_id,
                    table_id=table.id,
                    size_id=sz.id,
                    coeff=Decimal("1"),
                )
            )

    if link_suggest_categories:
        cats = db.scalars(
            select(MaterialCategory).where(
                MaterialCategory.tenant_id == tenant_id,
                MaterialCategory.name.in_(list(DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES)),
            )
        ).all()
        for cat in cats:
            cat.suggest_usage_by_size = True
            if not cat.default_size_usage_table_id:
                cat.default_size_usage_table_id = table.id

    db.flush()
    # created 仅用于调用方日志；表对象始终返回
    _ = created
    return table


def required_qty_for_row(
    row: OrderMaterialRequirement,
    order: Order,
    *,
    size_qtys: dict[int, int] | None = None,
) -> Decimal:
    fixed = getattr(row, "loss_fixed_qty", None) or Decimal("0")
    rate = row.loss_rate or Decimal("0")
    if getattr(row, "usage_by_size", False) and row.size_id:
        qtys = size_qtys if size_qtys is not None else order_size_qty_map(order)
        size_qty = int(qtys.get(int(row.size_id), 0))
        return calc_required_qty_sized(
            row.qty_per_pair or Decimal("0"),
            size_qty,
            getattr(row, "size_coeff", None) or Decimal("1"),
            rate,
            fixed,
        )
    return calc_required_qty(
        row.qty_per_pair or Decimal("0"),
        int(order.total_qty or 0),
        rate,
        fixed,
    )


def resolve_consume_segment(
    db: Session,
    tenant_id: int,
    *,
    bom_consume_segment_id: int | None,
    bom_consume_process_id: int | None = None,
    supplier_product_id: int,
) -> tuple[int | None, str]:
    """解析消耗工序段：(segment_id, source)。工序段重构 4.1。

    优先级：BOM 段覆盖 > BOM 工序（经工序归属段，兼容迁移前旧 BOM）> 物料分类默认段
    > unlabeled（运行时算进首段）。
    旧字段（consume_process_id）仍在两期过渡内保留，见 D20。
    """
    if bom_consume_segment_id:
        seg = db.get(ProcessSegment, bom_consume_segment_id)
        if seg and seg.tenant_id == tenant_id:
            return seg.id, "bom"
    if bom_consume_process_id:
        proc = db.get(ProcessDefinition, bom_consume_process_id)
        if proc and proc.tenant_id == tenant_id and proc.segment_id:
            return proc.segment_id, "bom"
    sp = db.get(SupplierProduct, supplier_product_id)
    if sp and sp.tenant_id == tenant_id and sp.category_id:
        cat = db.get(MaterialCategory, sp.category_id)
        if cat and cat.tenant_id == tenant_id and cat.default_consume_segment_id:
            seg = db.get(ProcessSegment, cat.default_consume_segment_id)
            if seg and seg.tenant_id == tenant_id:
                return seg.id, "category"
    return None, "unlabeled"


def resolve_consume_process(
    db: Session,
    tenant_id: int,
    *,
    bom_consume_process_id: int | None,
    supplier_product_id: int,
) -> tuple[int | None, str]:
    """解析消耗工序：(process_id, source)。（旧实现，两期过渡保留，D20）

    优先级：BOM 覆盖 > 物料分类默认 > unlabeled（运行时算进首道）。
    """
    if bom_consume_process_id:
        proc = db.get(ProcessDefinition, bom_consume_process_id)
        if proc and proc.tenant_id == tenant_id:
            return proc.id, "bom"
    sp = db.get(SupplierProduct, supplier_product_id)
    if sp and sp.tenant_id == tenant_id and sp.category_id:
        cat = db.get(MaterialCategory, sp.category_id)
        if (
            cat
            and cat.tenant_id == tenant_id
            and cat.default_consume_process_id
        ):
            proc = db.get(ProcessDefinition, cat.default_consume_process_id)
            if proc and proc.tenant_id == tenant_id:
                return proc.id, "category"
    return None, "unlabeled"


def process_display_name(db: Session, process_id: int | None) -> str | None:
    if not process_id:
        return None
    proc = db.get(ProcessDefinition, process_id)
    return proc.name if proc else None


def first_order_process(db: Session, tenant_id: int, order_id: int) -> OrderProcess | None:
    """首道 = 建单时按产品路线写入的第一道（OrderProcess.id 升序）。"""
    return db.scalar(
        select(OrderProcess)
        .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order_id)
        .order_by(OrderProcess.id)
        .limit(1)
    )


def last_order_process(db: Session, tenant_id: int, order_id: int) -> OrderProcess | None:
    """末道 = 路线最后一道（OrderProcess.id 降序；与首道对称，无独立 sort_order 列）。

    B0a 齐码可发默认认此工序；将来若有「约定发货工序」配置可在此替换。
    """
    return db.scalar(
        select(OrderProcess)
        .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order_id)
        .order_by(OrderProcess.id.desc())
        .limit(1)
    )


def row_in_process_scope(
    row: OrderMaterialRequirement,
    process_id: int,
    *,
    first_process_id: int | None,
    db: Session | None = None,
    segment_cache: dict[int, int | None] | None = None,
) -> bool:
    """工序齐套过滤（段级，工序段重构 4.3/D16）。

    匹配键 = **段**：row.consume_segment_id vs 工序归属段（ProcessDefinition.segment_id）。
    首道含 unlabeled（consume_segment_id 为空）；其它工序仅匹配显式归属。
    by_process 产出结构不变（仍按 process_id 索引，D16）。
    """
    cid = getattr(row, "consume_segment_id", None)
    seg_id = _segment_of_process(db, process_id, cache=segment_cache)
    if first_process_id is not None and process_id == first_process_id:
        # 首段：未标注（unlabeled）或显式归属首段
        return cid is None or (seg_id is not None and cid == seg_id)
    # 其它段：仅显式归属匹配；未挂段工序（D18 未分段）不匹配任何料
    return seg_id is not None and cid == seg_id


def _segment_of_process(
    db: Session | None,
    process_id: int,
    *,
    cache: dict[int, int | None] | None = None,
) -> int | None:
    """工序归属段 id（带缓存，避免 by_process 循环内重复查库）。"""
    if cache is not None and process_id in cache:
        return cache[process_id]
    seg_id = None
    if db is not None:
        proc = db.get(ProcessDefinition, process_id)
        if proc:
            seg_id = proc.segment_id
    if cache is not None:
        cache[process_id] = seg_id
    return seg_id


def apply_consume_snapshot(
    db: Session,
    tenant_id: int,
    row: OrderMaterialRequirement,
    *,
    bom_consume_segment_id: int | None = None,
    bom_consume_process_id: int | None = None,
    supplier_product_id: int,
) -> str:
    """把解析结果写入订单用料快照，返回 source（工序段重构 4.2/7.2）。

    段字段为新主键（consume_segment_id/name）；旧工序字段两期过渡保留
    （BOM 有工序级信息才写，D20）。
    """
    seg_id, seg_name, source = _resolve_segment_with_name(
        db,
        tenant_id,
        bom_consume_segment_id=bom_consume_segment_id,
        bom_consume_process_id=bom_consume_process_id,
        supplier_product_id=supplier_product_id,
    )
    row.consume_segment_id = seg_id
    row.consume_segment_name = seg_name
    # 旧工序字段两期过渡（D20）：保持旧解析逻辑，兼容存量消费方
    pid, _ = resolve_consume_process(
        db,
        tenant_id,
        bom_consume_process_id=bom_consume_process_id,
        supplier_product_id=supplier_product_id,
    )
    row.consume_process_id = pid
    row.consume_process_name = process_display_name(db, pid)
    return source


def _resolve_segment_with_name(
    db: Session,
    tenant_id: int,
    *,
    bom_consume_segment_id: int | None,
    bom_consume_process_id: int | None,
    supplier_product_id: int,
) -> tuple[int | None, str | None, str]:
    seg_id, source = resolve_consume_segment(
        db,
        tenant_id,
        bom_consume_segment_id=bom_consume_segment_id,
        bom_consume_process_id=bom_consume_process_id,
        supplier_product_id=supplier_product_id,
    )
    name = None
    if seg_id:
        seg = db.get(ProcessSegment, seg_id)
        name = seg.name if seg else None
    return seg_id, name, source


def ensure_material_snapshot(db: Session, tenant_id: int, order: Order) -> list[OrderMaterialRequirement]:
    """若尚无用料行，从产品 BOM 生成快照。"""
    existing = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
    )
    if existing:
        header = resolve_header_for_order(db, tenant_id, order.id)
        if header:
            dirty = False
            for row in existing:
                if getattr(row, "header_id", None) != header.id:
                    row.header_id = header.id
                    dirty = True
            if dirty:
                db.flush()
        return existing
    return refresh_from_bom(db, tenant_id, order, keep_progress=False)


def refresh_from_bom(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    keep_progress: bool = True,
) -> list[OrderMaterialRequirement]:
    materials = db.scalars(
        select(OwnProductMaterial)
        .where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.own_product_id == order.own_product_id,
        )
        .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
    ).all()
    materials = filter_bom_for_colorway(materials, colorway_id_from_order(db, order))

    size_qtys = order_size_qty_map(order, db)
    # 预检：按码 BOM 缺系数则整单拒绝刷新
    missing: list[str] = []
    labels = size_labels(db, set(size_qtys.keys()))
    for m in materials:
        if not getattr(m, "usage_by_size", False):
            continue
        table_id = getattr(m, "size_usage_table_id", None)
        if not table_id:
            raise MaterialError("missing_size_table", "按码用量物料未绑定用量码表")
        table = db.get(MaterialSizeUsageTable, table_id)
        if not table or table.tenant_id != tenant_id:
            raise MaterialError("missing_size_table", "用量码表不存在")
        coeff_map = load_size_coeff_map(db, tenant_id, table_id)
        sp = db.get(SupplierProduct, m.supplier_product_id)
        sp_label = (sp.product_code if sp else None) or str(m.supplier_product_id)
        for sid in size_qtys:
            if sid not in coeff_map:
                missing.append(f"{sp_label}/{labels.get(sid) or sid}")
    if missing:
        raise MaterialError(
            "missing_size_coeff",
            "用量码表缺少尺码系数：" + "、".join(missing[:20])
            + ("…" if len(missing) > 20 else ""),
        )

    by_key: dict[PoolKey, OrderMaterialRequirement] = {}
    if keep_progress:
        for row in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all():
            by_key[_req_match_key(row.supplier_product_id, row.size_id if row.usage_by_size else None)] = row
    else:
        for row in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all():
            db.delete(row)
        db.flush()

    kept_ids: set[int] = set()
    result: list[OrderMaterialRequirement] = []
    sort_base = 0

    def _upsert_row(
        *,
        m: OwnProductMaterial,
        size_id: int | None,
        size_coeff: Decimal,
        usage_by_size: bool,
        required: Decimal,
        sort_order: int,
        loss_rate: Decimal,
        loss_fixed_qty: Decimal,
        sync_loss_from_bom: bool,
    ) -> OrderMaterialRequirement:
        key = _req_match_key(m.supplier_product_id, size_id if usage_by_size else None)
        bom_pid = getattr(m, "consume_process_id", None)
        bom_sid = getattr(m, "consume_segment_id", None)
        if key in by_key and keep_progress:
            row = by_key[key]
            row.qty_per_pair = m.qty
            row.unit_price = m.unit_price
            if sync_loss_from_bom:
                row.loss_rate = loss_rate
                row.loss_fixed_qty = loss_fixed_qty
            else:
                row.loss_rate = row.loss_rate or Decimal("0")
                row.loss_fixed_qty = getattr(row, "loss_fixed_qty", None) or Decimal("0")
            row.required_qty = (
                calc_required_qty_sized(
                    m.qty,
                    size_qtys.get(size_id or 0, 0),
                    size_coeff,
                    row.loss_rate,
                    row.loss_fixed_qty,
                )
                if usage_by_size and size_id
                else calc_required_qty(m.qty, order.total_qty, row.loss_rate, row.loss_fixed_qty)
            )
            row.sort_order = sort_order
            row.usage_by_size = usage_by_size
            row.size_id = size_id if usage_by_size else None
            row.size_coeff = size_coeff if usage_by_size else Decimal("1")
            apply_consume_snapshot(
                db,
                tenant_id,
                row,
                bom_consume_segment_id=bom_sid,
                bom_consume_process_id=bom_pid,
                supplier_product_id=m.supplier_product_id,
            )
            if row.id:
                kept_ids.add(row.id)
            result.append(row)
            return row
        row = OrderMaterialRequirement(
            tenant_id=tenant_id,
            order_id=order.id,
            supplier_product_id=m.supplier_product_id,
            qty_per_pair=m.qty,
            loss_rate=loss_rate,
            loss_fixed_qty=loss_fixed_qty,
            unit_price=m.unit_price or Decimal("0"),
            required_qty=required,
            arrived_qty=Decimal("0"),
            issued_qty=Decimal("0"),
            is_customer_supplied=False,
            sort_order=sort_order,
            usage_by_size=usage_by_size,
            size_id=size_id if usage_by_size else None,
            size_coeff=size_coeff if usage_by_size else Decimal("1"),
        )
        apply_consume_snapshot(
            db,
            tenant_id,
            row,
            bom_consume_segment_id=bom_sid,
            bom_consume_process_id=bom_pid,
            supplier_product_id=m.supplier_product_id,
        )
        db.add(row)
        result.append(row)
        return row

    for i, m in enumerate(materials):
        usage_by_size = bool(getattr(m, "usage_by_size", False))
        bom_loss_rate = getattr(m, "loss_rate", None) or Decimal("0")
        bom_loss_fixed = getattr(m, "loss_fixed_qty", None) or Decimal("0")
        if usage_by_size:
            coeff_map = load_size_coeff_map(db, tenant_id, int(m.size_usage_table_id))
            if not size_qtys:
                raise MaterialError("no_order_sizes", "按码用量需要生产单色码明细")
            # 固定损耗只加在首码行，避免按码展开重复加
            first_sid = True
            for sid, sqty in sorted(size_qtys.items(), key=lambda x: x[0]):
                coeff = coeff_map[sid]
                fixed = bom_loss_fixed if first_sid else Decimal("0")
                first_sid = False
                req = calc_required_qty_sized(m.qty, sqty, coeff, bom_loss_rate, fixed)
                _upsert_row(
                    m=m,
                    size_id=sid,
                    size_coeff=coeff,
                    usage_by_size=True,
                    required=req,
                    sort_order=(m.sort_order if m.sort_order is not None else i) * 1000 + sort_base,
                    loss_rate=bom_loss_rate,
                    loss_fixed_qty=fixed,
                    sync_loss_from_bom=True,
                )
                sort_base += 1
        else:
            req = calc_required_qty(m.qty, order.total_qty, bom_loss_rate, bom_loss_fixed)
            _upsert_row(
                m=m,
                size_id=None,
                size_coeff=Decimal("1"),
                usage_by_size=False,
                required=req,
                sort_order=m.sort_order if m.sort_order is not None else i,
                loss_rate=bom_loss_rate,
                loss_fixed_qty=bom_loss_fixed,
                sync_loss_from_bom=True,
            )

    if keep_progress:
        for row in by_key.values():
            if row.id and row.id not in kept_ids and row.arrived_qty == 0 and row.issued_qty == 0:
                db.delete(row)

    # B1d：承接外包/来料加工——用料全标客供（上家供料）
    if is_subcontract_in_sales_order(db, order.sales_order_id):
        mark_requirements_customer_supplied(result)

    db.flush()
    header = resolve_header_for_order(db, tenant_id, order.id)
    exe_id = resolve_execution_id_for_order(db, tenant_id, order.id)
    for row in result:
        if header:
            row.header_id = header.id
        if exe_id:
            row.execution_id = exe_id
    if header or exe_id:
        db.flush()
    return result


def recalculate_required(db: Session, tenant_id: int, order: Order) -> list[OrderMaterialRequirement]:
    rows = ensure_material_snapshot(db, tenant_id, order)
    size_qtys = order_size_qty_map(order, db)
    for row in rows:
        row.required_qty = required_qty_for_row(row, order, size_qtys=size_qtys)
    db.flush()
    return rows


def _get_shared_stock(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None = None,
) -> SharedMaterialStock | None:
    q = select(SharedMaterialStock).where(
        SharedMaterialStock.tenant_id == tenant_id,
        SharedMaterialStock.supplier_product_id == supplier_product_id,
    )
    if size_id is None:
        q = q.where(SharedMaterialStock.size_id.is_(None))
    else:
        q = q.where(SharedMaterialStock.size_id == size_id)
    return db.scalar(q)


def _shared_qty(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None = None,
) -> Decimal:
    stock = _get_shared_stock(db, tenant_id, supplier_product_id, size_id)
    return stock.qty if stock else Decimal("0")


def _shared_avg_cost(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None = None,
) -> Decimal:
    stock = _get_shared_stock(db, tenant_id, supplier_product_id, size_id)
    return stock.avg_unit_cost if stock else Decimal("0")


def ordered_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status.in_(list(ORDERED_PO_STATUSES)),
        )
    ).all()
    return sum((ln.qty for ln in lines), Decimal("0"))


def in_transit_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    """在途 = 已下单/在运采购行的未收量（只认 PO 实收，不跟 arrived 混算）。"""
    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    total = Decimal("0")
    for ln in lines:
        open_qty = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
        if open_qty > 0:
            total += open_qty
    return total



def draft_qty_for_requirement(db: Session, tenant_id: int, req_id: int) -> Decimal:
    """采购草稿占用（不进齐套，但占用待采购数量，避免重复下单）。"""
    val = db.scalar(
        select(func.coalesce(func.sum(PurchaseOrderLine.qty), 0))
        .select_from(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.order_material_requirement_id == req_id,
            PurchaseOrder.status == PurchaseOrderStatus.draft,
        )
    )
    return Decimal(str(val or 0))


def resolve_include_shared(
    db: Session,
    tenant_id: int,
    include_shared: bool | None = None,
) -> bool:
    """显式入参优先；否则读租户 kit_include_unallocated_pool。"""
    if include_shared is not None:
        return bool(include_shared)
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    return bool(inv.get("kit_include_unallocated_pool", False))


OPEN_KIT_STATUSES = {
    OrderStatus.draft,
    OrderStatus.confirmed,
    OrderStatus.in_progress,
}


def _pool_need(row: OrderMaterialRequirement) -> Decimal:
    """相对已占用（arrived），还差多少才齐套（不含池）。"""
    if row.is_customer_supplied:
        return Decimal("0")
    required = row.required_qty or Decimal("0")
    arrived = row.arrived_qty or Decimal("0")
    return max(Decimal("0"), required - arrived)


def _order_kit_priority(order: Order) -> tuple:
    """急单优先，交期早优先，同交期 id 小优先。"""
    rush = 0 if getattr(order, "is_rush", False) else 1
    dd = order.delivery_date.toordinal() if order.delivery_date else 10**9
    return (rush, dd, order.id or 0)


def build_pool_credits(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool,
    focus_order_ids: set[int] | None = None,
) -> tuple[dict[tuple[int | None, int], Decimal], dict[PoolKey, Decimal]]:
    """按 (SKU, size) 把未分配池拆成各用料行的可承诺量，禁止多单重复吃满池。

    返回:
      credits[(order_id|None, req_id)] -> 本行可计入齐套的池数量
      pool_by_key[(supplier_product_id, size_id|None)] -> 池余额
    """
    stocks = db.scalars(
        select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
    ).all()
    pool_by_key: dict[PoolKey, Decimal] = {
        _pool_key(s.supplier_product_id, s.size_id): (s.qty or Decimal("0")) for s in stocks
    }
    credits: dict[tuple[int | None, int], Decimal] = {}
    if not include_shared:
        return credits, pool_by_key

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    orders.sort(key=_order_kit_priority)
    order_by_id = {o.id: o for o in orders}

    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.in_([o.id for o in orders] or [-1]),
            )
        ).all()
    )
    # K4-B：无桥接壳的用料行（order_id 空，挂 header_id）
    header_reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.is_(None),
                OrderMaterialRequirement.header_id.isnot(None),
            )
        ).all()
    )
    header_ids = {int(r.header_id) for r in header_reqs if r.header_id}
    headers_by_id: dict[int, ExecutionHeader] = {}
    if header_ids:
        headers_by_id = {
            h.id: h
            for h in db.scalars(
                select(ExecutionHeader).where(
                    ExecutionHeader.tenant_id == tenant_id,
                    ExecutionHeader.id.in_(list(header_ids)),
                    ExecutionHeader.status != SpecExecutionStatus.cancelled,
                )
            ).all()
        }
    header_reqs = [r for r in header_reqs if r.header_id and int(r.header_id) in headers_by_id]

    by_key: dict[PoolKey, list[OrderMaterialRequirement]] = {}
    for row in reqs:
        if row.order_id not in order_by_id:
            continue
        by_key.setdefault(_req_pool_key(row), []).append(row)
    for row in header_reqs:
        by_key.setdefault(_req_pool_key(row), []).append(row)

    def _req_priority(row: OrderMaterialRequirement) -> tuple:
        if row.order_id and row.order_id in order_by_id:
            return _order_kit_priority(order_by_id[row.order_id])
        hdr = headers_by_id.get(int(row.header_id)) if row.header_id else None
        if hdr:
            rush = 0 if getattr(hdr, "is_rush", False) else 1
            dd = hdr.delivery_date.toordinal() if hdr.delivery_date else 10**9
            return (rush, dd, hdr.id or 0)
        return (1, 10**9, row.id or 0)

    for key, rows in by_key.items():
        remaining = pool_by_key.get(key, Decimal("0"))
        rows.sort(key=_req_priority)
        for row in rows:
            need = _pool_need(row)
            credit = min(need, remaining) if need > 0 and remaining > 0 else Decimal("0")
            credits[(row.order_id, row.id)] = credit
            remaining -= credit

    if focus_order_ids:
        pass
    return credits, pool_by_key


def db_scalars_in(db: Session, model, ids: list[int]):
    """按主键 IN 批量查模型实例（用于齐套批量预取）。"""
    if not ids:
        return []
    return list(db.scalars(select(model).where(model.id.in_(ids))).all())


def kit_row_dict(
    db: Session,
    tenant_id: int,
    row: OrderMaterialRequirement,
    *,
    include_shared: bool = True,
    shared_credit: Decimal | None = None,
    pool_qty: Decimal | None = None,
    purchase_totals: tuple[Decimal, Decimal, Decimal] | None = None,
    lookups: dict | None = None,
) -> dict:
    """单行齐套投影。shared_credit 应由 build_pool_credits 传入，避免每行独吞整池。"""
    if lookups:
        sp = lookups.get("sp", {}).get(int(row.supplier_product_id)) if row.supplier_product_id else None
        partner = (
            lookups.get("partner", {}).get(int(sp.partner_id)) if sp and sp.partner_id else None
        )
        color = (
            lookups.get("color", {}).get(int(sp.color_id)) if sp and sp.color_id else None
        )
        unit = (
            lookups.get("pricing_unit", {}).get(int(sp.pricing_unit_id))
            if sp and sp.pricing_unit_id
            else None
        )
        consume_name = row.consume_process_name or (
            lookups.get("process_name", {}).get(int(row.consume_process_id), None)
            if row.consume_process_id
            else None
        )
        size_value = None
        if getattr(row, "usage_by_size", False) and row.size_id:
            sz = lookups.get("size", {}).get(int(row.size_id))
            size_value = sz.size_value if sz else None
    else:
        sp = db.get(SupplierProduct, row.supplier_product_id)
        partner = db.get(Partner, sp.partner_id) if sp and sp.partner_id else None
        consume_name = None
        size_value = None
        color = None
        unit = None
    if purchase_totals is not None:
        ordered, draft_qty, in_transit = purchase_totals
    else:
        ordered = ordered_qty_for_requirement(db, tenant_id, row.id)
        draft_qty = draft_qty_for_requirement(db, tenant_id, row.id)
        in_transit = in_transit_qty_for_requirement(db, tenant_id, row.id)
    size_id = row.size_id if getattr(row, "usage_by_size", False) else None
    pool = (
        pool_qty
        if pool_qty is not None
        else (
            _shared_qty(db, tenant_id, row.supplier_product_id, size_id)
            if include_shared
            else Decimal("0")
        )
    )
    arrived = row.arrived_qty or Decimal("0")
    required = row.required_qty or Decimal("0")
    if shared_credit is None:
        credit = Decimal("0")
    else:
        credit = shared_credit if include_shared else Decimal("0")
    if row.is_customer_supplied:
        shortage = max(Decimal("0"), required - arrived)
        credit = Decimal("0")
    else:
        shortage = max(Decimal("0"), required - arrived - credit)
    to_buy = max(Decimal("0"), shortage - draft_qty - in_transit)
    # 缺料行一生一稿：已有未取消采购（草稿或已下单及后续）则不可再生成
    has_purchase = draft_qty > 0 or ordered > 0
    can_create_draft = to_buy > 0 and not has_purchase
    if to_buy <= 0 and in_transit > 0:
        purchase_status = "ordered"
        purchase_status_label = "已下单在途"
    elif to_buy <= 0 and draft_qty > 0:
        purchase_status = "draft"
        purchase_status_label = "草稿已建"
    elif has_purchase:
        purchase_status = "partial"
        purchase_status_label = "已生成采购"
    else:
        purchase_status = "open"
        purchase_status_label = "待采购"
    kit_ok = shortage <= 0
    consume_pid = getattr(row, "consume_process_id", None)
    if consume_name is None:
        consume_name = getattr(row, "consume_process_name", None) or process_display_name(
            db, consume_pid
        )
    if size_value is None and getattr(row, "usage_by_size", False) and row.size_id:
        sz = db.get(Size, row.size_id)
        size_value = sz.size_value if sz else None
    if color is None and sp and sp.color_id:
        color = db.get(Color, sp.color_id)
    if unit is None and sp and sp.pricing_unit_id:
        unit = db.get(PricingUnit, sp.pricing_unit_id)
    return {
        "id": row.id,
        "order_id": row.order_id,
        "execution_id": getattr(row, "execution_id", None),
        "header_id": getattr(row, "header_id", None),
        "supplier_product_id": row.supplier_product_id,
        "supplier_product_code": sp.product_code if sp else None,
        "supplier_product_name": sp.name if sp else None,
        "image_url": sp.image_url if sp else None,
        "partner_id": sp.partner_id if sp else None,
        "partner_name": partner.name if partner else None,
        "pricing_unit_id": sp.pricing_unit_id if sp else None,
        "pricing_unit_name": unit.name if unit else None,
        "qty_per_pair": row.qty_per_pair,
        "loss_rate": row.loss_rate,
        "loss_fixed_qty": getattr(row, "loss_fixed_qty", None) or Decimal("0"),
        "unit_price": row.unit_price,
        "required_qty": required,
        "ordered_qty": ordered,
        "draft_qty": draft_qty,
        "arrived_qty": arrived,
        "in_transit_qty": in_transit,
        "pool_qty": pool if include_shared else Decimal("0"),
        "shared_credit_qty": credit,
        "shared_qty": credit,
        "shortage_qty": shortage,
        "to_buy_qty": to_buy,
        "has_purchase": has_purchase,
        "can_create_draft": can_create_draft,
        "purchase_status": purchase_status,
        "purchase_status_label": purchase_status_label,
        "issued_qty": row.issued_qty or Decimal("0"),
        "is_customer_supplied": bool(row.is_customer_supplied),
        "customer_chase_status": getattr(row, "customer_chase_status", None) or "open",
        "customer_chase_note": getattr(row, "customer_chase_note", None),
        "customer_chased_at": (
            row.customer_chased_at.isoformat()
            if getattr(row, "customer_chased_at", None)
            else None
        ),
        "kit_ok": kit_ok,
        "sort_order": row.sort_order,
        "notes": row.notes,
        "consume_process_id": consume_pid,
        "consume_process_name": consume_name,
        "consume_unlabeled": consume_pid is None,
        "usage_by_size": bool(getattr(row, "usage_by_size", False)),
        "size_id": size_id,
        "size_value": size_value,
        "size_coeff": getattr(row, "size_coeff", None) or Decimal("1"),
        "color_id": sp.color_id if sp else None,
        "color_name": color.name if color else None,
    }


class KitContext:
    """租户级齐套上下文：一次建池承诺，多处复用（列表/缺料/看板）。"""

    def __init__(
        self,
        db: Session,
        tenant_id: int,
        *,
        include_shared: bool,
        credits: dict[tuple[int, int], Decimal],
        pool_by_key: dict[PoolKey, Decimal],
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.include_shared = include_shared
        self.credits = credits
        self.pool_by_key = pool_by_key
        # 兼容旧字段名
        self.pool_by_sp = {
            sp_id: qty
            for (sp_id, size_id), qty in pool_by_key.items()
            if size_id is None
        }
        # 批量采购量缓存：req_id -> (ordered, draft, in_transit)
        self._req_purchase_totals: dict[int, tuple[Decimal, Decimal, Decimal]] | None = None
        # 批量关联表缓存：避免逐行 db.get
        self._sp_by_id: dict[int, SupplierProduct] = {}
        self._partner_by_id: dict[int, Partner] = {}
        self._size_by_id: dict[int, Size] = {}
        self._color_by_id: dict[int, Color] = {}
        self._pricing_unit_by_id: dict[int, PricingUnit] = {}
        self._process_name_by_id: dict[int, str] = {}
        self._lookups_loaded = False

    def _load_row_lookups_batch(self, rows: list[OrderMaterialRequirement]) -> None:
        """批量预取 row_dict 所需的关联表（SupplierProduct/Partner/Size/Color/工序）。"""
        sp_ids = {int(r.supplier_product_id) for r in rows if r.supplier_product_id}
        partner_ids: set[int] = set()
        color_ids: set[int] = set()
        pricing_ids: set[int] = set()
        if sp_ids:
            sps = db_scalars_in(self.db, SupplierProduct, list(sp_ids))
            self._sp_by_id = {int(x.id): x for x in sps}
            partner_ids = {int(x.partner_id) for x in sps if x.partner_id}
            color_ids = {int(x.color_id) for x in sps if x.color_id}
            pricing_ids = {int(x.pricing_unit_id) for x in sps if x.pricing_unit_id}
        if partner_ids:
            self._partner_by_id = {
                int(x.id): x for x in db_scalars_in(self.db, Partner, list(partner_ids))
            }
        if color_ids:
            self._color_by_id = {int(x.id): x for x in db_scalars_in(self.db, Color, list(color_ids))}
        if pricing_ids:
            self._pricing_unit_by_id = {
                int(x.id): x for x in db_scalars_in(self.db, PricingUnit, list(pricing_ids))
            }
        size_ids = {int(r.size_id) for r in rows if r.size_id}
        if size_ids:
            self._size_by_id = {int(x.id): x for x in db_scalars_in(self.db, Size, list(size_ids))}
        proc_ids = {int(r.consume_process_id) for r in rows if r.consume_process_id}
        if proc_ids:
            self._process_name_by_id = dict(
                self.db.execute(
                    select(ProcessDefinition.id, ProcessDefinition.name).where(
                        ProcessDefinition.id.in_(list(proc_ids))
                    )
                ).all()
            )
        self._lookups_loaded = True

    def _load_req_purchase_totals_batch(
        self, req_ids: list[int]
    ) -> dict[int, tuple[Decimal, Decimal, Decimal]]:
        """一次查出多个用料行的采购量（已下单/草稿/在途），避免逐行查询。"""
        if not req_ids:
            return {}
        rows = self.db.execute(
            select(
                PurchaseOrderLine.order_material_requirement_id,
                PurchaseOrder.status,
                PurchaseOrderLine.qty,
                PurchaseOrderLine.received_qty,
            )
            .select_from(PurchaseOrderLine)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(
                PurchaseOrderLine.tenant_id == self.tenant_id,
                PurchaseOrderLine.order_material_requirement_id.in_(req_ids),
            )
        ).all()
        totals: dict[int, tuple[Decimal, Decimal, Decimal]] = {}
        for req_id, status, qty, received in rows:
            if isinstance(status, str):
                status = PurchaseOrderStatus(status)
            ordered, draft, in_transit = totals.get(req_id, (Decimal("0"), Decimal("0"), Decimal("0")))
            if status in ORDERED_PO_STATUSES:
                ordered += qty or Decimal("0")
            elif status == PurchaseOrderStatus.draft:
                draft += qty or Decimal("0")
            if status in [
                PurchaseOrderStatus.ordered,
                PurchaseOrderStatus.shipped,
                PurchaseOrderStatus.partial_received,
            ]:
                open_qty = (qty or Decimal("0")) - (received or Decimal("0"))
                if open_qty > 0:
                    in_transit += open_qty
            totals[req_id] = (ordered, draft, in_transit)
        return totals

    def row_dict(self, row: OrderMaterialRequirement) -> dict:
        return kit_row_dict(
            self.db,
            self.tenant_id,
            row,
            include_shared=self.include_shared,
            shared_credit=self.credits.get((row.order_id, row.id), Decimal("0")),
            pool_qty=self.pool_by_key.get(_req_pool_key(row), Decimal("0")),
            purchase_totals=(
                self._req_purchase_totals.get(int(row.id))
                if self._req_purchase_totals is not None
                else None
            ),
            lookups=(
                {
                    "sp": self._sp_by_id,
                    "partner": self._partner_by_id,
                    "size": self._size_by_id,
                    "color": self._color_by_id,
                    "pricing_unit": self._pricing_unit_by_id,
                    "process_name": self._process_name_by_id,
                }
                if self._lookups_loaded
                else None
            ),
        )

    def _kit_summary_from_rows(
        self,
        rows: list[OrderMaterialRequirement],
        *,
        first_process: OrderProcess | None,
    ) -> dict:
        if not rows:
            return {
                "kit_ok": False,
                "empty_bom": True,
                "shortage_lines": 0,
                "include_shared": self.include_shared,
                "first_kit_ok": False,
                "first_process_id": None,
                "first_process_name": None,
            }
        shortage = 0
        for row in rows:
            if not self.row_dict(row)["kit_ok"]:
                shortage += 1
        first_id = first_process.process_id if first_process else None
        first_name = first_process.process_name if first_process else None
        if first_id is not None:
            first_shortage = 0
            _seg_cache: dict[int, int | None] = {}
            for row in rows:
                if not row_in_process_scope(
                    row, first_id, first_process_id=first_id, db=self.db, segment_cache=_seg_cache
                ):
                    continue
                if not self.row_dict(row)["kit_ok"]:
                    first_shortage += 1
            first_kit_ok = first_shortage == 0
        else:
            first_kit_ok = shortage == 0
        return {
            "kit_ok": shortage == 0,
            "empty_bom": False,
            "shortage_lines": shortage,
            "include_shared": self.include_shared,
            "first_kit_ok": first_kit_ok,
            "first_process_id": first_id,
            "first_process_name": first_name,
        }

    def summary_for_order(self, order_id: int, rows: list[OrderMaterialRequirement] | None = None) -> dict:
        if rows is None:
            rows = list(
                self.db.scalars(
                    select(OrderMaterialRequirement).where(
                        OrderMaterialRequirement.tenant_id == self.tenant_id,
                        OrderMaterialRequirement.order_id == order_id,
                    )
                ).all()
            )
        first = first_order_process(self.db, self.tenant_id, order_id) if rows else None
        return self._kit_summary_from_rows(rows, first_process=first)

    def summary_for_header(
        self,
        header_id: int,
        rows: list[OrderMaterialRequirement] | None = None,
        processes: list[OrderProcess] | None = None,
    ) -> dict:
        if rows is None:
            rows = list(
                self.db.scalars(
                    select(OrderMaterialRequirement).where(
                        OrderMaterialRequirement.tenant_id == self.tenant_id,
                        OrderMaterialRequirement.header_id == header_id,
                    )
                ).all()
            )
        if processes is None:
            processes = list_header_processes(self.db, self.tenant_id, header_id)
        first = processes[0] if processes else None
        out = self._kit_summary_from_rows(rows, first_process=first)
        out["header_id"] = header_id
        return out


def build_kit_context(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool | None = None,
) -> KitContext:
    resolved = resolve_include_shared(db, tenant_id, include_shared)
    credits, pool_by_key = build_pool_credits(db, tenant_id, include_shared=resolved)
    return KitContext(
        db,
        tenant_id,
        include_shared=resolved,
        credits=credits,
        pool_by_key=pool_by_key,
    )


def get_order_kit(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    include_shared: bool | None = None,
) -> dict:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.material_requirements))
    )
    if not order:
        raise MaterialError("order_not_found", "订单不存在")
    rows = ensure_material_snapshot(db, tenant_id, order)
    db.flush()
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    lines = [ctx.row_dict(r) for r in rows]
    lines.sort(key=lambda x: (x["sort_order"], x["id"]))
    empty_bom = len(lines) == 0
    # 空 BOM 不算齐套（否则会虚放行开裁）
    kit_ok = (not empty_bom) and all(x["kit_ok"] for x in lines)

    first = first_order_process(db, tenant_id, order.id)
    first_id = first.process_id if first else None
    first_name = first.process_name if first else None

    processes = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order.id)
            .order_by(OrderProcess.id)
        ).all()
    )
    by_process: list[dict] = []
    for p in processes:
        is_first = first_id is not None and p.process_id == first_id
        if empty_bom:
            by_process.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "kit_ok": False if is_first else True,
                    "shortage_lines": 0,
                    "line_count": 0,
                    "is_first": is_first,
                    "empty_bom": True,
                }
            )
            continue
        _seg_cache: dict[int, int | None] = {}
        scoped = [
            r
            for r in rows
            if row_in_process_scope(
                r, p.process_id, first_process_id=first_id, db=db, segment_cache=_seg_cache
            )
        ]
        if not scoped and p.process_id != first_id:
            # 无归属到该工序的料：视为齐套（不挡分段排产）
            by_process.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "kit_ok": True,
                    "shortage_lines": 0,
                    "line_count": 0,
                    "is_first": is_first,
                }
            )
            continue
        shortage_n = 0
        for r in scoped:
            if not ctx.row_dict(r)["kit_ok"]:
                shortage_n += 1
        by_process.append(
            {
                "process_id": p.process_id,
                "process_name": p.process_name,
                "kit_ok": shortage_n == 0,
                "shortage_lines": shortage_n,
                "line_count": len(scoped),
                "is_first": is_first,
            }
        )

    if empty_bom:
        first_kit_ok = False
    elif first_id is not None:
        first_kit_ok = next((x["kit_ok"] for x in by_process if x["is_first"]), kit_ok)
    else:
        first_kit_ok = kit_ok

    # A1a：缺料行预计到料日 + 整单预计齐套日
    from app.services.purchase_service import annotate_rows_with_etas

    shortage_lines = [ln for ln in lines if float(ln.get("shortage_qty") or 0) > 0]
    eta = annotate_rows_with_etas(db, tenant_id, shortage_lines)
    # annotate 改的是 shortage_lines 引用（即 lines 子集），lines 已带 expected_ready_*
    kit_ready = None
    if not kit_ok and shortage_lines:
        kit_ready = (eta.get("by_order_id") or {}).get(str(order.id)) or eta.get("earliest_start")

    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "header_id": getattr(rows[0], "header_id", None) if rows else None,
        "empty_bom": empty_bom,
        "kit_ok": kit_ok,
        "first_kit_ok": first_kit_ok,
        "first_process_id": first_id,
        "first_process_name": first_name,
        "by_process": by_process,
        "include_shared": ctx.include_shared,
        "lines": lines,
        "kit_ready_date": kit_ready,
        "kit_ready_label": "预计齐套日",
        "shortage_lines": sum(1 for x in lines if not x["kit_ok"]),
    }


def get_header_kit(
    db: Session,
    tenant_id: int,
    header_id: int,
    *,
    include_shared: bool | None = None,
) -> dict:
    """执行单头齐套：有桥接壳走旧路径；无壳则认 header 用料/工序。"""
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise MaterialError("header_not_found", "生产单不存在")
    if header.shop_order_id:
        missing = db.scalar(
            select(func.count())
            .select_from(OrderMaterialRequirement)
            .where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == int(header.shop_order_id),
                OrderMaterialRequirement.header_id.is_(None),
            )
        )
        if int(missing or 0) > 0:
            stamp_order_materials_header(
                db,
                tenant_id=tenant_id,
                order_id=int(header.shop_order_id),
                header_id=header.id,
            )
        data = get_order_kit(
            db, tenant_id, int(header.shop_order_id), include_shared=include_shared
        )
        data["header_id"] = header.id
        data["header_no"] = header.header_no
        data["shop_order_id"] = header.shop_order_id
        return data

    rows = ensure_material_snapshot_for_header(db, tenant_id, header)
    db.flush()
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    lines = [ctx.row_dict(r) for r in rows]
    lines.sort(key=lambda x: (x["sort_order"], x["id"]))
    empty_bom = len(lines) == 0
    kit_ok = (not empty_bom) and all(x["kit_ok"] for x in lines)
    processes = list_header_processes(db, tenant_id, header.id)
    first = processes[0] if processes else None
    first_id = first.process_id if first else None
    first_name = first.process_name if first else None
    by_process: list[dict] = []
    for p in processes:
        is_first = first_id is not None and p.process_id == first_id
        if empty_bom:
            by_process.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "kit_ok": False if is_first else True,
                    "shortage_lines": 0,
                    "line_count": 0,
                    "is_first": is_first,
                    "empty_bom": True,
                }
            )
            continue
        _seg_cache: dict[int, int | None] = {}
        scoped = [
            r
            for r in rows
            if row_in_process_scope(
                r, p.process_id, first_process_id=first_id, db=db, segment_cache=_seg_cache
            )
        ]
        if not scoped and p.process_id != first_id:
            by_process.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "kit_ok": True,
                    "shortage_lines": 0,
                    "line_count": 0,
                    "is_first": is_first,
                }
            )
            continue
        shortage_n = sum(1 for r in scoped if not ctx.row_dict(r)["kit_ok"])
        by_process.append(
            {
                "process_id": p.process_id,
                "process_name": p.process_name,
                "kit_ok": shortage_n == 0,
                "shortage_lines": shortage_n,
                "line_count": len(scoped),
                "is_first": is_first,
            }
        )
    first_kit_ok = True
    if first_id is not None and not empty_bom:
        first_kit_ok = all(
            by_process[i]["kit_ok"]
            for i, p in enumerate(processes)
            if p.process_id == first_id
        )
    elif empty_bom:
        first_kit_ok = False
    return {
        "order_id": None,
        "order_no": None,
        "header_id": header.id,
        "header_no": header.header_no,
        "shop_order_id": None,
        "kit_ok": kit_ok,
        "empty_bom": empty_bom,
        "shortage_lines": sum(1 for x in lines if not x["kit_ok"]),
        "lines": lines,
        "by_process": by_process,
        "first_kit_ok": first_kit_ok,
        "first_process_id": first_id,
        "first_process_name": first_name,
        "include_shared": ctx.include_shared,
    }


def list_shortages(
    db: Session,
    tenant_id: int,
    *,
    order_ids: list[int] | None = None,
    include_shared: bool | None = None,
    keyword: str | None = None,
    partner_id: int | None = None,
    order_no: str | None = None,
    rush_only: bool = False,
    hide_purchased: bool = True,
) -> list[dict]:
    """缺料/待采购列表。与订单齐套共用 KitContext（池承诺不重复占用）。"""
    q = select(Order).where(Order.tenant_id == tenant_id)
    if order_ids:
        q = q.where(Order.id.in_(order_ids))
    else:
        q = q.where(Order.status.in_(list(OPEN_KIT_STATUSES)))
    if order_no and order_no.strip():
        q = q.where(Order.order_no.contains(order_no.strip()))
    if rush_only:
        q = q.where(Order.is_rush.is_(True))
    orders = list(db.scalars(q).all())
    orders.sort(key=_order_kit_priority)
    for order in orders:
        ensure_material_snapshot(db, tenant_id, order)
    db.flush()
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    product_ids = {o.own_product_id for o in orders if o.own_product_id}
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.id.in_(product_ids))
        ).all()
    } if product_ids else {}
    kw = (keyword or "").strip().lower()
    header_map = _headers_by_shop_order(db, tenant_id, [o.id for o in orders])
    out: list[dict] = []
    for order in orders:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
        product = products.get(order.own_product_id) if order.own_product_id else None
        size_qtys = order_size_qty_map(order, db)
        header = header_map.get(order.id)
        for row in reqs:
            d = ctx.row_dict(row)
            if d["is_customer_supplied"]:
                continue
            if d["shortage_qty"] <= 0:
                continue
            if hide_purchased and (d["to_buy_qty"] <= 0 or d.get("has_purchase")):
                continue
            if partner_id is not None and d.get("partner_id") != partner_id:
                continue
            d["order_no"] = order.order_no
            d["header_id"] = header.id if header else getattr(row, "header_id", None)
            d["header_no"] = header.header_no if header else None
            d["is_rush"] = bool(getattr(order, "is_rush", False))
            d["product_image_url"] = product.image_url if product else None
            if d.get("usage_by_size") and d.get("size_id"):
                d["order_qty"] = int(size_qtys.get(int(d["size_id"]), 0))
            else:
                d["order_qty"] = int(order.total_qty or 0)
            if kw:
                hay = " ".join(
                    [
                        str(d.get("supplier_product_code") or ""),
                        str(d.get("supplier_product_name") or ""),
                        str(d.get("color_name") or ""),
                        str(d.get("partner_name") or ""),
                        str(d.get("order_no") or ""),
                        str(d.get("header_no") or ""),
                    ]
                ).lower()
                if kw not in hay:
                    continue
            out.append(d)
    db.commit()
    return out


def patch_requirement(
    db: Session,
    tenant_id: int,
    req_id: int,
    *,
    loss_rate: Decimal | None = None,
    loss_fixed_qty: Decimal | None = None,
    qty_per_pair: Decimal | None = None,
    is_customer_supplied: bool | None = None,
    notes: str | None = None,
    arrived_qty: Decimal | None = None,
    consume_segment_id: int | None = None,
    clear_consume_segment: bool = False,
    consume_process_id: int | None = None,
    clear_consume_process: bool = False,
) -> dict:
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    order = db.get(Order, row.order_id)
    if not order:
        raise MaterialError("order_not_found", "订单不存在")
    if loss_rate is not None:
        if loss_rate < 0:
            raise MaterialError("invalid_loss", "损耗率不能为负")
        row.loss_rate = loss_rate
    if loss_fixed_qty is not None:
        if loss_fixed_qty < 0:
            raise MaterialError("invalid_loss", "固定损耗不能为负")
        row.loss_fixed_qty = loss_fixed_qty
    if qty_per_pair is not None:
        row.qty_per_pair = qty_per_pair
    if is_customer_supplied is not None:
        row.is_customer_supplied = is_customer_supplied
        if is_customer_supplied and not (getattr(row, "customer_chase_status", None) or "").strip():
            row.customer_chase_status = "open"
        if is_customer_supplied and row.customer_chase_status not in ("open", "chased", "cleared"):
            row.customer_chase_status = "open"
    if notes is not None:
        row.notes = notes
    if arrived_qty is not None:
        if arrived_qty < 0:
            raise MaterialError("invalid_qty", "已到数量不能为负")
        row.arrived_qty = arrived_qty
    if clear_consume_segment:
        row.consume_segment_id = None
        row.consume_segment_name = None
    elif consume_segment_id is not None:
        seg = db.get(ProcessSegment, consume_segment_id)
        if not seg or seg.tenant_id != tenant_id:
            raise MaterialError("invalid_segment", "消耗工序段不存在")
        row.consume_segment_id = seg.id
        row.consume_segment_name = seg.name
    # 旧工序字段两期过渡保留（D20）；前端 5 期切段后不再传
    if clear_consume_process:
        row.consume_process_id = None
        row.consume_process_name = None
    elif consume_process_id is not None:
        proc = db.get(ProcessDefinition, consume_process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise MaterialError("invalid_process", "消耗工序不存在")
        row.consume_process_id = proc.id
        row.consume_process_name = proc.name
    row.required_qty = required_qty_for_row(row, order)
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def add_requirement(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    supplier_product_id: int,
    qty_per_pair: Decimal = Decimal("1"),
    loss_rate: Decimal = Decimal("0"),
    loss_fixed_qty: Decimal = Decimal("0"),
    is_customer_supplied: bool = False,
) -> dict:
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    sp = db.get(SupplierProduct, supplier_product_id)
    if not sp or sp.tenant_id != tenant_id:
        raise MaterialError("product_not_found", "供应商产品不存在")
    row = OrderMaterialRequirement(
        tenant_id=tenant_id,
        order_id=order_id,
        supplier_product_id=supplier_product_id,
        qty_per_pair=qty_per_pair,
        loss_rate=loss_rate,
        loss_fixed_qty=loss_fixed_qty or Decimal("0"),
        unit_price=sp.unit_price or Decimal("0"),
        required_qty=calc_required_qty(
            qty_per_pair, order.total_qty, loss_rate, loss_fixed_qty or Decimal("0")
        ),
        is_customer_supplied=is_customer_supplied,
        usage_by_size=False,
        size_id=None,
        size_coeff=Decimal("1"),
    )
    apply_consume_snapshot(
        db,
        tenant_id,
        row,
        bom_consume_process_id=None,
        supplier_product_id=supplier_product_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def delete_requirement(db: Session, tenant_id: int, req_id: int) -> None:
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    if (row.arrived_qty or 0) > 0 or (row.issued_qty or 0) > 0:
        raise MaterialError("has_progress", "已有到货/发车间，不能删除")
    linked = db.scalar(
        select(PurchaseOrderLine.id).where(
            PurchaseOrderLine.order_material_requirement_id == req_id,
        )
    )
    if linked:
        raise MaterialError("has_po", "已关联采购行，不能删除")
    db.delete(row)
    db.commit()


def adjust_shared_stock(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    qty_delta: Decimal,
    *,
    size_id: int | None = None,
    unit_cost: Decimal | None = None,
    note: str | None = None,
    user_id: int | None = None,
    ledger_type: SharedLedgerType = SharedLedgerType.adjust,
    ref_type: str | None = None,
    ref_id: int | None = None,
    order_id: int | None = None,
) -> SharedMaterialStock:
    stock = _get_shared_stock(db, tenant_id, supplier_product_id, size_id)
    if not stock:
        stock = SharedMaterialStock(
            tenant_id=tenant_id,
            supplier_product_id=supplier_product_id,
            size_id=size_id,
            qty=Decimal("0"),
            avg_unit_cost=Decimal("0"),
        )
        db.add(stock)
        db.flush()

    new_qty = (stock.qty or Decimal("0")) + qty_delta
    if new_qty < 0:
        raise MaterialError("insufficient_shared", "库存池不足")

    if qty_delta > 0 and unit_cost is not None:
        old_val = (stock.qty or Decimal("0")) * (stock.avg_unit_cost or Decimal("0"))
        new_val = old_val + qty_delta * unit_cost
        stock.avg_unit_cost = (new_val / new_qty).quantize(Decimal("0.0001")) if new_qty else Decimal("0")
    stock.qty = new_qty

    db.add(
        SharedMaterialLedger(
            tenant_id=tenant_id,
            supplier_product_id=supplier_product_id,
            size_id=size_id,
            ledger_type=ledger_type,
            qty_delta=qty_delta,
            unit_cost=unit_cost,
            balance_after=new_qty,
            ref_type=ref_type,
            ref_id=ref_id,
            order_id=order_id,
            note=note,
            created_by=user_id,
        )
    )
    db.flush()
    return stock


def release_to_workshop(
    db: Session,
    tenant_id: int,
    order_id: int | None,
    requirement_id: int,
    qty: Decimal,
    *,
    deduct_shared: bool = False,
    user_id: int | None = None,
    header_id: int | None = None,
) -> dict:
    from app.models import ExecutionHeader, SpecExecutionStatus
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    if inv.get("issue_required") or inv.get("capabilities", {}).get("stock_docs"):
        raise MaterialError("use_stock_docs", "已开通强制领料，请使用领退料单")

    if qty <= 0:
        raise MaterialError("invalid_qty", "发车间数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")

    header: ExecutionHeader | None = None
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise MaterialError("header_not_found", "生产单不存在")
        if header.status == SpecExecutionStatus.cancelled:
            raise MaterialError("header_cancelled", "已取消生产单不能发车间")
        if int(row.header_id or 0) != int(header.id):
            raise MaterialError("not_found", "用料行不存在")
        order_id = header.shop_order_id
    elif order_id:
        if row.order_id != order_id:
            raise MaterialError("not_found", "用料行不存在")
    else:
        raise MaterialError("missing_ref", "请指定生产单")

    if deduct_shared:
        adjust_shared_stock(
            db,
            tenant_id,
            row.supplier_product_id,
            -qty,
            size_id=_req_pool_key(row)[1],
            ledger_type=SharedLedgerType.issue_to_order,
            ref_type="material_release",
            order_id=order_id,
            user_id=user_id,
            note="发车间扣公用库存",
        )

    row.issued_qty = (row.issued_qty or Decimal("0")) + qty
    rel = MaterialRelease(
        tenant_id=tenant_id,
        order_id=order_id,
        header_id=header_id or row.header_id,
        order_material_requirement_id=requirement_id,
        qty=qty,
        deduct_shared=deduct_shared,
        created_by=user_id,
    )
    db.add(rel)
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def _supplier_product_catalog_fields(db: Session, sp: SupplierProduct | None) -> dict:
    """色卡基础信息投影，供库存池等列表与色卡列对齐。"""
    if not sp:
        return {
            "supplier_product_code": None,
            "supplier_product_name": None,
            "image_url": None,
            "partner_id": None,
            "partner_name": None,
            "category_id": None,
            "category_name": None,
            "color_id": None,
            "color_name": None,
            "pricing_unit_id": None,
            "pricing_unit_name": None,
            "unit_price": None,
        }
    cat = db.get(MaterialCategory, sp.category_id) if sp.category_id else None
    color = db.get(Color, sp.color_id) if sp.color_id else None
    unit = db.get(PricingUnit, sp.pricing_unit_id) if sp.pricing_unit_id else None
    partner = db.get(Partner, sp.partner_id) if sp.partner_id else None
    return {
        "supplier_product_code": sp.product_code,
        "supplier_product_name": sp.name,
        "image_url": sp.image_url,
        "partner_id": sp.partner_id,
        "partner_name": partner.name if partner else None,
        "category_id": sp.category_id,
        "category_name": cat.name if cat else None,
        "color_id": sp.color_id,
        "color_name": color.name if color else None,
        "pricing_unit_id": sp.pricing_unit_id,
        "pricing_unit_name": unit.name if unit else None,
        "unit_price": sp.unit_price,
    }


def list_shared_stocks(db: Session, tenant_id: int) -> list[dict]:
    """库存池列表：池余额 + 已占用(未发) + 采购在途（按码料分码展示）。"""
    stocks = list(
        db.scalars(
            select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
        ).all()
    )
    # 占用按 (SKU, size)：按码行用 size_id；未按码行 size_id=None
    occ_rows = db.execute(
        select(
            OrderMaterialRequirement.supplier_product_id,
            OrderMaterialRequirement.usage_by_size,
            OrderMaterialRequirement.size_id,
            func.coalesce(func.sum(OrderMaterialRequirement.arrived_qty), 0),
            func.coalesce(func.sum(OrderMaterialRequirement.issued_qty), 0),
        )
        .where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.is_customer_supplied.is_(False),
        )
        .group_by(
            OrderMaterialRequirement.supplier_product_id,
            OrderMaterialRequirement.usage_by_size,
            OrderMaterialRequirement.size_id,
        )
    ).all()
    arrived_by_key: dict[PoolKey, Decimal] = {}
    issued_by_key: dict[PoolKey, Decimal] = {}
    for sp_id, usage_by_size, size_id, arrived, issued in occ_rows:
        key = _pool_key(
            int(sp_id),
            int(size_id) if usage_by_size and size_id is not None else None,
        )
        arrived_by_key[key] = arrived_by_key.get(key, Decimal("0")) + Decimal(str(arrived or 0))
        issued_by_key[key] = issued_by_key.get(key, Decimal("0")) + Decimal(str(issued or 0))

    in_transit_by_key = in_transit_qty_by_pool_key(db, tenant_id)
    size_ids = {s.size_id for s in stocks if s.size_id} | {
        k[1] for k in arrived_by_key if k[1]
    } | {k[1] for k in in_transit_by_key if k[1]}
    size_map = size_labels(db, size_ids)

    out = []
    seen: set[PoolKey] = set()
    for s in stocks:
        key = _pool_key(s.supplier_product_id, s.size_id)
        seen.add(key)
        sp_id = s.supplier_product_id
        sp = db.get(SupplierProduct, sp_id)
        arrived = arrived_by_key.get(key, Decimal("0"))
        issued = issued_by_key.get(key, Decimal("0"))
        occupied = max(Decimal("0"), arrived - issued)
        pool = s.qty or Decimal("0")
        out.append(
            {
                "id": s.id,
                "supplier_product_id": sp_id,
                **_supplier_product_catalog_fields(db, sp),
                "size_id": s.size_id,
                "size_value": size_map.get(s.size_id) if s.size_id else None,
                "qty": pool,
                "pool_qty": pool,
                "occupied_qty": occupied,
                "on_hand_qty": pool + occupied,
                "in_transit_qty": in_transit_by_key.get(key, Decimal("0")),
                "avg_unit_cost": s.avg_unit_cost,
                "updated_at": s.updated_at,
            }
        )

    extra_keys = set(arrived_by_key.keys()) | set(in_transit_by_key.keys())
    for key in extra_keys:
        if key in seen:
            continue
        sp_id, size_id = key
        arrived = arrived_by_key.get(key, Decimal("0"))
        issued = issued_by_key.get(key, Decimal("0"))
        occupied = max(Decimal("0"), arrived - issued)
        transit = in_transit_by_key.get(key, Decimal("0"))
        if occupied <= 0 and transit <= 0:
            continue
        sp = db.get(SupplierProduct, sp_id)
        out.append(
            {
                "id": None,
                "supplier_product_id": sp_id,
                **_supplier_product_catalog_fields(db, sp),
                "size_id": size_id,
                "size_value": size_map.get(size_id) if size_id else None,
                "qty": Decimal("0"),
                "pool_qty": Decimal("0"),
                "occupied_qty": occupied,
                "on_hand_qty": occupied,
                "in_transit_qty": transit,
                "avg_unit_cost": Decimal("0"),
                "updated_at": None,
            }
        )
    out.sort(
        key=lambda x: (
            x.get("supplier_product_code") or "",
            x.get("size_value") or "",
            x.get("size_id") or 0,
        )
    )
    return out


_PO_STATUS_LABELS = {
    "draft": "草稿",
    "ordered": "已下单",
    "shipped": "已发货",
    "partial_received": "部分到货",
    "received": "已到齐",
    "cancelled": "已取消",
}


def list_shared_occupancy(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None = None,
) -> list[dict]:
    """库存池「已占用」明细：按执行单列出 arrived−issued > 0 的占用。"""
    target = _pool_key(supplier_product_id, size_id)
    sp = db.get(SupplierProduct, supplier_product_id)
    reqs = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.supplier_product_id == supplier_product_id,
            OrderMaterialRequirement.is_customer_supplied.is_(False),
        )
    ).all()
    out: list[dict] = []
    for row in reqs:
        if _req_pool_key(row) != target:
            continue
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        occupied = max(Decimal("0"), arrived - issued)
        if occupied <= 0:
            continue
        order = db.get(Order, row.order_id) if row.order_id else None
        header = db.get(ExecutionHeader, row.header_id) if getattr(row, "header_id", None) else None
        so_id = (order.sales_order_id if order else None) or (
            header.sales_order_id if header else None
        )
        so = db.get(SalesOrder, so_id) if so_id else None
        out.append(
            {
                "order_id": row.order_id,
                "order_no": (header.header_no if header else None)
                or (order.order_no if order else None),
                "header_id": header.id if header else None,
                "header_no": header.header_no if header else None,
                "sales_order_id": so_id,
                "sales_order_no": so.order_no if so else None,
                "customer_name": (so.customer_name if so else None)
                or (order.customer_name if order else None),
                "supplier_product_id": supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "image_url": sp.image_url if sp else None,
                "occupied_qty": occupied,
                "delivery_date": (header.delivery_date if header else None)
                or (order.delivery_date if order else None),
            }
        )
    out.sort(
        key=lambda x: (
            str(x.get("delivery_date") or "9999-99-99"),
            x.get("sales_order_no") or "",
            x.get("order_no") or "",
        )
    )
    return out


def list_shared_in_transit(
    db: Session,
    tenant_id: int,
    supplier_product_id: int,
    size_id: int | None = None,
) -> list[dict]:
    """库存池「在途」明细：未收完的采购行。"""
    target = _pool_key(supplier_product_id, size_id)
    lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.supplier_product_id == supplier_product_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
        .options(selectinload(PurchaseOrderLine.purchase_order))
    ).all()
    out: list[dict] = []
    for ln in lines:
        if _pool_key(ln.supplier_product_id, ln.size_id) != target:
            continue
        open_qty = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
        if open_qty <= 0:
            continue
        po = ln.purchase_order or db.get(PurchaseOrder, ln.purchase_order_id)
        partner = db.get(Partner, po.partner_id) if po and po.partner_id else None
        prod = db.get(Order, ln.order_id) if ln.order_id else None
        header_no = None
        if getattr(ln, "order_material_requirement_id", None):
            req = db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
            if req and getattr(req, "header_id", None):
                hdr = db.get(ExecutionHeader, req.header_id)
                header_no = hdr.header_no if hdr else None
        status = po.status.value if po and hasattr(po.status, "value") else (po.status if po else None)
        out.append(
            {
                "purchase_order_id": po.id if po else ln.purchase_order_id,
                "po_no": po.po_no if po else None,
                "supplier_name": partner.name if partner else None,
                "status": status,
                "status_label": _PO_STATUS_LABELS.get(str(status), str(status or "")),
                "qty": ln.qty or Decimal("0"),
                "received_qty": ln.received_qty or Decimal("0"),
                "open_qty": open_qty,
                "expected_date": po.expected_date if po else None,
                "order_id": ln.order_id,
                "order_no": header_no or (prod.order_no if prod else None),
                "header_no": header_no,
            }
        )
    out.sort(
        key=lambda x: (
            str(x.get("expected_date") or "9999-99-99"),
            x.get("po_no") or "",
        )
    )
    return out


_LEDGER_LABELS = {
    "unallocated_receive": "采购入池",
    "receive_surplus": "超收入池",
    "allocate_to_order": "锁料到单",
    "issue_to_order": "发车间扣池",
    "release_from_order": "退回库存池",
    "adjust": "库存调整",
}


def list_shared_ledgers(
    db: Session,
    tenant_id: int,
    *,
    supplier_product_id: int | None = None,
    size_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """库存池出入流水。"""
    q = (
        select(SharedMaterialLedger)
        .where(SharedMaterialLedger.tenant_id == tenant_id)
        .order_by(SharedMaterialLedger.id.desc())
        .limit(min(limit, 500))
    )
    if supplier_product_id:
        q = q.where(SharedMaterialLedger.supplier_product_id == supplier_product_id)
    if size_id is not None:
        q = q.where(SharedMaterialLedger.size_id == size_id)
    rows = list(db.scalars(q).all())
    size_map = size_labels(db, {ln.size_id for ln in rows if ln.size_id})
    out = []
    for ln in rows:
        sp = db.get(SupplierProduct, ln.supplier_product_id)
        order = db.get(Order, ln.order_id) if ln.order_id else None
        lt = ln.ledger_type.value if hasattr(ln.ledger_type, "value") else str(ln.ledger_type)
        out.append(
            {
                "id": ln.id,
                "supplier_product_id": ln.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "size_id": ln.size_id,
                "size_value": size_map.get(ln.size_id) if ln.size_id else None,
                "ledger_type": lt,
                "ledger_type_label": _LEDGER_LABELS.get(lt, lt),
                "qty_delta": ln.qty_delta,
                "unit_cost": ln.unit_cost,
                "balance_after": ln.balance_after,
                "ref_type": ln.ref_type,
                "ref_id": ln.ref_id,
                "order_id": ln.order_id,
                "order_no": order.order_no if order else None,
                "note": ln.note,
                "created_at": ln.created_at,
            }
        )
    return out


def allocate_from_pool(
    db: Session,
    tenant_id: int,
    order_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
    commit: bool = True,
    ref_type: str = "manual_allocate",
    ref_id: int | None = None,
    note: str | None = None,
) -> dict:
    """从库存池硬分配到订单占用（arrived）。"""
    if qty <= 0:
        raise MaterialError("invalid_qty", "分配数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id or row.order_id != order_id:
        raise MaterialError("not_found", "用料行不存在")
    if row.is_customer_supplied:
        raise MaterialError("customer_supplied", "客供料不从库存池分配")
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")
    if order.status == OrderStatus.cancelled:
        raise MaterialError("order_cancelled", "已取消订单不能分配")

    adjust_shared_stock(
        db,
        tenant_id,
        row.supplier_product_id,
        -qty,
        size_id=_req_pool_key(row)[1],
        unit_cost=row.unit_price,
        ledger_type=SharedLedgerType.allocate_to_order,
        ref_type=ref_type,
        ref_id=ref_id if ref_id is not None else order_id,
        order_id=order_id,
        user_id=user_id,
        note=note or f"分配到订单 {order.order_no}",
    )
    row.arrived_qty = (row.arrived_qty or Decimal("0")) + qty
    if commit:
        db.commit()
    else:
        db.flush()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def deallocate_to_pool(
    db: Session,
    tenant_id: int,
    order_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
) -> dict:
    """将订单未发占用回收到库存池。"""
    if qty <= 0:
        raise MaterialError("invalid_qty", "回收数量须大于 0")
    row = db.get(OrderMaterialRequirement, requirement_id)
    if not row or row.tenant_id != tenant_id or row.order_id != order_id:
        raise MaterialError("not_found", "用料行不存在")
    if row.is_customer_supplied:
        raise MaterialError("customer_supplied", "客供料不走库存池回收")
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "订单不存在")

    arrived = row.arrived_qty or Decimal("0")
    issued = row.issued_qty or Decimal("0")
    reusable = max(Decimal("0"), arrived - issued)
    if qty > reusable:
        raise MaterialError(
            "exceed_reusable",
            f"可回收数量不足（已占用 {arrived}，已发 {issued}，可回收 {reusable}）",
        )

    adjust_shared_stock(
        db,
        tenant_id,
        row.supplier_product_id,
        qty,
        size_id=_req_pool_key(row)[1],
        unit_cost=row.unit_price,
        ledger_type=SharedLedgerType.release_from_order,
        ref_type="manual_deallocate",
        ref_id=order_id,
        order_id=order_id,
        user_id=user_id,
        note=f"手动回收自订单 {order.order_no}",
    )
    row.arrived_qty = arrived - qty
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    return ctx.row_dict(row)


def list_allocate_candidates(
    db: Session,
    tenant_id: int,
    *,
    keyword: str | None = None,
) -> list[dict]:
    """可从池分配的行：有缺口且池有货；以及有可回收占用的行。"""
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    orders.sort(key=_order_kit_priority)
    order_by_id = {o.id: o for o in orders}
    for order in orders:
        ensure_material_snapshot(db, tenant_id, order)
    db.flush()

    stocks = {
        _pool_key(s.supplier_product_id, s.size_id): (s.qty or Decimal("0"))
        for s in db.scalars(
            select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
        ).all()
    }
    kw = (keyword or "").strip().lower()
    out: list[dict] = []
    for order in orders:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
        for row in reqs:
            if row.is_customer_supplied:
                continue
            need = _pool_need(row)
            key = _req_pool_key(row)
            pool = stocks.get(key, Decimal("0"))
            arrived = row.arrived_qty or Decimal("0")
            issued = row.issued_qty or Decimal("0")
            reusable = max(Decimal("0"), arrived - issued)
            if need <= 0 and reusable <= 0:
                continue
            if need > 0 and pool <= 0 and reusable <= 0:
                continue
            sp = db.get(SupplierProduct, row.supplier_product_id)
            size_id = key[1]
            size_value = None
            if size_id:
                sz = db.get(Size, size_id)
                size_value = sz.size_value if sz else None
            d = {
                "id": row.id,
                "order_id": order.id,
                "order_no": order.order_no,
                "is_rush": bool(getattr(order, "is_rush", False)),
                "delivery_date": order.delivery_date,
                "supplier_product_id": row.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "usage_by_size": bool(getattr(row, "usage_by_size", False)),
                "size_id": size_id,
                "size_value": size_value,
                "required_qty": row.required_qty or Decimal("0"),
                "arrived_qty": arrived,
                "issued_qty": issued,
                "need_qty": need,
                "pool_qty": pool,
                "allocatable_qty": min(need, pool) if need > 0 and pool > 0 else Decimal("0"),
                "reusable_qty": reusable,
            }
            out.append(d)
    # K4-B：无桥接壳的执行单用料
    header_only = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.is_(None),
                OrderMaterialRequirement.header_id.isnot(None),
            )
        ).all()
    )
    header_ids = {int(r.header_id) for r in header_only if r.header_id}
    headers = {
        h.id: h
        for h in db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.id.in_(list(header_ids) or [-1]),
                ExecutionHeader.status != SpecExecutionStatus.cancelled,
            )
        ).all()
    }
    for row in header_only:
        hdr = headers.get(int(row.header_id)) if row.header_id else None
        if not hdr:
            continue
        if row.is_customer_supplied:
            continue
        need = _pool_need(row)
        key = _req_pool_key(row)
        pool = stocks.get(key, Decimal("0"))
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        reusable = max(Decimal("0"), arrived - issued)
        if need <= 0 and reusable <= 0:
            continue
        if need > 0 and pool <= 0 and reusable <= 0:
            continue
        sp = db.get(SupplierProduct, row.supplier_product_id)
        size_id = key[1]
        size_value = None
        if size_id:
            sz = db.get(Size, size_id)
            size_value = sz.size_value if sz else None
        out.append(
            {
                "id": row.id,
                "order_id": None,
                "order_no": None,
                "header_id": hdr.id,
                "header_no": hdr.header_no,
                "is_rush": bool(getattr(hdr, "is_rush", False)),
                "delivery_date": hdr.delivery_date,
                "supplier_product_id": row.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "usage_by_size": bool(getattr(row, "usage_by_size", False)),
                "size_id": size_id,
                "size_value": size_value,
                "required_qty": row.required_qty or Decimal("0"),
                "arrived_qty": arrived,
                "issued_qty": issued,
                "need_qty": need,
                "pool_qty": pool,
                "allocatable_qty": min(need, pool) if need > 0 and pool > 0 else Decimal("0"),
                "reusable_qty": reusable,
            }
        )
    header_map = _headers_by_shop_order(db, tenant_id, [o.id for o in orders])
    for d in out:
        if d.get("header_id"):
            continue
        h = header_map.get(int(d["order_id"])) if d.get("order_id") else None
        d["header_id"] = h.id if h else None
        d["header_no"] = h.header_no if h else None
    if kw:
        filtered = []
        for d in out:
            hay = " ".join(
                [
                    str(d.get("supplier_product_code") or ""),
                    str(d.get("supplier_product_name") or ""),
                    str(d.get("size_value") or ""),
                    str(d.get("order_no") or ""),
                    str(d.get("header_no") or ""),
                ]
            ).lower()
            if kw in hay:
                filtered.append(d)
        return filtered
    return out


def stock_reconcile_report(db: Session, tenant_id: int) -> dict:
    """按物料对账：库存池 + 订单未发占用 + PO 在途。

    说明：切仓前「直接挂 arrived」的占用不会出现在池流水里，属正常历史；
    账面解释量 = pool + occupancy；实物盘点需另行对照。
    """
    from app.services.inventory_settings import get_inventory_by_tenant_id

    inv = get_inventory_by_tenant_id(db, tenant_id)
    open_orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    open_ids = [o.id for o in open_orders]

    # occupancy & anomalies by SKU
    occupancy: dict[int, Decimal] = {}
    anomaly_rows: list[dict] = []
    if open_ids:
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id.in_(open_ids),
            )
        ).all()
        order_no = {o.id: o.order_no for o in open_orders}
        for row in reqs:
            if row.is_customer_supplied:
                continue
            arrived = row.arrived_qty or Decimal("0")
            issued = row.issued_qty or Decimal("0")
            if arrived < issued:
                sp = db.get(SupplierProduct, row.supplier_product_id)
                anomaly_rows.append(
                    {
                        "type": "arrived_lt_issued",
                        "order_id": row.order_id,
                        "order_no": order_no.get(row.order_id),
                        "requirement_id": row.id,
                        "supplier_product_id": row.supplier_product_id,
                        "supplier_product_code": sp.product_code if sp else None,
                        "arrived_qty": arrived,
                        "issued_qty": issued,
                        "message": "已占用小于已发，数据异常",
                    }
                )
            reusable = max(Decimal("0"), arrived - issued)
            if reusable > 0:
                occupancy[row.supplier_product_id] = (
                    occupancy.get(row.supplier_product_id, Decimal("0")) + reusable
                )

    # pool
    stocks = {
        s.supplier_product_id: s
        for s in db.scalars(
            select(SharedMaterialStock).where(SharedMaterialStock.tenant_id == tenant_id)
        ).all()
    }

    # in-transit by SKU (all open PO lines, not only linked to req)
    transit: dict[int, Decimal] = {}
    po_lines = db.scalars(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    for ln in po_lines:
        open_qty = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
        if open_qty > 0:
            transit[ln.supplier_product_id] = transit.get(ln.supplier_product_id, Decimal("0")) + open_qty

    sp_ids = set(stocks.keys()) | set(occupancy.keys()) | set(transit.keys())
    lines: list[dict] = []
    for sp_id in sorted(sp_ids):
        sp = db.get(SupplierProduct, sp_id)
        pool_qty = stocks[sp_id].qty if sp_id in stocks else Decimal("0")
        occ = occupancy.get(sp_id, Decimal("0"))
        tr = transit.get(sp_id, Decimal("0"))
        lines.append(
            {
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "pool_qty": pool_qty,
                "order_occupancy_qty": occ,
                "in_transit_qty": tr,
                "book_total_qty": pool_qty + occ,
                "avg_unit_cost": stocks[sp_id].avg_unit_cost if sp_id in stocks else None,
            }
        )

    lines.sort(key=lambda x: (x.get("supplier_product_code") or "", x["supplier_product_id"]))
    return {
        "inventory": inv,
        "summary": {
            "sku_count": len(lines),
            "pool_total": sum((x["pool_qty"] for x in lines), Decimal("0")),
            "occupancy_total": sum((x["order_occupancy_qty"] for x in lines), Decimal("0")),
            "in_transit_total": sum((x["in_transit_qty"] for x in lines), Decimal("0")),
            "anomaly_count": len(anomaly_rows),
            "open_order_count": len(open_orders),
        },
        "lines": lines,
        "anomalies": anomaly_rows,
        "notes": [
            "订单占用 = 未取消/在制单上 max(已占用 − 已发，0)；切仓前直接挂单的占用也计入，不一定有对应入池流水。",
            "账面解释量（现存量）= 可用 + 占用；不含在途。在途单独列示，便于跟采购对账。",
            "实物盘点请用现存量对照仓库实数；差异用库存池「调整」处理。",
        ],
    }


def order_kit_summary(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    include_shared: bool | None = None,
    ctx: KitContext | None = None,
) -> dict:
    """单订单齐套摘要；与列表/缺料/看板共用同一套池承诺。"""
    context = ctx or build_kit_context(db, tenant_id, include_shared=include_shared)
    return context.summary_for_order(order_id)


def order_kit_summaries(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    include_shared: bool | None = None,
) -> dict[int, dict]:
    if not order_ids:
        return {}
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    return {oid: ctx.summary_for_order(oid) for oid in order_ids}


def header_kit_summaries(
    db: Session,
    tenant_id: int,
    header_ids: list[int],
    *,
    include_shared: bool | None = None,
) -> dict[int, dict]:
    """列表用：池建一次，按执行单头打齐套/开裁齐套。详情/开裁仍走 get_header_kit。"""
    ids = [int(x) for x in header_ids if x]
    if not ids:
        return {}
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.id.in_(ids),
            )
        ).all()
    )
    by_id = {int(h.id): h for h in headers}
    shop_ids = [int(h.shop_order_id) for h in headers if h.shop_order_id]
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                or_(
                    OrderMaterialRequirement.header_id.in_(ids),
                    OrderMaterialRequirement.order_id.in_(shop_ids or [-1]),
                ),
            )
        ).all()
    )
    reqs_by_header: dict[int, list[OrderMaterialRequirement]] = {}
    reqs_by_order: dict[int, list[OrderMaterialRequirement]] = {}
    for row in reqs:
        if row.header_id:
            reqs_by_header.setdefault(int(row.header_id), []).append(row)
        if row.order_id:
            reqs_by_order.setdefault(int(row.order_id), []).append(row)
    procs = list(
        db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                or_(
                    OrderProcess.header_id.in_(ids),
                    OrderProcess.order_id.in_(shop_ids or [-1]),
                ),
            )
            .order_by(OrderProcess.id)
        ).all()
    )
    procs_by_header: dict[int, list[OrderProcess]] = {}
    procs_by_order: dict[int, list[OrderProcess]] = {}
    for proc in procs:
        if proc.header_id:
            procs_by_header.setdefault(int(proc.header_id), []).append(proc)
        if proc.order_id:
            procs_by_order.setdefault(int(proc.order_id), []).append(proc)
    # 批量预取所有用料行的采购量与关联表，避免 summary 逐行查询
    totals = ctx._load_req_purchase_totals_batch([int(r.id) for r in reqs])
    zero = (Decimal("0"), Decimal("0"), Decimal("0"))
    ctx._req_purchase_totals = {int(r.id): totals.get(int(r.id), zero) for r in reqs}
    ctx._load_row_lookups_batch(reqs)
    out: dict[int, dict] = {}
    for hid in ids:
        header = by_id.get(hid)
        if not header:
            continue
        rows = reqs_by_header.get(hid)
        if not rows and header.shop_order_id:
            rows = reqs_by_order.get(int(header.shop_order_id), [])
        processes = procs_by_header.get(hid)
        if not processes and header.shop_order_id:
            processes = procs_by_order.get(int(header.shop_order_id), [])
        summary = ctx.summary_for_header(hid, rows=rows or [], processes=processes or [])
        summary["header_no"] = header.header_no
        summary["shop_order_id"] = header.shop_order_id
        # 采购状态聚合：齐套/采购中/缺材料（供列表「采购」列，参考订单管理采购列）
        summary["material_status"] = _aggregate_material_status(ctx, rows or [], summary)
        out[hid] = summary
    return out


def _aggregate_material_status(
    ctx: "KitContext",
    rows: list[OrderMaterialRequirement],
    summary: dict,
) -> str | None:
    """按用料行聚合采购状态：kit_ok=齐套；缺料但有采购在途/草稿=采购中；否则缺材料。"""
    if summary.get("empty_bom") or not rows:
        return None
    if summary.get("kit_ok"):
        return "kit_ok"
    for row in rows:
        rd = ctx.row_dict(row)
        if not rd.get("kit_ok"):
            if (
                rd.get("has_purchase")
                or float(rd.get("in_transit_qty") or 0) > 0
                or float(rd.get("draft_qty") or 0) > 0
            ):
                return "purchasing"
    return "short"


def stamp_order_materials_execution(
    db: Session,
    *,
    tenant_id: int,
    order_id: int,
    execution_id: int,
) -> int:
    """用料快照双写 execution_id（齐套/领料仍认 order_id）。"""
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order_id,
            )
        ).all()
    )
    for row in rows:
        row.execution_id = execution_id
    return len(rows)


def stamp_order_materials_header(
    db: Session,
    *,
    tenant_id: int,
    order_id: int,
    header_id: int,
    execution_id: int | None = None,
    clear_execution_if_none: bool = False,
) -> int:
    """用料快照挂执行单头；可选钉/清空码明细 execution_id。"""
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order_id,
            )
        ).all()
    )
    for row in rows:
        row.header_id = header_id
        if execution_id is not None:
            row.execution_id = execution_id
        elif clear_execution_if_none:
            row.execution_id = None
    db.flush()
    return len(rows)


def stamp_order_processes_header(
    db: Session,
    *,
    tenant_id: int,
    order_id: int,
    header_id: int,
) -> int:
    """K4：桥接单工序/派工挂执行单头。"""
    procs = list(
        db.scalars(
            select(OrderProcess).where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.order_id == order_id,
            )
        ).all()
    )
    for p in procs:
        p.header_id = header_id
    assigns = list(
        db.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.tenant_id == tenant_id,
                OrderProcessAssignment.order_id == order_id,
            )
        ).all()
    )
    for a in assigns:
        a.header_id = header_id
    # 壳打标
    order = db.get(Order, order_id)
    if order and order.tenant_id == tenant_id:
        order.is_bridge = True
        note = (order.notes or "").strip()
        if note and not note.startswith("[桥接]"):
            order.notes = f"[桥接] {note}"
        elif not note:
            order.notes = "[桥接]"
    db.flush()
    return len(procs)


def header_size_qty_map(db: Session, header: ExecutionHeader) -> dict[int, int]:
    """执行单头按 size_id 汇总双数（活跃码明细）。"""
    from app.models import SpecExecutionOrder, SpecExecutionStatus

    rows = list(
        db.scalars(
            select(SpecExecutionOrder).where(
                SpecExecutionOrder.header_id == header.id,
                SpecExecutionOrder.tenant_id == header.tenant_id,
                SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
            )
        ).all()
    )
    out: dict[int, int] = {}
    for r in rows:
        if not r.size_id:
            continue
        out[int(r.size_id)] = out.get(int(r.size_id), 0) + int(r.total_qty or 0)
    return out


def list_header_processes(db: Session, tenant_id: int, header_id: int) -> list[OrderProcess]:
    return list(
        db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.header_id == header_id,
            )
            .order_by(OrderProcess.id)
        ).all()
    )


def ensure_header_processes(
    db: Session,
    *,
    tenant_id: int,
    header: ExecutionHeader,
    delivery_date=None,
) -> list[OrderProcess]:
    """K4-B：无桥接壳时按产品工艺种子工序（header_id，order_id 空）。"""
    from app.models import OrderProcessStatus, ProcessDefinition
    from app.services.order_service import OrderError, order_labors_for_route

    existing = list_header_processes(db, tenant_id, header.id)
    if existing:
        # 同步计划量
        for p in existing:
            p.plan_qty = int(header.total_qty or 0)
        db.flush()
        return existing
    try:
        labors = order_labors_for_route(db, tenant_id, header.own_product_id)
    except OrderError as e:
        raise MaterialError(e.code, e.message) from e
    out: list[OrderProcess] = []
    total = int(header.total_qty or 0)
    for labor in labors:
        process = db.get(ProcessDefinition, labor.process_id)
        if not process:
            continue
        row = OrderProcess(
            tenant_id=tenant_id,
            order_id=None,
            header_id=header.id,
            process_id=process.id,
            process_name=labor.process_name or process.name,
            process_type=process.type,
            part_id=getattr(labor, "part_id", None),
            segment_id=process.segment_id,  # 工序段重构 7.1：从工序继承段快照
            plan_qty=total,
            completed_qty=0,
            defect_qty=0,
            rework_qty=0,
            status=OrderProcessStatus.pending,
            end_date=delivery_date or header.delivery_date,
        )
        db.add(row)
        out.append(row)
    db.flush()
    return out


def ensure_material_snapshot_for_header(
    db: Session,
    tenant_id: int,
    header: ExecutionHeader,
) -> list[OrderMaterialRequirement]:
    """K4-B：用料快照挂执行单头（无桥接壳）。"""
    existing = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header.id,
            )
        ).all()
    )
    if existing:
        return existing
    return refresh_from_bom_for_header(db, tenant_id, header, keep_progress=False)


def refresh_from_bom_for_header(
    db: Session,
    tenant_id: int,
    header: ExecutionHeader,
    *,
    keep_progress: bool = True,
) -> list[OrderMaterialRequirement]:
    """从产品 BOM 生成挂 header 的用料行（order_id 空）。"""
    materials = list(
        db.scalars(
            select(OwnProductMaterial)
            .where(
                OwnProductMaterial.tenant_id == tenant_id,
                OwnProductMaterial.own_product_id == header.own_product_id,
            )
            .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
        ).all()
    )
    materials = filter_bom_for_colorway(materials, getattr(header, "color_id", None))
    size_qtys = header_size_qty_map(db, header)
    missing: list[str] = []
    labels = size_labels(db, set(size_qtys.keys()))
    for m in materials:
        if not getattr(m, "usage_by_size", False):
            continue
        table_id = getattr(m, "size_usage_table_id", None)
        if not table_id:
            raise MaterialError("missing_size_table", "按码用量物料未绑定用量码表")
        table = db.get(MaterialSizeUsageTable, table_id)
        if not table or table.tenant_id != tenant_id:
            raise MaterialError("missing_size_table", "用量码表不存在")
        coeff_map = load_size_coeff_map(db, tenant_id, table_id)
        sp = db.get(SupplierProduct, m.supplier_product_id)
        sp_label = (sp.product_code if sp else None) or str(m.supplier_product_id)
        for sid in size_qtys:
            if sid not in coeff_map:
                missing.append(f"{sp_label}/{labels.get(sid) or sid}")
    if missing:
        raise MaterialError(
            "missing_size_coeff",
            "用量码表缺少尺码系数：" + "、".join(missing[:20])
            + ("…" if len(missing) > 20 else ""),
        )

    by_key: dict[PoolKey, OrderMaterialRequirement] = {}
    if keep_progress:
        for row in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header.id,
            )
        ).all():
            by_key[_req_match_key(row.supplier_product_id, row.size_id if row.usage_by_size else None)] = row
    else:
        for row in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header.id,
            )
        ).all():
            db.delete(row)
        db.flush()

    kept_ids: set[int] = set()
    result: list[OrderMaterialRequirement] = []
    sort_base = 0
    total_qty = int(header.total_qty or 0)

    def _upsert_row(
        *,
        m: OwnProductMaterial,
        size_id: int | None,
        size_coeff: Decimal,
        usage_by_size: bool,
        required: Decimal,
        sort_order: int,
        loss_rate: Decimal,
        loss_fixed_qty: Decimal,
    ) -> OrderMaterialRequirement:
        key = _req_match_key(m.supplier_product_id, size_id if usage_by_size else None)
        bom_pid = getattr(m, "consume_process_id", None)
        bom_sid = getattr(m, "consume_segment_id", None)
        if key in by_key and keep_progress:
            row = by_key[key]
            row.qty_per_pair = m.qty
            row.unit_price = m.unit_price
            row.loss_rate = loss_rate
            row.loss_fixed_qty = loss_fixed_qty
            row.required_qty = required
            row.sort_order = sort_order
            row.usage_by_size = usage_by_size
            row.size_id = size_id if usage_by_size else None
            row.size_coeff = size_coeff if usage_by_size else Decimal("1")
            row.header_id = header.id
            row.order_id = None
            apply_consume_snapshot(
                db,
                tenant_id,
                row,
                bom_consume_process_id=bom_pid,
                supplier_product_id=m.supplier_product_id,
            )
            if row.id:
                kept_ids.add(row.id)
            result.append(row)
            return row
        row = OrderMaterialRequirement(
            tenant_id=tenant_id,
            order_id=None,
            header_id=header.id,
            supplier_product_id=m.supplier_product_id,
            qty_per_pair=m.qty,
            loss_rate=loss_rate,
            loss_fixed_qty=loss_fixed_qty,
            unit_price=m.unit_price or Decimal("0"),
            required_qty=required,
            arrived_qty=Decimal("0"),
            issued_qty=Decimal("0"),
            is_customer_supplied=False,
            sort_order=sort_order,
            usage_by_size=usage_by_size,
            size_id=size_id if usage_by_size else None,
            size_coeff=size_coeff if usage_by_size else Decimal("1"),
        )
        apply_consume_snapshot(
            db,
            tenant_id,
            row,
            bom_consume_segment_id=bom_sid,
            bom_consume_process_id=bom_pid,
            supplier_product_id=m.supplier_product_id,
        )
        db.add(row)
        result.append(row)
        return row

    for i, m in enumerate(materials):
        usage_by_size = bool(getattr(m, "usage_by_size", False))
        bom_loss_rate = getattr(m, "loss_rate", None) or Decimal("0")
        bom_loss_fixed = getattr(m, "loss_fixed_qty", None) or Decimal("0")
        if usage_by_size:
            if not size_qtys:
                raise MaterialError("no_order_sizes", "按码用量需要生产单色码明细")
            coeff_map = load_size_coeff_map(db, tenant_id, int(m.size_usage_table_id))
            first_sid = True
            for sid, sqty in sorted(size_qtys.items(), key=lambda x: x[0]):
                coeff = coeff_map[sid]
                fixed = bom_loss_fixed if first_sid else Decimal("0")
                first_sid = False
                req = calc_required_qty_sized(m.qty, sqty, coeff, bom_loss_rate, fixed)
                _upsert_row(
                    m=m,
                    size_id=sid,
                    size_coeff=coeff,
                    usage_by_size=True,
                    required=req,
                    sort_order=(m.sort_order if m.sort_order is not None else i) * 1000 + sort_base,
                    loss_rate=bom_loss_rate,
                    loss_fixed_qty=fixed,
                )
                sort_base += 1
        else:
            req = calc_required_qty(m.qty, total_qty, bom_loss_rate, bom_loss_fixed)
            _upsert_row(
                m=m,
                size_id=None,
                size_coeff=Decimal("1"),
                usage_by_size=False,
                required=req,
                sort_order=m.sort_order if m.sort_order is not None else i,
                loss_rate=bom_loss_rate,
                loss_fixed_qty=bom_loss_fixed,
            )

    if keep_progress:
        for row in by_key.values():
            if row.id and row.id not in kept_ids and row.arrived_qty == 0 and row.issued_qty == 0:
                db.delete(row)
    # B1d：承接外包/来料加工——用料全标客供（上家供料）
    if is_subcontract_in_sales_order(db, header.sales_order_id):
        mark_requirements_customer_supplied(result)
    db.flush()
    return result


def resolve_header_for_order(db: Session, tenant_id: int, order_id: int) -> ExecutionHeader | None:
    """桥接生产单 → 执行单头（取最新）。"""
    return db.scalar(
        select(ExecutionHeader)
        .where(
            ExecutionHeader.tenant_id == tenant_id,
            ExecutionHeader.shop_order_id == order_id,
        )
        .order_by(ExecutionHeader.id.desc())
        .limit(1)
    )


def resolve_order_from_header(db: Session, tenant_id: int, header_id: int):
    """执行单头 → 桥接生产单（含 items/processes）。无桥接壳则返回 None。"""
    from sqlalchemy.orm import selectinload

    from app.models import Order

    header = db.scalar(
        select(ExecutionHeader).where(
            ExecutionHeader.id == header_id,
            ExecutionHeader.tenant_id == tenant_id,
        )
    )
    if not header or not header.shop_order_id:
        return None, header
    order = db.scalar(
        select(Order)
        .where(Order.id == header.shop_order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items), selectinload(Order.processes))
    )
    return order, header


def resolve_header_id_for_write(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    execution_id: int | None = None,
    header_id: int | None = None,
) -> int | None:
    """开裁/报工写账时解析 header_id（显式 > 码明细 > 桥接单）。"""
    if header_id:
        return int(header_id)
    if execution_id:
        from app.models import SpecExecutionOrder

        exe = db.get(SpecExecutionOrder, int(execution_id))
        if exe and exe.tenant_id == tenant_id and exe.header_id:
            return int(exe.header_id)
    if order_id:
        h = resolve_header_for_order(db, tenant_id, int(order_id))
        if h:
            return int(h.id)
    return None


def _headers_by_shop_order(
    db: Session, tenant_id: int, order_ids: list[int]
) -> dict[int, ExecutionHeader]:
    ids = [int(x) for x in order_ids if x]
    if not ids:
        return {}
    rows = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.shop_order_id.in_(ids),
            )
        ).all()
    )
    out: dict[int, ExecutionHeader] = {}
    for h in rows:
        sid = int(h.shop_order_id) if h.shop_order_id else None
        if sid is None:
            continue
        prev = out.get(sid)
        if prev is None or h.id > prev.id:
            out[sid] = h
    return out


def allocate_from_pool_for_header(
    db: Session,
    tenant_id: int,
    header_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
    commit: bool = True,
    ref_type: str = "manual_allocate",
    ref_id: int | None = None,
    note: str | None = None,
) -> dict:
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise MaterialError("header_not_found", "生产单不存在")
    if header.shop_order_id:
        stamp_order_materials_header(
            db, tenant_id=tenant_id, order_id=int(header.shop_order_id), header_id=header.id
        )
        row = allocate_from_pool(
            db,
            tenant_id,
            int(header.shop_order_id),
            requirement_id,
            qty,
            user_id=user_id,
            commit=commit,
            ref_type=ref_type,
            ref_id=ref_id if ref_id is not None else header.id,
            note=note or f"锁料到生产单 {header.header_no}",
        )
        row["header_id"] = header.id
        row["header_no"] = header.header_no
        return row

    # K4-B：无桥接壳，直接锁到 header 用料行
    if qty <= 0:
        raise MaterialError("invalid_qty", "分配数量须大于 0")
    req = db.get(OrderMaterialRequirement, requirement_id)
    if (
        not req
        or req.tenant_id != tenant_id
        or int(req.header_id or 0) != int(header.id)
    ):
        raise MaterialError("not_found", "用料行不存在")
    if req.is_customer_supplied:
        raise MaterialError("customer_supplied", "客供料不从库存池分配")
    adjust_shared_stock(
        db,
        tenant_id,
        req.supplier_product_id,
        -qty,
        size_id=_req_pool_key(req)[1],
        unit_cost=req.unit_price,
        ledger_type=SharedLedgerType.allocate_to_order,
        ref_type=ref_type,
        ref_id=ref_id if ref_id is not None else header.id,
        order_id=None,
        user_id=user_id,
        note=note or f"锁料到生产单 {header.header_no}",
    )
    req.arrived_qty = (req.arrived_qty or Decimal("0")) + qty
    if commit:
        db.commit()
    else:
        db.flush()
    ctx = build_kit_context(db, tenant_id)
    out = ctx.row_dict(req)
    out["header_id"] = header.id
    out["header_no"] = header.header_no
    return out


def deallocate_to_pool_for_header(
    db: Session,
    tenant_id: int,
    header_id: int,
    requirement_id: int,
    qty: Decimal,
    *,
    user_id: int | None = None,
) -> dict:
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise MaterialError("header_not_found", "生产单不存在")
    if header.shop_order_id:
        row = deallocate_to_pool(
            db,
            tenant_id,
            int(header.shop_order_id),
            requirement_id,
            qty,
            user_id=user_id,
        )
        row["header_id"] = header.id
        row["header_no"] = header.header_no
        return row

    if qty <= 0:
        raise MaterialError("invalid_qty", "回收数量须大于 0")
    req = db.get(OrderMaterialRequirement, requirement_id)
    if (
        not req
        or req.tenant_id != tenant_id
        or int(req.header_id or 0) != int(header.id)
    ):
        raise MaterialError("not_found", "用料行不存在")
    arrived = req.arrived_qty or Decimal("0")
    issued = req.issued_qty or Decimal("0")
    reusable = max(Decimal("0"), arrived - issued)
    if qty > reusable:
        raise MaterialError("over_reusable", f"可回收仅 {reusable}")
    adjust_shared_stock(
        db,
        tenant_id,
        req.supplier_product_id,
        qty,
        size_id=_req_pool_key(req)[1],
        unit_cost=req.unit_price,
        ledger_type=SharedLedgerType.release_from_order,
        ref_type="manual_deallocate",
        ref_id=header.id,
        order_id=None,
        user_id=user_id,
        note=f"回收自生产单 {header.header_no}",
    )
    req.arrived_qty = arrived - qty
    db.commit()
    ctx = build_kit_context(db, tenant_id)
    out = ctx.row_dict(req)
    out["header_id"] = header.id
    out["header_no"] = header.header_no
    return out


def resolve_execution_id_for_order(db: Session, tenant_id: int, order_id: int) -> int | None:
    """桥接生产单 → 未取消执行单。"""
    from app.models import SpecExecutionOrder, SpecExecutionStatus

    row = db.scalar(
        select(SpecExecutionOrder)
        .where(
            SpecExecutionOrder.tenant_id == tenant_id,
            SpecExecutionOrder.shop_order_id == order_id,
            SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
        )
        .order_by(SpecExecutionOrder.id.desc())
        .limit(1)
    )
    return int(row.id) if row else None


def estimate_sku_kit_hint(
    db: Session,
    tenant_id: int,
    *,
    own_product_id: int,
    qty: int,
    size_id: int | None = None,
    color_id: int | None = None,
    include_shared: bool | None = None,
) -> str:
    """可产色码齐套粗估：ready|short|empty_bom。

    按产品 BOM × qty 对照共享池剩余（已承诺给在制单的池量已扣），
    无正式生产单时的预估口径，入库前不作精确。
    """
    if qty <= 0:
        return "empty_bom"
    materials = list(
        db.scalars(
            select(OwnProductMaterial)
            .where(
                OwnProductMaterial.tenant_id == tenant_id,
                OwnProductMaterial.own_product_id == own_product_id,
            )
            .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
        ).all()
    )
    materials = filter_bom_for_colorway(materials, color_id)
    if not materials:
        return "empty_bom"

    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    free_pool: dict[PoolKey, Decimal] = {
        k: Decimal(str(v)) for k, v in ctx.pool_by_key.items()
    }
    for (_oid, rid), credit in ctx.credits.items():
        row = db.get(OrderMaterialRequirement, rid)
        if not row or credit <= 0:
            continue
        key = _req_pool_key(row)
        free_pool[key] = free_pool.get(key, Decimal("0")) - Decimal(str(credit))

    for m in materials:
        usage_by_size = bool(getattr(m, "usage_by_size", False))
        loss_rate = getattr(m, "loss_rate", None) or Decimal("0")
        loss_fixed = getattr(m, "loss_fixed_qty", None) or Decimal("0")
        if usage_by_size:
            if not size_id:
                return "short"
            table_id = getattr(m, "size_usage_table_id", None)
            if not table_id:
                return "short"
            coeff_map = load_size_coeff_map(db, tenant_id, int(table_id))
            if size_id not in coeff_map:
                return "short"
            need = calc_required_qty_sized(
                m.qty, qty, coeff_map[size_id], loss_rate, loss_fixed
            )
            key = (int(m.supplier_product_id), int(size_id))
        else:
            need = calc_required_qty(m.qty, qty, loss_rate, loss_fixed)
            key = (int(m.supplier_product_id), None)
        available = free_pool.get(key, Decimal("0"))
        if available + Decimal("0.0001") < need:
            return "short"
    return "ready"


def order_ids_matching_kit(
    db: Session,
    tenant_id: int,
    *,
    kit_ok: bool,
    include_shared: bool | None = None,
) -> set[int]:
    """用于订单列表齐套筛选：与徽章同一算法。"""
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.status.in_(list(OPEN_KIT_STATUSES)),
            )
        ).all()
    )
    # 已完成/取消：无缺料行视为齐套=true（筛选「缺料」不含它们）
    closed = list(
        db.scalars(
            select(Order.id).where(
                Order.tenant_id == tenant_id,
                Order.status.in_([OrderStatus.completed, OrderStatus.cancelled]),
            )
        ).all()
    )
    ctx = build_kit_context(db, tenant_id, include_shared=include_shared)
    matched: set[int] = set()
    for o in orders:
        summary = ctx.summary_for_order(o.id)
        if bool(summary.get("kit_ok")) == bool(kit_ok):
            matched.add(o.id)
    if kit_ok:
        matched.update(int(x) for x in closed)
    return matched


def release_unused_arrived_to_pool(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    user_id: int | None = None,
    note: str | None = None,
) -> list[dict]:
    """将订单未发占用（arrived − issued）释放回库存池。"""
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
    )
    released: list[dict] = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        unused = max(Decimal("0"), arrived - issued)
        if unused <= 0:
            continue
        adjust_shared_stock(
            db,
            tenant_id,
            row.supplier_product_id,
            unused,
            size_id=_req_pool_key(row)[1],
            unit_cost=row.unit_price,
            ledger_type=SharedLedgerType.release_from_order,
            ref_type="order",
            ref_id=order.id,
            order_id=order.id,
            user_id=user_id,
            note=note or f"订单 {order.order_no} 释放未发占用",
        )
        row.arrived_qty = arrived - unused
        released.append(
            {
                "requirement_id": row.id,
                "supplier_product_id": row.supplier_product_id,
                "qty": unused,
            }
        )
    db.flush()
    return released


def sync_requirements_after_qty_change(
    db: Session,
    tenant_id: int,
    order: Order,
    *,
    user_id: int | None = None,
) -> dict:
    """改量后重算需求；已占用超过新需求的部分释放回池（不低于已发量）。"""
    rows = recalculate_required(db, tenant_id, order)
    released: list[dict] = []
    for row in rows:
        if row.is_customer_supplied:
            continue
        required = row.required_qty or Decimal("0")
        arrived = row.arrived_qty or Decimal("0")
        issued = row.issued_qty or Decimal("0")
        floor = issued
        target = max(required, floor)
        if arrived > target:
            excess = arrived - target
            adjust_shared_stock(
                db,
                tenant_id,
                row.supplier_product_id,
                excess,
                size_id=_req_pool_key(row)[1],
                unit_cost=row.unit_price,
                ledger_type=SharedLedgerType.release_from_order,
                ref_type="order_qty_change",
                ref_id=order.id,
                order_id=order.id,
                user_id=user_id,
                note=f"订单 {order.order_no} 改量释放超额占用",
            )
            row.arrived_qty = target
            released.append(
                {
                    "requirement_id": row.id,
                    "supplier_product_id": row.supplier_product_id,
                    "qty": excess,
                }
            )
    db.flush()
    return {"released": released, "requirement_count": len(rows)}


def free_pool_after_production_credits(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool,
) -> tuple[dict[PoolKey, Decimal], dict[PoolKey, Decimal]]:
    """生产单池承诺之后的剩余可用池。

    返回:
      pool_by_key: 库存池余额（原值）
      free_by_key: 扣除未结生产单承诺后的剩余（销售算料从此取）
    """
    credits, pool_by_key = build_pool_credits(db, tenant_id, include_shared=include_shared)
    committed: dict[PoolKey, Decimal] = {}
    if include_shared and credits:
        req_ids = [rid for (_, rid) in credits.keys()]
        reqs = db.scalars(
            select(OrderMaterialRequirement).where(OrderMaterialRequirement.id.in_(req_ids or [-1]))
        ).all()
        key_by_id = {r.id: _req_pool_key(r) for r in reqs}
        for (_, rid), credit in credits.items():
            key = key_by_id.get(rid)
            if key is None:
                continue
            committed[key] = committed.get(key, Decimal("0")) + credit
    free_by_key = {
        key: max(Decimal("0"), (pool_by_key.get(key) or Decimal("0")) - committed.get(key, Decimal("0")))
        for key in set(pool_by_key) | set(committed)
    }
    return pool_by_key, free_by_key


def in_transit_qty_by_supplier_product(db: Session, tenant_id: int) -> dict[int, Decimal]:
    """按 SKU 汇总采购在途（已下单/在运/部分收货的未收量）。"""
    by_key = in_transit_qty_by_pool_key(db, tenant_id)
    out: dict[int, Decimal] = {}
    for (sp_id, _size_id), qty in by_key.items():
        out[sp_id] = out.get(sp_id, Decimal("0")) + qty
    return out


def in_transit_qty_by_pool_key(db: Session, tenant_id: int) -> dict[PoolKey, Decimal]:
    """按 (SKU, size) 汇总采购在途。"""
    transit_rows = db.execute(
        select(
            PurchaseOrderLine.supplier_product_id,
            PurchaseOrderLine.size_id,
            PurchaseOrderLine.qty,
            PurchaseOrderLine.received_qty,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                ]
            ),
        )
    ).all()
    in_transit: dict[PoolKey, Decimal] = {}
    for sp_id, size_id, qty, recv in transit_rows:
        open_qty = Decimal(str(qty or 0)) - Decimal(str(recv or 0))
        if open_qty > 0:
            key = _pool_key(int(sp_id), int(size_id) if size_id is not None else None)
            in_transit[key] = in_transit.get(key, Decimal("0")) + open_qty
    return in_transit


def simulate_mrp_from_bom(
    db: Session,
    tenant_id: int,
    demands: list[dict],
    *,
    include_shared: bool | None = None,
    shortages_only: bool = False,
) -> dict:
    """销售算料：BOM 展开后按库存池剩余 + 采购在途实时算缺口；不写库、不锁池。

    demands 每项:
      key, label, order_no, product_code, own_product_id, total_qty,
      size_qtys optional {size_id: qty},
      delivery_date (optional), priority_key (optional tuple-like)
    """
    resolved = resolve_include_shared(db, tenant_id, include_shared)
    empty = {
        "locked": False,
        "include_shared": resolved,
        "empty_bom": True,
        "kit_ok": False,
        "shortage_lines": 0,
        "demand_count": 0,
        "lines": [],
    }
    if not demands:
        return {**empty, "kit_ok": True, "empty_bom": False}

    pool_by_key, free_by_key = free_pool_after_production_credits(
        db, tenant_id, include_shared=resolved
    )
    in_transit_by_key = in_transit_qty_by_pool_key(db, tenant_id)
    remaining_pool = dict(free_by_key) if resolved else {}
    remaining_transit = dict(in_transit_by_key)

    expanded: list[dict] = []
    for d in demands:
        own_product_id = int(d["own_product_id"])
        total_qty = int(d.get("total_qty") or 0)
        if total_qty <= 0:
            continue
        raw_sizes = d.get("size_qtys") or {}
        size_qtys = {int(k): int(v) for k, v in raw_sizes.items() if int(v or 0) > 0}
        materials = db.scalars(
            select(OwnProductMaterial)
            .where(
                OwnProductMaterial.tenant_id == tenant_id,
                OwnProductMaterial.own_product_id == own_product_id,
            )
            .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
        ).all()
        materials = filter_bom_for_colorway(materials, d.get("color_id"))
        priority_key = d.get("priority_key") or (
            d.get("delivery_date").toordinal()
            if getattr(d.get("delivery_date"), "toordinal", None)
            else 10**9,
            d.get("key") or "",
        )
        for i, m in enumerate(materials):
            sort_order = m.sort_order if m.sort_order is not None else i
            base = {
                "key": d.get("key"),
                "label": d.get("label"),
                "order_no": d.get("order_no"),
                "product_code": d.get("product_code"),
                "product_image_url": d.get("product_image_url"),
                "own_product_id": own_product_id,
                "supplier_product_id": m.supplier_product_id,
                "qty_per_pair": m.qty,
                "unit_price": m.unit_price or Decimal("0"),
                "sort_order": sort_order,
                "delivery_date": d.get("delivery_date"),
                "priority_key": priority_key,
            }
            bom_loss_rate = getattr(m, "loss_rate", None) or Decimal("0")
            bom_loss_fixed = getattr(m, "loss_fixed_qty", None) or Decimal("0")
            if getattr(m, "usage_by_size", False):
                table_id = getattr(m, "size_usage_table_id", None)
                if not table_id or not size_qtys:
                    expanded.append(
                        {
                            **base,
                            "required_qty": calc_required_qty(
                                m.qty, total_qty, bom_loss_rate, bom_loss_fixed
                            ),
                            "size_id": None,
                            "usage_by_size": True,
                            "pair_qty": total_qty,
                        }
                    )
                    continue
                coeff_map = load_size_coeff_map(db, tenant_id, int(table_id))
                first_sid = True
                for sid, sqty in sorted(size_qtys.items()):
                    coeff = coeff_map.get(sid, Decimal("1"))
                    fixed = bom_loss_fixed if first_sid else Decimal("0")
                    first_sid = False
                    expanded.append(
                        {
                            **base,
                            "required_qty": calc_required_qty_sized(
                                m.qty, sqty, coeff, bom_loss_rate, fixed
                            ),
                            "size_id": sid,
                            "usage_by_size": True,
                            "size_coeff": coeff,
                            "pair_qty": sqty,
                        }
                    )
            else:
                expanded.append(
                    {
                        **base,
                        "required_qty": calc_required_qty(
                            m.qty, total_qty, bom_loss_rate, bom_loss_fixed
                        ),
                        "size_id": None,
                        "usage_by_size": False,
                        "pair_qty": total_qty,
                    }
                )

    if not expanded:
        return {**empty, "demand_count": len(demands)}

    expanded.sort(
        key=lambda x: (
            x["priority_key"],
            x["sort_order"],
            x["supplier_product_id"],
            x.get("size_id") or 0,
        )
    )

    size_name_map = size_labels(
        db, {int(x["size_id"]) for x in expanded if x.get("size_id")}
    )
    merged: dict[PoolKey, dict] = {}
    for row in expanded:
        sp_id = row["supplier_product_id"]
        size_id = row.get("size_id")
        key = _pool_key(sp_id, size_id if row.get("usage_by_size") else None)
        need = row["required_qty"]
        left = need
        pool_credit = Decimal("0")
        transit_credit = Decimal("0")
        if resolved and left > 0:
            pool_credit = min(left, remaining_pool.get(key, Decimal("0")))
            remaining_pool[key] = remaining_pool.get(key, Decimal("0")) - pool_credit
            left -= pool_credit
        if left > 0:
            transit_credit = min(left, remaining_transit.get(key, Decimal("0")))
            remaining_transit[key] = remaining_transit.get(key, Decimal("0")) - transit_credit
            left -= transit_credit
        shortage = max(Decimal("0"), left)
        covered = pool_credit + transit_credit

        bucket = merged.get(key)
        if not bucket:
            sp = db.get(SupplierProduct, sp_id)
            partner = db.get(Partner, sp.partner_id) if sp and sp.partner_id else None
            unit = db.get(PricingUnit, sp.pricing_unit_id) if sp and sp.pricing_unit_id else None
            bucket = {
                "supplier_product_id": sp_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "partner_id": sp.partner_id if sp else None,
                "partner_name": partner.name if partner else None,
                "pricing_unit_id": sp.pricing_unit_id if sp else None,
                "pricing_unit_name": unit.name if unit else None,
                "usage_by_size": bool(row.get("usage_by_size")),
                "size_id": key[1],
                "size_value": size_name_map.get(key[1]) if key[1] else None,
                "qty_per_pair": row["qty_per_pair"],
                "unit_price": row["unit_price"],
                "required_qty": Decimal("0"),
                "pool_qty": pool_by_key.get(key, Decimal("0")) if resolved else Decimal("0"),
                "free_pool_qty": free_by_key.get(key, Decimal("0")) if resolved else Decimal("0"),
                "in_transit_qty": in_transit_by_key.get(key, Decimal("0")),
                "shared_qty": Decimal("0"),
                "pool_credit_qty": Decimal("0"),
                "transit_credit_qty": Decimal("0"),
                "shortage_qty": Decimal("0"),
                "sort_order": row["sort_order"],
                "sources": [],
            }
            merged[key] = bucket

        bucket["required_qty"] += need
        bucket["pool_credit_qty"] += pool_credit
        bucket["transit_credit_qty"] += transit_credit
        bucket["shared_qty"] += covered
        bucket["shortage_qty"] += shortage
        bucket["sources"].append(
            {
                "key": row["key"],
                "label": row["label"],
                "order_no": row["order_no"],
                "product_code": row["product_code"],
                "product_image_url": row.get("product_image_url"),
                "size_id": key[1],
                "pair_qty": row.get("pair_qty"),
                "qty_per_pair": row["qty_per_pair"],
                "required_qty": need,
                "pool_credit_qty": pool_credit,
                "transit_credit_qty": transit_credit,
                "shared_qty": covered,
                "shortage_qty": shortage,
            }
        )

    lines = list(merged.values())
    lines.sort(key=lambda x: (x["sort_order"], x["supplier_product_id"], x.get("size_id") or 0))
    if shortages_only:
        lines = [x for x in lines if x["shortage_qty"] > 0]

    shortage_n = sum(1 for x in lines if x["shortage_qty"] > 0)
    return {
        "locked": False,
        "include_shared": resolved,
        "empty_bom": False,
        "kit_ok": shortage_n == 0,
        "shortage_lines": shortage_n,
        "demand_count": len(demands),
        "lines": lines,
    }
