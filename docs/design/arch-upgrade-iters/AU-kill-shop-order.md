# 干掉生产单（去桥接终局）

> **状态：** ✅ K1·K2·K3·K4-A·K4-B 停写·**K4-C 零桥接日用**·**K4-D 经典排产认 header**·**K4-E 预装/不良/返修认 header**·**K4-F 领退料/客供/核销/整单装箱/分活/同步工序**·**K4-G 出货毛利/智能排产/计件统计认销售单与 header**·**K4-H 文案/卸 FK（不归档、不 DROP）** 已落地 · 2026-08-13  
> **目标：** 业务与 UI **不再出现「生产单」主体**；车间/PMC 只认 **销售单 + 执行单**。  
> **非目标：** 立刻 `DROP TABLE orders`（Order 双路径 + `create_all` 仍会建回表；遗留测试仍 `create_order`）。

---

## 1. 裁决

| 问题 | 裁决 |
|------|------|
| 对人还要不要生产单？ | **不要**。菜单、建单、导入、默认跳转全部关掉或改去执行单 |
| 库内 `orders`？ | **过渡期保留表**；新路径 **停写桥接壳**（`shop_order_id`/`production_order_id` 空） |
| 手建 `/orders` POST？ | **禁止**（仅服务层内部 `create_order` 给遗留路径） |
| 合批？ | **只读**：禁新建/加成员；历史可看、打印、移出、作废 |
| 报工/开裁主键？ | **认 `header_id`**；`order_id` 列可空 |
| 工序？ | `OrderProcess.header_id` + `order_id` 可空；无壳时 `ensure_header_processes` |
| 用料？ | 齐套/锁料认 `header_id`；`OMR.order_id` 可空 |
| 何时删表？ | **不做软归档**；物理 DROP 仍阻塞（双路径 + `create_all`） |

---

## 2. 切片

| 切片 | 内容 | 状态 |
|------|------|------|
| **K1** | 藏菜单；`/admin/orders`→执行单；禁 HTTP 建单/导入；销售「看生产」→执行单头 | ✅ |
| **K2** | 现场/看板文案与深链改执行单；合批降只读 | ✅ |
| **K3** | `WorkLog`/`TraceUnit` 挂 `header_id` 且 `order_id` 可空；报工认 `header_id`/`header_no` | ✅ |
| **K4-A** | 桥接壳 `is_bridge` + 备注 `[桥接]`；`OrderProcess`/`Assignment.header_id` 双写回填 | ✅ |
| **K4-B** | **停写壳**：开裁认码明细；报工认 `header` 工序；OMR/`order_id` 可空 | ✅ 停写 · 不 DROP |
| **K4-C** | **零桥接日用**：`cut_cards_for_execution` 认 header；头级 trace-units/打印；看板+工位候选含无壳头 | ✅ |
| **K4-D** | **经典排产**：`ScheduleDraftLine.header_id` + `order_id` 可空；pool/draft/confirm 认无壳头 | ✅ |
| **K4-E** | **预装/不良/返修**：筐预装 + `DefectEvent`/`ReworkTask` 认 `header_id`，`order_id` 可空 | ✅ |
| **K4-F** | **无壳日用补齐**：领退料/发车间、客供台、核销、整单装箱、分活板、同步到在制 | ✅ |
| **K4-G** | **仍摸 Order 的后置项**：出货写回认销售行、智能排产引擎、毛利/计件/部分统计 | ✅ |
| **K4-H** | **不归档**：用户可见「生产单」改执行单/销售单；剩余 NOT NULL 可空；MySQL 卸指向 `orders` 的 FK | ✅ |

---

## 3. K2 落地摘要

- `POST /merge-batches`、加成员 → 400「合批组批已停用」
- 排产「合批推荐」仅展示；桥接页去掉「组成合批」
- 车间看板主显 `header_no`；出入库深链 → `/admin/executions`

---

## 4. K3 落地摘要

- `work_logs` / `trace_units`：`header_id` + `order_id` 可空；新写仍双写
- 报工：`header_id` 或执行单号

---

## 5. K4-A 落地摘要

- `orders.is_bridge`；执行路径曾 `create_order(..., is_bridge=True)`；备注强制 `[桥接]` 前缀
- `order_processes.header_id` / `order_process_assignments.header_id`；确认/合单后 `stamp_order_processes_header`
- 存量：有 `execution_headers.shop_order_id` 的壳回填 `is_bridge` + 工序 `header_id`
- **本波不**停写壳、**不** DROP

### K4-B 停写落地摘要（本波）

- `create_execution` / `create_execution_from_sales_line`：**不再** `create_order`；`shop_order_id`/`production_order_id` = `None`
- 工序/用料：`ensure_header_processes` + `ensure_material_snapshot_for_header`（挂 `header_id`）
- 开裁：`preview_or_create_cut_cards(header_id=…)` 认 `SpecExecutionOrder` 色码；`create_bundle` 允许无 `order_id`
- 报工：无桥接壳时认 `list_header_processes`；`WorkLog.order_id` 可空；领料闸 `assert_issue_gate_for_header`
- 销售确认：容忍 `production_order_id is None`（以 `execution_header_id` 为准）

### K4-B DROP 仍阻塞

1. ~~排产草稿/`ScheduleDraftLine` 挂 `order_id` + `order_process_id`~~ → **K4-D** 已挂 `header_id`，`order_id` 可空（经典 pool/draft/confirm）
2. ~~出货仍可写回 `OrderItem.shipped_qty`（有壳时）~~ → **K4-G** 无壳只写销售色码；有壳仍双写
3. 列仍在：`shop_order_id`、`production_order_id`、`Order`/`OrderItem` 子表；MySQL 指向 `orders` 的 FK 已卸（K4-H）
4. ~~无壳时执行进度回写~~ → 已认 header 工序
5. ~~`cut_cards_for_execution`（码明细级）仍要求桥接壳~~ → **K4-C** 无壳走 `header_id`
6. ~~装箱预装 / 不良 / 返修要求 `order_id`~~ → **K4-E** 已挂 `header_id`，`order_id` 可空

### K4-C 落地摘要（本波）

- `cut_cards_for_execution`：无 `shop_order_id` 时认 `header_id` 开裁（不再抛 `no_shop_order`）
- `GET /executions/headers/{id}/trace-units`：与订单 trace-units 同形
- 执行单管理：开裁/打印/筐列表认 header；打印路由 `/admin/executions/print/:id`
- 车间看板：开放无壳 `ExecutionHeader` 进 `focus_orders`（显示 `header_no`）
- 工位报工候选：含 `OrderProcess.header_id`（无 `order_id`）行

### K4-D 落地摘要（本波）

- `ScheduleDraftLine.header_id` + `order_id` 可空；`create_draft(header_ids=…)` / pool 含无壳头
- `confirm_draft` / `discard_draft`：无 `order_id` 时不写 `Order.schedule_status`；齐套走 `get_header_kit`
- 排产 UI：待排池可选执行单（`header_ids`）；单号列标「执行单」
- **已知限制：** ~~`schedule_engine` 智能方案仍按生产单~~ → **K4-G** 已收无壳 header；色码级 `ExecutionScheduleDraft`（AU-I3）不变

### K4-E 落地摘要（本波）

- `create_basket_prepack`：无 `order_id` 时认筐 `header_id`；`PackingPlan.header_id` + `order_id` 可空；备注用筐码前缀
- `create_defect_event`：捆/筐可仅挂 `header_id`；进行中捆校验认 `TraceUnit.header_id`；错误文案「请选择执行单/订单或扫捆标」
- `create_rework_task`：容忍 `defect.order_id` 空；拷贝 `header_id`；派工认 `list_header_processes`
- **整单装箱** `create_packing_plan(order_id=…)` 本波未迁 → **K4-F** 已迁 header

### K4-F 落地摘要（本波）

- `StockDoc.order_id` 可空；`submit_stock_doc` / `list_issue_candidates` 认 `header_id`
- `MaterialRelease.header_id` + `order_id` 可空；`release_to_workshop(header_id=…)`
- 客供台 outerjoin 执行单头；`CustomerSupplyReceipt.order_id` 可空 + `header_id`
- `PaymentAllocation.order_id` 可空（应收无生产单仍可核销）
- 整单装箱 `create_packing_plan(header_id=…)`；池=码明细；API `/executions/headers/{id}/packing-plans`
- 针车分活：`unit_detail_dict` 无壳走 header 工序；`POST /trace-units/{id}/assign-bundles`
- 产品工序「同步到在制」同时扫无壳 `ExecutionHeader`

### K4-G 落地摘要（本波）

- 无壳出货不写 `OrderItem`；`profit_report` 按销售单归集（材料/人工认执行单头）
- `schedule_engine.collect_candidate_orders` / `generate_proposals(header_ids=…)` 收无壳头；方案落草稿挂 `header_id`
- 计件 `list_work_logs` / 月结明细：无壳显示并可用执行单号筛选
- 接单色码历史 + 争料同伴含完工销售行 / 无壳执行单

### K4-H 落地摘要（本波）

- **不做**存量壳软归档（`status=archived` / 移历史库），**不** `DROP TABLE orders`
- 文案：菜单/筛选/导出/预警/排产草稿列不再写「生产单」；遗留页 `?legacy=1` 改称「遗留内部单」
- `OrderChangeLog.order_id` / `MergeBatchMember.order_id` 可空
- MySQL `ensure_schema`：上述列 `MODIFY … NULL`；`information_schema` 查出并 `DROP FOREIGN KEY` 所有指向 `orders` 的约束（SQLite 跳过）
- 占用明细无壳认 `header_no`；执行单页不再深链桥接单
- **物理 DROP 仍阻塞：** Order 双路径、`Base.metadata.create_all` 会建回表、大量遗留测试仍 `create_order`

### 存量壳策略（不归档）

| 项 | 策略 |
|----|------|
| 新业务 | 永不建壳（K4-B）；日用无壳（K4-C 起） |
| 存量壳 | 保留 `orders` 行；UI 仅 `?legacy=1` 排障 |
| 双写期 | 有壳路径仍可报工/开裁（兼容历史）；无壳走 `header_id` |
| DROP | **不做本波**：确认无活跃引用且模型/测试不再依赖 `Order` 后再议 |

---

## 6. 失败条件

- 新业务只能靠手建生产单才能开裁/报工  
- 合单场景又要求人选生产单锁料/出货  
- 静默删表导致报工断链  
- **假停写**：去掉 `create_order` 却未迁工序/开裁 → 现场断链  
