"""领任务必须填写双数，并按数量写入当前任务配额。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Department,
    Employee,
    ExecutionHeader,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessStatus,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    SpecExecutionStatus,
    Tenant,
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


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


def _setup(session):
    tenant = Tenant(name="领取厂")
    session.add(tenant)
    session.flush()
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    session.add(stitch)
    session.flush()
    dep = Department(tenant_id=tenant.id, name="针车部", process_segment_id=stitch.id)
    session.add(dep)
    session.flush()
    worker_a = Employee(
        tenant_id=tenant.id,
        name="针车甲",
        mobile="13800003001",
        department_id=dep.id,
        is_active=True,
    )
    worker_b = Employee(
        tenant_id=tenant.id,
        name="针车乙",
        mobile="13800003002",
        department_id=dep.id,
        is_active=True,
    )
    session.add_all([worker_a, worker_b])
    session.flush()
    proc_upper = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车上线",
        code="STITCH-1",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        segment_id=stitch.id,
    )
    proc_bottom = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车下线",
        code="STITCH-2",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        segment_id=stitch.id,
    )
    session.add_all([proc_upper, proc_bottom])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="OP-CLAIM-01", is_active=True)
    session.add(product)
    session.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-CLAIM-0001",
        own_product_id=product.id,
        total_qty=80,
        status=SpecExecutionStatus.in_progress,
    )
    session.add(header)
    session.flush()
    processes = [
        OrderProcess(
            tenant_id=tenant.id,
            header_id=header.id,
            process_id=proc_upper.id,
            process_name="针车上线",
            process_type=ProcessType.personal,
            plan_qty=80,
            completed_qty=0,
            status=OrderProcessStatus.pending,
            segment_id=stitch.id,
        ),
        OrderProcess(
            tenant_id=tenant.id,
            header_id=header.id,
            process_id=proc_bottom.id,
            process_name="针车下线",
            process_type=ProcessType.personal,
            plan_qty=80,
            completed_qty=0,
            status=OrderProcessStatus.in_progress,
            segment_id=stitch.id,
        ),
    ]
    session.add_all(processes)
    session.commit()
    return header, processes, worker_a, worker_b


def test_claim_task_requires_qty_and_rejects_over_claim():
    session = _db()
    header, processes, worker_a, worker_b = _setup(session)
    client = _client(session)
    url = f"/api/v1/executions/headers/{header.id}/claim-task"

    missing = client.post(url, json={"segment_code": "stitch"}, headers=_auth(worker_a))
    assert missing.status_code == 422

    first = client.post(url, json={"segment_code": "stitch", "qty": 50}, headers=_auth(worker_a))
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["qty"] == 50
    assert data["remaining_qty"] == 30
    assert data["claimed"] is True

    home = client.get("/api/v1/home/overview", headers=_auth(worker_a))
    assert home.status_code == 200, home.text
    tasks = home.json()["data"]["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["header_no"] == "XE-CLAIM-0001"
    assert tasks[0]["qty"] == 50
    assert tasks[0]["completed_qty"] == 0
    assert client.get("/api/v1/home/overview", headers=_auth(worker_b)).json()["data"]["tasks"] == []

    session.expire_all()
    assigned = list(
        session.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.header_id == header.id,
                OrderProcessAssignment.worker_id == worker_a.id,
            )
        ).all()
    )
    assert len(assigned) == 2
    assert {row.order_process_id for row in assigned} == {processes[0].id, processes[1].id}
    assert all(row.quota_qty == 50 for row in assigned)

    over = client.post(url, json={"segment_code": "stitch", "qty": 50}, headers=_auth(worker_b))
    assert over.status_code == 400
    assert "还可领 30 双" in over.json()["detail"]

    second = client.post(url, json={"segment_code": "stitch", "qty": 30}, headers=_auth(worker_b))
    assert second.status_code == 200, second.text
    assert second.json()["data"]["qty"] == 30
    assert second.json()["data"]["remaining_qty"] == 0

    session.expire_all()
    b_rows = list(
        session.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.header_id == header.id,
                OrderProcessAssignment.worker_id == worker_b.id,
            )
        ).all()
    )
    assert len(b_rows) == 2
    assert all(row.quota_qty == 30 for row in b_rows)

    update = client.post(url, json={"segment_code": "stitch", "qty": 40}, headers=_auth(worker_a))
    assert update.status_code == 200, update.text
    assert update.json()["data"]["claimed"] is False
    assert update.json()["data"]["qty"] == 40
    session.expire_all()
    a_rows = list(
        session.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.header_id == header.id,
                OrderProcessAssignment.worker_id == worker_a.id,
            )
        ).all()
    )
    assert all(row.quota_qty == 40 for row in a_rows)

    app.dependency_overrides.clear()
    session.close()
