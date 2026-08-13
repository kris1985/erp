"""租户车间执行配置 API（AU-I0）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Tenant, User
from app.schemas.common import ok
from app.services import shop_floor_settings

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
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    tenant = db.get(Tenant, user.tenant_id)
    return ok(shop_floor_settings.get_shop_floor_for_tenant(tenant))


@router.patch("")
def patch_shop_floor_settings(
    body: ShopFloorPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(shop_floor_settings.save_shop_floor_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
