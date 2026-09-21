"""预计交货日期：剩余产量正排，未齐套则等预计到货/齐套日。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
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
    SharedMaterialStock,
    Size,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
)
from app.services import inventory_settings
from app.services.execution_service import (
    _standard_capacity_map,
    create_execution_from_sales_line,
    header_out,
    project_header_finish,
)
from app.services import attendance_rules as ar
from app.services.material_service import get_header_kit, header_kit_summaries


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
    tenant = Tenant(name="预计交期厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    cut = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CD",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("100"),
        standard_workers=1,
        sort_order=1,
    )
    form = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("100"),
        standard_workers=1,
        sort_order=2,
    )
    session.add_all([cut, form])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="PD-1", is_active=True)
    session.add(product)
    session.flush()
    for i, proc in enumerate((cut, form)):
        session.add(
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=proc.id,
                process_name=proc.name,
                unit_price=Decimal("1"),
                sort_order=i,
            )
        )
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-1",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=mat.id,
            qty=Decimal("1"),
            unit_price=Decimal("1"),
            line_total=Decimal("1"),
            sort_order=0,
        )
    )
    session.commit()
    inventory_settings.save_inventory_patch(
        session,
        tenant.id,
        {
            "shared_pool": True,
            "allocate_ui": True,
            "stock_docs": True,
            "kit_include_unallocated_pool": True,
        },
    )
    yield session
    session.close()


def test_attendance_workday_helpers():
    weekly = ar.merge_attendance_rules({"weekly_rest_days": [6, 7]})
    assert ar.is_attendance_workday(date(2026, 3, 2), weekly)
    assert not ar.is_attendance_workday(date(2026, 3, 7), weekly)
    monthly = ar.merge_attendance_rules(
        {"rest_day_mode": "monthly", "monthly_rest_days": [15], "weekly_rest_days": []}
    )
    assert ar.is_attendance_workday(date(2026, 3, 14), monthly)
    assert not ar.is_attendance_workday(date(2026, 3, 15), monthly)
    assert ar.is_attendance_workday(date(2026, 3, 7), monthly)


def _header(db, *, stocked: bool, qty: int = 100):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    partner = db.scalar(select(Partner).limit(1))
    mat = db.scalar(select(SupplierProduct).limit(1))
    if stocked:
        db.add(
            SharedMaterialStock(
                tenant_id=tenant.id,
                supplier_product_id=mat.id,
                size_id=None,
                qty=Decimal("1000"),
            )
        )
        db.flush()
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-PD",
        customer_name="客户",
        ordered_at=date(2026, 3, 2),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=qty,
        delivery_date=date(2026, 4, 1),
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant.id,
            sales_order_line_id=line.id,
            color_id=color.id,
            size_id=size.id,
            qty=qty,
            allocated_qty=0,
            produced_qty=0,
        )
    )
    db.flush()
    header = create_execution_from_sales_line(
        db, tenant_id=tenant.id, sales_order=so, line=line, created_by=1, commit=True
    )
    return tenant, partner, mat, header


def _expected_finish(start: date, process_days: list[int], rules=None) -> date:
    cursor = ar.next_attendance_workday(start, rules)
    finish = cursor
    for days in process_days:
        _s, finish = ar.attendance_span_starting(cursor, days, rules)
        cursor = ar.next_attendance_workday(finish + timedelta(days=1), rules)
    return finish


def test_kitted_order_projects_from_today_by_capacity(db):
    tenant, _partner, _mat, header = _header(db, stocked=True)
    as_of = date(2026, 3, 2)
    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    kit = out["kit"]
    assert kit["kit_ok"] is True
    finish = project_header_finish(
        out["process_progress"],
        kit,
        status=str(header.status.value),
        cap_map=cap_map,
        as_of=as_of,
    )
    # 两道各 100 双 / 100 双天 = 各 1 天，串行 2 个工作日
    assert finish == _expected_finish(as_of, [1, 1])
    assert finish != header.delivery_date


def test_shortage_waits_for_purchase_eta(db):
    tenant, partner, mat, header = _header(db, stocked=False)
    as_of = date(2026, 3, 2)
    eta = date(2026, 3, 16)
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-ETA",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
        expected_date=eta,
        ordered_at=datetime(2026, 3, 1),
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=mat.id,
            qty=Decimal("100"),
            received_qty=Decimal("0"),
            unit_price=Decimal("1"),
        )
    )
    db.commit()

    kit = get_header_kit(db, tenant.id, header.id)
    assert kit["kit_ok"] is False
    assert kit["kit_ready_date"] == eta.isoformat()
    batch = header_kit_summaries(db, tenant.id, [header.id])
    assert batch[header.id]["kit_ready_date"] == eta.isoformat()

    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    finish = project_header_finish(
        out["process_progress"],
        {
            "kit_ok": False,
            "empty_bom": False,
            "kit_ready_date": kit["kit_ready_date"],
        },
        status=str(header.status.value),
        cap_map=cap_map,
        as_of=as_of,
    )
    assert finish == _expected_finish(eta, [1, 1])
    assert finish > as_of


def test_in_progress_shortage_cannot_finish_before_kit_ready(db):
    tenant, _partner, _mat, header = _header(db, stocked=False)
    header.status = SpecExecutionStatus.in_progress
    db.commit()
    as_of = date(2026, 3, 2)
    kit_ready = date(2026, 3, 20)
    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    production_finish = _expected_finish(as_of, [1, 1])
    finish = project_header_finish(
        out["process_progress"],
        {
            "kit_ok": False,
            "empty_bom": False,
            "kit_ready_date": kit_ready.isoformat(),
        },
        status="in_progress",
        cap_map=cap_map,
        as_of=as_of,
    )
    assert finish == ar.next_attendance_workday(max(production_finish, kit_ready))


def test_uses_attendance_rest_days_not_national_weekend(db):
    tenant, _partner, _mat, header = _header(db, stocked=True)
    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    # 只休周日，周六照常生产
    rules = ar.merge_attendance_rules({"weekly_rest_days": [7]})
    as_of = date(2026, 3, 6)  # 周五
    finish = project_header_finish(
        out["process_progress"],
        out["kit"],
        status=str(header.status.value),
        cap_map=cap_map,
        as_of=as_of,
        attendance_rules=rules,
    )
    assert finish == date(2026, 3, 7)  # 周五 + 周六


def test_special_holiday_skips_weekday(db):
    tenant, _partner, _mat, header = _header(db, stocked=True)
    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_holidays": [{"start": "2026-03-03 00:00", "end": "2026-03-04 00:00"}],
        }
    )
    as_of = date(2026, 3, 2)  # 周一；周二放假
    finish = project_header_finish(
        out["process_progress"],
        out["kit"],
        status=str(header.status.value),
        cap_map=cap_map,
        as_of=as_of,
        attendance_rules=rules,
    )
    assert finish == date(2026, 3, 4)  # 周一 + 周三


def test_special_overtime_counts_rest_day(db):
    tenant, _partner, _mat, header = _header(db, stocked=True)
    cap_map = _standard_capacity_map(db, tenant.id)
    out = header_out(db, header)
    rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_overtimes": [{"start": "2026-03-08 08:00", "end": "2026-03-08 17:30"}],
        }
    )
    as_of = date(2026, 3, 6)  # 周五；周六休息，周日加班
    finish = project_header_finish(
        out["process_progress"],
        out["kit"],
        status=str(header.status.value),
        cap_map=cap_map,
        as_of=as_of,
        attendance_rules=rules,
    )
    assert finish == date(2026, 3, 8)
