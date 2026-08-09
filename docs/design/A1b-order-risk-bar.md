# A1b 设计：订单风险条

> **状态：** 已验收（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 A1b  
> **对象：** **生产单** `orders` 列表（主入口）

---

## 1. 目标与边界

**目标**  
PMC/跟单打开生产单列表，一眼区分红/黄/绿风险；悬停或点击可见可读原因 chip（交期、急单、缺料、齐套日、进度）。

**不做**

- 蒙特卡洛 / ML  
- 销售单列表风险条（可后置复用同一函数）  
- 改齐套/排产算法本身  

---

## 2. 口径（规则，非黑盒）

与看板 `at_risk` 对齐：`delivery_date ≤ today+2` 且整单进度 `< 90%` → `at_risk=true`。

| 等级 | 条件（取最高） | 列表色 |
|------|----------------|--------|
| **red** | 已逾期；或 `at_risk`；或（急单且缺料） | 危险 |
| **yellow** | 缺料未齐套；或急单；或交期 ≤ today+7 且进度 &lt; 100% | 警告 |
| **green** | 其余在制/确认单 | 成功 |
| **none** | 已完成 / 已取消 | 灰「—」 |

**不矛盾约束：** `at_risk=true` ⇒ 不得为 green。

**原因 chip（有则出，有序）：**

1. `overdue` 已逾期 N 天  
2. `delivery_risk` 交期风险（≤2 天且进度&lt;90%）  
3. `rush` 急单  
4. `material` 缺料未齐套  
5. `kit_ready` 预计齐套日 YYYY-MM-DD  
6. `progress` 进度 xx%  

---

## 3. API

`OrderOut` 增补：

```text
risk_level: "red" | "yellow" | "green" | "none"
risk_label: "高风险" | "关注" | "正常" | "—"
risk_reasons: [{ code, text }]
at_risk: bool   # 与看板同口径，便于计数对照
```

---

## 4. UI

生产单列表「风险」列：色 tag；`el-popover` 展示 chip 列表。

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A1b-T1 | `order_risk` 规则 + 单测（急单缺料 / 交期风险 / 正常） | ✅ |
| A1b-T2 | `OrderOut` + `_serialize_order` | ✅ |
| A1b-T3 | `OrdersAdminView` 风险列 | ✅ |
| A1b-T4 | 总纲挂设计 | ✅ |
| A1b-T5 | 走查签字：红/黄/绿样例 + at_risk 不矛盾 | ✅ |

---

## 6. 走查证据（2026-08-09）

| 等级 | 样例单 | 要点 |
|------|--------|------|
| 高风险 red | `26080702` | 已逾期 + 缺料；`at_risk=true` |
| 关注 yellow | `B1C-WALK` | 缺料 + 预计齐套日；非 at_risk |
| 正常 green | `260725` | 齐套；仅进度 chip |
| — none | `260701` | 已完成 |

约束：全库 `at_risk=true` 无 green；红/黄均有可读 reasons。单测 `tests/test_a1b_order_risk.py` 4 passed。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并开干 |
| 2026-08-09 | 走查通过，已验收 |
