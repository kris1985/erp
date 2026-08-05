"""租户库存模式与对账。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Tenant, User
from app.schemas.common import ok
from app.services import inventory_settings, material_service

router = APIRouter(prefix="/inventory-settings", tags=["inventory-settings"])


class InventoryPatchIn(BaseModel):
    kit_include_unallocated_pool: bool | None = None
    auto_allocate_on_receive: bool | None = None
    issue_required: bool | None = None
    mark_cutover: bool | None = Field(
        default=None,
        description="true 时写入 cutover_phase=pool_allocate_live 与 cutover_at",
    )


@router.get("")
def get_inventory_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    tenant = db.get(Tenant, user.tenant_id)
    return ok(inventory_settings.get_inventory_for_tenant(tenant))


@router.get("/reconcile")
def get_stock_reconcile(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    return ok(material_service.stock_reconcile_report(db, user.tenant_id))


@router.patch("")
def patch_inventory_settings(
    body: InventoryPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    patch: dict = {}
    data = body.model_dump(exclude_unset=True)
    if "kit_include_unallocated_pool" in data:
        patch["kit_include_unallocated_pool"] = data["kit_include_unallocated_pool"]
    if "auto_allocate_on_receive" in data:
        patch["auto_allocate_on_receive"] = data["auto_allocate_on_receive"]
    if "issue_required" in data:
        patch["issue_required"] = data["issue_required"]
        if data["issue_required"]:
            patch["cost_basis"] = "issued"
    if data.get("mark_cutover"):
        patch["cutover_phase"] = "pool_allocate_live"
        patch["cutover_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(inventory_settings.save_inventory_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
