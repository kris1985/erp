"""B1c：按码用量 BOM — 展开 / 缺码拦截 / 池不串码 / PO 带码。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    MaterialSizeUsageCoeff,
    MaterialSizeUsageTable,
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
    PurchaseOrderLine,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import material_service, purchase_service


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
    tenant = Tenant(name="B1c厂")
    session.add(tenant)
    session.flush()
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=1)
    s42 = Size(tenant_id=tenant.id, size_value="42", sort_order=2)
    session.add_all([s37, s42])
    partner = Partner(tenant_id=tenant.id, name="底厂", is_supplier=True, is_active=True)
    session.add(partner)
    proc = ProcessDefinition(
        tenant_id=tenant.id, name="成型", code="CX", default_price=Decimal("1"), sort_order=1
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SHOE-1", is_active=True)
    session.add(product)
    session.flush()
    fabric = SupplierProduct(
        tenant_id=tenant.id,
        product_code="FAB-1",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("10"),
        is_active=True,
    )
    session.add_all([fabric, sole])
    session.flush()
    table = MaterialSizeUsageTable(tenant_id=tenant.id, name="大底通用")
    session.add(table)
    session.flush()
    session.add_all(
        [
            MaterialSizeUsageCoeff(
                tenant_id=tenant.id, table_id=table.id, size_id=s37.id, coeff=Decimal("1")
            ),
            MaterialSizeUsageCoeff(
                tenant_id=tenant.id, table_id=table.id, size_id=s42.id, coeff=Decimal("1.05")
            ),
        ]
    )
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=fabric.id,
            qty=Decimal("0.5"),
            unit_price=Decimal("2"),
            line_total=Decimal("1"),
            sort_order=0,
            usage_by_size=False,
        )
    )
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sole.id,
            qty=Decimal("1"),
            unit_price=Decimal("10"),
            line_total=Decimal("10"),
            sort_order=1,
            usage_by_size=True,
            size_usage_table_id=table.id,
        )
    )
    session.commit()
    yield session, tenant.id, product.id, fabric.id, sole.id, s37.id, s42.id, proc.id, table.id
    session.close()


def _order(session, tenant_id, product_id, proc_id, s37, s42, *, qty37=100, qty42=80):
    order = Order(
        tenant_id=tenant_id,
        order_no="PO-B1C-1",
        customer_name="客户",
        own_product_id=product_id,
        total_qty=qty37 + qty42,
        status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    session.add_all(
        [
            OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                color_id=None,
                size_id=s37,
                qty=qty37,
            ),
            OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                color_id=None,
                size_id=s42,
                qty=qty42,
            ),
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=proc_id,
                process_name="成型",
                status=OrderProcessStatus.pending,
                plan_qty=qty37 + qty42,
            ),
        ]
    )
    session.commit()
    session.refresh(order)
    return order


def test_refresh_expands_size_and_keeps_fabric_total(db):
    session, tenant_id, product_id, fabric_id, sole_id, s37, s42, proc_id, _table = db
    order = _order(session, tenant_id, product_id, proc_id, s37, s42)
    rows = material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    session.commit()

    fabric_rows = [r for r in rows if r.supplier_product_id == fabric_id]
    sole_rows = [r for r in rows if r.supplier_product_id == sole_id]
    assert len(fabric_rows) == 1
    assert fabric_rows[0].size_id is None
    assert fabric_rows[0].required_qty == Decimal("90.0000")  # 0.5 * 180

    assert len(sole_rows) == 2
    by_size = {r.size_id: r for r in sole_rows}
    assert by_size[s37].required_qty == Decimal("100.0000")  # 1 * 100 * 1
    assert by_size[s42].required_qty == Decimal("84.0000")  # 1 * 80 * 1.05


def test_loss_percent_and_fixed_on_bom(db):
    session, tenant_id, product_id, fabric_id, sole_id, s37, s42, proc_id, _table = db
    fabric_bom = session.scalar(
        select(OwnProductMaterial).where(
            OwnProductMaterial.own_product_id == product_id,
            OwnProductMaterial.supplier_product_id == fabric_id,
        )
    )
    fabric_bom.loss_rate = Decimal("0.03")
    fabric_bom.loss_fixed_qty = Decimal("0.5")
    sole_bom = session.scalar(
        select(OwnProductMaterial).where(
            OwnProductMaterial.own_product_id == product_id,
            OwnProductMaterial.supplier_product_id == sole_id,
        )
    )
    sole_bom.loss_rate = Decimal("0.02")
    sole_bom.loss_fixed_qty = Decimal("2")
    session.commit()

    order = _order(session, tenant_id, product_id, proc_id, s37, s42, qty37=50, qty42=0)
    # only size 37 with 50 — rebuild order items: helper always makes both sizes
    # use qty42=0 still creates size 42 with 0 — size_qtys may include 0
    rows = material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    session.commit()
    fabric = next(r for r in rows if r.supplier_product_id == fabric_id)
    # 0.5 * 50 * 1.03 + 0.5 = 25.75 + 0.5 = 26.25
    assert fabric.required_qty == Decimal("26.2500")
    sole_rows = [r for r in rows if r.supplier_product_id == sole_id and (r.required_qty or 0) > 0]
    # first size gets fixed 2; 1*50*1*1.02 + 2 = 53
    assert any(r.required_qty == Decimal("53.0000") for r in sole_rows)
    # other size row if qty 0: 0 + 0 fixed
    assert sum((r.loss_fixed_qty or 0) for r in rows if r.supplier_product_id == sole_id) == Decimal("2")


def test_missing_coeff_blocks_refresh(db):
    session, tenant_id, product_id, _f, _s, s37, s42, proc_id, table_id = db
    # 删掉 42 系数
    row = session.scalar(
        select(MaterialSizeUsageCoeff).where(
            MaterialSizeUsageCoeff.table_id == table_id,
            MaterialSizeUsageCoeff.size_id == s42,
        )
    )
    session.delete(row)
    session.commit()
    order = _order(session, tenant_id, product_id, proc_id, s37, s42)
    with pytest.raises(material_service.MaterialError) as ei:
        material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    assert ei.value.code == "missing_size_coeff"


def test_pool_does_not_cross_sizes(db):
    session, tenant_id, product_id, _f, sole_id, s37, s42, proc_id, _t = db
    order = _order(session, tenant_id, product_id, proc_id, s37, s42)
    material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    session.commit()

    # 只入 42 码池
    material_service.adjust_shared_stock(
        session, tenant_id, sole_id, Decimal("200"), size_id=s42
    )
    session.commit()

    ctx = material_service.build_kit_context(session, tenant_id, include_shared=True)
    reqs = list(
        session.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.order_id == order.id,
                OrderMaterialRequirement.supplier_product_id == sole_id,
            )
        ).all()
    )
    d37 = ctx.row_dict(next(r for r in reqs if r.size_id == s37))
    d42 = ctx.row_dict(next(r for r in reqs if r.size_id == s42))
    assert d37["shared_credit_qty"] == 0
    assert d37["shortage_qty"] == Decimal("100.0000")
    assert d42["shared_credit_qty"] == Decimal("84.0000")
    assert d42["kit_ok"] is True


def test_po_draft_carries_size_id(db):
    session, tenant_id, product_id, _f, sole_id, s37, s42, proc_id, _t = db
    order = _order(session, tenant_id, product_id, proc_id, s37, s42)
    material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    session.commit()

    created = purchase_service.create_drafts_from_shortages(
        session, tenant_id, order_ids=[order.id], include_shared=False
    )
    assert created
    lines = list(
        session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.tenant_id == tenant_id)
        ).all()
    )
    sole_lines = [ln for ln in lines if ln.supplier_product_id == sole_id]
    assert {ln.size_id for ln in sole_lines} == {s37, s42}
