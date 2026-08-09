"""P1-3：今日行动 facts 引用 A1b 风险码 + 齐套日。"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Order, OrderStatus, OwnProduct, Tenant
from app.services import analytics


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


def test_risk_evidence_lines_include_codes(db):
    tenant = Tenant(name="风险厂")
    db.add(tenant)
    db.flush()
    p = OwnProduct(tenant_id=tenant.id, product_code="R1", quote_price=Decimal("10"))
    db.add(p)
    db.flush()
    o = Order(
        tenant_id=tenant.id,
        order_no="RISK-1",
        customer_name="客",
        own_product_id=p.id,
        style_id=p.id,
        total_qty=10,
        delivery_date=date.today() - timedelta(days=2),
        status=OrderStatus.in_progress,
        is_rush=True,
    )
    db.add(o)
    db.commit()

    with patch(
        "app.services.analytics.material_service.order_kit_summaries",
        return_value={
            o.id: {
                "kit_ok": False,
                "kit_ready_date": date.today() + timedelta(days=3),
            }
        },
    ):
        lines = analytics._risk_evidence_lines(
            db,
            tenant.id,
            [
                {
                    "order_id": o.id,
                    "order_no": o.order_no,
                    "delivery_date": o.delivery_date,
                    "is_rush": True,
                    "overall_percent": 10,
                    "kit_ok": False,
                }
            ],
        )
    assert lines
    assert "RISK-1" in lines[0]
    assert "overdue" in lines[0] or "rush" in lines[0] or "material" in lines[0]
    assert "kit_ready" in lines[0] or "齐套日" in lines[0]
