"""A2d：IM 预警推送 + 进度日报 —— 设置 + 预览 + 试发（只推不改）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Tenant, User
from app.schemas.common import ok
from app.services import im_alerts_service

router = APIRouter(tags=["im-alerts"])


class ImAlertsPatchIn(BaseModel):
    webhook_url: str | None = None
    enabled: bool | None = None
    events: list[str] | None = None


class ImAlertsTestSendIn(BaseModel):
    kind: str = "alert"
    webhook_url: str | None = None


@router.get("/im-alerts-settings")
def get_im_alerts_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    tenant = db.get(Tenant, user.tenant_id)
    return ok(im_alerts_service.get_im_alerts_for_tenant(tenant))


@router.patch("/im-alerts-settings")
def patch_im_alerts_settings(
    body: ImAlertsPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(im_alerts_service.save_im_alerts_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/ops/im-alerts/preview")
def get_im_alerts_preview(
    kind: str = "alert",
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    tenant = db.get(Tenant, user.tenant_id)
    settings = im_alerts_service.get_im_alerts_for_tenant(tenant)
    payload = (
        im_alerts_service.build_daily_digest(db, user.tenant_id)
        if kind == "digest"
        else im_alerts_service.build_alert_payload(db, user.tenant_id)
    )
    return ok({"settings": settings, "kind": payload.get("kind", kind), "payload": payload})


@router.post("/ops/im-alerts/test-send")
def post_im_alerts_test_send(
    body: ImAlertsTestSendIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        result = im_alerts_service.send_test(
            db,
            user.tenant_id,
            kind=body.kind,
            webhook_url_override=body.webhook_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ok(result)
