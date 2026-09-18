"""订单利润分析：含退货行、综合分摊（无日期段）、不分页字段。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AfterSalesReturn,
    DailyExpense,
    DailyExpenseLine,
    Department,
    Employee,
    Order,
    OrderStatus,
    OwnProduct,
    OwnProductCommission,
    PaymentStatus,
    SalaryModel,
    SalesOrder,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
    Tenant,
)
from app.services import cost_analysis_service, finance_service


@pytest.fixture()
def profit_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="利润厂", settings_json={})
    session.add(tenant)
    session.flush()
    prod = Department(tenant_id=tenant.id, name="生产部", sort_order=1)
    session.add(prod)
    session.flush()
    session.add(
        Employee(
            tenant_id=tenant.id,
            name="工人",
            department_id=prod.id,
            salary_model=SalaryModel.pure_piece,
            is_active=True,
        )
    )
    session.flush()
    yield session, tenant, prod
    session.close()


def test_profit_report_includes_returns_and_unbounded_allocated(profit_db):
    db, tenant, prod = profit_db
    worker = db.query(Employee).filter(Employee.tenant_id == tenant.id).one()

    # 报销 → 综合分摊基数
    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=prod.id,
        employee_id=worker.id,
        expense_date=date(2026, 9, 1),
        amount=Decimal("1000"),
        status=PaymentStatus.posted,
    )
    db.add(expense)
    db.flush()
    db.add(
        DailyExpenseLine(
            tenant_id=tenant.id,
            expense_id=expense.id,
            sort_order=0,
            category="办公",
            occurred_on=date(2026, 9, 1),
            amount=Decimal("1000"),
        )
    )

    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="456",
        image_url="https://example.com/shoe.png",
        is_active=True,
        commission_cost=Decimal("5"),
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            employee_id=worker.id,
            amount=Decimal("5"),
            sort_order=0,
        )
    )

    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-657",
        customer_name="张武",
        ordered_at=date(2026, 9, 1),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()

    order = Order(
        tenant_id=tenant.id,
        order_no="657",
        customer_name="张武",
        own_product_id=product.id,
        total_qty=100,
        unit_price=Decimal("100"),
        status=OrderStatus.confirmed,
        sales_order_id=so.id,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-657",
            order_id=order.id,
            sales_order_id=so.id,
            customer_name="张武",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 9, 5),
            unit_price=Decimal("100"),
            total_qty=100,
            amount=Decimal("10000"),
        )
    )

    db.add(
        AfterSalesReturn(
            tenant_id=tenant.id,
            return_date=date(2026, 9, 15),
            return_no="59579",
            customer_name="张武",
            own_product_id=product.id,
            customer_brand="百丽",
            factory_model="456",
            product_image_url="https://example.com/shoe.png",
            color="黑",
            quantity=10,
            return_quantity=10,
            loss_amount=Decimal("800"),
        )
    )
    db.commit()

    unbounded = cost_analysis_service.allocated_cost_unbounded(db, tenant.id)
    assert unbounded["shipped_qty"] == 100
    assert unbounded["total_expense"] == 1000.0
    assert unbounded["unit_cost"] == 10.0

    # 日期段筛选不应影响综合分摊 unit；退货按 return_date 进入同月
    report = finance_service.profit_report(db, tenant.id, year=2026, month=9)
    assert report["allocated_cost"]["unit_cost"] == 10.0

    order_rows = [r for r in report["orders"] if r.get("row_type") == "order"]
    return_rows = [r for r in report["orders"] if r.get("row_type") == "return"]
    assert len(order_rows) == 1
    assert len(return_rows) == 1

    o = order_rows[0]
    assert o["order_date"] == "2026-09-01"
    assert o["order_no"] == "657"
    assert o["customer_name"] == "张武"
    assert o["factory_model"] == "456"
    assert o["image_url"] == "https://example.com/shoe.png"
    assert o["total_qty"] == 100
    assert o["shipped_qty"] == 100
    assert Decimal(str(o["total_price"])) == Decimal("10000")
    assert Decimal(str(o["commission"])) == Decimal("500")
    # 无计件报工 → labor=0；利润 = 10000 - 0 - 0 - 500
    assert Decimal(str(o["profit"])) == Decimal("9500")
    assert Decimal(str(o["allocated_cost"])) == Decimal("1000.00")  # 10 × 100
    assert o["return_no"] is None

    r = return_rows[0]
    assert r["order_date"] == "2026-09-15"  # 退货日期显示在下单日期列
    assert r["order_no"] is None
    assert r["return_no"] == "59579"
    assert r["return_qty"] == 10
    assert Decimal(str(r["loss_amount"])) == Decimal("800")
    assert r["brand"] == "百丽"
    assert r["factory_model"] == "456"
    assert r["allocated_cost"] is None

    assert report["summary"]["return_qty"] == 10
    assert Decimal(str(report["summary"]["loss_amount"])) == Decimal("800")
    assert Decimal(str(report["summary"]["allocated_cost"])) == Decimal("1000.00")


def test_profit_report_return_outside_month_excluded(profit_db):
    db, tenant, _prod = profit_db
    product = OwnProduct(tenant_id=tenant.id, product_code="X1", is_active=True)
    db.add(product)
    db.flush()
    db.add(
        AfterSalesReturn(
            tenant_id=tenant.id,
            return_date=date(2026, 8, 20),
            return_no="OUT-1",
            customer_name="客",
            own_product_id=product.id,
            factory_model="X1",
            return_quantity=2,
            loss_amount=Decimal("50"),
        )
    )
    db.commit()
    report = finance_service.profit_report(db, tenant.id, year=2026, month=9)
    assert all(r.get("row_type") != "return" for r in report["orders"])
