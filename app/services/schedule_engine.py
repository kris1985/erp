"""确定性排产规则引擎（L2）。

AI 只能调用本模块产出方案，禁止自行编造日期/配额。
同输入 + 同规则版本 → 同 proposal（可审计、可复现）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from math import ceil
from typing import Any, Literal, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Order,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ScheduleStatus,
)
from app.services import material_service, schedule_settings
from app.utils.cn_holidays import (
    iter_workdays,
    next_workday,
    prev_workday,
    workday_span_ending,
    workday_span_starting,
)

ENGINE_VERSION = "schedule_engine_v1"

RiskLevel = Literal["ok", "tight", "late", "kit_blocked", "capacity_blocked"]

RISK_LABELS_ZH: dict[str, str] = {
    "ok": "余量充足",
    "tight": "交期偏紧",
    "late": "预计逾期",
    "kit_blocked": "缺料卡住",
    "capacity_blocked": "产能不足",
}


def risk_label_zh(risk: str | None) -> str:
    """排产风险码 → 中文（给人看；勿直接展示 tight/late）。"""
    if not risk:
        return "—"
    return RISK_LABELS_ZH.get(str(risk), str(risk))


class _ProcessLike(Protocol):
    id: int
    process_id: int
    process_name: str
    plan_qty: int


@dataclass
class ProcessSpec:
    """内存工序（虚拟插单用不落库）。"""

    id: int
    process_id: int
    process_name: str
    plan_qty: int


@dataclass
class IntakeDemand:
    """销售行等未落生产单的接单需求（幽灵单）。"""

    key: str
    order_no: str
    own_product_id: int
    total_qty: int
    delivery_date: date | None = None
    is_rush: bool = False
    first_kit_ok: bool = True
    kit_ok: bool = True
    earliest_start: date | None = None  # 等预计到料日后再开工


@dataclass
class ProcessWindow:
    order_process_id: int
    process_id: int
    process_name: str
    plan_qty: int
    days: int
    start_date: date
    end_date: date
    risk: RiskLevel = "ok"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        return d


@dataclass
class OrderPlan:
    order_id: int
    order_no: str
    delivery_date: date | None
    is_rush: bool
    total_qty: int
    first_kit_ok: bool
    kit_ok: bool
    priority_score: int
    windows: list[ProcessWindow]
    risk: RiskLevel = "ok"
    projected_finish: date | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_no": self.order_no,
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
            "is_rush": self.is_rush,
            "total_qty": self.total_qty,
            "first_kit_ok": self.first_kit_ok,
            "kit_ok": self.kit_ok,
            "priority_score": self.priority_score,
            "risk": self.risk,
            "risk_label": risk_label_zh(self.risk),
            "projected_finish": self.projected_finish.isoformat() if self.projected_finish else None,
            "notes": self.notes,
            "windows": [w.to_dict() for w in self.windows],
        }


@dataclass
class ScheduleProposal:
    proposal_id: str
    strategy: str
    title: str
    summary: str
    engine_version: str
    as_of: date
    orders: list[OrderPlan]
    risks: dict[str, int]
    load: list[dict[str, Any]] = field(default_factory=list)
    impacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "strategy": self.strategy,
            "title": self.title,
            "summary": self.summary,
            "engine_version": self.engine_version,
            "as_of": self.as_of.isoformat(),
            "orders": [o.to_dict() for o in self.orders],
            "risks": self.risks,
            "load": self.load,
            "impacts": self.impacts,
        }


def _open_statuses() -> list[OrderStatus]:
    return [OrderStatus.confirmed, OrderStatus.in_progress]


def _risk_rank(r: RiskLevel) -> int:
    order = {"ok": 0, "tight": 1, "late": 2, "capacity_blocked": 3, "kit_blocked": 4}
    return order.get(r, 9)


def _worse(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if _risk_rank(a) >= _risk_rank(b) else b


def _process_days_map(db: Session, tenant_id: int, cfg: dict[str, Any]) -> dict[int, int]:
    default_days = max(1, int(cfg.get("default_process_days") or 1))
    rows = db.scalars(
        select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant_id)
    ).all()
    out: dict[int, int] = {}
    for p in rows:
        days = getattr(p, "default_days", None)
        try:
            out[p.id] = max(1, int(days if days is not None else default_days))
        except (TypeError, ValueError):
            out[p.id] = default_days
    return out


def _priority_score(order: Order, first_kit_ok: bool, *, as_of: date) -> int:
    """越大越优先：急单 > 交期近 > 已齐套 > 已排过。"""
    score = 0
    if order.is_rush:
        score += 10_000
    if order.delivery_date:
        days_left = (order.delivery_date - as_of).days
        score += max(0, 5000 - days_left * 10)
    else:
        score += 1000
    if first_kit_ok:
        score += 500
    status = getattr(order, "schedule_status", None)
    if status == ScheduleStatus.partial or (
        hasattr(status, "value") and status.value == "partial"
    ):
        score += 100
    return score


def _classify_finish_risk(
    finish: date | None,
    delivery: date | None,
    *,
    tight_days: int,
) -> RiskLevel:
    if not finish or not delivery:
        return "ok"
    if finish <= delivery:
        gap = (delivery - finish).days
        if gap <= tight_days:
            return "tight"
        return "ok"
    return "late"


def backward_windows_for_processes(
    processes: Sequence[_ProcessLike],
    delivery: date | None,
    days_map: dict[int, int],
    *,
    default_days: int = 1,
    as_of: date | None = None,
) -> list[ProcessWindow]:
    """按路线倒序、工作日倒排。"""
    n = len(processes)
    if n == 0:
        return []
    as_of = as_of or date.today()
    total_days = sum(
        max(1, int(days_map.get(p.process_id, default_days))) for p in processes
    )
    end_anchor = delivery or (as_of + timedelta(days=total_days * 2))
    cursor_end = prev_workday(end_anchor)
    windows: list[ProcessWindow | None] = [None] * n
    for i in range(n - 1, -1, -1):
        p = processes[i]
        days = max(1, int(days_map.get(p.process_id, default_days)))
        start, end = workday_span_ending(cursor_end, days)
        windows[i] = ProcessWindow(
            order_process_id=int(p.id),
            process_id=p.process_id,
            process_name=p.process_name,
            plan_qty=int(p.plan_qty or 0),
            days=days,
            start_date=start,
            end_date=end,
        )
        cursor_end = prev_workday(start - timedelta(days=1))
    return [w for w in windows if w is not None]


def forward_windows_for_processes(
    processes: Sequence[_ProcessLike],
    days_map: dict[int, int],
    *,
    start_from: date,
    default_days: int = 1,
) -> list[ProcessWindow]:
    """从 start_from 起正排（工作日）。"""
    cursor = next_workday(start_from)
    out: list[ProcessWindow] = []
    for p in processes:
        days = max(1, int(days_map.get(p.process_id, default_days)))
        start, end = workday_span_starting(cursor, days)
        out.append(
            ProcessWindow(
                order_process_id=int(p.id),
                process_id=p.process_id,
                process_name=p.process_name,
                plan_qty=int(p.plan_qty or 0),
                days=days,
                start_date=start,
                end_date=end,
            )
        )
        cursor = next_workday(end + timedelta(days=1))
    return out


def _daily_load_units(window: ProcessWindow) -> dict[date, float]:
    days = list(iter_workdays(window.start_date, window.end_date))
    if not days:
        return {}
    per = float(window.plan_qty) / len(days)
    return {d: per for d in days}


def _apply_capacity_and_shift(
    windows: list[ProcessWindow],
    *,
    cfg: dict[str, Any],
    base_load: dict[tuple[int, date], float],
    allow_shift: bool,
) -> tuple[list[ProcessWindow], list[str]]:
    """粗产能校验；allow_shift 时把超产能工序顺延到后续工作日。"""
    notes: list[str] = []
    load = dict(base_load)
    result: list[ProcessWindow] = []
    for w in windows:
        cur = ProcessWindow(**{**asdict(w), "notes": list(w.notes)})
        if allow_shift:
            # 若首日已超产能，整体后移
            shifted = 0
            while True:
                units = _daily_load_units(cur)
                blocked = False
                for d, qty in units.items():
                    cap = schedule_settings.capacity_for_process(cfg, cur.process_id)
                    if cap is None:
                        continue
                    used = load.get((cur.process_id, d), 0.0) + qty
                    if used > cap + 1e-6:
                        blocked = True
                        break
                if not blocked or shifted >= 60:
                    break
                # 整体后移 1 个工作日
                new_start = next_workday(cur.start_date + timedelta(days=1))
                start, end = workday_span_starting(new_start, cur.days)
                cur.start_date = start
                cur.end_date = end
                shifted += 1
            if shifted:
                cur.notes.append(f"产能顺延{shifted}个工作日")
                notes.append(f"{cur.process_name}产能顺延{shifted}日")

        units = _daily_load_units(cur)
        over = False
        for d, qty in units.items():
            key = (cur.process_id, d)
            load[key] = load.get(key, 0.0) + qty
            cap = schedule_settings.capacity_for_process(cfg, cur.process_id)
            if cap is not None and load[key] > cap + 1e-6:
                over = True
        if over:
            cur.risk = "capacity_blocked"
            cur.notes.append("超出工序日产能")
        result.append(cur)
    return result, notes


def _aggregate_order_risk(
    plan: OrderPlan,
    *,
    tight_days: int,
    require_first_kit: bool,
) -> OrderPlan:
    risk: RiskLevel = "ok"
    if require_first_kit and not plan.first_kit_ok:
        risk = "kit_blocked"
        plan.notes.append("首道未齐套")
    finish = max((w.end_date for w in plan.windows), default=None)
    plan.projected_finish = finish
    finish_risk = _classify_finish_risk(finish, plan.delivery_date, tight_days=tight_days)
    risk = _worse(risk, finish_risk)
    for w in plan.windows:
        risk = _worse(risk, w.risk)
        # 开工早于今天且倒排导致「已经该开却未开」——仍用交期风险表达
        if plan.delivery_date and w.end_date > plan.delivery_date:
            w.risk = _worse(w.risk, "late")
            risk = _worse(risk, "late")
    plan.risk = risk
    return plan


def _proposal_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _risk_counts(orders: list[OrderPlan]) -> dict[str, int]:
    counts = {"ok": 0, "tight": 0, "late": 0, "kit_blocked": 0, "capacity_blocked": 0}
    for o in orders:
        counts[o.risk] = counts.get(o.risk, 0) + 1
    return counts


def _build_load_snapshot(
    windows: list[ProcessWindow],
    cfg: dict[str, Any],
    *,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    load: dict[tuple[int, str, date], float] = {}
    names: dict[int, str] = {}
    for w in windows:
        names[w.process_id] = w.process_name
        for d, qty in _daily_load_units(w).items():
            if d < date_from or d > date_to:
                continue
            key = (w.process_id, w.process_name, d)
            load[key] = load.get(key, 0.0) + qty
    rows: list[dict[str, Any]] = []
    for (pid, pname, d), qty in sorted(load.items(), key=lambda x: (x[0][2], x[0][0])):
        cap = schedule_settings.capacity_for_process(cfg, pid)
        util = (qty / cap) if cap else None
        rows.append(
            {
                "date": d.isoformat(),
                "process_id": pid,
                "process_name": pname,
                "load_qty": round(qty, 2),
                "capacity": cap,
                "utilization": round(util, 3) if util is not None else None,
                "over_capacity": bool(cap is not None and qty > cap + 1e-6),
            }
        )
    return rows


def _load_existing_windows(db: Session, tenant_id: int) -> list[ProcessWindow]:
    """已确认排产的工序窗（作负荷基线）。"""
    rows = db.scalars(
        select(OrderProcess)
        .join(Order, Order.id == OrderProcess.order_id)
        .where(
            OrderProcess.tenant_id == tenant_id,
            Order.tenant_id == tenant_id,
            Order.status.in_(_open_statuses()),
            OrderProcess.start_date.is_not(None),
            OrderProcess.end_date.is_not(None),
        )
    ).all()
    out: list[ProcessWindow] = []
    for p in rows:
        out.append(
            ProcessWindow(
                order_process_id=p.id,
                process_id=p.process_id,
                process_name=p.process_name,
                plan_qty=int(p.plan_qty or 0),
                days=1,
                start_date=p.start_date,
                end_date=p.end_date,
            )
        )
    return out


def collect_candidate_orders(
    db: Session,
    tenant_id: int,
    *,
    order_ids: list[int] | None = None,
    hide_scheduled: bool = True,
    hide_first_kit_blocked: bool = False,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """候选订单（含齐套与优先级），供引擎与 Agent 工具使用。"""
    as_of = as_of or date.today()
    q = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.status.in_(_open_statuses()),
    )
    if hide_scheduled:
        q = q.where(Order.schedule_status != ScheduleStatus.scheduled)
    if order_ids:
        q = q.where(Order.id.in_(order_ids))
    orders = list(db.scalars(q).all())
    if not orders:
        return []

    for o in orders:
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id)

    product_ids = {o.own_product_id for o in orders if o.own_product_id}
    product_map = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_(product_ids or [0]),
            )
        ).all()
    }

    items: list[dict[str, Any]] = []
    for o in orders:
        summary = ctx.summary_for_order(o.id)
        first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
        if hide_first_kit_blocked and not first_ok:
            continue
        product = product_map.get(o.own_product_id)
        score = _priority_score(o, first_ok, as_of=as_of)
        items.append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "customer_name": o.customer_name,
                "product_code": product.product_code if product else None,
                "total_qty": o.total_qty,
                "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None,
                "is_rush": bool(o.is_rush),
                "first_kit_ok": first_ok,
                "kit_ok": bool(summary.get("kit_ok")),
                "priority_score": score,
                "schedule_status": (
                    o.schedule_status.value
                    if getattr(o, "schedule_status", None) and hasattr(o.schedule_status, "value")
                    else str(getattr(o, "schedule_status", None) or "none")
                ),
            }
        )
    items.sort(key=lambda x: (-x["priority_score"], x["order_id"]))
    return items


def _plan_orders(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    strategy: Literal["delivery_first", "capacity_first", "kit_ready"],
    as_of: date,
    cfg: dict[str, Any],
) -> list[OrderPlan]:
    days_map = _process_days_map(db, tenant_id, cfg)
    default_days = max(1, int(cfg.get("default_process_days") or 1))
    tight_days = int(cfg.get("tight_days") or 2)
    require_first_kit = strategy == "kit_ready"

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_(order_ids),
                Order.status.in_(_open_statuses()),
            )
        ).all()
    )
    order_map = {o.id: o for o in orders}
    # 保持传入优先级顺序
    ordered = [order_map[i] for i in order_ids if i in order_map]

    for o in ordered:
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id)

    base_windows = _load_existing_windows(db, tenant_id)
    # 排除本次要重排的订单工序，避免双重占用
    replan_ops = set()
    for o in ordered:
        procs = db.scalars(
            select(OrderProcess.id).where(
                OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == o.id
            )
        ).all()
        replan_ops.update(procs)
    base_windows = [w for w in base_windows if w.order_process_id not in replan_ops]
    base_load: dict[tuple[int, date], float] = {}
    for w in base_windows:
        for d, qty in _daily_load_units(w).items():
            base_load[(w.process_id, d)] = base_load.get((w.process_id, d), 0.0) + qty

    plans: list[OrderPlan] = []
    for o in ordered:
        summary = ctx.summary_for_order(o.id)
        first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == o.id)
                .order_by(OrderProcess.id)
            ).all()
        )
        plan, base_load = _plan_route_item(
            order_id=o.id,
            order_no=o.order_no,
            delivery_date=o.delivery_date,
            is_rush=bool(o.is_rush),
            total_qty=int(o.total_qty or 0),
            first_kit_ok=first_ok,
            kit_ok=bool(summary.get("kit_ok")),
            processes=procs,
            strategy=strategy,
            as_of=as_of,
            days_map=days_map,
            default_days=default_days,
            tight_days=tight_days,
            require_first_kit=require_first_kit,
            cfg=cfg,
            base_load=base_load,
            priority_score=_priority_score(o, first_ok, as_of=as_of),
        )
        plans.append(plan)
    return plans


def _plan_route_item(
    *,
    order_id: int,
    order_no: str,
    delivery_date: date | None,
    is_rush: bool,
    total_qty: int,
    first_kit_ok: bool,
    kit_ok: bool,
    processes: Sequence[_ProcessLike],
    strategy: Literal["delivery_first", "capacity_first", "kit_ready"],
    as_of: date,
    days_map: dict[int, int],
    default_days: int,
    tight_days: int,
    require_first_kit: bool,
    cfg: dict[str, Any],
    base_load: dict[tuple[int, date], float],
    priority_score: int,
) -> tuple[OrderPlan, dict[tuple[int, date], float]]:
    if strategy == "capacity_first":
        windows = forward_windows_for_processes(
            processes, days_map, start_from=as_of, default_days=default_days
        )
        allow_shift = True
    else:
        windows = backward_windows_for_processes(
            processes,
            delivery_date,
            days_map,
            default_days=default_days,
            as_of=as_of,
        )
        if windows and windows[0].start_date < as_of:
            windows = forward_windows_for_processes(
                processes, days_map, start_from=as_of, default_days=default_days
            )
        allow_shift = strategy != "delivery_first"

    windows, shift_notes = _apply_capacity_and_shift(
        windows, cfg=cfg, base_load=base_load, allow_shift=allow_shift
    )
    load = dict(base_load)
    for w in windows:
        for d, qty in _daily_load_units(w).items():
            load[(w.process_id, d)] = load.get((w.process_id, d), 0.0) + qty

    plan = OrderPlan(
        order_id=order_id,
        order_no=order_no,
        delivery_date=delivery_date,
        is_rush=is_rush,
        total_qty=total_qty,
        first_kit_ok=first_kit_ok,
        kit_ok=kit_ok,
        priority_score=priority_score,
        windows=windows,
        notes=list(shift_notes),
    )
    return (
        _aggregate_order_risk(plan, tight_days=tight_days, require_first_kit=require_first_kit),
        load,
    )


def _priority_score_intake(d: IntakeDemand, *, as_of: date) -> int:
    score = 0
    if d.is_rush:
        score += 10_000
    if d.delivery_date:
        days_left = (d.delivery_date - as_of).days
        score += max(0, 5000 - days_left * 10)
    else:
        score += 1000
    if d.first_kit_ok:
        score += 500
    return score


def build_product_route_specs(
    db: Session,
    tenant_id: int,
    own_product_id: int,
    plan_qty: int,
    *,
    id_base: int,
) -> list[ProcessSpec] | None:
    """从产品工序报价生成虚拟路线；无工序返回 None。"""
    labors = list(
        db.scalars(
            select(OwnProductLabor)
            .where(
                OwnProductLabor.tenant_id == tenant_id,
                OwnProductLabor.own_product_id == own_product_id,
                OwnProductLabor.process_id.is_not(None),
            )
            .order_by(OwnProductLabor.sort_order, OwnProductLabor.id)
        ).all()
    )
    if not labors:
        return None
    qty = max(0, int(plan_qty))
    specs: list[ProcessSpec] = []
    for i, labor in enumerate(labors):
        pid = int(labor.process_id)  # type: ignore[arg-type]
        name = (labor.process_name or "").strip()
        if not name:
            proc = db.get(ProcessDefinition, pid)
            name = proc.name if proc else f"工序{pid}"
        specs.append(
            ProcessSpec(
                id=id_base - i,
                process_id=pid,
                process_name=name,
                plan_qty=qty,
            )
        )
    return specs


def _compromise_intake_order(
    real_candidates: list[dict[str, Any]],
    ghost_ids: list[int],
) -> list[int]:
    """折中：急单 → 幽灵 → 已齐套非急 → 其余。"""
    rush = [c["order_id"] for c in real_candidates if c.get("is_rush")]
    ready = [
        c["order_id"]
        for c in real_candidates
        if c.get("first_kit_ok") and not c.get("is_rush")
    ]
    rest = [
        c["order_id"]
        for c in real_candidates
        if c["order_id"] not in set(rush + ready)
    ]
    return rush + ghost_ids + ready + rest


def simulate_intake_demands(
    db: Session,
    tenant_id: int,
    demands: list[IntakeDemand] | list[dict[str, Any]],
    *,
    as_of: date | None = None,
    strategy_filter: str | None = None,
) -> dict[str, Any]:
    """未下生产单的虚拟插单仿真：保交期/保现场/折中，附对其它单冲击。

    不写库。无产品工序时返回 sim_error=no_route。
    """
    as_of = as_of or date.today()
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    days_map = _process_days_map(db, tenant_id, cfg)
    default_days = max(1, int(cfg.get("default_process_days") or 1))
    tight_days = int(cfg.get("tight_days") or 2)

    normalized: list[IntakeDemand] = []
    for raw in demands or []:
        if isinstance(raw, IntakeDemand):
            normalized.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        dd = raw.get("delivery_date")
        if isinstance(dd, str) and dd:
            dd = date.fromisoformat(dd[:10])
        elif not isinstance(dd, date):
            dd = None
        es = raw.get("earliest_start")
        if isinstance(es, str) and es:
            es = date.fromisoformat(es[:10])
        elif not isinstance(es, date):
            es = None
        normalized.append(
            IntakeDemand(
                key=str(raw.get("key") or f"intake:{len(normalized)}"),
                order_no=str(raw.get("order_no") or raw.get("key") or "INTAKE"),
                own_product_id=int(raw["own_product_id"]),
                total_qty=int(raw.get("total_qty") or raw.get("qty") or 0),
                delivery_date=dd,
                is_rush=bool(raw.get("is_rush")),
                first_kit_ok=bool(raw.get("first_kit_ok", True)),
                kit_ok=bool(raw.get("kit_ok", True)),
                earliest_start=es,
            )
        )
    # 交期优先依次插入
    normalized.sort(
        key=lambda d: (
            d.delivery_date.toordinal() if d.delivery_date else 10**9,
            d.key,
        )
    )

    if not normalized:
        return {
            "sim_error": "empty_demands",
            "message": "无接单需求可仿真",
            "proposals": [],
            "engine_version": ENGINE_VERSION,
            "as_of": as_of.isoformat(),
        }

    ghost_routes: list[tuple[IntakeDemand, list[ProcessSpec], int]] = []
    for i, d in enumerate(normalized):
        if d.total_qty <= 0:
            return {
                "sim_error": "invalid_qty",
                "message": f"{d.order_no} 数量无效",
                "proposals": [],
                "engine_version": ENGINE_VERSION,
                "as_of": as_of.isoformat(),
            }
        specs = build_product_route_specs(
            db, tenant_id, d.own_product_id, d.total_qty, id_base=-(10_000 + i * 100)
        )
        if not specs:
            return {
                "sim_error": "no_route",
                "message": f"{d.order_no} 产品未配置工序报价，无法仿真",
                "key": d.key,
                "own_product_id": d.own_product_id,
                "proposals": [],
                "engine_version": ENGINE_VERSION,
                "as_of": as_of.isoformat(),
            }
        ghost_id = -(i + 1)
        ghost_routes.append((d, specs, ghost_id))

    candidates = collect_candidate_orders(
        db, tenant_id, hide_scheduled=False, hide_first_kit_blocked=False, as_of=as_of
    )
    base_ids = [c["order_id"] for c in candidates]
    # 冲击对比必须同排法：保交期对照 delivery_first，保现场对照 capacity_first。
    # 否则会把「排法切换」误报成「新单挤了现场」。
    base_plans_delivery = (
        _plan_orders(db, tenant_id, base_ids, strategy="delivery_first", as_of=as_of, cfg=cfg)
        if base_ids
        else []
    )
    base_plans_capacity = (
        _plan_orders(db, tenant_id, base_ids, strategy="capacity_first", as_of=as_of, cfg=cfg)
        if base_ids
        else []
    )
    base_finish_delivery = {p.order_id: p.projected_finish for p in base_plans_delivery}
    base_risk_delivery = {p.order_id: p.risk for p in base_plans_delivery}
    base_finish_capacity = {p.order_id: p.projected_finish for p in base_plans_capacity}
    base_risk_capacity = {p.order_id: p.risk for p in base_plans_capacity}

    ghost_ids = [gid for _, _, gid in ghost_routes]
    ghost_by_id = {gid: (d, specs) for d, specs, gid in ghost_routes}

    variants: list[tuple[str, str, list[int]]] = [
        ("protect_delivery", "保交期（接单置顶）", ghost_ids + base_ids),
        ("protect_floor", "保现场（接单置后）", base_ids + ghost_ids),
        ("compromise", "折中（急单后、齐套前）", _compromise_intake_order(candidates, ghost_ids)),
    ]
    if strategy_filter:
        variants = [v for v in variants if v[0] == strategy_filter]
        if not variants:
            return {
                "sim_error": "unknown_strategy",
                "message": f"未知策略：{strategy_filter}",
                "proposals": [],
                "engine_version": ENGINE_VERSION,
                "as_of": as_of.isoformat(),
            }

    # 预取真实订单与工序
    real_orders = {
        o.id: o
        for o in db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_(base_ids or [0]),
                Order.status.in_(_open_statuses()),
            )
        ).all()
    }
    for o in real_orders.values():
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id) if real_orders else None
    procs_by_order: dict[int, list[OrderProcess]] = {}
    for oid in base_ids:
        procs_by_order[oid] = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == oid)
                .order_by(OrderProcess.id)
            ).all()
        )

    def _run_sequence(seq_ids: list[int], plan_strategy: Literal["delivery_first", "capacity_first"]) -> list[OrderPlan]:
        base_windows = _load_existing_windows(db, tenant_id)
        # 真实重排单排除已确认窗
        replan_ops = set()
        for oid in seq_ids:
            if oid > 0:
                for p in procs_by_order.get(oid) or []:
                    replan_ops.add(p.id)
        base_windows = [w for w in base_windows if w.order_process_id not in replan_ops]
        load: dict[tuple[int, date], float] = {}
        for w in base_windows:
            for d, qty in _daily_load_units(w).items():
                load[(w.process_id, d)] = load.get((w.process_id, d), 0.0) + qty

        plans: list[OrderPlan] = []
        for oid in seq_ids:
            if oid < 0:
                d, specs = ghost_by_id[oid]
                ghost_as_of = as_of
                extra_notes: list[str] = [f"intake_key:{d.key}"]
                if d.earliest_start and d.earliest_start > as_of:
                    ghost_as_of = d.earliest_start
                    extra_notes.append(f"等料至{d.earliest_start.isoformat()}再开工")
                plan, load = _plan_route_item(
                    order_id=oid,
                    order_no=d.order_no,
                    delivery_date=d.delivery_date,
                    is_rush=d.is_rush,
                    total_qty=d.total_qty,
                    first_kit_ok=d.first_kit_ok,
                    kit_ok=d.kit_ok,
                    processes=specs,
                    strategy=plan_strategy,
                    as_of=ghost_as_of,
                    days_map=days_map,
                    default_days=default_days,
                    tight_days=tight_days,
                    require_first_kit=False,
                    cfg=cfg,
                    base_load=load,
                    priority_score=_priority_score_intake(d, as_of=as_of),
                )
                plan.notes = [*extra_notes, *plan.notes]
                plans.append(plan)
                continue
            o = real_orders.get(oid)
            if not o:
                continue
            summary = ctx.summary_for_order(o.id) if ctx else {"kit_ok": True, "first_kit_ok": True}
            first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
            plan, load = _plan_route_item(
                order_id=o.id,
                order_no=o.order_no,
                delivery_date=o.delivery_date,
                is_rush=bool(o.is_rush),
                total_qty=int(o.total_qty or 0),
                first_kit_ok=first_ok,
                kit_ok=bool(summary.get("kit_ok")),
                processes=procs_by_order.get(o.id) or [],
                strategy=plan_strategy,
                as_of=as_of,
                days_map=days_map,
                default_days=default_days,
                tight_days=tight_days,
                require_first_kit=False,
                cfg=cfg,
                base_load=load,
                priority_score=_priority_score(o, first_ok, as_of=as_of),
            )
            plans.append(plan)
        return plans

    out: list[dict[str, Any]] = []
    for strategy, title, ids in variants:
        plan_strategy: Literal["delivery_first", "capacity_first"] = (
            "capacity_first" if strategy == "protect_floor" else "delivery_first"
        )
        if plan_strategy == "capacity_first":
            base_finish = base_finish_capacity
            base_risk = base_risk_capacity
        else:
            base_finish = base_finish_delivery
            base_risk = base_risk_delivery
        plans = _run_sequence(ids, plan_strategy)
        impacts: list[dict[str, Any]] = []
        for p in plans:
            if p.order_id < 0:
                continue
            old_f = base_finish.get(p.order_id)
            new_f = p.projected_finish
            delay = None
            if old_f and new_f:
                delay = (new_f - old_f).days
            delay_days = int(delay or 0)
            old_r = base_risk.get(p.order_id)
            # 只报真实变差：延期，或风险等级升高（完工提前/风险变好不算「冲击」）
            worsened = delay_days > 0 or _risk_rank(p.risk) > _risk_rank(old_r or "ok")
            if worsened:
                impacts.append(
                    {
                        "order_id": p.order_id,
                        "order_no": p.order_no,
                        "old_finish": old_f.isoformat() if old_f else None,
                        "new_finish": new_f.isoformat() if new_f else None,
                        "delay_days": delay_days,
                        "old_risk": old_r,
                        "new_risk": p.risk,
                        "old_risk_label": risk_label_zh(old_r),
                        "new_risk_label": risk_label_zh(p.risk),
                    }
                )
        intake_plans = [p for p in plans if p.order_id < 0]
        intake_bits = []
        for p in intake_plans:
            intake_bits.append(
                f"{p.order_no}完工{p.projected_finish or '—'}（{risk_label_zh(p.risk)}）"
            )
        delayed = [i for i in impacts if int(i.get("delay_days") or 0) > 0]
        if delayed:
            impact_bit = (
                f"挤其它单 {len(delayed)} 张："
                + "、".join(
                    f"{i.get('order_no')}延{i.get('delay_days')}日" for i in delayed[:5]
                )
                + ("等" if len(delayed) > 5 else "")
            )
        elif impacts:
            impact_bit = (
                f"其它单风险上升 {len(impacts)} 处："
                + "、".join(str(i.get("order_no") or "") for i in impacts[:5] if i.get("order_no"))
                + ("等" if len(impacts) > 5 else "")
            )
        else:
            impact_bit = "未挤其它单"
        summary = (
            f"{title}。"
            + ("；".join(intake_bits) if intake_bits else "无接单计划")
            + f"；{impact_bit}。"
        )
        body = {
            "strategy": strategy,
            "as_of": as_of.isoformat(),
            "engine_version": ENGINE_VERSION,
            "intake_keys": [d.key for d, _, _ in ghost_routes],
            "orders": [p.to_dict() for p in plans],
        }
        prop = ScheduleProposal(
            proposal_id=_proposal_id(body),
            strategy=strategy,
            title=title,
            summary=summary,
            engine_version=ENGINE_VERSION,
            as_of=as_of,
            orders=plans,
            risks=_risk_counts(plans),
            load=[],
            impacts=impacts,
        )
        payload = prop.to_dict()
        payload["intake_orders"] = [p.to_dict() for p in intake_plans]
        out.append(payload)

    return {
        "sim_error": None,
        "message": None,
        "proposals": out,
        "engine_version": ENGINE_VERSION,
        "as_of": as_of.isoformat(),
        "demand_count": len(normalized),
    }


def generate_proposals(
    db: Session,
    tenant_id: int,
    *,
    order_ids: list[int] | None = None,
    hide_scheduled: bool = True,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """生成 2～3 套可对比方案（纯规则，无 AI）。"""
    as_of = as_of or date.today()
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    candidates = collect_candidate_orders(
        db,
        tenant_id,
        order_ids=order_ids,
        hide_scheduled=hide_scheduled,
        hide_first_kit_blocked=False,
        as_of=as_of,
    )
    if not candidates:
        return []

    selected_ids = [c["order_id"] for c in candidates]
    kit_ids = [c["order_id"] for c in candidates if c["first_kit_ok"]]

    strategies: list[tuple[str, str, str, list[int]]] = [
        (
            "delivery_first",
            "保交期",
            "按交期/急单倒排；产能超限仅标红不主动后移",
            selected_ids,
        ),
        (
            "capacity_first",
            "保现场",
            "从今天正排并顺延避产能冲突；可能推迟交期",
            selected_ids,
        ),
    ]
    if kit_ids and len(kit_ids) < len(selected_ids):
        strategies.append(
            (
                "kit_ready",
                "只排齐套",
                "仅纳入首道已齐套订单；缺料单进待料说明",
                kit_ids,
            )
        )

    proposals: list[ScheduleProposal] = []
    horizon_to = as_of + timedelta(days=45)
    capacity_configured = schedule_settings.capacity_is_configured(cfg)
    for strategy, title, blurb, ids in strategies:
        plans = _plan_orders(
            db, tenant_id, ids, strategy=strategy, as_of=as_of, cfg=cfg  # type: ignore[arg-type]
        )
        all_windows = [w for p in plans for w in p.windows]
        load = _build_load_snapshot(all_windows, cfg, date_from=as_of, date_to=horizon_to)
        risks = _risk_counts(plans)
        late_n = risks.get("late", 0) + risks.get("capacity_blocked", 0)
        summary = (
            f"{blurb}。共{len(plans)}单；偏紧/逾期相关 {late_n + risks.get('tight', 0)} 单"
            f"（预计逾期{risks.get('late', 0)}、交期偏紧{risks.get('tight', 0)}、"
            f"产能不足{risks.get('capacity_blocked', 0)}、缺料卡住{risks.get('kit_blocked', 0)}）。"
        )
        if not capacity_configured:
            summary = (
                "未配置日产能：仅按交期/工期排序，未校验是否超产能。" + summary
            )
        if strategy == "kit_ready":
            skipped = [c["order_no"] for c in candidates if not c["first_kit_ok"]]
            if skipped:
                summary += f" 待料未排：{', '.join(skipped[:8])}" + (
                    "…" if len(skipped) > 8 else ""
                )

        body = {
            "strategy": strategy,
            "as_of": as_of.isoformat(),
            "order_ids": ids,
            "engine_version": ENGINE_VERSION,
            "capacity_configured": capacity_configured,
            "orders": [p.to_dict() for p in plans],
        }
        prop = ScheduleProposal(
            proposal_id=_proposal_id(body),
            strategy=strategy,
            title=title,
            summary=summary,
            engine_version=ENGINE_VERSION,
            as_of=as_of,
            orders=plans,
            risks=risks,
            load=load,
        )
        proposals.append(prop)

    return [p.to_dict() for p in proposals]


def daily_load(
    db: Session,
    tenant_id: int,
    *,
    date_from: date,
    date_to: date,
    include_draft_orders: bool = True,
) -> dict[str, Any]:
    """日负荷：已确认排产 + 可选待排倒排预估。"""
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    windows = _load_existing_windows(db, tenant_id)
    if include_draft_orders:
        candidates = collect_candidate_orders(
            db, tenant_id, hide_scheduled=True, hide_first_kit_blocked=False
        )
        ids = [c["order_id"] for c in candidates]
        if ids:
            plans = _plan_orders(
                db,
                tenant_id,
                ids,
                strategy="delivery_first",
                as_of=date_from,
                cfg=cfg,
            )
            windows = windows + [w for p in plans for w in p.windows]
    rows = _build_load_snapshot(windows, cfg, date_from=date_from, date_to=date_to)
    bottlenecks = [r for r in rows if r.get("over_capacity")]
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "items": rows,
        "bottlenecks": bottlenecks,
        "engine_version": ENGINE_VERSION,
    }


def simulate_insert(
    db: Session,
    tenant_id: int,
    insert_order_id: int,
    *,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """插单仿真：保交期 / 保现场 / 折中，附影响清单。"""
    as_of = as_of or date.today()
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    insert = db.get(Order, insert_order_id)
    if not insert or insert.tenant_id != tenant_id:
        raise ValueError("order_not_found")

    candidates = collect_candidate_orders(
        db, tenant_id, hide_scheduled=False, hide_first_kit_blocked=False, as_of=as_of
    )
    # 冲击对比必须同排法：保交期对照 delivery_first，保现场对照 capacity_first。
    base_ids = [c["order_id"] for c in candidates if c["order_id"] != insert_order_id]
    base_plans_delivery = (
        _plan_orders(db, tenant_id, base_ids, strategy="delivery_first", as_of=as_of, cfg=cfg)
        if base_ids
        else []
    )
    base_plans_capacity = (
        _plan_orders(db, tenant_id, base_ids, strategy="capacity_first", as_of=as_of, cfg=cfg)
        if base_ids
        else []
    )
    base_finish_delivery = {p.order_id: p.projected_finish for p in base_plans_delivery}
    base_risk_delivery = {p.order_id: p.risk for p in base_plans_delivery}
    base_finish_capacity = {p.order_id: p.projected_finish for p in base_plans_capacity}
    base_risk_capacity = {p.order_id: p.risk for p in base_plans_capacity}

    variants: list[tuple[str, str, list[int]]] = [
        (
            "protect_delivery",
            "保交期（插单置顶）",
            [insert_order_id] + base_ids,
        ),
        (
            "protect_floor",
            "保现场（插单置后）",
            base_ids + [insert_order_id],
        ),
        (
            "compromise",
            "折中（急单后、未齐套前）",
            _compromise_order(candidates, insert_order_id),
        ),
    ]

    out: list[dict[str, Any]] = []
    for strategy, title, ids in variants:
        plan_strategy: Literal["delivery_first", "capacity_first"] = (
            "capacity_first" if strategy == "protect_floor" else "delivery_first"
        )
        if plan_strategy == "capacity_first":
            base_finish = base_finish_capacity
            base_risk = base_risk_capacity
        else:
            base_finish = base_finish_delivery
            base_risk = base_risk_delivery
        plans = _plan_orders(
            db, tenant_id, ids, strategy=plan_strategy, as_of=as_of, cfg=cfg
        )
        impacts: list[dict[str, Any]] = []
        for p in plans:
            if p.order_id == insert_order_id:
                continue
            old_f = base_finish.get(p.order_id)
            new_f = p.projected_finish
            delay = None
            if old_f and new_f:
                delay = (new_f - old_f).days
            delay_days = int(delay or 0)
            old_r = base_risk.get(p.order_id)
            worsened = delay_days > 0 or _risk_rank(p.risk) > _risk_rank(old_r or "ok")
            if worsened:
                impacts.append(
                    {
                        "order_id": p.order_id,
                        "order_no": p.order_no,
                        "old_finish": old_f.isoformat() if old_f else None,
                        "new_finish": new_f.isoformat() if new_f else None,
                        "delay_days": delay_days,
                        "old_risk": old_r,
                        "new_risk": p.risk,
                        "old_risk_label": risk_label_zh(old_r),
                        "new_risk_label": risk_label_zh(p.risk),
                    }
                )
        insert_plan = next((p for p in plans if p.order_id == insert_order_id), None)
        body = {
            "strategy": strategy,
            "insert_order_id": insert_order_id,
            "as_of": as_of.isoformat(),
            "engine_version": ENGINE_VERSION,
            "orders": [p.to_dict() for p in plans],
        }
        delayed = [i for i in impacts if int(i.get("delay_days") or 0) > 0]
        if delayed:
            impact_bit = (
                f"挤其它单 {len(delayed)} 张："
                + "、".join(
                    f"{i.get('order_no')}延{i.get('delay_days')}日" for i in delayed[:5]
                )
                + ("等" if len(delayed) > 5 else "")
            )
        elif impacts:
            impact_bit = (
                f"其它单风险上升 {len(impacts)} 处："
                + "、".join(str(i.get("order_no") or "") for i in impacts[:5] if i.get("order_no"))
                + ("等" if len(impacts) > 5 else "")
            )
        else:
            impact_bit = "未挤其它单"
        summary = (
            f"{title}。插单 {insert.order_no} 预计完工 "
            f"{insert_plan.projected_finish if insert_plan else '—'}，"
            f"{risk_label_zh(insert_plan.risk if insert_plan else None)}；"
            f"{impact_bit}。"
        )
        prop = ScheduleProposal(
            proposal_id=_proposal_id(body),
            strategy=strategy,
            title=title,
            summary=summary,
            engine_version=ENGINE_VERSION,
            as_of=as_of,
            orders=plans,
            risks=_risk_counts(plans),
            load=[],
            impacts=impacts,
        )
        out.append(prop.to_dict())
    return out


def _compromise_order(candidates: list[dict[str, Any]], insert_id: int) -> list[int]:
    rush = [c["order_id"] for c in candidates if c["is_rush"] and c["order_id"] != insert_id]
    ready = [
        c["order_id"]
        for c in candidates
        if c["first_kit_ok"] and not c["is_rush"] and c["order_id"] != insert_id
    ]
    rest = [
        c["order_id"]
        for c in candidates
        if c["order_id"] not in set(rush + ready + [insert_id])
    ]
    return rush + [insert_id] + ready + rest


def proposal_to_draft_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    """把方案转成 create_draft 可用的结构化输入。"""
    lines: list[dict[str, Any]] = []
    order_ids: list[int] = []
    for o in proposal.get("orders") or []:
        order_ids.append(int(o["order_id"]))
        for w in o.get("windows") or []:
            lines.append(
                {
                    "order_id": int(o["order_id"]),
                    "order_process_id": int(w["order_process_id"]),
                    "process_id": int(w["process_id"]),
                    "process_name": w["process_name"],
                    "plan_qty": int(w["plan_qty"]),
                    "start_date": w["start_date"],
                    "end_date": w["end_date"],
                    "risk": w.get("risk") or o.get("risk"),
                }
            )
    return {
        "proposal_id": proposal.get("proposal_id"),
        "strategy": proposal.get("strategy"),
        "order_ids": order_ids,
        "lines": lines,
        "summary": proposal.get("summary"),
        "engine_version": proposal.get("engine_version") or ENGINE_VERSION,
    }


def explain_capacity_need(plan_qty: int, days: int) -> int:
    """均分到工作日后的日占用量（向上取整）。"""
    days = max(1, int(days))
    return int(ceil(max(0, int(plan_qty)) / days))
