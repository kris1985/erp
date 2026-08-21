from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    get_current_employee,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.models import Department, Employee, Position, Tenant, TenantRole
from app.schemas.api import ChangePasswordRequest, LoginRequest, TenantSelectRequest
from app.schemas.common import ok
from app.services import rbac_service, team_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _find_login_employees(db: Session, identifier: str) -> list[Employee]:
    """跨租户按 用户名 或 手机号 匹配在职员工。"""
    key = (identifier or "").strip()
    if not key:
        return []
    return list(
        db.scalars(
            select(Employee).where(
                Employee.is_active.is_(True),
                or_(Employee.username == key, Employee.mobile == key),
            )
        ).all()
    )


def _valid_credential(employee: Employee, password: str) -> bool:
    if not employee.password_hash:
        return False
    try:
        return verify_password(password, employee.password_hash)
    except Exception:
        return False


def _login_payload(db: Session, employee: Employee, tenant: Tenant | None = None) -> dict:
    token = create_access_token(employee)
    if tenant is None:
        tenant = db.get(Tenant, employee.tenant_id)
    roles = rbac_service.list_employee_role_codes(db, employee)
    try:
        permissions = rbac_service.get_employee_permissions(db, employee)
    except Exception:
        permissions = []
    base_role = rbac_service.employee_effective_base_role(db, employee)
    role_names: list[str] = []
    for code in roles:
        row = db.scalar(
            select(TenantRole).where(TenantRole.tenant_id == employee.tenant_id, TenantRole.code == code)
        )
        role_names.append(row.name if row else code)
    from app.services import inventory_settings, reporting_settings, shop_floor_settings

    inventory = inventory_settings.get_inventory_by_tenant_id(db, employee.tenant_id)
    reporting = reporting_settings.get_reporting_by_tenant_id(db, employee.tenant_id)
    shop_floor = shop_floor_settings.get_shop_floor_by_tenant_id(db, employee.tenant_id)
    position_name = None
    if employee.position_id:
        pos = db.get(Position, employee.position_id)
        if pos and pos.tenant_id == employee.tenant_id:
            position_name = pos.name
    department_name = None
    process_segment_id = None
    process_segment_name = None
    process_segment_is_first = False
    if employee.department_id:
        dep = db.get(Department, employee.department_id)
        if dep and dep.tenant_id == employee.tenant_id:
            department_name = dep.name
            process_segment_id = dep.process_segment_id
            if dep.process_segment_id:
                from app.models import ProcessSegment

                seg = db.get(ProcessSegment, dep.process_segment_id)
                if seg and seg.tenant_id == employee.tenant_id:
                    process_segment_name = seg.name
                    first_id = db.scalar(
                        select(ProcessSegment.id)
                        .where(
                            ProcessSegment.tenant_id == employee.tenant_id,
                            ProcessSegment.is_active.is_(True),
                        )
                        .order_by(ProcessSegment.sort_order.asc(), ProcessSegment.id.asc())
                        .limit(1)
                    )
                    process_segment_is_first = first_id == seg.id
    return {
        "access_token": token,
        "token_type": "bearer",
        "id": employee.id,
        "display_name": employee.name,
        "name": employee.name,
        "username": employee.username,
        "mobile": employee.mobile,
        "role": "worker",
        "is_leader": team_service.is_leader(db, employee),
        "roles": roles,
        "role_names": role_names,
        "role_name": "、".join(role_names) if role_names else None,
        "base_role": base_role,
        "tenant_id": employee.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "department_id": employee.department_id,
        "department_name": department_name,
        "process_segment_id": process_segment_id,
        "process_segment_name": process_segment_name,
        "process_segment_is_first": process_segment_is_first,
        "position_id": employee.position_id,
        "position_name": position_name,
        "salary_model": employee.salary_model.value if hasattr(employee.salary_model, "value") else str(employee.salary_model),
        "actor": "employee",
        "must_change_password": bool(employee.must_change_password),
        "permissions": permissions,
        "inventory": inventory,
        "reporting": reporting,
        "shop_floor": shop_floor,
    }


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    candidates = _find_login_employees(db, body.identifier)
    matched = [e for e in candidates if _valid_credential(e, body.password)]
    if not matched:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if len(matched) == 1:
        return ok(_login_payload(db, matched[0]))
    # 多租户命中：返回候选工厂，由前端让用户选择
    tenants = []
    seen: set[int] = set()
    for e in matched:
        t = db.get(Tenant, e.tenant_id)
        if t and t.id not in seen:
            seen.add(t.id)
            tenants.append({"tenant_id": t.id, "tenant_name": t.name})
    return ok({"need_select": True, "tenants": tenants})


@router.post("/login/select")
def login_select(body: TenantSelectRequest, db: Session = Depends(get_db)):
    employee = db.scalar(
        select(Employee).where(
            Employee.tenant_id == body.tenant_id,
            Employee.is_active.is_(True),
            or_(Employee.username == (body.identifier or "").strip(), Employee.mobile == (body.identifier or "").strip()),
        )
    )
    if not employee or not _valid_credential(employee, body.password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return ok(_login_payload(db, employee))


@router.get("/me")
def me(employee: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    data = _login_payload(db, employee)
    return ok({k: v for k, v in data.items() if k not in ("access_token", "token_type")})


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    if not employee.password_hash or not verify_password(body.old_password, employee.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    settings = get_settings()
    if body.new_password == settings.worker_default_password:
        raise HTTPException(status_code=400, detail="新密码不能与默认密码相同")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    employee.password_hash = hash_password(body.new_password)
    employee.must_change_password = False
    db.commit()
    return ok({"message": "密码已修改", "must_change_password": False})


# ── 兼容别名（合并前遗留路径）：/auth/worker/* 等价于 /auth/* ──
@router.post("/worker/login", include_in_schema=False)
def worker_login_compat(body: LoginRequest, db: Session = Depends(get_db)):
    return login(body, db)


@router.get("/worker/me", include_in_schema=False)
def worker_me_compat(employee: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    return me(employee, db)


@router.post("/worker/change-password", include_in_schema=False)
def worker_change_password_compat(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    return change_password(body, db, employee)
