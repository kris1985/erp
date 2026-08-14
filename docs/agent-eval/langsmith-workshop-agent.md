# 车间军师：LangSmith Trace 与 LLM-as-a-Judge

## Trace 接入

部署时配置：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=workshop-agent
```

每一轮军师咨询会生成独立 `run_id`，同时作为 LangSmith 根 trace ID。Trace 带有 `tenant_id`、`conversation_id`、传输方式与 `workshop-agent` 标签；不要把 token、用户原始问题或完整工具结果写入 metadata。

## Judge 的定位

LLM Judge 只做离线回归和抽样质检，**不**作为生产请求的实时事实闸门。实时 evidence guardrail 会在回复出站前检查：高风险问答必须有工具证据；回复中的日期、订单号、长数字和带单位数值必须能在工具结果中找到。校验失败时统一降级为「暂不能确认」，且 SSE 不会先把未经校验的 token 发给前端。Judge 用于发现提示词、工具选择或 guardrail 的回归。

在 LangSmith Prompt Hub 新建并提交一个 `StructuredPrompt`，名称建议：`workshop-agent-evidence-judge`。输出 schema：

```json
{
  "grounded": {"type": "boolean", "description": "所有事实性结论都能由参考 evidence 支持"},
  "decision_quality": {"type": "string", "enum": ["pass", "review", "fail"]},
  "concise": {"type": "boolean", "description": "默认短答没有重复、表格或无关展开"},
  "reason": {"type": "string", "description": "最多 80 字，指出唯一最重要的问题"}
}
```

Judge prompt：

```text
你是鞋厂 ERP 的严格质检员。根据“问题”“回答”“参考证据”评分。

硬规则：订单号、日期、数量、金额、产能、交期、质量风险等事实，必须能在参考证据中逐项找到。没有证据即 grounded=false，decision_quality=fail。不要因回答文采好而放宽事实要求。

回答默认应是结论 + 最多 3 条短行动；用户没有要求详细时，重复解释、长表格、工具过程均 concise=false。

“建议”可以不等于事实，但不得伪装成已确认结论。信息不足时，明确说“暂不能确认”是正确行为。
```

创建 evaluator（默认 dry-run）：

```bash
python3 scripts/register_langsmith_workshop_judge.py \
  --prompt-repo-handle <repo_handle> --commit latest --apply
```

执行完整黄金集（demo 环境可上传完整指标 payload）：

```bash
PYTHONPATH=. .venv/bin/python scripts/run_langsmith_workshop_eval.py
```

测试集会从 demo 数据库加入交期、负荷、质量、订单进度、财务等可用事实案例，并为 `decision` 与 `attribution_analysis` 单独标注分类；同时始终加入无权限、无数据、工具错误三个失败边界案例。首次运行会创建固定快照；后续运行复用该快照，不会重复追加案例。只有在 demo 数据有意更新时才使用 `--refresh` 创建新快照行，并应改用新的数据集名称（如 `workshop-agent-db-grounded-v4`），避免参考证据过期或重复案例污染基线。先离线跑黄金集，再开启对生产 trace 的抽样评测。

## 上线门槛

- `grounded=false`：0 条高风险事实。
- `decision_quality=fail`：低于 1%。
- `concise=false`：低于 5%。
- Judge 与人工抽检结论不一致时，人工为准；把纠正加入 LangSmith corrections dataset，作为 few-shot 反馈。
