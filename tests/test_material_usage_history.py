"""产品用量历史：裁断实际平均覆盖和产品保存改用量都落流水。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Employee,
    ExecutionHeader,
    MaterialUsageHistory,
    Tenant,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    SpecExecutionStatus,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
    WorkLog,
    WorkLogStatus,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.material_usage_history_service import (
    MaterialUsageApplyError,
    apply_cut_average,
    list_material_usage_history,
    record_material_qty_changes,
    snapshot_material_qty,
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0) - LOCAL_OFFSET


def test_apply_average_and_product_save_keep_history():
    db = _db()
    tenant = Tenant(name="用量历史厂")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    db.add_all([cut, stitch])
    db.flush()
    process = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    partner = Partner(tenant_id=tenant.id, name="供应商", is_supplier=True)
    db.add_all([process, partner])
    db.flush()
    material = SupplierProduct(
        tenant_id=tenant.id,
        product_code="L1",
        name="皮料",
        partner_id=partner.id,
        unit_price=Decimal("10"),
    )
    other = SupplierProduct(
        tenant_id=tenant.id,
        product_code="G1",
        name="胶水",
        partner_id=partner.id,
        unit_price=Decimal("2"),
    )
    db.add_all([material, other])
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="A款", material_cost=Decimal("7"))
    db.add(product)
    db.flush()
    cut_line = OwnProductMaterial(
        tenant_id=tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        qty=Decimal("0.5"),
        unit_price=Decimal("10"),
        line_total=Decimal("5"),
        consume_segment_id=cut.id,
    )
    cut_line_b = OwnProductMaterial(
        tenant_id=tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        qty=Decimal("0.4"),
        unit_price=Decimal("10"),
        line_total=Decimal("4"),
        consume_segment_id=cut.id,
    )
    stitch_line = OwnProductMaterial(
        tenant_id=tenant.id,
        own_product_id=product.id,
        supplier_product_id=other.id,
        qty=Decimal("1"),
        unit_price=Decimal("2"),
        line_total=Decimal("2"),
        consume_segment_id=stitch.id,
    )
    db.add_all([cut_line, cut_line_b, stitch_line])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="SO-1",
        customer_name="客户",
        own_product_id=product.id,
        total_qty=20,
    )
    db.add(order)
    db.flush()
    order_process = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=process.id,
        process_name="裁断",
        plan_qty=20,
        segment_id=cut.id,
    )
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="HD-1",
        own_product_id=product.id,
        total_qty=20,
        status=SpecExecutionStatus.confirmed,
    )
    worker = Employee(tenant_id=tenant.id, name="张三")
    db.add_all([order_process, header, worker])
    db.flush()
    when = date(2026, 9, 15)
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_id=order.id,
            order_process_id=order_process.id,
            own_product_id=product.id,
            process_id=process.id,
            qualified_qty=Decimal("20"),
            segment_id=cut.id,
            status=WorkLogStatus.valid,
            created_at=_at(when),
        )
    )
    pickup = WarehousePickup(
        tenant_id=tenant.id,
        doc_no="PK-1",
        kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed,
        header_id=header.id,
        picker_employee_id=worker.id,
        picker_name=worker.name,
        signed_at=_at(when),
    )
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id,
        order_id=order.id,
        supplier_product_id=material.id,
        consume_segment_id=cut.id,
    )
    db.add_all([pickup, requirement])
    db.flush()
    db.add(
        WarehousePickupLine(
            tenant_id=tenant.id,
            pickup_id=pickup.id,
            supplier_product_id=material.id,
            requirement_id=requirement.id,
            material_name="皮料",
            material_code="L1",
            qty=Decimal("12"),
        )
    )
    db.flush()

    result = apply_cut_average(
        db,
        tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        date_from=when,
        date_to=when,
        changed_by=worker.id,
    )
    db.flush()
    assert result["changed"] is True
    assert result["qty"] == "0.6"
    assert result["old_qty"] is None
    assert cut_line.qty == Decimal("0.6000")
    assert cut_line_b.qty == Decimal("0.6000")
    assert cut_line.line_total == Decimal("6.0000")
    assert stitch_line.qty == Decimal("1")
    assert product.material_cost == Decimal("14.0000")
    histories = list(
        db.scalars(
            select(MaterialUsageHistory).where(MaterialUsageHistory.own_product_id == product.id)
        ).all()
    )
    assert len(histories) == 2
    assert {row.old_qty for row in histories} == {Decimal("0.5000"), Decimal("0.4000")}
    assert {row.new_qty for row in histories} == {Decimal("0.6000")}
    assert {row.source for row in histories} == {"cut_average"}
    assert {row.material_code for row in histories} == {"L1"}

    again = apply_cut_average(
        db,
        tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        date_from=when,
        date_to=when,
        changed_by=worker.id,
    )
    assert again["changed"] is False
    assert len(list_material_usage_history(
        db, tenant.id, own_product_id=product.id, supplier_product_id=material.id
    )) == 2

    try:
        apply_cut_average(
            db,
            tenant.id,
            own_product_id=product.id,
            supplier_product_id=other.id,
            date_from=when,
            date_to=when,
            changed_by=worker.id,
        )
        raise AssertionError("胶水不在裁断用料上，不应覆盖")
    except MaterialUsageApplyError as exc:
        assert "不在产品裁断用料上" in exc.message

    old = snapshot_material_qty(list(product.materials))
    cut_line.qty = Decimal("0.8")
    record_material_qty_changes(db, product, old, changed_by=worker.id, source="product_save")
    db.flush()
    saved = list_material_usage_history(
        db, tenant.id, own_product_id=product.id, supplier_product_id=material.id
    )
    assert saved[0].source == "product_save"
    assert saved[0].old_qty == Decimal("0.6000")
    assert saved[0].new_qty == Decimal("0.8000")
    assert saved[0].changed_by == worker.id

    again_old = snapshot_material_qty(list(product.materials))
    record_material_qty_changes(
        db, product, again_old, changed_by=worker.id, source="product_save"
    )
    db.flush()
    assert len(list_material_usage_history(
        db, tenant.id, own_product_id=product.id, supplier_product_id=material.id
    )) == 3
    db.close()


def test_same_qty_does_not_record_even_if_line_identity_drifts():
    db = _db()
    tenant = Tenant(name="用量未变厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="供应商", is_supplier=True)
    db.add(partner)
    db.flush()
    material = SupplierProduct(
        tenant_id=tenant.id,
        product_code="L1",
        name="皮料",
        partner_id=partner.id,
        unit_price=Decimal("10"),
    )
    db.add(material)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="B款")
    db.add(product)
    db.flush()
    line = OwnProductMaterial(
        tenant_id=tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        qty=Decimal("1.25"),
        unit_price=Decimal("10"),
        line_total=Decimal("12.5"),
        color_id=None,
        consume_segment_id=None,
    )
    other = OwnProductMaterial(
        tenant_id=tenant.id,
        own_product_id=product.id,
        supplier_product_id=material.id,
        qty=Decimal("1.25"),
        unit_price=Decimal("10"),
        line_total=Decimal("12.5"),
        color_id=9,
        consume_segment_id=3,
    )
    db.add_all([line, other])
    db.flush()

    old = snapshot_material_qty([line, other])
    line.color_id = 9
    line.consume_segment_id = 3
    other.color_id = None
    other.consume_segment_id = None
    record_material_qty_changes(db, product, old, changed_by=None, source="product_save")
    db.flush()
    assert list_material_usage_history(
        db, tenant.id, own_product_id=product.id, supplier_product_id=material.id
    ) == []

    line.qty = Decimal("2")
    other.qty = Decimal("2")
    record_material_qty_changes(db, product, old, changed_by=None, source="product_save")
    db.flush()
    rows = list_material_usage_history(
        db, tenant.id, own_product_id=product.id, supplier_product_id=material.id
    )
    assert len(rows) == 1
    assert rows[0].old_qty == Decimal("1.2500")
    assert rows[0].new_qty == Decimal("2.0000")
    db.close()
