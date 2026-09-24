"""余额制往来：周期对账单、总额收付款与可选逐单核销。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AccountStatement,
    AccountStatementStatus,
    Color,
    PackingCarton,
    PackingCartonLine,
    Partner,
    Payable,
    PayableLine,
    PayableStatus,
    PricingUnit,
    PurchaseOrder,
    PurchaseOrderLine,
    Receivable,
    ReceivableStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    Shipment,
    ShipmentLine,
    Size,
    SettlementDirection,
    SupplierProduct,
    Tenant,
)
from app.api.v1.partners import create_partner, update_partner
from app.schemas.api import PartnerCreate, PartnerUpdate
from app.services import ap_service, finance_service, settlement_service


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
    tenant = Tenant(name="T-SETTLEMENT")
    session.add(tenant)
    session.flush()
    customer = Partner(
        tenant_id=tenant.id,
        name="客户甲",
        short_name="甲客",
        is_customer=True,
        is_active=True,
    )
    session.add(customer)
    session.flush()
    session.add_all(
        [
            Receivable(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name="甲客",
                receivable_date=date(2026, 8, 5),
                amount=Decimal("350000"),
                adjustment=Decimal("0"),
                received_amount=Decimal("0"),
                status=ReceivableStatus.open,
            ),
            Receivable(
                tenant_id=tenant.id,
                customer_id=customer.id,
                customer_name="甲客",
                receivable_date=date(2026, 8, 20),
                amount=Decimal("200000"),
                adjustment=Decimal("0"),
                received_amount=Decimal("0"),
                status=ReceivableStatus.open,
            ),
        ]
    )
    session.commit()
    yield session, tenant.id, customer.id
    session.close()


def test_statement_accepts_partial_total_payment_without_document_allocations(db):
    session, tenant_id, customer_id = db
    statement = settlement_service.generate_statement(
        session,
        tenant_id,
        partner_id=customer_id,
        direction="customer",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    assert Decimal(str(statement["closing_balance"])) == Decimal("550000")
    receivable_lines = [line for line in statement["lines"] if line["source_type"] == "receivable"]
    assert len(receivable_lines) == 2
    assert all(line["description"] == "本期出货货款" for line in receivable_lines)
    assert all("#" not in line["description"] for line in receivable_lines)

    confirmed = settlement_service.confirm_statement(session, tenant_id, statement["id"])
    assert confirmed["status"] == "confirmed"

    payment = finance_service.create_payment(
        session,
        tenant_id,
        customer_id=customer_id,
        customer_name="甲客",
        amount=Decimal("300000"),
        payment_date=date(2026, 9, 30),
        method="bank",
        statement_id=statement["id"],
        allocations=[],
    )
    assert payment["allocation_mode"] == "statement"
    assert Decimal(str(payment["allocated_amount"])) == Decimal("0")
    assert Decimal(str(payment["unallocated_amount"])) == Decimal("0")

    refreshed = settlement_service.statement_out(session, tenant_id, statement["id"])
    assert refreshed["status"] == "partial"
    assert Decimal(str(refreshed["settled_amount"])) == Decimal("300000")
    assert Decimal(str(refreshed["remaining_amount"])) == Decimal("250000")


def test_customer_statement_shipment_items_use_actual_cartons_and_assortment(db):
    session, tenant_id, customer_id = db
    color = Color(tenant_id=tenant_id, name="黑色", code="BK")
    size38 = Size(tenant_id=tenant_id, size_value="38", sort_order=38)
    size39 = Size(tenant_id=tenant_id, size_value="39", sort_order=39)
    session.add_all([color, size38, size39])
    session.flush()
    order = SalesOrder(
        tenant_id=tenant_id,
        order_no="XS-TEST-01",
        customer_id=customer_id,
        customer_name="甲客",
        ordered_at=date(2026, 8, 1),
    )
    session.add(order)
    session.flush()
    sales_line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=order.id,
        own_product_id=999,
        color_id=color.id,
        customer_sku="客款-A88",
        brand_name="测试品牌",
        unit_price=Decimal("50"),
        carton_qty=2,
        total_qty=10,
    )
    session.add(sales_line)
    session.flush()
    item38 = SalesOrderLineItem(
        tenant_id=tenant_id, sales_order_line_id=sales_line.id,
        color_id=color.id, size_id=size38.id, qty=4,
    )
    item39 = SalesOrderLineItem(
        tenant_id=tenant_id, sales_order_line_id=sales_line.id,
        color_id=color.id, size_id=size39.id, qty=6,
    )
    session.add_all([item38, item39])
    session.flush()
    shipment = Shipment(
        tenant_id=tenant_id,
        shipment_no="CK-TEST-01",
        sales_order_id=order.id,
        sales_order_no=order.order_no,
        customer_id=customer_id,
        customer_name="甲客",
        ship_date=date(2026, 8, 10),
        unit_price=Decimal("50"),
        total_qty=10,
        amount=Decimal("500"),
    )
    session.add(shipment)
    session.flush()
    session.add_all([
        ShipmentLine(
            tenant_id=tenant_id, shipment_id=shipment.id,
            sales_order_line_item_id=item38.id, color_id=color.id,
            size_id=size38.id, qty=4,
        ),
        ShipmentLine(
            tenant_id=tenant_id, shipment_id=shipment.id,
            sales_order_line_item_id=item39.id, color_id=color.id,
            size_id=size39.id, qty=6,
        ),
    ])
    for seq in (1, 2):
        carton = PackingCarton(
            tenant_id=tenant_id, plan_id=999, seq=seq, code=f"BOX-TEST-{seq}",
            total_qty=5, sales_order_id=order.id, sales_order_line_id=sales_line.id,
            customer_id=customer_id, customer_name="甲客", brand_name="测试品牌",
            customer_sku="客款-A88", shipment_id=shipment.id,
        )
        session.add(carton)
        session.flush()
        session.add_all([
            PackingCartonLine(
                tenant_id=tenant_id, carton_id=carton.id,
                color_id=color.id, size_id=size38.id, qty=2,
            ),
            PackingCartonLine(
                tenant_id=tenant_id, carton_id=carton.id,
                color_id=color.id, size_id=size39.id, qty=3,
            ),
        ])
    session.commit()

    details = settlement_service._shipment_statement_items(session, shipment.id)
    assert details == [{
        "brand_name": "测试品牌",
        "customer_sku": "客款-A88",
        "color_name": "黑色",
        "assortment": "38×2 / 39×3",
        "assortment_label": "每箱配码",
        "size_breakdown": [
            {"size_value": "38", "qty": 2},
            {"size_value": "39", "qty": 3},
        ],
        "carton_count": 2,
        "qty": 10,
        "unit_price": Decimal("50.0000"),
        "amount": Decimal("500.0000"),
    }]


def test_account_payment_can_remain_unallocated(db):
    session, tenant_id, customer_id = db
    payment = finance_service.create_payment(
        session,
        tenant_id,
        customer_id=customer_id,
        customer_name="甲客",
        amount=Decimal("300000"),
        payment_date=date(2026, 8, 28),
        allocations=[],
    )
    assert payment["allocation_mode"] == "account"
    assert Decimal(str(payment["unallocated_amount"])) == Decimal("300000")
    summary = finance_service.customer_ar_summary(session, tenant_id, customer_id=customer_id)[0]
    assert Decimal(str(summary["received_amount"])) == Decimal("300000")
    assert Decimal(str(summary["unallocated_credit"])) == Decimal("300000")
    assert Decimal(str(summary["balance"])) == Decimal("250000")


def test_void_statement_can_be_regenerated_for_same_period(db):
    session, tenant_id, customer_id = db
    first = settlement_service.generate_statement(
        session,
        tenant_id,
        partner_id=customer_id,
        direction="customer",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    settlement_service.void_statement(session, tenant_id, first["id"])

    regenerated = settlement_service.generate_statement(
        session,
        tenant_id,
        partner_id=customer_id,
        direction="customer",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    assert regenerated["id"] != first["id"]
    assert regenerated["status"] == "draft"


def test_monthly_cutoff_and_fixed_payment_day(db):
    session, tenant_id, customer_id = db
    settlement_service.upsert_policy(
        session,
        tenant_id,
        customer_id,
        "customer",
        settlement_mode="balance_forward",
        cycle_type="monthly",
        cutoff_day=25,
        due_rule="fixed_day",
        due_months=1,
        fixed_due_day=30,
    )
    due = settlement_service.effective_due_date(
        session,
        tenant_id,
        customer_id,
        "customer",
        business_date=date(2026, 8, 26),
    )
    # 8月26日已过25日截账，进入9月25日周期，再于下月30日到期。
    assert due == date(2026, 10, 30)


def test_partner_create_and_update_persist_settlement_policy(db):
    session, tenant_id, _customer_id = db

    class User:
        pass

    user = User()
    user.tenant_id = tenant_id
    created = create_partner(
        PartnerCreate(
            name="客户乙",
            is_customer=True,
            customer_settlement_policy={
                "settlement_mode": "balance_forward",
                "cycle_type": "monthly",
                "cutoff_day": 25,
                "reconciliation_day": 28,
                "due_rule": "fixed_day",
                "due_months": 1,
                "fixed_due_day": 30,
            },
        ),
        session,
        user,
    )["data"]
    assert created["customer_settlement_policy"]["cutoff_day"] == 25
    assert created["customer_settlement_policy"]["fixed_due_day"] == 30

    updated = update_partner(
        created["id"],
        PartnerUpdate(
            customer_settlement_policy={
                "settlement_mode": "balance_forward",
                "cycle_type": "monthly",
                "cutoff_day": 31,
                "due_rule": "cutoff_days",
                "term_days": 45,
            }
        ),
        session,
        user,
    )["data"]
    policy = updated["customer_settlement_policy"]
    assert policy["cutoff_day"] == 31
    assert policy["due_rule"] == "cutoff_days"
    assert policy["term_days"] == 45


def test_new_partner_automatically_copies_default_settlement_template(db):
    session, tenant_id, _customer_id = db
    settlement_service.upsert_policy_template(
        session,
        tenant_id,
        name="鞋厂客户月结",
        direction="customer",
        is_default=True,
        settlement_mode="balance_forward",
        cycle_type="monthly",
        cutoff_day=25,
        reconciliation_day=28,
        due_rule="fixed_day",
        due_months=1,
        fixed_due_day=30,
    )

    class User:
        pass

    user = User()
    user.tenant_id = tenant_id
    created = create_partner(
        PartnerCreate(name="自动套模板客户", is_customer=True), session, user
    )["data"]
    policy = created["customer_settlement_policy"]
    assert policy["cutoff_day"] == 25
    assert policy["reconciliation_day"] == 28
    assert policy["due_rule"] == "fixed_day"
    assert policy["fixed_due_day"] == 30


def test_supplier_payment_reduces_account_balance_without_open_item_allocation(db):
    session, tenant_id, _customer_id = db
    supplier = Partner(
        tenant_id=tenant_id,
        name="供应商乙",
        is_supplier=True,
        is_active=True,
    )
    session.add(supplier)
    session.flush()
    po = PurchaseOrder(tenant_id=tenant_id, po_no="PO-SUP-01", partner_id=supplier.id)
    session.add(po)
    session.flush()
    payable = Payable(
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            supplier_name="供应商乙",
            purchase_order_id=po.id,
            payable_date=date(2026, 8, 10),
            due_date=date(2026, 9, 10),
            payment_term_days=30,
            amount=Decimal("550000"),
            adjustment=Decimal("0"),
            paid_amount=Decimal("0"),
            status=PayableStatus.open,
        )
    session.add(payable)
    session.flush()
    session.add(
        PayableLine(
            tenant_id=tenant_id,
            payable_id=payable.id,
            source_type="purchase_receive",
            source_document_no="PO-SUP-01",
            item_code="MAT-FABRIC",
            item_name="针织面料",
            color_name="黑色",
            unit_name="米",
            qty=Decimal("1000"),
            unit_price=Decimal("550"),
            amount=Decimal("550000"),
        )
    )
    session.commit()

    from app.services.purchase_settlement_service import (
        generate_purchase_statement,
        list_pending_lines,
        supplier_purchase_balance,
    )

    pending = list_pending_lines(session, tenant_id, supplier_id=supplier.id)
    assert len(pending) == 1
    statement = generate_purchase_statement(
        session,
        tenant_id,
        supplier_id=supplier.id,
        line_ids=[pending[0]["line_id"]],
        remainder_payable_ids=[],
    )
    payable_line = next(line for line in statement["lines"] if line["source_type"] == "payable_line")
    assert payable_line["supplier_items"][0]["item_name"] == "针织面料"
    assert payable_line["supplier_items"][0]["color_name"] == "黑色"

    payment = ap_service.create_supplier_payment(
        session,
        tenant_id,
        supplier_id=supplier.id,
        supplier_name="供应商乙",
        amount=Decimal("300000"),
        payment_date=date(2026, 9, 30),
        statement_id=statement["id"],
    )
    assert payment["allocation_mode"] == "statement"
    balance = supplier_purchase_balance(session, tenant_id, supplier.id)
    assert Decimal(str(balance["debt"])) == Decimal("250000")
    assert Decimal(str(balance["pending_amount"])) == Decimal("0")


def test_legacy_purchase_payable_restores_supplier_item_details(db):
    session, tenant_id, _ = db
    supplier = Partner(
        tenant_id=tenant_id, name="老供应商", short_name="老供应商",
        is_supplier=True, is_active=True,
    )
    unit = PricingUnit(tenant_id=tenant_id, name="米")
    color = Color(tenant_id=tenant_id, name="灰色", code="GY")
    size = Size(tenant_id=tenant_id, size_value="1.2mm", sort_order=1)
    session.add_all([supplier, unit, color, size])
    session.flush()
    product = SupplierProduct(
        tenant_id=tenant_id, partner_id=supplier.id, product_code="MAT-OLD",
        name="超纤面料", pricing_unit_id=unit.id, color_id=color.id,
    )
    session.add(product)
    session.flush()
    po = PurchaseOrder(tenant_id=tenant_id, po_no="PO-OLD-01", partner_id=supplier.id)
    session.add(po)
    session.flush()
    session.add(PurchaseOrderLine(
        tenant_id=tenant_id, purchase_order_id=po.id, supplier_product_id=product.id,
        qty=Decimal("20"), received_qty=Decimal("20"), unit_price=Decimal("12"),
        size_id=size.id,
    ))
    session.flush()
    payable = Payable(
        tenant_id=tenant_id, supplier_id=supplier.id, supplier_name="老供应商",
        purchase_order_id=po.id, payable_date=date(2026, 8, 5), due_date=date(2026, 9, 5),
        payment_term_days=30, amount=Decimal("240"), adjustment=Decimal("0"),
        paid_amount=Decimal("0"), status=PayableStatus.open,
    )
    session.add(payable)
    session.commit()

    item = settlement_service._payable_statement_items(session, payable.id)[0]
    assert item["source_document_no"] == "PO-OLD-01"
    assert item["item_name"] == "超纤面料"
    assert item["item_code"] == "MAT-OLD"
    assert item["color_name"] == "灰色"
    assert item["unit_name"] == "米"
    assert item["size_breakdown"][0]["size_value"] == "1.2mm"


def test_statement_list_separates_suppliers_and_subcontractors_and_filters_period(db):
    session, tenant_id, _ = db
    supplier = Partner(
        tenant_id=tenant_id, name="物料供应商", is_supplier=True, is_active=True,
    )
    subcontractor = Partner(
        tenant_id=tenant_id, name="外协厂", is_supplier=True,
        is_subcontractor=True, is_active=True,
    )
    session.add_all([supplier, subcontractor])
    session.flush()

    def add_statement(no: str, partner: Partner, start: date, end: date):
        session.add(AccountStatement(
            tenant_id=tenant_id, statement_no=no, partner_id=partner.id,
            partner_name=partner.name, direction=SettlementDirection.supplier,
            period_start=start, period_end=end, statement_date=end, due_date=end,
            opening_balance=Decimal("0"), current_amount=Decimal("100"),
            adjustment_amount=Decimal("0"), period_settlement_amount=Decimal("0"),
            closing_balance=Decimal("100"), status=AccountStatementStatus.draft,
        ))

    add_statement("DZ-S-OLD", supplier, date(2026, 6, 1), date(2026, 6, 30))
    add_statement("DZ-S-AUG", supplier, date(2026, 8, 1), date(2026, 8, 31))
    add_statement("DZ-W-AUG", subcontractor, date(2026, 8, 1), date(2026, 8, 31))
    session.commit()

    supplier_rows = settlement_service.list_statements(
        session, tenant_id, direction="supplier", partner_type="supplier",
        date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
    )
    subcontract_rows = settlement_service.list_statements(
        session, tenant_id, direction="supplier", partner_type="subcontractor",
        date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
    )
    assert [row["statement_no"] for row in supplier_rows] == ["DZ-S-AUG"]
    assert [row["statement_no"] for row in subcontract_rows] == ["DZ-W-AUG"]
    assert supplier_rows[0]["partner_type"] == "supplier"
    assert subcontract_rows[0]["partner_type"] == "subcontractor"
