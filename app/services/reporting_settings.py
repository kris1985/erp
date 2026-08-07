"""租户报工规则：未派是否可报、返修是否计薪、超计划确认。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_REPORTING: dict[str, Any] = {
    # 工序无人派工时，是否允许任意人报工（现网默认允许）
    "allow_unassigned_report": True,
    # 返修报工是否计入计件工资（现网默认计薪）
    "rework_pays": True,
    # 是否允许超额报工（关闭后即使 confirm 也不放行）
    "allow_over_plan": True,
    # 超额时报工是否需要二次确认（关闭且 allow_over_plan=true 时直接放行）
    "over_plan_requires_confirm": True,
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def default_reporting() -> dict[str, Any]:
    return deepcopy(DEFAULT_REPORTING)


def merge_reporting(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = default_reporting()
    raw = _as_dict(stored)
    src = _as_dict(raw.get("reporting") if "reporting" in raw else raw)
    for key in DEFAULT_REPORTING:
        if key in src:
            out[key] = bool(src[key])
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_reporting_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_reporting(_as_dict(settings.get("reporting")) if settings else None)


def get_reporting_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_reporting_for_tenant(tenant)


def save_reporting_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("reporting")))
    for key in DEFAULT_REPORTING:
        if key in patch:
            current[key] = bool(patch[key])
    settings["reporting"] = merge_reporting(current)
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.commit()
    db.refresh(tenant)
    return get_reporting_for_tenant(tenant)
