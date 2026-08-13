"""干掉生产单 K4-E：无壳筐预装 + 不良/返修认 header_id。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    DefectEvent,
    ExecutionHeader,
    OwnProduct,
    OwnProductLabor,
    OwnProductPart,
    PartDefinition,
    ProcessDefinition,
    ProcessType,
    ReworkTask,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    Tenant,
    TraceUnit,
    TraceUnitType,
    Worker,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.packing_service import create_basket_prepack
from app.services import rework_task_service, trace_service


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
    tenant = Tenant(name="K4E厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    session.add(front)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4E-A", is_active=True, trace_enabled=True
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
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                sort_order=0,
            ),
        ]
    )
    session.add(Worker(tenant_id=tenant.id, name="返修员", mobile="13900006666", is_active=True))
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
    return so, line, item


def _header_only_exe(db, *, qty: int = 20):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4E",
        qty=qty,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert exe.shop_order_id is None
    return tenant, header, exe


def test_basket_prepack_without_order(db):
    tenant, header, exe = _header_only_exe(db, qty=24)
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=24,
        mode="basket_bundles",
    )
    basket_id = cut["created"][0]["id"]
    basket = db.get(TraceUnit, basket_id)
    assert basket is not None
    assert basket.order_id is None
    assert basket.header_id == header.id
    assert _enum_type(basket) == TraceUnitType.basket.value

    plan = create_basket_prepack(
        db, tenant.id, basket_id, mode="single_size", pairs_per_carton=12
    )
    assert plan["basket_id"] == basket_id
    assert plan["execution_id"] == exe.id
    assert plan["header_id"] == header.id
    assert plan["order_id"] is None
    assert plan["carton_count"] == 2
    assert plan["total_qty"] == 24
    assert plan["note"] and "筐预装" in plan["note"]


def test_defect_event_header_only_unit(db):
    tenant, header, exe = _header_only_exe(db, qty=20)
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=20,
        mode="basket_bundles",
    )
    unit_id = cut["created"][0]["id"]
    unit = db.get(TraceUnit, unit_id)
    assert unit.order_id is None
    assert unit.header_id == header.id

    zc = db.scalar(select(ProcessDefinition).where(ProcessDefinition.code == "ZC"))
    worker = db.scalar(select(Worker).limit(1))
    event = trace_service.create_defect_event(
        db,
        tenant_id=tenant.id,
        defect_type="open_seam",
        qty=2,
        trace_unit_id=unit_id,
        responsible_process_id=zc.id,
        responsible_worker_id=worker.id,
        disposition="rework",
        auto_suggest_worker=False,
    )
    assert event.order_id is None
    assert event.header_id == header.id
    assert event.trace_unit_id == unit_id

    row = db.get(DefectEvent, event.id)
    assert row is not None
    assert row.order_id is None
    assert row.header_id == header.id


def test_rework_task_header_only(db):
    tenant, header, exe = _header_only_exe(db, qty=20)
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=20,
        mode="basket_bundles",
    )
    unit_id = cut["created"][0]["id"]
    zc = db.scalar(select(ProcessDefinition).where(ProcessDefinition.code == "ZC"))
    worker = db.scalar(select(Worker).limit(1))
    defect = trace_service.create_defect_event(
        db,
        tenant_id=tenant.id,
        defect_type="dirty",
        qty=3,
        trace_unit_id=unit_id,
        responsible_process_id=zc.id,
        disposition="rework",
        auto_suggest_worker=False,
    )
    assert defect.order_id is None
    assert defect.header_id == header.id

    task = rework_task_service.create_rework_task(
        db,
        tenant.id,
        defect.id,
        worker_id=worker.id,
        process_id=zc.id,
        qty=3,
    )
    assert task["order_id"] is None
    assert task["header_id"] == header.id
    assert task["status"] == "pending"

    row = db.get(ReworkTask, task["id"])
    assert row is not None
    assert row.order_id is None
    assert row.header_id == header.id

    listed = rework_task_service.list_rework_tasks(
        db, tenant.id, status="pending", header_id=header.id
    )
    assert any(t["id"] == task["id"] for t in listed)


def _enum_type(unit: TraceUnit) -> str:
    ut = unit.unit_type
    return ut.value if hasattr(ut, "value") else str(ut)
