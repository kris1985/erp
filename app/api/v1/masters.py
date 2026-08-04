from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import ProcessDefinition, ProcessType, User, Worker, WorkerRole
from app.schemas.api import ProcessCreate, ProcessOut, WorkerCreate, WorkerOut
from app.schemas.common import ok

router = APIRouter(tags=["masters"])


@router.get("/workers")
def list_workers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Worker).where(Worker.tenant_id == user.tenant_id).order_by(Worker.id.desc())
    ).all()
    items = [
        WorkerOut(
            id=w.id,
            name=w.name,
            mobile=w.mobile,
            role=w.role.value if hasattr(w.role, "value") else str(w.role),
            wechat_openid=w.wechat_openid,
            is_active=w.is_active,
        ).model_dump()
        for w in rows
    ]
    return ok({"items": items, "total": len(items)})


@router.post("/workers")
def create_worker(body: WorkerCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = Worker(
        tenant_id=user.tenant_id,
        name=body.name,
        mobile=body.mobile,
        role=WorkerRole(body.role) if body.role in WorkerRole.__members__ else WorkerRole.worker,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return ok(
        WorkerOut(
            id=w.id,
            name=w.name,
            mobile=w.mobile,
            role=w.role.value,
            wechat_openid=w.wechat_openid,
            is_active=w.is_active,
        ).model_dump()
    )


@router.get("/processes")
def list_processes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(ProcessDefinition)
        .where(ProcessDefinition.tenant_id == user.tenant_id)
        .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
    ).all()
    items = [
        ProcessOut(
            id=p.id,
            name=p.name,
            code=p.code,
            default_price=p.default_price,
            sort_order=p.sort_order,
            type=p.type.value if hasattr(p.type, "value") else str(p.type),
            is_active=p.is_active,
        ).model_dump()
        for p in rows
    ]
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
        sort_order=body.sort_order,
        type=ProcessType(body.type) if body.type in ProcessType.__members__ else ProcessType.personal,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(
        ProcessOut(
            id=p.id,
            name=p.name,
            code=p.code,
            default_price=p.default_price,
            sort_order=p.sort_order,
            type=p.type.value,
            is_active=p.is_active,
        ).model_dump()
    )
