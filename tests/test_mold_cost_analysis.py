"""模具成本分析：按产品开发的楦、鞋底模具、鞋跟型号归组，刀模编号等于工厂型号。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Department,
    Order,
    OrderStatus,
    OwnProduct,
    Partner,
    Shipment,
    ShipmentStatus,
    Size,
    SupplierProduct,
    Tenant,
    ToolingItem,
    ToolingReceipt,
    ToolingReceiptLine,
    ToolingReceiptSize,
)
from app.services.mold_cost_service import mold_cost_report, mold_unit_costs_by_product


@pytest.fixture()
def mold_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="模具成本厂", settings_json={})
    session.add(tenant)
    session.flush()
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True, is_active=True)
    session.add(supplier)
    session.flush()
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    prod = Department(tenant_id=tenant.id, name="生产部", is_active=True, sort_order=1)
    dev = Department(tenant_id=tenant.id, name="开发部", is_active=True, sort_order=2)
    session.add_all([size, prod, dev])
    session.flush()
    yield session, tenant, supplier, size, prod, dev
    session.close()


def _card(db, tenant_id, supplier_id, code):
    card = SupplierProduct(
        tenant_id=tenant_id,
        product_code=code,
        name=code,
        partner_id=supplier_id,
        is_active=True,
    )
    db.add(card)
    db.flush()
    return card


def _product(db, tenant_id, code, *, last, sole, heel_id):
    product = OwnProduct(
        tenant_id=tenant_id,
        product_code=code,
        product_year=2026,
        season="SP",
        shoe_last=last,
        sole_mold=sole,
        heel_model_id=heel_id,
        is_active=True,
    )
    db.add(product)
    db.flush()
    return product


def _receive(db, tenant, supplier, size, kind, code, price, qty, department_id):
    item = db.query(ToolingItem).filter_by(tenant_id=tenant.id, code=code).one_or_none()
    if item is None:
        item = ToolingItem(tenant_id=tenant.id, code=code, kind=kind, is_active=True)
        db.add(item)
        db.flush()
    receipt = ToolingReceipt(
        tenant_id=tenant.id,
        receipt_no=f"R-{kind}-{code}-{department_id}",
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        receipt_date=date(2026, 10, 1),
    )
    db.add(receipt)
    db.flush()
    line = ToolingReceiptLine(
        tenant_id=tenant.id,
        receipt_id=receipt.id,
        department_id=department_id,
        tooling_item_id=item.id,
        unit_price=Decimal(str(price)),
    )
    db.add(line)
    db.flush()
    db.add(
        ToolingReceiptSize(
            tenant_id=tenant.id,
            line_id=line.id,
            size_id=size.id,
            qty=Decimal(str(qty)),
        )
    )


def _ship(db, tenant, product, qty):
    order = Order(
        tenant_id=tenant.id,
        order_no=f"MO-{product.product_code}",
        customer_name="客户",
        own_product_id=product.id,
        total_qty=qty,
        status=OrderStatus.completed,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant.id,
            shipment_no=f"SH-{product.product_code}",
            order_id=order.id,
            customer_name="客户",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 10, 2),
            total_qty=qty,
            amount=Decimal("0"),
        )
    )


def test_mold_cost_groups_by_product_development_and_allocates_by_shipped_qty(mold_db):
    db, tenant, supplier, size, prod, dev = mold_db
    heel_a = _card(db, tenant.id, supplier.id, "g123a")
    heel_b = _card(db, tenant.id, supplier.id, "g123b")
    uppers = [
        ("45677", "d123a", heel_a.id, 1000, "100"),
        ("345635", "d123a", heel_a.id, 700, "110"),
        ("57856", "d123a", heel_a.id, 300, "100"),
        ("67", "d123b", heel_b.id, 900, "100"),
        ("46746", "d123b", heel_b.id, 800, "100"),
        ("46748", "d123b", heel_b.id, 750, "100"),
    ]
    for code, sole, heel_id, shipped, knife_price in uppers:
        product = _product(db, tenant.id, code, last="x123", sole=sole, heel_id=heel_id)
        _ship(db, tenant, product, shipped)
        _receive(db, tenant, supplier, size, "knife_die", code, knife_price, 6, prod.id)
    _receive(db, tenant, supplier, size, "shoe_last", "x123", "30", 500, prod.id)
    _receive(db, tenant, supplier, size, "sole_mold", "d123a", "5000", 6, prod.id)
    _receive(db, tenant, supplier, size, "sole_mold", "d123b", "5500", 6, prod.id)
    _receive(db, tenant, supplier, size, "heel_mold", "g123a", "300", 6, prod.id)
    _receive(db, tenant, supplier, size, "heel_mold", "g123b", "350", 6, prod.id)
    # 开发部同编号到货不进模具成本。
    _receive(db, tenant, supplier, size, "shoe_last", "x123", "30", 100, dev.id)
    plain = OwnProduct(tenant_id=tenant.id, product_code="PLAIN", product_year=2026, season="SP")
    db.add(plain)
    # 填了楦、鞋底、鞋跟编号，但生产部没有对应金额，不统计。
    empty_heel = _card(db, tenant.id, supplier.id, "no-heel")
    _product(db, tenant.id, "re67567", last="no-money", sole="no-sole", heel_id=empty_heel.id)
    db.commit()

    rows = mold_cost_report(db, tenant.id)["rows"]
    assert [row["factory_model"] for row in rows] == [
        "345635",
        "45677",
        "57856",
        "46746",
        "46748",
        "67",
    ]
    models = {row["factory_model"] for row in rows}
    assert "PLAIN" not in models
    assert "re67567" not in models

    first = rows[0]
    assert first["last_code"] == "x123"
    assert first["last_qty"] == 500
    assert first["last_amount"] == 15000
    assert first["last_share"] == "3.37元/双"
    assert first["last_key"] == rows[5]["last_key"]

    sole_a = [row for row in rows if row["sole_code"] == "d123a"]
    assert len(sole_a) == 3
    assert sole_a[0]["sole_qty"] == 6
    assert sole_a[0]["sole_amount"] == 30000
    assert sole_a[0]["sole_share"] == "15元/双"
    assert sole_a[0]["heel_code"] == "g123a"
    assert sole_a[0]["heel_amount"] == 1800
    assert sole_a[0]["heel_share"] == "0.9元/双"
    assert {row["sole_key"] for row in sole_a} == {sole_a[0]["sole_key"]}

    sole_b = [row for row in rows if row["sole_code"] == "d123b"]
    assert sole_b[0]["sole_amount"] == 33000
    assert sole_b[0]["sole_share"] == "13.47元/双"
    assert sole_b[0]["heel_share"] == "0.86元/双"

    knife = next(row for row in rows if row["factory_model"] == "45677")
    assert knife["knife_code"] == "45677"
    assert knife["knife_qty"] == 6
    assert knife["knife_amount"] == 600
    assert knife["knife_share"] == "0.6元/双"
    assert knife["shipped_qty"] == 1000

    second = next(row for row in rows if row["factory_model"] == "345635")
    assert second["knife_code"] == "345635"
    assert second["knife_amount"] == 660
    assert second["knife_share"] == "0.94元/双"

    units = mold_unit_costs_by_product(db, tenant.id)
    shared = db.query(OwnProduct).filter_by(tenant_id=tenant.id, product_code="345635").one()
    assert units[shared.id]["last"] == Decimal("3.37")
    assert units[shared.id]["sole"] == Decimal("15.00")
    assert units[shared.id]["heel"] == Decimal("0.90")
    assert units[shared.id]["knife"] == Decimal("0.94")
