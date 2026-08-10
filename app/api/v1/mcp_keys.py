"""管理端：创建 / 列出 / 吊销对外 MCP API Key。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.mcp.scopes import MCP_SERVERS
from app.models import User
from app.schemas.common import ok
from app.services import mcp_keys
from app.services.mcp_keys import McpKeyError

router = APIRouter(prefix="/mcp-keys", tags=["mcp-keys"])


class McpKeyCreate(BaseModel):
    name: str = Field(default="MCP Key", max_length=100)
    scopes: list[str] = Field(default_factory=lambda: list(MCP_SERVERS))
    expires_at: datetime | None = None


def _http(e: McpKeyError) -> HTTPException:
    status = 404 if e.code == "not_found" else 400
    return HTTPException(status_code=status, detail=e.message)


@router.get("")
def api_list_mcp_keys(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    items = mcp_keys.list_keys(db, user.tenant_id, include_inactive=include_inactive)
    return ok({"items": items, "total": len(items), "servers": list(MCP_SERVERS)})


@router.post("")
def api_create_mcp_key(
    body: McpKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        row, raw = mcp_keys.create_key(
            db,
            user.tenant_id,
            name=body.name,
            scopes=body.scopes,
            created_by=user.id,
            expires_at=body.expires_at,
        )
    except McpKeyError as e:
        raise _http(e) from e
    data = mcp_keys.serialize_key(row)
    data["api_key"] = raw  # 仅此一次
    data["hint"] = "请立即保存 api_key；服务端只存哈希，无法再次查看明文"
    return ok(data)


@router.delete("/{key_id}")
def api_revoke_mcp_key(
    key_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        row = mcp_keys.revoke_key(db, user.tenant_id, key_id)
    except McpKeyError as e:
        raise _http(e) from e
    return ok(row)
