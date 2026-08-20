"""B2a：外发工序单——建单/发料/收回/欠数/损耗/加工费应付/关联追溯。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    ExecutionHeader,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    Partner,
    Payable,
    ProcessDefinition,
    ProcessType,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SubcontractOrder,
    SubcontractOrderStatus,
    Tenant,
)
from app.services import subcontract_out_service as svc
from scripts.seed_subcontract_demo import seed_b2a


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
    yield session
    session.close()


def _seed(db):
    tenant = Tenant(name="外发厂")
    db.add(tenant)
    db.flush()
    partner = Partner(
        tenant_id=tenant.id,
        name="外协厂A",
        short_name="外协A",
        is_supplier=True,
        is_subcontractor=True,
        is_active=True,
        payment_term_days=30,
    )
    proc = ProcessDefinition(tenant_id=tenant.id, name="针车", code="ZC", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="WX-01", is_active=True)
    db.add_all([partner, proc, product])
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="EXEC-001",
        own_product_id=product.id,
        total_qty=100,
        status=SpecExecutionStatus.in_progress,
    )
    db.add(header)
    db.commit()
    return tenant.id, partner.id, proc.id, product.id, header.id


def test_create_issue_receive_full_flow(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        process_id=proc_id,
        header_id=header_id,
        own_product_id=product_id,
        total_qty=100,
        unit_price=Decimal("2.50"),
        notes="外发针车",
    )
    assert order.status == SubcontractOrderStatus.draft
    out = svc._out(db, order)
    assert out["linked_no"] == "EXEC-001"  # 关联可追溯
    assert out["partner_name"] == "外协A"
    assert out["process_name"] == "针车"

    # 发料 60
    svc.issue_subcontract(db, tid, order.id, qty=60, note="第一批")
    order = db.get(SubcontractOrder, order.id)
    assert order.issued_qty == 60
    assert order.status == SubcontractOrderStatus.issued

    # 收回 40 → 部分收回 + 应付
    out2 = svc.receive_subcontract(db, tid, order.id, qty=40, defect_qty=3)
    assert out2["received_qty"] == 40
    assert out2["outstanding_qty"] == 20  # 欠数 = 发 − 收
    assert out2["loss_qty"] == 20  # 损耗 = 发 − 收
    assert float(out2["payable_amount"]) == 40 * 2.50  # 应付按收回结算
    order = db.get(SubcontractOrder, order.id)
    assert order.status == SubcontractOrderStatus.partial_received

    ap = db.scalar(select(Payable).where(Payable.subcontract_order_id == order.id))
    assert ap is not None
    assert ap.purchase_order_id is None  # 外发应付不挂 PO
    assert float(ap.amount) == 40 * 2.50  # 加工费 = 收回 × 单价
    assert ap.supplier_name == "外协A"

    # 再收回 20 → 平账
    svc.receive_subcontract(db, tid, order.id, qty=20)
    order = db.get(SubcontractOrder, order.id)
    assert order.received_qty == 60
    assert order.status == SubcontractOrderStatus.received
    out3 = svc._out(db, order)
    assert out3["outstanding_qty"] == 0
    assert out3["loss_qty"] == 0


def test_outstanding_filter_and_cancel(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)

    o1 = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=50, unit_price=Decimal("1")
    )
    o2 = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=30, unit_price=Decimal("1")
    )
    svc.issue_subcontract(db, tid, o1.id, qty=50)
    svc.issue_subcontract(db, tid, o2.id, qty=30)
    svc.receive_subcontract(db, tid, o2.id, qty=30)  # o2 平账

    rows, total = svc.list_subcontract_orders(db, tid, outstanding=True)
    assert total == 1
    assert rows[0]["id"] == o1.id

    # 有发料/收回不可取消
    with pytest.raises(svc.SubcontractError):
        svc.cancel_subcontract_order(db, tid, o1.id)

    o3 = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    svc.cancel_subcontract_order(db, tid, o3.id)
    assert db.get(SubcontractOrder, o3.id).status == SubcontractOrderStatus.cancelled


def test_receive_updates_execution_process_progress(db):
    """B2a：收回后回写关联执行单对应工序完成量。"""
    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    size = Size(tenant_id=tid, size_value="40", sort_order=0)
    db.add(size)
    db.flush()
    header = db.get(ExecutionHeader, header_id)
    db.add(
        OrderProcess(
            tenant_id=tid,
            header_id=header.id,
            process_id=proc_id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=100,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.add(
        SpecExecutionOrder(
            tenant_id=tid,
            execution_no="EXEC-PROG-1",
            header_id=header.id,
            own_product_id=product_id,
            size_id=size.id,
            total_qty=100,
            completed_qty=0,
            status=SpecExecutionStatus.in_progress,
        )
    )
    db.commit()

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        process_id=proc_id,
        header_id=header.id,
        own_product_id=product_id,
        total_qty=100,
        unit_price=Decimal("2"),
    )
    svc.issue_subcontract(db, tid, order.id, qty=100)
    svc.receive_subcontract(db, tid, order.id, qty=40)

    proc = db.scalar(
        select(OrderProcess).where(
            OrderProcess.tenant_id == tid,
            OrderProcess.header_id == header.id,
            OrderProcess.process_id == proc_id,
        )
    )
    assert proc.completed_qty == 40  # 收回 40 → 工序完成量 +40
    assert proc.status == OrderProcessStatus.in_progress


def test_issue_receive_validations(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    order = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    with pytest.raises(svc.SubcontractError) as ei:
        svc.issue_subcontract(db, tid, order.id, qty=0)
    assert ei.value.code == "invalid_qty"
    with pytest.raises(svc.SubcontractError) as ei:
        svc.receive_subcontract(db, tid, order.id, qty=-1)
    assert ei.value.code == "invalid_qty"

    with pytest.raises(svc.SubcontractError) as ei:
        svc.create_subcontract_order(
            db, tid, partner_id=99999, total_qty=10, unit_price=Decimal("1")
        )
    assert ei.value.code == "partner_not_found"


def test_seed_b2a_demo_idempotent(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    seed_b2a(db, tid)
    db.commit()

    factories = list(
        db.scalars(
            select(Partner).where(Partner.tenant_id == tid, Partner.is_subcontractor.is_(True))
        ).all()
    )
    names = {p.name for p in factories}
    assert {"鼎盛针车", "宏发成型", "顺达包装"} <= names

    orders = list(
        db.scalars(
            select(SubcontractOrder).where(SubcontractOrder.tenant_id == tid)
        ).all()
    )
    assert len(orders) == 1
    o = orders[0]
    assert o.subcontract_no == "SC-DEMO-01"
    assert o.issued_qty == 100
    assert o.received_qty == 60
    assert o.status == SubcontractOrderStatus.partial_received

    # 幂等：再跑一次不新增
    seed_b2a(db, tid)
    db.commit()
    orders2 = list(
        db.scalars(
            select(SubcontractOrder).where(SubcontractOrder.tenant_id == tid)
        ).all()
    )
    assert len(orders2) == 1
    assert len(db.scalars(select(Partner).where(Partner.tenant_id == tid)).all()) == 4  # 原 1 + 外协厂 3
