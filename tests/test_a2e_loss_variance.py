"""A2e：实耗 vs 标准损耗预警 — 复用用料行 required_qty/issued_qty 规则扫描。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    OwnProduct,
    Partner,
    SupplierProduct,
    Tenant,
)
from app.services import material_service
from app.services.loss_variance_service import scan_loss_variance, loss_variance_summary


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


def _setup(db):
    tenant = Tenant(name="损耗厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    db.add(partner)
    product = OwnProduct(tenant_id=tenant.id, product_code="A2E-款", is_active=True)
    db.add(product)
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-LEATHER",
        name="黑皮",
        partner_id=partner.id,
        unit_price=Decimal("20"),
        is_active=True,
    )
    db.add(sp)
    db.commit()
    return tenant, product, sp


def _order(db, tenant_id, product_id, *, order_no, qty=100, status=OrderStatus.in_progress, created_days_ago=1, is_rush=False):
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户A",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=date.today() + timedelta(days=7),
        status=status,
        is_rush=is_rush,
        created_at=datetime.now() - timedelta(days=created_days_ago),
    )
    db.add(order)
    db.commit()
    return order


def _requirement(db, tenant_id, order, sp_id, *, qty_per_pair, loss_rate, loss_fixed_qty, issued_qty, is_customer_supplied=False):
    required = material_service.calc_required_qty(
        Decimal(str(qty_per_pair)), order.total_qty, Decimal(str(loss_rate)), Decimal(str(loss_fixed_qty))
    )
    row = OrderMaterialRequirement(
        tenant_id=tenant_id,
        order_id=order.id,
        supplier_product_id=sp_id,
        qty_per_pair=Decimal(str(qty_per_pair)),
        loss_rate=Decimal(str(loss_rate)),
        loss_fixed_qty=Decimal(str(loss_fixed_qty)),
        required_qty=required,
        issued_qty=Decimal(str(issued_qty)),
        is_customer_supplied=is_customer_supplied,
    )
    db.add(row)
    db.commit()
    return row


def test_over_threshold_is_flagged(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-OVER", qty=100)
    # standard = 1*100*(1+0.05)+0 = 105；发 130 > 105*1.1=115.5 → 超标
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0.05, loss_fixed_qty=0, issued_qty=130)

    rows = scan_loss_variance(db, tenant.id)
    assert len(rows) == 1
    r = rows[0]
    assert r["order_no"] == "O-OVER"
    assert r["required_qty"] == pytest.approx(105.0)
    assert r["issued_qty"] == pytest.approx(130.0)
    assert r["over_qty"] == pytest.approx(25.0)
    assert r["over_pct"] == pytest.approx(23.8, abs=0.1)
    assert r["supplier_product_name"] == "黑皮"


def test_within_threshold_not_flagged(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-OK", qty=100)
    # standard = 105；发 110 < 115.5 → 不超标
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0.05, loss_fixed_qty=0, issued_qty=110)

    rows = scan_loss_variance(db, tenant.id)
    assert rows == []


def test_boundary_at_exact_threshold_not_flagged(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-BOUND", qty=100)
    # standard = 100；threshold 10% → cap=110；发=110 恰好等于 cap，不严格大于 → 不算超标
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=110)

    rows = scan_loss_variance(db, tenant.id, threshold=Decimal("0.10"))
    assert rows == []

    rows2 = scan_loss_variance(db, tenant.id, threshold=Decimal("0.099"))
    assert len(rows2) == 1


def test_not_issued_not_flagged(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-NOISSUE", qty=100)
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0.05, loss_fixed_qty=0, issued_qty=0)

    rows = scan_loss_variance(db, tenant.id)
    assert rows == []


def test_zero_standard_with_issue_is_flagged_without_pct(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-ZEROSTD", qty=0)
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=5)

    rows = scan_loss_variance(db, tenant.id)
    assert len(rows) == 1
    assert rows[0]["required_qty"] == 0
    assert rows[0]["over_pct"] is None
    assert rows[0]["over_qty"] == pytest.approx(5.0)


def test_cancelled_order_excluded(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-CANCEL", qty=100, status=OrderStatus.cancelled)
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=999)

    rows = scan_loss_variance(db, tenant.id)
    assert rows == []


def test_outside_days_window_excluded(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-OLD", qty=100, created_days_ago=200)
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=999)

    rows = scan_loss_variance(db, tenant.id, days=90)
    assert rows == []
    # 放大窗口即可看到
    rows2 = scan_loss_variance(db, tenant.id, days=365)
    assert len(rows2) == 1


def test_sorted_by_over_qty_desc(db):
    tenant, product, sp = _setup(db)
    o1 = _order(db, tenant.id, product.id, order_no="O-SMALL", qty=100)
    _requirement(db, tenant.id, o1, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=150)
    o2 = _order(db, tenant.id, product.id, order_no="O-BIG", qty=100)
    _requirement(db, tenant.id, o2, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=300)

    rows = scan_loss_variance(db, tenant.id)
    assert [r["order_no"] for r in rows] == ["O-BIG", "O-SMALL"]


def test_customer_supplied_rows_still_participate(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-CS", qty=100)
    _requirement(
        db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0, loss_fixed_qty=0, issued_qty=200, is_customer_supplied=True
    )

    rows = scan_loss_variance(db, tenant.id)
    assert len(rows) == 1
    assert rows[0]["is_customer_supplied"] is True


def test_loss_variance_summary_shape(db):
    tenant, product, sp = _setup(db)
    order = _order(db, tenant.id, product.id, order_no="O-SUM", qty=100)
    _requirement(db, tenant.id, order, sp.id, qty_per_pair=1, loss_rate=0.05, loss_fixed_qty=0, issued_qty=130)

    summary = loss_variance_summary(db, tenant.id)
    assert summary["flagged_count"] == 1
    assert summary["order_count"] == 1
    assert summary["threshold_pct"] == 10.0
    assert "O-SUM" in summary["summary"]
    assert len(summary["rows"]) == 1


def test_summary_empty_state(db):
    tenant, product, sp = _setup(db)
    summary = loss_variance_summary(db, tenant.id)
    assert summary["flagged_count"] == 0
    assert summary["order_count"] == 0
    assert summary["rows"] == []
