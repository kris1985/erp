"""自己产品开发：成品 + 颜色 + 供应商物料 + 工序人工 + 客户报价。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_employee, require_permissions, require_roles
from app.db import get_db
from app.models import (
    Brand,
    Color,
    brand_logo_urls,
    MaterialSizeUsageTable,
    OwnProduct,
    OwnProductBrandQuote,
    OwnProductColor,
    OwnProductCommission,
    OwnProductMgmtCommission,
    OwnProductLabor,
    OwnProductMaterial,
    OwnProductOtherCost,
    OwnProductPart,
    OwnProductQuote,
    OwnProductVersion,
    OtherCostItem,
    PartDefinition,
    Partner,
    PricingUnit,
    ProcessDefinition,
    ProcessPriceHistory,
    ProcessRouteTemplate,
    ProcessRouteTemplateItem,
    MgmtCommissionTemplate,
    MgmtCommissionTemplateItem,
    OtherCostTemplate,
    OtherCostTemplateItem,
    JobTitle,
    ProcessSegment,
    ProcessType,
    Department,
    SupplierProduct,
    Tenant,
    Employee,
    MaterialUsageHistory,
)
from app.services.material_service import process_display_name, resolve_consume_process
from app.schemas.api import (
    ColorOut,
    OwnProductBatchQuoteExportIn,
    OwnProductBrandQuoteIn,
    OwnProductBrandQuoteOut,
    OwnProductCommissionIn,
    OwnProductCommissionOut,
    OwnProductMgmtCommissionIn,
    OwnProductMgmtCommissionOut,
    OwnProductCreate,
    OwnProductLaborIn,
    OwnProductLaborOut,
    OwnProductMaterialIn,
    OwnProductMaterialOut,
    OwnProductOtherCostIn,
    OwnProductOtherCostOut,
    OWN_PRODUCT_SEASONS,
    OwnProductOut,
    OwnProductPartIn,
    OwnProductPartOut,
    OwnProductQuoteIn,
    OwnProductQuoteOut,
    OwnProductUpdate,
    OwnProductVersionListItem,
    OwnProductVersionOut,
    MaterialUsageHistoryOut,
    ProcessPriceHistoryOut,
    ProcessRouteTemplateCreate,
    ProcessRouteTemplateItemOut,
    ProcessRouteTemplateOut,
    MgmtCommissionTemplateCreate,
    MgmtCommissionTemplateItemOut,
    MgmtCommissionTemplateOut,
    OtherCostTemplateCreate,
    OtherCostTemplateItemOut,
    OtherCostTemplateOut,
    RequirementNoteHistoryOut,
)
from app.schemas.common import normalize_page, ok, page_payload
from app.services.material_usage_history_service import (
    changed_by_names,
    list_material_usage_history,
    record_material_qty_changes,
    snapshot_material_qty,
)
from app.services.own_product_material_import import (
    OwnProductMaterialImportError,
    build_own_product_material_import_template,
    parse_own_product_materials_xlsx,
)

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
    consume_segment_name: str | None = None,
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
        consume_segment_id=getattr(m, "consume_segment_id", None),
        consume_segment_name=consume_segment_name,
        consume_source=consume_source,
        usage_by_size=bool(getattr(m, "usage_by_size", False)),
        size_usage_table_id=getattr(m, "size_usage_table_id", None),
        size_usage_table_name=size_usage_table_name,
        loss_rate=getattr(m, "loss_rate", None) or Decimal("0"),
        loss_fixed_qty=getattr(m, "loss_fixed_qty", None) or Decimal("0"),
        bom_color_id=getattr(m, "color_id", None),
        bom_color_name=bom_color.name if bom_color else None,
    )


def _labor_out(db: Session, row: OwnProductLabor, process: ProcessDefinition | None) -> OwnProductLaborOut:
    name = getattr(row, "process_name", None) or (process.name if process else None)
    ptype = "personal"
    if process and process.type is not None:
        ptype = process.type.value if hasattr(process.type, "value") else str(process.type)
    segment_name = None
    if getattr(row, "segment_id", None):
        from app.models import ProcessSegment

        seg = db.get(ProcessSegment, row.segment_id)
        segment_name = seg.name if seg and seg.tenant_id == row.tenant_id else None
    return OwnProductLaborOut(
        id=row.id,
        process_id=row.process_id,
        process_name=name,
        requirement_note=getattr(row, "requirement_note", None),
        process_type=ptype,
        pay_mode="piecework",
        unit_price=row.unit_price,
        department_id=getattr(row, "department_id", None),
        department_prices=getattr(row, "department_prices", None) or None,
        sort_order=row.sort_order,
        part_id=getattr(row, "part_id", None),
        is_kit_checkpoint=bool(getattr(row, "is_kit_checkpoint", False)),
        segment_id=getattr(row, "segment_id", None),
        segment_name=segment_name,
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
        # 工序段重构（16.3）：消耗段（新主键；旧工序字段两期过渡）
        from app.services.material_service import resolve_consume_segment

        seg_id, _seg_src = resolve_consume_segment(
            db,
            p.tenant_id,
            bom_consume_segment_id=getattr(m, "consume_segment_id", None),
            bom_consume_process_id=getattr(m, "consume_process_id", None),
            supplier_product_id=m.supplier_product_id,
        )
        seg_name = None
        if seg_id:
            from app.models import ProcessSegment

            seg = db.get(ProcessSegment, seg_id)
            seg_name = seg.name if seg else None
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
                consume_segment_name=seg_name,
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
        labors_out.append(_labor_out(db, row, process_map.get(row.process_id)))

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

    commission_rows = list(p.commissions or [])
    commission_emp_ids = [x.employee_id for x in commission_rows if x.employee_id]
    commission_emp_map: dict[int, Employee] = {}
    if commission_emp_ids:
        commission_emp_map = {
            x.id: x
            for x in db.scalars(select(Employee).where(Employee.id.in_(commission_emp_ids))).all()
        }
    commissions_out = [
        OwnProductCommissionOut(
            id=row.id,
            employee_id=row.employee_id,
            employee_name=(
                commission_emp_map[row.employee_id].name
                if row.employee_id and row.employee_id in commission_emp_map
                else None
            ),
            amount=row.amount,
            sort_order=row.sort_order,
        )
        for row in sorted(commission_rows, key=lambda x: (x.sort_order, x.id))
    ]

    mgmt_rows = list(getattr(p, "mgmt_commissions", None) or [])
    mgmt_title_ids = [x.job_title_id for x in mgmt_rows]
    mgmt_title_map: dict[int, JobTitle] = {}
    if mgmt_title_ids:
        mgmt_title_map = {
            x.id: x
            for x in db.scalars(select(JobTitle).where(JobTitle.id.in_(mgmt_title_ids))).all()
        }
    mgmt_commissions_out = []
    for row in sorted(mgmt_rows, key=lambda x: (x.sort_order, x.id)):
        title = mgmt_title_map.get(row.job_title_id)
        mgmt_commissions_out.append(
            OwnProductMgmtCommissionOut(
                id=row.id,
                job_title_id=row.job_title_id,
                job_title_name=title.name if title else None,
                amount=row.amount,
                sort_order=row.sort_order,
            )
        )

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

    brand_ids = [row.master_brand_id for row in (p.brand_quotes or []) if row.master_brand_id]
    brand_map = {
        row.id: row
        for row in db.scalars(select(Brand).where(Brand.id.in_(brand_ids or [-1]))).all()
    }
    brand_quotes_out = []
    for row in sorted(p.brand_quotes or [], key=lambda x: (x.sort_order, x.id)):
        logos = brand_logo_urls(brand_map.get(row.master_brand_id))
        brand_quotes_out.append(
            OwnProductBrandQuoteOut(
                id=row.id,
                brand_name=row.brand_name,
                master_brand_id=row.master_brand_id,
                logo_url=logos[0] if logos else None,
                logo_urls=logos,
                quote_price=row.quote_price,
                sort_order=row.sort_order,
            )
        )

    shoe_last_product_id, shoe_last_code, shoe_last_name = _color_card_fields(
        db, p.tenant_id, getattr(p, "shoe_last_product_id", None)
    )
    sole_mold_product_id, sole_mold_code, sole_mold_name = _color_card_fields(
        db, p.tenant_id, getattr(p, "sole_mold_product_id", None)
    )
    heel_model_id, heel_model_code, heel_model_name = _color_card_fields(
        db, p.tenant_id, getattr(p, "heel_model_id", None)
    )
    heel_model_2_id, heel_model_2_code, heel_model_2_name = _color_card_fields(
        db, p.tenant_id, getattr(p, "heel_model_2_id", None)
    )

    out = OwnProductOut(
        id=p.id,
        product_code=p.product_code,
        product_year=getattr(p, "product_year", None),
        season=getattr(p, "season", None),
        image_url=p.image_url,
        fabric=getattr(p, "fabric", None),
        lining=getattr(p, "lining", None),
        shoe_last=shoe_last_code or getattr(p, "shoe_last", None),
        sole_mold=sole_mold_code or getattr(p, "sole_mold", None),
        shoe_last_product_id=shoe_last_product_id,
        shoe_last_code=shoe_last_code,
        shoe_last_name=shoe_last_name,
        sole_mold_product_id=sole_mold_product_id,
        sole_mold_code=sole_mold_code,
        sole_mold_name=sole_mold_name,
        heel_model_id=heel_model_id,
        heel_model_code=heel_model_code,
        heel_model_name=heel_model_name,
        heel_model_2_id=heel_model_2_id,
        heel_model_2_code=heel_model_2_code,
        heel_model_2_name=heel_model_2_name,
        shoe_last_hours=getattr(p, "shoe_last_hours", None),
        color_ids=color_ids,
        colors=colors,
        parts=parts_out,
        materials=materials_out,
        labors=labors_out,
        quotes=quotes_out,
        brand_quotes=brand_quotes_out,
        commissions=commissions_out,
        mgmt_commissions=mgmt_commissions_out,
        other_costs=other_costs_out,
        material_cost=p.material_cost or Decimal("0"),
        labor_cost=p.labor_cost or Decimal("0"),
        commission_cost=getattr(p, "commission_cost", None) or Decimal("0"),
        other_cost=p.other_cost or Decimal("0"),
        quote_price=p.quote_price,
        segment_ref_prices=getattr(p, "segment_ref_prices", None) or None,
        order_qty=int(getattr(p, "order_qty", 0) or 0),
        is_active=bool(p.is_active),
        trace_enabled=bool(getattr(p, "trace_enabled", False)),
        approval_status=getattr(p, "approval_status", None) or "approved",
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
            selectinload(OwnProduct.commissions),
            selectinload(OwnProduct.mgmt_commissions),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
            selectinload(OwnProduct.brand_quotes),
        )
    )
    if not p:
        raise HTTPException(status_code=404, detail="产品不存在")
    return p


# 版本变更板块：key → 中文标签（列表/详情一眼可见）
PRODUCT_VERSION_SECTION_LABELS: dict[str, str] = {
    "create": "新建",
    "info": "产品信息",
    "parts": "部件",
    "materials": "物料",
    "labors": "工艺路线",
    "commissions": "设计师提成",
    "mgmt_commissions": "管理提成",
    "other_costs": "其它成本",
    "quotes": "客户报价",
    "brand_quotes": "品牌报价",
}

_VERSION_SKIP_KEYS = frozenset({"id", "created_at", "updated_at", "own_product_id"})
_INFO_COMPARE_KEYS = (
    "product_code",
    "product_year",
    "season",
    "image_url",
    "fabric",
    "lining",
    "shoe_last",
    "sole_mold",
    "shoe_last_product_id",
    "sole_mold_product_id",
    "heel_model_id",
    "heel_model_2_id",
    "shoe_last_hours",
    "color_ids",
    "quote_price",
    "order_qty",
    "is_active",
    "trace_enabled",
    "segment_ref_prices",
    "material_cost",
    "labor_cost",
    "commission_cost",
    "other_cost",
)


def _version_canon(value: Any) -> Any:
    """比较用规范化：去掉行 id/时间戳，避免替换子表导致误判。"""
    if isinstance(value, dict):
        return {
            str(k): _version_canon(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            if k not in _VERSION_SKIP_KEYS
        }
    if isinstance(value, list):
        return [_version_canon(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _version_section_payload(snapshot: dict | None, key: str) -> Any:
    snap = snapshot or {}
    if key == "info":
        return {k: snap.get(k) for k in _INFO_COMPARE_KEYS}
    return snap.get(key) or []


def _diff_product_sections(prev: dict | None, curr: dict | None) -> list[str]:
    """相对上一版，返回有变化的板块 key 列表（稳定顺序）。"""
    if prev is None:
        return ["create"]
    changed: list[str] = []
    for key in (
        "info",
        "parts",
        "materials",
        "labors",
        "commissions",
        "mgmt_commissions",
        "other_costs",
        "quotes",
        "brand_quotes",
    ):
        if _version_canon(_version_section_payload(prev, key)) != _version_canon(
            _version_section_payload(curr, key)
        ):
            changed.append(key)
    return changed


def _section_labels(keys: list[str] | None) -> list[str]:
    return [
        PRODUCT_VERSION_SECTION_LABELS.get(k, k)
        for k in (keys or [])
        if k
    ]


def _save_product_version(
    db: Session,
    product: OwnProduct,
    *,
    changed_by: int | None,
    source: str,
) -> OwnProductVersion:
    """每次创建/保存落一份完整档案快照（即使内容未变也记）。"""
    prev = db.scalar(
        select(OwnProductVersion)
        .where(
            OwnProductVersion.tenant_id == product.tenant_id,
            OwnProductVersion.own_product_id == product.id,
        )
        .order_by(OwnProductVersion.version_no.desc(), OwnProductVersion.id.desc())
        .limit(1)
    )
    version_no = int(prev.version_no if prev else 0) + 1
    snapshot = _product_out(product, db)
    if source == "product_create" or prev is None:
        changed_sections = ["create"]
    else:
        changed_sections = _diff_product_sections(prev.snapshot, snapshot)
    row = OwnProductVersion(
        tenant_id=product.tenant_id,
        own_product_id=product.id,
        version_no=version_no,
        snapshot=snapshot,
        changed_sections=changed_sections,
        changed_by=changed_by,
        source=source,
    )
    db.add(row)
    return row


def _ensure_colors(db: Session, tenant_id: int, color_ids: list[int]) -> None:
    if not color_ids:
        raise HTTPException(
            status_code=400,
            detail="请选择成品颜色。一色一款：每个工厂型号绑一个颜色；同楦不同色请另建工厂型号",
        )
    rows = db.scalars(
        select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids))
    ).all()
    if len(rows) != len(set(color_ids)):
        raise HTTPException(status_code=400, detail="存在无效颜色")


def _normalize_product_text(raw, label: str) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) > 100:
        raise HTTPException(status_code=400, detail=f"{label}不能超过100个字")
    return text


def _color_card_fields(db: Session, tenant_id: int, card_id: int | None) -> tuple[int | None, str | None, str | None]:
    if not card_id:
        return None, None, None
    card = db.get(SupplierProduct, card_id)
    if not card or card.tenant_id != tenant_id:
        return card_id, None, None
    return card_id, card.product_code, card.name


def _require_field_category(db: Session, card: SupplierProduct, label: str) -> None:
    """楦型、鞋底型号、鞋跟型号只能选对应物料分类下的色卡。"""
    category_name = {"楦型": "楦头", "鞋底型号": "大底", "鞋跟型号": "鞋跟"}.get(label)
    if not category_name:
        return
    from app.models import MaterialCategory

    cat = db.get(MaterialCategory, card.category_id) if card.category_id else None
    if not cat or cat.tenant_id != card.tenant_id or str(cat.name or "").strip() != category_name:
        raise HTTPException(status_code=400, detail=f"请从「{category_name}」分类中选择{label}")


def _ensure_color_card(
    db: Session, tenant_id: int, card_id: int | None, *, label: str = "物料色卡"
) -> SupplierProduct | None:
    if card_id is None:
        return None
    card = db.get(SupplierProduct, card_id)
    if not card or card.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail=f"请从物料色卡中选择{label}")
    from app.services.supplier_product_price import catalog_approved

    if not catalog_approved(card):
        name = (card.name or "").strip() or card.product_code
        raise HTTPException(status_code=400, detail=f"「{name}」尚未审批通过，不能使用")
    _require_field_category(db, card, label)
    return card


def _apply_color_card_field(
    db: Session,
    tenant_id: int,
    card_id: int | None,
    *,
    label: str,
) -> tuple[int | None, str | None]:
    """色卡 id → (id, product_code)；空则清空。"""
    if card_id is None:
        return None, None
    card = _ensure_color_card(db, tenant_id, card_id, label=label)
    assert card is not None
    return card.id, (card.product_code or "").strip() or None


def _normalize_shoe_last_hours(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    hours = Decimal(str(raw)).quantize(Decimal("0.1"))
    if hours < 0:
        raise HTTPException(status_code=400, detail="楦头占用时间不能为负")
    return hours


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
    seen_materials: set[tuple[int | None, int]] = set()
    for i, row in enumerate(materials):
        sp = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.id == row.supplier_product_id,
                SupplierProduct.tenant_id == product.tenant_id,
            )
        )
        if not sp:
            raise HTTPException(status_code=400, detail=f"供应商产品不存在: {row.supplier_product_id}")
        from app.services.supplier_product_price import catalog_approved

        if not catalog_approved(sp):
            mat_name = (sp.name or "").strip() or sp.product_code
            raise HTTPException(status_code=400, detail=f"「{mat_name}」尚未审批通过，不能使用")
        qty = Decimal(row.qty or 0)
        if qty < 0:
            raise HTTPException(status_code=400, detail="用量不能为负")
        qty = qty.quantize(Decimal("0.0001"))
        consume_pid = row.consume_process_id
        if consume_pid is not None:
            proc = db.get(ProcessDefinition, consume_pid)
            if not proc or proc.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="消耗工序不存在")
        # 工序段重构（16.1）：消耗段（新主键；旧工序字段两期过渡）
        consume_sid = getattr(row, "consume_segment_id", None)
        if consume_sid is not None:
            from app.models import ProcessSegment

            seg = db.get(ProcessSegment, consume_sid)
            if not seg or seg.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="消耗部门不存在")
        # 按码跟物料分类（产品开发 BOM 不再单独维护）
        from app.models import MaterialCategory

        cat = (
            db.get(MaterialCategory, sp.category_id)
            if getattr(sp, "category_id", None)
            else None
        )
        usage_by_size = bool(cat and getattr(cat, "suggest_usage_by_size", False))
        size_table_id = (
            getattr(cat, "default_size_usage_table_id", None) if usage_by_size else None
        )
        if usage_by_size and size_table_id:
            table = db.get(MaterialSizeUsageTable, size_table_id)
            if not table or table.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="用量码表不存在")
        elif not usage_by_size:
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
        if consume_sid is None:
            raise HTTPException(status_code=400, detail="请选择消耗部门")
        material_key = (int(bom_color_id) if bom_color_id is not None else None, sp.id)
        if material_key in seen_materials:
            color_name = "共用"
            if bom_color_id is not None:
                color = db.get(Color, int(bom_color_id))
                color_name = (color.name if color and color.name else None) or str(bom_color_id)
            mat_name = (sp.name or "").strip() or sp.product_code
            raise HTTPException(
                status_code=400,
                detail=f"「{color_name}」中物料「{mat_name}」重复",
            )
        seen_materials.add(material_key)
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
                consume_segment_id=consume_sid,
                usage_by_size=usage_by_size,
                size_usage_table_id=size_table_id,
                loss_rate=loss_rate,
                loss_fixed_qty=loss_fixed,
                color_id=int(bom_color_id) if bom_color_id is not None else None,
            )
        )
    return total.quantize(Decimal("0.0001"))


def _ensure_process_by_name(
    db: Session,
    tenant_id: int,
    name: str,
    segment_id: int | None = None,
) -> ProcessDefinition:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写工序名称")
    stmt = select(ProcessDefinition).where(
        ProcessDefinition.tenant_id == tenant_id,
        ProcessDefinition.name == name,
    )
    if segment_id is None:
        stmt = stmt.where(ProcessDefinition.segment_id.is_(None))
    else:
        stmt = stmt.where(ProcessDefinition.segment_id == int(segment_id))
    existing = db.scalar(stmt)
    if existing:
        if not existing.is_active:
            existing.is_active = True
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
        type=ProcessType.personal,
        default_price=Decimal("0"),
        sort_order=0,
        is_active=True,
        segment_id=int(segment_id) if segment_id is not None else None,
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
        if row.source_supplier_product_id:
            from app.services.supplier_product_price import unapproved_catalog_label

            blocked = unapproved_catalog_label(
                db, product.tenant_id, [row.source_supplier_product_id]
            )
            if blocked:
                raise HTTPException(status_code=400, detail=blocked)
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


def _ref_price_key(key: object) -> tuple[str, int, int | None]:
    """参考价键。只认工序段 id；旧的「工序段:部门」会并回该段。"""
    text = str(key).strip()
    if ":" in text:
        seg_text, dept_text = text.split(":", 1)
        seg_id = int(seg_text)
        return str(seg_id), seg_id, int(dept_text)
    seg_id = int(text)
    return str(seg_id), seg_id, None


def _normalize_department_prices(raw: dict | None) -> dict[str, float] | None:
    """同一工序的分部门单价。0 保留，负价拒绝。"""
    if not raw:
        return None
    out: dict[str, float] = {}
    for key, val in raw.items():
        try:
            dept_id = int(key)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"无效部门 id：{key}")
        price = Decimal(str(val if val is not None else 0))
        if price < 0:
            raise HTTPException(status_code=400, detail="工序价格不能为负")
        out[str(dept_id)] = float(price.quantize(Decimal("0.0001")))
    return out or None


def _normalize_segment_ref_prices(raw: dict | None) -> dict[str, float] | None:
    """校验并规范化段参考价；0 元项丢弃，负价拒绝。

    一个工序段只有一个参考价。旧的「工序段:部门」并回该段；已有段级价时忽略部门键。
    """
    if not raw:
        return None
    segment_prices: dict[str, float] = {}
    dept_fallback: dict[str, float] = {}
    for key, val in raw.items():
        try:
            _stored, seg_id, dept_id = _ref_price_key(key)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"无效工序段 id：{key}")
        price = Decimal(str(val if val is not None else 0))
        if price < 0:
            raise HTTPException(status_code=400, detail="参考价不能为负")
        if price == 0:
            continue
        seg_key = str(seg_id)
        quantized = float(price.quantize(Decimal("0.0001")))
        if dept_id is None:
            segment_prices[seg_key] = quantized
        elif seg_key not in dept_fallback:
            dept_fallback[seg_key] = quantized
    for seg_key, price in dept_fallback.items():
        segment_prices.setdefault(seg_key, price)
    return segment_prices or None


def _labor_department_prices(labor: OwnProductLabor) -> dict[int, Decimal] | None:
    raw = getattr(labor, "department_prices", None)
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[int, Decimal] = {}
    for key, val in raw.items():
        try:
            out[int(key)] = Decimal(str(val or 0))
        except (TypeError, ValueError):
            continue
    return out or None


def _multi_segment_departments(db: Session, tenant_id: int) -> dict[int, list[int]]:
    """同一工序段挂了多个叶子部门时，成本按部门分开计。"""
    from app.services.department_scope import list_segment_leaf_departments

    grouped: dict[int, list[int]] = {}
    for row in list_segment_leaf_departments(db, tenant_id):
        grouped.setdefault(int(row["process_segment_id"]), []).append(int(row["id"]))
    return {sid: depts for sid, depts in grouped.items() if len(depts) > 1}


def _compute_labor_cost(
    labors: list[OwnProductLabor],
    segment_ref_prices: dict | None,
    *,
    departments_by_segment: dict[int, list[int]] | None = None,
) -> Decimal:
    """人工成本。

    有工序价用工序价合计，没有工序价用该段参考价。
    同一工序段挂多个部门时不把部门加在一起，只计一个部门（按部门顺序取第一个）。
    页面上的人工成本按当前选中的部门实时算，规则相同。
    """
    groups: dict[tuple[int | None, int | None], Decimal] = {}
    for labor in labors:
        sid = getattr(labor, "segment_id", None)
        owned_dept = getattr(labor, "department_id", None)
        if owned_dept is not None:
            key = (sid, int(owned_dept))
            groups[key] = groups.get(key, Decimal("0")) + Decimal(labor.unit_price or 0)
            continue
        prices = _labor_department_prices(labor)
        if prices:
            for dept_id, price in prices.items():
                key = (sid, dept_id)
                groups[key] = groups.get(key, Decimal("0")) + price
            continue
        key = (sid, None)
        groups[key] = groups.get(key, Decimal("0")) + Decimal(labor.unit_price or 0)

    refs: dict[int, Decimal] = {}
    normalized = _normalize_segment_ref_prices(segment_ref_prices) if isinstance(segment_ref_prices, dict) else None
    for key, val in (normalized or {}).items():
        refs[int(key)] = Decimal(str(val or 0))

    depts_by_sid: dict[int, set[int]] = {}
    for sid, dept_id in groups:
        if sid is not None and dept_id is not None:
            depts_by_sid.setdefault(sid, set()).add(dept_id)
    ordered_multi: dict[int, list[int]] = {}
    for sid, depts in (departments_by_segment or {}).items():
        if len(depts) > 1:
            ordered_multi[int(sid)] = [int(dept) for dept in depts]
    for sid, dept_ids in depts_by_sid.items():
        if len(dept_ids) > 1 and sid not in ordered_multi:
            ordered_multi[sid] = sorted(dept_ids)

    total = Decimal("0")
    covered: set[int] = set()
    for sid, depts in ordered_multi.items():
        covered.add(sid)
        owned = [dept for dept in depts if (sid, dept) in groups]
        if not owned and (sid, None) in groups:
            price_sum = groups[(sid, None)]
            total += price_sum if price_sum > 0 else refs.get(sid, Decimal("0"))
            continue
        # 多部门只计第一个部门，不把各部门工序价加在一起
        price_sum = groups.get((sid, depts[0]), Decimal("0"))
        total += price_sum if price_sum > 0 else refs.get(sid, Decimal("0"))

    for (sid, _dept_id), price_sum in groups.items():
        if sid in ordered_multi:
            continue
        if price_sum > 0:
            total += price_sum
            if sid is not None:
                covered.add(sid)
            continue
        if sid is None:
            continue
        covered.add(sid)
        total += refs.get(sid, Decimal("0"))

    for sid, ref in refs.items():
        if ref > 0 and sid not in covered:
            total += ref

    return total.quantize(Decimal("0.0001"))


def _replace_labors(
    db: Session,
    product: OwnProduct,
    labors: list[OwnProductLaborIn],
    *,
    changed_by: int | None = None,
    source: str = "product_save",
) -> Decimal:
    from app.models import Order, OrderProcess, OrderProcessAssignment, WorkLog

    old_labors = list(product.labors)
    old_by_pid = {l.process_id: l for l in old_labors if l.process_id}
    product_part_ids = {p.part_id for p in (product.parts or [])}
    # 先解析新清单（会 ensure 工序），再校验删除
    planned: list[tuple[ProcessDefinition, OwnProductLaborIn, Decimal, dict | None]] = []
    seen: set[str] = set()
    kit_count = 0
    for i, row in enumerate(labors):
        name = (row.process_name or "").strip()
        part_id = getattr(row, "part_id", None)
        dept_id = getattr(row, "department_id", None)
        if not name:
            raise HTTPException(status_code=400, detail="请填写工序名称")
        key = f"{part_id or 0}:{dept_id or 0}:{name.lower()}"
        if key in seen:
            raise HTTPException(status_code=400, detail=f"同一部门工序「{name}」重复")
        seen.add(key)
        if part_id is not None and part_id not in product_part_ids:
            raise HTTPException(status_code=400, detail=f"工序绑定的部件不在产品部件清单中: {part_id}")
        if bool(getattr(row, "is_kit_checkpoint", False)):
            kit_count += 1
            if part_id is not None:
                raise HTTPException(status_code=400, detail="齐套检查点须落在整鞋段工序")
        row_seg = getattr(row, "segment_id", None)
        process = _ensure_process_by_name(
            db, product.tenant_id, name, segment_id=row_seg
        )
        unit_price = Decimal(row.unit_price or 0)
        if unit_price < 0:
            raise HTTPException(status_code=400, detail="工序价格不能为负")
        if dept_id is not None:
            from app.models import Department

            dept = db.get(Department, int(dept_id))
            if dept is None or dept.tenant_id != product.tenant_id:
                raise HTTPException(status_code=400, detail="工序所属部门不存在")
            dept_prices = None
        else:
            dept_prices = _normalize_department_prices(getattr(row, "department_prices", None))
        planned.append((process, row, unit_price, dept_prices))

    if kit_count > 1:
        raise HTTPException(status_code=400, detail="齐套检查点最多只能勾选一个")

    keep_pids = {p.id for p, _, _, _ in planned}
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

    _record_process_price_history(
        db,
        product=product,
        old_labors=old_labors,
        planned=[(process, row, unit_price) for process, row, unit_price, _prices in planned],
        changed_by=changed_by,
        source=source,
    )

    product.labors.clear()
    db.flush()
    total = Decimal("0")
    for i, (process, row, unit_price, dept_prices) in enumerate(planned):
        total += unit_price
        # 优先用路线上的段；未传时回退工序主数据段（工序段重构 D13）
        seg_id = getattr(row, "segment_id", None)
        if seg_id is None:
            seg_id = process.segment_id
        product.labors.append(
            OwnProductLabor(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                part_id=getattr(row, "part_id", None),
                process_id=process.id,
                process_name=(row.process_name or "").strip(),
                requirement_note=(getattr(row, "requirement_note", None) or "").strip() or None,
                unit_price=unit_price,
                department_id=getattr(row, "department_id", None),
                department_prices=dept_prices,
                sort_order=row.sort_order if row.sort_order else i,
                is_kit_checkpoint=bool(getattr(row, "is_kit_checkpoint", False)),
                segment_id=seg_id,
            )
        )
    return total.quantize(Decimal("0.0001"))


def _price_q(v: Decimal | None) -> Decimal | None:
    if v is None:
        return None
    return Decimal(v).quantize(Decimal("0.0001"))


def _old_labor_price(
    old_labors: list[OwnProductLabor],
    process_id: int,
    department_id: int | None,
) -> tuple[OwnProductLabor | None, Decimal | None]:
    """按工序和部门找旧价。部门行优先；没有时回落到旧的分部门单价。"""
    exact: OwnProductLabor | None = None
    shared: OwnProductLabor | None = None
    for old in old_labors:
        if old.process_id != process_id:
            continue
        if getattr(old, "department_id", None) == department_id:
            exact = old
        elif getattr(old, "department_id", None) is None:
            shared = old
    old = exact or shared
    if old is None:
        return None, None
    if department_id is not None and getattr(old, "department_id", None) != department_id:
        raw = getattr(old, "department_prices", None)
        if isinstance(raw, dict):
            val = raw.get(str(department_id))
            if val is None:
                val = raw.get(department_id)
            if val is not None:
                return old, _price_q(Decimal(str(val or 0)))
    return old, _price_q(Decimal(old.unit_price or 0))


def _record_process_price_history(
    db: Session,
    *,
    product: OwnProduct,
    old_labors: list[OwnProductLabor],
    planned: list[tuple[ProcessDefinition, OwnProductLaborIn, Decimal]],
    changed_by: int | None,
    source: str,
) -> None:
    """产品工艺路线保存时：工序单价变化落流水。分部门单价按部门各记一条。"""
    old_by_pid = {labor.process_id: labor for labor in old_labors if labor.process_id}
    for process, row, unit_price in planned:
        dept_id = getattr(row, "department_id", None)
        if dept_id is not None:
            _old, old_price = _old_labor_price(old_labors, process.id, int(dept_id))
            new_price = _price_q(unit_price) or Decimal("0.0000")
            if _old is None:
                if new_price <= 0:
                    continue
            elif old_price == new_price:
                continue
            db.add(
                ProcessPriceHistory(
                    tenant_id=product.tenant_id,
                    process_id=process.id,
                    process_name=(row.process_name or process.name or "").strip() or process.name,
                    own_product_id=product.id,
                    product_code=product.product_code,
                    old_price=old_price,
                    new_price=new_price,
                    changed_by=changed_by,
                    source=source,
                )
            )
            continue
        old = old_by_pid.get(process.id)
        new_prices = _normalize_department_prices(getattr(row, "department_prices", None)) or {}
        if new_prices:
            old_map: dict[str, Decimal] = {}
            raw_old = getattr(old, "department_prices", None) if old is not None else None
            if isinstance(raw_old, dict):
                for key, val in raw_old.items():
                    try:
                        old_map[str(int(key))] = _price_q(Decimal(str(val or 0))) or Decimal("0")
                    except (TypeError, ValueError):
                        continue
            fallback = _price_q(Decimal(old.unit_price or 0)) if old is not None else None
            for key, raw_price in new_prices.items():
                new_price = _price_q(Decimal(str(raw_price))) or Decimal("0.0000")
                if key in old_map:
                    old_price = old_map[key]
                else:
                    old_price = fallback
                if old is None:
                    if new_price <= 0:
                        continue
                elif old_price == new_price:
                    continue
                db.add(
                    ProcessPriceHistory(
                        tenant_id=product.tenant_id,
                        process_id=process.id,
                        process_name=(row.process_name or process.name or "").strip() or process.name,
                        own_product_id=product.id,
                        product_code=product.product_code,
                        old_price=old_price,
                        new_price=new_price,
                        changed_by=changed_by,
                        source=source,
                    )
                )
            continue
        old_price = _price_q(Decimal(old.unit_price or 0)) if old is not None else None
        new_price = _price_q(unit_price) or Decimal("0.0000")
        if old is None:
            # 新品/新工序：仅记录有价首填
            if new_price <= 0:
                continue
        elif old_price == new_price:
            continue
        db.add(
            ProcessPriceHistory(
                tenant_id=product.tenant_id,
                process_id=process.id,
                process_name=(row.process_name or process.name or "").strip() or process.name,
                own_product_id=product.id,
                product_code=product.product_code,
                old_price=old_price,
                new_price=new_price,
                changed_by=changed_by,
                source=source,
            )
        )

def _copy_segment_department_dispatch(db: Session, op, siblings: list) -> None:
    """同工序段已经派过部门时，后补的工序跟着派到同一个部门。"""
    from app.models import OrderProcessAssignedDepartment

    if not op.id or op.segment_id is None:
        return
    sibling_ids = [
        int(row.id)
        for row in siblings
        if row.id and row.id != op.id and row.segment_id == op.segment_id
    ]
    if not sibling_ids:
        return
    department_ids = list(
        dict.fromkeys(
            int(dep_id)
            for dep_id in db.scalars(
                select(OrderProcessAssignedDepartment.department_id).where(
                    OrderProcessAssignedDepartment.order_process_id.in_(sibling_ids)
                )
            ).all()
        )
    )
    if not department_ids:
        return
    already = {
        int(dep_id)
        for dep_id in db.scalars(
            select(OrderProcessAssignedDepartment.department_id).where(
                OrderProcessAssignedDepartment.order_process_id == op.id
            )
        ).all()
    }
    for department_id in department_ids:
        if department_id in already:
            continue
        db.add(
            OrderProcessAssignedDepartment(
                tenant_id=op.tenant_id,
                order_process_id=op.id,
                department_id=department_id,
            )
        )


def _sync_labors_to_open_orders(db: Session, product: OwnProduct) -> dict:
    """把产品工序同步到 confirmed/in_progress 生产单与无壳执行单。

    - 已有同 process_id：更新名称/类型
    - 产品新增：追加 OrderProcess（plan_qty=总量），并沿用同工序段已有的部门派工
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
                op = OrderProcess(
                    tenant_id=product.tenant_id,
                    order_id=order_id,
                    header_id=header_id,
                    process_id=pid,
                    process_name=labor.process_name or (pdef.name if pdef else str(pid)),
                    process_type=ptype,
                    part_id=part_id,
                    segment_id=pdef.segment_id if pdef else None,  # 工序段重构 7.1
                    plan_qty=plan_qty,
                    status=OrderProcessStatus.pending,
                )
                db.add(op)
                db.flush()
                _copy_segment_department_dispatch(db, op, existing)
                existing.append(op)
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


def _user_can_approve_product(db: Session, user: Employee) -> bool:
    """审批按钮权限。管理员始终可以；不走多级审批流。"""
    from app.services import rbac_service

    codes = set(rbac_service.list_employee_role_codes(db, user))
    if not codes and (user.username or "").strip().lower() == "admin":
        return True
    if "admin" in codes or rbac_service.employee_effective_base_role(db, user) == "admin":
        return True
    granted = set(rbac_service.get_employee_permissions(db, user))
    return "btn.own_products.approve" in granted


def _sync_materials_to_open_orders(db: Session, product: OwnProduct) -> dict:
    """把产品物料同步到在制生产单，保留已到货、已发料进度。"""
    from app.models import ExecutionHeader, Order, OrderStatus, SpecExecutionStatus
    from app.services.material_service import refresh_from_bom, refresh_from_bom_for_header

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
        refresh_from_bom(db, product.tenant_id, order, keep_progress=True)
    headers = list(
        db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == product.tenant_id,
                ExecutionHeader.own_product_id == product.id,
                ExecutionHeader.shop_order_id.is_(None),
                ExecutionHeader.status.in_(
                    (
                        SpecExecutionStatus.confirmed,
                        SpecExecutionStatus.cut,
                        SpecExecutionStatus.in_progress,
                    )
                ),
            )
        ).all()
    )
    for header in headers:
        refresh_from_bom_for_header(db, product.tenant_id, header, keep_progress=True)
    return {"orders": len(orders), "headers": len(headers)}


def _sync_product_to_open_orders(db: Session, product: OwnProduct) -> dict:
    from sqlalchemy.exc import IntegrityError

    from app.services.material_service import MaterialError

    try:
        materials = _sync_materials_to_open_orders(db, product)
        labors = _sync_labors_to_open_orders(db, product)
    except MaterialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=400,
            detail="有物料已挂采购单或领料，不能从在制订单去掉",
        ) from exc
    return {"materials": materials, "labors": labors}


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


def _replace_commissions(
    db: Session,
    product: OwnProduct,
    commissions: list[OwnProductCommissionIn],
) -> Decimal:
    product.commissions.clear()
    db.flush()
    total = Decimal("0")
    seen_employees: set[int] = set()
    for i, row in enumerate(commissions):
        amount = Decimal(row.amount or 0).quantize(Decimal("0.01"))
        if amount < 0:
            raise HTTPException(status_code=400, detail="提成金额不能为负")
        employee_id = row.employee_id
        if employee_id is not None:
            if employee_id in seen_employees:
                raise HTTPException(status_code=400, detail="同一人员不能重复提成")
            emp = db.scalar(
                select(Employee).where(
                    Employee.id == employee_id,
                    Employee.tenant_id == product.tenant_id,
                )
            )
            if not emp:
                raise HTTPException(status_code=400, detail="提成人员不存在")
            seen_employees.add(employee_id)
        if amount == 0 and employee_id is None:
            continue
        total += amount
        product.commissions.append(
            OwnProductCommission(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                employee_id=employee_id,
                amount=amount,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )
    return total.quantize(Decimal("0.0001"))


def _replace_mgmt_commissions(
    db: Session,
    product: OwnProduct,
    rows: list[OwnProductMgmtCommissionIn],
) -> None:
    product.mgmt_commissions.clear()
    db.flush()
    seen: set[int] = set()
    for i, row in enumerate(rows):
        amount = Decimal(row.amount or 0).quantize(Decimal("0.01"))
        if amount < 0:
            raise HTTPException(status_code=400, detail="管理提成金额不能为负")
        if amount == 0:
            continue
        job_title_id = row.job_title_id
        if job_title_id in seen:
            raise HTTPException(status_code=400, detail="同一职务不能重复管理提成")
        title = db.scalar(
            select(JobTitle).where(
                JobTitle.id == job_title_id,
                JobTitle.tenant_id == product.tenant_id,
            )
        )
        if not title:
            raise HTTPException(status_code=400, detail="职务不存在")
        seen.add(job_title_id)
        product.mgmt_commissions.append(
            OwnProductMgmtCommission(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                job_title_id=job_title_id,
                amount=amount,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )


def _refresh_commission_cost(product: OwnProduct) -> Decimal:
    designer = sum((c.amount or Decimal("0") for c in product.commissions or []), Decimal("0"))
    mgmt = sum((c.amount or Decimal("0") for c in product.mgmt_commissions or []), Decimal("0"))
    total = (designer + mgmt).quantize(Decimal("0.0001"))
    product.commission_cost = total
    return total


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


def _replace_brand_quotes(
    db: Session,
    product: OwnProduct,
    quotes: list[OwnProductBrandQuoteIn],
) -> None:
    product.brand_quotes.clear()
    db.flush()
    seen: set[str] = set()
    for i, row in enumerate(quotes):
        brand = db.get(Brand, row.master_brand_id) if row.master_brand_id else None
        if row.master_brand_id:
            if not brand or brand.tenant_id != product.tenant_id or not brand.is_active:
                raise HTTPException(status_code=400, detail="品牌不存在或未启用")
            name = brand.name
        else:
            name = (row.brand_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请选择品牌")
        key = name.lower()
        if key in seen:
            raise HTTPException(status_code=400, detail=f"品牌「{name}」重复报价")
        seen.add(key)
        price = Decimal(row.quote_price or 0)
        if price < 0:
            raise HTTPException(status_code=400, detail="品牌报价不能为负")
        product.brand_quotes.append(
            OwnProductBrandQuote(
                tenant_id=product.tenant_id,
                own_product_id=product.id,
                brand_name=name,
                master_brand_id=brand.id if brand else None,
                quote_price=price,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )


@router.get("")
def list_own_products(
    keyword: str | None = Query(None),
    product_year: int | None = Query(None, ge=2000, le=2100),
    season: str | None = Query(None),
    shoe_last: str | None = Query(None, description="按楦型筛选"),
    approval_status: str | None = Query(None, description="pending | approved"),
    active_only: bool = Query(False),
    sort_by: str = Query("date", description="date | order_qty"),
    sort_order: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    page, page_size, offset = normalize_page(page, page_size)
    q = select(OwnProduct).where(OwnProduct.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(OwnProduct.is_active.is_(True))
    if keyword and keyword.strip():
        q = q.where(OwnProduct.product_code.ilike(f"%{keyword.strip()}%"))
    if product_year is not None:
        q = q.where(OwnProduct.product_year == product_year)
    if season is not None:
        normalized_season = season.strip().upper()
        if normalized_season not in OWN_PRODUCT_SEASONS:
            raise HTTPException(status_code=400, detail="季节仅支持春、夏、秋、冬")
        q = q.where(OwnProduct.season == normalized_season)
    if shoe_last and shoe_last.strip():
        q = q.where(OwnProduct.shoe_last == shoe_last.strip())
    if approval_status in ("pending", "approved"):
        q = q.where(OwnProduct.approval_status == approval_status)

    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0

    sort_col = OwnProduct.order_qty if sort_by == "order_qty" else OwnProduct.created_at
    order_expr = sort_col.asc() if sort_order == "asc" else sort_col.desc()

    rows = db.scalars(
        q.options(
            selectinload(OwnProduct.colors),
            selectinload(OwnProduct.parts),
            selectinload(OwnProduct.materials),
            selectinload(OwnProduct.labors),
            selectinload(OwnProduct.commissions),
            selectinload(OwnProduct.mgmt_commissions),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
            selectinload(OwnProduct.brand_quotes),
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
    user: Employee = Depends(require_roles("admin", "manager")),
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
            selectinload(OwnProduct.commissions),
            selectinload(OwnProduct.mgmt_commissions),
            selectinload(OwnProduct.other_costs),
            selectinload(OwnProduct.quotes),
            selectinload(OwnProduct.brand_quotes),
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


@router.get("/requirement-notes")
def list_requirement_note_history(
    process_id: int | None = Query(None),
    process_name: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """按工序聚合历史工艺要求，供编辑时选用填充。"""
    name = (process_name or "").strip()
    if process_id is None and not name:
        raise HTTPException(status_code=400, detail="请指定工序")

    note_col = OwnProductLabor.requirement_note
    q = (
        select(note_col.label("note"), func.count().label("use_count"))
        .where(
            OwnProductLabor.tenant_id == user.tenant_id,
            note_col.isnot(None),
            note_col != "",
        )
        .group_by(note_col)
        .order_by(func.count().desc(), func.max(OwnProductLabor.id).desc())
        .limit(limit)
    )
    if process_id is not None:
        q = q.where(OwnProductLabor.process_id == process_id)
    else:
        q = q.where(OwnProductLabor.process_name == name)

    rows = db.execute(q).all()
    items = []
    for r in rows:
        note = str(r.note or "").strip()
        if not note:
            continue
        items.append(
            RequirementNoteHistoryOut(note=note, use_count=int(r.use_count or 0)).model_dump()
        )
    return ok({"items": items})


@router.get("/process-price-history")
def list_process_price_history(
    process_id: int | None = Query(None),
    process_name: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """工序价格变更流水（真历史），供编辑时选用填充。"""
    name = (process_name or "").strip()
    if process_id is None and not name:
        raise HTTPException(status_code=400, detail="请指定工序")

    q = (
        select(ProcessPriceHistory)
        .where(ProcessPriceHistory.tenant_id == user.tenant_id)
        .order_by(ProcessPriceHistory.changed_at.desc(), ProcessPriceHistory.id.desc())
        .limit(limit)
    )
    if process_id is not None:
        q = q.where(ProcessPriceHistory.process_id == process_id)
    else:
        q = q.where(ProcessPriceHistory.process_name == name)

    rows = list(db.scalars(q).all())
    emp_ids = {r.changed_by for r in rows if r.changed_by}
    emp_map: dict[int, Employee] = {}
    if emp_ids:
        emp_map = {
            e.id: e
            for e in db.scalars(select(Employee).where(Employee.id.in_(list(emp_ids)))).all()
        }
    items = [
        ProcessPriceHistoryOut(
            id=r.id,
            process_id=r.process_id,
            process_name=r.process_name,
            own_product_id=r.own_product_id,
            product_code=r.product_code,
            old_price=r.old_price,
            new_price=r.new_price,
            changed_by=r.changed_by,
            changed_by_name=(emp_map[r.changed_by].name if r.changed_by in emp_map else None),
            changed_at=r.changed_at,
            source=r.source or "product_save",
        ).model_dump(mode="json")
        for r in rows
    ]
    return ok({"items": items})


@router.get("/material-usage-history")
def list_material_qty_history(
    own_product_id: int = Query(...),
    supplier_product_id: int = Query(...),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """产品物料用量变更流水，供裁断用料和产品用料两边回看、回填。"""
    rows = list_material_usage_history(
        db,
        user.tenant_id,
        own_product_id=own_product_id,
        supplier_product_id=supplier_product_id,
        limit=limit,
    )
    names = changed_by_names(db, rows)
    items = [
        MaterialUsageHistoryOut(
            id=row.id,
            own_product_id=row.own_product_id,
            product_code=row.product_code,
            supplier_product_id=row.supplier_product_id,
            material_code=row.material_code,
            material_name=row.material_name,
            old_qty=row.old_qty,
            new_qty=row.new_qty,
            changed_by=row.changed_by,
            changed_by_name=names.get(row.changed_by) if row.changed_by else None,
            changed_at=row.changed_at,
            source=row.source or "product_save",
        ).model_dump(mode="json")
        for row in rows
    ]
    return ok({"items": items})


@router.get("/materials/import-template")
def download_material_import_template(
    user: Employee = Depends(require_permissions("btn.own_products.write")),
):
    from urllib.parse import quote

    from fastapi.responses import Response

    _ = user
    content = build_own_product_material_import_template()
    filename = "产品物料导入模版.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="own_product_materials_import.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/materials/import")
async def import_product_materials(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.own_products.write")),
    file: UploadFile | None = File(None),
):
    """解析物料表，返回可填入当前成品颜色的明细，不直接保存。"""
    if not file:
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    name = (file.filename or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 8MB")
    try:
        result = parse_own_product_materials_xlsx(db, user.tenant_id, raw)
    except OwnProductMaterialImportError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return ok(result)


def _route_template_out(tpl: ProcessRouteTemplate, db: Session) -> dict:
    seg_ids = [i.segment_id for i in (tpl.items or []) if i.segment_id]
    seg_map: dict[int, ProcessSegment] = {}
    if seg_ids:
        seg_map = {
            s.id: s
            for s in db.scalars(select(ProcessSegment).where(ProcessSegment.id.in_(seg_ids))).all()
        }
    items = [
        ProcessRouteTemplateItemOut(
            id=row.id,
            process_id=row.process_id,
            process_name=row.process_name,
            requirement_note=row.requirement_note,
            unit_price=row.unit_price,
            segment_id=row.segment_id,
            segment_name=(seg_map[row.segment_id].name if row.segment_id in seg_map else None),
            sort_order=row.sort_order,
        )
        for row in sorted(tpl.items or [], key=lambda x: (x.sort_order, x.id))
    ]
    ref = getattr(tpl, "segment_ref_prices", None) or None
    return ProcessRouteTemplateOut(
        id=tpl.id,
        name=tpl.name,
        segment_ref_prices=ref,
        items=items,
        is_active=bool(tpl.is_active),
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    ).model_dump(mode="json")


@router.get("/route-templates")
def list_route_templates(
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    rows = db.scalars(
        select(ProcessRouteTemplate)
        .where(
            ProcessRouteTemplate.tenant_id == user.tenant_id,
            ProcessRouteTemplate.is_active.is_(True),
        )
        .options(selectinload(ProcessRouteTemplate.items))
        .order_by(ProcessRouteTemplate.updated_at.desc(), ProcessRouteTemplate.id.desc())
    ).all()
    return ok({"items": [_route_template_out(r, db) for r in rows]})


@router.post("/route-templates")
def create_route_template(
    body: ProcessRouteTemplateCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写模版名称")
    items_in = [
        row
        for row in (body.items or [])
        if (row.process_name or "").strip()
    ]
    if not items_in and not (body.segment_ref_prices or {}):
        raise HTTPException(status_code=400, detail="模版至少需要一道工序或段参考价")

    exists = db.scalar(
        select(ProcessRouteTemplate.id).where(
            ProcessRouteTemplate.tenant_id == user.tenant_id,
            ProcessRouteTemplate.name == name,
            ProcessRouteTemplate.is_active.is_(True),
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"模版「{name}」已存在")

    process_names = {(row.process_name or "").strip() for row in items_in}
    process_map: dict[str, ProcessDefinition] = {}
    if process_names:
        for p in db.scalars(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == user.tenant_id,
                ProcessDefinition.name.in_(list(process_names)),
            )
        ).all():
            process_map[p.name] = p

    ref_payload: dict[str, float] | None = None
    if body.segment_ref_prices:
        cleaned: dict[str, float] = {}
        for k, v in body.segment_ref_prices.items():
            n = float(Decimal(v or 0))
            if n > 0:
                cleaned[str(k)] = n
        ref_payload = cleaned or None

    tpl = ProcessRouteTemplate(
        tenant_id=user.tenant_id,
        name=name,
        segment_ref_prices=ref_payload,
        is_active=True,
    )
    db.add(tpl)
    db.flush()
    for i, row in enumerate(items_in):
        pname = (row.process_name or "").strip()
        proc = process_map.get(pname)
        unit = Decimal(row.unit_price or 0)
        if unit < 0:
            raise HTTPException(status_code=400, detail="工序价格不能为负")
        seg_id = row.segment_id
        if seg_id is None and proc is not None:
            seg_id = proc.segment_id
        tpl.items.append(
            ProcessRouteTemplateItem(
                tenant_id=user.tenant_id,
                template_id=tpl.id,
                process_id=proc.id if proc else None,
                process_name=pname,
                requirement_note=(row.requirement_note or "").strip() or None,
                unit_price=unit,
                segment_id=seg_id,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )
    db.commit()
    db.refresh(tpl)
    tpl = db.scalar(
        select(ProcessRouteTemplate)
        .where(ProcessRouteTemplate.id == tpl.id)
        .options(selectinload(ProcessRouteTemplate.items))
    )
    return ok(_route_template_out(tpl, db))


@router.get("/route-templates/{template_id}")
def get_route_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    tpl = db.scalar(
        select(ProcessRouteTemplate)
        .where(
            ProcessRouteTemplate.id == template_id,
            ProcessRouteTemplate.tenant_id == user.tenant_id,
        )
        .options(selectinload(ProcessRouteTemplate.items))
    )
    if not tpl or not tpl.is_active:
        raise HTTPException(status_code=404, detail="模版不存在")
    return ok(_route_template_out(tpl, db))


@router.delete("/route-templates/{template_id}")
def delete_route_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    tpl = db.scalar(
        select(ProcessRouteTemplate).where(
            ProcessRouteTemplate.id == template_id,
            ProcessRouteTemplate.tenant_id == user.tenant_id,
        )
    )
    if not tpl or not tpl.is_active:
        raise HTTPException(status_code=404, detail="模版不存在")
    tpl.is_active = False
    db.commit()
    return ok({"id": template_id})


def _mgmt_commission_template_out(tpl: MgmtCommissionTemplate, db: Session) -> dict:
    title_ids = [row.job_title_id for row in (tpl.items or [])]
    title_map: dict[int, JobTitle] = {}
    if title_ids:
        title_map = {
            row.id: row
            for row in db.scalars(select(JobTitle).where(JobTitle.id.in_(title_ids))).all()
        }
    items = [
        MgmtCommissionTemplateItemOut(
            id=row.id,
            job_title_id=row.job_title_id,
            job_title_name=title_map[row.job_title_id].name if row.job_title_id in title_map else None,
            amount=row.amount,
            sort_order=row.sort_order,
        )
        for row in sorted(tpl.items or [], key=lambda x: (x.sort_order, x.id))
    ]
    return MgmtCommissionTemplateOut(
        id=tpl.id,
        name=tpl.name,
        items=items,
        is_active=bool(tpl.is_active),
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    ).model_dump(mode="json")


def _other_cost_template_out(tpl: OtherCostTemplate) -> dict:
    items = [
        OtherCostTemplateItemOut(
            id=row.id,
            name=row.name,
            amount=row.amount,
            sort_order=row.sort_order,
        )
        for row in sorted(tpl.items or [], key=lambda x: (x.sort_order, x.id))
    ]
    return OtherCostTemplateOut(
        id=tpl.id,
        name=tpl.name,
        items=items,
        is_active=bool(tpl.is_active),
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    ).model_dump(mode="json")


@router.get("/mgmt-commission-templates")
def list_mgmt_commission_templates(
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    rows = db.scalars(
        select(MgmtCommissionTemplate)
        .where(
            MgmtCommissionTemplate.tenant_id == user.tenant_id,
            MgmtCommissionTemplate.is_active.is_(True),
        )
        .options(selectinload(MgmtCommissionTemplate.items))
        .order_by(MgmtCommissionTemplate.updated_at.desc(), MgmtCommissionTemplate.id.desc())
    ).all()
    return ok({"items": [_mgmt_commission_template_out(r, db) for r in rows]})


@router.post("/mgmt-commission-templates")
def create_mgmt_commission_template(
    body: MgmtCommissionTemplateCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写模版名称")
    items_in = [row for row in (body.items or []) if row.job_title_id and Decimal(row.amount or 0) > 0]
    if not items_in:
        raise HTTPException(status_code=400, detail="模版至少需要一项管理提成")
    exists = db.scalar(
        select(MgmtCommissionTemplate.id).where(
            MgmtCommissionTemplate.tenant_id == user.tenant_id,
            MgmtCommissionTemplate.name == name,
            MgmtCommissionTemplate.is_active.is_(True),
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"模版「{name}」已存在")
    seen: set[int] = set()
    title_ids = [row.job_title_id for row in items_in]
    titles = {
        row.id: row
        for row in db.scalars(
            select(JobTitle).where(
                JobTitle.tenant_id == user.tenant_id,
                JobTitle.id.in_(title_ids),
            )
        ).all()
    }
    tpl = MgmtCommissionTemplate(tenant_id=user.tenant_id, name=name, is_active=True)
    db.add(tpl)
    db.flush()
    for i, row in enumerate(items_in):
        if row.job_title_id in seen:
            raise HTTPException(status_code=400, detail="同一职务不能重复")
        if row.job_title_id not in titles:
            raise HTTPException(status_code=400, detail="职务不存在")
        amount = Decimal(row.amount or 0).quantize(Decimal("0.01"))
        if amount < 0:
            raise HTTPException(status_code=400, detail="管理提成金额不能为负")
        seen.add(row.job_title_id)
        tpl.items.append(
            MgmtCommissionTemplateItem(
                tenant_id=user.tenant_id,
                template_id=tpl.id,
                job_title_id=row.job_title_id,
                amount=amount,
                sort_order=row.sort_order if row.sort_order else i,
            )
        )
    db.commit()
    tpl = db.scalar(
        select(MgmtCommissionTemplate)
        .where(MgmtCommissionTemplate.id == tpl.id)
        .options(selectinload(MgmtCommissionTemplate.items))
    )
    return ok(_mgmt_commission_template_out(tpl, db))


@router.delete("/mgmt-commission-templates/{template_id}")
def delete_mgmt_commission_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    tpl = db.scalar(
        select(MgmtCommissionTemplate).where(
            MgmtCommissionTemplate.id == template_id,
            MgmtCommissionTemplate.tenant_id == user.tenant_id,
        )
    )
    if not tpl or not tpl.is_active:
        raise HTTPException(status_code=404, detail="模版不存在")
    tpl.is_active = False
    db.commit()
    return ok({"id": template_id})


@router.get("/other-cost-templates")
def list_other_cost_templates(
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    rows = db.scalars(
        select(OtherCostTemplate)
        .where(
            OtherCostTemplate.tenant_id == user.tenant_id,
            OtherCostTemplate.is_active.is_(True),
        )
        .options(selectinload(OtherCostTemplate.items))
        .order_by(OtherCostTemplate.updated_at.desc(), OtherCostTemplate.id.desc())
    ).all()
    return ok({"items": [_other_cost_template_out(r) for r in rows]})


@router.post("/other-cost-templates")
def create_other_cost_template(
    body: OtherCostTemplateCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写模版名称")
    items_in = []
    seen_names: set[str] = set()
    for row in body.items or []:
        item_name = (row.name or "").strip()
        amount = Decimal(row.amount or 0)
        if not item_name or amount <= 0:
            continue
        if item_name in seen_names:
            raise HTTPException(status_code=400, detail="其它成本项目不能重复")
        if amount < 0:
            raise HTTPException(status_code=400, detail="其它成本金额不能为负")
        seen_names.add(item_name)
        items_in.append((item_name, amount.quantize(Decimal("0.0001")), row.sort_order))
    if not items_in:
        raise HTTPException(status_code=400, detail="模版至少需要一项其它成本")
    exists = db.scalar(
        select(OtherCostTemplate.id).where(
            OtherCostTemplate.tenant_id == user.tenant_id,
            OtherCostTemplate.name == name,
            OtherCostTemplate.is_active.is_(True),
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"模版「{name}」已存在")
    tpl = OtherCostTemplate(tenant_id=user.tenant_id, name=name, is_active=True)
    db.add(tpl)
    db.flush()
    for i, (item_name, amount, sort_order) in enumerate(items_in):
        tpl.items.append(
            OtherCostTemplateItem(
                tenant_id=user.tenant_id,
                template_id=tpl.id,
                name=item_name,
                amount=amount,
                sort_order=sort_order if sort_order else i,
            )
        )
    db.commit()
    tpl = db.scalar(
        select(OtherCostTemplate)
        .where(OtherCostTemplate.id == tpl.id)
        .options(selectinload(OtherCostTemplate.items))
    )
    return ok(_other_cost_template_out(tpl))


@router.delete("/other-cost-templates/{template_id}")
def delete_other_cost_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    tpl = db.scalar(
        select(OtherCostTemplate).where(
            OtherCostTemplate.id == template_id,
            OtherCostTemplate.tenant_id == user.tenant_id,
        )
    )
    if not tpl or not tpl.is_active:
        raise HTTPException(status_code=404, detail="模版不存在")
    tpl.is_active = False
    db.commit()
    return ok({"id": template_id})


@router.get("/field-history")
def own_product_field_history(
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    def _values(column):
        rows = db.execute(
            select(column, func.max(OwnProduct.updated_at).label("used_at"))
            .where(
                OwnProduct.tenant_id == user.tenant_id,
                column.is_not(None),
                column != "",
            )
            .group_by(column)
            .order_by(func.max(OwnProduct.updated_at).desc(), column)
        ).all()
        return [row[0] for row in rows]

    return ok({
        "fabrics": _values(OwnProduct.fabric),
        "linings": _values(OwnProduct.lining),
    })


@router.get("/{product_id}/export")
def export_own_product(
    product_id: int,
    partner_id: int | None = Query(None, description="已废弃，成本明细不再含报价"),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
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
    user: Employee = Depends(require_roles("admin", "manager")),
):
    code = body.product_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写工厂型号")
    exists = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == user.tenant_id, OwnProduct.product_code == code)
    )
    if exists:
        raise HTTPException(status_code=400, detail="工厂型号已存在")
    _ensure_colors(db, user.tenant_id, body.color_ids)

    def _resolve_card_id(product_id: int | None, code_text, *, label: str) -> int | None:
        if product_id is not None:
            return product_id
        text = _normalize_product_text(code_text, label)
        if text is None:
            return None
        card = db.scalar(
            select(SupplierProduct)
            .where(
                SupplierProduct.tenant_id == user.tenant_id,
                SupplierProduct.product_code == text,
            )
            .limit(1)
        )
        if not card:
            raise HTTPException(status_code=400, detail=f"请从物料色卡中选择{label}")
        _require_field_category(db, card, label)
        return card.id

    shoe_last_product_id, shoe_last = _apply_color_card_field(
        db,
        user.tenant_id,
        _resolve_card_id(
            getattr(body, "shoe_last_product_id", None),
            getattr(body, "shoe_last", None),
            label="楦型",
        ),
        label="楦型",
    )
    sole_mold_product_id, sole_mold = _apply_color_card_field(
        db,
        user.tenant_id,
        _resolve_card_id(
            getattr(body, "sole_mold_product_id", None),
            getattr(body, "sole_mold", None),
            label="鞋底型号",
        ),
        label="鞋底型号",
    )
    heel_model_id, _heel_code = _apply_color_card_field(
        db, user.tenant_id, getattr(body, "heel_model_id", None), label="鞋跟型号"
    )
    heel_model_2_id, _heel2_code = _apply_color_card_field(
        db, user.tenant_id, getattr(body, "heel_model_2_id", None), label="鞋跟型号"
    )
    shoe_last_hours = _normalize_shoe_last_hours(getattr(body, "shoe_last_hours", None))
    p = OwnProduct(
        tenant_id=user.tenant_id,
        product_code=code,
        product_year=body.product_year,
        season=body.season,
        image_url=(body.image_url or "").strip() or None,
        fabric=(body.fabric or "").strip() or None,
        lining=(body.lining or "").strip() or None,
        shoe_last=shoe_last,
        sole_mold=sole_mold,
        shoe_last_product_id=shoe_last_product_id,
        sole_mold_product_id=sole_mold_product_id,
        heel_model_id=heel_model_id,
        heel_model_2_id=heel_model_2_id,
        shoe_last_hours=shoe_last_hours,
        is_active=body.is_active,
        trace_enabled=bool(body.trace_enabled),
        material_cost=Decimal("0"),
        quote_price=Decimal(body.quote_price) if body.quote_price is not None else None,
        order_qty=max(0, int(body.order_qty or 0)),
        labor_cost=Decimal("0"),
        commission_cost=Decimal("0"),
        other_cost=Decimal("0"),
        segment_ref_prices=_normalize_segment_ref_prices(
            getattr(body, "segment_ref_prices", None)
        ),
        approval_status="approved" if _user_can_approve_product(db, user) else "pending",
    )
    if p.quote_price is not None and p.quote_price < 0:
        raise HTTPException(status_code=400, detail="统一报价不能为负")
    db.add(p)
    db.flush()
    _replace_colors(db, p, body.color_ids)
    _replace_parts(db, p, list(body.parts or []))
    old_materials = []
    p.material_cost = _replace_materials(db, p, body.materials)
    record_material_qty_changes(
        db, p, old_materials, changed_by=user.id, source="product_create"
    )
    _replace_labors(db, p, body.labors, changed_by=user.id, source="product_create")
    p.labor_cost = _compute_labor_cost(
        list(p.labors or []),
        p.segment_ref_prices,
        departments_by_segment=_multi_segment_departments(db, user.tenant_id),
    )
    _replace_commissions(db, p, list(body.commissions or []))
    _replace_mgmt_commissions(db, p, list(getattr(body, "mgmt_commissions", None) or []))
    _refresh_commission_cost(p)
    p.other_cost = _replace_other_costs(db, p, body.other_costs)
    _replace_quotes(db, p, body.quotes)
    _replace_brand_quotes(db, p, list(body.brand_quotes or []))
    db.flush()
    p = _get_product(db, user.tenant_id, p.id)
    _save_product_version(db, p, changed_by=user.id, source="product_create")
    db.commit()
    p = _get_product(db, user.tenant_id, p.id)
    return ok(_product_out(p, db))


@router.get("/{product_id}/peer-actuals")
def get_own_product_peer_actuals(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
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
    user: Employee = Depends(get_current_employee),
):
    p = _get_product(db, user.tenant_id, product_id)
    return ok(_product_out(p, db))


@router.get("/{product_id}/versions")
def list_own_product_versions(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """产品完整档案版本列表（不含 snapshot 正文）。"""
    _get_product(db, user.tenant_id, product_id)
    rows = list(
        db.scalars(
            select(OwnProductVersion)
            .where(
                OwnProductVersion.tenant_id == user.tenant_id,
                OwnProductVersion.own_product_id == product_id,
            )
            .order_by(OwnProductVersion.version_no.desc(), OwnProductVersion.id.desc())
        ).all()
    )
    emp_ids = {r.changed_by for r in rows if r.changed_by}
    emp_map: dict[int, Employee] = {}
    if emp_ids:
        emp_map = {
            e.id: e
            for e in db.scalars(select(Employee).where(Employee.id.in_(list(emp_ids)))).all()
        }
    items = [
        OwnProductVersionListItem(
            id=r.id,
            version_no=r.version_no,
            changed_by=r.changed_by,
            changed_by_name=(emp_map[r.changed_by].name if r.changed_by in emp_map else None),
            changed_at=r.changed_at,
            source=r.source,
            changed_sections=list(r.changed_sections or []),
            changed_section_labels=_section_labels(list(r.changed_sections or [])),
        ).model_dump(mode="json")
        for r in rows
    ]
    return ok({"items": items})


@router.get("/{product_id}/versions/{version_id}")
def get_own_product_version(
    product_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """单条完整档案快照。"""
    _get_product(db, user.tenant_id, product_id)
    row = db.scalar(
        select(OwnProductVersion).where(
            OwnProductVersion.id == version_id,
            OwnProductVersion.tenant_id == user.tenant_id,
            OwnProductVersion.own_product_id == product_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    changed_by_name = None
    if row.changed_by:
        emp = db.get(Employee, row.changed_by)
        if emp and emp.tenant_id == user.tenant_id:
            changed_by_name = emp.name
    sections = list(row.changed_sections or [])
    return ok(
        OwnProductVersionOut(
            id=row.id,
            own_product_id=row.own_product_id,
            version_no=row.version_no,
            changed_by=row.changed_by,
            changed_by_name=changed_by_name,
            changed_at=row.changed_at,
            source=row.source,
            changed_sections=sections,
            changed_section_labels=_section_labels(sections),
            snapshot=row.snapshot or {},
        ).model_dump(mode="json")
    )


@router.patch("/{product_id}")
def update_own_product(
    product_id: int,
    body: OwnProductUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    p = _get_product(db, user.tenant_id, product_id)
    data = body.model_dump(exclude_unset=True)
    if "product_code" in data:
        code = (data["product_code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="请填写工厂型号")
        dup = db.scalar(
            select(OwnProduct).where(
                OwnProduct.tenant_id == user.tenant_id,
                OwnProduct.product_code == code,
                OwnProduct.id != product_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="工厂型号已存在")
        p.product_code = code
    if "product_year" in data and data["product_year"] is not None:
        p.product_year = int(data["product_year"])
    if "season" in data and data["season"] is not None:
        p.season = data["season"]
    if "image_url" in data:
        p.image_url = (data["image_url"] or "").strip() or None
    if "fabric" in data:
        p.fabric = (data["fabric"] or "").strip() or None
    if "lining" in data:
        p.lining = (data["lining"] or "").strip() or None
    if "shoe_last_product_id" in data:
        pid, code_text = _apply_color_card_field(
            db, user.tenant_id, data["shoe_last_product_id"], label="楦型"
        )
        p.shoe_last_product_id = pid
        p.shoe_last = code_text
    elif "shoe_last" in data:
        # 兼容旧客户端：只接受色卡编号，不再允许任意手填
        text = _normalize_product_text(data["shoe_last"], "楦型")
        if text is None:
            p.shoe_last = None
            p.shoe_last_product_id = None
        else:
            card = db.scalar(
                select(SupplierProduct)
                .where(
                    SupplierProduct.tenant_id == user.tenant_id,
                    SupplierProduct.product_code == text,
                )
                .limit(1)
            )
            if not card:
                raise HTTPException(status_code=400, detail="请从「楦头」分类中选择楦型")
            _require_field_category(db, card, "楦型")
            p.shoe_last = text
            p.shoe_last_product_id = card.id
    if "sole_mold_product_id" in data:
        pid, code_text = _apply_color_card_field(
            db, user.tenant_id, data["sole_mold_product_id"], label="鞋底型号"
        )
        p.sole_mold_product_id = pid
        p.sole_mold = code_text
    elif "sole_mold" in data:
        text = _normalize_product_text(data["sole_mold"], "鞋底型号")
        if text is None:
            p.sole_mold = None
            p.sole_mold_product_id = None
        else:
            card = db.scalar(
                select(SupplierProduct)
                .where(
                    SupplierProduct.tenant_id == user.tenant_id,
                    SupplierProduct.product_code == text,
                )
                .limit(1)
            )
            if not card:
                raise HTTPException(status_code=400, detail="请从「大底」分类中选择鞋底型号")
            _require_field_category(db, card, "鞋底型号")
            p.sole_mold = text
            p.sole_mold_product_id = card.id
    if "heel_model_id" in data:
        pid, _code = _apply_color_card_field(
            db, user.tenant_id, data["heel_model_id"], label="鞋跟型号"
        )
        p.heel_model_id = pid
    if "heel_model_2_id" in data:
        pid, _code = _apply_color_card_field(
            db, user.tenant_id, data["heel_model_2_id"], label="鞋跟型号"
        )
        p.heel_model_2_id = pid
    if "shoe_last_hours" in data:
        p.shoe_last_hours = _normalize_shoe_last_hours(data["shoe_last_hours"])
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
        old_materials = snapshot_material_qty(p.materials)
        p.material_cost = _replace_materials(db, p, list(body.materials or []))
        record_material_qty_changes(
            db, p, old_materials, changed_by=user.id, source="product_save"
        )
    if "labors" in data and data["labors"] is not None:
        # 若同请求也改了 parts，先 flush 保证 labors 校验能看到新部件清单
        if "parts" in data and data["parts"] is not None:
            db.flush()
        _replace_labors(
            db,
            p,
            list(body.labors or []),
            changed_by=user.id,
            source="product_save",
        )
    if "segment_ref_prices" in data:
        p.segment_ref_prices = _normalize_segment_ref_prices(data["segment_ref_prices"])
    if "labors" in data or "segment_ref_prices" in data:
        p.labor_cost = _compute_labor_cost(
            list(p.labors or []),
            p.segment_ref_prices,
            departments_by_segment=_multi_segment_departments(db, user.tenant_id),
        )
    if "other_costs" in data and data["other_costs"] is not None:
        p.other_cost = _replace_other_costs(db, p, list(body.other_costs or []))
    if "commissions" in data and data["commissions"] is not None:
        _replace_commissions(db, p, list(body.commissions or []))
    if "mgmt_commissions" in data and data["mgmt_commissions"] is not None:
        _replace_mgmt_commissions(db, p, list(body.mgmt_commissions or []))
    if ("commissions" in data and data["commissions"] is not None) or (
        "mgmt_commissions" in data and data["mgmt_commissions"] is not None
    ):
        _refresh_commission_cost(p)
    if "quotes" in data and data["quotes"] is not None:
        _replace_quotes(db, p, list(body.quotes or []))
    if "brand_quotes" in data and data["brand_quotes"] is not None:
        _replace_brand_quotes(db, p, list(body.brand_quotes or []))
    db.flush()
    p = _get_product(db, user.tenant_id, product_id)
    touches_production = ("materials" in data and data["materials"] is not None) or (
        "labors" in data and data["labors"] is not None
    )
    was_pending = (getattr(p, "approval_status", None) or "approved") != "approved"
    materials_changed = "materials" in data and data["materials"] is not None
    if _user_can_approve_product(db, user):
        p.approval_status = "approved"
        if (
            was_pending
            or touches_production
            or bool(getattr(body, "sync_labors_to_open_orders", False))
        ):
            _sync_product_to_open_orders(db, p)
    else:
        p.approval_status = "pending"
        if materials_changed:
            _sync_materials_to_open_orders(db, p)
    db.flush()
    p = _get_product(db, user.tenant_id, product_id)
    _save_product_version(db, p, changed_by=user.id, source="product_save")
    db.commit()
    p = _get_product(db, user.tenant_id, product_id)
    return ok(_product_out(p, db))


@router.post("/{product_id}/approve")
def approve_own_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.own_products.approve")),
):
    """通过当前产品档案，并把物料、工艺路线同步到在制订单。"""
    p = _get_product(db, user.tenant_id, product_id)
    p.approval_status = "approved"
    sync = _sync_product_to_open_orders(db, p)
    db.flush()
    p = _get_product(db, user.tenant_id, product_id)
    _save_product_version(db, p, changed_by=user.id, source="product_approve")
    db.commit()
    p = _get_product(db, user.tenant_id, product_id)
    payload = _product_out(p, db)
    payload["sync"] = sync
    return ok(payload)


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
    user: Employee = Depends(require_roles("admin", "manager")),
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
    # 版本和用量/工价流水是产品自己的历史，不是外部引用，随产品一起删。
    for model in (OwnProductVersion, MaterialUsageHistory, ProcessPriceHistory):
        for row in db.scalars(
            select(model).where(
                model.tenant_id == user.tenant_id,
                model.own_product_id == product_id,
            )
        ).all():
            db.delete(row)
    db.delete(p)
    db.commit()
    return ok({"deleted": True, "id": product_id})
