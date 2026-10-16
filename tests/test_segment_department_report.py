"""扫码报工：工序段对应部门的负责人可以集体报工，其他人只能报自己。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Department,
    Employee,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    Size,
    Tenant,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.department_scope import led_segment_departments, segment_leader_department_ids
from app.services.order_service import create_order
from app.services.report_service import ReportError, submit_report


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="报工厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    session.commit()
    yield session
    session.close()


def _seed(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    segment = ProcessSegment(tenant_id=tenant.id, name="裁断部", code="cut", sort_order=1)
    db.add(segment)
    db.flush()
    department = Department(
        tenant_id=tenant.id,
        name="裁断部",
        process_segment_id=segment.id,
        is_active=True,
    )
    child = Department(
        tenant_id=tenant.id,
        name="裁断一组",
        parent_id=None,
        is_active=True,
    )
    db.add_all([department, child])
    db.flush()
    child.parent_id = department.id
    leader = Employee(tenant_id=tenant.id, name="负责人", mobile="13900000001", department_id=department.id)
    worker = Employee(tenant_id=tenant.id, name="裁断工", mobile="13900000002", department_id=department.id)
    child_worker = Employee(tenant_id=tenant.id, name="一组工", mobile="13900000003", department_id=child.id)
    outsider = Employee(tenant_id=tenant.id, name="外部门", mobile="13900000004")
    db.add_all([leader, worker, child_worker, outsider])
    db.flush()
    department.leader_id = leader.id
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
        segment_id=segment.id,
    )
    db.add(proc)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SHOE", is_active=True)
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    db.commit()
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            own_product_id=product.id,
            customer_name="C",
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=20)],
        ),
        created_by=None,
    )
    return tenant, order, segment, department, child, leader, worker, child_worker, outsider


def test_leader_scope_includes_child_department(db):
    _tenant, _order, segment, department, child, leader, _worker, _child_worker, _outsider = _seed(db)
    rows = led_segment_departments(db, leader)
    assert rows == [{"segment_id": segment.id, "department_ids": sorted([department.id, child.id])}]
    scope = segment_leader_department_ids(db, leader.tenant_id, leader.id, segment.id)
    assert scope == {department.id, child.id}
    assert segment_leader_department_ids(db, leader.tenant_id, _worker.id, segment.id) == set()


def test_only_segment_department_leader_can_report_for_others(db):
    tenant, order, _segment, _department, _child, leader, worker, child_worker, outsider = _seed(db)
    with pytest.raises(ReportError) as blocked:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="裁断",
            qualified_qty=4,
            proxy=True,
            beneficiary_worker_ids=[worker.id, child_worker.id],
            shares=[
                {"worker_id": worker.id, "pairs": 2},
                {"worker_id": child_worker.id, "pairs": 2},
            ],
        )
    assert blocked.value.code == "personal_report_only"

    with pytest.raises(ReportError) as outsider_blocked:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=leader.id,
            order_no=order.order_no,
            process_name="裁断",
            qualified_qty=2,
            proxy=True,
            beneficiary_worker_ids=[outsider.id],
        )
    assert outsider_blocked.value.code == "not_in_department"

    own = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="裁断",
        qualified_qty=2,
        proxy=True,
        beneficiary_worker_ids=[worker.id],
    )
    assert own["qualified_qty"] == 2

    group = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=leader.id,
        order_no=order.order_no,
        process_name="裁断",
        qualified_qty=4,
        proxy=True,
        beneficiary_worker_ids=[leader.id, child_worker.id],
        shares=[
            {"worker_id": leader.id, "pairs": 2},
            {"worker_id": child_worker.id, "pairs": 2},
        ],
    )
    assert set(group["beneficiary_worker_ids"]) == {leader.id, child_worker.id}
