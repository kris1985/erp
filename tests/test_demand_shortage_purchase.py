"""需求缺料认销售：接单后可算、可建采购草稿，不锁库存、不建执行单。"""

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
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services.sales_order_service import (
    SalesOrderError,
    confirm_sales_order,
    create_demand_purchase_drafts,
    list_demand_shortages,
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
    tenant = Tenant(name="需求缺料厂")
    session.add(tenant)
    session.flush()
    partner = Partner(tenant_id=tenant.id, name="底厂", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="DM-1",
        image_url="http://example.com/dm-1.png",
        is_active=True,
        trace_enabled=True,
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
    sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="SOLE-40",
        name="大底",
        unit_price=Decimal("10"),
        is_active=True,
    )
    session.add(sp)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("10"),
            line_total=Decimal("10"),
            sort_order=0,
        )
    )
    session.commit()
    yield session
    session.close()


def _seed_confirmed_so(db):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))
    product_id = db.scalar(select(OwnProduct.id))
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-DM-1",
        customer_name="客户",
        ordered_at=date.today(),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=20,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant_id,
            sales_order_line_id=line.id,
            color_id=color_id,
            size_id=size_id,
            qty=20,
        )
    )
    db.commit()
    confirm_sales_order(db, tenant_id, so.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    return so, line


def test_demand_shortages_after_accept_no_lock(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_confirmed_so(db)
    assert line.execution_header_id is None
    data = list_demand_shortages(db, tenant_id, sales_order_id=so.id)
    assert data["source"] == "demand"
    assert data["locked"] is False
    assert int(data["shortage_lines"]) >= 1
    assert int(data.get("to_buy_lines") or 0) >= 1
    assert any(Decimal(str(x.get("to_buy_qty") or x["shortage_qty"])) > 0 for x in data["lines"])
    src = (data["lines"][0].get("sources") or [None])[0]
    assert src is not None
    assert src.get("product_code") == "DM-1"
    assert src.get("product_image_url") == "http://example.com/dm-1.png"
    assert int(src.get("pair_qty") or 0) == 20
    assert Decimal(str(src.get("qty_per_pair") or 0)) == Decimal("1")
    assert "pricing_unit_name" in data["lines"][0]


def test_create_demand_purchase_drafts_hangs_sales(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_confirmed_so(db)
    created = create_demand_purchase_drafts(
        db,
        tenant_id,
        [(so.id, line.id)],
        user_id=None,
    )
    assert created
    po = db.scalar(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()))
    assert po is not None
    assert po.notes and "需求备料" in po.notes
    pl = db.scalar(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
    assert pl is not None
    assert pl.sales_order_id == so.id
    assert pl.sales_order_line_id == line.id
    assert pl.order_material_requirement_id is None
    assert pl.order_id is None
    listed = list_demand_shortages(db, tenant_id, sales_order_id=so.id)
    assert int(listed.get("to_buy_lines") or 0) == 0
    assert all(Decimal(str(x.get("to_buy_qty") or 0)) <= 0 for x in listed["lines"])
    with pytest.raises(SalesOrderError):
        create_demand_purchase_drafts(db, tenant_id, [(so.id, line.id)], user_id=None)
