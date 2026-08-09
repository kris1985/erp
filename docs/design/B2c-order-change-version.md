# B2c 设计：订单变更版本 v1

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 P2-Next B2c

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_b2c_order_change.py` 通过 |
| API | `GET /orders/{id}/change-logs` 200 |

---


## 1. 目标与边界

**目标**

生产单（`orders`）数量或交期发生**实质变化**时，自动追加一条变更版本记录（`order_change_logs`），
让 PMC / 跟单能在订单详情「变更历史」里看到「谁、何时、改了什么、改前改后」，从而减少「改单扯皮」
（口头改单、事后对不上、争执是谁改的）。

**不做 / 禁区（v1 明确排除）**

- **完整审批工作流**：不做「提交变更 → 审批 → 生效」的状态机；变更即时生效，留痕只做记录，不拦截。
- **强制变更原因**：v1 不强制填写变更原因/理由（后续可加可选字段，不阻塞主路径）。
- **通知推送**：不做变更后自动 IM/短信通知（属 A2d IM 推送范畴，独立排期）。
- **客户/备注/状态/急单等字段**变更不进版本历史，避免噪音；只认**数量（总数/色码明细）与交期**。
- **物料/齐套联动的重算逻辑本身**不重做，直接复用既有 `sync_requirements_after_qty_change` /
  `recalculate_required` 路径（生产单改量后释放超额占用等既有语义不变）。

---

## 2. 主路径

1. PMC/管理员通过 `PATCH /orders/{id}` 修改生产单的 `items`（色码明细/总数）和/或 `delivery_date`。
2. `order_service.update_order`：
   - 修改前，先用 `order_change_service.capture_order_snapshot` 拍下「改前」快照
     （`total_qty` / `delivery_date` / `items[color_id,size_id,qty]`）。
   - 按既有逻辑校验并落库（含 `sync_requirements_after_qty_change` 物料重算）。
   - 提交前调用 `record_order_change_if_needed`：拍「改后」快照并与「改前」逐字段 diff：
     - 若 `total_qty` 或 `items` 有任何差异 → `change_type` 含 `qty`；
     - 若 `delivery_date` 有差异 → `change_type` 含 `delivery_date`；
     - 两者都无差异（比如只改了客户名/备注/急单）→ **不写入**版本记录。
   - 有差异时写入一条 `order_change_logs`，`version_no` 按订单自增（1,2,3…），
     `before_json` / `after_json` 存完整快照，`summary` 生成可读文案
     （如「总数 200→270；色码：黑37 100→120、白37新增50；交期 2026-08-10→2026-08-20」）。
3. PMC 在生产单详情抽屉「变更历史」Tab 查看该单全部版本（按版本号倒序），含操作人与时间。

---

## 3. 数据 `order_change_logs`

| 字段 | 说明 |
|------|------|
| tenant_id / order_id | 归属 |
| version_no | 订单内自增版本号（1 起） |
| change_type | 逗号分隔：`qty` / `delivery_date`（可并存） |
| summary | 人可读变更摘要（服务端生成，非用户填写） |
| before_json / after_json | `{total_qty, delivery_date, items:[{color_id,size_id,qty}]}` 快照 |
| created_by / created_at | 操作人（`users.id`）与时间 |

唯一约束：`(order_id, version_no)`。

---

## 4. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/orders/{id}/change-logs` | 返回该生产单全部版本记录（`created_by_name` 已解析用户名），按版本号倒序 |

写入无独立 API：由 `PATCH /orders/{id}` 内部在数量/交期有实质变化时自动追加，不暴露单独的「手写变更记录」接口
（避免绕过实际改单产生假记录）。

---

## 5. UI

- `OrdersAdminView` 详情抽屉新增「变更历史」Tab（有记录时显示徽标数量）。
- 表格列：版本（V1/V2…）、类型（数量/色码 · 交期 标签）、变更摘要、操作人、时间。
- 空态：「暂无变更记录（数量/交期有实质变化才留痕）」。
- 复用现有列宽记忆 composable（`orders-change-logs`），符合 admin 表格规范。

> v1 未在 `OrdersAdminView` 里新增「编辑数量/交期」的表单入口——现有 `PATCH /orders/{id}` 接口本身已支持
> `items` / `delivery_date`，供后续补的改单表单或其它客户端调用；只要经过该接口的改动都会自动留痕。

---

## 6. 任务

| ID | 内容 | 状态 |
|----|------|------|
| B2c-T1 | 模型 `OrderChangeLog` + 迁移（`create_all` 自动建表） | ✅ |
| B2c-T2 | `order_change_service`：快照/diff/摘要/版本号/查询 | ✅ |
| B2c-T3 | `update_order` 钩子：改前快照 → 改后 diff → 写入版本 | ✅ |
| B2c-T4 | API `GET /orders/{id}/change-logs` | ✅ |
| B2c-T5 | UI「变更历史」Tab | ✅ |
| B2c-T6 | 单测：qty+交期同时变更、无实质变更不留痕、多次变更版本递增 | ✅ |

---

## 7. 走查清单（签收用）

- [ ] 改总数/色码明细后，`change-logs` 新增一条，`change_type` 含 `qty`，摘要含改前改后数字
- [ ] 只改交期，`change_type` 仅含 `delivery_date`
- [ ] 只改客户名/备注/急单，不产生任何版本记录（回归验证不误报）
- [ ] 同一订单多次改动，版本号按序递增且历史全部可查
- [ ] `sync_requirements_after_qty_change` 既有齐套/物料释放语义不受影响（回归）
- [ ] 无权限用户不可通过 `PATCH /orders/{id}` 误改（复用现有 `require_roles`）

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | v1 落地：模型/服务/API/UI/单测；总纲 B2c 状态改为 ⚠️ 已实现待走查 |
