"""客户/供应商结算政策与周期对账单。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.api import PartnerSettlementPolicyInput
from app.schemas.common import ok, paginate_sequence
from app.services import settlement_service


router = APIRouter(tags=["settlements"])


def _http(exc: settlement_service.SettlementError):
    raise HTTPException(status_code=400, detail=exc.message) from exc


class StatementGenerateIn(BaseModel):
    partner_id: int
    direction: str
    period_start: date
    period_end: date
    statement_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


class SettlementPolicyTemplateIn(PartnerSettlementPolicyInput):
    name: str
    direction: str
    is_default: bool = False


@router.get("/settlement-policy-templates")
def api_list_settlement_policy_templates(
    direction: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(
            settlement_service.list_policy_templates(
                db, user.tenant_id, direction=direction, active_only=active_only
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.post("/settlement-policy-templates")
def api_create_settlement_policy_template(
    body: SettlementPolicyTemplateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(
            settlement_service.upsert_policy_template(
                db, user.tenant_id, **body.model_dump()
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.put("/settlement-policy-templates/{template_id}")
def api_update_settlement_policy_template(
    template_id: int,
    body: SettlementPolicyTemplateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(
            settlement_service.upsert_policy_template(
                db, user.tenant_id, template_id=template_id, **body.model_dump()
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.delete("/settlement-policy-templates/{template_id}")
def api_delete_settlement_policy_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        settlement_service.delete_policy_template(db, user.tenant_id, template_id)
        return ok({"deleted": True})
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.get("/settlement-policies/{partner_id}/{direction}")
def api_get_settlement_policy(
    partner_id: int,
    direction: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(settlement_service.get_policy(db, user.tenant_id, partner_id, direction))
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.put("/settlement-policies/{partner_id}/{direction}")
def api_upsert_settlement_policy(
    partner_id: int,
    direction: str,
    body: PartnerSettlementPolicyInput,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(
            settlement_service.upsert_policy(
                db,
                user.tenant_id,
                partner_id,
                direction,
                **body.model_dump(),
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.get("/account-statements")
def api_list_account_statements(
    partner_id: Optional[int] = None,
    direction: Optional[str] = None,
    partner_type: Optional[str] = Query(None, description="customer|supplier|subcontractor"),
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        rows = settlement_service.list_statements(
            db,
            user.tenant_id,
            partner_id=partner_id,
            direction=direction,
            partner_type=partner_type,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
        return ok(paginate_sequence(rows, page, page_size))
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.post("/account-statements/generate")
def api_generate_account_statement(
    body: StatementGenerateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(
            settlement_service.generate_statement(
                db,
                user.tenant_id,
                **body.model_dump(),
                user_id=user.id,
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.get("/account-statements/{statement_id}")
def api_get_account_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(
            settlement_service.statement_out(
                db, user.tenant_id, statement_id, with_lines=True
            )
        )
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.get("/account-statements/{statement_id}/export")
def api_export_account_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """导出对账单 Excel（版式对齐打印预览）。"""
    from datetime import datetime
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.services.settlement_export import build_statement_workbook

    try:
        detail = settlement_service.statement_out(
            db, user.tenant_id, statement_id, with_lines=True
        )
    except settlement_service.SettlementError as exc:
        _http(exc)
    content = build_statement_workbook(detail)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    statement_no = detail.get("statement_no") or str(statement_id)
    filename = f"对账单_{statement_no}_{stamp}.xlsx"
    ascii_name = f"statement_{statement_id}_{stamp}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/account-statements/{statement_id}/export-pdf")
def api_export_account_statement_pdf(
    statement_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    """导出对账单 PDF（用于浏览器打印，样式与 Excel 完全一致）。"""
    from app.services.settlement_export import build_statement_workbook, workbook_to_pdf

    try:
        detail = settlement_service.statement_out(
            db, user.tenant_id, statement_id, with_lines=True
        )
    except settlement_service.SettlementError as exc:
        _http(exc)
    xlsx_bytes = build_statement_workbook(detail)
    try:
        pdf_bytes = workbook_to_pdf(xlsx_bytes)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="PDF 导出需要安装 LibreOffice",
        )
    from fastapi.responses import Response

    statement_no = detail.get("statement_no") or str(statement_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="statement_{statement_no}.pdf"'
        },
    )


@router.post("/account-statements/{statement_id}/confirm")
def api_confirm_account_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(settlement_service.confirm_statement(db, user.tenant_id, statement_id))
    except settlement_service.SettlementError as exc:
        _http(exc)


@router.post("/account-statements/{statement_id}/void")
def api_void_account_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "finance")),
):
    try:
        return ok(settlement_service.void_statement(db, user.tenant_id, statement_id))
    except settlement_service.SettlementError as exc:
        _http(exc)
