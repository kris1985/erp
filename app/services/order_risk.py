"""A1b：生产单风险条（红/黄/绿 + 可读原因）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models import OrderStatus
from app.services.progress_service import _process_percent

# 与 workshop_display_service 看板 at_risk 同口径
DELIVERY_RISK_DAYS = 2
DELIVERY_WATCH_DAYS = 7
PROGRESS_RISK_PCT = 90.0


def overall_progress_percent(processes: list[Any] | None) -> float:
    rows = list(processes or [])
    if not rows:
        return 0.0
    pcts = [_process_percent(p) for p in rows]
    return round(sum(pcts) / len(pcts), 1) if pcts else 0.0


def compute_order_risk(
    *,
    status: str | OrderStatus | None,
    delivery_date: date | None,
    overall_percent: float,
    is_rush: bool = False,
    kit_ok: bool | None = None,
    kit_ready_date: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """返回 risk_level / risk_label / risk_reasons / at_risk。"""
    as_of = today or date.today()
    st = status.value if hasattr(status, "value") else str(status or "")
    if st in (OrderStatus.completed.value, OrderStatus.cancelled.value, "completed", "cancelled"):
        return {
            "risk_level": "none",
            "risk_label": "—",
            "risk_reasons": [],
            "at_risk": False,
            "overall_percent": overall_percent,
        }

    soon = as_of + timedelta(days=DELIVERY_RISK_DAYS)
    watch = as_of + timedelta(days=DELIVERY_WATCH_DAYS)
    material_blocked = kit_ok is False
    overdue = bool(delivery_date and delivery_date < as_of)
    at_risk = bool(delivery_date and delivery_date <= soon and overall_percent < PROGRESS_RISK_PCT)

    reasons: list[dict[str, str]] = []
    if overdue and delivery_date:
        reasons.append(
            {
                "code": "overdue",
                "text": f"已逾期 {(as_of - delivery_date).days} 天",
            }
        )
    elif at_risk:
        reasons.append(
            {
                "code": "delivery_risk",
                "text": f"交期风险（≤{DELIVERY_RISK_DAYS} 天且进度 {overall_percent:.0f}%）",
            }
        )
    if is_rush:
        reasons.append({"code": "rush", "text": "急单"})
    if material_blocked:
        reasons.append({"code": "material", "text": "缺料未齐套"})
    if kit_ready_date and material_blocked:
        reasons.append({"code": "kit_ready", "text": f"预计齐套日 {kit_ready_date}"})
    if overall_percent < 100:
        reasons.append({"code": "progress", "text": f"进度 {overall_percent:.0f}%"})

    if overdue or at_risk or (is_rush and material_blocked):
        level, label = "red", "高风险"
    elif material_blocked or is_rush or (
        delivery_date and delivery_date <= watch and overall_percent < 100
    ):
        level, label = "yellow", "关注"
    else:
        level, label = "green", "正常"

    if at_risk and level == "green":
        level, label = "red", "高风险"

    return {
        "risk_level": level,
        "risk_label": label,
        "risk_reasons": reasons,
        "at_risk": at_risk,
        "overall_percent": overall_percent,
    }
