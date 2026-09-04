"""正式缺料认生产单；合单只生成一份生产用料。"""

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
    OrderMaterialRequirement,
    Partner,
    ProcessDefinition,
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
    confirm_sales_order,
    list_demand_shortages,
)
from app.services.execution_service import create_execution
from app.services.purchase_service import (
    PurchaseError,
    create_drafts_from_shortages,
    receive_po,
    submit_po,
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


def _seed_confirmed_so(db, *, order_no: str = "SO-DM-1", qty: int = 20):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))
    product_id = db.scalar(select(OwnProduct.id))
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
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
        total_qty=qty,
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
            qty=qty,
        )
    )
    db.commit()
    confirm_sales_order(db, tenant_id, so.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    return so, line


def test_confirmed_sales_order_has_no_formal_shortage_before_production(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_confirmed_so(db)
    assert line.execution_header_id is None
    data = list_demand_shortages(db, tenant_id, sales_order_id=so.id)
    assert data["production_order_count"] == 0
    assert data["shortage_lines"] == 0
    assert data["to_buy_lines"] == 0
    assert data["lines"] == []
    assert data["requirement_ids"] == []


def test_confirmed_production_requirement_stays_in_buy_list_and_creates_linked_draft(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_confirmed_so(db)

    confirm_sales_order(db, tenant_id, so.id, created_by=None, direct_create=True)
    db.refresh(line)
    assert line.execution_header_id is not None

    listed = list_demand_shortages(db, tenant_id, sales_order_id=so.id)
    formal = listed["lines"]
    assert formal
    assert listed["production_order_count"] == 1
    assert listed["requirement_ids"] == [row["requirement_id"] for row in formal]
    assert all(row["header_id"] == line.execution_header_id for row in formal)
    assert all(row["production_order_id"] == line.execution_header_id for row in formal)
    assert all("source" not in row and "sources" not in row for row in formal)

    created = create_drafts_from_shortages(
        db,
        tenant_id,
        requirement_ids=[formal[0]["requirement_id"]],
        user_id=None,
    )
    assert created
    po_line = db.scalar(
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.order_material_requirement_id == formal[0]["requirement_id"])
    )
    assert po_line is not None
    assert po_line.sales_order_id == so.id
    assert po_line.sales_order_line_id == line.id
    assert db.get(OrderMaterialRequirement, po_line.order_material_requirement_id).header_id == line.execution_header_id
    po_out = created[0]
    assert po_out["lines"][0]["header_no"]
    assert po_out["lines"][0]["order_no"] == po_out["lines"][0]["header_no"]
    assert po_out["lines"][0]["sales_order_no"] == so.order_no
    assert po_out["summary_lines"][0]["allocations"][0]["header_no"] == po_out["lines"][0]["header_no"]

    submit_po(db, tenant_id, created[0]["id"])
    with pytest.raises(PurchaseError) as exc:
        receive_po(
            db,
            tenant_id,
            created[0]["id"],
            [{"line_id": po_line.id, "qty": Decimal(str(po_line.qty)) + Decimal("0.01")}],
        )
    assert exc.value.code == "over_receive"


def test_merged_production_order_has_one_shortage_ledger_and_filters_by_either_sales_order(db):
    tenant_id = db.scalar(select(Tenant.id))
    so_a, line_a = _seed_confirmed_so(db, order_no="SO-MERGE-A", qty=30)
    so_b, line_b = _seed_confirmed_so(db, order_no="SO-MERGE-B", qty=20)
    item_a = db.scalar(
        select(SalesOrderLineItem).where(SalesOrderLineItem.sales_order_line_id == line_a.id)
    )
    item_b = db.scalar(
        select(SalesOrderLineItem).where(SalesOrderLineItem.sales_order_line_id == line_b.id)
    )

    execution = create_execution(
        db,
        tenant_id=tenant_id,
        items=[
            {"sales_order_line_item_id": item_a.id, "qty": 30},
            {"sales_order_line_item_id": item_b.id, "qty": 20},
        ],
    )
    header_id = int(execution.header_id)

    all_rows = list_demand_shortages(db, tenant_id)
    by_a = list_demand_shortages(db, tenant_id, sales_order_id=so_a.id)
    by_b = list_demand_shortages(db, tenant_id, sales_order_id=so_b.id)

    assert all_rows["production_order_count"] == 1
    assert by_a["production_order_count"] == 1
    assert by_b["production_order_count"] == 1
    assert {row["requirement_id"] for row in by_a["lines"]} == {
        row["requirement_id"] for row in by_b["lines"]
    }
    assert all(row["header_id"] == header_id for row in all_rows["lines"])
    assert all(Decimal(str(row["required_qty"])) == Decimal("50") for row in all_rows["lines"])
    assert all("source" not in row and "sources" not in row for row in all_rows["lines"])

    created = create_drafts_from_shortages(
        db,
        tenant_id,
        requirement_ids=[all_rows["lines"][0]["requirement_id"]],
        user_id=None,
    )
    assert created
    po_line = db.scalar(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.order_material_requirement_id
            == all_rows["lines"][0]["requirement_id"]
        )
    )
    assert po_line is not None
    assert po_line.sales_order_id is None
    assert po_line.sales_order_line_id is None
    requirement = db.get(OrderMaterialRequirement, po_line.order_material_requirement_id)
    assert requirement.header_id == header_id
