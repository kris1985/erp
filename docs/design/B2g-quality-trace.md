# B2g 设计：品质追溯（不良可反查）

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §3 / §7 B2g  
> **上游：** B1b 不良→返修 · 捆标 `TraceUnit` · A2b 质量预警 · B0b 流转卡  
> **架构：** §9（有条件批准已收口）  
> **竞品口径：** 捆级责任线索、可解释可改责；不对齐单双一码 / 视觉定责

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `tests/test_b2g_quality_trace.py` 6 passed；B1b 回归 3 passed |
| 服务层演示脚本 §7.4 | 9/9 通过（捆码流水、建议 medium/high、强/弱筛、硬拦、集体 none、单号/不良 ID、改责 note） |
| 演示库 API | `GET /quality-trace?q=230711` → 单头+1 捆；`q=TU1-000001` → logs≥3；`suggest-responsible?process_id=2` → 张三 high+basis；无捆 POST → `本单有进行中捆…`；`trace_quality=weak` 可筛 |
| UI | 不良台 Tab「列表/追溯」已挂；A2b chip → `/admin/defects?mode=trace` |

## 0. 问题与目标

**痛点**  
投诉/后道不良时，能力散落在捆标页、不良台、报工废数、A2b 预警，缺「一页反查」。

**目标**  
在**不良管理内嵌「追溯」模式**：用生产单号 / 捆标码 / 不良 ID 反查  
**单 → 捆 → 过站流水 → 不良事件 → 责任线索 → 返修状态**；  
登记时有进行中捆则**硬拦无捆提交**；责任建议带**依据 + 候选 + confidence**。

**角色**  
质检 / 组长 / 跟单（读 + 登不良）；改责 / 派返修：admin、manager、leader（沿用 B1b）。

---

## 1. 定稿决策（原 OPEN 已勾）

| 项 | 定稿 |
|----|------|
| 无捆提交 | 该生产单存在 **open / in_process** 捆时 → **硬拦**必须选捆；无此类捆时允许无捆，派生 `trace_quality=weak` |
| 入口 | **不良台内嵌**：`/admin/defects?mode=trace`（Tab「追溯」）；**不**新建独立菜单 |
| A2b 深链 | 仅带 query 跳转不良台（`mode=trace` 或列表筛）；**不做**「款×工序相关捆」聚合 |
| 演示数据 | seed/走查租户样例款必须 `trace_enabled=true`，且有挂捆报工流水 |
| 责任建议与工资 | **禁止**写入计件/奖罚自动流；文案固定为「建议/线索」 |
| 报工补登 | v1 **不做**（不写 `source_work_log_id`） |
| 审计表 | v1 **不做**；改责仅追加系统 note |

---

## 2. 边界（不做）

| 不做 | 说明 |
|------|------|
| 单双一码 / piece 强制 | — |
| 视觉质检、AI 定责 | P∞ |
| IPQC 巡检工单 / ISO 质检档案 | 后置 |
| 集体工序自动定个人 | 建议 `confidence=none`，文案「集体工序不定个人」 |
| `WorkLog.defect_qty` → 自动 `DefectEvent` | 双口径分离 |
| 新质量中台 / 复制流水查询核心 | 门面编排现网 API |
| 独立 `menu.quality_trace` | 复用 `menu.defects` |
| 责任建议驱动扣款 | 硬禁 |

**双口径：** 追溯 UI **只展示 `DefectEvent`**；不与报工废数混成一张「真相表」。

---

## 3. 主路径

### 3.1 投诉反查

1. 打开不良台 → Tab「追溯」（或 `?mode=trace`）  
2. 输入：生产单号 **或** 捆标码 **或** 不良事件 ID  
3. 展示：单头；捆摘要列表（分页）；选中捆的时间线；该捆/该单不良（含返修 pending 信息，复用 `defect_out`）  
4. 从不良行可派返修 / 改责（现网能力）；可切回「列表」Tab  

**演示口径：** 已知捆码 → ≤3 次操作看到责任建议工人及依据。

### 3.2 登记硬化

1. **捆标页**登记：选责任工序后拉建议；展示 `basis`、`candidates`、`confidence`；可一键采用或手改  
2. **后台登记：**  
   - 选定生产单后加载捆下拉  
   - 若存在 open/in_process 捆且未选 `trace_unit_id` → API/UI **硬拦**（`trace_unit_required`）  
   - 无此类捆 → 允许无捆；列表 `trace_quality=weak`  
3. **改责：** PATCH 变更 `responsible_worker_id` 时，自动追加 note：`[改责] {old}→{new} by user#{id} @ {iso}`  

### 3.3 A2b 深链

Dashboard / 今日行动 A2b chip →  
`/admin/defects?mode=trace&product_code=…&process_id=…`  
（或列表模式筛不良；v1 不保证「相关捆」面板。）

---

## 4. 口径

### 4.1 追溯粒度

```text
可承诺：生产单 × 捆 × 责任工序 → 责任工人线索（该捆 TraceUnitLog.report 最近个人报工）
不承诺：单双唯一责任人；集体定个人；无捆 100% 可追
```

### 4.2 责任建议（扩展现网，不新开平行 API）

**算法（保持）：**  
`TraceUnitLog`：`action=report` ∧ `process_id=责任工序` ∧ `worker_id≠null`，按 id 倒序；集体工序类型 → 无建议。

**响应扩展** `GET /trace-units/{unit_id}/suggest-responsible?process_id=`：

| 字段 | 规则 |
|------|------|
| `worker_id` / `worker_name` | 主建议（最近一条）；可 null |
| `basis` | 人话，如「该捆 · 车帮 · 最近报工 · 张三 · 2026-08-09 14:22」；集体：「集体工序，不自动建议个人」 |
| `candidates` | 最多 3 条：同捆同工序不同工人（或同人多次取最近），`{worker_id, worker_name, at, log_id}` |
| `confidence` | `high`=该工序仅一人出现；`medium`=多人取最近；`none`=无流水或集体 |

### 4.3 `trace_quality`（派生，不落库）

| 值 | 条件 |
|----|------|
| `strong` | 有 `trace_unit_id`，且（有 `responsible_worker_id` **或** 责任工序为集体已注明） |
| `partial` | 有捆、个人责任工序、无责任人 |
| `weak` | 无 `trace_unit_id` |

`GET /defect-events` 增加可选 `trace_quality=` 筛选；`defect_out` 增加字段 `trace_quality`。

### 4.4 硬拦规则

```text
create_defect / 后台登记：
  IF order_id 已选
     AND EXISTS TraceUnit(order_id, status ∈ {open, in_process})
     AND trace_unit_id IS NULL
  THEN Material/TraceError("trace_unit_required", "本单有进行中捆，请选择捆标后再登记")
```

捆标页登记本身已带 `trace_unit_id`，不受影响。

---

## 5. 数据与 API

**复用（禁止复制实现）：**

| 现网 | 用途 |
|------|------|
| `GET /trace-units/by-code/{code}` | 码反查 |
| `GET /trace-units/{id}` → `unit_detail_dict` | 时间线 + 不良 |
| `GET /orders/{id}/trace-units` | 单下捆列表 |
| `GET /defect-events` · `PATCH` · 返修 | 不良/改责/B1b |
| `suggest_responsible_worker` | 建议内核 |

**新增 / 变更：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quality-trace` | **门面**：`q` 自动识别 order_no / unit code / defect id；拼装 `{order, units_summary, focus_unit?, defects_summary}`；units 分页；**详情 logs 仅在 focus 时取自 unit_detail** |
| GET | `/trace-units/{id}/suggest-responsible` | **扩展**响应字段（见 §4.2） |
| POST | `/defect-events` | 增加硬拦 §4.4 |
| GET | `/defect-events` | `trace_quality` 筛；out 带 `trace_quality` |
| PATCH | `/defect-events/{id}` | 改责写系统 note |

**不做的 API：** `/defect-events/{id}/responsibility-suggest`；`/quality-trace/units/{id}`（直接用现网 unit 详情）。

权限：读写均挂 `menu.defects`（与现网不良台一致）。

---

## 6. UI

| 面 | 要求 |
|----|------|
| 不良台 | Tab：`列表` \| `追溯`；追溯区：单搜索框 + 结果一页；空态提示开 `trace_enabled` / 打捆 |
| 捆时间线 | 工序/人/动作/时间；不良节点高亮；展示 pending 返修若有 |
| 列表 Tab | 列「追溯」强度；筛弱追溯；行「打开追溯」→ `mode=trace&q=` |
| 登记弹窗 | 捆必选（有进行中捆时）；建议区展示依据/候选/confidence 标签 |
| 文案 | 责任人旁标注「线索」；禁止「认定责任」用语 |

---

## 7. 验收标准（签收用）

> 产品 + 研发对下列条款逐条勾选；任一条未过不算 B2g 完成。兼总纲 §7.0 通用 DoD。

### 7.1 功能通过标准

| # | 标准 | 验证方式 |
|---|------|----------|
| A1 | 不良台「追溯」Tab：输入**生产单号**可展示单头 + 捆摘要（有捆数据时） | 走查 |
| A2 | 输入**捆标码**可展示该捆时间线，且至少 1 条 report/过站流水（样例数据） | 走查 |
| A3 | 输入**不良事件 ID**可定位到关联单/捆（有捆则 focus 该捆） | 走查 |
| A4 | 有捆登记不良：建议接口返回非空 `basis`；UI 可见依据文案 | 走查 + API |
| A5 | 责任工序为**集体**：`confidence=none`，文案含「不定个人」，不瞎填工人 | 单测 + 走查 |
| A6 | 同捆同工序多人报工：`confidence=medium`，`candidates` ≤3 且含主建议 | 单测 |
| A7 | 生产单存在 open/in_process 捆时，无 `trace_unit_id` 创建不良 → **4xx** `trace_unit_required` | 单测 |
| A8 | 生产单**无**进行中捆时，允许无捆创建；列表 `trace_quality=weak` 可筛出 | 单测 + UI |
| A9 | 有捆无责任人（个人工序）→ `partial`；有捆有责任人 → `strong` | 单测 |
| A10 | 不良行 ↔ 追溯 Tab 可互跳；时间线上可见该捆不良及 pending 返修（有则） | 走查 |
| A11 | 改责后 note 含旧责任人→新责任人及操作者痕迹 | 走查 / DB |
| A12 | A2b chip 深链可打开不良台并带上 query（不报错即可；不验「相关捆」面板） | 走查 |
| A13 | **回归：** B1b 派返修/完成、集体返修仍禁、A2b chip、计件报工、捆标页登记不良 | 回归清单 |

### 7.2 负面标准（违反即失败）

| # | 不得出现 |
|---|----------|
| N1 | 新菜单 `品质追溯` 或平行 `menu.quality_trace`（本版） |
| N2 | 追溯页把 `WorkLog.defect_qty` 与 `DefectEvent` 混成同一「不良数」 |
| N3 | 责任建议写入工资/奖罚自动逻辑 |
| N4 | 新建 `defect_event_audits` 或 piece 级强制码 |
| N5 | 复制一套与 `unit_detail_dict` 分叉的流水查询实现且长期双维护 |

### 7.3 DoD

- [ ] §7.1 A1–A13 勾选通过  
- [ ] §7.2 N1–N5 抽检无违反  
- [ ] 单测：`test_b2g_quality_trace.py`（硬拦、suggest 扩展、trace_quality 派生）通过  
- [ ] 演示脚本（下方 §8）在演示环境走通；样例款 `trace_enabled=true`  
- [ ] 总纲 B2g 状态可更新为 ✅ 或 ⚠️ 注明剩余  
- [ ] 权限：无 `menu.defects` 不可写关键接口  

### 7.4 演示脚本（走查必跑）

```text
前置：样例生产单 O，款 trace_enabled；捆 U 有工序 P 的个人报工（工人 W）
1. 不良台 → 追溯 → 输入 U.code → 见流水含 W
2. 登记不良（捆 U，责任工序 P）→ 见依据含 W；confidence ≠ none
3. 列表筛强/弱追溯正常
4. 另建单仅无进行中捆 → 无捆登记成功且 weak
5. 单 O 仍有进行中捆 → 后台无捆提交失败
6. 派返修一条并完成或取消（B1b 回归）
```

---

## 8. 实现切片

| ID | 内容 | 退出 | 状态 |
|----|------|------|------|
| B2g-M0 | suggest 响应扩展；`trace_quality` 派生 + 列表筛；硬拦 §4.4；改责 note | 单测绿 | ✅ |
| B2g-M1 | `GET /quality-trace` 门面（编排现网）；不良台 Tab 追溯 UI | A1–A3、A10 | ✅ |
| B2g-M2 | 登记/捆标页建议 UI；弱追溯列与筛；硬拦前端 | A4–A9、A11 | ✅ |
| B2g-M3 | A2b 深链 query；演示 seed；走查 §7.4 | A12–A13、DoD | ✅ |

---

## 9. 架构约束（摘要）

1. **门面优先**：`/quality-trace` 只解析 `q` + 拼装；流水/不良细节走现网 dict。  
2. **大单**：捆列表分页；勿一次返回全单所有 logs。  
3. **建议只读 TraceUnitLog.report**；不扫未挂捆 WorkLog。  
4. 完整评审背景见修订前讨论；本版已吸收 C1–C6。

---

## 10. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 需求初稿 |
| 2026-08-09 | 架构有条件批准（原 §11） |
| 2026-08-09 | **定稿**：硬拦 + 不良台内嵌；收口 OPEN；完整验收 A1–A13 / N1–N5 / 演示脚本 |
| 2026-08-09 | **落地**：M0–M3；`test_b2g_quality_trace.py`；不良台追溯 Tab + `/quality-trace` |
| 2026-08-09 | **走查通过**：单测+演示脚本+演示库 API（230711 / TU1-000001 / 硬拦 / suggest） |
