# A2b 设计：质量预警浅层

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §3 A2b
> **对象：** `WorkLog` 报工不良（复用既有字段，不新建质检档案）

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_a2b_quality_alert.py` 7 passed |
| 服务 | `list_quality_alerts` 可调用；Dashboard chip 已挂 |
| 今日行动 | `quality_watch` 可带 evidence |

---

## 1. 目标与边界

**目标**
PMC/质检不必等出货/客户投诉才发现问题：系统按「款×工序」近 N 日不良率与同工序均值对比，超出阈值即出 **2–5 个 chip**（工作台/今日行动皆可见），附一句抽检建议，一眼看到该抽查哪款哪道工序。

**不做**

- 不做异常检测/聚类/时序模型（sklearn 留 P3）；本轮仅规则阈值
- 不做质检档案、抽检任务闭环（可后置接 B1b 返修任务，见 §6 备注）
- 不改 `analyze_quality`（整体工序不良率）本身，只新增更细粒度（款×工序）的浅层预警，二者并存

---

## 2. 口径（规则，非黑盒）

**样本**：近 `days`（默认 14，范围 7–60）日 `WorkLog.status = valid` 报工，按 `own_product_id × process_id` 分组求 `qualified_qty` / `defect_qty` 之和。

**基线**：同工序（跨全部款）近同窗口不良率均值 `baseline_rate_pct`。

**突增判定**

```text
sample_qty = qualified + defect
rate_pct   = defect / sample_qty * 100
threshold  = max(QUALITY_ALERT_MIN_RATE_PCT, baseline_rate_pct * QUALITY_ALERT_SPIKE_MULTIPLIER)
alert  ⇔  sample_qty ≥ QUALITY_ALERT_MIN_SAMPLE(10) 且 defect_qty > 0 且 rate_pct ≥ threshold
```

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `QUALITY_ALERT_MIN_SAMPLE` | 10 | 样本太小不判定，避免小样本假警 |
| `QUALITY_ALERT_MIN_RATE_PCT` | 5.0 | 绝对下限，避免基线过低时轻微波动也报警 |
| `QUALITY_ALERT_SPIKE_MULTIPLIER` | 1.6 | 相对基线倍数 |

**严重度**：`rate_pct ≥ 15` 或 `rate_pct ≥ baseline_rate_pct × 2.2` → `high`；否则 `medium`。

**排序**：`defect_rate_pct` 降序，同值按 `sample_qty` 降序；接口层最多返回 `limit`（默认 5，范围 2–5）条。

---

## 3. 服务

`app/services/analytics.py`

| 函数 | 说明 |
|------|------|
| `list_quality_alerts(db, tenant_id, *, days=14, limit=5)` | 返回款×工序不良率突增 top issues；无数据/无突增均给出空态摘要 |

返回形状（与其它 `analyze_*` 一致，便于复用 `run_analysis` / 军师工具）：

```text
analysis_id: "quality_alerts"
title / as_of / summary / insights
data:
  days
  alerts: [{ own_product_id, product_code, process_id, process_name,
             defect_rate_pct, baseline_rate_pct, sample_qty, defect_qty,
             severity, chip_label, suggestion }]
  count        # 全部命中数（未截断）
  min_sample
chart          # top 的不良率柱图，无数据为 null
```

`chip_label` 形如 `A1×车帮 不良18.0%`；`suggestion` 形如「建议抽检：A1 在「车帮」，近14日不良率 18.0%（同工序均值 5.2%），加严抽检本批次并复核工艺/来料。」

已注册进 `ANALYSIS_RUNNERS["quality_alerts"]`，可用 `scripts/run_analytics_report.py --kind quality_alerts` 核对。

---

## 4. API（复用现有 analytics/军师指标通道，未新开路由）

`POST /schedule/agent/metrics/query`，`metric_id = "analytics.quality_alerts"`，`params: { days?, limit? }`。

权限：`menu.work_logs`（与 `analytics.quality_hotspots` 同口径）。

新增指标条目见 `workshop_metrics.METRIC_CATALOG`；`list_metrics()` 亦可发现。

---

## 5. 今日行动 / UI

**今日行动**（`build_today_actions`，规则路径）
`quality_watch` action 复用现有整体不良率触发条件，新增：`quality_alerts` 命中任一条即追加触发（即使整体不良率 &lt;3%，只要有款×工序突增也会出现）；`facts` 追加 top3 `chip_label`；`do` 追加首条 `suggestion`；命中 `high` 严重度时 action 本身升级为 `high`；`extra.quality_alerts` 挂 top5 供前端/军师取用。

**工作台**（`DashboardView.vue`）
「今日 3 件事」下方新增小节「质量预警」：横向 chip 列表（2–5 个），`el-tooltip` 悬停展示 `suggestion`；点击 chip 跳转 `/admin/work-logs`。无命中时整节隐藏（不占位、不当异常）。

---

## 6. 与既有能力的边界

- 与 `analyze_quality`（整体工序不良率，`analytics.quality_hotspots`）并存：后者是「哪个工序总体不良高」，本设计是「哪个款在哪个工序偏离该工序自身均值」，粒度更细但仍是规则阈值。
- 与 B1b 不良→返修任务：本设计只出「建议抽检」文案，不自动派返修单；抽检后若确认不良仍走现有报工/返修流程（`okr-roadmap-triage.md` 已记「B1b 与质量预警 A2b 合流」为后续可选项，不在本轮范围）。
- 与 A3 质量根因（多维交叉/帕累托）：留 P3，本设计不做工人×款×情境交叉。

---

## 7. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A2b-T1 | `list_quality_alerts` 规则函数 + 单测 | ✅ |
| A2b-T2 | 指标 `analytics.quality_alerts`（复用现有 metrics 通道） | ✅ |
| A2b-T3 | `build_today_actions` 接入 `quality_alerts` 证据 | ✅ |
| A2b-T4 | 工作台「质量预警」chip 小节 | ✅ |
| A2b-T5 | 总纲状态 → ⚠️ 已实现待走查 | ✅ |
| A2b-T6 | 产品走查签字（真实突增样例 + 阈值可调） | ⬜ 待走查 |

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并实现 T1–T5；待 T6 走查签字 |
