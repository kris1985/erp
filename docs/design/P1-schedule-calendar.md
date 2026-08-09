# P1-7 走查：加班开关 + 停工日

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-7 · [`schedule-params-sme-decision.md`](./schedule-params-sme-decision.md)

## 结论

- `allow_schedule_on_non_workdays`：true 时周末/法定假可排
- `schedule_blackout_dates`：停工日**优先**，即使加班模式也不排
- 排产入口经 `schedule_calendar.use_schedule_calendar(cfg)` 绑定租户配置
- 排产页「计划设置」可读写上述字段 + 合批推荐旋钮（交期窗/同色/最小量/负荷预警）

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_schedule_calendar.py tests/test_p0_kit_ready_schedule.py tests/test_schedule_engine.py tests/test_a2c_schedule_compare.py -q
→ 15 passed
```

| 用例 | 结果 |
|------|------|
| 加班开 → 周六可排 | ✅ |
| 加班开 + 停工日=周六 → 仍不可排，next→周日后工作日 | ✅ |
| 默认空配置 ≡ cn_holidays | ✅ |
| PATCH schema 含日历/合批字段 | ✅（`ScheduleSettingsPatchIn`） |
| UI「计划设置」对话框 | ✅ `ScheduleAdminView` 加载/保存 |

设置经 `GET/PATCH /api/v1/schedule/settings` 读写。

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 后端日历策略 + 单测 |
| 2026-08-09 | 补齐 UI 设置面板 + PATCH 入参字段；走查通过 |
