"""工资提成：按出货数量 × 产品提成单价计入应发。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Department,
    Employee,
    Order,
    OrderStatus,
    OwnProduct,
    OwnProductCommission,
    SalaryModel,
    Shipment,
    ShipmentLine,
    ShipmentStatus,
    Size,
    Tenant,
)
from app.services.salary_service import month_salary, month_salary_all


@pytest.fixture()
def commission_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="提成厂", settings_json={})
    session.add(tenant)
    session.flush()
    dept = Department(tenant_id=tenant.id, name="业务")
    session.add(dept)
    session.flush()
    size = Size(tenant_id=tenant.id, size_value="39", sort_order=1)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="C-100",
        is_active=True,
        commission_cost=Decimal("2.50"),
    )
    session.add_all([size, product])
    session.flush()
    salesman = Employee(
        tenant_id=tenant.id,
        name="业务员甲",
        department_id=dept.id,
        salary_model=SalaryModel.fixed,
        base_salary=Decimal("3000"),
        is_active=True,
    )
    other = Employee(
        tenant_id=tenant.id,
        name="业务员乙",
        department_id=dept.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    session.add_all([salesman, other])
    session.flush()
    session.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            employee_id=salesman.id,
            amount=Decimal("2.50"),
            sort_order=0,
        )
    )
    order = Order(
        tenant_id=tenant.id,
        order_no="PO-C1",
        customer_name="客户A",
        own_product_id=product.id,
        total_qty=100,
        status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    sh = Shipment(
        tenant_id=tenant.id,
        shipment_no="SH-C1",
        order_id=order.id,
        customer_name="客户A",
        status=ShipmentStatus.shipped,
        ship_date=date(2026, 3, 10),
        unit_price=Decimal("50"),
        total_qty=40,
        amount=Decimal("2000"),
    )
    session.add(sh)
    session.flush()
    session.add(
        ShipmentLine(
            tenant_id=tenant.id,
            shipment_id=sh.id,
            size_id=size.id,
            qty=40,
        )
    )
    # 草稿出货不应计入
    draft = Shipment(
        tenant_id=tenant.id,
        shipment_no="SH-DRAFT",
        order_id=order.id,
        customer_name="客户A",
        status=ShipmentStatus.draft,
        ship_date=date(2026, 3, 12),
        unit_price=Decimal("50"),
        total_qty=10,
        amount=Decimal("500"),
    )
    session.add(draft)
    session.flush()
    session.add(
        ShipmentLine(
            tenant_id=tenant.id,
            shipment_id=draft.id,
            size_id=size.id,
            qty=10,
        )
    )
    # 次月出货不应计入本月
    next_month = Shipment(
        tenant_id=tenant.id,
        shipment_no="SH-NEXT",
        order_id=order.id,
        customer_name="客户A",
        status=ShipmentStatus.shipped,
        ship_date=date(2026, 4, 1),
        unit_price=Decimal("50"),
        total_qty=20,
        amount=Decimal("1000"),
    )
    session.add(next_month)
    session.flush()
    session.add(
        ShipmentLine(
            tenant_id=tenant.id,
            shipment_id=next_month.id,
            size_id=size.id,
            qty=20,
        )
    )
    session.commit()
    yield session, tenant, salesman, other, product
    session.close()


def test_salary_commission_from_shipped_qty(commission_db):
    db, tenant, salesman, other, product = commission_db
    row = month_salary(db, tenant.id, salesman.id, "2026-03")
    assert row["commission_total"] == pytest.approx(100.0)  # 40 × 2.50
    assert row["commission_qty"] == 40
    assert len(row["commissions"]) == 1
    assert row["commissions"][0]["product_code"] == "C-100"
    assert row["commissions"][0]["shipped_qty"] == 40
    # 固定工资 3000 + 提成 100
    assert row["total_wage"] == pytest.approx(3100.0)

    other_row = month_salary(db, tenant.id, other.id, "2026-03")
    assert other_row["commission_total"] == 0
    assert other_row["commissions"] == []


def test_salary_commission_respects_settle_through(commission_db):
    db, tenant, salesman, *_ = commission_db
    # 截止 3/5：出货 3/10 未计入
    early = month_salary(
        db, tenant.id, salesman.id, "2026-03", settle_through=date(2026, 3, 5)
    )
    assert early["commission_total"] == 0
    # 截止 3/10：计入
    on_day = month_salary(
        db, tenant.id, salesman.id, "2026-03", settle_through=date(2026, 3, 10)
    )
    assert on_day["commission_total"] == pytest.approx(100.0)


def test_month_salary_all_includes_commission_summary(commission_db):
    db, tenant, salesman, *_ = commission_db
    overview = month_salary_all(db, tenant.id, "2026-03")
    item = next(i for i in overview["items"] if i["worker_id"] == salesman.id)
    assert item["commission_total"] == pytest.approx(100.0)
    assert overview["summary"]["commission_total"] == pytest.approx(100.0)
