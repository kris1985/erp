"""干掉生产单 K4-F：无壳日用补齐 — 领退料/客供/核销/整单装箱/分活/同步工序。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.own_products import _sync_labors_to_open_orders
from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    MaterialRelease,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessAssignment,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    PaymentAllocation,
    ProcessDefinition,
    ProcessType,
    Receivable,
    ReceivableStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
    TraceUnit,
    Employee,
)
from app.services import inventory_settings, packing_service, stock_doc_service
from app.services.assignment_service import assign_basket
from app.services.customer_supply_service import list_customer_supply, receive_customer_supply
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.finance_service import create_payment
from app.services.material_service import release_to_workshop
from app.services.trace_service import unit_detail_dict


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
    tenant = Tenant(name="K4F厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4F-A", is_active=True
    )
    session.add(product)
    session.flush()
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-K4F",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=early.id,
                process_name=early.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=late.id,
                process_name=late.name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=mat.id,
                qty=Decimal("1"),
                unit_price=Decimal("2"),
                line_total=Decimal("2"),
                sort_order=0,
            ),
            SharedMaterialStock(
                tenant_id=tenant.id,
                supplier_product_id=mat.id,
                size_id=None,
                qty=Decimal("100"),
            ),
            Employee(tenant_id=tenant.id, name="分活员", mobile="13900007777", is_active=True),
        ]
    )
    session.commit()
    yield session
    session.close()


def _so_item(db, *, order_no: str, qty: int, product_id: int, color_id: int, size_id: int, tenant_id: int):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=qty,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant_id,
        sales_order_line_id=line.id,
        color_id=color_id,
        size_id=size_id,
        qty=qty,
        allocated_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return so, line, item


def _header_only(db, *, qty: int = 12, order_no: str = "SO-K4F"):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    so, _line, item = _so_item(
        db,
        order_no=order_no,
        qty=qty,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    return tenant, header, exe, so


def test_stock_doc_issue_without_shop_order(db):
    tenant, header, _exe, _so = _header_only(db, qty=10)
    inventory_settings.save_inventory_patch(db, tenant.id, {"issue_required": True})
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert req is not None
    assert req.order_id is None
    req.arrived_qty = Decimal("10")
    db.commit()

    pending = stock_doc_service.submit_stock_doc(
        db,
        tenant.id,
        doc_type="issue",
        header_id=header.id,
        lines=[{"requirement_id": req.id, "qty": Decimal("6")}],
    )
    assert pending["status"] == "pending"
    assert pending["header_id"] == header.id
    assert pending["order_id"] is None
    db.refresh(req)
    assert (req.issued_qty or 0) == 0

    posted = stock_doc_service.confirm_stock_doc(db, tenant.id, pending["id"])
    assert posted["status"] == "posted"
    db.refresh(req)
    assert req.issued_qty == Decimal("6")


def test_material_release_without_shop_order(db):
    tenant, header, _exe, _so = _header_only(db, qty=8, order_no="SO-K4F-REL")
    # 默认开领退料工作台会挡住轻量发车间；本项测无壳 MaterialRelease 直发。
    inventory_settings.save_inventory_patch(
        db, tenant.id, {"capabilities": {"stock_docs": False}}
    )
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert req is not None
    out = release_to_workshop(
        db,
        tenant.id,
        None,
        req.id,
        Decimal("3"),
        header_id=header.id,
    )
    assert Decimal(str(out["issued_qty"])) == Decimal("3")
    db.refresh(req)
    assert req.issued_qty == Decimal("3")
    rel = db.scalar(
        select(MaterialRelease).where(MaterialRelease.header_id == header.id)
    )
    assert rel is not None
    assert rel.order_id is None
    assert rel.header_id == header.id


def test_customer_supply_without_shop_order(db):
    tenant, header, _exe, so = _header_only(db, qty=10, order_no="SO-K4F-CS")
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert req is not None
    req.is_customer_supplied = True
    db.commit()

    rows = list_customer_supply(db, tenant.id)
    assert any(r["id"] == req.id and r["header_no"] == header.header_no for r in rows)

    rec = receive_customer_supply(db, tenant.id, req.id, qty=Decimal("4"))
    assert rec["line"]["arrived_qty"] == Decimal("4")
    assert rec["line"]["header_id"] == header.id
    assert rec["line"]["customer_name"] == so.customer_name


def test_payment_allocation_without_order_id(db):
    tenant, _header, _exe, so = _header_only(db, qty=6, order_no="SO-K4F-PAY")
    ar = Receivable(
        tenant_id=tenant.id,
        customer_name=so.customer_name,
        order_id=None,
        sales_order_id=so.id,
        sales_order_no=so.order_no,
        receivable_date=date.today(),
        amount=Decimal("100"),
        adjustment=Decimal("0"),
        received_amount=Decimal("0"),
        status=ReceivableStatus.open,
    )
    db.add(ar)
    db.commit()
    out = create_payment(
        db,
        tenant.id,
        customer_id=None,
        customer_name=so.customer_name,
        amount=Decimal("40"),
        payment_date=date.today(),
        allocations=[{"receivable_id": ar.id, "amount": Decimal("40")}],
    )
    assert out["allocations"][0]["order_id"] is None
    alloc = db.scalar(select(PaymentAllocation).where(PaymentAllocation.receivable_id == ar.id))
    assert alloc is not None
    assert alloc.order_id is None
    assert alloc.amount == Decimal("40")


def test_header_packing_plan(db):
    tenant, header, _exe, _so = _header_only(db, qty=24, order_no="SO-K4F-PK")
    plan = packing_service.create_packing_plan(
        db,
        tenant.id,
        header_id=header.id,
        mode="single_size",
        pairs_per_carton=12,
    )
    assert plan["header_id"] == header.id
    assert plan["order_id"] is None
    assert plan["total_qty"] == 24
    assert plan["carton_count"] == 2
    assert plan["header_no"] == header.header_no
    assert plan["cartons"][0]["code"].startswith(f"CTN-{header.header_no}-")


def test_stitch_assign_without_order(db):
    tenant, header, exe = _header_only(db, qty=12, order_no="SO-K4F-ST")[:3]
    cut = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=12,
        # 首道齐套门禁：本测试用「仅头单」fixture（无 BOM 用料），
        # 开裁需填写原因才能继续（A1a kit-ready 门禁）。
        skip_kit_reason="测试缺料开裁",
    )
    basket_id = cut["created"][0]["id"]
    basket = db.get(TraceUnit, basket_id)
    assert basket.order_id is None
    detail = unit_detail_dict(db, basket)
    assert detail["header_id"] == header.id
    assert any(p["process_name"] == "针车" for p in detail["order_processes"])

    proc = db.scalar(
        select(OrderProcess).where(
            OrderProcess.header_id == header.id,
            OrderProcess.process_name == "针车",
        )
    )
    worker = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id))
    assert proc is not None and worker is not None
    out = assign_basket(
        db,
        tenant.id,
        basket_id=basket.id,
        process_id=proc.id,
        items=[{"worker_id": worker.id, "quota_qty": int(basket.qty)}],
    )
    assert out["items"][0]["worker_id"] == worker.id
    row = db.scalar(
        select(OrderProcessAssignment).where(
            OrderProcessAssignment.trace_unit_id == basket.id
        )
    )
    assert row is not None
    assert row.order_id is None
    assert row.header_id == header.id


def test_sync_labors_to_open_headers(db):
    tenant, header, _exe, _so = _header_only(db, qty=10, order_no="SO-K4F-SYNC")
    product = db.get(OwnProduct, header.own_product_id)
    extra = ProcessDefinition(
        tenant_id=tenant.id,
        name="包装",
        code="BZ",
        type=ProcessType.personal,
        default_price=Decimal("0.5"),
        sort_order=9,
    )
    db.add(extra)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=extra.id,
            process_name=extra.name,
            unit_price=Decimal("0.5"),
            sort_order=2,
        )
    )
    db.commit()
    db.refresh(product)
    stats = _sync_labors_to_open_orders(db, product)
    assert stats["headers"] == 1
    assert stats["added"] >= 1
    names = {
        p.process_name
        for p in db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    }
    assert "包装" in names
    assert "针车" in names
