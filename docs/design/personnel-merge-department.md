# 员工/用户合并 + 部门管理（人事主档重构）

> 状态：已实施（2025-08，开发阶段无真实数据时落地）

## 背景与决策

原系统存在两张平行人员表：

- `users`：后台登录账号（用户名/密码/RBAC 角色/可空 `worker_id` 关联员工）
- `workers`：员工档案（姓名/手机/微信/工种/计薪/银行代发/密码——**本身可登录**，报工端）

两者字段大量重复（password_hash、wechat_unionid、is_active），同一人需维护两条记录，鉴权为双主体（`get_current_user` / `get_current_worker`，token `typ` 区分）。

**决策：合并为单一「员工/人员」实体 `employees`，账号是员工的可选属性。**

理由（开发阶段、无真实数据，合并成本最低）：

1. 每个领工资的人都是一条员工档案（生产工人、办公室、老板均在表内，办公室用 `salary_model=fixed`）；
2. 登录账号（username/password）可空：纯工人无账号也能微信报工；老板/财务一人一条记录既管后台又算工资；
3. 生命周期用软删除 + 可空账号字段化解：离职 = `is_active=false`，历史报工/工资靠外键保留；
4. 部门挂载问题自动消失：部门只挂员工。

## 数据模型

```text
employees                          departments
├─ 身份: name, mobile,             ├─ name, parent_id(树)
│   wechat_openid/unionid          ├─ manager_employee_id → employees（主管，一人可兼多部门）
├─ 账号(可空): username(租户内唯一), ├─ ext_source/ext_dept_id（企微/钉钉组织同步预留）
│   password_hash, must_change_password
├─ 组织: department_id → departments,
│   position_id → positions（班组走 team_members 不变）
├─ 生产角色: role (worker/leader)   employee_roles（原 user_roles）
├─ 计薪: salary_model/base_salary/ ├─ employee_id, role_code（后台 RBAC 多角色，权限并集）
│   base_quota/skill_factor
├─ 银行代发: bank_*                tenants.corpid（企微，已有）
└─ 预留: ext_source/ext_user_id
```

- 唯一约束：`(tenant_id, username)`、`(tenant_id, ext_source, ext_user_id)`（同步幂等）
- 所有原指向 workers.id / users.id 的外键统一指向 employees.id（列名保留，如 `assigned_worker_id`、`created_by`，减少迁移面）

## 鉴权（单主体）

- 唯一 token（`typ=employee`），`get_current_employee` 为唯一依赖；`get_current_user` / `get_current_worker` 为兼容别名
- RBAC：`employee_roles` 决定后台权限；`require_roles` 校验；无任何后台角色的员工 `base_role=""`（纯生产员工）
- `Principal.is_staff` = 无后台角色 → 只能访问自己的报工/数据（原 worker-kind 语义）

## 多租户登录选择

一个自然人在多家厂各有一条员工档案（租户隔离不变量不变：token 带 tenant_id）。

```
POST /auth/login {identifier, password}    # identifier = 用户名或手机号
  ├─ 命中 0 → 401
  ├─ 命中 1 → 直接发 token
  └─ 命中 N → {need_select, tenants:[{tenant_id, tenant_name}]}
POST /auth/login/select {identifier, password, tenant_id} → 发该租户 token
```

- 密码按租户独立；改密只影响当前租户
- 以后做「厂区切换」= 同凭证重新走 select，无需新接口

## API

- `GET/POST /employees`、`PATCH /employees/{id}`：档案+账号+角色一体 CRUD；`department_id` 筛选**含子部门**；兼容别名 `/workers`
- `GET/POST /departments`、`PATCH /departments/{id}`：部门树（parent_id 防环）、主管（manager_employee_id）、停用守卫（有在职员工/子部门不可停用）、`employee_count`
- `GET /auth/me`：合并后的员工画像（含部门/职位/角色/权限）

## 前端

- 登录页：单登录框（用户名或手机号 + 密码）→ 多工厂命中时二次选择工厂
- 员工管理页 `/admin/employees`：**左部门树（含主管/人数/增删改停用）右员工列表**（筛选：关键词/部门/职位/生产角色/有无账号/状态；编辑弹窗分 基本信息 / 计薪 / 登录账号 三区）
- 路由/导航：删除「用户」菜单，「员工」指向新页；`actor` 概念移除 → `isPureStaff`（无后台角色）决定生产端/后台端 UI
- 生产端扫码/报工/组长功能按生产角色（leader）放行，不再按登录入口区分

## 生产组织：去掉二元生产角色，班组挂部门/产线（可配置）

- **删除 `Employee.role`（worker/leader 二元字段）**：工人是默认态；**组长身份从班组关系推导**
  （`team_service.is_leader(db, employee)` = 是否为某启用班组的 `leader_worker_id`）；
  工种用 `Position`；后台权限用角色
- **新增 `production_lines` 表**（tenant/name/department_id/sort_order/is_active）；
  `Team` 增加 `department_id` / `production_line_id`（二选一挂载）
- **多产线开关**（tenant.settings_json.org.enable_production_lines，默认关闭）：
  - 关闭（单产线）：班组挂部门，界面无产线概念
  - 开启：班组挂产线（产线挂部门），界面出现"产线管理"
- API：`/production-lines` CRUD + `/production-lines/config`（GET/PUT 开关）；
  登录/`/auth/me` 返回 `is_leader`（不再返回 role=leader/worker）
- 前端：员工页/表单去掉"生产角色"；班组页按开关显示"所属部门/产线"+产线管理；
  组长相关判断（组员管理入口、看板、代报）改用 `auth.isLeader`

## 排产产能模型：工序工艺定额（单人日产能 × 标准人力）

- **删除 `ProcessDefinition.default_days`**（固定工期），新增：
  - `per_worker_capacity`：单人日产能（双/人/天），可空
  - `standard_workers`：标准人力（默认几人干），默认 1
- **排产天数 = ⌈数量 ÷ (单人日产能 × 标准人力)⌉**（引擎 `_calc_days`），
  排产设置里的旧 `default_process_days` / 日产能配置不再参与计算（字段保留兼容）
- **强制先配**：色码排产出方案前检查工序产能，未配 → 400 提示工序名；
  排产页捕获后弹出**内联补填对话框**（工序表直接填产能/人力，保存后自动重新出方案，不跳转）
- **派工出入提醒**（执行单页）：派工保存后按 `数量 ÷ (单人产能 × 实际人数)` 估算所需天数，
  与排产窗口对比，超窗弹提醒"可能影响后续工序和交期"
- 受影响单：方案卡片风险标签（逾期/偏紧/产能冲突）+ 急单冲击清单（新方案会推迟哪些在产单）

## 企微/钉钉组织同步（预留，未实现）

- `employees.ext_source/ext_user_id`、`departments.ext_source/ext_dept_id` 已加字段 + 唯一约束
- 同步规矩：单向（企微/钉钉 → 本地）、非破坏（只增改+标记停用，绝不删除，保护历史报工/工资）、匹配键先 ext_user_id 后手机号
- 登录打通复用已有 wechat_openid/unionid

## 旧库迁移（合并后已有数据的 MySQL 库）

`ensure_schema` 只建新表不搬数据：旧 `workers`/`users` 表的数据不会自动进入 `employees`，
直接导致 admin 无法登录（401）。对已有数据的库执行：

```bash
PYTHONPATH=. .venv/bin/python scripts/migrate_legacy_personnel.py
```

脚本做的事（幂等，`employees` 有数据时跳过数据迁移）：
1. 收集并删除所有指向旧 `users`/`workers` 的外键约束
2. `workers` → `employees`（档案字段全量迁移）
3. `users` → 合并进对应员工（按旧 `worker_id`/手机号/姓名匹配，补账号字段）；纯后台用户（admin/manager）新建员工档案
4. `user_roles` → `employee_roles`
5. 业务表外键重指到新 `employees.id`（如 work_logs.worker_id、orders.created_by 等，本库实测 250 条）
6. 重建外键约束指向 `employees(id)`（实测 30 个）

迁移后登录密码不变（admin 原密码可用）。

## 已知既有问题（与本次重构无关，未修）

- `tests/test_au_i0_scan_gate.py`、`test_au_kill_shop_order_k4f.py`：引用不存在的 `assign_basket`（服务为 `assign_bundles_for_basket`）
- `tests/test_intent_router.py`：Settings 缺 `intent_embedder`；`test_agent_observability_p4.py`、`test_workshop_evidence_guardrail.py`：`schedule_agent` 缺少 `_extract_routing`/`_diagnosis_context_meta`
- `scripts/seed_rich_demo.py` 甘特演示：A款/黑 颜色绑定缺失（demo 数据问题）
