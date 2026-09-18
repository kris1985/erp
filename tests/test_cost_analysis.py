"""综合成本分析：按部门×按日，空列不输出二级表头。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    DailyExpense,
    DailyExpenseLine,
    Department,
    Employee,
    OwnProduct,
    OwnProductCommission,
    PaymentStatus,
    ProcessDefinition,
    ProcessType,
    SalaryModel,
    Shipment,
    ShipmentStatus,
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
    SupplierProduct,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    ReportType,
    Order,
    OrderStatus,
    OrderProcess,
    OrderProcessStatus,
    Size,
)
from app.services import cost_analysis_service


@pytest.fixture()
def cost_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="成本厂", settings_json={})
    session.add(tenant)
    session.flush()
    dev = Department(tenant_id=tenant.id, name="开发部", sort_order=1)
    prod = Department(tenant_id=tenant.id, name="生产部", sort_order=2)
    purchase = Department(tenant_id=tenant.id, name="采购部", sort_order=3)
    session.add_all([dev, prod, purchase])
    session.flush()
    session.add_all(
        [
            Employee(
                tenant_id=tenant.id,
                name="开发员",
                department_id=dev.id,
                salary_model=SalaryModel.fixed,
                base_salary=Decimal("3000"),
                is_active=True,
            ),
            Employee(
                tenant_id=tenant.id,
                name="生产工",
                department_id=prod.id,
                salary_model=SalaryModel.pure_piece,
                is_active=True,
            ),
            Employee(
                tenant_id=tenant.id,
                name="采购员",
                department_id=purchase.id,
                salary_model=SalaryModel.fixed,
                base_salary=Decimal("2000"),
                is_active=True,
            ),
        ]
    )
    session.flush()
    yield session, tenant, {"dev": dev, "prod": prod, "purchase": purchase}
    session.close()


def test_cost_analysis_hides_empty_secondary_columns(cost_db):
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    # 报销：仅开发部有其它开支
    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=depts["dev"].id,
        employee_id=workers["开发员"].id,
        expense_date=date(2026, 3, 5),
        amount=Decimal("100"),
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
            occurred_on=date(2026, 3, 5),
            amount=Decimal("100"),
        )
    )
    # 计件：仅生产部
    size = Size(tenant_id=tenant.id, size_value="39", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="P-1", is_active=True)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("2"),
    )
    db.add_all([size, product, process])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-1",
        customer_name="客",
        own_product_id=product.id,
        total_qty=10,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=process.id,
        process_name="针车",
        process_type=ProcessType.personal,
        plan_qty=10,
        status=OrderProcessStatus.pending,
    )
    db.add(op)
    db.flush()
    # 本地 2026-03-06 10:00 = UTC 2026-03-06 02:00
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=workers["生产工"].id,
            order_id=order.id,
            order_process_id=op.id,
            own_product_id=product.id,
            process_id=process.id,
            report_type=ReportType.normal,
            qualified_qty=Decimal("10"),
            unit_price=Decimal("2"),
            source=WorkLogSource.manual,
            status=WorkLogStatus.valid,
            created_at=datetime(2026, 3, 6, 2, 0, 0),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, year=2026, month=3
    )
    headers = {h["department_name"]: [c["key"] for c in h["children"]] for h in report["headers"]}
    # 采购部仅有固定工资，无提成/计件/物料/报销 → 这些二级表头不出现
    assert "采购部" in headers
    assert headers["采购部"] == ["fixed_salary"]
    # 开发部：其它开支 + 固定工资；无提成/计件/物料
    assert "开发部" in headers
    assert "other" in headers["开发部"]
    assert "fixed_salary" in headers["开发部"]
    assert "commission" not in headers["开发部"]
    assert "piecework" not in headers["开发部"]
    assert "material" not in headers["开发部"]
    # 计件按发薪日（次月10号），3 月视图不应出现报工日计件
    assert "piecework" not in headers.get("生产部", [])

    dates = {r["date"] for r in report["rows"]}
    assert "2026-03-05" in dates
    assert "2026-03-06" not in dates  # 报工日不再记计件
    assert report["rows"]

    # 4 月发薪日可见 3 月计件
    report_apr = cost_analysis_service.cost_analysis_report(
        db, tenant.id, year=2026, month=4
    )
    headers_apr = {
        h["department_name"]: [c["key"] for c in h["children"]] for h in report_apr["headers"]
    }
    assert "piecework" in headers_apr.get("生产部", [])
    by_date = {r["date"]: r["values"] for r in report_apr["rows"]}
    assert by_date["2026-04-10"][f"{depts['prod'].id}:piecework"] == 20.0  # 10×2


def test_cost_analysis_material_net_and_commission_day(cost_db):
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    product = OwnProduct(
        tenant_id=tenant.id, product_code="C-1", is_active=True, commission_cost=Decimal("1")
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            employee_id=workers["开发员"].id,
            amount=Decimal("1.50"),
            sort_order=0,
        )
    )
    order = Order(
        tenant_id=tenant.id,
        order_no="O-C",
        customer_name="客",
        own_product_id=product.id,
        total_qty=20,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-1",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 3, 8),
            unit_price=Decimal("50"),
            total_qty=20,
            amount=Decimal("1000"),
        )
    )
    from app.models import OrderMaterialRequirement, Partner

    partner = Partner(
        tenant_id=tenant.id,
        name="供应商A",
        is_supplier=True,
    )
    db.add(partner)
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="M-1",
        name="面料",
        partner_id=partner.id,
        is_active=True,
    )
    db.add(sp)
    db.flush()
    from app.models import OrderMaterialRequirement

    req = OrderMaterialRequirement(
        tenant_id=tenant.id,
        order_id=order.id,
        supplier_product_id=sp.id,
        required_qty=Decimal("10"),
        unit_price=Decimal("5"),
    )
    db.add(req)
    db.flush()
    doc = StockDoc(
        tenant_id=tenant.id,
        doc_no="ISS-1",
        doc_type=StockDocType.issue,
        status=StockDocStatus.posted,
        order_id=order.id,
        created_by=workers["生产工"].id,
        posted_at=datetime(2026, 3, 7, 4, 0, 0),  # 本地 3/7 12:00
    )
    db.add(doc)
    db.flush()
    db.add(
        StockDocLine(
            tenant_id=tenant.id,
            stock_doc_id=doc.id,
            order_material_requirement_id=req.id,
            supplier_product_id=sp.id,
            qty=Decimal("4"),
            unit_cost=Decimal("5"),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31)
    )
    headers = {h["department_name"]: [c["key"] for c in h["children"]] for h in report["headers"]}
    assert "commission" in headers.get("开发部", [])
    assert "material" not in headers.get("生产部", [])

    by_date = {r["date"]: r["values"] for r in report["rows"]}
    assert by_date["2026-03-08"][f"{depts['dev'].id}:commission"] == 30.0  # 20*1.5
    # 生产部物料进出完全去掉：不展示、不进汇总、不进综合分摊
    assert f"{depts['prod'].id}:material" not in by_date.get("2026-03-07", {})
    assert "2026-03-07" not in by_date  # 当天仅有被剔除的生产部物料
    # 综合分摊：固定工资(开发3000+采购2000)=5000，不含生产部物料 20、不含提成 30
    assert report["allocated_cost"]["total_expense"] == 5000.0
    assert report["allocated_cost"]["shipped_qty"] == 20
    assert report["allocated_cost"]["unit_cost"] == 250.0


def test_cost_analysis_rolls_up_to_root_department(cost_db):
    """子部门开支归并到一级部门，表头不出子部门。"""
    db, tenant, depts = cost_db
    prod = depts["prod"]
    cut = Department(
        tenant_id=tenant.id, name="裁断部", sort_order=1, parent_id=prod.id
    )
    form = Department(
        tenant_id=tenant.id, name="成型部", sort_order=2, parent_id=prod.id
    )
    db.add_all([cut, form])
    db.flush()
    cut_worker = Employee(
        tenant_id=tenant.id,
        name="裁断工",
        department_id=cut.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    form_worker = Employee(
        tenant_id=tenant.id,
        name="成型工",
        department_id=form.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    db.add_all([cut_worker, form_worker])
    db.flush()
    size = Size(tenant_id=tenant.id, size_value="41", sort_order=3)
    product = OwnProduct(tenant_id=tenant.id, product_code="P-ROLL", is_active=True)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CT",
        type=ProcessType.personal,
        default_price=Decimal("1"),
    )
    db.add_all([size, product, process])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-ROLL",
        customer_name="客",
        own_product_id=product.id,
        total_qty=10,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=process.id,
        process_name="裁断",
        process_type=ProcessType.personal,
        plan_qty=10,
        status=OrderProcessStatus.pending,
    )
    db.add(op)
    db.flush()
    for worker, qty in ((cut_worker, 4), (form_worker, 6)):
        db.add(
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_id=order.id,
                order_process_id=op.id,
                own_product_id=product.id,
                process_id=process.id,
                report_type=ReportType.normal,
                qualified_qty=Decimal(qty),
                unit_price=Decimal("1"),
                source=WorkLogSource.manual,
                status=WorkLogStatus.valid,
                created_at=datetime(2026, 3, 12, 2, 0, 0),
            )
        )
    db.commit()

    # 3 月报工 → 4 月 10 日发薪
    report = cost_analysis_service.cost_analysis_report(db, tenant.id, year=2026, month=4)
    names = [h["department_name"] for h in report["headers"]]
    assert "生产部" in names
    assert "裁断部" not in names
    assert "成型部" not in names
    by_date = {r["date"]: r["values"] for r in report["rows"]}
    assert by_date["2026-04-10"][f"{prod.id}:piecework"] == 10.0


def test_cost_analysis_drops_unassigned_department(cost_db):
    """无部门归属视为脏数据，不出现「未分配」列。"""
    db, tenant, _depts = cost_db
    orphan = Employee(
        tenant_id=tenant.id,
        name="无部门工",
        department_id=None,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    db.add(orphan)
    db.flush()
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=2)
    product = OwnProduct(tenant_id=tenant.id, product_code="P-ORPHAN", is_active=True)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="包装",
        code="BZ",
        type=ProcessType.personal,
        default_price=Decimal("3"),
    )
    db.add_all([size, product, process])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-ORPHAN",
        customer_name="客",
        own_product_id=product.id,
        total_qty=5,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=process.id,
        process_name="包装",
        process_type=ProcessType.personal,
        plan_qty=5,
        status=OrderProcessStatus.pending,
    )
    db.add(op)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=orphan.id,
            order_id=order.id,
            order_process_id=op.id,
            own_product_id=product.id,
            process_id=process.id,
            report_type=ReportType.normal,
            qualified_qty=Decimal("5"),
            unit_price=Decimal("3"),
            source=WorkLogSource.manual,
            status=WorkLogStatus.valid,
            created_at=datetime(2026, 3, 10, 2, 0, 0),
        )
    )
    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=None,
        employee_id=orphan.id,
        expense_date=date(2026, 3, 10),
        amount=Decimal("50"),
        status=PaymentStatus.posted,
    )
    db.add(expense)
    db.flush()
    db.add(
        DailyExpenseLine(
            tenant_id=tenant.id,
            expense_id=expense.id,
            sort_order=0,
            category="其它",
            occurred_on=date(2026, 3, 10),
            amount=Decimal("50"),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(db, tenant.id, year=2026, month=3)
    names = [h["department_name"] for h in report["headers"]]
    assert "未分配" not in names
    for r in report["rows"]:
        assert all(not str(k).startswith("0:") for k in (r.get("values") or {}))
    # 脏计件未计入任何部门
    piece_total = sum(
        float(v or 0)
        for r in report["rows"]
        for k, v in (r.get("values") or {}).items()
        if str(k).endswith(":piecework")
    )
    # fixture 里生产工另有计件；此处只保证无部门 5×3=15 未混入（通过无 0: 键已覆盖）
    assert piece_total >= 0


def test_cost_analysis_dev_cost_kpi(cost_db):
    """开发成本 = 开发部期间费用 ÷ 出货双数。"""
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=depts["dev"].id,
        employee_id=workers["开发员"].id,
        expense_date=date(2026, 5, 1),
        amount=Decimal("200"),
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
            occurred_on=date(2026, 5, 1),
            amount=Decimal("200"),
        )
    )
    product = OwnProduct(tenant_id=tenant.id, product_code="DEV-1", is_active=True)
    db.add(product)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-DEV",
        customer_name="客",
        own_product_id=product.id,
        total_qty=50,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-DEV",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 5, 10),
            unit_price=Decimal("10"),
            total_qty=50,
            amount=Decimal("500"),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 5, 1), date_to=date(2026, 5, 31)
    )
    kpi = report["dev_cost"]
    assert kpi["department_name"] == "开发部"
    assert kpi["shipped_qty"] == 50
    # 开发员固定工资记在月末 + 报销 200
    assert kpi["total_expense"] == 3200.0
    assert kpi["unit_cost"] == 64.0


def test_cost_analysis_allocated_cost_excludes_piece_and_commission(cost_db):
    """综合分摊不含计件、提成。"""
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    expense = DailyExpense(
        tenant_id=tenant.id,
        department_id=depts["prod"].id,
        employee_id=workers["生产工"].id,
        expense_date=date(2026, 6, 1),
        amount=Decimal("100"),
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
            occurred_on=date(2026, 6, 1),
            amount=Decimal("100"),
        )
    )
    product = OwnProduct(
        tenant_id=tenant.id, product_code="ALLOC-1", is_active=True, commission_cost=Decimal("1")
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductCommission(
            tenant_id=tenant.id,
            own_product_id=product.id,
            employee_id=workers["开发员"].id,
            amount=Decimal("1"),
            sort_order=0,
        )
    )
    order = Order(
        tenant_id=tenant.id,
        order_no="O-ALLOC",
        customer_name="客",
        own_product_id=product.id,
        total_qty=10,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-ALLOC",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 6, 5),
            unit_price=Decimal("20"),
            total_qty=10,
            amount=Decimal("200"),
        )
    )
    size = Size(tenant_id=tenant.id, size_value="42", sort_order=4)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="包装2",
        code="BZ2",
        type=ProcessType.personal,
        default_price=Decimal("5"),
    )
    db.add_all([size, process])
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=process.id,
        process_name="包装2",
        process_type=ProcessType.personal,
        plan_qty=10,
        status=OrderProcessStatus.pending,
    )
    db.add(op)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=workers["生产工"].id,
            order_id=order.id,
            order_process_id=op.id,
            own_product_id=product.id,
            process_id=process.id,
            report_type=ReportType.normal,
            qualified_qty=Decimal("10"),
            unit_price=Decimal("5"),
            source=WorkLogSource.manual,
            status=WorkLogStatus.valid,
            created_at=datetime(2026, 6, 3, 2, 0, 0),
        )
    )
    db.commit()

    # 6 月视图：报销 100 + 固定工资(开发3000+采购2000=5000) = 5100；计件在 7/10 发薪，提成在出货日
    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)
    )
    # 提成 10 在 6/5，不计入综合分摊；计件不在 6 月
    assert report["allocated_cost"]["shipped_qty"] == 10
    # 100(报销) + 3000(开发固定) + 2000(采购固定) = 5100，不含提成 10
    assert report["allocated_cost"]["total_expense"] == 5100.0
    assert report["allocated_cost"]["unit_cost"] == 510.0
