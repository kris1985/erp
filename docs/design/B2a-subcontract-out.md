# B2a 设计：外发工序单（我们发包出去）

> **状态：** v1 已落地（2026-08-20）；见 §6 任务打勾  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md)（B2a · P2-Must；§7 验收标准）  
> **竞品分析：** [`competitive-outsourcing-module.md`](../competitive-outsourcing-module.md)（2026-08-20）  
> **镜像：** [`B1d-subcontract-in.md`](./B1d-subcontract-in.md)（承接外包=承揽方；本文=发包方）  
> **对象：** `SubcontractOrder`（外发单）+ `SubcontractIssue`（发料流水）+ `SubcontractReceipt`（收回流水）+ `Payable`（加工费应付）  
> **复用：** A2e 损耗口径（[`A2e-loss-variance.md`](./A2e-loss-variance.md)）· 执行单头关联（`ExecutionHeader`）· 应付（`ap_service`）· 供应商（`Partner`）

---

## 1. 目标与边界

**目标**  
把「发出去的工序回不来、回来多少说不清、损耗算谁的」这一外协第一痛点收口为**一张外发单**的闭环：

```text
外发单(下达) → 发料 → 厂外加工 → 收回
                              ↘ 欠数 = 发 − 收（未收回在途）
                              ↘ 损耗 = 发 − 收（对照 BOM 标准后预警，后置 A2e 阈值）
                              ↘ 加工费 = 收回 × 单价 → 自动生成外加工商应付
```

**v1 范围（对齐路线图 B2a 验收）**

- 外发单按**工序**建模（把某道工序发出去），数量按**双/件**对账；供应商=外协厂。
- 发料/收回走**手工登记数量**（扫码/PDA 后置，B2a+）。
- 加工费按**收回数量 × 单价**结算，收回时自动挂一笔 `Payable`（外加工商应付）。
- 欠数列表可查；发/收/损耗在单上可见。

**不做（明确）**

- 多工厂 APS；外协厂产能/自报进度 SCM（B2a+）
- 材料级委外（发具体物料出去加工再收物料，需 BOM 物料维度对账）——单独立项
- 完整损耗责任判定（谁赔）；v1 只展示发收差，超阈值预警后置
- 成鞋外的鞋底专版

---

## 2. 定位：与 B1d 承接外包的镜像

| | 外发 B2a（发包方） | 承接外包 B1d（承揽方） |
|---|---|---|
| 我们是谁 | 上家 | 外协厂 |
| 物料谁出 | **我们发料出去** | 上家供料（客供） |
| 钱怎么走 | **付加工费 → `Payable`** | 收加工费 → `Receivable` |
| 典型工序 | 针车/硫化发出去 | 针车来料加工 |

两态可共用一套「外协」抽象（`Partner` 既是上家也是下家），但**单据各自独立**：B1d 几乎零新表；B2a 需外发单 + 发/收流水。

---

## 3. 主路径

1. 建**外发单**：选供应商（外协厂）+ 工序 + 关联生产单/执行单 + 外发数量 + 加工费单价。  
2. **发料**：登记发出数量（累加 `issued_qty`，写 `subcontract_issues`）。  
3. **收回**：登记收回数量（累加 `received_qty`，写 `subcontract_receipts`），自动生成加工费应付。  
4. **欠数**：`欠数 = 发 − 收`，未收回列表可查。  
5. **损耗**：`损耗 = 发 − 收`，在单上可见。  
6. **对账**：收回累计应付 → 应付台账（复用 `menu.payables`）。

---

## 4. 数据

### 4.1 新表

**`subcontract_orders`（外发工序单）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id / tenant_id | | |
| subcontract_no | String(50) | 单号（租户内唯一） |
| partner_id | FK partners | 外协厂 |
| process_id | FK process_definitions, nullable | 外发工序（可空=未指定） |
| process_name | String(50) | 工序名快照 |
| order_id | FK orders, nullable | 生产单（桥接，可追溯） |
| header_id | FK execution_headers, nullable | 执行单头（K4 主键） |
| execution_id | FK spec_execution_orders, nullable | 码明细（更细） |
| own_product_id | FK own_products, nullable | 产品（展示用） |
| total_qty | Integer | 计划外发量 |
| issued_qty | Integer | 已发累计（缓存） |
| received_qty | Integer | 已收累计（缓存） |
| unit_price | Numeric(14,4) | 加工费单价（元/双） |
| status | Enum | draft/issued/partial_received/received/cancelled |
| notes | Text | |
| created_by / created_at / updated_at | | |

**`subcontract_issues`（发料流水）**：`id/tenant_id/subcontract_order_id/qty/note/created_by/created_at`

**`subcontract_receipts`（收回流水）**：`id/tenant_id/subcontract_order_id/qty/defect_qty(可空)/note/created_by/created_at`

### 4.2 Payable 扩展（加工费 → 应付）

`Payable` 现 `purchase_order_id` NOT NULL（只服务采购到货）。扩展：

- `purchase_order_id` → **nullable**
- 新增 `subcontract_order_id` FK `subcontract_orders.id`（nullable）

收回时按 `qty × unit_price` 生成一笔应付，`notes` 记外发单号。应付台账（`menu.payables`）可读到，来源为外发单时展示外发单号。

### 4.3 口径

| 口径 | 公式 | 含义 |
|------|------|------|
| 已发 | Σ issues.qty | 发出去的双数 |
| 已收 | Σ receipts.qty | 收回来的双数 |
| 欠数（在途） | 已发 − 已收 | 还没回来的 |
| 损耗 | 已发 − 已收（v1 直接展示；A2e 阈值预警后置） | 对不上账的量 |

状态机：`draft → issued`（首次发料）→ `partial_received`（部分收回）→ `received`（已收 ≥ 已发或人工结单）；`cancelled`（取消）。

---

## 5. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/subcontract-orders` | 列表；`status` / `outstanding`（欠数>0）筛选 |
| POST | `/subcontract-orders` | 建外发单 |
| GET | `/subcontract-orders/{id}` | 详情（含发/收流水） |
| PATCH | `/subcontract-orders/{id}` | 改单/取消 |
| POST | `/subcontract-orders/{id}/issues` | 发料登记 |
| POST | `/subcontract-orders/{id}/receipts` | 收回登记（自动挂应付） |
| GET | `/subcontract-orders/{id}/issues` | 发料流水 |
| GET | `/subcontract-orders/{id}/receipts` | 收回流水 |

权限：新 `menu.subcontract_out` + `btn.subcontract_out.write`；默认授权 `manager` / `merchandiser` / `warehouse`（PMC/采购/仓）。

---

## 6. 任务

| ID | 内容 | 依赖 |
|----|------|------|
| B2a-T1 | `SubcontractOrder`/`SubcontractIssue`/`SubcontractReceipt` 模型 + `SubcontractOrderStatus` + `ensure_schema` 迁移 | — ✅ |
| B2a-T2 | `Payable.purchase_order_id` 改 nullable + `subcontract_order_id` 列 | T1 ✅ |
| B2a-T3 | `subcontract_out_service`：建单/发料/收回/欠数/损耗 + 收回挂应付 | T1/T2 ✅ |
| B2a-T4 | API + 权限（`menu.subcontract_out` / `btn.subcontract_out.write` + 默认授权） | T3 ✅ |
| B2a-T5 | 前端：侧栏「外发」菜单 + 外发单列表/新建/详情 + 发料/收回 | T4 ✅ |
| B2a-T6 | 单测（发收对账、欠数、损耗、加工费应付、关联追溯）+ seed | T3–T5 ✅（`tests/test_b2a_subcontract_out.py` 3 passed） |
| B2a-T7 | 总纲挂 B2a ✅ + 本文档链接 | 全部 ✅ |

**验收口径（对齐路线图 §7）：** 一单外发可跑通「建单(工序/供应商/关联单) → 发料 → 收回 → 欠数可查 → 加工费挂应付」；① 发与收数量可对账 ② 损耗可见 ③ 与生产单/指令可追溯 ④ 未收回欠数列表可用。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-20 | 初稿：工序外发单 + 发/收流水 + 加工费应付；源自 [`competitive-outsourcing-module.md`](../competitive-outsourcing-module.md) 与路线图 §7 B2a |
| 2026-08-20 | v1 落地：T1–T7 全部完成；`SubcontractOrder`/发料/收回/欠数/损耗、收回挂应付（`Payable.subcontract_order_id`）、关联追溯、`menu.subcontract_out` + `/admin/subcontract-out` 页、单测 3 条 |
