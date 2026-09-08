"""B2a：外发工序单——建单/发料/收回/欠数/损耗/加工费应付/关联追溯。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    DefectResponsibility,
    Employee,
    ExecutionHeader,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    OwnProductLabor,
    Partner,
    Payable,
    PayableLine,
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


def _link_scrap(db, tenant_id, order, qty):
    event = DefectEvent(
        tenant_id=tenant_id,
        header_id=order.header_id,
        found_process_id=order.process_id,
        defect_type="other",
        qty=qty,
        scrap_source="subcontract",
        subcontract_order_id=order.id,
        disposition=DefectDisposition.scrap,
    )
    db.add(event)
    db.commit()
    return event


def test_create_auto_issues_and_receive_full_flow(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    db.add(OwnProductLabor(
        tenant_id=tid,
        own_product_id=product_id,
        process_id=proc_id,
        process_name="针车",
        requirement_note="鞋口车线均匀，不得跳针",
        unit_price=Decimal("2.50"),
    ))
    db.commit()

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        process_id=proc_id,
        header_id=header_id,
        own_product_id=product_id,
        total_qty=100,
        unit_price=Decimal("2.50"),
        material_unit_price=Decimal("18.75"),
        subcontract_unit_consumption=Decimal("1.25"),
        delivery_date=date(2026, 9, 15),
        notes="外发针车",
    )
    assert order.status == SubcontractOrderStatus.issued
    assert order.issued_qty == 100
    out = svc._out(db, order)
    assert out["linked_no"] == "EXEC-001"  # 关联可追溯
    assert out["partner_name"] == "外协A"
    assert out["process_name"] == "针车"
    assert out["material_unit_price"] == Decimal("18.75")
    assert out["subcontract_unit_consumption"] == Decimal("1.25")
    assert out["delivery_date"] == "2026-09-15"
    assert out["issue_count"] == 0
    detail = svc._out(db, order, include_flows=True)
    assert detail["process_requirements"] == [{
        "process_name": "针车",
        "requirement_note": "鞋口车线均匀，不得跳针",
    }]

    # 报废先登记并挂到外发单；验收只记完工，废品从报废记录同步。
    _link_scrap(db, tid, order, 3)
    out2 = svc.receive_subcontract(
        db, tid, order.id, qty=40, shared_loss_amount=Decimal("5")
    )
    assert out2["received_qty"] == 40
    assert out2["outstanding_qty"] == 60  # 新建即发出 100，收回 40
    assert out2["loss_qty"] == 3  # 报废（损耗）= 关联报废记录数量
    assert float(out2["processing_fee"]) == 40 * 2.50  # 加工费 = 完工数量 × 工价
    assert float(out2["loss_amount"]) == 3 * 2.50
    assert float(out2["shared_loss_amount"]) == 5
    assert float(out2["company_loss_amount"]) == 2.5
    assert float(out2["payable_amount"]) == 40 * 2.50 - 5
    order = db.get(SubcontractOrder, order.id)
    assert order.status == SubcontractOrderStatus.partial_received

    ap = db.scalar(select(Payable).where(Payable.subcontract_order_id == order.id))
    assert ap is not None
    assert ap.purchase_order_id is None  # 外发应付不挂 PO
    assert float(ap.amount) == 40 * 2.50 - 5
    assert ap.supplier_name == "外协A"
    snapshot = db.scalar(select(PayableLine).where(PayableLine.payable_id == ap.id))
    assert snapshot is not None
    assert snapshot.source_type == "subcontract_receive"
    assert snapshot.source_document_no == order.subcontract_no
    assert snapshot.process_name == "针车"
    assert snapshot.item_code == "WX-01"
    assert snapshot.unit_name == "双"
    assert Decimal(str(snapshot.qty)) == Decimal("40")
    assert Decimal(str(snapshot.unit_price)) == Decimal("2.5")
    assert Decimal(str(snapshot.amount)) == Decimal("95")

    defects = list(db.scalars(select(DefectEvent).where(DefectEvent.header_id == header_id)))
    assert len(defects) == 1
    assert defects[0].qty == 3
    assert defects[0].scrap_source == "subcontract"
    assert defects[0].subcontract_order_id == order.id

    # 再收回 60 → 平账
    svc.receive_subcontract(db, tid, order.id, qty=60)
    order = db.get(SubcontractOrder, order.id)
    assert order.received_qty == 100
    assert order.status == SubcontractOrderStatus.received
    out3 = svc._out(db, order)
    assert out3["outstanding_qty"] == 0
    assert out3["loss_qty"] == 3


def test_outstanding_filter_and_cancel(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)

    o1 = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=50, unit_price=Decimal("1")
    )
    o2 = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=30, unit_price=Decimal("1")
    )
    svc.receive_subcontract(db, tid, o1.id, qty=1)
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
    svc.receive_subcontract(db, tid, order.id, qty=40)

    proc = db.scalar(
        select(OrderProcess).where(
            OrderProcess.tenant_id == tid,
            OrderProcess.header_id == header.id,
            OrderProcess.process_id == proc_id,
        )
    )
    assert proc.completed_qty == 40  # 完工数量直接计入工序完成量
    assert proc.status == OrderProcessStatus.in_progress


def test_acceptance_loss_uses_work_price_and_validates_shared_loss(db):
    tid, partner_id, _proc_id, product_id, header_id = _seed(db)
    prep = ProcessDefinition(tenant_id=tid, name="备料", code="BL", sort_order=1)
    external = ProcessDefinition(tenant_id=tid, name="针车外发", code="ZCWF", sort_order=2)
    db.add_all([prep, external])
    db.flush()
    prep_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=prep.id,
        process_name=prep.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        completed_qty=20,
        status=OrderProcessStatus.completed,
    )
    external_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=external.id,
        process_name=external.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        completed_qty=0,
        status=OrderProcessStatus.pending,
    )
    db.add_all([prep_route, external_route])
    db.add(OwnProductLabor(
        tenant_id=tid,
        own_product_id=product_id,
        process_id=prep.id,
        process_name=prep.name,
        unit_price=Decimal("1.50"),
    ))
    db.commit()

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        header_id=header_id,
        order_process_ids=[external_route.id],
        total_qty=20,
        unit_price=Decimal("3"),
        material_unit_price=Decimal("10"),
    )
    _link_scrap(db, tid, order, 2)
    result = svc.receive_subcontract(
        db, tid, order.id, qty=10, shared_loss_amount=Decimal("4")
    )

    assert Decimal(str(result["loss_unit_amount"])) == Decimal("3.0000")
    assert Decimal(str(result["loss_amount"])) == Decimal("6.00")
    assert Decimal(str(result["shared_loss_amount"])) == Decimal("4.00")
    assert Decimal(str(result["company_loss_amount"])) == Decimal("2.00")
    assert Decimal(str(result["payable_amount"])) == Decimal("26.0000")


def test_create_autofills_material_unit_price_from_material_and_wages(db):
    tid, partner_id, _proc_id, product_id, header_id = _seed(db)
    prep = ProcessDefinition(tenant_id=tid, name="备料", code="BL", sort_order=1)
    external = ProcessDefinition(tenant_id=tid, name="针车外发", code="ZCWF", sort_order=2)
    db.add_all([prep, external])
    db.flush()
    prep_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=prep.id,
        process_name=prep.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        status=OrderProcessStatus.pending,
    )
    external_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=external.id,
        process_name=external.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        status=OrderProcessStatus.pending,
    )
    db.add_all([prep_route, external_route])
    db.add(OwnProductLabor(
        tenant_id=tid,
        own_product_id=product_id,
        process_id=prep.id,
        process_name=prep.name,
        unit_price=Decimal("1.50"),
    ))
    db.commit()

    quoted = svc.suggest_subcontract_material_unit_price(
        db,
        tenant_id=tid,
        header_id=header_id,
        order_process_ids=[external_route.id],
    )
    assert quoted["labor_amount"] == Decimal("1.5000")
    assert quoted["material_unit_price"] == Decimal("1.5000")

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        header_id=header_id,
        order_process_ids=[external_route.id],
        total_qty=20,
        unit_price=Decimal("3"),
        material_unit_price=Decimal("0"),
    )
    assert order.material_unit_price == Decimal("1.5000")

    custom = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        header_id=header_id,
        order_process_ids=[external_route.id],
        total_qty=10,
        unit_price=Decimal("3"),
        material_unit_price=Decimal("18.75"),
    )
    assert custom.material_unit_price == Decimal("18.75")

    second = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        total_qty=5,
        unit_price=Decimal("3"),
    )
    with pytest.raises(svc.SubcontractError) as exc:
        svc.receive_subcontract(
            db, tid, second.id, qty=5, shared_loss_amount=Decimal("3.01")
        )
    assert exc.value.code == "shared_loss_exceeds_loss"


def test_one_subcontract_order_can_cover_multiple_route_processes(db):
    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    second_def = ProcessDefinition(tenant_id=tid, name="成型", code="CX", sort_order=2)
    db.add(second_def)
    db.flush()
    first_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=proc_id,
        process_name="针车",
        process_type=ProcessType.personal,
        plan_qty=100,
        completed_qty=0,
        status=OrderProcessStatus.pending,
    )
    second_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=second_def.id,
        process_name="成型",
        process_type=ProcessType.group,
        plan_qty=100,
        completed_qty=0,
        status=OrderProcessStatus.pending,
    )
    db.add_all([first_route, second_route])
    db.commit()

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        header_id=header_id,
        order_process_ids=[second_route.id, first_route.id],
        total_qty=100,
        unit_price=Decimal("3"),
    )
    out = svc._out(db, order)
    assert out["order_process_ids"] == [first_route.id, second_route.id]
    assert out["process_name"] == "针车、成型"

    svc.receive_subcontract(db, tid, order.id, qty=40)
    db.refresh(first_route)
    db.refresh(second_route)
    assert first_route.completed_qty == 40
    assert second_route.completed_qty == 40


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
        svc.receive_subcontract(db, tid, order.id, qty=11)
    assert ei.value.code == "qty_exceeds_outstanding"
    ignored = svc.receive_subcontract(db, tid, order.id, qty=2, defect_qty=3)
    assert ignored["received_qty"] == 2
    assert ignored["loss_qty"] == 0

    with pytest.raises(svc.SubcontractError) as ei:
        svc.create_subcontract_order(
            db, tid, partner_id=99999, total_qty=10, unit_price=Decimal("1")
        )
    assert ei.value.code == "partner_not_found"


def test_issued_order_without_receipt_can_still_be_edited(db):
    tid, partner_id, _, _, _ = _seed(db)
    order = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    # 兼容旧单可能已有发料流水；只要还没有完工记录，仍允许修改。
    svc.issue_subcontract(db, tid, order.id, qty=1, note="旧发料流水")
    updated = svc.update_subcontract_order(
        db,
        tid,
        order.id,
        total_qty=12,
        unit_price=Decimal("1.5"),
    )
    assert updated.total_qty == 12
    assert updated.issued_qty == 12
    assert updated.unit_price == Decimal("1.5")

    svc.receive_subcontract(db, tid, order.id, qty=1)
    with pytest.raises(svc.SubcontractError) as exc:
        svc.update_subcontract_order(db, tid, order.id, unit_price=Decimal("2"))
    assert exc.value.code == "not_editable"


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


def test_delete_draft_subcontract_order_and_block_order_with_flows(db):
    tid, partner_id, _, _, _ = _seed(db)
    draft = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    draft_id = draft.id
    svc.delete_subcontract_order(db, tid, draft_id)
    assert db.get(SubcontractOrder, draft_id) is None

    received = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    svc.receive_subcontract(db, tid, received.id, qty=1)
    with pytest.raises(svc.SubcontractError) as exc:
        svc.delete_subcontract_order(db, tid, received.id)
    assert exc.value.code == "not_deletable"


def test_list_filters_by_factory_and_date_range(db):
    tid, partner_id, _, _, _ = _seed(db)
    other_partner = Partner(
        tenant_id=tid,
        name="外协厂B",
        is_supplier=True,
        is_subcontractor=True,
        is_active=True,
    )
    db.add(other_partner)
    db.flush()
    first = svc.create_subcontract_order(
        db, tid, partner_id=partner_id, total_qty=10, unit_price=Decimal("1")
    )
    second = svc.create_subcontract_order(
        db, tid, partner_id=other_partner.id, total_qty=20, unit_price=Decimal("2")
    )
    first.created_at = datetime(2026, 9, 1, 9, 30)
    second.created_at = datetime(2026, 9, 8, 15, 45)
    db.commit()

    rows, total = svc.list_subcontract_orders(
        db,
        tid,
        partner_id=other_partner.id,
        date_from=datetime(2026, 9, 8).date(),
        date_to=datetime(2026, 9, 8).date(),
    )
    assert total == 1
    assert rows[0]["id"] == second.id


def test_factory_responsibility_does_not_require_workers(db):
    from app.services.trace_service import apply_defect_loss_allocation, defect_out

    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        process_id=proc_id,
        header_id=header_id,
        own_product_id=product_id,
        total_qty=20,
        unit_price=Decimal("3"),
    )
    event = DefectEvent(
        tenant_id=tid,
        header_id=header_id,
        found_process_id=proc_id,
        defect_type="other",
        qty=2,
        scrap_source="subcontract",
        subcontract_order_id=order.id,
        responsible_party_type="subcontractor",
        disposition=DefectDisposition.scrap,
    )
    db.add(event)
    db.flush()
    apply_defect_loss_allocation(
        db,
        tenant_id=tid,
        event=event,
        loss_amount=Decimal("10.00"),
        company_share_percent=40,
        responsibilities=[],
        responsible_party_type="subcontractor",
    )
    db.commit()
    db.refresh(event)
    assert event.responsible_party_type == "subcontractor"
    assert event.responsible_worker_id is None
    assert event.company_share_percent == 40
    assert event.wage_deduction_from_event is False
    rows = list(
        db.scalars(
            select(DefectResponsibility).where(DefectResponsibility.defect_event_id == event.id)
        )
    )
    assert rows == []
    out = defect_out(db, event)
    assert out["responsible_party_type"] == "subcontractor"
    assert out["responsible_party_type_name"] == "外发厂"
    assert out["factory_loss_amount"] == 6.0
    assert out["responsibilities"][0]["partner_name"] == "外协A"
    assert out["responsibilities"][0]["share_percent"] == 60


def test_factory_scrap_uses_first_outsourced_process_and_material_unit_price(db):
    from app.services.trace_service import create_defect_event, defect_out

    tid, partner_id, proc_id, product_id, header_id = _seed(db)
    first = db.get(ProcessDefinition, proc_id)
    second = ProcessDefinition(tenant_id=tid, name="成型", code="CX", sort_order=2)
    db.add(second)
    db.flush()
    first_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=first.id,
        process_name=first.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        status=OrderProcessStatus.pending,
    )
    second_route = OrderProcess(
        tenant_id=tid,
        header_id=header_id,
        process_id=second.id,
        process_name=second.name,
        process_type=ProcessType.personal,
        plan_qty=20,
        status=OrderProcessStatus.pending,
    )
    db.add_all([first_route, second_route])
    db.commit()

    order = svc.create_subcontract_order(
        db,
        tid,
        partner_id=partner_id,
        header_id=header_id,
        order_process_ids=[second_route.id],
        total_qty=20,
        unit_price=Decimal("3"),
        material_unit_price=Decimal("18.75"),
    )
    event = create_defect_event(
        db,
        tenant_id=tid,
        defect_type="other",
        qty=2,
        header_id=header_id,
        found_process_id=first.id,
        scrap_source="subcontract",
        subcontract_order_id=order.id,
        responsible_party_type="subcontractor",
        auto_suggest_worker=False,
        company_share_percent=0,
        responsibilities=[],
    )
    assert event.found_process_id == second.id
    assert event.material_loss_amount == Decimal("18.75")
    assert event.labor_loss_amount == Decimal("0.00")
    assert event.loss_amount == Decimal("18.75")
    assert event.status == DefectEventStatus.closed
    assert event.scrap_confirmed_at is not None
    assert event.wage_deduction_from_event is False
    admin = Employee(tenant_id=tid, name="厂长", mobile="13900001111", is_active=True)
    db.add(admin)
    db.flush()
    from app.services.trace_service import can_supervisor_confirm_defect
    assert not can_supervisor_confirm_defect(
        db, employee=admin, event=event, viewer_is_tenant_wide=True
    )
    out = defect_out(db, event)
    assert out["factory_loss_amount"] == 18.75
    assert out["found_process_name"] == "成型"
