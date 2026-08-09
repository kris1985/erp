"""P1-4：排产池按合批筛选 + 行上带合批号。"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
from app.services import merge_batch_service, schedule_service


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
    tenant = Tenant(name="池筛厂")
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="米白", code="MB")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    p1 = OwnProduct(tenant_id=tenant.id, product_code="池筛款", quote_price=Decimal("80"))
    db.add_all([c1, s37, p1])
    db.flush()

    def make(no: str, qty: int):
        o = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name="客",
            own_product_id=p1.id,
            style_id=p1.id,
            total_qty=qty,
            delivery_date=date.today() + timedelta(days=7),
            status=OrderStatus.confirmed,
        )
        db.add(o)
        db.flush()
        db.add(
            OrderItem(
                tenant_id=tenant.id,
                order_id=o.id,
                color_id=c1.id,
                size_id=s37.id,
                qty=qty,
            )
        )
        return o

    o1, o2, o3 = make("POOL-1", 10), make("POOL-2", 20), make("POOL-3", 30)
    db.commit()
    batch = merge_batch_service.create_merge_batch(db, tenant.id, [o1.id, o2.id])
    return {"tenant": tenant, "orders": [o1, o2, o3], "batch": batch}


class _Kit:
    def summary_for_order(self, order_id: int):
        return {"kit_ok": True, "first_kit_ok": True}


def test_pool_filter_by_merge_batch(db):
    s = _seed(db)
    tid = s["tenant"].id
    bid = s["batch"]["id"]
    with (
        patch("app.services.schedule_service.material_service.ensure_material_snapshot"),
        patch("app.services.schedule_service.material_service.build_kit_context", return_value=_Kit()),
    ):
        all_rows = schedule_service.list_schedule_pool(db, tid, hide_scheduled=False)
        filtered = schedule_service.list_schedule_pool(
            db, tid, hide_scheduled=False, merge_batch_id=bid
        )
    assert len(all_rows) == 3
    assert {r["order_no"] for r in filtered} == {"POOL-1", "POOL-2"}
    for r in filtered:
        assert r["merge_batch_id"] == bid
        assert r["merge_batch_no"] == s["batch"]["batch_no"]
    alone = next(r for r in all_rows if r["order_no"] == "POOL-3")
    assert alone["merge_batch_id"] is None
