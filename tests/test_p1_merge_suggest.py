"""P1-6：合批推荐 — 同款同色交期窗、齐套门槛、最小量；HITL 不落库。"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
from app.services import merge_batch_service, merge_suggest_service, schedule_settings


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
    tenant = Tenant(name="荐批厂", settings_json={"schedule": {}})
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="米白", code="MB")
    c2 = Color(tenant_id=tenant.id, name="黑", code="BK")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    p1 = OwnProduct(tenant_id=tenant.id, product_code="荐批款A", quote_price=Decimal("80"))
    p2 = OwnProduct(tenant_id=tenant.id, product_code="荐批款B", quote_price=Decimal("90"))
    db.add_all([c1, c2, s37, p1, p2])
    db.flush()

    def make_order(no: str, product, color, qty: int, delivery: date):
        o = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name="客",
            own_product_id=product.id,
            style_id=product.id,
            total_qty=qty,
            delivery_date=delivery,
            status=OrderStatus.confirmed,
        )
        db.add(o)
        db.flush()
        db.add(
            OrderItem(
                tenant_id=tenant.id,
                order_id=o.id,
                color_id=color.id,
                size_id=s37.id,
                qty=qty,
            )
        )
        return o

    today = date.today()
    o1 = make_order("SG-1", p1, c1, 100, today + timedelta(days=3))
    o2 = make_order("SG-2", p1, c1, 120, today + timedelta(days=5))  # within 7d of o1
    o3 = make_order("SG-3", p1, c1, 80, today + timedelta(days=20))  # outside window vs o1/o2
    o4 = make_order("SG-4", p1, c2, 90, today + timedelta(days=4))  # diff color
    o5 = make_order("SG-5", p2, c1, 50, today + timedelta(days=4))  # diff product
    o6 = make_order("SG-6", p2, c1, 60, today + timedelta(days=5))
    db.commit()
    return {
        "tenant": tenant,
        "c1": c1,
        "c2": c2,
        "p1": p1,
        "p2": p2,
        "orders": [o1, o2, o3, o4, o5, o6],
    }


def _kit_ok_ctx(order_ids, *, blocked: set[int] | None = None):
    blocked = blocked or set()

    class FakeCtx:
        def summary_for_order(self, order_id: int):
            ok = order_id not in blocked
            return {"kit_ok": ok, "first_kit_ok": ok}

    return FakeCtx()


def test_suggest_same_style_color_window(db):
    s = _seed(db)
    tid = s["tenant"].id
    with (
        patch("app.services.merge_suggest_service.material_service.ensure_material_snapshot"),
        patch(
            "app.services.merge_suggest_service.material_service.build_kit_context",
            return_value=_kit_ok_ctx([o.id for o in s["orders"]]),
        ),
    ):
        out = merge_suggest_service.suggest_merge_batches(db, tid)
    assert out["params"]["merge_delivery_window_days"] == 7
    items = out["items"]
    # p1+c1: o1+o2 together; o3 alone (outside) → one suggestion of 2
    # p2+c1: o5+o6
    assert len(items) >= 2
    groups = {tuple(sorted(it["order_ids"])) for it in items}
    assert tuple(sorted([s["orders"][0].id, s["orders"][1].id])) in groups
    assert tuple(sorted([s["orders"][4].id, s["orders"][5].id])) in groups
    # o4 alone different color — not with o1/o2
    for it in items:
        assert s["orders"][3].id not in it["order_ids"] or len(it["order_ids"]) == 1


def test_suggest_skips_not_kit(db):
    s = _seed(db)
    tid = s["tenant"].id
    blocked = {s["orders"][1].id}  # SG-2 not kit → o1 alone in window
    with (
        patch("app.services.merge_suggest_service.material_service.ensure_material_snapshot"),
        patch(
            "app.services.merge_suggest_service.material_service.build_kit_context",
            return_value=_kit_ok_ctx([], blocked=blocked),
        ),
    ):
        out = merge_suggest_service.suggest_merge_batches(db, tid)
    assert out["skipped"]["not_kit"] >= 1
    for it in out["items"]:
        assert s["orders"][1].id not in it["order_ids"]


def test_suggest_min_qty_filter(db):
    s = _seed(db)
    tid = s["tenant"].id
    schedule_settings.save_schedule_patch(db, tid, {"merge_min_qty": 500})
    with (
        patch("app.services.merge_suggest_service.material_service.ensure_material_snapshot"),
        patch(
            "app.services.merge_suggest_service.material_service.build_kit_context",
            return_value=_kit_ok_ctx([o.id for o in s["orders"]]),
        ),
    ):
        out = merge_suggest_service.suggest_merge_batches(db, tid)
    assert out["items"] == []


def test_suggest_does_not_write_batch(db):
    s = _seed(db)
    tid = s["tenant"].id
    with (
        patch("app.services.merge_suggest_service.material_service.ensure_material_snapshot"),
        patch(
            "app.services.merge_suggest_service.material_service.build_kit_context",
            return_value=_kit_ok_ctx([o.id for o in s["orders"]]),
        ),
    ):
        merge_suggest_service.suggest_merge_batches(db, tid)
    listed = merge_batch_service.list_merge_batches(db, tid)
    assert listed == []


def test_adopt_via_create(db):
    s = _seed(db)
    tid = s["tenant"].id
    o1, o2 = s["orders"][0], s["orders"][1]
    batch = merge_batch_service.create_merge_batch(
        db, tid, [o1.id, o2.id], require_same_color=True, note="采纳荐批"
    )
    assert batch["member_count"] == 2
    with (
        patch("app.services.merge_suggest_service.material_service.ensure_material_snapshot"),
        patch(
            "app.services.merge_suggest_service.material_service.build_kit_context",
            return_value=_kit_ok_ctx([o.id for o in s["orders"]]),
        ),
    ):
        out = merge_suggest_service.suggest_merge_batches(db, tid)
    # already in batch → not re-suggested together
    for it in out["items"]:
        assert o1.id not in it["order_ids"]
        assert o2.id not in it["order_ids"]
