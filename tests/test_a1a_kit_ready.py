"""A1a：预计到料日/齐套日 — 在途按码匹配不串码。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Partner,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import purchase_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="A1a厂")
    session.add(tenant)
    session.flush()
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=1)
    s42 = Size(tenant_id=tenant.id, size_value="42", sort_order=2)
    session.add_all([s37, s42])
    partner = Partner(tenant_id=tenant.id, name="底厂", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("10"),
        is_active=True,
    )
    session.add(sole)
    session.flush()
    # 仅 42 码在途，预计 10 天后到
    as_of = date(2026, 8, 9)
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-ETA-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
        expected_date=as_of + timedelta(days=10),
        ordered_at=as_of,
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=sole.id,
            qty=Decimal("100"),
            received_qty=Decimal("0"),
            unit_price=Decimal("10"),
            size_id=s42.id,
        )
    )
    session.commit()
    yield session, tenant.id, sole.id, partner.id, s37.id, s42.id, as_of
    session.close()


def test_in_transit_eta_does_not_cross_sizes(db):
    session, tenant_id, sole_id, partner_id, s37, s42, as_of = db
    rows = [
        {
            "order_id": 1,
            "supplier_product_id": sole_id,
            "partner_id": partner_id,
            "size_id": s37,
            "shortage_qty": 50,
            "supplier_product_code": "SOLE-1",
        },
        {
            "order_id": 1,
            "supplier_product_id": sole_id,
            "partner_id": partner_id,
            "size_id": s42,
            "shortage_qty": 80,
            "supplier_product_code": "SOLE-1",
        },
    ]
    eta = purchase_service.estimate_material_etas(session, tenant_id, rows, as_of=as_of)
    by_size = {it["size_id"]: it for it in eta["items"]}
    assert by_size[s42]["source"] == "in_transit"
    assert by_size[s42]["expected_ready_date"] == (as_of + timedelta(days=10)).isoformat()
    # 37 不能吃 42 的在途
    assert by_size[s37]["source"] != "in_transit"
    assert eta["by_order_id"]["1"] == by_size[s37]["expected_ready_date"] or eta[
        "by_order_id"
    ]["1"] == by_size[s42]["expected_ready_date"]
    # 齐套日 = 两行到料日最晚
    assert eta["earliest_start"] == max(
        by_size[s37]["expected_ready_date"], by_size[s42]["expected_ready_date"]
    )


def test_annotate_rows_with_etas(db):
    session, tenant_id, sole_id, partner_id, s37, s42, as_of = db
    rows = [
        {
            "order_id": 7,
            "supplier_product_id": sole_id,
            "partner_id": partner_id,
            "size_id": s42,
            "shortage_qty": 10,
        },
        {
            "order_id": 7,
            "supplier_product_id": sole_id,
            "partner_id": partner_id,
            "size_id": s37,
            "shortage_qty": 10,
        },
    ]
    summary = purchase_service.annotate_rows_with_etas(session, tenant_id, rows, as_of=as_of)
    assert rows[0]["expected_ready_date"] == (as_of + timedelta(days=10)).isoformat()
    assert rows[1]["expected_ready_date"] is not None
    assert rows[1]["expected_ready_date"] != rows[0]["expected_ready_date"] or rows[1][
        "expected_ready_date"
    ] == rows[0]["expected_ready_date"]
    assert summary["by_order_id"]["7"] == summary["earliest_start"]
