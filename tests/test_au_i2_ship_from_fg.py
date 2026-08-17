"""AU-I2：已入库筐从 FG 出货 + 预装落成。"""

from sqlalchemy import select

from app.models import (
    Color,
    FgLedger,
    FgStock,
    OwnProduct,
    PackingCarton,
    PackingPlan,
    PackingPlanStatus,
    Receivable,
    Size,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import FgError, ship_warehoused_basket, warehouse_basket
from app.services.packing_service import create_basket_prepack, list_shipment_packing_cartons
from tests.test_au_i2_fg_warehouse import _so_item, db


def test_ship_from_fg_requires_prepack(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-FG-OFF",
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
    warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
    try:
        ship_warehoused_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "无预装须拦截"
    except FgError as exc:
        assert exc.code == "prepack_required"


def test_ship_from_fg_settles_prepack_and_decrements_stock(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-FG-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-FG-B",
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
    # 合单分筐：SO-FG-A 30 / SO-FG-B 20 各自独立成筐
    assert len(created) == 2
    created = {int(c["qty"]): c for c in created}
    basket_a = created[30]["id"]
    basket_b = created[20]["id"]
    plan_a = create_basket_prepack(db, tenant.id, basket_a, pairs_per_carton=10)
    plan_b = create_basket_prepack(db, tenant.id, basket_b, pairs_per_carton=10)
    warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_b)
    stock = db.scalar(select(FgStock).where(FgStock.tenant_id == tenant.id))
    assert int(stock.qty) == 50

    result = ship_warehoused_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    assert result["status"] == "shipped"
    assert result["prepack"]["status"] == "confirmed"
    assert {row["sales_order_no"]: row["total_qty"] for row in result["shipments"]} == {
        "SO-FG-A": 30,
    }
    result2 = ship_warehoused_basket(db, tenant_id=tenant.id, trace_unit_id=basket_b)
    assert result2["status"] == "shipped"
    assert result2["prepack"]["status"] == "confirmed"
    assert {row["sales_order_no"]: row["total_qty"] for row in result2["shipments"]} == {
        "SO-FG-B": 20,
    }
    assert db.get(TraceUnit, basket_a).status == TraceUnitStatus.shipped
    assert db.get(TraceUnit, basket_b).status == TraceUnitStatus.shipped
    ledgers = list(
        db.scalars(select(FgLedger).where(FgLedger.trace_unit_id.in_([basket_a, basket_b]))).all()
    )
    dirs = [(x.direction, int(x.qty)) for x in ledgers]
    assert ("in", 30) in dirs and ("in", 20) in dirs
    assert ("out", 30) in dirs and ("out", 20) in dirs
    assert any(x.ref_type == "fg_ship" for x in ledgers)

    plan_row = db.get(PackingPlan, plan_a["id"])
    assert plan_row.status == PackingPlanStatus.confirmed
    cartons = list(
        db.scalars(select(PackingCarton).where(PackingCarton.plan_id == plan_row.id)).all()
    )
    assert all(c.shipment_id for c in cartons)
    sh_id = result["shipments"][0]["id"]
    listed = list_shipment_packing_cartons(db, tenant.id, sh_id)
    assert listed
    assert db.scalar(select(Receivable).where(Receivable.sales_order_no == "SO-FG-A")) is not None
    db.refresh(a)
    db.refresh(b)
    assert (a.shipped_qty, b.shipped_qty) == (30, 20)


def test_ship_from_fg_rejects_non_warehoused(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-FG-OPEN",
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
    create_basket_prepack(db, tenant.id, basket_id, pairs_per_carton=10)
    try:
        ship_warehoused_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "未入库不可从 FG 出货"
    except FgError as exc:
        assert exc.code == "not_warehoused"
