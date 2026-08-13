"""B2f：合批组批 + 详情 + 成员维护。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import User
from app.schemas.common import ok
from app.services import merge_batch_service
from app.services.merge_batch_service import MergeBatchError

router = APIRouter(tags=["merge-batches"])


class MergeBatchCreateIn(BaseModel):
    order_ids: list[int] = Field(min_length=2)
    require_same_color: bool = True
    note: str | None = None


class MergeBatchAddMembersIn(BaseModel):
    order_ids: list[int] = Field(min_length=1)
    require_same_color: bool = True


class MergeCutCardsIn(BaseModel):
    dry_run: bool = True
    only_missing: bool = True
    bundle_size: int | None = None


def _raise(e: MergeBatchError) -> None:
    code = 404 if e.code in ("not_found",) else 400
    raise HTTPException(status_code=code, detail=e.message)


_MERGE_CREATE_DISABLED = (
    "合批组批已停用：请用「排产」确认下发执行单；历史合批仍可查看、打印或作废"
)


@router.post("/merge-batches")
def create_merge_batch(
    body: MergeBatchCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    # 干掉生产单 K2：合批降只读，禁止新建
    raise HTTPException(status_code=400, detail=_MERGE_CREATE_DISABLED)


@router.get("/merge-batches/suggestions")
def suggest_merge_batches(
    delivery_window_days: int | None = Query(None, ge=0, le=60),
    require_same_color: bool | None = Query(None),
    min_qty: int | None = Query(None, ge=0),
    require_first_kit: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """P1-6：合批推荐（只读展示；K2 起不可采纳组批）。"""
    from app.services import merge_suggest_service

    return ok(
        merge_suggest_service.suggest_merge_batches(
            db,
            user.tenant_id,
            delivery_window_days=delivery_window_days,
            require_same_color=require_same_color,
            min_qty=min_qty,
            require_first_kit=require_first_kit,
            limit=limit,
        )
    )


@router.get("/merge-batches")
def list_merge_batches(
    status: str | None = Query(None),
    own_product_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        merge_batch_service.list_merge_batches(
            db,
            user.tenant_id,
            status=status,
            own_product_id=own_product_id,
            limit=limit,
        )
    )


@router.get("/merge-batches/{batch_id}")
def get_merge_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return ok(merge_batch_service.get_merge_batch(db, user.tenant_id, batch_id))
    except MergeBatchError as e:
        _raise(e)
        return


@router.post("/merge-batches/{batch_id}/members")
def add_merge_batch_members(
    batch_id: int,
    body: MergeBatchAddMembersIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    # 干掉生产单 K2：合批降只读，禁止加成员
    raise HTTPException(status_code=400, detail=_MERGE_CREATE_DISABLED)


@router.delete("/merge-batches/{batch_id}/members/{order_id}")
def remove_merge_batch_member(
    batch_id: int,
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(merge_batch_service.remove_member(db, user.tenant_id, batch_id, order_id))
    except MergeBatchError as e:
        _raise(e)
        return


@router.post("/merge-batches/{batch_id}/void")
def void_merge_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(merge_batch_service.void_batch(db, user.tenant_id, batch_id))
    except MergeBatchError as e:
        _raise(e)
        return


@router.post("/merge-batches/{batch_id}/cut-cards")
def merge_cut_cards(
    batch_id: int,
    body: MergeCutCardsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """B2h-R5b：合批批量开裁打主码（一次生成各成员捆标）。"""
    try:
        return ok(
            merge_batch_service.preview_or_create_merge_cut_cards(
                db,
                user.tenant_id,
                batch_id,
                dry_run=body.dry_run,
                bundle_size=body.bundle_size,
                only_missing=body.only_missing,
            )
        )
    except MergeBatchError as e:
        _raise(e)
        return


@router.get("/merge-batches/{batch_id}/trace-units")
def list_merge_trace_units(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """合批一页打印全员货上主码。"""
    try:
        return ok(merge_batch_service.list_merge_batch_trace_units(db, user.tenant_id, batch_id))
    except MergeBatchError as e:
        _raise(e)
        return
