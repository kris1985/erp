"""组织配置（tenant.settings_json.org）：多产线开关等。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Tenant


def _as_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            import json

            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def get_org_settings(db: Session, tenant_id: int) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return {}
    return dict(_as_dict(getattr(tenant, "settings_json", None)).get("org", {}) or {})


def _save_org_settings(db: Session, tenant: Tenant, settings: dict) -> None:
    full = _as_dict(getattr(tenant, "settings_json", None))
    full["org"] = settings
    tenant.settings_json = full
    flag_modified(tenant, "settings_json")


def enable_production_lines(db: Session, tenant_id: int) -> bool:
    """多产线开关：默认关闭（单产线，班组挂部门）。"""
    return bool(get_org_settings(db, tenant_id).get("enable_production_lines", False))


def set_enable_production_lines(db: Session, tenant_id: int, enabled: bool) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    settings = get_org_settings(db, tenant_id)
    settings["enable_production_lines"] = bool(enabled)
    _save_org_settings(db, tenant, settings)
    db.commit()
    return {"enable_production_lines": bool(enabled)}
