"""租户排产规则：默认工期、粗产能（工序/天）、风险阈值。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_SCHEDULE: dict[str, Any] = {
    # 工序未配置 default_days 时的回退工期（工作日）
    "default_process_days": 1,
    # 完工日相对交期：差 <= tight_days 标 tight，超过标 late
    "tight_days": 2,
    # 工序日产能：{ "12": 800 } process_id -> 双/天；空则不做产能硬阻断（仅负荷展示）
    "daily_capacity_by_process": {},
    # 全局兜底日产能（双/天）；None 表示不限制
    "default_daily_capacity": None,
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def default_schedule() -> dict[str, Any]:
    return deepcopy(DEFAULT_SCHEDULE)


def merge_schedule(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = default_schedule()
    raw = _as_dict(stored)
    src = _as_dict(raw.get("schedule") if "schedule" in raw else raw)

    if "default_process_days" in src:
        try:
            out["default_process_days"] = max(1, int(src["default_process_days"]))
        except (TypeError, ValueError):
            pass
    if "tight_days" in src:
        try:
            out["tight_days"] = max(0, int(src["tight_days"]))
        except (TypeError, ValueError):
            pass
    if "default_daily_capacity" in src:
        v = src["default_daily_capacity"]
        if v is None or v == "":
            out["default_daily_capacity"] = None
        else:
            try:
                out["default_daily_capacity"] = max(0, int(v))
            except (TypeError, ValueError):
                pass
    cap = src.get("daily_capacity_by_process")
    if isinstance(cap, dict):
        cleaned: dict[str, int] = {}
        for k, v in cap.items():
            try:
                cleaned[str(int(k))] = max(0, int(v))
            except (TypeError, ValueError):
                continue
        out["daily_capacity_by_process"] = cleaned
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_schedule_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_schedule(_as_dict(settings.get("schedule")) if settings else None)


def get_schedule_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_schedule_for_tenant(tenant)


def save_schedule_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("schedule")))
    for key in (
        "default_process_days",
        "tight_days",
        "default_daily_capacity",
        "daily_capacity_by_process",
    ):
        if key in patch:
            current[key] = patch[key]
    settings["schedule"] = merge_schedule(current)
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.commit()
    db.refresh(tenant)
    return get_schedule_for_tenant(tenant)


def capacity_for_process(cfg: dict[str, Any], process_id: int) -> int | None:
    """返回工序日产能（双）；None=不限制。"""
    by = cfg.get("daily_capacity_by_process") or {}
    key = str(int(process_id))
    if key in by:
        return int(by[key])
    v = cfg.get("default_daily_capacity")
    if v is None:
        return None
    return int(v)


def capacity_is_configured(cfg: dict[str, Any] | None) -> bool:
    """是否已配置可用日产能（>0）。未配置时排产仅按交期/工期，不校验产能。"""
    if not cfg:
        return False
    by = cfg.get("daily_capacity_by_process") or {}
    for v in by.values():
        try:
            if int(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    v = cfg.get("default_daily_capacity")
    if v is None or v == "":
        return False
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False

