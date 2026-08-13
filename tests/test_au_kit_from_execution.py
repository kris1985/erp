"""去桥接：齐套/锁料认执行单头。"""

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
from app.services.execution_service import create_execution, create_execution_from_sales_line
from app.services.material_service import (
    allocate_from_pool_for_header,
    get_header_kit,
    header_kit_summaries,
    list_allocate_candidates,
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
    tenant = Tenant(name="料桥接厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    session.add(Size(tenant_id=tenant.id, size_value="41", sort_order=1))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
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
        tenant_id=tenant.id, product_code="KIT-HDR", is_active=True, trace_enabled=True
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
        product_code="MAT-HDR",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("1"),
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
            unit_price=Decimal("1"),
            line_total=Decimal("1"),
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
    session.commit()
    inventory_settings.save_inventory_patch(
        session,
        tenant.id,
        {
            "shared_pool": True,
            "allocate_ui": True,
            "stock_docs": True,
            "kit_include_unallocated_pool": True,
        },
    )
    yield session
    session.close()


def _so_line(db, *, order_no: str, qtys: list[tuple[int, int]], product_id, color_id, tenant_id):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
        ordered_at=date.today(),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    total = sum(q for _, q in qtys)
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=total,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    items = []
    for size_id, qty in qtys:
        it = SalesOrderLineItem(
            tenant_id=tenant_id,
            sales_order_line_id=line.id,
            color_id=color_id,
            size_id=size_id,
            qty=qty,
            allocated_qty=0,
            produced_qty=0,
        )
        db.add(it)
        items.append(it)
    db.flush()
    return so, line, items


def test_confirm_production_stamps_header_on_materials(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    sizes = list(db.scalars(select(Size).order_by(Size.sort_order)).all())
    so, line, _items = _so_line(
        db,
        order_no="SO-HDR-KIT",
        qtys=[(sizes[0].id, 10), (sizes[1].id, 14)],
        product_id=product.id,
        color_id=color.id,
        tenant_id=tenant.id,
    )
    header = create_execution_from_sales_line(
        db, tenant_id=tenant.id, sales_order=so, line=line, created_by=1, commit=True
    )
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == header.id
            )
        ).all()
    )
    assert reqs
    assert all(r.header_id == header.id for r in reqs)
    assert all(r.order_id is None for r in reqs)
    # 多码不钉单一 execution_id
    assert all(r.execution_id is None for r in reqs)

    kit = get_header_kit(db, tenant.id, header.id)
    assert kit["header_id"] == header.id
    assert kit["header_no"] == header.header_no
    assert kit["shop_order_id"] is None
    assert kit["kit_ok"] is True
    batch = header_kit_summaries(db, tenant.id, [header.id])
    assert header.id in batch
    assert batch[header.id]["kit_ok"] is True
    assert batch[header.id]["first_kit_ok"] == kit["first_kit_ok"]
    assert batch[header.id]["empty_bom"] == kit["empty_bom"]
    assert batch[header.id]["shortage_lines"] == kit["shortage_lines"]


def test_header_kit_summaries_two_headers_match_full_kit(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    sizes = list(db.scalars(select(Size).order_by(Size.sort_order)).all())
    so1, line1, _ = _so_line(
        db,
        order_no="SO-BATCH-1",
        qtys=[(sizes[0].id, 10)],
        product_id=product.id,
        color_id=color.id,
        tenant_id=tenant.id,
    )
    so2, line2, _ = _so_line(
        db,
        order_no="SO-BATCH-2",
        qtys=[(sizes[0].id, 8)],
        product_id=product.id,
        color_id=color.id,
        tenant_id=tenant.id,
    )
    h1 = create_execution_from_sales_line(
        db, tenant_id=tenant.id, sales_order=so1, line=line1, created_by=1, commit=True
    )
    h2 = create_execution_from_sales_line(
        db, tenant_id=tenant.id, sales_order=so2, line=line2, created_by=1, commit=True
    )
    full = {h.id: get_header_kit(db, tenant.id, h.id) for h in (h1, h2)}
    batch = header_kit_summaries(db, tenant.id, [h1.id, h2.id])
    assert set(batch) == {h1.id, h2.id}
    for hid, kit in full.items():
        assert batch[hid]["kit_ok"] == kit["kit_ok"]
        assert batch[hid]["first_kit_ok"] == kit["first_kit_ok"]
        assert batch[hid]["empty_bom"] == kit["empty_bom"]
        assert batch[hid]["shortage_lines"] == kit["shortage_lines"]


def test_allocate_by_header_and_candidates_show_header_no(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-ALLOC",
        customer_name="客户",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=20,
        status=SalesOrderLineStatus.in_production,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        color_id=color.id,
        size_id=size.id,
        qty=20,
        allocated_qty=0,
        produced_qty=0,
    )
    db.add(item)
    db.commit()
    exe = create_execution(
        db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 20}]
    )
    assert exe.header_id
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.header_id == exe.header_id
        )
    )
    assert req and req.header_id == exe.header_id
    assert req.order_id is None

    # 清空占用再锁
    req.arrived_qty = Decimal("0")
    db.commit()
    out = allocate_from_pool_for_header(
        db, tenant.id, int(exe.header_id), req.id, Decimal("5"), user_id=1
    )
    assert out["header_id"] == exe.header_id
    assert Decimal(out["arrived_qty"]) >= Decimal("5")

    from app.models import ExecutionHeader

    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    cands = list_allocate_candidates(db, tenant.id, keyword=header.header_no)
    assert any(c.get("header_no") == header.header_no for c in cands)
