"""甘特单道工序编辑（patch_draft_job_process）：改开始日 / 改天数。

覆盖：改日期、改天数、其它工序不动、早于今天钳制、非草稿拒绝、链重叠提示。
运行：pytest tests/test_aps_gantt_process_edit.py -s -v
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ExecutionScheduleDraft, ExecutionScheduleDraftStatus, Tenant
from app.services import execution_schedule_service as ess
from app.services.execution_schedule_service import ExecutionScheduleError

AS_OF = date.today()


def _win(process_id, process_name, days, start_offset):
    from app.services import schedule_calendar as scal

    start, end = scal.workday_span_starting(
        scal.next_workday(AS_OF + timedelta(days=start_offset)), days
    )
    return {
        "process_id": process_id,
        "process_name": process_name,
        "plan_qty": 5000,
        "days": days,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "source": "standard",
    }


@pytest.fixture()
def draft():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="甘特编辑厂", settings_json={})
    session.add(tenant)
    session.flush()
    payload = {
        "strategy": "delivery_first",
        "jobs": [
            {
                "key": "JOB-1",
                "label": "女鞋A",
                "delivery_date": (AS_OF + timedelta(days=30)).isoformat(),
                "total_qty": 5000,
                "is_rush": False,
                "first_kit_ok": True,
                "kit_ok": True,
                "windows": [
                    _win(101, "裁断", 3, 0),
                    _win(102, "针车", 5, 3),
                ],
            }
        ],
    }
    d = ExecutionScheduleDraft(
        tenant_id=tenant.id, status=ExecutionScheduleDraftStatus.draft, payload=payload
    )
    session.add(d)
    session.commit()
    yield session, tenant.id, d.id
    session.close()


def _jobs(out: dict):
    return out["jobs"] if isinstance(out.get("jobs"), list) else out.get("data", {}).get("jobs", [])


def _patch(session, tenant_id, draft_id, job_key, process_id, **kw):
    return ess.patch_draft_job_process(
        session, tenant_id=tenant_id, draft_id=draft_id, job_key=job_key,
        process_id=process_id, commit=False, **kw
    )


def test_change_start_date_keeps_days(draft, capsys):
    session, tenant_id, draft_id = draft
    new_start = AS_OF + timedelta(days=10)
    out = _patch(session, tenant_id, draft_id, "JOB-1", 101, start_date=new_start)
    jobs = _jobs(out)
    win = next(w for w in jobs[0]["windows"] if w["process_id"] == 101)
    from app.services import schedule_calendar as scal

    assert win["start_date"] == scal.next_workday(new_start).isoformat()
    assert win["days"] == 3  # 天数保持
    # 其它工序不动
    other = next(w for w in jobs[0]["windows"] if w["process_id"] == 102)
    assert other["start_date"] == _win(102, "针车", 5, 3)["start_date"]
    print(f"\n改开始日: 裁断 {win['start_date']} 起 {win['days']} 天；针车未动")


def test_change_days_recomputes_end(draft, capsys):
    session, tenant_id, draft_id = draft
    out = _patch(session, tenant_id, draft_id, "JOB-1", 101, days=7)
    jobs = _jobs(out)
    win = next(w for w in jobs[0]["windows"] if w["process_id"] == 101)
    from app.services import schedule_calendar as scal

    expect_end = scal.workday_span_starting(date.fromisoformat(win["start_date"]), 7)[1]
    assert win["days"] == 7
    assert win["end_date"] == expect_end.isoformat()
    print(f"\n改天数: 裁断 {win['days']} 天 → {win['start_date']}~{win['end_date']}")


def test_start_clamped_to_today(draft):
    session, tenant_id, draft_id = draft
    out = _patch(session, tenant_id, draft_id, "JOB-1", 101, start_date=AS_OF - timedelta(days=2))
    jobs = _jobs(out)
    win = next(w for w in jobs[0]["windows"] if w["process_id"] == 101)
    from app.services import schedule_calendar as scal

    assert win["start_date"] == scal.next_workday(AS_OF).isoformat()


def test_overlap_adds_note(draft, capsys):
    session, tenant_id, draft_id = draft
    # 把针车挪到与裁断重叠
    out = _patch(session, tenant_id, draft_id, "JOB-1", 102, start_date=AS_OF)
    jobs = _jobs(out)
    notes = jobs[0].get("notes") or []
    assert any("重叠" in n or "倒挂" in n for n in notes), notes
    print(f"\n重叠提示: {[n for n in notes if '重叠' in n or '倒挂' in n]}")


def test_non_draft_rejected(draft):
    session, tenant_id, draft_id = draft
    d = session.get(ExecutionScheduleDraft, draft_id)
    d.status = ExecutionScheduleDraftStatus.confirmed
    session.commit()
    with pytest.raises(ExecutionScheduleError, match="仅草案可改"):
        _patch(session, tenant_id, draft_id, "JOB-1", 101, start_date=AS_OF)


def test_empty_patch_rejected(draft):
    session, tenant_id, draft_id = draft
    with pytest.raises(ExecutionScheduleError, match="请提供开始日期或天数"):
        _patch(session, tenant_id, draft_id, "JOB-1", 101)
