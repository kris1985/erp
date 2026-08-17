"""AU-I0 M4：组报工 shares + 技能系数。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    Size,
    Tenant,
    WorkLogGroupShare,
    Employee,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order
from app.services.report_service import submit_report


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="拆分厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="灰", code="GY"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.group,
        default_price=Decimal("2"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SHARE", is_active=True)
    session.add(product)
    session.flush()
    session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("2"),
            sort_order=0,
        )
    )
    a = Employee(tenant_id=tenant.id, name="甲", mobile="13700000001", skill_factor=Decimal("1.00"))
    b = Employee(tenant_id=tenant.id, name="乙", mobile="13700000002", skill_factor=Decimal("2.00"))
    session.add_all([a, b])
    session.commit()
    color = session.scalar(select(Color).limit(1))
    size = session.scalar(select(Size).limit(1))
    order = create_order(
        session,
        tenant.id,
        OrderCreate(
            own_product_id=product.id,
            customer_name="C",
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=30)],
        ),
        created_by=None,
    )
    yield session, tenant, order, a, b
    session.close()


def test_skill_factor_prefill_shares(db):
    session, tenant, order, a, b = db
    # 派工两人
    from app.models import OrderProcess, OrderProcessAssignment

    process = session.scalar(select(OrderProcess).where(OrderProcess.order_id == order.id))
    for w in (a, b):
        session.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=w.id,
                quota_qty=None,
            )
        )
    session.commit()

    submit_report(
        session,
        tenant_id=tenant.id,
        worker_id=a.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=30,
        report_type="group",
        member_ids=[a.id, b.id],
        create_trace_bundle=False,
    )
    shares = list(session.scalars(select(WorkLogGroupShare)).all())
    assert len(shares) == 2
    by_worker = {s.worker_id: s for s in shares}
    # 权重 1:2 → 10 + 20
    assert by_worker[a.id].pairs == 10
    assert by_worker[b.id].pairs == 20
    assert by_worker[a.id].is_adjusted is False


def test_manual_shares_marked_adjusted(db):
    session, tenant, order, a, b = db
    from app.models import OrderProcess, OrderProcessAssignment

    process = session.scalar(select(OrderProcess).where(OrderProcess.order_id == order.id))
    for w in (a, b):
        session.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=w.id,
            )
        )
    session.commit()

    submit_report(
        session,
        tenant_id=tenant.id,
        worker_id=a.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=30,
        report_type="group",
        member_ids=[a.id, b.id],
        shares=[{"worker_id": a.id, "pairs": 12}, {"worker_id": b.id, "pairs": 18}],
        create_trace_bundle=False,
    )
    shares = list(session.scalars(select(WorkLogGroupShare)).all())
    by_worker = {s.worker_id: s.pairs for s in shares}
    assert by_worker[a.id] == 12
    assert by_worker[b.id] == 18
    assert all(s.is_adjusted for s in shares)
