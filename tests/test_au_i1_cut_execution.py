"""AU-I1 M2：执行单开裁挂 execution_id；筐打印带来源。"""

from datetime import date
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
    TraceUnitType,
)
from app.services.execution_service import (
    allocation_sources_for_execution,
    create_execution,
    cut_cards_for_execution,
)
from app.services.trace_service import preview_or_create_cut_cards, unit_detail_dict


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
    tenant = Tenant(name="开裁合单厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    tongue = PartDefinition(tenant_id=tenant.id, code="SX", name="鞋舌", source="裁断")
    session.add_all([front, tongue])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="XE-CUT", is_active=True, trace_enabled=True
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
    session.add_all(
        [
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                sort_order=0,
            ),
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=tongue.id,
                sort_order=1,
            ),
        ]
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


def test_execution_cut_stamps_execution_id_and_sources(db):
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

    data = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=50,
        only_missing=True,
        mode="basket_bundles",
    )
    assert data["mode"] == "basket_bundles"
    assert data["execution_id"] == exe.id
    labels = [x["label"] for x in data["allocation_sources"]]
    assert "SO-A 30" in labels
    assert "SO-B 20" in labels
    assert len(data["created"]) == 1
    assert data["created"][0]["unit_type"] == "basket"
    assert data["created"][0]["execution_id"] == exe.id
    assert len(data["created"][0]["children"]) == 2

    baskets = list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.order_id == exe.shop_order_id,
                TraceUnit.unit_type == TraceUnitType.basket,
            )
        ).all()
    )
    assert len(baskets) == 1
    assert baskets[0].execution_id == exe.id
    children = list(
        db.scalars(select(TraceUnit).where(TraceUnit.parent_id == baskets[0].id)).all()
    )
    assert len(children) == 2
    assert all(c.execution_id == exe.id for c in children)

    db.refresh(exe)
    assert exe.status == SpecExecutionStatus.cut

    detail = unit_detail_dict(db, baskets[0])
    assert detail["execution_id"] == exe.id
    assert detail["execution_no"] == exe.execution_no
    assert [x["label"] for x in detail["allocation_sources"]] == ["SO-A 30", "SO-B 20"]


def test_shop_order_cut_auto_links_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-C",
        qty=40,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": a.id, "qty": 40}],
    )
    data = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=int(exe.shop_order_id),
        dry_run=False,
        bundle_size=40,
        mode="basket_bundles",
    )
    assert data["execution_id"] == exe.id
    assert allocation_sources_for_execution(db, exe.id)[0]["label"] == "SO-C 40"
    unit = db.get(TraceUnit, data["created"][0]["id"])
    assert unit is not None
    assert unit.execution_id == exe.id
