"""B0a：齐码可发货闸门 — 末道色码合格 − 已出；确认硬拦。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
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
    Worker,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order
from app.services.report_service import submit_report
from app.services import shipment_service


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

    tenant = Tenant(name="齐码测试厂")
    session.add(tenant)
    session.flush()
    for name, code in [("红", "R"), ("黑", "BK")]:
        session.add(Color(tenant_id=tenant.id, name=name, code=code))
    for i, v in enumerate(["37", "38"]):
        session.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))
    procs = []
    for name, code, price, seq in [
        ("裁断", "CT", "0.3", 1),
        ("针车", "ZC", "0.5", 2),
        ("成型", "CX", "0.8", 3),
    ]:
        p = ProcessDefinition(
            tenant_id=tenant.id,
            name=name,
            code=code,
            default_price=Decimal(price),
            sort_order=seq,
        )
        session.add(p)
        session.flush()
        procs.append(p)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="齐码款",
        quote_price=Decimal("68.00"),
        is_active=True,
    )
    session.add(product)
    session.flush()
    for p in procs:
        session.add(
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=p.id,
                process_name=p.name,
                unit_price=p.default_price,
                sort_order=p.sort_order,
            )
        )
    session.add(Worker(tenant_id=tenant.id, name="李四", mobile="13900000001"))
    session.commit()
    yield session
    session.close()


def _refs(db):
    tenant = db.query(Tenant).first()
    product = db.query(OwnProduct).first()
    worker = db.query(Worker).first()
    color = db.query(Color).filter_by(name="红").one()
    size = db.query(Size).filter_by(size_value="37").one()
    return tenant, product, worker, color, size


def test_delivery_summary_shippable_uses_last_process_not_mid(db):
    tenant, product, worker, color, size = _refs(db)
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            order_no="B0A-001",
            customer_name="测客户",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=10)],
            unit_price=Decimal("10"),
        ),
        created_by=None,
    )
    # 中道报满 — 不应算可发
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
    )
    summary = shipment_service.order_delivery_summary(db, tenant.id, order.id)
    assert summary["gate_enabled"] is True
    assert summary["last_process_name"] == "成型"
    row = summary["items"][0]
    assert row["last_qualified_qty"] == 0
    assert row["shippable_qty"] == 0
    assert row["short_qty"] == 10
    assert row["backlog_qty"] == 10

    # 末道报 6 — 可出 6
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=6,
        color_name="红",
        size_value="37",
    )
    summary2 = shipment_service.order_delivery_summary(db, tenant.id, order.id)
    row2 = summary2["items"][0]
    assert row2["last_qualified_qty"] == 6
    assert row2["shippable_qty"] == 6
    assert row2["short_qty"] == 4


def test_confirm_blocks_when_not_shippable_draft_ok(db):
    tenant, product, worker, color, size = _refs(db)
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            order_no="B0A-002",
            customer_name="测客户",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=10)],
            unit_price=Decimal("10"),
        ),
        created_by=None,
    )
    item_id = order.items[0].id

    # 草稿可超可发（仅卡欠交）
    draft = shipment_service.create_shipment(
        db,
        tenant.id,
        order_id=order.id,
        lines=[{"order_item_id": item_id, "qty": 5}],
        confirm=False,
    )
    assert draft["status"] == "draft"

    with pytest.raises(shipment_service.ShipmentError) as ei:
        shipment_service.confirm_shipment(db, tenant.id, draft["id"])
    assert ei.value.code == "not_shippable"

    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=5,
        color_name="红",
        size_value="37",
    )
    out = shipment_service.confirm_shipment(db, tenant.id, draft["id"])
    assert out["status"] == "shipped"
    assert out["total_qty"] == 5


def test_create_confirm_blocks_incomplete(db):
    tenant, product, worker, color, size = _refs(db)
    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            order_no="B0A-003",
            customer_name="测客户",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=8)],
            unit_price=Decimal("10"),
        ),
        created_by=None,
    )
    with pytest.raises(shipment_service.ShipmentError) as ei:
        shipment_service.create_shipment(
            db,
            tenant.id,
            order_id=order.id,
            lines=[{"order_item_id": order.items[0].id, "qty": 3}],
            confirm=True,
        )
    assert ei.value.code == "not_shippable"
