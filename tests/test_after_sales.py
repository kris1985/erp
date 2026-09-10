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
    delete_return,
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
    Receivable,
    ReceivableStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Size,
    Tenant,
)
from app.services.finance_service import receivable_balance
from app.services.settlement_service import generate_statement


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
        "progress": "pending",
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
        progress="pending",
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
    assert result["return"]["remake_header_no"] == result["production_order"]["header_no"]
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


def test_after_sales_refund_writes_receivable_adjustment(ctx):
    db, user, customer, source_line = ctx
    sales_order = db.get(SalesOrder, source_line.sales_order_id)
    ar = Receivable(
        tenant_id=user.tenant_id,
        customer_id=customer.id,
        customer_name=customer.name,
        sales_order_id=sales_order.id,
        sales_order_no=sales_order.order_no,
        receivable_date=date(2026, 8, 15),
        amount=Decimal("1000.00"),
        adjustment=Decimal("0"),
        received_amount=Decimal("0"),
        status=ReceivableStatus.open,
    )
    db.add(ar)
    db.commit()

    created = create_return(
        _body(
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
    assert created["actual_refund_amount"] == 294.0
    assert created["posted_receivable_refund"] == 294.0
    assert created["receivable_id"] == ar.id

    db.refresh(ar)
    assert ar.adjustment == Decimal("-294.00")
    assert ar.notes == f"售后退款 {created['return_no']}"
    assert receivable_balance(ar) == Decimal("706.00")

    updated = update_return(
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
    assert updated["posted_receivable_refund"] == 200.0
    db.refresh(ar)
    assert ar.adjustment == Decimal("-200.00")

    statement = generate_statement(
        db,
        user.tenant_id,
        partner_id=customer.id,
        direction="customer",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 9, 30),
        user_id=user.id,
    )
    assert Decimal(str(statement["adjustment_amount"])) == Decimal("-200.00")
    adj_lines = [
        line
        for line in statement["lines"]
        if line["source_type"] == "receivable_adjustment"
    ]
    assert len(adj_lines) == 1
    assert Decimal(str(adj_lines[0]["credit_amount"])) == Decimal("200.00")
    assert "售后退款" in adj_lines[0]["description"]

    cancelled = update_return(
        created["id"],
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=5,
            repair_quantity=0,
            actual_refund_amount=Decimal("0"),
            progress="pending",
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, return_quantity=3),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert cancelled["posted_receivable_refund"] == 0
    assert cancelled["receivable_id"] is None
    db.refresh(ar)
    assert ar.adjustment == Decimal("0.00")

    # 再入账后删除，应冲回应收调账
    restored = update_return(
        created["id"],
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=5,
            repair_quantity=0,
            actual_refund_amount=Decimal("150.00"),
            progress="pending",
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, return_quantity=3),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert restored["posted_receivable_refund"] == 150.0
    delete_return(created["id"], db=db, user=user)
    db.refresh(ar)
    assert ar.adjustment == Decimal("0.00")


def test_complete_requires_full_handling(ctx):
    from app.api.v1.after_sales import complete_return
    from fastapi import HTTPException

    db, user, customer, source_line = ctx
    created = create_return(
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=2,
            repair_quantity=0,
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, return_quantity=0),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert created["progress"] == "pending"
    with pytest.raises(HTTPException) as exc:
        complete_return(created["id"], db=db, user=user)
    assert "须等于总数量" in str(exc.value.detail)

    filled = update_return(
        created["id"],
        _body(
            customer_id=customer.id,
            source_sales_order_line_id=source_line.id,
            carton_count=1,
            quantity=5,
            return_quantity=2,
            repair_quantity=3,
            sizes=[
                ReturnSizeIn(size="36", quantity=2, return_quantity=2),
                ReturnSizeIn(size="37", quantity=3, repair_quantity=3),
            ],
        ),
        db=db,
        user=user,
    )["data"]
    assert filled["return_quantity"] + filled["repair_quantity"] + filled["remake_quantity"] == filled["quantity"]
    done = complete_return(created["id"], db=db, user=user)["data"]
    assert done["progress"] == "completed"

def test_after_sales_remake_shipment_skips_receivable(ctx):
    from app.models import Shipment, ShipmentStatus
    from app.services.finance_service import create_receivable_for_shipment

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
    header_id = result["production_order"]["id"]
    sales_order = db.get(SalesOrder, source_line.sales_order_id)
    sh = Shipment(
        tenant_id=user.tenant_id,
        shipment_no="SH-REMAKE-001",
        sales_order_id=sales_order.id,
        sales_order_no=sales_order.order_no,
        customer_id=customer.id,
        customer_name=customer.name,
        status=ShipmentStatus.shipped,
        ship_date=date(2026, 9, 10),
        unit_price=Decimal("58.80"),
        total_qty=3,
        amount=Decimal("176.40"),
        notes="售后重做出货测试",
    )
    db.add(sh)
    db.flush()

    ar = create_receivable_for_shipment(db, user.tenant_id, sh, header_id=header_id)
    assert ar is None
    normal = Shipment(
        tenant_id=user.tenant_id,
        shipment_no="SH-NORMAL-001",
        sales_order_id=sales_order.id,
        sales_order_no=sales_order.order_no,
        customer_id=customer.id,
        customer_name=customer.name,
        status=ShipmentStatus.shipped,
        ship_date=date(2026, 9, 10),
        unit_price=Decimal("58.80"),
        total_qty=2,
        amount=Decimal("117.60"),
        notes="正常出货",
    )
    db.add(normal)
    db.flush()
    ar2 = create_receivable_for_shipment(db, user.tenant_id, normal)
    assert ar2 is not None
    assert ar2.amount == Decimal("117.60")
