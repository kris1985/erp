"""总账经营流水：现金口径（收款/付款登记）与汇总分页。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    BusinessLedgerEntry,
    DailyExpense,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Payable,
    PayableStatus,
    Shipment,
    ShipmentStatus,
    SupplierPayment,
    Tenant,
)
from app.services import ledger_service


@pytest.fixture()
def ledger_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="总账厂", settings_json={})
    session.add(tenant)
    session.commit()
    yield session, tenant
    session.close()


def test_ledger_cash_basis_signs_and_void(ledger_db):
    db, tenant = ledger_db
    # 出货/挂账即使写入也不应作为业务主路径；现金口径以收付款为准
    ledger_service.post_payment(
        db,
        tenant.id,
        payment_id=2,
        customer_name="客户甲",
        amount=Decimal("600"),
        payment_date=date(2026, 5, 9),
        fund_account="bank",
        voucher_no="SK1",
    )
    ledger_service.post_supplier_payment(
        db,
        tenant.id,
        payment_id=3,
        supplier_name="供应商乙",
        amount=Decimal("200"),
        payment_date=date(2026, 5, 10),
        fund_account="bank",
        voucher_no="FK1",
    )
    ledger_service.post_daily_expense(
        db,
        tenant.id,
        expense_id=4,
        amount=Decimal("50"),
        expense_date=date(2026, 5, 11),
        reason="办公",
        employee_name="张三",
        fund_account="cash",
    )
    db.commit()

    listed = ledger_service.list_entries(db, tenant.id, status="posted")
    assert listed["summary"]["count"] == 3
    assert listed["summary"]["inflow"] == pytest.approx(600.0)
    assert listed["summary"]["piece"] == pytest.approx(0.0)
    assert listed["summary"]["outflow"] == pytest.approx(-250.0)
    assert listed["summary"]["net"] == pytest.approx(350.0)
    assert listed["summary"]["balance"] == pytest.approx(350.0)

    pay_row = next(i for i in listed["items"] if i["biz_type"] == "payment")
    assert pay_row["amount_in"] == pytest.approx(600.0)
    assert "收款登记" in pay_row["biz_type_label"]

    ledger_service.void_payment_entry(db, tenant.id, 2)
    db.commit()
    posted = ledger_service.list_entries(db, tenant.id, status="posted")
    assert posted["summary"]["count"] == 2
    assert all(i["biz_type"] != "payment" for i in posted["items"])

    csv_text = ledger_service.export_csv(db, tenant.id, include_void=True)
    assert "进帐金额" in csv_text
    assert "计件/提成" in csv_text
    assert "账户" not in csv_text.split("\n")[0]


def test_salary_month_entry_upsert(ledger_db):
    db, tenant = ledger_db
    ledger_service.post_salary_month(
        db,
        tenant.id,
        lock_id=9,
        year_month="2026-05",
        total_wage=Decimal("8888.50"),
        settle_through=date(2026, 5, 31),
        worker_count=3,
    )
    db.commit()
    listed = ledger_service.list_entries(db, tenant.id)
    assert listed["items"][0]["amount"] == pytest.approx(-8888.50)
    assert listed["items"][0]["amount_piece"] == pytest.approx(8888.50)
    assert listed["items"][0]["amount_out"] == 0
    assert listed["items"][0]["biz_type"] == "salary"
    assert listed["summary"]["piece"] == pytest.approx(8888.50)

    ledger_service.void_salary_month_entry(db, tenant.id, 9)
    db.commit()
    assert ledger_service.list_entries(db, tenant.id)["summary"]["count"] == 0

    ledger_service.post_salary_month(
        db,
        tenant.id,
        lock_id=9,
        year_month="2026-05",
        total_wage=Decimal("9000"),
        settle_through=date(2026, 5, 31),
        worker_count=3,
    )
    db.commit()
    listed = ledger_service.list_entries(db, tenant.id)
    assert listed["summary"]["count"] == 1
    assert listed["items"][0]["amount"] == pytest.approx(-9000.0)


def test_backfill_skips_accrual_uses_cash(ledger_db):
    db, tenant = ledger_db
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no="SH-BF-1",
            customer_name="回填客户",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 6, 1),
            unit_price=Decimal("10"),
            total_qty=5,
            amount=Decimal("50"),
        )
    )
    db.add(
        Payable(
            tenant_id=tenant.id,
            supplier_name="回填供应商",
            payable_date=date(2026, 6, 2),
            due_date=date(2026, 7, 2),
            amount=Decimal("30"),
            status=PayableStatus.open,
        )
    )
    db.add(
        Payment(
            tenant_id=tenant.id,
            customer_name="回填客户",
            amount=Decimal("40"),
            payment_date=date(2026, 6, 4),
            method=PaymentMethod.bank,
            status=PaymentStatus.posted,
            voucher_no="SK-BF",
        )
    )
    db.add(
        SupplierPayment(
            tenant_id=tenant.id,
            supplier_name="回填供应商",
            amount=Decimal("15"),
            payment_date=date(2026, 6, 5),
            method=PaymentMethod.cash,
            status=PaymentStatus.posted,
            voucher_no="FK-BF",
        )
    )
    db.add(
        DailyExpense(
            tenant_id=tenant.id,
            reason="回填开支",
            expense_date=date(2026, 6, 3),
            amount=Decimal("8"),
            fund_account="cash",
            status=PaymentStatus.posted,
        )
    )
    # 模拟历史错误入账的出货流水
    ledger_service.post_shipment(
        db,
        tenant.id,
        shipment_id=999,
        shipment_no="SH-OLD",
        customer_name="旧",
        amount=Decimal("99"),
        ship_date=date(2026, 1, 1),
    )
    db.commit()

    counts = ledger_service.backfill_tenant(db, tenant.id)
    db.commit()
    assert counts["voided_accrual"] >= 1
    assert counts["payment"] == 1
    assert counts["supplier_payment"] == 1
    assert counts["daily_expense"] == 1

    listed = ledger_service.list_entries(db, tenant.id)
    assert listed["summary"]["count"] == 3
    assert listed["summary"]["inflow"] == pytest.approx(40.0)
    assert listed["summary"]["outflow"] == pytest.approx(-23.0)
    assert listed["summary"]["net"] == pytest.approx(17.0)
    assert all(i["biz_type"] in ledger_service.CASH_BIZ_TYPES for i in listed["items"])

    paged = ledger_service.list_entries(db, tenant.id, page=1, page_size=2)
    assert paged["total"] == 3
    assert len(paged["items"]) == 2
    assert paged["summary"]["net"] == pytest.approx(17.0)

    # 幂等
    counts2 = ledger_service.backfill_tenant(db, tenant.id)
    db.commit()
    assert counts2["payment"] == 1
    posted_n = len(
        db.scalars(
            select(BusinessLedgerEntry).where(
                BusinessLedgerEntry.tenant_id == tenant.id,
                BusinessLedgerEntry.status == "posted",
            )
        ).all()
    )
    assert posted_n == 3
