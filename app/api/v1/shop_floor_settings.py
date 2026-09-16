"""租户车间执行配置 API（AU-I0）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal, require_permissions
from app.db import get_db
from app.models import Department, Employee, Tenant
from app.schemas.common import ok
from app.services import employee_process_service, shop_floor_settings, shop_floor_worker_service

router = APIRouter(prefix="/shop-floor-settings", tags=["shop-floor-settings"])


class ShopFloorPatchIn(BaseModel):
    allow_unassigned_bundle_report: bool | None = None
    stitch_leader_proxy_report: bool | None = None
    auto_basket_receive_on_first_action: bool | None = None
    require_basket_receive_before_stitch: bool | None = None
    basket_pairs_cutting: int | None = Field(default=None, ge=1)
    basket_pairs_forming: int | None = Field(default=None, ge=1)
    enable_skill_factor_split: bool | None = None
    kit_ready_qty_ratio: float | None = Field(default=None, gt=0)
    allow_direct_ship: bool | None = None


@router.get("")
def get_shop_floor_settings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    tenant = db.get(Tenant, principal.tenant_id)
    return ok(shop_floor_settings.get_shop_floor_for_tenant(tenant))


@router.get("/workers")
def list_shop_floor_workers(
    segment_code: str | None = None,
    process_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """现场代报/分活：在职工人短名单（工人与后台均可）。"""
    rows = shop_floor_worker_service.list_shop_floor_workers(
        db,
        principal.tenant_id,
        process_id=process_id,
        segment_code=segment_code,
    )
    role_map = shop_floor_worker_service.leader_role_map(
        db, principal.tenant_id, [w.id for w in rows]
    )
    department_names = {
        int(department.id): department.name
        for department in (
            [db.get(Department, department_id) for department_id in {int(w.department_id) for w in rows if w.department_id}]
        )
        if department and department.tenant_id == principal.tenant_id
    }
    return ok(
        [
            {
                "id": w.id,
                "name": w.name,
                "mobile": w.mobile,
                "role": role_map.get(w.id, "员工"),
                "department_name": department_names.get(int(w.department_id)) if w.department_id else None,
                "process_names": employee_process_service.list_names(db, w),
            }
            for w in rows
        ]
    )


@router.patch("")
def patch_shop_floor_settings(
    body: ShopFloorPatchIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.workshop_settings")),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(shop_floor_settings.save_shop_floor_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
