"""Semantic Compiler — 跨轮继承判定切片（第一落地块）。

背景：turn2 追问（「只显示top3」「大于500万的」「上月呢」）之前靠正则枚举
（agent_fast_path._detect_filter_followup / _LIMIT_FOLLOWUP_RE / _FILTER_RE），
任何新说法都不在词表里 → 掉进 LLM 路径牛头不对马嘴。本模块把「是不是
同主题追问、继承什么参数」的判断交给 LLM（语义理解），但守住两条确定性
边界：

1. **校验在代码里**：即使 LLM 说 inherits=true，也要查会话历史确认上轮
   确有 Fast Path 排行轮次（不再从回复文本正则抠年份），refine 参数必须
   合法（limit∈[1,100]、min_amount>0、period 合法），否则拒绝。
2. **不 fallback**：LLM 不可用或校验不过 → 明确返回（not_applicable /
   requires_clarification），绝不猜测、绝不正则兜底。

与主 Compiler 的关系：本模块是「LLM propose + 确定性校验」模式在跨轮
场景的第一个实现；后续单轮原子、复合、最高级都进同一模式。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings

LOCAL_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai fixed offset (v1)

MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# LLM propose 载荷（结构化输出；extra 字段被拒绝、缺字段失败）
# --------------------------------------------------------------------------


class RefineSpec(BaseModel):
    """追问要调整的排行参数。只允许这三个；其他语义（换指标/换维度）是
    新问题，不走继承（inherits=false 让上层按新问题编译）。"""

    model_config = ConfigDict(extra="forbid")

    limit: int | None = Field(default=None, ge=MIN_LIMIT, le=MAX_LIMIT)
    min_amount: float | None = Field(default=None, gt=0)
    period: Literal["last_month", "last_year", "this_year", "this_month"] | None = None


class InheritanceProposal(BaseModel):
    """跨轮继承判定。LLM 只 propose，不执行。"""

    model_config = ConfigDict(extra="forbid")

    inherits: bool
    refine: RefineSpec = Field(default_factory=RefineSpec)


# --------------------------------------------------------------------------
# 会话历史读取（只读短连接，不触碰 schedule_agent 的共享连接）
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviousTurn:
    question: str
    reply: str
    analysis_type: str | None
    year: int | None
    month: int | None
    limit: int | None


def _read_previous_fast_path_turn(
    tenant_id: int, conversation_id: str
) -> PreviousTurn | None:
    """读取最后一条 Fast Path 轮次（assistant + path=fast_path）。

    返回结构化信息（问题/结论/类型/期间/limit），不再从回复文本抠年份。
    无 Fast Path 历史 → None（上层不猜测）。

    注：不同分析类型（ranking / metric_snapshot）的跨轮继承由各自的
    Fast Path 路径处理；本函数只返回上轮是什么，是否继承由调用方结合
    analysis_type 判定（ranking 路径只继承 ranking 轮次）。
    """
    try:
        from pathlib import Path

        import sqlite3

        path = Path(get_settings().schedule_agent_data_dir) / "conversations.sqlite"
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT ui_messages FROM conversations WHERE id=? AND tenant_id=?",
                (conversation_id, tenant_id),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return None
        messages = json.loads(row[0])
        # 找最后一对 user/assistant（fast_path 轮次）。
        for index in range(len(messages) - 1, -1, -1):
            msg = messages[index]
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "assistant" and msg.get("path") == "fast_path":
                question = ""
                for j in range(index - 1, -1, -1):
                    prev = messages[j]
                    if isinstance(prev, dict) and prev.get("role") == "user":
                        question = str(prev.get("content") or "")
                        break
                presentation = msg.get("presentation") or {}
                return PreviousTurn(
                    question=question,
                    reply=str(msg.get("content") or ""),
                    analysis_type=str(presentation.get("analysis_type") or "")
                    or None,
                    year=_as_int(presentation.get("year")),
                    month=_as_int(presentation.get("month")),
                    limit=_as_int(presentation.get("limit")),
                )
    except Exception:
        return None
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# LLM propose（temperature=0，结构化输出）
# --------------------------------------------------------------------------


def _make_model():
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=settings.deepseek_model or "deepseek-chat",
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url or "https://api.deepseek.com",
        temperature=0,
        max_tokens=512,
    )


def _propose_inheritance(question: str, previous: PreviousTurn) -> InheritanceProposal:
    """LLM 判断 turn2 是否继承上轮排行上下文，以及要调整什么参数。

    只 propose 不执行。无法判断时必须输出 inherits=false（宁可当新问题，
    不可猜一个 refine 让答案错）。

    注意：不用 ``with_structured_output``——DeepSeek API 不支持
    ``response_format=json_schema``（400 "This response_format type is
    unavailable"）。改为提示词强制 JSON + 本地 pydantic 校验，输出契约
    不变（extra 字段被拒绝、缺字段失败）。
    """
    system = (
        "你是 ERP 语义计划器的跨轮继承判定器。用户上一轮问了一个分析问题，"
        "这一轮可能是追问（继承上轮并调整参数），也可能是新问题。"
        "判断规则：\n"
        "- 追问（inherits=true）：本轮明显承接上轮主题且只是调整参数，如\n"
        "  「只显示top3」「只看前3名」→ limit=3；「大于500万的」→ min_amount；\n"
        "  「上月呢」「去年呢」→ period。\n"
        "- 新问题（inherits=false）：换了主题、换了指标、换了维度，或无法\n"
        "  确定是否相关。拿不准一律 false，绝不猜测。\n"
        "- refine 只填本轮明确要求调整的参数；没有就不填（null）。\n"
        "只输出 JSON，不要解释。"
    )
    human = (
        "上轮问题：{q}\n上轮结论：{reply}\n本轮问题：{current}"
    ).format(
        q=previous.question or "（无）",
        reply=previous.reply or "（无）",
        current=question,
    )
    response = _make_model().invoke([("system", system), ("human", human)])
    text = _content_to_text(getattr(response, "content", ""))
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("inheritance_proposal_not_json")
    return InheritanceProposal.model_validate_json(match.group(0))


def _content_to_text(content: Any) -> str:
    """提取消息文本：str 直接用；list（多模态块）拼接文本块。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")


# --------------------------------------------------------------------------
# 确定性校验 + 组装 RankingRequest 参数
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InheritanceVerdict:
    status: Literal["inherited", "not_applicable", "requires_clarification", "unavailable"]
    reason_code: str
    limit: int | None = None
    min_amount: Decimal | None = None
    period: str | None = None
    year: int | None = None
    month: int | None = None


def resolve_inheritance(
    question: str,
    *,
    tenant_id: int,
    conversation_id: str,
) -> InheritanceVerdict:
    """跨轮继承主入口：读上轮 → LLM propose → 确定性校验。

    返回四种状态之一：
    - inherited：继承成立，携带 limit/min_amount/period/year/month
    - not_applicable：无 Fast Path 上轮 / LLM 判定为新问题 → 按新问题编译
    - requires_clarification：LLM 判继承但参数非法或上轮信息不足
    - unavailable：LLM 不可用（明确失败，不猜测）
    """
    previous = _read_previous_fast_path_turn(tenant_id, conversation_id)
    if previous is None:
        return InheritanceVerdict(
            status="not_applicable", reason_code="NO_PREVIOUS_FAST_PATH_TURN"
        )
    if previous.analysis_type not in (None, "ranking"):
        # 上轮不是 ranking（如 metric_snapshot 轮次）→ ranking 路径不继承；
        # 该轮次由 snapshot 路径自己的继承逻辑处理。
        return InheritanceVerdict(
            status="not_applicable", reason_code="PREVIOUS_TURN_NOT_RANKING"
        )

    try:
        proposal = _propose_inheritance(question, previous)
    except Exception as exc:
        return InheritanceVerdict(
            status="unavailable",
            reason_code="INHERITANCE_LLM_UNAVAILABLE",
        )

    if not proposal.inherits:
        return InheritanceVerdict(
            status="not_applicable", reason_code="NEW_QUESTION_NOT_INHERIT"
        )

    # ---- 确定性校验：inherits=true 必须能落到合法参数 ----
    refine = proposal.refine
    if refine.limit is None and refine.min_amount is None and refine.period is None:
        return InheritanceVerdict(
            status="requires_clarification",
            reason_code="INHERIT_WITHOUT_REFINE",
        )

    year = previous.year
    month = previous.month

    if refine.period is not None:
        today = date.today()
        if refine.period == "last_month":
            if month is None:
                month = today.month
            if month == 1:
                year, month = (year or today.year) - 1, 12
            else:
                year, month = year or today.year, month - 1
        elif refine.period == "last_year":
            year = (year or today.year) - 1
            month = None
        elif refine.period == "this_year":
            year = today.year
            month = None
        elif refine.period == "this_month":
            year, month = today.year, today.month

    return InheritanceVerdict(
        status="inherited",
        reason_code="INHERITED_VIA_COMPILER",
        limit=refine.limit,
        min_amount=(
            Decimal(str(refine.min_amount)) if refine.min_amount is not None else None
        ),
        period=refine.period,
        year=year,
        month=month,
    )
