"""AU-I0 M3：载体闸门 / 收料（仅筐；齐套点/追溯开关已下线）。"""

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
    TraceUnit,
    TraceUnitType,
    WorkLog,
    Worker,
    WorkerRole,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.assignment_service import assign_basket
from app.services.order_service import create_order
from app.services.report_service import ReportError, submit_report
from app.services.shop_floor_gates import mark_basket_received
from app.services.shop_floor_settings import save_shop_floor_patch
from app.services.trace_service import preview_or_create_cut_cards


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
    tenant = Tenant(name="闸门厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="棕", code="BR"))
    session.add(Size(tenant_id=tenant.id, size_value="39", sort_order=0))
    session.commit()
    yield session
    session.close()


def _seed(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    procs = []
    for i, (name, code, ptype) in enumerate(
        [
            ("针车", "ZC", ProcessType.personal),
            ("合帮", "HB", ProcessType.personal),
            ("成型", "CX", ProcessType.group),
        ],
        start=1,
    ):
        p = ProcessDefinition(
            tenant_id=tenant.id,
            name=name,
            code=code,
            type=ptype,
            default_price=Decimal("1"),
            sort_order=i,
        )
        db.add(p)
        procs.append(p)
    db.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="GATE",
        is_active=True,
    )
    db.add(product)
    db.flush()
    db.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=procs[0].id,
                process_name=procs[0].name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=procs[1].id,
                process_name=procs[1].name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=procs[2].id,
                process_name=procs[2].name,
                unit_price=Decimal("1"),
                sort_order=2,
            ),
        ]
    )
    worker = Worker(tenant_id=tenant.id, name="针车工", mobile="13800000001", role=WorkerRole.worker)
    leader = Worker(tenant_id=tenant.id, name="组长", mobile="13800000002", role=WorkerRole.leader)
    w2 = Worker(tenant_id=tenant.id, name="成型甲", mobile="13800000003", role=WorkerRole.worker)
    w3 = Worker(tenant_id=tenant.id, name="成型乙", mobile="13800000004", role=WorkerRole.worker)
    db.add_all([worker, leader, w2, w3])
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
    cut = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        bundle_size=20,
    )
    basket_id = cut["created"][0]["id"]
    return tenant, order, worker, leader, w2, w3, basket_id


def test_basket_report_all_personal_processes(db):
    """全工序（个人/集体）都扫流转卡；无齐套点、无追溯开关之分。"""
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    # 针车（个人）：直接扫筐
    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=20,
        trace_unit_id=basket_id,
    )
    assert result["qualified_qty"] == 20
    # 合帮（个人）：同样扫筐
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="合帮",
        qualified_qty=20,
        trace_unit_id=basket_id,
    )
    # 成型（集体）：扫筐组报
    result2 = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=w2.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=20,
        trace_unit_id=basket_id,
        member_ids=[w2.id, w3.id],
    )
    assert result2.get("members")
    assert {m["worker_id"] for m in result2["members"]} == {w2.id, w3.id}


def test_receive_idempotent(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    basket = db.get(TraceUnit, basket_id)
    assert basket.unit_type == TraceUnitType.basket
    assert mark_basket_received(db, tenant_id=tenant.id, basket=basket, worker_id=leader.id) is True
    db.flush()
    assert mark_basket_received(db, tenant_id=tenant.id, basket=basket, worker_id=leader.id) is False
    assert basket.received_at is not None


def _stitch_process(order):
    return next(p for p in order.processes if p.process_name == "针车")


def test_unassigned_basket_rejected_when_dispatched_to_other(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    assign_basket(
        db,
        tenant.id,
        basket_id=basket_id,
        process_id=_stitch_process(order).id,
        items=[{"worker_id": worker.id, "quota_qty": 20}],
        worker_id_for_receive=leader.id,
    )
    with pytest.raises(ReportError) as ei:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=w2.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=5,
            trace_unit_id=basket_id,
        )
    assert ei.value.code == "not_assigned"
    ok = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=5,
        trace_unit_id=basket_id,
    )
    assert ok.get("qualified_qty") == 5


def test_leader_proxy_credits_beneficiary(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=leader.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=8,
        trace_unit_id=basket_id,
        proxy=True,
        beneficiary_worker_id=worker.id,
    )
    assert result.get("proxy") is True
    assert result.get("beneficiary_worker_id") == worker.id
    log = db.get(WorkLog, result["work_log_id"])
    assert log is not None
    assert log.worker_id == worker.id
    assert "代报" in (log.original_text or "")
    assert "工资记针车工" in (result.get("message") or "")


def test_worker_cannot_proxy(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    with pytest.raises(ReportError) as ei:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=5,
            trace_unit_id=basket_id,
            proxy=True,
            beneficiary_worker_id=w2.id,
        )
    assert ei.value.code == "proxy_not_leader"


def test_proxy_disabled_blocks(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    save_shop_floor_patch(db, tenant.id, {"stitch_leader_proxy_report": False})
    with pytest.raises(ReportError) as ei:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=leader.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=5,
            trace_unit_id=basket_id,
            proxy=True,
            beneficiary_worker_id=worker.id,
        )
    assert ei.value.code == "proxy_disabled"


def test_leader_proxy_batch_on_basket(db):
    tenant, order, worker, leader, w2, w3, basket_id = _seed(db)
    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=leader.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=8,
        trace_unit_id=basket_id,
        proxy=True,
        beneficiary_worker_ids=[worker.id, w2.id],
    )
    assert result.get("proxy") is True
    assert set(result.get("beneficiary_worker_ids") or []) == {worker.id, w2.id}
    ids = result.get("work_log_ids") or []
    logs = [db.get(WorkLog, i) for i in ids]
    assert len(logs) == 2
    assert {log.worker_id for log in logs} == {worker.id, w2.id}
    assert sorted(int(log.qualified_qty) for log in logs) == [4, 4]
    assert all(
        (log.report_type.value if hasattr(log.report_type, "value") else str(log.report_type))
        == "normal"
        for log in logs
    )
    assert logs[0].group_id and logs[0].group_id == logs[1].group_id
    assert "工资记针车工、成型甲" in (result.get("message") or "") or "工资记成型甲、针车工" in (
        result.get("message") or ""
    )
