"""H5 首页概览：员工看本人，班组长看本班组；不包含组员薪资。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProcessDefinition, ReportType, WorkLog, WorkLogStatus, Employee
from app.services import salary_service, team_service


def _is_rework(log: WorkLog) -> bool:
    value = log.report_type.value if hasattr(log.report_type, "value") else str(log.report_type)
    return value == ReportType.rework.value


def worker_home_overview(db: Session, tenant_id: int, worker: Employee) -> dict:
    """返回员工或其所带班组的今日概览，金额仅限员工本人模式。"""
    team = None
    if team_service.is_leader(db, worker):
        teams = team_service.list_teams(db, tenant_id, leader_worker_id=worker.id)
        team = teams[0] if teams else None

    member_ids = {worker.id}
    if team:
        member_ids.update(int(member["id"]) for member in team.get("members", []) if member.get("id"))

    today = datetime.now().date()
    base_filters = [
        WorkLog.tenant_id == tenant_id,
        WorkLog.worker_id.in_(member_ids),
        WorkLog.status == WorkLogStatus.valid,
        func.date(WorkLog.created_at) == today,
    ]
    qualified, defects, record_count, reporter_count = db.execute(
        select(
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
            func.count(WorkLog.id),
            func.count(func.distinct(WorkLog.worker_id)),
        ).where(*base_filters)
    ).one()

    recent_rows = db.execute(
        select(WorkLog, Employee.name, ProcessDefinition.name)
        .join(Employee, Employee.id == WorkLog.worker_id)
        .outerjoin(ProcessDefinition, ProcessDefinition.id == WorkLog.process_id)
        .where(*base_filters)
        .order_by(WorkLog.created_at.desc(), WorkLog.id.desc())
        .limit(3)
    ).all()
    recent = []
    for log, worker_name, process_name in recent_rows:
        type_value = log.report_type.value if hasattr(log.report_type, "value") else str(log.report_type)
        recent.append(
            {
                "id": log.id,
                "worker_name": worker_name,
                "process_name": process_name or "工序待补充",
                "report_type": type_value,
                "qty": int(log.rework_qty if _is_rework(log) else log.qualified_qty or 0),
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
        )

    is_leader = team is not None
    result = {
        "mode": "leader" if is_leader else "worker",
        "team_name": team.get("name") if team else None,
        "team_member_count": int(team.get("member_count", len(team.get("members", [])))) if team else 0,
        "today": {
            "qualified": int(qualified or 0),
            "defects": int(defects or 0),
            "record_count": int(record_count or 0),
            "reporter_count": int(reporter_count or 0),
        },
        "recent": recent,
    }
    if not is_leader:
        salary = salary_service.month_salary(db, tenant_id, worker.id)
        result["month"] = {
            "amount": salary.get("total_wage", salary.get("total_piece_wage", 0)),
            "is_locked": bool(salary.get("is_locked")),
        }
    return result
