"""A1c：批价同类实绩 — 同款出货中位/四分位；空态。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderStatus,
    OwnProduct,
    Shipment,
    ShipmentStatus,
    Tenant,
)
from app.services.peer_actuals_service import PeerActualsError, peer_actuals_for_product


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


def _product(db, *, code="A1C-款"):
    tenant = Tenant(name="批价厂")
    db.add(tenant)
    db.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code=code,
        material_cost=Decimal("10"),
        labor_cost=Decimal("5"),
        other_cost=Decimal("5"),
        quote_price=Decimal("80"),
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return tenant, product


def _shipped_order(db, tenant_id, product_id, *, order_no, other_amount, qty, unit_price, ship_day_offset=0):
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客",
        own_product_id=product_id,
        style_id=product_id,
        total_qty=qty,
        delivery_date=date.today() + timedelta(days=7),
        status=OrderStatus.completed,
        other_cost_amount=Decimal(str(other_amount)),
    )
    db.add(order)
    db.flush()
    amt = Decimal(str(unit_price)) * Decimal(qty)
    db.add(
        Shipment(
            tenant_id=tenant_id,
            shipment_no=f"SH-{order_no}",
            order_id=order.id,
            customer_name="客",
            status=ShipmentStatus.shipped,
            ship_date=date.today() - timedelta(days=ship_day_offset),
            unit_price=Decimal(str(unit_price)),
            total_qty=qty,
            amount=amt,
        )
    )
    db.commit()
    return order


def test_empty_state_no_shipments(db):
    tenant, product = _product(db)
    panel = peer_actuals_for_product(db, tenant.id, product.id)
    assert panel["available"] is False
    assert panel["sample_size"] == 0
    assert "出货记录" in (panel["empty_reason"] or "")
    assert panel["card_unit_cost"] == 20.0
    assert panel["advisory_only"] is True
    assert panel["actual_unit_cost"]["median"] is None


def test_median_and_margin_with_samples(db):
    tenant, product = _product(db)
    # unit cost = other_amount/qty → 22, 24, 30；中位 24；卡 20 → delta +4 (+20%)
    _shipped_order(
        db, tenant.id, product.id, order_no="P1", other_amount=2200, qty=100, unit_price=80, ship_day_offset=3
    )
    _shipped_order(
        db, tenant.id, product.id, order_no="P2", other_amount=2400, qty=100, unit_price=80, ship_day_offset=2
    )
    _shipped_order(
        db, tenant.id, product.id, order_no="P3", other_amount=3000, qty=100, unit_price=80, ship_day_offset=1
    )

    panel = peer_actuals_for_product(db, tenant.id, product.id)
    assert panel["available"] is True
    assert panel["sample_size"] == 3
    assert panel["peer_scope"] == "same_sku"
    assert panel["actual_unit_cost"]["median"] == pytest.approx(24.0)
    assert panel["actual_unit_cost"]["p25"] is not None
    assert panel["actual_unit_cost"]["p75"] is not None
    assert panel["delta_vs_card"]["median"] == pytest.approx(4.0)
    assert panel["delta_vs_card"]["median_pct"] == pytest.approx(20.0)
    # margins: (8000-2200)/8000=0.725, (8000-2400)/8000=0.7, (8000-3000)/8000=0.625 → median 0.7
    assert panel["actual_gross_margin"]["median"] == pytest.approx(0.7)
    assert len(panel["sample_orders"]) == 3
    assert panel["definitions"]["median"]


def test_product_not_found(db):
    tenant, _ = _product(db)
    with pytest.raises(PeerActualsError) as ei:
        peer_actuals_for_product(db, tenant.id, 99999)
    assert ei.value.code == "product_not_found"
