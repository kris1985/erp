"""AU-I0 M1：部件路线建单顺序与齐套检查点。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OrderProcess,
    OwnProduct,
    OwnProductLabor,
    OwnProductPart,
    PartDefinition,
    ProcessDefinition,
    Size,
    Tenant,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order


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
    tenant = Tenant(name="AU-I0厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    session.commit()
    yield session
    session.close()


def _seed_two_stage(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    front = PartDefinition(tenant_id=tenant.id, code="QB", name="前帮", source="裁断")
    back = PartDefinition(tenant_id=tenant.id, code="HB", name="后帮", source="裁断")
    db.add_all([front, back])
    db.flush()

    procs = []
    for i, (name, code) in enumerate(
        [("针车前帮", "ZC_QB"), ("针车后帮", "ZC_HB"), ("合帮", "HB_KIT"), ("成型", "CX")],
        start=1,
    ):
        p = ProcessDefinition(
            tenant_id=tenant.id,
            name=name,
            code=code,
            default_price=Decimal("1.0"),
            sort_order=i,
        )
        db.add(p)
        procs.append(p)
    db.flush()

    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="AU-I0-A",
        is_active=True,
        trace_enabled=True,
        labor_cost=Decimal("4"),
    )
    db.add(product)
    db.flush()
    db.add_all(
        [
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                pieces_per_pair=1,
                sort_order=0,
            ),
            OwnProductPart(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=back.id,
                pieces_per_pair=1,
                sort_order=1,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=front.id,
                process_id=procs[0].id,
                process_name=procs[0].name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=back.id,
                process_id=procs[1].id,
                process_name=procs[1].name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=None,
                process_id=procs[2].id,
                process_name=procs[2].name,
                unit_price=Decimal("1"),
                sort_order=0,
                is_kit_checkpoint=True,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                part_id=None,
                process_id=procs[3].id,
                process_name=procs[3].name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
        ]
    )
    db.commit()
    return tenant, product, color, size, front, back, procs


def test_create_order_process_order_with_parts(db):
    tenant, product, color, size, front, back, procs = _seed_two_stage(db)
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            own_product_id=product.id,
            customer_name="测试客户",
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=40)],
        ),
        created_by=None,
    )
    ops = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.order_id == order.id)
            .order_by(OrderProcess.id)
        ).all()
    )
    assert [op.process_name for op in ops] == ["针车前帮", "针车后帮", "合帮", "成型"]
    assert ops[0].part_id == front.id
    assert ops[1].part_id == back.id
    assert ops[2].part_id is None
    assert ops[3].part_id is None


def test_legacy_flat_route_still_works(db):
    tenant = db.scalar(select(Tenant).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX2",
        default_price=Decimal("0.5"),
        sort_order=1,
    )
    db.add(proc)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="LEGACY", is_active=True)
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("0.5"),
            sort_order=0,
        )
    )
    db.commit()
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            own_product_id=product.id,
            customer_name="旧款",
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=10)],
        ),
        created_by=None,
    )
    ops = list(db.scalars(select(OrderProcess).where(OrderProcess.order_id == order.id)).all())
    assert len(ops) == 1
    assert ops[0].process_name == "成型"
    assert ops[0].part_id is None
