"""租户库存模式：池唯一库存 + 分配 + 领料开关。

到货：receive_po 一律先入池，再按 auto_allocate_on_receive 自动分配到挂单行
（arrived_qty 为订单占用投影）。停单/改量释放走 release_from_order。
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

INVENTORY_MODEL = "pool_allocate"

DEFAULT_CAPABILITIES: dict[str, bool] = {
    "shared_pool": True,
    "allocate_ui": False,  # 高级「锁料」；默认关，日常走领料一步完成
    "stock_docs": True,  # 领/退料工作台默认开（支持多次领料）
    "issue_gate": False,
    "warehouse_dim": False,
}

DEFAULT_INVENTORY: dict[str, Any] = {
    "model": INVENTORY_MODEL,
    "auto_allocate_on_receive": True,
    "issue_required": False,
    # 过渡期：现网齐套仍可吃共用池；真·分配落地后默认改为 false
    "kit_include_unallocated_pool": True,
    "cost_basis": "po_received",
    "cutover_phase": "pool_allocate_live",  # migrating | pool_allocate_live
    "cutover_at": None,
    "capabilities": dict(DEFAULT_CAPABILITIES),
}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def default_inventory() -> dict[str, Any]:
    return deepcopy(DEFAULT_INVENTORY)


def merge_inventory(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    """合并租户覆盖，并按 issue_required 推导 capabilities / cost_basis。"""
    base = default_inventory()
    raw = _as_dict(stored)
    inv_in = _as_dict(raw.get("inventory") if "inventory" in raw else raw)

    out = deepcopy(base)
    for key in (
        "model",
        "auto_allocate_on_receive",
        "issue_required",
        "kit_include_unallocated_pool",
        "cost_basis",
        "cutover_phase",
        "cutover_at",
    ):
        if key in inv_in:
            out[key] = inv_in[key]

    out["model"] = INVENTORY_MODEL

    caps = dict(DEFAULT_CAPABILITIES)
    caps.update(_as_dict(inv_in.get("capabilities")))

    issue_required = bool(out.get("issue_required"))
    if issue_required:
        caps["stock_docs"] = True
        caps["issue_gate"] = True
        if "cost_basis" not in inv_in:
            out["cost_basis"] = "issued"
    else:
        # 不强制关领退料工作台；仅关报工闸门
        caps["issue_gate"] = False

    caps["shared_pool"] = True
    out["capabilities"] = caps
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_inventory_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_inventory(_as_dict(settings.get("inventory")) if settings else None)


def get_inventory_by_tenant_id(db: Session, tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_inventory_for_tenant(tenant)


def has_capability(inventory: dict[str, Any], code: str) -> bool:
    caps = _as_dict(inventory.get("capabilities"))
    return bool(caps.get(code))


def save_inventory_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    """合并写入 tenant.settings_json.inventory（仅允许白名单字段）。"""
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("inventory")))
    allowed = {
        "auto_allocate_on_receive",
        "issue_required",
        "kit_include_unallocated_pool",
        "cost_basis",
        "cutover_phase",
        "cutover_at",
        "capabilities",
    }
    for k, v in patch.items():
        if k in allowed:
            current[k] = v
    # issue_required 推导能力
    if "issue_required" in patch:
        caps = dict(DEFAULT_CAPABILITIES)
        caps.update(_as_dict(current.get("capabilities")))
        if current.get("issue_required"):
            caps["stock_docs"] = True
            caps["issue_gate"] = True
            if "cost_basis" not in patch:
                current["cost_basis"] = "issued"
        else:
            caps["issue_gate"] = False
            # 关闭强制领料时仍保留领退料工作台
            if "stock_docs" not in _as_dict(patch.get("capabilities")):
                caps["stock_docs"] = True
        current["capabilities"] = caps
    settings["inventory"] = current
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return get_inventory_for_tenant(tenant)
