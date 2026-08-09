# B2h-M1 实现设计：开裁生码 · 一单多码 · 扫主码即报

> **状态：** ✅ 已落地待走查（2026-08-09）  
> **需求总纲：** [`B2h-shop-floor-loop.md`](./B2h-shop-floor-loop.md) §1.3 D1–D6 · R21/R22/R23/R27/R28  
> **原则：** 做正确事；复用 `TraceUnit` / `create_bundle` / `POST /reports`，不新造账本主体。  
> **本切片不做：** M0 纯文案（可并行）、R5 合批成员派工（可后）、R9 按捆草稿、真合单。  
> **R5b 合批批量开裁：** 已落地（`POST /merge-batches/{id}/cut-cards` + 合批打印 `?mode=main-codes`）。

---

## 走查脚本（给验收）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 追溯款生产单 →「开裁打主码」→ 预览 → 确认 | 生成 TU*；跳转打印页多枚 QR |
| 2 | 手机扫其中一枚 QR → 登录工人 →「报本工序」 | 单/色/码/捆预填；提交成功 |
| 3 | 同码进不良登记 / 不良台追溯 Tab 反查 | 可见流水 |
| 4 | 作废：`POST /trace-units/{id}/void`（无报工的 open 码）后再报 | 不可报 |
| 5 | 已开裁单用工位选单报工（不传 create_trace_bundle） | **不**再静默平行起捆 |
| 6 | 再次开裁 only_missing | skip，不重复灌水 |

单测：`PYTHONPATH=. .venv/bin/pytest tests/test_b2h_m1_cut_cards.py -q`

---

## 0. 目标与非目标

**目标（验收对齐 E1/E2/E6/E7 + N2/N5）**

1. 开裁：生产单一键按策略生成 `TraceUnit`（一码一捆），进入打印。  
2. 打印：B0b `/admin/orders/print/:id` 升级为 **一单多码主码页**（可扫）。  
3. 报工：扫主码 → 单/色/码/捆预填；工序优先来自工位，否则手选。  
4. 互斥：已开裁生码的单，报工不再静默 `create_bundle_from_work_log`。  
5. 生命周期：补打同码；作废后不可报工。

**非目标**

- 整单一码当货上主码  
- 改排产/合批账本模型  
- 废除工位实体（只改角色）  
- 单双一码 / 拆 piece

---

## 1. 领域契约（写死）

| 概念 | 实现 |
|------|------|
| 货上主码 | `TraceUnit.code`（`TU{tenant}-{id:06d}`） |
| 一码一捆 | 一行生成结果 = 一个 `TraceUnit`（`unit_type=bundle`） |
| 开裁生码 | `created_from_work_log_id IS NULL` 且 `note`/`log` 标明开裁（见 §3） |
| 可报工状态 | `status ∈ {open, in_process}` |
| 作废 | `status → scrapped` + `TraceUnitLog.action=inspect` 或新增 `void` action（见 §3.4）；报工硬拦 |
| 工位 | 仅提供 `process_id` / `process_name`；不提供选单主路径 |

**默认生码策略（M1）**

```text
对每个 order_items 行（color_id + size_id + qty）：
  若 bundle_size 未传或 ≥ qty → 生成 1 个 TraceUnit(qty=行 qty)
  若 bundle_size = N < qty → 拆成 ⌈qty/N⌉ 个（末捆余数）
```

色或码为空的行：跳过并在预览里标红（须先维护色码）。

---

## 2. API

### 2.1 开裁预览 / 生成（新）

`POST /orders/{order_id}/cut-cards`

权限：admin / manager / leader（与订单打印同级）；工人不可。

**Body**

```json
{
  "dry_run": true,
  "bundle_size": null,
  "only_missing": true
}
```

| 字段 | 含义 |
|------|------|
| `dry_run` | true=只预览不写库 |
| `bundle_size` | null=每色码行一捆；正整数=按 N 双拆 |
| `only_missing` | true（默认）：已有**未作废**且同色码覆盖的开裁捆则跳过；false：仍禁止对已覆盖行重复灌水，仅允许对「无活跃捆」的色码行补生成 |

**Response（预览与实写同形）**

```json
{
  "order_id": 1,
  "order_no": "…",
  "strategy": { "bundle_size": null },
  "lines": [
    {
      "color_id": 1, "size_id": 2, "color_name": "黑", "size_value": "40",
      "item_qty": 120,
      "action": "create" | "skip_exists" | "skip_invalid",
      "reason": null,
      "planned_units": [{ "qty": 120 }],
      "existing_unit_ids": []
    }
  ],
  "to_create": 1,
  "created": [],
  "print_path": "/admin/orders/print/1?mode=main-codes"
}
```

实写时：循环调用现有 `trace_service.create_bundle(..., work_log_id=None, note="开裁打卡")`，`TraceUnitLog.action=create`。  
`commit` 一次事务。返回 `created: [{id, code, qty, color_id, size_id}]`。

**错误**

| code | 何时 |
|------|------|
| `order_not_found` | — |
| `trace_not_enabled` | 产品未开 `trace_enabled`（M1 要求开追溯才开裁生码；文案引导去款上打开） |
| `no_items` | 无色码行 |
| `nothing_to_create` | only_missing 下全 skip（非 4xx，200 + to_create=0） |

> 不开追溯的款：不走本 API；继续工位选单（B2h §2.2）。

### 2.2 作废（新）

`POST /trace-units/{unit_id}/void`

- 仅 `open`（可选：尚无 `report` 流水）可作废；已有报工流水 → 400 `has_reports`，须走不良报废等现网路径。  
- 置 `status=scrapped`，写 `TraceUnitLog(action=create 以外：用 note="开裁作废"|建议枚举加 void)`。  
- **M1 枚举：** 在 `TraceUnitAction` 增加 `void`（小迁移）；避免滥用 `scrapped` 与质检报废混淆——若怕迁移，可用 `scrapped` + `note` 前缀 `[void]`，报工拦截同一套。

**推荐：** 加 `TraceUnitAction.void`，状态仍用现有 `scrapped`（少加 status 值）。

### 2.3 现网复用（不改契约或微改）

| API | 用途 |
|-----|------|
| `GET /orders/{id}/trace-units` | 打印页列码 |
| `GET /trace-units/by-code/{code}` | 扫码落地 |
| `GET /trace-units/by-code/{code}/qr.png` | 标签图 |
| `POST /reports` | 报工；见 §4 互斥与状态拦 |
| `POST /trace-units` | 保留手工单条创建；开裁主路径走 cut-cards |

### 2.4 扫码禁报（轻，可 M0）

若合批打印未来带可识别码：扫到合批落地页只展示「请扫各单货上主码」，不调 `/reports`。M1 不强制合批有 QR。

---

## 3. 服务层

### 3.1 `trace_service.preview_cut_cards` / `create_cut_cards`

- 读 `Order.items` + 已有 `TraceUnit`（order_id，status ≠ scrapped）。  
- **覆盖判定（同色码）：** 同 `color_id+size_id` 的活跃捆 `sum(qty) >= item.qty` → `skip_exists`。  
- 未覆盖：按 `bundle_size` 生成 planned_units。  
- create：逐个 `create_bundle`；`process_id=None`；`created_by` 可记当前 user→不强制 worker。

### 3.2 报工拦截（`report_service.submit_report`）

1. **作废/不可报：** 若 `trace_unit_id` 指向单位且 `status not in (open, in_process)` → `ReportError("trace_unit_inactive", "该主码已作废或结束，不可报工")`。  
2. **自动起捆互斥（D4/R27）：**

```text
若 create_trace_bundle is None（默认）：
  product.trace_enabled
  AND NOT is_group AND NOT is_rework AND not trace_unit
  AND qualified_qty > 0
  AND NOT order_has_cut_cards(order)   # 存在 created_from_work_log_id IS NULL 且未 scrapped
→ 才自动 create_bundle_from_work_log

若 order_has_cut_cards：默认不自动起捆（即使 trace_enabled）
显式 create_trace_bundle=true：仍允许（管理员补救），但 UI 不开追溯日常不传 true
```

`order_has_cut_cards`：  
`EXISTS TraceUnit(order_id, created_from_work_log_id IS NULL, status != scrapped)`。

### 3.3 扫主码报工工序（R22）

不改 `POST /reports` 字段；改前端预填：

1. URL：`/trace/:code` 或 `/trace-report?code=`（现网）  
2. 可选 query `station` = 工位 code → `GET /stations/by-code/{code}` 取 `process_name`，锁定工序字段。  
3. 无 station：保持现网「推下一道未完成工序 + 可改选」。  
4. 推荐现场 SOP：工位码贴在台面（定工序）→ 工人只扫鞋上主码；App 可「记住本机工位」（localStorage `station_code`），报工页自动带工序。

**管理端/工人端：** 开追溯款的工位报工页（`ScanReportView`）顶部提示「有货上主码请扫捆标报工」；不在本切片删除选单能力（兜底 + 二次确认放 M0/R24）。

---

## 4. 前端

### 4.1 开裁打卡入口

- 生产单详情 / 列表「更多」：在「打印流转卡」旁增加 **「开裁打主码」**。  
- 流程：弹窗 → 调 `cut-cards` dry_run 预览表 → 确认 → `dry_run:false` → 跳转 `print_path`。  
- 产品未 `trace_enabled`：按钮禁用 + 说明。

### 4.2 打印页合流（R23）——改 `OrderFlowCardPrintView`

路由仍：`/admin/orders/print/:id`。

| mode | 行为 |
|------|------|
| 默认 / `?mode=main-codes` | **主码页**：单头信息 + **每捆一块标签区**（码、色、尺码、qty、QR→`/trace/{code}`、合批号若有则印） |
| `?mode=sheet` | 旧版「色码表+工序勾选」无 QR，仅作对照附录；入口降为次要或不在菜单强调 |

M1 默认进入 `main-codes`。无 TraceUnit 时：空态「尚未开裁生码」+ 按钮调起开裁。

标签区复用现网 QR：`/api/v1/trace-units/by-code/{code}/qr.png`（与 `TracePrintView` 一致）。  
一页多枚；CSS `@media print` 控制分页（每枚或每 6 枚一页，实现自定，验收能扫即可）。

### 4.3 本捆报工页（`TraceReportView` / `TraceUnitView`）

- 主 CTA 文案：「报本工序」。  
- 读 `localStorage.station_code` 或 `?station=` → 锁定工序。  
- 继续 `create_trace_bundle: false`。  
- 作废码：加载详情若 inactive → 整页错误，禁提交。

### 4.4 单条补打

- 订单捆列表 / 主码打印页：每码「补打」→ 现网 `/trace-print/{code}` 或打印页锚点。  
- **禁止**补打时新建 TraceUnit。

---

## 5. 数据与迁移

| 项 | 说明 |
|----|------|
| 表结构 | **可不改表**：开裁捆 = `created_from_work_log_id IS NULL` |
| 可选 | `TraceUnitAction.void` 枚举值（Alembic 小改，若 DB 为原生 enum 需迁；当前多为 `native_enum=False` 字符串则只改 Python Enum） |
| 索引 | 现有 `order_id` 足够；可选 `(order_id, color_id, size_id)` 非唯一 |

---

## 6. 与闭环其它段的接口（本切片只碰边界）

| 段 | M1 影响 |
|----|---------|
| 排产 | 无；仍整工序 assignment |
| 合批 | 打印可带合批号（读成员关系）；批量开裁 → M2 R5b |
| 派工 | 按捆仍依赖已有 TraceUnit；开裁后即可细派 |
| 不良/B2g | 开裁后常有 open 捆 → 硬拦更常触发；登记走扫主码（现网） |
| 追溯 | 无新 API；码更早存在 |

---

## 7. 测试

| 用例 | 期望 |
|------|------|
| dry_run 三色码行 | to_create=3，不写库 |
| 确认生成 | 3 个 TU*，log create，note 含开裁 |
| 再次 only_missing | skip_exists，to_create=0 |
| bundle_size=50、qty=120 | 3 捆 50+50+20 |
| 未开 trace_enabled | 400 |
| 报工挂 active 主码 | 成功；不新建捆 |
| 同单已开裁后工位报工不传 bundle | **不**自动起捆 |
| void 后 POST /reports | 400 inactive |
| 有 report 流水后 void | 400 has_reports |
| 打印页 | 含 ≥1 个可解码 QR，指向 `/trace/{code}` |

单测文件建议：`tests/test_b2h_m1_cut_cards.py`。

---

## 8. 实现切片（开发顺序）

| 步 | 内容 | 预估 |
|----|------|------|
| M1-a | `preview/create_cut_cards` + API + 单测 | M |
| M1-b | 报工：inactive 拦 + 自动起捆互斥 | S |
| M1-c | void API + 单测 | S |
| M1-d | 开裁 UI + 打印页 main-codes | M |
| M1-e | TraceReport 工位工序预填（localStorage/`?station=`） | S |
| M1-f | 走查 E1/E2/E6/E7 | S |

**可与 M0 并行：** M0 不阻塞 M1-a；M1-d 前最好有 R24 提示文案。

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| 开裁一次生过多码 | 默认一行一捆；大单用 `bundle_size`；预览确认 |
| 旧单已有报工后起捆 | `order_has_cut_cards` 仅认无 work_log 来源；纯报工起的捆不挡「再开裁」——若同色码已覆盖则 skip；文档说明先开裁再报 |
| 打印太密扫不清 | 标签最小尺寸 + 分页；走查真机扫 |
| 工位工序与卡「下一道」冲突 | 有 station 时**工位优先** |

---

## 10. DoD（本设计落地）

- [ ] §7 单测绿  
- [ ] 走查：开裁 → 打印扫码 → 报工成功 → 追溯可见；void 不可报；开裁后工位报工不平行起捆  
- [ ] B0b 默认主码页，旧 sheet 不作为开追溯主入口  
- [ ] [`B2h-shop-floor-loop.md`](./B2h-shop-floor-loop.md) / 总纲勾选 M1 设计完成  

---

## 11. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿：cut-cards、打印合流、报工互斥、void、工位定工序 |
