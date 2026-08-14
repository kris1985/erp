"""回复出站 Evidence Guardrail 的确定性回归。"""

import json

from app.services.schedule_agent import (
    _auto_diagnostic_metric_ids,
    _stream_safe_reply,
    apply_evidence_guardrail,
    build_evidence_ledger,
    build_decision_summary,
    build_response_presentation,
    select_response_charts,
    validate_evidence_guardrail,
)


def test_cashflow_question_gets_a_readonly_diagnostic_bundle(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent.workshop_metrics,
        "list_metrics",
        lambda **_kwargs: [
            {"id": "finance.payments_this_month"},
            {"id": "finance.receivables_open"},
            {"id": "finance.business_kpi"},
            {"id": "finance.profit_report"},
        ],
    )
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("本月回款只有 1 笔，现金流是否有风险？") == [
        "finance.payments_this_month",
        "finance.receivables_open",
        "finance.business_kpi",
    ]


def test_profit_question_prioritises_profit_data_over_cashflow(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent.workshop_metrics,
        "list_metrics",
        lambda **_kwargs: [
            {"id": "finance.payments_this_month"},
            {"id": "finance.receivables_open"},
            {"id": "finance.profit_report"},
            {"id": "finance.business_kpi"},
        ],
    )
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("本月利润概况：收入、成本、毛利各多少？") == [
        "finance.profit_report",
        "finance.business_kpi",
    ]


def test_profit_number_question_is_answered_with_numbers_only(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent, "_make_model", lambda: (_ for _ in ()).throw(RuntimeError()))
    summary = build_decision_summary(
        "本月利润概况：收入、成本、毛利各多少？",
        "毛利主要来自若干订单。",
        [{
            "source": "利润报表",
            "facts": ["收入：9398", "材料成本：407.8", "人工成本：500", "其它成本：114.2", "成本合计：1022", "毛利：8376"],
        }],
    )
    assert summary.decision == "本月收入 9398 元，成本 1022 元，毛利 8376 元。"
    assert summary.reason == ""
    assert summary.facts == []


def test_profit_number_question_gets_a_verified_metric_snapshot():
    presentation = build_response_presentation(
        "本月利润概况：收入、成本、毛利各多少？",
        [{"source": "利润报表", "facts": ["收入：9398", "成本合计：1021.5", "毛利：8376.5"]}],
    )
    assert presentation == {
        "type": "metric_snapshot",
        "title": "本月利润概况",
        "items": [
            {"label": "收入", "value": "9398", "unit": "元"},
            {"label": "成本", "value": "1021.5", "unit": "元"},
            {"label": "毛利", "value": "8376.5", "unit": "元"},
        ],
    }


def test_profit_period_question_gets_a_verified_comparison():
    presentation = build_response_presentation(
        "本月毛利环比多少？",
        [
            {"source": "利润报表", "filters": {"year": 2026, "month": 8}, "facts": ["毛利：8376.5"]},
            {"source": "利润报表", "filters": {"year": 2026, "month": 7}, "facts": ["毛利：7000"]},
        ],
    )
    assert presentation == {
        "type": "period_comparison", "title": "毛利环比", "label": "毛利",
        "current": {"label": "2026年8月", "value": "8376.5", "unit": "元"},
        "previous": {"label": "2026年7月", "value": "7000", "unit": "元"},
        "delta": "1376.5", "rate": "19.7",
    }


def test_customer_sales_ranking_gets_a_ranked_presentation():
    presentation = build_response_presentation(
        "2026年销售额最高的 2 个客户",
        [{"source": "客户销售额排行", "facts": ["客户：客户A", "销售额：1000", "客户：客户B", "销售额：800"]}],
    )
    assert presentation == {
        "type": "ranking", "title": "客户销售额排行",
        "items": [{"label": "客户A", "value": "1000", "unit": "元"}, {"label": "客户B", "value": "800", "unit": "元"}],
    }


def test_profit_trend_selects_only_the_trend_metric(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent.workshop_metrics,
        "list_metrics",
        lambda **_kwargs: [{"id": "finance.gross_profit_time_series"}, {"id": "finance.profit_report"}],
    )
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("看近 12 个月毛利趋势") == ["finance.gross_profit_time_series"]


def test_delivery_risk_list_selects_the_exception_metric(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent.workshop_metrics, "list_metrics",
        lambda **_kwargs: [{"id": "analytics.delivery_risk"}],
    )
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("列出交期风险订单前 5") == ["analytics.delivery_risk"]


def test_cost_composition_selects_only_the_profit_report(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent.workshop_metrics, "list_metrics", lambda **_kwargs: [
        {"id": "finance.profit_report"}, {"id": "finance.business_kpi"},
    ])
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("本月成本构成和占比") == ["finance.profit_report"]


def test_order_level_payment_question_without_order_number_is_not_guessed(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent.workshop_metrics,
        "list_metrics",
        lambda **_kwargs: [{"id": "finance.payments_this_month"}],
    )
    monkeypatch.setattr(schedule_agent.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)

    assert _auto_diagnostic_metric_ids("请按单号查询回款") == []


def test_high_risk_reply_requires_a_tool_result():
    reply, verdict = apply_evidence_guardrail("订单 260701 进度怎么样？", "订单已完成 80%。", [])
    assert verdict["passed"] is False
    assert verdict["reason"] == "missing_tool_evidence"
    assert "暂不能确认" in reply


def test_rejects_measurable_claim_missing_from_evidence():
    verdict = validate_evidence_guardrail(
        "交期风险如何？",
        "订单 260701 完成 80%，交期是 2026-08-20。",
        ['{"order_no":"260701","overall_percent":65,"delivery_date":"2026-08-19"}'],
    )
    assert verdict["passed"] is False
    assert "80%" in verdict["unmatched"]


def test_removes_only_unsupported_line_when_other_answer_is_grounded():
    reply, verdict = apply_evidence_guardrail(
        "交期风险如何？",
        "订单 260701 完成 65%。\n订单 260702 完成 80%。",
        [{"name": "query_metric", "content": '{"order_no":"260701","overall_percent":65}'}],
    )
    assert verdict["action"] == "removed_unsupported_lines"
    assert reply == "订单 260701 完成 65%。"


def test_allows_tool_supported_measurable_claims():
    verdict = validate_evidence_guardrail(
        "交期风险如何？",
        "订单 260701 完成 65%，交期为 2026-08-19。",
        ['{"order_no":"260701","overall_percent":65,"delivery_date":"2026-08-19"}'],
    )
    assert verdict["passed"] is True


def test_allows_tool_supported_data_capability_boundary_without_generic_fallback():
    reply = "当前可用问数指标未提供按单号查询回款的独立指标；本月回款仅按年月汇总。"
    verdict = validate_evidence_guardrail(
        "按单号查询回款", reply, ['{"metric_id":"finance.monthly_receipts","data":[]}']
    )
    assert verdict["passed"] is True
    assert verdict["reason"] == "tool_supported_capability_boundary"


def test_capability_boundary_summary_stays_actionable_without_hallucinating():
    raw = "本月回款按年月汇总，未提供按单号查询回款的独立指标。未结应收可按客户+单号查询。"
    summary = build_decision_summary("按单号查询回款", raw, [])
    assert summary.decision == "当前无法按单号直接查询回款流水"
    assert summary.actions[0].type == "await_input"


def test_allows_safe_uncertainty_reply_without_evidence():
    verdict = validate_evidence_guardrail("缺料有风险吗？", "当前账号无权限查询，暂不能确认。", [])
    assert verdict["passed"] is True


def test_evidence_ledger_returns_safe_metric_scope_and_facts():
    cards = build_evidence_ledger(
        [{
            "name": "query_metric",
            "content": (
                '{"metric_id":"production.order_progress","data":{"as_of":"2026-08-15",'
                '"order_no":"260701","overall_percent":60,"processes":[{"process_name":"针车","qty":600}]},'
                '"_result":{"result_id":"r_internal","metric_id":"production.order_progress"},'
                '"_evidence":{"metric_id":"production.order_progress","filters":{"order_no":"260701"},'
                '"queried_at":"2026-08-15T10:00:00"}}'
            ),
        }],
        permission_codes=["menu.orders"],
    )
    assert len(cards) == 1
    assert cards[0]["status"] == "已核验"
    assert "订单：260701" in cards[0]["facts"]
    assert cards[0]["filters"] == {"order_no": "260701"}
    assert "result_id" not in cards[0]


def test_verified_reply_is_delivered_in_small_safe_chunks():
    assert list(_stream_safe_reply("已核验的业务结论", width=3)) == ["已核验", "的业务", "结论"]


def test_summary_fallback_never_uses_agent_work_draft(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent, "_make_model", lambda: (_ for _ in ()).throw(RuntimeError()))
    raw = "我先查工具。\n关键事实：\n- 进度 22%\n裁决：不建议硬插，仍会逾期。\n解释为何：产能已经超载。"
    summary = build_decision_summary("能不能插单", raw, [])
    assert summary.decision == "不建议硬插，仍会逾期。"
    assert "我先查" not in summary.decision


def test_suggested_actions_use_business_types_instead_of_always_following_up(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent, "_make_model", lambda: (_ for _ in ()).throw(RuntimeError()))
    raw = (
        "关键事实：\n- 缺料\n"
        "裁决：等待采购回填。\n解释为何：当前无到料日。\n"
        "- 采购线下联系供应商确认到料日\n"
        "- 回填系统采购单后重新计算齐套日\n"
        "- 等待供应商回复后再排产"
    )
    summary = build_decision_summary("下一步怎么办", raw, [])
    assert [action.type for action in summary.actions] == [
        "offline_task", "navigate_form", "await_input"
    ]
    assert summary.actions[1].target_path == "/admin/purchase?tab=orders"
    json.dumps([action.model_dump() for action in summary.actions], ensure_ascii=False)


def test_named_customer_confirmation_is_an_offline_task_not_an_ai_followup():
    from app.services.schedule_agent import _classify_action

    action = _classify_action("与厦门海丝确认后续回款节奏")
    assert action.type == "offline_task"
    assert action.owner_role == "业务"


def test_charts_are_opt_in_and_match_the_question():
    charts = [
        {"metric_id": "analytics.delivery_risk", "title": "在制进度"},
        {"metric_id": "analytics.capacity_load", "title": "产能负荷"},
    ]
    assert select_response_charts("260718 能不能优先保？", charts) == []
    assert select_response_charts("看一下产能负荷图", charts) == [charts[1]]
