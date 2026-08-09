# B0a 设计：齐码可发货闸门

> **状态：** 已验收（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 B0a  

---

## 1. 可发口径（定稿）

```text
约定工序 = 默认末道 OrderProcess（同首道约定：按 id 升序，末道 = id 最大）
last_qualified[色,码] = SUM(work_logs.qualified_qty)
  WHERE order_process_id = 末道.id
    AND status = valid
    AND report_type ∈ {normal, group, supplement, tail}  # 不含 rework
    AND color_id / size_id 匹配该 order_item
    # 无色码报工不计入任何 SKU

shippable_qty = max(0, last_qualified − shipped_qty)
可出上限展示 = min(shippable_qty, backlog=plan−shipped)

欠码（相对计划）= max(0, plan − last_qualified)
```

**禁止**用 `order_items.completed_qty`（任意工序累加，≠末道成品）。

**无工序：** `gate_enabled=false`，本单仅保留欠交闸（不启用齐码闸），摘要注明。

**强制出货：** P0 不做入口。

---

## 2. 闸门行为

| 动作 | 行为 |
|------|------|
| 存草稿 | 仍只卡欠交；**可不卡**齐码（可存未齐草稿） |
| 确认出货（含创建并确认） | **硬拦**：`qty > shippable` → `ShipmentError("not_shippable", …)` |

---

## 3. API

`GET /orders/{id}/delivery` 每行增加：

- `last_process_id` / `last_process_name`（单头级也可）
- `gate_enabled`
- `last_qualified_qty`
- `shippable_qty`
- `short_qty`（欠码 vs 计划）

---

## 4. UI

出货新建表：列 **末道合格 / 可出码 / 欠码**；本次出货 `max = min(backlog, shippable)`（gate 关时 = backlog）。

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| B0a-T1 | last_order_process + 汇总 + delivery 扩展 | ✅ |
| B0a-T2 | confirm 闸门 | ✅ |
| B0a-T3 | ShipmentsAdminView 列与 max | ✅ |
| B0a-T4 | 单测未齐拦 / 齐码放 | ✅ |
