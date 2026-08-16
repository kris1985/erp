# Semantic Compiler — 跨轮继承切片（第一落地块）

> 定稿（2026-08-17）。回答「是否继承应该由 LLM 判断吗？」——**是**。跨轮
> 追问（「只显示top3」「大于500万的」「上月呢」）的判断本质是语义理解，正则
> 枚举永远追不上。本切片把继承判定交给 LLM，但守住两条确定性边界：校验在
> 代码里、失败不 fallback。

## 1. 背景与根因

turn2 追问之前靠**两层正则**：

1. `_detect_filter_followup`（agent_fast_path）：`_FILTER_RE`（大于X万）+
   `_LIMIT_FOLLOWUP_RE`（只显示top3/前3名…）——**枚举词表**，任何新说法
   （「按金额排序」「top3 的客户」「倒数三名」）都不在表里 → 掉进 LLM 路径
   牛头不对马嘴。
2. `_inherited_year`：从回复文本正则抠年份——上轮信息不可靠。

用户连续三次点破同一根：**正则 planner 承担了它承担不了的语义理解**
（最高级、复合、跨轮继承）。正确方向是 Semantic Compiler（LLM propose +
约束校验），本切片是它在跨轮场景的第一个实现。

## 2. 架构（新模块 `app/services/semantic_compiler.py`）

```
turn2 问题 + 上轮上下文（结构化投影）
  │
  ├─① LLM propose（with_structured_output，temperature=0）
  │     InheritanceProposal {
  │       inherits: bool,
  │       refine: { limit? ∈[1,100], min_amount? >0,
  │                 period?: last_month|last_year|this_year|this_month }
  │     }
  │     → 判断是不是同主题追问、要改什么参数
  │     → 拿不准一律 inherits=false（宁可当新问题，不猜 refine）
  │
  ├─② 确定性校验（代码，不信任 LLM 自觉）
  │     ✓ 上轮确有 Fast Path 排行轮次（查 ui_messages 结构化 presentation，
  │       不抠回复文本）
  │     ✓ 上轮 analysis_type 是 ranking（metric_snapshot 轮次由快照路径处理）
  │     ✓ refine 至少一个参数；limit/min_amount/period 各自合法
  │     ✗ 任一不满足 → requires_clarification / not_applicable
  │
  └─③ 确定性执行（现有 Fast Path 可信链）
        RankingRequest(limit/min_amount/year/month) → Resolver → Router
        → 执行 → Renderer（可信链不变）
```

## 3. 边界决策（延续「不 fallback」原则）

| 场景 | 行为 | 理由 |
|---|---|---|
| LLM 判继承 + 参数合法 + 上轮是 ranking | `inherited` → 执行 | 正常路径 |
| LLM 判继承但上轮不是 ranking | `not_applicable` | 轮次类型不符，快照路径自己处理 |
| LLM 判继承但无 refine 参数 | `requires_clarification` | 没说要改什么，不猜测 |
| LLM 判新问题（inherits=false） | `not_applicable` → 按新问题编译 | 正常 |
| LLM propose 失败 | `unavailable` → 明确失败（observational+原因） | **不 fallback**，不静默掉 LLM 主链 |
| 无 Fast Path 历史 | `not_applicable`（即使 LLM 误判继承也拒绝） | 校验在代码里 |

## 4. 上轮上下文结构化（废除文本抠取）

- Fast Path 写 ui_messages 时，presentation 现在携带
  `analysis_type / year / month / limit`（`agent_fast_path.py` 两处）。
- `_read_previous_fast_path_turn` 从 presentation 读结构化字段，
  `_inherited_year`（正则抠年份）已删除。
- 只读短连接（sqlite3 直连），不触碰 schedule_agent 的共享 `_catalog_conn`。

## 5. 废除的正则

- `_detect_filter_followup` / `_inherited_year` / `_FILTER_RE` /
  `_LIMIT_FOLLOWUP_RE` / `_cn_to_int`（agent_fast_path 内）——全部删除。
- 保留：planner 的单轮正则 `plan_finance_question`（仍作单轮确定性解析，
  跨轮不再走正则）。⚠️ 注意：单轮正则仍是「LLM propose」前的先行层，后续
  Compiler 单轮切片会再评估其退役。

## 6. 测试

- `tests/test_semantic_compiler.py`（7 用例）：inherited(limit/min_amount/
  period 回绕)、无历史拒绝、无 refine 澄清、LLM 不可用、结构化读取。
- `tests/test_agent_fast_path.py`：5 种 limit 追问 E2E（mock propose）、
  无历史不适用、requires_clarification、unavailable。
- `tests/test_sse_fast_path.py`：过滤追问 SSE 链路（mock propose）。

## 7. 与主 Compiler 的关系

本切片是「LLM propose + 确定性校验」模式在跨轮场景的第一个实现。后续：
- 单轮原子 propose（问题 → 原子列表）→ 同一模式
- 复合/混合问题 → 原子列表 + 拆漏检查 + partially_compiled
- 最高级/量词 → 由 propose 语义理解，不再补正则

三者共用同一入口与同一「校验在代码、失败不 fallback」边界。
