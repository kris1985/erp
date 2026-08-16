# Agent Runtime Contract

> 本文是运行时对象、证据链和验证协议的唯一详细定义。

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

### 3.5 Typed Analysis Result 与 Assertion IR

工具不得只返回无语义的行数组。Metric/SQL/Python 的输出必须先包装为 `TypedAnalysisResult`，至少包含：`result_type`、指标及定义版本、维度、时间、过滤条件、Scope、Coverage、单位、行或标量值，以及执行引用。Claim Builder 只消费 Typed Result，不重新解释 SQL 文本或用户原话。

```json
{
  "result_type": "ranking",
  "metric": {"metric_id": "finance.customer_sales", "definition_version": "3.2.0"},
  "dimension": "customer",
  "scope": {"year": 2026},
  "coverage": {"type": "complete_population", "population_complete": true},
  "rows": [
    {"entity_id": "customer:A", "entity_label": "客户 A", "value": 12350000, "unit": "CNY", "rank": 1}
  ],
  "execution_ref": "metric_exec_9328"
}
```

`Claim` 的内部表达采用轻量 Assertion IR，而不是为每种自然语言问法建立一套 Schema：

```json
{
  "claim_id": "c_rank_a",
  "subject": {
    "metric_id": "finance.customer_sales",
    "metric_definition_version": "3.2.0",
    "dimensions": {"customer": "customer:A"},
    "scope": {"year": 2026}
  },
  "predicate": "rank",
  "object": {"rank": 1, "value_fact_ref": "f_customer_a_sales"},
  "claim_strength": "deterministic",
  "evidence_refs": ["r_xxx"]
}
```

首期只实现 ranking 所需谓词，如 `value`、`rank`、`share_of_total` 和 `classification`。后续由已落地的分析类型逐步增加 `period_change`、`trend`、`exception`、`contribution` 等谓词，不提前建设通用表达式语言。

三类对象的边界必须固定：

- `TypedAnalysisResult` 是“执行得到了什么”的数据证据，尚不等于允许对用户陈述的结论。
- `Assertion` 是由 Operation、Typed Result、Fact 和 Calculation 自动构造的候选事实。
- `VerifiedAssertion` 是通过 Plan/Metric/Calculation/Structural Validation 后，允许 Renderer 消费的事实。

Renderer 不得直接读取 SQL、Python 输出或状态中的全部 Evidence。这样即使 Renderer 使用 LLM，它也没有机会从未验证数据中自行选择数字或推导结论。

`TypedAnalysisResult` 与 `EvidenceEnvelope` 允许在代码实现中采用 `EvidenceEnvelope<RankingResult>` 或共享不可变 `EvidenceMeta`，避免分别维护 metric、scope、coverage、unit 两份可漂移字段。无论最终采用组合还是引用，必须满足以下不变量：

- 相同语义字段只有一个权威存储位置，另一对象只能通过引用读取。
- 构造时即校验 `result_id`、metric definition、scope 和 coverage 一致，构造后不可变。
- 序列化 Trace 能同时还原“执行数据”和“证据元数据”，但不得因 DTO 展开而形成两个可独立修改的副本。

该结构选择作为 PR #1 的实现 Spike，由序列化测试和篡改测试决定，不继续在设计阶段扩展抽象。

### 3.6 Resolved Semantic Plan 与 Operation DAG

Semantic Interpreter 的输出仍是业务意图；Resolver 必须将模糊表达确定化为可执行、可验证的 Resolved Semantic Plan。至少解析：

- `metric_id + definition_version + aggregation`
- `dimension_id` 与稳定实体 ID
- `time_field`、时区、`as_of`、当前/对比区间及区间开闭规则
- 过滤条件、排序、Limit、单位与币种
- 有稳定 `operation_id` 的分析原子及其依赖关系
- 比较使用的实体集合与集合选择时点

复合问题应表示为 Operation DAG，而不是把多个动作藏在一段 Prompt 中：

```json
{
  "as_of": "2026-08-16T23:59:59+08:00",
  "operations": [
    {"operation_id": "op_rank_current", "type": "ranking", "top_n": 3},
    {"operation_id": "op_total_current", "type": "metric_snapshot"},
    {
      "operation_id": "op_share_current",
      "type": "composition",
      "numerator_ref": "op_rank_current.sum",
      "denominator_ref": "op_total_current.value"
    },
    {
      "operation_id": "op_compare",
      "type": "period_comparison",
      "current_ref": "op_rank_current.sum",
      "previous_scope": {
        "mode": "fixed_cohort",
        "entity_set_ref": "op_rank_current.entities"
      }
    }
  ]
}
```

“今年前三客户和去年同期相比”存在至少两种不同语义：

- `fixed_cohort`：取今年 Top 3 的同一组客户，比较其去年同期表现，回答客户组合自身的同比。
- `period_top_n`：分别取今年 Top 3 与去年 Top 3，比较两个动态集合，回答头部结构变化。

Resolver 必须根据问题明确选择 `comparison_scope.mode`；无法可靠消歧时进入 `unresolved_questions`，不得默认执行后再用自然语言掩盖差异。所有下游 Result、Fact、Calculation 和 Assertion 必须保留 `operation_id`、依赖引用和最终物化的实体 ID 集合。

#### 跨轮复合意图聚合协议

复合不限于单轮提问，追问也是复合的来源。协议定义“本轮与上轮是否合并进同一 DAG”：

- **聚合判定**：Resolver 对比本轮 Unresolved AST 与上轮 Resolved Plan 的 `metric_id`、`dimension`、`scope`、`period`、`entity`。完全同主题（同指标/同维度/同 scope，仅新增 Operation 或对已物化实体集合再计算）→ **合并进同一 DAG**，新 Operation 通过 `entity_set_ref` 引用上轮已物化实体集合；任一实质变化（指标/期间/维度变更）→ **独立编译新 DAG**，旧 DAG 只贡献可继承的约束与实体，不贡献数据。
- **禁止隐式聚合**：本轮未表达与上轮关联时，不得默认复用上轮 Evidence。聚合必须显式记录 `aggregation_reason`（如 `same_metric_entity_ref`、`constraint_only`），进入 Trace。
- **行为基准（Case 12）**：第二轮“客户销售额排行”相对第一轮“本月回款”主题不同 → 独立编译、不携带第一轮 Evidence；第三轮“前两名占多少”与第二轮同主题 → 合并/继承排行 DAG 的实体集合与 Evidence；第四轮“他们回款怎么样”指标变更 → 独立编译，只继承实体。每一轮都满足“只继承仍有效约束与实体，不继承数据”。
- **v1 范围**：v1 只实现两分支最小判定（基于 `metric_id` + `scope` 相等性：同则继承实体集合，异则独立编译），不做通用跨轮规划；跨轮 DAG 合并的完整能力随 `period_comparison` 切片增强。


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
- [ ] Calculation Validator 使用独立实现或声明式公式注册表重新计算，并校验除零、空值、单位转换、精度和容差；禁止仅比较 Calculation Engine 自己回传的结果。
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
- 篡改 Calculation 输出、公式、任一输入或舍入策略时，独立重算必须失败并给出稳定 `reason_code`。

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
- [ ] 主链路由 `SemanticPlan + AnswerContract + TypedAnalysisResult` 选择有限的 Claim Builder，并机械生成结构化 Claim：`claim_id`、`type/predicate`、`claim_strength`、`subject`、`object`、`fact_refs`、可选 `calculation_ref`、`rule_ref` 和置信度。
- [ ] 一个复合问题可以组合多个分析原子和 Claim Builder，例如“前三名是谁、占比多少、同比如何”组合 `ranking + composition + period_comparison`，禁止为组合问法新增专用 Case Schema。
- [ ] Renderer 将 Claim 与 Fact 渲染为最终中文，不让 LLM重复格式化数值。
- [ ] Renderer 只接收 `VerifiedAssertion[] + AnswerContract + 用户问题`；默认看不到候选 Assertion、裸 Evidence、SQL、Python Result 和未通过的 Fact。
- [ ] Fact Claim 必须直接绑定原始 Fact；Derived Claim 必须绑定派生 Fact 和 Calculation。
- [ ] Judgement Claim 必须绑定 Fact 和版本化 Business Rule；Recommendation Claim 必须绑定支持它的 Fact/Judgement，并明确它是建议而非事实。
- [ ] Structural Validator 确定性校验事实存在、计算输入、单位、实体、时间、Scope、Coverage、Authority、Contract 和 Claim Type。
- [ ] Semantic Validator 仅校验判断、因果、风险描述和建议是否获得合理支持，可采用规则或 LLM Judge，但不得推翻结构校验。
- [ ] Lightweight/Specialist LLM 若在渲染阶段增加了 Assertion IR 中不存在的解释性句子，必须经过 Post-render Claim Extractor 拆分，再由 Semantic Validator 标记 `supported`、`partial` 或 `unsupported`；该机制只处理自由解释，不承担主链路数字 Claim 的生成。
- [ ] `unsupported` 句子不得随 SSE 提前发送；应删除、重写为证据边界说明，或将整答降级为结构化失败。`partial` 必须弱化措辞并明确现有证据不能证明的部分。
- [ ] Renderer 输出句子级绑定：每个业务句子必须声明 `assertion_refs`；纯连接或格式文本可为空，但不得携带新的指标、实体、时间、数值、判断或因果语义。
- [ ] 单位换算与显示舍入由确定性 Formatter 完成，或作为可验证的 display transform 返回；例如 `12350000 CNY → 1235 万元` 必须可回放，不能被视为 LLM 的自由改写。
- [ ] Evidence 卡片能够按 Claim 反查证据，而不是只展示本轮所有工具结果。

`claim_strength` 至少支持：`deterministic`、`rule_supported`、`analytical`、`hypothesis`。其中确定性事实由 Structural Validator 校验；规则判断同时校验规则；分析性结论需要 Evidence + Semantic Validator；假设必须显式使用弱化措辞，禁止将相关性表达为因果性。

**验收标准**：每个可验证业务 Claim 都能回答“使用了哪些 Fact、经过什么 Calculation/Rule、最终来源于哪个 Evidence Result”；结构校验必须 100% deterministic。

Renderer 输出协议示例：

```json
{
  "sentences": [
    {"text": "截至 8 月 16 日，销售额前三客户为 A、B、C。", "assertion_refs": ["a_rank"]},
    {"text": "三家合计占总销售额 40.0%。", "assertion_refs": ["a_share"]},
    {"text": "同一组三家客户较去年同期下降 9.1%。", "assertion_refs": ["a_fixed_cohort_yoy"]}
  ]
}
```

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

### P1.5 分层验证协议与失败语义

Validator 不提供单一 `hallucination_score`，而是返回可定位、可采取动作的分层结果：

1. `PlanValidator`：校验用户约束是否完整进入 Resolved Semantic Plan，以及 Plan 与指标、时间语义、维度、过滤条件是否兼容。
2. `MetricValidator`：校验 Claim/Fact 与 Evidence 的指标定义版本、Scope、维度、过滤、时间、单位和值。
3. `CalculationValidator`：独立重算公式，校验输入血缘、数值、精度、容差和异常分支。
4. `StructuralClaimValidator`：校验 Claim Predicate、Fact/Rule 引用、Coverage、Authority 与 Answer Contract。
5. `SemanticGroundingValidator`：只处理不能确定性验证的归因、因果、风险和建议语言。

其中 `PlanValidator` 还必须检查 Operation DAG 引用存在且无环、依赖输出类型兼容、比较区间对齐、`as_of` 一致，以及 comparison cohort 已明确并成功物化。`StructuralClaimValidator` 必须检查 Assertion 的实体集合与对应 Typed Result 完全一致，防止“今年 Top3 的同比”被错误替换为“去年 Top3 的同比”。

```json
{
  "status": "rejected",
  "stage": "metric_validation",
  "reason_code": "TIME_SCOPE_MISMATCH",
  "claim_id": "c_sales_2026",
  "expected": {"year": 2026},
  "actual": {"year": 2025},
  "evidence_refs": ["r_xxx"],
  "action": "replan"
}
```

顶层状态至少支持 `verified`、`partially_verified`、`insufficient_evidence`、`rejected`；每个失败必须包含 `stage`、稳定 `reason_code`、受影响的 Claim、证据引用和建议动作（如 `replan`、`refetch`、`recalculate`、`remove_claim`、`human_review`）。禁止把所有失败折叠成无法调试的置信分数。

**最终出口兜底（egress backstop）**：分层 Validator 是前置验证，现有 `apply_evidence_guardrail`（`schedule_agent.py` 出口确定性检查）作为**最后一道门**保留：无论前置链路如何，最终文本中的数字/金额/日期仍须能在工具证据中找到，找不到即整体替换为安全重试文案。前置 Validator 与出口 Guardrail 验收独立，任一失败不得被另一方掩盖。该双保险同时覆盖 Fast Path 与 Agent 路径。

**验收标准**：同一故障在 Replay 中产生稳定阶段和原因码；前端可精确展示“哪个 Claim 的哪个口径/计算/依据失败”，而不是只显示“回答可信度低”。

## 四、Semantic Compiler 工程契约

Semantic Compiler 不是 JSON Extractor，而是可验证、可拒绝、可回放的编译流水线。LLM 只负责提出未解析语义 AST，不能直接产出可执行计划：

```text
User Query
  → Semantic Parser（LLM，生成 Unresolved AST）
  → Registry Resolver（绑定 Metric/Dimension/Entity/Time）
  → Operation Planner（生成强类型依赖）
  → Semantic Type Checker
  → Capability / Policy Checker
  → Ambiguity & Clarification Gate
  → Independent Plan Validator
  → Executable ResolvedSemanticPlan
```

### 4.1 Registry 与符号解析

至少维护 Metric、Dimension、Operation、Formula 四类 Registry。Resolved Symbol 必须包含稳定 ID、定义版本、单位、聚合方式、时间语义、粒度与可加维度。Resolver 必须保存候选项、匹配方式、Registry 版本和选择依据；不得只保留最终字符串。

Formula Registry 只登记有明确业务含义的跨指标公式。没有登记的计算不能因为单位相同就自动放行。

**`metric.definition_version` 的来源（v1 登记方案）**：现有 `workshop_metrics.query_metric` 是函数式执行 API，本身无版本概念——v1 **不改造执行函数**，而是新增 Metric Registry 登记表，为每个指标显式登记 `metric_id + definition_version + 口径摘要（单位/聚合/时间语义/粒度/可加维度）`。Ranking v1 只登记一个指标：`finance.customer_sales_ranking@1.0.0`（口径摘要随切片验收一并冻结）。后续接入 `metric_snapshot` 时同步登记对应指标，禁止出现“执行可用但 Registry 无版本”的指标进入 Evidence 链路。Resolver 解析出的 `definition_version` 必须与 Typed Result/Evidence Envelope 记录的版本一致，不一致即 `METRIC_VERSION_MISMATCH` 拒绝。

### 4.2 强类型 Operation

Operation 必须声明输入引用、期望类型、Scope 要求和输出类型。Type Checker 至少校验：

- 指标、维度与聚合兼容性。
- 单位、币种和数据粒度。
- 时间范围、时区、`as_of` 和 comparison cohort。
- DAG 引用存在、无环且输入输出兼容。
- `share_of_total` 的分子是同指标、同口径、同期间分母的真实子集。
- 跨指标运算存在注册公式和明确业务含义。

例如“今年 Top5 销售额 ÷ 去年总利润”可以拆为多个 Operation，但不能标记为合法 `share_of_total`：它同时存在非组成关系、跨指标和时间 Scope 不一致。Compiler 应阻断该 Operation，并澄清用户要的是销售额占总销售额、同期间指标倍数，还是其他已定义公式。

#### Operation 拆分粒度验证（防过度拆分 / 防拆漏）

Type Checker 校验的是“DAG 内部合法”，不回答“拆分粒度是否正确”。拆分由 LLM 提议，但**粒度质量由确定性规则校验**，落入 PlanValidator：

- **防过度拆分（合并规则）**：同一分析原子（同 `metric_id + definition_version + dimension + scope + period + limit`）不允许拆成多个 Operation；无独立输出引用、结果完全被同轮其他 Operation 覆盖的冗余节点必须合并。合并后若出现孤立节点或重复执行同一查询，PlanValidator 拒绝或强制合并。
- **防拆漏（覆盖检查）**：对已识别分析原子集合，逐项核对用户问题中的核心信息点——指标、维度、期间、实体、比较词、占比词——是否都有 Operation 覆盖；任何核心点缺失即进入澄清或 `partially_compiled`，**不得静默执行不完整 DAG**。
- **粒度可观测**：每次编译记录 `operation_count`、合并/拆分原因、覆盖检查结果进入 Trace；Replay 可断言“同一问题两次编译产出相同粒度”。
- **v1 范围**：Ranking v1 的 DAG 是固定形状（`ranking → topn_total → share_of_total` 依赖），不开放任意拆分，因此 v1 只校验“形状正确 + 依赖完整 + 核心信息点覆盖”；通用粒度验证随 `period_comparison` 切片引入多 Operation 时生效。

### 4.3 编译状态与失败语义

编译结果至少支持：

- `compiled`：全部 Operation 可执行且验证通过。
- `requires_clarification`：缺失信息或候选歧义会实质改变结果。
- `partially_compiled`：部分 Operation 合法；只有产品策略明确允许时才能执行合法部分。授权机制见下。
- `unsupported`：系统没有指标、公式或执行能力。
- `invalid`：类型、引用或 Scope 冲突。
- `policy_denied`：权限或安全策略拒绝。

首批稳定错误码包括：`UNKNOWN_METRIC`、`AMBIGUOUS_METRIC`、`METRIC_DIMENSION_INCOMPATIBLE`、`INVALID_AGGREGATION`、`TIME_SCOPE_AMBIGUOUS`、`TIME_SCOPE_MISMATCH`、`GRAIN_MISMATCH`、`UNIT_MISMATCH`、`NON_COMPOSITIONAL_RATIO`、`UNREGISTERED_CROSS_METRIC_FORMULA`、`UNRESOLVED_COHORT`、`INVALID_OPERATION_REFERENCE`、`CYCLIC_OPERATION_DEPENDENCY`、`CAPABILITY_UNAVAILABLE`、`POLICY_DENIED` 和 `UNSUPPORTED_ANALYSIS_TYPE`。

**`partially_compiled` 授权机制**：能否执行合法部分由**编译策略（Compile Policy）**决定，不是 LLM 决定，也不是默认放行。授权判定为三条件**同时满足**：

1. 该部分对应的分析原子已在 Registry 注册且可执行；
2. 该部分产生的谓词/Claim 被对应 Answer Contract 模板允许；
3. 该部分无权限/Scope/时间冲突。

任一条不满足，该部分一律不执行。**默认策略为 `allow_partial_execution=false`**：新部署未显式开启时不执行任何部分，整体返回 `partially_compiled` 或 `requires_clarification`（由产品策略选择）。开启后，执行合法部分还必须遵守输出契约：Response 显式披露未覆盖部分（如“已回答排行；利润查询暂不支持”），Trace 记录 `partial_scope` 与被拒部分的 `reason_code`，**不得静默假装完整回答**。

- **v1 落点**：Case 11（“排行，顺便问利润”）即 `partially_compiled` 实例——排行部分满足三条件执行，利润部分（指标未注册）拒绝并披露。v1 不建设通用策略平台，实现为“Answer Contract 模板 + 固定裁决”（与切片文档 Case 11 裁决一致），并记录 `reason_code=UNSUPPORTED_ANALYSIS_TYPE`。
- **验证基线**：Replay 必须断言“部分执行时披露内容正确、拒绝原因稳定、未执行部分不产生 Claim”。

### 4.4 置信度与澄清策略

引入置信度，但禁止使用单一全局分数或 LLM 自报分数直接决定放行。每个语义决策分别记录：

```json
{
  "field_path": "operations.op2.metric",
  "selected": "finance.net_profit",
  "confidence": 0.62,
  "candidates": [
    {"id": "finance.net_profit", "score": 0.62},
    {"id": "finance.gross_profit", "score": 0.58}
  ],
  "candidate_margin": 0.04,
  "resolution_method": "registry_semantic_match",
  "registry_version": "finance-metrics@3.2"
}
```

置信度来源优先级为：精确 ID/别名匹配、租户配置与已确认约束、确定性规则、检索分数及候选差值、经标注数据校准的模型概率，最后才是 LLM 自报分数。阈值必须通过 Replay 数据按字段校准，不能统一写死为 `0.8`。

澄清由 `ClarificationPolicy` 根据确定性冲突、候选歧义、信息重要程度、执行成本和业务风险决定：

- 类型、Scope、权限等确定性错误无视置信度，直接阻断。
- 多个接近候选或不同解释会显著改变结果时，必须澄清。
- 有版本化租户默认值且风险低时，可以自动解析，但必须记录并向用户披露 assumption。
- 只影响展示形式或已在当前会话确认的约束，不重复澄清。

澄清问题一次只处理真正阻塞的字段，给出 2～3 个业务候选，并保留已解析部分。用户回答后进行增量编译，不重新解释整个请求。

```json
{
  "status": "requires_clarification",
  "ambiguities": [{
    "field_path": "operations.op2.metric",
    "reason_code": "AMBIGUOUS_METRIC",
    "materiality": "high"
  }],
  "clarification": {
    "question": "这里的总利润是指毛利润还是净利润？",
    "options": ["finance.gross_profit", "finance.net_profit"]
  }
}
```

核心放行原则是：LLM 提议 AST，Registry 解析符号，Type Checker 判断合法性，Plan Validator 决定是否进入 Evidence 链路；无法证明可执行且语义正确时，不执行。
