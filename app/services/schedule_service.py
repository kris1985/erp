"""排产建议草稿：倒排时间窗 + 派工拆量草稿 → 人工确认 → 写 OrderProcess 日期与 assignment。

确认前不改派工/报工/材料占用。不上甘特拖拽。
派工草稿仅支持整工序粒度；色码/捆仍走订单派工。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    MergeBatch,
    MergeBatchMember,
    MergeBatchStatus,
    Order,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    ProcessType,
    ScheduleDraft,
    ScheduleDraftAssignment,
    ScheduleDraftLine,
    ScheduleDraftStatus,
    ScheduleStatus,
    WorkLog,
    WorkLogStatus,
    Worker,
)
from app.services import assignment_service, material_service, schedule_engine, schedule_settings
from app.services import team_service
from app.utils.cn_holidays import prev_workday, workday_span_ending

# 粗工期：每道工序默认占用天数（中小厂可先固定，后期接节拍）
DEFAULT_PROCESS_DAYS = 1
# 自动建议派工：取该工序近期报过工的工人上限
SUGGEST_WORKER_LIMIT = 6


class ScheduleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _open_statuses() -> list[OrderStatus]:
    return [OrderStatus.confirmed, OrderStatus.in_progress]


def list_schedule_pool(
    db: Session,
    tenant_id: int,
    *,
    keyword: str | None = None,
    rush_only: bool = False,
    hide_first_kit_blocked: bool = False,
    hide_scheduled: bool = True,
    merge_batch_id: int | None = None,
) -> list[dict]:
    """待排池：已确认/生产中的 MO。

    默认隐藏已全部排完（schedule_status=scheduled）的单；改期/重排可传 hide_scheduled=False。
    merge_batch_id：仅显示该合批的成员生产单（P1-4）。
    """
    q = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.status.in_(_open_statuses()),
    )
    if hide_scheduled:
        q = q.where(Order.schedule_status != ScheduleStatus.scheduled)
    if rush_only:
        q = q.where(Order.is_rush.is_(True))
    if merge_batch_id is not None:
        member_ids = list(
            db.scalars(
                select(MergeBatchMember.order_id).where(
                    MergeBatchMember.tenant_id == tenant_id,
                    MergeBatchMember.batch_id == int(merge_batch_id),
                )
            ).all()
        )
        if not member_ids:
            return []
        q = q.where(Order.id.in_(member_ids))
    if keyword and keyword.strip():
        kw = keyword.strip()
        product_ids = list(
            db.scalars(
                select(OwnProduct.id).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.product_code.contains(kw),
                )
            ).all()
        )
        if product_ids:
            q = q.where(
                Order.order_no.contains(kw)
                | Order.customer_name.contains(kw)
                | Order.own_product_id.in_(product_ids)
            )
        else:
            q = q.where(Order.order_no.contains(kw) | Order.customer_name.contains(kw))
    orders = list(db.scalars(q.order_by(Order.is_rush.desc(), Order.delivery_date, Order.id)).all())
    if not orders:
        return []

    product_ids = {o.own_product_id for o in orders if o.own_product_id}
    product_map: dict[int, OwnProduct] = {}
    if product_ids:
        product_map = {
            p.id: p
            for p in db.scalars(
                select(OwnProduct).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.id.in_(product_ids),
                )
            ).all()
        }

    order_ids = [o.id for o in orders]
    batch_rows = db.execute(
        select(MergeBatchMember.order_id, MergeBatch.id, MergeBatch.batch_no)
        .join(MergeBatch, MergeBatch.id == MergeBatchMember.batch_id)
        .where(
            MergeBatchMember.tenant_id == tenant_id,
            MergeBatchMember.order_id.in_(order_ids),
            MergeBatch.status == MergeBatchStatus.open,
        )
    ).all()
    batch_by_order = {int(r[0]): (int(r[1]), str(r[2])) for r in batch_rows}

    for o in orders:
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id)
    out: list[dict] = []
    for o in orders:
        summary = ctx.summary_for_order(o.id)
        first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
        if hide_first_kit_blocked and not first_ok:
            continue
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == o.id)
                .order_by(OrderProcess.id)
            ).all()
        )
        scheduled_n = sum(1 for p in procs if p.start_date and p.end_date)
        product = product_map.get(o.own_product_id)
        bid, bno = batch_by_order.get(o.id, (None, None))
        out.append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "customer_name": o.customer_name,
                "own_product_id": o.own_product_id,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "total_qty": o.total_qty,
                "delivery_date": o.delivery_date,
                "is_rush": bool(o.is_rush),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "schedule_status": (
                    o.schedule_status.value
                    if getattr(o, "schedule_status", None) and hasattr(o.schedule_status, "value")
                    else str(getattr(o, "schedule_status", None) or "none")
                ),
                "kit_ok": bool(summary.get("kit_ok")),
                "first_kit_ok": first_ok,
                "first_process_name": summary.get("first_process_name"),
                "empty_bom": bool(summary.get("empty_bom")),
                "process_count": len(procs),
                "scheduled_process_count": scheduled_n,
                "merge_batch_id": bid,
                "merge_batch_no": bno,
            }
        )
    return out


def _backward_windows(
    processes: list[OrderProcess],
    delivery: date | None,
    *,
    days_per_process: int = DEFAULT_PROCESS_DAYS,
    days_by_process_id: dict[int, int] | None = None,
) -> list[tuple[date, date]]:
    """按路线倒序倒排（工作日）：末道完工落在交期（或今天+工序数）。"""
    n = len(processes)
    if n == 0:
        return []
    days_map = days_by_process_id or {}
    default_days = max(1, int(days_per_process))
    total = sum(max(1, int(days_map.get(p.process_id, default_days))) for p in processes)
    end = delivery or (date.today() + timedelta(days=total * 2))
    cursor_end = prev_workday(end)
    windows: list[tuple[date, date]] = [None] * n  # type: ignore
    for i in range(n - 1, -1, -1):
        days = max(1, int(days_map.get(processes[i].process_id, default_days)))
        start, end_d = workday_span_ending(cursor_end, days)
        windows[i] = (start, end_d)
        cursor_end = prev_workday(start - timedelta(days=1))
    return windows


def _worker_name_map(db: Session, tenant_id: int, worker_ids: set[int]) -> dict[int, str]:
    if not worker_ids:
        return {}
    return {
        w.id: w.name
        for w in db.scalars(
            select(Worker).where(Worker.tenant_id == tenant_id, Worker.id.in_(worker_ids))
        ).all()
    }


def _serialize_line_assignments(
    line: ScheduleDraftLine, name_map: dict[int, str]
) -> list[dict]:
    rows = sorted(line.assignments or [], key=lambda a: a.id)
    return [
        {
            "id": a.id,
            "worker_id": a.worker_id,
            "worker_name": name_map.get(a.worker_id),
            "quota_qty": a.quota_qty,
            "share_weight": a.share_weight,
        }
        for a in rows
    ]


def _infer_assignment_team(
    assignments: list[dict],
    team_by_worker: dict[int, dict],
) -> dict:
    """若派工人员同属一个班组，回填 team 提示（不持久化，便于 UI 展示）。"""
    if not assignments:
        return {}
    infos = []
    for a in assignments:
        info = team_by_worker.get(int(a["worker_id"]))
        if not info:
            return {}
        infos.append(info)
    tids = {int(i["team_id"]) for i in infos}
    if len(tids) != 1:
        return {}
    return {
        "team_id": next(iter(tids)),
        "team_name": infos[0].get("team_name"),
        "mode": "leader" if len(assignments) == 1 else "members",
    }


def _clear_line_assignments(db: Session, line: ScheduleDraftLine) -> None:
    for a in list(line.assignments or []):
        db.delete(a)
    db.flush()


def _set_line_assignment_rows(
    db: Session,
    tenant_id: int,
    line: ScheduleDraftLine,
    items: list[tuple[int, int | None, int | None]],
    *,
    equal_split: bool = False,
) -> None:
    """写入草稿派工行。equal_split=True 时按 plan_qty 均分配额。"""
    seen: set[int] = set()
    cleaned: list[tuple[int, int | None, int | None]] = []
    for wid, quota, weight in items:
        if wid in seen:
            continue
        seen.add(wid)
        worker = db.get(Worker, wid)
        if not worker or worker.tenant_id != tenant_id or not worker.is_active:
            raise ScheduleError("worker_not_found", f"工人不存在或未启用：{wid}")
        if quota is not None and int(quota) < 0:
            raise ScheduleError("invalid_quota", "配额不能为负")
        if weight is not None and int(weight) < 0:
            raise ScheduleError("invalid_weight", "分账权重不能为负")
        cleaned.append((wid, quota, weight if weight is not None else 1))

    if equal_split and cleaned:
        splits = assignment_service.split_equal_qty(line.plan_qty, len(cleaned))
        cleaned = [(wid, splits[i], weight) for i, (wid, _, weight) in enumerate(cleaned)]

    if cleaned:
        finite = [q for _, q, _ in cleaned if q is not None]
        if finite and all(q is not None for _, q, _ in cleaned):
            if sum(int(q) for q in finite) > int(line.plan_qty):
                raise ScheduleError(
                    "over_plan_quota",
                    f"{line.process_name}派工配额合计超过计划{line.plan_qty}",
                )

    _clear_line_assignments(db, line)
    for wid, quota, weight in cleaned:
        db.add(
            ScheduleDraftAssignment(
                tenant_id=tenant_id,
                draft_line_id=line.id,
                worker_id=wid,
                quota_qty=quota,
                share_weight=weight,
            )
        )
    db.flush()


def _suggest_workers_for_process(
    db: Session,
    tenant_id: int,
    process: OrderProcess,
) -> list[int]:
    """建议工人：优先拷贝已有整工序派工；否则取该工序近期报过工的活跃工人。"""
    existing = assignment_service.list_assignments(db, process.id)
    process_scope = [a for a in existing if assignment_service.is_process_scope(a)]
    if process_scope:
        return list(dict.fromkeys(a.worker_id for a in process_scope))

    # 已有色码/捆派工则不自动建议（避免覆盖精细派工）
    if existing:
        return []

    rows = db.execute(
        select(WorkLog.worker_id, WorkLog.created_at)
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.process_id == process.process_id,
            WorkLog.status == WorkLogStatus.valid,
        )
        .order_by(WorkLog.created_at.desc())
        .limit(80)
    ).all()
    ordered: list[int] = []
    for wid, _ in rows:
        if wid not in ordered:
            ordered.append(wid)
        if len(ordered) >= SUGGEST_WORKER_LIMIT:
            break
    if not ordered:
        return []
    active = {
        w.id
        for w in db.scalars(
            select(Worker).where(
                Worker.tenant_id == tenant_id,
                Worker.id.in_(ordered),
                Worker.is_active.is_(True),
            )
        ).all()
    }
    return [wid for wid in ordered if wid in active]


def _auto_fill_assignments_for_draft(db: Session, tenant_id: int, draft: ScheduleDraft) -> None:
    """生成草稿时自动拆量建议（可改可空）。"""
    for line in draft.lines or []:
        proc = db.get(OrderProcess, line.order_process_id)
        if not proc:
            continue
        existing = assignment_service.list_assignments(db, proc.id)
        process_scope = [a for a in existing if assignment_service.is_process_scope(a)]
        if process_scope:
            items = [
                (a.worker_id, a.quota_qty, a.share_weight if a.share_weight is not None else 1)
                for a in process_scope
            ]
            # 若原配额为空，按均分补一份建议配额，便于确认落库
            if all(q is None for _, q, _ in items):
                _set_line_assignment_rows(
                    db, tenant_id, line, [(w, None, wt) for w, _, wt in items], equal_split=True
                )
            else:
                _set_line_assignment_rows(db, tenant_id, line, items, equal_split=False)
            continue

        if existing:
            # 色码/捆已派：草稿不碰
            continue

        worker_ids = _suggest_workers_for_process(db, tenant_id, proc)
        ptype = proc.process_type
        if hasattr(ptype, "value"):
            ptype = ptype.value
        if ptype == ProcessType.group.value and len(worker_ids) < 2:
            continue
        if not worker_ids:
            continue
        items = [(wid, None, 1) for wid in worker_ids]
        _set_line_assignment_rows(db, tenant_id, line, items, equal_split=True)


def create_draft(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    user_id: int | None = None,
    note: str | None = None,
    process_ids: list[int] | None = None,
    days_per_process: int = DEFAULT_PROCESS_DAYS,
    auto_assign: bool = True,
) -> dict:
    if not order_ids:
        raise ScheduleError("empty", "请选择生产订单")
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_(order_ids),
                Order.status.in_(_open_statuses()),
            )
        ).all()
    )
    if len(orders) != len(set(order_ids)):
        raise ScheduleError("order_not_found", "部分订单不存在或不在可排状态")

    # 优先级：急单 → 交期近 → id
    orders.sort(key=lambda o: (0 if o.is_rush else 1, o.delivery_date or date.max, o.id))

    draft = ScheduleDraft(
        tenant_id=tenant_id,
        status=ScheduleDraftStatus.draft,
        note=note,
        created_by=user_id,
    )
    db.add(draft)
    db.flush()

    allow_procs = set(process_ids) if process_ids else None
    cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
    days_map = schedule_engine._process_days_map(db, tenant_id, cfg)
    fallback_days = max(1, int(days_per_process or cfg.get("default_process_days") or DEFAULT_PROCESS_DAYS))
    priority = 0
    for order in orders:
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order.id)
                .order_by(OrderProcess.id)
            ).all()
        )
        windows = _backward_windows(
            procs,
            order.delivery_date,
            days_per_process=fallback_days,
            days_by_process_id=days_map,
        )
        for p, (start, end) in zip(procs, windows):
            included = True if allow_procs is None else (p.process_id in allow_procs)
            db.add(
                ScheduleDraftLine(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    order_id=order.id,
                    order_process_id=p.id,
                    process_id=p.process_id,
                    process_name=p.process_name,
                    plan_qty=p.plan_qty,
                    start_date=start,
                    end_date=end,
                    sort_priority=priority,
                    included=included,
                )
            )
        order.schedule_status = ScheduleStatus.drafted
        priority += 1

    db.flush()
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft.id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    assert draft is not None
    if auto_assign:
        _auto_fill_assignments_for_draft(db, tenant_id, draft)

    db.commit()
    return get_draft(db, tenant_id, draft.id)


def create_draft_from_proposal(
    db: Session,
    tenant_id: int,
    proposal: dict,
    *,
    user_id: int | None = None,
    note: str | None = None,
    auto_assign: bool = True,
) -> dict:
    """将规则引擎方案写入排产草稿（仍须人工确认才落库）。"""
    payload = schedule_engine.proposal_to_draft_payload(proposal)
    order_ids = payload.get("order_ids") or []
    if not order_ids:
        raise ScheduleError("empty", "方案中没有订单")
    lines = payload.get("lines") or []
    if not lines:
        raise ScheduleError("empty", "方案中没有工序窗")

    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_(order_ids),
                Order.status.in_(_open_statuses()),
            )
        ).all()
    )
    if len(orders) != len(set(order_ids)):
        raise ScheduleError("order_not_found", "部分订单不存在或不在可排状态")

    meta = (
        f"[engine:{payload.get('engine_version')}|{payload.get('strategy')}|"
        f"{payload.get('proposal_id')}]"
    )
    draft_note = f"{meta} {note or payload.get('summary') or ''}".strip()
    draft = ScheduleDraft(
        tenant_id=tenant_id,
        status=ScheduleDraftStatus.draft,
        note=draft_note[:500],
        created_by=user_id,
    )
    db.add(draft)
    db.flush()

    # 保持方案内订单顺序
    order_rank = {oid: i for i, oid in enumerate(order_ids)}
    for ln in lines:
        oid = int(ln["order_id"])
        start = ln["start_date"]
        end = ln["end_date"]
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        db.add(
            ScheduleDraftLine(
                tenant_id=tenant_id,
                draft_id=draft.id,
                order_id=oid,
                order_process_id=int(ln["order_process_id"]),
                process_id=int(ln["process_id"]),
                process_name=ln.get("process_name") or "",
                plan_qty=int(ln.get("plan_qty") or 1),
                start_date=start,
                end_date=end,
                sort_priority=order_rank.get(oid, 0),
                included=True,
            )
        )
    for order in orders:
        order.schedule_status = ScheduleStatus.drafted

    db.flush()
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft.id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    assert draft is not None
    if auto_assign:
        _auto_fill_assignments_for_draft(db, tenant_id, draft)
    db.commit()
    return get_draft(db, tenant_id, draft.id)


def get_draft(db: Session, tenant_id: int, draft_id: int) -> dict:
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    lines = sorted(draft.lines, key=lambda x: (x.sort_priority, x.id))
    order_ids = sorted({ln.order_id for ln in lines})
    order_map = {
        o.id: o
        for o in db.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids or [0]))
        ).all()
    }
    product_ids = {o.own_product_id for o in order_map.values() if o.own_product_id}
    product_map: dict[int, OwnProduct] = {}
    if product_ids:
        product_map = {
            p.id: p
            for p in db.scalars(
                select(OwnProduct).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.id.in_(product_ids),
                )
            ).all()
        }
    kit_cache: dict[int, dict] = {}
    for oid in order_ids:
        try:
            kit_cache[oid] = material_service.get_order_kit(db, tenant_id, oid)
        except material_service.MaterialError:
            kit_cache[oid] = {}

    worker_ids = {a.worker_id for ln in lines for a in (ln.assignments or [])}
    name_map = _worker_name_map(db, tenant_id, worker_ids)
    team_by_worker = team_service.worker_team_map(db, tenant_id)

    op_ids = {ln.order_process_id for ln in lines}
    process_type_map: dict[int, str] = {}
    if op_ids:
        for op in db.scalars(select(OrderProcess).where(OrderProcess.id.in_(op_ids))).all():
            pt = op.process_type
            process_type_map[op.id] = pt.value if hasattr(pt, "value") else str(pt)

    line_out = []
    for ln in lines:
        order = order_map.get(ln.order_id)
        product = product_map.get(order.own_product_id) if order else None
        kit = kit_cache.get(ln.order_id) or {}
        by_proc = {x["process_id"]: x for x in kit.get("by_process") or []}
        proc_kit = by_proc.get(ln.process_id) or {}
        first_id = kit.get("first_process_id")
        is_first = first_id is not None and ln.process_id == first_id
        assignments = _serialize_line_assignments(ln, name_map)
        assigned_qty = sum(int(a["quota_qty"]) for a in assignments if a["quota_qty"] is not None)
        team_hint = _infer_assignment_team(assignments, team_by_worker)
        line_out.append(
            {
                "id": ln.id,
                "order_id": ln.order_id,
                "order_no": order.order_no if order else None,
                "customer_name": order.customer_name if order else None,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "delivery_date": order.delivery_date if order else None,
                "is_rush": bool(order.is_rush) if order else False,
                "order_process_id": ln.order_process_id,
                "process_id": ln.process_id,
                "process_name": ln.process_name,
                "process_type": process_type_map.get(ln.order_process_id, "personal"),
                "plan_qty": ln.plan_qty,
                "start_date": ln.start_date,
                "end_date": ln.end_date,
                "sort_priority": ln.sort_priority,
                "included": bool(ln.included),
                "is_first": is_first,
                "process_kit_ok": bool(proc_kit.get("kit_ok", True)) if proc_kit else True,
                "first_kit_ok": bool(kit.get("first_kit_ok", True)),
                "assignments": assignments,
                "assigned_qty": assigned_qty,
                "assignment_count": len(assignments),
                "team_id": team_hint.get("team_id"),
                "team_name": team_hint.get("team_name"),
                "team_assign_mode": team_hint.get("mode"),
            }
        )
    return {
        "id": draft.id,
        "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
        "note": draft.note,
        "created_by": draft.created_by,
        "confirmed_by": draft.confirmed_by,
        "confirmed_at": draft.confirmed_at,
        "created_at": draft.created_at,
        "lines": line_out,
    }


def patch_draft_line(
    db: Session,
    tenant_id: int,
    draft_id: int,
    line_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    included: bool | None = None,
    plan_qty: int | None = None,
) -> dict:
    draft = db.get(ScheduleDraft, draft_id)
    if not draft or draft.tenant_id != tenant_id:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_editable", "仅草稿可修改")
    line = db.get(ScheduleDraftLine, line_id)
    if not line or line.tenant_id != tenant_id or line.draft_id != draft_id:
        raise ScheduleError("line_not_found", "草稿行不存在")
    if start_date is not None:
        line.start_date = start_date
    if end_date is not None:
        line.end_date = end_date
    if included is not None:
        line.included = included
    if plan_qty is not None:
        if plan_qty <= 0:
            raise ScheduleError("invalid_qty", "计划数量须大于 0")
        line.plan_qty = plan_qty
    if line.start_date and line.end_date and line.start_date > line.end_date:
        raise ScheduleError("invalid_dates", "开始日期不能晚于结束日期")
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def set_line_assignments(
    db: Session,
    tenant_id: int,
    draft_id: int,
    line_id: int,
    assignments: list[dict] | None = None,
    *,
    equal_split: bool = False,
    team_id: int | None = None,
    team_mode: str = "members",
) -> dict:
    """设置某草稿行派工建议。

    - 普通：assignments [{worker_id, quota_qty?, share_weight?}]
    - 班组：传 team_id，展开为成员工人行（落库仍是 worker_id，确认路径不变）
      team_mode=members 整班；leader 仅组长
    """
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_editable", "仅草稿可修改")
    line = next((ln for ln in draft.lines if ln.id == line_id), None)
    if not line:
        raise ScheduleError("line_not_found", "草稿行不存在")

    items: list[tuple[int, int | None, int | None]] = []
    if team_id is not None:
        mode = (team_mode or "members").strip().lower()
        if mode not in ("members", "leader"):
            raise ScheduleError("invalid_team_mode", "班组模式须为 members 或 leader")
        try:
            team = team_service.get_team(db, tenant_id, int(team_id))
            member_ids = team_service.list_team_member_ids(db, tenant_id, int(team_id))
        except team_service.TeamError as e:
            raise ScheduleError(e.code, e.message) from e
        if not team.is_active:
            raise ScheduleError("team_inactive", "班组已停用")
        if mode == "leader":
            worker_ids = [int(team.leader_worker_id)]
        else:
            worker_ids = list(dict.fromkeys(member_ids))
            if team.leader_worker_id and team.leader_worker_id not in worker_ids:
                worker_ids.insert(0, int(team.leader_worker_id))
        if not worker_ids:
            raise ScheduleError("team_empty", "班组无成员，无法派工")

        proc = db.get(OrderProcess, line.order_process_id)
        ptype = proc.process_type if proc else None
        if hasattr(ptype, "value"):
            ptype = ptype.value
        if ptype == ProcessType.group.value and len(worker_ids) < 2:
            raise ScheduleError(
                "group_need_members",
                "集体工序派班组至少需要 2 人；可改派整班成员，或将该工序改为个人计件",
            )

        items = [(wid, None, 1) for wid in worker_ids]
        equal_split = True
    else:
        for row in assignments or []:
            wid = int(row["worker_id"])
            quota = row.get("quota_qty", None)
            if quota is not None:
                quota = int(quota)
            weight = row.get("share_weight", 1)
            if weight is not None:
                weight = int(weight)
            items.append((wid, quota, weight))

    _set_line_assignment_rows(db, tenant_id, line, items, equal_split=equal_split)
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def suggest_assignments(db: Session, tenant_id: int, draft_id: int) -> dict:
    """按规则重算派工建议（覆盖现有草稿派工行）。"""
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_editable", "仅草稿可修改")
    _auto_fill_assignments_for_draft(db, tenant_id, draft)
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def confirm_draft(
    db: Session,
    tenant_id: int,
    draft_id: int,
    *,
    user_id: int | None = None,
    require_first_kit: bool = True,
    apply_assignments: bool = True,
) -> dict:
    """确认：写回 OrderProcess 时间窗；有派工草稿时同步写 assignment。"""
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_confirmable", "草稿已确认或已作废")

    included = [ln for ln in draft.lines if ln.included]
    if not included:
        raise ScheduleError("empty_lines", "没有勾选要确认的工序行")

    # 齐套 / 齐套日闸门：确认前校验
    order_ids = {ln.order_id for ln in included}
    for oid in order_ids:
        kit = material_service.get_order_kit(db, tenant_id, oid)
        first_id = kit.get("first_process_id")
        touches_first = bool(
            first_id and any(ln.process_id == first_id for ln in included if ln.order_id == oid)
        )
        if require_first_kit and first_id:
            if touches_first and kit.get("empty_bom"):
                order = db.get(Order, oid)
                raise ScheduleError(
                    "empty_bom_blocked",
                    f"订单 {order.order_no if order else oid} 未建 BOM/无用料，不能确认开裁段排产",
                )
            if touches_first and not kit.get("first_kit_ok"):
                order = db.get(Order, oid)
                raise ScheduleError(
                    "first_kit_blocked",
                    f"订单 {order.order_no if order else oid} 首道缺料，不能确认开裁段排产",
                )
            # 分段：非首道也校验对应 process_kit
            for ln in included:
                if ln.order_id != oid:
                    continue
                by_proc = {x["process_id"]: x for x in kit.get("by_process") or []}
                info = by_proc.get(ln.process_id)
                if info and not info.get("kit_ok"):
                    raise ScheduleError(
                        "process_kit_blocked",
                        f"订单 {kit.get('order_no') or oid} 工序「{ln.process_name}」缺料，无法确认该段",
                    )

        # P0-1：计划开工不得早于预计齐套日（与 require_first_kit 无关，始终生效）
        kr = kit.get("kit_ready_date")
        kit_ready: date | None = None
        if kr:
            try:
                kit_ready = date.fromisoformat(str(kr)[:10])
            except ValueError:
                kit_ready = None
        if kit_ready:
            for ln in included:
                if ln.order_id != oid or not ln.start_date:
                    continue
                if ln.start_date < kit_ready:
                    order = db.get(Order, oid)
                    raise ScheduleError(
                        "kit_ready_too_early",
                        f"订单 {order.order_no if order else oid} 计划开工 "
                        f"{ln.start_date.isoformat()} 早于预计齐套日 {kit_ready.isoformat()}，不能确认",
                    )

    touched_orders: set[int] = set()
    for ln in included:
        proc = db.get(OrderProcess, ln.order_process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise ScheduleError("process_missing", f"工序计划不存在: {ln.order_process_id}")
        proc.start_date = ln.start_date
        proc.end_date = ln.end_date
        if ln.plan_qty and ln.plan_qty > 0:
            proc.plan_qty = ln.plan_qty
        touched_orders.add(ln.order_id)

        if apply_assignments and ln.assignments:
            items = [
                (
                    a.worker_id,
                    a.quota_qty,
                    a.share_weight if a.share_weight is not None else 1,
                )
                for a in ln.assignments
            ]
            try:
                assignment_service.replace_process_assignments(
                    db,
                    tenant_id=tenant_id,
                    order_id=ln.order_id,
                    process=proc,
                    items=items,
                    commit=False,
                )
            except assignment_service.AssignmentError as e:
                raise ScheduleError(e.code, e.message) from e

    for oid in touched_orders:
        procs = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == oid
                )
            ).all()
        )
        dated = sum(1 for p in procs if p.start_date and p.end_date)
        order = db.get(Order, oid)
        if not order:
            continue
        if dated == 0:
            order.schedule_status = ScheduleStatus.none
        elif dated < len(procs):
            order.schedule_status = ScheduleStatus.partial
        else:
            order.schedule_status = ScheduleStatus.scheduled

    draft.status = ScheduleDraftStatus.confirmed
    draft.confirmed_by = user_id
    draft.confirmed_at = datetime.now()
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def discard_draft(db: Session, tenant_id: int, draft_id: int) -> dict:
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(selectinload(ScheduleDraft.lines))
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_discardable", "仅草稿可作废")
    order_ids = {ln.order_id for ln in draft.lines}
    draft.status = ScheduleDraftStatus.discarded
    for oid in order_ids:
        order = db.get(Order, oid)
        if not order or order.tenant_id != tenant_id:
            continue
        # 若该单没有其它 draft 中草稿，且工序尚无日期 → 回 none
        other = db.scalar(
            select(ScheduleDraftLine.id)
            .join(ScheduleDraft, ScheduleDraft.id == ScheduleDraftLine.draft_id)
            .where(
                ScheduleDraftLine.order_id == oid,
                ScheduleDraft.tenant_id == tenant_id,
                ScheduleDraft.status == ScheduleDraftStatus.draft,
                ScheduleDraft.id != draft_id,
            )
            .limit(1)
        )
        if other:
            continue
        procs = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == oid
                )
            ).all()
        )
        dated = sum(1 for p in procs if p.start_date and p.end_date)
        if dated == 0:
            order.schedule_status = ScheduleStatus.none
        elif dated < len(procs):
            order.schedule_status = ScheduleStatus.partial
        else:
            order.schedule_status = ScheduleStatus.scheduled
    db.commit()
    return {"id": draft_id, "status": "discarded"}


def list_drafts(db: Session, tenant_id: int, *, status: str | None = "draft", limit: int = 50) -> list[dict]:
    q = (
        select(ScheduleDraft)
        .where(ScheduleDraft.tenant_id == tenant_id)
        .options(
            selectinload(ScheduleDraft.lines).selectinload(ScheduleDraftLine.assignments)
        )
    )
    if status:
        q = q.where(ScheduleDraft.status == ScheduleDraftStatus(status))
    rows = db.scalars(q.order_by(ScheduleDraft.id.desc()).limit(limit)).all()
    out: list[dict] = []
    for d in rows:
        lines = d.lines or []
        order_ids = {ln.order_id for ln in lines}
        included = sum(1 for ln in lines if ln.included)
        with_assign = sum(1 for ln in lines if ln.included and (ln.assignments or []))
        out.append(
            {
                "id": d.id,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                "note": d.note,
                "created_at": d.created_at,
                "confirmed_at": d.confirmed_at,
                "line_count": len(lines),
                "included_count": included,
                "order_count": len(order_ids),
                "assigned_line_count": with_assign,
            }
        )
    return out


def list_calendar(
    db: Session,
    tenant_id: int,
    *,
    date_from: date,
    date_to: date,
) -> dict:
    """全局已确认工序计划（只读）：OrderProcess 已写 start/end 且与区间相交。"""
    from app.utils.cn_holidays import day_meta_range

    if date_to < date_from:
        raise ScheduleError("invalid_range", "结束日期不能早于开始日期")
    if (date_to - date_from).days > 62:
        raise ScheduleError("range_too_long", "查询跨度请不超过 62 天")

    day_meta = day_meta_range(date_from, date_to)

    procs = list(
        db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.start_date.is_not(None),
                OrderProcess.end_date.is_not(None),
                OrderProcess.start_date <= date_to,
                OrderProcess.end_date >= date_from,
            )
            .order_by(OrderProcess.start_date, OrderProcess.id)
        ).all()
    )
    if not procs:
        return {
            "from": date_from,
            "to": date_to,
            "items": [],
            "by_date": {k: [] for k in day_meta},
            "day_meta": day_meta,
        }

    order_ids = {p.order_id for p in procs}
    orders = {
        o.id: o
        for o in db.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids))
        ).all()
    }
    product_ids = {o.own_product_id for o in orders.values() if o.own_product_id}
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_(product_ids or [0]),
            )
        ).all()
    }

    items: list[dict] = []
    for p in procs:
        order = orders.get(p.order_id)
        if not order or order.status == OrderStatus.cancelled:
            continue
        product = products.get(order.own_product_id)
        items.append(
            {
                "order_process_id": p.id,
                "order_id": order.id,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "own_product_id": order.own_product_id,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "is_rush": bool(order.is_rush),
                "process_id": p.process_id,
                "process_name": p.process_name,
                "plan_qty": p.plan_qty,
                "completed_qty": p.completed_qty,
                "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                "start_date": p.start_date,
                "end_date": p.end_date,
                "delivery_date": order.delivery_date,
            }
        )

    by_date: dict[str, list[dict]] = {}
    cur = date_from
    while cur <= date_to:
        key = cur.isoformat()
        day_items = []
        for it in items:
            if it["start_date"] <= cur <= it["end_date"]:
                day_items.append(it)
        by_date[key] = day_items
        cur += timedelta(days=1)

    return {
        "from": date_from,
        "to": date_to,
        "items": items,
        "by_date": by_date,
        "day_meta": day_meta,
    }
