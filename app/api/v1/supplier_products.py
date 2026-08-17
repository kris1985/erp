"""供应商产品档案。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.config import get_settings
from app.db import get_db
from app.models import Color, MaterialCategory, Partner, PricingUnit, SupplierProduct, Employee
from app.schemas.api import SupplierProductCreate, SupplierProductOut, SupplierProductUpdate
from app.schemas.common import normalize_page, ok, page_payload

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
    return ok(page_payload(items, int(total), page, page_size))


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user: Employee = Depends(require_roles("admin", "manager")),
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


@router.post("")
def create_product(
    body: SupplierProductCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    code = body.product_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写商品编号")
    _ensure_supplier(db, user.tenant_id, body.partner_id)
    _ensure_color(db, user.tenant_id, body.color_id)
    _ensure_category(db, user.tenant_id, body.category_id)
    _ensure_unit(db, user.tenant_id, body.pricing_unit_id)
    exists = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == user.tenant_id,
            SupplierProduct.product_code == code,
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="商品编号已存在")
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
        min_stock_qty=body.min_stock_qty,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(_product_out(p, *_load_related(db, p)))


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
    user: Employee = Depends(require_roles("admin", "manager")),
):
    p = _get_product(db, user.tenant_id, product_id)
    data = body.model_dump(exclude_unset=True)
    if "product_code" in data:
        code = (data["product_code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="请填写商品编号")
        dup = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == user.tenant_id,
                SupplierProduct.product_code == code,
                SupplierProduct.id != product_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="商品编号已存在")
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
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return ok(_product_out(p, *_load_related(db, p)))


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    p = _get_product(db, user.tenant_id, product_id)
    db.delete(p)
    db.commit()
    return ok({"deleted": True, "id": product_id})
