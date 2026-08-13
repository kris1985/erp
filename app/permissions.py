"""菜单 / 按钮级权限目录 + 角色默认授权。

权限树与后台侧栏生命周期分组对齐；租户可在库中覆盖角色授权（admin 始终全选）。
系统内置角色按职能划分；用户可绑定多个角色（权限取并集）。
"""

from __future__ import annotations

from typing import Any

# 系统内置角色。base_role 仅作 API 天花板（admin | manager），细权靠 permissions。
ROLES: list[dict] = [
    {
        "code": "admin",
        "name": "管理员",
        "description": "全厂配置与账号管理；权限固定为全部，不可削减",
        "base_role": "admin",
        "editable": False,
    },
    {
        "code": "manager",
        "name": "厂长",
        "description": "经营全貌：订单排产采购出货回款工资；不含系统账号配置",
        "base_role": "manager",
        "editable": True,
    },
    {
        "code": "merchandiser",
        "name": "跟单",
        "description": "客户、销售单、执行单与进度齐料；少碰财务锁账与仓管过账",
        "base_role": "manager",
        "editable": True,
    },
    {
        "code": "warehouse",
        "name": "采购仓管",
        "description": "缺料采购、库存池、锁料、出入库过账",
        "base_role": "manager",
        "editable": True,
    },
    {
        "code": "finance",
        "name": "财务",
        "description": "出货、应收回款、利润、工资锁定与导出",
        "base_role": "manager",
        "editable": True,
    },
    {
        "code": "workshop",
        "name": "车间主管",
        "description": "排产派工、报工纠错、不良、班组与员工现场管理",
        "base_role": "manager",
        "editable": True,
    },
]

# 权限树：code 为空表示仅分组节点（不可单独勾选存储，勾选会级联到子节点）
PERMISSION_TREE: list[dict[str, Any]] = [
    {
        "code": None,
        "name": "今日入口",
        "children": [
            {"code": "menu.board", "name": "工作台", "children": []},
            {
                "code": "menu.orders",
                "name": "执行单",
                "children": [
                    {"code": "btn.orders.write", "name": "建单/改单", "children": []},
                    {"code": "btn.orders.dispatch", "name": "派工", "children": []},
                    {"code": "btn.orders.rush", "name": "标急单", "children": []},
                    {"code": "btn.orders.import", "name": "批量导入", "children": []},
                ],
            },
            {
                "code": "menu.schedule",
                "name": "排产",
                "children": [
                    {"code": "btn.schedule.confirm", "name": "确认排产", "children": []},
                ],
            },
            {
                "code": "menu.material_shortages",
                "name": "缺料",
                "children": [
                    {"code": "btn.material_shortages.create_po", "name": "生成采购草稿", "children": []},
                ],
            },
            {
                "code": "menu.customer_supply",
                "name": "客供收货",
                "children": [
                    {"code": "btn.customer_supply.receive", "name": "登记到货", "children": []},
                    {"code": "btn.customer_supply.chase", "name": "催客户", "children": []},
                ],
            },
            {
                "code": "menu.customers",
                "name": "客户",
                "children": [
                    {"code": "btn.customers.write", "name": "新增/编辑", "children": []},
                ],
            },
        ],
    },
    {
        "code": None,
        "name": "主数据",
        "children": [
            {
                "code": "menu.suppliers",
                "name": "供应商",
                "children": [
                    {"code": "btn.suppliers.write", "name": "新增/编辑", "children": []},
                ],
            },
            {
                "code": "menu.supplier_products",
                "name": "物料色卡",
                "children": [
                    {"code": "btn.supplier_products.write", "name": "新增/编辑", "children": []},
                ],
            },
            {
                "code": "menu.own_products",
                "name": "产品开发",
                "children": [
                    {"code": "btn.own_products.write", "name": "新增/编辑", "children": []},
                ],
            },
            {
                "code": "menu.sales_orders",
                "name": "订单管理",
                "children": [
                    {"code": "btn.sales_orders.write", "name": "建单/确认", "children": []},
                ],
            },
        ],
    },
    {
        "code": None,
        "name": "采购备料",
        "children": [
            {
                "code": "menu.purchase_orders",
                "name": "采购单",
                "children": [
                    {"code": "btn.purchase_orders.write", "name": "提交/到货/拆分", "children": []},
                ],
            },
            {
                "code": "menu.shared_materials",
                "name": "库存池",
                "children": [
                    {"code": "btn.shared_materials.write", "name": "调整库存", "children": []},
                ],
            },
            {
                "code": "menu.fg_stocks",
                "name": "成品仓",
                "children": [],
            },
            {
                "code": "menu.stock_allocate",
                "name": "锁料（高级）",
                "children": [
                    {"code": "btn.stock_allocate.write", "name": "锁料/回收", "children": []},
                ],
            },
            {
                "code": "menu.stock_issues",
                "name": "出入库单",
                "children": [
                    {"code": "btn.stock_issues.submit", "name": "提报（车间）", "children": []},
                    {"code": "btn.stock_issues.confirm", "name": "确认过账（仓管）", "children": []},
                    {"code": "btn.stock_issues.write", "name": "提报+确认（兼容）", "children": []},
                ],
            },
        ],
    },
    {
        "code": None,
        "name": "车间",
        "children": [
            {
                "code": "menu.work_logs",
                "name": "报工",
                "children": [
                    {"code": "btn.work_logs.correct", "name": "纠错/作废", "children": []},
                ],
            },
            {"code": "menu.defects", "name": "不良", "children": []},
        ],
    },
    {
        "code": None,
        "name": "财务",
        "children": [
            {
                "code": "menu.shipments",
                "name": "出货",
                "children": [
                    {"code": "btn.shipments.write", "name": "开单/作废", "children": []},
                ],
            },
            {"code": "menu.receivables", "name": "应收", "children": []},
            {
                "code": "menu.payments",
                "name": "回款",
                "children": [
                    {"code": "btn.payments.write", "name": "登记回款", "children": []},
                ],
            },
            {"code": "menu.payables", "name": "应付", "children": []},
            {
                "code": "menu.supplier_payments",
                "name": "付款",
                "children": [
                    {"code": "btn.supplier_payments.write", "name": "登记付款", "children": []},
                ],
            },
            {"code": "menu.profit", "name": "利润", "children": []},
            {
                "code": "menu.salary",
                "name": "工资",
                "children": [
                    {"code": "btn.salary.export", "name": "导出", "children": []},
                ],
            },
        ],
    },
    {
        "code": None,
        "name": "人事",
        "children": [
            {
                "code": "menu.workers",
                "name": "员工",
                "children": [
                    {"code": "btn.workers.write", "name": "新增/编辑", "children": []},
                ],
            },
            {
                "code": "menu.teams",
                "name": "班组",
                "children": [
                    {"code": "btn.teams.write", "name": "新增/编辑", "children": []},
                ],
            },
        ],
    },
    {
        "code": None,
        "name": "系统",
        "children": [
            {
                "code": "menu.users",
                "name": "用户",
                "children": [
                    {"code": "btn.users.write", "name": "新增/编辑/启停", "children": []},
                ],
            },
            {
                "code": "menu.roles",
                "name": "角色",
                "children": [
                    {"code": "btn.roles.write", "name": "编辑权限", "children": []},
                    {"code": "menu.permissions", "name": "权限矩阵", "children": []},
                ],
            },
            {
                "code": "menu.masters",
                "name": "基础资料",
                "children": [
                    {"code": "btn.masters.write", "name": "维护", "children": []},
                ],
            },
            {
                "code": "menu.stations",
                "name": "工位码",
                "children": [
                    {"code": "btn.stations.write", "name": "维护工位", "children": []},
                ],
            },
            {"code": "menu.inventory_settings", "name": "库存模式", "children": []},
            {"code": "menu.workshop_settings", "name": "报工规则", "children": []},
            {"code": "menu.im_alerts", "name": "IM 预警推送", "children": []},
            {"code": "menu.mcp_keys", "name": "MCP 密钥", "children": []},
        ],
    },
]

# 默认授权（admin 不写入，运行时恒为全部）
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "manager": [
        "menu.board",
        "menu.customers",
        "btn.customers.write",
        "menu.sales_orders",
        "btn.sales_orders.write",
        "menu.orders",
        "btn.orders.write",
        "btn.orders.dispatch",
        "btn.orders.rush",
        "btn.orders.import",
        "menu.schedule",
        "btn.schedule.confirm",
        "menu.material_shortages",
        "btn.material_shortages.create_po",
        "menu.customer_supply",
        "btn.customer_supply.receive",
        "btn.customer_supply.chase",
        "menu.suppliers",
        "btn.suppliers.write",
        "menu.supplier_products",
        "btn.supplier_products.write",
        "menu.own_products",
        "btn.own_products.write",
        "menu.purchase_orders",
        "btn.purchase_orders.write",
        "menu.shared_materials",
        "btn.shared_materials.write",
        "menu.fg_stocks",
        "menu.stock_allocate",
        "btn.stock_allocate.write",
        "menu.stock_issues",
        "btn.stock_issues.submit",
        "btn.stock_issues.confirm",
        "btn.stock_issues.write",
        "menu.work_logs",
        "btn.work_logs.correct",
        "menu.defects",
        "menu.stations",
        "btn.stations.write",
        "menu.shipments",
        "btn.shipments.write",
        "menu.receivables",
        "menu.payments",
        "btn.payments.write",
        "menu.payables",
        "menu.supplier_payments",
        "btn.supplier_payments.write",
        "menu.profit",
        "menu.workers",
        "btn.workers.write",
        "menu.teams",
        "btn.teams.write",
        "menu.salary",
        "btn.salary.export",
        "menu.masters",
        "btn.masters.write",
        "menu.workshop_settings",
    ],
    "merchandiser": [
        "menu.board",
        "menu.customers",
        "btn.customers.write",
        "menu.sales_orders",
        "btn.sales_orders.write",
        "menu.orders",
        "btn.orders.write",
        "btn.orders.rush",
        "btn.orders.import",
        "menu.schedule",
        "menu.material_shortages",
        "menu.customer_supply",
        "btn.customer_supply.receive",
        "btn.customer_supply.chase",
        "menu.own_products",
        "menu.suppliers",
        "menu.supplier_products",
        "menu.purchase_orders",
        "menu.fg_stocks",
        "menu.shipments",
        "menu.receivables",
        "menu.masters",
    ],
    "warehouse": [
        "menu.board",
        "menu.suppliers",
        "btn.suppliers.write",
        "menu.supplier_products",
        "btn.supplier_products.write",
        "menu.material_shortages",
        "btn.material_shortages.create_po",
        "menu.customer_supply",
        "btn.customer_supply.receive",
        "btn.customer_supply.chase",
        "menu.purchase_orders",
        "btn.purchase_orders.write",
        "menu.shared_materials",
        "btn.shared_materials.write",
        "menu.fg_stocks",
        "menu.stock_allocate",
        "btn.stock_allocate.write",
        "menu.stock_issues",
        "btn.stock_issues.submit",
        "btn.stock_issues.confirm",
        "btn.stock_issues.write",
        "menu.orders",
        "menu.own_products",
        "menu.masters",
        "btn.masters.write",
    ],
    "finance": [
        "menu.board",
        "menu.customers",
        "menu.sales_orders",
        "menu.orders",
        "menu.fg_stocks",
        "menu.shipments",
        "btn.shipments.write",
        "menu.receivables",
        "menu.payments",
        "btn.payments.write",
        "menu.payables",
        "menu.supplier_payments",
        "btn.supplier_payments.write",
        "menu.profit",
        "menu.salary",
        "btn.salary.export",
        "menu.workers",
    ],
    "workshop": [
        "menu.board",
        "menu.orders",
        "btn.orders.write",
        "btn.orders.dispatch",
        "btn.orders.rush",
        "menu.schedule",
        "btn.schedule.confirm",
        "menu.material_shortages",
        "menu.own_products",
        "menu.stock_issues",
        "btn.stock_issues.submit",
        "menu.work_logs",
        "btn.work_logs.correct",
        "menu.defects",
        "menu.stations",
        "btn.stations.write",
        "menu.workers",
        "btn.workers.write",
        "menu.teams",
        "btn.teams.write",
        "menu.salary",
        "menu.masters",
        "btn.masters.write",
        "menu.workshop_settings",
    ],
}

# 选主角色用的优先级（多角色时 users.role 同步为此）
PRIMARY_ROLE_PRIORITY: list[str] = [
    "admin",
    "manager",
    "workshop",
    "merchandiser",
    "warehouse",
    "finance",
]


def _walk(nodes: list[dict], acc: list[dict] | None = None) -> list[dict]:
    acc = acc if acc is not None else []
    for n in nodes:
        code = n.get("code")
        if code:
            acc.append({"code": code, "name": n["name"]})
        children = n.get("children") or []
        if children:
            _walk(children, acc)
    return acc


def all_permission_codes() -> list[str]:
    return [p["code"] for p in _walk(PERMISSION_TREE)]


def permission_catalog() -> list[dict]:
    """扁平目录（含模块路径名）。"""
    out: list[dict] = []

    def walk(nodes: list[dict], module: str) -> None:
        for n in nodes:
            code = n.get("code")
            name = n["name"]
            children = n.get("children") or []
            if code is None:
                walk(children, name)
                continue
            out.append(
                {
                    "code": code,
                    "name": name,
                    "module": module or name,
                    "kind": "menu" if str(code).startswith("menu.") else "button",
                }
            )
            walk(children, module or name)

    walk(PERMISSION_TREE, "")
    return out


def permission_tree_for_ui() -> list[dict]:
    """给前端 el-tree 用：每个节点有唯一 id。"""

    def convert(nodes: list[dict], prefix: str) -> list[dict]:
        result = []
        for i, n in enumerate(nodes):
            code = n.get("code")
            nid = code or f"group:{prefix}{i}:{n['name']}"
            children = n.get("children") or []
            result.append(
                {
                    "id": nid,
                    "code": code,
                    "label": n["name"],
                    "is_group": code is None,
                    "children": convert(children, f"{prefix}{i}-") if children else [],
                }
            )
        return result

    return convert(PERMISSION_TREE, "")


def default_permissions_for_role(role: str) -> list[str]:
    if role == "admin":
        return all_permission_codes()
    return list(DEFAULT_ROLE_PERMISSIONS.get(role, []))


def role_meta(role: str) -> dict | None:
    for r in ROLES:
        if r["code"] == role:
            return r
    return None


def pick_primary_role(role_codes: list[str]) -> str:
    codes = [c for c in role_codes if c]
    if not codes:
        return "manager"
    for p in PRIMARY_ROLE_PRIORITY:
        if p in codes:
            return p
    return codes[0]
