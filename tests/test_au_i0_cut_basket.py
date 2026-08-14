"""AU-I0 M2：开裁 1 筐 N 捆。"""

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
    OwnProductPart,
    PartDefinition,
    ProcessDefinition,
    Size,
    Tenant,
    TraceUnit,
    TraceUnitType,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order
from app.services.trace_service import TraceError, preview_or_create_cut_cards


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


def _product_with_parts(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    tongue = PartDefinition(tenant_id=tenant.id, code="SX", name="鞋舌", source="裁断")
    db.add_all([front, tongue])
    db.flush()
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
        product_code="CUT-BB",
        is_active=True,
        trace_enabled=True,
    )
    db.add(product)
    db.flush()
    db.add_all(
        [
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                sort_order=0,
            ),
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=tongue.id,
                sort_order=1,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=proc.id,
                process_name=proc.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
        ]
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
    return tenant, order, front, tongue


def test_cut_cards_basket_bundles(db):
    tenant, order, front, tongue = _product_with_parts(db)
    preview = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=True,
        mode="basket_bundles",
        bundle_size=40,
    )
    assert preview["mode"] == "basket_bundles"
    assert preview["to_create"] == 3  # 1 basket + 2 bundles
    assert len(preview["lines"][0]["planned_units"][0]["bundles"]) == 2

    result = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        mode="basket_bundles",
        bundle_size=40,
    )
    baskets = [
        u
        for u in db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all()
        if u.unit_type == TraceUnitType.basket
    ]
    bundles = [
        u
        for u in db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all()
        if u.unit_type == TraceUnitType.bundle
    ]
    assert len(baskets) == 1
    assert len(bundles) == 2
    assert baskets[0].qty == 40
    assert {b.parent_id for b in bundles} == {baskets[0].id}
    assert {b.part_id for b in bundles} == {front.id, tongue.id}
    assert result["created"][0]["unit_type"] == "basket"
    assert len(result["created"][0]["children"]) == 2


def test_cut_cards_without_parts_falls_back(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        sort_order=1,
    )
    db.add(proc)
    db.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="CUT-OLD",
        is_active=True,
        trace_enabled=True,
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
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=20)],
        ),
        created_by=None,
    )
    result = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        mode="basket_bundles",
        bundle_size=20,
    )
    assert result["mode"] == "bundles"
    units = list(db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all())
    assert len(units) == 1
    assert units[0].unit_type == TraceUnitType.bundle
    assert units[0].parent_id is None


def test_cut_basket_rejected_when_trace_on(db):
    tenant, order, front, tongue = _product_with_parts(db)
    with pytest.raises(TraceError) as ei:
        preview_or_create_cut_cards(
            db,
            tenant_id=tenant.id,
            order_id=order.id,
            dry_run=True,
            mode="basket",
            bundle_size=40,
        )
    assert ei.value.code == "trace_requires_bundle"


def test_cut_basket_only_when_trace_off(db):
    tenant, order, front, tongue = _product_with_parts(db)
    product = db.get(OwnProduct, order.own_product_id)
    product.trace_enabled = False
    db.commit()
    preview = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=True,
        mode="basket",
        bundle_size=40,
    )
    assert preview["mode"] == "basket"
    assert preview["to_create"] == 1
    assert preview["lines"][0]["planned_units"][0]["bundles"] == []

    result = preview_or_create_cut_cards(
        db,
        tenant_id=tenant.id,
        order_id=order.id,
        dry_run=False,
        mode="basket",
        bundle_size=40,
    )
    baskets = [
        u
        for u in db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all()
        if u.unit_type == TraceUnitType.basket
    ]
    bundles = [
        u
        for u in db.scalars(select(TraceUnit).where(TraceUnit.order_id == order.id)).all()
        if u.unit_type == TraceUnitType.bundle
    ]
    assert result["mode"] == "basket"
    assert len(baskets) == 1
    assert len(bundles) == 0
    assert baskets[0].qty == 40
    assert result["created"][0]["children"] == []
