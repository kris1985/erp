# A' 档实现设计：报工实测产能优先、配置兜底

> **用途：** A' 档（排产人力建模）的实现设计，含后端与前端改动点。基于 [`schedule-workforce-capacity.md`](./schedule-workforce-capacity.md) 确认的方案，本次为**设计稿，待评审后动手**。
> **定界：** 只改排产产能口径，不改排产算法本身（规则排产 + PMC 确认架构不变）。
> **关联：** 排产主稿 [`aps-dev-review.md`](./aps-dev-review.md) · 分析笔记 [`schedule-workforce-capacity.md`](./schedule-workforce-capacity.md)
>
> **实施状态（2026-08）：A' v1 已落地**——后端（models/db_schema/schemas/masters + schedule_settings 参数 + engine 回退链 + ProcessWindow 字段 + 负荷行 `capacity_source`）+ 前端（工序档案覆盖字段、排产设置窗口、确认弹窗依据行、补填弹窗覆盖列、**甘特条"实/标/覆"角标 + 悬停排产依据**），单测 18 例全过（`tests/test_schedule_workforce_capacity.py`），全量排产相关 60+ 例全过，web build 通过。**已定决策见 §四 决策点加粗项。**

---

## 一、总原则：四级优先级链

```
工序日产能 = 手动覆盖人数 × 单人日产能                 (1) 覆盖优先（PMC 手动，唯一"未来人力"入口）
          = 该款×该工序近N天实测人均 × 款级活跃人数    (2a) 款级实测（复杂度自动内含）
          = 该工序近N天实测人均 × 工序级活跃人数        (2b) 款级无史 → 工序级实测
          = 单人日产能 × 标准人力                       (3) 工序级无史 → 标准（现状）
          = 抛错「未配置单人日产能」                    (4) 现状行为，保持不变
```

排产天数公式不变：`⌈数量 ÷ 工序日产能⌉`（`_calc_days`）。

**复杂度不靠配置，靠实测：** 不同鞋款同一工序复杂度不同（女鞋针车 vs 运动鞋针车），聚合键带款号（`work_logs.own_product_id` 已有）后，真实产出天然捕捉复杂度——新款回退链 (2b)→(3)。

---

## 二、后端

### 2.1 报工反推聚合（新函数 `_derive_effective_capacity`）

**数据口径（`work_logs`）：**
- 范围：`tenant_id`、`status=valid`、`created_at >= as_of - N 天`（`as_of` = 排产基准日，默认今天）
- 聚合键：`(process_id, own_product_id, worker_id)` —— **款级聚合**，复杂度随款号自动进入产能（`work_logs.own_product_id` 字段已存在，零新主数据）；款级无史时再按 `(process_id, worker_id)` 工序级聚合回退
- 产出：`Σ qualified_qty`（合格量，返工行合格量为 0 天然排除）、人天 = `COUNT(DISTINCT date(created_at))`
- 结果：
  - 实测人均日产量 = Σ合格量 ÷ 总人天
  - 活跃人数 = 独立 worker 数
  - 工序日产能 = 实测人均 × 活跃人数
- **启用条件（防失真）：** 独立 worker ≥ 2 **且** 总人天 ≥ 3，否则视为"无史"降一级回退（款级→工序级→标准）——避免某工序只有 1 人报过 1 天就触发实测
- **时区注意：** `created_at` 是 UTC，按租户时区折算成业务日再 `DISTINCT date`；跨 UTC 日的晚班报工会落在相邻业务日，v1 接受近似并在注释标明
- 效率比 = 实测人均 ÷ `per_worker_capacity`（**仅展示，不参与计算**）

### 2.2 engine 单点改动（7 处调用点自动生效）

`_process_capacity_map(db, tenant_id, cfg)` 全库 7 处调用（engine 内 6 + `schedule_service` 1），签名一致，**改内部实现即全链路生效**（出方案、草稿、日/周负荷、插单仿真）：

1. `_process_capacity_map` 加 `as_of: date | None = None` 参数（缺省今天，调用点零改动）
2. map 值从 `(单人日产能, 标准人力)` 扩展为 `(cap_per_head, workers, source, detail)`：
   - `source ∈ {"override", "actual", "standard"}`；`detail = {active_workers, avg_per_head, lookback_days, efficiency}`
   - 判定顺序：`ProcessDefinition.current_workers` 非空 → override；否则 2.1 有史 → actual；否则 standard
3. `_calc_days` / `_daily_capacity` 适配新元组（继续用 `cap_per_head × workers`）
4. `ProcessWindow` 增字段：`source`、`active_workers`、`avg_per_head`、`efficiency` → `to_dict()` 序列化，方案卡/周负荷/确认窗格自动带出
5. `ENGINE_VERSION` 递增（前端有缓存/版本比对时用到）

### 2.3 参数（`schedule_settings.py`，/settings GET/PATCH 已有接口自动透出）

| 参数 | 默认 | 说明 |
|---|---|---|
| `actual_capacity_lookback_days` | 7 | 报工回溯窗口（可 7/14） |
| `actual_capacity_min_workers` | 2 | 启用实测的最小独立人数 |
| `actual_capacity_min_person_days` | 3 | 启用实测的最小总人天 |

### 2.4 覆盖值主数据（`ProcessDefinition.current_workers`）

- `models/__init__.py`：`current_workers: Mapped[Optional[int]]`（NULL = 不覆盖）
- `db_schema.py`：按既有 `_add_column` 模式加列（参照 L802-806 的 `standard_workers` 迁移写法）
- `schemas/api.py`：`ProcessCreate` / `ProcessUpdate` / `ProcessOut` 加 `current_workers`
- `app/api/v1/masters.py`：create / update / list 透传（参照现有 `standard_workers` 三处）

### 2.5 工序→人员映射（回答"谁能干这道工序"，零新主数据）

**原则：报工历史就是技能证据，Position 只做冷启动兜底，不建"Position→工序"映射当主链路。**

| 信号 | 来源 | 用途 |
|---|---|---|
| **报工历史**（主证据） | `work_logs` 按 `(process_id, worker_id)` | "谁能干工序 P" = 最近报工过 P 的 worker 集合；排产"该工序多少人可用" = 该集合近 N 天独立人数，再按 `team_members` 归组得"哪个班组能干什么" |
| **现场派工**（实时补充，非技能证据） | `order_processes.assigned_worker_id / assigned_group_id`、`order_process_assignments` | "这单这道工序现在派给谁"，可展示当前在干的人；"派了≠干过"，不能当能力依据 |
| **Position 职位**（冷启动兜底） | `Employee.position_id → positions` | 新人/无报工史时按职位归属判断；**若做映射必须给 `positions` 加 `process_id`（或工序族）字段，严禁名字字符串匹配**（"针车工"vs"车工"对不上） |

**为什么可行：** 排产要的人力和产能是同一个证据链——近 N 天在工序 P 上真实产出过的人（能力证据）和他们的产出水平（产能证据），都来自同一份 `work_logs`，一次聚合同时拿到，不依赖任何主数据映射。

### 2.6 测试（tests/）

- 有史工序 → source=actual，天数为 ⌈数量÷(人均×活跃人数)⌉
- 无史工序 → source=standard，回退现状公式
- 覆盖值 > 0 → source=override 且优先于实测
- 未配置且无史 → 仍抛错（现状行为回归）
- 窗口参数生效（N=7 vs 14 结果不同）；阈值防失真（1 人 1 天不触发实测）

---

## 三、前端

### 3.1 排产页（`ScheduleAdminView.vue`）

1. **确认弹窗工序窗格**（`confirm-window`，约 L946）：每道工序加一行依据小字：
   ```
   按 38 人 × 405 双/人/天 排 2 天（近7天实测，效率 99%）
   按 40 人 × 400 双/人/天 排 2 天（标准人力）
   按 30 人 × 400 双/人/天 排 3 天（手动覆盖）
   ```
   数据直接来自 `window.source / active_workers / avg_per_head / efficiency / days`
2. **待排款甘特 bar tooltip**：同口径（可复用同一格式化函数）
3. **未配产能补填弹窗**（约 L867）：在 `单人日产能 / 标准人力` 输入旁加"可用人数覆盖（空=不覆盖）"——复用现有保存链路，补填时一并落库
4. **设置表单**（`settingsForm`，约 L1128）：加"实测窗口天数"输入（7/14），随 `/settings` PATCH 保存

### 3.2 工序档案（`ProcessesAdminView.vue`）

- 工序表单加"可用人数覆盖"字段（与 `standard_workers` 同编辑位，工具提示：空=按实测/标准人力）

### 3.3 军师（`ScheduleAssistantView.vue`）

- **默认零改动**：军师读日/周负荷文本，engine 返回的 `source/detail` 会自然出现在负荷口径里；如要显式话术（"针车按近7天实测 38 人×405 双排"），在军师 prompt 里加一行取 `detail` 的说明，属增强项

---

## 四、口径决策点（评审时确认）

1. **活跃人数口径：** 近 N 天独立报工者数（简单，偏乐观）vs 日均在岗 = Σ人天 ÷ N（平滑，偏保守）。**v1 已定：近 N 天独立报工者数 + 阈值兜底（min_workers=2、min_person_days=3）。**
2. **全厂停工 N 天 → 该工序全部回退标准**：这是正确行为（系统不该在没数据时瞎猜），但 PMC 可能困惑——UI 依据行写"无近期报工，按标准人力"而不是只写"标准"。
3. **效率比异常（<0.5 或 >1.5）只展示不干预** v1；若大量出现说明 `per_worker_capacity` 配置失真，属于主数据治理问题，不靠算法兜。
4. **覆盖值必须有显式 UI 入口**（3.1.3 补填弹窗 + 3.2 工序档案），否则 PMC 不知道存在"未来人力"调整手段。**v1 已落地两处入口。**
5. **款级聚合的窗口权衡：** 款级实测最准但数据稀疏（低频款近 N 天没几个报工），工序级实测数据多但稀释复杂度——回退链 (2a)→(2b)→(3) 的启用条件阈值（独立 worker/人天）按款级更严、按工序级可放宽，参数分开配。**v1 已定：款级/工序级同一阈值（参数可独立调），待真实数据再拆。**
6. **Position 映射做不做、放哪：** **v1 已定：不做**（报工历史已覆盖"谁能干"）；冷启动兜底留到 B'，且必须给 `positions` 加 `process_id` 字段而非名字匹配。若客户报工覆盖率高，B' 甚至可以只做"款×工序产能配置"而完全跳过 Position。
7. **已确认排产不自动重算：** **v1 已定：不自动重算**——调整靠既有 `gantt-shift`（整单平移）/ `gantt-withdraw`（撤回重排）/ `gantt-rush`（急单挤压），均 PMC 主动触发且已开裁单禁止。**已排单追溯已落地**：`order_processes` 存 `capacity_source / active_workers / avg_per_head / efficiency` 四列（新流程 `_write_header_windows` 从窗口 dict 写、旧流程 `confirm_draft` 用 `_cap_info` 重算写），甘特已下发条子与确认弹窗自动带出"当时按什么排的"；平移/急单挤压不带 source 不覆盖已存快照。后续"产能漂移→提示需重排的单"可直接对比当前实测与已存快照，属可选增量。

---

## 五、实施步骤（顺序）

1. 主数据：models + db_schema 迁移 + schemas + masters API（`current_workers`）
2. 参数：`schedule_settings.py` 三项默认 + merge 解析
3. engine：`_derive_effective_capacity` → `_process_capacity_map` 改造 → `_calc_days`/`_daily_capacity` 适配 → `ProcessWindow` 字段
4. 测试：§2.5 五类用例
5. 前端：工序档案字段 → 排产设置项 → 方案卡/确认窗格依据行 → 补填弹窗覆盖入口

**预计工作量：后端 1~1.5 天，前端 0.5~1 天（不含测试打磨）。**

---

## 六、验收标准

- 有报工史的工序：方案卡显示 **实测** 依据（人数、人均、效率、窗口）
- 无史工序：显示 **标准** 依据
- 覆盖值 > 0：显示 **手动覆盖** 且优先于实测
- 未配置且无史：仍抛错，引导到补填弹窗（现状行为不变）
- 日/周负荷、插单仿真与出方案口径一致（同一 cap_map 来源）

---

## 七、验收样例（可运行）

**测试文件：** `tests/test_aps_actual_capacity_scenario.py`（`pytest tests/test_aps_actual_capacity_scenario.py -s -v`，4 例全过）

**数据规划**（每单 5000 双，交期 today+30，路线 裁断→针车→成型）：

| 工序 | 单人产能×标准人力 | 报工史 |
|---|---|---|
| P1 裁断 | 400×2 | 女鞋款 2人×5天×350/人/天；运动鞋款 2人×4天×320/人/天 |
| P2 针车 | 300×4 | 女鞋款 3人×5天×150/人/天；运动鞋款 3人×5天×100/人/天 |
| P3 成型 | 200×3 | 无（回退标准） |

**手工预期 vs 引擎结果（全部 ✔）：**

| 订单 | 工序 | 预期 | 实际 | 来源 |
|---|---|---|---|---|
| X 女鞋 | 裁断 / 针车 / 成型 | 8 / **12** / 9 天 | 同 | 款级实测 / 款级实测 / 标准 |
| Y 运动鞋 | 裁断 / 针车 / 成型 | 8 / **17** / 9 天 | 同 | 款级实测（复杂度差异） |
| Z 新款 | 裁断 / 针车 / 成型 | 4 / **7** / 9 天 | 同 | 工序级回退 / 工序级回退 / 标准 |
| 覆盖场景 | P2 针车 current_workers=5 | 全部 **4** 天（300×5） | 同 | override 压过实测 |

**结论要点：**
1. 优先级链四级（覆盖 > 款级 > 工序级 > 标准）与设计完全一致；
2. 复杂度被真实捕捉：同 5000 双，运动鞋针车 17 天 vs 女鞋 12 天（人均 100 vs 150）；
3. 效率比暴露标准配置失真：针车实测效率仅 0.33~0.50（标准 300 定得乐观）——数据自己会提示修正 `per_worker_capacity`，不靠算法硬扛；
4. 三单成型段（9/7~9/17）挤在同一标准窗口 → 成型是共同瓶颈，周负荷会标出——供军师/负荷提醒消费。

---

## 八、延伸验收：缺料齐套 × 急单插单 × 实测产能（联合场景）

**测试文件：** `tests/test_aps_combined_scenario.py`（4 单：O1 女鞋 5000 / O2 运动鞋 5000 / O3 新款缺料 5000（大底 T+10 到料、缺 2000）/ O4 急单 3000，`pytest tests/test_aps_combined_scenario.py -s -v`）

**验证结论：**
1. **等料闸门 > 插单优先级 > 实测产能，三者互不冲突**：O3 首道裁断在 保交期/保现场/折中 三个方案下最早均为 T+10（齐套日），急单撬不动闸门，备注均带"等料至…再开工"；
2. **实测产能贯穿插单仿真**：急单 O4 针车 7 天（款级 150×3）、O2 针车 17 天（复杂度）、O3 针车 7 天（工序级回退 125×6），与主场景口径一致；
3. **三策略取舍**：急单置顶完工 09-11（偏紧）vs 置后 10-15（逾期）；**保现场会把缺料单压后**（O3 从 09-23 → 10-27）；
4. **引擎特性（重要，UI 话术要用）：simulate_insert 是"预览"，日期级挤延不发生在预览里**——`delivery_first` 锚定日期不做产能顺延（只标"产能不足"风险），`capacity_first` 插单置后不影响前单；**真正移动已排单日期的是急单确认落库（`_apply_rush_impact_locked`）**。预览显示"未挤其它单"不代表落库不会动，反之亦然——需向 PMC 讲清"预览看风险、确认才动单"。
