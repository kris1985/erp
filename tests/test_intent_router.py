"""Intent Router 分层路由 + 本会话真实案例 golden 回归。

golden 集 = 产品侧"说法 → 期望意图"（对齐业界 golden-set evaluation）：
上线后真实日志反哺（补关键词/调阈值），任何路由层改动先跑本文件。
"""

from __future__ import annotations

import pytest

from app.runtime.intent_router import FollowUpResolver, IntentRouter, KeywordEmbedder
from app.services import schedule_agent as sa

ROUTER = IntentRouter()
RESOLVER = FollowUpResolver()


@pytest.fixture
def fake_conv_db(monkeypatch):
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations ("
        "id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL, title TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ui_messages TEXT)"
    )
    monkeypatch.setattr(sa, "_catalog_conn", lambda: conn)
    return conn


# ---------------------------------------------------------------- 分层路由单测

def test_rules_layer_beats_similarity():
    """rules 层（正则决策树）命中时优先，置信度最高。"""
    result = ROUTER.route(
        "客户销售额排行",
        rules_result="ranking",
        rules_metric_ids=["finance.customer_sales_ranking"],
    )
    assert result.layer == "rules"
    assert result.confidence == 1.0
    assert result.intent == "ranking"


def test_rules_hit_fails_keyword_verify_then_similarity():
    """正则命中但关键词互检不过（误命中）→ 降级 similarity。"""
    result = ROUTER.route(
        "销售额趋势",  # 不含回款/应收关键词
        rules_result="cashflow",
        rules_metric_ids=["finance.payments_this_month"],
    )
    # 互检不过 → 不走 rules；similarity 应路由到销售额趋势
    assert result.layer == "similarity"
    assert result.intent == "sales_trend"


def test_rules_verify_passes_when_keywords_match():
    result = ROUTER.route(
        "这个月回款和应收怎么样",
        rules_result="cashflow",
        rules_metric_ids=["finance.payments_this_month", "finance.receivables_open", "finance.business_kpi"],
    )
    assert result.layer == "rules"
    assert result.intent == "cashflow"


# ---------------------------------------------------------------- similarity 层

def test_similarity_routes_synonym_of_ranking():
    """同义说法（rules 认不出）→ similarity 层命中排行。"""
    result = ROUTER.similarity_route("哪个客户卖得最多")
    assert result.intent == "ranking"
    assert result.metric_ids == ["finance.customer_sales_ranking"]
    assert result.confidence >= 0.12


def test_similarity_routes_sales_trend():
    result = ROUTER.similarity_route("今年的销售走势怎么样")
    assert result.intent == "sales_trend"
    assert result.metric_ids == ["finance.sales_time_series"]


def test_similarity_fails_closed_on_vague_question():
    """模糊问题（无意图词）→ 不命中，不硬猜。"""
    result = ROUTER.similarity_route("随便看看")
    assert result.intent is None
    assert result.layer == "none"


def test_similarity_fails_closed_on_single_generic_hit():
    """只命中 1 个通用词（如"多少"）→ 不命中（MIN_HITS=2）。"""
    result = ROUTER.similarity_route("多少")
    assert result.intent is None


# ---------------------------------------------------------------- 混合问题

@pytest.mark.parametrize("question", [
    "这个月回款多少，顺便看下缺料情况",
    "客户销售额排行，还有利润概况",
    "哪个客户卖得最多，毛利多少",
    "看看今天的产量和明天的负荷",
])
def test_multi_intent_detected(question):
    assert ROUTER.detect_multi_intent(question) is True


def test_multi_intent_not_triggered_within_same_domain():
    """同一意图内部的并列（回款+应收同属 cashflow）不算混合。"""
    assert ROUTER.detect_multi_intent("本月回款和未结应收怎么样") is False


def test_multi_intent_skips_injection_in_schedule_agent(monkeypatch):
    """混合问题 → 注入为空（交 agent 拆解），不再吞意图。"""
    monkeypatch.setattr(
        sa.workshop_metrics, "list_metrics",
        lambda permission_codes=None: [{"id": "finance.payments_this_month"},
                                       {"id": "finance.receivables_open"},
                                       {"id": "finance.business_kpi"},
                                       {"id": "finance.customer_sales_ranking"}],
    )
    monkeypatch.setattr(sa.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)
    assert sa._auto_diagnostic_metric_ids("客户销售额排行，还有利润概况") == []


# ---------------------------------------------------------------- golden 集（本会话真实案例）

@pytest.mark.parametrize("question,expected_ids", [
    ("客户销售额排行", ["finance.customer_sales_ranking"]),
    ("这个月回款和应收怎么样", ["finance.payments_this_month", "finance.receivables_open", "finance.business_kpi"]),
    ("今年的销售额趋势怎么样", ["finance.sales_time_series"]),
    ("看近 12 个月毛利趋势", ["finance.gross_profit_time_series"]),
    ("本月利润概况：收入、成本、毛利各多少？", ["finance.profit_report", "finance.business_kpi"]),
])
def test_golden_question_to_metric_ids(monkeypatch, question, expected_ids):
    """golden 集：说法 → 注入指标（锁回归，防止路由层改动破坏）。"""
    ids = [m["id"] for m in [
        {"id": "finance.customer_sales_ranking"}, {"id": "finance.payments_this_month"},
        {"id": "finance.receivables_open"}, {"id": "finance.business_kpi"},
        {"id": "finance.sales_time_series"}, {"id": "finance.gross_profit_time_series"},
        {"id": "finance.profit_report"},
    ]]
    monkeypatch.setattr(
        sa.workshop_metrics, "list_metrics",
        lambda permission_codes=None: [{"id": mid, "name": mid, "description": mid} for mid in ids],
    )
    monkeypatch.setattr(sa.lifecycle_agents, "allowed_metric_ids", lambda _profiles: None)
    result = sa._auto_diagnostic_metric_ids(question)
    assert result == expected_ids, f"{question}: {result}"


def test_embedder_pluggable():
    """Embedder 可插拔：纯向量 embedder（无 hits 能力）仅用阈值判定。"""
    class _Dummy:
        def similarity(self, text, keywords):
            return 0.9 if "排行" in text else 0.0

    router = IntentRouter(embedder=_Dummy())
    result = router.similarity_route("客户销售额排行")
    assert result.intent == "ranking"
    assert isinstance(KeywordEmbedder(), KeywordEmbedder)


def test_build_intent_router_defaults_to_keyword(monkeypatch):
    """默认配置 → keyword embedder；vector_api 配置 → 可插拔切换。"""
    from app.runtime import intent_router as ir

    monkeypatch.setattr(ir, "get_settings", lambda: type("S", (), {
        "intent_embedder": "keyword", "embedding_model": "m",
        "embedding_api_base": "", "embedding_api_key": "", "embedding_api_model": "m",
    })())
    router = ir.build_intent_router()
    assert isinstance(router._embedder, KeywordEmbedder)

    monkeypatch.setattr(ir, "get_settings", lambda: type("S", (), {
        "intent_embedder": "vector_api", "embedding_model": "m",
        "embedding_api_base": "https://x.example", "embedding_api_key": "k",
        "embedding_api_model": "bge",
    })())
    router = ir.build_intent_router()
    assert isinstance(router._embedder, ir.VectorEmbedder)
    assert router._embedder._backend == "api"


def test_vector_embedder_api_mode(monkeypatch):
    """VectorEmbedder API 模式：OpenAI 兼容 embeddings → 意图种子相似度。"""
    import httpx

    from app.runtime import intent_router as ir

    fake_embeddings = {
        "客户销售额排行": [1.0, 0.0],
        "哪个客户卖得最多": [1.0, 0.1],
        "今年销售额多少": [0.0, 1.0],
    }

    def fake_post(url, **kwargs):
        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                texts = kwargs["json"]["input"]
                return {"data": [{"embedding": fake_embeddings.get(t, [0.0, 0.0])} for t in texts]}
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    embedder = ir.VectorEmbedder(backend="api", api_base="https://x.example", api_key="k")
    embedder._encode = embedder._encode_api  # 强制走 API 分支
    router = IntentRouter(embedder=embedder)
    result = router.similarity_route("客户销售额排行")
    assert result.intent == "ranking"
    assert result.confidence > 0.9


def test_aggregate_trace_stats():
    """trace 聚合：层分布 / 拦截 / 低置信 / 未路由。"""
    from scripts.analyze_agent_traces import aggregate_trace_stats

    traces = [
        {"routing": {"layer": "rules", "confidence": 1.0}, "outcome": "completed:supported"},
        {"routing": {"layer": "similarity", "confidence": 0.15}, "outcome": "completed:supported"},
        {"routing": {"layer": "none"}, "outcome": "completed"},
        {"routing": {"layer": "rules", "confidence": 1.0}, "outcome": "completed:unsupported_measurable_claim"},
        {"routing": {}, "outcome": "completed:supported"},
    ]
    stats = aggregate_trace_stats(traces)
    assert stats["total"] == 5
    assert stats["layer_dist"]["rules"] == 2
    assert stats["layer_dist"]["similarity"] == 1
    assert stats["unrouted"] == 2  # layer=none + 无 routing
    assert stats["low_confidence"] == 1
    assert stats["intercepted"] == 3  # 2×unrouted + 1×guardrail 拦截
    assert len(stats["samples"]) == 4


# ---------------------------------------------------------------- 一致性检查

def test_consistency_gaps_flags_missing_year():
    """问 2025 年但注入数据是今年的 → 披露缺口，不硬答。"""
    gaps = sa._consistency_gaps(
        "2025年销售额多少",
        [{"metric_id": "finance.sales_snapshot", "data": {"year": 2026, "revenue": 9398}}],
    )
    assert gaps == ["2025"]


def test_consistency_gaps_empty_when_covered():
    gaps = sa._consistency_gaps(
        "2026年销售额多少",
        [{"metric_id": "finance.sales_snapshot", "data": {"year": 2026, "revenue": 9398}}],
    )
    assert gaps == []


# ---------------------------------------------------------------- 追问继承

_RANKING_ROUTE = {
    "intent": "ranking",
    "metric_ids": ["finance.customer_sales_ranking"],
    "params": {"year": 2026, "order": "desc", "limit": 10},
    "layer": "injected",
}


def test_follow_up_limit_modifies_params_deterministically():
    """「只要top3」→ 确定性继承 ranking + limit=3，不靠模型剪裁。"""
    result = RESOLVER.resolve("只要top3", _RANKING_ROUTE)
    assert result is not None
    assert result.intent == "ranking"
    assert result.params["limit"] == 3
    assert result.layer == "follow_up_limit"


def test_follow_up_前十_parses():
    result = RESOLVER.resolve("只看前十", _RANKING_ROUTE)
    assert result is not None
    assert result.params["limit"] == 10


def test_follow_up_order_asc_desc():
    """「从小到大排」→ 确定性继承 ranking + order=asc（表格/图表顺序一致）。"""
    asc = RESOLVER.resolve("销售额从小到大排", _RANKING_ROUTE)
    assert asc is not None
    assert asc.intent == "ranking"
    assert asc.params["order"] == "asc"
    assert asc.layer == "follow_up_order"

    desc = RESOLVER.resolve("从大到小排", _RANKING_ROUTE)
    assert desc is not None
    assert desc.params["order"] == "desc"


def test_follow_up_month_shifts_previous_month():
    snapshot_route = {
        "intent": "sales_snapshot",
        "metric_ids": ["finance.sales_snapshot"],
        "params": {"year": 2026, "month": 8},
        "layer": "injected",
    }
    result = RESOLVER.resolve("上月呢", snapshot_route)
    assert result is not None
    assert result.params == {"year": 2026, "month": 7}
    assert result.layer == "follow_up_month"


def test_follow_up_month_handles_january_wraparound():
    route = {"intent": "sales_snapshot", "metric_ids": ["finance.sales_snapshot"],
             "params": {"year": 2026, "month": 1}, "layer": "injected"}
    result = RESOLVER.resolve("上个月呢", route)
    assert result is not None
    assert result.params == {"year": 2025, "month": 12}


def test_follow_up_switch_intent():
    """「换成毛利」→ 从 ranking 确定性切换到利润概况。"""
    result = RESOLVER.resolve("换成毛利", _RANKING_ROUTE)
    assert result is not None
    assert result.intent == "profit_overview"
    assert result.layer == "follow_up_switch"


def test_follow_up_switch_to_shortages():
    result = RESOLVER.resolve("那缺料呢", _RANKING_ROUTE)
    assert result is not None
    assert result.intent == "shortages"
    assert result.metric_ids == ["materials.shortages"]


def test_follow_up_pure_inherit_without_modifier():
    result = RESOLVER.resolve("再查一下", _RANKING_ROUTE)
    assert result is not None
    assert result.intent == "ranking"
    assert result.params == _RANKING_ROUTE["params"]
    assert result.layer == "follow_up_inherit"


def test_follow_up_year_modification():
    """「去年呢 / 2025年呢」→ 年份确定性修改。"""
    route = {"intent": "sales_snapshot", "metric_ids": ["finance.sales_snapshot"],
             "params": {"year": 2026, "month": 8}, "layer": "injected"}
    result = RESOLVER.resolve("去年呢", route)
    assert result is not None
    assert result.params == {"year": 2025, "month": 8}
    assert result.layer == "follow_up_year"

    explicit = RESOLVER.resolve("2024年呢", route)
    assert explicit is not None
    assert explicit.params == {"year": 2024, "month": 8}


def test_follow_up_months_for_trend():
    """「近6个月呢」→ 趋势意图的 months 参数。"""
    route = {"intent": "sales_trend", "metric_ids": ["finance.sales_time_series"],
             "params": {"year": 2026, "month": 8, "months": 12}, "layer": "injected"}
    result = RESOLVER.resolve("近6个月呢", route)
    assert result is not None
    assert result.params["months"] == 6
    assert result.layer == "follow_up_months"


def test_follow_up_composite_modifications():
    """组合修改：去年8月 / 从小到大只要前5 → 一次应用全部修改。"""
    snapshot_route = {"intent": "sales_snapshot", "metric_ids": ["finance.sales_snapshot"],
                      "params": {"year": 2026, "month": 8}, "layer": "injected"}
    composite = RESOLVER.resolve("去年8月", snapshot_route)
    assert composite is not None
    assert composite.params == {"year": 2025, "month": 8}
    assert composite.layer == "follow_up_params"
    assert "年份" in composite.reason and "月份" in composite.reason

    order_limit = RESOLVER.resolve("从小到大只要前5", _RANKING_ROUTE)
    assert order_limit is not None
    assert order_limit.params == {"year": 2026, "order": "asc", "limit": 5}
    assert order_limit.layer == "follow_up_params"


def test_follow_up_requires_previous_route():
    assert RESOLVER.resolve("只要top3", None) is None


def test_follow_up_not_triggered_without_connective():
    assert RESOLVER.resolve("客户销售额排行", _RANKING_ROUTE) is None


# ---------------------------------------------------------------- route 落库回读

def test_route_persisted_and_read_back(fake_conv_db):
    """enrich 落库 route → _read_last_assistant_route 读回（追问继承的稳定来源）。"""
    import json as _json

    fake_conv_db.execute(
        "INSERT INTO conversations (id, tenant_id, title, created_at, updated_at, ui_messages)"
        " VALUES ('c1',1,'t','2026-01-01','2026-01-01',?)",
        (_json.dumps([{"role": "user", "content": "客户销售额排行"},
                      {"role": "assistant", "content": "回复"}], ensure_ascii=False),),
    )
    fake_conv_db.commit()

    sa._enrich_last_assistant_message(
        1, "c1", route={"intent": "ranking", "metric_ids": ["finance.customer_sales_ranking"],
                        "params": {"limit": 10}, "layer": "injected"},
    )
    route = sa._read_last_assistant_route(1, "c1")
    assert route is not None
    assert route["intent"] == "ranking"
    assert route["params"] == {"limit": 10}


# ---------------------------------------------------------------- fast path route / 混合路径

def test_direct_route_built_from_ranking_artifact():
    """fast path 成功 → 构建确定性 route（追问继承来源）。"""
    from app.runtime.workshop.finalize_middleware import _direct_route

    artifact = {
        "status": "success",
        "result": {"metric_id": "finance.customer_sales_ranking",
                   "year": 2026, "order": "desc", "limit": 10},
    }
    route = _direct_route(artifact)
    assert route["intent"] == "ranking"
    assert route["metric_ids"] == ["finance.customer_sales_ranking"]
    assert route["params"] == {"year": 2026, "order": "desc", "limit": 10}
    assert route["layer"] == "direct"


def test_direct_route_none_on_rejection():
    from app.runtime.workshop.finalize_middleware import _direct_route

    assert _direct_route({"status": "model_argument_error", "result": None}) is None


def test_merge_fast_path_rows_preserves_fast_path_turns():
    """fast path 轮（不进 checkpoint）在重序列化后仍保留（含 route）。"""
    old = [
        {"role": "user", "content": "客户销售额排行", "path": "fast_path"},
        {"role": "assistant", "content": "排行结论", "path": "fast_path",
         "route": {"intent": "ranking", "params": {"limit": 10}}},
        {"role": "user", "content": "只要top3"},
        {"role": "assistant", "content": "top3结论"},
    ]
    new = [
        {"role": "user", "content": "客户销售额排行"},
        {"role": "user", "content": "只要top3"},
        {"role": "assistant", "content": "top3结论"},
    ]
    merged = sa._merge_fast_path_rows(old, new)
    assert merged[0]["content"] == "客户销售额排行"
    assert merged[1]["path"] == "fast_path"
    assert merged[1]["route"]["intent"] == "ranking"
    assert merged[2]["content"] == "只要top3"
    assert merged[3]["content"] == "top3结论"
