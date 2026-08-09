# P1-6 走查：合批推荐引擎 HITL

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`aps-dev-review.md`](./aps-dev-review.md) P1-6 · [`merge-batch-aps-alignment.md`](./merge-batch-aps-alignment.md) §11～12

## 结论

- 推荐规则：同款 +（默认同色）+ 交期窗（默认 7 天）+ 首道齐套 + 最小合计双数
- **只荐不落库**；采纳走既有 `POST /merge-batches`
- 排产池「合批推荐」为主入口；订单页手工组批保留

## 证据

```text
.venv/bin/python -m pytest tests/test_p1_merge_suggest.py -q
→ 5 passed
```

| 用例 | 结果 |
|------|------|
| 同款同色窗内聚成组；异色/异款不并 | ✅ |
| 未齐套不参与 | ✅ |
| `merge_min_qty` 过滤碎组 | ✅ |
| suggest 不写 MergeBatch | ✅ |
| 采纳 create 后不再荐同组成员 | ✅ |

| 接口 / UI | |
|-----------|--|
| `GET /api/v1/merge-batches/suggestions` | 只读荐组 |
| `ScheduleAdminView`「合批推荐」 | 展示 +「采纳组批」 |

## 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 引擎 + API + 排产池 UI + 单测；走查通过 |
