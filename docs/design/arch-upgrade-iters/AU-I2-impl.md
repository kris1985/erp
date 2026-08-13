# AU-I2 实现设计：成品入库 / 直发 · 预装箱 · 成本归集

> **状态：** ✅ M1–M4 已落地  
> **需求：** [`AU-I2-fg-direct-ship-packing.md`](./AU-I2-fg-direct-ship-packing.md)  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md)  
> **验收：** [`ACCEPTANCE.md`](./ACCEPTANCE.md) §C  
> **依赖：** AU-I1（执行单、分配、筐、预估产量）  
> **原则：** 先入库闭环再直发；预装箱未齐不可直发；精确产量只在入库/直发写。

---

## 0. 切片

| 切片 | 内容 | 可演示 | 状态 |
|------|------|--------|------|
| **I2-M1** | 轻量 FG 账 + 筐完工入库；`produced_qty` 精确按 ratio 勾平；筐→warehoused | 合单筐入库 → FG++、SO 精确产量 | ✅ |
| **I2-M2** | `allow_direct_ship` + 直发虚拟入出 + 按分配拆出货 | 直发净库存 0；多 SO 出货 | ✅ |
| **I2-M3** | 预装箱挂筐/执行；无预装拦截直发；落成出货装箱/箱唛 | 走查 1/4/5 | ✅ |
| **I2-M4** | 入库人工成本 ratio 归集线索 + 文档/对账说明 | G5 线索可见 | ✅ |

推荐：**M1 → M2 → M3 → M4**。

---

## 1. I2-M1 领域契约

```text
TraceUnit(basket, done|in_process) --warehouse--> status=warehoused
  FG stock += basket.qty (own_product + color + size)
  FG ledger: inbound
  ExecutionAllocation.produced_qty_est 下调（转精确）
  SalesOrderLineItem.produced_qty += 精确分摊（末行吃余）
  SpecExecutionOrder：可选 completed_qty 与入库累计对齐策略见下
```

**精确分摊：** 与 M3 预估同算法 `split_produced_by_ratio(basket.qty, ratios)`，写入 `produced_qty`；同步 `produced_qty_est = max(0, est - share)`。

**进度口径：** 入库前展示预估；入库后 `produced_qty` 为精确；API `progress_kind=exact` 出现在已产字段。

**不做（M1）：** 直发、预装箱、成本归集、FG 库位。

---

## 2. 数据模型（M1）

```text
fg_stocks
  id, tenant_id, own_product_id, color_id, size_id, qty
  UNIQUE(tenant_id, own_product_id, color_id, size_id)

fg_ledgers
  id, tenant_id, fg_stock_id, direction(in|out|adjust)
  qty, order_id NULL, execution_id NULL, trace_unit_id NULL
  ref_type, ref_id, note, created_by, created_at
```

扩表：
| 表 | 字段 |
|----|------|
| `trace_units.status` | 枚举加 `warehoused`（及预留 `shipped` 字符串值） |
| `sales_order_line_items` | `produced_qty INT default 0` |

---

## 3. API（M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trace-units/{id}/warehouse` | 筐入库（须 basket；挂 execution 时写精确产量） |
| GET | `/fg-stocks` | FG 结存列表 |

---

## 4. 单测（M1）

| 文件 | 覆盖 |
|------|------|
| `test_au_i2_fg_warehouse.py` | 两来源合单筐入库；FG+=qty；produced 30/20 勾平；重复入库拒绝 |

---

**进度：** I2-M1 ✅（FG + 筐入库 + 精确产量）。  
**进度：** I2-M2 ✅（直发开关 + 虚拟入出 + 按销售分配拆出货/应收）。  
**进度：** I2-M3 ✅（按筐预装 + 直发闸门 + 落成箱挂出货）。  
**进度：** I2-M4 ✅（入库/直发人工成本 ratio 归集线索 + 对账 API）。  
**下一步：** AU-I2 验收走查；或进入 **AU-I3**。  
**回链：** README / AU-I2 需求文头。

---

## 5. I2-M3 领域契约

```text
PackingPlan(basket_id, execution_id?, draft)
  cartons: CTN-{basket.code}-{seq}，合计 == basket.qty

直发 gate：
  无挂筐草稿预装 → prepack_required
  箱合计 ≠ 筐数量 → prepack_qty_mismatch

直发 settle：
  plan.status → confirmed
  PackingCarton.shipment_id ← 按出货量贪心挂靠（不新造箱）
```

扩表：
| 表 | 字段 |
|----|------|
| `packing_plans` | `basket_id`, `execution_id` |
| `packing_cartons` | `shipment_id` |

API：
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trace-units/{id}/prepack-plans` | 按筐生成预装 |
| GET | `/trace-units/{id}/prepack-plans` | 筐预装列表 |

单测：`test_au_i2_prepack.py`（挂筐、闸门、落成、数量不符）。

### 补丁：从 FG 出货（验收缺口关闭）

```text
TraceUnit(warehoused) --ship-from-fg-->
  assert prepack ready
  FG stock -= qty；ledger out (fg_ship)
  status=shipped
  create_direct_shipments(按 ratio，产量已在入库写过)
  settle_basket_prepack
```

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trace-units/{id}/ship-from-fg` | 成品仓出货 |
| GET | `/shipments/{id}/packing-cartons` | 落成箱唛补打列表 |

箱唛三入口：订单装箱 · 执行单预装/箱唛 · 出货单箱唛。

单测：`test_au_i2_ship_from_fg.py`。

---

## 6. I2-M4 领域契约（G5）

```text
工资账：WorkLog（人 × 桥接生产单）— 报工不按 ratio 拆销售
订单成本账：入库/直发时归集
  source = Σ(WorkLog 锁价×计件量) on shop_order
  basket_pool = 剩余未归集 × (筐qty / 剩余未终态qty)  # 末筐吃余
  → split_money_by_ratio(basket_pool, allocation.ratios)
  → sales_line_labor_allocations + SalesOrderLineItem.labor_cost +=
```

扩表：
| 表 | 字段 |
|----|------|
| `sales_order_line_items` | `labor_cost` |
| `sales_line_labor_allocations` | 流水：SO 色码、execution、trace_unit、amount、ref_type |

API：
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/executions/{id}/labor-allocations` | 计件总额 / 已归集 / 未归集 + 明细 |
| （副作用） | 入库/直发响应 `labor_splits` | 当场线索 |

### 对账说明

1. **计件月结**仍认 `WorkLog`（人×执行/报工）；**不**因合单改个人工资到销售单。  
2. **销售色码人工成本**只在入库/直发写入；允许报工与入库分时机——未入库前 `unallocated_labor > 0` 属正常。  
3. 同一执行单全部筐入库/直发后：`allocated_labor_total` 应等于入库当时的 `shop_order_piecework_total`（末筐吃余）。若之后又有补报工，会出现新的未归集额，需后续入库事件或运维补归集（本切片不自动追平历史）。  
4. 接单/毛利：销售明细 `labor_cost` 为累计线索；生产单 `order_profit` 仍按桥接单 WorkLog 估算，两者口径不同勿直接加减。

单测：`test_au_i2_labor_cost.py`。
