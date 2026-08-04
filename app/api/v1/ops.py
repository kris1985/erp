from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.schemas.api import ChatRequest, ReportRequest
from app.schemas.common import ok
from app.services import progress_service, salary_service
from app.services.nlu import handle_chat
from app.services.report_service import ReportError, submit_report

router = APIRouter(tags=["ops"])


@router.post("/reports")
def api_report(body: ReportRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        result = submit_report(
            db,
            tenant_id=user.tenant_id,
            worker_id=body.worker_id,
            order_no=body.order_no,
            process_name=body.process_name,
            qualified_qty=body.qualified_qty,
            defect_qty=body.defect_qty,
            color_name=body.color_name,
            size_value=body.size_value,
            original_text=body.original_text,
            source=body.source,
            confirm_over_plan=body.confirm_over_plan,
        )
    except ReportError as e:
        if e.need_confirm:
            return ok({"need_confirm": True, "message": e.message, **e.data})
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/salary/{worker_id}")
def api_salary(
    worker_id: int,
    year_month: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(salary_service.month_salary(db, user.tenant_id, worker_id, year_month))


@router.get("/progress/orders/{order_no}")
def api_order_progress(order_no: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = progress_service.order_progress(db, user.tenant_id, order_no)
    if data.get("error"):
        raise HTTPException(status_code=404, detail=data["error"])
    return ok(data)


@router.get("/progress/today")
def api_today(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ok(progress_service.today_output(db, user.tenant_id))


@router.post("/chat")
def api_chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = handle_chat(
        db,
        tenant_id=user.tenant_id,
        text=body.text,
        worker_id=body.worker_id,
        openid=body.openid,
        confirm=body.confirm,
    )
    return ok(result)
