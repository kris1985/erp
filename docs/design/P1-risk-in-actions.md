# P1-3 走查：风险根因进今日行动 / 军师

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-3 · A1b

## 结论

- 今日行动 facts 追加 A1b 风险码（`overdue`/`delivery_risk`/`rush`/`material`/`kit_ready`/…）与预计齐套日
- 齐套诊断行带 `kit_ready_date`；交期 `focus_orders` 带 `order_id`
- 军师既有约束「只引用 evidence」即可吃到这些 facts，不口编

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_risk_in_actions.py tests/test_analytics.py::test_today_actions -q
→ 2 passed
```

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | `_risk_evidence_lines` + 今日行动接入；走查通过 |
