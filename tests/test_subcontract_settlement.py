"""外协验收待结算与勾选对账单，不进采购对账。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    OwnProduct,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PaymentMethod,
    PaymentStatus,
    SubcontractOrder,
    SupplierPayment,
    Tenant,
)
from app.services.purchase_settlement_service import list_pending_lines as list_purchase_pending
from app.services.subcontract_settlement_service import (
    carry_balance,
    generate_subcontract_statement,
    list_pending_lines,
    supplier_subcontract_balance,
    void_subcontract_statement,
)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="外协对账厂")
    db.add(tenant)
    db.flush()
    factory = Partner(
        tenant_id=tenant.id,
        name="针车外协",
        short_name="针车",
        is_subcontractor=True,
    )
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="WX-01",
        image_url="/uploads/wx-01.jpg",
    )
    db.add_all([factory, product])
    db.flush()
    order = SubcontractOrder(
        tenant_id=tenant.id,
        subcontract_no="WX260924001",
        partner_id=factory.id,
        process_name="针车",
        order_process_ids=[],
        own_product_id=product.id,
        total_qty=80,
        issued_qty=100,
        unit_price=Decimal("3.50"),
        created_at=datetime(2026, 9, 1, 9, 0),
    )
    db.add(order)
    db.flush()
    payable = Payable(
        tenant_id=tenant.id,
        supplier_id=factory.id,
        supplier_name="针车",
        subcontract_order_id=order.id,
        payable_date=date(2026, 9, 20),
        due_date=date(2026, 9, 20),
        amount=Decimal("280"),
        delivery_note_no="DN-1",
        status=PayableStatus.open,
        created_at=datetime(2026, 9, 20, 15, 0),
    )
    db.add(payable)
    db.flush()
    line = PayableLine(
        tenant_id=tenant.id,
        payable_id=payable.id,
        source_type="subcontract_receive",
        source_document_no=order.subcontract_no,
        item_code="WX-01",
        process_name="针车",
        customer_sku="KH-WX",
        color_name="黑",
        size_value="37",
        unit_name="双",
        qty=Decimal("80"),
        unit_price=Decimal("3.50"),
        amount=Decimal("280"),
    )
    db.add(line)
    db.commit()
    return {
        "db": db,
        "tenant": tenant,
        "factory": factory,
        "line": line,
    }


def test_pending_line_and_statement_roundtrip(ctx):
    db = ctx["db"]
    tenant_id = ctx["tenant"].id
    factory_id = ctx["factory"].id
    rows = list_pending_lines(db, tenant_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["subcontract_no"] == "WX260924001"
    assert row["process_name"] == "针车"
    assert row["item_code"] == "WX-01"
    assert row["customer_sku"] == "KH-WX"
    assert row["delivery_note_no"] == "DN-1"
    assert row["issued_qty"] == 100
    assert row["qty"] == Decimal("80")
    assert row["gross_amount"] == Decimal("280.0000")
    assert row["shared_loss_amount"] == Decimal("0.00")
    assert row["image_url"] == "/uploads/wx-01.jpg"
    assert row["amount"] == Decimal("280.0000")
    assert list_purchase_pending(db, tenant_id) == []

    statement = generate_subcontract_statement(
        db,
        tenant_id,
        supplier_id=factory_id,
        line_ids=[ctx["line"].id],
        remainder_payable_ids=[],
        statement_no="DZ-WX-1",
        statement_date=date(2026, 9, 24),
    )
    assert statement["statement_kind"] == "subcontract"
    assert statement["partner_type"] == "subcontractor"
    assert statement["current_amount"] == Decimal("280.0000")
    detail = next(line for line in statement["lines"] if line["source_type"] == "payable_line")
    item = detail["supplier_items"][0]
    assert item["process_name"] == "针车"
    assert item["customer_sku"] == "KH-WX"
    assert item["source_document_no"] == "WX260924001"
    assert list_pending_lines(db, tenant_id) == []

    void_subcontract_statement(db, tenant_id, statement["id"])
    restored = list_pending_lines(db, tenant_id)
    assert len(restored) == 1
    assert restored[0]["line_id"] == ctx["line"].id


def test_prepayment_only_for_pure_subcontractor(ctx):
    db = ctx["db"]
    tenant_id = ctx["tenant"].id
    factory_id = ctx["factory"].id
    db.add(
        SupplierPayment(
            tenant_id=tenant_id,
            supplier_id=factory_id,
            supplier_name="针车",
            amount=Decimal("50"),
            payment_date=date(2026, 9, 1),
            method=PaymentMethod.bank,
            status=PaymentStatus.posted,
        )
    )
    mixed = Partner(
        tenant_id=tenant_id,
        name="兼营厂",
        short_name="兼营",
        is_supplier=True,
        is_subcontractor=True,
    )
    db.add(mixed)
    db.flush()
    db.add(
        SupplierPayment(
            tenant_id=tenant_id,
            supplier_id=mixed.id,
            supplier_name="兼营",
            amount=Decimal("80"),
            payment_date=date(2026, 9, 1),
            method=PaymentMethod.bank,
            status=PaymentStatus.posted,
        )
    )
    db.commit()

    balance = supplier_subcontract_balance(db, tenant_id, factory_id)
    assert balance["carry_balance"] == Decimal("-50.0000")
    assert balance["pending_amount"] == Decimal("280.0000")
    assert balance["debt"] == Decimal("230.0000")
    assert carry_balance(db, tenant_id, mixed.id) == Decimal("0.0000")
