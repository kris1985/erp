"""干掉生产单 K4-B：停写桥接壳；开裁/报工认 header。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessAssignedTeam,
    OwnProduct,
    OwnProductLabor,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionStatus,
    SupplierProduct,
    Team,
    TeamMember,
    Tenant,
    TraceUnit,
    WorkLog,
    Employee,
)
from app.services.execution_service import (
    ExecutionError,
    assign_header_process_segments,
    assign_header_process_workers,
    create_execution,
    create_execution_from_sales_line,
    cut_cards_for_header,
    start_cutting,
)
from app.services.material_service import MaterialError
from app.services.report_service import ReportError, submit_report
from app.services.sales_order_service import confirm_sales_order_line
from app.services import inventory_settings, stock_doc_service


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
    tenant = Tenant(name="K4B厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    stitch_segment = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=1)
    forming_segment = ProcessSegment(tenant_id=tenant.id, name="成型", code="forming", sort_order=2)
    session.add_all([stitch_segment, forming_segment])
    session.flush()
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
        segment_id=stitch_segment.id,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
        segment_id=forming_segment.id,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4B-A", is_active=True, trace_enabled=True
    )
    session.add(product)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=early.id,
                process_name=early.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=late.id,
                process_name=late.name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
        ]
    )
    session.add(Employee(tenant_id=tenant.id, name="报工员", mobile="13900003333"))
    session.commit()
    yield session
    session.close()


def _so_item(db, *, order_no: str, qty: int, product_id: int, color_id: int, size_id: int, tenant_id: int):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=qty,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant_id,
        sales_order_line_id=line.id,
        color_id=color_id,
        size_id=size_id,
        qty=qty,
        allocated_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    db.refresh(line)
    db.refresh(so)
    return so, line, item


def test_confirm_creates_no_order_row(db):
    tenant_id = db.scalar(select(Tenant.id))
    product_id = db.scalar(select(OwnProduct.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))
    so, line, _item = _so_item(
        db,
        order_no="SO-K4B",
        qty=12,
        product_id=product_id,
        color_id=color_id,
        size_id=size_id,
        tenant_id=tenant_id,
    )
    before = db.scalar(select(func.count()).select_from(Order)) or 0
    confirm_sales_order_line(db, tenant_id, so.id, line.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    create_execution_from_sales_line(
        db, tenant_id=tenant_id, sales_order=so, line=line, created_by=None, commit=True
    )
    db.refresh(line)
    assert line.production_order_id is None
    assert line.execution_header_id
    header = db.get(ExecutionHeader, line.execution_header_id)
    assert header is not None
    assert header.shop_order_id is None
    after = db.scalar(select(func.count()).select_from(Order)) or 0
    assert after == before
    procs = list(
        db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    )
    assert procs
    assert all(p.order_id is None for p in procs)


def test_cut_cards_for_header_without_shop(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-CUT",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert exe.shop_order_id is None

    cut = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        dry_run=False,
        bundle_size=20,
        only_missing=True,
        mode="bundles",
    )
    assert cut["created"]
    units = list(
        db.scalars(select(TraceUnit).where(TraceUnit.header_id == header.id)).all()
    )
    assert units
    assert all(u.order_id is None for u in units)
    assert all(u.header_id == header.id for u in units)


def test_start_cutting_changes_status_without_creating_baskets(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-START-CUT",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)

    result = start_cutting(db, tenant.id, header.id)

    db.refresh(header)
    db.refresh(exe)
    assert result["status"] == "cut"
    assert header.status == SpecExecutionStatus.cut
    assert exe.status == SpecExecutionStatus.cut
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 0


def test_first_posted_issue_starts_cutting_automatically(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-ISSUE-START",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    stitch_segment = db.scalar(
        select(ProcessSegment).where(ProcessSegment.code == "stitch")
    )
    forming_segment = db.scalar(
        select(ProcessSegment).where(ProcessSegment.code == "forming")
    )
    supplier = Partner(tenant_id=tenant.id, name="领料测试供应商", is_supplier=True, is_active=True)
    db.add(supplier)
    db.flush()
    material = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-ISSUE-START",
        name="测试面料",
        partner_id=supplier.id,
        is_active=True,
    )
    db.add(material)
    db.flush()
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        execution_id=exe.id,
        supplier_product_id=material.id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("20"),
        arrived_qty=Decimal("20"),
        issued_qty=Decimal("0"),
        consume_segment_id=stitch_segment.id,
        consume_segment_name=stitch_segment.name,
    )
    later_requirement = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        execution_id=exe.id,
        supplier_product_id=material.id,
        qty_per_pair=Decimal("0.5"),
        required_qty=Decimal("10"),
        arrived_qty=Decimal("10"),
        issued_qty=Decimal("0"),
        consume_segment_id=stitch_segment.id,
        consume_segment_name=stitch_segment.name,
    )
    other_segment_requirement = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        execution_id=exe.id,
        supplier_product_id=material.id,
        qty_per_pair=Decimal("0.2"),
        required_qty=Decimal("4"),
        arrived_qty=Decimal("4"),
        issued_qty=Decimal("0"),
        consume_segment_id=forming_segment.id,
        consume_segment_name=forming_segment.name,
    )
    db.add_all([requirement, later_requirement, other_segment_requirement])
    db.commit()
    inventory_settings.save_inventory_patch(db, tenant.id, {"issue_required": True})

    stitch_candidates = stock_doc_service.list_issue_candidates(
        db,
        tenant.id,
        header_id=header.id,
        consume_segment_id=stitch_segment.id,
        pairs=10,
    )
    assert {row["id"] for row in stitch_candidates["lines"]} == {
        requirement.id,
        later_requirement.id,
    }
    forming_candidates = stock_doc_service.list_issue_candidates(
        db,
        tenant.id,
        header_id=header.id,
        consume_segment_id=forming_segment.id,
        pairs=10,
    )
    assert [row["id"] for row in forming_candidates["lines"]] == [
        other_segment_requirement.id
    ]

    pending = stock_doc_service.submit_stock_doc(
        db,
        tenant.id,
        doc_type="issue",
        header_id=header.id,
        lines=[{"requirement_id": requirement.id, "qty": Decimal("5"), "pairs": 8}],
    )
    db.refresh(header)
    assert header.status == SpecExecutionStatus.confirmed

    posted = stock_doc_service.confirm_stock_doc(db, tenant.id, pending["id"])

    db.refresh(header)
    db.refresh(exe)
    assert posted["production_started"] is True
    assert posted["lines"][0]["pairs"] == 8
    assert header.status == SpecExecutionStatus.cut
    assert exe.status == SpecExecutionStatus.cut
    db.refresh(later_requirement)
    assert later_requirement.issued_qty == Decimal("0")
    stock_doc_service.assert_posted_issue_for_header(
        db,
        tenant.id,
        header.id,
        consume_segment_id=stitch_segment.id,
    )
    with pytest.raises(MaterialError):
        stock_doc_service.assert_posted_issue_for_header(
            db,
            tenant.id,
            header.id,
            consume_segment_id=forming_segment.id,
        )


def test_cut_cards_can_be_generated_incrementally_by_reported_target(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Employee).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-PARTIAL-CUT",
        qty=12,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 12}],
    )
    report1 = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=exe.header_id,
        process_name="针车",
        qualified_qty=6,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    first = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=exe.header_id,
        dry_run=False,
        bundle_size=4,
        target_qty_by_size={size.id: 6},
        force_new_batch=True,
        report_ids=report1["work_log_ids"],
    )
    report2 = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=exe.header_id,
        process_name="针车",
        qualified_qty=6,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    second = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=exe.header_id,
        dry_run=False,
        bundle_size=4,
        target_qty_by_size={size.id: 12},
        force_new_batch=True,
        report_ids=report2["work_log_ids"],
    )
    units = list(db.scalars(select(TraceUnit).where(TraceUnit.header_id == exe.header_id)).all())
    assert sum(u.qty for u in units) == 12
    assert sum(x["qty"] for x in first["created"]) == 6
    assert sum(x["qty"] for x in second["created"]) == 6
    assert first["batch_ids"][0] != second["batch_ids"][0]
    assert first["batches"][0]["batch_no"] != second["batches"][0]["batch_no"]
    assert db.get(WorkLog, report1["work_log_id"]).batch_id == first["batch_ids"][0]
    assert db.get(WorkLog, report2["work_log_id"]).batch_id == second["batch_ids"][0]


def test_report_by_header_id_without_shop(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Employee).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-RPT",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header.shop_order_id is None

    cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        dry_run=False,
        bundle_size=20,
        only_missing=True,
        mode="bundles",
    )

    procs = list(
        db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    )
    assert procs
    for p in procs:
        db.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=None,
                header_id=header.id,
                order_process_id=p.id,
                worker_id=worker.id,
            )
        )
    db.commit()

    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=header.id,
        process_name="针车",
        qualified_qty=5,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    assert result["header_id"] == header.id
    logs = list(db.scalars(select(WorkLog).where(WorkLog.header_id == header.id)).all())
    assert len(logs) == 1
    assert logs[0].order_id is None
    assert logs[0].own_product_id == product.id


def test_basket_ends_after_stitch_and_forming_reports_by_flow_card(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Employee).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-CARRIER",
        qty=12,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 12}],
    )
    cut = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=exe.header_id,
        dry_run=False,
        bundle_size=12,
    )
    basket = db.get(TraceUnit, cut["created"][0]["id"])
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=exe.header_id,
        process_name="针车",
        qualified_qty=12,
        trace_unit_id=basket.id,
        create_trace_bundle=False,
    )
    db.refresh(basket)
    assert basket.status.value == "done"
    forming = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=exe.header_id,
        process_name="成型",
        qualified_qty=12,
        trace_unit_id=None,
        create_trace_bundle=False,
    )
    assert forming["qualified_qty"] == 12


def test_dispatch_by_header_without_legacy_shop_order(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Employee).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-DISPATCH",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    process = db.scalar(
        select(OrderProcess).where(OrderProcess.header_id == header.id).limit(1)
    )
    assert header.shop_order_id is None
    assert process is not None

    result = assign_header_process_workers(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=process.id,
        worker_ids=[worker.id],
    )

    assignment = db.scalar(
        select(OrderProcessAssignment).where(
            OrderProcessAssignment.order_process_id == process.id
        )
    )
    assert assignment is not None
    assert assignment.order_id is None
    assert assignment.header_id == header.id
    assert result["items"][0]["assignments"][0]["worker_id"] == worker.id

    outsider = Employee(tenant_id=tenant.id, name="外组工人", mobile="13900004444")
    team = Team(tenant_id=tenant.id, name="针车一组", is_active=True)
    db.add_all([outsider, team])
    db.flush()
    db.add(TeamMember(tenant_id=tenant.id, team_id=team.id, worker_id=worker.id))
    db.commit()

    team_result = assign_header_process_workers(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=process.id,
        worker_ids=[],
        team_id=team.id,
    )
    assert team_result["items"][0]["assigned_group_id"] == team.id
    assert team_result["items"][0]["assigned_group_name"] == "针车一组"
    assert db.scalar(
        select(OrderProcessAssignment).where(
            OrderProcessAssignment.order_process_id == process.id
        )
    ) is None

    with pytest.raises(ReportError, match="不在该班组中"):
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=outsider.id,
            header_id=header.id,
            process_name=process.process_name,
            qualified_qty=1,
            color_name=color.name,
            size_value=size.size_value,
            create_trace_bundle=False,
        )


def test_dispatch_multiple_teams_by_process_segment(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    forming_segment = db.scalar(select(ProcessSegment).where(ProcessSegment.code == "forming"))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4B-SEGMENT-DISPATCH",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    workers = [
        Employee(tenant_id=tenant.id, name="成型甲", mobile="13900005551"),
        Employee(tenant_id=tenant.id, name="成型乙", mobile="13900005552"),
    ]
    teams = [
        Team(tenant_id=tenant.id, name="成型一组", segment_id=forming_segment.id, is_active=True),
        Team(tenant_id=tenant.id, name="成型二组", segment_id=forming_segment.id, is_active=True),
    ]
    db.add_all([*workers, *teams])
    db.flush()
    db.add_all(
        [
            TeamMember(tenant_id=tenant.id, team_id=teams[0].id, worker_id=workers[0].id),
            TeamMember(tenant_id=tenant.id, team_id=teams[1].id, worker_id=workers[1].id),
        ]
    )
    db.commit()

    result = assign_header_process_segments(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        assignments=[
            {"segment_id": forming_segment.id, "team_ids": [teams[0].id, teams[1].id]}
        ],
    )

    forming = next(row for row in result["items"] if row["segment_id"] == forming_segment.id)
    assert forming["assigned_group_ids"] == [teams[0].id, teams[1].id]
    assert forming["assigned_group_names"] == ["成型一组", "成型二组"]
    assert forming["assigned_group_id"] is None
    saved = list(
        db.scalars(
            select(OrderProcessAssignedTeam).where(
                OrderProcessAssignedTeam.order_process_id == forming["order_process_id"]
            )
        ).all()
    )
    assert {row.team_id for row in saved} == {teams[0].id, teams[1].id}

    stitch_segment = db.scalar(select(ProcessSegment).where(ProcessSegment.code == "stitch"))
    with pytest.raises(ExecutionError, match="不属于当前工序段"):
        assign_header_process_segments(
            db,
            tenant_id=tenant.id,
            header_id=header.id,
            assignments=[{"segment_id": stitch_segment.id, "team_ids": [teams[0].id]}],
        )

    cleared = assign_header_process_segments(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        assignments=[{"segment_id": forming_segment.id, "team_ids": []}],
    )
    forming = next(row for row in cleared["items"] if row["segment_id"] == forming_segment.id)
    assert forming["assigned_group_ids"] == []
