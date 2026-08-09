# A2f 设计：计件/成本异常核对 v1

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 A2f

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_a2f_piecework_anomaly.py` 5 passed |
| API | `GET /work-logs/anomalies` 返回 items + summary |
| 边界 | 只读高亮，不改工资引擎 |

---

## 1. 目标与边界

**目标**
月底对计件工资做人工核对时，异常行常靠肉眼从整张报工表里抠——本迭代把可解释的异常规则跑一遍，
高亮出待复核的报工行，省掉月底逐行翻表的时间。

**不做 / 禁区**

- **不重做工资引擎**：不改 `salary_service` 任何计薪口径、不新增结算字段，纯只读高亮
- 不做统计学离群检测（无 ML/标准差），规则全部可解释、可在 UI 直接读到理由
- 不做直接成本（材料/其它成本）异常，本轮只覆盖计件人工（direct cost 异常留作可选后续）
- 不自动处理异常行（不自动作废/改价/拦发工资）；处理仍走既有「改数 / 作废 / 驳回申诉」操作

---

## 2. 规则（均可解释，非黑盒）

复用 `work_logs` / `order_processes.completed_qty` / `own_product_labors` / `salary_service` 月结锁定信息，
不重算工资、不新增账本字段。规则集中在新服务 `app/services/piecework_anomaly.py::list_anomalies`。

| code | 触发条件 | 说明 |
|------|----------|------|
| `qty_over_plan` | 单笔（非返修、非作废）报工数量本身 > 该工序 `plan_qty` | 多半是数量录入错（如多打一个 0） |
| `process_over_plan` | 该工序 `order_processes.completed_qty` 当前已 > `plan_qty` | 直接读已有累计字段，不重新求和；代表行取该工序范围内最新一笔正常有效报工 |
| `price_outlier` | 报工锁定单价 `unit_price` 相对当前工序参考价（产品工序报价，无则工序默认价）比值 **< 0.5 或 > 2.0** | 参考价来自 `get_labor_unit_price`（已有函数），阈值先取固定倍数，不做统计模型 |
| `void_in_locked_month` | 报工已作废，且所在月份 `salary_service.is_month_locked` 当前为锁定 | 作废需先解锁才能操作；若月份现处锁定态仍见到作废行，提示核实是否已发工资又作废 |

单条报工行可同时命中多个 code；返回时按行聚合成 `reasons: [{code, text}]`。

**不矛盾约束：** 规则只读取既有字段（`plan_qty` / `completed_qty` / `unit_price` / 月结锁定），不写库、不影响
`salary_service.month_salary` 计算结果。

---

## 3. API

```text
GET /api/v1/work-logs/anomalies?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
```

- 权限：`admin` / `manager`（与工资导出同级）
- 参数均可选；缺省时不限日期范围（跑全量报工，量大时建议按月查）
- 响应 `data`：

```text
items: [{
  work_log_id, created_at, worker_id, worker_name,
  order_no, product_code, process_name, report_type,
  qty, unit_price, status,
  reasons: [{ code, text }],
  reason_codes: [code, ...]
}]
total: int
summary: { code: count, ... }
message: string
```

实现：`app/services/piecework_anomaly.py`；路由挂在 `app/api/v1/ops.py`（与既有 `/work-logs`、`/salary` 同文件，
复用已导入的 `salary_service` / `order_service` 函数，不新建独立业务模块）。

---

## 4. UI

`WorkLogsAdminView`（报工记录页）新增「异常核对」入口：

1. 工具条加「仅看异常」切换 + 日期范围选择（默认本月）
2. 打开后调用 `/work-logs/anomalies`，表格用同一套列 + 新增「异常原因」列（`el-tag` 多个 chip，
   danger 色，hover 显示完整文案）
3. 关闭「仅看异常」回到原有分页列表，两套数据互不影响
4. 异常行仍用原有「改数 / 作废 / 驳回申诉」按钮处理，不新增处理动作

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A2f-T1 | `piecework_anomaly.list_anomalies` 规则 + 单测 | ✅ |
| A2f-T2 | `GET /work-logs/anomalies` API | ✅ |
| A2f-T3 | `WorkLogsAdminView` 异常核对入口 + 原因 chip | ✅ |
| A2f-T4 | 总纲挂设计 + changelog | ✅ |
| A2f-T5 | 走查签字：四类异常各一个样例 + 与工资计算结果不冲突回归 | ⬜ |

---

## 6. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并落地：四类规则 + API + UI 异常 chip；待走查 |
