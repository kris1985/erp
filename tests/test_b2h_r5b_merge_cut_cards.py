"""B2h-R5b：合批批量开裁打主码 + 列表主码。"""

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
    OrderStatus,
    OwnProduct,
    Size,
    Tenant,
    TraceUnit,
)
from app.services import merge_batch_service
from app.services.merge_batch_service import MergeBatchError


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


def _seed(db, *, trace_enabled=True):
    tenant = Tenant(name="合批开裁厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="白", code="WH")
    s40 = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    s41 = Size(tenant_id=tenant.id, size_value="41", sort_order=1)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="MB-CUT",
        quote_price=Decimal("80"),
        trace_enabled=trace_enabled,
    )
    db.add_all([color, s40, s41, product])
    db.flush()

    def make_order(no: str, qtys: list[tuple[Size, int]], customer: str):
        total = sum(q for _, q in qtys)
        o = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name=customer,
            own_product_id=product.id,
            total_qty=total,
            delivery_date=date.today() + timedelta(days=10),
            status=OrderStatus.confirmed,
        )
        db.add(o)
        db.flush()
        for size, qty in qtys:
            db.add(
                OrderItem(
                    tenant_id=tenant.id,
                    order_id=o.id,
                    color_id=color.id,
                    size_id=size.id,
                    qty=qty,
                )
            )
        return o

    o1 = make_order("MBC-A", [(s40, 40), (s41, 20)], "甲")
    o2 = make_order("MBC-B", [(s40, 30)], "乙")
    db.commit()
    batch = merge_batch_service.create_merge_batch(
        db, tenant.id, [o1.id, o2.id], require_same_color=True
    )
    return {
        "tenant": tenant,
        "product": product,
        "o1": o1,
        "o2": o2,
        "batch": batch,
        "color": color,
        "s40": s40,
        "s41": s41,
    }


def test_merge_cut_cards_dry_run_no_write(db):
    ctx = _seed(db)
    data = merge_batch_service.preview_or_create_merge_cut_cards(
        db,
        ctx["tenant"].id,
        ctx["batch"]["id"],
        dry_run=True,
    )
    assert data["to_create"] == 3  # A:2 + B:1
    assert len(data["members"]) == 2
    assert data["created_count"] == 0
    assert data["print_path"].endswith("?mode=main-codes")
    n = db.scalar(select(TraceUnit).where(TraceUnit.tenant_id == ctx["tenant"].id))
    assert n is None


def test_merge_cut_cards_create_once_all_members(db):
    ctx = _seed(db)
    data = merge_batch_service.preview_or_create_merge_cut_cards(
        db,
        ctx["tenant"].id,
        ctx["batch"]["id"],
        dry_run=False,
    )
    assert data["created_count"] == 3
    assert data["to_create"] == 3
    units = list(
        db.scalars(select(TraceUnit).where(TraceUnit.tenant_id == ctx["tenant"].id)).all()
    )
    assert len(units) == 3
    by_order = {}
    for u in units:
        by_order.setdefault(u.order_id, []).append(u)
    assert len(by_order[ctx["o1"].id]) == 2
    assert len(by_order[ctx["o2"].id]) == 1

    listed = merge_batch_service.list_merge_batch_trace_units(
        db, ctx["tenant"].id, ctx["batch"]["id"]
    )
    assert listed["unit_count"] == 3
    assert len(listed["members"]) == 2

    again = merge_batch_service.preview_or_create_merge_cut_cards(
        db,
        ctx["tenant"].id,
        ctx["batch"]["id"],
        dry_run=False,
    )
    assert again["to_create"] == 0
    assert again["created_count"] == 0


def test_merge_cut_cards_requires_trace(db):
    ctx = _seed(db, trace_enabled=False)
    with pytest.raises(MergeBatchError) as ei:
        merge_batch_service.preview_or_create_merge_cut_cards(
            db,
            ctx["tenant"].id,
            ctx["batch"]["id"],
            dry_run=True,
        )
    assert "追溯" in ei.value.message
