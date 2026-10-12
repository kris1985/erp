"""复版记录进入客户待结算，对账后锁定，作废对账单后恢复。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Employee, Partner, Tenant
from app.services.finance_service import FinanceError
from app.services.sample_remake_service import create_remake, delete_remake, update_remake
from app.services.sales_settlement_service import (
    generate_sales_statement,
    list_pending_lines,
    pending_amount,
    void_sales_statement,
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_sample_remake_pending_locks_until_statement_void():
    db = _db()
    tenant = Tenant(name="复版对账厂")
    db.add(tenant)
    db.flush()
    admin = Employee(tenant_id=tenant.id, name="管理员", username="admin", is_active=True)
    customer = Partner(tenant_id=tenant.id, name="华东客户", is_customer=True, is_active=True)
    db.add_all([admin, customer])
    db.commit()

    created = create_remake(
        db,
        tenant.id,
        remake_date=date(2026, 9, 28),
        delivery_no="FB-LOCK-1",
        courier_company="顺丰",
        tracking_no="SF001",
        customer_id=customer.id,
        lines=[
            {"brand": "甲牌", "factory_model": "TYL-1001", "color": "黑", "qty": 2, "unit_price": 12.5},
            {"brand": "乙牌", "factory_model": "手填型号", "color": "白", "qty": 1, "unit_price": 8},
            {"brand": "零", "factory_model": "赠品", "color": "红", "qty": 1, "unit_price": 0},
        ],
        created_by=admin.id,
    )
    assert created["statement_id"] is None

    rows = list_pending_lines(db, tenant.id, customer_id=customer.id)
    assert [row["factory_model"] for row in rows] == ["TYL-1001", "手填型号"]
    assert all(row["row_type"] == "sample_remake" for row in rows)
    assert all(row["delivery_no"] == "FB-LOCK-1" for row in rows)
    assert rows[0]["brand_name"] == "甲牌"
    assert rows[0]["qty"] == 2
    assert pending_amount(rows) == Decimal("33.0000")
    matched = list_pending_lines(db, tenant.id, shipment_no="FB-LOCK")
    assert len(matched) == 2

    statement = generate_sales_statement(
        db,
        tenant.id,
        customer_id=customer.id,
        sample_remake_ids=[created["id"]],
        statement_no="DZ-FB-1",
        statement_date=date(2026, 9, 28),
        user_id=admin.id,
    )
    assert Decimal(str(statement["current_amount"])) == Decimal("33.0000")
    remake_lines = [line for line in statement["lines"] if line["source_type"] == "sample_remake"]
    assert len(remake_lines) == 2
    assert remake_lines[0]["document_no"] == "FB-LOCK-1"
    assert remake_lines[0]["customer_items"][0]["delivery_no"] == "FB-LOCK-1"
    assert remake_lines[0]["shipment_items"][0]["shipment_no"] == "FB-LOCK-1"
    assert list_pending_lines(db, tenant.id, customer_id=customer.id) == []

    payload = dict(
        remake_date=date(2026, 9, 28),
        delivery_no="FB-LOCK-1",
        courier_company="顺丰",
        tracking_no="SF001",
        customer_id=customer.id,
        lines=[{"factory_model": "TYL-1001", "qty": 2, "unit_price": 12.5}],
    )
    try:
        update_remake(db, tenant.id, created["id"], **payload)
        raise AssertionError("已对账的复版记录不应能修改")
    except ValueError as err:
        assert str(err) == "already_statemented"
    try:
        delete_remake(db, tenant.id, created["id"])
        raise AssertionError("已对账的复版记录不应能删除")
    except ValueError as err:
        assert str(err) == "already_statemented"

    void_sales_statement(db, tenant.id, statement["id"])
    restored = list_pending_lines(db, tenant.id, customer_id=customer.id)
    assert pending_amount(restored) == Decimal("33.0000")
    updated = update_remake(db, tenant.id, created["id"], **payload)
    assert updated["statement_id"] is None
    assert updated["total_amount"] == 25


def test_sample_remake_statement_rejects_second_time():
    db = _db()
    tenant = Tenant(name="复版对账厂")
    db.add(tenant)
    db.flush()
    customer = Partner(tenant_id=tenant.id, name="华东客户", is_customer=True, is_active=True)
    db.add(customer)
    db.commit()
    created = create_remake(
        db,
        tenant.id,
        remake_date=date(2026, 9, 28),
        delivery_no=None,
        courier_company=None,
        tracking_no=None,
        customer_id=customer.id,
        lines=[{"factory_model": "A", "qty": 1, "unit_price": 10}],
        created_by=None,
    )
    generate_sales_statement(
        db,
        tenant.id,
        customer_id=customer.id,
        sample_remake_ids=[created["id"]],
        statement_no="DZ-FB-2",
        statement_date=date(2026, 9, 28),
    )
    try:
        generate_sales_statement(
            db,
            tenant.id,
            customer_id=customer.id,
            sample_remake_ids=[created["id"]],
            statement_no="DZ-FB-3",
            statement_date=date(2026, 9, 28),
        )
        raise AssertionError("已对账的复版记录不应再次进对账单")
    except FinanceError as err:
        assert err.code == "already_statemented"
