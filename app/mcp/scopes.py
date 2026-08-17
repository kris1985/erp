"""四个对外 MCP Server 的能力面与指标白名单。"""

from __future__ import annotations

from typing import Any, Literal

ServerId = Literal["intake", "schedule", "supply", "ops"]

MCP_SERVERS: tuple[ServerId, ...] = ("intake", "schedule", "supply", "ops")

SERVER_META: dict[ServerId, dict[str, str]] = {
    "intake": {
        "name": "erp-intake",
        "title": "接单参谋",
        "description": "销售/老板侧：接单冲击诊断（毛利/缺料/交期/争料/回款）。只读，不确认生产。",
    },
    "schedule": {
        "name": "erp-schedule",
        "title": "排产参谋",
        "description": "PMC：待排池、负荷、规则方案、插单仿真、齐套可排。只读，不确认草稿。",
    },
    "supply": {
        "name": "erp-supply",
        "title": "齐套供应链",
        "description": "采购/PMC：缺料、在途 PO、共享池、供应链诊断。只读，不下采购单。",
    },
    "ops": {
        "name": "erp-ops",
        "title": "厂务简报",
        "description": "厂长/老板：今日 3 件事、进度风险、产量、质量人效、周月简报与经营 KPI。只读。",
    },
}

# 各 Server 可查的 metric_id（与 workshop_metrics.METRIC_CATALOG 对齐）
SERVER_METRICS: dict[ServerId, frozenset[str]] = {
    "intake": frozenset({"analytics.order_intake"}),
    "schedule": frozenset(
        {
            "schedule.daily_load",
            "analytics.kit_ready",
            "analytics.capacity_load",
        }
    ),
    "supply": frozenset(
        {
            "materials.shortages",
            "purchase.open_pos",
            "inventory.shared_pool",
            "analytics.supply_chain",
        }
    ),
    "ops": frozenset(
        {
            "production.today_output",
            "production.order_progress",
            "production.open_orders_board",
            "production.late_rush_orders",
            "production.process_bottlenecks",
            "analytics.delivery_risk",
            "analytics.today_actions",
            "analytics.quality_hotspots",
            "analytics.quality_alerts",
            "analytics.labor_efficiency",
            "analytics.salary_cost_reconcile",
            "analytics.weekly_brief",
            "analytics.monthly_brief",
            "analytics.finance_health",
            "finance.receivables_open",
            "finance.payments_this_month",
            "finance.profit_report",
            "finance.business_kpi",
        }
    ),
}

# 查询指标时注入的权限码（MCP Key 代替用户，按 Server 放开所需菜单权限）
SERVER_PERMISSIONS: dict[ServerId, list[str]] = {
    "intake": ["menu.sales_orders"],
    "schedule": ["menu.schedule", "menu.orders"],
    "supply": ["menu.material_shortages", "menu.purchase_orders", "menu.shared_materials"],
    "ops": [
        "menu.orders",
        "menu.schedule",
        "menu.work_logs",
        "menu.salary",
        "menu.profit",
        "menu.receivables",
        "menu.payments",
    ],
}

# schedule Server 额外只读工具（非 metric）
SCHEDULE_EXTRA_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_schedule_pool",
        "description": "查看待排池订单（含齐套、优先级）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hide_scheduled": {"type": "boolean", "default": True},
                "hide_first_kit_blocked": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "get_schedule_settings",
        "description": "读取租户排产规则：默认工期、粗产能、风险阈值。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_daily_load",
        "description": "查看从今天起 N 天的工序日负荷与瓶颈。",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 14, "minimum": 1, "maximum": 60}},
        },
    },
    {
        "name": "generate_schedule_proposals",
        "description": "用规则引擎生成 2～3 套排产方案（含风险）。可指定 order_ids，否则用待排池。不落库。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "生产单 id 列表；空则用待排池",
                }
            },
        },
    },
    {
        "name": "simulate_insert_order",
        "description": "插单仿真：返回保交期/保现场/折中三套方案及影响清单。不落库。",
        "inputSchema": {
            "type": "object",
            "required": ["order_id"],
            "properties": {"order_id": {"type": "integer", "description": "要插入的生产单 id"}},
        },
    },
]


def is_valid_server(server: str) -> bool:
    return server in MCP_SERVERS


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    raw = [str(s).strip().lower() for s in (scopes or []) if str(s).strip()]
    if "*" in raw or "all" in raw:
        return list(MCP_SERVERS)
    out: list[str] = []
    for s in raw:
        if s in MCP_SERVERS and s not in out:
            out.append(s)
    return out


def key_allows_server(scopes: list[str] | None, server: ServerId) -> bool:
    allowed = normalize_scopes(list(scopes or []))
    return server in allowed
