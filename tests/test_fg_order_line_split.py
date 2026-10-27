"""成品仓按订单行拆开，同一订单的两行不能并成一行。"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    OwnProduct,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Size,
    SpecExecutionStatus,
    Tenant,
)
from app.services.fg_service import _finished_order_rows


def test_finished_warehouse_splits_lines_of_the_same_order():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="成品仓厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    product = OwnProduct(tenant_id=tenant.id, product_code="FG-A", is_active=True)
    db.add_all([color, size, product])
    db.flush()
    order = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-1",
        customer_name="客户甲",
        ordered_at=date(2026, 10, 1),
    )
    db.add(order)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-1",
        own_product_id=product.id,
        color_id=color.id,
        sales_order_id=order.id,
        total_qty=16,
        status=SpecExecutionStatus.completed,
    )
    db.add(header)
    db.flush()
    line_a = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=order.id,
        own_product_id=product.id,
        color_id=color.id,
        execution_header_id=header.id,
        customer_sku="AAA",
        brand_name="品牌甲",
        carton_qty=1,
        total_qty=10,
        sort_order=0,
    )
    line_b = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=order.id,
        own_product_id=product.id,
        color_id=color.id,
        execution_header_id=header.id,
        customer_sku="BBB",
        brand_name="品牌乙",
        carton_qty=1,
        total_qty=6,
        sort_order=1,
    )
    db.add_all([line_a, line_b])
    db.flush()
    db.add_all(
        [
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=line_a.id,
                color_id=color.id,
                size_id=size.id,
                qty=10,
            ),
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=line_b.id,
                color_id=color.id,
                size_id=size.id,
                qty=6,
            ),
        ]
    )
    db.commit()

    rows = _finished_order_rows(
        db,
        tenant.id,
        [header],
        None,
        warehouse_only=True,
        stock_view="pending",
        finished_ids={int(header.id)},
        done_pairs_by_header={int(header.id): 16},
    )
    items = rows["items"]
    assert len(items) == 2
    assert {item["customer_sku"] for item in items} == {"AAA", "BBB"}
    assert {item["brand_name"] for item in items} == {"品牌甲", "品牌乙"}
    assert {item["sales_order_line_id"] for item in items} == {int(line_a.id), int(line_b.id)}
    assert {item["total_qty"] for item in items} == {10, 6}
    assert len({item["row_key"] for item in items}) == 2
