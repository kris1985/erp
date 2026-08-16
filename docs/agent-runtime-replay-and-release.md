# Agent Runtime Replay、评估与发布

> 本文定义测试、质量指标和上线门禁；开发切片不得绕过这里的失败用例。

## 一、Ranking Replay 查询集

以下查询作为同一组端到端测试（v1 预期与裁决见 `customer-sales-ranking-slice.md` 的查询集表格）：

1. 客户销售额排行 —— SUPPORTED。
2. 今年客户销售额前 3 名 —— SUPPORTED。
3. 今年哪个客户销售额最高？—— SUPPORTED。
4. 前两名客户占多少？—— SUPPORTED。
5. 客户集中度怎么样？—— SUPPORTED/GATE（Coverage 不足时必须 `insufficient_evidence`）。
6. 厦门海丝排第几？—— SUPPORTED。
7. 给我客户销售额表格。—— SUPPORTED。
8. 去年呢？—— SUPPORTED（期间切换，非跨期比较）。
9. 跟去年相比客户结构有什么变化？—— **UNSUPPORTED_V1**：需要 `period_top_n` 两期对比，不在首期 Predicate/Operation 清单。v1 返回 `unsupported`（`UNSUPPORTED_ANALYSIS_TYPE`）+ 业务化说明，Plan 不得进入 Metric Execute，**不得**偷换成今年固定 Top-N 客户的同比。`fixed_cohort`/`period_top_n` 随 `period_comparison` 切片实现，实现前该 fixture 断言“明确失败语义”。
10. **Coverage 不足**：只返回 Top 3 且无总体分母时询问整体集中度，必须返回 `insufficient_evidence`。
11. **Contract 越界**：只有销售排行 Evidence 时追问利润，排行照答；利润部分以 `CONTRACT_VIOLATION` 拒绝并返回 `unsupported`（利润指标未注册），不得由 Renderer/Response LLM 扩展。注册利润指标后，越界部分才改为触发新 Plan。
12. **跨轮 Evidence 污染**：依次询问“本月回款怎么样？”→“客户销售额排行”→“前两名占多少？”→“他们回款怎么样？”。第二轮不得携带第一轮 Evidence，第三轮继承排行上下文，第四轮只继承实体并重新获取回款 Evidence。

Case 2 后追加“这三家和去年同期相比怎么样？”属于跨期比较（`fixed_cohort`），v1 与 Case 9 同路径返回 `unsupported`；单一期间内的追问（如“这三家占总销售额多少？”）由 composition 依赖支持。`fixed_cohort` 与 `period_top_n` 的 Plan、Evidence、Assertion 和回答措辞必须可区分，是 `period_comparison` 切片的验收标准，不进入 Ranking v1 DoD。

Case 5（Coverage 分支）与 Case 10～12 是架构门禁：任一失败都禁止开启 Ranking Fast Path 灰度。

Replay fixture 从 PR #1 建立，建议使用 Python 测试基建固定目录与编号：`tests/replay/ranking/01-basic.json` 至 `12-cross-turn-pollution.json`（项目根为 pytest 布局，`tests/` 下按 `replay/<analysis_type>/NN-name.json` 组织，由 `tests/test_replay_ranking.py` 统一加载断言）。每个 fixture 必须记录输入、期望 Plan/Assertion、v1 预期（`supported`/`unsupported`/`gate`）、状态和稳定 `reason_code`。

## 二、测试断言

至少覆盖：

- 年度继承和变更、相对时间解析、时区与 `as_of`。
- Limit、排序、实体定位和 comparison cohort。
- Scope、Coverage、总体分母和 Authority。
- 原始 Fact、派生计算、独立重算和计算血缘。
- Business Rule、Answer Contract 和 Deterministic Renderer。
- 句子到 Verified Assertion、Operation 和 Evidence 的反查。
- 跨轮不携带无关 Tool Result。
- 篡改 Calculation 输出、公式、输入、舍入策略或 Evidence Scope 时确定性失败。
- 指标别名、指标歧义、相对时间歧义和固定 cohort/动态 Top-N 歧义能正确解析或澄清。
- 非组成占比、未注册跨指标公式、单位/粒度不兼容和无执行能力不会进入 Evidence 链路。
- 澄清后只增量更新受影响字段，已确认的 Metric、Scope 和 Operation 不发生漂移。

## 三、评估指标与发布门槛

### 正确性

- 数值 Claim 绑定率：100%。
- Claim Precision：100%。
- Evidence Sufficiency Rate：100%。
- Unsupported Claim Escape Rate：0。
- Structured State 与运行时指令一致率：100%。
- 无权限、不完整覆盖和跨口径对比必须显式失败或降级。
- Executable Plan Precision 接近 100%，Unsafe Compile Escape Rate 为 0。
- 必要澄清召回率、非必要澄清率、澄清成功率和平均澄清轮数可观测；阈值在标注 Replay 集上按字段校准。

### 效率

> **基线定义（PR #1 前固化）**：基线在现有链路上采样，不等待新链路。采集窗口 = 现有 `chat()` 生产路径连续 ≥7 个自然日或 ≥200 个简单分析样本（先到者）；简单分析 = 六类（`metric_snapshot`/`ranking`/`time_series`/`data_table`/`composition`/`period_comparison`）中实际已具备的查询，每类 ≥50 样本。指标口径：输入 Token 中位数取整轮模型调用所有输入消息的 token 合计（`tiktoken`/模型同族 tokenizer 统计，与验收时同口径）；P95 延迟取业务入口 `chat()` 到首次业务回复落地的墙钟；SubAgent 调用率 = 该查询集内产生 `task` 子 Agent 调用的轮次占比。验收时用同一查询集、同一口径对比，基线样本与验收脚本一并入库版本控制。

- 简单分析输入 Token 中位数下降至少 40%。
- 简单分析 SubAgent 调用率低于 5%。
- 简单分析 P95 延迟下降至少 30%。
- 大 Tool Result 再次内联率为 0。
- Context Relevance Ratio 持续提升，不能依赖粗暴截断。

### 可观测性

每轮至少记录：

- Context Projection 前后消息数、Token 和每个块的纳入原因。
- Router 路径、`reason_code`、`rule_id`、预计成本和实际成本。
- Semantic/Execution/Result/Calculation ID。
- Compiler 状态、字段级候选与置信度、candidate margin、解析方法、Registry 版本、assumption 和 clarification reason。
- Metric Definition Version、Scope、Coverage、Freshness 和 Authority。
- Fact、Calculation、Rule、Assertion 与 Answer Contract 引用。
- 时间区间、时区、`as_of`、Operation 依赖和物化 cohort。
- 各 Validator 状态、稳定原因码与恢复动作。
- Runtime Contract、Prompt、Policy、Renderer 和 Projector 版本。

**Trace 落库方案（v1）**：继续使用现有本地账本 `agent_trace_service.py`（`agent_run_traces` 表的 `trace_json` JSON blob），不新增表、不改 schema——新字段（契约版本、Projection 前后消息数与 Token、计算血缘、Validator 状态、Router 路径、失败 reason_code）直接写入 `trace_json`；`versions` 字典承载 `ResolvedSemanticPlan@1`、`TypedAnalysisResult@1` 等 8 个契约的 Schema Version。LangSmith 保持可选分布式 Trace，本账本保证无 LangSmith 时仍可 Replay。契约升级时保留兼容读取：旧 `trace_json` 缺少新字段按“未知”处理，不阻断回放。

## 四、发布策略

1. Offline Replay：重放现有 Trace，不影响线上回答。
2. Shadow：新旧链路并行比较 Plan、Fact、Assertion、Token 和延迟（离线示例：`scripts/shadow_ranking_demo.py`，基线 = 12-case Replay fixture 期望，候选 = Fast Path 实际产物）。
3. 灰度：先开放 Ranking；通过后再开放 Metric Snapshot。
4. 扩展：稳定后逐类迁移其他确定性分析。
5. 回滚：契约或 Validator 失败时回退旧链路，并保留完整失败 Trace。

### 4.1 灰度操作与部署验证清单（Ranking / Metric Snapshot Fast Path）

**开关**：`AGENT_FAST_PATH_ENABLED`（默认 `false`）。由 uvicorn 进程启动时读取——远程经 `deploy.sh` source `deploy.env`，本地经 `.env` 或环境变量。**修改开关必须重启服务才生效**（进程启动时读一次）。

**灰度步骤（Ranking）**：
1. 重新部署最新代码（含 `iter_chat_sse` 接入与前端展示）并重启：`./deploy.sh`（或本地 `uvicorn app.main:app` 重启）。
2. 保持开关 `false` 先观察：问"客户销售额排行"，前端应出现灰色"观测"状态条 + `fast_path_observation` 记录（现有 Agent 路径照常）。
3. 打开开关（`AGENT_FAST_PATH_ENABLED=true`）重启，用 12-case 查询集逐条验证：
   - "客户销售额排行" / "今年客户销售额前 3 名" → 排行回复
   - "前两名客户占多少" / "客户集中度怎么样" → 占比 + 规则判断（无集中度判断时占比句仍在）
   - "给我客户销售额表格" → 表格卡片
   - "去年呢" → 2025 年数据（期间切换）
   - "跟去年相比客户结构有什么变化" → 明确拒绝（`unsupported`，不偷换语义）
4. **预期效果核对**（确定性链路 vs LLM 路径）：
   - 绿色"确定性链路"状态条，而非灰色"观测"
   - 主回复一句结论 + 表格卡片 + 折叠中文依据（查询范围/数据来源/计算方式/判断依据/查询时间）
   - 占比数值精确（如 81.6%）且折叠区可追溯公式与输入；无"约 82%"式 LLM 自算
   - 无越界建议（毛利/回款/应收等 forbidden 领域不出现在排行回答中）
   - 金额显示无 4 位小数泄漏（`3,920 元` 而非 `3920.0000`）
5. 任一异常：关闭开关重启回滚，保留失败 Trace（`agent_run_traces` 与 LangSmith）。

**灰度步骤（Metric Snapshot）**（`docs/metric-snapshot-slice.md` §6 为实施记录）：
1. 保持开关 `false` 先观察：问"本月销售额多少"，前端应出现灰色"观测"状态条。
2. 打开开关重启，验证：
   - "本月销售额多少" → 一句结论"2026 年 8 月销售额 X 万元。"+ 指标/数值表格卡片 + 折叠中文依据（查询范围/数据来源/数值/查询时间）
   - "今年销售额多少" → 年度口径（无月份）
   - "上月销售额多少" / 追问"上月呢" → 期间切换为上一月（跨年回绕正确）
   - "销售额同比多少" / "跟去年比" → 不进入快照 Fast Path（无跨期比较能力）
   - "客户销售额排行" → 仍走 ranking 路径（`fast_path_ranking_v1`），不被快照路径拦截
   - 无权限账号 → `POLICY_DENIED`（"无权限查询销售额"），不降级为数据为空
3. 任一异常：关闭开关重启回滚，保留失败 Trace。

**Shadow 示例**：`scripts/shadow_ranking_demo.py`（ranking 12-case）与 `scripts/shadow_metric_snapshot_demo.py`（快照 9-case，基线 = Replay fixture 期望，候选 = Fast Path 实际产物）。

## 五、完成定义

### Ranking 首期 DoD

1. 8 个 Ranking v1 核心载荷完成序列化、兼容读取和 Trace。
2. Typed Result 与 Evidence 不存在可双写漂移的重复字段。
3. Context 与历史执行信息分离，只继承仍有效实体和约束。
4. 原始及派生数字来自 FactBuilder 和 Calculation，计算经过独立重算。
5. 确定性判断只来自版本化 Business Rule。
6. Answer Contract 和 Structural Validator 能拦截 Coverage 不足、利润越界和跨轮污染。
7. Renderer 为纯确定性实现，只消费 Verified Assertion；Semantic Grounding 记录为 `not_applicable`。
8. 12-case Replay 全部通过——其中 v1 范围外 case（Case 9、Case 2 后跨期追问）以明确 `unsupported` 失败语义通过（断言“返回 unsupported 且 Plan 不进入 Metric Execute”），Unsupported Claim Escape Rate 为 0。
9. Fast Path 通过功能开关灰度，失败时可回退并保留 Trace（✅ 已接入：`AGENT_FAST_PATH_ENABLED` 开关 + `chat()`/`iter_chat_sse` 双入口 + 观测模式；操作见 §4.1）。
10. Semantic Compiler 对 Ranking 输入完成 Registry Resolution、Type Check 和 Plan Validation；歧义输入进入 `requires_clarification`，确定性冲突不会被高置信度绕过。

### Metric Snapshot 首期 DoD

1. `finance.sales_snapshot@1.0.0` 完成 Registry 登记；Resolver 只绑定已注册指标，未注册指标返回 `UNKNOWN_METRIC`。
2. Snapshot 载荷（`TypedAnalysisResult.result_type="metric_snapshot"` + `SnapshotValue`）与 Evidence Envelope 单一权威：payload 不带 metric/scope/coverage。
3. CoverageGate：值缺失 → `insufficient_evidence`，不硬算；销售额为 0 是合法答案（有值即可答）。
4. 值 Fact 由 `SnapshotFactBuilder` 产生，断言只有一个 `value` 谓词；无 rank/share/classification。
5. Answer Contract（`snapshot_answer_contract`）只许可 `value`；利润/回款/增长域 forbid（Case 11 语义）。
6. DeterministicRenderer 输出"X 年 X 月销售额 X 万元。"与指标/数值表格；内部标识符只进 Trace。
7. Replay 9-case 全部通过（`tests/replay/metric_snapshot/`，`tests/test_replay_metric_snapshot.py`），逃逸率 0 / 充分率 100% / 绑定率 100%。
8. 期间切换（上月/去年，跨年回绕）正确继承；"销售额同比/跟去年比"不进入快照 Fast Path（无跨期比较能力）。
9. Fast Path 复用 `AGENT_FAST_PATH_ENABLED` 开关灰度，失败回退并保留 Trace（✅ 已接入：`run_fast_path` 分发 ranking → metric_snapshot；观测模式同上）。

### 总体 Runtime DoD

1. Model Context 与完整事件历史结构分离。
2. 运行时自然语言指令均由 Structured State 渲染。
3. 六类简单分析默认走 Fast Path，不调用 SubAgent。
4. 所有业务数字和派生比例来自 Fact/Calculation，不由 LLM 计算。
5. 所有可验证 Claim 可追溯到 Fact、Calculation/Rule 和充分 Evidence。
6. Prompt 不再承担完整目录、权限判断、格式执行和结果校验。
7. 正确性不下降，并达到 Token、延迟和 SubAgent 指标。
8. Ranking Trace 能展示从 Semantic Plan 到 Verified Assertion、Rendered Answer 和 Validation 的完整链路。

完成 `ranking`、`metric_snapshot`、`period_comparison` 后设置抽象复盘门，再决定 Fact 和 Answer Contract 的保留、合并或扩展。

sed: 1: "694,737;748,900p
": invalid command code ;
