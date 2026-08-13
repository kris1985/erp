# AU-I1 实现设计：有分配合单 · 执行开裁 · 齐套接驳

> **状态：** ✅ M1–M4 已落地  
> **需求：** [`AU-I1-merge-execution.md`](./AU-I1-merge-execution.md)  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md)  
> **验收：** [`ACCEPTANCE.md`](./ACCEPTANCE.md) §B  
> **依赖：** AU-I0（筐捆、工艺、派工闸门）已落地  
> **原则：** 规格执行单**新表**；车间短时仍挂一张「桥接生产单」复用 I0 开裁/报工；合批不删但不做新主路径。

---

## 0. 切片

| 切片 | 内容 | 可演示 | 状态 |
|------|------|--------|------|
| **I1-M1** | `spec_execution_orders` + `execution_allocations`；可产色码列表；手工合单生成执行单+桥接 `orders` | 两 SO 同色码 → 一执行单，ratio 正确 | ✅ |
| **I1-M2** | 开裁挂执行单；筐打印印分配来源；TraceUnit 记 `execution_id` | 打印见 SO-A/SO-B 双数 | ✅ |
| **I1-M3** | 报工回写执行进度 + 按 ratio **预估**销售色码产量（勾平） | 合计=分摊合计 | ✅ |
| **I1-M4** | 用料快照/领料认执行单（双写 `order_id`）；可产齐套过滤入口；文档合批降过渡 | G1 不裂 | ✅ |

推荐：**M1 → M2 → M3 → M4**。

---

## 1. 领域契约

```text
SalesOrderLineItem (需求色码)
  remaining = qty - allocated_qty
  同 (own_product_id, color_id, size_id) 可勾选合并

SpecExecutionOrder (规格执行单：款+色+码)
  total_qty = Σ allocation.qty
  shop_order_id → 桥接生产单（I0 工序/开裁/报工仍走它）
  status: draft|confirmed|in_progress|completed|cancelled

ExecutionAllocation
  sales_order_line_item_id, qty, ratio
  ratio = qty / execution.total_qty（落库快照，改量需重算）
  UNIQUE 约束：同一 line_item 在未取消执行单上 allocated 合计 ≤ item.qty
```

**禁无分配合并：** 创建执行单必须 ≥1 条 allocation，且 Σqty=total_qty，ratio 合计=1（容差 1e-6）。

**桥接策略（迁移期）：**

- 合单成功 → `create_order` 一张 `orders`（单色码明细=执行总量）+ 从产品落工序（I0）。  
- `TraceUnit.order_id` 仍指向桥接单；另写 `execution_id`（M2）。  
- 领料/齐套：M4 起认 `execution_id`，双写旧 `order_id`。

**工资：** 报工仍记桥接单/`WorkLog`；**不**按 ratio 拆个人工资到 SO（成本归集 I2）。

---

## 2. 数据模型

### 2.1 新表

```text
spec_execution_orders
  id, tenant_id, execution_no
  own_product_id, color_id, size_id
  total_qty, completed_qty (default 0)
  status, delivery_date NULL
  shop_order_id NULL FK(orders)   -- 桥接
  notes, created_by, created_at
  UNIQUE(tenant_id, execution_no)
  INDEX(tenant_id, own_product_id, color_id, size_id, status)

execution_allocations
  id, tenant_id, execution_id
  sales_order_id, sales_order_line_id, sales_order_line_item_id
  qty INT, ratio DECIMAL(12,8)
  produced_qty_est INT DEFAULT 0   -- M3 预估回写
  UNIQUE(execution_id, sales_order_line_item_id)
  INDEX(sales_order_line_item_id)
```

### 2.2 扩表

| 表 | 字段 | 说明 |
|----|------|------|
| `sales_order_line_items` | `allocated_qty` INT default 0 | 已占用合单量；剩余=qty−allocated |
| `trace_units` | `execution_id` NULL FK | M2；筐/捆挂执行单 |
| `order_material_requirements` | `execution_id` NULL | M4 双写 |

---

## 3. API 草表（M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/executions/producible` | 可产色码：按款色码聚合 remaining；可选 `kit_ready` 占位 |
| POST | `/executions` | 合单：`items:[{line_item_id, qty}]` → 执行单+分配+桥接生产单 |
| GET | `/executions` | 列表 |
| GET | `/executions/{id}` | 详情含 allocations + shop_order |
| POST | `/executions/{id}/cancel` | 取消：释放 allocated_qty（无报工/无活跃码时） |

M2+：`POST /executions/{id}/cut-cards`（桥接单 cut-cards 也会自动挂 execution）。

---

## 4. 合单伪代码

```text
function create_execution(items):
  assert items non-empty
  resolve line_items; assert same product+color+size
  for each: qty>0 and qty <= item.qty - item.allocated_qty
  total = sum(qty)
  ratios = qty_i / total  (last eats rounding so sum(ratio)=1)
  insert SpecExecutionOrder(total_qty=total, ...)
  insert allocations
  bump line_item.allocated_qty += qty
  shop = create_order(product, items=[{color,size,qty:total}], notes=f"执行单 {execution_no}")
  execution.shop_order_id = shop.id
  return execution
```

---

## 5. 单测

| 文件 | 覆盖 |
|------|------|
| `test_au_i1_merge_execution.py` | 两来源合单 ratio；超量拒绝；不同规格拒绝；取消释放 |
| `test_au_i1_cut_execution.py` | 执行单开裁挂 `execution_id`；分配来源 SO-A/SO-B；桥接单开裁自动挂靠 |
| `test_au_i1_progress_writeback.py` | 末道报工回写 completed；ratio 分摊勾平；作废回滚 |
| `test_au_i1_kit_execution.py` | 用料双写 execution_id；可产 kit_hint；合单后齐套不裂 |

---

## 6. 明确不做（交 AU-I2/I3）

- 排产池切色码主输入（→ I3）  
- FG/直发精确产量（→ I2）  
- 删除 MergeBatch 代码（保留过渡入口；新路径不依赖）  
- 计件工资按 ratio 拆到销售单（明确不做）

---

## 7. 开放拍板（已按推荐落地）

| # | 问题 | 决定 |
|---|------|------|
| 1 | 新表 vs 演化 orders | **新表** + 桥接 `shop_order_id` |
| 2 | 可产齐套 | BOM×剩余量对照池净可用 → `kit_hint`；`kit_ready_only` 过滤 |
| 3 | 父流转卡 | M2 用同色码下筐的逻辑父；独立实体可空 |
| 4 | 在制进度口径 | **末道整款工序** `completed_qty` 作预估基数；分配末行吃余数勾平 |
| 5 | 用料/领料主体 | 需求行/领料单双写 `execution_id`；齐套算法仍认 `order_id` |

---

**进度：** M1–M4 全部 ✅（合单 → 开裁印来源 → 报工预估 → 用料/齐套接驳）。  
**下一步：** AU-I2（FG/直发/入库精确拆分）或 I0 收尾（车间设置 UI）。  
**回链：** README / AU-I1 需求文头链本文。
