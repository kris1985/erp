"""组织配置端点（工序段重构 6.x/18A/28.2-28.4）：铲皮/班组/车间叫法 + 租户初始化。

- GET/PUT /org/settings：读/写 skiving_enabled、enable_teams、team_label（D5/D6/D14）
- POST /org/setup：租户初始化向导 seed（18A，P5 支撑，权限码 org.setup）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal
from app.db import get_db
from app.models import Department, Employee, ProcessSegment, Team
from app.schemas.common import ok
from app.services import org_settings
from app.services.segment_service import ensure_default_segments

router = APIRouter(prefix="/org", tags=["org"])


@router.get("/settings")
def api_get_org_settings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    tenant_id = principal.tenant_id
    return ok(
        {
            "enable_teams": org_settings.enable_teams(db, tenant_id),
            "team_label": org_settings.get_team_label(db, tenant_id),
            "skiving_enabled": org_settings.is_skiving_enabled(db, tenant_id),
        }
    )


@router.put("/settings")
def api_put_org_settings(
    body: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    tenant_id = principal.tenant_id
    out: dict = {}
    if "skiving_enabled" in body:
        out.update(org_settings.set_skiving_enabled(db, tenant_id, bool(body["skiving_enabled"])))
    if "team_label" in body:
        out.update(org_settings.set_team_label(db, tenant_id, str(body["team_label"])))
    if "enable_teams" in body:
        # 6.5：开启时对已有挂段部门 ensure 默认组（可见化）
        out.update(org_settings.set_enable_teams(db, tenant_id, bool(body["enable_teams"])))
    return ok(out)


@router.post("/setup")
def api_org_setup(
    body: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """租户初始化向导 seed（18A.1-18A.3，幂等）。

    body: {mode: 'simple'|'teams', team_label?, skiving_enabled?, leader_map?}
      simple：生产部 → 4/5 个段部门 → 每部门一个 is_default 默认组（无组长）；enable_teams=false
      teams ：同结构 + 默认组可指定组长（leader_map: 段code→员工id）；enable_teams=true
    老租户（已有部门数据）跳过；重复调用幂等。
    """
    tenant_id = principal.tenant_id
    dept_count = db.scalar(
        select(func.count())
        .select_from(Department)
        .where(Department.tenant_id == tenant_id)
    ) or 0
    if dept_count > 0:
        return ok({"skipped": True, "message": "已有组织数据，跳过初始化"})

    mode = str(body.get("mode", "simple"))
    if mode not in ("simple", "teams"):
        raise HTTPException(status_code=400, detail="mode 须为 simple 或 teams")
    team_label = str(body.get("team_label") or "班组")
    skiving = bool(body.get("skiving_enabled", False))
    leader_map = body.get("leader_map") or {}

    ensure_default_segments(db, tenant_id)
    db.flush()
    segs = {
        s.code: s
        for s in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }

    production = Department(
        tenant_id=tenant_id, name="生产部", sort_order=1, is_active=True
    )
    db.add(production)
    db.flush()

    created_depts = []
    for code in ("cut", "stitch", "forming", "packing"):
        seg = segs.get(code)
        if not seg:
            continue
        dep = Department(
            tenant_id=tenant_id,
            name=f"{seg.name}部",
            parent_id=production.id,
            process_segment_id=seg.id,
            sort_order=seg.sort_order,
            is_active=True,
        )
        db.add(dep)
        db.flush()
        created_depts.append((code, dep, seg))
    if skiving:
        seg = segs.get("skiving")
        if seg:
            dep = Department(
                tenant_id=tenant_id,
                name="铲皮部",
                parent_id=production.id,
                process_segment_id=seg.id,
                sort_order=seg.sort_order,
                is_active=True,
            )
            db.add(dep)
            db.flush()
            created_depts.append(("skiving", dep, seg))

    # 每段部门一个默认组（simple 无组长；teams 按 leader_map 指定）
    for code, dep, seg in created_depts:
        leader_id = None
        if mode == "teams":
            raw = leader_map.get(code) or leader_map.get(seg.name)
            if raw is not None:
                ldr = db.get(Employee, int(raw))
                if ldr and ldr.tenant_id == tenant_id:
                    leader_id = ldr.id
                    dep.leader_id = leader_id
        team = Team(
            tenant_id=tenant_id,
            name=f"{seg.name}组",
            leader_worker_id=leader_id,
            department_id=dep.id,
            segment_id=seg.id,
            is_default=True,
            is_active=True,
        )
        db.add(team)
        db.flush()

    # 组织配置
    org_settings.set_enable_teams(db, tenant_id, mode == "teams")
    org_settings.set_team_label(db, tenant_id, team_label)
    org_settings.set_skiving_enabled(db, tenant_id, skiving)
    db.commit()
    return ok(
        {
            "skipped": False,
            "mode": mode,
            "departments": len(created_depts),
            "enable_teams": mode == "teams",
            "team_label": team_label,
            "skiving_enabled": skiving,
        }
    )
