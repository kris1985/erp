"""AU-I2 M3：按筐预装箱；无预装不可直发；直发落成箱挂出货单。"""

from sqlalchemy import select

from app.models import (
    Color,
    OwnProduct,
    PackingCarton,
    PackingPlan,
    PackingPlanStatus,
    Size,
    Tenant,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import FgError, direct_ship_basket
from app.services.packing_service import create_basket_prepack
from app.services.shop_floor_settings import save_shop_floor_patch
from tests.test_au_i2_fg_warehouse import _so_item, db


def test_basket_prepack_hangs_on_basket_and_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-PP-1",
        qty=24,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 24}]
    )
    basket_id = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=24,
        mode="basket_bundles",
    )["created"][0]["id"]

    plan = create_basket_prepack(
        db, tenant.id, basket_id, mode="single_size", pairs_per_carton=12
    )
    assert plan["basket_id"] == basket_id
    assert plan["execution_id"] == exe.id
    assert plan["carton_count"] == 2
    assert plan["total_qty"] == 24
    assert plan["status"] == "draft"


def test_direct_ship_requires_prepack(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-PP-OFF",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 10}]
    )
    basket_id = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=10,
        mode="basket_bundles",
    )["created"][0]["id"]
    save_shop_floor_patch(db, tenant.id, {"allow_direct_ship": True})
    try:
        direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "无预装必须拦截直发"
    except FgError as exc:
        assert exc.code == "prepack_required"


def test_direct_ship_settles_prepack_to_shipments(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-PP-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-PP-B",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    created = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=50,
        mode="basket_bundles",
    )["created"]
    # 合单分筐：SO-PP-A 30 / SO-PP-B 20 各自独立成筐
    assert len(created) == 2
    created = {int(c["qty"]): c for c in created}
    basket_a = created[30]["id"]
    basket_b = created[20]["id"]
    save_shop_floor_patch(db, tenant.id, {"allow_direct_ship": True})
    plan_a = create_basket_prepack(
        db, tenant.id, basket_a, mode="single_size", pairs_per_carton=10
    )
    assert plan_a["total_qty"] == 30
    plan_b = create_basket_prepack(
        db, tenant.id, basket_b, mode="single_size", pairs_per_carton=10
    )
    assert plan_b["total_qty"] == 20

    result = direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    assert result["prepack"]["status"] == "confirmed"
    assert {row["sales_order_no"]: row["total_qty"] for row in result["shipments"]} == {
        "SO-PP-A": 30,
    }
    result2 = direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_b)
    assert result2["prepack"]["status"] == "confirmed"
    assert {row["sales_order_no"]: row["total_qty"] for row in result2["shipments"]} == {
        "SO-PP-B": 20,
    }

    plan = db.get(PackingPlan, plan_a["id"])
    assert plan.status == PackingPlanStatus.confirmed
    cartons = list(
        db.scalars(select(PackingCarton).where(PackingCarton.plan_id == plan.id)).all()
    )
    assert cartons
    assert all(c.shipment_id for c in cartons)
    shipment_ids = {c.shipment_id for c in cartons}
    assert shipment_ids == {row["id"] for row in result["shipments"]}

    plan_b_row = db.get(PackingPlan, plan_b["id"])
    assert plan_b_row.status == PackingPlanStatus.confirmed
    cartons_b = list(
        db.scalars(select(PackingCarton).where(PackingCarton.plan_id == plan_b_row.id)).all()
    )
    assert cartons_b
    assert all(c.shipment_id for c in cartons_b)
    assert {c.shipment_id for c in cartons_b} == {row["id"] for row in result2["shipments"]}


def test_prepack_qty_mismatch_blocks_direct_ship(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-PP-MIS",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 20}]
    )
    basket_id = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=20,
        mode="basket_bundles",
    )["created"][0]["id"]
    create_basket_prepack(db, tenant.id, basket_id, pairs_per_carton=10)
    # 人为破坏：改箱合计，使闸门失败
    plan = db.scalar(
        select(PackingPlan).where(
            PackingPlan.basket_id == basket_id,
            PackingPlan.status == PackingPlanStatus.draft,
        )
    )
    carton = db.scalar(select(PackingCarton).where(PackingCarton.plan_id == plan.id).limit(1))
    carton.total_qty = int(carton.total_qty) - 1
    db.commit()
    save_shop_floor_patch(db, tenant.id, {"allow_direct_ship": True})
    try:
        direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "预装数量不符须拦截"
    except FgError as exc:
        assert exc.code == "prepack_qty_mismatch"
