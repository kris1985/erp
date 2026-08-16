# Metric Snapshot 垂直切片（第二个切片：Direct Metric）

> 承接 `customer-sales-ranking-slice.md`（§六"该切片完成后，再复制到 metric_snapshot…"）。
> 本切片只做一件事：**单值销售额快照**（"本月销售额多少" → Direct Metric +
> Deterministic Renderer），并把 ranking 已固化的可信链原样复用，不引入任何
> 通用 BI 能力。

## 1. 切片范围

```text
ResolvedSemanticPlan (metric_snapshot)
  → Metric Execute (finance_service.profit_report → summary.revenue)
  → TypedAnalysisResult (result_type="metric_snapshot" + SnapshotValue)
  → EvidenceEnvelope (operation="metric_snapshot")
  → CoverageGate → SnapshotFactBuilder
  → AssertionBuilder (唯一 value 断言)
  → StructuralValidator → ContractChecker (snapshot_answer_contract)
  → DeterministicRenderer
```

首期明确只实现：

- 指标：`finance.sales_snapshot@1.0.0`（单值销售额，自然月粒度，域 sales）。
- 时间范围：年 + 可选月（`TimeScope.year/month`）；"上月/去年"是期间切换
  （跨年回绕），不是跨期比较。
- 断言：仅 `value` 谓词；无 rank/share/classification/rule。
- Contract：`snapshot_answer_contract()` 只许可 `value`；利润/回款/增长 forbid。
- 渲染：一句结论（"2026 年 8 月销售额 3,425 万元。"）+ 指标/数值表格卡片 +
  折叠中文依据（查询范围/数据来源/数值/查询时间）。
- 明确不做：跨期比较（`period_comparison` 切片）、趋势、占比/集中度、多指标
  快照（收入/成本/毛利三值仍走 LLM 路径的 `profit_overview`）、Metric 层
  下推（过滤下推候选与 ranking 切片一致，不在本切片评估）。

## 2. 查询集（Replay fixture：`tests/replay/metric_snapshot/`）

| # | 查询 | v1 预期 | 说明 |
|---|------|---------|------|
| 1 | 本月销售额多少 | SUPPORTED | 基础快照（年+月） |
| 2 | 今年销售额多少 | SUPPORTED | 年度口径（无月） |
| 3 | 上月销售额多少 | SUPPORTED | 期间切换（跨年回绕，fixture 08） |
| 4 | 本月销售额 | SUPPORTED | 无"多少"也识别（期间词触发） |
| 5 | 给我本月销售额表格 | SUPPORTED | 表格形态（指标/数值 ≤2 列） |
| 6 | 销售额为 0 | SUPPORTED | 有值即答，0 是合法答案非证据不足 |
| 7 | 利润越界 | GATE | 断言集天然无利润断言（利润指标未注册），Contract forbid 兜底 |
| 8 | 上月呢（turn2 追问） | SUPPORTED | 仅当历史存在快照轮次时继承并切换期间 |
| 9 | 未注册指标 | 拒绝 | `UNKNOWN_METRIC`（`finance.profit_snapshot`） |
| 10 | 销售额同比/跟去年比 | 不进入快照 | 无跨期比较能力，交给 LLM 路径 |

额外保证：

- "客户销售额排行" / "今年客户销售额前 3 名" 仍走 ranking 路径
  （`fast_path_ranking_v1`），不被快照路径拦截（planner 消歧测试覆盖）。
- 无权限账号 → `POLICY_DENIED`（"无权限查询销售额"），不降级为数据为空。
- 未指定期间（如"销售额多少"）→ 默认当前年月，Renderer 折叠区披露
  assumption（契约 §4.4 低风险默认 + 披露）。

## 3. 实施记录（2026-08-17）

### 代码落点

- `app/runtime/contracts.py`：`TimeScope` 增加 month 1..12 校验；
  `TypedAnalysisResult` 支持 `result_type="metric_snapshot"` + `SnapshotValue`
  （shape 校验：snapshot 必须带值且无 rows，ranking 反之）；`EvidenceEnvelope`
  operation 加 `metric_snapshot`；新增 `snapshot_answer_contract()`。
- `app/runtime/registry.py`：新增 `SALES_SNAPSHOT_METRIC`
  （`finance.sales_snapshot@1.0.0`，自然月，域 sales）；`MetricRegistry.v1()`
  同时登记 ranking + snapshot 两个指标。
- `app/runtime/resolver.py`：新增 `SnapshotRequest` + `SnapshotResolver`
  （固定 `op_snapshot` 单操作 DAG；year 缺失 → `TIME_SCOPE_AMBIGUOUS`；
  month 越界 → `INVALID_MONTH`；未注册指标 → `UNKNOWN_METRIC`）。
- `app/runtime/coverage.py`：新增 `check_snapshot_coverage`（值缺失 →
  `insufficient_evidence`；值存在即 verified——0 是合法答案）。
- `app/runtime/fact_builder.py`：新增 `SnapshotFactBuilder`（单值 Fact
  `{result_id}:total`，无维度）。
- `app/runtime/assertions.py`：`AssertionBuilder` 对 metric_snapshot 只产一个
  `value` 断言（`a_snapshot_value`）。
- `app/runtime/structural_validator.py`：snapshot 的 value 断言增加
  `check_snapshot_coverage` 门禁。
- `app/runtime/renderer.py`：`render_snapshot_sentences`（一句结论）、
  `render_snapshot_table`（指标/数值）、`render_summary`/`render_explanation`
  快照分支（折叠区不含内部标识符）。
- `app/runtime/router.py`：`FAST_PATH_METRICS` 加入 snapshot 指标；
  `route.fast_path.metric_snapshot@1` / `fast_path_metric_snapshot_v1`。
- `app/runtime/spill.py`：快照结果 spill（单值 summary，无行预览）。
- `app/services/analysis_plans.py`：`_match_sales_snapshot` 识别
  销售额/销售金额/销售总额 + 数值或期间或表格意图；排除排行/Top/前N名/
  占比/集中度/趋势/同比环比等其它分析原子；期间解析优先级
  显式年月 > 上月/去年 > 本月/今年 > 默认当前年月。
- `app/services/workshop_metrics.py`：catalog 登记 `finance.sales_snapshot`
  （`_metric_sales_snapshot`，权限 `menu.profit`，与排行共用 profit_report 口径）。
- `app/services/agent_fast_path.py`：`MetricSnapshotFastPath` + `run_fast_path`
  分发（ranking → metric_snapshot → LLM）；turn2「上月呢」期间切换继承。
- `app/agent_policy/metric-catalog.yaml` / `analysis-registry.yaml`：
  `sales_snapshot` 语义指标登记（`finance.sales_snapshot`，metric_snapshot）。
- `tests/test_replay_metric_snapshot.py` + `tests/replay/metric_snapshot/` 9 个
  fixture；`tests/test_agent_fast_path.py` 快照用例（观测/执行/年度/月度/
  权限/排行不混淆/期间切换）；`tests/test_sse_fast_path.py` SSE 快照用例。
- `scripts/shadow_metric_snapshot_demo.py`：快照 Shadow 对比示例。

### 决策记录

1. **单值模型**：snapshot 用 `SnapshotValue`（value+unit）而非复排行 rows；
   `TypedAnalysisResult` 用 shape 校验在两种结果类型间互斥，避免双写漂移。
2. **期间切换 ≠ 跨期比较**："上月/去年"是绝对期间切换（Case 8 语义），
   "同比/环比/跟去年比"无跨期能力 → 不进入快照 Fast Path。
3. **planner 消歧**：`客户销售额前3名`（前N名在客户之后）补充进 ranking
   匹配（`_RANKING_TOP_SUFFIX_RE`），防止被快照分支误吞。
4. **0 是可答值**：销售额 0 是合法答案；只有"无值"（shape 校验无法构造）
   或执行失败才算证据不足——与 ranking 的 denominator 门禁语义不同。
5. **复用开关**：与 ranking 共用 `AGENT_FAST_PATH_ENABLED` 灰度开关，观测
   模式记录 `fast_path_observation`，失败回退 LLM 路径并保留 Trace。

### 验收（当前全绿）

- `pytest tests/test_replay_metric_snapshot.py tests/test_agent_fast_path.py
  tests/test_sse_fast_path.py`：快照 9-case Replay + 快照集成全部通过。
- `pytest` 相关 runtime/planner/policy 回归（`test_analysis_plans.py`
  `test_agent_policy.py` `test_runtime_*` `test_replay_ranking.py`）：全部通过。
- `scripts/shadow_metric_snapshot_demo.py`：3/3 一致（plan/value/table/trust）。

## 4. 下一下切片

按发布策略（replay doc §四）：Metric Snapshot 通过后，复制到
`period_comparison`（需要 `fixed_cohort`/`period_top_n` 与跨期 Operation，
是 ranking Case 9 / snapshot 同比的落点）。
