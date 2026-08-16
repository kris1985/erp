# 前端显示分层契约（Assistant 回答展示）

> 决策定稿（2026-08-17）。回答「LLM 思考内容要不要显示」：**①链式推理（CoT）不显示**；
> ②过程轨迹（工具调用）显示为「查询过程」折叠；③「数据依据/分析说明」永远是
> **可追溯的推导**，不是生成式原文。本契约约束后端 `iter_chat_sse` 的字段语义与
> 前端 `AssistantChatPanel.vue` 的渲染职责，二者一一对应，禁止跨层。

## 分层总览（五个正交层）

```
┌─ ① 正文（reply）──────────── 用户第一眼要的答案
│     Fast Path: 确定性结论句（已校验，kind 无关）
│     LLM 路径:  guardrail 通过的摘要（decision + reason，可追溯）
│
├─ ② 结构化卡片（presentation）── 数据本身，不用语言
│     按 analysis_type 注册的形态（ui-contract.yaml）：表格/排行/构成/对比…
│     列 ≤ 6、行 ≤ 20；数字来自 Fact/Verified Assertion，非 LLM 自算
│
├─ ③ 依据（evidence 折叠）────── 数字从哪来（工具证据）
│     build_evidence_ledger：来源卡片 = 指标 + 状态 + 事实 + 时间
│
├─ ④ 分析说明（detail 折叠）──── 结论是怎么算出来的（可追溯推导）
│     Fast Path: kind="deterministic"，Renderer 生成
│       （查询范围 / 数据来源 / 计算方式 / 判断依据 / 查询时间）
│     LLM 路径:  kind="summary"，结构化拼接
│       （结论 / 关键原因 / 已核验事实 / 查询过程 / 查询时间）
│     ✗ 永不包含：模型原始回答（raw_reply）、未校验文本
│
├─ ⑤ 状态条（fastPath / fastPathObservation）
│     这条回答走没走确定性可信链（绿色「确定性链路」/ 灰色「观测」）
│
└─ ✗ 永不显示：链式推理（CoT/reasoning tokens）、模型内心独白
     只进服务端 Trace（agent_trace_service），与「State != Model Context」一致
```

## 字段契约（后端 → 前端）

### `detail`（④ 分析说明）

```ts
// 语义统一：永远是可追溯的推导说明
detail?: {
  available: boolean      // false 时前端不渲染折叠块
  kind: 'deterministic' | 'summary'
  content?: string        // available=true 时必填，markdown
}
```

| 路径 | kind | content 来源 | 禁止 |
|---|---|---|---|
| Fast Path（ranking/快照） | `deterministic` | `DeterministicRenderer.render_explanation` | 无 |
| LLM 路径 | `summary` | `_llm_path_detail(summary, reply, tool_evidence)` | **raw_reply**、思考过程、内部字段 |

前端标签（按 kind 区分，标题跟随内容语义）：
- `kind === 'summary'`（LLM 路径）→ **分析说明**（结论/原因/已核验事实）
- `kind === 'deterministic'`（Fast Path）→ **数据依据**（范围/来源/计算/判断依据）

> 命名修正（2026-08-17）：Fast Path 折叠标题由「完整业务分析」改为「数据依据」——
> 内容是该结论「怎么来的」（查询范围/数据来源/计算方式/判断依据/查询时间），
> 是溯源而非分析洞察；「分析」由正文与 presentation 承担，折叠区不冒充分析。

### `tools`（② 过程轨迹，新渲染）

```ts
tools?: { name?: string; content?: string }[]
```
- 来源：SSE `tool` 事件流式缓存 + `done.tool_traces[-8:]`。
- 渲染：折叠「查询过程」，每条 = 工具名 + 一句话摘要（`toolSummary`）。
- 禁止：展开原始 JSON / 完整工具参数。

### `evidence`（③ 依据，现状保留）

来源卡片：`{ id, source, status, facts[], as_of/queried_at }`。

## 三路径对照（验收基线）

| 场景 | 正文 | 卡片 | 依据 | 分析说明 | 状态条 |
|---|---|---|---|---|---|
| 客户销售额排行（Fast Path） | 确定性结论句 | ranking/table | （快照表） | kind=deterministic 完整推导 | 绿色 |
| 本月销售额多少（Fast Path） | 确定性结论句 | metric/table | （快照表） | kind=deterministic 完整推导 | 绿色 |
| 复杂问题（LLM 路径） | guardrail 摘要 | 按类型 | 工具证据 | kind=summary 结构化说明 | 无/观测 |
| 混合/观测（开关关闭） | 同上 | 同上 | 同上 | kind=summary，不显示未校验原文 | 灰色 |

## 测试与回归

- `tests/test_agent_display_contract.py`：
  - LLM detail 不含 raw_reply（回归断言）
  - 无可追溯成分时 `available=false`（前端隐藏）
  - Fast Path detail `kind=deterministic`
- 前端 `vue-tsc --noEmit` 通过；渲染层只消费契约字段。

## 关联决策

- ① CoT 不显示：`agent_orchestration.forbidden`（reasoning/thought/chain_of_thought）
  保持拦截；若要「更透明的推理」，前提是证据链能解释一切，再单独评估。
- ④ 与上一轮 detail 混乱的根因：LLM 路径曾把 `raw_reply` 塞进 `detail.content`
  （2544 行），导致折叠区出现未校验原文与正文重复。本契约将其语义收敛为
  「可追溯推导」，两条路径统一。
