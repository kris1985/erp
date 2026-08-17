# A2g 设计：工资 vs 实际人工成本对账 + AI 根因分析

> **状态：** ✅ 落地（2026-08-16）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 A2g

---

## 1. 目标与边界

**目标**
月底对账时回答三个问题：① 工资应发总额与实际人工成本差多少、差在哪；② 是否所有员工已电子签名；
③ 差异根因可否让 AI 军师直接解释（根因分析入口）。

**口径**
「实际人工成本」= 当月全部**有效报工**的计件金额（数量×单价，返修按租户「返修是否计薪」设置），
与工资引擎 `month_salary` **同源**（同一批 `work_logs`、同一 `work_log_unit_price` 锁价优先逻辑），
且**含非在职员工**当月报工（离职/停用仍产生真实人工）。

**差异根因 bucket（互斥、合计等于差异，均可解释）**

| key | label | 符号 | 触发 |
|-----|-------|------|------|
| `base_salary` | 底薪部分（固定/底薪+计件等） | + | 应发含底薪，人工成本不含 |
| `fixed_piece_unpaid` | 固定工资员工计件不计发 | − | fixed 员工有报工但工资只发底薪 |
| `quota_reduction` | 定额折算扣减（计件应发 < 计件全额） | − | base_plus_piece 有定额、超额比例折算 |
| `inactive_worker_logs` | 非在职员工当月报工计件 | − | 离职/停用员工当月仍有报工 |
| `other` | 其它/取整残差 | ± | 仅当残差 ≥ 0.005 时出现 |

**不做 / 禁区**

- 不重做工资引擎：复用 `month_salary_all` 与既有单价逻辑，不改任何计薪口径、不新增结算字段
- 不把「一致/不一致」做成黑盒结论：差异必须能逐项还原（`explained` 布尔由 bucket 合计与残差决定）
- 不自动改数/拦发工资：只读对账 + AI 解读，处理仍走既有改数/作废/申诉流程

---

## 2. 后端

- `app/services/salary_service.py`
  - `month_salary_all` 新增：`all_acknowledged`（锁定且全员已签）、`unacknowledged`（锁定后未签名单）
  - `reconcile_salary_cost(db, tenant_id, year_month)`：应发侧 + 人工成本侧 + 差异分解 + 签名完成度
- `app/services/analytics.py`：`analyze_salary_cost_reconcile`（insights + bar 图，供 AI 说话）
- `app/services/workshop_metrics.py`：注册指标 `analytics.salary_cost_reconcile`（权限 `menu.salary`）
- `app/mcp/scopes.py`：ops Server 指标白名单加入该指标 → 外部 MCP 代理也可查
- `app/api/v1/ops.py`：`GET /salary/reconcile?year_month=`（admin/manager）

**响应要点**：`payroll{count,total_wage,base_salary_total,piece_full_total,piece_payable_total,no_log_workers}`
+ `labor_cost{total,inactive_workers_piece,unpaid_rework_*}` + `variance{amount,rate,explained,significant}`
+ `breakdown[]` + `signature{acknowledged_count,total,all_acknowledged,unacknowledged}`。

---

## 3. AI 入口

- 应用内军师（`/admin/schedule-assistant`）：用户问「某月工资和人工成本为什么对不上」时，
  经 `list_metrics` 发现 `analytics.salary_cost_reconcile` → `query_metric` 取回 insights 直接作答；
  前端对账卡「问 AI 军师原因」按钮带 `?q=` 深链自动提问
- MCP ops Server：`query_metric(analytics.salary_cost_reconcile, {"year_month": "YYYY-MM"})`

---

## 4. 验收

| 项 | 结果 |
|----|------|
| 单测 | `tests/test_salary_cost_reconcile.py` 8 passed（纯计件一致 / 底薪差异 / 定额折算 / 非在职报工 / 返修不计薪 / 签名完成度 / AI 分析 / API） |
| API | `GET /salary/reconcile` 返回对账结构 |
| 指标 | `workshop_metrics.query_metric("analytics.salary_cost_reconcile")` 可查 |
| 边界 | 只读对账，不改工资引擎口径 |
