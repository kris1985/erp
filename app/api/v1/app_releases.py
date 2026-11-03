"""手机按系统检查整包和热更新。不要求登录，旧版本在登录前也能更新。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.common import ok
from app.services.app_release_service import AppReleaseError, current_release

router = APIRouter(prefix="/app-releases", tags=["app-releases"])


@router.get("/current")
def api_current_app_release(
    platform: str = Query(default="android"),
    db: Session = Depends(get_db),
):
    try:
        data = current_release(db, platform)
    except AppReleaseError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return ok(data)
