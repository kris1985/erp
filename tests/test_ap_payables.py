"""采购到货挂应付、付款核销。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Partner,
    Payable,
    PayableStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierProduct,
    Tenant,
)
from app.services import ap_service, purchase_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # iqc_before_pool=False：receive_po 走「直入池 + 生成应付」路径。
    # 本组测试聚焦 payable 的生成/支付/结算逻辑；IQC 流程（合格后才挂账）
    # 由 iqc_service 的测试覆盖。
    tenant = Tenant(name="T-AP", settings_json={"inventory": {"iqc_before_pool": False}})
    session.add(tenant)
    session.flush()
    partner = Partner(
        tenant_id=tenant.id,
        name="供应商甲",
        short_name="甲料",
        is_supplier=True,
        is_active=True,
    )
    session.add(partner)
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="MAT-1",
        name="面料",
        unit_price=Decimal("10"),
        is_active=True,
    )
    session.add(sp)
    session.commit()
    yield session, tenant.id, partner.id, sp.id
    session.close()


def _ordered_po(session, tenant_id, partner_id, sp_id, *, qty="10", price="10", po_no="PO-AP1"):
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no=po_no,
        public_token=f"tok-{po_no}",
        partner_id=partner_id,
        status=PurchaseOrderStatus.ordered,
    )
    session.add(po)
    session.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant_id,
        purchase_order_id=po.id,
        supplier_product_id=sp_id,
        qty=Decimal(qty),
        unit_price=Decimal(price),
        received_qty=Decimal("0"),
    )
    session.add(line)
    session.commit()
    return po, line


def test_receive_creates_payable(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)

    purchase_service.receive_po(
        session,
        tenant_id,
        po.id,
        [{"line_id": line.id, "qty": Decimal("4")}],
    )

    rows = ap_service.list_payables(session, tenant_id)
    assert len(rows) == 1
    assert Decimal(str(rows[0]["amount"])) == Decimal("40")
    assert Decimal(str(rows[0]["balance"])) == Decimal("40")
    assert rows[0]["status"] == "open"
    assert rows[0]["supplier_name"] == "甲料"
    assert rows[0]["po_no"] == "PO-AP1"

    summary = ap_service.supplier_ap_summary(session, tenant_id, with_balance_only=True)
    assert len(summary) == 1
    assert Decimal(str(summary[0]["balance"])) == Decimal("40")


def test_partial_receive_two_payables_then_pay(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)

    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("3")}]
    )
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("2")}]
    )
    rows = ap_service.list_payables(session, tenant_id)
    assert len(rows) == 2
    total_bal = sum((Decimal(str(r["balance"])) for r in rows), Decimal("0"))
    assert total_bal == Decimal("50")

    open_rows = [r for r in rows if r["status"] == "open"]
    target = next(r for r in open_rows if Decimal(str(r["balance"])) == Decimal("30"))
    pay = ap_service.create_supplier_payment(
        session,
        tenant_id,
        supplier_id=partner_id,
        supplier_name="甲料",
        amount=Decimal("30"),
        payment_date=date.today(),
        method="bank",
        allocations=[
            {"payable_id": target["id"], "amount": Decimal("30")},
        ],
    )
    assert pay["status"] == "posted"
    assert Decimal(str(pay["amount"])) == Decimal("30")

    ap = session.get(Payable, target["id"])
    assert ap.status == PayableStatus.settled
    assert Decimal(str(ap.paid_amount)) == Decimal("30")

    remaining = ap_service.list_payables(session, tenant_id, status="open")
    assert len(remaining) == 1
    assert Decimal(str(remaining[0]["balance"])) == Decimal("20")


def test_void_payment_reopens_payable(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("5")}]
    )
    ap_row = ap_service.list_payables(session, tenant_id)[0]
    pay = ap_service.create_supplier_payment(
        session,
        tenant_id,
        supplier_id=partner_id,
        supplier_name="甲料",
        amount=Decimal("50"),
        payment_date=date.today(),
        allocations=[{"payable_id": ap_row["id"], "amount": Decimal("50")}],
    )
    ap_service.void_supplier_payment(session, tenant_id, pay["id"])
    ap = session.get(Payable, ap_row["id"])
    assert ap.status == PayableStatus.open
    assert Decimal(str(ap.paid_amount)) == Decimal("0")


def test_receive_uses_supplier_term_for_due_date(db):
    session, tenant_id, partner_id, sp_id = db
    partner = session.get(Partner, partner_id)
    partner.payment_term_days = 30
    session.commit()
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("1")}]
    )
    row = ap_service.list_payables(session, tenant_id)[0]
    assert row["payment_term_days"] == 30
    assert row["due_date"] == date.today() + timedelta(days=30)
    assert row["age_bucket"] == "not_due"


def test_po_term_overrides_supplier(db):
    session, tenant_id, partner_id, sp_id = db
    partner = session.get(Partner, partner_id)
    partner.payment_term_days = 30
    session.commit()
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)
    purchase_service.update_po(session, tenant_id, po.id, payment_term_days=7)
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("1")}]
    )
    row = ap_service.list_payables(session, tenant_id)[0]
    assert row["payment_term_days"] == 7
    assert row["due_date"] == date.today() + timedelta(days=7)


def test_zero_price_stays_open_for_adjust(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id, price="0")
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("2")}]
    )
    ap_row = ap_service.list_payables(session, tenant_id)[0]
    assert ap_row["status"] == "open"
    assert Decimal(str(ap_row["amount"])) == Decimal("0")

    updated = ap_service.adjust_payable(session, tenant_id, ap_row["id"], Decimal("15"))
    assert Decimal(str(updated["balance"])) == Decimal("15")
    assert updated["status"] == "open"
