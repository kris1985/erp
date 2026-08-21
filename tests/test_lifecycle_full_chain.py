"""经营生命周期全链路：建单→接单→采购→入库→排产→领料→出库→报工→工资→出货。

覆盖验收 G「采购→IQC→齐套→领料→执行」+ 计件工资 + FG 出货/应收。
领料/出库认执行单头，故排产在领料之前（与 lifecycle-status-flow 一致）。
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    FgStock,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    OwnProductPart,
    PartDefinition,
    Partner,
    Payable,
    ProcessDefinition,
    ProcessType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Receivable,
    SalesOrder,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
    Employee,
)
from app.schemas.api import SalesOrderCreate, SalesOrderLineIn, SalesOrderLineItemIn
from app.services import inventory_settings, iqc_service, purchase_service, stock_doc_service
from app.services.execution_schedule_service import confirm_draft, propose_draft
from app.services.execution_service import cut_cards_for_execution, list_producible
from app.services.fg_service import ship_warehoused_basket, warehouse_basket
from app.services.material_service import (
    allocate_from_pool_for_header,
    get_header_kit,
    list_shared_stocks,
)
from app.services.packing_service import create_basket_prepack
from app.services.purchase_service import generate_po_no, new_public_token
from app.services.report_service import ReportError, submit_report
from app.services.salary_service import month_salary
from app.services.sales_order_service import (
    confirm_sales_order,
    create_sales_order,
    serialize_sales_order,
    simulate_sales_order_lines_mrp,
)

QTY = 12
MAT_PRICE = Decimal("8.00")
STITCH_PRICE = Decimal("2.00")
FORM_PRICE = Decimal("1.50")


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
    tenant = Tenant(name="全链路厂")
    session.add(tenant)
    session.flush()
    customer = Partner(
        tenant_id=tenant.id, name="客户甲", is_customer=True, is_active=True
    )
    supplier = Partner(
        tenant_id=tenant.id, name="面料商", is_supplier=True, is_active=True
    )
    session.add_all([customer, supplier])
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    stitch = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=STITCH_PRICE,
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
    )
    form = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=FORM_PRICE,
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=2,
    )
    session.add_all([stitch, form])
    session.flush()
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    session.add(front)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="LC-01",
        quote_price=Decimal("88.00"),
        is_active=True,
        trace_enabled=True,
    )
    session.add(product)
    session.flush()
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-LC",
        name="面料",
        partner_id=supplier.id,
        unit_price=MAT_PRICE,
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=stitch.id,
                process_name=stitch.name,
                unit_price=STITCH_PRICE,
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=form.id,
                process_name=form.name,
                unit_price=FORM_PRICE,
                sort_order=1,
            ),
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                sort_order=0,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=mat.id,
                qty=Decimal("1"),
                unit_price=MAT_PRICE,
                line_total=MAT_PRICE,
                sort_order=0,
            ),
            Employee(tenant_id=tenant.id, name="张三", mobile="13900001001", is_active=True),
        ]
    )
    session.commit()
    inventory_settings.save_inventory_patch(
        session,
        tenant.id,
        {
            "iqc_before_pool": True,
            "auto_allocate_on_receive": True,
            "issue_required": True,
            "kit_include_unallocated_pool": False,
            "capabilities": {"stock_docs": True, "allocate_ui": True},
        },
    )
    yield session
    session.close()


def _pool_qty(db, tenant_id: int, sp_id: int) -> Decimal:
    row = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    return Decimal(str(row.qty)) if row else Decimal("0")


def _basket_id(db, created: list[dict]) -> int:
    for row in created:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == TraceUnitType.basket.value:
            return tu.id
    raise AssertionError(f"开裁未出筐: {created}")


def _enum(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _assert_lifecycle(
    db,
    *,
    so,
    line,
    item,
    header=None,
    exe=None,
    so_stored: str,
    so_display: str,
    line_stored: str,
    line_display: str,
    exe_status: str | None,
    allocated: int,
    produced: int,
    shipped: int,
    wip: int | None = None,
):
    """对照 lifecycle-status-flow：头/行展示态 + 色码四轨 + 执行单状态。"""
    db.refresh(so)
    db.refresh(line)
    db.refresh(item)
    if header is not None:
        db.refresh(header)
    if exe is not None:
        db.refresh(exe)
    ser = serialize_sales_order(db, so.tenant_id, so)
    ln = next(x for x in ser["lines"] if x["id"] == line.id)
    it = next(x for x in ln["items"] if x["id"] == item.id)
    assert ser["status"] == so_stored
    assert ser["display_status"] == so_display
    assert _enum(line.status) == line_stored
    assert ln["display_status"] == line_display
    assert int(it["allocated_qty"]) == allocated
    assert int(it["produced_qty"]) == produced
    assert int(it["shipped_qty"]) == shipped
    if wip is not None:
        assert int(ln["wip_qty"]) == wip
    if exe_status is None:
        assert exe is None and header is None
        return
    assert exe is not None and header is not None
    assert _enum(exe.status) == exe_status
    assert _enum(header.status) == exe_status


def test_full_lifecycle_sales_purchase_issue_report_salary_ship(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    customer = db.scalar(select(Partner).where(Partner.is_customer.is_(True)))
    supplier = db.scalar(select(Partner).where(Partner.is_supplier.is_(True)))
    mat = db.scalar(select(SupplierProduct).limit(1))
    worker = db.scalar(select(Employee).limit(1))
    tid = tenant.id

    # --- 1. 建单 ---
    so = create_sales_order(
        db,
        tid,
        SalesOrderCreate(
            order_no="SO-LC-1",
            customer_id=customer.id,
            ordered_at=date.today(),
            lines=[
                SalesOrderLineIn(
                    own_product_id=product.id,
                    color_id=color.id,
                    unit_price=Decimal("88.00"),
                    items=[SalesOrderLineItemIn(size_id=size.id, qty=QTY)],
                )
            ],
        ),
        created_by=None,
    )
    assert so.status == SalesOrderStatus.draft
    assert so.lines[0].total_qty == QTY
    line = so.lines[0]
    item = line.items[0]
    assert db.scalar(select(SpecExecutionOrder).limit(1)) is None
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        so_stored="draft",
        so_display="pending_confirm",
        line_stored="pending",
        line_display="pending_confirm",
        exe_status=None,
        allocated=0,
        produced=0,
        shipped=0,
        wip=0,
    )

    # --- 2. 接单：只入待排，不建执行单 ---
    so = confirm_sales_order(db, tid, so.id, created_by=None)
    assert so.status == SalesOrderStatus.confirmed
    db.refresh(line)
    assert line.execution_header_id is None
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        so_stored="confirmed",
        so_display="pending_schedule",
        line_stored="pending",
        line_display="pending_schedule",
        exe_status=None,
        allocated=0,
        produced=0,
        shipped=0,
        wip=0,
    )
    pool = list_producible(db, tenant_id=tid)
    assert any(
        any(s["sales_order_id"] == so.id for s in b["sources"]) and b["remaining_qty"] == QTY
        for b in pool
    )

    mrp = simulate_sales_order_lines_mrp(
        db, tid, [(so.id, line.id)], include_shared=True, shortages_only=True
    )
    assert mrp["shortage_lines"] >= 1
    short = next(x for x in mrp["lines"] if x["supplier_product_id"] == mat.id)
    assert Decimal(str(short["shortage_qty"])) == Decimal(QTY)

    # --- 3. 采购：接单后按需求缺口下单（尚未有执行用料行） ---
    po = PurchaseOrder(
        tenant_id=tid,
        po_no=generate_po_no(db, tid),
        public_token=new_public_token(),
        partner_id=supplier.id,
        status=PurchaseOrderStatus.draft,
        expected_date=date.today(),
    )
    db.add(po)
    db.flush()
    po_line = PurchaseOrderLine(
        tenant_id=tid,
        purchase_order_id=po.id,
        supplier_product_id=mat.id,
        qty=Decimal(QTY),
        unit_price=MAT_PRICE,
        received_qty=Decimal("0"),
        sales_order_id=so.id,
        sales_order_line_id=line.id,
    )
    db.add(po_line)
    db.commit()
    submitted = purchase_service.submit_po(db, tid, po.id)
    assert submitted["status"] == PurchaseOrderStatus.ordered.value

    # --- 4. 入库：到货先 IQC，合格后才入共享池 ---
    recv = purchase_service.receive_po(
        db, tid, po.id, [{"line_id": po_line.id, "qty": QTY}], user_id=1
    )
    assert recv.get("iqc_pending_count") == 1
    assert _pool_qty(db, tid, mat.id) == 0
    iqc_id = recv["iqc_pending_ids"][0]
    iqc_service.decide_iqc(db, tid, iqc_id, decision="pass", user_id=1)
    assert _pool_qty(db, tid, mat.id) == Decimal(QTY)
    stocks = list_shared_stocks(db, tid)
    assert any(int(s["qty"]) >= QTY and s["supplier_product_id"] == mat.id for s in stocks)
    db.refresh(po)
    assert po.status == PurchaseOrderStatus.received
    assert db.scalar(select(Payable).where(Payable.purchase_order_id == po.id)) is not None

    # --- 5. 排产：草案确认才建执行单 ---
    draft = propose_draft(
        db,
        tenant_id=tid,
        selections=[{"sales_order_line_item_id": item.id, "qty": QTY}],
    )
    db.refresh(item)
    assert int(item.allocated_qty or 0) == 0
    confirmed = confirm_draft(db, tenant_id=tid, draft_id=draft["id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["execution_count"] == 1
    exe = db.get(SpecExecutionOrder, confirmed["executions"][0]["id"])
    assert exe is not None
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    db.refresh(item)
    db.refresh(so)
    assert int(item.allocated_qty) == QTY
    assert exe.status == SpecExecutionStatus.confirmed
    assert header.status == SpecExecutionStatus.confirmed
    assert line.execution_header_id == header.id
    assert list_producible(db, tenant_id=tid) == []
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="pending_production",
        line_stored="scheduled",
        line_display="pending_production",
        exe_status="confirmed",
        allocated=QTY,
        produced=0,
        shipped=0,
        wip=0,
    )

    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert req is not None
    assert req.order_id is None
    kit_before = get_header_kit(db, tid, header.id)
    assert kit_before["kit_ok"] is False

    # --- 6. 锁料：从共享池分到执行单头 ---
    alloc = allocate_from_pool_for_header(
        db, tid, header.id, req.id, Decimal(QTY), user_id=1
    )
    assert Decimal(str(alloc["arrived_qty"])) == Decimal(QTY)
    db.refresh(req)
    assert req.arrived_qty == Decimal(QTY)
    kit_after = get_header_kit(db, tid, header.id)
    assert kit_after["kit_ok"] is True

    # --- 7. 领料：车间提报，库存未动 ---
    pending = stock_doc_service.submit_stock_doc(
        db,
        tid,
        doc_type="issue",
        header_id=header.id,
        lines=[{"requirement_id": req.id, "qty": Decimal(QTY)}],
        user_id=1,
    )
    assert pending["status"] == "pending"
    assert pending["header_id"] == header.id
    db.refresh(req)
    assert (req.issued_qty or 0) == 0

    with pytest.raises(ReportError) as blocked:
        submit_report(
            db,
            tenant_id=tid,
            worker_id=worker.id,
            header_id=header.id,
            process_name="针车",
            qualified_qty=QTY,
            color_name=color.name,
            size_value=size.size_value,
            create_trace_bundle=False,
        )
    assert blocked.value.code == "issue_required"

    # --- 8. 出库：仓管过账才发料 ---
    posted = stock_doc_service.confirm_stock_doc(db, tid, pending["id"])
    assert posted["status"] == "posted"
    db.refresh(req)
    assert req.issued_qty == Decimal(QTY)

    # --- 9. 开裁 + 报工 ---
    cut = cut_cards_for_execution(
        db,
        tenant_id=tid,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=QTY,
        mode="basket_bundles",
    )
    created = cut.get("created") or []
    assert created
    basket_id = _basket_id(db, created)
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="in_progress",
        line_stored="in_production",
        line_display="in_progress",
        exe_status="cut",
        allocated=QTY,
        produced=0,
        shipped=0,
        wip=0,
    )

    submit_report(
        db,
        tenant_id=tid,
        worker_id=worker.id,
        header_id=header.id,
        process_name="针车",
        qualified_qty=QTY,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="in_progress",
        line_stored="in_production",
        line_display="in_progress",
        exe_status="in_progress",
        allocated=QTY,
        produced=0,
        shipped=0,
    )
    submit_report(
        db,
        tenant_id=tid,
        worker_id=worker.id,
        header_id=header.id,
        process_name="成型",
        qualified_qty=QTY,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    db.refresh(exe)
    db.refresh(header)
    assert int(exe.completed_qty) == QTY
    assert exe.status == SpecExecutionStatus.completed
    procs = list(db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all())
    assert {p.process_name: int(p.completed_qty or 0) for p in procs}["成型"] == QTY
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="completed",
        line_stored="completed",
        line_display="completed",
        exe_status="completed",
        allocated=QTY,
        produced=0,
        shipped=0,
    )

    # --- 10. 工资 ---
    sal = month_salary(db, tid, worker.id)
    expected_wage = STITCH_PRICE * QTY + FORM_PRICE * QTY
    assert Decimal(str(sal["total_piece_wage"])) == expected_wage
    assert Decimal(str(sal["total_wage"])) == expected_wage
    assert len(sal["details"]) == 2

    # --- 11. 预装 + 成品入库 + 出货 ---
    pre = create_basket_prepack(db, tid, basket_id, pairs_per_carton=QTY)
    assert pre["carton_count"] == 1
    wh = warehouse_basket(db, tenant_id=tid, trace_unit_id=basket_id)
    assert wh["status"] == "warehoused"
    assert int(wh["qty"]) == QTY
    db.refresh(item)
    assert int(item.produced_qty or 0) == QTY
    fg = db.scalar(select(FgStock).where(FgStock.tenant_id == tid))
    assert fg is not None and int(fg.qty) == QTY
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="completed",
        line_stored="completed",
        line_display="completed",
        exe_status="completed",
        allocated=QTY,
        produced=QTY,
        shipped=0,
        wip=0,
    )

    ship = ship_warehoused_basket(db, tenant_id=tid, trace_unit_id=basket_id)
    assert ship["status"] == "shipped"
    assert {row["sales_order_no"]: row["total_qty"] for row in ship["shipments"]} == {
        "SO-LC-1": QTY
    }
    db.refresh(item)
    db.refresh(so)
    db.refresh(line)
    assert int(item.shipped_qty or 0) == QTY
    assert db.get(TraceUnit, basket_id).status == TraceUnitStatus.shipped
    assert int(fg.qty) == 0
    recv_row = db.scalar(select(Receivable).where(Receivable.sales_order_no == "SO-LC-1"))
    assert recv_row is not None
    assert so.status == SalesOrderStatus.completed
    assert line.status == SalesOrderLineStatus.completed
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="completed",
        so_display="completed",
        line_stored="completed",
        line_display="completed",
        exe_status="completed",
        allocated=QTY,
        produced=QTY,
        shipped=QTY,
        wip=0,
    )


def test_lifecycle_partial_schedule_stays_pending_production(db):
    """部分排产：allocated < qty，执行仍 planned，销售展示已排产而非生产中。"""
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    customer = db.scalar(select(Partner).where(Partner.is_customer.is_(True)))
    so = create_sales_order(
        db,
        tenant.id,
        SalesOrderCreate(
            order_no="SO-LC-PART",
            customer_id=customer.id,
            ordered_at=date.today(),
            lines=[
                SalesOrderLineIn(
                    own_product_id=product.id,
                    color_id=color.id,
                    unit_price=Decimal("88.00"),
                    items=[SalesOrderLineItemIn(size_id=size.id, qty=QTY)],
                )
            ],
        ),
        created_by=None,
    )
    confirm_sales_order(db, tenant.id, so.id, created_by=None)
    line = so.lines[0]
    item = line.items[0]
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 6}],
    )
    confirmed = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    exe = db.get(SpecExecutionOrder, confirmed["executions"][0]["id"])
    header = db.get(ExecutionHeader, exe.header_id)
    _assert_lifecycle(
        db,
        so=so,
        line=line,
        item=item,
        header=header,
        exe=exe,
        so_stored="confirmed",
        so_display="pending_production",
        line_stored="scheduled",
        line_display="pending_production",
        exe_status="confirmed",
        allocated=6,
        produced=0,
        shipped=0,
        wip=0,
    )
    db.refresh(item)
    assert int(item.qty) - int(item.allocated_qty) == 6
    assert list_producible(db, tenant_id=tenant.id)
