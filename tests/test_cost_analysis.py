"""综合成本分析：按部门×按日，空列不输出二级表头。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AccountStatement,
    AccountStatementStatus,
    DailyExpense,
    DailyExpenseLine,
    Department,
    Employee,
    OwnProduct,
    OwnProductCommission,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PaymentStatus,
    SalaryModel,
    SettlementDirection,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    Shipment,
    ShipmentStatus,
    Size,
    SupplierProduct,
    Tenant,
    ToolingItem,
    ToolingReceipt,
    ToolingReceiptLine,
    ToolingReceiptSize,
    Order,
    OrderStatus,
    SampleRemake,
    SampleRemakeLine,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
)
from app.services import cost_analysis_service


def _header_map(report: dict) -> dict[str, list[dict]]:
    return {h["department_name"]: h["children"] for h in report["headers"]}


def _keys(children: list[dict]) -> list[str]:
    assert all("children" not in child for child in children)
    return [child["key"] for child in children]


def _add_expense(db, tenant_id, department_id, employee_id, day, lines):
    amount = sum((Decimal(str(amt)) for _cat, amt in lines), Decimal("0"))
    expense = DailyExpense(
        tenant_id=tenant_id,
        department_id=department_id,
        employee_id=employee_id,
        expense_date=day,
        amount=amount,
        status=PaymentStatus.posted,
    )
    db.add(expense)
    db.flush()
    for idx, (category, amt) in enumerate(lines):
        db.add(
            DailyExpenseLine(
                tenant_id=tenant_id,
                expense_id=expense.id,
                sort_order=idx,
                category=category,
                occurred_on=day,
                amount=Decimal(str(amt)),
            )
        )
    return expense


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
    # 报销：仅开发部有其它开支，按报销类型出列
    _add_expense(
        db,
        tenant.id,
        depts["dev"].id,
        workers["开发员"].id,
        date(2026, 3, 5),
        [("办公", "100")],
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, year=2026, month=3
    )
    headers = _header_map(report)
    # 采购部仅有固定工资，无报销 → 不出现其它开支
    assert "采购部" in headers
    assert [c["key"] for c in headers["采购部"]] == ["fixed_salary"]
    # 开发部：固定工资 + 其它开支（报销类型），无提成/计件
    assert "开发部" in headers
    assert _keys(headers["开发部"]) == ["fixed_salary", "办公"]
    assert "commission" not in _keys(headers["开发部"])
    assert "piecework" not in _keys(headers["开发部"])
    assert "生产部" not in headers

    dates = {r["date"] for r in report["rows"]}
    assert "2026-03-05" in dates
    by_date = {r["date"]: r["values"] for r in report["rows"]}
    assert by_date["2026-03-05"][f"{depts['dev'].id}:办公"] == 100.0


def test_cost_analysis_splits_other_by_expense_category(cost_db):
    """其它开支按报销类型分列：旧编码并入中文名，自定义类型排在「其它」前。"""
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    _add_expense(
        db,
        tenant.id,
        depts["dev"].id,
        workers["开发员"].id,
        date(2026, 4, 2),
        [
            ("其它", "8"),
            ("打样费", "30"),
            ("meals", "12"),
            ("餐饮费", "3"),
            ("交通费", "20"),
        ],
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 4, 1), date_to=date(2026, 4, 30)
    )
    labels = [c["label"] for c in _header_map(report)["开发部"] if c["key"] != "fixed_salary"]
    assert labels == ["交通费", "餐饮费", "打样费", "其它"]
    values = {r["date"]: r["values"] for r in report["rows"]}["2026-04-02"]
    assert values[f"{depts['dev'].id}:交通费"] == 20.0
    assert values[f"{depts['dev'].id}:餐饮费"] == 15.0  # meals 12 + 餐饮费 3
    assert values[f"{depts['dev'].id}:打样费"] == 30.0
    assert values[f"{depts['dev'].id}:其它"] == 8.0


def test_cost_analysis_commission_day(cost_db):
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
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31)
    )
    headers = _header_map(report)
    flat = {key for cols in headers.values() for key in _keys(cols)}
    assert "commission" not in flat
    assert "piecework" not in flat
    assert "2026-03-08" not in {r["date"] for r in report["rows"]}
    # 综合分摊：固定工资(开发3000+采购2000)=5000，不含提成 30
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
    _add_expense(
        db, tenant.id, cut.id, cut_worker.id, date(2026, 3, 12), [("交通费", "40")]
    )
    _add_expense(
        db,
        tenant.id,
        form.id,
        form_worker.id,
        date(2026, 3, 12),
        [("交通费", "60"), ("餐饮费", "15")],
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(db, tenant.id, year=2026, month=3)
    names = [h["department_name"] for h in report["headers"]]
    assert "生产部" in names
    assert "裁断部" not in names
    assert "成型部" not in names
    headers = _header_map(report)
    assert _keys(headers["生产部"]) == ["交通费", "餐饮费"]
    by_date = {r["date"]: r["values"] for r in report["rows"]}
    assert by_date["2026-03-12"][f"{prod.id}:交通费"] == 100.0
    assert by_date["2026-03-12"][f"{prod.id}:餐饮费"] == 15.0


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
    _add_expense(db, tenant.id, None, orphan.id, date(2026, 3, 10), [("其它", "50")])
    db.commit()

    report = cost_analysis_service.cost_analysis_report(db, tenant.id, year=2026, month=3)
    names = [h["department_name"] for h in report["headers"]]
    assert "未分配" not in names
    flat = {key for cols in _header_map(report).values() for key in _keys(cols)}
    assert "其它" not in flat
    assert "piecework" not in flat
    for r in report["rows"]:
        assert all(not str(k).startswith("0:") for k in (r.get("values") or {}))
        assert all(float(v or 0) != 50 for v in (r.get("values") or {}).values())


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
    db.commit()

    # 6 月视图：报销 100 + 固定工资(开发3000+采购2000=5000) = 5100；不计件、提成
    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)
    )
    flat = {key for cols in _header_map(report).values() for key in _keys(cols)}
    assert "办公" in flat
    assert "commission" not in flat
    assert "piecework" not in flat
    assert report["allocated_cost"]["shipped_qty"] == 10
    # 100(报销) + 3000(开发固定) + 2000(采购固定) = 5100，不含提成 10
    assert report["allocated_cost"]["total_expense"] == 5100.0
    assert report["allocated_cost"]["unit_cost"] == 510.0


def test_cost_analysis_counts_signed_dev_pickups(cost_db):
    """已确认的仓库开发部领料按出库均价记入开发部，待确认和生产领主料不计。"""
    db, tenant, depts = cost_db
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    cloth = SupplierProduct(
        tenant_id=tenant.id,
        product_code="CLOTH",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("9"),
        is_active=True,
    )
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("8"),
        is_active=True,
    )
    db.add_all([cloth, sole])
    db.flush()
    db.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=sole.id,
            qty=Decimal("5"),
            avg_unit_cost=Decimal("3"),
        )
    )
    signed = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="DV-1",
        kind=WarehousePickupKind.dev,
        status=WarehousePickupStatus.signed,
        signed_at=datetime(2026, 3, 5, 1, 0, 0),
    )
    pending = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="DV-2",
        kind=WarehousePickupKind.dev,
        status=WarehousePickupStatus.pending,
        signed_at=datetime(2026, 3, 5, 1, 0, 0),
    )
    production = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="PD-1",
        kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed,
        signed_at=datetime(2026, 3, 5, 1, 0, 0),
    )
    db.add_all([signed, pending, production])
    db.flush()
    db.add_all(
        [
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=signed.id,
                supplier_product_id=cloth.id,
                material_name="面料",
                qty=Decimal("4"),
            ),
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=signed.id,
                supplier_product_id=sole.id,
                material_name="大底",
                qty=Decimal("2"),
            ),
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=pending.id,
                supplier_product_id=cloth.id,
                material_name="面料",
                qty=Decimal("10"),
            ),
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=production.id,
                supplier_product_id=cloth.id,
                material_name="面料",
                qty=Decimal("10"),
            ),
        ]
    )
    db.add(
        SharedMaterialLedger(
            tenant_id=tenant.id,
            supplier_product_id=cloth.id,
            ledger_type=SharedLedgerType.dev_issue,
            qty_delta=Decimal("-4"),
            unit_cost=Decimal("2.5"),
            balance_after=Decimal("0"),
            ref_type="warehouse_pickup",
            ref_id=signed.id,
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 3, 5), date_to=date(2026, 3, 5)
    )
    headers = _header_map(report)
    assert _keys(headers["开发部"]) == ["仓库领料"]
    assert "仓库领料" not in _keys(headers.get("采购部", []))
    values = {r["date"]: r["values"] for r in report["rows"]}["2026-03-05"]
    # 面料 4×2.5（流水均价）+ 大底 2×3（库存均价，无流水单价）
    assert values[f"{depts['dev'].id}:仓库领料"] == 16.0
    assert report["dev_cost"]["total_expense"] == 16.0
    assert report["allocated_cost"]["total_expense"] == 16.0


def test_cost_analysis_counts_signed_aux_pickups_on_production(cost_db):
    """已确认的生产领辅料耗材按出库均价记入生产部辅料耗材，不进开发部。"""
    db, tenant, depts = cost_db
    partner = Partner(tenant_id=tenant.id, name="辅料商", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    lace = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LACE",
        name="鞋带",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    db.add(lace)
    db.flush()
    signed = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="AX-1",
        kind=WarehousePickupKind.aux,
        status=WarehousePickupStatus.signed,
        signed_at=datetime(2026, 4, 2, 1, 0, 0),
    )
    db.add(signed)
    db.flush()
    db.add(
        WarehousePickupLine(
            tenant_id=tenant.id,
            pickup_id=signed.id,
            supplier_product_id=lace.id,
            material_name="鞋带",
            qty=Decimal("6"),
        )
    )
    db.add(
        SharedMaterialLedger(
            tenant_id=tenant.id,
            supplier_product_id=lace.id,
            ledger_type=SharedLedgerType.aux_issue,
            qty_delta=Decimal("-6"),
            unit_cost=Decimal("0.5"),
            balance_after=Decimal("0"),
            ref_type="warehouse_pickup",
            ref_id=signed.id,
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 4, 2), date_to=date(2026, 4, 2)
    )
    headers = _header_map(report)
    assert _keys(headers["生产部"]) == ["辅料耗材"]
    assert "开发部" not in headers
    values = {r["date"]: r["values"] for r in report["rows"]}["2026-04-02"]
    assert values[f"{depts['prod'].id}:辅料耗材"] == 3.0
    assert report["dev_cost"]["total_expense"] == 0.0
    assert report["allocated_cost"]["total_expense"] == 3.0
    assert report["aux_material_cost"]["total_expense"] == 3.0
    assert report["aux_material_cost"]["unit_cost"] is None


def test_cost_analysis_aux_share_nets_returns_and_divides_by_shipped_qty(cost_db):
    """辅料耗材分摊 =（生产领料 − 生产退料）÷ 出货双数。"""
    db, tenant, depts = cost_db
    partner = Partner(tenant_id=tenant.id, name="辅料商", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    lace = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LACE-R",
        name="鞋带",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    db.add(lace)
    db.flush()
    issued = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="AX-ISSUE",
        kind=WarehousePickupKind.aux,
        status=WarehousePickupStatus.signed,
        signed_at=datetime(2026, 9, 2, 1, 0, 0),
    )
    returned = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="AX-RET",
        kind=WarehousePickupKind.aux_return,
        status=WarehousePickupStatus.signed,
        signed_at=datetime(2026, 9, 3, 1, 0, 0),
    )
    db.add_all([issued, returned])
    db.flush()
    db.add_all(
        [
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=issued.id,
                supplier_product_id=lace.id,
                material_name="鞋带",
                qty=Decimal("10"),
            ),
            WarehousePickupLine(
                tenant_id=tenant.id,
                pickup_id=returned.id,
                supplier_product_id=lace.id,
                material_name="鞋带",
                qty=Decimal("4"),
            ),
        ]
    )
    db.add_all(
        [
            SharedMaterialLedger(
                tenant_id=tenant.id,
                supplier_product_id=lace.id,
                ledger_type=SharedLedgerType.aux_issue,
                qty_delta=Decimal("-10"),
                unit_cost=Decimal("2"),
                balance_after=Decimal("0"),
                ref_type="warehouse_pickup",
                ref_id=issued.id,
            ),
            SharedMaterialLedger(
                tenant_id=tenant.id,
                supplier_product_id=lace.id,
                ledger_type=SharedLedgerType.aux_return,
                qty_delta=Decimal("4"),
                unit_cost=Decimal("2"),
                balance_after=Decimal("4"),
                ref_type="warehouse_pickup",
                ref_id=returned.id,
            ),
        ]
    )
    product = OwnProduct(tenant_id=tenant.id, product_code="AUX-SHARE", is_active=True)
    db.add(product)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-AUX",
        customer_name="客",
        own_product_id=product.id,
        total_qty=8,
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-AUX",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 9, 10),
            unit_price=Decimal("10"),
            total_qty=8,
            amount=Decimal("80"),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )
    values = {r["date"]: r["values"] for r in report["rows"]}
    assert values["2026-09-02"][f"{depts['prod'].id}:辅料耗材"] == 20.0
    assert values["2026-09-03"][f"{depts['prod'].id}:辅料耗材"] == -8.0
    assert report["aux_material_cost"]["total_expense"] == 12.0
    assert report["aux_material_cost"]["shipped_qty"] == 8
    assert report["aux_material_cost"]["unit_cost"] == 1.5
    # 固定工资 5000 + 辅料耗材净额 12
    assert report["allocated_cost"]["total_expense"] == 5012.0


def test_cost_analysis_share_kpis_divide_by_shipped_qty(cost_db):
    """房租、水电、固定工资按总额 ÷ 出货双数。"""
    db, tenant, depts = cost_db
    workers = {
        e.name: e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
    }
    _add_expense(
        db,
        tenant.id,
        depts["purchase"].id,
        workers["采购员"].id,
        date(2026, 8, 2),
        [("房租", "1000"), ("水电", "250")],
    )
    product = OwnProduct(tenant_id=tenant.id, product_code="SHARE-1", is_active=True)
    db.add(product)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="O-SHARE",
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
            shipment_no="SH-SHARE",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 8, 10),
            unit_price=Decimal("10"),
            total_qty=20,
            amount=Decimal("200"),
        )
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)
    )
    assert report["rent_cost"]["total_expense"] == 1000.0
    assert report["rent_cost"]["unit_cost"] == 50.0
    assert report["utility_cost"]["total_expense"] == 250.0
    assert report["utility_cost"]["unit_cost"] == 12.5
    # 开发 3000 + 采购 2000
    assert report["fixed_salary_cost"]["total_expense"] == 5000.0
    assert report["fixed_salary_cost"]["shipped_qty"] == 20
    assert report["fixed_salary_cost"]["unit_cost"] == 250.0
    assert report["aux_material_cost"]["total_expense"] == 0.0
    assert report["aux_material_cost"]["shipped_qty"] == 20
    assert report["aux_material_cost"]["unit_cost"] == 0.0


def test_cost_analysis_counts_sample_remakes_as_negative_dev_cost(cost_db):
    """复版进账记入开发部，金额为负，并冲减开发成本与综合分摊。"""
    db, tenant, depts = cost_db
    worker = next(
        e
        for e in db.query(Employee).filter(Employee.tenant_id == tenant.id).all()
        if e.name == "开发员"
    )
    _add_expense(
        db,
        tenant.id,
        depts["dev"].id,
        worker.id,
        date(2026, 5, 8),
        [("鞋样品", "20")],
    )
    customer = Partner(tenant_id=tenant.id, name="样品客户", is_customer=True)
    db.add(customer)
    db.flush()
    remake = SampleRemake(
        tenant_id=tenant.id,
        remake_date=date(2026, 5, 8),
        delivery_no="FY-0508",
        customer_id=customer.id,
        customer_name=customer.name,
    )
    outside = SampleRemake(
        tenant_id=tenant.id,
        remake_date=date(2026, 4, 1),
        delivery_no="FY-0401",
        customer_id=customer.id,
        customer_name=customer.name,
    )
    db.add_all([remake, outside])
    db.flush()
    db.add_all(
        [
            SampleRemakeLine(
                tenant_id=tenant.id,
                remake_id=remake.id,
                sort_order=0,
                qty=3,
                unit_price=Decimal("10"),
            ),
            SampleRemakeLine(
                tenant_id=tenant.id,
                remake_id=remake.id,
                sort_order=1,
                qty=2,
                unit_price=Decimal("7.5"),
            ),
            SampleRemakeLine(
                tenant_id=tenant.id,
                remake_id=outside.id,
                sort_order=0,
                qty=9,
                unit_price=Decimal("100"),
            ),
        ]
    )
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 5, 8), date_to=date(2026, 5, 8)
    )
    headers = _header_map(report)
    assert _keys(headers["开发部"]) == ["鞋样资讯", "复版收费"]
    assert "复版收费" not in _keys(headers.get("采购部", []))
    values = {r["date"]: r["values"] for r in report["rows"]}["2026-05-08"]
    assert values[f"{depts['dev'].id}:复版收费"] == -45.0
    assert report["dev_cost"]["total_expense"] == -25.0
    assert report["allocated_cost"]["total_expense"] == -25.0


def test_cost_analysis_books_statemented_molds_to_dev(cost_db):
    """对账后的底模、楦头、其它模具按对账日记入开发部；刀模和未对账不记。"""
    db, tenant, depts = cost_db
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True, is_active=True)
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    db.add_all([supplier, size])
    db.flush()

    def statement(no: str, day: date, status=AccountStatementStatus.confirmed) -> AccountStatement:
        row = AccountStatement(
            tenant_id=tenant.id,
            statement_no=no,
            partner_id=supplier.id,
            partner_name=supplier.name,
            direction=SettlementDirection.supplier,
            period_start=day,
            period_end=day,
            statement_date=day,
            due_date=day,
            status=status,
            statement_kind="purchase",
        )
        db.add(row)
        db.flush()
        return row

    june = statement("ST-MOLD-6", date(2026, 6, 15))
    april = statement("ST-MOLD-4", date(2026, 4, 2))
    voided = statement("ST-MOLD-V", date(2026, 6, 15), AccountStatementStatus.void)

    def book(kind: str, code: str, amount: str, department_id: int, stmt: AccountStatement | None):
        item = ToolingItem(tenant_id=tenant.id, code=code, kind=kind, is_active=True)
        db.add(item)
        db.flush()
        payable = Payable(
            tenant_id=tenant.id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            payable_date=date(2026, 4, 1),
            due_date=date(2026, 4, 1),
            amount=Decimal(amount),
            status=PayableStatus.open,
        )
        db.add(payable)
        db.flush()
        receipt = ToolingReceipt(
            tenant_id=tenant.id,
            receipt_no=f"XT-{code}",
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            receipt_date=date(2026, 4, 1),
            payable_id=payable.id,
        )
        db.add(receipt)
        db.flush()
        line = ToolingReceiptLine(
            tenant_id=tenant.id,
            receipt_id=receipt.id,
            department_id=department_id,
            tooling_item_id=item.id,
            unit_price=Decimal(amount),
        )
        db.add(line)
        db.flush()
        size_row = ToolingReceiptSize(
            tenant_id=tenant.id,
            line_id=line.id,
            size_id=size.id,
            qty=1,
        )
        db.add(size_row)
        db.flush()
        db.add(
            PayableLine(
                tenant_id=tenant.id,
                payable_id=payable.id,
                source_type="tooling_receive",
                source_ref_id=size_row.id,
                qty=Decimal("1"),
                unit_price=Decimal(amount),
                amount=Decimal(amount),
                statement_id=stmt.id if stmt else None,
            )
        )

    book("sole_mold", "SOLE", "100", depts["dev"].id, june)
    book("shoe_last", "LAST", "30", depts["prod"].id, june)
    book("other_mold", "OTHER", "40", depts["dev"].id, june)
    book("knife_die", "KNIFE", "999", depts["prod"].id, june)
    book("shoe_last", "OPEN", "50", depts["dev"].id, None)
    book("sole_mold", "VOID", "70", depts["dev"].id, voided)
    book("shoe_last", "APRIL", "8", depts["dev"].id, april)
    db.commit()

    report = cost_analysis_service.cost_analysis_report(
        db, tenant.id, date_from=date(2026, 6, 15), date_to=date(2026, 6, 15)
    )
    headers = _header_map(report)
    assert _keys(headers["开发部"]) == ["底模", "楦头", "其它模具"]
    assert "生产部" not in headers
    values = {row["date"]: row["values"] for row in report["rows"]}["2026-06-15"]
    assert values[f"{depts['dev'].id}:底模"] == 100.0
    assert values[f"{depts['dev'].id}:楦头"] == 30.0
    assert values[f"{depts['dev'].id}:其它模具"] == 40.0
    assert report["dev_cost"]["total_expense"] == 170.0
