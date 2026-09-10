"""售后服务：客户退货登记与按尺码重做。"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_roles
from app.config import get_settings
from app.db import get_db
from app.models import (
    AfterSalesReturn,
    AfterSalesReturnSize,
    Color,
    Employee,
    ExecutionHeader,
    OwnProduct,
    Partner,
    SalesOrder,
    SalesOrderLine,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
)
from app.schemas.common import normalize_page, ok, page_payload
from app.services import finance_service

router = APIRouter(prefix="/after-sales", tags=["after-sales"])

PROGRESSES = {"pending", "completed"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _normalize_progress(value: str | None) -> str:
    return "completed" if value == "completed" else "pending"


class ReturnSizeIn(BaseModel):
    size: str = Field(min_length=1, max_length=20)
    quantity: int = Field(ge=0)
    return_quantity: int = Field(default=0, ge=0)
    repair_quantity: int = Field(default=0, ge=0)
    remake_quantity: int = Field(default=0, ge=0)

    @field_validator("size")
    @classmethod
    def clean_size(cls, value: str) -> str:
        return value.strip()


class AfterSalesIn(BaseModel):
    return_date: date
    # 新建由系统生成；保留入参仅兼容编辑页面回传，服务端不会采纳修改。
    return_no: str | None = Field(default=None, max_length=50)
    customer_id: int
    source_sales_order_line_id: int
    customer_brand: str | None = Field(default=None, max_length=100)
    customer_model: str | None = Field(default=None, max_length=100)
    factory_model: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=50)
    return_photo_urls: list[str] = Field(default_factory=list, max_length=9)
    carton_count: int = Field(ge=1)
    quantity: int = Field(ge=1)
    return_quantity: int = Field(default=0, ge=0)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    return_reason: str | None = None
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0)
    actual_refund_amount: Decimal | None = Field(default=None, ge=0)
    repair_quantity: int = Field(default=0, ge=0)
    repair_unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    progress: Literal["pending", "completed"] = "pending"
    sizes: list[ReturnSizeIn] = Field(min_length=1)

    @field_validator("return_no")
    @classmethod
    def clean_no(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("return_photo_urls")
    @classmethod
    def clean_photo_urls(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_sizes(self):
        names = [row.size for row in self.sizes]
        if len(names) != len(set(names)):
            raise ValueError("同一码数只能填写一次")
        size_total = sum(row.quantity for row in self.sizes)
        if self.sizes and size_total != self.quantity:
            raise ValueError(f"各码数双数合计 {size_total}，应等于总数量 {self.quantity}")
        return_total = sum(row.return_quantity for row in self.sizes)
        repair_total = sum(row.repair_quantity for row in self.sizes)
        if return_total != self.return_quantity:
            raise ValueError("各码数退货数量合计与退货数量不一致")
        if repair_total != self.repair_quantity:
            raise ValueError("各码数修复数量合计与修复数量不一致")
        if any(row.return_quantity + row.repair_quantity + row.remake_quantity > row.quantity for row in self.sizes):
            raise ValueError("每个码数的处理数量不能超过该码总数")
        return self


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _kit_list_payload(raw: dict | None) -> dict | None:
    if not raw:
        return None
    return {
        "kit_ok": bool(raw.get("kit_ok")),
        "shortage_lines": raw.get("shortage_lines"),
        "empty_bom": bool(raw.get("empty_bom")),
        "first_kit_ok": bool(raw.get("first_kit_ok")),
        "material_status": raw.get("material_status"),
        "header_id": raw.get("header_id"),
        "header_no": raw.get("header_no"),
        "shop_order_id": raw.get("shop_order_id"),
    }


def _attach_kits(db: Session, tenant_id: int, items: list[dict]) -> list[dict]:
    """为已生成重做生产单的售后行挂上齐套摘要与生产单号。"""
    header_ids = [
        int(item["remake_execution_header_id"])
        for item in items
        if item.get("remake_execution_header_id")
    ]
    if not header_ids:
        for item in items:
            item["kit"] = None
            item["remake_header_no"] = None
        return items
    from app.services.material_service import header_kit_summaries

    kit_map = header_kit_summaries(db, tenant_id, header_ids)
    headers = {
        int(row.id): row
        for row in db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.id.in_(header_ids),
            )
        ).all()
    }
    for item in items:
        hid = item.get("remake_execution_header_id")
        header = headers.get(int(hid)) if hid else None
        item["remake_header_no"] = header.header_no if header else None
        item["kit"] = _kit_list_payload(kit_map.get(int(hid))) if hid else None
        if item["kit"] is not None and item["remake_header_no"]:
            item["kit"]["header_no"] = item["remake_header_no"]
    return items


def _out(row: AfterSalesReturn) -> dict:
    sizes = [
        {
            "id": item.id,
            "size": item.size,
            "quantity": int(item.quantity or 0),
            "return_quantity": int(item.return_quantity or 0),
            "repair_quantity": int(item.repair_quantity or 0),
            "remake_quantity": int(item.remake_quantity or 0),
        }
        for item in row.sizes
    ]
    return_quantity = sum(item["return_quantity"] for item in sizes)
    repair_quantity = sum(item["repair_quantity"] for item in sizes)
    remake_quantity = sum(item["remake_quantity"] for item in sizes)
    return {
        "id": row.id,
        "return_date": row.return_date.isoformat(),
        "return_no": row.return_no,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "source_sales_order_line_id": row.source_sales_order_line_id,
        "own_product_id": row.own_product_id,
        "customer_brand": row.customer_brand,
        "customer_model": row.customer_model,
        "factory_model": row.factory_model,
        "product_image_url": row.product_image_url,
        "return_photo_urls": list(row.return_photo_urls or []),
        "color": row.color,
        "carton_count": int(row.carton_count or 0),
        "quantity": int(row.quantity or 0),
        "return_quantity": return_quantity,
        "unit_price": float(row.unit_price or 0),
        "total_price": float(row.total_price or 0),
        "return_reason": row.return_reason,
        "refund_amount": float(row.refund_amount or 0),
        "actual_refund_amount": float(row.actual_refund_amount or 0),
        "repair_quantity": repair_quantity,
        "repair_unit_price": float(row.repair_unit_price or 0),
        "repair_amount": float(row.repair_amount or 0),
        "remake_quantity": remake_quantity,
        "remake_material_unit_cost": float(row.remake_material_unit_cost or 0),
        "remake_labor_unit_cost": float(row.remake_labor_unit_cost or 0),
        "remake_material_cost": float(row.remake_material_cost or 0),
        "remake_labor_cost": float(row.remake_labor_cost or 0),
        "remake_amount": float(row.remake_amount or 0),
        "loss_amount": float(row.loss_amount or 0),
        "remake_execution_header_id": row.remake_execution_header_id,
        "remake_header_no": None,
        "posted_receivable_refund": float(row.posted_receivable_refund or 0),
        "receivable_id": row.receivable_id,
        "progress": _normalize_progress(row.progress),
        "sizes": sizes,
        "kit": None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get(db: Session, tenant_id: int, return_id: int) -> AfterSalesReturn:
    row = db.scalar(
        select(AfterSalesReturn)
        .where(AfterSalesReturn.id == return_id, AfterSalesReturn.tenant_id == tenant_id)
        .options(selectinload(AfterSalesReturn.sizes))
    )
    if not row:
        raise HTTPException(status_code=404, detail="售后退货单不存在")
    return row


def _generate_return_no(db: Session, tenant_id: int, return_date: date) -> str:
    """生成 TH + 退货日期 + 三位流水，如 TH260910001。"""
    prefix = f"TH{return_date.strftime('%y%m%d')}"
    existing = db.scalars(
        select(AfterSalesReturn.return_no).where(
            AfterSalesReturn.tenant_id == tenant_id,
            AfterSalesReturn.return_no.like(f"{prefix}%"),
        )
    ).all()
    sequences = [
        int(value[len(prefix) :])
        for value in existing
        if value[len(prefix) :].isdigit()
    ]
    return f"{prefix}{(max(sequences, default=0) + 1):03d}"


def _size_pattern(db: Session, line: SalesOrderLine) -> list[tuple[str, int]]:
    """从销售行绝对数量还原每箱配码。"""
    boxes = max(1, int(line.carton_qty or 1))
    size_ids = {item.size_id for item in line.items if int(item.qty or 0) > 0}
    size_map = {
        row.id: row.size_value
        for row in db.scalars(select(Size).where(Size.id.in_(size_ids))).all()
    } if size_ids else {}
    pattern: list[tuple[str, int]] = []
    for item in line.items:
        qty = int(item.qty or 0)
        if qty <= 0:
            continue
        if qty % boxes:
            raise HTTPException(
                status_code=400,
                detail=f"销售订单码数 {size_map.get(item.size_id, item.size_id)} 数量不能按 {boxes} 箱整除",
            )
        per_carton = qty // boxes
        if per_carton > 0:
            pattern.append((size_map.get(item.size_id) or str(item.size_id), per_carton))
    if not pattern:
        raise HTTPException(status_code=400, detail="所选工厂型号没有有效配码")
    return pattern


def _apply(db: Session, row: AfterSalesReturn, body: AfterSalesIn, tenant_id: int) -> None:
    customer = db.scalar(
        select(Partner).where(
            Partner.id == body.customer_id,
            Partner.tenant_id == tenant_id,
            Partner.is_customer.is_(True),
        )
    )
    if not customer:
        raise HTTPException(status_code=400, detail="请选择有效客户")
    source = db.execute(
        select(SalesOrderLine, OwnProduct, Color)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .join(OwnProduct, OwnProduct.id == SalesOrderLine.own_product_id)
        .outerjoin(Color, Color.id == SalesOrderLine.color_id)
        .where(
            SalesOrderLine.id == body.source_sales_order_line_id,
            SalesOrderLine.tenant_id == tenant_id,
            SalesOrder.customer_id == customer.id,
        )
    ).first()
    if not source:
        raise HTTPException(status_code=400, detail="所选工厂型号不属于该客户")
    source_line, product, source_color = source
    for key in ("return_reason",):
        setattr(row, key, _clean(getattr(body, key)))
    row.return_date = body.return_date
    row.customer_id = customer.id
    row.customer_name = customer.name
    row.source_sales_order_line_id = source_line.id
    row.own_product_id = product.id
    row.customer_brand = _clean(source_line.brand_name)
    row.customer_model = _clean(source_line.customer_sku)
    row.factory_model = product.product_code
    row.product_image_url = product.image_url
    row.return_photo_urls = body.return_photo_urls
    row.color = source_color.name if source_color else None
    row.carton_count = body.carton_count
    pattern = _size_pattern(db, source_line)
    allowed_sizes = {size for size, _per_carton in pattern}
    submitted = {item.size: item.quantity for item in body.sizes}
    if set(submitted) != allowed_sizes:
        raise HTTPException(status_code=400, detail="码数须来自所选型号的订单配码")
    if body.quantity != sum(submitted.values()):
        raise HTTPException(status_code=400, detail="总数量与各码数数量合计不一致")
    if any(quantity % body.carton_count for quantity in submitted.values()):
        raise HTTPException(status_code=400, detail="各码数数量须为每箱配码乘以箱数")
    source_price = Decimal(str(source_line.unit_price or 0)).quantize(Decimal("0.01"))
    row.quantity = sum(submitted.values())
    return_map = {item.size: item.return_quantity for item in body.sizes}
    repair_map = {item.size: item.repair_quantity for item in body.sizes}
    remake_map = {item.size: item.remake_quantity for item in body.sizes}
    row.return_quantity = sum(return_map.values())
    row.unit_price = source_price
    row.total_price = (source_price * row.quantity).quantize(Decimal("0.01"))
    row.refund_amount = (source_price * row.return_quantity).quantize(Decimal("0.01"))
    if body.actual_refund_amount is None:
        row.actual_refund_amount = row.refund_amount
    else:
        row.actual_refund_amount = body.actual_refund_amount.quantize(Decimal("0.01"))
    row.repair_quantity = sum(repair_map.values())
    row.repair_unit_price = body.repair_unit_price.quantize(Decimal("0.01"))
    row.repair_amount = (row.repair_unit_price * row.repair_quantity).quantize(Decimal("0.01"))
    row.remake_quantity = sum(remake_map.values())
    row.remake_material_unit_cost = Decimal(str(product.material_cost or 0)).quantize(Decimal("0.0001"))
    row.remake_labor_unit_cost = Decimal(str(product.labor_cost or 0)).quantize(Decimal("0.0001"))
    row.remake_material_cost = (row.remake_material_unit_cost * row.remake_quantity).quantize(Decimal("0.01"))
    row.remake_labor_cost = (row.remake_labor_unit_cost * row.remake_quantity).quantize(Decimal("0.01"))
    row.remake_amount = (row.remake_material_cost + row.remake_labor_cost).quantize(Decimal("0.01"))
    row.loss_amount = (row.actual_refund_amount + row.repair_amount + row.remake_amount).quantize(Decimal("0.01"))
    # 进度仅由「已完成」接口修改；保存时保持原状态（新建默认待处理）。
    if not row.id:
        row.progress = "pending"
    # 先落地删除旧明细，避免同一码数替换时唯一键在 INSERT/DELETE 排序间冲突。
    if row.id and row.sizes:
        row.sizes.clear()
        db.flush()
    row.sizes = [
        AfterSalesReturnSize(
            tenant_id=tenant_id,
            size=size,
            quantity=quantity,
            return_quantity=return_map.get(size, 0),
            repair_quantity=repair_map.get(size, 0),
            remake_quantity=remake_map.get(size, 0),
            sort_order=index,
        )
        for index, (size, quantity) in enumerate(submitted.items())
    ]


@router.get("/options")
def list_options(
    customer_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """返回该客户销售订单中出现过的工厂型号及客户侧品牌/型号快照。"""
    customer = db.scalar(
        select(Partner).where(
            Partner.id == customer_id,
            Partner.tenant_id == user.tenant_id,
            Partner.is_customer.is_(True),
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    records = db.execute(
        select(SalesOrderLine, OwnProduct, Color)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .join(OwnProduct, OwnProduct.id == SalesOrderLine.own_product_id)
        .outerjoin(Color, Color.id == SalesOrderLine.color_id)
        .where(
            SalesOrderLine.tenant_id == user.tenant_id,
            SalesOrder.customer_id == customer_id,
        )
        .order_by(SalesOrder.id.desc(), SalesOrderLine.id.desc())
    ).all()
    all_size_ids = {
        item.size_id
        for line, _product, _color in records
        for item in line.items
        if int(item.qty or 0) > 0
    }
    size_map = {
        row.id: row.size_value
        for row in db.scalars(select(Size).where(Size.id.in_(all_size_ids))).all()
    } if all_size_ids else {}
    items = []
    seen: set[tuple[int, str, str, str]] = set()
    for line, product, color in records:
        key = (
            product.id,
            line.brand_name or "",
            line.customer_sku or "",
            color.name if color else "",
        )
        if key in seen:
            continue
        boxes = max(1, int(line.carton_qty or 1))
        sizes = []
        for detail in line.items:
            qty = int(detail.qty or 0)
            if qty <= 0 or qty % boxes:
                continue
            sizes.append(
                {
                    "size": size_map.get(detail.size_id) or str(detail.size_id),
                    "quantity_per_carton": qty // boxes,
                }
            )
        if not sizes:
            continue
        seen.add(key)
        items.append(
            {
                "source_sales_order_line_id": line.id,
                "own_product_id": product.id,
                "factory_model": product.product_code,
                "customer_brand": line.brand_name,
                "customer_model": line.customer_sku,
                "color": color.name if color else None,
                "image_url": product.image_url,
                "unit_price": float(line.unit_price or 0),
                "material_cost": float(product.material_cost or 0),
                "labor_cost": float(product.labor_cost or 0),
                "order_carton_count": boxes,
                "sizes": sizes,
            }
        )
    return ok({"customer_id": customer.id, "customer_name": customer.name, "items": items})


@router.get("")
def list_returns(
    keyword: str | None = Query(default=None),
    progress: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    page, page_size, offset = normalize_page(page, page_size)
    q = select(AfterSalesReturn).where(AfterSalesReturn.tenant_id == user.tenant_id)
    if keyword and keyword.strip():
        value = f"%{keyword.strip()}%"
        q = q.where(
            or_(
                AfterSalesReturn.return_no.like(value),
                AfterSalesReturn.customer_name.like(value),
                AfterSalesReturn.customer_brand.like(value),
                AfterSalesReturn.customer_model.like(value),
                AfterSalesReturn.factory_model.like(value),
            )
        )
    if progress:
        progress = _normalize_progress(progress)
        if progress not in PROGRESSES:
            raise HTTPException(status_code=400, detail="处理进度无效")
        if progress == "pending":
            q = q.where(
                or_(
                    AfterSalesReturn.progress == "pending",
                    AfterSalesReturn.progress == "processing",
                    AfterSalesReturn.progress == "cancelled",
                    AfterSalesReturn.progress.is_(None),
                )
            )
        else:
            q = q.where(AfterSalesReturn.progress == "completed")
    if date_from:
        q = q.where(AfterSalesReturn.return_date >= date_from)
    if date_to:
        q = q.where(AfterSalesReturn.return_date <= date_to)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.scalars(q.options(selectinload(AfterSalesReturn.sizes)).order_by(AfterSalesReturn.return_date.desc(), AfterSalesReturn.id.desc()).offset(offset).limit(page_size)).all()
    items = _attach_kits(db, user.tenant_id, [_out(row) for row in rows])
    return ok(page_payload(items, int(total), page, page_size))


def _sync_refund_or_raise(db: Session, tenant_id: int, row: AfterSalesReturn) -> None:
    try:
        finance_service.sync_after_sales_receivable_refund(db, tenant_id, row)
    except finance_service.FinanceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("")
def create_return(body: AfterSalesIn, db: Session = Depends(get_db), user: Employee = Depends(require_roles("admin", "manager"))):
    row = AfterSalesReturn(
        tenant_id=user.tenant_id,
        return_no=_generate_return_no(db, user.tenant_id, body.return_date),
        created_by=user.id,
    )
    _apply(db, row, body, user.tenant_id)
    db.add(row)
    db.flush()
    _sync_refund_or_raise(db, user.tenant_id, row)
    db.commit()
    return ok(_out(_get(db, user.tenant_id, row.id)))


@router.put("/{return_id}")
def update_return(return_id: int, body: AfterSalesIn, db: Session = Depends(get_db), user: Employee = Depends(require_roles("admin", "manager"))):
    row = _get(db, user.tenant_id, return_id)
    if row.remake_execution_header_id:
        old_remake = {item.size: int(item.remake_quantity or 0) for item in row.sizes}
        new_remake = {item.size: int(item.remake_quantity or 0) for item in body.sizes}
        if old_remake != new_remake:
            raise HTTPException(status_code=400, detail="已生成重做生产单，不能修改重做码数或数量")
    _apply(db, row, body, user.tenant_id)
    _sync_refund_or_raise(db, user.tenant_id, row)
    db.commit()
    return ok(_out(_get(db, user.tenant_id, return_id)))


@router.post("/{return_id}/remake-production")
def create_remake_production(
    return_id: int,
    body: AfterSalesIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """保存重做码数，并生成一张独立的售后重做生产单。"""
    row = _get(db, user.tenant_id, return_id)
    if row.remake_execution_header_id:
        existing = db.get(ExecutionHeader, int(row.remake_execution_header_id))
        if existing:
            payload = _attach_kits(db, user.tenant_id, [_out(row)])[0]
            return ok({"return": payload, "production_order": {"id": existing.id, "header_no": existing.header_no, "existing": True}})

    _apply(db, row, body, user.tenant_id)
    _sync_refund_or_raise(db, user.tenant_id, row)
    remake_rows = [item for item in body.sizes if int(item.remake_quantity or 0) > 0]
    if not remake_rows:
        raise HTTPException(status_code=400, detail="请选择重做码数并填写数量")

    source_line = db.scalar(
        select(SalesOrderLine)
        .where(
            SalesOrderLine.id == row.source_sales_order_line_id,
            SalesOrderLine.tenant_id == user.tenant_id,
        )
        .options(selectinload(SalesOrderLine.items))
    )
    if not source_line:
        raise HTTPException(status_code=400, detail="来源销售订单明细不存在")
    source_size_ids = {item.size_id for item in source_line.items}
    size_by_id = {
        item.id: item
        for item in db.scalars(select(Size).where(Size.id.in_(source_size_ids))).all()
    } if source_size_ids else {}
    source_by_size = {
        size_by_id[item.size_id].size_value: item
        for item in source_line.items
        if item.size_id in size_by_id
    }

    from app.services.execution_service import generate_header_no, size_execution_no
    from app.services.material_service import (
        MaterialError,
        ensure_header_processes,
        ensure_material_snapshot_for_header,
    )

    header_no = generate_header_no(db, user.tenant_id)
    remake_total = sum(int(item.remake_quantity) for item in remake_rows)
    notes = f"售后重做：关联退货单 {row.return_no}"
    header = ExecutionHeader(
        tenant_id=user.tenant_id,
        header_no=header_no,
        own_product_id=int(row.own_product_id),
        color_id=source_line.color_id,
        sales_order_id=source_line.sales_order_id,
        sales_order_line_id=source_line.id,
        total_qty=remake_total,
        completed_qty=0,
        status=SpecExecutionStatus.confirmed,
        delivery_date=source_line.delivery_date,
        shop_order_id=None,
        notes=notes,
        created_by=user.id,
    )
    db.add(header)
    db.flush()
    for remake in remake_rows:
        source_item = source_by_size.get(remake.size)
        if not source_item:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"{remake.size} 码不在来源订单中")
        db.add(
            SpecExecutionOrder(
                tenant_id=user.tenant_id,
                execution_no=size_execution_no(header_no, remake.size, source_item.size_id),
                header_id=header.id,
                own_product_id=int(row.own_product_id),
                color_id=source_item.color_id if source_item.color_id is not None else source_line.color_id,
                size_id=source_item.size_id,
                total_qty=int(remake.remake_quantity),
                completed_qty=0,
                status=SpecExecutionStatus.confirmed,
                delivery_date=source_line.delivery_date,
                shop_order_id=None,
                notes=notes,
                created_by=user.id,
            )
        )
    db.flush()
    try:
        ensure_header_processes(db, tenant_id=user.tenant_id, header=header, delivery_date=source_line.delivery_date)
        ensure_material_snapshot_for_header(db, user.tenant_id, header)
    except MaterialError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=exc.message) from exc
    row.remake_execution_header_id = header.id
    db.commit()
    payload = _attach_kits(db, user.tenant_id, [_out(_get(db, user.tenant_id, row.id))])[0]
    return ok({"return": payload, "production_order": {"id": header.id, "header_no": header.header_no, "existing": False}})


@router.post("/{return_id}/complete")
def complete_return(
    return_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """将售后单标记为已完成；退款+返修+重做数量须等于总数量。"""
    row = _get(db, user.tenant_id, return_id)
    if _normalize_progress(row.progress) == "completed":
        return ok(_out(row))
    return_qty = sum(int(item.return_quantity or 0) for item in row.sizes)
    repair_qty = sum(int(item.repair_quantity or 0) for item in row.sizes)
    remake_qty = sum(int(item.remake_quantity or 0) for item in row.sizes)
    total_qty = int(row.quantity or 0)
    handled = return_qty + repair_qty + remake_qty
    if handled != total_qty:
        raise HTTPException(
            status_code=400,
            detail=f"退款+返修+重做须等于总数量（当前 {handled}/{total_qty}）",
        )
    row.progress = "completed"
    db.commit()
    return ok(_out(_get(db, user.tenant_id, return_id)))


@router.delete("/{return_id}")
def delete_return(return_id: int, db: Session = Depends(get_db), user: Employee = Depends(require_roles("admin", "manager"))):
    row = _get(db, user.tenant_id, return_id)
    # 删除前冲回已写入应收的退款调账。
    row.actual_refund_amount = Decimal("0")
    _sync_refund_or_raise(db, user.tenant_id, row)
    db.delete(row)
    db.commit()
    return ok({"id": return_id})


@router.post("/upload")
async def upload_return_photo(
    file: UploadFile = File(...),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    _ = user
    ext = Path(file.filename or "image.jpg").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="仅支持 jpg/png/gif/webp 图片")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="单张图片不能超过 5MB")
    uploads = Path(get_settings().uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (uploads / name).write_bytes(raw)
    return ok({"url": f"/uploads/{name}", "filename": name})
