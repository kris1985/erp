"""Deterministic Renderer + Formatter tests (PR #5, contracts §P1.3).

Acceptance: every business sentence binds to its assertions; number display is
a replayable deterministic transform (12350000 CNY -> "1,235 万元"), never an
LLM paraphrase; the renderer consumes verified assertions only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.runtime.assertions import AssertionBuilder
from app.runtime.calculation import CalculationEngine
from app.runtime.contracts import (
    Coverage,
    EvidenceEnvelope,
    Fact,
    Freshness,
    MetricRef,
    TimeScope,
    ranking_answer_contract,
)
from app.runtime.fact_builder import RankingFactBuilder
from app.runtime.renderer import (
    DeterministicRenderer,
    RenderedTable,
    format_money,
    format_percent,
)
from app.runtime.structural_validator import StructuralValidator

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
METRIC = MetricRef(metric_id="finance.customer_sales_ranking", definition_version="1.0.0")
SCOPE = TimeScope(year=2026)
RENDERER = DeterministicRenderer()
CONTRACT = ranking_answer_contract()
STRUCTURAL = StructuralValidator()


def make_envelope(rows: list[dict] | None = None) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        result_id="r_007",
        metric=METRIC,
        scope=SCOPE,
        dimension="customer",
        operation="ranking",
        coverage=Coverage(
            type="complete_population",
            requested=4,
            returned=4,
            population_complete=True,
            population_size=4,
            denominator_available=True,
        ),
        freshness=Freshness(queried_at=AS_OF),
        payload={
            "result_type": "ranking",
            "rows": rows
            or [
                {"entity_id": "customer:A", "entity_label": "客户 A", "value": "12350000", "unit": "CNY", "rank": 1},
                {"entity_id": "customer:B", "entity_label": "客户 B", "value": "9800000", "unit": "CNY", "rank": 2},
                {"entity_id": "customer:C", "entity_label": "客户 C", "value": "7600000", "unit": "CNY", "rank": 3},
                {"entity_id": "customer:D", "entity_label": "客户 D", "value": "4500000", "unit": "CNY", "rank": 4},
            ],
            "execution_ref": "metric_exec_9307",
        },
    )


def verified_assertions(env: EvidenceEnvelope) -> list:
    built = RankingFactBuilder().build(env)
    engine = CalculationEngine()
    top2 = built.facts[:2]
    total = Fact(
        fact_id="f_total_sales",
        type="metric_fact",
        name="客户销售额",
        value=Decimal("34250000"),
        unit="CNY",
        scope=SCOPE,
        evidence_refs=["r_007_total"],
    )
    _, top2_fact = engine.compute(
        "topn_total", top2, calculation_id="c_top2_total", output_fact_id="c_top2_total"
    )
    calc, share_fact = engine.compute(
        "share_of_total",
        [top2_fact, total],
        calculation_id="c_top2_share",
        output_fact_id="c_top2_share",
    )
    facts = built.facts + [top2_fact, share_fact, total]
    assertions = AssertionBuilder().build(envelope=env, facts=facts, calculations=[calc])
    verdicts = STRUCTURAL.validate(
        assertions, facts=facts, calculations=[calc], envelope=env, contract=CONTRACT
    )
    verified = [a for a, v in zip(assertions, verdicts) if v.status == "verified"]
    return verified, facts, [calc]


# --------------------------------------------------------------------------
# Formatters
# --------------------------------------------------------------------------


def test_format_money_wan_and_yuan() -> None:
    assert format_money(Decimal("12350000")) == "1,235 万元"
    assert format_money(Decimal("9800000")) == "980 万元"
    assert format_money(Decimal("5000000")) == "500 万元"
    assert format_money(Decimal("7890")) == "7,890 元"
    assert format_money(Decimal("12350000"), unit="USD") == "12,350,000 USD"


def test_format_percent_from_canonical_ratio() -> None:
    assert format_percent(Decimal("0.646715328467")) == "64.7%"
    assert format_percent(Decimal("0.9")) == "90.0%"
    assert format_percent(Decimal("0.7996")) == "80.0%"  # display only


def test_money_transform_is_replayable() -> None:
    assert format_money(Decimal("12350000")) == format_money(Decimal("12350000"))
    dumped = [format_money(Decimal(v)) for v in ("12350000", "9800000", "7600000")]
    assert dumped == ["1,235 万元", "980 万元", "760 万元"]


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------


def test_render_sentences_with_binding() -> None:
    env = make_envelope()
    verified, facts, calcs = verified_assertions(env)
    sentences = RENDERER.render_sentences(verified, facts=facts, envelope=env)
    assert [s.text for s in sentences] == [
        "客户 A 销售额 1,235 万元，排名第 1。",
        "客户 B 销售额 980 万元，排名第 2。",
        "客户 C 销售额 760 万元，排名第 3。",
        "客户 D 销售额 450 万元，排名第 4。",
        "前 2 名客户合计占总销售额 64.7%。",
    ]
    first = sentences[0]
    assert first.assertion_refs == ["a_value_customer:A", "a_rank_customer:A"]
    share = sentences[-1]
    assert share.assertion_refs == ["a_share"]


def test_render_entity_label_single_sentence() -> None:
    env = make_envelope()
    verified, facts, _ = verified_assertions(env)
    sentences = RENDERER.render_sentences(
        verified, facts=facts, envelope=env, entity_label="厦门海丝"
    )
    # no row labelled 厦门海丝 -> nothing for it; use a real label instead
    sentences = RENDERER.render_sentences(
        verified, facts=facts, envelope=env, entity_label="客户 B"
    )
    assert len(sentences) == 1
    assert sentences[0].text == "客户 B 销售额 980 万元，排名第 2。"


def test_render_table() -> None:
    env = make_envelope()
    verified, facts, _ = verified_assertions(env)
    table = RENDERER.render_table(verified, facts=facts, envelope=env)
    assert isinstance(table, RenderedTable)
    assert table.columns == ["排名", "客户", "销售额"]
    assert table.rows == [
        ["1", "客户 A", "1,235 万元"],
        ["2", "客户 B", "980 万元"],
        ["3", "客户 C", "760 万元"],
        ["4", "客户 D", "450 万元"],
    ]
    assert table.assertion_refs == ["a_rank_customer:A", "a_rank_customer:B", "a_rank_customer:C", "a_rank_customer:D"]


def test_render_dispatches_on_presentation_mode() -> None:
    env = make_envelope()
    verified, facts, _ = verified_assertions(env)
    out = RENDERER.render(
        verified, facts=facts, envelope=env, contract=ranking_answer_contract(presentation_mode="table")
    )
    assert isinstance(out, RenderedTable)
    out2 = RENDERER.render(
        verified, facts=facts, envelope=env, contract=ranking_answer_contract(presentation_mode="sentence")
    )
    assert isinstance(out2, list)


def test_render_is_deterministic() -> None:
    env = make_envelope()
    v1, f1, _ = verified_assertions(env)
    v2, f2, _ = verified_assertions(env)
    assert RENDERER.render_sentences(v1, facts=f1, envelope=env) == RENDERER.render_sentences(
        v2, facts=f2, envelope=env
    )


# --------------------------------------------------------------------------
# Summary + trace (Fast Path 主回复与折叠溯源)
# --------------------------------------------------------------------------


def test_render_summary_one_sentence() -> None:
    env = make_envelope()
    verified, facts, calcs = verified_assertions(env)
    summary = RENDERER.render_summary(verified, facts=facts, envelope=env)
    assert summary.startswith("2026 年客户销售额排行：客户 A居首（销售额 1,235 万元）。")
    assert "前 2 名客户合计占总销售额 64.7%。" in summary
    assert "\n" not in summary  # 一句结论


def test_render_summary_with_judgement() -> None:
    env = make_envelope()
    verified, facts, _ = verified_assertions(env)
    # 附加集中度判断（手工构造 rule_supported judgement）
    from app.runtime.contracts import Assertion, AssertionSubject

    judgement = Assertion(
        assertion_id="a_concentration",
        type="judgement",
        predicate="classification",
        claim_strength="rule_supported",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={"classification": "客户集中度较高"},
        fact_refs=["c_top2_share"],
        rule_ref="customer_concentration.high@1.0.0",
        evidence_refs=["r_007"],
    )
    summary = RENDERER.render_summary(verified + [judgement], facts=facts, envelope=env)
    assert summary.endswith("客户集中度较高。")


def test_render_explanation_user_facing_chinese() -> None:
    """折叠区 = 中文依据说明，不含内部标识符（assertion/fact id 等）。"""
    env = make_envelope()
    verified, facts, calcs = verified_assertions(env)
    explanation = RENDERER.render_explanation(
        verified, facts=facts, calculations=calcs, envelope=env,
        rules={"customer_concentration.high@1.0.0": ("客户集中度较高", "0.80")},
    )
    assert "数据来源：客户销售额排行（2026 年，完整总体 4 户）" in explanation
    assert "计算方式：前 2 名客户合计 2,215 万元 ÷ 总体销售额 3,425 万元 = 64.7%" in explanation
    assert "查询时间" in explanation
    # 不暴露内部标识符
    for internal in ("Fact `", "Evidence `", "coverage=", "definition_version", "deterministic"):
        assert internal not in explanation


def test_render_explanation_includes_rule_basis() -> None:
    env = make_envelope()
    verified, facts, _ = verified_assertions(env)
    from app.runtime.contracts import Assertion, AssertionSubject

    judgement = Assertion(
        assertion_id="a_concentration",
        type="judgement",
        predicate="classification",
        claim_strength="rule_supported",
        subject=AssertionSubject(metric=METRIC, scope=SCOPE),
        object={"classification": "客户集中度较高"},
        fact_refs=["c_top2_share"],
        rule_ref="customer_concentration.high@1.0.0",
        evidence_refs=["r_007"],
    )
    explanation = RENDERER.render_explanation(
        verified + [judgement], facts=facts, calculations=[],
        envelope=env,
        rules={"customer_concentration.high@1.0.0": ("客户集中度较高", "0.80")},
    )
    assert "判断依据：前 2 名客户占比 64.7%，达到阈值 0.80，判定「客户集中度较高」（业务规则 customer_concentration.high@1.0.0）" in explanation
