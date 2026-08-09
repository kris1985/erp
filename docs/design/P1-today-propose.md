# P1-2 走查：今日可排 → 一键出方案

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-2 · A0

## 结论

- `kit_schedule` / `kit_partial` / `delivery_risk` 的 `ui_path` 带 `order_ids` + `propose=1`
- 排产页读到 `propose=1` 后自动打开智能方案弹窗（预填勾选单）
- 工作台点击兜底也会补 `propose`

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_today_propose.py tests/test_analytics.py::test_today_actions -q
→ 3 passed
```

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 深链 + 自动出方案；走查通过 |
