"""P1-5：缺料导出 Excel 含款号/齐套日/风险；推送消息组装。"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderStatus,
    OwnProduct,
    Partner,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import shortage_export_service


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


def _seed(db):
    tenant = Tenant(name="缺料导出厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="MAT-01",
        name="大底黑",
        unit_price=Decimal("1"),
    )
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    product = OwnProduct(tenant_id=tenant.id, product_code="款A-01", quote_price=Decimal("80"))
    db.add_all([sp, color, size, product])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="SH-EXP-1",
        customer_name="客户",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=100,
        delivery_date=date.today() - timedelta(days=1),
        status=OrderStatus.confirmed,
        is_rush=True,
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
        OrderMaterialRequirement(
            tenant_id=tenant.id,
            order_id=order.id,
            supplier_product_id=sp.id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("100"),
            arrived_qty=Decimal("0"),
            issued_qty=Decimal("0"),
            is_customer_supplied=False,
        )
    )
    db.commit()
    return {"tenant": tenant, "order": order, "product": product, "sp": sp}


def test_workbook_contains_product_and_risk_headers(db):
    s = _seed(db)
    tid = s["tenant"].id

    fake_rows = [
        {
            "order_id": s["order"].id,
            "order_no": "SH-EXP-1",
            "supplier_product_code": "MAT-01",
            "supplier_product_name": "大底黑",
            "shortage_qty": 100,
            "to_buy_qty": 100,
            "is_rush": True,
            "partner_name": "供应商甲",
        }
    ]

    with (
        patch("app.services.shortage_export_service.material_service.list_shortages", return_value=fake_rows),
        patch(
            "app.services.shortage_export_service.annotate_rows_with_etas",
            return_value={"by_order_id": {str(s["order"].id): (date.today() + timedelta(days=2)).isoformat()}},
        ),
        patch(
            "app.services.shortage_export_service.progress_service.progress_board",
            return_value={"orders": [{"id": s["order"].id, "overall_percent": 5}]},
        ),
        patch(
            "app.services.shortage_export_service.material_service.order_kit_summaries",
            return_value={s["order"].id: {"kit_ok": False}},
        ),
    ):
        rows = shortage_export_service.build_shortage_export_rows(db, tid)
        content = shortage_export_service.build_shortage_workbook(rows)

    assert rows
    assert rows[0]["product_code"] == "款A-01"
    assert rows[0]["kit_ready_date"]
    assert rows[0]["risk_level"] in ("red", "yellow")
    assert content[:2] == b"PK"  # xlsx zip


def test_push_message_mentions_shortage(db):
    s = _seed(db)
    rows = [
        {
            "order_no": "SH-EXP-1",
            "product_code": "款A-01",
            "supplier_product_name": "大底黑",
            "shortage_qty": 12,
            "kit_ready_date": "2026-08-12",
            "risk_level": "red",
            "risk_label": "高风险",
        }
    ]
    msg = shortage_export_service.build_shortage_push_message(db, s["tenant"].id, rows)
    content = msg["message"]["text"]["content"]
    assert "缺料催办" in content
    assert "SH-EXP-1" in content
    assert "款A-01" in content
