from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_employee, get_principal, require_roles, Principal
from app.db import get_db
from app.models import Employee
from app.schemas.api import (
    ChatRequest,
    LineReportRequest,
    ReportRequest,
    CartonReportRequest,
    SalaryConfirmRequest,
    WorkLogAppealRequest,
    WorkLogCorrectRequest,
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
    void_work_log,
)

router = APIRouter(tags=["ops"])


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
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


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
    order_no: str | None = None,
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
            reviewed_by=user.id,
        )
    except ReportError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/salary")
def api_salary_overview(
    year_month: str | None = None,
    worker_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    from app.schemas.common import paginate_sequence

    data = salary_service.month_salary_all(
        db, user.tenant_id, year_month, worker_id=worker_id
    )
    items = data.get("items") or []
    paged = paginate_sequence(items, page, page_size)
    return ok({**data, **paged})


@router.get("/salary/lock")
def api_salary_lock_get(
    year_month: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    return ok(salary_service.get_month_lock(db, user.tenant_id, year_month))


@router.post("/salary/lock")
def api_salary_lock_set(
    body: dict,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    year_month = str(body.get("year_month") or "").strip()
    locked = bool(body.get("locked"))
    note = body.get("note")
    try:
        data = salary_service.set_month_lock(
            db,
            user.tenant_id,
            year_month,
            locked=locked,
            locked_by=user.id,
            note=note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ok(data)


@router.get("/salary/export")
def api_salary_export(
    year_month: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    csv_text = salary_service.export_month_salary_csv(db, user.tenant_id, year_month)
    ym = year_month or "current"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="salary_{ym}.csv"'},
    )


@router.get("/salary/export-bank")
def api_salary_export_bank(
    year_month: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    try:
        csv_text = salary_service.export_bank_payroll_csv(db, user.tenant_id, year_month)
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
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if principal.is_staff and principal.employee and principal.employee.id != worker_id:
        raise HTTPException(status_code=403, detail="只能查看自己的工资")
    data = salary_service.month_salary(db, principal.tenant_id, worker_id, year_month)
    if data.get("error"):
        raise HTTPException(status_code=404, detail=data["error"])
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
