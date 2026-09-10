"""B2g：品质追溯 — 硬拦 / suggest 扩展 / trace_quality / 门面反查。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    DefectEvent,
    DefectResponsibility,
    ExecutionHeader,
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    Size,
    StockDoc,
    StockDocStatus,
    StockDocType,
    SubcontractOrder,
    Tenant,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    Employee,
)
from app.services import trace_service
from app.services.trace_service import TraceError


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed(db, *, trace_enabled=True):
    tenant = Tenant(name="追溯厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    w1 = Employee(tenant_id=tenant.id, name="张三", mobile="13900000001", is_active=True)
    w2 = Employee(tenant_id=tenant.id, name="李四", mobile="13900000002", is_active=True)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="QT-01",
        quote_price=Decimal("80"),
        trace_enabled=trace_enabled,
    )
    segment = ProcessSegment(tenant_id=tenant.id, name="针车段", code="stitch", sort_order=1)
    db.add(segment)
    db.flush()
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        sort_order=1,
        type=ProcessType.personal,
        segment_id=segment.id,
    )
    cx = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("2.0"),
        sort_order=2,
        type=ProcessType.group,
    )
    db.add_all([color, size, w1, w2, product, zc, cx])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="QT-001",
        customer_name="测试",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=100,
        delivery_date=date.today() + timedelta(days=10),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            color_id=color.id,
            size_id=size.id,
            qty=50,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=zc.id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=100,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "product": product,
        "color": color,
        "size": size,
        "w1": w1,
        "w2": w2,
        "zc": zc,
        "cx": cx,
        "segment": segment,
    }


def _bundle_with_reports(db, ctx, workers):
    unit = trace_service.create_bundle(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        qty=10,
        color_id=ctx["color"].id,
        size_id=ctx["size"].id,
        worker_id=ctx["w1"].id,
        process_id=ctx["zc"].id,
    )
    for w in workers:
        db.add(
            TraceUnitLog(
                tenant_id=ctx["tenant"].id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.report,
                worker_id=w.id,
                process_id=ctx["zc"].id,
                qty=5,
                note="报工",
            )
        )
    unit.status = TraceUnitStatus.in_process
    db.commit()
    db.refresh(unit)
    return unit


def test_suggest_high_and_medium_and_group(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    d = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
    )
    assert d["worker_id"] == ctx["w1"].id
    assert d["confidence"] == "high"
    assert "张三" in (d["basis"] or "")
    assert len(d["candidates"]) == 1

    unit2 = _bundle_with_reports(db, ctx, [ctx["w1"], ctx["w2"]])
    d2 = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit2.id,
        responsible_process_id=ctx["zc"].id,
    )
    assert d2["confidence"] == "medium"
    assert len(d2["candidates"]) == 2

    dg = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["cx"].id,
    )
    assert dg["confidence"] == "none"
    assert dg["worker_id"] is None
    assert "集体" in (dg["basis"] or "")


def test_create_defect_requires_bundle_when_active(db):
    ctx = _seed(db)
    _bundle_with_reports(db, ctx, [ctx["w1"]])
    with pytest.raises(TraceError) as ei:
        trace_service.create_defect_event(
            db,
            tenant_id=ctx["tenant"].id,
            defect_type="dirty",
            qty=1,
            order_id=ctx["order"].id,
            auto_suggest_worker=False,
        )
    assert ei.value.code == "trace_unit_required"


def test_create_defect_allow_weak_without_active_bundle(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        auto_suggest_worker=False,
    )
    assert event.trace_unit_id is None
    out = trace_service.defect_out(db, event)
    assert out["trace_quality"] == "weak"


def test_create_defect_keeps_brand_size_and_side_quantities(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=3,
        order_id=ctx["order"].id,
        size_id=ctx["size"].id,
        found_process_id=ctx["zc"].id,
        brand_name="测试品牌",
        left_qty=2,
        right_qty=1,
        auto_suggest_worker=False,
    )
    out = trace_service.defect_out(db, event)
    assert out["brand_name"] == "测试品牌"
    assert out["size_value"] == "40"
    assert out["found_process_name"] == "针车"
    assert out["qty"] == 3
    assert out["left_qty"] == 2
    assert out["right_qty"] == 1


def test_create_defect_rejects_mismatched_side_total(db):
    ctx = _seed(db)
    with pytest.raises(TraceError) as ei:
        trace_service.create_defect_event(
            db,
            tenant_id=ctx["tenant"].id,
            defect_type="dirty",
            qty=2,
            order_id=ctx["order"].id,
            left_qty=2,
            right_qty=1,
            auto_suggest_worker=False,
        )
    assert ei.value.code == "invalid_side_total"


def test_trace_quality_strong_partial(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    strong = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="open_seam",
        qty=1,
        order_id=ctx["order"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
        responsible_worker_id=ctx["w1"].id,
        auto_suggest_worker=False,
    )
    assert trace_service.defect_out(db, strong)["trace_quality"] == "strong"

    partial = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
        auto_suggest_worker=False,
    )
    assert trace_service.defect_out(db, partial)["trace_quality"] == "partial"

    listed = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="weak", page=1, page_size=20
    )
    assert listed["total"] == 0
    listed_p = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="partial", page=1, page_size=20
    )
    assert listed_p["total"] == 1
    listed_s = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="strong", page=1, page_size=20
    )
    assert listed_s["total"] == 1


def test_quality_trace_lookup_by_code_and_order(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    by_code = trace_service.quality_trace_lookup(
        db, tenant_id=ctx["tenant"].id, q=unit.code
    )
    assert by_code["order"]["order_no"] == "QT-001"
    assert by_code["focus_unit"]["code"] == unit.code
    assert len(by_code["focus_unit"]["logs"]) >= 1

    by_order = trace_service.quality_trace_lookup(
        db, tenant_id=ctx["tenant"].id, q="QT-001"
    )
    assert by_order["units_summary"]["total"] >= 1
    assert by_order["focus_unit"] is None


def test_update_defect_writes_responsibility_note(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        responsible_worker_id=ctx["w1"].id,
        auto_suggest_worker=False,
    )
    updated = trace_service.update_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
        responsible_worker_id=ctx["w2"].id,
        updated_by_user_id=99,
    )
    assert "[改责]" in (updated.note or "")
    assert "张三" in (updated.note or "")
    assert "李四" in (updated.note or "")
    assert "user#99" in (updated.note or "")


def test_delete_defect_removes_event_and_responsibilities(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        loss_amount=10,
        company_share_percent=50,
        responsibilities=[{"worker_id": ctx["w1"].id, "share_percent": 50}],
        auto_suggest_worker=False,
    )
    event_id = event.id

    trace_service.delete_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event_id,
    )

    assert db.get(DefectEvent, event_id) is None
    assert db.scalar(
        select(DefectResponsibility).where(
            DefectResponsibility.defect_event_id == event_id
        )
    ) is None


def test_delete_defect_removes_linked_pending_material_doc(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        auto_suggest_worker=False,
    )
    doc = StockDoc(
        tenant_id=ctx["tenant"].id,
        doc_no="LL-DEFECT-PENDING",
        doc_type=StockDocType.issue,
        status=StockDocStatus.pending,
        order_id=ctx["order"].id,
        defect_event_ids=[event.id],
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id

    trace_service.delete_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
    )

    assert db.get(DefectEvent, event.id) is None
    assert db.get(StockDoc, doc_id) is None


def test_delete_defect_keeps_posted_material_doc(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        auto_suggest_worker=False,
    )
    doc = StockDoc(
        tenant_id=ctx["tenant"].id,
        doc_no="LL-DEFECT-POSTED",
        doc_type=StockDocType.issue,
        status=StockDocStatus.posted,
        order_id=ctx["order"].id,
        defect_event_ids=[event.id],
    )
    db.add(doc)
    db.commit()

    with pytest.raises(TraceError) as exc:
        trace_service.delete_defect(
            db,
            tenant_id=ctx["tenant"].id,
            defect_id=event.id,
        )

    assert exc.value.code == "material_doc_posted"
    assert db.get(DefectEvent, event.id) is not None
    assert db.get(StockDoc, doc.id) is not None


def test_create_defect_batch_with_multiple_sizes_and_photos(db):
    ctx = _seed(db)
    size_41 = Size(tenant_id=ctx["tenant"].id, size_value="41")
    db.add(size_41)
    db.flush()
    events = trace_service.create_defect_events_batch(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        size_lines=[
            {"size_id": ctx["size"].id, "left_qty": 1, "right_qty": 0, "loss_amount": 12},
            {"size_id": size_41.id, "left_qty": 0, "right_qty": 2, "loss_amount": 34},
        ],
        order_id=ctx["order"].id,
        found_process_id=ctx["zc"].id,
        brand_name="测试品牌",
        photo_urls=["/uploads/defect_a.jpg", "/uploads/defect_b.jpg"],
        auto_suggest_worker=False,
    )
    assert len(events) == 2
    outs = [trace_service.defect_out(db, event) for event in events]
    assert outs[0]["size_value"] == "40"
    assert outs[0]["left_qty"] == 1
    assert outs[1]["size_value"] == "41"
    assert outs[1]["right_qty"] == 2
    assert outs[0]["loss_amount"] == 12
    assert outs[1]["loss_amount"] == 34
    assert outs[0]["photo_urls"] == ["/uploads/defect_a.jpg", "/uploads/defect_b.jpg"]
    assert outs[1]["photo_urls"] == ["/uploads/defect_a.jpg", "/uploads/defect_b.jpg"]


def test_create_defect_batch_rejects_duplicate_size(db):
    ctx = _seed(db)
    with pytest.raises(TraceError) as ei:
        trace_service.create_defect_events_batch(
            db,
            tenant_id=ctx["tenant"].id,
            defect_type="dirty",
            size_lines=[
                {"size_id": ctx["size"].id, "left_qty": 1, "right_qty": 0},
                {"size_id": ctx["size"].id, "left_qty": 0, "right_qty": 1},
            ],
            order_id=ctx["order"].id,
            auto_suggest_worker=False,
        )
    assert ei.value.code == "duplicate_size"


def test_add_defect_size_lines_keeps_registration_group(db):
    ctx = _seed(db)
    size_41 = Size(tenant_id=ctx["tenant"].id, size_value="41")
    db.add(size_41)
    db.flush()
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        size_id=ctx["size"].id,
        left_qty=1,
        right_qty=0,
        brand_name="测试品牌",
        auto_suggest_worker=False,
    )

    added = trace_service.add_defect_size_lines(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
        size_lines=[{"size_id": size_41.id, "left_qty": 0, "right_qty": 2}],
    )

    assert len(added) == 1
    assert added[0].size_id == size_41.id
    assert added[0].qty == 2
    detail = trace_service.get_defect_detail(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
    )
    assert {item["size_value"] for item in detail["registration_items"]} == {"40", "41"}


def test_add_defect_size_lines_repairs_external_order_without_employee_allocation(db):
    ctx = _seed(db)
    size_41 = Size(tenant_id=ctx["tenant"].id, size_value="41")
    partner = Partner(tenant_id=ctx["tenant"].id, name="外协厂", is_subcontractor=True)
    db.add_all([size_41, partner])
    db.flush()
    subcontract = SubcontractOrder(
        tenant_id=ctx["tenant"].id,
        subcontract_no="WF-TEST-001",
        partner_id=partner.id,
        order_id=ctx["order"].id,
        total_qty=10,
    )
    db.add(subcontract)
    db.flush()
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        size_id=ctx["size"].id,
        left_qty=1,
        right_qty=0,
        company_share_percent=0,
        auto_suggest_worker=False,
    )
    event.scrap_source = "subcontract"
    event.subcontract_order_id = subcontract.id
    event.responsible_party_type = "employee"
    db.commit()

    added = trace_service.add_defect_size_lines(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
        size_lines=[{"size_id": size_41.id, "left_qty": 1, "right_qty": 1}],
    )

    db.refresh(event)
    assert event.responsible_party_type == "subcontractor"
    assert added[0].responsible_party_type == "subcontractor"
    assert added[0].qty == 2


def test_create_defect_with_loss_allocation_at_register(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=2,
        order_id=ctx["order"].id,
        found_process_id=ctx["zc"].id,
        responsible_process_id=ctx["zc"].id,
        disposition="scrap",
        loss_amount=100,
        company_share_percent=40,
        responsibilities=[
            {"worker_id": ctx["w1"].id, "share_percent": 36},
            {"worker_id": ctx["w2"].id, "share_percent": 24},
        ],
        auto_suggest_worker=False,
    )
    out = trace_service.defect_out(db, event)
    assert float(out["loss_amount"]) == 100
    assert out["company_share_percent"] == 40
    assert len(out["responsibilities"]) == 2
    assert out["responsible_worker_id"] == ctx["w1"].id
    assert event.scrap_confirmed_at is None
    assert out["wage_deduction_from_event"] is False


def test_defect_loss_quote_accumulates_material_segments_and_wages_to_found_process(db):
    ctx = _seed(db)
    header = ExecutionHeader(
        tenant_id=ctx["tenant"].id,
        header_no="XE-QT-001",
        own_product_id=ctx["product"].id,
        shop_order_id=ctx["order"].id,
        total_qty=100,
    )
    db.add(header)
    db.flush()
    process = db.scalar(
        select(OrderProcess).where(OrderProcess.order_id == ctx["order"].id)
    )
    process.header_id = header.id
    process.segment_id = ctx["segment"].id
    forming_segment = ProcessSegment(
        tenant_id=ctx["tenant"].id,
        name="成型段",
        code="forming",
        sort_order=2,
    )
    db.add(forming_segment)
    db.flush()
    ctx["cx"].segment_id = forming_segment.id
    forming_process = OrderProcess(
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        header_id=header.id,
        process_id=ctx["cx"].id,
        process_name="成型",
        process_type=ProcessType.group,
        segment_id=forming_segment.id,
        plan_qty=100,
        status=OrderProcessStatus.pending,
    )
    db.add_all(
        [
            forming_process,
            OrderMaterialRequirement(
                tenant_id=ctx["tenant"].id,
                order_id=ctx["order"].id,
                header_id=header.id,
                supplier_product_id=999,
                qty_per_pair=Decimal("2"),
                unit_price=Decimal("5"),
                required_qty=Decimal("200"),
                consume_segment_id=ctx["segment"].id,
            ),
            OrderMaterialRequirement(
                tenant_id=ctx["tenant"].id,
                order_id=ctx["order"].id,
                header_id=header.id,
                supplier_product_id=998,
                qty_per_pair=Decimal("1"),
                unit_price=Decimal("4"),
                required_qty=Decimal("100"),
                consume_segment_id=forming_segment.id,
            ),
            OwnProductLabor(
                tenant_id=ctx["tenant"].id,
                own_product_id=ctx["product"].id,
                process_id=ctx["zc"].id,
                process_name="针车",
                unit_price=Decimal("3"),
                segment_id=ctx["segment"].id,
            ),
            OwnProductLabor(
                tenant_id=ctx["tenant"].id,
                own_product_id=ctx["product"].id,
                process_id=ctx["cx"].id,
                process_name="成型",
                unit_price=Decimal("5"),
                segment_id=forming_segment.id,
            ),
        ]
    )
    db.commit()

    quote = trace_service.calculate_defect_loss_quote(
        db,
        tenant_id=ctx["tenant"].id,
        header_id=header.id,
        order_process_id=forming_process.id,
    )
    assert quote["material_per_piece"] == 7.0
    assert quote["labor_per_piece"] == 4.0
    assert quote["labor_before_process_per_piece"] == 1.5

    requirements = list(
        db.scalars(
            select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
        ).all()
    )
    for requirement in requirements:
        requirement.arrived_qty = Decimal("100")
    defect_a = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=2,
        order_id=ctx["order"].id,
        header_id=header.id,
        size_id=ctx["size"].id,
        found_process_id=ctx["cx"].id,
        auto_suggest_worker=False,
    )
    defect_b = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="open_seam",
        qty=4,
        order_id=ctx["order"].id,
        header_id=header.id,
        size_id=ctx["size"].id,
        found_process_id=ctx["zc"].id,
        auto_suggest_worker=False,
    )
    db.commit()

    defect_a_kit = trace_service.get_defect_material_kit(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=defect_a.id,
    )
    assert defect_a_kit["qty"] == 2
    assert defect_a_kit["process_start_name"] == "针车"
    assert defect_a_kit["process_end_name"] == "成型"
    assert [Decimal(str(line["required_qty"])) for line in defect_a_kit["lines"]] == [
        Decimal("2.0000"),
        Decimal("1.0000"),
    ]
    assert defect_a_kit["kit_ok"] is True

    defect_b_kit = trace_service.get_defect_material_kit(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=defect_b.id,
    )
    assert defect_b_kit["process_end_name"] == "针车"
    assert [Decimal(str(line["required_qty"])) for line in defect_b_kit["lines"]] == [
        Decimal("4.0000")
    ]

    external_loss = trace_service.update_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=defect_a.id,
        scrap_source="subcontract",
        replacement_source="subcontract",
    )
    assert external_loss.loss_amount == Decimal("17.00")
    assert external_loss.material_loss_amount == Decimal("14.00")
    assert external_loss.labor_loss_amount == Decimal("3.00")

    with pytest.raises(TraceError) as invalid_source:
        trace_service.update_defect(
            db,
            tenant_id=ctx["tenant"].id,
            defect_id=defect_a.id,
            scrap_source="internal",
            replacement_source="subcontract",
        )
    assert invalid_source.value.code == "invalid_replacement_source"

    internal_loss = trace_service.update_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=defect_a.id,
        scrap_source="internal",
        replacement_source="internal",
    )
    assert internal_loss.loss_amount == Decimal("22.00")
    assert internal_loss.material_loss_amount == Decimal("14.00")
    assert internal_loss.labor_loss_amount == Decimal("8.00")

    replenishment = trace_service.create_defect_material_replenishment(
        db,
        tenant_id=ctx["tenant"].id,
        defect_ids=[defect_a.id, defect_b.id],
        created_by=ctx["w1"].id,
    )
    assert replenishment["issue_kind"] == "补料"
    assert replenishment["defect_event_ids"] == [defect_a.id, defect_b.id]
    assert [Decimal(str(line["qty"])) for line in replenishment["lines"]] == [
        Decimal("6.0000"),
        Decimal("1.0000"),
    ]
    detail = trace_service.get_defect_detail(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=defect_a.id,
    )
    assert detail["product_code"] == "QT-01"
    assert detail["material_docs"][0]["doc_no"] == replenishment["doc_no"]
    listed = trace_service.list_defects(
        db,
        tenant_id=ctx["tenant"].id,
        page=1,
        page_size=20,
    )
    linked = next(item for item in listed["items"] if item["id"] == defect_a.id)
    assert linked["material_doc_no"] == replenishment["doc_no"]

    with pytest.raises(TraceError) as duplicated:
        trace_service.create_defect_material_replenishment(
            db,
            tenant_id=ctx["tenant"].id,
            defect_ids=[defect_a.id],
        )
    assert duplicated.value.code == "already_replenished"


def test_supervisor_confirm_only_for_own_department_loss_bearers(db):
    from app.models import Department, Team

    ctx = _seed(db)
    cut_dep = Department(tenant_id=ctx["tenant"].id, name="裁断部", is_active=True)
    stitch_dep = Department(tenant_id=ctx["tenant"].id, name="针车部", is_active=True)
    db.add_all([cut_dep, stitch_dep])
    db.flush()

    leader = Employee(tenant_id=ctx["tenant"].id, name="裁断组长", mobile="13900000009", is_active=True)
    db.add(leader)
    db.flush()
    cut_dep.leader_id = leader.id
    ctx["w1"].department_id = cut_dep.id
    ctx["w2"].department_id = stitch_dep.id
    team = Team(
        tenant_id=ctx["tenant"].id,
        name="裁断一组",
        leader_worker_id=leader.id,
        department_id=cut_dep.id,
        is_active=True,
    )
    db.add(team)
    db.flush()

    own_dept_event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        disposition="scrap",
        loss_amount=50,
        company_share_percent=0,
        responsibilities=[{"worker_id": ctx["w1"].id, "share_percent": 100}],
        auto_suggest_worker=False,
    )
    other_dept_event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        disposition="scrap",
        loss_amount=50,
        company_share_percent=0,
        responsibilities=[{"worker_id": ctx["w2"].id, "share_percent": 100}],
        auto_suggest_worker=False,
    )
    company_only = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        disposition="scrap",
        loss_amount=50,
        company_share_percent=100,
        responsibilities=[],
        auto_suggest_worker=False,
    )

    assert trace_service.can_supervisor_confirm_defect(
        db, employee=leader, event=own_dept_event
    )
    assert not trace_service.can_supervisor_confirm_defect(
        db, employee=leader, event=other_dept_event
    )
    assert not trace_service.can_supervisor_confirm_defect(
        db, employee=leader, event=company_only
    )
    assert trace_service.can_supervisor_confirm_defect(
        db, employee=leader, event=company_only, viewer_is_tenant_wide=True
    )

    listed = trace_service.list_defects(
        db,
        tenant_id=ctx["tenant"].id,
        page=1,
        page_size=20,
        viewer=leader,
        scope_to_managed_departments=True,
    )
    listed_ids = {item["id"] for item in listed["items"]}
    assert own_dept_event.id in listed_ids
    assert other_dept_event.id not in listed_ids
    assert company_only.id not in listed_ids
    by_id = {item["id"]: item for item in listed["items"]}
    assert by_id[own_dept_event.id]["needs_my_confirm"] is True

    with pytest.raises(TraceError) as blocked:
        trace_service.confirm_defect_by_supervisor(
            db,
            tenant_id=ctx["tenant"].id,
            defect_id=other_dept_event.id,
            confirmed_by=leader.id,
            confirmer=leader,
        )
    assert blocked.value.code == "forbidden"

    confirmed = trace_service.confirm_defect_by_supervisor(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=own_dept_event.id,
        confirmed_by=leader.id,
        confirmer=leader,
    )
    assert confirmed.scrap_confirmed_at is not None
    assert confirmed.status.value == "closed"
