# Customer Sales Ranking 垂直切片

> 当前唯一实施范围。除非实现发现 Ranking v1 无法表达或无法确定性验证，否则不再扩展总体设计。

### 2.3 Ranking MVP 实施边界

首期必须跑通的生产链路收缩为：

```text
ResolvedSemanticPlan
  → Metric Execute
  → TypedAnalysisResult / EvidenceEnvelope
  → FactBuilder
  → CalculationEngine / IndependentCalculationValidator
  → AssertionBuilder
  → StructuralValidator
  → VerifiedAssertion
  → DeterministicRenderer
```

首期明确只实现：

- Semantic Compiler 只支持 Ranking 所需的 `metric + dimension + period + filters + sort + limit`，以及总体分母、Top-N 合计和占比的固定依赖；不支持任意多指标混合公式。
- Metric/Dimension/Time Resolver 使用 Registry 确定性绑定；无法唯一解析时输出 `requires_clarification`，不得带歧义进入 Metric Execute。
- Ranking Type Checker 校验指标与客户维度、聚合方式、绝对时间区间、Limit 和 `share_of_total` 子集关系。
- `MetricFact` 与 `DerivedFact` 两类 Fact。
- `rank`、`value`、`share_of_total`、`classification` 四个 Assertion Predicate。
- `TopNTotal` 与 `ShareOfTotal` 两个 Calculation Definition。
- `complete_population`、`top_n`、`truncated`、`unknown` 四种真实参与校验的 Coverage；其他枚举可以保留但不建设复杂逻辑。
- `customer_concentration.high@1.0.0` 一个 Business Rule，不建设通用规则管理平台。
- 薄 Answer Contract：`allowed_predicates + required_assertion_ids + presentation_mode`。Contract 定义许可策略，Validator 只执行策略并返回 `CONTRACT_VIOLATION`，禁止在 Validator 内硬编码“利润/回款”等业务许可。
- Deterministic Renderer 与确定性单位/百分比 Formatter，不接入 LLM Renderer。

首期只预留接口、不接生产主链的能力：`SemanticGroundingValidator`、Post-render Claim Extractor、Recommendation/Hypothesis Claim、Specialist LLM、通用 Operation DAG 执行器、通用 Business Rule Registry。它们不是 ranking Fast Path 的上线依赖；进入开放式归因场景时再实现。

多指标并列查询、跨指标公式和批量混合计算属于后续切片。Compiler 可以返回 `unsupported` 或对真正阻塞字段发起澄清，但不得为了覆盖这些输入提前扩建万能 AST。

这里的“Operation DAG”首期仅指 ranking、总体分母、Top-N 合计和占比之间的显式依赖引用，不包括通用图调度、表达式语言或任意节点编排。


## 四、分阶段实施计划

### P0：阻断上下文与语义污染

### P0.1 引入 Context Projector

- [ ] 新增显式 `ContextProjection` 数据结构，输入为 Conversation、Business、Evidence、Execution 四类状态。
- [ ] 每轮调用模型前只投影：当前问题、已确认约束、当前 Evidence、允许动作和必要业务记忆。
- [ ] 默认排除历史 Tool Call、Tool Result、SubAgent 原文和 Execution State。
- [ ] 仅当上一轮信息形成当前约束、未决问题或用户偏好时才进入 Projection。
- [ ] 为投影增加 Token/字符预算和可观测字段：原始消息数、投影消息数、裁剪原因、预计 Token。
- [ ] 每个进入 Context 的内容块记录 `content_ref`、`projection_reason`、`source_event_id` 和 `token_cost`，使“为什么纳入这段上下文”可审计。

**污染源实测定位（2026-08-15 Trace 归因修正）**：`chat()` 当前构造的模型输入只有 3 条消息（user + preflight + child context），**主要 Token 消耗不是“上一轮完整历史回放”，而是两处全量内联**：

1. `_run_auto_diagnostic_bundle` 生成的 `preflight_context`：把自动诊断多组指标的**完整 `context_rows` JSON** 拼进 system message（`schedule_agent.py` `_run_auto_diagnostic_bundle` 末尾 `json.dumps(context_rows, ...)`）。
2. `_build_agent` 的 `mem_block`：30 条长期记忆 + **全部可见指标目录**（metric_lines 全量拼接）+ 角色说明，再叠加 54 行 `SYSTEM_PROMPT`。

LangGraph `_checkpointer()` 保留的跨轮 `messages` 历史是**次因**（多轮会话时线性增长）。因此 P0 的落点必须同时覆盖以上三处，只做“历史裁剪”达不到 -40% 的验收线。

**v1 落地机制（State ≠ Model Context）**：保留 LangGraph checkpointer/store 用于**持久化与审计**（事件不丢）；但模型调用输入只构造“投影后的 messages”——`agent_messages = [system(基础角色+投影块), user(当前问题)]`，**不把 checkpoint 历史重放进本轮输入**。具体做法：`agent.invoke({"messages": 投影后的 agent_messages})`，并把“历史 messages 仅存在于 checkpoint、不进模型输入”写成单元测试断言（模拟两轮对话后断言第二轮输入消息数 ≤ 3 且不含第一轮 ToolMessage）。跨轮约束继承由 Projection 的 Conversation State（`confirmed_constraints`/`active_entities`/`unresolved_questions`）显式携带，而不是靠重放历史让模型自己回忆。

**建议代码落点**：`app/services/schedule_agent.py` 中 `_run_auto_diagnostic_bundle`（preflight_context 改按 `result_id + schema + summary + preview` 投影）、`_build_agent`（mem_block 改为领域 Top-K 指标 + 必要记忆）、`chat()` 的 `agent_messages` 构造；新增 `app/services/agent_context.py` 承接 ContextProjector。

**验收标准**：

- “本月经营情况”后追问“客户销售额排行”，模型上下文不再包含上一轮完整工具输出。
- 当前轮必要约束（如 2026 年）仍能正确继承，且继承来自 Conversation State 而非历史回放。
- 简单排行问题输入 Token 相比基线下降至少 40%。
- Trace 同时保留完整事件（checkpoint/账本）与实际 Model Context（Projection 快照），二者可独立检查。

### P0.2 消除自然语言模板漂移

- [ ] 删除按宽泛关键词手写的“用户问的是回款/应收或现金流”等运行时判断。
- [ ] 新增 `render_runtime_instruction(semantic_plan, execution_plan, evidence_state)`。
- [ ] 自动诊断标题、回答焦点、允许指标和时间范围全部由 Structured State 渲染。
- [ ] Structured State 与渲染文案不一致时，Match Gate 拒绝进入回答阶段并记录原因。
- [ ] 将“今年/去年同期/截至目前”等相对时间解析为带时区的绝对区间和 `as_of`，并记录自然日、财务期间及区间开闭规则。
- [ ] 对 `fixed_cohort`、`period_top_n` 等比较集合语义执行消歧；未决时禁止进入 Execution Plan。

**建议代码落点**：替换 `app/services/schedule_agent.py` 中 `diagnosis_name`、`answer_focus` 的二分模板。

**验收标准**：

- `ranking/sales_amount/customer` 只能渲染为客户销售额排行语义。
- 排行、利润、回款、应收、趋势、明细六类黄金用例均无语义残留。
- 自动诊断文案不得引入 Semantic Plan 中不存在的指标或分析目标。
- 同一 Trace 能解释“比较的是哪一组客户、这组客户在哪个时点被选中、去年同期截止到哪一天”。

### P0.3 Result Spill 与历史 Tool Result 裁剪

- [ ] 定义 `max_inline_bytes` 和 `max_preview_rows`。
- [ ] 超限结果写入 Result Store，模型只接收 `result_id + schema + summary + preview + truncated`。
- [ ] **该裁剪同样作用于自动诊断链路**：`preflight_context` 内联的完整 `context_rows` 必须走 Result Store 投影，不允许绕过“内联限制”直达模型（这是当前 Token 大头之一，见 P0.1 归因）。
- [ ] 子 Agent 只返回 Typed Result、Fact 引用和协调事项，不返回完整作文式报告。
- [ ] 增加按字段、分页和限量读取 Result 的受控接口。

**与现有 Evidence Guardrail 的关系（保留为第二道门）**：现有 `apply_evidence_guardrail`（`schedule_agent.py` 出口正则检查）继续保留，作为 **egress 最终兜底**，与新的 Structural Claim Validator 并存：Structural Validator 负责“Claim → Fact → Calculation/Rule → Evidence”的结构验证（前置），Guardrail 负责“最终文本中的数字是否都能在工具证据里找到”（后置）。两者验收标准独立：Guardrail 保持现有黄金测试通过率不下降；新 Validator 的失败不得被 Guardrail 掩盖，反之亦然。

**验收标准**：

- 大结果不再完整出现在下一轮 Model Context（含自动诊断链路）。
- 明细可通过同一 `result_id` 按权限继续读取。
- 前端和 Trace 能区分“结果被裁剪”与“数据本身为空”。
- 既有 `apply_evidence_guardrail` 黄金测试全部保持通过。


### P2：建立 Fast Path 与能力路由

### P2.1 Capability Router

- [ ] 新增四级路由：Direct Metric、Deterministic Analysis、Specialist Agent、Multi-Agent Workflow。
- [ ] Router 默认由 Semantic Plan + 确定性 Policy 决策；只有未命中规则的边界情况才允许 Router LLM。
- [ ] 路由结果记录稳定 `reason_code`、`rule_id`、预计成本和实际成本；自然语言原因只用于 Trace UI。
- [ ] 以下类型默认 Fast Path：`metric_snapshot`、`ranking`、`time_series`、`data_table`、`composition`、`period_comparison`。
- [ ] `attribution_analysis`、复杂 `scenario/decision` 和多领域诊断才允许调用 Specialist/SubAgent。
- [ ] Router 决策写入 Trace，包括选择原因、预计成本和实际成本。
- [ ] 路由输出分离为正交字段 `execution_mode` 与 `response_mode`，禁止只记录含义模糊的 `FAST_PATH`。

**Fast Path 的权限/HITL 嵌入点（v1）**：权限检查在 **Router 决策之后、Metric Execute 之前**执行，复用现有 `get_policy_bundle()` 与 `list_metrics(permission_codes=...)` 过滤，与 Agent 路径共用同一策略源，不引入第二套权限逻辑。具体顺序：`Semantic Plan → Router（execution_mode/response_mode）→ Permission Check（指标/维度/租户范围）→ Metric Execute → Evidence`。权限不足时返回 `policy_denied`（`POLICY_DENIED`），不降级为“数据为空”。HITL 不进入 ranking Fast Path 主链（只读查询无需审批）；写操作路径保持现有审批中间件不变。验收：同一 tenant 在 Fast Path 与 Agent 路径下对相同指标的可见性结果一致。

Fast Path 的正式定义是：**没有自主工具规划、没有 SubAgent、没有自由计算、没有不受 Contract 约束的 Claim**，而不是简单等同于“不使用 LLM”。执行路径与回答路径分别选择：

- Execution Mode：`DIRECT`、`DETERMINISTIC`、`AGENTIC`、`MULTI_AGENT`。
- Response Mode：`TEMPLATE`、`DETERMINISTIC_RENDERER`、`LIGHTWEIGHT_LLM`、`SPECIALIST_LLM`。

- Deterministic Renderer：适合 `metric_snapshot`、`ranking`、`data_table`。
- Lightweight Response LLM：只接收 Fact Set + Answer Contract，适合 `composition`、`period_comparison`、`time_series`。

路由基线：

| 问题 | 路径 |
| --- | --- |
| 客户销售额排行 | Direct Metric |
| 本月销售额多少 | Direct Metric |
| 同比多少 | Deterministic Analysis |
| 为什么毛利下降 | Specialist Agent |
| 这个急单能不能接 | Specialist + Simulation |
| 制定下周生产方案 | Multi-Agent Workflow |

例如“客户销售额排行”可记录为 `execution_mode=DIRECT`、`response_mode=DETERMINISTIC_RENDERER`；“趋势怎么样”可记录为 `DETERMINISTIC + LIGHTWEIGHT_LLM`。

**验收标准**：

- 六类简单分析不产生 `task` SubAgent 调用。
- 简单问题 P95 延迟和 Token 成本分别下降至少 30%。
- 复杂跨领域问题仍能保留专业分工、Evidence 和 HITL。

### P3：Prompt 与 Harness 模块化

### P3.1 动态 Prompt Assembly

- [ ] 将系统提示拆为稳定基础段和按需运行时段。
- [ ] 基础段只保留角色、事实原则、业务安全和表达职责。
- [ ] Metric Catalog、Analysis Catalog、格式限制、权限和 HITL 分别由 Registry、Renderer、Policy Middleware 保证。
- [ ] 根据 Semantic Plan 只召回当前领域的 Top-K Metric/Skill 描述。
- [ ] 保持基础 Prompt 和 Tool Schema 顺序稳定，动态内容追加在后缀。

**验收标准**：

- 财务排行上下文不再包含排产、缺料、质量、工时和接单仿真规则。
- 核心安全策略在 Prompt 缩短后仍通过既有黄金测试。
- 缓存命中率相较基线持续提升。

### P3.2 Session Event Log 与 Projection

> 本项为 Projection 抽象稳定后的演进项，不阻塞首个垂直切片。短期允许继续使用现有 LangGraph State 作为数据源，只要保证 `State != Model Context`。

- [ ] 将 User Message、Metric Executed、Tool Result、Approval、SubAgent、Compaction 等定义为持久化事件。
- [ ] Model Context 从事件 Projection 生成，不直接回放事件列表。
- [ ] 增加语义压缩：输出约束、活跃实体、未决问题、可信结果引用和用户偏好，而不是作文式摘要。
- [ ] Projection 结果可缓存，并在相关事件发生时失效。

**验收标准**：长会话轮数增长时，Model Context 不再线性增长；关键约束不因压缩丢失。

### P3.3 Skill/Metric 延迟加载

- [ ] 模型先看到领域级 Skill Catalog，例如经营分析、生产分析、缺料分析、质量分析和排产分析。
- [ ] 选定领域后再加载相关指标、工具和细则。
- [ ] SubAgent 保持为可选 Capability，而不是复杂度稍高就默认调用。

## 五、实施顺序

### 5.1 可信链开发顺序

Ranking MVP 按以下依赖顺序推进；先在现有执行模型下证明可信链，再接入 ContextProjection 和 Fast Path。上一层未具备最小可测试契约时，不启用下一层线上流量：

```text
① ResolvedSemanticPlan + Ranking v1 Contract
        ↓
② TypedAnalysisResult + EvidenceEnvelope
        ↓
③ CoverageGate + FactBuilder
        ↓
④ Calculation + Independent Validation
        ↓
⑤ Automatic Assertion Builder
        ↓
⑥ StructuralValidator → VerifiedAssertions Only
        ↓
⑦ BusinessRule + Thin AnswerContract
        ↓
⑧ DeterministicRenderer
        ↓
⑨ Minimal ContextProjection
        ↓
⑩ ranking Fast Path
        ↓
⑪ Replay + Shadow
```

关键发布约束是：**Router 可以先产出观测性决策，但在可信链和 Structural Validator 完成前，不得把生产流量切换到 ranking Fast Path。** 先证明 Evidence、Fact、Calculation、Rule 与 Claim 的闭环成立，再改变执行路径。

与现有 Phase 的对应关系如下：

1. **Phase 0 — 一致性与契约**：修复 Semantic Plan 漂移，冻结 Ranking v1 核心载荷并完成 Resolved Plan/Typed Result。
2. **Phase 1 — Evidence**：为 `ranking` 建立 Evidence Envelope、Coverage Gate 和 Fact Builder。
3. **Phase 1 — Trusted Derivation**：加入 Calculation Engine、独立重算与最小 Business Rule。
4. **Phase 1 — Assertion Protocol**：构建 Assertion、薄 Answer Contract 与 Structural Validator，产出 Verified Assertion。
5. **Phase 2 — Deterministic Output**：上线 Deterministic Renderer 和单位/比例 Formatter；Semantic Grounding 记为 `not_applicable`。
6. **Phase 2 — Context/Fast Path**：增加最小 Context Projection 和 Result Spill，过滤历史 Tool/SubAgent 原文，在可信链通过后切换 ranking 路由。
7. **Phase 3 — Replay/Shadow**：完成 12-case Replay、新旧链路 Shadow 和灰度回滚。
8. **Phase 4 — Harness**：以真实 Trace 数据演进 Prompt Assembly、Skill 延迟加载、Event Log + Projection，以及其他分析类型；迁移期间保留兼容读取。

### 5.2 建议 PR 拆分

每个 PR 只建立一个可独立审查和回放的边界：

1. **PR #1 — Ranking Contract + Resolved Plan + Typed Result**：冻结 8 个 Ranking v1 核心载荷，完成最小 Resolver、Typed Result/Evidence 组合方式 Spike 和契约序列化测试；不改变现有路由。
2. **PR #2 — EvidenceEnvelope + CoverageGate + FactBuilder**：完成 ranking Evidence 到 `MetricFact` 的转换，并从第一天加入 Case 10 `insufficient_evidence` Replay。
3. **PR #3 — Calculation + Independent Validator**：实现 Top-N 合计、占比、除零/空值/精度处理和独立重算；篡改输出或输入时必须失败。
4. **PR #4 — AssertionBuilder + StructuralValidator**：生成 `rank/value/share_of_total` Assertion，并完成 Metric、Scope、Coverage、Fact、Calculation Binding 等确定性检查。
5. **PR #5 — BusinessRule + Thin AnswerContract + DeterministicRenderer**：只实现集中度规则、许可策略和确定性输出；加入 Case 11 Contract 越界 Replay。
6. **PR #6 — ContextProjection + Ranking Fast Path**：接入最小 Projection，加入 Case 12 跨轮污染 Replay；可信链通过后才开启带开关的 Fast Path。
7. **PR #7 — 12-case Replay + Shadow Metrics**：补齐完整查询集、故意失败、旧新链对比、Token/延迟和 Unsupported Claim Escape 指标。

如果当前 Context 污染已造成线上错误而非仅成本升高，可将 PR #6 中的最小 ContextProjection 提前为独立热修 PR；仍不得与 Evidence/Calculation/Assertion 大规模重构混在同一个 PR。

每个 PR 必须包含对应单元测试、契约序列化测试和必要 Trace 字段；不得用后续 PR 才会提供的安全校验作为当前 PR 上线前提。

Replay fixture 从 PR #1 即建立，固定使用 Python 测试基建目录与编号：`tests/replay/ranking/01-basic.json` 至 `12-cross-turn-pollution.json`，由 `tests/test_replay_ranking.py` 统一加载断言（pytest 布局，`tests/` 下按 `replay/<analysis_type>/NN-name.json` 组织）。每个 fixture 必须记录输入、期望 Plan/Assertion、v1 预期（`supported`/`unsupported`/`gate`）、期望状态和 `reason_code`，全部进入版本控制，禁止到 PR #7 才集中补测试。

## 六、首个垂直切片：客户销售额排行

本节是当前唯一实施范围。设计评审到此冻结；除非实现发现契约无法表达 ranking 或 Validator 无法确定性校验，否则不再扩充总体架构，开发资源转入该垂直切片。

以本次 Trace 作为第一个端到端样板：

- [ ] Semantic Plan：年度、指标、维度、排序、Limit。
- [ ] Resolved Plan：将相对时间解析为绝对区间与 `as_of`，以 Operation DAG 表达 ranking、总额、占比及比较依赖，并明确 comparison cohort。
- [ ] Direct Metric：查询 `finance.customer_sales_ranking`。
- [ ] Typed Result：将查询结果包装为 `ranking`，明确 Metric Definition、Scope、Coverage、单位、实体和执行引用。
- [ ] Evidence State：保存 Result 引用、过滤条件、查询时间和覆盖状态。
- [ ] Calculation Engine：计算总销售额、Top 2 合计和 Top 2 占比。
- [ ] Fact Set：客户名、销售额、排名、总额和集中度。
- [ ] Coverage Gate：只有总体完整或有可信总体分母时，才允许计算整体集中度。
- [ ] Business Rule：通过 `customer_concentration.high@1.0.0` 将 Top 2 占比转换为 Judgement Claim。
- [ ] Answer Contract Template：实例化 Ranking Protocol，仅允许排行、数值、占比和受规则支持的集中度，不允许利润、回款和增长结论。
- [ ] Deterministic Renderer：输出一句结论；用户明确要表格时再渲染表格。
  - **v1 渲染形态覆盖（按 case 明确）**：① 排行句（Case 1/2/3：名次 + 客户 + 金额，确定性 Formatter 输出 `1235 万元`）；② 占比句（Case 4：`TopNTotal`/`ShareOfTotal` Fact + 百分比 Formatter）；③ 集中度判断句（Case 5：规则支持的 Judgement Claim）；④ 实体定位句（Case 6：“厦门海丝排名第 N”，由 ranking rows 内 `rank` 字段定位，不做模糊匹配）；⑤ 表格（Case 7：列由 Answer Contract `presentation` 限定，≤6 列、≤20 行）；⑥ 期间切换（Case 8：标题/范围随新 period 渲染，明确“去年”= 2025 绝对区间）；⑦ unsupported 说明（Case 9/11 越界部分：一句固定业务化文案，不进入正式 Claim）。所有数字只来自 Fact/Verified Assertion，格式化（万元/百分比/保留位）全部由确定性 Formatter 完成并可回放。
- [ ] Structural Validator：验证所有金额、排名、百分比、Scope、Coverage、Calculation、Rule 和 Contract。
- [ ] Semantic Validator：首期只保留接口和 Trace 状态 `not_applicable`，Deterministic Renderer 不产生开放式判断；不得作为 Ranking 上线阻塞项。
- [ ] Output Gate：验证完成前不发送包含业务 Claim 的 SSE；失败时按 `reason_code` 删除 Claim、重新取数/计算或返回证据不足。
  - **v1 流式决策**：Deterministic Renderer 采用“**先生成完整句子列表 → 全部通过 Output Gate → 一次性发送**”，不做流式中途裁决；现有 `chat()` 为同步 `agent.invoke`，该模式零额外成本，且与“Renderer 只消费 Verified Assertion”的约束天然一致。SSE 仅负责传输已通过验证的内容。若后续接入 Lightweight LLM 流式渲染（`period_comparison` 切片），再引入“逐句 gate：`unsupported` 句子不发送、`partial` 弱化措辞”的流式协议，不属于 Ranking v1 DoD。
- [ ] Sentence Binding：最终每个业务句子绑定一个或多个 Verified Assertion；实体集合、时间和数值均能从句子反查到对应 Operation。
- [ ] Trace：记录路由、投影 Token、结果引用、计算血缘、Contract 和验证结果。

该切片完成后，再复制到 `metric_snapshot`、`period_comparison`、`time_series`、`composition` 和 `data_table`。

> ✅ **已复制：`metric_snapshot`**（2026-08-17，见 `docs/metric-snapshot-slice.md`）。
> 单值销售额快照（"本月销售额多少" → Direct Metric + Deterministic Renderer）
> 已完成 9-case Replay、Fast Path 接入与 Shadow 示例；期间切换/排行消歧/
> Contract 越界门禁全绿。下一复制目标：`period_comparison`。

### 垂直切片查询集

以下查询必须作为同一组端到端测试，覆盖追问、约束继承和分析类型变换。每项标注 Ranking v1 的预期结果：

- `SUPPORTED`：v1 必须端到端跑通并断言。
- `UNSUPPORTED_V1`：v1 返回**明确失败语义**（`unsupported` + 业务化说明），Plan 不得进入 Metric Execute；能力随后续切片实现。
- `GATE`：架构门禁，任一失败禁止开启 ranking Fast Path 灰度。

| # | 查询 | v1 预期 | 说明 |
|---|------|---------|------|
| 1 | 客户销售额排行 | SUPPORTED | ranking 主链路样板 |
| 2 | 今年客户销售额前 3 名 | SUPPORTED | limit=3；“今年”解析为绝对区间与 `as_of` |
| 3 | 今年哪个客户销售额最高？ | SUPPORTED | limit=1 + `rank` predicate |
| 4 | 前两名客户占多少？ | SUPPORTED | `TopNTotal` + `ShareOfTotal` 派生 Fact |
| 5 | 客户集中度怎么样？ | SUPPORTED（GATE） | Coverage 完整时才允许规则判断，否则 `insufficient_evidence` |
| 6 | 厦门海丝排第几？ | SUPPORTED | 实体解析 + ranking 内 rank 定位 |
| 7 | 给我客户销售额表格 | SUPPORTED | Deterministic Renderer 表格形态 |
| 8 | 去年呢？ | SUPPORTED | 继承上下文，period 切换为去年绝对区间；是**期间切换**而非跨期比较 |
| 9 | 跟去年相比客户结构有什么变化？ | UNSUPPORTED_V1 | 需 `period_top_n` 两期对比，非首期 Predicate/Operation；见下方裁决 |
| 10 | Coverage 不足 | GATE | 返回 `insufficient_evidence`，不得硬算 |
| 11 | Contract 越界 | GATE | 排行照答，利润按 v1 规则拒绝；见下方裁决 |
| 12 | 跨轮 Evidence 污染 | GATE | 只继承有效约束与实体，不携带无关 Tool Result |

**Case 9（v1 裁决）**：`period_top_n` 需要 `period_comparison` Operation 和两期实体集合对比，不在 Ranking v1 的 Predicate/Operation 清单内。v1 对该查询返回 `unsupported`（reason_code `UNSUPPORTED_ANALYSIS_TYPE`）+ 一句业务化说明（如“当前只能查询单一期间的排行，暂不支持跨期结构对比”），**不得**偷换成今年固定 Top-N 客户的同比——那正是 v1 禁止的语义偷换。`fixed_cohort` 与 `period_top_n` 随 `period_comparison` 切片一并实现；实现前 Case 9 的 Replay fixture 断言“返回 unsupported 且 Plan 不进入 Metric Execute”。

**Case 11（v1 裁决）**：“利润最好”触发 Contract 越界。v1 行为：排行部分正常回答；利润部分由 Structural Claim Validator 以 `CONTRACT_VIOLATION` 拒绝，Answer Contract 之外不生成任何利润 Claim；利润指标未注册（不在首期 Metric Registry），Compiler 对越界部分返回 `unsupported` 并提示“可发起新的利润排行查询”，**不得**由 Response LLM 自行扩展，也不得静默吞掉用户请求。若后续注册利润指标，越界部分才改为触发新的 Semantic/Execution Plan（重新编译）；该能力不属于 Ranking v1 DoD。

在 Case 2 后追加复合追问“这三家和去年同期相比怎么样？”时：该追问属于跨期比较（`fixed_cohort`），v1 中与 Case 9 同路径返回 `unsupported`；若追问在单一期间内（如“这三家占总销售额多少？”），v1 支持 composition 依赖并物化 Case 2 的实体集合。`fixed_cohort` 与 `period_top_n` 的 Plan、Evidence、Assertion 和回答措辞必须可区分，是 `period_comparison` 切片的验收标准，不进入 Ranking v1 DoD。

测试断言至少包括：年度继承与变更、Limit 覆盖、实体定位、总体分母与 Coverage、派生计算、Judgement Rule、表格 Renderer、期间切换（Case 8）、unsupported 明确失败（Case 9）以及跨轮不携带无关 Tool Result。

其中 Case 5（Coverage 分支）、Case 10～12 是架构门禁而非普通回归测试：任一失败都表示 Coverage Gate、Answer Contract 或 Context Projection 尚未真正成立，禁止开启 ranking Fast Path 灰度。

### 复合多语义输入的 v1 行为汇总

复合多语义的通用协议定义在 `agent-runtime-contracts.md`（§3.6 Operation DAG 与跨轮聚合、§4.2 拆分粒度验证、§4.3 `partially_compiled` 授权）。Ranking v1 的落点如下，实施时以本表为准：

| 机制（contracts 定义） | Ranking v1 落点 | 验证用例 |
|---|---|---|
| Operation DAG 复合（§3.6） | 固定形状：`ranking → topn_total → share_of_total` 显式依赖引用；不支持任意多 Operation/通用图调度 | Case 4、Case 2 后单一期间追问 |
| 拆分粒度验证（§4.2） | 只校验“形状正确 + 依赖完整 + 核心信息点覆盖”（防拆漏生效；固定形状下防过度拆分不适用） | Case 4（占比 Operation 不得缺失） |
| `partially_compiled` 授权（§4.3） | 固定裁决替代策略平台：Case 11 排行部分执行、利润部分拒绝并披露，`reason_code=UNSUPPORTED_ANALYSIS_TYPE`；默认不执行未授权部分 | Case 11（GATE） |
| 跨轮复合聚合（§3.6 聚合协议） | 最小判定：`metric_id + scope` 相同 → 继承实体集合与 Evidence；不同 → 独立编译只继承实体 | Case 12（GATE） |
| 跨期复合（`period_top_n`/`fixed_cohort`） | v1 返回 `unsupported`（`UNSUPPORTED_ANALYSIS_TYPE`），随 `period_comparison` 切片实现 | Case 9、Case 2 后跨期追问 |

### 6.1 Fast Path 接入与前端展示形态（实施记录，2026-08-16）

以下为 DoD #9 落地与前端打磨后的**最终形态**，作为后续切片（`metric_snapshot` 等）复用的展示模板。技术内部标识符（assertion/fact/calculation id、`definition_version`、coverage 枚举、claim_strength）**只进服务端 Trace**（`agent_trace_service` 已记录 `result_ids/calculation_ids/versions`），不出现在前端任何位置。

**接入点**：
- `schedule_agent.chat()`（非流式）与 `iter_chat_sse`（SSE 流，前端实际路径）入口处尝试 `agent_fast_path.run_fast_path`，`executed` 直接短路返回；`observational` 附加决策继续现有路径；`rejected` 结构化失败回复。
- 执行复用现有 `finance_service.profit_report`（一次查询得行集 + 总体营收 `summary.revenue`），Result Store 持久化（`result_id` 可回放）。

**开关行为**（`AGENT_FAST_PATH_ENABLED`，默认 `false`）：
- `false` → 观测模式：`fast_path_observation` 随响应返回（前端灰色"观测"状态条），流量仍走现有 Agent 路径；前端提示"该问题可走确定性链路，当前为观测模式"。
- `true` → ranking 请求走确定性链路（绿色"确定性链路"状态条），完全绕过 LLM。
- 部署注意：开关由 uvicorn 进程启动时读取（`deploy.env` 经 `deploy.sh` source；本地经 `.env` 或环境变量），**修改后必须重启服务才生效**。

**展示形态（确定性链路）**：
1. 主回复 = 一句结论（扫读短答）："2026 年客户销售额排行：厦门海丝进出口居首（销售额 3,920 元）。前 2 名客户合计占总销售额 81.6%。客户集中度较高。"
2. 表格卡片始终显示（排名/客户/销售额，金额格式化）。
3. "完整业务分析"默认折叠 = **面向用户的中文依据说明**：
   - 查询范围：2026 年（未指定年份时默认当前年份）——默认年份假设必须明确披露，不反问（契约 §4.4 低风险默认 + 披露 assumption 策略）
   - 数据来源：客户销售额排行（前 2 名 2 户）
   - 计算方式：前 2 名客户合计 7,670 元 ÷ 总体销售额 9,398 元 = 81.6%
   - 判断依据：前 2 名客户占比 81.6%，达到阈值 0.80，判定「客户集中度较高」（业务规则 customer_concentration.high@1.0.0）
   - 查询时间
4. 状态条：观测（灰）/确定性（绿）+ 三个可信指标（未通过验证语句 0 / 证据充分率 100% / 数值绑定率 100%）。

**金额显示**：canonical 值保持数据库原始 Decimal 精度（如 `3920.0000`）；显示由确定性 Formatter 归一化——`format_money` 对"元"分支归整到最多 2 位小数并去尾零（`3920.0000 → "3,920 元"`、`3750.5000 → "3,750.5 元"`），"万元"分支取整。规则判断始终读 canonical，不受显示精度影响。

**Planner 增强（12-case 查询集所需）**：`plan_finance_question` 的 ranking 识别扩展到占比/集中度（"前两名客户占多少"）、表格（"给我客户销售额表格"）、中文数字 Top-N（"前三名"）；"集中度/占比"类问题无显式 N 时默认 `limit=2`（`customer_concentration.high` 规则的输入是 top2_share）——否则会出现"前 limit 名占 100% 恒命中规则"的错误（Shadow 对比发现并修复）。

**追加过滤（turn2 继承排行上下文 + 过滤条件，2026-08-16）**：识别"大于/超过/高于 X 元/万/亿"类过滤追问（支持万/亿单位换算），**仅当会话历史存在 Fast Path 排行轮次**（ui_messages `path=fast_path` 标记）时继承为排行过滤；年份从上一轮排行回复解析，无排行上下文不猜测（交给 LLM 路径）。

- **当前过滤实现（服务层内存过滤）**：执行层 `_execute_ranking` 先 `profit_report(year)` 聚合出**全部客户的年销售额**（与普通排行同一次查询，无额外查询），再按 `min_amount` 在内存过滤（作用于完整客户集合，不会"先取 Top-N 再筛"漏掉第 11 名以后也达标的客户），然后排序截断。`envelope.filters.min_amount` 进 Trace 可回放。
- **下推候选（未来，非 Ranking v1 范围）**：把过滤条件作为查询参数下推到 Metric 层（如 `finance.customer_sales_ranking` 增加 `min_amount` 参数，在 SQL/聚合层 `WHERE 客户年营收 > X GROUP BY 客户`），省去全量订单行传输。这符合"Metric 负责取数"的职责边界，建议在 `metric_snapshot` 切片或抽象复盘时评估，不在当前垂直切片实现。



## 七、现状 → 目标迁移映射（PR 落点时逐个核对）

以下清单约束“老代码怎么办”，避免每个 PR 现场临时决定。映射原则：**能复用的复用，能增强的增强，只在确有新契约需求时才新建模块**；不在本清单内的现有模块默认保持不变。

| 现有模块（app/services/） | 现状作用 | 迁移动作 | 对应计划项 |
|---|---|---|---|
| `schedule_agent.py` `SYSTEM_PROMPT` | 54 行角色+规则+格式堆叠 | **改造**：瘦身为“稳定前缀”（角色/事实原则/表达职责）；指标目录、格式、权限规则移出 | P3.1 |
| `schedule_agent.py` `_run_auto_diagnostic_bundle` + `preflight_context` | 正则选指标 + 全量 JSON 内联 | **改造**：选指标逻辑保留；输出改走 Result Store 投影（`result_id+schema+summary+preview`） | P0.1/P0.3 |
| `schedule_agent.py` `diagnosis_name`/`answer_focus` 二分模板 | 关键词模板渲染诊断文案 | **退役**：由 `render_runtime_instruction(semantic_plan, ...)` 替代 | P0.2 |
| `schedule_agent.py` `_build_agent` `mem_block` | 全量指标目录+30 条记忆内联 | **改造**：改为领域 Top-K 指标召回 + 按需记忆 | P0.1/P3.1/P3.3 |
| `schedule_agent.py` `chat()` `agent_messages` 构造 | 3 条消息直传 `agent.invoke` | **改造**：接入 ContextProjector，断言“输入 = 投影结果，不含 checkpoint 历史” | P0.1 |
| `schedule_agent.py` `_checkpointer()`/LangGraph State | 全量历史持久化 | **保留**：继续作为持久化与审计；与模型输入解耦（State ≠ Model Context） | P0.1/P3.2 |
| `schedule_agent.py` `apply_evidence_guardrail` | 出口正则数字检查 | **保留**：作为 egress 第二道门，与新 Validator 并存 | P0.3（契约文档验证协议） |
| `agent_policy.py` `get_policy_bundle` | 指标目录+策略 | **保留并复用**：Fast Path 权限检查与 Agent 路径共用同一策略源 | P2.1 |
| `analysis_plans.py` `SemanticPlan`/`parse_planner_json` | 约束式语义计划（`extra=forbid` 拒绝多余键） | **保留为解析层基础**：其拒绝策略并入 Resolver/Type Checker；产出升级为 `ResolvedSemanticPlan@1` | PR #1 |
| `analysis_plans.py` `ExecutionPlan` | 执行步骤列表 | **保留**：叠加 `operation_id` 依赖引用后作为 `ExecutionPlan@1` | PR #1 |
| `agent_orchestration.py` `ChildResult`/`sanitize_child_result` | 子 Agent 只返回 Typed Result+摘要，拦截内部字段 | **保留**：正是“SubAgent 轻量化”的既有实现，随 Fast Path 收敛调用频率 | P2.1 |
| `analysis_result_store.py` | Result Store 雏形（`result_id` 存储与读取） | **保留并增强**：增加按字段/分页/限量读取接口 | P0.3 |
| `workshop_metrics.py` `query_metric`/`list_metrics` | 函数式指标执行 | **保留执行函数**；新增 Metric Registry 显式版本登记（见契约文档 4.1） | PR #1 |
| `agent_trace_service.py` | 本地 trace 账本（JSON blob） | **保留**：新字段写入 `trace_json`，不新增表 | 回放文档可观测性 |
| `nlu.py`/`agent_trace_service.py` 之外的旧意图正则（`_FINANCE_DIAGNOSIS_RE` 等） | 关键词意图识别 | **改造/收敛**：ranking 路径改为 Router 确定性决策；正则保留为 Fast Path 未覆盖时的回退（记录 `reason_code=regex_fallback`） | P2.1 |
| `lifecycle_agents.py` PROFILES / `_build_tools` | 角色子 Agent 注册表 | **保留**：仅 Special 路径调用；Fast Path 不触发 | P2.1 |


## 八、明确不做

- 不为解决上下文问题整体替换现有 LangGraph/DeepAgents 技术栈。
- 不让 LLM 生成 SQL 或绕过 Metric Layer。
- 不因 Fast Path 放松权限、Evidence、Calculation 或 HITL。
- 不把 1M Context 当作继续堆叠历史和工具结果的理由。
- 不在本阶段继续增加采购、财务、生产等新角色；优先做硬中间链路。
- 不在 Ranking MVP 建设通用 Fact Ontology、表达式语言、规则平台、Operation DAG 调度平台或 NLI/LLM Grounding 服务。
- 不因最终架构包含 Recommendation、Hypothesis、Specialist Agent，就把它们纳入首个垂直切片 DoD。
