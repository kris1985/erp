"""MCP API Key：创建、校验、吊销。"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mcp.scopes import MCP_SERVERS, normalize_scopes
from app.models import McpApiKey


class McpKeyError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_raw_key() -> str:
    # mcp_ + 40 hex ≈ 43 chars；前缀便于日志脱敏
    return f"mcp_{secrets.token_hex(20)}"


def _prefix_of(raw: str) -> str:
    return (raw or "")[:12]


@dataclass
class VerifiedMcpKey:
    id: int
    tenant_id: int
    name: str
    scopes: list[str]


def create_key(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    scopes: list[str],
    created_by: int | None = None,
    expires_at: datetime | None = None,
) -> tuple[McpApiKey, str]:
    normalized = normalize_scopes(scopes)
    if not normalized:
        raise McpKeyError("invalid_scopes", f"scopes 须为 {', '.join(MCP_SERVERS)} 之一，或 *")
    raw = _new_raw_key()
    prefix = _prefix_of(raw)
    # 极低概率前缀冲突时重试
    for _ in range(5):
        exists = db.scalar(
            select(McpApiKey.id).where(
                McpApiKey.tenant_id == tenant_id,
                McpApiKey.key_prefix == prefix,
            )
        )
        if not exists:
            break
        raw = _new_raw_key()
        prefix = _prefix_of(raw)
    else:
        raise McpKeyError("key_collision", "无法生成唯一 Key，请重试")

    row = McpApiKey(
        tenant_id=tenant_id,
        name=(name or "").strip()[:100] or "MCP Key",
        key_prefix=prefix,
        key_hash=_hash_key(raw),
        scopes=normalized,
        is_active=True,
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def list_keys(db: Session, tenant_id: int, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    q = select(McpApiKey).where(McpApiKey.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(McpApiKey.is_active.is_(True))
    q = q.order_by(McpApiKey.id.desc())
    rows = list(db.scalars(q).all())
    return [serialize_key(r) for r in rows]


def revoke_key(db: Session, tenant_id: int, key_id: int) -> dict[str, Any]:
    row = db.get(McpApiKey, key_id)
    if not row or row.tenant_id != tenant_id:
        raise McpKeyError("not_found", "Key 不存在")
    row.is_active = False
    db.commit()
    db.refresh(row)
    return serialize_key(row)


def verify_bearer(db: Session, token: str) -> VerifiedMcpKey:
    raw = (token or "").strip()
    if not raw.startswith("mcp_"):
        raise McpKeyError("invalid_token", "无效 API Key")
    prefix = _prefix_of(raw)
    digest = _hash_key(raw)
    rows = list(
        db.scalars(
            select(McpApiKey).where(
                McpApiKey.key_prefix == prefix,
                McpApiKey.is_active.is_(True),
            )
        ).all()
    )
    row: Optional[McpApiKey] = None
    for cand in rows:
        if cand.key_hash == digest:
            row = cand
            break
    if row is None:
        raise McpKeyError("invalid_token", "无效 API Key")
    if row.expires_at is not None:
        exp = row.expires_at
        if exp.tzinfo is None:
            now = datetime.utcnow()
            if exp < now:
                raise McpKeyError("expired", "API Key 已过期")
        else:
            if exp < datetime.now(timezone.utc):
                raise McpKeyError("expired", "API Key 已过期")
    row.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return VerifiedMcpKey(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        scopes=list(row.scopes or []),
    )


def serialize_key(row: McpApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "scopes": list(row.scopes or []),
        "is_active": bool(row.is_active),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
