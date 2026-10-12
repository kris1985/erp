"""日常开支：公司内部费用流水。"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.config import get_settings
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import expense_service, rbac_service

router = APIRouter(tags=["expenses"])

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _granted_codes(db: Session, user: Employee) -> set[str]:
    if rbac_service.employee_effective_base_role(db, user) == "admin":
        return {"menu.daily_expenses", "btn.daily_expenses.write", "mobile.expense"}
    return set(rbac_service.get_employee_permissions(db, user))


def _full_expense_access(db: Session, user: Employee) -> bool:
    codes = _granted_codes(db, user)
    return "menu.daily_expenses" in codes or "btn.daily_expenses.write" in codes


def _can_post_expense(db: Session, user: Employee) -> bool:
    return "btn.daily_expenses.write" in _granted_codes(db, user)


def _owns_expense(data: dict, user: Employee) -> bool:
    return data.get("employee_id") == user.id or data.get("created_by") == user.id


def _http_from_err(err: Exception) -> HTTPException:
    msg = str(err)
    code_map = {
        "not_found": (404, "记录不存在"),
        "amount_invalid": (400, "金额须大于 0"),
        "category_invalid": (400, "费用类型不能超过 100 字"),
        "category_required": (400, "请选择费用类型"),
        "department_required": (400, "请选择费用承担部门"),
        "department_not_found": (400, "费用承担部门不存在"),
        "employee_required": (400, "请选择报销人"),
        "employee_not_found": (400, "报销人不存在"),
        "status_invalid": (400, "状态无效"),
        "not_payable": (400, "只有待付款的报销可以付款"),
        "lines_required": (400, "请至少添加一条明细"),
        "occurred_on_required": (400, "请填写产生日期"),
    }
    status, detail = code_map.get(msg, (400, msg))
    return HTTPException(status_code=status, detail=detail)


class ExpenseLineIn(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    occurred_on: date
    amount: float
    description: str | None = None
    category_image_urls: list[str] = Field(default_factory=list)
    invoice_urls: list[str] = Field(default_factory=list)
    receipt_urls: list[str] = Field(default_factory=list)


class ExpenseIn(BaseModel):
    department_id: int
    employee_id: int
    reason: str | None = None
    lines: list[ExpenseLineIn] = Field(min_length=1)
    await_payment: bool = False


@router.get("/daily-expenses")
def api_list_expenses(
    date_from: date | None = None,
    date_to: date | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.daily_expenses", "mobile.expense")),
):
    try:
        data = expense_service.list_expenses(
            db,
            user.tenant_id,
            date_from=date_from,
            date_to=date_to,
            department_id=department_id,
            employee_id=employee_id,
            category=category,
            status=status,
            owner_id=None if _full_expense_access(db, user) else user.id,
        )
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.get("/daily-expenses/category-suggestions")
def api_category_suggestions(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.daily_expenses", "mobile.expense")),
):
    try:
        data = expense_service.list_category_suggestions(db, user.tenant_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.post("/daily-expenses/upload")
async def api_upload_attachment(
    file: UploadFile = File(...),
    user: Employee = Depends(require_permissions("btn.daily_expenses.write", "mobile.expense")),
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


@router.post("/daily-expenses")
def api_create_expense(
    body: ExpenseIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.daily_expenses.write", "mobile.expense")),
):
    await_payment = body.await_payment or not _can_post_expense(db, user)
    try:
        data = expense_service.create_expense(
            db,
            user.tenant_id,
            department_id=body.department_id,
            employee_id=body.employee_id,
            reason=body.reason,
            lines=[line.model_dump() for line in body.lines],
            created_by=user.id,
            await_payment=await_payment,
        )
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.get("/daily-expenses/{expense_id}")
def api_get_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.daily_expenses", "mobile.expense")),
):
    try:
        data = expense_service.get_expense(db, user.tenant_id, expense_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    if not _full_expense_access(db, user) and not _owns_expense(data, user):
        raise HTTPException(status_code=404, detail="记录不存在")
    return ok(data)


@router.post("/daily-expenses/{expense_id}/pay")
def api_pay_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.daily_expenses.write")),
):
    try:
        data = expense_service.pay_expense(db, user.tenant_id, expense_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.post("/daily-expenses/{expense_id}/void")
def api_void_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.daily_expenses.write", "mobile.expense")),
):
    if not _can_post_expense(db, user):
        try:
            current = expense_service.get_expense(db, user.tenant_id, expense_id)
        except ValueError as err:
            raise _http_from_err(err) from err
        if current.get("status") != "pending" or not _owns_expense(current, user):
            raise HTTPException(status_code=403, detail="只能作废自己的待付款报销")
    try:
        data = expense_service.void_expense(db, user.tenant_id, expense_id)
    except ValueError as err:
        raise _http_from_err(err) from err
    return ok(data)
