"""采购退货：减可用库存，待结算负数行，未进对账单可作废。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Partner,
    PayableLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedMaterialLedger,
    SharedMaterialStock,
    SupplierProduct,
    Tenant,
)
from app.services.ap_service import ApError
from app.services.material_service import adjust_shared_stock
from app.services.purchase_return_service import (
    create_purchase_return,
    void_purchase_return_lines,
)
from app.services.purchase_service import receive_po
from app.services.purchase_settlement_service import (
    generate_purchase_statement,
    list_pending_lines,
    supplier_purchase_balance,
    void_purchase_statement,
)


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
    tenant = Tenant(name="T-RET", settings_json={"inventory": {"iqc_before_pool": False}})
    session.add(tenant)
    session.flush()
    partner = Partner(
        tenant_id=tenant.id,
        name="供应商甲",
        short_name="甲料",
        is_supplier=True,
        is_active=True,
    )
    other = Partner(
        tenant_id=tenant.id,
        name="供应商乙",
        short_name="乙料",
        is_supplier=True,
        is_active=True,
    )
    session.add_all([partner, other])
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="MAT-1",
        name="面料",
        unit_price=Decimal("10"),
        is_active=True,
    )
    other_sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=other.id,
        product_code="MAT-2",
        name="里布",
        unit_price=Decimal("8"),
        is_active=True,
    )
    session.add_all([sp, other_sp])
    session.commit()
    yield session, tenant.id, partner.id, sp.id, other.id, other_sp.id
    session.close()


def _receive(session, tenant_id, partner_id, sp_id, qty, price, po_no):
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
    receive_po(session, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal(qty)}])
    return po, line


def _stock_qty(session, sp_id):
    stock = session.scalar(
        select(SharedMaterialStock).where(SharedMaterialStock.supplier_product_id == sp_id)
    )
    return stock.qty if stock else Decimal("0")


def test_return_uses_material_price_and_pending_line(db):
    session, tenant_id, partner_id, sp_id, _other_id, _other_sp = db
    _receive(session, tenant_id, partner_id, sp_id, "10", "10", "PO-1")
    _receive(session, tenant_id, partner_id, sp_id, "4", "12", "PO-2")

    created = create_purchase_return(
        session,
        tenant_id,
        [{"supplier_product_id": sp_id, "size_id": None, "qty": Decimal("5"), "unit_price": Decimal("15")}],
        note="破损",
    )
    assert created["amount"] == Decimal("-75.0000")
    assert _stock_qty(session, sp_id) == Decimal("9")

    pending = list_pending_lines(session, tenant_id, supplier_id=partner_id)
    returns = [row for row in pending if row["source_type"] == "purchase_return"]
    assert len(returns) == 1
    row = returns[0]
    assert row["po_no"] is None
    assert row["delivery_note_no"] is None
    assert row["ordered_at"] is None
    assert row["order_qty"] is None
    assert row["qty"] == Decimal("-5.0000")
    assert row["unit_price"] == Decimal("15.0000")
    assert row["amount"] == Decimal("-75.0000")
    assert row["item_code"] == "MAT-1"

    balance = supplier_purchase_balance(session, tenant_id, partner_id)
    assert balance["pending_amount"] == Decimal("73.0000")
    assert balance["debt"] == Decimal("73.0000")

    ledger = session.scalar(
        select(SharedMaterialLedger)
        .where(SharedMaterialLedger.supplier_product_id == sp_id)
        .order_by(SharedMaterialLedger.id.desc())
    )
    assert ledger.ledger_type.value == "purchase_return"
    assert ledger.qty_delta == Decimal("-5")
    assert ledger.note == "破损"


def test_return_cannot_exceed_available_qty(db):
    session, tenant_id, partner_id, sp_id, _other_id, _other_sp = db
    _receive(session, tenant_id, partner_id, sp_id, "10", "10", "PO-CAP")
    stock = session.scalar(
        select(SharedMaterialStock).where(SharedMaterialStock.supplier_product_id == sp_id)
    )
    stock.qty = Decimal("3")
    session.commit()
    with pytest.raises(ApError) as capped:
        create_purchase_return(
            session,
            tenant_id,
            [{"supplier_product_id": sp_id, "qty": Decimal("4")}],
        )
    assert capped.value.code == "qty_exceeds_returnable"


def test_return_without_arrival_uses_material_price(db):
    session, tenant_id, partner_id, sp_id, _other_id, _other_sp = db
    adjust_shared_stock(session, tenant_id, sp_id, Decimal("6"), note="期初")
    session.commit()
    created = create_purchase_return(
        session,
        tenant_id,
        [{"supplier_product_id": sp_id, "qty": Decimal("1")}],
    )
    assert created["amount"] == Decimal("-10.0000")
    assert _stock_qty(session, sp_id) == Decimal("5")
    pending = [
        row for row in list_pending_lines(session, tenant_id, supplier_id=partner_id)
        if row["source_type"] == "purchase_return"
    ]
    assert pending[0]["delivery_note_no"] is None
    assert pending[0]["unit_price"] == Decimal("10.0000")
    assert pending[0]["po_no"] is None


def test_one_supplier_per_return(db):
    session, tenant_id, partner_id, sp_id, _other_id, other_sp = db
    _receive(session, tenant_id, partner_id, sp_id, "2", "10", "PO-A")
    _receive(session, tenant_id, _other_id, other_sp, "2", "8", "PO-B")
    with pytest.raises(ApError) as exc:
        create_purchase_return(
            session,
            tenant_id,
            [
                {"supplier_product_id": sp_id, "qty": Decimal("1")},
                {"supplier_product_id": other_sp, "qty": Decimal("1")},
            ],
        )
    assert exc.value.code == "mixed_supplier"


def test_void_return_restores_stock_until_statemented(db):
    session, tenant_id, partner_id, sp_id, _other_id, _other_sp = db
    _receive(session, tenant_id, partner_id, sp_id, "10", "10", "PO-V")
    created = create_purchase_return(
        session,
        tenant_id,
        [{"supplier_product_id": sp_id, "qty": Decimal("4")}],
    )
    assert _stock_qty(session, sp_id) == Decimal("6")
    void_purchase_return_lines(session, tenant_id, created["line_ids"])
    assert _stock_qty(session, sp_id) == Decimal("10")
    assert not [
        row for row in list_pending_lines(session, tenant_id) if row["source_type"] == "purchase_return"
    ]
    assert session.get(PayableLine, created["line_ids"][0]) is None

    again = create_purchase_return(
        session,
        tenant_id,
        [{"supplier_product_id": sp_id, "qty": Decimal("4")}],
    )
    statement = generate_purchase_statement(
        session,
        tenant_id,
        supplier_id=partner_id,
        line_ids=again["line_ids"],
        remainder_payable_ids=[],
        statement_no="RET-1",
        statement_date=date.today(),
    )
    with pytest.raises(ApError) as blocked:
        void_purchase_return_lines(session, tenant_id, again["line_ids"])
    assert blocked.value.code == "already_statemented"
    assert _stock_qty(session, sp_id) == Decimal("6")

    void_purchase_statement(session, tenant_id, statement["id"])
    assert _stock_qty(session, sp_id) == Decimal("6")
    pending = [
        row for row in list_pending_lines(session, tenant_id) if row["source_type"] == "purchase_return"
    ]
    assert len(pending) == 1
    assert pending[0]["amount"] == Decimal("-40.0000")
    void_purchase_return_lines(session, tenant_id, [pending[0]["line_id"]])
    assert _stock_qty(session, sp_id) == Decimal("10")
