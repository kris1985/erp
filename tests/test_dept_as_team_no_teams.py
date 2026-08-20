"""无班组模式「部门=组」镜像（双向一致 A）。

- 员工挂部门 → 自动进该部门默认组（employees 创建/改部门）；
- 建子部门自动继承父部门工序段；挂段部门建即补隐身默认组（departments）；
- H5 组长加减组员 → 部门归属同步（无班组模式）；班组模式保持分离（C）。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import Department, Employee, ProcessSegment, Team, TeamMember, Tenant
from app.services import org_settings, team_service
from app.services.segment_service import ensure_default_segments


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _client(session):
    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _auth(worker):
    return {"Authorization": f"Bearer {create_worker_token(worker)}"}


def _seed(session):
    tenant = Tenant(name="直管厂")
    session.add(tenant)
    session.flush()
    ensure_default_segments(session, tenant.id)
    session.flush()
    leader = Employee(
        tenant_id=tenant.id, name="针车负责人", mobile="13800001001", is_active=True
    )
    w1 = Employee(tenant_id=tenant.id, name="张三", mobile="13800001002", is_active=True)
    w2 = Employee(tenant_id=tenant.id, name="李四", mobile="13800001003", is_active=True)
    session.add_all([leader, w1, w2])
    session.commit()
    stitch = session.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )
    assert stitch is not None
    return tenant, leader, w1, w2, stitch


def _default_team(session, tenant_id: int, department_id: int):
    return session.scalar(
        select(Team).where(
            Team.tenant_id == tenant_id,
            Team.department_id == department_id,
            Team.is_default.is_(True),
        )
    )


def test_segment_dept_created_with_default_team_and_employee_auto_joins():
    session = _db()
    tenant, leader, w1, w2, stitch = _seed(session)
    client = _client(session)

    dep_res = client.post(
        "/api/v1/departments",
        json={"name": "针车部", "process_segment_id": stitch.id, "leader_id": leader.id},
        headers=_auth(leader),
    )
    assert dep_res.status_code == 200, dep_res.text
    dep = session.get(Department, dep_res.json()["data"]["id"])
    assert dep.process_segment_id == stitch.id

    # 无班组模式：挂段部门建即补隐身默认组，负责人同步为组长
    default_team = _default_team(session, tenant.id, dep.id)
    assert default_team is not None
    assert default_team.leader_worker_id == leader.id

    # 员工挂部门 → 自动进该部门默认组
    emp_res = client.post(
        "/api/v1/employees",
        json={"name": "王五", "mobile": "13800001009", "department_id": dep.id},
        headers=_auth(leader),
    )
    assert emp_res.status_code == 200, emp_res.text
    emp = session.scalar(
        select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "王五")
    )
    member = session.scalar(
        select(TeamMember).where(TeamMember.tenant_id == tenant.id, TeamMember.worker_id == emp.id)
    )
    assert member is not None and member.team_id == default_team.id
    app.dependency_overrides.clear()
    session.close()


def test_sub_department_inherits_parent_segment():
    session = _db()
    tenant, leader, w1, w2, stitch = _seed(session)
    client = _client(session)

    dep_res = client.post(
        "/api/v1/departments",
        json={"name": "针车部", "process_segment_id": stitch.id},
        headers=_auth(leader),
    )
    parent_id = dep_res.json()["data"]["id"]
    sub_res = client.post(
        "/api/v1/departments",
        json={"name": "针车一组", "parent_id": parent_id},
        headers=_auth(leader),
    )
    assert sub_res.status_code == 200, sub_res.text
    sub = session.get(Department, sub_res.json()["data"]["id"])
    # 未传段 → 自动继承父部门段（不落"未分段"、不掉出派工候选）
    assert sub.process_segment_id == stitch.id
    # 子部门同样补默认组
    assert _default_team(session, tenant.id, sub.id) is not None
    app.dependency_overrides.clear()
    session.close()


def test_h5_member_add_remove_syncs_department_in_no_team_mode():
    session = _db()
    tenant, leader, w1, w2, stitch = _seed(session)
    client = _client(session)

    dep_res = client.post(
        "/api/v1/departments",
        json={"name": "针车部", "process_segment_id": stitch.id, "leader_id": leader.id},
        headers=_auth(leader),
    )
    dep = session.get(Department, dep_res.json()["data"]["id"])

    # 组长（=部门负责人）H5 加人 → 员工部门同步为该部门
    added = client.post(
        "/api/v1/teams/mine/members",
        json={"worker_id": w1.id},
        headers=_auth(leader),
    )
    assert added.status_code == 200, added.text
    session.refresh(w1)
    assert w1.department_id == dep.id

    # H5 移除 → 部门置空（未分段 D18）
    removed = client.delete(f"/api/v1/teams/mine/members/{w1.id}", headers=_auth(leader))
    assert removed.status_code == 200, removed.text
    session.refresh(w1)
    assert w1.department_id is None
    app.dependency_overrides.clear()
    session.close()


def test_employee_department_move_resyncs_default_team():
    session = _db()
    tenant, leader, w1, w2, stitch = _seed(session)
    client = _client(session)

    dep_a = client.post(
        "/api/v1/departments",
        json={"name": "针车一部", "process_segment_id": stitch.id, "leader_id": leader.id},
        headers=_auth(leader),
    ).json()["data"]
    dep_b = client.post(
        "/api/v1/departments",
        json={"name": "针车二部", "process_segment_id": stitch.id},
        headers=_auth(leader),
    ).json()["data"]

    emp_res = client.post(
        "/api/v1/employees",
        json={"name": "王五", "mobile": "13800001009", "department_id": dep_a["id"]},
        headers=_auth(leader),
    )
    emp = session.scalar(
        select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "王五")
    )
    team_a = _default_team(session, tenant.id, dep_a["id"])
    assert session.scalar(
        select(TeamMember).where(
            TeamMember.tenant_id == tenant.id,
            TeamMember.worker_id == emp.id,
            TeamMember.team_id == team_a.id,
        )
    )

    # 管理员把员工挪到针车二部 → 默认组跟随（从 A 组移出、进 B 组）
    moved = client.patch(
        f"/api/v1/employees/{emp.id}",
        json={"department_id": dep_b["id"]},
        headers=_auth(leader),
    )
    assert moved.status_code == 200, moved.text
    team_b = _default_team(session, tenant.id, dep_b["id"])
    assert team_b is not None
    rows = session.scalars(
        select(TeamMember).where(
            TeamMember.tenant_id == tenant.id, TeamMember.worker_id == emp.id
        )
    ).all()
    assert [r.team_id for r in rows] == [team_b.id]
    app.dependency_overrides.clear()
    session.close()


def test_team_mode_keeps_department_separate():
    session = _db()
    tenant, leader, w1, w2, stitch = _seed(session)
    client = _client(session)
    org_settings.set_enable_teams(session, tenant.id, True)

    # 班组模式：API 建挂段部门不再自动补默认组（与建组分离）
    dep_res = client.post(
        "/api/v1/departments",
        json={"name": "针车部", "process_segment_id": stitch.id},
        headers=_auth(leader),
    )
    dep = session.get(Department, dep_res.json()["data"]["id"])
    assert _default_team(session, tenant.id, dep.id) is None

    # 班组模式：组长 H5 加人 → 只改组，部门不动（C）
    team = team_service.create_team(
        session,
        tenant.id,
        name="针车一组",
        leader_worker_id=leader.id,
        worker_ids=[leader.id],
        department_id=dep.id,
    )
    session.commit()
    added = client.post(
        "/api/v1/teams/mine/members",
        json={"worker_id": w1.id},
        headers=_auth(leader),
    )
    assert added.status_code == 200, added.text
    session.refresh(w1)
    assert w1.department_id is None
    app.dependency_overrides.clear()
    session.close()
