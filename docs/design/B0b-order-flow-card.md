# B0b 设计：生产单开裁/配码流转卡

> **状态：** 已验收（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 B0b  
> **对象：** **生产单** `orders`（文案禁止写成销售单）

---

## 1. 目标与边界

**目标**  
PMC/裁床从生产单列表或详情一键打开浏览器打印页：单号、货号、客户、交期、色码数量表、工序列，能当场开裁。

**不做**

- 合批组批 / 合批卡（仅预留 HTML 注释骨架）  
- 改报工、领料、排产  
- Excel/PDF 导出（可后置，参照出货单）  
- 深链 APS  

---

## 2. 主路径

1. `/admin/orders` 列表「更多 → 打印流转卡」或详情抽屉工具栏  
2. 新窗口 `/admin/orders/print/:id`  
3. 加载 `GET /orders/{id}` → 预览 → 自动/手动打印（清 `document.title` + 临时改 URL，同出货单）

---

## 3. 数据

| 区块 | 字段 |
|------|------|
| 抬头 | `order_no`、`product_code`、`customer_name`、`delivery_date`、`total_qty`、可选 `sales_order_no`（标注「关联销售单」） |
| 色码表 | `items[]`：颜色、尺码、数量；须有 `color_name` / `size_value`（序列化 enrichment） |
| 工序 | `processes[]`：序号、`process_name`、`plan_qty`；勾选列供现场手写 |
| 空态 | 无 items / 无 processes 时表格内提示，不白屏 |

合批预留：打印页 HTML 注释 `<!-- MERGE_BATCH_MEMBERS: 合批卡时在此展开多生产单成员区 -->`

---

## 4. 生产任务

| 任务 | 内容 | 状态 |
|------|------|------|
| B0b-T1 | `OrderItemOut` + `_serialize_order` 补颜色/尺码名 | ✅ |
| B0b-T2 | `OrderFlowCardPrintView.vue` + 路由 | ✅ |
| B0b-T3 | `OrdersAdminView` 入口 | ✅ |
| B0b-T4 | 总纲挂设计；状态更新 | ✅ |

---

## 5. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并开干 |
