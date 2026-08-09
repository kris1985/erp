# A2c 设计：排产方案对比卡

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md)
> **退出标准（`okr-roadmap-triage.md` KR1）：** 排产 A/B 方案对比卡（延期单数/负荷峰）可演示

## 结论：已有引擎 + 补前端展示

`app/services/schedule_engine.py::generate_proposals` 早已生成 2～3 套确定性规则方案
（保交期 / 保现场 / 仅排齐套），每套方案自带 `risks`（延期计数）与 `load`（按工序×日
的负荷/利用率快照，含 `over_capacity`）。**缺口只在前端**：`ScheduleAdminView.vue`
的「智能方案」弹窗此前只展示 5 个风险 tag（余量充足/交期偏紧/预计逾期/产能不足/
缺料卡住），**没有把 `load` 里的负荷峰信息汇总展示**，也没有把「延期单数」做成
可一眼对比的头部数字——方案是并排卡片，但不构成可读的 A/B 对比卡。

本次改动：在既有并排卡片基础上，为每张方案卡新增一行「对比头」，从后端已返回的
`risks` / `load` 字段派生并展示两个头部指标：

- **延期单数** = `risks.late + risks.capacity_blocked`（预计逾期 + 产能不足单，二者都意味着该方案下会晚交）
- **负荷峰** = `load` 中利用率最高的工序×日（`utilization` 峰值 %），并附超产能天数

不改排产引擎/算法，仅前端读取已有字段做聚合展示。

## 走查证据

代码证据：[`tests/test_a2c_schedule_compare.py`](../../tests/test_a2c_schedule_compare.py)
构造一笔急单（400 双 / 3 天交期）+ 一笔正常单（200 双 / 60 天交期），产能配置为
20 双/天，跑 `generate_proposals` 后用与前端 `proposalHeadline()` 完全一致的算法
在 Python 侧复算：

```text
=== A2c 排产方案对比卡 · 走查证据 ===
[保交期(delivery_first)] 延期单数=2 负荷峰=1000% @ 裁断 2026-08-10 超产能天数=5
[保现场(capacity_first)] 延期单数=2 负荷峰=None% @ None None 超产能天数=0
```

两套方案「延期单数」相同，但「负荷峰」截然不同——保交期方案把急单堵在最前，工序
利用率冲到 1000%、连续 5 天超产能；保现场方案顺延避冲突，全程不超产能（用交期
换负荷）。这正是对比卡该呈现的取舍信息：**同样的延期单数下，两套方案对现场冲击
完全不同**，帮 PMC/厂长判断该选哪套。测试断言了两策略的 `over_days` 确实不同，
防止未来改动让对比卡退化成"数字一样、看不出区别"。

后端单测：`tests/test_schedule_engine.py`（9 项，覆盖可复现 proposal_id、产能标红、
插单仿真影响）与新增 `tests/test_a2c_schedule_compare.py` 全部通过：

```text
$ pytest tests/test_schedule_engine.py tests/test_a2c_schedule_compare.py -q
10 passed
```

前端：`npx vue-tsc --noEmit` 无报错；`npm run build` 构建通过（`ScheduleAdminView`
chunk 正常产出）。

## UI 改动

文件：`web/src/views/admin/ScheduleAdminView.vue`（排产页 →「智能方案」弹窗，
`/admin/schedule`）。

- 新增 `proposalHeadline(p)`：从方案的 `risks` / `load` 派生「延期单数」「负荷峰」
  （峰值利用率 % + 命中工序/日期 + 超产能天数）。
- 每张方案卡头部新增一行两列对比区（`.proposal-compare`），置于原有风险 tag 之上，
  一眼可比：

  | 对比区字段 | 取值 |
  |------------|------|
  | 延期单数 | `risks.late + risks.capacity_blocked`，>0 时标红 |
  | 负荷峰 | `load` 峰值利用率 %（`—` 表示无产能配置数据）；副行显示命中工序/日期，超产能天数>0 时数字标红 |

- 原有风险 tag（余量充足/交期偏紧/预计逾期/产能不足/缺料卡住）与「采用进草稿」
  操作保持不变；不改 `generate_proposals` / `_build_load_snapshot` 等引擎代码。
- 车间军师（`ScheduleAssistantView.vue`）不复述本卡数字；banner 已明确「规则引擎
  『智能方案』仍可在排产页独立使用」，军师侧维持只解说、不接管排产写路径。

## 主路径

1. 排产页「待排池」勾选订单（或不选=全部待排）→ 点「智能方案」。
2. 弹窗并排展示 2～3 套方案卡，每卡先看头部「延期单数 / 负荷峰」对比，再看风险
   tag 明细与摘要文案。
3. 选中偏好的一套 →「采用进草稿」→ 进入既有倒排草稿流程，仍需人工确认落日期/派工。

## 通过标准（对照 §7.0 通用 DoD + 本条专项）

- [x] 主路径可在演示环境走通（种子数据 + 单测复算一致）
- [x] 至少两套方案并排可见，且「延期单数」「负荷峰」两个指标在卡片头部直接可读
- [x] 数值来自既有规则引擎返回字段（`risks`/`load`），未新增/重写排产算法
- [x] 军师（AI）不参与生成或篡改该卡数字，仅可在对话中引用/解说
- [x] 权限：入口挂在既有排产页写操作按钮组下，无排产权限用户不可达（沿用现有路由/菜单权限）

## 负面/不做

- 不做蒙特卡洛式概率分布主 UI（`okr-roadmap-triage.md` 已定：确定性对比卡足够）
- 不新增第三方案以外的排产策略；`kit_ready`（只排齐套）仍按候选是否存在部分缺料
  订单才出现，逻辑不变
- 不在对比卡内直接编辑日期/产能参数（仍走排产设置页）
