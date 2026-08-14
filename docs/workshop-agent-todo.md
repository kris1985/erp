# 车间军师 Agent 工程化待办

> 目标：把“能对话的军师”升级为**受 ERP 数据、权限、证据和人工审批治理的分析工作流引擎**。
>
> 核心原则：LLM 负责理解、编排与非数值解释；指标服务负责查询；计算引擎负责数值；前端负责渲染；人负责不可逆业务动作。

## 当前已完成

- [x] Evidence Guardrail、证据账本、默认折叠证据
- [x] 生命周期领域角色：订单承诺、采购保供、排产产能、生产质量、交付经营
- [x] 自动只读诊断包：回款 / 应收 / 利润类问题同轮补齐数据
- [x] `metric_snapshot`、`period_comparison`、`ranking` 的第一版 Typed Presentation
- [x] `AnalysisType Registry`、`SemanticPlan`、`ExecutionPlan`、基础 Match Gate
- [x] 利润快照、同比/环比、客户销售额排行的 Registry 样板
- [x] Result Store：查询结果生成租户隔离的 `result_id`
- [x] Restricted Calculation Tool：只接受字段引用，返回 `calculation_id` 与计算血缘

## P0：治理工件与稳定契约

### 0.1 配置即代码

- [x] 新建 `app/agent_policy/`，替代散落在 Prompt 中的长规则
  - `global-policy.yaml`：数字、证据、权限、HITL 总规则
  - `analysis-registry.yaml`：分析类型、必填 Slot、默认值、Match 规则
  - `metric-catalog.yaml`：语义指标到实际 `metric_id` 的映射
  - `action-policy.yaml`：只读 / 草稿 / 审批 / 禁止动作矩阵
  - `ui-contract.yaml`：Typed Result 与展示形状映射
- [x] 为以上配置增加版本号，并在每轮 Trace 中记录版本
- [x] 后端启动时校验配置 Schema；禁止仅靠 Prompt 解释规则

**验收**：新增一个 Metric 或 analysis type 不需要修改主 Prompt；非法 Registry 配置启动失败。

### 0.2 Semantic Plan Planner

- [x] 用受约束 JSON 输出替代当前 Finance 关键词样板 Planner
- [x] Planner 只能生成已注册的 `analysis_type`、Metric、Dimension、Order、Limit
- [x] Slot 不足时返回 `missing_slots`，前端展示明确的补充问题
- [x] 将 Planner 输出记录为 `semantic_plan_id`

**验收**：`按单号查回款` 未提供单号时不执行查询；`Top 10 客户` 的时间、维度、排序和数量可被断言。

## P1：数据血缘与计算闭环

### 1.1 Result Store 完整化

- [x] 为 `result_id` 增加会话 ID、TTL、最大保留量和清理任务
- [x] 支持安全的字段目录查询：`inspect_result(result_id, fields, limit)`
- [x] 仅把摘要、Schema 与字段引用给模型；大明细按需读取
- [x] Evidence 卡片仅展示业务事实，不向前端暴露内部 `result_id`

### 1.2 Calculation Engine 完整化

- [x] 支持 `rank`、同比、环比、移动平均、占比等受限运算
- [x] 计算输入仅允许 `result_id.field` 或 `calculation_id.value`
- [x] `calculation_id` 可重放：保存公式、输入血缘、精度、执行时间
- [x] 将 `metric_snapshot`、`period_comparison`、`ranking` 全部迁移为引用驱动

**验收**：模型生成的裸金额、日期、百分比不能通过；所有展示数值都可追溯到字段或计算节点。

## P2：补齐分析类型

按价值顺序实施，每一类都必须同时具备：Slot Schema、Resolver、Execution Plan、Match Test、Typed Result、Evidence、UI Contract。

- [x] `time_series`
  - Slot：Metric、TimeRange、TimeGranularity、Filters
  - 默认不出图；仅趋势问题、显式“看图”或仿真需要时展示
- [x] `exception_list`
  - Slot：Entity、RiskCondition、TimeRange、Order、Limit
  - 场景：逾期、缺料、超产能、质量预警、低回款
- [x] `composition`
  - Slot：Metric、Dimension、TimeRange、Filters
  - 场景：成本、产能占用、缺料原因构成；优先占比条，避免滥用饼图
- [x] `data_table`
  - Slot：Entity、Columns、Filters、Order、Limit
  - 仅用户明确要明细 / 列表 / 出表时展开
- [x] `scenario`
  - Slot：Base Facts、Assumptions、Calculation Method、Comparison Target
  - 场景：插单、加班、外协、交期与现金流仿真
- [x] `attribution_analysis`
  - 与 `decision` 分离；默认折叠，仅解释“主要由谁/什么造成”

## P3：子 Agent 与人工审批

- [x] 主控根据 Semantic Plan 选择固定生命周期角色；不动态创建无边界子 agent
- [x] 复杂 `decision / scenario` 拆为子 Plan，各子 agent 只返回 Typed Result + Evidence 摘要
- [x] 子 agent 不回传思维过程或完整原始数据，防止上下文污染
- [x] 建立 HITL 状态机：草稿、待审批、已批准、已拒绝、已执行、已过期
- [ ] 下列动作一律审批后恢复执行：确认排产、改交期、创建采购单、核销回款、工资/工时修改、外发通知

**验收**：同一问题的多领域分析可回放；任何写入动作都可定位审批人、证据、影响对象和恢复节点。

## P4：可观测性、Eval 与发布

- [x] Trace 记录：`semantic_plan_id`、`execution_plan_id`、`result_id`、`calculation_id`、Match、审批与版本
- [x] 每会话锁替代全局锁；不同租户/会话可并行
- [x] Prompt / Registry / Metric Catalog / Calculation Engine / Guardrail 版本化
- [x] 建立按 analysis type 分类的黄金测试集
  - [x] 正常查询
  - [x] 缺 Slot
  - [x] Metric / Time / Dimension / Filter / Order / Limit 不匹配
  - [x] 无权限
  - [x] 计算血缘缺失
  - [x] 写操作审批
- [x] LLM-as-a-Judge 评估 `decision` 与 `attribution_analysis`，不替代确定性 Match
- [ ] Shadow → 灰度 → 全量发布；监控追问率、拦截率、计划失败率、人工否决率

## 下一刀（建议立即执行）

1. 将 `AnalysisType Registry` 从 Python 常量迁移到版本化 YAML + Schema 校验。
2. 为 Result Store 增加会话归属与 TTL；将内部 ID 从前端 Evidence payload 隐藏。
3. 实现 `time_series` 的第一个指标（建议“近 12 月回款”或“近 12 月毛利”）。
4. 为 `time_series` 补 Slot / Match / Chart opt-in 的端到端测试。

## 后续演进：语义指标层试点

> 不让 LLM 生成 SQL；LLM 只填受约束的语义查询 Schema，查询编译器只生成参数化、权限注入后的查询计划。
>
> 设计借鉴：采用 dbt / MetricFlow 的 `entity / measure / dimension / metric` 语义模型，采用 Cube 的 Catalog + Policy + Runtime + Metadata API，采用 Looker 的主键、Join 基数与 fanout 校验；不直接引入 Apache Calcite，单 MySQL ERP 首版使用窄范围 SQLAlchemy AST 编译器。关注 Open Semantic Interchange（OSI）作为未来导入 / 导出兼容目标，不作为首版运行时依赖。

- [ ] 新增 `semantic_query` Execution Plan：`metric`、`dimensions`、`filters`、`time_range`、`order`、`limit`
- [ ] 首批语义指标目录：收入、成本、毛利、回款、应收
- [ ] 首批语义维度目录：客户、订单、月份（支持按客户 / 订单 / 月份切分上述指标）
- [ ] 定义语义模型 Schema：`entity`、`measure`、`dimension`、`metric`、默认时间维度、时间粒度、指标口径版本与负责人
- [ ] 为每个 Measure / Metric 声明可加性：`additive`、`semi_additive`、`non_additive`；半可加指标（如期末应收、库存）限定快照时间语义，不可加指标（如毛利率、回款率）强制按分子 / 分母重算
- [ ] 派生指标重算：毛利率、回款率、良率、单位成本等保存分子 / 分母 / 公式，跨维度汇总时重算；禁止对已计算比例直接求和或平均
- [ ] 新增 `Temporal Expression Resolver`：将“本月、近 N 月、上月、去年同期、截至今天”等自然语言归一化为带基准时刻、时区、日历、粒度与 `[start, end)` 边界的时间对象
- [ ] 新增 ERP 日历策略：自然月 / 财务月、生产周、关账日与指标默认时间字段（如回款日、出货日、订单日）；为时间表达式建立固定基准日黄金测试
- [ ] 消除时间字段歧义：每个指标声明默认业务时间字段及可切换字段；收入明确按下单 / 出货 / 开票 / 确认收入，回款明确按到账 / 核销 / 录入，切换须进入 Evidence
- [ ] 新增 `TimeCoverageGuard`：在时间解析后、查询编译前校验指标数据可用范围、查询最大跨度、粒度与时间字段
- [ ] 时间覆盖状态显式化：`complete`、`partial`、`empty`、`out_of_bounds`；空数据、部分覆盖或超范围不得静默替换为最近可用数据，须返回可用起止日期
- [ ] 对比窗口对齐：同比 / 环比按相同日历窗口或相同长度窗口生成基线；不完整、不可比较的区间返回明确状态并写入 Evidence / Typed Result
- [ ] 定义 Join Graph：主键、外键、Join Key、基数（1:1 / N:1 / 1:N / N:N）与 fanout 黄金测试；聚合前先验证可加性
- [ ] 定义事实粒度（grain）：订单行、发货单行、回款流水、期末快照等；禁止未声明粒度的跨事实表 Join 后直接聚合
- [ ] 定义慢变维（SCD）语义：客户等级、业务员、订单状态等按“历史当时值”还是“当前值”切分必须显式声明
- [ ] 定义空值 / 未知值语义：未分配、未建 BOM、未确认交期等不得被静默过滤；明确是否归入“未知 / 未配置”分组
- [ ] 定义高基数与 Top N 策略：最大分组数、最大明细行数、分页、`Top N + 其他` 与占比分母口径
- [ ] 定义货币、单位与精度契约：币种、含税 / 未税、单位（元 / 万元、双 / 件）、精度与四舍五入阶段；禁止展示格式化数参与计算
- [ ] 定义指标版本可比性：口径变更保留 `metric_version`；跨版本对比默认拒绝或明确标注不可比
- [ ] 建立 Metric / Dimension / Filter / Join 白名单与字段、行级权限注入；拒绝 LLM 直接输入 SQL、表名或表达式
- [ ] 将 Schema 编译为逻辑查询 AST（Scan / Filter / Join / Aggregate / Project / Sort / Limit），再由 SQLAlchemy 编译为参数化 SQL；仅值可绑定参数，表 / 列 / 排序 / Join 一律来自服务端映射
- [ ] 为语义层提供 Metadata API：发现可查询指标、维度、过滤器、权限与描述；供 Agent、前端与外部 BI 复用
- [ ] 查询成本治理：强制 tenant / 数据域条件、最大时间跨度、最大分组数 / 返回行数、超时、`EXPLAIN` 成本摘要、索引检查与预聚合策略
- [ ] 权限与缓存隔离：缓存键包含租户、数据域 / 权限版本、指标版本、时间范围与过滤器；禁止跨租户或跨权限复用结果
- [ ] 解释与证据：每个结果记录指标 / 口径版本、数据截至时间、时间字段、过滤器、覆盖状态、逻辑 / 物理执行计划与字段血缘；结果继续进入 Result Store 与 Calculation Engine
- [ ] 与现有代码型利润/回款报表跑黄金集对账；口径一致后才灰度开放
- [ ] 保留代码型指标：今日行动、齐套判断、交期风险、排产建议、插单仿真、质量预警不迁移为通用 SQL

## 后续演进：业务剧本与开发 Skill

> 运行时优先建设版本化业务剧本（YAML / JSON），不把业务规则继续堆进 Prompt；Codex Skill 仅用于复用开发流程，不作为 ERP 在线请求的执行机制。

- [ ] 定义业务剧本 Schema：触发意图、必填 Slot、可用指标 / 维度、默认参数、禁止行为、输出形状、审批要求与版本
- [ ] 经营问数剧本：收入、成本、毛利、回款、应收；路由到 `semantic_query` 试点
- [ ] 今日经营剧本：今日 3 件事固定调用 `analytics.today_actions`，仅展示 `top3` 与逐条证据
- [ ] 决策 / 仿真剧本：插单、加班、外协；固定拆分订单承诺、采购保供、排产产能子计划，产出审批草稿而非直接写入
- [ ] 待“新增指标”流程稳定后，创建开发用 Codex Skill：自动补齐指标目录、Schema、权限 / 血缘、黄金测试和文档；不参与生产请求执行

## 后续演进：查询成本、结果预览与受控导出

> 查询需要分级做成本预检，而不是默认先执行一次昂贵查询。模型只接收摘要与字段引用；大明细存入 Result Store 或异步查询任务结果，按需分页读取。

- [ ] 查询编译前生成逻辑计划：指标、事实粒度、Join、过滤器、预估分组数与 `limit`
- [ ] 为可能昂贵的 MySQL 查询执行普通 `EXPLAIN` 成本预检；禁止默认使用会实际执行查询的 `EXPLAIN ANALYZE`
- [ ] 定义成本阈值与降级策略：扫描行数、临时表、全表扫描、Join 数或预计耗时超限时拒绝、缩小范围、走预聚合或转异步任务
- [ ] 默认 `interactive_preview`：同步返回 KPI / 汇总值、最多 10～20 行预览、总行数、截断标记、排序、过滤条件与数据时间范围
- [ ] 大结果禁止直接注入 LLM 上下文或聊天 SSE；完整结果只保留在 Result Store / 查询任务结果，并提供继续分页、缩小范围、导出的下一步选项
- [ ] 实现 `paginated_detail`：用户主动翻页读取明细，并继承原查询的权限、租户隔离、排序与过滤条件
- [ ] 实现 `async_export`：仅在用户明确要求“导出”“下载 Excel/CSV”或“生成明细表”时，创建受限异步导出任务，由服务端生成 CSV / XLSX 和短期下载链接
- [ ] 导出任务具备权限校验、租户隔离、过期时间、最大行数与导出审计；大导出分页流式写入，禁止将全量结果装入内存
- [ ] 敏感数据或大范围导出要求审批或至少二次确认
- [ ] Agent 仅可建议导出或创建导出草稿 / 任务；不得拥有任意路径写文件、任意 SQL 导出或自行上传外部存储的权限
- [ ] 明确普通查询不写文件；只有受控服务在用户明确导出后生成文件
