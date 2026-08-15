# 车间军师 Agent Runtime 改进计划

> 来源：基于 2026-08-15「客户销售额排行」Trace 的专家复盘。
>
> 目标：不继续横向增加 Agent，而是把 `Semantic → Evidence → Calculation → Claim` 链路做成可验证的运行时契约，同时降低上下文污染、Token 成本和无效编排。

## 一、专家结论摘要

### 1. 总体判断

当前系统已经不是普通 ChatBI，而是“受约束的业务决策 Agent”雏形，整体方向正确：

- LLM 不直接访问数据库，而是通过语义指标层、受限工具和计算引擎获取事实。
- 已具备 Semantic Plan、Metric Layer、Evidence Guardrail、HITL、长期记忆和版本化 Trace。
- 权限、不可编造、禁止不等价指标代答、自动诊断结果不得重复查询等治理规则较完整。
- LangSmith 已记录策略、指标目录、计算引擎、语义计划和执行计划版本，具备 Agent Runtime Engineering 基础。

初版专家综合评分约为 **7.8/10**；在补齐 Coverage、Claim 类型、Business Rule、两层 Validator 和确定性 Router 后，当前设计成熟度已提升至约 **9.5/10**，可以作为正式实施设计进入开发。现阶段不再继续横向扩充设计，重点是冻结核心运行时对象和版本，并用 `ranking` 垂直切片验证整条可信链。

### 2. Trace 暴露的核心问题

1. **Context 污染**：模型输入混入上一轮完整 Tool Call、Tool Result、SubAgent 总结和最终回答；本轮 7,061 个输入 Token 只产生 167 个输出 Token。
2. **状态边界不清**：`LangGraph State.messages` 基本等同于 Model Context，持久化历史与模型本轮所需上下文没有分离。
3. **结构化状态与自然语言指令漂移**：Semantic Plan 正确表示“客户销售额排行”，自动诊断文案却仍写“回款/应收或现金流”。
4. **Evidence 仍主要靠 Prompt 约束**：原始金额有 `result_id`，但“头部两户占 81.6%”仍由 LLM 自行计算，派生结论缺少公式和计算血缘。
5. **缺少 Answer Contract**：Semantic Plan 约束“查什么”，但没有独立契约约束最终“能说什么、必须说什么、禁止说什么”。
6. **SubAgent 使用偏重**：简单指标、排行、趋势等问题仍可能经历“主 Agent → 子 Agent → 主 Agent”的重复总结。
7. **Prompt 过胖**：身份、业务规则、指标目录、权限、HITL、格式、Memory 和诊断策略长期堆叠在同一个系统提示中。
8. **大结果反复内联**：Tool/SubAgent 完整输出进入后续上下文，Result Store 尚未完全承担“外部结果存储 + 按需读取”的职责。

### 3. 推荐的目标形态

```text
User
  ↓
Semantic Compiler
  ↓
Runtime State / Context Projection
  ↓
Capability Router
  ├─ Fast Path
  ├─ Deterministic Analysis
  ├─ Specialist Agent
  └─ Multi-Agent Workflow
  ↓
Evidence Store
  ↓
Calculation Engine
  ↓
Facts / Derived Facts
  ↓
Business Rules
  ↓
Typed Claims
  ↓
Answer Contract
  ↓
Response LLM
  ↓
Structural Validator
  ↓
Semantic Validator
  ↓
UI Renderer
```

外围能力应下沉到 Agent Harness：Session Projection、Prompt Assembly、Tool/Skill Registry、Permission/HITL、Compaction、Persistence、SubAgent 和 Telemetry。LLM 最终主要负责理解、表达和无法确定性编码的开放式推理。

## 二、设计原则

1. **Structured State 是唯一真相源（SSOT）**：所有自然语言运行时指令必须由 Semantic Plan、Evidence 和 Policy 动态渲染，禁止平行维护业务判断文案。
2. **Event Log 不等于 Model Context**：完整事件用于持久化和审计；模型只接收当前任务的 Context Projection。
3. **数字必须先成为 Fact**：原始值来自 Result Store，派生值来自 Calculation Engine；LLM 不承担业务数字计算。
4. **可验证 Claim 必须有完整依据链**：最终业务主张必须能够追溯至 `claim → fact → calculation/rule → evidence → scope/coverage`；建议类 Claim 也必须声明依据，但不伪装成事实。
5. **简单问题走确定性路径**：可由既有 Typed Result 和 Renderer 完成的问题，不进入 SubAgent。
6. **Prompt 只保留必要规则**：权限、格式、计算、证据校验和结果裁剪优先由代码保证。
7. **稳定前缀、动态后缀**：基础角色、核心政策和工具 Schema 尽量稳定；当前计划、证据和用户问题作为动态上下文，提升缓存命中率。
8. **职责边界固定**：LLM 负责理解和表达；Metric 负责取数；Calculation 负责算数；Rule 负责确定性判断；Agent 负责开放式分析；Validator 负责最后放行。

### 2.1 核心运行时契约冻结

开发前冻结以下对象为版本化 Runtime Contract，而不是仅依赖 Java/Python 类结构：

- `SemanticPlan@2`、`ExecutionPlan@1`、`ContextProjection@1`
- `EvidenceEnvelope@1`、`Fact@1`、`Calculation@1`
- `BusinessRule@1`、`AnswerContract@1`、`Claim@1`
- `ValidationResult@1`

所有 Trace 必须记录对象的 Schema Version。契约升级需要兼容读取或显式迁移策略，以保证老 Trace 可用于 Offline Replay 和 Shadow 对比。首期只要求版本化序列化、兼容读取与回放测试，不要求一次性建设完整 Event Sourcing、Snapshot、Projection Cache 和 Migration 平台。

### 2.2 Ranking-first 最小建模原则

第一版 Runtime Contract **只服务 `customer_sales_ranking` 垂直切片**。`EvidenceEnvelope`、`Fact`、`Calculation`、`BusinessRule`、`Claim`、`AnswerContract` 和 `ValidationResult` 只定义当前切片实际需要的字段与扩展点，不预先设计覆盖所有 BI 场景的通用中间表示（IR）。

抽象节奏固定为：

1. 先让 `customer_sales_ranking` 端到端运行并通过 Replay。
2. 接入 `metric_snapshot`，识别第一批真实公共字段。
3. 接入 `period_comparison`，再基于至少三个已实现用例提取稳定抽象。

新增字段必须由已落地用例或明确的 Validator/Replay 需求驱动。禁止为了假设中的未来分析类型提前引入万能节点、通用表达式语言或大而全 Schema，避免将 Runtime 改造演变为“万能 BI IR”项目。

## 三、目标状态模型

### 3.1 Conversation State

只保留对当前任务仍然有效的对话语义：

```json
{
  "current_turn": "客户销售额排行",
  "last_intent": "customer_sales_ranking",
  "confirmed_constraints": {"year": 2026},
  "active_entities": [],
  "unresolved_questions": []
}
```

### 3.2 Business State

保存跨轮有效、与租户业务相关的已确认状态，例如工厂、产能校准和业务偏好。不得包含一次性 Tool Result。

### 3.3 Evidence State

保存当前任务允许使用的事实引用和数据范围：

```json
{
  "result_id": "r_xxx",
  "metric": {
    "metric_id": "finance.customer_sales",
    "definition_version": "3.2.0"
  },
  "scope": {"year": 2026},
  "dimension": "customer",
  "operation": "ranking",
  "limit": 10,
  "coverage": {
    "type": "top_n",
    "requested": 10,
    "returned": 4,
    "population_complete": true,
    "population_size": 4,
    "denominator_available": true
  },
  "freshness": {"queried_at": "2026-08-15T17:46:36+08:00"},
  "authority": "metric_engine"
}
```

大明细保存在 Result Store；模型默认只看到 Schema、摘要、必要行和引用。

`coverage` 是 Evidence Envelope 的一级契约，而非展示元数据。它至少表达：完整集合、Top-N、抽样、部分时间窗口、截断或未知覆盖；同时记录请求量、返回量、总体是否完整、总体规模和关键分母是否可用。存在 `result_id` 不代表证据足够，Validator 必须继续检查 Scope、Coverage、Freshness 和 Authority。

`metric.definition_version` 是强制字段。相同 `metric_id` 在不同口径版本下不能视为同一业务事实；Replay、Calculation 和 Claim lineage 必须保留定义版本，完整链路为 `Claim → Fact → Calculation/Rule → Evidence → Metric Definition Version → Scope/Filters/Coverage → Result`。

### 3.4 Execution State

保存 `semantic_plan_id`、`execution_plan_id`、工具调用、耗时、Token、重试、审批和版本信息。该状态进入 Trace/Event Log，默认不重新注入模型。

## 四、分阶段实施计划

## P0：阻断上下文与语义污染

### P0.1 引入 Context Projector

- [ ] 新增显式 `ContextProjection` 数据结构，输入为 Conversation、Business、Evidence、Execution 四类状态。
- [ ] 每轮调用模型前只投影：当前问题、已确认约束、当前 Evidence、允许动作和必要业务记忆。
- [ ] 默认排除历史 Tool Call、Tool Result、SubAgent 原文和 Execution State。
- [ ] 仅当上一轮信息形成当前约束、未决问题或用户偏好时才进入 Projection。
- [ ] 为投影增加 Token/字符预算和可观测字段：原始消息数、投影消息数、裁剪原因、预计 Token。
- [ ] 每个进入 Context 的内容块记录 `content_ref`、`projection_reason`、`source_event_id` 和 `token_cost`，使“为什么纳入这段上下文”可审计。

**建议代码落点**：`app/services/schedule_agent.py` 中模型调用前的 `agent_messages` 构造；后续可拆到 `app/services/agent_context.py`。

**验收标准**：

- “本月经营情况”后追问“客户销售额排行”，模型上下文不再包含上一轮完整工具输出。
- 当前轮必要约束（如 2026 年）仍能正确继承。
- 简单排行问题输入 Token 相比基线下降至少 40%。
- Trace 同时保留完整事件与实际 Model Context，二者可独立检查。

### P0.2 消除自然语言模板漂移

- [ ] 删除按宽泛关键词手写的“用户问的是回款/应收或现金流”等运行时判断。
- [ ] 新增 `render_runtime_instruction(semantic_plan, execution_plan, evidence_state)`。
- [ ] 自动诊断标题、回答焦点、允许指标和时间范围全部由 Structured State 渲染。
- [ ] Structured State 与渲染文案不一致时，Match Gate 拒绝进入回答阶段并记录原因。

**建议代码落点**：替换 `app/services/schedule_agent.py` 中 `diagnosis_name`、`answer_focus` 的二分模板。

**验收标准**：

- `ranking/sales_amount/customer` 只能渲染为客户销售额排行语义。
- 排行、利润、回款、应收、趋势、明细六类黄金用例均无语义残留。
- 自动诊断文案不得引入 Semantic Plan 中不存在的指标或分析目标。

### P0.3 Result Spill 与历史 Tool Result 裁剪

- [ ] 定义 `max_inline_bytes` 和 `max_preview_rows`。
- [ ] 超限结果写入 Result Store，模型只接收 `result_id + schema + summary + preview + truncated`。
- [ ] 子 Agent 只返回 Typed Result、Fact 引用和协调事项，不返回完整作文式报告。
- [ ] 增加按字段、分页和限量读取 Result 的受控接口。

**验收标准**：

- 大结果不再完整出现在下一轮 Model Context。
- 明细可通过同一 `result_id` 按权限继续读取。
- 前端和 Trace 能区分“结果被裁剪”与“数据本身为空”。

## P1：把 Evidence、Calculation、Claim 做成硬链路

### P1.0 建立 Evidence Envelope 与 Coverage Gate

- [ ] 定义统一 `EvidenceEnvelope`：`result_id`、指标及版本、Scope、Coverage、Freshness、Authority、查询过滤条件和数据口径。
- [ ] 将 `metric_id + definition_version` 设为强制组合，禁止仅凭指标名或 ID 复用旧 Evidence。
- [ ] Coverage 类型至少支持：`complete_population`、`top_n`、`sample`、`partial_period`、`truncated`、`unknown`。
- [ ] 需要总体分母的计算必须显式声明 `denominator_available=true`，不得从 Top-N 行和误推总体。
- [ ] 增加 Coverage Gate：在 Fact Builder 和 Claim Validator 两处校验证据是否足够。
- [ ] Evidence 不足时返回结构化 `insufficient_evidence`，禁止静默生成判断。

**验收标准**：仅有 Top 10 行但没有客户总体销售额时，可以回答 Top 10 排名，但不能回答“整体客户集中度”。

### P1.1 建立 Fact Schema

- [ ] 定义 `Fact`：`fact_id`、类型、业务名称、canonical value、单位、时间范围、维度、来源和 Evidence 引用；展示精度与格式放入独立 `display` 字段。
- [ ] 原始指标行转换为 `metric_fact`。
- [ ] 派生数字必须通过 Calculation Engine 生成 `derived_fact`，保存公式、输入 Fact、舍入策略和 `calculation_id`。
- [ ] 禁止 Response LLM 输出未出现在 Fact 集中的金额、日期、数量、百分比和排名。

示例：

```json
{
  "fact_id": "f_top2_share",
  "type": "derived_metric",
  "name": "top2_share",
  "value": 0.8161310917,
  "unit": "ratio",
  "display": {"scale": 1, "format": "percent"},
  "calculation_id": "c_xxx",
  "inputs": ["f_customer_1", "f_customer_2", "f_total_sales"],
  "evidence": ["r_xxx"]
}
```

**验收标准**：

- “前两名占 81.6%”可完整回放公式、输入、精度和原始查询。
- 删除对应派生 Fact 后，Claim Validator 必须拦截该百分比。
- Business Rule 始终基于 canonical value 判断，Renderer 最后才按 `display` 舍入；例如原值 79.96% 不得因显示为 80.0% 而命中 `>= 80%` 的规则。

### P1.2 增加 Answer Contract

- [ ] 为每种 Analysis Type 定义版本化 Answer Contract Template；禁止每个问题由 LLM 自由生成 Contract。
- [ ] Contract 至少包含：`answer_type`、`required_facts`、`optional_facts`、`allowed_claims`、`forbidden_claims`、`presentation`。
- [ ] Semantic Plan 只负责用指标、维度、时间和过滤条件实例化模板，形成 Answer Contract Instance。
- [ ] 排行类允许排名和集中度；未提供相关 Fact 时禁止利润、回款、增长等扩展结论。

示例：

```json
{
  "answer_type": "ranking",
  "required_facts": ["customer", "sales_amount", "rank"],
  "optional_facts": ["top2_share"],
  "allowed_claims": ["ranking", "concentration"],
  "forbidden_claims": ["profit", "payment", "growth"]
}
```

**验收标准**：

- 最终答案遗漏必需事实时校验失败。
- 最终答案出现禁止 Claim 或无 Fact 数字时校验失败。
- Contract 与 Typed Presentation/UI Contract 保持一致。

### P1.3 Claim Binding 与 Claim Validator

- [ ] 建立正式 Claim 类型系统：`fact`、`derived`、`judgement`、`recommendation`。
- [ ] Response LLM 或确定性构建器输出结构化 Claim 草稿：`claim_id`、`type`、`claim_strength`、文本模板、`fact_refs`、可选 `calculation_ref`、`rule_ref` 和置信度。
- [ ] Renderer 将 Claim 与 Fact 渲染为最终中文，不让 LLM重复格式化数值。
- [ ] Fact Claim 必须直接绑定原始 Fact；Derived Claim 必须绑定派生 Fact 和 Calculation。
- [ ] Judgement Claim 必须绑定 Fact 和版本化 Business Rule；Recommendation Claim 必须绑定支持它的 Fact/Judgement，并明确它是建议而非事实。
- [ ] Structural Validator 确定性校验事实存在、计算输入、单位、实体、时间、Scope、Coverage、Authority、Contract 和 Claim Type。
- [ ] Semantic Validator 仅校验判断、因果、风险描述和建议是否获得合理支持，可采用规则或 LLM Judge，但不得推翻结构校验。
- [ ] Evidence 卡片能够按 Claim 反查证据，而不是只展示本轮所有工具结果。

`claim_strength` 至少支持：`deterministic`、`rule_supported`、`analytical`、`hypothesis`。其中确定性事实由 Structural Validator 校验；规则判断同时校验规则；分析性结论需要 Evidence + Semantic Validator；假设必须显式使用弱化措辞，禁止将相关性表达为因果性。

**验收标准**：每个可验证业务 Claim 都能回答“使用了哪些 Fact、经过什么 Calculation/Rule、最终来源于哪个 Evidence Result”；结构校验必须 100% deterministic。

### P1.4 Business Rule Registry

- [ ] 新增版本化 Business Rule Registry，保存规则 ID、适用指标/范围、输入 Fact、阈值、输出 Judgement、版本和负责人。
- [ ] “集中度较高”等判断不得由 LLM 临场推断，首个规则为 `customer_concentration.high`。
- [ ] 规则示例：当证据为完整总体且 `top2_share >= 0.80` 时，生成“客户集中度较高”的 Judgement Claim。
- [ ] 阈值变化必须产生新规则版本；Trace 和 Claim 均记录 `rule_ref`。
- [ ] 没有适用规则时，允许陈述数值事实，但不生成确定性业务判断。
- [ ] Rule Engine 仅承载 Threshold、Classification、Known Formula 和 Deterministic Business Policy；Attribution、Hypothesis、Root Cause、Trade-off 与开放式诊断必须进入 Specialist Agent，避免 Registry 演变为大规模 `if/else` 系统。

示例：

```json
{
  "claim_id": "c_concentration",
  "type": "judgement",
  "claim_strength": "rule_supported",
  "text": "客户集中度较高",
  "fact_refs": ["f_top2_share"],
  "rule_ref": "customer_concentration.high@1.0.0",
  "confidence": 1.0
}
```

## P2：建立 Fast Path 与能力路由

### P2.1 Capability Router

- [ ] 新增四级路由：Direct Metric、Deterministic Analysis、Specialist Agent、Multi-Agent Workflow。
- [ ] Router 默认由 Semantic Plan + 确定性 Policy 决策；只有未命中规则的边界情况才允许 Router LLM。
- [ ] 路由结果记录稳定 `reason_code`、`rule_id`、预计成本和实际成本；自然语言原因只用于 Trace UI。
- [ ] 以下类型默认 Fast Path：`metric_snapshot`、`ranking`、`time_series`、`data_table`、`composition`、`period_comparison`。
- [ ] `attribution_analysis`、复杂 `scenario/decision` 和多领域诊断才允许调用 Specialist/SubAgent。
- [ ] Router 决策写入 Trace，包括选择原因、预计成本和实际成本。
- [ ] 路由输出分离为正交字段 `execution_mode` 与 `response_mode`，禁止只记录含义模糊的 `FAST_PATH`。

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

## P3：Prompt 与 Harness 模块化

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

开发严格按以下依赖顺序推进；上一层未具备最小可测试契约时，不启用下一层线上流量：

```text
① Structured State SSOT
        ↓
② ContextProjection
        ↓
③ Result Spill
        ↓
④ EvidenceEnvelope + CoverageGate
        ↓
⑤ FactBuilder
        ↓
⑥ Calculation
        ↓
⑦ BusinessRule
        ↓
⑧ AnswerContract + Claim
        ↓
⑨ StructuralValidator
        ↓
⑩ ranking Fast Path
```

关键发布约束是：**Router 可以先产出观测性决策，但在可信链和 Structural Validator 完成前，不得把生产流量切换到 ranking Fast Path。** 先证明 Evidence、Fact、Calculation、Rule 与 Claim 的闭环成立，再改变执行路径。

与现有 Phase 的对应关系如下：

1. **Phase 0 — 一致性**：确立 Structured State SSOT，修复自动诊断文案与 Semantic Plan 不一致，并建立 Runtime Instruction Renderer。
2. **Phase 1 — Context**：增加 Context Projection，过滤历史 Tool/SubAgent 原文和无关领域 Prompt。
3. **Phase 1 — Result Interface**：增加 Result Spill，以 `result_id + schema + preview + coverage` 作为模型侧接口。
4. **Phase 2 — Evidence**：先为 `ranking` 建立 Evidence Envelope、Coverage Gate 和 Fact Builder。
5. **Phase 2 — Trusted Derivation**：加入 Calculation Engine 血缘和 Business Rule Registry，分别生成 Derived Fact 与 Judgement Claim。
6. **Phase 2 — Claim Protocol**：实例化 Answer Contract Template，构建 Claim Type，并上线 Structural/Semantic 两层 Validator。
7. **Phase 3 — Fast Path**：可信链完整后再启用 `ranking` 确定性路由，并复制到另外五类简单分析。
8. **Phase 4 — Harness**：以真实 Trace 数据做 Prompt Assembly、Skill 延迟加载和 Event Log + Projection 演进；迁移期间保留兼容读取。

### 5.2 建议 PR 拆分

每个 PR 只建立一个可独立审查和回放的边界：

1. **PR #1 — Runtime Contract + ContextProjection**：加入最小版本化契约、Structured State SSOT、Projection 及其可观测字段；不改变现有路由行为。
2. **PR #2 — EvidenceEnvelope + CoverageGate + FactBuilder**：完成 ranking Evidence 到原始 Fact 的转换，并覆盖 `insufficient_evidence`。
3. **PR #3 — Calculation + BusinessRule**：实现总额、Top 2 合计、Top 2 占比的确定性计算，以及集中度规则和完整血缘。
4. **PR #4 — AnswerContract + Claim + StructuralValidator**：约束 ranking 能说什么，阻止无依据数字、越界利润结论和不受支持的判断。
5. **PR #5 — Ranking Fast Path + Renderer**：在可信链已通过后启用确定性路由与渲染；保留开关和旧链路回退。
6. **PR #6 — 12-case Replay + Shadow Metrics**：运行正常与故意失败用例，接入 Claim Precision、Evidence Sufficiency、Unsupported Claim Escape、Token 和延迟指标。

每个 PR 必须包含对应单元测试、契约序列化测试和必要 Trace 字段；不得用后续 PR 才会提供的安全校验作为当前 PR 上线前提。

## 六、首个垂直切片：客户销售额排行

本节是当前唯一实施范围。设计评审到此冻结；除非实现发现契约无法表达 ranking 或 Validator 无法确定性校验，否则不再扩充总体架构，开发资源转入该垂直切片。

以本次 Trace 作为第一个端到端样板：

- [ ] Semantic Plan：年度、指标、维度、排序、Limit。
- [ ] Direct Metric：查询 `finance.customer_sales_ranking`。
- [ ] Evidence State：保存 Result 引用、过滤条件、查询时间和覆盖状态。
- [ ] Calculation Engine：计算总销售额、Top 2 合计和 Top 2 占比。
- [ ] Fact Set：客户名、销售额、排名、总额和集中度。
- [ ] Coverage Gate：只有总体完整或有可信总体分母时，才允许计算整体集中度。
- [ ] Business Rule：通过 `customer_concentration.high@1.0.0` 将 Top 2 占比转换为 Judgement Claim。
- [ ] Answer Contract Template：实例化 Ranking Protocol，仅允许排行、数值、占比和受规则支持的集中度，不允许利润、回款和增长结论。
- [ ] Deterministic Renderer：输出一句结论；用户明确要表格时再渲染表格。
- [ ] Structural Validator：验证所有金额、排名、百分比、Scope、Coverage、Calculation、Rule 和 Contract。
- [ ] Semantic Validator：验证判断和建议措辞没有超出规则与事实支持范围。
- [ ] Trace：记录路由、投影 Token、结果引用、计算血缘、Contract 和验证结果。

该切片完成后，再复制到 `metric_snapshot`、`period_comparison`、`time_series`、`composition` 和 `data_table`。

### 垂直切片查询集

以下查询必须作为同一组端到端测试，覆盖追问、约束继承和分析类型变换：

1. 客户销售额排行
2. 今年客户销售额前 3 名
3. 今年哪个客户销售额最高？
4. 前两名客户占多少？
5. 客户集中度怎么样？
6. 厦门海丝排第几？
7. 给我客户销售额表格
8. 去年呢？
9. 跟去年相比客户结构有什么变化？
10. **Coverage 不足**：询问“客户整体集中度怎么样”，故意只返回 Top 3 且无总体分母；必须返回 `insufficient_evidence`，不得硬算。
11. **Contract 越界**：询问“客户销售额排行，顺便告诉我哪个客户利润最好”，但 Evidence 只有销售排行；排行可回答，利润必须触发新的 Semantic/Execution Plan，不得由 Response LLM 扩展。
12. **跨轮 Evidence 污染**：依次询问“本月回款怎么样？”→“客户销售额排行”→“前两名占多少？”→“他们回款怎么样？”；第二轮不得携带第一轮无关 Evidence，第三轮继承排行上下文，第四轮只继承实体并因 metric 改变重新获取回款 Evidence。

测试断言至少包括：年度继承与变更、Limit 覆盖、实体定位、总体分母与 Coverage、派生计算、Judgement Rule、表格 Renderer、Period Comparison 路由以及跨轮不携带无关 Tool Result。

其中 Case 10～12 是架构门禁而非普通回归测试：任一失败都表示 Coverage Gate、Answer Contract 或 Context Projection 尚未真正成立，禁止开启 ranking Fast Path 灰度。

## 七、评估指标与发布门槛

### 正确性

- 数值 Claim 绑定率：100%。
- **Claim Precision**：受支持的可验证 Claim / 全部可验证 Claim，目标 100%。
- **Evidence Sufficiency Rate**：Coverage、Scope、Freshness 足以支持的 Claim / 全部 Claim，目标 100%。
- **Unsupported Claim Escape Rate**：Validator 本应拦截但实际成功返回的 Claim / 全部 Claim，线上目标为 0；作为 Shadow、灰度和正式发布的运行时安全红线。
- Structured State 与自然语言运行时指令一致率：100%。
- Semantic/Execution Match 通过率不得因改造下降。
- 无权限、不完整覆盖、跨口径对比继续保持显式失败或降级。

### 效率

- 简单分析输入 Token 中位数下降至少 40%。
- 简单分析 SubAgent 调用率降至 5% 以下。
- 简单分析 P95 延迟下降至少 30%。
- 大 Tool Result 再次内联率降至 0。
- **Context Relevance Ratio**：相关运行时段 Token / 总输入 Token 持续提升；不能仅靠粗暴截断实现降本。

### 可观测性

每轮至少记录：

- Context Projection 前后消息数和 Token。
- Capability Router 路径与选择原因。
- `semantic_plan_id`、`execution_plan_id`、`result_id`、`calculation_id`。
- Evidence Coverage/Freshness/Authority、Fact 数、Calculation 和 Rule 引用、各类型 Claim 数。
- Structural Validator 与 Semantic Validator 分层结果。
- Router `reason_code`、`rule_id`、执行路径和回答路径。
- 每个 Context Block 的 `projection_reason`、来源事件与 Token 成本。
- 每个 Runtime Contract 的 Schema Version，以及 Metric Definition Version。
- Prompt/Policy/Registry/Renderer/Projector 版本。

### 发布策略

1. Offline Replay：用现有 LangSmith Trace 重放，不影响线上回答。
2. Shadow：新旧链路并行，比较 Plan、Fact、Claim、Token 和延迟。
3. 灰度：先开放 `ranking` 和 `metric_snapshot` Fast Path。
4. 扩展：验证稳定后逐类迁移其他确定性分析。
5. 回滚：任何新契约失败时回退旧回答链路，但保留失败 Trace。

## 八、明确不做

- 不为解决上下文问题整体替换现有 LangGraph/DeepAgents 技术栈。
- 不让 LLM 生成 SQL 或绕过 Metric Layer。
- 不因 Fast Path 放松权限、Evidence、Calculation 或 HITL。
- 不把 1M Context 当作继续堆叠历史和工具结果的理由。
- 不在本阶段继续增加采购、财务、生产等新角色；优先做硬中间链路。

## 九、完成定义

当以下条件同时满足时，本轮 Runtime 改进视为完成：

1. Model Context 与完整会话/执行历史已经结构分离。
2. 所有运行时自然语言指令均由 Structured State 渲染。
3. 六类简单分析默认走 Fast Path，不调用 SubAgent。
4. 所有业务数字和派生比例均来自 Fact/Calculation，不由 LLM 计算。
5. Fact、Derived、Judgement、Recommendation 四类 Claim 均受 Answer Contract 约束；所有可验证 Claim 可追溯到 Fact、Calculation/Rule 和具备充分 Coverage 的 Evidence。
6. Prompt 不再承载完整指标目录、格式执行、权限判断和结果校验。
7. 正确性不下降，同时达到 Token、延迟和 SubAgent 调用率目标。
8. `ranking` 垂直切片 Trace 能按顺序展示 `SemanticPlan → Route → EvidenceEnvelope → Facts → Calculation → BusinessRule → Claims → AnswerContract → StructuralValidation → RenderedAnswer`，并通过 12 个查询与故意失败用例。

### 首期开发里程碑 DoD

在继续复制到其他五类简单分析之前，`customer_sales_ranking` 必须先满足：

1. 使用 ranking 所需的最小 Schema 完成端到端序列化与 Trace，不依赖尚未落地的通用 BI IR。
2. Context 与历史执行信息分离，跨轮仅继承仍有效的实体和约束。
3. 所有原始及派生数字分别来自 FactBuilder 和 Calculation，确定性判断来自 BusinessRule。
4. Answer Contract 与 Structural Validator 能拦截 Coverage 不足、无利润 Evidence 的越界回答和跨轮 Evidence 污染。
5. 12-case Replay 全部通过，`Unsupported Claim Escape Rate = 0`。
6. Fast Path 通过功能开关灰度，失败时可回退旧链路且完整保留失败 Trace。
