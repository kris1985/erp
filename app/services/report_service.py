from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    Order,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessStatus,
    OrderStatus,
    ProcessType,
    ReportType,
    Size,
    Station,
    TraceUnit,
    TraceUnitStatus,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Worker,
)
from app.services.order_service import get_labor_unit_price, get_order_by_no
from app.services import trace_service
from app.services.trace_service import TraceError


class ReportError(Exception):
    def __init__(self, code: str, message: str, need_confirm: bool = False, data: dict | None = None):
        self.code = code
        self.message = message
        self.need_confirm = need_confirm
        self.data = data or {}
        super().__init__(message)


def _resolve_color(db: Session, tenant_id: int, color_name: str | None) -> Color | None:
    if not color_name:
        return None
    return db.scalar(
        select(Color).where(Color.tenant_id == tenant_id, Color.name == color_name.strip())
    )


def _resolve_size(db: Session, tenant_id: int, size_value: str | None) -> Size | None:
    if not size_value:
        return None
    value = size_value.strip().replace("码", "")
    return db.scalar(select(Size).where(Size.tenant_id == tenant_id, Size.size_value == value))


def _parse_report_type(report_type: str) -> ReportType:
    if report_type not in ReportType.__members__:
        raise ReportError("invalid_report_type", f"不支持的报工类型：{report_type}")
    rt = ReportType(report_type)
    if rt not in (
        ReportType.normal,
        ReportType.rework,
        ReportType.group,
        ReportType.supplement,
        ReportType.tail,
    ):
        raise ReportError("invalid_report_type", f"暂不支持报工类型：{report_type}")
    return rt


def _split_equal(total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _split_by_weight(total: int, weights: list[int]) -> list[int]:
    """按权重拆整数；最大余数法保证合计=total。权重均相等时等价均分。"""
    n = len(weights)
    if n <= 0:
        return []
    if total <= 0:
        return [0] * n
    norm = [w if w and w > 0 else 1 for w in weights]
    wsum = sum(norm)
    if wsum <= 0:
        return _split_equal(total, n)
    if all(w == norm[0] for w in norm):
        return _split_equal(total, n)
    raw = [total * w / wsum for w in norm]
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    order = sorted(range(n), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:rem]:
        floors[i] += 1
    return floors


def _member_weights(
    assign_rows,
    members: list[int],
    *,
    color_id: int | None,
    size_id: int | None,
    trace_unit_id: int | None,
) -> list[int]:
    from app.services.assignment_service import effective_share_weight, match_assignment_for_quota

    if not assign_rows:
        return [1] * len(members)
    out: list[int] = []
    for mid in members:
        a = match_assignment_for_quota(assign_rows, mid, color_id, size_id, trace_unit_id)
        out.append(effective_share_weight(a))
    return out


def _enforce_quotas(
    db: Session,
    *,
    process,
    members: list[int],
    bill_qty: int,
    is_group: bool,
    is_rework: bool,
    color_id: int | None = None,
    size_id: int | None = None,
    trace_unit_id: int | None = None,
    weights: list[int] | None = None,
) -> None:
    """有配额则校验累计+本次 ≤ 配额；返修不计配额。优先捆/色码行，否则整工序行。"""
    if is_rework:
        return
    from app.services.assignment_service import (
        list_assignments,
        match_assignment_for_quota,
        reported_for_assignment,
    )

    rows = list_assignments(db, process.id)
    if not rows:
        return
    if is_group:
        wts = weights or _member_weights(
            rows, members, color_id=color_id, size_id=size_id, trace_unit_id=trace_unit_id
        )
        splits = _split_by_weight(bill_qty, wts)
    else:
        splits = [bill_qty]
    for mid, sq in zip(members, splits):
        a = match_assignment_for_quota(rows, mid, color_id, size_id, trace_unit_id)
        if not a or a.quota_qty is None:
            continue
        used = reported_for_assignment(db, a)
        if used + sq > int(a.quota_qty):
            w = db.get(Worker, mid)
            name = w.name if w else str(mid)
            raise ReportError(
                "over_quota",
                f"{name}在{process.process_name}配额{a.quota_qty}，已报{used}，"
                f"本次{sq}将超配额。请假请「收回剩余」到未分配池，或改派给他人。",
            )


def submit_report(
    db: Session,
    *,
    tenant_id: int,
    worker_id: int,
    order_no: str | None = None,
    process_name: str,
    qualified_qty: int,
    defect_qty: int = 0,
    color_name: str | None = None,
    size_value: str | None = None,
    original_text: str | None = None,
    source: str = "manual",
    confirm_over_plan: bool = False,
    report_type: str = "normal",
    member_ids: list[int] | None = None,
    station_id: int | None = None,
    trace_unit_id: int | None = None,
    create_trace_bundle: bool | None = None,
    unit_price_override: Decimal | None = None,
    proxy: bool = False,
    beneficiary_worker_id: int | None = None,
    beneficiary_worker_ids: list[int] | None = None,
    shares: list[dict] | None = None,
    header_id: int | None = None,
) -> dict:
    from app.services.salary_service import assert_month_unlocked, year_month_of
    from app.services.shop_floor_gates import ShopFloorGateError, assert_report_carrier

    rt = _parse_report_type(report_type)
    is_rework = rt == ReportType.rework

    if qualified_qty < 0 or defect_qty < 0:
        raise ReportError("invalid_qty", "数量不能为负")
    if is_rework:
        if qualified_qty == 0:
            raise ReportError("empty_qty", "请填写返修数量")
    elif qualified_qty == 0 and defect_qty == 0:
        raise ReportError("empty_qty", "请填写合格或不良数量")

    assert_month_unlocked(db, tenant_id, year_month_of(datetime.utcnow()), action="报工")

    operator = db.get(Worker, worker_id)
    if not operator or operator.tenant_id != tenant_id or not operator.is_active:
        raise ReportError("worker_not_found", "工人不存在或未启用")

    def _unique_ids(raw: list[int] | None) -> list[int]:
        seen: set[int] = set()
        out: list[int] = []
        for i in raw or []:
            ii = int(i)
            if ii and ii not in seen:
                seen.add(ii)
                out.append(ii)
        return out

    beneficiary_ids: list[int] = []
    pay_worker_id = worker_id
    if proxy:
        raw_ids = list(beneficiary_worker_ids or [])
        if beneficiary_worker_id:
            raw_ids.append(int(beneficiary_worker_id))
        if not raw_ids and member_ids:
            raw_ids = list(member_ids)
        beneficiary_ids = _unique_ids(raw_ids)
        if not beneficiary_ids:
            raise ReportError("proxy_need_beneficiary", "代报须指定工人")
        for bid in beneficiary_ids:
            pw = db.get(Worker, bid)
            if not pw or pw.tenant_id != tenant_id or not pw.is_active:
                raise ReportError("worker_not_found", "代报受益人不存在或未启用")
        pay_worker_id = beneficiary_ids[0]

    worker = db.get(Worker, pay_worker_id)
    if not worker or worker.tenant_id != tenant_id or not worker.is_active:
        raise ReportError("worker_not_found", "工人不存在或未启用")
    log_text = original_text
    if proxy:
        pay_names = "、".join(
            (db.get(Worker, bid).name if db.get(Worker, bid) else str(bid))
            for bid in beneficiary_ids
        )
        note = f"代报：{operator.name}→{pay_names}"
        log_text = f"{note}；{original_text}" if original_text else note

    station = None
    if station_id is not None:
        station = db.get(Station, station_id)
        if not station or station.tenant_id != tenant_id or not station.is_active:
            raise ReportError("station_not_found", "工位不存在或未启用")

    order = None
    header = None
    resolved_header_id = header_id
    if header_id is not None:
        from app.services.material_service import resolve_order_from_header

        order, header = resolve_order_from_header(db, tenant_id, int(header_id))
        if not header:
            raise ReportError("header_not_found", "执行单不存在")
        resolved_header_id = int(header.id)
    elif order_no:
        order = get_order_by_no(db, tenant_id, order_no.strip())
        if not order:
            # 允许扫/填执行单号
            from app.models import ExecutionHeader
            from app.services.material_service import resolve_order_from_header

            hdr = db.scalar(
                select(ExecutionHeader).where(
                    ExecutionHeader.tenant_id == tenant_id,
                    ExecutionHeader.header_no == order_no.strip(),
                )
            )
            if hdr:
                order, header = resolve_order_from_header(db, tenant_id, int(hdr.id))
                if header:
                    resolved_header_id = int(header.id)
        if not order and not header:
            raise ReportError("order_not_found", f"找不到订单 {order_no}")
    else:
        raise ReportError("order_required", "请提供单号或执行单")

    if resolved_header_id is None and order is not None:
        from app.services.material_service import resolve_header_id_for_write

        resolved_header_id = resolve_header_id_for_write(
            db, tenant_id, order_id=order.id
        )

    from app.services.material_service import MaterialError, list_header_processes
    from app.services.stock_doc_service import assert_issue_gate, assert_issue_gate_for_header

    try:
        if order is not None:
            assert_issue_gate(db, tenant_id, order)
        elif resolved_header_id is not None:
            assert_issue_gate_for_header(db, tenant_id, int(resolved_header_id))
    except MaterialError as e:
        raise ReportError(e.code, e.message) from e

    own_product_id = (
        order.own_product_id if order is not None else int(header.own_product_id)
    )
    display_no = (
        order.order_no
        if order is not None
        else (header.header_no if header is not None else order_no)
    )

    trace_unit: TraceUnit | None = None
    if trace_unit_id is not None:
        trace_unit = db.get(TraceUnit, trace_unit_id)
        if not trace_unit or trace_unit.tenant_id != tenant_id:
            raise ReportError("trace_not_found", "捆标不存在")
        order_ok = order is not None and trace_unit.order_id == order.id
        header_ok = (
            resolved_header_id is not None
            and getattr(trace_unit, "header_id", None) is not None
            and int(trace_unit.header_id) == int(resolved_header_id)
        )
        if not order_ok and not header_ok:
            raise ReportError("trace_order_mismatch", "捆标与订单不一致")
        st = (
            trace_unit.status.value
            if hasattr(trace_unit.status, "value")
            else str(trace_unit.status)
        )
        if st not in (
            TraceUnitStatus.open.value,
            TraceUnitStatus.in_process.value,
        ):
            raise ReportError(
                "trace_unit_inactive",
                "该主码已作废、入库或结束，不可报工",
            )
        # 色码：捆上有则强制对齐（未传则预填）
        if trace_unit.color_id and color_name is None:
            c = db.get(Color, trace_unit.color_id)
            color_name = c.name if c else color_name
        if trace_unit.size_id and size_value is None:
            s = db.get(Size, trace_unit.size_id)
            size_value = s.size_value if s else size_value
        if resolved_header_id is None and getattr(trace_unit, "header_id", None):
            resolved_header_id = int(trace_unit.header_id)

    if order is not None:
        order_processes = list(order.processes or [])
    else:
        order_processes = list_header_processes(db, tenant_id, int(resolved_header_id))

    process = next((p for p in order_processes if p.process_name == process_name), None)
    if not process:
        process = next((p for p in order_processes if process_name in p.process_name), None)
    if not process:
        names = "、".join(p.process_name for p in order_processes)
        raise ReportError("process_not_found", f"订单无此工序，可选：{names}")

    if station and station.process_id != process.process_id:
        raise ReportError(
            "station_process_mismatch",
            f"工位「{station.name}」对应工序与报工工序不一致",
        )

    try:
        assert_report_carrier(
            db,
            tenant_id=tenant_id,
            order_processes=order_processes,
            process=process,
            product_id=own_product_id,
            trace_unit=trace_unit,
            pay_worker_id=pay_worker_id,
            operator=operator,
            is_leader_proxy=bool(proxy),
            beneficiary_worker_id=beneficiary_ids[0] if proxy else None,
        )
    except ShopFloorGateError as e:
        raise ReportError(e.code, e.message) from e

    process_type = process.process_type
    if hasattr(process_type, "value"):
        process_type = process_type.value
    # 集体工序禁止返修（政策禁区）；普通报工才升为集体计件
    if is_rework and process_type == ProcessType.group.value:
        raise ReportError("group_rework_forbidden", "集体工序不支持返修报工（政策禁区）")
    if rt == ReportType.normal and process_type == ProcessType.group.value:
        rt = ReportType.group
    is_group = rt == ReportType.group

    assigned_ids = list(
        db.scalars(
            select(OrderProcessAssignment.worker_id).where(
                OrderProcessAssignment.order_process_id == process.id
            )
        ).all()
    )

    from app.services import reporting_settings

    reporting = reporting_settings.get_reporting_by_tenant_id(db, tenant_id)

    if is_group:
        members = list(dict.fromkeys(member_ids or assigned_ids or [worker_id]))
        if len(members) < 2:
            raise ReportError(
                "group_need_members",
                f"{process.process_name}为集体工序，请先派工至少 2 人，或指定集体成员",
            )
        for mid in members:
            mw = db.get(Worker, mid)
            if not mw or mw.tenant_id != tenant_id or not mw.is_active:
                raise ReportError("worker_not_found", f"集体成员不存在或未启用：{mid}")
        if worker_id not in members:
            raise ReportError("not_assigned", "你不在该集体派工名单中，无法代报")
    else:
        members = beneficiary_ids if proxy else [pay_worker_id]
        for check_worker_id in members:
            if not assigned_ids and not reporting.get("allow_unassigned_report", True):
                raise ReportError(
                    "not_assigned",
                    f"{process.process_name}尚未派工，当前规则不允许未派报工",
                )
            if assigned_ids and check_worker_id not in set(assigned_ids):
                names = []
                for wid in assigned_ids:
                    w = db.get(Worker, wid)
                    if w:
                        names.append(w.name)
                tip = "、".join(names) if names else "已派工人"
                mw = db.get(Worker, check_worker_id)
                who = mw.name if mw else str(check_worker_id)
                raise ReportError(
                    "not_assigned",
                    f"{process.process_name}已派给{tip}，{who}不在派工名单中",
                )

    proxy_batch = bool(proxy and not is_group and len(members) > 1)
    split_across = is_group or proxy_batch

    color = _resolve_color(db, tenant_id, color_name)
    if color_name and not color:
        raise ReportError("color_not_found", f"颜色不存在：{color_name}")
    size = _resolve_size(db, tenant_id, size_value)
    if size_value and not size:
        raise ReportError("size_not_found", f"尺码不存在：{size_value}")

    from app.services.assignment_service import (
        is_bundle_scope,
        is_sku_scope,
        list_assignments,
        match_assignment_for_quota,
    )

    assign_rows = list_assignments(db, process.id)
    bundle_dispatch = any(is_bundle_scope(a) for a in assign_rows)
    sku_dispatch = any(is_sku_scope(a) for a in assign_rows)
    cid = color.id if color else None
    sid = size.id if size else None
    tid = trace_unit.id if trace_unit else None

    if bundle_dispatch and not is_rework:
        if tid is None:
            raise ReportError(
                "need_trace_unit",
                f"{process.process_name}已按捆派工，请扫捆报工",
            )
        for mid in members:
            matched = match_assignment_for_quota(assign_rows, mid, cid, sid, tid)
            if matched is None or not is_bundle_scope(matched):
                mw = db.get(Worker, mid)
                raise ReportError(
                    "not_assigned",
                    f"{mw.name if mw else mid}未派工{process.process_name}·捆{trace_unit.code}，无法报工",
                )
    elif sku_dispatch and not is_rework:
        for mid in members:
            matched = match_assignment_for_quota(assign_rows, mid, cid, sid, tid)
            if matched is None or not is_sku_scope(matched):
                mw = db.get(Worker, mid)
                tip = f"{color_name or '—'}{size_value or ''}码" if (color_name or size_value) else "该色码"
                raise ReportError(
                    "not_assigned",
                    f"{mw.name if mw else mid}未派工{process.process_name}·{tip}，无法报工",
                )

    bill_qty = qualified_qty
    if trace_unit and not is_rework and bill_qty > int(trace_unit.qty):
        raise ReportError(
            "over_bundle_qty",
            f"本捆{trace_unit.qty}双，本次报工{bill_qty}超捆量",
        )

    member_weights = (
        _member_weights(assign_rows, members, color_id=cid, size_id=sid, trace_unit_id=tid)
        if is_group
        else [1] * len(members)
    )
    from app.services import shop_floor_settings as _shop_floor_settings

    shop_floor = _shop_floor_settings.get_shop_floor_by_tenant_id(db, tenant_id)
    shares_adjusted = False
    splits_override: list[int] | None = None
    if split_across and shares:
        parsed: list[tuple[int, int]] = []
        for row in shares:
            mid = int(row.get("worker_id") or 0)
            pairs = int(row.get("pairs") or 0)
            if mid <= 0 or pairs < 0:
                raise ReportError("invalid_shares", "组报工拆分无效")
            mw = db.get(Worker, mid)
            if not mw or mw.tenant_id != tenant_id or not mw.is_active:
                raise ReportError("worker_not_found", f"拆分工人不存在：{mid}")
            parsed.append((mid, pairs))
        if sum(p for _, p in parsed) != bill_qty:
            raise ReportError("invalid_shares", f"拆分双数合计须等于 {bill_qty}")
        members = [m for m, _ in parsed]
        splits_override = [p for _, p in parsed]
        member_weights = [1] * len(members)
        shares_adjusted = True
        proxy_batch = bool(proxy and not is_group and len(members) > 1)
        split_across = is_group or proxy_batch
    elif is_group and shop_floor.get("enable_skill_factor_split", True):
        skill_weights: list[int] = []
        for mid in members:
            mw = db.get(Worker, mid)
            factor = Decimal(getattr(mw, "skill_factor", None) or 1)
            if factor <= 0:
                factor = Decimal("1")
            skill_weights.append(max(1, int((factor * 100).to_integral_value())))
        member_weights = skill_weights

    _enforce_quotas(
        db,
        process=process,
        members=members,
        bill_qty=bill_qty,
        is_group=split_across,
        is_rework=is_rework,
        color_id=cid,
        size_id=sid,
        trace_unit_id=tid,
        weights=member_weights,
    )

    if not is_rework:
        new_completed = process.completed_qty + qualified_qty
        allow_over = bool(reporting.get("allow_over_plan", True))
        need_confirm = bool(reporting.get("over_plan_requires_confirm", True))
        if new_completed > process.plan_qty:
            if not allow_over:
                raise ReportError(
                    "over_plan_forbidden",
                    f"{process.process_name}计划{process.plan_qty}，已完成{process.completed_qty}，"
                    f"当前规则不允许超额报工",
                )
            if need_confirm and not confirm_over_plan:
                raise ReportError(
                    "over_plan",
                    f"{process.process_name}计划{process.plan_qty}，已完成{process.completed_qty}，"
                    f"本次再报{qualified_qty}将超额，确认继续吗？",
                    need_confirm=True,
                    data={
                        "order_no": order_no,
                        "process_name": process.process_name,
                        "qualified_qty": qualified_qty,
                        "defect_qty": defect_qty,
                        "color_name": color_name,
                        "size_value": size_value,
                        "worker_id": worker_id,
                        "report_type": rt.value,
                        "member_ids": members if split_across else None,
                    },
                )

    if unit_price_override is not None:
        unit_price = Decimal(unit_price_override)
    else:
        unit_price = get_labor_unit_price(
            db, tenant_id, own_product_id, process.process_id
        )
    if unit_price is None:
        raise ReportError("price_missing", f"{process.process_name}未配置工序单价")
    unit_price = Decimal(unit_price).quantize(Decimal("0.0001"))
    # 返修不计薪：仍记报工账，金额记 0（工资汇总侧也会跳过）
    if is_rework and not reporting.get("rework_pays", True):
        unit_price = Decimal("0")
    total_amount = unit_price * Decimal(bill_qty)
    source_enum = WorkLogSource(source) if source in WorkLogSource.__members__ else WorkLogSource.manual

    if process.actual_start is None:
        process.actual_start = datetime.utcnow()

    logs: list[WorkLog] = []
    splits = (
        splits_override
        if splits_override is not None
        else (_split_by_weight(bill_qty, member_weights) if split_across else [bill_qty])
    )
    if is_rework:
        defect_splits = [0] * len(members)
    elif split_across:
        defect_splits = _split_by_weight(defect_qty, member_weights)
    else:
        defect_splits = [defect_qty]
    group_id = None
    member_detail = []
    split_mode = "equal"
    if split_across:
        split_mode = "equal" if all(w == member_weights[0] for w in member_weights) else "ratio"
        for mid, sq, wt in zip(members, splits, member_weights):
            mw = db.get(Worker, mid)
            member_detail.append(
                {
                    "worker_id": mid,
                    "name": mw.name if mw else str(mid),
                    "qty": sq,
                    "weight": wt,
                }
            )

    for i, mid in enumerate(members):
        sq = splits[i]
        dq = defect_splits[i] if i < len(defect_splits) else 0
        group_detail = None
        if is_group:
            group_detail = {
                "total_qty": bill_qty,
                "split": split_mode,
                "reporter_id": worker_id,
                "members": member_detail,
            }
        elif proxy_batch:
            group_detail = {
                "kind": "proxy_batch",
                "total_qty": bill_qty,
                "split": split_mode,
                "reporter_id": worker_id,
                "members": member_detail,
            }
        log = WorkLog(
            tenant_id=tenant_id,
            worker_id=mid,
            order_id=order.id if order is not None else None,
            header_id=resolved_header_id,
            order_process_id=process.id,
            own_product_id=own_product_id,
            style_id=(
                (getattr(order, "style_id", None) or order.own_product_id)
                if order is not None
                else own_product_id
            ),
            process_id=process.process_id,
            color_id=color.id if color else None,
            size_id=size.id if size else None,
            report_type=rt,
            qualified_qty=0 if is_rework else sq,
            defect_qty=0 if is_rework else dq,
            rework_qty=sq if is_rework else 0,
            unit_price=unit_price,
            group_id=None,
            group_detail=group_detail,
            original_text=log_text,
            source=source_enum,
            station_id=station.id if station else None,
            trace_unit_id=trace_unit.id if trace_unit else None,
            status=WorkLogStatus.valid,
        )
        db.add(log)
        logs.append(log)

    db.flush()
    if split_across and logs:
        group_id = logs[0].id
        for log in logs:
            log.group_id = group_id
        if is_group:
            from app.models import WorkLogGroupShare

            for log in logs:
                mw = db.get(Worker, log.worker_id)
                factor = Decimal(getattr(mw, "skill_factor", None) or 1) if mw else Decimal("1")
                pairs = int(log.qualified_qty or 0)
                wage = (Decimal(pairs) * unit_price).quantize(Decimal("0.01"))
                db.add(
                    WorkLogGroupShare(
                        tenant_id=tenant_id,
                        work_log_id=log.id,
                        worker_id=log.worker_id,
                        pairs=pairs,
                        unit_price=unit_price,
                        wage=wage,
                        is_adjusted=shares_adjusted,
                        skill_factor_snapshot=factor,
                    )
                )

    if is_rework:
        process.rework_qty += bill_qty
        if process.status == OrderProcessStatus.pending:
            process.status = OrderProcessStatus.in_progress
        if order is not None and order.status == OrderStatus.confirmed:
            order.status = OrderStatus.in_progress
    else:
        process.completed_qty = process.completed_qty + qualified_qty
        process.defect_qty += defect_qty
        if process.status == OrderProcessStatus.pending:
            process.status = OrderProcessStatus.in_progress
        if process.completed_qty >= process.plan_qty:
            process.status = OrderProcessStatus.completed
            process.actual_end = datetime.utcnow()

        if order is not None:
            if order.status == OrderStatus.confirmed:
                order.status = OrderStatus.in_progress
            if all(p.status == OrderProcessStatus.completed for p in order_processes):
                order.status = OrderStatus.completed

            if size:
                item = next(
                    (
                        i
                        for i in order.items
                        if i.size_id == size.id
                        and ((color is None and i.color_id is None) or (color and i.color_id == color.id))
                    ),
                    None,
                )
                if item is None:
                    item = next((i for i in order.items if i.size_id == size.id), None)
                if item:
                    item.completed_qty += qualified_qty

    # AU-I1 M3：挂执行单时按末道工序回写进度 + ratio 预估销售产量
    if not is_rework:
        from app.services.execution_service import (
            ExecutionError as ExecutionProgressError,
            refresh_execution_progress_for_order,
        )

        try:
            eid = getattr(trace_unit, "execution_id", None) if trace_unit else None
            refresh_execution_progress_for_order(
                db,
                tenant_id=tenant_id,
                order_id=order.id if order else None,
                header_id=resolved_header_id,
                execution_id=int(eid) if eid else None,
                size_id=size.id if size else None,
            )
        except ExecutionProgressError:
            pass

    # 挂捆过站流水
    if trace_unit and logs:
        try:
            trace_service.attach_report_to_unit(
                db,
                tenant_id=tenant_id,
                unit=trace_unit,
                work_log=logs[0],
                station_id=station.id if station else None,
            )
        except TraceError as e:
            raise ReportError(e.code, e.message)

    # 捆标只从开裁打印。报工默认不起捆；仅显式 create_trace_bundle=True 且尚未开裁生码时才补一张。
    created_trace = None
    should_bundle = bool(create_trace_bundle)
    if should_bundle and order is not None and trace_service.order_has_cut_cards(
        db, tenant_id=tenant_id, order_id=order.id
    ):
        should_bundle = False
    elif (
        should_bundle
        and resolved_header_id is not None
        and db.scalar(
            select(func.count())
            .select_from(TraceUnit)
            .where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.header_id == int(resolved_header_id),
                TraceUnit.created_from_work_log_id.is_(None),
                TraceUnit.status != TraceUnitStatus.scrapped,
            )
        )
    ):
        should_bundle = False
    if (
        should_bundle
        and not is_rework
        and not is_group
        and not trace_unit
        and logs
        and qualified_qty > 0
    ):
        try:
            created_trace = trace_service.create_bundle_from_work_log(
                db,
                tenant_id=tenant_id,
                work_log_id=logs[0].id,
                qty=qualified_qty,
                commit=False,
            )
        except TraceError as e:
            raise ReportError(e.code, e.message)

    db.commit()
    for log in logs:
        db.refresh(log)
    if created_trace:
        db.refresh(created_trace)
    if trace_unit:
        db.refresh(trace_unit)

    rework_task = None
    if is_rework and logs and order is not None:
        try:
            from app.services import rework_task_service

            rework_task = rework_task_service.try_complete_on_rework_report(
                db,
                tenant_id,
                order_id=order.id,
                process_def_id=process.process_id,
                worker_id=worker_id,
                work_log_id=logs[0].id,
                qty=int(bill_qty),
            )
        except Exception:
            rework_task = None

    if is_rework:
        message = (
            f"返修报工成功：{display_no} {process.process_name} 返修{bill_qty}"
            f"；工序返修累计 {process.rework_qty}，本次约 ¥{total_amount:.2f}"
        )
        if rework_task:
            message += f"；已勾连完成返修任务 #{rework_task.get('id')}"
    elif is_group:
        parts = "、".join(f"{m['name']}{m['qty']}" for m in member_detail)
        message = (
            f"集体报工成功：{display_no} {process.process_name} 合计{bill_qty}"
            f"（均分 {parts}）；工序累计 {process.completed_qty}/{process.plan_qty}，"
            f"本组合计约 ¥{total_amount:.2f}"
        )
    elif rt == ReportType.supplement:
        message = (
            f"补数报工成功：{display_no} {process.process_name} 补数{qualified_qty}"
            f"；工序累计 {process.completed_qty}/{process.plan_qty}，本次约 ¥{total_amount:.2f}"
        )
    elif rt == ReportType.tail:
        message = (
            f"尾数报工成功：{display_no} {process.process_name} 尾数{qualified_qty}"
            f"；工序累计 {process.completed_qty}/{process.plan_qty}，本次约 ¥{total_amount:.2f}"
        )
    else:
        message = (
            f"报工成功：{display_no} {process.process_name} 合格{qualified_qty}"
            + (f" 不良{defect_qty}" if defect_qty else "")
            + f"；工序累计 {process.completed_qty}/{process.plan_qty}，本次约 ¥{total_amount:.2f}"
        )
    if proxy:
        pay_names = "、".join(
            (db.get(Worker, bid).name if db.get(Worker, bid) else str(bid))
            for bid in (beneficiary_ids or members)
        )
        message = f"代报成功，工资记{pay_names}。" + message

    return {
        "work_log_id": logs[0].id if logs else None,
        "work_log_ids": [x.id for x in logs],
        "group_id": group_id,
        "order_no": display_no,
        "header_id": resolved_header_id,
        "process_name": process.process_name,
        "report_type": rt.value,
        "qualified_qty": 0 if is_rework else qualified_qty,
        "defect_qty": 0 if is_rework else defect_qty,
        "rework_qty": bill_qty if is_rework else 0,
        "members": member_detail if split_across else None,
        "process_completed": process.completed_qty,
        "process_plan": process.plan_qty,
        "process_rework": process.rework_qty,
        "unit_price": float(unit_price),
        "amount": float(total_amount),
        "message": message,
        "trace_unit_id": (created_trace or trace_unit).id if (created_trace or trace_unit) else None,
        "trace_code": (created_trace or trace_unit).code if (created_trace or trace_unit) else None,
        "trace_unit": (
            {
                "id": created_trace.id,
                "code": created_trace.code,
                "qty": created_trace.qty,
                "scan_path": f"/trace/{created_trace.code}",
            }
            if created_trace
            else (
                {
                    "id": trace_unit.id,
                    "code": trace_unit.code,
                    "qty": trace_unit.qty,
                    "scan_path": f"/trace/{trace_unit.code}",
                }
                if trace_unit
                else None
            )
        ),
        "print_trace_label": bool(created_trace),
        "rework_task_id": (rework_task or {}).get("id") if rework_task else None,
        "proxy": bool(proxy),
        "beneficiary_worker_id": pay_worker_id if proxy else None,
        "beneficiary_worker_ids": beneficiary_ids if proxy else None,
        "operator_worker_id": operator.id if proxy else None,
    }


def _report_type_value(log: WorkLog) -> str:
    rt = log.report_type
    return rt.value if hasattr(rt, "value") else str(rt)


def _collect_related_reviewable_logs(db: Session, log: WorkLog) -> list[WorkLog]:
    """个人单返回自身；集体单返回同 group_id 下同状态的全部记录（valid / appealed）。"""
    if log.status not in (WorkLogStatus.valid, WorkLogStatus.appealed):
        return []
    if log.group_id:
        return list(
            db.scalars(
                select(WorkLog).where(
                    WorkLog.tenant_id == log.tenant_id,
                    WorkLog.group_id == log.group_id,
                    WorkLog.status == log.status,
                )
            ).all()
        )
    return [log]


def _rollback_progress(db: Session, logs: list[WorkLog]) -> None:
    if not logs:
        return
    log0 = logs[0]
    process = db.get(OrderProcess, log0.order_process_id)
    order = db.get(Order, log0.order_id) if log0.order_id else None
    if not process:
        raise ReportError("process_not_found", "关联工序不存在，无法回滚")

    qualified = sum(int(x.qualified_qty or 0) for x in logs)
    defect = sum(int(x.defect_qty or 0) for x in logs)
    rework = sum(int(x.rework_qty or 0) for x in logs)
    is_rework = _report_type_value(log0) == ReportType.rework.value

    if is_rework:
        process.rework_qty = max(0, int(process.rework_qty or 0) - rework)
    else:
        process.completed_qty = max(0, int(process.completed_qty or 0) - qualified)
        process.defect_qty = max(0, int(process.defect_qty or 0) - defect)
        if order and log0.size_id:
            item = next(
                (
                    i
                    for i in order.items
                    if i.size_id == log0.size_id
                    and (
                        (log0.color_id is None and i.color_id is None)
                        or (log0.color_id and i.color_id == log0.color_id)
                    )
                ),
                None,
            )
            if item is None:
                item = next((i for i in order.items if i.size_id == log0.size_id), None)
            if item:
                item.completed_qty = max(0, int(item.completed_qty or 0) - qualified)

        if process.completed_qty < process.plan_qty and process.status == OrderProcessStatus.completed:
            process.status = OrderProcessStatus.in_progress
            process.actual_end = None

    if order and order.status == OrderStatus.completed:
        order.status = OrderStatus.in_progress


def void_work_log(
    db: Session,
    *,
    tenant_id: int,
    work_log_id: int,
    review_note: str | None = None,
    reviewed_by: int | None = None,
) -> dict:
    from app.services.salary_service import assert_month_unlocked, year_month_of

    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        raise ReportError("not_found", "报工记录不存在")
    if log.status not in (WorkLogStatus.valid, WorkLogStatus.appealed):
        raise ReportError("invalid_status", "仅有效或申诉中的报工可作废")
    assert_month_unlocked(db, tenant_id, year_month_of(log.created_at), action="作废报工")

    related = _collect_related_reviewable_logs(db, log)
    if not related:
        raise ReportError("invalid_status", "没有可作废的报工")

    _rollback_progress(db, related)
    note = review_note or "管理端作废"
    for x in related:
        x.status = WorkLogStatus.void
        x.review_note = note
        if reviewed_by is not None:
            x.reviewed_by = reviewed_by

    from app.services.execution_service import (
        ExecutionError as ExecutionProgressError,
        refresh_execution_progress_for_order,
    )

    try:
        eid = None
        if log.trace_unit_id:
            tu = db.get(TraceUnit, log.trace_unit_id)
            eid = getattr(tu, "execution_id", None) if tu else None
        refresh_execution_progress_for_order(
            db,
            tenant_id=tenant_id,
            order_id=int(log.order_id) if log.order_id else None,
            header_id=getattr(log, "header_id", None),
            execution_id=int(eid) if eid else None,
            size_id=log.size_id,
        )
    except ExecutionProgressError:
        pass

    db.commit()
    return {
        "id": log.id,
        "voided_ids": [x.id for x in related],
        "status": WorkLogStatus.void.value,
        "review_note": note,
        "message": f"已作废 {len(related)} 条报工并回滚进度",
    }


def appeal_work_log(
    db: Session,
    *,
    tenant_id: int,
    work_log_id: int,
    worker_id: int,
    reason: str | None = None,
) -> dict:
    """工人申诉：valid → appealed。进度暂不回滚；不计薪直至审结。"""
    from app.services.salary_service import assert_month_unlocked, year_month_of

    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        raise ReportError("not_found", "报工记录不存在")
    if log.status != WorkLogStatus.valid:
        raise ReportError("invalid_status", "仅有效报工可申诉")
    assert_month_unlocked(db, tenant_id, year_month_of(log.created_at), action="申诉")

    related = _collect_related_reviewable_logs(db, log)
    if not related:
        raise ReportError("invalid_status", "没有可申诉的报工")
    if worker_id not in {x.worker_id for x in related}:
        raise ReportError("forbidden", "只能申诉自己的报工")

    note = (reason or "").strip() or "工人申诉"
    for x in related:
        x.status = WorkLogStatus.appealed
        x.review_note = note

    db.commit()
    return {
        "id": log.id,
        "appealed_ids": [x.id for x in related],
        "status": WorkLogStatus.appealed.value,
        "review_note": note,
        "message": f"已提交申诉 {len(related)} 条，等待主管审核（申诉期间暂不计薪）",
    }


def reject_appeal(
    db: Session,
    *,
    tenant_id: int,
    work_log_id: int,
    review_note: str | None = None,
    reviewed_by: int | None = None,
) -> dict:
    """驳回申诉：appealed → valid，恢复计薪。"""
    from app.services.salary_service import assert_month_unlocked, year_month_of

    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        raise ReportError("not_found", "报工记录不存在")
    if log.status != WorkLogStatus.appealed:
        raise ReportError("invalid_status", "仅申诉中的报工可驳回")
    assert_month_unlocked(db, tenant_id, year_month_of(log.created_at), action="驳回申诉")

    related = _collect_related_reviewable_logs(db, log)
    if not related:
        raise ReportError("invalid_status", "没有可驳回的申诉")

    note = review_note or "申诉驳回，维持原报工"
    for x in related:
        x.status = WorkLogStatus.valid
        x.review_note = note
        if reviewed_by is not None:
            x.reviewed_by = reviewed_by

    db.commit()
    return {
        "id": log.id,
        "restored_ids": [x.id for x in related],
        "status": WorkLogStatus.valid.value,
        "review_note": note,
        "message": f"已驳回申诉，恢复 {len(related)} 条有效报工",
    }


def correct_work_log(
    db: Session,
    *,
    tenant_id: int,
    work_log_id: int,
    qualified_qty: int = 0,
    defect_qty: int = 0,
    rework_qty: int = 0,
    color_name: str | None = None,
    size_value: str | None = None,
    review_note: str | None = None,
    reviewed_by: int | None = None,
) -> dict:
    from app.services.salary_service import assert_month_unlocked, year_month_of

    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        raise ReportError("not_found", "报工记录不存在")
    if log.status not in (WorkLogStatus.valid, WorkLogStatus.appealed):
        raise ReportError("invalid_status", "仅有效或申诉中的报工可改数")
    assert_month_unlocked(db, tenant_id, year_month_of(log.created_at), action="更正报工")

    related = _collect_related_reviewable_logs(db, log)
    if not related:
        raise ReportError("invalid_status", "没有可改数的报工")

    order = db.get(Order, log.order_id)
    process = db.get(OrderProcess, log.order_process_id)
    if not order or not process:
        raise ReportError("process_not_found", "关联工序或订单不存在")

    rt = _report_type_value(log)
    is_rework = rt == ReportType.rework.value
    is_group = rt == ReportType.group.value
    proxy_batch = isinstance(log.group_detail, dict) and log.group_detail.get("kind") == "proxy_batch"

    if is_rework:
        new_qty = rework_qty if rework_qty > 0 else qualified_qty
        if new_qty <= 0:
            raise ReportError("empty_qty", "请填写返修数量")
        report_qualified = new_qty
        report_defect = 0
        report_type = ReportType.rework.value
    else:
        if qualified_qty < 0 or defect_qty < 0:
            raise ReportError("invalid_qty", "数量不能为负")
        if qualified_qty == 0 and defect_qty == 0:
            raise ReportError("empty_qty", "请填写合格或不良数量")
        report_qualified = qualified_qty
        report_defect = defect_qty
        if is_group:
            report_type = ReportType.group.value
        elif rt in (ReportType.supplement.value, ReportType.tail.value):
            report_type = rt
        else:
            report_type = ReportType.normal.value

    # 色码：显式传入优先，否则沿用原单
    if color_name is None and log.color_id:
        c = db.get(Color, log.color_id)
        color_name = c.name if c else None
    if size_value is None and log.size_id:
        s = db.get(Size, log.size_id)
        size_value = s.size_value if s else None

    member_ids = None
    reporter_id = log.worker_id
    proxy_ids = None
    if is_group or proxy_batch:
        detail = log.group_detail or {}
        members = detail.get("members") or []
        member_ids = [m["worker_id"] for m in members if m.get("worker_id")]
        if not member_ids:
            member_ids = [x.worker_id for x in related]
        reporter_id = detail.get("reporter_id") or related[0].worker_id
        if proxy_batch:
            proxy_ids = list(member_ids)
            member_ids = None

    origin_ids = [x.id for x in related]
    _rollback_progress(db, related)
    note = review_note or f"更正自 #{','.join(str(i) for i in origin_ids)}"
    for x in related:
        x.status = WorkLogStatus.corrected
        x.review_note = note
        if reviewed_by is not None:
            x.reviewed_by = reviewed_by
    db.flush()

    # 更正沿用原报工锁价，避免被现价改写
    locked_price = log.unit_price
    if locked_price is None:
        for x in related:
            if x.unit_price is not None:
                locked_price = x.unit_price
                break

    result = submit_report(
        db,
        tenant_id=tenant_id,
        worker_id=reporter_id,
        order_no=order.order_no,
        process_name=process.process_name,
        qualified_qty=report_qualified,
        defect_qty=report_defect,
        color_name=color_name,
        size_value=size_value,
        original_text=f"更正自 #{log.id}",
        source="manual",
        confirm_over_plan=True,
        report_type=report_type,
        member_ids=member_ids,
        station_id=log.station_id,
        unit_price_override=Decimal(locked_price) if locked_price is not None else None,
        proxy=bool(proxy_batch),
        beneficiary_worker_ids=proxy_ids,
        trace_unit_id=log.trace_unit_id,
    )

    # 给新单补上 review 备注
    new_ids = result.get("work_log_ids") or ([result["work_log_id"]] if result.get("work_log_id") else [])
    for nid in new_ids:
        new_log = db.get(WorkLog, nid)
        if new_log:
            new_log.review_note = f"更正自 #{log.id}"
            if reviewed_by is not None:
                new_log.reviewed_by = reviewed_by
    db.commit()

    return {
        "corrected_ids": origin_ids,
        "new_work_log_id": result.get("work_log_id"),
        "new_work_log_ids": new_ids,
        "message": f"已更正：原 #{log.id} → 新单，" + result.get("message", ""),
        "report": result,
    }
