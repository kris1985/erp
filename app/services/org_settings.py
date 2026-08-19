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


def is_skiving_enabled(db: Session, tenant_id: int) -> bool:
    """铲皮工序段开关（6.2）：控制铲皮段是否在工艺路线中显示。"""
    return bool(get_org_settings(db, tenant_id).get("skiving_enabled", False))


def set_skiving_enabled(db: Session, tenant_id: int, enabled: bool) -> dict:
    """写入铲皮开关（6.3）。"""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    settings = get_org_settings(db, tenant_id)
    settings["skiving_enabled"] = bool(enabled)
    _save_org_settings(db, tenant, settings)
    db.commit()
    return {"skiving_enabled": bool(enabled)}


def enable_teams(db: Session, tenant_id: int) -> bool:
    """班组管理开关（6.4，D6）：默认 false（无班组模式）。"""
    return bool(get_org_settings(db, tenant_id).get("enable_teams", False))


def set_enable_teams(db: Session, tenant_id: int, enabled: bool) -> dict:
    """开启班组管理（6.5）：开启时对已有挂段部门 ensure 默认组（可见化）。

    单向升级（D12/37.1）：关闭视为隐藏默认组，不删数据；30 天冷静期内可回退（C4）。
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    if enabled:
        from app.models import Department
        from app.services.team_service import ensure_default_team_for_segment_departments

        depts = (
            db.query(Department)
            .filter(
                Department.tenant_id == tenant_id,
                Department.process_segment_id.is_not(None),
            )
            .all()
        )
        ensure_default_team_for_segment_departments(db, tenant_id, depts)
    settings = get_org_settings(db, tenant_id)
    settings["enable_teams"] = bool(enabled)
    _save_org_settings(db, tenant, settings)
    db.commit()
    return {"enable_teams": bool(enabled)}


def get_team_label(db: Session, tenant_id: int) -> str:
    """车间单位叫法（6.6，D5）：'班组'/'部'/'产线'/'班'；默认'班组'。"""
    label = get_org_settings(db, tenant_id).get("team_label", "班组")
    return label if label in ("班组", "部", "产线", "班") else "班组"


def set_team_label(db: Session, tenant_id: int, label: str) -> dict:
    """写入车间单位叫法（6.7）。"""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    settings = get_org_settings(db, tenant_id)
    settings["team_label"] = label if label in ("班组", "部", "产线", "班") else "班组"
    _save_org_settings(db, tenant, settings)
    db.commit()
    return {"team_label": settings["team_label"]}
