"""Semantic Compiler 跨轮继承切片单元测试。

验证「LLM propose + 确定性校验」边界：
- 有 Fast Path 历史 + 合法 refine → inherited（limit/min_amount/period 正确组装）
- 无 Fast Path 历史 → not_applicable（即使 LLM 误判也不执行）
- LLM 判继承但无 refine 参数 → requires_clarification
- LLM propose 失败 → unavailable（不 fallback）
- period 切换（上月/去年）正确回绕
- 上轮信息来自结构化 presentation（不抠回复文本）
"""

from __future__ import annotations

import pytest

from app.services import semantic_compiler
from app.services.semantic_compiler import (
    InheritanceProposal,
    PreviousTurn,
    RefineSpec,
    resolve_inheritance,
)


def _mk_turn(
    *,
    question: str = "客户销售额排行",
    reply: str = "2026 年客户销售额排行：客户 A居首。",
    year: int = 2026,
    month: int | None = None,
    limit: int | None = 10,
) -> PreviousTurn:
    return PreviousTurn(
        question=question, reply=reply,
        analysis_type="ranking", year=year, month=month, limit=limit,
    )


def test_inherited_limit(monkeypatch, tmp_path) -> None:
    from app.services import schedule_agent

    conv_id = "c_inh_limit"
    schedule_agent._upsert_conversation(1, conv_id, title="t")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "客户销售额排行", "path": "fast_path"},
        {"role": "assistant", "content": "2026 年…居首。", "presentation": {"type": "table", "year": 2026, "limit": 10}, "path": "fast_path"},
    ])
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: InheritanceProposal(inherits=True, refine=RefineSpec(limit=3)),
    )
    try:
        verdict = resolve_inheritance("只显示top3", tenant_id=1, conversation_id=conv_id)
    finally:
        schedule_agent._catalog_conn.cache_clear()
    assert verdict.status == "inherited"
    assert verdict.limit == 3
    assert verdict.year == 2026


def test_inherited_min_amount(monkeypatch, tmp_path) -> None:
    from app.services import schedule_agent
    from decimal import Decimal

    conv_id = "c_inh_amount"
    schedule_agent._upsert_conversation(1, conv_id, title="t")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "客户销售额排行", "path": "fast_path"},
        {"role": "assistant", "content": "2026 年…居首。", "presentation": {"type": "table", "year": 2026, "limit": 10}, "path": "fast_path"},
    ])
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: InheritanceProposal(inherits=True, refine=RefineSpec(min_amount=5000000.0)),
    )
    try:
        verdict = resolve_inheritance("只要大于500万的", tenant_id=1, conversation_id=conv_id)
    finally:
        schedule_agent._catalog_conn.cache_clear()
    assert verdict.status == "inherited"
    assert verdict.min_amount == Decimal("5000000")


def test_inherited_period_last_month_wraps(monkeypatch, tmp_path) -> None:
    from app.services import schedule_agent

    conv_id = "c_inh_period"
    schedule_agent._upsert_conversation(1, conv_id, title="t")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "客户销售额排行", "path": "fast_path"},
        {"role": "assistant", "content": "2026 年…居首。", "presentation": {"type": "table", "year": 2026, "limit": 10}, "path": "fast_path"},
    ])
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: InheritanceProposal(inherits=True, refine=RefineSpec(period="last_year")),
    )
    try:
        verdict = resolve_inheritance("去年呢", tenant_id=1, conversation_id=conv_id)
    finally:
        schedule_agent._catalog_conn.cache_clear()
    assert verdict.status == "inherited"
    assert verdict.year == 2025
    assert verdict.month is None


def test_no_history_not_applicable_even_if_llm_says_inherit(monkeypatch, tmp_path) -> None:
    """无 Fast Path 历史：即使 LLM 误判 inherits=true 也拒绝（校验在代码里）。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "schedule_agent_data_dir", str(tmp_path))
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: InheritanceProposal(inherits=True, refine=RefineSpec(limit=3)),
    )
    verdict = resolve_inheritance("只显示top3", tenant_id=1, conversation_id="no_history")
    assert verdict.status == "not_applicable"
    assert verdict.reason_code == "NO_PREVIOUS_FAST_PATH_TURN"


def test_inherit_without_refine_requires_clarification(monkeypatch) -> None:
    monkeypatch.setattr(
        semantic_compiler,
        "_read_previous_fast_path_turn",
        lambda tenant_id, conversation_id: _mk_turn(),
    )
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: InheritanceProposal(inherits=True, refine=RefineSpec()),
    )
    verdict = resolve_inheritance("再分析一下", tenant_id=1, conversation_id="c")
    assert verdict.status == "requires_clarification"
    assert verdict.reason_code == "INHERIT_WITHOUT_REFINE"


def test_llm_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        semantic_compiler,
        "_read_previous_fast_path_turn",
        lambda tenant_id, conversation_id: _mk_turn(),
    )
    monkeypatch.setattr(
        semantic_compiler,
        "_propose_inheritance",
        lambda q, p: (_ for _ in ()).throw(RuntimeError("down")),
    )
    verdict = resolve_inheritance("只显示top3", tenant_id=1, conversation_id="c")
    assert verdict.status == "unavailable"
    assert verdict.reason_code == "INHERITANCE_LLM_UNAVAILABLE"


def test_propose_parses_json_from_model(monkeypatch) -> None:
    """回归：DeepSeek 不支持 with_structured_output(json_schema)（400），
    _propose_inheritance 必须走「提示词 JSON + 本地 pydantic 校验」。
    模型返回 JSON 文本 → 正确解析出 inherits/refine。"""
    class _Resp:
        content = '{"inherits": true, "refine": {"limit": 3}}'

    monkeypatch.setattr(
        semantic_compiler,
        "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    proposal = semantic_compiler._propose_inheritance(
        "只看top3", _mk_turn()
    )
    assert proposal.inherits is True
    assert proposal.refine.limit == 3


def test_propose_rejects_non_json(monkeypatch) -> None:
    """模型返回非 JSON → 抛错（resolve_inheritance 捕获为 unavailable）。"""
    class _Resp:
        content = "我不确定，这不是追问。"

    monkeypatch.setattr(
        semantic_compiler,
        "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    import pytest as _pytest

    with _pytest.raises(ValueError):
        semantic_compiler._propose_inheritance("随便说说", _mk_turn())


def test_propose_rejects_extra_keys(monkeypatch) -> None:
    """输出带多余字段 → pydantic 拒绝（extra=forbid，契约不变）。"""
    class _Resp:
        content = '{"inherits": true, "refine": {"limit": 3}, "hack": 1}'

    monkeypatch.setattr(
        semantic_compiler,
        "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    import pytest as _pytest

    with _pytest.raises(Exception):
        semantic_compiler._propose_inheritance("只看top3", _mk_turn())


def test_previous_turn_reads_structured_presentation(monkeypatch, tmp_path) -> None:
    """上轮信息从 ui_messages 的 assistant+fast_path 轮次读取；presentation
    提供 year/limit 等结构化字段（不再从回复文本抠年份）。"""
    from app.services import schedule_agent

    conv_id = "c_struct"
    schedule_agent._upsert_conversation(1, conv_id, title="t")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "客户销售额排行", "path": "fast_path"},
        {"role": "assistant",
         "content": "2026 年客户销售额排行：客户 A居首（销售额 1,235 万元）。",
         "presentation": {"year": 2026, "limit": 10},
         "path": "fast_path"},
    ])
    try:
        turn = semantic_compiler._read_previous_fast_path_turn(1, conv_id)
    finally:
        schedule_agent._catalog_conn.cache_clear()
    assert turn is not None
    assert turn.year == 2026
    assert turn.limit == 10
    assert turn.question == "客户销售额排行"
