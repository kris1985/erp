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

> **评分口径说明**：9.5/10 是**设计成熟度**评分（诊断准确、契约与门禁完备），**不代表实现就绪度**。对照当前代码（`app/services/schedule_agent.py` 等），8 个核心契约对象均为 0 实现，Evidence/Fact/Calculation/Assertion/Validator 链路是全新工程。实现规模：约 7 个 PR、每条含单元测试与契约序列化测试；**各 PR 人日估算与里程碑需在 PR #1 立项时补充**，本总纲不承诺工期。现有代码的保留/改造/退役清单见 [Customer Sales Ranking Slice](customer-sales-ranking-slice.md) 第七章。

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
9. **Claim 按分析原子建模，不按用户问法建模**：用户问题不可枚举，但 `metric_snapshot`、`ranking`、`composition`、`period_comparison` 等分析原子有限；主链路 Claim 必须由 Semantic Plan 与 Typed Result 机械派生，不以“回答后再让 LLM 抽取 Claim”为默认方案。
10. **生成与验证相互独立**：Calculation Engine 负责产出派生值，Calculation Validator 必须根据公式、输入和精度策略独立重算；不能用同一段计算结果自证正确。
11. **先验证 Assertion，再生成答案**：Renderer 的输入只能是 `verified` Assertion，而不是裸 SQL、未校验 Fact 或候选 Claim；Post-render Grounding 是防止语言越界的第二道门，不能替代前置验证。

### 2.1 核心运行时契约冻结

最终链路涉及以下版本化 Runtime Contract，而不是仅依赖 Java/Python 类结构：

- `SemanticPlan@2`、`ExecutionPlan@1`、`ContextProjection@1`
- `TypedAnalysisResult@1`、`EvidenceEnvelope@1`、`Fact@1`、`Calculation@1`
- `BusinessRule@1`、`AnswerContract@1`、`Claim@1`
- `ValidationResult@1`

所有 Trace 必须记录对象的 Schema Version。契约升级需要兼容读取或显式迁移策略，以保证老 Trace 可用于 Offline Replay 和 Shadow 对比。首期只要求版本化序列化、兼容读取与回放测试，不要求一次性建设完整 Event Sourcing、Snapshot、Projection Cache 和 Migration 平台。

为避免“冻结总体架构”被误解为“首个 PR 一次实现全部对象”，`customer_sales_ranking` 首期只冻结并编码以下 8 个核心载荷：

1. `ResolvedSemanticPlan@1`
2. `TypedAnalysisResult@1`
3. `EvidenceEnvelope@1`
4. `Fact@1`
5. `Calculation@1`
6. `Assertion@1`（代码命名可以沿用 `Claim`，但 Trace 语义必须一致）
7. `AnswerContract@1`
8. `ValidationResult@1`

`ContextProjection`、`ExecutionPlan`、`BusinessRule` 等仍保留版本和 Trace 引用，但首期不建设通用平台：集中度只实现一个具体版本化规则，Execution 只表达 ranking 实际依赖，Projection 只满足 Case 12。字段冻结仅表示 Ranking v1 可以序列化、回放和兼容读取，不表示 Schema 已覆盖未来所有分析类型。

### 2.2 Ranking-first 最小建模原则

第一版 Runtime Contract **只服务 `customer_sales_ranking` 垂直切片**。`EvidenceEnvelope`、`Fact`、`Calculation`、`BusinessRule`、`Claim`、`AnswerContract` 和 `ValidationResult` 只定义当前切片实际需要的字段与扩展点，不预先设计覆盖所有 BI 场景的通用中间表示（IR）。

抽象节奏固定为：

1. 先让 `customer_sales_ranking` 端到端运行并通过 Replay。
2. 接入 `metric_snapshot`，识别第一批真实公共字段。
3. 接入 `period_comparison`，再基于至少三个已实现用例提取稳定抽象。

新增字段必须由已落地用例或明确的 Validator/Replay 需求驱动。禁止为了假设中的未来分析类型提前引入万能节点、通用表达式语言或大而全 Schema，避免将 Runtime 改造演变为“万能 BI IR”项目。

### 2.3 Apache Ossie 兼容方向与后续适配器

当前 Runtime **不将 Apache Ossie 作为执行引擎、Semantic Runtime 或核心运行时依赖**。内部 Semantic Registry 仍是运行时语义定义的唯一真相源，`ResolvedSemanticPlan`、Evidence、Fact、Calculation、Business Rule、Assertion、Answer Contract 和 Validator 继续使用本项目冻结的版本化契约。

Apache Ossie 定位为未来跨工具交换 Dataset、Field、Metric、Relationship 和 AI Context 的标准化边界：

```text
Apache Ossie Model
  ↓ import/export adapter（后续实现）
Internal Semantic Registry
  ↓ Resolver / Type Checker / Plan Validator
ResolvedSemanticPlan
  ↓
Evidence → Fact → Calculation → Assertion → Validation
```

兼容决策如下：

1. 内部 Registry 的稳定 ID、定义版本、指标、字段、数据集、关系和 AI Context 在不增加 Ranking v1 复杂度的前提下，应尽量保持可映射到 Ossie；不得为了追随外部规范提前扩充通用 IR。**Ranking v1 不为“可映射性”做任何额外字段或设计**——该条仅在 `ranking`/`metric_snapshot`/`period_comparison` 三个切片完成后的抽象复盘中评估，任何 Ossie 对齐需求必须由真实交换场景驱动。
2. Ossie Schema Version 与内部 Registry Version 独立管理。导入时必须记录源模型、源版本、转换器版本、映射结果和无法无损转换的字段。
3. 通过 Ossie Schema 校验只表示交换格式合法，不表示指标可执行或业务语义正确。所有导入定义仍必须经过内部 Resolver、Type Checker、Policy 和 Plan Validator，禁止直接进入 Evidence 链路。
4. Ossie Metric 可以映射为内部 Metric Definition，但不能直接等同于内部 `metric_id + definition_version`；内部的单位、粒度、时间语义、聚合方式、可加维度和执行能力仍以 Registry 校验结果为准。
5. Evidence、Fact、Calculation、Business Rule、Assertion、Answer Contract 和 ValidationResult 属于 Agent Runtime 信任链，不纳入 Ossie 核心模型，也不通过 `custom_extensions` 将其伪装为通用语义定义。
6. Ranking v1 不实施 Ossie 集成。完成 `customer_sales_ranking`、`metric_snapshot` 和 `period_comparison` 三个切片并通过抽象复盘后，如出现外部 BI、数据平台或 Agent 的语义交换需求，再实施单向 `Ossie → Internal Registry` Adapter Spike；只有存在明确回写需求时才评估双向转换。

该决策的目标是保留未来与开放语义生态互操作的能力，同时不让尚未成熟的外部交换规范改变当前 Ranking-first 的实施范围、运行时信任边界或上线门禁。


## 三、文档导航

当前设计已经冻结，详细内容按用途拆分：

- [Runtime Contract](agent-runtime-contracts.md)：状态模型、Typed Result、Evidence、Fact、Calculation、Assertion、Answer Contract 与 Validator。
- [Customer Sales Ranking Slice](customer-sales-ranking-slice.md)：当前唯一开发范围、MVP 边界、实施顺序、PR 拆分和明确不做项。
- [Replay and Release](agent-runtime-replay-and-release.md)：12-case Replay、指标、Shadow、灰度、回滚和完成定义。

发生定义冲突时，以 Runtime Contract 为数据结构依据，以 Ranking Slice 为首期开发范围依据，以 Replay and Release 为上线门禁依据。
