# P1-5 走查：缺料批量导出 + 企微推送

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-5 · 复用 A2d Webhook

## 结论

- `GET /material-shortages/export.xlsx`：Excel 含款号、缺料物料、预计齐套日、风险等级/原因
- `POST /material-shortages/push-im`：摘要推到租户企微/钉钉群机器人 Webhook（与 A2d 同通道）
- 缺料汇总页「导出 Excel」「推送企微」

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_shortage_export.py -q
→ 2 passed
```

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 导出服务 + API + UI + 单测；走查通过 |
