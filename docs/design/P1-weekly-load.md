# P1-1 走查：周负荷汇总

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-1

## 结论

- `GET /schedule/load/weekly`：自然周（周一～日）汇总超载天 / 预警天 / 峰利用率
- 排产页「周负荷」Tab 可读出本周/下周超载几天

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_weekly_load.py -q
→ 1 passed
```

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | `weekly_load` + API + UI Tab + 单测；走查通过 |
