# B2e 设计：补码/改码/尾数向导

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §5 / §7 B2e
> **对象：** 生产单 `orders` 的色码明细 `order_items`（补新码 / 改现有码数量 / 尾数微调）

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_b2e_size_adjust.py` 13 passed |
| API | dry_run 预览 `B1C-WALK` 180→181 成功 |
| UI | 生产单「补改码」向导 |

---

## 1. 目标与边界

**要解决什么**

现场经常出现「补码」（客户临时加某个尺码）、「改码」（把某色码计划数改成另一个数）、「尾数」（结尾几双的零星调整）。此前只能走 `PATCH /orders/{id}` 的整单明细替换（必须一次传全量色码，容易漏码/误删已完成色码），改完也不清楚会不会影响已发货的明细。

**目标（v1）**

1. 一个专用向导接口：只改「本次涉及的色码行」，不要求整单明细全量传入。
2. 支持两种模式：
   - `delta`（补码/减码）：填**变化量**（正数补码，负数减码）
   - `replace`（改码）：填**目标数量**（绝对值）
3. 提交前可「预览」差异（不落库、不触发材料重算），确认后才真正提交。
4. 提交后复用既有 `sync_requirements_after_qty_change` 重算材料需求（占用超发的部分回池）。
5. 标注本次调整是否影响已发货色码（`shipped_qty > 0` 且发生变化），供跟单核对发货单。
6. 变更留痕：若 B2c `OrderChangeLog` 已落地，直接复用其 `capture_order_snapshot` / `record_order_change_if_needed` 写入正式版本记录（向导备注会追加进该版本的 `summary`）；若 B2c 尚未落地，回退为在 `orders.notes` 追加一行备注，保证功能在两种前置状态下都可用。

**不做（v1）**

- 不做「串派工」（改码后自动重新派工/收回配额）——本轮只覆盖料，派工仍走现有派工入口，跟单人工核对。
- 不做「串交期」（改码不联动交期计算/风险条重算）——`A1b` 风险条会在下次刷新时按新的 `total_qty`/进度自然重算，本向导不做特殊处理。
- 不做批量多订单一起补改码（合批已有单独入口 B2f，本向导仍按单张生产单操作）。
- 不做审批流（对齐 B2c 的「不做审批流」边界）。

---

## 2. 主路径

1. 生产单列表「更多」→「补改码」，或详情抽屉工具栏「补改码」按钮 → 打开向导弹窗。
2. 弹窗默认按当前色码明细铺一行一行的编辑网格；顶部切换「补码/减码」或「改码」模式：
   - 补码/减码：每行填**变化量**；「加一行」可选颜色+尺码补一个新码（变化量即新增数量）。
   - 改码：每行填**目标数量**（现有行的尺码不可再改，避免和「新增」混淆；要变更尺码本身，用「删除旧行 + 加一行新码」组合表达）。
3. 填完后点「预览差异」→ 调用同一接口、`dry_run=true`：后端按当前订单状态计算每行 `before_qty → after_qty`，并标注：
   - `below_completed`：调整后低于已完成量 → 提交会被拦截（硬校验，与 `PATCH /orders/{id}` 明细校验一致）
   - `delivery_impact` / `over_shipped`：该色码已有发货且本次改动 → 提示核对发货单
4. 预览通过（无 `has_blocking`）后点「确认提交」→ `dry_run=false` 真正落库：
   - 更新/新增/（必要时）删除 `order_items`
   - 重算 `order.total_qty` 与各工序 `plan_qty`
   - 调 `sync_requirements_after_qty_change` 重算材料需求、释放超占材料回池
   - 写变更记录（B2c 存在则写 `order_change_logs`，否则回退订单备注）
5. 提交成功后：订单列表、详情抽屉的用料/发货/变更记录标签页自动刷新，跟单可立即看到对发货单的影响提示。

---

## 3. 拦截 / 提示规则

| 规则 | 行为 |
|------|------|
| 订单已取消 | 硬拦（`cancelled`） |
| 订单已完成 | 硬拦，需先改回生产中（`completed`，与 `PATCH` 现有规则一致） |
| 调整后数量为负 | 硬拦（`negative_qty`），预览与提交都拦 |
| 调整后低于已完成量 | 预览只标红提示（`below_completed`），**提交**时硬拦（`qty_below_completed`） |
| 该色码已有发货且本次改动 | 不拦截，仅标 `delivery_impact` 提示核对发货单（出货口径仍按 `order_items.shipped_qty`，不在本向导改） |
| `replace` 模式同一色码重复且数值不一致 | 硬拦（`duplicate_item`） |

---

## 4. 数据 / API

**接口**

```
POST /api/v1/orders/{order_id}/size-adjust
{
  "items": [{ "color_id": 1, "size_id": 5, "qty": 5 }],
  "mode": "delta" | "replace",   // 默认 delta
  "note": "客户临时加5双39码",     // 可选
  "dry_run": true | false        // 默认 false；预览用 true
}
```

返回：每行 `before_qty/after_qty/delta_qty/completed_qty/shipped_qty/is_new/below_completed/over_shipped/delivery_impact`，以及订单级 `total_qty_before/after`、`has_blocking`、`has_delivery_impact`；非预览时附带材料重算结果（`released`/`requirement_count`）与变更记录结果（`change_log_id`/`change_logged`/`summary`）。

**落地文件**

- `app/services/order_service.py`：`adjust_order_sizes()`（核心逻辑，复用 `_item_key`/`OrderStatus` 校验，与 `update_order` 共用材料重算与变更留痕挂钩点）
- `app/api/v1/orders.py`：`POST /{order_id}/size-adjust`
- `app/schemas/api.py`：`SizeAdjustItemIn` / `SizeAdjustRequest` / `SizeAdjustItemOut` / `SizeAdjustResult`
- 前端：`web/src/views/admin/OrdersAdminView.vue`（`sizeAdjust*` 系列状态/函数与弹窗，命名与既有弹窗区分，避免并行改动冲突）

**复用而未新增**

- 材料重算：`app/services/material_service.sync_requirements_after_qty_change`（不新增逻辑，直接复用）
- 变更留痕：`app/services/order_change_service.capture_order_snapshot` / `record_order_change_if_needed`（B2c 落地后自动接上；未落地时向导内部回退为 `orders.notes` 追加）

---

## 5. 走查证据（待补）

开走查前请覆盖：① 补码新增一个尺码并联动总数 ② 改码把某色码数量改小并触发材料回池 ③ 已完成量校验硬拦 ④ 已发货色码改动后前端提示「影响发货单」且详情页发货 tab 数字联动 ⑤ 变更记录里能看到本次调整版本（如 B2c 已上线）。

单测：`tests/test_b2e_size_adjust.py`（13 项：补码新增/改码替换/预览不落库/低于完成量拦截/负数拦截/材料回池/发货影响标注/变更记录集成与版本递增/预览不写变更记录/取消与已完成订单硬拦/空明细与非法模式校验）。

---

## 6. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 落地 v1：`POST /orders/{id}/size-adjust`（delta/replace + dry_run 预览）+ 向导弹窗 + 材料重算联动 + B2c 变更记录集成（存在则用，否则回退备注） |
