"""材料齐套全局正确性：池承诺不重复占用、取消回池、改量重算。"""

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
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import material_service, order_service, purchase_service
from app.schemas.api import OrderItemIn


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
    tenant = Tenant(name="齐套厂")
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


def _make_order(db, tenant_id, product_id, proc_id, *, order_no: str, qty: int, is_rush: bool = False):
    size = db.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户A",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=date(2026, 8, 10),
        status=OrderStatus.confirmed,
        is_rush=is_rush,
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


def test_pool_not_double_claimed(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    material_service.adjust_shared_stock(
        session, tenant_id, sp_id, Decimal("10"), unit_cost=Decimal("10")
    )
    session.commit()

    o1 = _make_order(session, tenant_id, product_id, proc_id, order_no="R1", qty=10, is_rush=True)
    o2 = _make_order(session, tenant_id, product_id, proc_id, order_no="N1", qty=10, is_rush=False)

    s1 = material_service.order_kit_summary(session, tenant_id, o1.id, include_shared=True)
    s2 = material_service.order_kit_summary(session, tenant_id, o2.id, include_shared=True)
    assert s1["kit_ok"] is True
    assert s2["kit_ok"] is False

    kit2 = material_service.get_order_kit(session, tenant_id, o2.id, include_shared=True)
    line = kit2["lines"][0]
    assert line["shared_credit_qty"] == Decimal("0")
    assert line["pool_qty"] == Decimal("10")
    assert line["shortage_qty"] == Decimal("10")


def test_cancel_releases_arrived_to_pool(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="C1", qty=5)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("5")
    session.commit()

    order_service.update_order(session, tenant_id, order.id, status="cancelled")
    stock = session.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    assert stock is not None
    assert stock.qty == Decimal("5")
    session.refresh(req)
    assert req.arrived_qty == Decimal("0")
    ledgers = session.scalars(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.tenant_id == tenant_id,
            SharedMaterialLedger.ledger_type == SharedLedgerType.release_from_order,
        )
    ).all()
    assert len(ledgers) == 1


def test_qty_downsize_releases_excess(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="Q1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("10")
    session.commit()

    size = session.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order_service.update_order(
        session,
        tenant_id,
        order.id,
        items=[OrderItemIn(color_id=None, size_id=size.id, qty=4)],
    )
    session.refresh(req)
    assert req.required_qty == Decimal("4.0000")
    assert req.arrived_qty == Decimal("4")
    stock = session.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    assert stock.qty == Decimal("6")


def test_list_kit_filter_matches_summary(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    material_service.adjust_shared_stock(session, tenant_id, sp_id, Decimal("10"))
    session.commit()
    o1 = _make_order(session, tenant_id, product_id, proc_id, order_no="F1", qty=10, is_rush=True)
    o2 = _make_order(session, tenant_id, product_id, proc_id, order_no="F2", qty=10)

    ok_ids = material_service.order_ids_matching_kit(session, tenant_id, kit_ok=True)
    bad_ids = material_service.order_ids_matching_kit(session, tenant_id, kit_ok=False)
    assert o1.id in ok_ids
    assert o2.id in bad_ids
    assert o1.id not in bad_ids


def test_receive_into_pool_then_auto_allocate(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    partner = session.scalar(select(Partner).where(Partner.tenant_id == tenant_id))
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="PO1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-T1",
        public_token="tok-recv-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    session.add(po)
    session.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant_id,
        purchase_order_id=po.id,
        supplier_product_id=sp_id,
        order_id=order.id,
        order_material_requirement_id=req.id,
        qty=Decimal("10"),
        unit_price=Decimal("10"),
        received_qty=Decimal("0"),
    )
    session.add(line)
    session.commit()

    # 到货 12：10 分配到单，2 留池
    purchase_service.receive_po(
        session,
        tenant_id,
        po.id,
        [{"line_id": line.id, "qty": Decimal("12")}],
    )
    session.refresh(req)
    session.refresh(line)
    stock = session.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.supplier_product_id == sp_id,
        )
    )
    assert req.arrived_qty == Decimal("10")
    assert line.received_qty == Decimal("12")
    assert stock.qty == Decimal("2")
    types = {
        x.ledger_type
        for x in session.scalars(
            select(SharedMaterialLedger).where(SharedMaterialLedger.tenant_id == tenant_id)
        ).all()
    }
    assert SharedLedgerType.unallocated_receive in types
    assert SharedLedgerType.allocate_to_order in types


def test_manual_allocate_and_deallocate(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    material_service.adjust_shared_stock(session, tenant_id, sp_id, Decimal("8"))
    session.commit()
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="A1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )

    material_service.allocate_from_pool(session, tenant_id, order.id, req.id, Decimal("5"))
    session.refresh(req)
    stock = session.scalar(
        select(SharedMaterialStock).where(SharedMaterialStock.supplier_product_id == sp_id)
    )
    assert req.arrived_qty == Decimal("5")
    assert stock.qty == Decimal("3")

    material_service.deallocate_to_pool(session, tenant_id, order.id, req.id, Decimal("2"))
    session.refresh(req)
    session.refresh(stock)
    assert req.arrived_qty == Decimal("3")
    assert stock.qty == Decimal("5")


def test_in_transit_uses_po_open_qty(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    partner = session.scalar(select(Partner).where(Partner.tenant_id == tenant_id))
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="T1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("3")  # 占用与在途脱钩
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-T2",
        public_token="tok-tr-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=sp_id,
            order_id=order.id,
            order_material_requirement_id=req.id,
            qty=Decimal("10"),
            unit_price=Decimal("10"),
            received_qty=Decimal("4"),
        )
    )
    session.commit()
    transit = material_service.in_transit_qty_for_requirement(session, tenant_id, req.id)
    assert transit == Decimal("6")
    kit = material_service.get_order_kit(session, tenant_id, order.id, include_shared=False)
    assert kit["lines"][0]["in_transit_qty"] == Decimal("6")


def test_stock_reconcile_report(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    material_service.adjust_shared_stock(session, tenant_id, sp_id, Decimal("7"))
    session.commit()
    order = _make_order(session, tenant_id, product_id, proc_id, order_no="RC1", qty=10)
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("4")
    req.issued_qty = Decimal("1")
    session.commit()

    report = material_service.stock_reconcile_report(session, tenant_id)
    assert report["summary"]["anomaly_count"] == 0
    line = next(x for x in report["lines"] if x["supplier_product_id"] == sp_id)
    assert line["pool_qty"] == Decimal("7")
    assert line["order_occupancy_qty"] == Decimal("3")
    assert line["book_total_qty"] == Decimal("10")
