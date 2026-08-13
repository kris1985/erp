# 出货改挂销售单（去桥接 · 出货刀）

> **状态：** 🚧 实施中（2026-08-12）· M1–M3 已落代码  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md) §2.10 / §4.3 / §11  
> **前提：** 方案 C 执行单头已落地；直发已按分配拆销售出货，但 schema 仍以生产单为主键。

---

## 1. 裁决

| 问题 | 裁决 |
|------|------|
| 出货挂谁？ | **销售单 + 销售色码**（可出量认 `SalesOrderLineItem`） |
| 生产单？ | `Shipment.order_id` **降为可选桥接/追溯**，新单可不写或双写过渡 |
| 应收？ | 跟出货：**认销售单**；`Receivable.order_id` 同步降级 |
| 合单？ | 一张执行/一筐可对应多销售 → **按分配拆多张出货**（直发已做；手工出货也按销售） |
| 手工出货 UI？ | 选**销售单可出量**，不再选生产单 |

---

## 2. 现状 → 目标

| 对象 | 现状 | 目标 |
|------|------|------|
| `Shipment.order_id` | NOT NULL，业务主键 | 可空；双写过渡后只追溯 |
| `Shipment.sales_order_id` / `sales_order_no` | 可空快照 | **业务必填**（新单） |
| `ShipmentLine.order_item_id` | 挂生产色码行 | 增 `sales_order_line_item_id`（业务量）；`order_item_id` 可空双写 |
| `Receivable.order_id` | NOT NULL | 可空；`sales_order_id` 必填 |
| 齐码闸 `/orders/{id}/delivery` | 按生产单齐码 | 按**销售色码**可出量（produced − shipped） |
| `ShipmentsAdminView` | 下拉生产单 | 下拉/搜索销售单 → 勾色码行出货 |
| 直发 `create_direct_shipments` | 已拆销售，仍强制桥接 `order`/`order_item` | 去掉硬依赖；桥接 shipped 可双写 |
| 箱唛 | 挂出货单（已部分） | 不变；出货主体变销售后自然对齐 |

---

## 3. 实施切片（建议串行）

### M1 · Schema 双写（不破旧）
- `shipments.sales_order_id` 对新写入强制有值（应用层）
- `shipment_lines` 增 `sales_order_line_item_id`（可空 → 新单必填）
- `order_id` / `order_item_id` 改为可空（迁移：`ALTER` + 旧行保留）
- `receivables` 同理：`sales_order_id` 应用层必填；`order_id` 可空

### M2 · 服务层
- `create_shipment`：入参改为 `sales_order_id` + `items[{sales_order_line_item_id, qty}]`
  - 校验：色码属于该 SO；`qty ≤ produced_qty - shipped_qty`（无 produced 时过渡规则写明）
  - 回写 `SalesOrderLineItem.shipped_qty`
  - 若能解析到桥接 `order_item`：双写 `OrderItem.shipped_qty` + 填 `order_id`（过渡）
- `create_direct_shipments`：以 allocation 写销售出货为主；桥接可选
- `order_delivery_summary` → `sales_delivery_summary(sales_order_id)`（或并存）
- 列表/打印：主显销售单号；生产单号降为次要

### M3 · API + Admin UI
- `POST /shipments`：body 改销售口径（兼容旧 `order_id` 一期）
- `GET /sales-orders/{id}/delivery`：可出色码汇总
- `ShipmentsAdminView`：选销售单 → 色码可出量表格 → 确认出货
- `ShipmentPrintView`：抬头「销售单」为主，「内部生产单」次要/可隐藏

### M4 · 验收与旧数据
- 旧出货：仅有 `order_id` 的，列表仍能打开；尽量回填 `sales_order_id`（从 `orders.sales_order_id` / 快照）
- 合单直发：两客户两张出货、两张应收，数量勾平
- 手工出货：不选生产单也能出；合单场景按色码行出，不串客户

---

## 4. 非目标（本刀不做）

- 删掉生产单表或强制所有历史 `order_id` IS NULL  
- 齐套/锁料迁执行单（下一刀）  
- 报工/开裁改主键  
- 重画财务核销模型（只改出货/应收挂载）

---

## 5. 风险与过渡

| 风险 | 对策 |
|------|------|
| 合单桥接一单多客户，旧手工出货糊客户 | M3 禁止再以生产单为唯一选择；合单只走出销售 |
| 无 `produced_qty` 的旧单可出量不清 | 过渡：允许按销售色码 qty − shipped；或要求先有入库/直发回写 |
| 打印/导出仍写「生产单」 | 文案一并改；字段保留兼容 |

---

## 6. 开改顺序（动手时）

1. 模型 + `db_schema` 可空/新列  
2. `shipment_service` + 直发路径  
3. API  
4. Admin 出货页 + 打印  
5. 测试：手工销售出货、合单直发拆单、旧单列表兼容  
