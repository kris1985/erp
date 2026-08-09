# P0-1 走查：齐套日硬卡排产开工

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P0-1  
> **代码：** `schedule_engine._plan_route_item` / `_earliest_starts_for_orders` · `schedule_service.confirm_draft`

## 结论

缺料单生成排产方案时，首道（及整条路线）开工日 **≥ 预计齐套日**；确认草稿时若开工早于齐套日 → `kit_ready_too_early`。

## 证据

```text
.venv/bin/python -m pytest tests/test_p0_kit_ready_schedule.py tests/test_schedule_engine.py tests/test_a2c_schedule_compare.py -q
→ 12 passed
```

| 用例 | 结果 |
|------|------|
| `test_proposals_start_not_before_kit_ready` | 保交期/保现场方案 `earliest_start`=ETA；窗口 start ≥ 齐套日；notes 含「等料至」 |
| `test_confirm_rejects_start_before_kit_ready` | 草稿 start=今天 < 齐套日 → 确认抛 `kit_ready_too_early` |
| 既有引擎 / A2c | 回归通过 |

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 落地 + 单测走查通过 |
