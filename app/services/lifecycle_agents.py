"""Static lifecycle-agent registry with dynamic, permission-safe selection.

Profiles are product capabilities, not model-generated agents. The planner may
select several profiles for one question, but cannot invent tools or broaden a
profile's metric allow-list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleAgentProfile:
    id: str
    name: str
    description: str
    keywords: tuple[str, ...]
    metric_ids: tuple[str, ...]


PROFILES: tuple[LifecycleAgentProfile, ...] = (
    LifecycleAgentProfile(
        "order_commitment", "跟单军师", "核对订单进度、交期承诺、齐套与订单变更",
        ("接单", "订单", "交期", "急单", "插单", "齐套", "能不能接", "跟单", "客户催"),
        ("analytics.order_intake", "analytics.delivery_risk", "analytics.kit_ready", "production.order_progress"),
    ),
    LifecycleAgentProfile(
        "procurement_supply", "采购军师", "核对缺料、采购在途、供应商交期与保供风险",
        ("缺料", "物料", "采购", "到料", "库存", "BOM", "齐套"),
        ("materials.shortages", "purchase.open_pos", "inventory.shared_pool", "analytics.supply_chain", "analytics.kit_ready"),
    ),
    LifecycleAgentProfile(
        "warehouse_stock", "仓管军师", "核对仓库库存、库龄、批次、库位与盘点异常",
        ("仓库", "仓管", "库位", "库龄", "盘点", "批次", "出入库"),
        ("inventory.shared_pool", "materials.shortages", "analytics.kit_ready"),
    ),
    LifecycleAgentProfile(
        "schedule_capacity", "排产军师", "核对排产、工序负荷、瓶颈与插单影响",
        ("排产", "产能", "负荷", "瓶颈", "工序", "插单", "日产能"),
        ("schedule.daily_load", "analytics.capacity_load", "production.process_bottlenecks", "analytics.delivery_risk"),
    ),
    LifecycleAgentProfile(
        "production_quality", "生产品质军师", "核对生产进度、现场异常、质量与返工风险",
        ("进度", "报工", "生产", "质量", "返工", "不良", "产量"),
        ("production.today_output", "production.order_progress", "production.process_bottlenecks", "analytics.quality_hotspots", "analytics.quality_alerts"),
    ),
    LifecycleAgentProfile(
        "delivery_finance", "财务军师", "核对发货、应收、回款、利润与现金流风险",
        ("发货", "回款", "应收", "利润", "现金流", "经营", "付款"),
        ("finance.receivables_open", "finance.payments_this_month", "finance.profit_report", "finance.gross_profit_time_series", "finance.business_kpi", "finance.customer_sales_ranking", "analytics.finance_health"),
    ),
)


def select_profiles(question: str, *, max_profiles: int = 3) -> list[LifecycleAgentProfile]:
    """Select one to three registered roles; no keyword means no restriction."""
    text = (question or "").lower()
    ranked: list[tuple[int, LifecycleAgentProfile]] = []
    for profile in PROFILES:
        score = sum(1 for keyword in profile.keywords if re.search(re.escape(keyword.lower()), text))
        if score:
            ranked.append((score, profile))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [profile for _, profile in ranked[:max_profiles]]


def allowed_metric_ids(profiles: list[LifecycleAgentProfile]) -> set[str] | None:
    """None means an unclassified question keeps the existing full catalog."""
    if not profiles:
        return None
    return {metric_id for profile in profiles for metric_id in profile.metric_ids}


def public_profiles(profiles: list[LifecycleAgentProfile]) -> list[dict[str, str]]:
    return [{"id": p.id, "name": p.name, "description": p.description} for p in profiles]
