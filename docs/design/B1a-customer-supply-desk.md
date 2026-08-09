# B1a 设计：客供收货台

> **状态：** 已验收（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 B1a  
> **对象：** 生产单用料行 `OrderMaterialRequirement`（`is_customer_supplied=true`）

---

## 1. 目标与边界

**目标**  
仓/跟单有独立「客供收货台」：看某单客供欠/到 → 登记到货 → 可催客户；齐套读 `arrived_qty`；成本仍不计客供。

**不做**

- 客户协同门户 / 客户自助登录  
- 客供进共享库存池  
- 改 BOM 默认客供矩阵（可后置；本版用料行标记即可）

---

## 2. 主路径

1. 生产单用料标「客供」（已有 PATCH / 台内标记）  
2. `/admin/customer-supply` 列表：生产单、物料、需求、已到、欠数、催办状态  
3. 「登记到货」→ 累加 `arrived_qty` + 写收货流水  
4. 「催客户」→ `chase_status=chased` + 备注/时间  
5. 欠清 → 可标 `cleared`（到货使 shortage≤0 时可自动 cleared）  
6. 齐套页同单行显示已到量，影响 `kit_ok`

---

## 3. 数据

**用料行增补**

| 字段 | 说明 |
|------|------|
| `customer_chase_status` | `open` / `chased` / `cleared`（仅客供有意义） |
| `customer_chase_note` | 催办备注 |
| `customer_chased_at` | 最近催办时间 |

**收货流水表** `customer_supply_receipts`

| 字段 | 说明 |
|------|------|
| order_id / requirement_id | 关联 |
| qty | 本次到货 |
| note / created_by / created_at | 痕迹 |

齐套：`shortage = required − arrived`（客供不吃池）——保持现状。  
成本：`finance_service` 跳过客供——回归。

---

## 4. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/customer-supply` | 客供行列表（可筛 order_no / chase_status / owed_only） |
| POST | `/customer-supply/{req_id}/receive` | 登记到货 |
| POST | `/customer-supply/{req_id}/chase` | 催办/清标记 |
| GET | `/customer-supply/{req_id}/receipts` | 流水 |

权限：`menu.customer_supply`（仓/PMC；admin 全开）。

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| B1a-T1 | 模型 + schema + 服务 | ✅ |
| B1a-T2 | API | ✅ |
| B1a-T3 | 收货台 UI + 菜单 | ✅ |
| B1a-T4 | 单测（收货→欠清、成本不计）+ seed | ✅ |
| B1a-T5 | 总纲挂设计 | ✅ |

---

## 6. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并开干 |
