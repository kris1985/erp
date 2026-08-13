from decimal import Decimal
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, require_roles
from app.config import get_settings
from app.db import get_db
from app.models import (
    Color,
    MaterialCategory,
    MaterialSizeUsageTable,
    OtherCostItem,
    PartDefinition,
    Position,
    PricingUnit,
    ProcessDefinition,
    ProcessType,
    SalaryModel,
    Size,
    User,
    Worker,
    WorkerRole,
)
from app.schemas.api import (
    ColorCreate,
    ColorOut,
    ColorUpdate,
    MaterialCategoryCreate,
    MaterialCategoryOut,
    MaterialCategoryUpdate,
    OtherCostItemCreate,
    OtherCostItemOut,
    OtherCostItemUpdate,
    PartDefinitionCreate,
    PartDefinitionOut,
    PartDefinitionUpdate,
    PositionCreate,
    PositionOut,
    PositionUpdate,
    PricingUnitCreate,
    PricingUnitOut,
    PricingUnitUpdate,
    ProcessCreate,
    ProcessOut,
    ProcessUpdate,
    SizeCreate,
    SizeOut,
    SizeUpdate,
    WorkerCreate,
    WorkerOut,
    WorkerUpdate,
)
from app.schemas.common import ok

router = APIRouter(tags=["masters"])


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
        raise HTTPException(status_code=400, detail="职位不存在")
    if not pos.is_active and position_id != allow_inactive_id:
        raise HTTPException(status_code=400, detail="职位未启用")
    return pos


def _worker_out(db: Session, w: Worker) -> dict:
    position_name = None
    if w.position_id:
        pos = db.get(Position, w.position_id)
        if pos and pos.tenant_id == w.tenant_id:
            position_name = pos.name
    return WorkerOut(
        id=w.id,
        name=w.name,
        mobile=w.mobile,
        role=w.role.value if hasattr(w.role, "value") else str(w.role),
        position_id=w.position_id,
        position_name=position_name,
        salary_model=w.salary_model.value if hasattr(w.salary_model, "value") else str(w.salary_model),
        base_salary=w.base_salary or Decimal("0"),
        base_quota=w.base_quota or 0,
        skill_factor=getattr(w, "skill_factor", None) or Decimal("1.00"),
        bank_account=getattr(w, "bank_account", None),
        bank_name=getattr(w, "bank_name", None),
        bank_account_name=getattr(w, "bank_account_name", None),
        wechat_openid=w.wechat_openid,
        is_active=w.is_active,
        must_change_password=bool(getattr(w, "must_change_password", False)),
    ).model_dump(mode="json")


def _set_default_password(w: Worker) -> None:
    settings = get_settings()
    w.password_hash = hash_password(settings.worker_default_password)
    w.must_change_password = True


@router.get("/workers")
def list_workers(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    position_id: Optional[int] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import func

    from app.schemas.common import normalize_page, page_payload
    from app.services import team_service

    page, page_size, offset = normalize_page(page, page_size, max_size=500)
    scoped = team_service.leader_worker_ids(db, user)
    if scoped is not None and not scoped:
        return ok(
            {
                **page_payload([], 0, page, page_size),
                "team_scoped": True,
                "team_empty": True,
            }
        )
    filters = [Worker.tenant_id == user.tenant_id]
    if scoped is not None:
        filters.append(Worker.id.in_(scoped))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        filters.append(or_(Worker.name.ilike(like), Worker.mobile.ilike(like)))
    if position_id is not None:
        filters.append(Worker.position_id == position_id)
    if role:
        if role not in WorkerRole.__members__:
            raise HTTPException(status_code=400, detail="无效角色")
        filters.append(Worker.role == WorkerRole(role))
    if is_active is not None:
        filters.append(Worker.is_active.is_(is_active))
    total = int(db.scalar(select(func.count()).select_from(Worker).where(*filters)) or 0)
    rows = db.scalars(
        select(Worker).where(*filters).order_by(Worker.id.desc()).offset(offset).limit(page_size)
    ).all()
    items = [_worker_out(db, w) for w in rows]
    return ok(
        {
            **page_payload(items, total, page, page_size),
            "team_scoped": scoped is not None,
            "team_empty": False,
        }
    )


@router.post("/workers")
def create_worker(body: WorkerCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.mobile:
        exists = db.scalar(
            select(Worker).where(Worker.tenant_id == user.tenant_id, Worker.mobile == body.mobile)
        )
        if exists:
            raise HTTPException(status_code=400, detail="手机号已存在")
    position_id = body.position_id
    if position_id is not None:
        _resolve_position(db, user.tenant_id, position_id)
    w = Worker(
        tenant_id=user.tenant_id,
        name=body.name,
        mobile=body.mobile,
        role=WorkerRole(body.role) if body.role in WorkerRole.__members__ else WorkerRole.worker,
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
    _set_default_password(w)
    db.add(w)
    db.commit()
    db.refresh(w)
    return ok(_worker_out(db, w))


@router.patch("/workers/{worker_id}")
def update_worker(
    worker_id: int,
    body: WorkerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    w = db.get(Worker, worker_id)
    if not w or w.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工人不存在")
    data = body.model_dump(exclude_unset=True)
    reset_password = data.pop("reset_password", None)
    if "mobile" in data and data["mobile"]:
        exists = db.scalar(
            select(Worker).where(
                Worker.tenant_id == user.tenant_id,
                Worker.mobile == data["mobile"],
                Worker.id != worker_id,
            )
        )
        if exists:
            raise HTTPException(status_code=400, detail="手机号已存在")
    if "role" in data and data["role"] in WorkerRole.__members__:
        data["role"] = WorkerRole(data["role"])
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
            _resolve_position(db, user.tenant_id, pid, allow_inactive_id=w.position_id)
        data["position_id"] = pid
    for bank_key in ("bank_account", "bank_name", "bank_account_name"):
        if bank_key in data and isinstance(data[bank_key], str):
            data[bank_key] = data[bank_key].strip() or None
    for k, v in data.items():
        setattr(w, k, v)
    if reset_password:
        _set_default_password(w)
    db.commit()
    db.refresh(w)
    return ok(_worker_out(db, w))


def _process_out(p: ProcessDefinition) -> dict:
    return ProcessOut(
        id=p.id,
        name=p.name,
        code=p.code,
        default_price=p.default_price,
        default_days=int(getattr(p, "default_days", None) or 1),
        sort_order=p.sort_order,
        type=p.type.value if hasattr(p.type, "value") else str(p.type),
        is_active=p.is_active,
    ).model_dump(mode="json")


@router.get("/processes")
def list_processes(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(ProcessDefinition).where(ProcessDefinition.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(ProcessDefinition.is_active.is_(True))
    rows = db.scalars(q.order_by(ProcessDefinition.sort_order, ProcessDefinition.id)).all()
    items = [_process_out(p) for p in rows]
    return ok({"items": items, "total": len(items)})


@router.post("/processes")
def create_process(body: ProcessCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写工序名称")
    name_exists = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == user.tenant_id, ProcessDefinition.name == name
        )
    )
    if name_exists:
        raise HTTPException(status_code=400, detail="工序名称已存在")
    exists = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == user.tenant_id, ProcessDefinition.code == body.code
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="工序编码已存在")
    p = ProcessDefinition(
        tenant_id=user.tenant_id,
        name=name,
        code=body.code,
        default_price=body.default_price,
        default_days=max(1, int(body.default_days or 1)),
        sort_order=body.sort_order,
        type=ProcessType(body.type) if body.type in ProcessType.__members__ else ProcessType.personal,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(_process_out(p))


@router.patch("/processes/{process_id}")
def update_process(
    process_id: int,
    body: ProcessUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import OrderProcess, OrderProcessStatus

    p = db.get(ProcessDefinition, process_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工序不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写工序名称")
        name_dup = db.scalar(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == user.tenant_id,
                ProcessDefinition.name == name,
                ProcessDefinition.id != process_id,
            )
        )
        if name_dup:
            raise HTTPException(status_code=400, detail="工序名称已存在")
        data["name"] = name
    if "code" in data and data["code"] != p.code:
        exists = db.scalar(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == user.tenant_id,
                ProcessDefinition.code == data["code"],
                ProcessDefinition.id != process_id,
            )
        )
        if exists:
            raise HTTPException(status_code=400, detail="工序编码已存在")
    if "type" in data and data["type"] in ProcessType.__members__:
        new_type = ProcessType(data["type"])
        old_type = p.type if isinstance(p.type, ProcessType) else ProcessType(str(p.type))
        if new_type != old_type:
            open_ref = db.scalar(
                select(OrderProcess.id).where(
                    OrderProcess.tenant_id == user.tenant_id,
                    OrderProcess.process_id == process_id,
                    OrderProcess.status.in_(
                        (OrderProcessStatus.pending, OrderProcessStatus.in_progress)
                    ),
                ).limit(1)
            )
            if open_ref:
                raise HTTPException(
                    status_code=400,
                    detail="该工序仍有在制订单，不能改个人/集体类型；请待相关订单完工后再改",
                )
        data["type"] = new_type
    if "default_days" in data and data["default_days"] is not None:
        try:
            data["default_days"] = max(1, int(data["default_days"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="default_days 无效")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return ok(_process_out(p))


def _process_delete_blockers(db: Session, tenant_id: int, process_id: int) -> list[str]:
    """硬删引用检查；返回人话阻断原因。"""
    from app.models import (
        DefectEvent,
        MaterialCategory,
        OrderMaterialRequirement,
        OrderProcess,
        OwnProductLabor,
        OwnProductMaterial,
        ScheduleDraftLine,
        Station,
        TraceUnit,
        TraceUnitLog,
        WorkLog,
    )

    checks: list[tuple[str, object]] = [
        ("订单工序", select(OrderProcess.id).where(
            OrderProcess.tenant_id == tenant_id, OrderProcess.process_id == process_id
        ).limit(1)),
        ("产品工序", select(OwnProductLabor.id).where(
            OwnProductLabor.tenant_id == tenant_id, OwnProductLabor.process_id == process_id
        ).limit(1)),
        ("产品用料归属", select(OwnProductMaterial.id).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.consume_process_id == process_id,
        ).limit(1)),
        ("材料分类默认工序", select(MaterialCategory.id).where(
            MaterialCategory.tenant_id == tenant_id,
            MaterialCategory.default_consume_process_id == process_id,
        ).limit(1)),
        ("订单用料归属", select(OrderMaterialRequirement.id).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.consume_process_id == process_id,
        ).limit(1)),
        ("报工记录", select(WorkLog.id).where(
            WorkLog.tenant_id == tenant_id, WorkLog.process_id == process_id
        ).limit(1)),
        ("工位", select(Station.id).where(
            Station.tenant_id == tenant_id, Station.process_id == process_id
        ).limit(1)),
        ("捆标当前工序", select(TraceUnit.id).where(
            TraceUnit.tenant_id == tenant_id, TraceUnit.current_process_id == process_id
        ).limit(1)),
        ("捆标流转", select(TraceUnitLog.id).where(
            TraceUnitLog.tenant_id == tenant_id, TraceUnitLog.process_id == process_id
        ).limit(1)),
        ("不良记录", select(DefectEvent.id).where(
            DefectEvent.tenant_id == tenant_id,
            (DefectEvent.found_process_id == process_id)
            | (DefectEvent.responsible_process_id == process_id),
        ).limit(1)),
        ("排产草稿", select(ScheduleDraftLine.id).where(
            ScheduleDraftLine.tenant_id == tenant_id,
            ScheduleDraftLine.process_id == process_id,
        ).limit(1)),
    ]
    blockers: list[str] = []
    for label, stmt in checks:
        if db.scalar(stmt):
            blockers.append(label)
    return blockers


@router.delete("/processes/{process_id}")
def delete_process(
    process_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = db.get(ProcessDefinition, process_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="工序不存在")
    blockers = _process_delete_blockers(db, user.tenant_id, process_id)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail=f"工序「{p.name}」仍被引用（{'、'.join(blockers)}），请先停用或清理引用后再删",
        )
    db.delete(p)
    db.commit()
    return ok({"deleted": True, "id": process_id})


@router.get("/colors")
def list_colors(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Color).where(Color.tenant_id == user.tenant_id).order_by(Color.id)).all()
    return ok({"items": [ColorOut.model_validate(r).model_dump() for r in rows], "total": len(rows)})


@router.post("/colors")
def create_color(body: ColorCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写颜色名称")
    existing_name = db.scalar(
        select(Color).where(Color.tenant_id == user.tenant_id, Color.name == name)
    )
    if existing_name:
        return ok(ColorOut.model_validate(existing_name).model_dump())
    code = (body.code or "").strip()
    if not code:
        code = f"C{uuid.uuid4().hex[:6].upper()}"
        while db.scalar(
            select(Color).where(Color.tenant_id == user.tenant_id, Color.code == code)
        ):
            code = f"C{uuid.uuid4().hex[:6].upper()}"
    else:
        exists = db.scalar(
            select(Color).where(Color.tenant_id == user.tenant_id, Color.code == code)
        )
        if exists:
            raise HTTPException(status_code=400, detail="颜色编码已存在")
    c = Color(tenant_id=user.tenant_id, name=name, code=code)
    db.add(c)
    db.commit()
    db.refresh(c)
    return ok(ColorOut.model_validate(c).model_dump())


@router.patch("/colors/{color_id}")
def update_color(
    color_id: int,
    body: ColorUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.get(Color, color_id)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="颜色不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] != c.code:
        exists = db.scalar(
            select(Color).where(
                Color.tenant_id == user.tenant_id, Color.code == data["code"], Color.id != color_id
            )
        )
        if exists:
            raise HTTPException(status_code=400, detail="颜色编码已存在")
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return ok(ColorOut.model_validate(c).model_dump())


@router.get("/sizes")
def list_sizes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Size).where(Size.tenant_id == user.tenant_id).order_by(Size.sort_order)).all()
    items = []
    for r in rows:
        d = SizeOut.model_validate(r).model_dump()
        if d.get("is_active") is None:
            d["is_active"] = True
        items.append(d)
    return ok({"items": items, "total": len(items)})


@router.post("/sizes")
def create_size(body: SizeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exists = db.scalar(
        select(Size).where(Size.tenant_id == user.tenant_id, Size.size_value == body.size_value)
    )
    if exists:
        raise HTTPException(status_code=400, detail="尺码已存在")
    s = Size(
        tenant_id=user.tenant_id,
        size_value=body.size_value,
        sort_order=body.sort_order,
        is_active=True if body.is_active is None else bool(body.is_active),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(SizeOut.model_validate(s).model_dump())


@router.patch("/sizes/{size_id}")
def update_size(
    size_id: int,
    body: SizeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = db.get(Size, size_id)
    if not s or s.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="尺码不存在")
    data = body.model_dump(exclude_unset=True)
    if "size_value" in data and data["size_value"] != s.size_value:
        exists = db.scalar(
            select(Size).where(
                Size.tenant_id == user.tenant_id,
                Size.size_value == data["size_value"],
                Size.id != size_id,
            )
        )
        if exists:
            raise HTTPException(status_code=400, detail="尺码已存在")
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return ok(SizeOut.model_validate(s).model_dump())


def _category_out(db: Session, tenant_id: int, row: MaterialCategory) -> dict:
    d = MaterialCategoryOut.model_validate(row).model_dump()
    pid = row.default_consume_process_id
    d["default_consume_process_name"] = None
    if pid:
        proc = db.get(ProcessDefinition, pid)
        d["default_consume_process_name"] = proc.name if proc and proc.tenant_id == tenant_id else None
    tid = getattr(row, "default_size_usage_table_id", None)
    d["default_size_usage_table_name"] = None
    if tid:
        table = db.get(MaterialSizeUsageTable, tid)
        d["default_size_usage_table_name"] = (
            table.name if table and table.tenant_id == tenant_id else None
        )
    d["suggest_usage_by_size"] = bool(getattr(row, "suggest_usage_by_size", False))
    return d


def _ensure_size_usage_table(db: Session, tenant_id: int, table_id: int | None) -> None:
    if table_id is None:
        return
    table = db.get(MaterialSizeUsageTable, table_id)
    if not table or table.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="用量码表不存在")


@router.get("/material-categories")
def list_material_categories(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(MaterialCategory).where(MaterialCategory.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(MaterialCategory.is_active.is_(True))
    rows = db.scalars(q.order_by(MaterialCategory.sort_order, MaterialCategory.id)).all()
    items = [_category_out(db, user.tenant_id, r) for r in rows]
    return ok({"items": items, "total": len(items)})


def _ensure_consume_process(db: Session, tenant_id: int, process_id: int | None) -> None:
    if process_id is None:
        return
    proc = db.get(ProcessDefinition, process_id)
    if not proc or proc.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="默认消耗工序不存在")


@router.post("/material-categories")
def create_material_category(
    body: MaterialCategoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写分类名称")
    exists = db.scalar(
        select(MaterialCategory).where(
            MaterialCategory.tenant_id == user.tenant_id,
            MaterialCategory.name == name,
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="分类名称已存在")
    _ensure_consume_process(db, user.tenant_id, body.default_consume_process_id)
    _ensure_size_usage_table(db, user.tenant_id, body.default_size_usage_table_id)
    suggest = bool(body.suggest_usage_by_size)
    table_id = body.default_size_usage_table_id
    if suggest and not table_id:
        from app.services.material_service import ensure_default_size_usage_table

        table_id = ensure_default_size_usage_table(
            db, user.tenant_id, link_suggest_categories=False
        ).id
    if not suggest:
        table_id = None
    row = MaterialCategory(
        tenant_id=user.tenant_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
        default_consume_process_id=body.default_consume_process_id,
        suggest_usage_by_size=suggest,
        default_size_usage_table_id=table_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(_category_out(db, user.tenant_id, row))


@router.patch("/material-categories/{category_id}")
def update_material_category(
    category_id: int,
    body: MaterialCategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(MaterialCategory, category_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="分类不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写分类名称")
        dup = db.scalar(
            select(MaterialCategory).where(
                MaterialCategory.tenant_id == user.tenant_id,
                MaterialCategory.name == name,
                MaterialCategory.id != category_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="分类名称已存在")
        data["name"] = name
    if "default_consume_process_id" in data:
        _ensure_consume_process(db, user.tenant_id, data["default_consume_process_id"])
    if "default_size_usage_table_id" in data:
        _ensure_size_usage_table(db, user.tenant_id, data["default_size_usage_table_id"])
    for k, v in data.items():
        setattr(row, k, v)
    if row.suggest_usage_by_size and not row.default_size_usage_table_id:
        from app.services.material_service import ensure_default_size_usage_table

        row.default_size_usage_table_id = ensure_default_size_usage_table(
            db, user.tenant_id, link_suggest_categories=False
        ).id
    if not row.suggest_usage_by_size:
        row.default_size_usage_table_id = None
    db.commit()
    db.refresh(row)
    return ok(_category_out(db, user.tenant_id, row))


@router.get("/positions")
def list_positions(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Position).where(Position.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(Position.is_active.is_(True))
    rows = db.scalars(q.order_by(Position.sort_order, Position.id)).all()
    return ok({"items": [PositionOut.model_validate(r).model_dump() for r in rows], "total": len(rows)})


@router.post("/positions")
def create_position(
    body: PositionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写职位名称")
    exists = db.scalar(
        select(Position).where(Position.tenant_id == user.tenant_id, Position.name == name)
    )
    if exists:
        raise HTTPException(status_code=400, detail="职位名称已存在")
    row = Position(
        tenant_id=user.tenant_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(PositionOut.model_validate(row).model_dump())


@router.patch("/positions/{position_id}")
def update_position(
    position_id: int,
    body: PositionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(Position, position_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="职位不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写职位名称")
        dup = db.scalar(
            select(Position).where(
                Position.tenant_id == user.tenant_id,
                Position.name == name,
                Position.id != position_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="职位名称已存在")
        data["name"] = name
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ok(PositionOut.model_validate(row).model_dump())


@router.get("/pricing-units")
def list_pricing_units(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(PricingUnit).where(PricingUnit.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(PricingUnit.is_active.is_(True))
    rows = db.scalars(q.order_by(PricingUnit.sort_order, PricingUnit.id)).all()
    return ok(
        {"items": [PricingUnitOut.model_validate(r).model_dump() for r in rows], "total": len(rows)}
    )


@router.post("/pricing-units")
def create_pricing_unit(
    body: PricingUnitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写单位名称")
    exists = db.scalar(
        select(PricingUnit).where(PricingUnit.tenant_id == user.tenant_id, PricingUnit.name == name)
    )
    if exists:
        raise HTTPException(status_code=400, detail="计价单位已存在")
    row = PricingUnit(
        tenant_id=user.tenant_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(PricingUnitOut.model_validate(row).model_dump())


@router.patch("/pricing-units/{unit_id}")
def update_pricing_unit(
    unit_id: int,
    body: PricingUnitUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(PricingUnit, unit_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="计价单位不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写单位名称")
        dup = db.scalar(
            select(PricingUnit).where(
                PricingUnit.tenant_id == user.tenant_id,
                PricingUnit.name == name,
                PricingUnit.id != unit_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="计价单位已存在")
        data["name"] = name
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ok(PricingUnitOut.model_validate(row).model_dump())


@router.get("/other-cost-items")
def list_other_cost_items(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(OtherCostItem).where(OtherCostItem.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(OtherCostItem.is_active.is_(True))
    rows = db.scalars(q.order_by(OtherCostItem.sort_order, OtherCostItem.id)).all()
    return ok(
        {
            "items": [OtherCostItemOut.model_validate(r).model_dump() for r in rows],
            "total": len(rows),
        }
    )


@router.post("/other-cost-items")
def create_other_cost_item(
    body: OtherCostItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写项目名称")
    exists = db.scalar(
        select(OtherCostItem).where(
            OtherCostItem.tenant_id == user.tenant_id, OtherCostItem.name == name
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="其它成本项目已存在")
    row = OtherCostItem(
        tenant_id=user.tenant_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(OtherCostItemOut.model_validate(row).model_dump())


@router.patch("/other-cost-items/{item_id}")
def update_other_cost_item(
    item_id: int,
    body: OtherCostItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(OtherCostItem, item_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="其它成本项目不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写项目名称")
        dup = db.scalar(
            select(OtherCostItem).where(
                OtherCostItem.tenant_id == user.tenant_id,
                OtherCostItem.name == name,
                OtherCostItem.id != item_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="其它成本项目已存在")
        data["name"] = name
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ok(OtherCostItemOut.model_validate(row).model_dump())


# ----- B1c 用量码表 -----


@router.get("/material-size-usage-tables")
def list_material_size_usage_tables(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import MaterialSizeUsageCoeff, MaterialSizeUsageTable

    tables = db.scalars(
        select(MaterialSizeUsageTable)
        .where(MaterialSizeUsageTable.tenant_id == user.tenant_id)
        .order_by(MaterialSizeUsageTable.id)
    ).all()
    out = []
    for t in tables:
        coeffs = db.scalars(
            select(MaterialSizeUsageCoeff)
            .where(
                MaterialSizeUsageCoeff.tenant_id == user.tenant_id,
                MaterialSizeUsageCoeff.table_id == t.id,
            )
            .order_by(MaterialSizeUsageCoeff.size_id)
        ).all()
        size_ids = [c.size_id for c in coeffs]
        size_map = {
            s.id: s.size_value
            for s in db.scalars(select(Size).where(Size.id.in_(size_ids or [-1]))).all()
        } if size_ids else {}
        out.append(
            {
                "id": t.id,
                "name": t.name,
                "notes": t.notes,
                "created_at": t.created_at,
                "coeffs": [
                    {
                        "id": c.id,
                        "size_id": c.size_id,
                        "size_value": size_map.get(c.size_id),
                        "coeff": c.coeff,
                    }
                    for c in coeffs
                ],
            }
        )
    return ok({"items": out, "total": len(out)})


@router.post("/material-size-usage-tables")
def create_material_size_usage_table(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from decimal import Decimal

    from app.models import MaterialSizeUsageCoeff, MaterialSizeUsageTable

    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写码表名称")
    table = MaterialSizeUsageTable(
        tenant_id=user.tenant_id,
        name=name,
        notes=(str(body.get("notes") or "").strip() or None),
    )
    db.add(table)
    db.flush()
    for item in body.get("coeffs") or []:
        sid = item.get("size_id")
        if not sid:
            continue
        sz = db.get(Size, int(sid))
        if not sz or sz.tenant_id != user.tenant_id:
            raise HTTPException(status_code=400, detail=f"尺码不存在: {sid}")
        db.add(
            MaterialSizeUsageCoeff(
                tenant_id=user.tenant_id,
                table_id=table.id,
                size_id=int(sid),
                coeff=Decimal(str(item.get("coeff") or 1)),
            )
        )
    db.commit()
    db.refresh(table)
    return ok({"id": table.id, "name": table.name})


@router.patch("/material-size-usage-tables/{table_id}")
def update_material_size_usage_table(
    table_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from decimal import Decimal

    from app.models import MaterialSizeUsageCoeff, MaterialSizeUsageTable

    table = db.get(MaterialSizeUsageTable, table_id)
    if not table or table.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="用量码表不存在")
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写码表名称")
        table.name = name
    if "notes" in body:
        table.notes = (str(body.get("notes") or "").strip() or None)
    if "coeffs" in body:
        existing = {
            c.size_id: c
            for c in db.scalars(
                select(MaterialSizeUsageCoeff).where(
                    MaterialSizeUsageCoeff.tenant_id == user.tenant_id,
                    MaterialSizeUsageCoeff.table_id == table.id,
                )
            ).all()
        }
        seen: set[int] = set()
        for item in body.get("coeffs") or []:
            sid = int(item["size_id"])
            seen.add(sid)
            coeff = Decimal(str(item.get("coeff") or 1))
            if sid in existing:
                existing[sid].coeff = coeff
            else:
                sz = db.get(Size, sid)
                if not sz or sz.tenant_id != user.tenant_id:
                    raise HTTPException(status_code=400, detail=f"尺码不存在: {sid}")
                db.add(
                    MaterialSizeUsageCoeff(
                        tenant_id=user.tenant_id,
                        table_id=table.id,
                        size_id=sid,
                        coeff=coeff,
                    )
                )
        for sid, row in existing.items():
            if sid not in seen:
                db.delete(row)
    db.commit()
    return ok({"id": table.id, "name": table.name})


@router.post("/material-size-usage-tables/{table_id}/fill-missing")
def fill_missing_size_coeffs(
    table_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一键补全租户全部尺码，缺的系数为 1。"""
    from decimal import Decimal

    from app.models import MaterialSizeUsageCoeff, MaterialSizeUsageTable

    table = db.get(MaterialSizeUsageTable, table_id)
    if not table or table.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="用量码表不存在")
    existing = {
        c.size_id
        for c in db.scalars(
            select(MaterialSizeUsageCoeff).where(
                MaterialSizeUsageCoeff.tenant_id == user.tenant_id,
                MaterialSizeUsageCoeff.table_id == table.id,
            )
        ).all()
    }
    sizes = db.scalars(
        select(Size).where(Size.tenant_id == user.tenant_id).order_by(Size.sort_order, Size.id)
    ).all()
    added = 0
    for sz in sizes:
        if sz.id in existing:
            continue
        db.add(
            MaterialSizeUsageCoeff(
                tenant_id=user.tenant_id,
                table_id=table.id,
                size_id=sz.id,
                coeff=Decimal("1"),
            )
        )
        added += 1
    db.commit()
    return ok({"added": added})


@router.post("/material-size-usage-tables/seed-defaults")
def seed_default_size_usage_tables(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入默认码表「大底通用」（全尺码系数=1），挂到大底/中底/鞋垫；
    同时拆旧分类、补默认消耗工序。"""
    from sqlalchemy import func

    from app.models import MaterialSizeUsageCoeff
    from app.services.material_service import (
        DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES,
        ensure_default_category_consume_processes,
        ensure_default_size_usage_table,
        split_legacy_material_categories,
    )

    split_stats = split_legacy_material_categories(db, user.tenant_id)
    table = ensure_default_size_usage_table(db, user.tenant_id)
    consume_updated = ensure_default_category_consume_processes(db, user.tenant_id)
    db.commit()
    n = db.scalar(
        select(func.count())
        .select_from(MaterialSizeUsageCoeff)
        .where(
            MaterialSizeUsageCoeff.tenant_id == user.tenant_id,
            MaterialSizeUsageCoeff.table_id == table.id,
        )
    )
    return ok(
        {
            "id": table.id,
            "name": table.name,
            "coeff_count": int(n or 0),
            "linked_categories": sorted(DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES),
            "consume_process_updated": consume_updated,
            "legacy_split": split_stats,
        }
    )


_PART_SOURCES = {"裁断", "外购", "其他"}


def _part_out(p: PartDefinition) -> dict:
    return PartDefinitionOut(
        id=p.id,
        code=p.code,
        name=p.name,
        source=p.source or "裁断",
        is_active=bool(p.is_active),
        created_at=p.created_at,
    ).model_dump(mode="json")


@router.get("/part-definitions")
def list_part_definitions(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(PartDefinition).where(PartDefinition.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(PartDefinition.is_active.is_(True))
    rows = db.scalars(q.order_by(PartDefinition.code, PartDefinition.id)).all()
    items = [_part_out(p) for p in rows]
    return ok({"items": items, "total": len(items)})


@router.post("/part-definitions")
def create_part_definition(
    body: PartDefinitionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    code = (body.code or "").strip().upper()
    name = (body.name or "").strip()
    source = (body.source or "裁断").strip() or "裁断"
    if not code:
        raise HTTPException(status_code=400, detail="请填写部件编码")
    if not name:
        raise HTTPException(status_code=400, detail="请填写部件名称")
    if source not in _PART_SOURCES:
        raise HTTPException(status_code=400, detail="部件来源须为：裁断 / 外购 / 其他")
    exists = db.scalar(
        select(PartDefinition).where(
            PartDefinition.tenant_id == user.tenant_id, PartDefinition.code == code
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="部件编码已存在")
    p = PartDefinition(
        tenant_id=user.tenant_id,
        code=code,
        name=name,
        source=source,
        is_active=bool(body.is_active),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(_part_out(p))


@router.patch("/part-definitions/{part_id}")
def update_part_definition(
    part_id: int,
    body: PartDefinitionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = db.get(PartDefinition, part_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="部件不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data:
        code = (data["code"] or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="请填写部件编码")
        exists = db.scalar(
            select(PartDefinition).where(
                PartDefinition.tenant_id == user.tenant_id,
                PartDefinition.code == code,
                PartDefinition.id != part_id,
            )
        )
        if exists:
            raise HTTPException(status_code=400, detail="部件编码已存在")
        data["code"] = code
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写部件名称")
        data["name"] = name
    if "source" in data:
        source = (data["source"] or "").strip() or "裁断"
        if source not in _PART_SOURCES:
            raise HTTPException(status_code=400, detail="部件来源须为：裁断 / 外购 / 其他")
        data["source"] = source
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return ok(_part_out(p))
