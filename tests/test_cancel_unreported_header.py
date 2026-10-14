"""未报工生产单取消：待买、采购单、订单状态。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Employee,
    ExecutionAllocation,
    ExecutionHeader,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    Partner,
    ProcessDefinition,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    WorkLog,
    WorkLogStatus,
)
from app.services.execution_service import ExecutionError, cancel_unreported_header
from app.services.purchase_demand_service import list_purchase_demand
from app.services.sales_order_service import _replace_line_items, list_demand_shortages


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _world(db):
    tenant = Tenant(name="取消厂")
    db.add(tenant)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="M-1", is_active=True)
    partner = Partner(tenant_id=tenant.id, name="料厂", is_supplier=True, is_active=True)
    db.add_all([product, partner])
    db.flush()
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=40)
    proc = ProcessDefinition(tenant_id=tenant.id, name="贴底", code="SOLE", default_price=Decimal("1"))
    db.add_all([size, proc])
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="LEA",
        name="面皮",
        unit_price=Decimal("20"),
        is_active=True,
    )
    db.add(leather)
    db.flush()
    return tenant, product, partner, size, proc, leather


def _header(db, tenant, product, size, *, no, sales_order, line, item, qty, required):
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no=no,
        own_product_id=product.id,
        sales_order_id=sales_order.id,
        sales_order_line_id=line.id,
        total_qty=qty,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(header)
    db.flush()
    exe = SpecExecutionOrder(
        tenant_id=tenant.id,
        execution_no=f"{no}-40",
        header_id=header.id,
        own_product_id=product.id,
        size_id=size.id,
        total_qty=qty,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(exe)
    db.flush()
    db.add(
        ExecutionAllocation(
            tenant_id=tenant.id,
            execution_id=exe.id,
            sales_order_id=sales_order.id,
            sales_order_line_id=line.id,
            sales_order_line_item_id=item.id,
            qty=qty,
            ratio=Decimal("1"),
        )
    )
    req = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        supplier_product_id=required[0],
        qty_per_pair=Decimal("1"),
        required_qty=Decimal(str(required[1])),
    )
    db.add(req)
    line.execution_header_id = header.id
    line.status = SalesOrderLineStatus.scheduled
    item.allocated_qty = qty
    db.flush()
    return header, req


def test_cancel_unreported_returns_order_and_drops_buy_list():
    db = _db()
    tenant, product, partner, size, _proc, leather = _world(db)
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-1",
        customer_name="客户",
        ordered_at=date(2026, 10, 1),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=10,
        status=SalesOrderLineStatus.scheduled,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        size_id=size.id,
        qty=10,
        allocated_qty=10,
    )
    db.add(item)
    db.flush()
    header, req = _header(
        db, tenant, product, size, no="XE-1", sales_order=so, line=line, item=item, qty=10, required=(leather.id, 10)
    )
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=leather.id,
            order_material_requirement_id=req.id,
            qty=Decimal("10"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()

    data = cancel_unreported_header(db, tenant_id=tenant.id, header_id=header.id)
    db.refresh(header)
    db.refresh(so)
    db.refresh(line)
    db.refresh(item)
    db.refresh(po)
    db.refresh(req)
    assert data["status"] == "cancelled"
    assert header.status == SpecExecutionStatus.cancelled
    assert so.status == SalesOrderStatus.draft
    assert line.status == SalesOrderLineStatus.pending
    assert line.execution_header_id is None
    assert int(item.allocated_qty or 0) == 0
    assert req.purchase_dismissed is True
    assert po.status == PurchaseOrderStatus.cancelled
    buy = list_demand_shortages(db, tenant.id)
    assert leather.id not in {row["supplier_product_id"] for row in buy["lines"]}
    left = db.scalar(
        select(func.count())
        .select_from(ExecutionAllocation)
        .where(ExecutionAllocation.sales_order_line_id == line.id)
    )
    assert int(left or 0) == 0


def test_edit_line_after_cancel_drops_leftover_allocations():
    """取消后若旧分配还指着码数，改明细应摘掉这些分配，而不是外键 500。"""
    db = _db()
    tenant, product, _partner, size, _proc, leather = _world(db)
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-EDIT",
        customer_name="客户",
        ordered_at=date(2026, 10, 1),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=10,
        status=SalesOrderLineStatus.scheduled,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        size_id=size.id,
        qty=10,
        allocated_qty=10,
    )
    db.add(item)
    db.flush()
    header, _req = _header(
        db,
        tenant,
        product,
        size,
        no="XE-EDIT",
        sales_order=so,
        line=line,
        item=item,
        qty=10,
        required=(leather.id, 10),
    )
    db.commit()
    cancel_unreported_header(db, tenant_id=tenant.id, header_id=header.id)
    exe = db.scalar(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    db.add(
        ExecutionAllocation(
            tenant_id=tenant.id,
            execution_id=exe.id,
            sales_order_id=so.id,
            sales_order_line_id=line.id,
            sales_order_line_item_id=item.id,
            qty=10,
            ratio=Decimal("1"),
        )
    )
    db.commit()

    class _Item:
        def __init__(self, size_id, qty):
            self.size_id = size_id
            self.qty = qty

    _replace_line_items(db, tenant.id, line, [_Item(size.id, 20)])
    db.commit()
    db.refresh(line)
    assert [int(it.qty) for it in line.items] == [20]
    left = db.scalar(
        select(func.count())
        .select_from(ExecutionAllocation)
        .where(ExecutionAllocation.sales_order_line_item_id == item.id)
    )
    assert int(left or 0) == 0


def test_reported_header_cannot_cancel():
    db = _db()
    tenant, product, _partner, size, proc, leather = _world(db)
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-2",
        customer_name="客户",
        ordered_at=date(2026, 10, 1),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=10,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id, sales_order_line_id=line.id, size_id=size.id, qty=10
    )
    db.add(item)
    db.flush()
    header, _req = _header(
        db, tenant, product, size, no="XE-2", sales_order=so, line=line, item=item, qty=10, required=(leather.id, 10)
    )
    worker = Employee(tenant_id=tenant.id, name="张三")
    db.add(worker)
    db.flush()
    order_process = OrderProcess(
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=proc.id,
        process_name="贴底",
        plan_qty=10,
    )
    db.add(order_process)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            header_id=header.id,
            order_process_id=order_process.id,
            own_product_id=product.id,
            process_id=proc.id,
            qualified_qty=Decimal("1"),
            status=WorkLogStatus.valid,
        )
    )
    db.commit()
    try:
        cancel_unreported_header(db, tenant_id=tenant.id, header_id=header.id)
        raise AssertionError("should reject reported header")
    except ExecutionError as exc:
        assert exc.code == "has_report"
    db.refresh(header)
    assert header.status == SpecExecutionStatus.confirmed


def test_draft_combined_po_only_subtracts_this_header():
    db = _db()
    tenant, product, partner, size, _proc, leather = _world(db)
    headers = []
    reqs = []
    for index, qty in ((1, 10), (2, 4)):
        so = SalesOrder(
            tenant_id=tenant.id,
            order_no=f"SO-C{index}",
            customer_name="客户",
            ordered_at=date(2026, 10, 1),
            status=SalesOrderStatus.confirmed,
        )
        db.add(so)
        db.flush()
        line = SalesOrderLine(
            tenant_id=tenant.id,
            sales_order_id=so.id,
            own_product_id=product.id,
            total_qty=qty,
        )
        db.add(line)
        db.flush()
        item = SalesOrderLineItem(
            tenant_id=tenant.id, sales_order_line_id=line.id, size_id=size.id, qty=qty
        )
        db.add(item)
        db.flush()
        header, req = _header(
            db,
            tenant,
            product,
            size,
            no=f"XE-C{index}",
            sales_order=so,
            line=line,
            item=item,
            qty=qty,
            required=(leather.id, qty),
        )
        headers.append(header)
        reqs.append(req)
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-MIX",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
    )
    db.add(po)
    db.flush()
    mixed = PurchaseOrderLine(
        tenant_id=tenant.id,
        purchase_order_id=po.id,
        supplier_product_id=leather.id,
        order_material_requirement_id=reqs[0].id,
        qty=Decimal("14"),
        unit_price=Decimal("20"),
    )
    db.add(mixed)
    db.commit()

    cancel_unreported_header(db, tenant_id=tenant.id, header_id=headers[1].id)
    db.refresh(po)
    db.refresh(mixed)
    assert po.status == PurchaseOrderStatus.draft
    assert mixed.qty == Decimal("10")
    assert mixed.order_material_requirement_id == reqs[0].id
    still = list_purchase_demand(db, tenant.id, only_shortage=False)
    leather_line = next(row for row in still["lines"] if row["supplier_product_id"] == leather.id)
    assert Decimal(str(leather_line["demand_qty"])) == Decimal("10")
    assert Decimal(str(leather_line["to_buy_qty"])) == Decimal("0")
    buy = list_demand_shortages(db, tenant.id)
    assert all(row["supplier_product_id"] != leather.id for row in buy["lines"])

    cancel_unreported_header(db, tenant_id=tenant.id, header_id=headers[0].id)
    db.refresh(po)
    assert po.status == PurchaseOrderStatus.cancelled
    left = db.scalar(select(func.count()).select_from(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
    assert int(left or 0) == 0


def test_received_po_still_allows_production_cancel():
    db = _db()
    tenant, product, partner, size, _proc, leather = _world(db)
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-R",
        customer_name="客户",
        ordered_at=date(2026, 10, 1),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=10,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id, sales_order_line_id=line.id, size_id=size.id, qty=10
    )
    db.add(item)
    db.flush()
    header, req = _header(
        db, tenant, product, size, no="XE-R", sales_order=so, line=line, item=item, qty=10, required=(leather.id, 10)
    )
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-R",
        partner_id=partner.id,
        status=PurchaseOrderStatus.partial_received,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=leather.id,
            order_material_requirement_id=req.id,
            qty=Decimal("10"),
            received_qty=Decimal("2"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()
    cancel_unreported_header(db, tenant_id=tenant.id, header_id=header.id)
    db.refresh(header)
    db.refresh(so)
    db.refresh(po)
    assert header.status == SpecExecutionStatus.cancelled
    assert so.status == SalesOrderStatus.draft
    assert po.status == PurchaseOrderStatus.partial_received
