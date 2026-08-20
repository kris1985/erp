"""B1d：承接外包（来料加工/承揽针车）——业务形态 + 用料全标客供 + 毛利口径 + 损耗对账。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    SalesBizMode,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.schemas.api import SalesOrderCreate, SalesOrderUpdate
from app.services import finance_service, sales_order_service, subcontract_service
from app.services.execution_service import create_execution_from_sales_line


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
    yield session
    session.close()


def _seed_base(db):
    tenant = Tenant(name="承揽针车厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    partner = Partner(tenant_id=tenant.id, name="上家鞋厂", is_customer=True, is_supplier=True)
    db.add_all([color, size, partner])
    db.flush()
    proc = ProcessDefinition(
        tenant_id=tenant.id, name="针车", code="ZC", default_price=Decimal("1"), sort_order=1
    )
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="CS-MAT",
        name="上家供料",
        partner_id=partner.id,
        unit_price=Decimal("9.00"),
        is_active=True,
    )
    product = OwnProduct(
        tenant_id=tenant.id, product_code="纯加工款", quote_price=Decimal("80"), is_active=True
    )
    db.add_all([proc, sp, product])
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
    db.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("9.00"),
            line_total=Decimal("9.00"),
            sort_order=0,
        )
    )
    db.commit()
    return tenant.id, color.id, size.id, partner.id, proc.id, sp.id, product.id


def _make_so(db, tenant_id, *, order_no, biz_mode, color_id, size_id, product_id, total=100):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="上家鞋厂",
        ordered_at=date.today(),
        status=SalesOrderStatus.draft,
        biz_mode=SalesBizMode(biz_mode),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        unit_price=Decimal("12.00"),
        customer_sku="上家款号-01",
        total_qty=total,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant_id,
            sales_order_line_id=line.id,
            color_id=color_id,
            size_id=size_id,
            qty=total,
            allocated_qty=0,
            produced_qty=0,
        )
    )
    db.commit()
    return so, line


def test_biz_mode_roundtrip_and_filter(db):
    tid, color_id, size_id, _pid, _proc_id, _sp_id, product_id = _seed_base(db)

    so, _line = _make_so(
        db, tid, order_no="SO-SUB-1", biz_mode="subcontract_in",
        color_id=color_id, size_id=size_id, product_id=product_id,
    )
    out = sales_order_service.serialize_sales_order(db, tid, so)
    assert out["biz_mode"] == "subcontract_in"

    rows, total = sales_order_service.list_sales_orders(db, tid, biz_mode="subcontract_in")
    assert total == 1
    assert rows[0].id == so.id

    rows2, total2 = sales_order_service.list_sales_orders(db, tid, biz_mode="self_produce")
    assert total2 == 0

    updated = sales_order_service.update_sales_order(
        db, tid, so.id, SalesOrderUpdate(biz_mode="self_produce")
    )
    assert updated.biz_mode == SalesBizMode.self_produce


def test_create_sales_order_accepts_biz_mode(db):
    tid, color_id, size_id, _pid, _proc_id, _sp_id, product_id = _seed_base(db)
    payload = SalesOrderCreate(
        order_no="SO-SUB-CREATE",
        customer_name="上家鞋厂",
        biz_mode="subcontract_in",
        lines=[],
    )
    so = sales_order_service.create_sales_order(db, tid, payload, created_by=1)
    assert so.biz_mode == SalesBizMode.subcontract_in
    assert sales_order_service.serialize_sales_order(db, tid, so)["biz_mode"] == "subcontract_in"


def test_confirm_production_marks_customer_supplied(db):
    tid, color_id, size_id, _pid, _proc_id, _sp_id, product_id = _seed_base(db)
    so, line = _make_so(
        db, tid, order_no="SO-SUB-KIT", biz_mode="subcontract_in",
        color_id=color_id, size_id=size_id, product_id=product_id,
    )
    header = create_execution_from_sales_line(
        db, tenant_id=tid, sales_order=so, line=line, created_by=1, commit=True
    )
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == header.id
            )
        ).all()
    )
    assert reqs
    assert all(r.is_customer_supplied is True for r in reqs)
    assert all(r.customer_chase_status == "open" for r in reqs)


def test_pure_processing_product_empty_bom_confirm(db):
    """T2：纯加工产品（无 BOM 材料）承接外包确认生产不报错，用料为空。"""
    tid, color_id, size_id, _pid, proc_id, _sp_id, _product_id = _seed_base(db)
    proc = db.get(ProcessDefinition, proc_id)
    pure = OwnProduct(
        tenant_id=tid, product_code="纯加工-空BOM", quote_price=Decimal("20"), is_active=True
    )
    db.add(pure)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tid,
            own_product_id=pure.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    db.commit()
    so, line = _make_so(
        db, tid, order_no="SO-SUB-EMPTY", biz_mode="subcontract_in",
        color_id=color_id, size_id=size_id, product_id=pure.id,
    )
    header = create_execution_from_sales_line(
        db, tenant_id=tid, sales_order=so, line=line, created_by=1, commit=True
    )
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == header.id
            )
        ).all()
    )
    assert reqs == []


def test_customer_supplied_material_cost_zero_and_profit_note(db):
    tid, color_id, size_id, _pid, _proc_id, _sp_id, product_id = _seed_base(db)
    so, line = _make_so(
        db, tid, order_no="SO-SUB-PROFIT", biz_mode="subcontract_in",
        color_id=color_id, size_id=size_id, product_id=product_id,
    )
    header = create_execution_from_sales_line(
        db, tenant_id=tid, sales_order=so, line=line, created_by=1, commit=True
    )
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == header.id
            )
        ).all()
    )
    for r in reqs:
        r.issued_qty = Decimal("100")
    db.commit()

    cost, basis = finance_service._material_cost_from_reqs(db, tid, reqs)
    assert float(cost) == 0.0  # 客供不计材料成本

    db.add(
        Shipment(
            tenant_id=tid,
            shipment_no="SHP-SUB-1",
            sales_order_id=so.id,
            customer_name=so.customer_name,
            status=ShipmentStatus.shipped,
            total_qty=100,
            unit_price=Decimal("12.00"),
            amount=Decimal("1200.00"),
        )
    )
    db.commit()

    profit = finance_service.sales_order_profit(db, tid, so.id)
    assert profit["biz_mode"] == "subcontract_in"
    assert float(profit["revenue"]) == 1200.0
    assert float(profit["material_cost"]) == 0.0
    assert float(profit["gross_profit"]) == 1200.0  # 材料客供不计，人工无报工=0
    assert "加工毛利" in profit["estimate_note"]


def test_subcontract_loss_scan_flags_over_std(db):
    tid, color_id, size_id, _pid, _proc_id, _sp_id, product_id = _seed_base(db)
    so, line = _make_so(
        db, tid, order_no="SO-SUB-LOSS", biz_mode="subcontract_in",
        color_id=color_id, size_id=size_id, product_id=product_id,
    )
    header = create_execution_from_sales_line(
        db, tenant_id=tid, sales_order=so, line=line, created_by=1, commit=True
    )
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.header_id == header.id
        )
    )
    assert req.is_customer_supplied is True
    req.arrived_qty = Decimal("120")
    req.issued_qty = Decimal("118")  # 超标准应耗 100（含损耗）
    req.required_qty = Decimal("100")
    db.commit()

    rows = subcontract_service.scan_subcontract_loss(db, tid, threshold=Decimal("0.10"))
    assert rows
    top = rows[0]
    assert top["order_no"] == "SO-SUB-LOSS"
    assert float(top["issued_qty"]) == 118.0
    assert float(top["arrived_qty"]) == 120.0
    assert float(top["loss_qty"]) == 118.0  # 无报工产出，损耗=实耗
    assert float(top["in_transit_qty"]) == 2.0  # 来料120 − 实耗118

    summary = subcontract_service.subcontract_loss_summary(db, tid)
    assert summary["flagged_count"] >= 1
    assert "SO-SUB-LOSS" in summary["summary"]
