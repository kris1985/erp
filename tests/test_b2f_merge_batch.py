"""B2f：合批 — 同款硬拦、同色默认、汇总色码、移出成员。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
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


def _seed(db):
    tenant = Tenant(name="合批厂")
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="米白", code="MB")
    c2 = Color(tenant_id=tenant.id, name="黑", code="BK")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    s38 = Size(tenant_id=tenant.id, size_value="38", sort_order=1)
    p1 = OwnProduct(tenant_id=tenant.id, product_code="合批款A", quote_price=Decimal("80"))
    p2 = OwnProduct(tenant_id=tenant.id, product_code="合批款B", quote_price=Decimal("90"))
    db.add_all([c1, c2, s37, s38, p1, p2])
    db.flush()

    def make_order(no: str, product, color, qtys: list[tuple], customer: str):
        total = sum(q for _, q in qtys)
        o = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name=customer,
            own_product_id=product.id,
            style_id=product.id,
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

    o1 = make_order("MB-O1", p1, c1, [(s37, 10), (s38, 20)], "客户甲")
    o2 = make_order("MB-O2", p1, c1, [(s37, 5), (s38, 15)], "客户乙")
    o3 = make_order("MB-O3", p1, c2, [(s37, 8)], "客户丙")
    o4 = make_order("MB-O4", p2, c1, [(s37, 12)], "客户丁")
    db.commit()
    return {
        "tenant": tenant,
        "c1": c1,
        "c2": c2,
        "s37": s37,
        "s38": s38,
        "p1": p1,
        "p2": p2,
        "o1": o1,
        "o2": o2,
        "o3": o3,
        "o4": o4,
    }


def test_create_rejects_diff_product(db):
    ctx = _seed(db)
    with pytest.raises(MergeBatchError) as ei:
        merge_batch_service.create_merge_batch(
            db, ctx["tenant"].id, [ctx["o1"].id, ctx["o4"].id]
        )
    assert ei.value.code == "diff_product"


def test_create_same_color_summary_and_remove(db):
    ctx = _seed(db)
    batch = merge_batch_service.create_merge_batch(
        db, ctx["tenant"].id, [ctx["o1"].id, ctx["o2"].id]
    )
    assert batch["member_count"] == 2
    assert batch["total_qty"] == 50  # 30+20
    assert batch["product_code"] == "合批款A"
    by_key = {(r["color_id"], r["size_id"]): r["qty"] for r in batch["size_summary"]}
    assert by_key[(ctx["c1"].id, ctx["s37"].id)] == 15
    assert by_key[(ctx["c1"].id, ctx["s38"].id)] == 35
    assert any(m["order_no"] == "MB-O1" for m in batch["members"])
    assert any(m["customer_name"] == "客户乙" for m in batch["members"])

    with pytest.raises(MergeBatchError) as ei:
        merge_batch_service.create_merge_batch(
            db, ctx["tenant"].id, [ctx["o1"].id, ctx["o2"].id]
        )
    assert ei.value.code == "already_in_batch"

    updated = merge_batch_service.remove_member(
        db, ctx["tenant"].id, batch["id"], ctx["o2"].id
    )
    assert updated["member_count"] == 1
    assert updated["total_qty"] == 30


def test_default_same_color_blocks_mixed(db):
    ctx = _seed(db)
    with pytest.raises(MergeBatchError) as ei:
        merge_batch_service.create_merge_batch(
            db, ctx["tenant"].id, [ctx["o1"].id, ctx["o3"].id]
        )
    assert ei.value.code == "diff_color"

    ok = merge_batch_service.create_merge_batch(
        db,
        ctx["tenant"].id,
        [ctx["o1"].id, ctx["o3"].id],
        require_same_color=False,
    )
    assert ok["member_count"] == 2
    assert ok["total_qty"] == 38
