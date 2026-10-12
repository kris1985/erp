"""经营报告：按日期范围汇总出货、利润、损失与开发成本。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AccountStatement,
    AfterSalesReturn,
    AttendanceDay,
    DailyExpense,
    DailyExpenseLine,
    DefectDisposition,
    DefectEvent,
    Department,
    Employee,
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductCommission,
    OwnProductLabor,
    Partner,
    ProcessDefinition,
    Payable,
    PayableLine,
    PayableStatus,
    Payment,
    PurchaseOrder,
    Receivable,
    ReceivableStatus,
    PaymentStatus,
    SalaryModel,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SpecExecutionStatus,
    SettlementDirection,
    Shipment,
    ShipmentStatus,
    Size,
    SubcontractOrder,
    SupplierPayment,
    Tenant,
)
from app.services import business_report_service
from app.services.attendance_service import LOCAL_OFFSET, _local_date


@pytest.fixture()
def report_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="经营厂", settings_json={})
    session.add(tenant)
    session.flush()
    dev = Department(tenant_id=tenant.id, name="开发部", sort_order=1)
    session.add(dev)
    session.flush()
    worker = Employee(
        tenant_id=tenant.id,
        name="开发员",
        department_id=dev.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    session.add(worker)
    session.flush()
    yield session, tenant, {"dev": dev, "worker": worker}
    session.close()


def _local_created_at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, 0) - LOCAL_OFFSET


def test_business_report_aggregates_period_kpis(report_db):
    db, tenant, ctx = report_db
    worker = ctx["worker"]
    dev = ctx["dev"]

    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=dev.id,
        employee_id=worker.id,
        expense_date=date(2026, 5, 2),
        amount=Decimal("500"),
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
            occurred_on=date(2026, 5, 2),
            amount=Decimal("500"),
        )
    )

    product = OwnProduct(tenant_id=tenant.id, product_code="BR-1", is_active=True)
    db.add(product)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-BR",
        customer_name="客",
        own_product_id=product.id,
        total_qty=20,
        unit_price=Decimal("100"),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-BR",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 5, 10),
            unit_price=Decimal("100"),
            total_qty=20,
            amount=Decimal("2000"),
        )
    )
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-OUT",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 4, 10),
            unit_price=Decimal("100"),
            total_qty=8,
            amount=Decimal("800"),
        )
    )

    db.add(
        DefectEvent(
            tenant_id=tenant.id,
            defect_type="dirty",
            qty=5,
            disposition=DefectDisposition.scrap,
            loss_amount=Decimal("100"),
            company_share_percent=40,
            created_at=_local_created_at(date(2026, 5, 8)),
        )
    )
    db.add(
        DefectEvent(
            tenant_id=tenant.id,
            defect_type="dirty",
            qty=9,
            disposition=DefectDisposition.rework,
            loss_amount=Decimal("50"),
            company_share_percent=100,
            created_at=_local_created_at(date(2026, 5, 9)),
        )
    )
    db.add(
        DefectEvent(
            tenant_id=tenant.id,
            defect_type="dirty",
            qty=3,
            disposition=DefectDisposition.scrap,
            loss_amount=Decimal("999"),
            company_share_percent=100,
            created_at=_local_created_at(date(2026, 4, 20)),
        )
    )
    db.add(
        AfterSalesReturn(
            tenant_id=tenant.id,
            return_date=date(2026, 5, 18),
            return_no="AS-1",
            customer_name="客",
            factory_model="BR-1",
            quantity=2,
            return_quantity=2,
            loss_amount=Decimal("80"),
        )
    )
    db.add(
        AfterSalesReturn(
            tenant_id=tenant.id,
            return_date=date(2026, 4, 18),
            return_no="AS-OUT",
            customer_name="客",
            factory_model="BR-1",
            quantity=1,
            return_quantity=1,
            loss_amount=Decimal("30"),
        )
    )
    db.commit()

    report = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 5, 1), date_to=date(2026, 5, 31)
    )

    assert report["date_from"] == "2026-05-01"
    assert report["date_to"] == "2026-05-31"
    assert report["shipped_qty"] == 20
    assert report["dev_expense"] == 500.0
    assert report["dev_unit_cost"] == 25.0
    assert report["allocated_total"] == 500.0
    assert report["allocated_unit_cost"] == 25.0
    # 报废 5 双计入报废率；返修数量不计入
    assert report["scrap_qty"] == 5
    assert report["scrap_rate"] == 0.2  # 5 / (20 + 5)
    # 公司承担：报废 100×40% + 返修 50×100% = 90；区间外报废不计
    assert report["production_loss"] == 90.0
    assert report["after_sales_loss"] == 80.0
    # 整单利润 2800（含 4 月 8 双），按期间 20/28 分摊 → 2000
    assert report["profit"] == 2000.0
    assert report["comprehensive_profit"] == 1330.0  # 2000 - 500 - 90 - 80
    assert report["loss_orders"] == []

    april = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 4, 1), date_to=date(2026, 4, 30)
    )
    assert april["shipped_qty"] == 8
    assert april["scrap_qty"] == 3
    assert april["scrap_rate"] == 0.2727  # 3 / (8 + 3)
    assert april["production_loss"] == 999.0
    assert april["after_sales_loss"] == 30.0
    assert april["profit"] == 800.0  # 2800 × 8/28
    assert april["dev_expense"] == 0.0
    assert april["allocated_total"] == 0.0


def test_business_report_empty_period(report_db):
    db, tenant, _ctx = report_db
    report = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
    )
    assert report["shipped_qty"] == 0
    assert report["scrap_qty"] == 0
    assert report["scrap_rate"] is None
    assert report["dev_unit_cost"] is None
    assert report["allocated_unit_cost"] is None
    assert report["comprehensive_profit"] == 0.0
    assert report["loss_orders"] == []


def test_business_report_lists_loss_orders(report_db):
    db, tenant, ctx = report_db
    worker = ctx["worker"]
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="LOSS-1",
        is_active=True,
        commission_cost=Decimal("20"),
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            employee_id=worker.id,
            amount=Decimal("20"),
            sort_order=0,
        )
    )
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-LOSS",
        customer_name="张武",
        ordered_at=date(2026, 5, 1),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        brand_name="武牌",
        unit_price=Decimal("10"),
        total_qty=10,
    )
    db.add(line)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-LOSS",
        customer_name="张武",
        own_product_id=product.id,
        total_qty=10,
        unit_price=Decimal("10"),
        status=OrderStatus.confirmed,
        sales_order_id=so.id,
        sales_order_line_id=line.id,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-LOSS",
            order_id=order.id,
            customer_name="张武",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 5, 12),
            unit_price=Decimal("10"),
            total_qty=10,
            amount=Decimal("100"),
        )
    )
    db.commit()

    report = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 5, 1), date_to=date(2026, 5, 31)
    )
    # 利润 = 100 − 提成 200 = −100
    assert report["profit"] == -100.0
    assert report["loss_orders"] == [
        {
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-1",
            "loss_amount": 100.0,
        }
    ]


def test_loss_orders_group_by_customer_brand_factory_model():
    rows = [
        {
            "order_no": "A",
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-1",
            "period_profit": Decimal("-40"),
        },
        {
            "order_no": "B",
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-1",
            "period_profit": Decimal("-60"),
        },
        {
            "order_no": "C",
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-2",
            "period_profit": Decimal("-10"),
        },
        {
            "order_no": "D",
            "customer_name": "",
            "brand_name": None,
            "factory_model": "LOSS-1",
            "period_profit": Decimal("-5"),
        },
        {
            "order_no": "E",
            "customer_name": None,
            "brand_name": "",
            "factory_model": "LOSS-1",
            "period_profit": Decimal("-3"),
        },
        {
            "order_no": "F",
            "customer_name": "李安",
            "brand_name": "安牌",
            "factory_model": "OK-1",
            "period_profit": Decimal("20"),
        },
    ]
    assert business_report_service._loss_orders(rows) == [
        {
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-1",
            "loss_amount": 100.0,
        },
        {
            "customer_name": "张武",
            "brand_name": "武牌",
            "factory_model": "LOSS-2",
            "loss_amount": 10.0,
        },
        {
            "customer_name": None,
            "brand_name": None,
            "factory_model": "LOSS-1",
            "loss_amount": 8.0,
        },
    ]


def test_business_report_current_snapshot_ignores_date_range(report_db):
    db, tenant, ctx = report_db
    today = _local_date()
    late_worker = Employee(
        tenant_id=tenant.id,
        name="迟到员",
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    ontime_worker = Employee(
        tenant_id=tenant.id,
        name="准时员",
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    inactive = Employee(
        tenant_id=tenant.id,
        name="离职员",
        salary_model=SalaryModel.pure_piece,
        is_active=False,
    )
    db.add_all([late_worker, ontime_worker, inactive])
    db.flush()

    def utc_at(hour: int, minute: int = 0) -> datetime:
        return datetime(today.year, today.month, today.day, hour, minute) - LOCAL_OFFSET

    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=late_worker.id,
            work_date=today,
            clock_in_at=utc_at(8, 20),
            clock_out_at=utc_at(17, 0),
            work_minutes=520,
            status="normal",
        )
    )
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=ontime_worker.id,
            work_date=today,
            clock_in_at=utc_at(8, 0),
            clock_out_at=utc_at(17, 30),
            work_minutes=570,
            status="normal",
        )
    )
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=inactive.id,
            work_date=today,
            clock_in_at=utc_at(9, 0),
            clock_out_at=utc_at(16, 0),
            work_minutes=420,
            status="normal",
        )
    )

    product = OwnProduct(tenant_id=tenant.id, product_code="NOW-1", is_active=True)
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_name="成型",
            unit_price=Decimal("5"),
            sort_order=0,
        )
    )
    db.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            amount=Decimal("2"),
            sort_order=0,
        )
    )
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    db.add(size)
    db.flush()
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-NOW",
        customer_name="现客",
        ordered_at=today,
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        unit_price=Decimal("50"),
        total_qty=100,
        delivery_date=today - timedelta(days=2),
        status=SalesOrderLineStatus.in_production,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant.id,
            sales_order_line_id=line.id,
            size_id=size.id,
            qty=100,
            produced_qty=40,
            shipped_qty=30,
        )
    )
    db.commit()

    jan = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
    )
    may = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 5, 1), date_to=date(2026, 5, 31)
    )
    snap = jan["snapshot"]
    assert jan["shipped_qty"] == 0
    assert snap["employee_count"] == 3  # 夹具开发员 + 迟到员 + 准时员
    assert snap["late_early_times"] == 2
    assert snap["late_early_minutes"] == 40  # 迟到 15 + 早退 25
    assert snap["unshipped_qty"] == 70
    assert snap["overdue_qty"] == 70
    assert snap["projected_overdue_qty"] == 0
    # 未出货 70 × (50 − 5 − 2) = 3010
    assert snap["projected_profit"] == 3010.0
    assert may["snapshot"] == snap
    assert snap["as_of"] == today.isoformat()


def test_current_snapshot_splits_overdue_and_projected_overdue(report_db):
    db, tenant, _ctx = report_db
    today = _local_date()
    product = OwnProduct(tenant_id=tenant.id, product_code="DUE-1", is_active=True)
    db.add(product)
    db.flush()
    slow = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="SEW",
        per_worker_capacity=Decimal("1"),
        standard_workers=1,
    )
    fast = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="LAST",
        per_worker_capacity=Decimal("100"),
        standard_workers=1,
    )
    db.add_all([slow, fast])
    db.flush()
    size = Size(tenant_id=tenant.id, size_value="41", sort_order=0)
    db.add(size)
    db.flush()
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-DUE",
        customer_name="交期客",
        ordered_at=today,
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()

    def add_line(qty: int, delivery: date) -> SalesOrderLine:
        line = SalesOrderLine(
            tenant_id=tenant.id,
            sales_order_id=so.id,
            own_product_id=product.id,
            unit_price=Decimal("40"),
            total_qty=qty,
            delivery_date=delivery,
            status=SalesOrderLineStatus.in_production,
        )
        db.add(line)
        db.flush()
        db.add(
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=line.id,
                size_id=size.id,
                qty=qty,
                shipped_qty=0,
            )
        )
        return line

    add_line(40, today - timedelta(days=1))
    late_line = add_line(30, today + timedelta(days=2))
    safe_line = add_line(10, today + timedelta(days=40))
    add_line(8, today + timedelta(days=3))

    def add_header(line: SalesOrderLine, proc: ProcessDefinition, plan_qty: int, no: str) -> None:
        header = ExecutionHeader(
            tenant_id=tenant.id,
            header_no=no,
            own_product_id=product.id,
            sales_order_id=so.id,
            sales_order_line_id=line.id,
            total_qty=plan_qty,
            status=SpecExecutionStatus.in_progress,
            delivery_date=line.delivery_date,
        )
        db.add(header)
        db.flush()
        db.add(
            OrderProcess(
                tenant_id=tenant.id,
                header_id=header.id,
                process_id=proc.id,
                process_name=proc.name,
                plan_qty=plan_qty,
                completed_qty=0,
                status=OrderProcessStatus.pending,
            )
        )

    add_header(late_line, slow, 30, "EH-LATE")
    add_header(safe_line, fast, 10, "EH-SAFE")
    db.commit()

    snap = business_report_service.business_report(
        db, tenant.id, date_from=today, date_to=today
    )["snapshot"]
    assert snap["overdue_qty"] == 40
    assert snap["projected_overdue_qty"] == 30
    assert snap["unshipped_qty"] == 88


def test_current_snapshot_agency_balance_splits_posted_cash(report_db):
    db, tenant, _ctx = report_db
    today = _local_date()
    supplier = Partner(tenant_id=tenant.id, name="材料商", is_supplier=True)
    factory = Partner(tenant_id=tenant.id, name="外发厂", is_subcontractor=True)
    customer = Partner(tenant_id=tenant.id, name="客户甲", is_customer=True)
    db.add_all([supplier, factory, customer])
    db.flush()

    def statement(partner: Partner, no: str, kind: str) -> AccountStatement:
        row = AccountStatement(
            tenant_id=tenant.id,
            statement_no=no,
            partner_id=partner.id,
            partner_name=partner.name,
            direction=SettlementDirection.supplier,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            statement_date=today,
            due_date=today,
            statement_kind=kind,
        )
        db.add(row)
        db.flush()
        return row

    purchase = statement(supplier, "ST-PUR", "purchase")
    purchase.closing_balance = Decimal("300")
    subcontract = statement(factory, "ST-SUB", "subcontract")
    subcontract.closing_balance = Decimal("120")
    po = PurchaseOrder(tenant_id=tenant.id, po_no="PO-DUE", partner_id=supplier.id)
    sub_order = SubcontractOrder(
        tenant_id=tenant.id,
        subcontract_no="WX-DUE",
        partner_id=factory.id,
        order_process_ids=[],
    )
    db.add_all([po, sub_order])
    db.flush()
    purchase_ap = Payable(
        tenant_id=tenant.id,
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        purchase_order_id=po.id,
        payable_date=today,
        due_date=today,
        amount=Decimal("80"),
        status=PayableStatus.open,
    )
    subcontract_ap = Payable(
        tenant_id=tenant.id,
        supplier_id=factory.id,
        supplier_name=factory.name,
        subcontract_order_id=sub_order.id,
        payable_date=today,
        due_date=today,
        amount=Decimal("40"),
        status=PayableStatus.open,
    )
    db.add_all([purchase_ap, subcontract_ap])
    db.flush()
    db.add_all(
        [
            PayableLine(
                tenant_id=tenant.id,
                payable_id=purchase_ap.id,
                source_type="purchase_receive",
                amount=Decimal("80"),
            ),
            PayableLine(
                tenant_id=tenant.id,
                payable_id=subcontract_ap.id,
                source_type="subcontract_receive",
                amount=Decimal("40"),
            ),
        ]
    )
    sales = AccountStatement(
        tenant_id=tenant.id,
        statement_no="ST-CUS",
        partner_id=customer.id,
        partner_name=customer.name,
        direction=SettlementDirection.customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        statement_date=today,
        due_date=today,
        closing_balance=Decimal("300"),
        statement_kind="sales",
    )
    db.add(sales)
    db.flush()
    db.add_all(
        [
            Receivable(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name=customer.name,
                receivable_date=today,
                amount=Decimal("1000"),
                received_amount=Decimal("200"),
                status=ReceivableStatus.open,
            ),
            Receivable(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name=customer.name,
                receivable_date=today,
                amount=Decimal("50"),
                status=ReceivableStatus.void,
            ),
            Payment(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name=customer.name,
                statement_id=sales.id,
                amount=Decimal("100"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
            Payment(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name=customer.name,
                amount=Decimal("50"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
            SupplierPayment(
                tenant_id=tenant.id,
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                statement_id=purchase.id,
                amount=Decimal("100"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
            SupplierPayment(
                tenant_id=tenant.id,
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                amount=Decimal("10"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
            SupplierPayment(
                tenant_id=tenant.id,
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                amount=Decimal("7"),
                payment_date=today,
                status=PaymentStatus.void,
            ),
            SupplierPayment(
                tenant_id=tenant.id,
                supplier_id=factory.id,
                supplier_name=factory.name,
                statement_id=subcontract.id,
                amount=Decimal("20"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
            SupplierPayment(
                tenant_id=tenant.id,
                supplier_id=factory.id,
                supplier_name=factory.name,
                amount=Decimal("9"),
                payment_date=today,
                status=PaymentStatus.posted,
            ),
        ]
    )
    db.commit()

    snap = business_report_service.business_report(
        db, tenant.id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
    )["snapshot"]
    from app.services.salary_service import month_salary_all

    salary = float(
        Decimal(str(month_salary_all(db, tenant.id, f"{today.year:04d}-{today.month:02d}")["total_wage"])).quantize(
            Decimal("0.01")
        )
    )
    assert snap["customer_receivable"] == 1000.0
    assert snap["salary_due"] == salary
    assert snap["supplier_due"] == 280.0
    assert snap["subcontract_due"] == 140.0
    assert snap["agency_balance"] == float(
        (Decimal("1000") - Decimal(str(salary)) - Decimal("280") - Decimal("140")).quantize(Decimal("0.01"))
    )
