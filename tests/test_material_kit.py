"""材料齐套全局正确性：池承诺不重复占用、取消回池、改量重算。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    MaterialCategory,
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
from app.services import inventory_settings, material_service, order_service, purchase_service
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
    # 本用例显式打开「齐套含未分配池」
    inventory_settings.save_inventory_patch(
        session, tenant_id, {"kit_include_unallocated_pool": True}
    )
    material_service.adjust_shared_stock(session, tenant_id, sp_id, Decimal("10"))
    session.commit()
    o1 = _make_order(session, tenant_id, product_id, proc_id, order_no="F1", qty=10, is_rush=True)
    o2 = _make_order(session, tenant_id, product_id, proc_id, order_no="F2", qty=10)

    ok_ids = material_service.order_ids_matching_kit(session, tenant_id, kit_ok=True)
    bad_ids = material_service.order_ids_matching_kit(session, tenant_id, kit_ok=False)
    assert o1.id in ok_ids
    assert o2.id in bad_ids
    assert o1.id not in bad_ids


def test_empty_bom_is_not_kit_ready(db):
    session, tenant_id, product_id, sp_id, proc_id = db
    # 无产品物料的订单：空 BOM 不得虚齐套
    bare = OwnProduct(tenant_id=tenant_id, product_code="BARE-NO-BOM", is_active=True)
    session.add(bare)
    session.flush()
    order = _make_order(session, tenant_id, bare.id, proc_id, order_no="EB1", qty=5)
    kit = material_service.get_order_kit(session, tenant_id, order.id)
    assert kit["empty_bom"] is True
    assert kit["kit_ok"] is False
    assert kit["first_kit_ok"] is False
    summary = material_service.order_kit_summary(session, tenant_id, order.id)
    assert summary["empty_bom"] is True
    assert summary["kit_ok"] is False
    assert summary["first_kit_ok"] is False


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


def test_consume_process_resolve_and_first_kit(db):
    """分类默认 / BOM 覆盖 / 未标注算首道；成型缺料不影响首道齐套。"""
    session, tenant_id, product_id, sp_id, proc_id = db

    cx = ProcessDefinition(
        tenant_id=tenant_id,
        name="成型",
        code="CX",
        type=ProcessType.group,
        default_price=Decimal("0.5"),
        sort_order=3,
    )
    session.add(cx)
    session.flush()

    cat_fabric = MaterialCategory(
        tenant_id=tenant_id,
        name="面料",
        sort_order=1,
        default_consume_process_id=proc_id,  # 裁断
    )
    cat_sole = MaterialCategory(
        tenant_id=tenant_id,
        name="鞋底",
        sort_order=2,
        default_consume_process_id=cx.id,
    )
    session.add_all([cat_fabric, cat_sole])
    session.flush()

    partner = session.scalar(select(Partner).where(Partner.tenant_id == tenant_id))
    sp_fabric = SupplierProduct(
        tenant_id=tenant_id,
        product_code="FAB-1",
        name="面布",
        partner_id=partner.id,
        category_id=cat_fabric.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    sp_sole = SupplierProduct(
        tenant_id=tenant_id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        category_id=cat_sole.id,
        unit_price=Decimal("5"),
        is_active=True,
    )
    session.add_all([sp_fabric, sp_sole])
    session.flush()

    # 清掉夹具里的旧 BOM，换成面布（跟分类）+ 大底（BOM 覆盖到成型，其实分类已是成型）
    for old in session.scalars(
        select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product_id)
    ).all():
        session.delete(old)
    session.flush()
    session.add_all(
        [
            OwnProductMaterial(
                tenant_id=tenant_id,
                own_product_id=product_id,
                supplier_product_id=sp_fabric.id,
                qty=Decimal("1"),
                unit_price=Decimal("2"),
                line_total=Decimal("2"),
                sort_order=0,
                consume_process_id=None,  # 跟分类 → 裁断
            ),
            OwnProductMaterial(
                tenant_id=tenant_id,
                own_product_id=product_id,
                supplier_product_id=sp_sole.id,
                qty=Decimal("1"),
                unit_price=Decimal("5"),
                line_total=Decimal("5"),
                sort_order=1,
                consume_process_id=None,  # 跟分类 → 成型
            ),
        ]
    )
    session.commit()

    # resolve
    pid, src = material_service.resolve_consume_process(
        session, tenant_id, bom_consume_process_id=None, supplier_product_id=sp_fabric.id
    )
    assert pid == proc_id and src == "category"
    pid2, src2 = material_service.resolve_consume_process(
        session, tenant_id, bom_consume_process_id=cx.id, supplier_product_id=sp_fabric.id
    )
    assert pid2 == cx.id and src2 == "bom"

    order = _make_order(session, tenant_id, product_id, proc_id, order_no="CP1", qty=10)
    # 补成型工序（建单助手只加了裁断）
    session.add(
        OrderProcess(
            tenant_id=tenant_id,
            order_id=order.id,
            process_id=cx.id,
            process_name="成型",
            process_type=ProcessType.group,
            plan_qty=10,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    session.commit()

    # 只给面布分配，大底缺料
    reqs = list(
        session.scalars(
            select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
        ).all()
    )
    by_sp = {r.supplier_product_id: r for r in reqs}
    assert by_sp[sp_fabric.id].consume_process_id == proc_id
    assert by_sp[sp_sole.id].consume_process_id == cx.id
    by_sp[sp_fabric.id].arrived_qty = Decimal("10")
    by_sp[sp_sole.id].arrived_qty = Decimal("0")
    session.commit()

    kit = material_service.get_order_kit(session, tenant_id, order.id, include_shared=False)
    assert kit["kit_ok"] is False
    assert kit["first_kit_ok"] is True
    assert kit["first_process_name"] == "裁断"
    by_name = {x["process_name"]: x for x in kit["by_process"]}
    assert by_name["裁断"]["kit_ok"] is True
    assert by_name["成型"]["kit_ok"] is False

    # 未标注料算进首道
    sp_misc = SupplierProduct(
        tenant_id=tenant_id,
        product_code="MISC-1",
        name="辅料",
        partner_id=partner.id,
        category_id=None,
        unit_price=Decimal("1"),
        is_active=True,
    )
    session.add(sp_misc)
    session.flush()
    material_service.add_requirement(
        session, tenant_id, order.id, supplier_product_id=sp_misc.id, qty_per_pair=Decimal("1")
    )
    misc_req = session.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.order_id == order.id,
            OrderMaterialRequirement.supplier_product_id == sp_misc.id,
        )
    )
    assert misc_req.consume_process_id is None
    # arrived 默认 0 → unlabeled 缺料卡首道
    kit2 = material_service.get_order_kit(session, tenant_id, order.id, include_shared=False)
    assert kit2["first_kit_ok"] is False
    by_name2 = {x["process_name"]: x for x in kit2["by_process"]}
    assert by_name2["成型"]["line_count"] == 1  # 不含 unlabeled
