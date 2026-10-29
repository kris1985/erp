"""平台运营：运营账号与租户开通。"""

from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import get_settings
from app.models import (
    Employee,
    EmployeeRoleAssignment,
    Operator,
    RolePermission,
    SalaryModel,
    SalesOrder,
    Tenant,
    TenantRole,
)
from app.services import rbac_service

_MOBILE_RE = re.compile(r"^1\d{10}$")


class OperatorError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def ensure_default_operator(db: Session) -> None:
    """库里还没有运营账号时，用配置里的默认账号灌一条。已有账号不改密码。"""
    exists = db.scalar(select(Operator.id).limit(1))
    if exists:
        return
    settings = get_settings()
    db.add(
        Operator(
            username=settings.operator_username.strip() or "ops",
            name="运营",
            password_hash=hash_password(settings.operator_password),
            is_active=True,
        )
    )
    db.commit()


def _clean_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        raise OperatorError("name_required", "请填写租户名称")
    if len(text) > 100:
        raise OperatorError("name_too_long", "租户名称不能超过 100 字")
    return text


def _clean_mobile(mobile: str) -> str:
    text = re.sub(r"\s+", "", (mobile or "").strip())
    if not _MOBILE_RE.match(text):
        raise OperatorError("invalid_mobile", "管理员手机号须为 11 位手机号")
    return text


def _clean_admin_name(name: str | None) -> str:
    text = (name or "").strip() or "管理员"
    if len(text) > 50:
        raise OperatorError("admin_name_too_long", "管理员姓名不能超过 50 字")
    return text


def _clean_password(password: str) -> str:
    text = password or ""
    if len(text) < 6:
        raise OperatorError("weak_password", "初始密码至少 6 位")
    if len(text) > 64:
        raise OperatorError("weak_password", "初始密码不能超过 64 位")
    return text


def _parse_expires_on(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise OperatorError("invalid_expires", "截止日期格式应为 YYYY-MM-DD") from exc


def tenant_status(tenant: Tenant, today: date | None = None) -> str:
    if not tenant.is_active:
        return "disabled"
    today = today or date.today()
    if tenant.expires_on is not None and tenant.expires_on < today:
        return "expired"
    return "active"


def _admin_employee(db: Session, tenant_id: int) -> Employee | None:
    row = db.scalar(
        select(Employee)
        .join(EmployeeRoleAssignment, EmployeeRoleAssignment.employee_id == Employee.id)
        .where(
            Employee.tenant_id == tenant_id,
            EmployeeRoleAssignment.role_code == "admin",
        )
        .order_by(Employee.id)
    )
    if row:
        return row
    return db.scalar(
        select(Employee)
        .where(Employee.tenant_id == tenant_id, Employee.username == "admin")
        .order_by(Employee.id)
    )


def _mobile_taken(
    db: Session,
    mobile: str,
    *,
    tenant_id: int,
    exclude_employee_id: int | None = None,
) -> bool:
    """仅在本厂内查重。同一手机号可在多厂各有账号，登录时按租户选择。"""
    q = select(Employee.id).where(
        Employee.tenant_id == tenant_id,
        Employee.is_active.is_(True),
        or_(Employee.mobile == mobile, Employee.username == mobile),
    )
    if exclude_employee_id:
        q = q.where(Employee.id != exclude_employee_id)
    return db.scalar(q.limit(1)) is not None


def _employee_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Employee.tenant_id, func.count())
        .where(Employee.is_active.is_(True))
        .group_by(Employee.tenant_id)
    ).all()
    return {int(tenant_id): int(count) for tenant_id, count in rows}


def serialize_tenant(db: Session, tenant: Tenant, *, employee_count: int | None = None) -> dict:
    admin = _admin_employee(db, tenant.id)
    if employee_count is None:
        employee_count = int(
            db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(Employee.tenant_id == tenant.id, Employee.is_active.is_(True))
            )
            or 0
        )
    created = tenant.created_at
    return {
        "id": tenant.id,
        "name": tenant.name,
        "admin_name": admin.name if admin else (tenant.contact_person or ""),
        "admin_mobile": (admin.mobile if admin and admin.mobile else tenant.contact_mobile) or "",
        "expires_on": tenant.expires_on.isoformat() if tenant.expires_on else None,
        "is_active": bool(tenant.is_active),
        "notes": tenant.notes or "",
        "status": tenant_status(tenant),
        "employee_count": employee_count,
        "created_at": created.isoformat(sep=" ", timespec="minutes") if created else None,
    }


def list_tenants(db: Session, *, keyword: str | None = None) -> list[dict]:
    rows = list(db.scalars(select(Tenant).order_by(Tenant.id.desc())).all())
    key = (keyword or "").strip()
    counts = _employee_counts(db)
    out = [serialize_tenant(db, row, employee_count=counts.get(row.id, 0)) for row in rows]
    if not key:
        return out
    return [
        item
        for item in out
        if key in item["name"] or key in item["admin_mobile"] or key in (item["admin_name"] or "")
    ]


def _ensure_admin(
    db: Session,
    tenant: Tenant,
    *,
    admin_name: str,
    admin_mobile: str,
    password: str | None,
) -> Employee:
    admin = _admin_employee(db, tenant.id)
    if _mobile_taken(
        db,
        admin_mobile,
        tenant_id=tenant.id,
        exclude_employee_id=admin.id if admin else None,
    ):
        raise OperatorError("mobile_taken", "该手机号在本厂已被其他账号使用")
    if admin is None:
        if not password:
            raise OperatorError("password_required", "请设置管理员初始密码")
        admin = Employee(
            tenant_id=tenant.id,
            name=admin_name,
            username=admin_mobile,
            mobile=admin_mobile,
            password_hash=hash_password(password),
            must_change_password=True,
            salary_model=SalaryModel.fixed,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        rbac_service.set_employee_roles(db, admin, ["admin"])
    else:
        old_mobile = (admin.mobile or "").strip()
        admin.name = admin_name
        admin.mobile = admin_mobile
        admin.is_active = True
        if admin.username == old_mobile or not admin.username:
            admin.username = admin_mobile
        if password:
            admin.password_hash = hash_password(password)
            admin.must_change_password = True
        codes = rbac_service.list_employee_role_codes(db, admin)
        if "admin" not in codes:
            rbac_service.set_employee_roles(db, admin, ["admin", *codes])
    tenant.contact_person = admin_name
    tenant.contact_mobile = admin_mobile
    return admin


def create_tenant(
    db: Session,
    *,
    name: str,
    admin_mobile: str,
    admin_name: str | None = None,
    password: str,
    expires_on: date | str | None = None,
    notes: str | None = None,
    is_active: bool = True,
) -> dict:
    name = _clean_name(name)
    admin_mobile = _clean_mobile(admin_mobile)
    admin_name = _clean_admin_name(admin_name)
    password = _clean_password(password)
    if db.scalar(select(Tenant.id).where(Tenant.name == name).limit(1)):
        raise OperatorError("duplicate_name", "已有同名租户")
    tenant = Tenant(
        name=name,
        contact_person=admin_name,
        contact_mobile=admin_mobile,
        expires_on=_parse_expires_on(expires_on),
        notes=(notes or "").strip() or None,
        is_active=bool(is_active),
    )
    db.add(tenant)
    db.flush()
    rbac_service.ensure_system_roles(db, tenant.id)
    _ensure_admin(
        db,
        tenant,
        admin_name=admin_name,
        admin_mobile=admin_mobile,
        password=password,
    )
    db.commit()
    db.refresh(tenant)
    return serialize_tenant(db, tenant)


def update_tenant(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    admin_mobile: str,
    admin_name: str | None = None,
    expires_on: date | str | None = None,
    notes: str | None = None,
    is_active: bool = True,
    password: str | None = None,
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise OperatorError("not_found", "租户不存在")
    name = _clean_name(name)
    admin_mobile = _clean_mobile(admin_mobile)
    admin_name = _clean_admin_name(admin_name)
    if password:
        password = _clean_password(password)
    dup = db.scalar(
        select(Tenant.id).where(Tenant.name == name, Tenant.id != tenant.id).limit(1)
    )
    if dup:
        raise OperatorError("duplicate_name", "已有同名租户")
    tenant.name = name
    tenant.expires_on = _parse_expires_on(expires_on)
    tenant.notes = (notes or "").strip() or None
    tenant.is_active = bool(is_active)
    db.flush()
    rbac_service.ensure_system_roles(db, tenant.id)
    _ensure_admin(
        db,
        tenant,
        admin_name=admin_name,
        admin_mobile=admin_mobile,
        password=password,
    )
    db.commit()
    db.refresh(tenant)
    return serialize_tenant(db, tenant)


def reset_tenant_admin_password(db: Session, tenant_id: int, password: str) -> None:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise OperatorError("not_found", "租户不存在")
    admin = _admin_employee(db, tenant.id)
    if not admin:
        raise OperatorError("admin_missing", "该租户还没有管理员账号")
    admin.password_hash = hash_password(_clean_password(password))
    admin.must_change_password = True
    admin.is_active = True
    db.commit()


def delete_tenant(db: Session, tenant_id: int) -> None:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise OperatorError("not_found", "租户不存在")
    admin = _admin_employee(db, tenant.id)
    others = db.scalar(
        select(func.count())
        .select_from(Employee)
        .where(
            Employee.tenant_id == tenant.id,
            Employee.id != (admin.id if admin else 0),
        )
    )
    if int(others or 0) > 0:
        raise OperatorError("tenant_in_use", "租户已有其他人员，不能删除，请改为停用")
    if db.scalar(select(SalesOrder.id).where(SalesOrder.tenant_id == tenant.id).limit(1)):
        raise OperatorError("tenant_in_use", "租户已有业务数据，不能删除，请改为停用")
    try:
        if admin:
            db.execute(
                EmployeeRoleAssignment.__table__.delete().where(
                    EmployeeRoleAssignment.employee_id == admin.id
                )
            )
            db.delete(admin)
            db.flush()
        db.execute(RolePermission.__table__.delete().where(RolePermission.tenant_id == tenant.id))
        db.execute(TenantRole.__table__.delete().where(TenantRole.tenant_id == tenant.id))
        db.delete(tenant)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise OperatorError("tenant_in_use", "租户已有业务数据，不能删除，请改为停用") from exc
