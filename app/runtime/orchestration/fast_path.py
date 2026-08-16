"""Bounded Semantic Workflow 子图（架构定稿 §4/§9 P1，修正版）。

FastPath 不是"0 模型"，而是——**无 Agent 自主循环、模型调用有固定上限
（0～2 次）、执行计划受强约束的可预测链路**。LLM 只能参与受限任务
（NL→SemanticPlan、指代消解、跨轮条件继承），且必须结构化输出 + 确定性
验证；不允许自主调用任意工具、不允许开放式循环。

节点序列：

    semantic_compile(LLM) → inheritance_resolve(两级) → plan_validate
      → deterministic_executor → evidence_validate → controlled_render

- ``semantic_compile``：LLM 把问题编译为 SemanticPlan（结构化输出，
  parse_planner_json 校验，extra=forbid），失败 → 显式 reason_code。
- ``inheritance_resolve``：**两级**——第一层确定性继承（读 previous_plans
  换时间/limit/filter，不从文本猜）；规则覆盖不了才调 LLM。
- ``plan_validate``：计划完整可信性校验（registered + complete）。
- ``deterministic_executor``：按固定 DAG 调 Domain Tool（权限在 Tool 内）。
- ``evidence_validate``：可信链校验（CoverageGate→Fact→Assertion→Validator）。
- ``controlled_render``：模板化响应（可含受限 LLM 生成简短受控文案）。

复用 ``app/runtime/`` 可信链与 Domain Tools（workshop_metrics.query_metric）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.runtime.orchestration.fallback import fallback_action
from app.runtime.orchestration.state import (
    ConversationState,
    ExecutionResult,
    Failure,
    Presentation,
    TrustMetrics,
)

LOCAL_TZ = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 节点 1: semantic_compile —— LLM 编译（结构化输出 + 本地校验）
# ---------------------------------------------------------------------------


def semantic_compile(state: ConversationState) -> dict[str, Any]:
    """LLM 把问题编译为 SemanticPlan。

    - 结构化输出 schema（提示词强制 JSON + parse_planner_json 本地校验，
      extra=forbid，缺字段失败）——DeepSeek 不支持 with_structured_output
      （json_schema 400），用 JSON 提示词 + 本地校验（与 semantic_compiler
      同法）。
    - 模型调用次数：1 次（本节点），有明确上限。
    - 编译失败 / 校验不过 → 显式 reason_code，不猜测。
    """
    from app.services.analysis_plans import parse_planner_json
    from app.services.schedule_agent import _content_to_text, _make_model

    question = state.get("question", "")
    # 组装注册表（allowed metrics / required slots），与 _plan_semantic_question 一致
    from app.services import analysis_plans

    registry = {
        name: {
            "required_slots": spec.required_slots,
            "allowed_metrics": spec.allowed_metrics,
        }
        for name, spec in analysis_plans.REGISTRY.items()
        if spec.allowed_metrics
    }
    import json

    system = (
        "你是 ERP 语义计划器。仅输出 JSON；仅能使用如下注册项。无法确定则"
        "输出一个已注册类型并留下缺失 slot，不得编造指标。\n"
        + json.dumps(registry, ensure_ascii=False)
    )
    try:
        response = _make_model().invoke([("system", system), ("human", question)])
        text = _content_to_text(getattr(response, "content", ""))
        import re

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {"failure": Failure(
                reason_code="SEMANTIC_COMPILE_FAILED", action="clarify",
                stage="semantic_compile",
            )}
        output = parse_planner_json(match.group(0))
        if output.missing_slots:
            return {"failure": Failure(
                reason_code="MISSING_SLOT", action="clarify",
                message="需要补充必要信息后才能回答。",
                stage="semantic_compile",
            )}
        plan = output.plan.model_dump() if output.plan is not None else None
        if plan is None:
            return {"failure": Failure(
                reason_code="SEMANTIC_COMPILE_FAILED", action="clarify",
                stage="semantic_compile",
            )}
        return {"current_plan": plan, "semantic_plan": plan}
    except Exception:
        return {"failure": Failure(
            reason_code="SEMANTIC_COMPILE_FAILED", action="clarify",
            stage="semantic_compile",
        )}


# ---------------------------------------------------------------------------
# 节点 2: inheritance_resolve —— 两级（规则优先，必要时 LLM）
# ---------------------------------------------------------------------------


# 确定性继承规则：读 previous_plans 结构化字段，换时间/limit/filter
_PERIOD_SWITCH_RE = None  # 占位；v1 用 previous_plans 结构化字段 + 简单规则

_INHERIT_TIME_RE = None


def inheritance_resolve(state: ConversationState) -> dict[str, Any]:
    """跨轮继承：两级解析。

    第一层（确定性）：上一轮有 plan 且本轮是明确的条件继承（时间/limit/
    filter），直接从 previous_plans 结构化替换，不调 LLM。
    第二层（LLM）：规则覆盖不了（多候选指代、多隐含条件）→ semantic_compiler
    的 LLM propose（有上限 1 次）。

    v1 实现：继承源是 state.previous_plans（结构化），不是 ui_messages 文本。
    若 previous_plans 为空 → 返回未继承（由 plan_validate 决定走哪条路）。
    """
    import re

    question = state.get("question", "")
    previous = state.get("previous_plans") or []

    if not previous:
        return {}

    last = previous[-1]
    # 第一层：确定性继承——「上月呢/去年呢」换时间；「只看top3」换 limit
    # （无当前 plan 时也尝试继承：追问的当前 plan 尚未编译）
    inherited = _deterministic_inherit(question, last)
    if inherited is not None:
        return {"current_plan": inherited, "semantic_plan": inherited,
                "_inheritance": "deterministic"}

    # 第二层：LLM 条件继承（语义编译器），1 次调用上限
    from app.services import semantic_compiler
    from app.services.semantic_compiler import PreviousTurn

    turn = PreviousTurn(
        question=state.get("previous_question") or "",
        reply="",
        analysis_type=last.get("analysis_type"),
        year=(last.get("time_range") or {}).get("year"),
        month=(last.get("time_range") or {}).get("month"),
        limit=last.get("limit"),
    )
    try:
        verdict = semantic_compiler.resolve_inheritance(
            question, tenant_id=state.get("tenant_id", 1),
            conversation_id=state.get("conversation_id", ""),
        )
    except Exception:
        return {}  # LLM 不可用 → 未继承（走 plan_validate → deep_agent）
    if verdict.status == "inherited":
        inherited_plan = _apply_inherited_refine(last, verdict)
        if inherited_plan is not None:
            return {"current_plan": inherited_plan, "semantic_plan": inherited_plan,
                    "_inheritance": "llm"}
    return {}


def _deterministic_inherit(question: str, last_plan: dict[str, Any]) -> dict[str, Any] | None:
    """第一层确定性继承：从上一轮结构化 plan 换时间/limit/filter。

    识别「上月/去年/今年」时间切换、「只看topN/前N名」limit 调整。
    不识别（多候选指代等）→ 返回 None，交第二层 LLM。
    """
    import re

    plan = dict(last_plan)
    tr = dict(plan.get("time_range") or {})
    today = date.today()

    changed = False
    if re.search(r"上月|上个月", question):
        year = tr.get("year") or today.year
        month = tr.get("month") or today.month
        if month == 1:
            tr = {"year": year - 1, "month": 12}
        else:
            tr = {"year": year, "month": month - 1}
        changed = True
    elif re.search(r"去年", question):
        tr = {"year": (tr.get("year") or today.year) - 1}
        changed = True
    elif re.search(r"今年", question):
        tr = {"year": today.year}
        changed = True
    elif re.search(r"本月|这个月", question):
        tr = {"year": today.year, "month": today.month}
        changed = True

    limit_match = re.search(r"(?:Top|top|前)\s*(\d+)", question)
    if limit_match:
        plan["limit"] = int(limit_match.group(1))
        changed = True

    if not changed:
        return None
    plan["time_range"] = tr
    return plan


def _apply_inherited_refine(last_plan: dict[str, Any], verdict: Any) -> dict[str, Any] | None:
    """把 semantic_compiler 的 InheritanceVerdict（limit/min_amount/period/year/
    month）应用到上一轮 plan，产出继承后的 plan。"""
    plan = dict(last_plan)
    if verdict.limit is not None:
        plan["limit"] = verdict.limit
    tr = dict(plan.get("time_range") or {})
    if verdict.year is not None:
        tr["year"] = verdict.year
    if verdict.month is not None:
        tr["month"] = verdict.month
    plan["time_range"] = tr
    if verdict.min_amount is not None:
        filters = dict(plan.get("filters") or {})
        filters["min_amount"] = str(verdict.min_amount)
        plan["filters"] = filters
    return plan


# ---------------------------------------------------------------------------
# 节点 3: plan_validate —— 计划完整可信性
# ---------------------------------------------------------------------------


def plan_validate(state: ConversationState) -> dict[str, Any]:
    """校验 current_plan 是否已注册且完整（架构定稿 §5 分层判定第 3 步）。

    已注册 + 完整 → 继续（deterministic_executor）。
    缺 slot → MISSING_SLOT → clarify。
    不在能力集 / 编译失败 → NOT_IN_FAST_PATH_CAPABILITY_SET → deep_agent。
    """
    from app.runtime.orchestration.router import ConversationRouter

    plan = state.get("current_plan") or state.get("semantic_plan")
    if plan is None:
        return {"failure": Failure(
            reason_code="NO_SEMANTIC_PLAN", action="to_deep_agent",
            stage="plan_validate",
        )}
    router = ConversationRouter()
    state["semantic_plan"] = plan
    decision = router.route(state, fast_path_enabled=True)
    if decision["route"] != "fast_path":
        action = decision.get("fallback_action") or "to_deep_agent"
        return {"failure": Failure(
            reason_code=decision["reason_code"], action=action,
            stage="plan_validate",
        )}
    return {"_validated_plan": plan}


# ---------------------------------------------------------------------------
# 节点 4: deterministic_executor —— 固定 DAG 调 Domain Tool（权限在 Tool 内）
# ---------------------------------------------------------------------------


def deterministic_executor(state: ConversationState) -> dict[str, Any]:
    """按固定 DAG 执行数据查询（Domain Tool 确定性调用，权限在 Tool 内）。

    复用 workshop_metrics.query_metric（白名单 + 权限过滤 + 参数校验）。
    执行产物（结果 JSON + result_id）写入 state，供 evidence_validate 消费。
    """
    from app.services import analysis_result_store, workshop_metrics

    db = state.get("_db")
    tenant_id = state.get("tenant_id")
    plan = state.get("current_plan") or state.get("semantic_plan")
    if db is None or tenant_id is None or plan is None:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="executor",
        )}

    analysis_type = plan.get("analysis_type")
    metric_name = plan.get("metric")
    tr = plan.get("time_range") or {}

    # 语义指标名 → metric_id（capability 层映射）
    try:
        from app.services.agent_policy import get_policy_bundle

        entry = get_policy_bundle().metric_catalog.metrics.get(metric_name)
        metric_id = entry.metric_id if entry is not None else None
    except Exception:
        metric_id = None
    if not metric_id:
        return {"failure": Failure(
            reason_code="UNKNOWN_METRIC", action="clarify", stage="executor",
        )}

    params: dict[str, Any] = {}
    if analysis_type in ("ranking", "metric_snapshot"):
        params = {"year": tr.get("year")}
        if tr.get("month") is not None:
            params["month"] = tr["month"]
    if analysis_type == "ranking":
        params["order"] = plan.get("order") or "desc"
        params["limit"] = plan.get("limit") or 10
        filters = plan.get("filters") or {}
        if filters.get("min_amount"):
            params["min_amount"] = str(filters["min_amount"])

    result = workshop_metrics.query_metric(
        db, tenant_id, metric_id, params=params,
        permission_codes=state.get("permission_codes"),
    )
    if result.get("error"):
        reason = "PERMISSION_DENIED" if result["error"] == "forbidden" else "EVIDENCE_FAILED"
        return {"failure": Failure(
            reason_code=reason,
            action=fallback_action(reason),
            message=result.get("message") or "查询失败",
            stage="executor",
        )}

    result_id = analysis_result_store.put_result(
        tenant_id, metric_id, result, params, session_id=state.get("conversation_id"),
    )
    return {"_execution": {"result_id": result_id, "metric_id": metric_id,
                            "params": params, "raw": result}}


# ---------------------------------------------------------------------------
# 节点 5: evidence_validate —— 可信链校验
# ---------------------------------------------------------------------------


def evidence_validate(state: ConversationState) -> dict[str, Any]:
    """跑可信链校验：CoverageGate → FactBuilder → Assertions →
    StructuralValidator → ContractChecker。任一失败 → 明确 reason_code。"""
    execution = state.get("_execution")
    if execution is None:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="evidence_validate",
        )}

    from app.runtime.contracts import (
        Coverage,
        EvidenceEnvelope,
        Freshness,
        MetricRef,
        SnapshotValue,
        TimeScope,
        TypedAnalysisResult,
        ranking_answer_contract,
        snapshot_answer_contract,
    )
    from app.runtime.fact_builder import RankingFactBuilder, SnapshotFactBuilder
    from app.runtime.assertions import AssertionBuilder
    from app.runtime.structural_validator import StructuralValidator
    from app.runtime.contract_checker import ContractChecker

    plan = state.get("current_plan") or state.get("semantic_plan") or {}
    analysis_type = plan.get("analysis_type")
    tr = plan.get("time_range") or {}
    scope = TimeScope(year=tr.get("year"), month=tr.get("month"))
    result_id = execution["result_id"]
    raw = execution["raw"]
    data = raw.get("data") or {}

    if analysis_type == "ranking":
        items = data.get("items") or []
        rows = []
        for index, item in enumerate(items, start=1):
            rows.append({
                "entity_id": str(item.get("customer_name") or "未知客户"),
                "entity_label": str(item.get("customer_name") or "未知客户"),
                "value": str(item.get("sales_amount") or 0),
                "unit": "CNY",
                "rank": index,
            })
        envelope = EvidenceEnvelope(
            result_id=result_id,
            metric=MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0"),
            scope=scope, dimension="customer", operation="ranking",
            coverage=Coverage(
                type="complete_population" if data.get("total", 0) <= len(rows) else "top_n",
                requested=plan.get("limit"),
                returned=len(rows),
                population_complete=data.get("total", 0) <= len(rows),
                population_size=data.get("total"),
                denominator_available=True,
            ),
            freshness=Freshness(queried_at=datetime.now(tz=LOCAL_TZ)),
            authority="metric_engine",
            filters={"year": scope.year, "limit": plan.get("limit")},
            payload=TypedAnalysisResult(result_type="ranking", rows=rows, execution_ref=f"exec_{result_id}"),
        )
        built = RankingFactBuilder().build(envelope)
        contract = ranking_answer_contract()
    elif analysis_type == "metric_snapshot":
        revenue = Decimal(str(data.get("revenue") or 0))
        envelope = EvidenceEnvelope(
            result_id=result_id,
            metric=MetricRef(metric_id="finance.sales_snapshot", definition_version="1.0.0"),
            scope=scope, dimension="", operation="metric_snapshot",
            coverage=Coverage(type="complete_population", population_complete=True,
                              population_size=1, denominator_available=revenue > 0),
            freshness=Freshness(queried_at=datetime.now(tz=LOCAL_TZ)),
            authority="metric_engine",
            filters={"year": scope.year, "month": scope.month},
            payload=TypedAnalysisResult(
                result_type="metric_snapshot",
                snapshot_value=SnapshotValue(value=revenue, unit="CNY"),
                execution_ref=f"exec_{result_id}",
            ),
        )
        built = SnapshotFactBuilder().build(envelope)
        contract = snapshot_answer_contract()
    else:
        return {"failure": Failure(
            reason_code="UNSUPPORTED_ANALYSIS_TYPE", action="clarify", stage="evidence_validate",
        )}

    if built.status != "verified":
        return {"failure": Failure(
            reason_code=built.reason_code or "EVIDENCE_FAILED", action="fail_closed",
            stage="evidence_validate", evidence_refs=built.evidence_refs,
        )}

    assertions = AssertionBuilder().build(envelope=envelope, facts=built.facts, calculations=[])
    verdicts = StructuralValidator().validate(
        assertions, facts=built.facts, calculations=[], envelope=envelope, contract=contract,
    )
    verified = [a for a, v in zip(assertions, verdicts) if v.status == "verified"]
    for result in ContractChecker().check(verified, contract):
        if result.status != "verified":
            return {"failure": Failure(
                reason_code=result.reason_code, action="fail_closed", stage="evidence_validate",
            )}

    return {
        "_validated": {
            "envelope": envelope, "facts": built.facts, "verified_assertions": verified,
        }
    }


# ---------------------------------------------------------------------------
# 节点 6: controlled_render —— 模板化响应
# ---------------------------------------------------------------------------


def controlled_render(state: ConversationState) -> dict[str, Any]:
    """把验证产物渲染为 Presentation + TrustMetrics + ExecutionResult
    （确定性 Formatter；受限 LLM 生成简短受控文案留待后续）。"""
    from app.runtime.metrics import collect_trust_metrics
    from app.runtime.renderer import DeterministicRenderer

    validated = state.get("_validated")
    if validated is None:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="render",
        )}

    envelope = validated["envelope"]
    facts = validated["facts"]
    verified = validated["verified_assertions"]
    renderer = DeterministicRenderer()

    table = renderer.render_table(verified, facts=facts, envelope=envelope)
    title = _presentation_title(envelope)
    presentation: Presentation = {
        "type": "table", "title": title, "columns": table.columns, "rows": table.rows,
    }
    reply = renderer.render_summary(verified, facts=facts, envelope=envelope)
    trust = collect_trust_metrics(
        assertions=verified, verified_ids=[a.assertion_id for a in verified],
        sentences=[], facts=facts,
    )
    return {
        "execution_result": ExecutionResult(
            result_ids=[envelope.result_id], assertion_count=len(verified),
            verified_count=len(verified),
            payload={"reply": reply, "facts": _facts_for_evidence(facts)},
        ),
        "presentation": presentation,
        "trust_metrics": TrustMetrics(
            unsupported_claim_escape_rate=trust.unsupported_claim_escape_rate,
            evidence_sufficiency_rate=trust.evidence_sufficiency_rate,
            claim_precision=trust.claim_precision,
            total_assertions=trust.total_assertions,
            verified_assertions=trust.verified_assertions,
        ),
    }


def _facts_for_evidence(facts: list[Any]) -> list[str]:
    """把 Fact 折叠为 evidence facts（供 guardrail 校验数字可追溯性）。"""
    out: list[str] = []
    for fact in facts:
        dims = "、".join(f"{k}={v}" for k, v in (fact.dimensions or {}).items())
        label = fact.name or "数值"
        scope = fact.scope
        period = f"{scope.year}年" + (f"{scope.month}月" if scope.month else "") if scope.year else ""
        out.append(f"{label} {fact.value} {fact.unit}（{period}{('; ' + dims) if dims else ''}）".rstrip("（"))
    return out[:20]


def _presentation_title(envelope: Any) -> str:
    scope = envelope.scope
    if envelope.operation == "metric_snapshot":
        return f"{scope.year} 年" + (f" {scope.month} 月" if scope.month else "") + "销售额"
    return f"{scope.year} 年客户销售额排行" if scope.year else "客户销售额排行"


# ---------------------------------------------------------------------------
# 组装：六节点串联为一个分支函数（挂到 ConversationRuntime）
# ---------------------------------------------------------------------------


def fast_path_branch(state: ConversationState) -> dict[str, Any]:
    """ConversationRuntime 的 fast_path 分支实现：六节点顺序执行。

    每节点失败即返回 Failure（显式 reason_code + action），不落到宽泛
    except。成功则返回 presentation / trust_metrics / execution_result
    （LangGraph 用节点返回值 merge state，原地修改不持久化）。

    注：semantic_compile / inheritance_resolve 已在图的 compile 节点执行
    （compile 在 route 之前）；本分支若 plan 已就绪则跳过前两步，避免重复
    LLM 调用（模型调用次数保持 ≤2 上限）。
    """
    carried: dict[str, Any] = {}

    def run_node(node, s):
        nonlocal carried
        result = node(s)
        if isinstance(result, dict) and "failure" in result:
            return result
        carried.update(result)
        s.update(carried)
        return None

    plan = state.get("current_plan") or state.get("semantic_plan")
    nodes = (
        (semantic_compile, inheritance_resolve, plan_validate,
         deterministic_executor, evidence_validate, controlled_render)
        if plan is None
        else (plan_validate, deterministic_executor, evidence_validate, controlled_render)
    )
    for node in nodes:
        failure = run_node(node, state)
        if failure is not None:
            return failure
    # 只返回需要 merge 的业务字段（LangGraph 不保留节点内原地修改）
    return {
        key: carried[key]
        for key in ("execution_result", "presentation", "trust_metrics", "failure")
        if key in carried
    }
