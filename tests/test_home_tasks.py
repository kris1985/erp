"""首页任务：各工序段只看见本段未完工生产单。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    Department,
    Employee,
    ExecutionHeader,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    Size,
    SpecExecutionOrder,
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


def test_home_tasks_only_show_own_segment():
    session = _db()
    tenant = Tenant(name="任务厂")
    session.add(tenant)
    session.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="截断", code="cut", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    session.add_all([cut, stitch])
    session.flush()
    cut_dep = Department(tenant_id=tenant.id, name="裁断部", process_segment_id=cut.id)
    stitch_dep = Department(tenant_id=tenant.id, name="针车部", process_segment_id=stitch.id)
    session.add_all([cut_dep, stitch_dep])
    session.flush()
    cutter = Employee(
        tenant_id=tenant.id,
        name="裁断工",
        mobile="13800002001",
        department_id=cut_dep.id,
        is_active=True,
    )
    stitcher = Employee(
        tenant_id=tenant.id,
        name="针车工",
        mobile="13800002002",
        department_id=stitch_dep.id,
        is_active=True,
    )
    session.add_all([cutter, stitcher])
    session.flush()

    cut_proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        segment_id=cut.id,
    )
    stitch_proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="STITCH",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        segment_id=stitch.id,
    )
    session.add_all([cut_proc, stitch_proc])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="OP-RUN-01", is_active=True)
    session.add(product)
    session.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    session.add(color)
    session.flush()

    active = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-20260821-0008",
        own_product_id=product.id,
        color_id=color.id,
        total_qty=24,
        status=SpecExecutionStatus.in_progress,
    )
    done = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-DONE-0001",
        own_product_id=product.id,
        total_qty=10,
        status=SpecExecutionStatus.in_progress,
    )
    # 头上无色，颜色只在码明细上 —— 应能回退显示
    fallback = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-COLOR-FALLBACK",
        own_product_id=product.id,
        color_id=None,
        total_qty=12,
        status=SpecExecutionStatus.cut,
    )
    session.add_all([active, done, fallback])
    session.flush()
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=1)
    session.add(size)
    session.flush()
    session.add(
        SpecExecutionOrder(
            tenant_id=tenant.id,
            execution_no="XE-COLOR-FALLBACK-40",
            header_id=fallback.id,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            total_qty=12,
            status=SpecExecutionStatus.cut,
        )
    )
    session.add_all(
        [
            OrderProcess(
                tenant_id=tenant.id,
                header_id=active.id,
                process_id=cut_proc.id,
                process_name="裁断",
                process_type=ProcessType.personal,
                plan_qty=24,
                completed_qty=8,
                status=OrderProcessStatus.in_progress,
                segment_id=cut.id,
            ),
            OrderProcess(
                tenant_id=tenant.id,
                header_id=active.id,
                process_id=stitch_proc.id,
                process_name="针车",
                process_type=ProcessType.personal,
                plan_qty=24,
                completed_qty=0,
                status=OrderProcessStatus.pending,
                segment_id=stitch.id,
            ),
            OrderProcess(
                tenant_id=tenant.id,
                header_id=done.id,
                process_id=cut_proc.id,
                process_name="裁断",
                process_type=ProcessType.personal,
                plan_qty=10,
                completed_qty=10,
                status=OrderProcessStatus.completed,
                segment_id=cut.id,
            ),
            OrderProcess(
                tenant_id=tenant.id,
                header_id=fallback.id,
                process_id=cut_proc.id,
                process_name="裁断",
                process_type=ProcessType.personal,
                plan_qty=12,
                completed_qty=0,
                status=OrderProcessStatus.pending,
                segment_id=cut.id,
            ),
        ]
    )
    session.commit()

    client = _client(session)
    cut_res = client.get("/api/v1/home/overview", headers=_auth(cutter))
    assert cut_res.status_code == 200
    cut_tasks = cut_res.json()["data"]["tasks"]
    by_no = {row["header_no"]: row for row in cut_tasks}
    assert "XE-20260821-0008" in by_no
    assert by_no["XE-20260821-0008"]["color_name"] == "黑"
    assert "XE-COLOR-FALLBACK" in by_no
    assert by_no["XE-COLOR-FALLBACK"]["color_name"] == "黑"

    stitch_res = client.get("/api/v1/home/overview", headers=_auth(stitcher))
    assert stitch_res.status_code == 200
    stitch_tasks = stitch_res.json()["data"]["tasks"]
    assert len(stitch_tasks) == 1
    assert stitch_tasks[0]["task_name"] == "针车"
    assert stitch_tasks[0]["segment_code"] == "stitch"
    assert stitch_tasks[0]["completed_qty"] == 0

    app.dependency_overrides.clear()
    session.close()
