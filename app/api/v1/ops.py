from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_employee, get_principal, require_permissions, require_roles, Principal
from app.db import get_db
from app.models import Employee, ExecutionHeader, OrderProcess
from app.schemas.api import (
    ChatRequest,
    LineReportRequest,
    ReportBatchRequest,
    ReportRequest,
    CartonReportRequest,
    SalaryConfirmRequest,
    WorkLogAppealRequest,
    WorkLogCorrectRequest,
    WorkLogLossUpdate,
    WorkLogStatusUpdate,
)
from app.schemas.common import ok
from app.services import home_service, piecework_anomaly, progress_service, salary_service, workshop_display_service
from app.services.nlu import handle_chat
from app.services.report_service import (
    ReportError,
    appeal_work_log,
    correct_work_log,
    reject_appeal,
    submit_carton_report,
    submit_line_report,
    submit_report,
    submit_report_batch,
    void_work_log,
)

router = APIRouter(tags=["ops"])


@router.get("/reports/quote")
def api_report_quote(
    header_id: int = Query(gt=0),
    order_process_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """现场报工页按工序查询计件单价。"""
    header = db.get(ExecutionHeader, header_id)
    process = db.get(OrderProcess, order_process_id)
    if not header or header.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="生产单不存在")
    if (
        not process
        or process.tenant_id != principal.tenant_id
        or not (
            process.header_id == header.id
            or (header.shop_order_id and process.order_id == int(header.shop_order_id))
        )
    ):
        raise HTTPException(status_code=404, detail="工序不存在")
    from app.services.order_service import get_labor_unit_price

    price = get_labor_unit_price(db, principal.tenant_id, header.own_product_id, process.process_id)
    if price is None:
        raise HTTPException(status_code=400, detail=f"工序{process.process_name}未配置计件单价")
    return ok({
        "process_id": process.process_id,
        "process_name": process.process_name,
        "unit_price": float(price),
    })


@router.get("/home/overview")
def api_home_overview(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    return ok(home_service.worker_home_overview(db, principal.tenant_id, principal.employee))


@router.post("/reports")
def api_report(
    body: ReportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    worker_id = body.worker_id
    if principal.is_staff:
        worker_id = principal.employee.id  # type: ignore[union-attr]
    try:
        result = submit_report(
            db,
            tenant_id=principal.tenant_id,
            worker_id=worker_id,
            order_no=body.order_no,
            header_id=getattr(body, "header_id", None),
            process_name=body.process_name,
            order_process_id=body.order_process_id,
            qualified_qty=body.qualified_qty,
            defect_qty=body.defect_qty,
            color_name=body.color_name,
            size_value=body.size_value,
            original_text=body.original_text,
            source=body.source,
            confirm_over_plan=body.confirm_over_plan,
            report_type=body.report_type,
            member_ids=body.member_ids,
            station_id=body.station_id,
            trace_unit_id=body.trace_unit_id,
            create_trace_bundle=body.create_trace_bundle,
            proxy=bool(getattr(body, "proxy", False)),
            beneficiary_worker_id=getattr(body, "beneficiary_worker_id", None),
            beneficiary_worker_ids=getattr(body, "beneficiary_worker_ids", None),
            shares=getattr(body, "shares", None),
            workshop_counts=(
                [row.model_dump() for row in body.workshop_counts] if body.workshop_counts else None
            ),
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.post("/reports/batch")
def api_report_batch(
    body: ReportBatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """多道工序一次报工。全部成功才写入。"""
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    worker_id = principal.employee.id if principal.is_staff else body.items[0].worker_id
    items = []
    for row in body.items:
        data = row.model_dump()
        data.pop("worker_id", None)
        items.append(data)
    try:
        result = submit_report_batch(
            db,
            tenant_id=principal.tenant_id,
            worker_id=worker_id,
            items=items,
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/reports/workshop-counts")
def api_report_workshop_counts(
    header_id: int = Query(gt=0),
    order_process_ids: str | None = Query(default=None),
    process_id: int | None = Query(default=None, gt=0),
    team_id: int | None = Query(default=None, gt=0),
    consume_segment_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """报工前要清点的车间剩余。传入部门工序段时只返回该段的料。"""
    from app.models import OrderProcess, Team
    from app.services.material_service import list_header_processes
    from app.services.purchase_demand_service import list_workshop_count_targets

    def_ids: set[int] = set()
    if process_id:
        def_ids.add(int(process_id))
    raw_ids = [int(part) for part in (order_process_ids or "").split(",") if part.strip().isdigit()]
    if raw_ids:
        rows = db.scalars(
            select(OrderProcess).where(
                OrderProcess.tenant_id == principal.tenant_id,
                OrderProcess.header_id == header_id,
                OrderProcess.id.in_(raw_ids),
            )
        ).all()
        def_ids.update(int(row.process_id) for row in rows)
    if team_id:
        team = db.get(Team, team_id)
        if team and team.tenant_id == principal.tenant_id and team.segment_id:
            processes = list_header_processes(db, principal.tenant_id, header_id)
            def_ids.update(
                int(row.process_id)
                for row in processes
                if row.part_id is None and row.segment_id == team.segment_id
            )
    items = list_workshop_count_targets(
        db,
        principal.tenant_id,
        header_id,
        set() if consume_segment_id else def_ids,
        employee_id=principal.employee.id,
        segment_ids={int(consume_segment_id)} if consume_segment_id else None,
    )
    return ok({"items": items})


@router.get("/line-reports/size-plan")
def api_line_report_size_plan(
    header_id: int = Query(gt=0),
    team_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """这道线产量要不要按码填。分码料（鞋底）才要。"""
    from app.services.report_service import line_report_size_plan

    return ok(line_report_size_plan(db, principal.tenant_id, header_id, team_id))


@router.post("/line-reports")
def api_line_report(
    body: LineReportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """成型段线产量报工（P7 41.2）：组长/统计员按线报产量，一次提交=集体报工+不良登记。"""
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    try:
        result = submit_line_report(
            db,
            tenant_id=principal.tenant_id,
            operator_id=principal.employee.id,
            header_id=body.header_id,
            color_name=body.color_name,
            team_id=body.team_id,
            qualified_qty=body.qualified_qty,
            defect_qty=body.defect_qty,
            rework_qty=body.rework_qty,
            defect_type=body.defect_type,
            batch_id=body.batch_id,
            note=body.note,
            member_ids=body.member_ids,
            confirm_over_plan=body.confirm_over_plan,
            size_lines=[row.model_dump() for row in body.size_lines] if body.size_lines else None,
            workshop_counts=(
                [row.model_dump() for row in body.workshop_counts] if body.workshop_counts else None
            ),
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.post("/carton-reports")
def api_carton_report(
    body: CartonReportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """包装末道扫箱唛报工：装一箱报一箱，报工量=箱内双数，一箱只报一次。"""
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    try:
        result = submit_carton_report(
            db,
            tenant_id=principal.tenant_id,
            worker_id=principal.employee.id,
            carton_code=body.carton_code,
            confirm_over_plan=body.confirm_over_plan,
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/work-logs")
def api_work_logs(
    worker_id: int | None = None,
    department_id: int | None = None,
    order_no: str | None = None,
    segment_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    from app.services import team_service

    wid = worker_id
    worker_ids = None
    if principal.is_staff and principal.employee:
        wid = principal.employee.id
    elif not principal.is_staff and principal.employee:
        worker_ids = team_service.leader_worker_ids(db, principal.employee)
    return ok(
        salary_service.list_work_logs(
            db,
            principal.tenant_id,
            worker_id=wid,
            order_no=order_no,
            segment_id=segment_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            page=page,
            page_size=page_size,
            limit=limit,
            worker_ids=worker_ids,
        )
    )


@router.get("/work-logs/anomalies")
def api_work_log_anomalies(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """A2f：计件/成本异常核对——月底对账用，高亮异常行，不重算工资。"""
    return ok(
        piecework_anomaly.list_anomalies(
            db, user.tenant_id, date_from=date_from, date_to=date_to
        )
    )


@router.patch("/work-logs/{work_log_id}")
def api_update_work_log(
    work_log_id: int,
    body: WorkLogStatusUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.models import WorkLog
    from app.services import team_service
    from app.services.team_service import TeamError

    log = db.scalar(
        select(WorkLog).where(WorkLog.tenant_id == user.tenant_id, WorkLog.id == work_log_id)
    )
    if not log:
        raise HTTPException(status_code=404, detail="报工不存在")
    try:
        team_service.assert_work_log_in_scope(db, user, log.worker_id)
    except TeamError as e:
        raise HTTPException(status_code=403, detail=e.message)

    if body.status == "void":
        try:
            result = void_work_log(
                db,
                tenant_id=user.tenant_id,
                work_log_id=work_log_id,
                review_note=body.review_note,
                reviewed_by=user.id,
            )
        except ReportError as e:
            raise HTTPException(status_code=400, detail=e.message)
        return ok(result)

    if body.status == "valid":
        # 主管驳回申诉 → 恢复有效
        try:
            result = reject_appeal(
                db,
                tenant_id=user.tenant_id,
                work_log_id=work_log_id,
                review_note=body.review_note,
                reviewed_by=user.id,
            )
        except ReportError as e:
            raise HTTPException(status_code=400, detail=e.message)
        return ok(result)

    result = salary_service.update_work_log_status(
        db,
        user.tenant_id,
        work_log_id,
        status=body.status,
        review_note=body.review_note,
        reviewed_by=user.id,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return ok(result)


@router.patch("/work-logs/{work_log_id}/loss")
def api_update_work_log_loss(
    work_log_id: int,
    body: WorkLogLossUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.models import WorkLog
    from app.services import team_service
    from app.services.team_service import TeamError

    log = db.scalar(
        select(WorkLog).where(WorkLog.tenant_id == user.tenant_id, WorkLog.id == work_log_id)
    )
    if not log:
        raise HTTPException(status_code=404, detail="报工不存在")
    try:
        team_service.assert_work_log_in_scope(db, user, log.worker_id)
    except TeamError as e:
        raise HTTPException(status_code=403, detail=e.message)
    result = salary_service.update_work_log_loss(
        db,
        user.tenant_id,
        work_log_id,
        loss_borne_percent=body.loss_borne_percent,
        loss_amount=body.loss_amount,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return ok(result)


@router.post("/work-logs/{work_log_id}/appeal")
def api_appeal_work_log(
    work_log_id: int,
    body: WorkLogAppealRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    try:
        result = appeal_work_log(
            db,
            tenant_id=principal.tenant_id,
            work_log_id=work_log_id,
            worker_id=principal.employee.id,
            reason=body.reason,
        )
    except ReportError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.post("/work-logs/{work_log_id}/correct")
def api_correct_work_log(
    work_log_id: int,
    body: WorkLogCorrectRequest,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.models import WorkLog
    from app.services import team_service
    from app.services.team_service import TeamError

    log = db.scalar(
        select(WorkLog).where(WorkLog.tenant_id == user.tenant_id, WorkLog.id == work_log_id)
    )
    if not log:
        raise HTTPException(status_code=404, detail="报工不存在")
    try:
        team_service.assert_work_log_in_scope(db, user, log.worker_id)
    except TeamError as e:
        raise HTTPException(status_code=403, detail=e.message)

    try:
        result = correct_work_log(
            db,
            tenant_id=user.tenant_id,
            work_log_id=work_log_id,
            qualified_qty=body.qualified_qty,
            defect_qty=body.defect_qty,
            rework_qty=body.rework_qty,
            color_name=body.color_name,
            size_value=body.size_value,
            review_note=body.review_note,
            loss_borne_percent=body.loss_borne_percent,
            loss_amount=body.loss_amount,
            reviewed_by=user.id,
        )
    except ReportError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/salary")
def api_salary_overview(
    year_month: str | None = None,
    worker_id: int | None = None,
    department_id: int | None = None,
    settle_through: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        data = salary_service.month_salary_all(
            db,
            user.tenant_id,
            year_month,
            worker_id=worker_id,
            department_id=department_id,
            settle_through=settle_through,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    items = data.get("items") or []
    data["items"] = items
    data["total"] = len(items)
    return ok(data)


@router.get("/salary/lock")
def api_salary_lock_get(
    year_month: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    return ok(salary_service.get_month_lock(db, user.tenant_id, year_month))


@router.post("/salary/settle")
def api_salary_settle(
    body: dict,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    year_month = str(body.get("year_month") or "").strip()
    settle_through = body.get("settle_through")
    try:
        data = salary_service.settle_month(
            db,
            user.tenant_id,
            year_month,
            settle_through,
            settled_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ok(data)


@router.post("/salary/lock")
def api_salary_lock_set(
    body: dict,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    year_month = str(body.get("year_month") or "").strip()
    locked = bool(body.get("locked"))
    note = body.get("note")
    settle_through = body.get("settle_through")
    try:
        data = salary_service.set_month_lock(
            db,
            user.tenant_id,
            year_month,
            locked=locked,
            locked_by=user.id,
            note=note,
            settle_through=settle_through,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ok(data)


@router.get("/salary/export")
def api_salary_export(
    year_month: str | None = None,
    department_id: int | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.salary.export")),
):
    csv_text = salary_service.export_month_salary_csv(
        db, user.tenant_id, year_month, department_id=department_id
    )
    ym = year_month or "current"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="salary_{ym}.csv"'},
    )


@router.get("/salary/export-bank")
def api_salary_export_bank(
    year_month: str | None = None,
    department_id: int | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.salary.export")),
):
    try:
        csv_text = salary_service.export_bank_payroll_csv(
            db, user.tenant_id, year_month, department_id=department_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ym = year_month or "current"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bank_payroll_{ym}.csv"'},
    )


@router.get("/salary/reconcile")
def api_salary_reconcile(
    year_month: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """工资 vs 实际人工成本对账（A2g）。须注册在 /salary/{worker_id} 之前。"""
    try:
        data = salary_service.reconcile_salary_cost(db, user.tenant_id, year_month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ok(data)


@router.post("/salary/{worker_id}/confirm")
def api_salary_confirm(
    worker_id: int,
    body: SalaryConfirmRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if principal.is_staff:
        if not principal.employee or principal.employee.id != worker_id:
            raise HTTPException(status_code=403, detail="只能确认自己的工资")
    elif principal.is_staff:
        raise HTTPException(status_code=403, detail="无权限")
    else:
        # 管理端可代为查看，但不代签；仅员工本人确认
        raise HTTPException(status_code=403, detail="请使用员工账号签字确认")
    try:
        data = salary_service.acknowledge_salary(
            db,
            principal.tenant_id,
            worker_id,
            year_month=body.year_month,
            confirm_name=body.confirm_name,
            signature_data=body.signature_data,
            note=body.note,
            source="h5",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ok(data)


@router.get("/salary/{worker_id}")
def api_salary(
    worker_id: int,
    year_month: str | None = None,
    settle_through: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if principal.is_staff and principal.employee and principal.employee.id != worker_id:
        raise HTTPException(status_code=403, detail="只能查看自己的工资")
    data = salary_service.month_salary(
        db,
        principal.tenant_id,
        worker_id,
        year_month,
        settle_through=settle_through,
    )
    if data.get("error"):
        raise HTTPException(status_code=404 if data["error"] == "工人不存在" else 400, detail=data["error"])
    return ok(data)


@router.get("/progress/orders/{order_no}")
def api_order_progress(
    order_no: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    data = progress_service.order_progress(db, principal.tenant_id, order_no)
    if data.get("error"):
        raise HTTPException(status_code=404, detail=data["error"])
    return ok(data)


@router.get("/progress/today")
def api_today(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    from app.services import team_service

    worker_ids = None
    if not principal.is_staff and principal.employee:
        worker_ids = team_service.leader_worker_ids(db, principal.employee)
    return ok(progress_service.today_output(db, principal.tenant_id, worker_ids=worker_ids))


@router.get("/progress/board")
def api_progress_board(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    from app.services import team_service

    worker_ids = None
    order_ids = None
    if not principal.is_staff and principal.employee:
        worker_ids = team_service.leader_worker_ids(db, principal.employee)
        order_ids = team_service.leader_order_ids(db, principal.employee, worker_ids)
    return ok(
        progress_service.progress_board(
            db, principal.tenant_id, order_ids=order_ids, worker_ids=worker_ids
        )
    )


@router.get("/workshop-display")
def api_workshop_display(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    """车间投屏专用数据（工人/班组长视角，无财务）。"""
    if principal.is_staff:
        raise HTTPException(status_code=403, detail="仅员工账号可查看投屏看板")
    return ok(workshop_display_service.workshop_display(db, principal.tenant_id))


@router.post("/chat")
def api_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    worker_id = body.worker_id
    if principal.is_staff and principal.employee:
        worker_id = principal.employee.id
    result = handle_chat(
        db,
        tenant_id=principal.tenant_id,
        text=body.text,
        worker_id=worker_id,
        openid=body.openid,
        confirm=body.confirm,
    )
    return ok(result)
