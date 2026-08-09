# P1-4 走查：排产池按合批筛选

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-4

## 结论

- `GET /schedule/pool?merge_batch_id=` 仅返回该合成员生产单
- 池行带 `merge_batch_id` / `merge_batch_no`（open 批）
- 排产池下拉「按合批筛选」+ 合批列

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_pool_merge_filter.py -q
→ 1 passed
```

| 项 | 结果 |
|----|------|
| 筛合批 → 仅成员 2 单 | ✅ |
| 未入批单 merge_batch_* 为空 | ✅ |
| UI 筛选 + 列 | ✅ `ScheduleAdminView` |

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | pool API/服务/UI + 单测；走查通过 |
