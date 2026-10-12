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
    Partner,
    PaymentStatus,
    SalaryModel,
    SalesOrder,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
    Size,
    SupplierProduct,
    Tenant,
    ToolingItem,
    ToolingReceipt,
    ToolingReceiptLine,
    ToolingReceiptSize,
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
    # 无计件报工、无模具到货 → 利润 = 10000 - 物料0 - 模具0 - 计件0 - 提成500
    assert Decimal(str(o["mold_last"])) == Decimal("0.00")
    assert Decimal(str(o["mold_sole"])) == Decimal("0.00")
    assert Decimal(str(o["mold_heel"])) == Decimal("0.00")
    assert Decimal(str(o["mold_knife"])) == Decimal("0.00")
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
    assert r["mold_last"] is None

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


def _receive_tool(db, tenant, supplier, size, kind, code, price, qty, department_id):
    item = db.query(ToolingItem).filter_by(tenant_id=tenant.id, code=code).one_or_none()
    if item is None:
        item = ToolingItem(tenant_id=tenant.id, code=code, kind=kind, is_active=True)
        db.add(item)
        db.flush()
    receipt = ToolingReceipt(
        tenant_id=tenant.id,
        receipt_no=f"R-{kind}-{code}-{department_id}",
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        receipt_date=date(2026, 9, 1),
    )
    db.add(receipt)
    db.flush()
    line = ToolingReceiptLine(
        tenant_id=tenant.id,
        receipt_id=receipt.id,
        department_id=department_id,
        tooling_item_id=item.id,
        unit_price=Decimal(str(price)),
    )
    db.add(line)
    db.flush()
    db.add(
        ToolingReceiptSize(
            tenant_id=tenant.id,
            line_id=line.id,
            size_id=size.id,
            qty=Decimal(str(qty)),
        )
    )


def test_profit_subtracts_shared_mold_allocation(profit_db):
    """楦头按共用编号的全部出货分摊；利润扣掉楦头、鞋底、鞋跟、刀模。"""
    db, tenant, prod = profit_db
    dev = Department(tenant_id=tenant.id, name="开发部", sort_order=2)
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True, is_active=True)
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    db.add_all([dev, supplier, size])
    db.flush()
    heel = SupplierProduct(
        tenant_id=tenant.id,
        product_code="H1",
        name="H1",
        partner_id=supplier.id,
        is_active=True,
    )
    db.add(heel)
    db.flush()
    product_a = OwnProduct(
        tenant_id=tenant.id,
        product_code="A1",
        shoe_last="L1",
        sole_mold="S1",
        heel_model_id=heel.id,
        is_active=True,
    )
    product_b = OwnProduct(
        tenant_id=tenant.id,
        product_code="B1",
        shoe_last="L1",
        is_active=True,
    )
    db.add_all([product_a, product_b])
    db.flush()

    def _order(product, qty, amount, no):
        order = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name="客户",
            own_product_id=product.id,
            total_qty=qty,
            unit_price=Decimal("10"),
            status=OrderStatus.confirmed,
        )
        db.add(order)
        db.flush()
        db.add(
            Shipment(
                tenant_id=tenant.id,
                shipment_no=f"SH-{no}",
                order_id=order.id,
                customer_name="客户",
                status=ShipmentStatus.shipped,
                ship_date=date(2026, 9, 8),
                unit_price=Decimal("10"),
                total_qty=qty,
                amount=Decimal(str(amount)),
            )
        )

    _order(product_a, 100, 1000, "A")
    _order(product_b, 300, 3000, "B")
    # 楦头 10×100=1000，两款共出 400 双 → 2.50 元/双。开发部到货不计。
    _receive_tool(db, tenant, supplier, size, "shoe_last", "L1", "100", 10, prod.id)
    _receive_tool(db, tenant, supplier, size, "shoe_last", "L1", "30", 100, dev.id)
    # 鞋底、鞋跟、刀模只挂在 A1。
    _receive_tool(db, tenant, supplier, size, "sole_mold", "S1", "25", 4, prod.id)
    _receive_tool(db, tenant, supplier, size, "heel_mold", "H1", "50", 2, prod.id)
    _receive_tool(db, tenant, supplier, size, "knife_die", "A1", "12", 5, prod.id)
    db.commit()

    report = finance_service.profit_report(db, tenant.id, year=2026, month=9)
    rows = {row["order_no"]: row for row in report["orders"]}
    order_a = rows["A"]
    order_b = rows["B"]
    assert Decimal(str(order_a["mold_last"])) == Decimal("250.00")
    assert Decimal(str(order_a["mold_sole"])) == Decimal("100.00")
    assert Decimal(str(order_a["mold_heel"])) == Decimal("100.00")
    assert Decimal(str(order_a["mold_knife"])) == Decimal("60.00")
    # 1000 - 250 - 100 - 100 - 60
    assert Decimal(str(order_a["profit"])) == Decimal("490.00")
    assert Decimal(str(order_b["mold_last"])) == Decimal("750.00")
    assert Decimal(str(order_b["mold_sole"])) == Decimal("0.00")
    assert Decimal(str(order_b["mold_heel"])) == Decimal("0.00")
    assert Decimal(str(order_b["mold_knife"])) == Decimal("0.00")
    assert Decimal(str(order_b["profit"])) == Decimal("2250.00")
    summary = report["summary"]
    assert Decimal(str(summary["mold_last"])) == Decimal("1000.00")
    assert Decimal(str(summary["mold_sole"])) == Decimal("100.00")
    assert Decimal(str(summary["mold_heel"])) == Decimal("100.00")
    assert Decimal(str(summary["mold_knife"])) == Decimal("60.00")
    assert Decimal(str(summary["profit"])) == Decimal("2740.00")
