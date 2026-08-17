"""组长 H5：组员加入 / 移除 / 姓名手机号搜索。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import Tenant, Employee
from app.services import team_service


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


def _seed(session):
    tenant = Tenant(name="班组厂")
    session.add(tenant)
    session.flush()
    leader = Employee(
        tenant_id=tenant.id,
        name="组长",
        mobile="13800001001",
        is_active=True,
    )
    w1 = Employee(tenant_id=tenant.id, name="针车甲", mobile="13800001002", is_active=True)
    w2 = Employee(tenant_id=tenant.id, name="针车乙", mobile="13900001003", is_active=True)
    other = Employee(tenant_id=tenant.id, name="他组员", mobile="13700001004", is_active=True)
    plain = Employee(
        tenant_id=tenant.id,
        name="普通工",
        mobile="13600001005",
        is_active=True,
    )
    session.add_all([leader, w1, w2, other, plain])
    session.commit()
    team = team_service.create_team(
        session,
        tenant.id,
        name="针车一组",
        leader_worker_id=leader.id,
        worker_ids=[leader.id],
    )
    other_leader = Employee(
        tenant_id=tenant.id,
        name="二组组长",
        mobile="13500001006",
        is_active=True,
    )
    session.add(other_leader)
    session.commit()
    team_service.create_team(
        session,
        tenant.id,
        name="针车二组",
        leader_worker_id=other_leader.id,
        worker_ids=[other_leader.id, other.id],
    )
    return tenant, leader, w1, w2, other, plain, team


def _auth(worker):
    return {"Authorization": f"Bearer {create_worker_token(worker)}"}


def test_leader_lists_own_team():
    session = _db()
    tenant, leader, w1, w2, other, plain, team = _seed(session)
    client = _client(session)
    res = client.get("/api/v1/teams/mine", headers=_auth(leader))
    assert res.status_code == 200
    items = res.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "针车一组"
    assert items[0]["leader_worker_id"] == leader.id

    denied = client.get("/api/v1/teams/mine", headers=_auth(plain))
    assert denied.status_code == 403
    app.dependency_overrides.clear()
    session.close()


def test_search_by_name_and_mobile_then_add_remove():
    session = _db()
    tenant, leader, w1, w2, other, plain, team = _seed(session)
    client = _client(session)
    h = _auth(leader)

    by_name = client.get("/api/v1/teams/mine/candidates", params={"q": "针车甲"}, headers=h)
    assert by_name.status_code == 200
    names = {x["name"]: x for x in by_name.json()["data"]["items"]}
    assert names["针车甲"]["can_join"] is True
    assert names["针车甲"]["status"] == "available"

    by_mobile = client.get("/api/v1/teams/mine/candidates", params={"q": "1390000"}, headers=h)
    assert by_mobile.status_code == 200
    found = by_mobile.json()["data"]["items"]
    assert any(x["id"] == w2.id and x["can_join"] for x in found)

    other_hit = client.get("/api/v1/teams/mine/candidates", params={"q": "他组员"}, headers=h)
    row = next(x for x in other_hit.json()["data"]["items"] if x["id"] == other.id)
    assert row["can_join"] is False
    assert row["status"] == "other_team"

    added = client.post(
        "/api/v1/teams/mine/members",
        json={"worker_id": w1.id},
        headers=h,
    )
    assert added.status_code == 200
    member_ids = {m["id"] for m in added.json()["data"]["members"]}
    assert w1.id in member_ids

    blocked = client.post(
        "/api/v1/teams/mine/members",
        json={"worker_id": other.id},
        headers=h,
    )
    assert blocked.status_code == 400

    removed = client.delete(f"/api/v1/teams/mine/members/{w1.id}", headers=h)
    assert removed.status_code == 200
    member_ids = {m["id"] for m in removed.json()["data"]["members"]}
    assert w1.id not in member_ids

    keep_leader = client.delete(f"/api/v1/teams/mine/members/{leader.id}", headers=h)
    assert keep_leader.status_code == 400
    app.dependency_overrides.clear()
    session.close()


def test_empty_query_rejected():
    session = _db()
    tenant, leader, w1, w2, other, plain, team = _seed(session)
    client = _client(session)
    res = client.get("/api/v1/teams/mine/candidates", params={"q": "  "}, headers=_auth(leader))
    assert res.status_code == 400
    app.dependency_overrides.clear()
    session.close()


def test_h5_home_overview_keeps_leader_and_worker_salary_scope_separate():
    session = _db()
    tenant, leader, w1, w2, other, plain, team = _seed(session)
    client = _client(session)

    leader_res = client.get("/api/v1/home/overview", headers=_auth(leader))
    assert leader_res.status_code == 200
    leader_data = leader_res.json()["data"]
    assert leader_data["mode"] == "leader"
    assert leader_data["team_name"] == "针车一组"
    assert leader_data["team_member_count"] == 1
    assert "month" not in leader_data

    worker_res = client.get("/api/v1/home/overview", headers=_auth(plain))
    assert worker_res.status_code == 200
    worker_data = worker_res.json()["data"]
    assert worker_data["mode"] == "worker"
    assert "month" in worker_data
    assert worker_data["recent"] == []

    app.dependency_overrides.clear()
    session.close()
