"""AU-I2 M2：筐直发虚拟入出，并按合单来源拆销售出货。"""

from sqlalchemy import select

from app.models import (
    Color, FgLedger, FgStock, OwnProduct, Receivable, Shipment, Size, Tenant,
    TraceUnit, TraceUnitStatus,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import FgError, direct_ship_basket
from app.services.packing_service import create_basket_prepack
from app.services.shop_floor_settings import save_shop_floor_patch
from tests.test_au_i2_fg_warehouse import _so_item, db


def test_direct_ship_requires_tenant_switch(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(db, order_no="SO-OFF", qty=10, product_id=product.id, color_id=color.id,
                    size_id=size.id, tenant_id=tenant.id)
    exe = create_execution(db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 10}])
    basket_id = cut_cards_for_execution(db, tenant_id=tenant.id, execution_id=exe.id,
                                        dry_run=False, bundle_size=10, mode="basket_bundles")["created"][0]["id"]
    create_basket_prepack(db, tenant.id, basket_id, pairs_per_carton=10)
    try:
        direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "直发开关关闭时必须拦截"
    except FgError as exc:
        assert exc.code == "direct_ship_disabled"


def test_direct_ship_virtual_ledger_and_split_sales_shipments(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(db, order_no="SO-DS-A", qty=30, product_id=product.id, color_id=color.id,
                 size_id=size.id, tenant_id=tenant.id)
    b = _so_item(db, order_no="SO-DS-B", qty=20, product_id=product.id, color_id=color.id,
                 size_id=size.id, tenant_id=tenant.id)
    exe = create_execution(db, tenant_id=tenant.id, items=[
        {"sales_order_line_item_id": a.id, "qty": 30},
        {"sales_order_line_item_id": b.id, "qty": 20},
    ])
    cut = cut_cards_for_execution(db, tenant_id=tenant.id, execution_id=exe.id,
                                  dry_run=False, bundle_size=50, mode="basket_bundles")
    # 合单分筐：SO-DS-A 30 / SO-DS-B 20 各自独立成筐
    assert len(cut["created"]) == 2
    created = {int(c["qty"]): c for c in cut["created"]}
    basket_a = created[30]["id"]
    basket_b = created[20]["id"]
    save_shop_floor_patch(db, tenant.id, {"allow_direct_ship": True})
    create_basket_prepack(db, tenant.id, basket_a, pairs_per_carton=10)
    create_basket_prepack(db, tenant.id, basket_b, pairs_per_carton=10)

    result_a = direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_a)
    assert result_a["status"] == "shipped"
    assert {row["sales_order_no"]: row["qty"] for row in result_a["produced_splits"] if row["qty"]} == {
        "SO-DS-A": 30,
    }
    result_b = direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_b)
    assert result_b["status"] == "shipped"
    assert {row["sales_order_no"]: row["qty"] for row in result_b["produced_splits"] if row["qty"]} == {
        "SO-DS-B": 20,
    }

    assert {row["sales_order_no"]: row["total_qty"] for row in result_b["shipments"]} == {
        "SO-DS-B": 20,
    }
    assert {row["sales_order_no"]: row["total_qty"] for row in result_a["shipments"]} == {
        "SO-DS-A": 30,
    }
    stock = db.scalar(select(FgStock).where(FgStock.tenant_id == tenant.id))
    assert int(stock.qty) == 0
    ledgers = list(
        db.scalars(select(FgLedger).where(FgLedger.trace_unit_id.in_([basket_a, basket_b]))).all()
    )
    assert [(x.direction, int(x.qty)) for x in ledgers] == [("in", 30), ("out", 30), ("in", 20), ("out", 20)]
    assert {s.sales_order_no for s in db.scalars(select(Shipment)).all()} == {"SO-DS-A", "SO-DS-B"}
    assert db.scalar(select(Receivable).where(Receivable.sales_order_no == "SO-DS-A")) is not None
    db.refresh(a)
    db.refresh(b)
    assert (a.produced_qty, a.shipped_qty, b.produced_qty, b.shipped_qty) == (30, 30, 20, 20)
    assert db.get(TraceUnit, basket_a).status == TraceUnitStatus.shipped
    assert db.get(TraceUnit, basket_b).status == TraceUnitStatus.shipped
