"""客户待结算明细带出退货，金额为负，且不和出货重复扣减。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AfterSalesReturn,
    Color,
    OwnProduct,
    Partner,
    Receivable,
    ReceivableStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Shipment,
    ShipmentLine,
    ShipmentStatus,
    Size,
    Tenant,
)
from app.services.sales_settlement_service import (
    customer_sales_balance,
    generate_sales_statement,
    list_pending_lines,
    pending_amount,
    void_sales_statement,
)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="对账测试厂")
    db.add(tenant)
    db.flush()
    customer = Partner(tenant_id=tenant.id, name="客户甲", short_name="甲", is_customer=True)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="GC-99",
        image_url="/uploads/gc-99.jpg",
    )
    color = Color(tenant_id=tenant.id, name="黑色", code="BK")
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=0)
    db.add_all([customer, product, color, size])
    db.flush()
    order = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-100",
        customer_id=customer.id,
        customer_name=customer.name,
        ordered_at=date(2026, 8, 1),
    )
    db.add(order)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=order.id,
        own_product_id=product.id,
        color_id=color.id,
        brand_name="北辰",
        customer_sku="KH-36",
        unit_price=Decimal("58.80"),
        total_qty=10,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        color_id=color.id,
        size_id=size.id,
        qty=10,
    )
    db.add(item)
    db.flush()
    shipment = Shipment(
        tenant_id=tenant.id,
        shipment_no="SH-100",
        sales_order_id=order.id,
        sales_order_no=order.order_no,
        customer_id=customer.id,
        customer_name=customer.name,
        status=ShipmentStatus.shipped,
        ship_date=date(2026, 9, 1),
        unit_price=Decimal("58.80"),
        total_qty=10,
        amount=Decimal("588.00"),
    )
    db.add(shipment)
    db.flush()
    db.add(
        ShipmentLine(
            tenant_id=tenant.id,
            shipment_id=shipment.id,
            sales_order_line_item_id=item.id,
            color_id=color.id,
            size_id=size.id,
            qty=10,
        )
    )
    ar = Receivable(
        tenant_id=tenant.id,
        customer_id=customer.id,
        customer_name=customer.name,
        sales_order_id=order.id,
        sales_order_no=order.order_no,
        shipment_id=shipment.id,
        receivable_date=date(2026, 9, 1),
        amount=Decimal("588.00"),
        adjustment=Decimal("-117.60"),
        received_amount=Decimal("0"),
        status=ReceivableStatus.open,
    )
    db.add(ar)
    db.flush()
    ret = AfterSalesReturn(
        tenant_id=tenant.id,
        return_date=date(2026, 9, 8),
        return_no="TH-100",
        customer_id=customer.id,
        customer_name=customer.name,
        source_sales_order_line_id=line.id,
        own_product_id=product.id,
        factory_model="GC-99",
        customer_brand="北辰",
        customer_model="KH-36",
        product_image_url="/uploads/gc-99.jpg",
        color="黑色",
        quantity=2,
        return_quantity=2,
        unit_price=Decimal("58.80"),
        total_price=Decimal("117.60"),
        actual_refund_amount=Decimal("117.60"),
        posted_receivable_refund=Decimal("117.60"),
        receivable_id=ar.id,
    )
    db.add(ret)
    db.commit()
    return db, tenant.id, customer.id, ar.id, ret.id


def test_pending_lines_include_return_as_negative(ctx):
    db, tenant_id, customer_id, _ar_id, _return_id = ctx
    rows = list_pending_lines(db, tenant_id, customer_id=customer_id)
    by_type = {row["row_type"]: row for row in rows}
    assert set(by_type) == {"shipment", "return"}

    shipment = by_type["shipment"]
    assert shipment["biz_date"] == date(2026, 9, 1)
    assert shipment["shipment_no"] == "SH-100"
    assert shipment["return_no"] is None
    assert shipment["sales_order_no"] == "SO-100"
    assert shipment["ordered_at"] == date(2026, 8, 1)
    assert shipment["factory_model"] == "GC-99"
    assert shipment["color_name"] == "黑色"
    assert shipment["brand_name"] == "北辰"
    assert shipment["customer_sku"] == "KH-36"
    assert shipment["image_url"] == "/uploads/gc-99.jpg"
    assert shipment["qty"] == 10
    assert shipment["unit_price"] == Decimal("58.8000")
    assert shipment["amount"] == Decimal("588.0000")

    returned = by_type["return"]
    assert returned["biz_date"] == date(2026, 9, 8)
    assert returned["shipment_no"] is None
    assert returned["return_no"] == "TH-100"
    assert returned["sales_order_no"] is None
    assert returned["ordered_at"] is None
    assert returned["factory_model"] == "GC-99"
    assert returned["color_name"] == "黑色"
    assert returned["brand_name"] == "北辰"
    assert returned["customer_sku"] == "KH-36"
    assert returned["qty"] == -2
    assert returned["amount"] == Decimal("-117.6000")

    assert pending_amount(rows) == Decimal("470.4000")
    balance = customer_sales_balance(db, tenant_id, customer_id)
    assert balance["pending_amount"] == Decimal("470.4000")
    assert balance["debt"] == Decimal("470.4000")

    matched = list_pending_lines(db, tenant_id, customer_id=customer_id, shipment_no="TH-100")
    assert [row["row_type"] for row in matched] == ["return"]
    by_order = list_pending_lines(db, tenant_id, customer_id=customer_id, sales_order_no="SO-100")
    assert {row["row_type"] for row in by_order} == {"shipment", "return"}
    assert next(row for row in by_order if row["row_type"] == "return")["sales_order_no"] is None


def test_statement_keeps_return_amount_and_void_restores_it(ctx):
    db, tenant_id, customer_id, ar_id, return_id = ctx
    statement = generate_sales_statement(
        db,
        tenant_id,
        customer_id=customer_id,
        receivable_ids=[ar_id],
        return_ids=[return_id],
        statement_no="DZ-100",
        statement_date=date(2026, 9, 10),
    )
    assert Decimal(str(statement["current_amount"])) == Decimal("470.4000")
    kinds = {line["source_type"] for line in statement["lines"]}
    assert kinds == {"receivable", "after_sales_return"}
    return_line = next(line for line in statement["lines"] if line["source_type"] == "after_sales_return")
    assert return_line["document_no"] == "TH-100"
    assert Decimal(str(return_line["credit_amount"])) == Decimal("117.6000")
    item = return_line["customer_items"][0]
    assert item["return_no"] == "TH-100"
    assert item["sales_order_no"] is None
    assert item["amount"] == Decimal("-117.6000")
    assert list_pending_lines(db, tenant_id, customer_id=customer_id) == []

    void_sales_statement(db, tenant_id, statement["id"])
    restored = list_pending_lines(db, tenant_id, customer_id=customer_id)
    assert pending_amount(restored) == Decimal("470.4000")
    assert {row["row_type"] for row in restored} == {"shipment", "return"}
