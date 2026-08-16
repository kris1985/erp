"""Minimal Metric Registry for Ranking v1 (contracts doc §4.1).

Existing ``workshop_metrics.query_metric`` stays untouched; this registry is
the explicit version source that resolves a ``metric_id`` to a pinned
``MetricRef`` (id + definition_version).  Only ``finance.customer_sales_ranking``
is registered in v1; a metric that is executable but not registered here must
never enter the Evidence chain.
"""

from __future__ import annotations

from pydantic import Field

from app.runtime.contracts import MetricRef, RuntimeModel


class MetricDefinition(RuntimeModel):
    metric_id: str
    definition_version: str
    name: str
    unit: str
    aggregation: str
    time_semantics: str
    granularity: str
    additive_dimensions: list[str] = Field(default_factory=list)
    domain: str = "sales"  # business domain used by AnswerContract.forbidden_claims


RANKING_METRIC = MetricDefinition(
    metric_id="finance.customer_sales_ranking",
    definition_version="1.0.0",
    name="客户销售额",
    unit="CNY",
    aggregation="sum",
    time_semantics="natural_year",
    granularity="year",
    additive_dimensions=["customer"],
    domain="sales",
)


class MetricRegistry:
    """Deterministic registry; resolution returns None on unknown/ambiguous."""

    def __init__(self, definitions: list[MetricDefinition] | None = None) -> None:
        self._by_id: dict[str, list[MetricDefinition]] = {}
        for definition in definitions if definitions is not None else [RANKING_METRIC]:
            self._by_id.setdefault(definition.metric_id, []).append(definition)

    def find(self, metric_id: str) -> list[MetricDefinition]:
        return list(self._by_id.get(metric_id, []))

    def resolve(self, metric_id: str) -> MetricRef | None:
        """Pin to the single registered version; None when unknown/ambiguous."""
        found = self.find(metric_id)
        if len(found) != 1:
            return None
        definition = found[0]
        return MetricRef(
            metric_id=definition.metric_id,
            definition_version=definition.definition_version,
        )

    def definitions(self) -> list[MetricDefinition]:
        return [d for versions in self._by_id.values() for d in versions]

    @classmethod
    def ranking_v1(cls) -> "MetricRegistry":
        return cls([RANKING_METRIC])
