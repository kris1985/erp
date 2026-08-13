"""租户车间执行配置（AU-I0：筐/捆 / 收料 / 代报 / 技能拆分）。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_SHOP_FLOOR: dict[str, Any] = {
    "allow_unassigned_bundle_report": False,
    "stitch_leader_proxy_report": True,
    "auto_basket_receive_on_first_action": True,
    "require_basket_receive_before_stitch": False,
    "basket_pairs_cutting": 40,
    "basket_pairs_forming": 24,
    "enable_skill_factor_split": True,
    "kit_ready_qty_ratio": 1.0,
    # AU-I2：急单可在筐完工时直接出货；默认仍须先入库。
    "allow_direct_ship": False,
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def default_shop_floor() -> dict[str, Any]:
    return deepcopy(DEFAULT_SHOP_FLOOR)


def merge_shop_floor(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    base = default_shop_floor()
    raw = _as_dict(stored)
    sf_in = _as_dict(raw.get("shop_floor") if "shop_floor" in raw else raw)
    out = deepcopy(base)
    for key in DEFAULT_SHOP_FLOOR:
        if key in sf_in:
            out[key] = sf_in[key]
    # 数值兜底
    for int_key in ("basket_pairs_cutting", "basket_pairs_forming"):
        try:
            out[int_key] = max(1, int(out[int_key]))
        except (TypeError, ValueError):
            out[int_key] = DEFAULT_SHOP_FLOOR[int_key]
    try:
        out["kit_ready_qty_ratio"] = float(out["kit_ready_qty_ratio"])
    except (TypeError, ValueError):
        out["kit_ready_qty_ratio"] = 1.0
    for bool_key in (
        "allow_unassigned_bundle_report",
        "stitch_leader_proxy_report",
        "auto_basket_receive_on_first_action",
        "require_basket_receive_before_stitch",
        "enable_skill_factor_split",
        "allow_direct_ship",
    ):
        out[bool_key] = bool(out[bool_key])
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    return _as_dict(getattr(tenant, "settings_json", None) if tenant else None)


def get_shop_floor_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_shop_floor(_as_dict(settings.get("shop_floor")) if settings else None)


def get_shop_floor_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_shop_floor_for_tenant(tenant)


def save_shop_floor_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    settings = dict(_as_dict(tenant.settings_json))
    current = merge_shop_floor(_as_dict(settings.get("shop_floor")))
    for key, value in patch.items():
        if key in DEFAULT_SHOP_FLOOR:
            current[key] = value
    settings["shop_floor"] = merge_shop_floor(current)
    tenant.settings_json = settings
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return get_shop_floor_for_tenant(tenant)
