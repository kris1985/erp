"""AU-I1 M4：用料双写 execution_id；可产齐套过滤；合单后齐套不裂。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
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
    SupplierProduct,
    Tenant,
)
from app.services import inventory_settings
from app.services.execution_service import create_execution, list_producible
from app.services.material_service import get_header_kit


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
    tenant = Tenant(name="齐套合单厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(
        tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True
    )
    session.add(partner)
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="KIT-XE", is_active=True, trace_enabled=True
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
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-XE",
        name="大底",
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
            qty=Decimal("100"),
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


def test_merge_stamps_execution_on_materials_and_kit_ok(db):
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
    prod = list_producible(db, tenant_id=tenant.id)
    assert len(prod) == 1
    assert prod[0]["kit_hint"] == "ready"
    assert list_producible(db, tenant_id=tenant.id, kit_ready_only=True)

    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == exe.header_id
            )
        ).all()
    )
    assert reqs
    assert all(r.header_id == exe.header_id for r in reqs)

    # G1：合单后齐套不裂（池 100 ≥ 需求 50）
    kit = get_header_kit(db, tenant.id, int(exe.header_id))
    assert kit["kit_ok"] is True
    assert kit["empty_bom"] is False


def test_producible_kit_ready_only_filters_short(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    stock = db.scalar(select(SharedMaterialStock).limit(1))
    stock.qty = Decimal("10")
    db.commit()

    _so_item(
        db,
        order_no="SO-S",
        qty=50,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    all_items = list_producible(db, tenant_id=tenant.id)
    assert all_items[0]["kit_hint"] == "short"
    assert list_producible(db, tenant_id=tenant.id, kit_ready_only=True) == []
