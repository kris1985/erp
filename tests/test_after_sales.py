"""售后退货：金额计算、尺码拆分与重做校验。"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.after_sales import (
    AfterSalesIn,
    ReturnSizeIn,
    create_return,
    create_remake_production,
    list_options,
    list_returns,
    update_return,
)
from app.db import Base
from app.models import (
    Color,
    Employee,
    OwnProductLabor,
    OwnProduct,
    Partner,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Size,
    Tenant,
)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="售后测试厂")
    db.add(tenant)
    db.flush()
    user = Employee(
        tenant_id=tenant.id,
        name="售后主管",
        mobile="13900000099",
        is_active=True,
    )
    db.add(user)
    customer = Partner(tenant_id=tenant.id, name="客户甲", is_customer=True)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="GC-99",
        image_url="/uploads/product.jpg",
    )
    color = Color(tenant_id=tenant.id, name="黑色", code="BK")
    size36 = Size(tenant_id=tenant.id, size_value="36", sort_order=0)
    size37 = Size(tenant_id=tenant.id, size_value="37", sort_order=1)
    db.add_all([customer, product, color, size36, size37])
    db.flush()
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX-AFTER",
        default_price=Decimal("1"),
        sort_order=1,
    )
    db.add(process)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=process.id,
            process_name=process.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    sales_order = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-AFTER-001",
        customer_id=customer.id,
        customer_name=customer.name,
        ordered_at=date(2026, 8, 1),
    )
    db.add(sales_order)
    db.flush()
    source_line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=sales_order.id,
        own_product_id=product.id,
        color_id=color.id,
        brand_name="客户品牌 A",
        customer_sku="KH-88",
        unit_price=Decimal("58.80"),
        carton_qty=2,
        total_qty=10,
    )
    db.add(source_line)
    db.flush()
    db.add_all(
        [
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=source_line.id,
                color_id=color.id,
                size_id=size36.id,
                qty=4,
            ),
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=source_line.id,
                color_id=color.id,
                size_id=size37.id,
                qty=6,
            ),
        ]
    )
    db.commit()
    try:
        yield db, user, customer, source_line
    finally:
        db.close()


def _body(**overrides) -> AfterSalesIn:
    data = {
        "return_date": date(2026, 9, 10),
        "return_no": "TH-20260910-01",
        "customer_id": 1,
        "source_sales_order_line_id": 1,
        "customer_brand": "客户品牌 A",
        "customer_model": "KH-88",
        "factory_model": "GC-99",
        "color": "黑色",
        "return_photo_urls": ["/uploads/return-1.jpg", "/uploads/return-2.jpg"],
        "carton_count": 2,
        "quantity": 10,
        "return_quantity": 3,
        "unit_price": Decimal("999"),
        "return_reason": "开胶",
        "repair_quantity": 4,
        "progress": "processing",
        "sizes": [
            ReturnSizeIn(size="36", quantity=4, return_quantity=1, repair_quantity=1, remake_quantity=2),
            ReturnSizeIn(size="37", quantity=6, return_quantity=2, repair_quantity=3, remake_quantity=1),
        ],
    }
    data.update(overrides)
    return AfterSalesIn(**data)


def test_create_list_and_update_after_sales(ctx):
    db, user, customer, source_line = ctx
    created = create_return(
        _body(customer_id=customer.id, source_sales_order_line_id=source_line.id),
        db=db,
        user=user,
    )["data"]
    assert created["total_price"] == 588.0
    assert created["return_no"] == "TH260910001"
    assert created["remake_quantity"] == 3
    assert created["return_quantity"] == 3
    assert created["repair_quantity"] == 4
    assert created["refund_amount"] == 176.4
    assert created["actual_refund_amount"] == 176.4
    assert created["loss_amount"] == 176.4
    assert created["customer_name"] == "客户甲"
    assert created["customer_brand"] == "客户品牌 A"
    assert created["customer_model"] == "KH-88"
    assert created["color"] == "黑色"
    assert created["product_image_url"] == "/uploads/product.jpg"
    assert created["return_photo_urls"] == [
        "/uploads/return-1.jpg",
        "/uploads/return-2.jpg",
    ]
    assert created["sizes"][0] == {
        "id": created["sizes"][0]["id"],
        "size": "36",
        "quantity": 4,
        "return_quantity": 1,
        "repair_quantity": 1,
        "remake_quantity": 2,
    }

    page = list_returns(
        keyword="GC-99",
        progress="processing",
        date_from=None,
        date_to=None,
        page=1,
        page_size=20,
        db=db,
        user=user,
    )["data"]
    assert page["total"] == 1
    assert page["items"][0]["return_no"] == "TH260910001"

    updated = update_return(
        created["id"],
        _body(
            return_no="MANUAL-NO-IGNORED",
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=5,
            repair_quantity=0,
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, return_quantity=3),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert updated["total_price"] == 294.0
    assert updated["return_no"] == "TH260910001"
    assert updated["remake_quantity"] == 0
    assert updated["refund_amount"] == 294.0
    assert updated["actual_refund_amount"] == 294.0
    assert updated["loss_amount"] == 294.0
    assert len(updated["sizes"]) == 2

    custom_refund = update_return(
        created["id"],
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=5,
            repair_quantity=0,
            actual_refund_amount=Decimal("200.00"),
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, return_quantity=3),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert custom_refund["refund_amount"] == 294.0
    assert custom_refund["actual_refund_amount"] == 200.0
    assert custom_refund["loss_amount"] == 200.0

    options = list_options(customer_id=customer.id, db=db, user=user)["data"]["items"]
    assert options[0]["factory_model"] == "GC-99"
    assert options[0]["customer_model"] == "KH-88"
    assert options[0]["color"] == "黑色"
    assert options[0]["unit_price"] == 58.8
    assert options[0]["image_url"] == "/uploads/product.jpg"
    assert options[0]["sizes"] == [
        {"size": "36", "quantity_per_carton": 2},
        {"size": "37", "quantity_per_carton": 3},
    ]

    custom_mix = create_return(
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
        ),
        db=db,
        user=user,
    )["data"]
    assert custom_mix["quantity"] == 10
    assert custom_mix["sizes"][0]["quantity"] == 4


def test_remake_cannot_exceed_return_size_quantity():
    with pytest.raises(ValidationError, match="不能超过"):
        _body(return_quantity=0, repair_quantity=0, sizes=[ReturnSizeIn(size="36", quantity=10, remake_quantity=11)])


def test_size_total_must_equal_return_quantity():
    with pytest.raises(ValidationError, match="应等于总数量"):
        _body(quantity=11)


def test_remake_action_creates_linked_production_header(ctx):
    db, user, customer, source_line = ctx
    pending = _body(
        customer_id=customer.id,
        source_sales_order_line_id=source_line.id,
        return_quantity=0,
        repair_quantity=0,
        sizes=[ReturnSizeIn(size="36", quantity=4), ReturnSizeIn(size="37", quantity=6)],
    )
    created = create_return(pending, db=db, user=user)["data"]
    remake = _body(
        customer_id=customer.id,
        source_sales_order_line_id=source_line.id,
        return_quantity=0,
        repair_quantity=0,
        sizes=[
            ReturnSizeIn(size="36", quantity=4, remake_quantity=2),
            ReturnSizeIn(size="37", quantity=6, remake_quantity=1),
        ],
    )
    result = create_remake_production(created["id"], remake, db=db, user=user)["data"]
    assert result["production_order"]["header_no"].startswith("XE-")
    assert result["production_order"]["existing"] is False
    assert result["return"]["remake_execution_header_id"] == result["production_order"]["id"]
    assert result["return"]["remake_quantity"] == 3
    assert result["return"]["kit"] is not None
    assert "material_status" in result["return"]["kit"] or result["return"]["kit"].get("empty_bom") is not None
    listed = list_returns(
        keyword=None,
        progress=None,
        date_from=None,
        date_to=None,
        page=1,
        page_size=20,
        db=db,
        user=user,
    )["data"]["items"]
    matched = next(item for item in listed if item["id"] == created["id"])
    assert matched["kit"] is not None
    assert matched["kit"].get("material_status") in ("kit_ok", "purchasing", "short", None) or matched["kit"].get("empty_bom") is True
    repeated = create_remake_production(created["id"], remake, db=db, user=user)["data"]
    assert repeated["production_order"]["id"] == result["production_order"]["id"]
    assert repeated["production_order"]["existing"] is True
    assert repeated["return"]["kit"] is not None
