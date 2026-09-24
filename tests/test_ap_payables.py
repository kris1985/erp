"""采购到货挂应付、付款核销。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Partner,
    Payable,
    PayableLine,
    PaymentStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierPayment,
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
    snapshot = session.scalar(select(PayableLine).where(PayableLine.payable_id == rows[0]["id"]))
    assert snapshot is not None
    assert snapshot.source_type == "purchase_receive"
    assert snapshot.source_document_no == "PO-AP1"
    assert snapshot.item_code == "MAT-1"
    assert snapshot.item_name == "面料"
    assert Decimal(str(snapshot.qty)) == Decimal("4")
    assert Decimal(str(snapshot.unit_price)) == Decimal("10")
    assert Decimal(str(snapshot.amount)) == Decimal("40")

    from app.services.purchase_settlement_service import supplier_purchase_balance

    balance = supplier_purchase_balance(session, tenant_id, partner_id)
    assert Decimal(str(balance["debt"])) == Decimal("40")
    assert Decimal(str(balance["pending_amount"])) == Decimal("40")
    assert Decimal(str(balance["carry_balance"])) == Decimal("0")


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
    snapshot_qtys = sorted(
        Decimal(str(row.qty)) for row in session.scalars(select(PayableLine)).all()
    )
    assert snapshot_qtys == [Decimal("2"), Decimal("3")]

    from app.services.purchase_settlement_service import (
        generate_purchase_statement,
        list_pending_lines,
        supplier_purchase_balance,
    )

    pending = list_pending_lines(session, tenant_id, supplier_id=partner_id)
    assert len(pending) == 2
    target = next(row for row in pending if Decimal(str(row["amount"])) == Decimal("30"))
    statement = generate_purchase_statement(
        session,
        tenant_id,
        supplier_id=partner_id,
        line_ids=[target["line_id"]],
        remainder_payable_ids=[],
    )
    pay = ap_service.create_supplier_payment(
        session,
        tenant_id,
        supplier_id=partner_id,
        supplier_name="甲料",
        amount=Decimal("30"),
        payment_date=date.today(),
        method="bank",
        statement_id=statement["id"],
    )
    assert pay["status"] == "posted"
    balance = supplier_purchase_balance(session, tenant_id, partner_id)
    assert Decimal(str(balance["pending_amount"])) == Decimal("20")
    assert Decimal(str(balance["debt"])) == Decimal("20")


def test_void_payment_restores_statement_unpaid(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("5")}]
    )
    from app.services.purchase_settlement_service import (
        generate_purchase_statement,
        list_pending_lines,
        supplier_purchase_balance,
        void_purchase_statement,
    )

    pending = list_pending_lines(session, tenant_id, supplier_id=partner_id)
    statement = generate_purchase_statement(
        session,
        tenant_id,
        supplier_id=partner_id,
        line_ids=[pending[0]["line_id"]],
        remainder_payable_ids=[],
    )
    pay = ap_service.create_supplier_payment(
        session,
        tenant_id,
        supplier_id=partner_id,
        supplier_name="甲料",
        amount=Decimal("50"),
        payment_date=date.today(),
        statement_id=statement["id"],
    )
    ap_service.void_supplier_payment(session, tenant_id, pay["id"])
    balance = supplier_purchase_balance(session, tenant_id, partner_id)
    assert Decimal(str(balance["debt"])) == Decimal("50")
    assert list_pending_lines(session, tenant_id, supplier_id=partner_id) == []
    void_purchase_statement(session, tenant_id, statement["id"])
    assert len(list_pending_lines(session, tenant_id, supplier_id=partner_id)) == 1


def test_receive_ignores_supplier_term_and_stores_delivery_note(db):
    session, tenant_id, partner_id, sp_id = db
    partner = session.get(Partner, partner_id)
    partner.payment_term_days = 30
    session.commit()
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id)
    purchase_service.receive_po(
        session,
        tenant_id,
        po.id,
        [{"line_id": line.id, "qty": Decimal("1")}],
        delivery_note_no="DN-1",
    )
    row = ap_service.list_payables(session, tenant_id)[0]
    assert row["payment_term_days"] == 0
    assert row["due_date"] == date.today()
    ap = session.get(Payable, row["id"])
    assert ap.delivery_note_no == "DN-1"


def test_po_term_does_not_change_purchase_payable(db):
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
    assert row["payment_term_days"] == 0
    assert row["due_date"] == date.today()


def test_zero_price_stays_open_for_adjust(db):
    session, tenant_id, partner_id, sp_id = db
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id, price="0")
    purchase_service.receive_po(
        session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("2")}]
    )
    ap_row = ap_service.list_payables(session, tenant_id)[0]
    assert ap_row["status"] == "open"
    assert Decimal(str(ap_row["amount"])) == Decimal("0")
    with pytest.raises(ap_service.ApError) as exc:
        ap_service.adjust_payable(session, tenant_id, ap_row["id"], Decimal("15"))
    assert exc.value.code == "purchase_no_adjust"


def test_statement_opening_follows_prepayment_then_unpaid(db):
    session, tenant_id, partner_id, sp_id = db
    session.add(
        SupplierPayment(
            tenant_id=tenant_id,
            supplier_id=partner_id,
            supplier_name="甲料",
            amount=Decimal("30"),
            payment_date=date.today(),
            status=PaymentStatus.posted,
        )
    )
    session.commit()
    po, line = _ordered_po(session, tenant_id, partner_id, sp_id, qty="14", price="10", po_no="PO-CARRY")
    purchase_service.receive_po(session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("10")}])
    purchase_service.receive_po(session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("4")}])

    from app.services.purchase_settlement_service import (
        generate_purchase_statement,
        list_pending_lines,
        supplier_purchase_balance,
    )

    before = supplier_purchase_balance(session, tenant_id, partner_id)
    assert Decimal(str(before["carry_balance"])) == Decimal("-30")
    assert Decimal(str(before["debt"])) == Decimal("110")
    pending = list_pending_lines(session, tenant_id, supplier_id=partner_id)
    red = next(row for row in pending if Decimal(str(row["amount"])) == Decimal("100"))
    blue = next(row for row in pending if Decimal(str(row["amount"])) == Decimal("40"))
    first = generate_purchase_statement(
        session, tenant_id, supplier_id=partner_id, line_ids=[red["line_id"]], remainder_payable_ids=[]
    )
    assert Decimal(str(first["opening_balance"])) == Decimal("-30")
    assert Decimal(str(first["closing_balance"])) == Decimal("70")
    ap_service.create_supplier_payment(
        session, tenant_id, supplier_id=partner_id, supplier_name="甲料",
        amount=Decimal("50"), payment_date=date.today(), statement_id=first["id"],
    )
    mid = supplier_purchase_balance(session, tenant_id, partner_id)
    assert Decimal(str(mid["debt"])) == Decimal("60")
    second = generate_purchase_statement(
        session, tenant_id, supplier_id=partner_id, line_ids=[blue["line_id"]], remainder_payable_ids=[]
    )
    assert Decimal(str(second["opening_balance"])) == Decimal("20")
    assert Decimal(str(second["closing_balance"])) == Decimal("60")
    with pytest.raises(ap_service.ApError):
        ap_service.create_supplier_payment(
            session, tenant_id, supplier_id=partner_id, supplier_name="甲料",
            amount=Decimal("1"), payment_date=date.today(), statement_id=first["id"],
        )
