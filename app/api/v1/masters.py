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
def list_processes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(ProcessDefinition)
        .where(ProcessDefinition.tenant_id == user.tenant_id)
        .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
    ).all()
    items = [_process_out(p) for p in rows]
    return ok({"items": items, "total": len(items)})


@router.post("/processes")
def create_process(body: ProcessCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exists = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == user.tenant_id, ProcessDefinition.code == body.code
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="工序编码已存在")
    p = ProcessDefinition(
        tenant_id=user.tenant_id,
        name=body.name,
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
    return ok({"items": [SizeOut.model_validate(r).model_dump() for r in rows], "total": len(rows)})


@router.post("/sizes")
def create_size(body: SizeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exists = db.scalar(
        select(Size).where(Size.tenant_id == user.tenant_id, Size.size_value == body.size_value)
    )
    if exists:
        raise HTTPException(status_code=400, detail="尺码已存在")
    s = Size(tenant_id=user.tenant_id, size_value=body.size_value, sort_order=body.sort_order)
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
    proc_ids = {r.default_consume_process_id for r in rows if r.default_consume_process_id}
    proc_map: dict[int, str] = {}
    if proc_ids:
        for p in db.scalars(
            select(ProcessDefinition).where(
                ProcessDefinition.tenant_id == user.tenant_id,
                ProcessDefinition.id.in_(proc_ids),
            )
        ).all():
            proc_map[p.id] = p.name
    items = []
    for r in rows:
        d = MaterialCategoryOut.model_validate(r).model_dump()
        pid = r.default_consume_process_id
        d["default_consume_process_name"] = proc_map.get(pid) if pid else None
        items.append(d)
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
    row = MaterialCategory(
        tenant_id=user.tenant_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
        default_consume_process_id=body.default_consume_process_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = MaterialCategoryOut.model_validate(row).model_dump()
    out["default_consume_process_name"] = (
        db.get(ProcessDefinition, row.default_consume_process_id).name
        if row.default_consume_process_id
        else None
    )
    return ok(out)


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
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    out = MaterialCategoryOut.model_validate(row).model_dump()
    out["default_consume_process_name"] = (
        db.get(ProcessDefinition, row.default_consume_process_id).name
        if row.default_consume_process_id
        else None
    )
    return ok(out)


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
