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
    WorkLogGroupShare,
    WorkLogStatus,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.cut_material_usage_service import cut_material_usage


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
    assert leather["average_usage"] == "0.1167"
    zhang, li, wang = shoe["employees"]
    assert leather["pickups"][str(zhang["id"])] == {"qty": "8", "usage_per_pair": "0.1333"}
    assert leather["pickups"][str(li["id"])] == {"qty": "4", "usage_per_pair": "0.1"}
    assert leather["pickups"][str(wang["id"])]["qty"] == "0"
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
                str(bare["employees"][0]["id"]): {"qty": "0", "usage_per_pair": "0"},
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
    assert picked["materials"][0]["pickups"][str(picked["employees"][0]["id"])] == {
        "qty": "6",
        "usage_per_pair": None,
    }
    db.close()
