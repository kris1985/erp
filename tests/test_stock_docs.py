"""强制领料：领退料单过账与报工闸门。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import inventory_settings, material_service, order_service, stock_doc_service
from app.services.material_service import MaterialError


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
    tenant = Tenant(name="领料厂")
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    session.add(partner)
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CT",
        default_price=Decimal("0.3"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="K1", is_active=True)
    session.add(product)
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-1",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("10"),
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
            unit_price=Decimal("10"),
            line_total=Decimal("10"),
            sort_order=0,
        )
    )
    session.commit()
    yield session, tenant.id, product.id, sp.id, proc.id
    session.close()


def _enable_issue(session, tenant_id: int):
    inventory_settings.save_inventory_patch(session, tenant_id, {"issue_required": True})


def _make_order(db, tenant_id, product_id, proc_id, *, order_no: str, qty: int):
    size = db.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户A",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=date(2026, 8, 10),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant_id,
            order_id=order.id,
            color_id=None,
            size_id=size.id,
            qty=qty,
            completed_qty=0,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant_id,
            order_id=order.id,
            process_id=proc_id,
            process_name="裁断",
            plan_qty=qty,
            completed_qty=0,
            defect_qty=0,
            status=OrderProcessStatus.pending,
            process_type=ProcessType.personal,
        )
    )
    db.flush()
    material_service.ensure_material_snapshot(db, tenant_id, order)
    db.commit()
    return order_service.get_order(db, tenant_id, order.id)


def test_issue_and_return(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    _enable_issue(session, tenant_id)
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="I1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("10")
    session.commit()

    doc = stock_doc_service.create_and_post_stock_doc(
        session,
        tenant_id,
        doc_type="issue",
        order_id=order.id,
        lines=[{"requirement_id": req.id, "qty": Decimal("6")}],
    )
    assert doc["doc_type"] == "issue"
    session.refresh(req)
    assert req.issued_qty == Decimal("6")

    with pytest.raises(MaterialError) as ei:
        stock_doc_service.create_and_post_stock_doc(
            session,
            tenant_id,
            doc_type="issue",
            order_id=order.id,
            lines=[{"requirement_id": req.id, "qty": Decimal("5")}],
        )
    assert ei.value.code == "exceed_available"

    stock_doc_service.create_and_post_stock_doc(
        session,
        tenant_id,
        doc_type="return_mat",
        order_id=order.id,
        lines=[{"requirement_id": req.id, "qty": Decimal("2")}],
    )
    session.refresh(req)
    assert req.issued_qty == Decimal("4")
    assert req.arrived_qty == Decimal("8")
    stock = session.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    assert stock is not None
    assert stock.qty == Decimal("2")


def test_issue_gate_and_block_light_release(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    _enable_issue(session, tenant_id)
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="G1", qty=5)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("5")
    session.commit()

    with pytest.raises(MaterialError) as eg:
        stock_doc_service.assert_issue_gate(session, tenant_id, order)
    assert eg.value.code == "issue_required"

    with pytest.raises(MaterialError) as er:
        material_service.release_to_workshop(
            session, tenant_id, order.id, req.id, Decimal("1")
        )
    assert er.value.code == "use_stock_docs"

    stock_doc_service.create_and_post_stock_doc(
        session,
        tenant_id,
        doc_type="issue",
        order_id=order.id,
        lines=[{"requirement_id": req.id, "qty": Decimal("5")}],
    )
    stock_doc_service.assert_issue_gate(session, tenant_id, order)

    inv = inventory_settings.get_inventory_by_tenant_id(session, tenant_id)
    assert inv["issue_required"] is True
    assert inv["capabilities"]["stock_docs"] is True
    assert inv["capabilities"]["issue_gate"] is True
    assert inv["cost_basis"] == "issued"
