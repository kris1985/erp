"""AU-I0 M2：开裁只出流转卡（筐），不生成扎捆码。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    Size,
    Tenant,
    TraceUnit,
    TraceUnitType,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order
from app.services.trace_service import preview_or_create_cut_cards


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
    tenant = Tenant(name="开裁厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="白", code="W"))
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=0))
    session.commit()
    yield session
    session.close()


def _product_with_process(db, code: str = "CUT-BB"):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1"),
        sort_order=1,
    )
    db.add(proc)
    db.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code=code,
        is_active=True,
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    db.commit()
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            own_product_id=product.id,
            customer_name="C",
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=40)],
        ),
        created_by=None,
    )
    return tenant, order


def test_cut_cards_basket_only(db):
    """开裁恒出筐：mode 参数（含历史 basket_bundles）不再影响结果，不生成捆。"""
    tenant, order = _product_with_process(db)
    preview = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=True,
        mode="basket_bundles",
        bundle_size=40,
    )
    assert preview["mode"] == "basket"
    assert preview["to_create"] == 1
    assert preview["strategy"]["parts"] == 0

    result = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        mode="basket_bundles",
        bundle_size=40,
    )
    units = list(db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all())
    baskets = [u for u in units if u.unit_type == TraceUnitType.basket]
    bundles = [u for u in units if u.unit_type == TraceUnitType.bundle]
    assert len(baskets) == 1
    assert len(bundles) == 0
    assert baskets[0].qty == 40
    assert result["created"][0]["unit_type"] == "basket"
    assert result["created"][0].get("children") is None


def test_cut_cards_multiple_baskets(db):
    """40双、筐量20 → 2 筐；拆筐逻辑不变。"""
    tenant, order = _product_with_process(db, code="CUT-MULTI")
    preview = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=True,
        mode="bundles",
        bundle_size=20,
    )
    assert preview["mode"] == "basket"
    assert preview["to_create"] == 2

    result = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        mode="bundles",
        bundle_size=20,
    )
    units = list(db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all())
    assert len(units) == 2
    assert all(u.unit_type == TraceUnitType.basket for u in units)
    assert {u.qty for u in units} == {20, 20}
    assert all(u.parent_id is None for u in units)
    assert result["created"][0]["unit_type"] == "basket"


def test_cut_cards_old_modes_all_basket(db):
    """历史 mode（bundles / basket）均收敛为仅筐；不再有 trace_requires_bundle。"""
    tenant, order = _product_with_process(db, code="CUT-OLD")
    for mode in ("bundles", "basket", "basket_bundles", None):
        preview = preview_or_create_cut_cards(
            db,
            tenant_id=tenant.id,
            order_id=order.id,
            dry_run=True,
            mode=mode,
            bundle_size=40,
        )
        assert preview["mode"] == "basket"
        assert all(u["unit_type"] == "basket" for u in preview["lines"][0]["planned_units"])
