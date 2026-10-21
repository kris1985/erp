from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    MaterialPrep,
    MaterialPrepQr,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    SpecExecutionStatus,
    SupplierProduct,
)
from app.services import inventory_settings
from app.services.material_prep_service import MaterialPrepError, create_prep, list_orders, list_qrs, preview_materials, sign_prep


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_prep_uses_first_segment_and_reuses_qr_after_sign():
    db = _db()
    tenant_id = 1
    from app.models import Tenant

    tenant = Tenant(name="备料测试厂")
    db.add(tenant)
    db.flush()
    tenant_id = tenant.id
    color = Color(tenant_id=tenant_id, name="黑", code="BK")
    partner = Partner(tenant_id=tenant_id, name="料商", is_supplier=True)
    product = OwnProduct(tenant_id=tenant_id, product_code="FT-1")
    db.add_all([color, partner, product])
    db.flush()
    cut = ProcessSegment(tenant_id=tenant_id, name="裁断", code="CUT", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant_id, name="针车", code="ST", sort_order=2)
    db.add_all([cut, stitch])
    db.flush()
    cut_proc = ProcessDefinition(tenant_id=tenant_id, name="开料", code="CUT1", type=ProcessType.personal, segment_id=cut.id)
    stitch_proc = ProcessDefinition(tenant_id=tenant_id, name="车帮", code="ST1", type=ProcessType.personal, segment_id=stitch.id)
    upper = SupplierProduct(tenant_id=tenant_id, product_code="MAT-1", name="面料", partner_id=partner.id, color_id=color.id)
    thread = SupplierProduct(tenant_id=tenant_id, product_code="MAT-2", name="车线", partner_id=partner.id)
    db.add_all([cut_proc, stitch_proc, upper, thread])
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-PREP",
        own_product_id=product.id,
        color_id=color.id,
        total_qty=100,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(header)
    db.flush()
    db.add_all([
        OrderProcess(
            tenant_id=tenant_id,
            header_id=header.id,
            process_id=cut_proc.id,
            process_name="开料",
            process_type=ProcessType.personal,
            plan_qty=100,
            segment_id=cut.id,
        ),
        OrderProcess(
            tenant_id=tenant_id,
            header_id=header.id,
            process_id=stitch_proc.id,
            process_name="车帮",
            process_type=ProcessType.personal,
            plan_qty=100,
            segment_id=stitch.id,
        ),
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=header.id,
            supplier_product_id=upper.id,
            qty_per_pair=Decimal("0.5"),
            required_qty=Decimal("50"),
            consume_segment_id=cut.id,
            is_customer_supplied=True,
        ),
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=header.id,
            supplier_product_id=thread.id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("100"),
            consume_segment_id=stitch.id,
            is_customer_supplied=True,
        ),
    ])
    user = Employee(tenant_id=tenant_id, name="仓管", is_active=True)
    picker = Employee(tenant_id=tenant_id, name="张三", is_active=True)
    db.add_all([user, picker])
    db.commit()

    preview = preview_materials(db, tenant_id, header.id)
    assert preview["segment_name"] == "裁断"
    assert [line["material_code"] for line in preview["lines"]] == ["MAT-1"]
    assert preview["lines"][0]["qty_per_pair"] == "0.5"

    codes = list_qrs(db, tenant_id)
    assert len(codes) == 10
    assert all(not row["occupied"] for row in codes)

    slips = []
    for index in range(10):
        slips.append(
            create_prep(
                db,
                tenant_id,
                user.id,
                header_id=header.id,
                pairs=2,
                lines=[{"supplier_product_id": upper.id, "actual_qty": Decimal("1")}],
                origin="http://127.0.0.1:8000",
            )
        )
    assert len({row["slot"] for row in slips}) == 10
    with pytest.raises(MaterialPrepError) as busy:
        create_prep(
            db,
            tenant_id,
            user.id,
            header_id=header.id,
            pairs=1,
            lines=[{"supplier_product_id": upper.id, "actual_qty": Decimal("1")}],
        )
    assert busy.value.code == "qr_busy"

    listed = list_orders(db, tenant_id)
    assert listed[0]["prepared_pairs"] == 20
    assert [row["header_no"] for row in listed] == ["XE-PREP"]
    token = db.scalar(select(MaterialPrepQr.token).where(MaterialPrepQr.id == db.get(MaterialPrep, slips[0]["id"]).qr_id))
    signed = sign_prep(db, tenant_id, token, picker)
    assert signed["picker_name"] == "张三"
    assert signed["status"] == "signed"
    again = create_prep(
        db,
        tenant_id,
        user.id,
        header_id=header.id,
        pairs=1,
        lines=[{"supplier_product_id": upper.id, "actual_qty": Decimal("0.5")}],
    )
    assert again["slot"] == slips[0]["slot"]
    db.close()


def test_prep_reduces_warehouse_by_actual_qty():
    db = _db()
    from app.models import Tenant

    tenant = Tenant(name="备料扣库厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="FT-2")
    db.add_all([partner, product])
    db.flush()
    material = SupplierProduct(
        tenant_id=tenant.id, product_code="MAT-9", name="大底", partner_id=partner.id
    )
    db.add(material)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-STOCK",
        own_product_id=product.id,
        total_qty=10,
        status=SpecExecutionStatus.in_progress,
    )
    db.add(header)
    db.flush()
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        supplier_product_id=material.id,
        qty_per_pair=Decimal("2"),
        required_qty=Decimal("20"),
        arrived_qty=Decimal("20"),
        issued_qty=Decimal("0"),
    )
    user = Employee(tenant_id=tenant.id, name="仓管", is_active=True)
    db.add_all([requirement, user])
    db.commit()
    inventory_settings.save_inventory_patch(db, tenant.id, {"issue_required": True})

    slip = create_prep(
        db,
        tenant.id,
        user.id,
        header_id=header.id,
        pairs=4,
        lines=[{"supplier_product_id": material.id, "actual_qty": Decimal("3.5")}],
        origin="http://127.0.0.1:8000",
    )
    assert slip["lines"][0]["qty"] == "8"
    assert slip["lines"][0]["actual_qty"] == "3.5"
    saved = db.get(OrderMaterialRequirement, requirement.id)
    assert saved.issued_qty == Decimal("3.5")
    db.close()


def test_prep_orders_follow_progress_sequence():
    db = _db()
    from app.models import Tenant

    tenant = Tenant(name="备料顺序厂")
    db.add(tenant)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="FT-3")
    db.add(product)
    db.flush()
    rows = [
        ExecutionHeader(
            tenant_id=tenant.id, header_no="NOSCHED-1", own_product_id=product.id,
            total_qty=1, status=SpecExecutionStatus.confirmed,
        ),
        ExecutionHeader(
            tenant_id=tenant.id, header_no="SEQ-2", own_product_id=product.id,
            total_qty=1, status=SpecExecutionStatus.in_progress, schedule_sequence=2,
        ),
        ExecutionHeader(
            tenant_id=tenant.id, header_no="SEQ-1", own_product_id=product.id,
            total_qty=1, status=SpecExecutionStatus.cut, schedule_sequence=1,
        ),
    ]
    db.add_all(rows)
    db.flush()
    db.add(
        ExecutionHeader(
            tenant_id=tenant.id, header_no="CHILD", own_product_id=product.id,
            total_qty=1, status=SpecExecutionStatus.confirmed, parent_header_id=rows[0].id,
        )
    )
    db.commit()

    listed = [row["header_no"] for row in list_orders(db, tenant.id)]
    assert listed == ["SEQ-1", "SEQ-2", "NOSCHED-1"]
    db.close()
