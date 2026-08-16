"""Deterministic Renderer + Formatter for the ranking slice (PR #5,
contracts doc §P1.3).

The renderer consumes *verified* assertions + facts + contract only — never
raw evidence, SQL or unverified candidates.  Every business sentence carries
``assertion_refs`` so the UI can drill from a sentence back to its claim and
evidence.  All numbers are formatted by deterministic transforms (money /
percent) that are replayable: 12350000 CNY -> "1,235 万元" is a fact of the
formatter, never an LLM paraphrase.

No LLM is involved: v1 renders the ranking slice entirely deterministically.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.runtime.contracts import (
    AnswerContract,
    Assertion,
    EvidenceEnvelope,
    Fact,
    RuntimeModel,
)

CNY_THOUSANDS_UNIT = Decimal("10000")


class RenderedSentence(RuntimeModel):
    text: str
    assertion_refs: list[str] = []


class RenderedTable(RuntimeModel):
    columns: list[str]
    rows: list[list[str]]
    assertion_refs: list[str] = []


# --------------------------------------------------------------------------
# Deterministic formatters (replayable display transforms)
# --------------------------------------------------------------------------


def _thousands(value: Decimal) -> str:
    formatted = format(value, "f")
    integer, _, fraction = formatted.partition(".")
    grouped = f"{int(integer):,}"
    return grouped if not fraction else f"{grouped}.{fraction}"


def format_money(value: Decimal, unit: str = "CNY") -> str:
    """Deterministic money display: >= 10k renders in 万, else in 元."""
    if unit != "CNY":
        return f"{_thousands(value)} {unit}"
    if abs(value) >= CNY_THOUSANDS_UNIT:
        wan = (value / CNY_THOUSANDS_UNIT).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{_thousands(wan)} 万元"
    return f"{_thousands(value)} 元"


def format_percent(ratio: Decimal, scale: int = 1) -> str:
    """Deterministic percent display from a canonical ratio (0.6467 -> 64.7%)."""
    step = Decimal("1").scaleb(-scale)
    pct = (ratio * Decimal("100")).quantize(step, rounding=ROUND_HALF_UP)
    return f"{pct}%"


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------


class DeterministicRenderer:
    def render(
        self,
        assertions: list[Assertion],
        *,
        facts: list[Fact],
        envelope: EvidenceEnvelope,
        contract: AnswerContract,
        entity_label: str | None = None,
    ) -> list[RenderedSentence] | RenderedTable:
        if contract.presentation_mode == "table":
            return self.render_table(assertions, facts, envelope)
        return self.render_sentences(assertions, facts, envelope, entity_label)

    def render_sentences(
        self,
        assertions: list[Assertion],
        facts: list[Fact],
        envelope: EvidenceEnvelope,
        entity_label: str | None = None,
    ) -> list[RenderedSentence]:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        sentences: list[RenderedSentence] = []

        value_by_entity = {
            a.subject.dimensions.get(envelope.dimension): a
            for a in assertions
            if a.predicate == "value"
        }
        rank_by_entity = {
            a.subject.dimensions.get(envelope.dimension): a
            for a in assertions
            if a.predicate == "rank"
        }

        for row in envelope.payload.rows:
            if entity_label is not None and row.entity_label != entity_label:
                continue
            refs: list[str] = []
            value_a = value_by_entity.get(row.entity_id)
            rank_a = rank_by_entity.get(row.entity_id)
            if value_a is None and rank_a is None:
                continue
            fact = facts_by_id.get(f"{envelope.result_id}:{row.entity_id}")
            amount = format_money(fact.value, fact.unit) if fact else ""
            if value_a is not None:
                refs.insert(0, value_a.assertion_id)
            if rank_a is not None:
                refs.append(rank_a.assertion_id)
            if value_a is not None and rank_a is not None and amount:
                text = f"{row.entity_label} 销售额 {amount}，排名第 {rank_a.object['rank']}。"
            elif value_a is not None and amount:
                text = f"{row.entity_label} 销售额 {amount}。"
            elif rank_a is not None:
                text = f"{row.entity_label} 排名第 {rank_a.object['rank']}。"
            else:  # pragma: no cover - unreachable given the guards above
                continue
            sentences.append(RenderedSentence(text=text, assertion_refs=refs))

        for assertion in assertions:
            if entity_label is not None:
                # Entity-location mode (Case 6): only the located entity's
                # sentence, no aggregate share/judgement sentences.
                continue
            if assertion.predicate == "share_of_total":
                share_fact = facts_by_id.get(assertion.object.get("value_fact_ref", ""))
                if share_fact is None:
                    continue
                top_n = self._top_n_from(assertion, facts)
                sentences.append(
                    RenderedSentence(
                        text=f"前 {top_n} 名客户合计占总销售额 {format_percent(share_fact.value, share_fact.display.scale)}。",
                        assertion_refs=[assertion.assertion_id],
                    )
                )
            elif assertion.predicate == "classification":
                sentences.append(
                    RenderedSentence(
                        text=f"{assertion.object['classification']}。",
                        assertion_refs=[assertion.assertion_id],
                    )
                )
        return sentences

    def render_table(
        self,
        assertions: list[Assertion],
        facts: list[Fact],
        envelope: EvidenceEnvelope,
    ) -> RenderedTable:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        columns = ["排名", "客户", "销售额"]
        rows: list[list[str]] = []
        for row in envelope.payload.rows:
            fact = facts_by_id.get(f"{envelope.result_id}:{row.entity_id}")
            rows.append(
                [str(row.rank), row.entity_label, format_money(fact.value, fact.unit) if fact else ""]
            )
        rank_refs = [a.assertion_id for a in assertions if a.predicate == "rank"]
        return RenderedTable(columns=columns, rows=rows, assertion_refs=rank_refs)

    @staticmethod
    def _top_n_from(assertion: Assertion, facts: list[Fact]) -> int:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        numerator_ref = assertion.object.get("numerator_ref")
        numerator = facts_by_id.get(numerator_ref) if numerator_ref else None
        if numerator is not None:
            return len(numerator.inputs)  # topn_total inputs = the top-N row facts
        return 0
