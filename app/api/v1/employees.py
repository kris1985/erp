from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_employee, hash_password
from app.config import get_settings
from app.db import get_db
from app.models import Department, Employee, Position, SalaryModel
from app.schemas.api import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.schemas.common import normalize_page, ok, page_payload
from app.services import rbac_service, team_service
from app.services.rbac_service import RbacError

router = APIRouter(prefix="/employees", tags=["employees"])


def _resolve_position(
    db: Session,
    tenant_id: int,
    position_id: int | None,
    *,
    allow_inactive_id: int | None = None,
) -> Position | None:
    if position_id is None:
        return None
    pos = db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="工种不存在")
    if not pos.is_active and position_id != allow_inactive_id:
        raise HTTPException(status_code=400, detail="工种未启用")
    return pos


def _resolve_department(
    db: Session, tenant_id: int, department_id: int | None
) -> Department | None:
    if department_id is None:
        return None
    dep = db.get(Department, department_id)
    if not dep or dep.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="部门不存在")
    return dep


def _employee_out(db: Session, e: Employee) -> dict:
    position_name = None
    if e.position_id:
        pos = db.get(Position, e.position_id)
        if pos and pos.tenant_id == e.tenant_id:
            position_name = pos.name
    department_name = None
    if e.department_id:
        dep = db.get(Department, e.department_id)
        if dep and dep.tenant_id == e.tenant_id:
            department_name = dep.name
    roles = rbac_service.list_employee_role_codes(db, e)
    role_names: list[str] = []
    for code in roles:
        row = rbac_service.get_tenant_role(db, e.tenant_id, code)
        role_names.append(row.name if row else code)
    return EmployeeOut(
        id=e.id,
        name=e.name,
        mobile=e.mobile,
        username=e.username,
        has_account=bool(e.username) or bool(e.mobile),
        roles=roles,
        role_names=role_names,
        department_id=e.department_id,
        department_name=department_name,
        position_id=e.position_id,
        position_name=position_name,
        salary_model=e.salary_model.value if hasattr(e.salary_model, "value") else str(e.salary_model),
        base_salary=e.base_salary or Decimal("0"),
        base_quota=e.base_quota or 0,
        skill_factor=getattr(e, "skill_factor", None) or Decimal("1.00"),
        bank_account=getattr(e, "bank_account", None),
        bank_name=getattr(e, "bank_name", None),
        bank_account_name=getattr(e, "bank_account_name", None),
        wechat_openid=e.wechat_openid,
        ext_source=getattr(e, "ext_source", None),
        ext_user_id=getattr(e, "ext_user_id", None),
        is_active=e.is_active,
        must_change_password=bool(getattr(e, "must_change_password", False)),
    ).model_dump(mode="json")


def _set_default_password(e: Employee) -> None:
    settings = get_settings()
    e.password_hash = hash_password(settings.worker_default_password)
    e.must_change_password = True


def _check_mobile_unique(db: Session, tenant_id: int, mobile: str | None, *, exclude_id: int | None = None) -> None:
    if not (mobile or "").strip():
        return
    q = select(Employee).where(
        Employee.tenant_id == tenant_id, Employee.mobile == (mobile or "").strip()
    )
    if exclude_id is not None:
        q = q.where(Employee.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(status_code=400, detail="手机号已存在")


def _check_username_unique(db: Session, tenant_id: int, username: str | None, *, exclude_id: int | None = None) -> None:
    if not (username or "").strip():
        return
    q = select(Employee).where(
        Employee.tenant_id == tenant_id, Employee.username == (username or "").strip()
    )
    if exclude_id is not None:
        q = q.where(Employee.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(status_code=400, detail="用户名已存在")


def _dept_descendant_ids(db: Session, tenant_id: int, department_id: int) -> set[int]:
    """含自身的部门树后代 id 集合（员工页按部门筛选默认含子部门）。"""
    deps = db.scalars(
        select(Department).where(Department.tenant_id == tenant_id, Department.is_active.is_(True))
    ).all()
    children: dict[int, list[int]] = {}
    for d in deps:
        if d.parent_id is not None:
            children.setdefault(d.parent_id, []).append(d.id)
    out: set[int] = set()
    stack = [department_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


@router.get("")
def list_employees(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    department_id: Optional[int] = None,
    position_id: Optional[int] = None,
    has_account: Optional[bool] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    page, page_size, offset = normalize_page(page, page_size, max_size=500)
    scoped = team_service.leader_worker_ids(db, employee)
    if scoped is not None and not scoped:
        return ok(
            {
                **page_payload([], 0, page, page_size),
                "team_scoped": True,
                "team_empty": True,
            }
        )
    filters = [Employee.tenant_id == employee.tenant_id]
    if scoped is not None:
        filters.append(Employee.id.in_(scoped))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        filters.append(or_(Employee.name.ilike(like), Employee.mobile.ilike(like)))
    if department_id is not None:
        filters.append(Employee.department_id.in_(_dept_descendant_ids(db, employee.tenant_id, department_id)))
    if position_id is not None:
        filters.append(Employee.position_id == position_id)
    if has_account is not None:
        if has_account:
            filters.append(or_(Employee.username.isnot(None), Employee.mobile.isnot(None)))
        else:
            filters.append(Employee.username.is_(None))
            filters.append(Employee.mobile.is_(None))
    if is_active is not None:
        filters.append(Employee.is_active.is_(is_active))
    total = int(db.scalar(select(func.count()).select_from(Employee).where(*filters)) or 0)
    rows = db.scalars(
        select(Employee).where(*filters).order_by(Employee.id.desc()).offset(offset).limit(page_size)
    ).all()
    items = [_employee_out(db, e) for e in rows]
    return ok(
        {
            **page_payload(items, total, page, page_size),
            "team_scoped": scoped is not None,
            "team_empty": False,
        }
    )


@router.post("")
def create_employee(
    body: EmployeeCreate,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    _check_mobile_unique(db, employee.tenant_id, body.mobile)
    _check_username_unique(db, employee.tenant_id, body.username)
    position_id = body.position_id
    if position_id is not None:
        _resolve_position(db, employee.tenant_id, position_id)
    department_id = body.department_id
    if department_id is not None:
        _resolve_department(db, employee.tenant_id, department_id)
    username = (body.username or "").strip() or None
    e = Employee(
        tenant_id=employee.tenant_id,
        name=body.name,
        mobile=(body.mobile or "").strip() or None,
        username=username,
        department_id=department_id,
        position_id=position_id,
        salary_model=(
            SalaryModel(body.salary_model)
            if body.salary_model in SalaryModel.__members__
            else SalaryModel.pure_piece
        ),
        base_salary=body.base_salary,
        base_quota=body.base_quota,
        skill_factor=Decimal(body.skill_factor or 1) if getattr(body, "skill_factor", None) is not None else Decimal("1.00"),
        bank_account=(body.bank_account or "").strip() or None,
        bank_name=(body.bank_name or "").strip() or None,
        bank_account_name=(body.bank_account_name or "").strip() or None,
    )
    if username:
        if body.password:
            # 显式创建账号：使用指定密码，不强制首登改密
            e.password_hash = hash_password(body.password)
            e.must_change_password = False
        else:
            # 密码不填：默认密码 + 首登改密
            _set_default_password(e)
    else:
        # 纯工人（无用户名）：默认密码 + 首登改密（保留手机号+密码登录能力）
        _set_default_password(e)
    db.add(e)
    db.flush()
    role_codes = list(body.roles or [])
    if role_codes:
        try:
            rbac_service.set_employee_roles(db, e, role_codes)
        except RbacError as err:
            db.rollback()
            raise HTTPException(status_code=400, detail=err.message) from err
    db.commit()
    db.refresh(e)
    return ok(_employee_out(db, e))


@router.patch("/{employee_id}")
def update_employee(
    employee_id: int,
    body: EmployeeUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_employee),
):
    target = db.get(Employee, employee_id)
    if not target or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="员工不存在")
    data = body.model_dump(exclude_unset=True)
    reset_password = data.pop("reset_password", None)
    if "mobile" in data:
        _check_mobile_unique(db, actor.tenant_id, data["mobile"], exclude_id=target.id)
        data["mobile"] = (data["mobile"] or "").strip() or None
    if "username" in data:
        new_username = (data["username"] or "").strip() or None
        _check_username_unique(db, actor.tenant_id, new_username, exclude_id=target.id)
        data["username"] = new_username
        if new_username and not target.password_hash:
            _set_default_password(target)
    if "skill_factor" in data and data["skill_factor"] is not None:
        sf = Decimal(data["skill_factor"])
        if sf <= 0:
            raise HTTPException(status_code=400, detail="技能系数须大于 0")
        data["skill_factor"] = sf
    if "salary_model" in data and data["salary_model"] in SalaryModel.__members__:
        data["salary_model"] = SalaryModel(data["salary_model"])
    if "position_id" in data:
        pid = data["position_id"]
        if pid is not None:
            _resolve_position(db, actor.tenant_id, pid, allow_inactive_id=target.position_id)
        data["position_id"] = pid
    if "department_id" in data:
        did = data["department_id"]
        if did is not None:
            _resolve_department(db, actor.tenant_id, did)
        data["department_id"] = did
    if "is_active" in data and target.id == actor.id and data["is_active"] is False:
        raise HTTPException(status_code=400, detail="不能停用自己")
    for bank_key in ("bank_account", "bank_name", "bank_account_name"):
        if bank_key in data and isinstance(data[bank_key], str):
            data[bank_key] = data[bank_key].strip() or None
    password = data.pop("password", None)
    if password:
        target.password_hash = hash_password(password)
        target.must_change_password = False
    roles = data.pop("roles", None)
    for k, v in data.items():
        setattr(target, k, v)
    if roles is not None:
        try:
            rbac_service.set_employee_roles(db, target, roles)
        except RbacError as err:
            raise HTTPException(status_code=400, detail=err.message) from err
    if reset_password:
        _set_default_password(target)
    db.commit()
    db.refresh(target)
    return ok(_employee_out(db, target))


# ── 兼容别名：/workers → /employees（旧前端页面/下拉框继续可用）──
_workers_router = APIRouter(prefix="/workers", tags=["employees-compat"], include_in_schema=False)
_workers_router.get("")(list_employees)
_workers_router.post("")(create_employee)


@_workers_router.patch("/{worker_id}")
def update_worker_compat(
    worker_id: int,
    body: EmployeeUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_employee),
):
    return update_employee(worker_id, body, db, actor)

