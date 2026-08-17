"""AU-I3 M4：停产释放可产/料/未报工筐；返修可用数勾平。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    DefectEventStatus,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SharedMaterialStock,
    Size,
    SpecExecutionStatus,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
)
from app.services import inventory_settings
from app.services.execution_service import (
    ExecutionError,
    confirm_halt,
    create_execution,
    list_producible,
    simulate_halt,
)
from app.services.fg_service import FgError, warehouse_basket
from app.services.material_service import get_header_kit
from app.services.trace_service import (
    carrier_available_qty,
    create_defect_event,
)


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
    tenant = Tenant(name="停产厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        sort_order=1,
    )
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1"),
        sort_order=0,
    )
    session.add_all([proc, zc])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="HALT-A", is_active=True, trace_enabled=True
    )
    session.add(product)
    session.flush()
    session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    from app.models import SupplierProduct

    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-HALT",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("5"),
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=mat.id,
            qty=Decimal("1"),
            unit_price=Decimal("5"),
            line_total=Decimal("5"),
            sort_order=0,
        )
    )
    session.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=mat.id,
            size_id=None,
            qty=Decimal("1000"),
        )
    )
    inventory_settings.save_inventory_patch(
        session, tenant.id, {"kit_include_unallocated_pool": True}
    )
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
    return item


def test_halt_voids_open_basket_releases_pool_and_material(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-H1",
        qty=100,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 80}],
    )
    # K4-B：用料快照直接挂执行单头，不再依赖桥接生产单。
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == exe.header_id
            )
        ).all()
    )
    assert reqs
    for r in reqs:
        r.arrived_qty = r.required_qty or Decimal("0")
    db.commit()

    db.add(
        TraceUnit(
            tenant_id=tenant.id,
            order_id=None,
            header_id=exe.header_id,
            execution_id=exe.id,
            code="BK-HALT-1",
            unit_type=TraceUnitType.basket,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            qty=40,
            status=TraceUnitStatus.open,
        )
    )
    exe.status = SpecExecutionStatus.in_progress
    db.commit()
    db.refresh(item)
    assert item.allocated_qty == 80

    sim = simulate_halt(db, tenant_id=tenant.id, execution_id=exe.id, void_open_units=True)
    assert sim["new_total_qty"] == 0
    assert len(sim["will_void"]) == 1
    assert sim["release_qty"] == 80

    out = confirm_halt(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        void_open_units=True,
        notes="客户停产",
    )
    db.refresh(item)
    db.refresh(exe)
    assert item.allocated_qty == 0
    assert exe.status == SpecExecutionStatus.cancelled
    unit = db.scalar(select(TraceUnit).where(TraceUnit.code == "BK-HALT-1"))
    assert unit.status == TraceUnitStatus.scrapped
    pool = list_producible(db, tenant_id=tenant.id)
    rem = {s["sales_order_line_item_id"]: s["remaining_qty"] for b in pool for s in b["sources"]}
    assert rem[item.id] == 100
    # 料占用应释放（arrived 回池后到 0 或 required 降为 0）。
    kit = get_header_kit(db, tenant.id, int(exe.header_id))
    assert kit is not None
    assert out["will_cancel_execution"] is True


def test_halt_keeps_warehoused_floor(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-H2",
        qty=50,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 50}],
    )
    db.add(
        TraceUnit(
            tenant_id=tenant.id,
            order_id=exe.shop_order_id,
            execution_id=exe.id,
            code="BK-WH-1",
            unit_type=TraceUnitType.basket,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            qty=20,
            status=TraceUnitStatus.warehoused,
        )
    )
    db.add(
        TraceUnit(
            tenant_id=tenant.id,
            order_id=exe.shop_order_id,
            execution_id=exe.id,
            code="BK-OPEN-1",
            unit_type=TraceUnitType.basket,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            qty=30,
            status=TraceUnitStatus.open,
        )
    )
    exe.status = SpecExecutionStatus.in_progress
    db.commit()

    sim = simulate_halt(db, tenant_id=tenant.id, execution_id=exe.id)
    assert sim["floor_qty"] == 20
    assert sim["new_total_qty"] == 20
    confirm_halt(db, tenant_id=tenant.id, execution_id=exe.id)
    db.refresh(exe)
    db.refresh(item)
    assert exe.total_qty == 20
    assert item.allocated_qty == 20
    assert exe.status != SpecExecutionStatus.cancelled


def test_halt_rejects_unstarted(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-H3",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    with pytest.raises(ExecutionError) as e:
        simulate_halt(db, tenant_id=tenant.id, execution_id=exe.id)
    assert e.value.code == "not_started"


def test_rework_freeze_blocks_warehouse_then_restores(db):
    from app.models import Employee

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    zc = db.scalar(select(ProcessDefinition).where(ProcessDefinition.code == "ZC").limit(1))
    worker = Employee(tenant_id=tenant.id, name="李四", mobile="13900000002", is_active=True)
    db.add(worker)
    db.flush()
    item = _so_item(
        db,
        order_no="SO-RW",
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
    unit = TraceUnit(
        tenant_id=tenant.id,
        order_id=exe.shop_order_id,
        execution_id=exe.id,
        code="BK-RW-1",
        unit_type=TraceUnitType.basket,
        own_product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        qty=20,
        status=TraceUnitStatus.done,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)

    defect = create_defect_event(
        db,
        tenant_id=tenant.id,
        defect_type="open_seam",
        qty=5,
        trace_unit_id=unit.id,
        disposition="rework",
        responsible_process_id=zc.id,
        responsible_worker_id=worker.id,
        found_by_worker_id=worker.id,
        auto_suggest_worker=False,
    )
    db.refresh(unit)
    assert carrier_available_qty(db, unit) == 15
    with pytest.raises(FgError) as e:
        warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=unit.id)
    assert e.value.code == "rework_frozen"

    defect.status = DefectEventStatus.closed
    db.commit()
    db.refresh(unit)
    assert carrier_available_qty(db, unit) == 20
    out = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=unit.id)
    assert out["qty"] == 20


def test_partial_scrap_reduces_warehouse_qty(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SC",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 30}],
    )
    unit = TraceUnit(
        tenant_id=tenant.id,
        order_id=exe.shop_order_id,
        execution_id=exe.id,
        code="BK-SC-1",
        unit_type=TraceUnitType.basket,
        own_product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        qty=30,
        status=TraceUnitStatus.done,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)

    create_defect_event(
        db,
        tenant_id=tenant.id,
        defect_type="dirty",
        qty=8,
        trace_unit_id=unit.id,
        disposition="scrap",
        auto_suggest_worker=False,
    )
    db.refresh(unit)
    assert int(unit.qty) == 22
    assert unit.status != TraceUnitStatus.scrapped
    assert carrier_available_qty(db, unit) == 22
    out = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=unit.id)
    assert out["qty"] == 22
