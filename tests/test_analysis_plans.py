from datetime import date

from app.services.analysis_plans import (
    SemanticPlan,
    TimeRange,
    match_execution_plan,
    parse_planner_json,
    plan_question,
    plan_finance_question,
    resolve_execution_plan,
    validate_semantic_plan,
)
import pytest


def test_profit_snapshot_plan_resolves_to_one_verified_query():
    plan = plan_finance_question("本月利润概况：收入、成本、毛利各多少？", today=date(2026, 8, 15))
    assert plan is not None
    assert plan.analysis_type == "metric_snapshot"
    execution = resolve_execution_plan(plan)
    assert execution.execution_plan_id.startswith("ep_")
    assert execution.steps[0].metric_id == "finance.profit_report"
    assert execution.steps[0].params == {"year": 2026, "month": 8}
    assert match_execution_plan(plan, execution) is True


def test_profit_mom_plan_keeps_the_two_periods_in_execution():
    plan = plan_finance_question("本月毛利环比多少？", today=date(2026, 8, 15))
    assert plan is not None
    assert plan.analysis_type == "period_comparison"
    execution = resolve_execution_plan(plan)
    assert [step.params for step in execution.steps] == [
        {"year": 2026, "month": 8}, {"year": 2026, "month": 7},
    ]
    assert match_execution_plan(plan, execution) is True


def test_registry_rejects_ranking_without_required_slots():
    plan = SemanticPlan(
        analysis_type="ranking", metric="sales_amount", time_range=TimeRange(year=2026)
    )
    assert validate_semantic_plan(plan) == ["dimension", "order", "limit"]


def test_customer_sales_ranking_plan_preserves_year_order_and_limit():
    plan = plan_finance_question("2026年销售额最高的 10 个客户", today=date(2026, 8, 15))
    assert plan is not None
    assert plan.analysis_type == "ranking"
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "finance.customer_sales_ranking"
    assert execution.steps[0].params == {"year": 2026, "order": "desc", "limit": 10}
    assert match_execution_plan(plan, execution) is True


def test_highest_customer_question_defaults_to_limit_one():
    """「哪个客户销售额最X」最高级语义统一识别（Case 3 语义）：
    - 正向最高级（最高/最大/最多/最好…）→ limit=1 + desc
    - 反向最高级（最低/最少/最小/最差…）→ limit=1 + asc
    不得回落到默认 10（否则会把全部客户当排行返回）。
    覆盖词表，禁止只对个别词打补丁。"""
    high_cases = (
        "今年哪个客户销售额最高？",
        "哪个客户销售额最大",
        "哪个客户销售额最多",
        "哪个客户销售额最好",
        "哪个客户销售额排第一",
        "本月哪个客户销售额最大",
    )
    low_cases = (
        "哪个客户销售额最低",
        "哪个客户销售额最少",
        "哪个客户销售额最小",
        "哪个客户销售额最差",
    )
    for question in high_cases:
        plan = plan_finance_question(question, today=date(2026, 8, 17))
        assert plan is not None, question
        assert plan.analysis_type == "ranking", question
        assert plan.limit == 1, f"{question}: limit={plan.limit}"
        assert plan.order == "desc", f"{question}: order={plan.order}"
    for question in low_cases:
        plan = plan_finance_question(question, today=date(2026, 8, 17))
        assert plan is not None, question
        assert plan.analysis_type == "ranking", question
        assert plan.limit == 1, f"{question}: limit={plan.limit}"
        assert plan.order == "asc", f"{question}: order={plan.order}"


def test_superlative_does_not_steal_snapshot_or_ranked_n():
    """最高级识别不得误伤其它分支：显式 N 排行、占比、快照保持原语义。"""
    assert plan_finance_question("今年客户销售额前 3 名", today=date(2026, 8, 17)).limit == 3
    assert plan_finance_question("销售额最高的 10 个客户", today=date(2026, 8, 17)).limit == 10
    assert plan_finance_question("最高的 10 个客户", today=date(2026, 8, 17)).limit == 10
    assert plan_finance_question("前两名客户占多少", today=date(2026, 8, 17)).limit == 2
    snapshot = plan_finance_question("本月销售额多少", today=date(2026, 8, 17))
    assert snapshot.analysis_type == "metric_snapshot"
    # 「本月哪个客户销售额最大」是排行不是快照
    assert plan_finance_question("本月哪个客户销售额最大", today=date(2026, 8, 17)).analysis_type == "ranking"
    # 非销售域最高级（收入）不进销售排行
    assert plan_finance_question("哪个客户收入最多", today=date(2026, 8, 17)) is None
    # 无上下文最高级（没有客户/销售额/销售）是歧义，v1 不猜测
    assert plan_finance_question("最大的 2 笔", today=date(2026, 8, 17)) is None


def test_superlative_with_explicit_n_limit_and_order():
    """「最大的2笔/销售额最小的3个」：最高级 + 显式 N（数字/中文数字）+ 量词
    → limit=N；反向最高级 → asc。覆盖「的」字与量词（笔/单/个/户/名）。"""
    cases = [
        ("最大的2笔客户销售额", 2, "desc"),
        ("销售额最大的2笔", 2, "desc"),
        ("客户销售额最大的两笔", 2, "desc"),
        ("销售额最大的两个客户", 2, "desc"),
        ("最大的3笔销售", 3, "desc"),
        ("今年销售额最大的5个客户", 5, "desc"),
        ("最小的2笔客户销售额", 2, "asc"),
        ("销售额最小的3个客户", 3, "asc"),
        ("前2大客户", 2, "desc"),
        ("前 3 名客户", 3, "desc"),
    ]
    for question, expected_limit, expected_order in cases:
        plan = plan_finance_question(question, today=date(2026, 8, 17))
        assert plan is not None, question
        assert plan.analysis_type == "ranking", question
        assert plan.limit == expected_limit, f"{question}: limit={plan.limit}"
        assert plan.order == expected_order, f"{question}: order={plan.order}"


def test_gross_profit_trend_plan_is_month_grain_and_bounded():
    plan = plan_finance_question("看近 12 个月毛利趋势", today=date(2026, 8, 15))
    assert plan is not None
    assert plan.analysis_type == "time_series"
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "finance.gross_profit_time_series"
    assert execution.steps[0].params == {"year": 2026, "month": 8, "months": 12, "granularity": "month"}
    assert match_execution_plan(plan, execution) is True


def test_delivery_risk_exception_list_has_all_governed_slots():
    plan = plan_finance_question("列出交期风险订单前 5", today=date(2026, 8, 15))
    assert plan is not None
    assert plan.analysis_type == "exception_list"
    assert (plan.entity, plan.risk_condition, plan.order, plan.limit) == ("order", "delivery_risk", "asc", 5)
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "analytics.delivery_risk"
    assert execution.steps[0].params == {"limit": 5}
    assert match_execution_plan(plan, execution) is True


def test_constrained_planner_json_rejects_unknown_keys_and_unregistered_metrics():
    with pytest.raises(ValueError, match="invalid_semantic_plan_json"):
        parse_planner_json({"analysis_type": "metric_snapshot", "metric": "profit_overview", "surprise": True})
    with pytest.raises(ValueError, match="unregistered_semantic_metric"):
        parse_planner_json({"analysis_type": "metric_snapshot", "metric": "not_registered"})
    output = parse_planner_json({"analysis_type": "metric_snapshot", "metric": "profit_overview"})
    assert output.plan is not None
    assert output.missing_slots == ["time_range"]
    assert output.semantic_plan_id.startswith("sp_")


def test_order_payment_without_order_number_returns_missing_slot_without_plan():
    output = plan_question("按单号查回款", today=date(2026, 8, 15))
    assert output.plan is None
    assert output.missing_slots == ["order_no"]


def test_model_planner_output_is_revalidated_against_registry(monkeypatch):
    from app.services import schedule_agent

    class FakeStructured:
        def invoke(self, _messages):
            return {"analysis_type": "metric_snapshot", "metric": "not_registered"}

    class FakeModel:
        def with_structured_output(self, _schema):
            return FakeStructured()

    monkeypatch.setattr(schedule_agent, "_make_model", lambda: FakeModel())
    output = schedule_agent._plan_semantic_question("本月利润多少")
    # Invalid model JSON falls back to the registered deterministic plan.
    assert output.plan is not None
    assert output.plan.metric == "profit_overview"


def test_cost_composition_resolves_to_a_single_profit_report():
    plan = plan_finance_question("本月成本构成和占比", today=date(2026, 8, 15))
    assert plan is not None and plan.analysis_type == "composition"
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "finance.profit_report"
    assert execution.steps[0].params == {"year": 2026, "month": 8}
    assert match_execution_plan(plan, execution)


def test_profit_detail_table_requires_explicit_table_request():
    assert plan_finance_question("本月利润多少", today=date(2026, 8, 15)).analysis_type != "data_table"
    plan = plan_finance_question("本月利润订单明细前 5", today=date(2026, 8, 15))
    assert plan is not None and plan.analysis_type == "data_table"
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].params == {"year": 2026, "month": 8, "limit": 5}
    assert match_execution_plan(plan, execution)


def test_scenario_without_base_facts_and_assumptions_is_blocked_for_clarification():
    output = plan_question("插单会影响交期吗？", today=date(2026, 8, 15))
    assert output.plan is not None and output.plan.analysis_type == "scenario"
    assert output.missing_slots == ["base_facts", "assumptions", "calculation_method", "comparison_target"]


def test_complete_order_intake_scenario_resolves_only_with_explicit_facts_and_assumptions():
    plan = SemanticPlan(
        analysis_type="scenario", metric="order_intake_scenario",
        base_facts={"lines": [{"own_product_id": 1, "qty": 100}]},
        assumptions={"default_daily_capacity": 500, "is_rush": True},
        calculation_method="order_intake_simulation", comparison_target="existing_schedule",
    )
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "analytics.order_intake"
    assert execution.steps[0].params == {
        "lines": [{"own_product_id": 1, "qty": 100}], "default_daily_capacity": 500, "is_rush": True,
    }
    assert match_execution_plan(plan, execution)


def test_profit_attribution_resolves_to_the_verified_profit_report():
    plan = plan_finance_question("本月毛利主要由哪些订单贡献？", today=date(2026, 8, 15))
    assert plan is not None and plan.analysis_type == "attribution_analysis"
    execution = resolve_execution_plan(plan)
    assert execution.steps[0].metric_id == "finance.profit_report"
    assert match_execution_plan(plan, execution)
