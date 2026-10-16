"""供应商产品档案。"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

import qrcode
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_permissions
from app.config import get_settings
from app.db import get_db
from app.models import (
    BatchMaterialConsumption,
    Color,
    Employee,
    MaterialCategory,
    MaterialIqcRecord,
    MaterialUsageHistory,
    MiscMaterialPickupLine,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductMaterial,
    OwnProductPart,
    Partner,
    PayableLine,
    PricingUnit,
    PurchaseOrderLine,
    SharedMaterialLedger,
    SharedMaterialStock,
    StockDocLine,
    SupplierProduct,
    WarehousePickupLine,
    WorkshopMaterialCount,
)
from app.schemas.api import SupplierProductCreate, SupplierProductOut, SupplierProductUpdate
from app.schemas.common import normalize_page, ok, page_payload
from app.services.supplier_product_price import (
    catalog_approved,
    list_catalog_price_history,
    price_histories_for_products,
    record_catalog_price_change,
    record_catalog_supplier_change,
    supplier_histories_for_products,
)
from app.services.supplier_product_import import (
    SupplierProductImportError,
    build_supplier_product_import_template,
    import_supplier_products_xlsx,
)

router = APIRouter(prefix="/supplier-products", tags=["supplier-products"])

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _uploads_dir() -> Path:
    settings = get_settings()
    path = Path(settings.uploads_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _product_out(
    p: SupplierProduct,
    partner: Partner | None,
    color: Color | None,
    category: MaterialCategory | None,
    unit: PricingUnit | None,
) -> dict:
    out = SupplierProductOut(
        id=p.id,
        product_code=p.product_code,
        name=p.name,
        category_id=p.category_id,
        category_name=category.name if category else None,
        image_url=p.image_url,
        internal_code=p.internal_code,
        pricing_unit_id=p.pricing_unit_id,
        pricing_unit_name=unit.name if unit else None,
        unit_price=p.unit_price,
        color_id=p.color_id,
        color_name=color.name if color else None,
        partner_id=p.partner_id,
        partner_name=partner.name if partner else None,
        is_active=bool(p.is_active),
        approval_status=getattr(p, "approval_status", None) or "approved",
        min_stock_qty=getattr(p, "min_stock_qty", None),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
    return out.model_dump(mode="json")


def _ensure_supplier(db: Session, tenant_id: int, partner_id: int) -> Partner:
    p = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.tenant_id == tenant_id,
            Partner.is_supplier.is_(True),
        )
    )
    if not p:
        raise HTTPException(status_code=400, detail="供应商不存在或未标记为供应商")
    return p


def _ensure_color(db: Session, tenant_id: int, color_id: int | None) -> Color | None:
    if not color_id:
        return None
    c = db.scalar(select(Color).where(Color.id == color_id, Color.tenant_id == tenant_id))
    if not c:
        raise HTTPException(status_code=400, detail="颜色不存在")
    return c


def _ensure_category(db: Session, tenant_id: int, category_id: int | None) -> MaterialCategory | None:
    if not category_id:
        return None
    c = db.scalar(
        select(MaterialCategory).where(
            MaterialCategory.id == category_id,
            MaterialCategory.tenant_id == tenant_id,
        )
    )
    if not c:
        raise HTTPException(status_code=400, detail="物料分类不存在")
    return c


def _ensure_unit(db: Session, tenant_id: int, unit_id: int | None) -> PricingUnit | None:
    if not unit_id:
        return None
    u = db.scalar(
        select(PricingUnit).where(PricingUnit.id == unit_id, PricingUnit.tenant_id == tenant_id)
    )
    if not u:
        raise HTTPException(status_code=400, detail="计价单位不存在")
    return u


def request_public_origin(request: Request) -> str:
    """打印页所在站点。优先用 Referer，避免开发时代理把二维码打成 API 端口。"""
    referer = request.headers.get("referer") or ""
    parsed = urlparse(referer)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


def material_label_scan_url(origin: str, product_code: str) -> str:
    return f"{origin.rstrip('/')}/material?code={quote(product_code, safe='')}"


def _get_product(db: Session, tenant_id: int, product_id: int) -> SupplierProduct:
    p = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.id == product_id,
            SupplierProduct.tenant_id == tenant_id,
        )
    )
    if not p:
        raise HTTPException(status_code=404, detail="供应商产品不存在")
    return p


def _user_can_approve_catalog(db: Session, user: Employee) -> bool:
    """物料色卡审批权限。管理员始终可以。"""
    from app.services import rbac_service

    codes = set(rbac_service.list_employee_role_codes(db, user))
    if not codes and (user.username or "").strip().lower() == "admin":
        return True
    if "admin" in codes or rbac_service.employee_effective_base_role(db, user) == "admin":
        return True
    granted = set(rbac_service.get_employee_permissions(db, user))
    return "btn.supplier_products.approve" in granted


def _load_related(db: Session, p: SupplierProduct):
    partner = db.get(Partner, p.partner_id)
    color = db.get(Color, p.color_id) if p.color_id else None
    category = db.get(MaterialCategory, p.category_id) if p.category_id else None
    unit = db.get(PricingUnit, p.pricing_unit_id) if p.pricing_unit_id else None
    return partner, color, category, unit


@router.get("")
def list_products(
    partner_id: int | None = Query(None),
    category_id: int | None = Query(None),
    keyword: str | None = Query(None),
    active_only: bool = Query(False),
    approval_status: str | None = Query(None, description="pending | approved"),
    approved_only: bool = Query(False),
    sort_by: str = Query("id", description="product_code|name|color_name|category_name|unit_price|pricing_unit_name|partner_name|created_at|id"),
    sort_order: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    page, page_size, offset = normalize_page(page, page_size)
    q = (
        select(SupplierProduct, Partner, Color, MaterialCategory, PricingUnit)
        .join(Partner, Partner.id == SupplierProduct.partner_id)
        .outerjoin(Color, Color.id == SupplierProduct.color_id)
        .outerjoin(MaterialCategory, MaterialCategory.id == SupplierProduct.category_id)
        .outerjoin(PricingUnit, PricingUnit.id == SupplierProduct.pricing_unit_id)
        .where(SupplierProduct.tenant_id == user.tenant_id)
    )
    if partner_id:
        q = q.where(SupplierProduct.partner_id == partner_id)
    if category_id:
        q = q.where(SupplierProduct.category_id == category_id)
    if active_only:
        q = q.where(SupplierProduct.is_active.is_(True))
    if approved_only:
        q = q.where(SupplierProduct.approval_status == "approved")
    elif approval_status in ("pending", "approved"):
        q = q.where(SupplierProduct.approval_status == approval_status)
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(
            or_(
                SupplierProduct.product_code.ilike(kw),
                SupplierProduct.name.ilike(kw),
                SupplierProduct.internal_code.ilike(kw),
                Partner.name.ilike(kw),
                Color.name.ilike(kw),
                MaterialCategory.name.ilike(kw),
                PricingUnit.name.ilike(kw),
            )
        )
    sort_map = {
        "id": SupplierProduct.id,
        "product_code": SupplierProduct.product_code,
        "name": SupplierProduct.name,
        "unit_price": SupplierProduct.unit_price,
        "created_at": SupplierProduct.created_at,
        "color_name": Color.name,
        "category_name": MaterialCategory.name,
        "pricing_unit_name": PricingUnit.name,
        "partner_name": Partner.name,
    }
    sort_col = sort_map.get(sort_by, SupplierProduct.id)
    order_expr = sort_col.asc() if sort_order == "asc" else sort_col.desc()
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.execute(
        q.order_by(order_expr, SupplierProduct.id.desc()).offset(offset).limit(page_size)
    ).all()
    items = [_product_out(p, partner, color, cat, unit) for p, partner, color, cat, unit in rows]
    product_ids = [item["id"] for item in items]
    histories = price_histories_for_products(db, user.tenant_id, product_ids)
    supplier_histories = supplier_histories_for_products(db, user.tenant_id, product_ids)
    for item in items:
        rows_history = histories.get(item["id"]) or []
        item["has_price_history"] = bool(rows_history)
        item["price_histories"] = rows_history
        supplier_rows = supplier_histories.get(item["id"]) or []
        item["has_supplier_history"] = bool(supplier_rows)
        item["supplier_histories"] = supplier_rows
    return ok(page_payload(items, int(total), page, page_size))


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user: Employee = Depends(
        require_permissions("btn.supplier_products.write", "btn.shared_materials.write")
    ),
):
    _ = user
    filename = file.filename or "image.jpg"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="仅支持 jpg/png/gif/webp 图片")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = _uploads_dir() / name
    dest.write_bytes(raw)
    return ok({"url": f"/uploads/{name}", "filename": name})


def _require_duplicate_confirm(
    db: Session,
    tenant_id: int,
    code: str,
    *,
    exclude_id: int | None,
    confirmed: bool,
) -> None:
    if confirmed:
        return
    q = select(SupplierProduct.id).where(
        SupplierProduct.tenant_id == tenant_id,
        SupplierProduct.product_code == code,
    )
    if exclude_id is not None:
        q = q.where(SupplierProduct.id != exclude_id)
    if db.scalar(q.limit(1)) is not None:
        raise HTTPException(status_code=409, detail=f"编号「{code}」已存在，确认仍要保存？")


@router.post("")
def create_product(
    body: SupplierProductCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.supplier_products.write")),
):
    code = body.product_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写商品编号")
    _ensure_supplier(db, user.tenant_id, body.partner_id)
    _ensure_color(db, user.tenant_id, body.color_id)
    _ensure_category(db, user.tenant_id, body.category_id)
    _ensure_unit(db, user.tenant_id, body.pricing_unit_id)
    _require_duplicate_confirm(
        db,
        user.tenant_id,
        code,
        exclude_id=None,
        confirmed=body.confirm_duplicate,
    )
    p = SupplierProduct(
        tenant_id=user.tenant_id,
        product_code=code,
        name=(body.name or "").strip() or None,
        category_id=body.category_id,
        image_url=(body.image_url or "").strip() or None,
        internal_code=(body.internal_code or "").strip() or None,
        pricing_unit_id=body.pricing_unit_id,
        unit_price=body.unit_price,
        color_id=body.color_id,
        partner_id=body.partner_id,
        is_active=body.is_active,
        approval_status="approved" if _user_can_approve_catalog(db, user) else "pending",
        min_stock_qty=body.min_stock_qty,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(_product_out(p, *_load_related(db, p)))


@router.get("/import-template")
def download_import_template(
    user: Employee = Depends(require_permissions("btn.supplier_products.write")),
):
    _ = user
    content = build_supplier_product_import_template()
    filename = "物料色卡导入模版.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="supplier_products_import.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/import")
async def import_products(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.supplier_products.write")),
    file: UploadFile | None = File(None),
):
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
        result = import_supplier_products_xlsx(
            db,
            user.tenant_id,
            raw,
            can_approve=_user_can_approve_catalog(db, user),
        )
    except SupplierProductImportError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return ok(result)


@router.get("/by-code")
def get_product_by_code(
    code: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    product_code = code.strip()
    p = db.scalar(
        select(SupplierProduct)
        .where(
            SupplierProduct.tenant_id == user.tenant_id,
            SupplierProduct.product_code == product_code,
        )
        .limit(1)
    )
    if not p:
        raise HTTPException(status_code=404, detail="物料不存在")
    return ok(_product_out(p, *_load_related(db, p)))


@router.get("/{product_id}/qr.png")
def product_label_qr_png(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """物料身份标二维码。内容为打开该物料的固定链接。"""
    p = _get_product(db, user.tenant_id, product_id)
    url = material_label_scan_url(request_public_origin(request), p.product_code)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="material_{p.id}.png"'},
    )


@router.get("/{product_id}/price-histories")
def product_price_histories(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    _get_product(db, user.tenant_id, product_id)
    return ok(list_catalog_price_history(db, user.tenant_id, product_id))


@router.get("/{product_id}")
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    p = _get_product(db, user.tenant_id, product_id)
    return ok(_product_out(p, *_load_related(db, p)))


@router.patch("/{product_id}")
def update_product(
    product_id: int,
    body: SupplierProductUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(
        require_permissions("btn.supplier_products.write", "btn.supplier_products.approve")
    ),
):
    p = _get_product(db, user.tenant_id, product_id)
    if catalog_approved(p) and not _user_can_approve_catalog(db, user):
        raise HTTPException(status_code=400, detail="已审批通过，不能修改")
    data = body.model_dump(exclude_unset=True)
    confirmed = bool(data.pop("confirm_duplicate", False))
    if "product_code" in data:
        code = (data["product_code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="请填写商品编号")
        data["product_code"] = code
    if "partner_id" in data and data["partner_id"] is not None:
        _ensure_supplier(db, user.tenant_id, data["partner_id"])
    if "color_id" in data:
        _ensure_color(db, user.tenant_id, data["color_id"])
    if "category_id" in data:
        _ensure_category(db, user.tenant_id, data["category_id"])
    if "pricing_unit_id" in data:
        _ensure_unit(db, user.tenant_id, data["pricing_unit_id"])
    for key in ("image_url", "internal_code", "name"):
        if key in data and isinstance(data[key], str):
            data[key] = data[key].strip() or None
    code = data.get("product_code", p.product_code)
    _require_duplicate_confirm(
        db,
        user.tenant_id,
        code,
        exclude_id=p.id,
        confirmed=confirmed,
    )
    if "unit_price" in data:
        record_catalog_price_change(
            db,
            p,
            data.pop("unit_price"),
            source="catalog_edit",
            changed_by=user.id,
        )
    if "partner_id" in data and data["partner_id"] is not None:
        record_catalog_supplier_change(
            db,
            p,
            data.pop("partner_id"),
            source="catalog_edit",
            changed_by=user.id,
        )
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return ok(_product_out(p, *_load_related(db, p)))


@router.post("/{product_id}/approve")
def approve_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.supplier_products.approve")),
):
    p = _get_product(db, user.tenant_id, product_id)
    p.approval_status = "approved"
    db.commit()
    db.refresh(p)
    return ok(_product_out(p, *_load_related(db, p)))


def _material_in_use(db: Session, model, column, tenant_id: int, product_id: int) -> bool:
    stmt = select(model.id).where(model.tenant_id == tenant_id, column == product_id).limit(1)
    return db.scalar(stmt) is not None


def _material_delete_block_reason(db: Session, tenant_id: int, product_id: int) -> str | None:
    """物料被业务引用时给出可理解的原因。不依赖数据库外键。"""
    checks: list[tuple[type, object, str]] = [
        (OwnProductMaterial, OwnProductMaterial.supplier_product_id, "该物料已用在产品物料清单里，不能删除"),
        (OwnProductPart, OwnProductPart.source_supplier_product_id, "该物料已关联产品部件，不能删除"),
        (PurchaseOrderLine, PurchaseOrderLine.supplier_product_id, "该物料已有采购记录，不能删除"),
        (MaterialIqcRecord, MaterialIqcRecord.supplier_product_id, "该物料已有来料检验记录，不能删除"),
        (OrderMaterialRequirement, OrderMaterialRequirement.supplier_product_id, "该物料已有订单用料，不能删除"),
        (StockDocLine, StockDocLine.supplier_product_id, "该物料已有出入库记录，不能删除"),
        (SharedMaterialStock, SharedMaterialStock.supplier_product_id, "该物料在物料仓还有库存记录，不能删除"),
        (SharedMaterialLedger, SharedMaterialLedger.supplier_product_id, "该物料已有库存流水，不能删除"),
        (WorkshopMaterialCount, WorkshopMaterialCount.supplier_product_id, "该物料已有车间点数，不能删除"),
        (BatchMaterialConsumption, BatchMaterialConsumption.supplier_product_id, "该物料已有裁断耗用记录，不能删除"),
        (MiscMaterialPickupLine, MiscMaterialPickupLine.supplier_product_id, "该物料已有零星领料，不能删除"),
        (WarehousePickupLine, WarehousePickupLine.supplier_product_id, "该物料已有仓库领料，不能删除"),
        (PayableLine, PayableLine.supplier_product_id, "该物料已有应付明细，不能删除"),
        (MaterialUsageHistory, MaterialUsageHistory.supplier_product_id, "该物料已有用量变更记录，不能删除"),
    ]
    for model, column, message in checks:
        if _material_in_use(db, model, column, tenant_id, product_id):
            return message
    used_on_product = db.scalar(
        select(OwnProduct.id)
        .where(
            OwnProduct.tenant_id == tenant_id,
            or_(
                OwnProduct.shoe_last_product_id == product_id,
                OwnProduct.sole_mold_product_id == product_id,
                OwnProduct.heel_model_id == product_id,
                OwnProduct.heel_model_2_id == product_id,
            ),
        )
        .limit(1)
    )
    if used_on_product is not None:
        return "该物料已用作楦型、鞋底或鞋跟，不能删除"
    return None


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.supplier_products.write")),
):
    p = _get_product(db, user.tenant_id, product_id)
    if catalog_approved(p):
        raise HTTPException(status_code=400, detail="已审批通过，不能删除")
    reason = _material_delete_block_reason(db, user.tenant_id, product_id)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    db.delete(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="该物料已被业务使用，不能删除")
    return ok({"deleted": True, "id": product_id})
