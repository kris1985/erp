# A2e 设计：实耗 vs 标准损耗预警

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §3 A2e
> **对象：** 生产单用料行 `OrderMaterialRequirement`（复用既有字段，不新建 BOM/损耗档）

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_a2e_loss_variance.py` 通过（与 B2c 合计 14） |
| API | `GET /analytics/loss-variance` 200 |

---


## 1. 目标与边界

**目标**
PMC/老板不必靠老师傅估算：系统按 BOM 标准（单耗 × 双数 ×(1+损耗率) + 固定损耗）自动核对「已发/已耗」是否明显超标，超标行进今日行动或小面板，一眼看到哪张单哪个物料超了多少。

**不做**

- 不做裁断排版 AI、不做新的材质标准损耗档案（沿用用料行现有 `loss_rate` / `loss_fixed_qty`）
- 不做完整成本会计/差异分摊，只做「预警」，不改用料行数据、不阻断发料
- 不接军师工具链（No AI nesting）：v1 只是规则扫描 + API + 看板小面板，不新增 Agent 工具

---

## 2. 口径（规则，非黑盒）

**标准应耗（复用字段，不重算）**

```text
standard_required = row.required_qty
  # 已由 material_service.calc_required_qty[_sized] 落库维护：
  # qty_per_pair * pairs * (1 + loss_rate) + loss_fixed_qty
```

**实耗** `row.issued_qty`（已发料，领料/发车间累计）。

**超标判定**

```text
over = issued_qty > standard_required * (1 + threshold)
threshold 默认 10%（可传参覆盖）
```

- `standard_required = 0` 且 `issued_qty > 0`：视为超标（分母为 0 时无法算比例，`over_pct` 记 `None`，仍进列表）。
- `is_customer_supplied` 行同样参与判定（客供物料浪费也是浪费），前端标注区分。

**扫描范围（v1，够用即可，非全库慢查询）**

- `tenant_id` 当前租户
- 生产单未取消（排除 `cancelled`），默认取 `created_at` 最近 `days`（默认 90 天）
- 每次最多扫 `order_limit`（默认 300 单）；超标行本身不设上限，接口层再截断展示条数

**排序**：超标量 `over_qty` 降序（超标绝对值大的先看）。

---

## 3. 服务

`app/services/loss_variance_service.py`

| 函数 | 说明 |
|------|------|
| `scan_loss_variance(db, tenant_id, *, threshold, days, order_limit)` | 返回超标用料行明细列表 |
| `loss_variance_summary(db, tenant_id, *, threshold, days, limit)` | 汇总（计数/涉及单数/Top 明细/人话摘要），供 API 与今日行动复用 |

明细字段：`requirement_id / order_id / order_no / customer_name / is_rush / delivery_date / supplier_product_id / supplier_product_code / supplier_product_name / qty_per_pair / loss_rate / loss_fixed_qty / required_qty / issued_qty / over_qty / over_pct / is_customer_supplied / consume_process_name`。

---

## 4. API

`GET /analytics/loss-variance`

| 参数 | 说明 |
|------|------|
| `threshold` | 超标阈值（小数，默认 0.10） |
| `days` | 扫描窗口天数（默认 90） |
| `limit` | 返回明细条数上限（默认 20） |

响应：`{ as_of, threshold_pct, days, flagged_count, order_count, summary, rows[] }`

权限：与「缺料」同口径，登录即可读（前端菜单权限 `menu.material_shortages` 或 `menu.orders` 控制入口显隐）。

---

## 5. 今日行动 / UI

**今日行动**（`build_today_actions`，规则路径，不经军师）
超标行数 ≥1 时追加一条 `id=loss_variance` 的 Action（`severity` 按超标行数分高/中），`evidence.facts` 列出 Top 物料超标摘要与单号，`ui_path=/admin`（点开后走看板小面板，v1 不建独立落地页）。

**看板小面板**（`DashboardView.vue`）
- 「今日关注」新增一块 `损耗超标` 计数 tile；
- 「马上处理」区新增小卡片「损耗超标」：chip 列表（订单号 · 物料 · 超 X% / 超 N），点击 chip 深链 `/admin/orders?open={order_id}`（复用现有订单详情「用料」tab 自动跳转），不建独立列表页。

---

## 6. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A2e-T1 | `loss_variance_service`：扫描 + 汇总 + 单测 | ✅ |
| A2e-T2 | API `GET /analytics/loss-variance` | ✅ |
| A2e-T3 | 今日行动追加 `loss_variance` action | ✅ |
| A2e-T4 | 看板「损耗超标」tile + chip 列表 | ✅ |
| A2e-T5 | 总纲状态 → ⚠️ 已实现待走查 | ✅ |
| A2e-T6 | 产品走查签字（真实超标单样例 + 阈值可调） | ⬜ 待走查 |

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并实现 T1–T5；待 T6 走查签字 |
