# A0 设计：今日 3 件事

> **状态：** 已验收（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 A0  
> **分析细项：** [`analytics-decision-roadmap.md`](../analytics-decision-roadmap.md) P0/A0  
> **过审后：** 按下节「生产任务单」开干；未过审不写码。

---

## 1. 目标与边界

**目标**  
厂长/PMC 打开工作台或军师，看到 **最多 3 条**可执行「今日事」，每条有证据，一点跳到落地页；**关掉军师仍可用**。

**不做（本设计）**

- ML / sklearn  
- 第 4–N 条当主 UI（完整列表可仅 API/军师调试保留）  
- 新报表中心、改齐套/库存模型  
- 强制用大模型生成 top3（规则引擎为准）

---

## 2. 现状（实现基线）

| 已有 | 缺口 |
|------|------|
| `build_today_actions`：规则汇聚交期/齐套/负荷/采购/财务/质量 | 返回最多 **8** 条；无统一 `id` / `evidence` / `top3` |
| Metric `analytics.today_actions`；军师可 `query_metric` | 权限仅 `menu.orders`，纯排产角色可能拉不到 |
| 军师快捷语「今日行动清单」 | 开场无 top3 卡片；答复未强制绑 evidence |
| 工作台「今日关注」计数/列表 | **无**「今日 3 件事」行动卡 |

规则来源保持现有分支（可排、等料、半齐套、保交期、削峰、催料、亏损、不良、空态巡检）；本设计只 **收敛契约 + UI + 权限 + Agent 约束**，不重写诊断算法。

---

## 3. API / 数据契约

### 3.1 响应形状（`build_today_actions` / metric.data）

```text
analysis_id: "today_actions"
title / as_of / summary          # 保留
data:
  actions: Action[]             # 完整候选，≤8（含空态 1 条巡检）；供调试/周报复用
  top3: Action[]                # = actions 按现有排序截断前 3；主 UI 只吃这个
  suggested_memories: [...]     # 保留，非 P0 UI 必显
  playbook: [...]               # 保留
```

### 3.2 Action 字段（每条必填）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 稳定短码，如 `kit_schedule` / `kit_blocked` / `delivery_risk` / `capacity_peak` / `supply_chase` / `finance_loss` / `quality_watch` / `capacity_calib_{process}` / `patrol` |
| `priority` | int | 保留现排序键 |
| `severity` | `high`\|`medium`\|`low` | 保留 |
| `title` | string | 短标题（展示） |
| `why` | string | 一句话原因 |
| `do` | string | 建议动作 |
| `ui_path` | string | 前端路由，如 `/admin/schedule` |
| `agent_next` | string[] | 军师工具提示，保留 |
| `evidence` | object | **新增，必填** |

### 3.3 `evidence`（必填）

```text
evidence:
  source: string          # 如 analytics.kit_ready / analytics.delivery_risk
  facts: string[]         # 1–5 条可读事实，禁止空数组（空态巡检除外可 1 条说明无告警）
  order_nos: string[]     # 相关生产单号，可 []
  order_ids: int[]        # 可选，有则带，便于深链
  extra: object           # 可选：缺料行摘要、负荷热点等已有字段挪入，勿丢信息
```

**facts 示例**

- 「急/险齐套可排 3 单：PO-…」  
- 「首道缺料：大底黑 42 差 120」  
- 「逾期急单 2；今日交期风险单 1」  

缺料类尽量带已有 ETA 字样（有则写入 facts，无则省略，不编造）。

### 3.4 空态

无高优告警时：`actions` / `top3` 仍为 **1 条** `id=patrol`（维持巡检），`severity=low`，`ui_path=/admin`，facts 说明未见高优告警。  
前端展示为正常卡片，不当成错误。

### 3.5 权限

Metric `analytics.today_actions`：`menu.orders` **或** `menu.schedule`（任一即可）。  
无权限：接口 403 或 metric 层拒绝；前端工作台卡片隐藏或提示无权限，**不 500**。

---

## 4. UI

### 4.1 工作台 `/admin`（主路径，无 AI）

- 在「今日关注」**上方或替代其行动位**：卡片标题 **「今日 3 件事」**。  
- 只渲染 `data.top3`（≤3）。  
- 每条：`title` + 1 行 `why` 或首条 `facts` + 严重度色点；整卡或按钮点击 `router.push(ui_path)`。  
- 加载中/失败：骨架或「暂不可用」；空权限见上。  
- **不**在此展开完整 8 条。

### 4.2 军师（排产助手等）

- **开场**：拉取同一 metric，展示 top3 卡片（与看板同源）；点击某条可填入聚焦追问（如「只讲 {title}，引用 evidence」）。  
- **对话**：系统/工具说明约束——讲今日行动时 **只陈述 top3**，每条必须点到 `evidence.facts` / 单号；禁止编造未在 evidence 中的日期与数量。  
- 快捷语可改为「先给我今日 3 件事（top3+证据）」；旧「行动清单」可保留但答复仍以 top3 为主。

### 4.3 跳转映射（沿用并固定）

| 行动类型（id 前缀） | ui_path |
|---------------------|---------|
| kit_schedule / delivery / capacity_peak | `/admin/schedule` |
| kit_blocked / supply_* | `/admin/purchase` |
| capacity_calib | `/admin/workshop-settings` |
| finance_loss | `/admin/profit` |
| quality_* | `/admin/work-logs` |
| patrol | `/admin` |

P0 **不做** 深链到具体 `order_id` 详情（有 ids 可后续加 query）；先到列表/功能页即可。

---

## 5. Agent / Metric

- `workshop_metrics`：permissions 改为 orders **或** schedule。  
- `schedule_agent` 提示词：今日行动 = top3 + 必须引用 evidence；可排仍提醒人工确认方案。  
- 单测：`top3` 长度 ≤3；每条含非空 `id`、`evidence.facts`（patrol 除外至少 1 条说明）；排序与截断稳定。

---

## 6. 验收对照（签收用 §7）

| §7 通过标准 | 本设计落点 |
|-------------|------------|
| ≤3 条 + 空态 | `top3` + patrol |
| 证据非空洞 | `evidence.facts` 必填 |
| 跳转匹配 | `ui_path` 表 |
| 关 AI 可用 | 工作台卡片 |
| 权限不 500 | 双 menu + UI 降级 |

---

## 7. 生产任务单（过审后拆开）

| 任务 | 内容 | 依赖 |
|------|------|------|
| **A0-T1** | 后端：Action 补 `id` + `evidence`；产出 `top3`；单测 | — | ✅ |
| **A0-T2** | Metric 权限：`menu.orders` ∨ `menu.schedule` | T1 | ✅ |
| **A0-T3** | 工作台「今日 3 件事」卡片 + 跳转 | T1 | ✅ |
| **A0-T4** | 军师开场 top3 + prompt 约束引用 evidence | T1–T2 | ✅ |
| **A0-T5** | 产品走查签字（看板→落地 ≤3 步；关军师重走） | T3–T4 | ✅ |

预估：小迭代（约 1 人·数日量级）。  
顺序建议：T1 → T2∥T3 → T4 → T5。

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿，待过审 |
| 2026-08-09 | 过审并实现 T1–T4；待 T5 走查 |
