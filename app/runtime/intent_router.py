"""Intent Router —— 问题 → 分析意图 的分层路由（rules → similarity → fail-closed）。

正确形态（对齐业界 layered routing）：
1. rules 层：确定性正则/决策树（精确说法，最高置信）
2. similarity 层：意图种子说法相似度（同义/模糊说法），≥ 阈值才命中，低分不硬猜
3. 都没有 → fail-closed（不注入，交给 agent / 澄清），绝不猜测

- Embedder 可插拔：默认 KeywordEmbedder（零依赖、可解释、易调），可替换为
  向量 embedder（如本地 bge-small-zh 或 embedding API），接口不变。
- 混合问题（multi-intent）单独检测：返回 multi_intent=True，调用方应跳过
  单意图注入，交给 agent 多工具路径。
- 置信度互检（verify_intent）：防"正则命中但关键词对不上"的误命中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.config import get_settings

# ---------------------------------------------------------------- 意图注册表

# 意图 → (metric_ids, 关键词组)。关键词组 = 该意图的"用户语言指纹"（产品侧资产，
# 上线后用真实日志反哺）。命中数越多、词越特异，相似度越高。
INTENT_KEYWORDS: dict[str, list[str]] = {
    "ranking": ["排行", "排名", "前", "名", "最高", "最多", "最大", "top", "冠军", "领先", "客户"],
    "sales_snapshot": ["销售额", "销售总额", "卖了", "销售金额"],
    "sales_trend": ["销售", "趋势", "走势", "月度", "变化", "每个月"],
    "gross_profit_trend": ["利润", "趋势", "走势", "月度", "变化"],
    "profit_overview": ["利润", "毛利", "收入", "成本", "赚", "概况", "各多少"],
    "cashflow": ["回款", "收款", "到账", "应收", "现金流", "催收", "欠款", "账龄"],
    "delivery_risk": ["交期", "延期", "逾期", "风险单", "急单"],
    "shortages": ["缺料", "待采", "缺什么料", "缺货"],
    "open_pos": ["采购", "在途", "到货", "采购单"],
    "today_output": ["产量", "产出", "今日", "今天", "报工"],
    "order_progress": ["进度", "做到哪", "生产单", "工序"],
    "schedule_load": ["负荷", "排产", "产能", "瓶颈"],
    "quality": ["不良", "质量", "抽检", "质检", "预警"],
    "labor": ["人效", "计件", "工资", "工时"],
}

# 意图 → 该意图落地时的注入指标（与 schedule_agent 决策树同源；相似度层专用）
INTENT_METRIC_IDS: dict[str, list[str]] = {
    "ranking": ["finance.customer_sales_ranking"],
    "sales_snapshot": ["finance.sales_snapshot"],
    "sales_trend": ["finance.sales_time_series"],
    "gross_profit_trend": ["finance.gross_profit_time_series"],
    "profit_overview": ["finance.profit_report", "finance.business_kpi"],
    "cashflow": ["finance.payments_this_month", "finance.receivables_open", "finance.business_kpi"],
    "delivery_risk": ["analytics.delivery_risk"],
    "shortages": ["materials.shortages"],
    "open_pos": ["purchase.open_pos"],
    "today_output": ["production.today_output"],
    "order_progress": ["production.order_progress"],
    "schedule_load": ["schedule.daily_load"],
    "quality": ["analytics.quality_alerts"],
    "labor": ["analytics.labor_efficiency"],
}


def intent_for_metric_ids(metric_ids: list[str]) -> str | None:
    """指标列表 → 意图名（用于把已执行的注入结果反查成可继承的路由）。"""
    for intent, ids in INTENT_METRIC_IDS.items():
        if set(ids) == set(metric_ids):
            return intent
    return None


# 向量 embedder 用的完整问法种子（每个意图 2-3 句；关键词是子串指纹、句子是语义指纹）
INTENT_SEED_SENTENCES: dict[str, list[str]] = {
    "ranking": ["客户销售额排行", "哪个客户卖得最多", "销售额最高的几家客户", "客户排名"],
    "sales_snapshot": ["今年销售额多少", "本月销售总额", "上个月卖了多少钱", "这个月销售额"],
    "sales_trend": ["今年的销售额趋势", "近几个月销售走势", "销售额变化曲线", "每月销售情况"],
    "gross_profit_trend": ["毛利趋势", "近几个月利润走势", "毛利变化"],
    "profit_overview": ["本月利润概况", "收入成本毛利各多少", "这个月赚了多少", "利润情况"],
    "cashflow": ["这个月回款多少", "谁还欠着钱", "应收余额和账龄", "现金流怎么样"],
    "delivery_risk": ["哪些订单交期风险", "延期订单列表", "急单有哪些"],
    "shortages": ["哪些材料缺料", "待采购清单", "缺什么料"],
    "open_pos": ["在途采购单", "采购单什么时候到货", "采购逾期情况"],
    "today_output": ["今天各工序产量", "今日产出多少", "今天报工情况"],
    "order_progress": ["这个单做到哪道工序了", "订单进度", "生产单进度"],
    "schedule_load": ["未来几天排产负荷", "工序负荷超产能吗", "产能瓶颈"],
    "quality": ["最近质量不良情况", "哪个工序不良率高", "质量预警"],
    "labor": ["本月人效怎么样", "计件工资情况", "人效和工资对账"],
}


def _cosine(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class VectorEmbedder:
    """向量 embedder：本地 sentence-transformers 或 OpenAI 兼容 embedding API。

    协议与 KeywordEmbedder 相同（similarity(text, candidates)），
    引擎可插拔：本地（bge 系列，CPU 可跑）或 API（硅基流动等）。
    ``prefer_seed_sentences=True`` 指示路由层传入完整问法种子而非关键词。
    """

    prefer_seed_sentences = True

    def __init__(
        self,
        *,
        backend: str = "local",
        model: str = "BAAI/bge-small-zh-v1.5",
        api_base: str = "",
        api_key: str = "",
        api_model: str = "",
    ) -> None:
        self._backend = backend
        self._model_name = model
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._api_model = api_model or model
        self._local_model = None

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if self._backend == "api":
            return self._encode_api(texts)
        return self._encode_local(texts)

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 依赖缺失提示
            raise RuntimeError(
                "vector_local 需要安装 sentence-transformers：pip install sentence-transformers"
            ) from exc
        if self._local_model is None:
            self._local_model = SentenceTransformer(self._model_name)
        return self._local_model.encode(list(texts)).tolist()

    def _encode_api(self, texts: list[str]) -> list[list[float]]:
        import httpx

        if not self._api_base or not self._api_key:
            raise RuntimeError("vector_api 需要配置 embedding_api_base / embedding_api_key")
        resp = httpx.post(
            f"{self._api_base}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._api_model, "input": list(texts)},
            timeout=30,
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]

    def similarity(self, text: str, candidates: list[str]) -> float:
        if not candidates:
            return 0.0
        text_vec = self._encode([text])[0]
        seed_vecs = self._encode(list(candidates))
        return max(_cosine(text_vec, vec) for vec in seed_vecs)


def build_intent_router(embedder_mode: str | None = None) -> IntentRouter:
    """按配置构建路由器（embedder 引擎可插拔，协议不变）。

    - keyword（默认）：零依赖关键词打分
    - vector_local：本地 sentence-transformers（bge 系列）
    - vector_api：OpenAI 兼容 embedding API
    """
    mode = (embedder_mode or get_settings().intent_embedder or "keyword").strip().lower()
    settings = get_settings()
    if mode == "vector_local":
        return IntentRouter(embedder=VectorEmbedder(backend="local", model=settings.embedding_model))
    if mode == "vector_api":
        return IntentRouter(embedder=VectorEmbedder(
            backend="api", model=settings.embedding_model,
            api_base=settings.embedding_api_base, api_key=settings.embedding_api_key,
            api_model=settings.embedding_api_model,
        ))
    return IntentRouter()

# 混合问题信号：连接词（会把两个独立意图连起来）；是否真混合由 domains≥2 判定，
# 同域并列（如"回款和应收"同属 cashflow）不会误伤。
_MULTI_INTENT_CONNECTORS = re.compile(
    r"还有|顺便|以及|同时|另外|再看看|再看下|顺便看|加上|并且|和|与|跟|,|，"
)
# 命中多个不同意图才算混合；同一意图内部用连接词不算（如"回款和应收"同属 cashflow）
_MULTI_INTENT_THRESHOLD = 2

# similarity 层阈值：得分 ≥ 阈值 且 命中词数 ≥ MIN_HITS 才命中；否则不猜（fail-closed）
SIMILARITY_THRESHOLD = 0.12
MIN_HITS = 1


# ---------------------------------------------------------------- Embedder 协议

class Embedder(Protocol):
    """可插拔相似度器：text 与候选说法/关键词组的相似度（0~1）。"""

    def similarity(self, text: str, candidate_keywords: list[str]) -> float: ...


class KeywordEmbedder:
    """零依赖关键词打分：命中关键词加权相似度，可解释、易调。

    每个意图的关键词按特异度给权重（由关键词长度近似），
    相似度 = Σ命中权重 / Σ全部权重。避免"排行"这类通用词一票命中。
    """

    def similarity(self, text: str, candidate_keywords: list[str]) -> float:
        lowered = text.lower()
        hit = 0.0
        total = 0.0
        for kw in candidate_keywords:
            w = 1.0 + min(2.0, len(kw) * 0.25)  # 长词更特异
            total += w
            if kw.lower() in lowered:
                hit += w
        return hit / total if total else 0.0

    def hits(self, text: str, candidate_keywords: list[str]) -> int:
        lowered = text.lower()
        return sum(1 for kw in candidate_keywords if kw.lower() in lowered)


# ---------------------------------------------------------------- 追问继承

# 承接表达：省略主语的追问（"只要top3 / 上月呢 / 换成毛利 / 那缺料呢 / 从小到大排"）
_FOLLOW_UP_RE = re.compile(
    r"^(?:只要|只看|只|就|再|换|换成|那|继续|另外|也|顺便|帮我再看|再看)"
    r"|前十|前\s*\d+\s*名?|上月|上个月|上上个月"
    r"|从小到大|升序|从低到高|由低到高|从少到多|低到高"
    r"|从大到小|降序|从高到低|由高到低|从多到少|高到低"
    r"|去年|前年|上年|(?:20\d{2})\s*年|近\s*\d+\s*个?月"
)
_ASC_RE = re.compile(r"从小到大|升序|从低到高|由低到高|从少到多|低到高")
_DESC_RE = re.compile(r"从大到小|降序|从高到低|由高到低|从多到少|高到低")
_YEAR_EXPLICIT_RE = re.compile(r"(20\d{2})\s*年")
_YEAR_AGO_RE = re.compile(r"去年|上年|前年")
_MONTHS_RE = re.compile(r"近\s*(\d+|[一二两三四五六七八九十]+)\s*个?月")
# 单一修改时的 trace 层名（组合修改统一 follow_up_params）
_SINGLE_FOLLOW_UP_LAYER = {
    "排序": "follow_up_order",
    "条数": "follow_up_limit",
    "年份": "follow_up_year",
    "月份": "follow_up_month",
    "跨度": "follow_up_months",
}
_LIMIT_RE = re.compile(
    r"(?:只要|只看|只|就|前|Top|top)\s*(?:看\s*)?(?:前\s*)?(?:Top|top\s*)?"
    r"(\d+|[一二两三四五六七八九十]+)\s*(?:名|个|家|户|单|条)?"
)
_MONTH_RE = re.compile(r"(\d{1,2})\s*月(?:份|底|初)?")
_PREV_MONTH_RE = re.compile(r"上上?个月|上月")

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value in _CN_DIGITS:
        return _CN_DIGITS[value]
    if "十" in value:
        head, _, tail = value.partition("十")
        return _CN_DIGITS.get(head, 1) * 10 + _CN_DIGITS.get(tail, 0)
    return 0


class FollowUpResolver:
    """追问继承：基于上一轮确定性路由结果，解析本轮承接句的修改。

    稳定性的来源：上一轮 RouteResult 是**持久化的确定性产物**（不是模型记忆），
    本轮修改（limit/月份/意图切换）由正则确定性解析，执行仍走确定性引擎。
    解析不了（无上一轮 / 无承接词 / 修改无法理解）→ 返回 None，走正常单句路由。
    """

    def detect(self, question: str) -> bool:
        return bool(_FOLLOW_UP_RE.search(question or ""))

    def __init__(self, embedder: Embedder | None = None) -> None:
        if embedder is not None:
            self._router = IntentRouter(embedder=embedder)
        else:
            self._router = build_intent_router()

    def resolve(self, question: str, prev_route: dict | None) -> RouteResult | None:
        """组合修改器：收集本句全部可识别修改（排序/条数/年份/月份/跨度）一次应用。

        无上一轮或无承接词 → None（走单句路由）。全部修改对当前意图不适用时
        才尝试意图切换；再不行则原样继承。
        """
        if not prev_route or not self.detect(question):
            return None
        text = question or ""
        intent = prev_route.get("intent")
        metric_ids = list(prev_route.get("metric_ids") or [])
        params = dict(prev_route.get("params") or {})
        reasons: list[str] = []
        changed = False

        # 1) 排序修改（ranking）——先于意图切换，避免"从小到大排"被误判为新意图
        if intent in {"ranking"} and (_ASC_RE.search(text) or _DESC_RE.search(text)):
            params["order"] = "asc" if _ASC_RE.search(text) else "desc"
            reasons.append(f"排序→{params['order']}")
            changed = True

        # 2) 条数修改（ranking）
        limit_match = _LIMIT_RE.search(text)
        if limit_match and intent in {"ranking"}:
            limit = _cn_to_int(limit_match.group(1))
            if 1 <= limit <= 100:
                params["limit"] = limit
                params.pop("months", None)
                reasons.append(f"条数→{limit}")
                changed = True

        # 3) 年份修改（对带年份参数的意图）
        explicit_year = _YEAR_EXPLICIT_RE.search(text)
        if explicit_year:
            params["year"] = int(explicit_year.group(1))
            reasons.append(f"年份→{params['year']}")
            changed = True
        elif _YEAR_AGO_RE.search(text):
            current_year = int(params.get("year") or date.today().year)
            params["year"] = current_year - (2 if "前年" in text else 1)
            reasons.append(f"年份→{params['year']}")
            changed = True

        # 4) 月份修改（在年份基础上；含跨年回绕）
        prev_month = params.get("month")
        if isinstance(prev_month, int) and _PREV_MONTH_RE.search(text):
            if "上上个月" in text:
                params["month"] = prev_month - 2
            else:
                params["month"] = prev_month - 1
            if params["month"] < 1:
                params["month"] += 12
                params["year"] = int(params.get("year") or date.today().year) - 1
            reasons.append(f"月份→{params['year']}-{params['month']}")
            changed = True
        elif isinstance(prev_month, int) and "月" in text:
            month_match = _MONTH_RE.search(text)
            if month_match:
                params["month"] = int(month_match.group(1))
                reasons.append(f"月份→{params['year']}-{params['month']}")
                changed = True

        # 5) 时间跨度修改（趋势意图："近6个月呢"）
        months_match = _MONTHS_RE.search(text)
        if months_match and intent in {"sales_trend", "gross_profit_trend"}:
            params["months"] = _cn_to_int(months_match.group(1))
            reasons.append(f"跨度→{params['months']}个月")
            changed = True

        if changed:
            layer = (
                _SINGLE_FOLLOW_UP_LAYER.get(reasons[0].split("→")[0], "follow_up_params")
                if len(reasons) == 1 else "follow_up_params"
            )
            return RouteResult(
                intent=intent, metric_ids=metric_ids, params=params, confidence=1.0,
                layer=layer, reason="；".join(reasons),
            )

        # 6) 意图切换：无参数修改时，承接句自带新意图关键词 → 重新路由
        switch = self._router.similarity_route(text)
        if switch.intent is not None and switch.intent != intent:
            return RouteResult(
                intent=switch.intent, metric_ids=list(switch.metric_ids),
                confidence=switch.confidence, layer="follow_up_switch",
                reason=f"追问切换意图 {intent} → {switch.intent}",
            )

        # 7) 纯承接（"再查一下 / 继续"）→ 原样继承上一轮
        return RouteResult(
            intent=intent, metric_ids=metric_ids, params=params, confidence=1.0,
            layer="follow_up_inherit", reason="追问原样继承上一轮",
        )


# ---------------------------------------------------------------- 路由结果

@dataclass
class RouteResult:
    intent: str | None = None
    metric_ids: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    layer: str = "none"          # rules | similarity | follow_up_* | none
    multi_intent: bool = False
    reason: str = ""


# ---------------------------------------------------------------- 路由器

class IntentRouter:
    """分层路由：多意图检测 → rules → similarity → fail-closed。"""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder or KeywordEmbedder()

    # -- 混合问题 -----------------------------------------------------

    def detect_multi_intent(self, question: str) -> bool:
        """同一句里出现 ≥2 个不同意图域的关键词 → 混合问题。

        混合问题不注入单意图，交给 agent 多工具路径（避免吞意图）。
        """
        if not _MULTI_INTENT_CONNECTORS.search(question or ""):
            return False
        domains = {
            intent for intent, keywords in INTENT_KEYWORDS.items()
            if any(kw.lower() in (question or "").lower() for kw in keywords)
        }
        return len(domains) >= _MULTI_INTENT_THRESHOLD

    # -- 相似度层 ------------------------------------------------------

    def similarity_route(self, question: str) -> RouteResult:
        """按意图种子关键词打分，最高分 ≥ 阈值且命中词数达标才命中。

        MIN_HITS 只对带 ``hits`` 能力的 embedder（如 KeywordEmbedder）生效；
        纯向量 embedder 可不实现 hits，仅用阈值判定。
        """
        hits_fn = getattr(self._embedder, "hits", None)
        best_intent: str | None = None
        best_score = 0.0
        best_hits = 0
        prefer_seeds = bool(getattr(self._embedder, "prefer_seed_sentences", False))
        for intent in INTENT_KEYWORDS:
            candidates = (
                INTENT_SEED_SENTENCES.get(intent) or INTENT_KEYWORDS[intent]
            ) if prefer_seeds else INTENT_KEYWORDS[intent]
            score = self._embedder.similarity(question or "", candidates)
            hits = hits_fn(question or "", candidates) if hits_fn else MIN_HITS
            if score > best_score:
                best_intent, best_score, best_hits = intent, score, hits
        if (
            best_intent is None
            or best_score < SIMILARITY_THRESHOLD
            or (hits_fn is not None and best_hits < MIN_HITS)
        ):
            return RouteResult(confidence=round(best_score, 3), layer="none",
                               reason=f"similarity 未达阈值（score={best_score:.3f}, hits={best_hits}）")
        return RouteResult(
            intent=best_intent,
            metric_ids=list(INTENT_METRIC_IDS.get(best_intent, [])),
            confidence=round(best_score, 3),
            layer="similarity",
            reason=f"similarity={best_score:.3f} hits={best_hits}",
        )

    # -- 置信度互检（防误命中） ------------------------------------------

    @staticmethod
    def verify_intent(question: str, intent: str | None) -> bool:
        """路由到 intent 后，用意图关键词复核问题：交集为空视为低置信误命中。

        例：问题"销售额趋势"被回款模板命中 → 关键词 {回款,应收…} ∩ 问题 = ∅ → 拒绝。
        """
        if not intent:
            return False
        keywords = INTENT_KEYWORDS.get(intent, [])
        if not keywords:
            return True
        lowered = (question or "").lower()
        return any(kw.lower() in lowered for kw in keywords)

    # -- 统一入口 ------------------------------------------------------

    def route(
        self,
        question: str,
        *,
        rules_result: str | None = None,
        rules_metric_ids: list[str] | None = None,
    ) -> RouteResult:
        """完整路由：多意图 → rules（调用方已算好）→ similarity → fail-closed。

        ``rules_result``：调用方 rules 层（正则决策树）已命中的意图名；
        ``rules_metric_ids``：rules 层给出的注入指标。
        """
        if self.detect_multi_intent(question):
            return RouteResult(multi_intent=True, layer="none", reason="混合问题，交 agent 拆解")
        if rules_result is not None:
            if not self.verify_intent(question, rules_result):
                # 正则命中但关键词互检不过 → 降级到 similarity，避免误命中
                fallback = self.similarity_route(question)
                if fallback.intent is not None:
                    return fallback
                return RouteResult(layer="none", confidence=0.0,
                                   reason=f"rules 命中 {rules_result} 但互检不过，且 similarity 未达阈值")
            return RouteResult(
                intent=rules_result,
                metric_ids=list(rules_metric_ids or []),
                confidence=1.0,
                layer="rules",
                reason="rules 命中且互检通过",
            )
        return self.similarity_route(question)
