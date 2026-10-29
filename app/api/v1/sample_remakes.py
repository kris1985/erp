"""复版明细：样品寄送登记。"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.config import get_settings
from app.db import get_db
from app.models import Employee
from app.schemas.common import normalize_page, ok
from app.services import sample_remake_service

router = APIRouter(prefix="/sample-remakes", tags=["sample-remakes"])

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _http_from_err(err: Exception) -> HTTPException:
    msg = str(err)
    code_map = {
        "not_found": (404, "记录不存在"),
        "customer_not_found": (400, "请选择有效客户"),
        "lines_required": (400, "请至少添加一条样品明细"),
        "factory_model_required": (400, "请填写工厂型号"),
        "qty_invalid": (400, "数量须大于 0"),
        "unit_price_invalid": (400, "样品单价无效"),
        "product_not_found": (400, "工厂型号不存在"),
        "delivery_no_taken": (400, "送货单号已存在"),
        "delivery_no_too_long": (400, "送货单号不能超过 40 字"),
        "image_too_long": (400, "图片地址过长"),
        "already_statemented": (400, "已进对账单，作废对账单后才能修改"),
    }
    status, detail = code_map.get(msg, (400, msg))
    return HTTPException(status_code=status, detail=detail)


class SampleRemakeLineIn(BaseModel):
    brand: str | None = None
    own_product_id: int | None = None
    factory_model: str = Field(min_length=1, max_length=80)
    image_url: str | None = None
    color: str | None = None
    qty: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class SampleRemakeIn(BaseModel):
    remake_date: date
    delivery_no: str | None = None
    courier_company: str | None = None
    tracking_no: str | None = None
    customer_id: int
    lines: list[SampleRemakeLineIn] = Field(min_length=1)


@router.get("")
def api_list_remakes(
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.sample_remakes")),
):
    page, page_size, _offset = normalize_page(page, page_size)
    try:
        data = sample_remake_service.list_remakes(
            db,
            user.tenant_id,
            date_from=date_from,
            date_to=date_to,
            customer_id=customer_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.post("/upload")
async def api_upload_image(
    file: UploadFile = File(...),
    user: Employee = Depends(require_permissions("btn.sample_remakes.write")),
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


@router.post("")
def api_create_remake(
    body: SampleRemakeIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.sample_remakes.write")),
):
    try:
        data = sample_remake_service.create_remake(
            db,
            user.tenant_id,
            remake_date=body.remake_date,
            delivery_no=body.delivery_no,
            courier_company=body.courier_company,
            tracking_no=body.tracking_no,
            customer_id=body.customer_id,
            lines=[line.model_dump() for line in body.lines],
            created_by=user.id,
        )
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.get("/{remake_id}")
def api_get_remake(
    remake_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.sample_remakes")),
):
    try:
        data = sample_remake_service.get_remake(db, user.tenant_id, remake_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.put("/{remake_id}")
def api_update_remake(
    remake_id: int,
    body: SampleRemakeIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.sample_remakes.write")),
):
    try:
        data = sample_remake_service.update_remake(
            db,
            user.tenant_id,
            remake_id,
            remake_date=body.remake_date,
            delivery_no=body.delivery_no,
            courier_company=body.courier_company,
            tracking_no=body.tracking_no,
            customer_id=body.customer_id,
            lines=[line.model_dump() for line in body.lines],
        )
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.delete("/{remake_id}")
def api_delete_remake(
    remake_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.sample_remakes.write")),
):
    try:
        data = sample_remake_service.delete_remake(db, user.tenant_id, remake_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)
