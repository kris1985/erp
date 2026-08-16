# Unified DeepAgent —— Tool-first Direct Path（架构定稿）

> 状态：**定稿**。取代 `agent-orchestration-runtime.md` 的顶层编排图方案与
> `semantic-compiler-cross-turn.md` 的独立跨轮继承方案。

## 1. 结论

`create_deep_agent` 是唯一根图（单一执行范式）。主模型的**第一次调用**同时
完成意图识别、指标选择、时间解析、上下文继承、Filter 编译与「走 direct
还是探索路径」的路由判断；命中强类型 `query_metric_direct`（return_direct）
后，工具内完成权限/租户/证据/渲染的可信链并直接进入 `after_agent` 统一收尾；
未命中则自然进入 model/tools/subagents 循环，最终同样汇入 `after_agent`。

```
create_deep_agent（唯一根图，单一 tool loop）
├── Dynamic System Prompt
│   ├── 权限过滤后的 Metric Capability Index（紧凑：id/名称/一句语义/维度/粒度）
│   ├── 继承规则（承接词优先继承上轮成功 Tool Call 的未改字段；
│   │             不继承失败或未通过证据校验的请求）
│   └── Direct Tool 独占调用规则
├── DirectToolCallPolicy.after_model
│   └── query_metric_direct 必须是唯一 Tool Call（混合 → 注入策略消息跳回
│       model 重试一次；再犯 → jump_to=end 受控拒绝，不执行任何工具）
├── query_metric_direct（强类型 DirectMetricRequest，return_direct=True）
│   └── DirectMetricExecutor 可信链（Tool 内，不信任主 Agent 参数）：
│       schema 重校验 → 能力注册 → 权限/租户 → 数据执行
│       → evidence 校验 → 契约校验 → 确定性渲染 → DirectArtifact
│       成功 / 受控拒绝 / 参数错误 → ToolMessage(artifact) → after_agent
├── query_metric（弱类型探索工具，保留）：复杂/多步分析路径，标准 loop
├── 其他 tools / subagents
├── ToolCallLimitMiddleware + recursion_limit（预算封顶）
└── FinalizeMiddleware.after_agent（统一收尾）
    ├── 归一：最后一条 ToolMessage(artifact) 按 status 分支，或 AIMessage
    ├── 共用输出 guardrail（apply_evidence_guardrail）
    ├── evidence ledger + presentation
    ├── 幂等持久化（record_run run_id 覆盖 / _save_ui_messages 覆盖写）
    └── UnifiedResponse（调用方只读 state["response"]）
```

## 2. 为什么这是最优方案（决策记录）

1. **单一执行范式**：一个根图、一个 checkpoint、一个 message history、一个
   LangSmith root run、一个 tool-call 协议、一个最终输出层。服务层旁路
   （旧 `run_fast_path`）与图内 Agent 两套生命周期彻底消除。
2. **主模型一次完成语义理解与路由**：相比「语义编译模型 + Router + Agent
   模型」，不再重复理解用户意图；function calling 参数由 API 层保证结构
   （DeepSeek 不支持 `response_format=json_schema`，这是最可靠的结构化通道）。
3. **return_direct + after_agent 语义正确**：LangChain 图装配把 return_direct
   工具执行后的出口指向 exit_node（after_agent 链），链路为
   model → query_metric_direct → FinalizeMiddleware.after_agent → END，
   不绕过统一收尾。
4. **可信链在 Tool 内是正确的安全边界**：主 Agent 有决策权（生成参数），
   但没有绕过业务规则的权力（参数/权限/证据/渲染全部重校验）。

### 与旧方案的对比（为何被取代）

| 维度 | 顶层图（已废弃） | FastPathMiddleware（已废弃） | Tool-first Direct Path |
|---|---|---|---|
| 根 | 自建 ConversationRuntime | create_deep_agent | create_deep_agent |
| 路由 | 确定性 Router（输入来自 LLM 编译） | before_agent 判定 | 主模型 Tool Call |
| 执行范式 | FastPath 子图 + DeepAgent 子图（双范式） | 短路 + agent loop（双范式） | 单一 tool loop |
| 结构化 | prompt-JSON + 本地 parse | prompt-JSON + 本地 parse | function calling 原生 |
| 可信链覆盖 | 2 个指标 | 2 个指标 | 全部指标（注册即覆盖） |
| 继承 | semantic_compiler 独立 LLM | semantic_compiler 独立 LLM | 主模型读 messages + 上轮 artifact |

关键洞察：**「确定性路由」是虚假的确定性**——路由输入（semantic_plan）本身
是 LLM 编译产物，Router 只对编译成功后的结果做注册表校验，LLM 理解偏时
Router 发现不了。真正的确定性（数值计算/证据校验/渲染）任何方案都在代码里。
Tool-first 把路由交给模型（它擅长的语义理解），把确定性留在 Tool（代码），
并让可信链覆盖全部指标——这是比「2 个指标做极致」更正确的分配。

## 3. 关键设计点

### 3.1 DirectToolCallPolicy（独占调用，上线阻断项）

return_direct 的退出判定（`_make_tools_to_model_edge`）基于「最后 AIMessage
的**全部** client-side tool_calls 是否 return_direct」——若模型混合调用
query_metric_direct 与其他工具（尤其写操作），LangGraph 会**执行全部工具**
后回模型，direct 短路被破坏且其他工具可能已产生副作用。因此 after_model
强制独占：

- direct 出现且唯一 → 放行（执行后 return_direct 短路）
- 混合 → 第一次：注入策略 SystemMessage + `jump_to="model"` 重试；
  第二次（`_direct_policy_attempts ≥ 1`）→ `jump_to="end"` 受控拒绝。
  预算由 ToolCallLimitMiddleware / recursion_limit 双重封顶。

### 3.2 DirectArtifact 契约（ToolMessage.content JSON）

```
status: success | rejected | missing_user_input | ambiguous_user_input | model_argument_error
reply / presentation / detail / trust_metrics / evidence / fast_path / reason_code / clarification
```

- `success`：确定性执行完成
- `rejected`：权限（POLICY_DENIED→reject）/ 证据不足（EVIDENCE_FAILED→fail_closed）/
  契约拦截（CONTRACT_VIOLATION→fail_closed）
- invalid 家族（不归咎用户，文案一律「当前未能形成有效查询…」）：
  - `missing_user_input`：用户没说清 → after_agent 生成澄清问题
  - `ambiguous_user_input`：多个合理解释 → after_agent 提供选项
  - `model_argument_error`：用户说清了但模型参数非法（未注册指标/limit 越界/
    维度不支持）→ 受控结束（return_direct 静态属性，失败无法回到 model loop，
    固定预算优先）

### 3.3 ToolErrorNormalizer（错误归一化，上线门槛 2）

Pydantic 校验/业务异常可能发生在 Tool body 之前或之中，不保证生成 artifact。
wrap_tool_call 包裹 direct 工具执行，异常 → 归一化 artifact ToolMessage；
FinalizeMiddleware 同时兼容 artifact 与框架原始错误 ToolMessage（兜底，
不假设 artifact 永远存在）。

### 3.4 FinalizeMiddleware（统一收尾）

- 最后一条消息判定：ToolMessage（direct artifact，按 status 分支）或
  AIMessage（agent 路径）→ 统一归一为 UnifiedResponse
- 共用输出 guardrail 只做「输出校验」，不做业务裁决（业务验证在
  DirectMetricExecutor 内、跳转之前完成——若推迟到 after_agent，短路后
  发现证据不足已无法回到 model 路径）
- 持久化幂等：`record_run` 按 run_id 覆盖（INSERT OR REPLACE）、
  `_save_ui_messages` 覆盖写、`_upsert_conversation` upsert；direct 路径
  追加本轮消息到历史（不覆盖丢历史）。失败不静默 except:pass——记录日志，
  进入本地账本，不阻断响应。

### 3.5 跨轮继承（由主模型完成）

上一轮 Tool Call 参数保留在 messages（AIMessage.tool_calls + ToolMessage
artifact 的 status），主模型直接读取继承。「那上个月呢 / 只看前三个 / 换成
销售数量」由模型输出新参数，Tool 重校验（确定性在数值层）。独立
semantic_compiler 退役；prompt 中保留规则：「承接表达优先继承上一轮成功
请求的未修改字段；不得继承失败或未通过证据校验的请求」。

### 3.6 权限过滤的指标索引（缓存边界）

`_build_agent` 每次调用重建 system prompt（mem_block 含权限过滤后的能力
索引）——不缓存 compiled agent/prompt，天然无跨用户泄漏。索引只放选择所
需信息（id/名称/一句语义/维度/粒度），权威定义（口径/权限/公式/版本/
evidence 规则）在 Registry 与工具内。

## 4. 上线门槛（全部为硬条件）

1. **direct Tool Call 独占**：DirectToolCallPolicy 强制（已实现）。
2. **错误归一化**：ToolErrorNormalizer + FinalizeMiddleware 兼容（已实现）。
3. **普通指标工具不得成为校验逃逸路径**：query_metric 与 direct 共享
   workshop_metrics 执行层（Registry/权限校验）；direct 额外有证据校验 +
   确定性渲染。工具描述区分「完整单指标查询 → direct；复杂探索 → query_metric」。
4. **语义忠实度评测**：`scripts/eval_direct_semantics.py`——metric /
   dimension / time / filter / order / limit / inheritance / direct-vs-agent
   routing 准确率。覆盖：本月/上月/去年同期、那华东呢、只看女鞋、前十呢、
   换成销售数量、刚才第二名的上个月表现。**未通过不得上线**。

## 5. LangSmith 结构

```
workshop-agent run（LangChainTracer root）
├── DirectToolCallPolicy.after_model
├── query_metric_direct（tool run）
│   └── direct_metric_execute（fast_path_traced 子 span，继承当前 run tree）
│       ├── schema/registry/permission/tenant
│       ├── execute
│       └── evidence_validate + render
└── FinalizeMiddleware.after_agent
    ├── shared_guardrail
    ├── presentation
    └── persistence
```

FastPath 内部函数不再显式创建独立 root trace（`fast_path_traced` 语义已改
为「继承当前 run tree 的子 span；无 active run 时独立，fail-open」）。

## 6. 模块清单

| 模块 | 职责 |
|---|---|
| `app/runtime/workshop/request.py` | DirectMetricRequest（强类型 Tool args schema）|
| `app/runtime/workshop/executor.py` | DirectMetricExecutor（可信链执行 + DirectArtifact）|
| `app/runtime/workshop/direct_tool.py` | query_metric_direct 工具（return_direct）|
| `app/runtime/workshop/direct_tool_policy.py` | DirectToolCallPolicy（独占调用）|
| `app/runtime/workshop/tool_error_normalizer.py` | ToolErrorNormalizer（错误归一化）|
| `app/runtime/workshop/finalize_middleware.py` | FinalizeMiddleware（统一收尾/持久化）|
| `app/runtime/workshop/state.py` | WorkshopAgentState（领域 state schema）|
| `app/runtime/workshop/context.py` | WorkshopContext（run-scoped 上下文）|
| `app/runtime/workshop/types.py` | 统一类型（UnifiedResponse/DirectArtifact/…）|
| `app/runtime/workshop/fallback.py` | 显式 fallback 状态机（reason_code→action）|
| `app/runtime/workshop/util.py` | last_human_text 等 |
| `tests/test_workshop_direct.py` | executor 测试 |
| `tests/test_workshop_middleware.py` | middleware 测试 |
| `tests/test_workshop_integration.py` | 端到端图链路测试 |
| `scripts/eval_direct_semantics.py` | 语义忠实度评测（上线门槛 4）|

## 7. 退役清单

- `app/services/agent_fast_path.py`（旁路执行链）→ DirectMetricExecutor 替代
- `app/services/semantic_compiler.py`（独立跨轮继承 LLM）→ 主模型继承替代
- `app/runtime/orchestration/`（顶层编排图）→ 本方案替代
- `app/runtime/workshop/fast_path_middleware.py` / `runner.py`（中间方案）
- 对应测试与 shadow/probe 脚本一并删除

## 8. Presentation Spec —— 展示语义协议（v1.0）

**边界**：后端决定「数据语义与推荐展示类型」，前端决定「视觉样式与交互」。
后端输出类型化 `PresentationSpec`（schema_version=1.0），不输出
HTML/React 卡片；前端组件注册表渲染，未知类型降级通用表格 → 确定性 reply。

### 8.1 协议类型（第一版固定）

```
PresentationType = metric | metric_delta | table | ranking | timeseries
                 | comparison | sections
```

- `metric`：KPI 卡片（value 保留原始数值 + format 元数据）
- `metric_delta`：KPI + 环比（后端只给 direction 语义 up/down/flat，
  颜色/箭头由前端决定）
- `table`：多列明细（columns 带 key/label/data_type/unit/format；
  rows 保留原始数值，前端可排序/筛选/换单位）
- `ranking`：排序列表（category_key/value_key + items；
  recommended_visual=horizontal_bar，前端可降级为列表/表格）
- `timeseries`：时间序列（x/points，前端绘制折线/tooltip/坐标轴）
- `comparison`：多指标对比；`sections`：多区块复合（嵌套 PresentationSpec）

### 8.2 类型选择（确定性规则，不写 if metric_id ==）

`PresentationBuilder` 依据：指标 Registry 展示元数据
（`METRIC_PRESENTATION_META`：unit/default_format/default_scale/
presentation_rules）+ result shape + 用户 presentation_hint：

    无维度 + 单值          → metric
    无维度 + 对比值        → metric_delta
    时间维度 + 连续周期    → timeseries
    非时间维度 + 排序+limit → ranking
    多列明细              → table
    多指标对比            → comparison
    多区块复合            → sections

`presentation_hint`（auto/metric/table/ranking/line/bar）由 Tool 参数携带，
后端必须校验适用性（单个标量不能被渲染为趋势图——hint 不适用则回退规则）。

### 8.3 Artifact 两层结果

```
DirectArtifact: { status, reply, result, presentation, evidence, result_id, ... }
  - reply: 确定性文本答案
  - result: 规范化业务数据（原始数值，如 sales_amount=2350000 而非 "235 万元"）
  - presentation: 展示协议（前端渲染依据）
  - evidence / result_id: 可信依据与后续追问/展开明细
```

### 8.4 前端组件注册表

`web/src/components/assistant/PresentationSpecView.vue`：
`presentationRenderers` 映射协议类型 → 渲染器；`activeRenderer ?? FallbackTable`
保证未知类型 → 通用表格 → reply 文本（后端升级协议旧前端不白屏）。
`AssistantChatPanel.vue` 展示链首分支按 `schema_version === '1.0'` 接入，
旧类型分支（metric_snapshot/period_comparison/…）保留兼容。

### 8.5 SSE 顺序（after_agent 完成校验后）

```
event: presentation  (PresentationSpec)
event: token         (确定性 reply)
event: done          (UnifiedResponse)
```

未经 evidence/guardrail 验证的 Tool 原始结果不提前显示（direct 路径
`query_metric_direct` 的 ToolMessage 在 SSE 层被跳过，事件全部在
FinalizeMiddleware 之后发出）。

### 8.6 测试

`tests/test_workshop_presentation.py`：类型选择、hint 适用性校验（标量 →
line hint 被拒绝）、format 元数据、原始数值保留、schema_version 固定。
`vue-tsc --noEmit` + `vite build` 通过。
