"""裁断用料：只计裁断段已签收领料和有效合格报工。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    PricingUnit,
    ProcessDefinition,
    ProcessSegment,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
    WorkLog,
    WorkshopMaterialCount,
    WorkshopMaterialCountLog,
    WorkLogGroupShare,
    WorkLogStatus,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.cut_material_usage_service import _average_usage, cut_material_usage


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0) - LOCAL_OFFSET


def _world():
    db = _db()
    tenant = Tenant(name="裁断厂")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    db.add_all([cut, stitch])
    db.flush()
    cut_proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    stitch_proc = ProcessDefinition(tenant_id=tenant.id, name="针车", code="ST", segment_id=stitch.id)
    db.add_all([cut_proc, stitch_proc])
    partner = Partner(tenant_id=tenant.id, name="供应商", is_supplier=True)
    db.add(partner)
    db.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    meter = PricingUnit(tenant_id=tenant.id, name="米")
    db.add_all([black, meter])
    db.flush()

    def supplier(code, name, *, color=None, image=None):
        row = SupplierProduct(
            tenant_id=tenant.id,
            product_code=code,
            name=name,
            partner_id=partner.id,
            color_id=color.id if color else None,
            pricing_unit_id=meter.id,
            image_url=image,
        )
        db.add(row)
        db.flush()
        return row

    leather = supplier("L1", "皮料", color=black, image="/img/leather.png")
    midsole = supplier("Z1", "中底")
    extra = supplier("F1", "辅料")
    glue = supplier("G1", "胶水")
    unlabeled = supplier("U1", "未标注")
    off_bom = supplier("X1", "额外")
    mix_a = supplier("M1", "混用")
    picked_only = supplier("P1", "只领")

    def product(code, image=None):
        row = OwnProduct(tenant_id=tenant.id, product_code=code, image_url=image)
        db.add(row)
        db.flush()
        return row

    shoe = product("BR-1", "/img/br1.png")
    bare = product("BR-2")
    other = product("OTHER")
    mixed = product("MIX")
    pick_only = product("PICK")
    percent = product("100%")

    def bom(own, material, qty, segment, loss="0"):
        row = OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=own.id,
            supplier_product_id=material.id,
            qty=Decimal(qty),
            loss_rate=Decimal(loss),
            consume_segment_id=segment.id if segment else None,
        )
        db.add(row)
        return row

    bom(shoe, leather, "0.15", cut, loss="0.5")
    bom(shoe, leather, "0.15", cut, loss="0.2")
    bom(shoe, midsole, "2", cut)
    bom(shoe, extra, "0.011", cut)
    bom(shoe, glue, "1", stitch)
    bom(shoe, unlabeled, "1", None)
    bom(mixed, mix_a, "1", cut)
    bom(mixed, mix_a, "1.5", cut)
    bom(pick_only, picked_only, "1.25", cut)
    db.flush()

    def order(own, no):
        row = Order(
            tenant_id=tenant.id,
            order_no=no,
            customer_name="客户",
            own_product_id=own.id,
            total_qty=10,
        )
        db.add(row)
        db.flush()
        return row

    shoe_order = order(shoe, "SO-1")
    other_order = order(other, "SO-2")
    pick_order = order(pick_only, "SO-3")
    proc = OrderProcess(
        tenant_id=tenant.id,
        order_id=shoe_order.id,
        process_id=cut_proc.id,
        process_name="裁断",
        plan_qty=10,
        segment_id=cut.id,
    )
    db.add(proc)
    db.flush()

    def header(own, no):
        row = ExecutionHeader(
            tenant_id=tenant.id,
            header_no=no,
            own_product_id=own.id,
            total_qty=10,
            status=SpecExecutionStatus.confirmed,
        )
        db.add(row)
        db.flush()
        return row

    shoe_header = header(shoe, "HD-1")

    zhang = Employee(tenant_id=tenant.id, name="张三")
    li = Employee(tenant_id=tenant.id, name="李四")
    wang = Employee(tenant_id=tenant.id, name="王伟")
    sun = Employee(tenant_id=tenant.id, name="孙伟")
    zhao = Employee(tenant_id=tenant.id, name="赵六")
    db.add_all([zhang, li, wang, sun, zhao])
    db.flush()

    def requirement(material, segment, order_row=None):
        row = OrderMaterialRequirement(
            tenant_id=tenant.id,
            order_id=order_row.id if order_row else None,
            supplier_product_id=material.id,
            consume_segment_id=segment.id if segment else None,
        )
        db.add(row)
        db.flush()
        return row

    leather_req = requirement(leather, cut, shoe_order)
    glue_req = requirement(glue, stitch, shoe_order)
    unlabeled_req = requirement(unlabeled, None, shoe_order)
    off_bom_req = requirement(off_bom, cut, shoe_order)
    pick_req = requirement(picked_only, cut, pick_order)

    inside = date(2026, 9, 15)
    outside = date(2026, 10, 2)

    def log(worker, own, segment, qty, *, when=inside, status=WorkLogStatus.valid, process=None, defect=0):
        row = WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_id=shoe_order.id,
            order_process_id=proc.id,
            own_product_id=own.id,
            process_id=(process or cut_proc).id,
            qualified_qty=Decimal(qty),
            defect_qty=Decimal(defect),
            segment_id=segment.id if segment else None,
            status=status,
            created_at=_at(when),
        )
        db.add(row)
        db.flush()
        return row

    log(zhang, shoe, cut, "60", defect=5)
    group = log(zhang, shoe, cut, "999")
    db.add(
        WorkLogGroupShare(
            tenant_id=tenant.id,
            work_log_id=group.id,
            worker_id=li.id,
            pairs=Decimal("40"),
        )
    )
    log(zhang, shoe, stitch, "500", process=stitch_proc)
    log(zhang, shoe, cut, "30", status=WorkLogStatus.void)
    log(zhang, shoe, None, "20")
    log(zhang, shoe, cut, "70", when=outside)
    log(sun, bare, cut, "5")
    log(zhao, other, cut, "8")
    log(zhang, percent, cut, "3")
    log(li, mixed, cut, "10")

    seq = {"n": 0}

    def pickup(picker, when, kind, status, *, header_row=None, order_row=None, lines):
        seq["n"] += 1
        row = WarehousePickup(
            tenant_id=tenant.id,
            doc_no=f"PK-{seq['n']}",
            kind=kind,
            status=status,
            header_id=header_row.id if header_row else None,
            order_id=order_row.id if order_row else None,
            picker_employee_id=picker.id,
            picker_name=picker.name,
            signed_at=_at(when) if status == WarehousePickupStatus.signed else None,
        )
        db.add(row)
        db.flush()
        for material, req, qty in lines:
            db.add(
                WarehousePickupLine(
                    tenant_id=tenant.id,
                    pickup_id=row.id,
                    supplier_product_id=material.id,
                    requirement_id=req.id,
                    material_name=material.name or material.product_code,
                    material_code=material.product_code,
                    qty=Decimal(qty),
                )
            )
        db.flush()
        return row

    pickup(
        zhang,
        inside,
        WarehousePickupKind.production,
        WarehousePickupStatus.signed,
        header_row=shoe_header,
        order_row=other_order,
        lines=[(leather, leather_req, "8"), (glue, glue_req, "99"), (unlabeled, unlabeled_req, "20")],
    )
    pickup(
        li,
        inside,
        WarehousePickupKind.production,
        WarehousePickupStatus.signed,
        order_row=shoe_order,
        lines=[(leather, leather_req, "1.5"), (leather, leather_req, "2.5")],
    )
    pickup(
        wang,
        inside,
        WarehousePickupKind.production,
        WarehousePickupStatus.signed,
        header_row=shoe_header,
        lines=[(off_bom, off_bom_req, "3")],
    )
    pickup(
        zhang,
        inside,
        WarehousePickupKind.production,
        WarehousePickupStatus.pending,
        header_row=shoe_header,
        lines=[(leather, leather_req, "100")],
    )
    pickup(
        zhang,
        inside,
        WarehousePickupKind.dev,
        WarehousePickupStatus.signed,
        lines=[(leather, leather_req, "50")],
    )
    pickup(
        zhang,
        outside,
        WarehousePickupKind.production,
        WarehousePickupStatus.signed,
        header_row=shoe_header,
        lines=[(leather, leather_req, "7")],
    )
    pickup(
        wang,
        inside,
        WarehousePickupKind.production,
        WarehousePickupStatus.signed,
        order_row=pick_order,
        lines=[(picked_only, pick_req, "6")],
    )
    db.commit()
    return db, tenant


def _report(db, tenant, **kwargs):
    return cut_material_usage(
        db,
        tenant.id,
        date_from=kwargs.get("date_from", date(2026, 9, 1)),
        date_to=kwargs.get("date_to", date(2026, 9, 30)),
        factory_model=kwargs.get("factory_model"),
    )


def _model(report, code):
    return next(row for row in report["models"] if row["factory_model"] == code)


def _material(model, code):
    return next(row for row in model["materials"] if row["material_code"] == code)


def test_average_usage_divides_total_consumed_by_total_pairs():
    assert _average_usage(
        [1, 2],
        {1: Decimal("10"), 2: Decimal("30")},
        {1: Decimal("10"), 2: Decimal("5")},
    ) == "2.6667"


def test_cut_usage_counts_only_signed_cut_pickups_and_valid_reports():
    db, tenant = _world()
    report = _report(db, tenant, factory_model="br-1")
    assert [row["factory_model"] for row in report["models"]] == ["BR-1"]
    shoe = report["models"][0]
    assert shoe["image_url"] == "/img/br1.png"
    assert shoe["total_pairs"] == "100"
    assert [row["name"] for row in shoe["employees"]] == ["张三", "李四", "王伟"]
    assert [row["pairs"] for row in shoe["employees"]] == ["60", "40", "0"]
    assert [row["material_code"] for row in shoe["materials"]] == ["F1", "L1", "X1", "Z1"]

    leather = _material(shoe, "L1")
    assert leather["image_url"] == "/img/leather.png"
    assert leather["material_name"] == "皮料"
    assert leather["color_name"] == "黑"
    assert leather["unit_name"] == "米"
    assert leather["budget_qty"] == "0.15"
    assert leather["average_usage"] == "0"
    zhang, li, wang = shoe["employees"]
    assert leather["pickups"][str(zhang["id"])]["records"] == []
    assert leather["pickups"][str(zhang["id"])]["consumed_qty"] == "0"
    assert leather["pickups"][str(zhang["id"])]["usage_per_pair"] == "0"
    assert leather["pickups"][str(li["id"])]["consumed_qty"] == "0"
    assert leather["pickups"][str(li["id"])]["usage_per_pair"] == "0"
    assert leather["pickups"][str(wang["id"])]["consumed_qty"] == "0"
    assert leather["pickups"][str(wang["id"])]["usage_per_pair"] is None

    assert _material(shoe, "F1")["budget_qty"] == "0.011"
    assert _material(shoe, "F1")["average_usage"] == "0"
    assert _material(shoe, "Z1")["budget_qty"] == "2"
    extra = _material(shoe, "X1")
    assert extra["budget_qty"] is None
    assert extra["average_usage"] == "0"
    assert extra["pickups"][str(wang["id"])]["usage_per_pair"] is None
    assert extra["pickups"][str(zhang["id"])]["usage_per_pair"] == "0"

    bare = _model(_report(db, tenant), "BR-2")
    assert bare["materials"] == [
        {
            "supplier_product_id": None,
            "material_code": None,
            "material_name": None,
            "image_url": None,
            "color_name": None,
            "unit_name": None,
            "on_bom": False,
            "budget_qty": None,
            "average_usage": "0",
            "pickups": {
                str(bare["employees"][0]["id"]): {
                    "issued_qty": "0",
                    "return_qty": "0",
                    "consumed_qty": "0",
                    "usage_per_pair": "0",
                    "records": [],
                },
            },
        }
    ]
    assert bare["employees"][0]["name"] == "孙伟"
    assert bare["employees"][0]["pairs"] == "5"

    codes = [row["factory_model"] for row in _report(db, tenant)["models"]]
    assert "G1" not in codes
    assert "BR-1" in codes and "OTHER" in codes
    assert _report(db, tenant, factory_model="nope")["models"] == []
    assert [row["factory_model"] for row in _report(db, tenant, factory_model="%")["models"]] == ["100%"]
    assert _report(db, tenant, factory_model="zz%")["models"] == []
    db.close()


def test_cut_usage_budget_is_per_pair_and_blank_when_qty_differs():
    db, tenant = _world()
    mixed = _model(_report(db, tenant, factory_model="MIX"), "MIX")
    assert mixed["total_pairs"] == "10"
    assert mixed["materials"][0]["budget_qty"] is None
    assert mixed["materials"][0]["average_usage"] == "0"

    picked = _model(_report(db, tenant, factory_model="PICK"), "PICK")
    assert picked["total_pairs"] == "0"
    assert picked["employees"][0]["pairs"] == "0"
    assert picked["materials"][0]["budget_qty"] == "1.25"
    assert picked["materials"][0]["average_usage"] is None
    assert picked["materials"][0]["pickups"][str(picked["employees"][0]["id"])]["consumed_qty"] == "0"
    assert picked["materials"][0]["pickups"][str(picked["employees"][0]["id"])]["usage_per_pair"] is None
    db.close()


def test_cut_usage_finds_segment_by_name_when_code_is_blank():
    db = _db()
    tenant = Tenant(name="演示")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断部", code="", sort_order=1)
    db.add(cut)
    db.flush()
    proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    shoe = OwnProduct(tenant_id=tenant.id, product_code="2006001-01")
    worker = Employee(tenant_id=tenant.id, name="禹云风")
    db.add_all([proc, shoe, worker])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="SO-CUT",
        customer_name="客户",
        own_product_id=shoe.id,
        total_qty=10,
    )
    db.add(order)
    db.flush()
    order_proc = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=proc.id,
        process_name="裁断",
        plan_qty=10,
        segment_id=cut.id,
    )
    db.add(order_proc)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_id=order.id,
            order_process_id=order_proc.id,
            own_product_id=shoe.id,
            process_id=proc.id,
            qualified_qty=Decimal("10"),
            segment_id=cut.id,
            status=WorkLogStatus.valid,
            created_at=_at(date(2026, 10, 16)),
        )
    )
    db.flush()
    report = cut_material_usage(db, tenant.id, date_from=date(2026, 10, 16), date_to=date(2026, 10, 16))
    assert [row["factory_model"] for row in report["models"]] == ["2006001-01"]
    assert report["models"][0]["total_pairs"] == "10"
    db.close()


def test_cut_usage_keeps_only_the_order_color():
    db = _db()
    tenant = Tenant(name="配色")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    white = Color(tenant_id=tenant.id, name="白", code="WH")
    db.add_all([cut, black, white])
    db.flush()
    proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    partner = Partner(tenant_id=tenant.id, name="皮行", is_supplier=True)
    shoe = OwnProduct(tenant_id=tenant.id, product_code="2006001-01")
    worker = Employee(tenant_id=tenant.id, name="禹云风")
    db.add_all([proc, partner, shoe, worker])
    db.flush()
    black_leather = SupplierProduct(
        tenant_id=tenant.id, product_code="3445", name="牛头层", partner_id=partner.id, color_id=black.id,
    )
    white_leather = SupplierProduct(
        tenant_id=tenant.id, product_code="3445", name="牛头层", partner_id=partner.id, color_id=white.id,
    )
    glue = SupplierProduct(
        tenant_id=tenant.id, product_code="GLUE", name="胶水", partner_id=partner.id,
    )
    db.add_all([black_leather, white_leather, glue])
    db.flush()
    db.add_all([
        OwnProductMaterial(
            tenant_id=tenant.id, own_product_id=shoe.id, supplier_product_id=black_leather.id,
            qty=Decimal("1.8"), consume_segment_id=cut.id, color_id=black.id,
        ),
        OwnProductMaterial(
            tenant_id=tenant.id, own_product_id=shoe.id, supplier_product_id=white_leather.id,
            qty=Decimal("1.9"), consume_segment_id=cut.id, color_id=white.id,
        ),
        OwnProductMaterial(
            tenant_id=tenant.id, own_product_id=shoe.id, supplier_product_id=glue.id,
            qty=Decimal("0.2"), consume_segment_id=cut.id, color_id=None,
        ),
    ])
    order = Order(
        tenant_id=tenant.id, order_no="SO-W", customer_name="客户", own_product_id=shoe.id, total_qty=10,
    )
    db.add(order)
    db.flush()
    order_proc = OrderProcess(
        tenant_id=tenant.id, order_id=order.id, process_id=proc.id, process_name="裁断",
        plan_qty=10, segment_id=cut.id,
    )
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="XE-W", own_product_id=shoe.id, color_id=white.id,
        total_qty=10, status=SpecExecutionStatus.cut,
    )
    db.add_all([order_proc, header])
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id, worker_id=worker.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal("10"), segment_id=cut.id, color_id=white.id,
            status=WorkLogStatus.valid, created_at=_at(date(2026, 10, 16)),
        )
    )
    db.flush()
    report = cut_material_usage(db, tenant.id, factory_model="2006001-01")
    codes = [row["material_code"] for row in report["models"][0]["materials"]]
    assert codes == ["3445", "GLUE"]
    leather = next(row for row in report["models"][0]["materials"] if row["material_code"] == "3445")
    assert leather["color_name"] == "白"
    assert leather["budget_qty"] == "1.9"
    db.close()


def test_cut_usage_consumes_pickup_minus_workshop_remain():
    db = _db()
    tenant = Tenant(name="剩余")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    db.add(cut)
    db.flush()
    proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    partner = Partner(tenant_id=tenant.id, name="皮行", is_supplier=True)
    shoe = OwnProduct(tenant_id=tenant.id, product_code="2006001-01")
    worker = Employee(tenant_id=tenant.id, name="禹云风")
    db.add_all([proc, partner, shoe, worker])
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id, product_code="3445", name="牛头层", partner_id=partner.id,
    )
    db.add(leather)
    db.flush()
    order = Order(
        tenant_id=tenant.id, order_no="SO-R", customer_name="客户", own_product_id=shoe.id, total_qty=10,
    )
    db.add(order)
    db.flush()
    order_proc = OrderProcess(
        tenant_id=tenant.id, order_id=order.id, process_id=proc.id, process_name="裁断",
        plan_qty=10, segment_id=cut.id,
    )
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="XE-R", own_product_id=shoe.id, total_qty=10,
        status=SpecExecutionStatus.cut,
    )
    db.add_all([order_proc, header])
    db.flush()
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id, order_id=order.id, header_id=header.id,
        supplier_product_id=leather.id, consume_segment_id=cut.id,
    )
    db.add(requirement)
    db.flush()
    when = datetime(2026, 10, 16, 16, 59)
    db.add(WorkLog(
        tenant_id=tenant.id, worker_id=worker.id, order_id=order.id, header_id=header.id,
        order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
        qualified_qty=Decimal("10"), segment_id=cut.id, status=WorkLogStatus.valid, created_at=when,
    ))
    pickup = WarehousePickup(
        tenant_id=tenant.id, doc_no="PK-R", kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed, header_id=header.id, picker_employee_id=worker.id,
        picker_name=worker.name, signed_at=when - LOCAL_OFFSET,
    )
    returned = WarehousePickup(
        tenant_id=tenant.id, doc_no="PK-B", kind=WarehousePickupKind.production_return,
        status=WarehousePickupStatus.signed, header_id=header.id, picker_employee_id=worker.id,
        picker_name=worker.name, signed_at=when - LOCAL_OFFSET,
    )
    db.add_all([pickup, returned])
    db.flush()
    db.add(WarehousePickupLine(
        tenant_id=tenant.id, pickup_id=pickup.id, supplier_product_id=leather.id,
        requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal("342"),
    ))
    db.add(WarehousePickupLine(
        tenant_id=tenant.id, pickup_id=returned.id, supplier_product_id=leather.id,
        requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal("12"),
    ))
    db.add(WorkshopMaterialCount(
        tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
        qty=Decimal("300"), counted_by=worker.id, counted_at=when,
    ))
    db.flush()
    report = cut_material_usage(db, tenant.id, date_from=date(2026, 10, 16), date_to=date(2026, 10, 16))
    cell = report["models"][0]["materials"][0]["pickups"][str(worker.id)]
    assert cell["issued_qty"] == "342"
    assert cell["return_qty"] == "12"
    assert cell["consumed_qty"] == "30"
    assert cell["usage_per_pair"] == "3"
    assert report["models"][0]["materials"][0]["average_usage"] == "3"
    assert cell["records"] == [
        {
            "work_log_id": cell["records"][0]["work_log_id"],
            "reported_at": "2026-10-16 16:59",
            "header_no": "XE-R",
            "issued_qty": "342",
            "opening_qty": "0",
            "return_qty": "12",
            "remain_qty": "300",
            "consumed_qty": "30",
            "pairs": "10",
        }
    ]
    db.close()


def test_cut_usage_lists_each_report_with_pickups_before_it():
    db = _db()
    tenant = Tenant(name="两次报工")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    db.add(cut)
    db.flush()
    proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    partner = Partner(tenant_id=tenant.id, name="皮行", is_supplier=True)
    shoe = OwnProduct(tenant_id=tenant.id, product_code="2006001-01")
    worker = Employee(tenant_id=tenant.id, name="禹云风")
    db.add_all([proc, partner, shoe, worker])
    db.flush()
    leather = SupplierProduct(tenant_id=tenant.id, product_code="3445", name="牛头层", partner_id=partner.id)
    db.add(leather)
    db.flush()
    order = Order(
        tenant_id=tenant.id, order_no="SO-2", customer_name="客户", own_product_id=shoe.id, total_qty=20,
    )
    db.add(order)
    db.flush()
    order_proc = OrderProcess(
        tenant_id=tenant.id, order_id=order.id, process_id=proc.id, process_name="裁断",
        plan_qty=20, segment_id=cut.id,
    )
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="XE-2", own_product_id=shoe.id, total_qty=20,
        status=SpecExecutionStatus.cut,
    )
    db.add_all([order_proc, header])
    db.flush()
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id, order_id=order.id, header_id=header.id,
        supplier_product_id=leather.id, consume_segment_id=cut.id,
    )
    db.add(requirement)
    db.flush()
    first_at = datetime(2026, 10, 16, 10, 0)
    second_at = datetime(2026, 10, 16, 18, 0)

    def report_at(moment, qty):
        db.add(WorkLog(
            tenant_id=tenant.id, worker_id=worker.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal(qty), segment_id=cut.id, status=WorkLogStatus.valid, created_at=moment,
        ))

    def move(doc_no, kind, moment, qty):
        pickup = WarehousePickup(
            tenant_id=tenant.id, doc_no=doc_no, kind=kind, status=WarehousePickupStatus.signed,
            header_id=header.id, picker_employee_id=worker.id, picker_name=worker.name,
            signed_at=moment - LOCAL_OFFSET,
        )
        db.add(pickup)
        db.flush()
        db.add(WarehousePickupLine(
            tenant_id=tenant.id, pickup_id=pickup.id, supplier_product_id=leather.id,
            requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal(qty),
        ))

    report_at(first_at, "10")
    report_at(second_at, "4")
    move("PK-1", WarehousePickupKind.production, datetime(2026, 10, 16, 9, 0), "342")
    move("PK-2", WarehousePickupKind.production, datetime(2026, 10, 16, 12, 0), "20")
    move("PK-3", WarehousePickupKind.production_return, datetime(2026, 10, 16, 13, 0), "5")
    db.add_all([
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("300"), created_at=first_at,
        ),
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("10"), created_at=second_at,
        ),
    ])
    db.flush()
    report = cut_material_usage(db, tenant.id, date_from=date(2026, 10, 16), date_to=date(2026, 10, 16))
    records = report["models"][0]["materials"][0]["pickups"][str(worker.id)]["records"]
    assert [(row["reported_at"], row["issued_qty"], row["opening_qty"], row["return_qty"], row["remain_qty"], row["consumed_qty"], row["pairs"]) for row in records] == [
        ("2026-10-16 10:00", "342", "0", "0", "300", "42", "10"),
        ("2026-10-16 18:00", "20", "300", "5", "10", "305", "4"),
    ]
    assert report["models"][0]["materials"][0]["pickups"][str(worker.id)]["consumed_qty"] == "347"
    db.close()


def test_cut_usage_remain_is_per_person():
    db = _db()
    tenant = Tenant(name="各算各的")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    db.add(cut)
    db.flush()
    proc = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="CT", segment_id=cut.id)
    partner = Partner(tenant_id=tenant.id, name="皮行", is_supplier=True)
    shoe = OwnProduct(tenant_id=tenant.id, product_code="2006001-01")
    first = Employee(tenant_id=tenant.id, name="禹云风")
    second = Employee(tenant_id=tenant.id, name="袁静")
    db.add_all([proc, partner, shoe, first, second])
    db.flush()
    leather = SupplierProduct(tenant_id=tenant.id, product_code="3445", name="牛头层", partner_id=partner.id)
    db.add(leather)
    db.flush()
    order = Order(
        tenant_id=tenant.id, order_no="SO-P", customer_name="客户", own_product_id=shoe.id, total_qty=20,
    )
    db.add(order)
    db.flush()
    order_proc = OrderProcess(
        tenant_id=tenant.id, order_id=order.id, process_id=proc.id, process_name="裁断",
        plan_qty=20, segment_id=cut.id,
    )
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="XE-P", own_product_id=shoe.id, total_qty=20,
        status=SpecExecutionStatus.cut,
    )
    db.add_all([order_proc, header])
    db.flush()
    requirement = OrderMaterialRequirement(
        tenant_id=tenant.id, order_id=order.id, header_id=header.id,
        supplier_product_id=leather.id, consume_segment_id=cut.id,
    )
    db.add(requirement)
    db.flush()
    first_at = datetime(2026, 10, 16, 10, 0)
    second_at = datetime(2026, 10, 16, 14, 0)
    later_at = datetime(2026, 10, 16, 16, 0)
    third_at = datetime(2026, 10, 16, 18, 0)
    db.add_all([
        WorkLog(
            tenant_id=tenant.id, worker_id=first.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal("10"), segment_id=cut.id, status=WorkLogStatus.valid, created_at=first_at,
        ),
        WorkLog(
            tenant_id=tenant.id, worker_id=second.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal("8"), segment_id=cut.id, status=WorkLogStatus.valid, created_at=second_at,
        ),
        WorkLog(
            tenant_id=tenant.id, worker_id=second.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal("6"), segment_id=cut.id, status=WorkLogStatus.valid, created_at=later_at,
        ),
        WorkLog(
            tenant_id=tenant.id, worker_id=first.id, order_id=order.id, header_id=header.id,
            order_process_id=order_proc.id, own_product_id=shoe.id, process_id=proc.id,
            qualified_qty=Decimal("4"), segment_id=cut.id, status=WorkLogStatus.valid, created_at=third_at,
        ),
    ])
    pickup = WarehousePickup(
        tenant_id=tenant.id, doc_no="PK-P", kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed, header_id=header.id,
        picker_employee_id=first.id, picker_name=first.name,
        signed_at=datetime(2026, 10, 16, 9, 0) - LOCAL_OFFSET,
    )
    other_pickup = WarehousePickup(
        tenant_id=tenant.id, doc_no="PK-Q", kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed, header_id=header.id,
        picker_employee_id=second.id, picker_name=second.name,
        signed_at=datetime(2026, 10, 16, 9, 30) - LOCAL_OFFSET,
    )
    later_pickup = WarehousePickup(
        tenant_id=tenant.id, doc_no="PK-L", kind=WarehousePickupKind.production,
        status=WarehousePickupStatus.signed, header_id=header.id,
        picker_employee_id=second.id, picker_name=second.name,
        signed_at=datetime(2026, 10, 16, 15, 0) - LOCAL_OFFSET,
    )
    db.add_all([pickup, other_pickup, later_pickup])
    db.flush()
    db.add_all([
        WarehousePickupLine(
            tenant_id=tenant.id, pickup_id=pickup.id, supplier_product_id=leather.id,
            requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal("342"),
        ),
        WarehousePickupLine(
            tenant_id=tenant.id, pickup_id=other_pickup.id, supplier_product_id=leather.id,
            requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal("100"),
        ),
        WarehousePickupLine(
            tenant_id=tenant.id, pickup_id=later_pickup.id, supplier_product_id=leather.id,
            requirement_id=requirement.id, material_name="牛头层", material_code="3445", qty=Decimal("100"),
        ),
    ])
    db.add_all([
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("300"), counted_by=first.id, created_at=first_at,
        ),
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("40"), counted_by=second.id, created_at=second_at,
        ),
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("20"), counted_by=second.id, created_at=later_at,
        ),
        WorkshopMaterialCountLog(
            tenant_id=tenant.id, header_id=header.id, supplier_product_id=leather.id,
            qty=Decimal("20"), counted_by=first.id, created_at=third_at,
        ),
    ])
    db.flush()
    report = cut_material_usage(db, tenant.id, date_from=date(2026, 10, 16), date_to=date(2026, 10, 16))
    pickups = report["models"][0]["materials"][0]["pickups"]

    def brief(emp_id):
        return [
            (row["reported_at"], row["issued_qty"], row["opening_qty"], row["remain_qty"], row["pairs"])
            for row in pickups[str(emp_id)]["records"]
        ]

    assert brief(first.id) == [
        ("2026-10-16 10:00", "342", "0", "300", "10"),
        ("2026-10-16 18:00", "0", "300", "20", "4"),
    ]
    assert brief(second.id) == [
        ("2026-10-16 14:00", "100", "0", "40", "8"),
        ("2026-10-16 16:00", "100", "40", "20", "6"),
    ]
    db.close()
