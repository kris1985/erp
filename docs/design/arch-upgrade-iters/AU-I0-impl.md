# AU-I0 实现设计：工艺两段 · 筐/捆 · 分段派工

> **状态：** 🚧 开发中（M1–M4 主路径 + 打印区分 + 分活看板 + 技能系数 UI 已接；ACCEPTANCE 走查待做）  
> **需求：** [`AU-I0-route-carriers-dispatch.md`](./AU-I0-route-carriers-dispatch.md)  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md)  
> **验收：** [`ACCEPTANCE.md`](./ACCEPTANCE.md) §A  
> **原则：** 不改合单账本；复用 `TraceUnit` / `OrderProcessAssignment` / `WorkLog` / `POST /reports`；修订 B2h「唯一主码=捆」为分阶段主码。  
> **本迭代不做：** 规格执行单、ratio、FG/直发、产线、排产池切主。

---

## 0. 切片建议（I0 内再拆）

| 切片 | 内容 | 可演示 |
|------|------|--------|
| **I0-M1** | 部件主数据 + 产品部件/路线扩展 + 建单落 `OrderProcess` + 管理端两段配置页 | 配一款、建单工序含部件序 |
| **I0-M2** | TraceUnit basket + 开裁生「1 筐 N 捆」+ 打印模板分筐/捆 | 打印样张；扫码能区分类型 |
| **I0-M3** | 扫码状态机 + 合帮齐套闸门 + 针车扫筐分捆派工 + **收料认领** + 报工校验 | ACCEPTANCE A 核心走查 3–5 |
| **I0-M4** | 组报工明细表 + 技能系数 + 租户配置；质检责任默认 + 返修挂载体 | 走查 6–7 |

推荐顺序：**M1 → M2 → M3 → M4**。M1/M2 可前后端并行。

---

## 1. 领域契约（写死）

| 概念 | 实现落点 |
|------|----------|
| 部件字典 | 新表 `part_definitions`（租户级） |
| 款的部件清单 | 新表 `own_product_parts` |
| 部件路线行 / 整鞋路线行 | **扩展** `own_product_labors`：`part_id` 可空；空=整鞋段 |
| 齐套检查点 | `own_product_labors.is_kit_checkpoint`（通常落在合帮那一行） |
| 筐卡（流转卡） | `TraceUnit.unit_type=basket`；对外文案「流转卡」 |
| 扎捆码 | `TraceUnit.unit_type=bundle`；`parent_id` → 筐；`part_id` → 部件 |
| 父流转卡 | **I0 不建表**；I1 合单再引入。开裁以「同色码下一筐」为本地父 |
| 针车派工 | `OrderProcessAssignment.trace_unit_id` = 捆 id |
| 个人报工载体 | `WorkLog.trace_unit_id` 指向 **bundle** |
| 班组报工载体 | `WorkLog.trace_unit_id` 指向 **basket**（或新增字段语义相同） |
| 组拆分 | 新表 `work_log_group_shares`；`group_detail` JSON 只读兼容一期 |

**扫码权限（与工艺检查点绑定）**

```text
令 kit_process = 该款 is_kit_checkpoint=true 的工序（若无则视为「无合帮闸门」，仅告警）

报工请求带 process_id + trace_unit：
  若 process 在 kit 之前（含部件路线工序）：
      必须 unit_type=bundle（个人）或组长代报策略
  若 process == kit 或之后（整鞋段）：
      必须 unit_type=basket
      bundle 报后道 → 400
  合帮（kit）额外：该筐下每个 own_product_parts 至少有一捆在 kit 前工序已完成（见 §5）
```

**派工校验（针车默认）**

```text
allow_unassigned_bundle_report = false（默认）：
  个人扫 bundle 报工 → 须存在 Assignment(process, worker, trace_unit=bundle)
  或 stitch_leader_proxy_report=true 且操作人为组长/有代报权，
     并显式传入 beneficiary_worker_id（工资记受益人，operator 记组长）
成型/包装 group 工序：不要求按人 Assignment；执行单/工序挂班组即可（沿用现网 group 派工）
```

**合帮前三模式（适配不同厂）**

| 模式 | 行为 | 默认 |
|------|------|------|
| A 工人自扫 | 工人扫捆，须已派工 | 主路径 |
| B 组长代报 | 组长扫捆 + 指定工人；载体仍是捆 | **开**（`stitch_leader_proxy_report`） |
| C 谁扫算谁 | 未派也可自扫 | **关**（`allow_unassigned_bundle_report`） |

合帮前禁止：用 **basket** 记针车个人计件。筐仅收料/分活/进度。

### 1.1 收料认领（筐卡事件）

```text
事件：basket_received
  actor_id, received_at
  写入 TraceUnitLog(action=transfer 或扩展 receive) + 可选 basket.received_at / received_by

触发（auto_basket_receive_on_first_action=true，默认）：
  首次 GET stitch-board(basket) 成功
  或 首次 assign-bundles(basket)
  或 首次对该筐下捆的代报
  → 幂等：已收料则跳过

显式：POST /trace-units/{basket_id}/receive

强制：require_basket_receive_before_stitch=true 时，
  未收料禁止 assign-bundles / 捆报工（合帮前）

不做：收料专用码；跨车间双人扫握手
```

---

## 2. 数据模型

### 2.1 新表

```text
part_definitions
  id, tenant_id, code, name, source(裁断|外购|其他), is_active, created_at
  UNIQUE(tenant_id, code)

own_product_parts
  id, tenant_id, own_product_id, part_id
  source_supplier_product_id NULL  -- I0 可空；I1+ 再强绑料
  pieces_per_pair INT DEFAULT 1
  sort_order INT
  UNIQUE(own_product_id, part_id)

work_log_group_shares
  id, tenant_id, work_log_id, worker_id
  pairs INT, unit_price DECIMAL, wage DECIMAL
  is_adjusted BOOL DEFAULT false
  skill_factor_snapshot DECIMAL NULL
  created_at
  INDEX(work_log_id), INDEX(worker_id, created_at)
```

### 2.2 扩表

| 表 | 字段 | 说明 |
|----|------|------|
| `own_product_labors` | `part_id` NULL FK | 非空=部件路线；空=整鞋路线 |
| | `is_kit_checkpoint` BOOL default false | 同款建议最多一个 true |
| `trace_units` | `unit_type` 增枚举值 `basket` | 已有 `bundle`/`piece` |
| | `part_id` NULL FK | 仅 bundle 使用 |
| | `parent_id` | **已有**：bundle → basket |
| | `received_at` / `received_by_worker_id` NULL | 仅 basket；收料认领 |
| `workers` | `skill_factor` DECIMAL(5,2) default 1.00 | 组拆分预填 |
| `order_processes` | `part_id` NULL | 建单从 labor 带下，便于齐套按部件统计 |
| `work_logs` | 保持 `trace_unit_id`；`group_detail` 保留兼容 | 写库优先写 shares 表 |
| `tenants.settings` JSON | 见 §6 | 不新建 system_config 表 |

### 2.3 建单落工序（改 `create_order`）

```text
若 own_product 有 own_product_parts：
  按 part.sort_order：
    取出 labors where part_id=该部件，按 sort_order 生成 OrderProcess（带 part_id）
  再取出 labors where part_id IS NULL，生成整鞋段 OrderProcess
否则：
  回退现逻辑：仅 OwnProductLabor 扁平列表（兼容旧款）
```

工价：报工锁价仍从 `OwnProductLabor` / 现网单价逻辑取；**不**改工序字典默认价为权威。

### 2.4 开裁生码（扩展 B2h cut-cards）

在现有 `POST /orders/{id}/cut-cards` 上增加策略（或 `mode=basket_bundles`）：

```text
对每个 order_items(color, size, qty)：
  按 basket_pairs_* 配置拆成若干「筐计划双数」
  每个筐：
    创建 TraceUnit(unit_type=basket, qty=筐双数, color, size, parent_id=NULL)
    对每个 own_product_part：
      创建 TraceUnit(unit_type=bundle, parent_id=筐, part_id=部件,
                   qty=筐双数 * pieces_per_pair 或按双数策略 — I0 默认 qty=筐双数)
若款无部件清单：回退 M1 旧行为（仅 bundle，无 basket）
```

打印：

- 筐：标题「生产流转卡」，码=筐 `code`，含款色码计划双  
- 捆：标题部件名，含「所属筐卡：{basket.code}」

---

## 3. API 草表

| 方法 | 路径 | 说明 |
|------|------|------|
| CRUD | `/part-definitions` | 部件字典 |
| GET/PUT | `/own-products/{id}` | 扩展 parts + labors（labor 带 part_id / is_kit_checkpoint） |
| POST | `/orders/{id}/cut-cards` | 扩展 basket_bundles 模式；dry_run 预览树 |
| GET | `/trace-units/{id}` | 返回 unit_type、part、parent/children、派工、received_* |
| GET | `/trace-units/by-code/{code}` | 扫码入口（已有则扩展字段） |
| POST | `/orders/{id}/processes/{pid}/assign-bundles` | 组长分活；可触发自动收料 |
| GET | `/trace-units/{basket_id}/stitch-board` | 分活看板；默认触发自动收料 |
| POST | `/trace-units/{basket_id}/receive` | 显式收料（幂等） |
| POST | `/reports` | 校验载体×阶段；捆派工；kit 齐套；支持 `proxy: true` + `beneficiary_worker_id`（组长代报） |
| POST | `/reports` group | 写 `work_log_group_shares`；可传 shares[] 或服务端按 skill_factor 预填 |
| PATCH | 返修/不良 | `defect`/`rework` 支持 `trace_unit_id`（捆或筐）；针车默认带 assignment.worker |

权限：分活/开裁 = leader+；工人只报自己的捆（除非代报）。

---

## 4. 报工校验伪代码

```text
function assert_report(tu, process, worker, operator, beneficiary_worker_id, is_leader_proxy):
  labor = find_labor(product, process)
  kit = find_kit_checkpoint(product)
  pay_to = beneficiary_worker_id or worker

  if tu.unit_type == bundle:
    if kit and process_is_at_or_after(kit, process):
      reject("合帮后请扫流转卡(筐)")
    if is_leader_proxy:
      if not settings.stitch_leader_proxy_report:
        reject("未开启组长代报")
      if not operator_is_leader(operator):
        reject("仅组长可代报")
      if not beneficiary_worker_id:
        reject("代报须指定工人")
      # 工资记 pay_to；建议仍要求该捆已派给 pay_to（可配置放宽）
    elif not settings.allow_unassigned_bundle_report:
      if not assigned(process, pay_to, tu.id):
        reject("未派工到你")
  elif tu.unit_type == basket:
    if personal_piecework_before_kit(process, kit):
      reject("针车个人/代报请扫扎捆码")
    if kit and process == kit:
      assert_parts_ready(tu)
  else:
    reject(...)
```

`assert_parts_ready(basket)`：对 `own_product_parts` 每个 part，存在 child bundle 且该 bundle 在 kit 前最后一道个人工序 completed（或简化：捆上 last_process 已达部件路线末道）。I0 允许「简化版」：各部件至少一捆 `status in (in_process, done)` 且有合格报工累计 ≥ 计划×阈值（默认 1.0，可配置放宽）。

---

## 5. 组报工与技能系数

```text
POST /reports { report_type: group, trace_unit_id: basket, qualified_qty: N, shares?: [...] }

若未传 shares 且 enable_skill_factor_split：
  取该工序 assignment 工人或班组成员
  weight_i = skill_factor_i（≤0 当 1）
  预填 pairs_i = round(N * w_i / sum(w))，末人吃误差
组长可改 shares 后提交 → is_adjusted=true
写入 work_log_group_shares；group_detail 同步一份 JSON 供旧读路径
工资结算优先读 shares 表，无则回退 group_detail
```

---

## 6. 租户配置键

写入 `tenants.settings`（或现有 schedule/inventory 同级）：

| Key | 类型 | 默认 |
|-----|------|------|
| `allow_unassigned_bundle_report` | bool | false |
| `stitch_leader_proxy_report` | bool | **true** |
| `auto_basket_receive_on_first_action` | bool | **true** |
| `require_basket_receive_before_stitch` | bool | false |
| `basket_pairs_cutting` | int | 40 |
| `basket_pairs_forming` | int | 24 |
| `enable_skill_factor_split` | bool | true |
| `kit_ready_qty_ratio` | float | 1.0 |

---

## 7. 前端入口（最小）

| 页面 | 改动 |
|------|------|
| 产品详情/编辑 | 「工艺两段」：部件泳道 + 整鞋单线；检查点勾选；工价汇总 |
| 生产单打印 / 开裁 | 模式选择：旧一码一捆 / 新筐+捆；预览树 |
| 组长 H5/平板 | 扫筐 →（自动/显式）收料 → 分活看板 → 一键派工；班组报工填数+微调 shares |
| 工人报工 | 扫捆；错误文案区分「请扫筐」「未派工」 |
| 工人/员工档案 | 技能系数编辑 |

---

## 8. 质检 / 返修（M4 最小）

- `DefectEvent.trace_unit_id`：捆或筐均可。  
- 若 tu=bundle 且有 assignment → 默认 `responsible_worker_id`。  
- 若 tu=basket → 不默认个人；`responsible_process_id` 用疵品类型默认工序；扣款分摊 **I0 可只记事件**，工资扣款可后置。  
- `ReworkTask`：创建时带同一 `trace_unit_id`；完成后回归不改筐 id（数量勾平细则 I3）。

---

## 9. 迁移与兼容

1. `ensure_schema` / Alembic：加列加表；`unit_type` 字符串枚举加 `basket`。  
2. 旧款无 `own_product_parts`：开裁与报工保持 B2h 现状。  
3. 旧 `group_detail`：读路径双读；新报工双写。  
4. 文档：改 [`B2h-shop-floor-loop.md`](../B2h-shop-floor-loop.md) §1.1 为分阶段主码，并链到本文。

---

## 10. 单测清单（最低）

| 文件建议 | 覆盖 |
|----------|------|
| `test_au_i0_route.py` | 有部件建单工序顺序；检查点唯一；工价汇总 |
| `test_au_i0_cut_basket.py` | 1 筐 N 捆 parent；无部件回退旧开裁 |
| `test_au_i0_scan_gate.py` | 合帮前捆可报、后不可；筐合帮齐套拦截 |
| `test_au_i0_assign_bundle.py` | 未派不可报；派后可报；组长代报 |
| `test_au_i0_basket_receive.py` | 首动自动收料幂等；强制未收拦截；显式 receive |
| `test_au_i0_group_shares.py` | 系数预填；手调 is_adjusted；结算读表 |

验收走查对齐 [`ACCEPTANCE.md`](./ACCEPTANCE.md) §A 与 AU-I0 §4。

---

## 11. 明确不做（防范围膨胀）

- 收料专用码；裁断↔针车双人扫握手  
- `execution_allocations` / 销售色码可产池  
- 父流转卡独立实体、合单 ratio  
- FG、直发、预装箱出货  
- `production_line`  
- 完整 `op_prerequisite` 图（只用 `is_kit_checkpoint`）  
- 平行 `report_personal` / `report_team` 表  

---

## 12. 开放问题（实现前 30 分钟拍板）

| # | 问题 | 推荐 |
|---|------|------|
| 1 | 筐计划双数用 cutting 还是 forming 配置？ | 开裁用 `basket_pairs_cutting`；成型不在开裁重拆 |
| 2 | 捆 `qty` 按「双」还是「片」？ | I0 统一用**双**（与现网 TraceUnit.qty 一致）；片数仅展示 pieces_per_pair |
| 3 | 同款多个 kit_checkpoint？ | 禁止；保存时校验 ≤1 |
| 4 | 裁断是否出现在部件泳道？ | I0 允许配置；开裁动作本身不报裁断工价（避免双计）— 若 labor 名含裁断且无报工则仅作展示 |

---

**下一步：** 确认 §12 四点后开 **I0-M1**（表结构 + 产品工艺 API/页）；同步改 B2h 主码文案。  
**回链：** 总纲 / AU-I0 需求文头可链本文为「实现设计」。
