"""生产单已完成：计划数量都入成品仓；本厂报废还没补完则退回生产中。"""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    DefectDisposition,
    DefectEvent,
    ExecutionHeader,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    Tenant,
)
from app.services.execution_service import refresh_execution_header_progress


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _build():
    db = _session()
    tenant = Tenant(name="完工口径厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    product = OwnProduct(tenant_id=tenant.id, product_code="DONE-A", is_active=True)
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="CUT", sort_order=1)
    pack = ProcessSegment(tenant_id=tenant.id, name="成型", code="PACK", sort_order=2)
    db.add_all([color, size, product, cut, pack])
    db.flush()
    cut_def = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        type=ProcessType.personal,
        segment_id=cut.id,
    )
    pack_def = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="PACK",
        type=ProcessType.personal,
        segment_id=pack.id,
    )
    db.add_all([cut_def, pack_def])
    db.flush()
    order = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-DONE",
        customer_name="客户甲",
        ordered_at=datetime(2026, 10, 1).date(),
    )
    db.add(order)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-DONE",
        own_product_id=product.id,
        color_id=color.id,
        sales_order_id=order.id,
        total_qty=100,
        status=SpecExecutionStatus.in_progress,
    )
    db.add(header)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=order.id,
        own_product_id=product.id,
        color_id=color.id,
        execution_header_id=header.id,
        carton_qty=2,
        total_qty=100,
        fg_intake_carton_qty=2,
        sort_order=0,
    )
    db.add(line)
    db.add(
        SpecExecutionOrder(
            tenant_id=tenant.id,
            execution_no="XE-DONE-40",
            header_id=header.id,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            total_qty=100,
            completed_qty=40,
            status=SpecExecutionStatus.in_progress,
        )
    )
    cut_proc = OrderProcess(
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=cut_def.id,
        process_name="裁断",
        process_type=ProcessType.personal,
        plan_qty=100,
        completed_qty=40,
        status=OrderProcessStatus.in_progress,
        segment_id=cut.id,
    )
    pack_proc = OrderProcess(
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=pack_def.id,
        process_name="成型",
        process_type=ProcessType.personal,
        plan_qty=100,
        completed_qty=40,
        status=OrderProcessStatus.in_progress,
        segment_id=pack.id,
    )
    db.add_all([cut_proc, pack_proc])
    db.commit()
    return db, tenant, header, cut_proc, pack_proc, pack_def


def _refresh(db, tenant, header):
    refresh_execution_header_progress(db, tenant_id=tenant.id, header_id=header.id)
    db.flush()
    return header.status


def test_finishes_when_everything_is_in_the_finished_warehouse():
    db, tenant, header, cut_proc, pack_proc, pack_def = _build()
    # 最后工序还没做完时，即使箱数已经填满，也只能入已完工的部分，不能算完成。
    assert _refresh(db, tenant, header) == SpecExecutionStatus.in_progress

    cut_proc.completed_qty = 100
    pack_proc.completed_qty = 100
    db.commit()
    assert _refresh(db, tenant, header) == SpecExecutionStatus.completed

    scrap = DefectEvent(
        tenant_id=tenant.id,
        header_id=header.id,
        found_process_id=pack_def.id,
        defect_type="other",
        qty=4,
        disposition=DefectDisposition.scrap,
        replacement_source="internal",
    )
    db.add(scrap)
    db.commit()
    assert _refresh(db, tenant, header) == SpecExecutionStatus.in_progress

    scrap.scrap_confirmed_at = datetime(2026, 10, 2, 8, 0, 0)
    db.commit()
    assert _refresh(db, tenant, header) == SpecExecutionStatus.in_progress

    cut_proc.completed_qty = 102
    db.commit()
    assert _refresh(db, tenant, header) == SpecExecutionStatus.completed
    db.close()


def test_subcontract_scrap_does_not_reopen_production():
    db, tenant, header, cut_proc, pack_proc, _pack_def = _build()
    cut_proc.completed_qty = 100
    pack_proc.completed_qty = 100
    db.add(
        DefectEvent(
            tenant_id=tenant.id,
            header_id=header.id,
            defect_type="other",
            qty=4,
            disposition=DefectDisposition.scrap,
            replacement_source="subcontract",
        )
    )
    db.commit()
    assert _refresh(db, tenant, header) == SpecExecutionStatus.completed
    db.close()


def test_recut_header_still_closes_when_its_processes_are_done():
    db, tenant, header, _cut_proc, _pack_proc, _pack_def = _build()
    child = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-DONE-补1",
        own_product_id=header.own_product_id,
        color_id=header.color_id,
        total_qty=4,
        status=SpecExecutionStatus.in_progress,
        parent_header_id=header.id,
    )
    db.add(child)
    db.flush()
    size_id = db.query(Size).filter(Size.tenant_id == tenant.id).one().id
    db.add(
        SpecExecutionOrder(
            tenant_id=tenant.id,
            execution_no="XE-DONE-补1-40",
            header_id=child.id,
            own_product_id=header.own_product_id,
            color_id=header.color_id,
            size_id=size_id,
            total_qty=4,
            completed_qty=4,
            status=SpecExecutionStatus.in_progress,
        )
    )
    db.commit()
    assert _refresh(db, tenant, child) == SpecExecutionStatus.completed
    db.close()
