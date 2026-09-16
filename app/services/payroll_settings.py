"""租户发薪配置：发薪日（默认每月 10 号）。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_PAYROLL: dict[str, Any] = {
    # 每月几号发上个自然月工资
    "payday": 10,
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def default_payroll() -> dict[str, Any]:
    return deepcopy(DEFAULT_PAYROLL)


def merge_payroll(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = default_payroll()
    src = _as_dict(stored)
    raw = _as_dict(src.get("payroll") if "payroll" in src else src)
    if "payday" in raw:
        try:
            day = int(raw["payday"])
            if 1 <= day <= 28:
                out["payday"] = day
        except (TypeError, ValueError):
            pass
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_payroll_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_payroll(_as_dict(settings.get("payroll")) if settings else None)


def get_payroll_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_payroll_for_tenant(tenant)


def save_payroll_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("payroll")))
    if "payday" in patch:
        day = int(patch["payday"])
        if not (1 <= day <= 28):
            raise ValueError("payday_invalid")
        current["payday"] = day
    settings["payroll"] = merge_payroll(current)
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.commit()
    db.refresh(tenant)
    return get_payroll_for_tenant(tenant)
