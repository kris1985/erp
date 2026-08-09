"""B1a：客供收货台 — 登记到货闭环 + 成本不计客供。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    Partner,
    ProcessDefinition,
    ProcessType,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import customer_supply_service, finance_service
from app.services.inventory_settings import save_inventory_patch
from app.services.material_service import MaterialError


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
    try:
        yield session
    finally:
        session.close()


def _seed_order_with_customer_line(db):
    tenant = Tenant(name="客供台厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    partner = Partner(tenant_id=tenant.id, name="客供客户", is_customer=True, is_supplier=True)
    db.add_all([color, size, partner])
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="CS-SOLE-01",
        name="客供大底",
        partner_id=partner.id,
        unit_price=Decimal("9.00"),
        is_active=True,
    )
    product = OwnProduct(tenant_id=tenant.id, product_code="客供款", quote_price=Decimal("80"))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="包装",
        code="BZ",
        default_price=Decimal("0.2"),
        sort_order=1,
        type=ProcessType.personal,
    )
    db.add_all([sp, product, proc])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="CS-001",
        customer_name="客供客户",
        customer_id=partner.id,
        own_product_id=product.id,
        style_id=product.id,
        total_qty=100,
        delivery_date=date.today() + timedelta(days=10),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            color_id=color.id,
            size_id=size.id,
            qty=100,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=proc.id,
            process_name="包装",
            process_type=ProcessType.personal,
            plan_qty=100,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    req = OrderMaterialRequirement(
        tenant_id=tenant.id,
        order_id=order.id,
        supplier_product_id=sp.id,
        qty_per_pair=Decimal("1"),
        unit_price=Decimal("9.00"),
        required_qty=Decimal("100"),
        arrived_qty=Decimal("0"),
        is_customer_supplied=True,
        customer_chase_status="open",
    )
    buy = OrderMaterialRequirement(
        tenant_id=tenant.id,
        order_id=order.id,
        supplier_product_id=sp.id,
        qty_per_pair=Decimal("0"),
        unit_price=Decimal("9.00"),
        required_qty=Decimal("10"),
        arrived_qty=Decimal("10"),
        issued_qty=Decimal("10"),
        is_customer_supplied=False,
    )
    db.add_all([req, buy])
    db.commit()
    return tenant.id, order.id, req.id


def test_receive_clears_owed_and_chase(db):
    tenant_id, _order_id, req_id = _seed_order_with_customer_line(db)
    rows = customer_supply_service.list_customer_supply(db, tenant_id, owed_only=True)
    assert len(rows) == 1
    assert float(rows[0]["owed_qty"]) == 100

    out = customer_supply_service.receive_customer_supply(
        db, tenant_id, req_id, qty=Decimal("40"), note="首批"
    )
    assert float(out["line"]["arrived_qty"]) == 40
    assert float(out["line"]["owed_qty"]) == 60
    assert out["line"]["customer_chase_status"] == "open"

    customer_supply_service.chase_customer_supply(
        db, tenant_id, req_id, status="chased", note="已催客户"
    )
    chased = customer_supply_service.list_customer_supply(db, tenant_id, chase_status="chased")
    assert len(chased) == 1

    out2 = customer_supply_service.receive_customer_supply(
        db, tenant_id, req_id, qty=Decimal("60"), note="补齐"
    )
    assert float(out2["line"]["owed_qty"]) == 0
    assert out2["line"]["customer_chase_status"] == "cleared"

    receipts = customer_supply_service.list_customer_supply_receipts(db, tenant_id, req_id)
    assert len(receipts) == 2
    assert sum(float(r["qty"]) for r in receipts) == 100


def test_customer_supply_excluded_from_material_cost(db):
    tenant_id, order_id, req_id = _seed_order_with_customer_line(db)
    customer_supply_service.receive_customer_supply(db, tenant_id, req_id, qty=Decimal("100"))
    order = db.get(Order, order_id)
    req = db.get(OrderMaterialRequirement, req_id)
    req.issued_qty = Decimal("100")
    db.commit()

    save_inventory_patch(db, tenant_id, {"cost_basis": "issued"})
    cost2, basis2 = finance_service._material_cost(db, tenant_id, order)
    assert basis2 == "issued"
    # non-customer buy line issued 10 * 9 = 90; customer 100*9 excluded
    assert float(cost2) == 90.0


def test_receive_rejects_non_customer(db):
    tenant_id, order_id, _req_id = _seed_order_with_customer_line(db)
    non_cs = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.order_id == order_id,
            OrderMaterialRequirement.is_customer_supplied.is_(False),
        )
    )
    with pytest.raises(MaterialError) as ei:
        customer_supply_service.receive_customer_supply(
            db, tenant_id, non_cs.id, qty=Decimal("1")
        )
    assert ei.value.code == "not_customer_supplied"
