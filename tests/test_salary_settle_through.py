"""提前结算 settle_through：截断取数 + 固定类按日折算。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Department, Employee, OwnProduct, ProcessDefinition, ProcessType, SalaryModel, Tenant, WorkLog, WorkLogSource, WorkLogStatus, ReportType
from app.services.salary_service import (
    export_bank_payroll_csv,
    month_salary,
    resolve_settle_window,
    set_month_lock,
)


@pytest.fixture()
def settle_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="截断结算厂", settings_json={})
    session.add(tenant)
    session.flush()
    dept = Department(tenant_id=tenant.id, name="车间")
    session.add(dept)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="P1", is_active=True)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
    )
    session.add_all([product, process])
    session.flush()
    fixed = Employee(
        tenant_id=tenant.id,
        name="固定工",
        department_id=dept.id,
        salary_model=SalaryModel.fixed,
        base_salary=Decimal("3100"),
        is_active=True,
        bank_account="62220000",
        bank_name="工行",
        bank_account_name="固定工",
    )
    piece = Employee(
        tenant_id=tenant.id,
        name="计件工",
        department_id=dept.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
        bank_account="62220001",
        bank_name="工行",
        bank_account_name="计件工",
    )
    session.add_all([fixed, piece])
    session.commit()
    yield session, tenant, fixed, piece, product, process
    session.close()


def test_resolve_settle_window_proration():
    w = resolve_settle_window("2026-12", date(2026, 12, 25))
    assert w["period_days"] == 25
    assert w["days_in_month"] == 31
    assert w["is_partial"] is True
    assert float(w["proration"]) == pytest.approx(25 / 31, rel=1e-4)

    full = resolve_settle_window("2026-12", None)
    assert full["is_partial"] is False
    assert float(full["proration"]) == 1.0


def test_fixed_salary_prorated_by_settle_through(settle_db):
    db, tenant, fixed, _piece, _product, _process = settle_db
    detail = month_salary(
        db, tenant.id, fixed.id, "2026-12", settle_through=date(2026, 12, 25)
    )
    # 先按 0.0001 折算系数，再算金额：3100 * round(25/31, 4)
    proration = (Decimal("25") / Decimal("31")).quantize(Decimal("0.0001"))
    expected = (Decimal("3100") * proration).quantize(Decimal("0.01"))
    assert detail["base_salary"] == pytest.approx(float(expected))
    assert detail["total_wage"] == pytest.approx(float(expected))
    assert detail["settle_through"] == "2026-12-25"
    assert "截至2026-12-25" in detail["settle_note"]


def test_piecework_cutoff_excludes_later_logs(settle_db):
    db, tenant, _fixed, piece, product, process = settle_db
    # 本地 12/20 与 12/28（UTC = 本地 - 8h）；order_process_id 仅占位，结算不读订单工序。
    early = WorkLog(
        tenant_id=tenant.id,
        worker_id=piece.id,
        order_process_id=1,
        own_product_id=product.id,
        process_id=process.id,
        qualified_qty=10,
        unit_price=Decimal("2"),
        report_type=ReportType.normal,
        status=WorkLogStatus.valid,
        source=WorkLogSource.manual,
        created_at=datetime(2026, 12, 19, 16, 0, 0),  # 本地 12/20 00:00
    )
    late = WorkLog(
        tenant_id=tenant.id,
        worker_id=piece.id,
        order_process_id=1,
        own_product_id=product.id,
        process_id=process.id,
        qualified_qty=10,
        unit_price=Decimal("2"),
        report_type=ReportType.normal,
        status=WorkLogStatus.valid,
        source=WorkLogSource.manual,
        created_at=datetime(2026, 12, 27, 16, 0, 0),  # 本地 12/28 00:00
    )
    db.add_all([early, late])
    db.commit()

    full = month_salary(db, tenant.id, piece.id, "2026-12")
    assert full["total_piece_wage"] == pytest.approx(40)

    cut = month_salary(
        db, tenant.id, piece.id, "2026-12", settle_through=date(2026, 12, 25)
    )
    assert cut["total_piece_wage"] == pytest.approx(20)
    assert cut["total_wage"] == pytest.approx(20)


def test_lock_persists_settle_through_and_bank_remark(settle_db):
    db, tenant, fixed, _piece, _product, _process = settle_db
    lock = set_month_lock(
        db,
        tenant.id,
        "2026-12",
        locked=True,
        locked_by=fixed.id,
        settle_through=date(2026, 12, 25),
    )
    assert lock["settle_through"] == "2026-12-25"
    assert lock["is_locked"] is True

    # 锁定后不传参数也应截断
    detail = month_salary(db, tenant.id, fixed.id, "2026-12")
    assert detail["settle_through"] == "2026-12-25"

    csv_text = export_bank_payroll_csv(db, tenant.id, "2026-12")
    assert "截至12-25" in csv_text
    assert "2026-12-25发" in csv_text

    unlocked = set_month_lock(db, tenant.id, "2026-12", locked=False)
    assert unlocked["settle_through"] is None
