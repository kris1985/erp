"""AU-I3：按款排产池 HITL + 急单冲击未开工交期。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    ExecutionScheduleDraft,
    ExecutionScheduleDraftStatus,
    Order,
    OwnProduct,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
)
from app.services.execution_service import (
    ExecutionError,
    create_execution,
    execution_is_started,
    execution_out,
    list_producible,
)


class ExecutionScheduleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def list_color_pool(
    db: Session,
    *,
    tenant_id: int,
    own_product_id: int | None = None,
    kit_ready_only: bool = False,
) -> list[dict]:
    """排产主输入：待排款色码池（包装 list_producible）。"""
    return list_producible(
        db,
        tenant_id=tenant_id,
        own_product_id=own_product_id,
        kit_ready_only=kit_ready_only,
    )


def _draft_out(row: ExecutionScheduleDraft) -> dict[str, Any]:
    payload = row.payload or {}
    proposals = list(payload.get("proposals") or [])
    return {
        "id": row.id,
        "status": _enum_val(row.status),
        "note": row.note,
        "groups": list(payload.get("groups") or []),
        "group_count": len(payload.get("groups") or []),
        "total_qty": int(payload.get("total_qty") or 0),
        "jobs": list(payload.get("jobs") or []),
        "job_count": len(payload.get("jobs") or []),
        "strategy": payload.get("strategy") or "delivery_first",
        "recommended_strategy": payload.get("recommended_strategy"),
        "proposals": proposals,
        "overrides": dict(payload.get("overrides") or {}),
        "rush_impact": payload.get("rush_impact"),
        "is_rush": bool(payload.get("is_rush")),
        "plan_error": payload.get("plan_error"),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
    }


def get_draft(db: Session, tenant_id: int, draft_id: int) -> ExecutionScheduleDraft:
    row = db.get(ExecutionScheduleDraft, draft_id)
    if not row or row.tenant_id != tenant_id:
        raise ExecutionScheduleError("draft_not_found", "色码排产草案不存在")
    return row


def propose_draft(
    db: Session,
    *,
    tenant_id: int,
    selections: list[dict],
    note: str | None = None,
    created_by: int | None = None,
    is_rush: bool = False,
    split_style_keys: list[str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """按选择生成草案：同规格合并为一组；确认前不占 allocated_qty。

    split_style_keys：这些款色按客户拆成多条，不合成一刀。未列出的款色仍按同款同色合并。
    """
    if not selections:
        raise ExecutionScheduleError("empty_items", "请至少选择一条色码需求")

    seen: set[int] = set()
    resolved: list[tuple[SalesOrderLineItem, SalesOrderLine, SalesOrder, int]] = []
    for raw in selections:
        try:
            lid = int(raw.get("sales_order_line_item_id") or 0)
            qty = int(raw.get("qty") or 0)
        except (TypeError, ValueError) as e:
            raise ExecutionScheduleError("invalid_item", "分配行无效") from e
        if lid <= 0 or qty <= 0:
            raise ExecutionScheduleError("invalid_item", "分配行 line_item_id/qty 无效")
        if lid in seen:
            raise ExecutionScheduleError("duplicate_item", f"色码行重复：{lid}")
        seen.add(lid)
        item = db.get(SalesOrderLineItem, lid)
        if not item or item.tenant_id != tenant_id:
            raise ExecutionScheduleError("line_item_not_found", f"色码行不存在：{lid}")
        line = db.get(SalesOrderLine, item.sales_order_line_id)
        if not line or line.tenant_id != tenant_id:
            raise ExecutionScheduleError("line_not_found", "销售行不存在")
        so = db.get(SalesOrder, line.sales_order_id)
        if not so or so.tenant_id != tenant_id:
            raise ExecutionScheduleError("sales_order_not_found", "销售单不存在")
        remaining = int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0)
        if qty > remaining:
            raise ExecutionScheduleError(
                "over_remaining",
                f"色码行 {lid} 剩余可产 {remaining}，无法排 {qty}",
            )
        resolved.append((item, line, so, qty))

    split_keys = {str(x).strip() for x in (split_style_keys or []) if str(x).strip()}
    groups_map: dict[tuple, dict] = {}
    for item, line, so, qty in resolved:
        color_id = item.color_id if item.color_id is not None else line.color_id
        style_key = _style_job_key(line.own_product_id, color_id)
        cust_key = _customer_key(so.customer_name, so.id)
        split = style_key in split_keys
        key = (line.own_product_id, color_id, item.size_id, cust_key if split else None)
        g = groups_map.get(key)
        if not g:
            product = db.get(OwnProduct, line.own_product_id)
            color = db.get(Color, color_id) if color_id else None
            size = db.get(Size, item.size_id)
            cust_name = (so.customer_name or "").strip() or so.order_no
            g = {
                "own_product_id": line.own_product_id,
                "product_code": product.product_code if product else None,
                "color_id": color_id,
                "color_name": color.name if color else None,
                "size_id": item.size_id,
                "size_value": size.size_value if size else None,
                "customer_key": cust_key if split else None,
                "customer_name": cust_name if split else None,
                "job_key": _style_job_key(line.own_product_id, color_id, cust_key if split else None),
                "total_qty": 0,
                "items": [],
            }
            groups_map[key] = g
        g["items"].append(
            {
                "sales_order_line_item_id": item.id,
                "sales_order_id": so.id,
                "sales_order_no": so.order_no,
                "sales_order_line_id": line.id,
                "customer_name": so.customer_name,
                "delivery_date": line.delivery_date.isoformat()
                if line.delivery_date
                else (so.ordered_at.isoformat() if so.ordered_at else None),
                "qty": qty,
                "remaining_qty": int(item.qty or 0) - int(getattr(item, "allocated_qty", 0) or 0),
            }
        )
        g["total_qty"] += qty

    groups = list(groups_map.values())
    _recompute_group_ratios(groups)

    payload = {
        "groups": groups,
        "total_qty": sum(int(g["total_qty"]) for g in groups),
        "selection_count": len(resolved),
        "is_rush": bool(is_rush),
        "split_style_keys": sorted(split_keys),
    }
    _attach_virtual_plan(db, tenant_id, payload, is_rush=bool(is_rush))
    row = ExecutionScheduleDraft(
        tenant_id=tenant_id,
        status=ExecutionScheduleDraftStatus.draft,
        note=note,
        payload=payload,
        created_by=created_by,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def _recompute_group_ratios(groups: list[dict]) -> None:
    for g in groups:
        items = list(g.get("items") or [])
        total = sum(int(it.get("qty") or 0) for it in items)
        g["total_qty"] = total
        g["items"] = items
        acc = Decimal("0")
        for i, it in enumerate(items):
            if total <= 0:
                it["ratio"] = 0.0
                continue
            if i == len(items) - 1:
                ratio = (Decimal("1") - acc).quantize(Decimal("0.00000001"))
            else:
                ratio = (Decimal(it["qty"]) / Decimal(total)).quantize(Decimal("0.00000001"))
                acc += ratio
            it["ratio"] = float(ratio)


def _customer_key(customer_name, sales_order_id=None) -> str:
    s = str(customer_name or "").strip()
    if s:
        return s
    sid = int(sales_order_id or 0)
    return f"so:{sid}" if sid else "unknown"


def _style_job_key(own_product_id, color_id, customer_key=None) -> str:
    cid = color_id if color_id is not None else "none"
    base = f"{int(own_product_id)}-{cid}"
    ck = str(customer_key or "").strip()
    return f"{base}::{ck}" if ck else base


def _group_job_key(g: dict) -> str:
    if g.get("job_key"):
        return str(g["job_key"])
    return _style_job_key(g.get("own_product_id"), g.get("color_id"), g.get("customer_key"))


def _jobs_from_groups(db: Session, tenant_id: int, groups: list[dict]) -> list[dict[str, Any]]:
    from app.services.material_service import estimate_sku_kit_hint

    styles: dict[str, dict[str, Any]] = {}
    for g in groups:
        key = _group_job_key(g)
        job = styles.get(key)
        if not job:
            code = g.get("product_code") or ""
            color = g.get("color_name") or ""
            cust = (g.get("customer_name") or "").strip()
            label = f"{code} {color}".strip() or key
            if cust:
                label = f"{label} · {cust}".strip()
            job = {
                "key": key,
                "own_product_id": int(g.get("own_product_id") or 0),
                "color_id": g.get("color_id"),
                "product_code": g.get("product_code"),
                "color_name": g.get("color_name"),
                "customer_key": g.get("customer_key"),
                "customer_name": cust or None,
                "label": label,
                "total_qty": 0,
                "delivery_date": None,
                "is_rush": False,
                "size_summary": [],
                "sources": {},
            }
            styles[key] = job
        job["total_qty"] += int(g.get("total_qty") or 0)
        src_map = job["sources"]
        for it in g.get("items") or []:
            sid = int(it.get("sales_order_id") or 0)
            if sid <= 0:
                continue
            src = src_map.get(sid)
            if not src:
                src = {
                    "sales_order_id": sid,
                    "sales_order_no": it.get("sales_order_no"),
                    "customer_name": it.get("customer_name"),
                    "qty": 0,
                    "delivery_date": it.get("delivery_date"),
                }
                src_map[sid] = src
            src["qty"] += int(it.get("qty") or 0)
            dd = it.get("delivery_date")
            cur = src.get("delivery_date")
            if dd and (not cur or str(dd)[:10] < str(cur)[:10]):
                src["delivery_date"] = dd
        d = _group_delivery(g)
        cur = job["delivery_date"]
        if d and (cur is None or (isinstance(cur, date) and d < cur) or (
            isinstance(cur, str) and d < date.fromisoformat(str(cur)[:10])
        )):
            job["delivery_date"] = d
        sv = g.get("size_value")
        if sv:
            job["size_summary"].append(f"{sv}×{int(g.get('total_qty') or 0)}")
    out = []
    for job in styles.values():
        hint = estimate_sku_kit_hint(
            db,
            tenant_id,
            own_product_id=int(job["own_product_id"]),
            qty=int(job["total_qty"]),
            color_id=int(job["color_id"]) if job.get("color_id") is not None else None,
        )
        job["kit_hint"] = hint
        job["first_kit_ok"] = hint == "ready"
        job["kit_ok"] = hint == "ready"
        if isinstance(job["delivery_date"], date):
            job["delivery_date"] = job["delivery_date"].isoformat()
        job["size_summary"] = " ".join(job["size_summary"])
        job["sources"] = sorted(
            job["sources"].values(),
            key=lambda s: (str(s.get("customer_name") or ""), int(s.get("sales_order_id") or 0)),
        )
        if not job.get("customer_name"):
            names = {
                str(s.get("customer_name") or "").strip()
                for s in job["sources"]
                if str(s.get("customer_name") or "").strip()
            }
            if len(names) == 1:
                job["customer_name"] = next(iter(names))
        out.append(job)
    return out


def _recommend_strategy(proposals: list[dict]) -> str:
    if not proposals:
        return "delivery_first"
    def _score(p: dict) -> tuple:
        r = p.get("risks") or {}
        return (
            int(r.get("late") or 0) + int(r.get("capacity_blocked") or 0),
            int(r.get("late") or 0),
            0 if p.get("strategy") == "delivery_first" else 1,
        )
    return str(min(proposals, key=_score).get("strategy") or "delivery_first")


def _attach_windows(jobs: list[dict], proposal: dict | None) -> list[dict]:
    by_key = {o.get("job_key"): o for o in (proposal or {}).get("orders") or []}
    out = []
    for job in jobs:
        plan = by_key.get(job.get("key")) or {}
        out.append(
            {
                **job,
                "windows": list(plan.get("windows") or []),
                "risk": plan.get("risk"),
                "risk_label": plan.get("risk_label"),
                "projected_finish": plan.get("projected_finish"),
                "notes": list(plan.get("notes") or []),
            }
        )
    return out


def _assert_capacity_configured(db: Session, tenant_id: int, jobs: list[dict]) -> None:
    """强制先配：工序未配单人日产能时拒绝出方案（排产页内联补填后再试）。"""
    from app.models import OrderProcess, ProcessDefinition

    pid_set: set[int] = set()
    for j in jobs:
        if j.get("order_id"):
            for p in db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == int(j["order_id"])
                )
            ).all():
                if p.process_id:
                    pid_set.add(int(p.process_id))
        elif j.get("header_id"):
            from app.services.material_service import list_header_processes

            for p in list_header_processes(db, tenant_id, int(j["header_id"])):
                if p.process_id:
                    pid_set.add(int(p.process_id))
    if not pid_set:
        return
    procs = db.scalars(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == tenant_id, ProcessDefinition.id.in_(list(pid_set))
        )
    ).all()
    missing = [
        p for p in procs
        if p.per_worker_capacity is None or (p.per_worker_capacity or 0) <= 0
    ]
    if missing:
        names = "、".join(p.name for p in missing[:8])
        more = f" 等{len(missing)}道" if len(missing) > 8 else ""
        raise ExecutionScheduleError(
            "capacity_missing",
            f"以下工序未配置单人日产能：{names}{more}，请先补齐后再出方案",
        )


def _attach_virtual_plan(db: Session, tenant_id: int, payload: dict, *, strategy: str | None = None, is_rush: bool | None = None) -> None:
    from app.services import schedule_engine

    jobs = _jobs_from_groups(db, tenant_id, list(payload.get("groups") or []))
    _assert_capacity_configured(db, tenant_id, jobs)
    rush = bool(payload.get("is_rush") if is_rush is None else is_rush)
    payload["is_rush"] = rush
    if rush:
        for j in jobs:
            j["is_rush"] = True
    planned = schedule_engine.generate_virtual_proposals(db, tenant_id, jobs)
    proposals = list(planned.get("items") or [])
    payload["plan_error"] = planned.get("message") if planned.get("sim_error") else None
    payload["proposals"] = proposals
    chosen = strategy or _recommend_strategy(proposals)
    if chosen not in {p.get("strategy") for p in proposals} and proposals:
        chosen = str(proposals[0].get("strategy") or "delivery_first")
    payload["strategy"] = chosen
    payload["recommended_strategy"] = _recommend_strategy(proposals)
    picked = next((p for p in proposals if p.get("strategy") == chosen), proposals[0] if proposals else None)
    payload["jobs"] = _attach_windows(jobs, picked)
    _attach_rush_impact(db, tenant_id, payload)


def select_draft_strategy(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    strategy: str,
    commit: bool = True,
) -> dict[str, Any]:
    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可切换方案")
    payload = dict(row.payload or {})
    proposals = list(payload.get("proposals") or [])
    picked = next((p for p in proposals if p.get("strategy") == strategy), None)
    if not picked:
        raise ExecutionScheduleError("unknown_strategy", "没有这套方案")
    jobs = [
        {k: v for k, v in j.items() if k not in ("windows", "risk", "risk_label", "projected_finish", "notes")}
        for j in (payload.get("jobs") or [])
    ]
    if not jobs:
        jobs = _jobs_from_groups(db, tenant_id, list(payload.get("groups") or []))
    payload["strategy"] = strategy
    payload["overrides"] = {}
    payload["jobs"] = _attach_windows(jobs, picked)
    _attach_rush_impact(db, tenant_id, payload)
    row.payload = payload
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def shift_draft_job(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    job_key: str,
    cut_start: date,
    commit: bool = True,
) -> dict[str, Any]:
    """拖改开裁日：整单平移窗口，重算当前方案负荷。不写执行单。"""
    from app.services import schedule_calendar as scal
    from app.services import schedule_engine, schedule_settings

    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可改期")
    payload = dict(row.payload or {})
    jobs = [dict(j) for j in (payload.get("jobs") or [])]
    job = next((j for j in jobs if str(j.get("key")) == str(job_key)), None)
    if not job:
        raise ExecutionScheduleError("unknown_job", "方案里没有这一款")
    windows_raw = list(job.get("windows") or [])
    if not windows_raw:
        raise ExecutionScheduleError("no_windows", "这一款还没有工序窗口")

    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    tight_days = int(cfg.get("tight_days") or 2)
    with scal.use_schedule_calendar(cfg):
        target = scal.next_workday(cut_start)
        es = _parse_iso_date(job.get("earliest_start"))
        if es and target < es:
            target = scal.next_workday(es)
        today = date.today()
        if target < today:
            target = scal.next_workday(today)
        windows = schedule_engine.process_windows_from_dicts(windows_raw)
        shifted = schedule_engine.shift_windows_to_cut_start(windows, target)
        dd = _parse_iso_date(job.get("delivery_date"))
        plan = schedule_engine.OrderPlan(
            order_id=None,
            header_id=None,
            job_key=str(job.get("key")),
            order_no=str(job.get("label") or job.get("key") or ""),
            delivery_date=dd,
            is_rush=bool(job.get("is_rush")),
            total_qty=int(job.get("total_qty") or 0),
            first_kit_ok=bool(job.get("first_kit_ok", True)),
            kit_ok=bool(job.get("kit_ok", job.get("first_kit_ok", True))),
            priority_score=0,
            windows=shifted,
            earliest_start=es,
        )
        plan = schedule_engine._aggregate_order_risk(
            plan, tight_days=tight_days, require_first_kit=False
        )

    job["windows"] = [w.to_dict() for w in plan.windows]
    job["risk"] = plan.risk
    job["risk_label"] = schedule_engine.risk_label_zh(plan.risk)
    job["projected_finish"] = (
        plan.projected_finish.isoformat() if plan.projected_finish else None
    )
    job["notes"] = list(plan.notes or [])
    overrides = dict(payload.get("overrides") or {})
    overrides[str(job_key)] = {"cut_start": target.isoformat()}
    payload["overrides"] = overrides
    payload["jobs"] = jobs
    _refresh_proposal_after_shift(db, tenant_id, payload, cfg)
    _attach_rush_impact(db, tenant_id, payload)
    row.payload = payload
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def patch_draft_job_process(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    job_key: str,
    process_id: int,
    start_date: date | None = None,
    days: int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """草稿内单道工序微调：改开始日 / 改天数（其它工序不动，纯人工覆盖）。

    对应甘特条子直接编辑"从哪天开始、排多少天"。不做级联平移；
    改完重算风险并做工序链自检提示（重叠不硬拦，PMC 说了算）。
    """
    from app.services import schedule_calendar as scal
    from app.services import schedule_engine, schedule_settings

    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可改")
    if start_date is None and days is None:
        raise ExecutionScheduleError("empty_patch", "请提供开始日期或天数")
    payload = dict(row.payload or {})
    jobs = [dict(j) for j in (payload.get("jobs") or [])]
    job = next((j for j in jobs if str(j.get("key")) == str(job_key)), None)
    if not job:
        raise ExecutionScheduleError("unknown_job", "方案里没有这一款")
    windows_raw = list(job.get("windows") or [])
    win = next(
        (w for w in windows_raw if int(w.get("process_id") or 0) == int(process_id)), None
    )
    if not win:
        raise ExecutionScheduleError("unknown_process", "方案里没有这道工序")

    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    tight_days = int(cfg.get("tight_days") or 2)
    with scal.use_schedule_calendar(cfg):
        es = _parse_iso_date(job.get("earliest_start"))
        today = date.today()
        if start_date is not None:
            target = scal.next_workday(start_date)
            if es and target < es:
                target = scal.next_workday(es)
            if target < today:
                target = scal.next_workday(today)
            ndays = max(1, int(days or win.get("days") or 1))
            new_start, new_end = scal.workday_span_starting(target, ndays)
            win["start_date"] = new_start.isoformat()
            win["end_date"] = new_end.isoformat()
            win["days"] = ndays
        else:
            ndays = max(1, int(days or 1))
            cur = _parse_iso_date(win.get("start_date"))
            if not cur:
                raise ExecutionScheduleError("no_start", "这道工序还没有开始日期")
            _s, new_end = scal.workday_span_starting(cur, ndays)
            win["end_date"] = new_end.isoformat()
            win["days"] = ndays

    windows = schedule_engine.process_windows_from_dicts(windows_raw)
    dd = _parse_iso_date(job.get("delivery_date"))
    plan = schedule_engine.OrderPlan(
        order_id=None,
        header_id=None,
        job_key=str(job.get("key")),
        order_no=str(job.get("label") or job.get("key") or ""),
        delivery_date=dd,
        is_rush=bool(job.get("is_rush")),
        total_qty=int(job.get("total_qty") or 0),
        first_kit_ok=bool(job.get("first_kit_ok", True)),
        kit_ok=bool(job.get("kit_ok", job.get("first_kit_ok", True))),
        priority_score=0,
        windows=windows,
        earliest_start=es,
    )
    plan = schedule_engine._aggregate_order_risk(
        plan, tight_days=tight_days, require_first_kit=False
    )
    notes = list(plan.notes or [])
    for i in range(1, len(windows)):
        if windows[i - 1].end_date >= windows[i].start_date:
            notes.append(
                f"{windows[i - 1].process_name}完工({windows[i - 1].end_date})"
                f"与{windows[i].process_name}开工({windows[i].start_date})重叠/倒挂，请注意"
            )
    job["windows"] = [w.to_dict() for w in windows]
    job["risk"] = plan.risk
    job["risk_label"] = schedule_engine.risk_label_zh(plan.risk)
    job["projected_finish"] = (
        plan.projected_finish.isoformat() if plan.projected_finish else None
    )
    job["notes"] = notes
    payload["jobs"] = jobs
    _refresh_proposal_after_shift(db, tenant_id, payload, cfg)
    _attach_rush_impact(db, tenant_id, payload)
    row.payload = payload
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def drop_draft_sources(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    job_key: str,
    sales_order_ids: list[int],
    commit: bool = True,
) -> dict[str, Any]:
    """从草稿某一款剔除销售来源，当场重算条子和负荷。不改本次数量。"""
    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可剔除来源")
    drop: set[int] = set()
    for raw in sales_order_ids:
        try:
            sid = int(raw)
        except (TypeError, ValueError) as e:
            raise ExecutionScheduleError("invalid_source", "销售来源无效") from e
        if sid > 0:
            drop.add(sid)
    if not drop:
        raise ExecutionScheduleError("empty_sources", "请选择要剔除的销售来源")

    payload = dict(row.payload or {})
    groups = list(payload.get("groups") or [])
    key = str(job_key)
    if not any(_group_job_key(g) == key for g in groups):
        raise ExecutionScheduleError("unknown_job", "方案里没有这一款")

    hit = False
    new_groups: list[dict] = []
    for g in groups:
        if _group_job_key(g) != key:
            new_groups.append(dict(g))
            continue
        kept = []
        for it in g.get("items") or []:
            sid = int(it.get("sales_order_id") or 0)
            if sid in drop:
                hit = True
                continue
            kept.append(dict(it))
        if not kept:
            continue
        ng = dict(g)
        ng["items"] = kept
        new_groups.append(ng)
    if not hit:
        raise ExecutionScheduleError("source_not_on_job", "这一款没有该销售来源")
    if not new_groups:
        raise ExecutionScheduleError("empty_groups", "至少留一个来源，或丢弃整份方案")

    _recompute_group_ratios(new_groups)
    payload["groups"] = new_groups
    payload["total_qty"] = sum(int(g["total_qty"]) for g in new_groups)
    payload["selection_count"] = sum(len(g.get("items") or []) for g in new_groups)
    payload["overrides"] = {}
    _attach_virtual_plan(
        db,
        tenant_id,
        payload,
        strategy=payload.get("strategy"),
        is_rush=payload.get("is_rush"),
    )
    row.payload = payload
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def _refresh_proposal_after_shift(
    db: Session,
    tenant_id: int,
    payload: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    from datetime import timedelta as _td

    from app.services import schedule_engine

    strategy = payload.get("strategy") or "delivery_first"
    jobs = list(payload.get("jobs") or [])
    proposals = list(payload.get("proposals") or [])
    picked = next((p for p in proposals if p.get("strategy") == strategy), None)
    if not picked:
        return
    picked = dict(picked)
    by_key = {str(j.get("key")): j for j in jobs}
    orders = []
    for o in list(picked.get("orders") or []):
        job = by_key.get(str(o.get("job_key") or ""))
        if job:
            o = dict(o)
            o["windows"] = list(job.get("windows") or [])
            o["risk"] = job.get("risk")
            o["risk_label"] = job.get("risk_label")
            o["projected_finish"] = job.get("projected_finish")
            o["notes"] = list(job.get("notes") or [])
        orders.append(o)
    picked["orders"] = orders
    as_of = date.today()
    try:
        as_of = date.fromisoformat(str(picked.get("as_of") or "")[:10])
    except ValueError:
        pass
    horizon_to = as_of + _td(days=45)
    cap_map = schedule_engine._process_capacity_map(db, tenant_id, cfg)
    draft_windows = schedule_engine.process_windows_from_dicts(
        [w for j in jobs for w in (j.get("windows") or [])]
    )
    load = schedule_engine._build_load_snapshot(
        draft_windows, cfg, date_from=as_of, date_to=horizon_to, cap_map=cap_map
    )
    issued = schedule_engine._load_existing_windows(db, tenant_id)
    if issued:
        issued_load = schedule_engine._build_load_snapshot(
            issued, cfg, date_from=as_of, date_to=horizon_to, cap_map=cap_map
        )
        load = schedule_engine._merge_load_snapshots(issued_load, load)
    picked["load"] = load
    risks = {"ok": 0, "tight": 0, "late": 0, "kit_blocked": 0, "capacity_blocked": 0}
    for j in jobs:
        r = str(j.get("risk") or "ok")
        if r not in risks:
            r = "ok"
        risks[r] = risks.get(r, 0) + 1
    picked["risks"] = risks
    over_days = sum(1 for row in load if row.get("over_capacity"))
    picked["summary"] = (
        f"已按开裁日手改。共{len(jobs)}款色"
        f"（预计逾期{risks.get('late', 0)}、交期偏紧{risks.get('tight', 0)}、"
        f"产能冲突{risks.get('capacity_blocked', 0)}；超产{over_days}天）。"
    )
    payload["proposals"] = [
        picked if p.get("strategy") == strategy else p for p in proposals
    ]


def _parse_iso_date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _group_delivery(g: dict) -> date | None:
    dates = [_parse_iso_date(it.get("delivery_date")) for it in (g.get("items") or [])]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def _apply_job_windows(
    db: Session,
    tenant_id: int,
    header_by_job: dict[str, int],
    jobs: list[dict],
) -> bool:
    """把人看过的工序窗写到执行单头。无窗口则返回 False，由倒排兜底。"""
    from app.models import ExecutionHeader
    from app.services import material_service

    by_key = {str(j.get("key")): j for j in jobs if j.get("key")}
    wrote = False
    for job_key, hid in header_by_job.items():
        job = by_key.get(str(job_key))
        windows = list((job or {}).get("windows") or [])
        if not windows:
            continue
        header = db.get(ExecutionHeader, hid)
        if not header or header.tenant_id != tenant_id:
            continue
        procs = material_service.list_header_processes(db, tenant_id, header.id)
        if not procs:
            procs = material_service.ensure_header_processes(
                db, tenant_id=tenant_id, header=header, delivery_date=header.delivery_date
            )
        by_pid = {int(w["process_id"]): w for w in windows if w.get("process_id")}
        for proc in procs:
            w = by_pid.get(int(proc.process_id))
            if not w:
                continue
            start = _parse_iso_date(w.get("start_date"))
            end = _parse_iso_date(w.get("end_date"))
            if start:
                proc.start_date = start
            if end:
                proc.end_date = end
            wrote = True
    if wrote:
        db.flush()
    return wrote


def _apply_backward_dates(db: Session, tenant_id: int, header_ids: list[int]) -> None:
    """按交期给执行单头工序写入倒排开工/完工日（确认排产一次完成）。"""
    if not header_ids:
        return
    from app.models import ExecutionHeader
    from app.services import material_service, schedule_engine, schedule_settings
    from app.services.schedule_service import _backward_windows

    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    cap_map = schedule_engine._process_capacity_map(db, tenant_id, cfg)
    seen: set[int] = set()
    for hid in header_ids:
        if not hid or hid in seen:
            continue
        seen.add(hid)
        header = db.get(ExecutionHeader, hid)
        if not header or header.tenant_id != tenant_id:
            continue
        procs = material_service.list_header_processes(db, tenant_id, header.id)
        if not procs:
            procs = material_service.ensure_header_processes(
                db, tenant_id=tenant_id, header=header, delivery_date=header.delivery_date
            )
        if not procs:
            continue
        windows = _backward_windows(
            procs,
            header.delivery_date,
            cap_map=cap_map,
        )
        for proc, (start, end) in zip(procs, windows):
            proc.start_date = start
            proc.end_date = end
    db.flush()


def confirm_production(
    db: Session,
    *,
    tenant_id: int,
    selections: list[dict],
    note: str | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    """一次确认排产：合单落执行单 + 按交期倒排工序日。"""
    draft = propose_draft(
        db,
        tenant_id=tenant_id,
        selections=selections,
        note=note or "确认排产",
        created_by=created_by,
        commit=False,
    )
    return confirm_draft(
        db,
        tenant_id=tenant_id,
        draft_id=int(draft["id"]),
        created_by=created_by,
    )


def discard_draft(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    commit: bool = True,
) -> dict[str, Any]:
    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可丢弃")
    row.status = ExecutionScheduleDraftStatus.discarded
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _draft_out(row)


def confirm_draft(
    db: Session,
    *,
    tenant_id: int,
    draft_id: int,
    created_by: int | None = None,
    dispatch: dict | None = None,
) -> dict[str, Any]:
    """dispatch: {job_key: {process_id: [worker_id, ...]}} —— 确认下发时一并落派工。"""
    """确认草案：各组 create_execution；失败整单回滚。"""
    row = get_draft(db, tenant_id, draft_id)
    if _enum_val(row.status) != ExecutionScheduleDraftStatus.draft.value:
        raise ExecutionScheduleError("invalid_status", "仅草案可确认落生产单")

    groups = list((row.payload or {}).get("groups") or [])
    if not groups:
        raise ExecutionScheduleError("empty_groups", "草案无分组")

    executions_out: list[dict] = []
    header_by_job: dict[str, int] = {}
    try:
        for g in groups:
            items = [
                {
                    "sales_order_line_item_id": int(it["sales_order_line_item_id"]),
                    "qty": int(it["qty"]),
                }
                for it in (g.get("items") or [])
            ]
            job_key = _group_job_key(g)
            exe = create_execution(
                db,
                tenant_id=tenant_id,
                items=items,
                created_by=created_by or row.created_by,
                notes=row.note or f"确认排产 #{row.id}",
                delivery_date=_group_delivery(g),
                commit=False,
                header_id=header_by_job.get(job_key),
            )
            if exe.header_id:
                header_by_job[job_key] = int(exe.header_id)
            executions_out.append(execution_out(db, exe))
        jobs = list((row.payload or {}).get("jobs") or [])
        applied = _apply_job_windows(db, tenant_id, header_by_job, jobs)
        if not applied:
            _apply_backward_dates(db, tenant_id, list(header_by_job.values()))
        if (row.payload or {}).get("is_rush"):
            for exe in executions_out:
                sid = exe.get("id")
                if not sid:
                    continue
                soe = db.get(SpecExecutionOrder, int(sid))
                if soe and soe.tenant_id == tenant_id:
                    soe.is_rush = True
        _apply_rush_impact_locked(db, tenant_id, (row.payload or {}).get("rush_impact"))
        _apply_dispatch(db, tenant_id, header_by_job, dispatch or {})
        row.status = ExecutionScheduleDraftStatus.confirmed
        row.confirmed_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
    except ExecutionError as e:
        db.rollback()
        raise ExecutionScheduleError(e.code, e.message) from e
    except Exception:
        db.rollback()
        raise

    header_ids = {x.get("header_id") for x in executions_out if x.get("header_id")}
    from app.models import ExecutionHeader
    from app.services.execution_service import header_out

    headers_out = []
    for hid in header_ids:
        header = db.get(ExecutionHeader, hid)
        if header:
            headers_out.append(header_out(db, header))
    return {
        **_draft_out(row),
        "executions": executions_out,
        "execution_count": len(executions_out),
        "header_count": len(header_ids),
        "headers": headers_out,
    }


def _apply_dispatch(
    db: Session,
    tenant_id: int,
    header_by_job: dict[str, int],
    dispatch: dict,
) -> None:
    """确认下发时按 (job_key, process_id) 写入工序派工。"""
    if not dispatch:
        return
    from app.models import ExecutionHeader, OrderProcess
    from app.services import assignment_service

    for job_key, procs in (dispatch or {}).items():
        header_id = header_by_job.get(str(job_key))
        if not header_id:
            continue
        header = db.get(ExecutionHeader, header_id)
        if not header or not header.shop_order_id:
            continue
        order_id = int(header.shop_order_id)
        for pid_str, worker_ids in (procs or {}).items():
            if not worker_ids:
                continue
            proc = db.scalar(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id,
                    OrderProcess.order_id == order_id,
                    OrderProcess.process_id == int(pid_str),
                )
            )
            if not proc:
                continue
            try:
                assignment_service.replace_process_assignments(
                    db,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    process=proc,
                    items=[(int(wid), None, 1) for wid in worker_ids],
                    commit=False,
                )
            except Exception:
                continue


def _window_span(windows: list[dict]) -> tuple[date | None, date | None]:
    starts = [_parse_iso_date(w.get("start_date")) for w in windows]
    ends = [_parse_iso_date(w.get("end_date")) for w in windows]
    starts = [d for d in starts if d]
    ends = [d for d in ends if d]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _write_header_windows(
    db: Session,
    tenant_id: int,
    header_id: int,
    windows: list[dict],
) -> bool:
    from app.models import ExecutionHeader
    from app.services import material_service

    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        return False
    procs = material_service.list_header_processes(db, tenant_id, header.id)
    if not procs:
        return False
    by_pid = {int(w["process_id"]): w for w in windows if w.get("process_id")}
    wrote = False
    for proc in procs:
        w = by_pid.get(int(proc.process_id))
        if not w:
            continue
        start = _parse_iso_date(w.get("start_date"))
        end = _parse_iso_date(w.get("end_date"))
        if start:
            proc.start_date = start
        if end:
            proc.end_date = end
        # A'档排产依据快照：dict 携带才写（平移/急单挤压不带则不覆盖已存值）
        if w.get("source"):
            proc.capacity_source = str(w["source"])[:20]
        if w.get("active_workers") is not None:
            try:
                proc.capacity_active_workers = max(1, int(w["active_workers"]))
            except (TypeError, ValueError):
                pass
        if w.get("avg_per_head") is not None:
            try:
                proc.capacity_avg_per_head = Decimal(str(w["avg_per_head"]))
            except (TypeError, ValueError, ArithmeticError):
                pass
        if w.get("efficiency") is not None:
            try:
                proc.capacity_efficiency = Decimal(str(w["efficiency"]))
            except (TypeError, ValueError, ArithmeticError):
                pass
        wrote = True
    if wrote:
        db.flush()
    return wrote


def _compute_rush_impact(
    db: Session,
    tenant_id: int,
    *,
    rush_windows: list[dict],
    rush_label: str,
    exclude_header_id: int | None = None,
    push_workdays: int = 3,
) -> dict[str, Any]:
    from app.services import schedule_calendar as scal
    from app.services import schedule_engine, schedule_settings

    if push_workdays < 1 or push_workdays > 60:
        raise ExecutionScheduleError("invalid_push_days", "延期工作日须在 1～60")
    rush_start, rush_end = _window_span(rush_windows)
    if not rush_start or not rush_end:
        return {
            "insert": {"label": rush_label, "windows": rush_windows},
            "push_workdays": push_workdays,
            "impacts": [],
            "frozen": [],
            "unaffected": [],
            "warning": "急单还没有工序窗口，无法计算冲击",
        }
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    issued = _load_open_header_rows(db, tenant_id)
    impacts: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    unaffected: list[dict[str, Any]] = []
    with scal.use_schedule_calendar(cfg):
        for row in issued:
            hid = int(row.get("header_id") or 0)
            if not hid or (exclude_header_id and hid == exclude_header_id):
                continue
            brief = {
                "header_id": hid,
                "header_no": row.get("header_no"),
                "product_code": row.get("product_code"),
                "color_name": row.get("color_name"),
                "status": row.get("status"),
                "windows": list(row.get("windows") or []),
            }
            wins = schedule_engine.process_windows_from_dicts(list(row.get("windows") or []))
            if not wins:
                unaffected.append({**brief, "note": "无工序窗"})
                continue
            peer_end = max(w.end_date for w in wins)
            if peer_end < rush_start:
                unaffected.append({**brief, "note": "已在急单之前结束"})
                continue
            if row.get("locked") or row.get("status") in ("cut", "in_progress"):
                frozen.append({**brief, "freeze_reason": "已开裁，日期不动"})
                continue
            new_start = scal.add_workdays(wins[0].start_date, push_workdays)
            shifted = schedule_engine.shift_windows_to_cut_start(wins, new_start)
            impacts.append(
                {
                    **brief,
                    "old_windows": [w.to_dict() for w in wins],
                    "windows": [w.to_dict() for w in shifted],
                    "delay_workdays": push_workdays,
                }
            )
    return {
        "insert": {
            "label": rush_label,
            "header_id": exclude_header_id,
            "windows": rush_windows,
            "will_mark_rush": True,
        },
        "push_workdays": push_workdays,
        "impacts": impacts,
        "frozen": frozen,
        "unaffected": unaffected,
        "warning": (
            f"{len(impacts)} 张未开裁生产单将推迟 {push_workdays} 个工作日；"
            f"{len(frozen)} 张已开裁日期不动"
        ),
    }


def _attach_rush_impact(db: Session, tenant_id: int, payload: dict[str, Any]) -> None:
    jobs = list(payload.get("jobs") or [])
    rush_jobs = [j for j in jobs if j.get("is_rush")]
    if not rush_jobs:
        payload["rush_impact"] = None
        return
    windows = [w for j in rush_jobs for w in (j.get("windows") or [])]
    label = "、".join(
        str(j.get("label") or j.get("product_code") or j.get("key") or "")
        for j in rush_jobs
    )
    payload["rush_impact"] = _compute_rush_impact(
        db,
        tenant_id,
        rush_windows=windows,
        rush_label=label or "急单",
        push_workdays=int(payload.get("push_workdays") or 3),
    )


def _apply_rush_impact_locked(db: Session, tenant_id: int, impact: dict | None) -> None:
    from app.models import ExecutionHeader

    if not impact:
        return
    for row in impact.get("impacts") or []:
        hid = int(row.get("header_id") or 0)
        if not hid:
            continue
        header = db.get(ExecutionHeader, hid)
        if not header or header.tenant_id != tenant_id:
            raise ExecutionScheduleError("peer_not_found", "冲击目标生产单不存在")
        st = header.status.value if hasattr(header.status, "value") else str(header.status)
        if st in ("cut", "in_progress", "completed"):
            raise ExecutionScheduleError(
                "peer_started",
                f"{header.header_no} 已开裁，禁止改工序日",
            )
        _write_header_windows(db, tenant_id, hid, list(row.get("windows") or []))
        new_end = _window_span(list(row.get("windows") or []))[1]
        if new_end and header.delivery_date and header.delivery_date < new_end:
            header.delivery_date = new_end


def preview_header_rush(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    push_workdays: int = 3,
) -> dict[str, Any]:
    from app.models import ExecutionHeader

    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise ExecutionScheduleError("header_not_found", "生产单不存在")
    st = header.status.value if hasattr(header.status, "value") else str(header.status)
    if st in ("cancelled", "completed"):
        raise ExecutionScheduleError("header_closed", "已完成/取消的生产单不能插急")
    if st in ("cut", "in_progress"):
        raise ExecutionScheduleError("header_started", "已开裁的生产单不能插急改别人日期")
    issued = _load_open_header_rows(db, tenant_id)
    row = next((x for x in issued if int(x.get("header_id") or 0) == header_id), None)
    windows = list((row or {}).get("windows") or [])
    if not windows:
        raise ExecutionScheduleError("no_windows", "这张生产单还没有工序窗口")
    return _compute_rush_impact(
        db,
        tenant_id,
        rush_windows=windows,
        rush_label=header.header_no,
        exclude_header_id=header.id,
        push_workdays=push_workdays,
    )


def confirm_header_rush(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    push_workdays: int = 3,
    reason: str | None = None,
) -> dict[str, Any]:
    sim = preview_header_rush(
        db, tenant_id=tenant_id, header_id=header_id, push_workdays=push_workdays
    )
    from app.models import ExecutionHeader

    header = db.get(ExecutionHeader, header_id)
    assert header is not None
    _apply_rush_impact_locked(db, tenant_id, sim)
    for sl in list(header.size_lines or []) or list(
        db.scalars(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    ):
        sl.is_rush = True
        sl.rush_reason = (reason or "甘特插急单")[:255]
        sl.rushed_at = datetime.utcnow()
    db.commit()
    return {**sim, "applied": sim.get("impacts") or []}


def shift_issued_header(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    cut_start: date,
    commit: bool = True,
) -> dict[str, Any]:
    """未开裁执行单改开裁日：整单平移工序窗口。已开裁禁止。"""
    from app.models import ExecutionHeader
    from app.services import material_service
    from app.services import schedule_calendar as scal
    from app.services import schedule_engine, schedule_settings

    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise ExecutionScheduleError("header_not_found", "生产单不存在")
    st = header.status.value if hasattr(header.status, "value") else str(header.status)
    if st in ("cancelled", "completed"):
        raise ExecutionScheduleError("header_closed", "已完成/取消的生产单不能改排")
    if st in ("cut", "in_progress"):
        raise ExecutionScheduleError("header_started", "已开裁不能改开裁日；请去生产单停产或减产")
    procs = material_service.list_header_processes(db, tenant_id, header.id)
    windows_raw = [
        {
            "process_id": p.process_id,
            "process_name": p.process_name,
            "plan_qty": int(p.plan_qty or 0),
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
        }
        for p in procs
        if p.start_date and p.end_date
    ]
    if not windows_raw:
        raise ExecutionScheduleError("no_windows", "这张生产单还没有工序窗口")

    old_start = _parse_iso_date(windows_raw[0].get("start_date"))
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    with scal.use_schedule_calendar(cfg):
        target = scal.next_workday(cut_start)
        today = date.today()
        if target < today:
            target = scal.next_workday(today)
        windows = schedule_engine.process_windows_from_dicts(windows_raw)
        shifted = schedule_engine.shift_windows_to_cut_start(windows, target)
    new_windows = [w.to_dict() for w in shifted]
    _write_header_windows(db, tenant_id, header.id, new_windows)
    new_end = _window_span(new_windows)[1]
    if new_end and header.delivery_date and header.delivery_date < new_end:
        header.delivery_date = new_end
    if commit:
        db.commit()
        db.refresh(header)
    else:
        db.flush()
    new_start = _parse_iso_date(new_windows[0].get("start_date")) if new_windows else None
    return {
        "header_id": header.id,
        "header_no": header.header_no,
        "old_cut_start": old_start.isoformat() if old_start else None,
        "cut_start": new_start.isoformat() if new_start else None,
        "windows": new_windows,
    }


def withdraw_issued_header(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
) -> dict[str, Any]:
    """未开裁撤回下发：取消执行单，数量回到待排池。"""
    from app.models import ExecutionHeader
    from app.services.execution_service import cancel_execution

    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise ExecutionScheduleError("header_not_found", "生产单不存在")
    st = header.status.value if hasattr(header.status, "value") else str(header.status)
    if st in ("cancelled",):
        raise ExecutionScheduleError("header_closed", "生产单已取消")
    if st in ("cut", "in_progress", "completed"):
        raise ExecutionScheduleError("header_started", "已开裁不能撤回；请去生产单停产")
    lines = list(header.size_lines or []) or list(
        db.scalars(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    )
    cancelled = 0
    try:
        for sl in lines:
            st_sl = sl.status.value if hasattr(sl.status, "value") else str(sl.status)
            if st_sl == "cancelled":
                continue
            cancel_execution(db, tenant_id=tenant_id, execution_id=sl.id, commit=False)
            cancelled += 1
    except ExecutionError as e:
        db.rollback()
        raise ExecutionScheduleError(e.code, e.message) from e
    header.status = SpecExecutionStatus.cancelled
    db.commit()
    return {
        "header_id": header.id,
        "header_no": header.header_no,
        "status": "cancelled",
        "cancelled_lines": cancelled,
    }


_GANTT_OPEN = (
    SpecExecutionStatus.confirmed,
    SpecExecutionStatus.cut,
    SpecExecutionStatus.in_progress,
)


def _load_open_header_rows(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """已下发执行单头 + 完整工序窗。冲击预览不裁切日期，甘特展示再裁。"""
    from sqlalchemy.orm import selectinload

    from app.models import ExecutionHeader
    from app.services import material_service

    headers = list(
        db.scalars(
            select(ExecutionHeader)
            .where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.status.in_(_GANTT_OPEN),
            )
            .options(selectinload(ExecutionHeader.size_lines))
            .order_by(ExecutionHeader.id)
            .limit(200)
        ).all()
    )
    product_ids = {h.own_product_id for h in headers}
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_(product_ids or [0]),
            )
        ).all()
    } if product_ids else {}
    color_ids = {h.color_id for h in headers if h.color_id}
    colors = {
        c.id: c
        for c in db.scalars(
            select(Color).where(Color.tenant_id == tenant_id, Color.id.in_(color_ids or [0]))
        ).all()
    } if color_ids else {}

    issued: list[dict[str, Any]] = []
    for h in headers:
        procs = material_service.list_header_processes(db, tenant_id, h.id)
        windows: list[dict[str, Any]] = []
        for p in procs:
            if not p.start_date or not p.end_date:
                continue
            if date_from and p.end_date < date_from:
                continue
            if date_to and p.start_date > date_to:
                continue
            windows.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "plan_qty": int(p.plan_qty or 0),
                    "completed_qty": int(p.completed_qty or 0),
                    "start_date": p.start_date.isoformat(),
                    "end_date": p.end_date.isoformat(),
                    "status": p.status.value if hasattr(p.status, "value") else str(p.status or ""),
                    # A'档排产依据快照（确认下发时写入；旧数据回退 standard）
                    "source": p.capacity_source or "standard",
                    "active_workers": p.capacity_active_workers,
                    "avg_per_head": (
                        float(p.capacity_avg_per_head) if p.capacity_avg_per_head is not None else None
                    ),
                    "efficiency": (
                        float(p.capacity_efficiency) if p.capacity_efficiency is not None else None
                    ),
                }
            )
        if not windows:
            continue
        product = products.get(h.own_product_id)
        color = colors.get(h.color_id) if h.color_id else None
        st = h.status.value if hasattr(h.status, "value") else str(h.status)
        issued.append(
            {
                "key": f"h:{h.id}",
                "kind": "issued",
                "header_id": h.id,
                "header_no": h.header_no,
                "own_product_id": h.own_product_id,
                "color_id": h.color_id,
                "product_code": product.product_code if product else None,
                "color_name": color.name if color else None,
                "total_qty": int(h.total_qty or 0),
                "delivery_date": h.delivery_date.isoformat() if h.delivery_date else None,
                "status": st,
                "locked": st in ("cut", "in_progress"),
                "is_rush": any(bool(getattr(sl, "is_rush", False)) for sl in (h.size_lines or [])),
                "windows": windows,
            }
        )
    issued.sort(
        key=lambda j: (
            min((w["start_date"] for w in j["windows"]), default=""),
            int(j["header_id"]),
        )
    )
    return issued


def list_gantt_board(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """已下发执行单头画在工作日上。只认 header，避免壳生产单再画一次。"""
    from app.services import schedule_calendar as scal
    from app.services import schedule_settings
    from app.utils.cn_holidays import day_info

    today = date.today()
    date_from = date_from or (today - timedelta(days=2))
    date_to = date_to or (today + timedelta(days=35))
    if date_to < date_from:
        raise ExecutionScheduleError("invalid_range", "结束日期不能早于开始日期")
    if (date_to - date_from).days > 62:
        raise ExecutionScheduleError("range_too_long", "查询跨度请不超过 62 天")

    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    days: list[dict[str, Any]] = []
    workdays: list[dict[str, Any]] = []
    with scal.use_schedule_calendar(cfg):
        cur = date_from
        while cur <= date_to:
            meta = day_info(cur)
            work = scal.is_workday(cur)
            blackout = scal.is_blackout(cur)
            row = {
                "date": cur.isoformat(),
                "workday": work,
                "is_weekend": bool(meta.get("is_weekend")),
                "is_holiday": bool(meta.get("is_holiday")),
                "is_blackout": blackout,
                "is_off": not work,
                "is_makeup": bool(meta.get("is_makeup_workday")),
                "label": "停工" if blackout else meta.get("label"),
            }
            days.append(row)
            if work:
                workdays.append(row)
            cur += timedelta(days=1)

    issued = _load_open_header_rows(db, tenant_id, date_from=date_from, date_to=date_to)
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "days": days,
        "workdays": workdays,
        "issued": issued,
    }


# ----- I3-M2：急单冲击未开工交期 -----
# execution_is_started 定义在 execution_service（M3 改量/禁改码共用）


def _exe_brief(db: Session, exe: SpecExecutionOrder) -> dict[str, Any]:
    product = db.get(OwnProduct, exe.own_product_id)
    return {
        "execution_id": exe.id,
        "execution_no": exe.execution_no,
        "product_code": product.product_code if product else None,
        "total_qty": int(exe.total_qty or 0),
        "status": _enum_val(exe.status),
        "delivery_date": exe.delivery_date.isoformat() if exe.delivery_date else None,
        "is_rush": bool(getattr(exe, "is_rush", False)),
        "started": execution_is_started(db, exe),
    }


def simulate_rush_insert(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    push_days: int = 3,
) -> dict[str, Any]:
    """急单插队仿真：仅未开工且交期≥急单交期的执行单延后；已开工冻结。"""
    if push_days < 1 or push_days > 60:
        raise ExecutionScheduleError("invalid_push_days", "延期天数须在 1～60")
    insert = db.get(SpecExecutionOrder, execution_id)
    if not insert or insert.tenant_id != tenant_id:
        raise ExecutionScheduleError("execution_not_found", "生产单不存在")
    if _enum_val(insert.status) == SpecExecutionStatus.cancelled.value:
        raise ExecutionScheduleError("execution_cancelled", "已取消生产单不可插队")

    insert_d = insert.delivery_date or date.today()
    peers = list(
        db.scalars(
            select(SpecExecutionOrder)
            .where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.id != insert.id,
                SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
            )
            .order_by(SpecExecutionOrder.delivery_date, SpecExecutionOrder.id)
        ).all()
    )

    impacts: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    unaffected: list[dict[str, Any]] = []
    for p in peers:
        brief = _exe_brief(db, p)
        if execution_is_started(db, p):
            frozen.append({**brief, "freeze_reason": "已开工，交期不动"})
            continue
        if p.delivery_date is None:
            unaffected.append({**brief, "note": "无交期，不调整"})
            continue
        if p.delivery_date < insert_d:
            unaffected.append({**brief, "note": "交期早于急单，不受冲击"})
            continue
        new_d = p.delivery_date + timedelta(days=push_days)
        impacts.append(
            {
                **brief,
                "old_delivery_date": p.delivery_date.isoformat(),
                "new_delivery_date": new_d.isoformat(),
                "delay_days": push_days,
            }
        )

    return {
        "insert": {
            **_exe_brief(db, insert),
            "will_mark_rush": True,
            "anchor_delivery_date": insert_d.isoformat(),
        },
        "push_days": push_days,
        "impacts": impacts,
        "frozen": frozen,
        "unaffected": unaffected,
        "warning": (
            f"{len(impacts)} 张未开工生产单交期将延后 {push_days} 天；"
            f"{len(frozen)} 张已开工交期不动"
        ),
    }


def confirm_rush_insert(
    db: Session,
    *,
    tenant_id: int,
    execution_id: int,
    push_days: int = 3,
    reason: str | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    """确认急单冲击：标记急单；仅改未开工交期（再校验已开工）。"""
    sim = simulate_rush_insert(
        db, tenant_id=tenant_id, execution_id=execution_id, push_days=push_days
    )
    insert = db.get(SpecExecutionOrder, execution_id)
    assert insert is not None

    for row in sim["impacts"]:
        peer = db.get(SpecExecutionOrder, int(row["execution_id"]))
        if not peer or peer.tenant_id != tenant_id:
            raise ExecutionScheduleError("peer_not_found", "冲击目标生产单不存在")
        if execution_is_started(db, peer):
            raise ExecutionScheduleError(
                "peer_started",
                f"生产单 {peer.execution_no} 已开工，禁止改交期",
            )

    insert.is_rush = True
    insert.rush_reason = (reason or "排产急单插队")[:255]
    insert.rushed_at = datetime.utcnow()
    if insert.shop_order_id:
        shop = db.get(Order, insert.shop_order_id)
        if shop and shop.tenant_id == tenant_id:
            shop.is_rush = True
            shop.rush_reason = insert.rush_reason
            shop.rushed_at = insert.rushed_at

    applied: list[dict[str, Any]] = []
    for row in sim["impacts"]:
        peer = db.get(SpecExecutionOrder, int(row["execution_id"]))
        if not peer:
            continue
        new_d = date.fromisoformat(row["new_delivery_date"])
        peer.delivery_date = new_d
        if peer.shop_order_id:
            shop = db.get(Order, peer.shop_order_id)
            if shop and shop.tenant_id == tenant_id:
                shop.delivery_date = new_d
        applied.append(
            {
                "execution_id": peer.id,
                "execution_no": peer.execution_no,
                "old_delivery_date": row["old_delivery_date"],
                "new_delivery_date": row["new_delivery_date"],
                "delay_days": row["delay_days"],
            }
        )

    db.commit()
    db.refresh(insert)
    return {
        **sim,
        "confirmed": True,
        "applied": applied,
        "insert": _exe_brief(db, insert),
        "confirmed_by": created_by,
    }
