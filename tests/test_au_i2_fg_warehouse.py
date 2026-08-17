"""AU-I2 M1：筐入库 → FG + 精确产量勾平。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    FgStock,
    OwnProduct,
    OwnProductLabor,
    OwnProductPart,
    PartDefinition,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionStatus,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import FgError, warehouse_basket


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
    tenant = Tenant(name="成品仓厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    session.add(front)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="FG-A", is_active=True, trace_enabled=True
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
    session.add(
        OwnProductPart(
            tenant_id=tenant.id,
            own_product_id=product.id,
            part_id=front.id,
            sort_order=0,
        )
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
        produced_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_warehouse_basket_fg_and_exact_produced(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-B",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=50,
        mode="basket_bundles",
    )
    # 合单分筐：SO-A 30 / SO-B 20 各自独立成筐
    assert len(cut["created"]) == 2
    created = {int(c["qty"]): c for c in cut["created"]}
    basket_a = created[30]["id"]
    basket_b = created[20]["id"]

    result_a = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    assert result_a["qty"] == 30
    assert result_a["status"] == "warehoused"
    assert result_a["fg_qty"] == 30
    by_so = {x["sales_order_no"]: x["qty"] for x in result_a["produced_splits"] if x["qty"]}
    assert by_so == {"SO-A": 30}

    result_b = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_b)
    assert result_b["qty"] == 20
    assert result_b["fg_qty"] == 50
    by_so_b = {x["sales_order_no"]: x["qty"] for x in result_b["produced_splits"] if x["qty"]}
    assert by_so_b == {"SO-B": 20}

    db.refresh(a)
    db.refresh(b)
    assert a.produced_qty == 30
    assert b.produced_qty == 20

    stock = db.scalar(select(FgStock).where(FgStock.tenant_id == tenant.id))
    assert stock is not None and int(stock.qty) == 50

    unit = db.get(TraceUnit, basket_a)
    assert unit.status == TraceUnitStatus.warehoused

    db.refresh(exe)
    assert exe.status == SpecExecutionStatus.completed
    assert int(exe.completed_qty) == 50

    with pytest.raises(FgError) as e:
        warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    assert e.value.code == "already_warehoused"
