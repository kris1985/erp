"""P0-1：生产单计划开工尊重预计齐套日；确认闸门拦截过早开工。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ScheduleDraft,
    ScheduleDraftLine,
    ScheduleDraftStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import material_service, schedule_engine, schedule_service


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
    tenant = Tenant(name="P0齐套排产厂", settings_json={})
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    ct = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CT",
        default_price=Decimal("0.3"),
        default_days=2,
        sort_order=1,
    )
    session.add(ct)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="P0-K", is_active=True)
    session.add(product)
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-P0",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("5"),
        is_active=True,
    )
    session.add(sp)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("5"),
            line_total=Decimal("5"),
            sort_order=0,
            consume_process_id=ct.id,
        )
    )
    session.commit()
    yield session, tenant.id, product.id, sp.id, partner.id, ct.id
    session.close()


def _order_with_shortage(session, tenant_id, product_id, sp_id, partner_id, ct_id, *, as_of: date, eta_days: int = 10):
    size = session.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no="P0-WAIT",
        customer_name="客",
        own_product_id=product_id,
        total_qty=100,
        delivery_date=as_of + timedelta(days=60),
        status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    session.add(OrderItem(tenant_id=tenant_id, order_id=order.id, size_id=size.id, qty=100, completed_qty=0))
    session.add(
        OrderProcess(
            tenant_id=tenant_id,
            order_id=order.id,
            process_id=ct_id,
            process_name="裁断",
            process_type=ProcessType.personal,
            plan_qty=100,
            status=OrderProcessStatus.pending,
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-P0-1",
        partner_id=partner_id,
        status=PurchaseOrderStatus.ordered,
        expected_date=as_of + timedelta(days=eta_days),
        ordered_at=as_of,
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=sp_id,
            qty=Decimal("100"),
            received_qty=Decimal("0"),
            unit_price=Decimal("5"),
        )
    )
    session.commit()
    material_service.ensure_material_snapshot(session, tenant_id, order)
    session.commit()
    return order, as_of + timedelta(days=eta_days)


def test_proposals_start_not_before_kit_ready(db):
    session, tenant_id, product_id, sp_id, partner_id, ct_id = db
    as_of = date(2026, 8, 9)
    order, kit_ready = _order_with_shortage(
        session, tenant_id, product_id, sp_id, partner_id, ct_id, as_of=as_of, eta_days=10
    )
    kit = material_service.get_order_kit(session, tenant_id, order.id)
    assert kit.get("first_kit_ok") is False
    assert kit.get("kit_ready_date") == kit_ready.isoformat()

    props = schedule_engine.generate_proposals(
        session, tenant_id, order_ids=[order.id], hide_scheduled=False, as_of=as_of
    )["items"]
    assert props
    for p in props:
        if p.get("strategy") == "kit_ready":
            # 缺料单不纳入「只排齐套」方案
            continue
        orders = p.get("orders") or []
        assert orders, p
        plan = orders[0]
        assert plan.get("earliest_start") == kit_ready.isoformat()
        wins = plan.get("windows") or []
        assert wins
        start = date.fromisoformat(wins[0]["start_date"])
        assert start >= kit_ready, (p.get("strategy"), start, kit_ready)
        notes = " ".join(plan.get("notes") or [])
        assert "等料至" in notes


def test_confirm_rejects_start_before_kit_ready(db):
    session, tenant_id, product_id, sp_id, partner_id, ct_id = db
    as_of = date(2026, 8, 9)
    order, kit_ready = _order_with_shortage(
        session, tenant_id, product_id, sp_id, partner_id, ct_id, as_of=as_of, eta_days=10
    )
    proc = session.scalar(
        select(OrderProcess).where(OrderProcess.order_id == order.id, OrderProcess.process_id == ct_id)
    )
    assert proc
    draft = ScheduleDraft(
        tenant_id=tenant_id,
        status=ScheduleDraftStatus.draft,
        note="早开草稿",
    )
    session.add(draft)
    session.flush()
    session.add(
        ScheduleDraftLine(
            tenant_id=tenant_id,
            draft_id=draft.id,
            order_id=order.id,
            order_process_id=proc.id,
            process_id=ct_id,
            process_name="裁断",
            plan_qty=100,
            start_date=as_of,  # 早于齐套日
            end_date=as_of + timedelta(days=1),
            included=True,
        )
    )
    session.commit()

    with pytest.raises(schedule_service.ScheduleError) as ei:
        schedule_service.confirm_draft(
            session, tenant_id, draft.id, user_id=1, require_first_kit=False
        )
    assert ei.value.code == "kit_ready_too_early"
    _ = kit_ready  # 齐套日用于构造场景
