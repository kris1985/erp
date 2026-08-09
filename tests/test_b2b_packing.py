"""B2b：配码装箱 — 单码/混码合计一致 + 验箱错码拦。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
from app.services import packing_service
from app.services.packing_service import PackingError


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
    tenant = Tenant(name="装箱厂")
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="红", code="R")
    c2 = Color(tenant_id=tenant.id, name="黑", code="BK")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    s38 = Size(tenant_id=tenant.id, size_value="38", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="箱唛款", quote_price=Decimal("68"))
    db.add_all([c1, c2, s37, s38, product])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="PK-001",
        customer_name="箱唛客户",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=30,
        delivery_date=date.today() + timedelta(days=7),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add_all(
        [
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s37.id, qty=10
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s38.id, qty=8
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c2.id, size_id=s37.id, qty=12
            ),
        ]
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "c1": c1,
        "c2": c2,
        "s37": s37,
        "s38": s38,
    }


def test_single_size_pack_totals(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["mode"] == "single_size"
    assert plan["carton_count"] == 3
    assert sum(c["total_qty"] for c in plan["cartons"]) == 30
    for c in plan["cartons"]:
        assert len(c["lines"]) == 1


def test_mixed_pack_and_label_fields(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["carton_count"] == 3
    assert plan["cartons"][0]["order_no"] == "PK-001"
    assert plan["cartons"][0]["product_code"] == "箱唛款"
    assert plan["cartons"][0]["customer_name"] == "箱唛客户"
    assert plan["cartons"][0]["code"].startswith("CTN-PK-001-")


def test_verify_blocks_wrong_and_accepts_match(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    carton = plan["cartons"][0]
    line = carton["lines"][0]
    with pytest.raises(PackingError) as ei:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"] + 1}],
        )
    assert ei.value.code in ("over_pack", "wrong_size")

    with pytest.raises(PackingError) as ei2:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[
                {
                    "color_id": ctx["c2"].id,
                    "size_id": ctx["s38"].id,
                    "qty": line["qty"],
                }
            ],
        )
    assert ei2.value.code in ("wrong_size", "mismatch")

    ok = packing_service.verify_packing_carton(
        db,
        ctx["tenant"].id,
        carton["id"],
        lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"]}],
    )
    assert ok["verified_at"]
