# B1d 设计：承接外包（来料加工 / 承揽针车）

> **状态：** v1 已落地（2026-08-20）；见 §7 任务打勾  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md)（新增 B1d；建议归 P2-Next，可提前到与 P1 并行）  
> **对象：** `SalesOrder`（收入语义）+ `ExecutionHeader` / `OrderMaterialRequirement`（来料=客供）+ `Shipment` / `Receivable`（加工费回款）  
> **关联：** [`B1a-customer-supply-desk.md`](./B1a-customer-supply-desk.md)（客供收货台，复用）· [`A2e-loss-variance.md`](./A2e-loss-variance.md)（实耗损耗，复用）· B2a 外发（镜像）  
> **背景：** [`competitive-outsourcing-module.md`](../competitive-outsourcing-module.md)

---

## 1. 目标与边界

**目标**  
让现有「自产自销」链路通过 **3 个语义切换 + 2 个轻增量** 支持「承接外包」：上家鞋厂供料、我方做针车等工序、收加工费。毛利公式零改动。

**不做**

- 上家协同门户 / 上家自助登录（对应外发的 SCM，属后置）  
- 承接外包再转包（承揽后二次外发）自动链路（B2a 落地后手工串联）  
- 来料进共享库存池（客供仍不进池，同 B1a 口径）  
- 按工序计价加工费（v1 按双）

---

## 2. 定位：与 B2a 外发的镜像

| | 外发 B2a（发包方） | 承接外包 B1d（承揽方） |
|---|---|---|
| 我们是谁 | 上家 | **外协厂** |
| 物料谁出 | 我们发料出去 | **上家供料（客供）** |
| 钱怎么走 | 付加工费 → `Payable` | **收加工费 → `Receivable`** |
| 典型工序 | 针车/硫化发出去 | **针车来料加工** |

两者可共用一套「外协」抽象（`Partner` 既是上家也是下家），但落地成本差异大：**承接外包几乎零新表**，外发要外发单六段闭环。

---

## 3. 主路径

1. 建 **「纯加工产品」**：`OwnProduct` 材料行为空 / 全客供，只配针车工序工价（`OwnProductLabor`，`process_type=personal`）。  
2. 接 **「来料加工单」**：`SalesOrder.customer_name` = 上家，`SalesOrderLine.unit_price` = 加工费（元/双），上家款号放 `customer_sku`。  
3. 用料全标客供：确认生产生成用料行时 `is_customer_supplied=true`，走 B1a 收货台登记到货 / 催料。  
4. 报工（针车计件，走现有 `OrderProcess` / `WorkLog`）。  
5. 完工出货：`Shipment.amount = 加工费 × 双数` → 自动生成 `Receivable`。  
6. 毛利自动正确：`gross = 加工费 − 计件人工 − 其他费用`（材料=0，见 §5）。

---

## 4. 数据

### 4.1 零新表复用（字段级映射）

| 承接外包需要 | 现有字段 | 语义 |
|-------------|---------|------|
| 上家 | `SalesOrder.customer_name` / `customer_id` | 既供料又收成品的上家鞋厂 |
| 加工费单价 | `SalesOrderLine.unit_price` | 元/双（不含料） |
| 上家款号 | `SalesOrderLine.customer_sku` | 上家对款的编号 |
| 来料标记 | `OrderMaterialRequirement.is_customer_supplied` | = `true` |
| 来料到货/欠数 | `OrderMaterialRequirement.arrived_qty` + `CustomerSupplyReceipt` | 复用 B1a |
| 针车工价 | `OwnProductLabor.unit_price` | 工序计件价 |
| 加工费收入 | `Shipment.amount` → `Receivable.amount` | 出货自动挂应收 |
| 加工毛利 | `finance_service.order_profit` | `revenue − material(0) − labor − other` |

### 4.2 增量 1：`biz_mode` 标记（订单维度）

现状无「业务形态」概念，来料加工单和卖货单会混在一屏，入口 / 列表 / 统计口径无法区分。落 `SalesOrder`：

```python
class SalesBizMode(str, PyEnum):
    self_produce = "self_produce"      # 自产自销（默认，存量单回填）
    subcontract_in = "subcontract_in"  # 承接外包 / 来料加工
```

| 字段 | 说明 |
|------|------|
| `SalesOrder.biz_mode` | 默认 `self_produce`；`subcontract_in` 时收入按加工费口径展示 |

影响面（v1 轻）：列表标签 + 收入口径文案 + 毛利报表分组；**不改变下单主流程**。

### 4.3 增量 2：来料损耗对账（复用 A2e）

承接外包核心痛点是「上家给 1000 双料，我交回 950 双成品，损耗算谁的」。A2e 已有「实耗 vs 标准损耗」引擎，补一层客供口径：

| 口径 | 字段 | 含义 |
|------|------|------|
| 上家来料 | `arrived_qty` | B1a 累计到货 |
| 我方实耗 | `issued_qty` | 发车间 / 领料累计 |
| 成品产出 | 报工合格量（`WorkLog.qualified_qty`） | 交回上家的产量 |

**规则：** `损耗 = 实耗 − 产出`；`在途 = 来料 − 实耗`。超阈值（如 > BOM 标准损耗 + 容差）进「今日行动」，并生成「上家对账行」（对账单可后置为导出/报表，v1 只在看板展示，不建独立表）。

---

## 5. 成本 / 毛利口径

`finance_service._material_cost_from_reqs` 已 `if r.is_customer_supplied: continue`，**公式零改动**。v1 仅需：

- `order_profit` / `sales_order_profit` 返回加 `biz_mode`；  
- 展示文案：`subcontract_in` 时 `revenue` 标「加工费收入」，`estimate_note` 改为「加工毛利（材料客供不计，人工按计件）」。

---

## 6. API

| 方法 | 路径 | 说明 |
|------|------|------|
| PATCH | `/sales-orders/{id}` | 支持 `biz_mode`（下单 / 编辑可设） |
| GET | `/sales-orders` | 列表可按 `biz_mode` 筛 |
| GET | `/customer-supply` | 复用 B1a；`subcontract_in` 单话术显示「上家来料」 |
| GET | `/profit-report` | 毛利报表按 `biz_mode` 分组 |

权限：沿用 `menu.customer_supply` + 销售单既有权限；不新增菜单。

---

## 7. 任务

| ID | 内容 | 依赖 |
|----|------|------|
| B1d-T1 | `SalesBizMode` 枚举 + `SalesOrder.biz_mode`（迁移回填 `self_produce`） | — ✅ |
| B1d-T2 | 纯加工产品：`OwnProduct` 材料可空 / 全客供（建单校验放宽），针车工价路线照常 | — ✅（空 BOM 本就允许；全客供由 T3 覆盖） |
| B1d-T3 | 来料加工单主路径走查：接单 → 用料全标客供 → B1a 到货 → 报工 → 出货 → 应收 | T1/T2 ✅ |
| B1d-T4 | 客供损耗对账（复用 A2e 引擎 + 上家口径：来料/实耗/产出），进今日行动 | T3 ✅ |
| B1d-T5 | 毛利口径：`order_profit` 带 `biz_mode` + 加工费文案 | T1 ✅ |
| B1d-T6 | 单测（加工费收入=毛利口径、客供成本=0、损耗对账）+ seed | T1–T5 ✅（`tests/test_b1d_subcontract_in.py` 6 passed） |
| B1d-T7 | 总纲 `product-roadmap.md` 挂 B1d + 本文档链接 | 全部 ✅ |

**验收口径：** 一单针车来料加工可跑通「上家交料 → 到货欠数 → 报工 → 出货按加工费挂应收 → 加工毛利不含料」，损耗超标能预警。

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-20 | 初稿：承接外包复用链路 + biz_mode + 损耗对账；源自 [`competitive-outsourcing-module.md`](../competitive-outsourcing-module.md) |
| 2026-08-20 | v1 落地：T1–T7 全部完成；`SalesBizMode`/`SalesOrder.biz_mode`、确认生产用料全标客供、毛利 biz_mode+加工费文案+profit_report 分组、`subcontract_service` 客供损耗对账进今日行动、单测 6 条 |
