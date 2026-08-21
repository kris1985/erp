"""箱唛是唯一出货载体；按框预装仍须能在生产单详情追溯。"""

from sqlalchemy import select

from app.models import Color, OwnProduct, Size, Tenant
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import FgError, direct_ship_basket
from app.services.packing_service import create_basket_prepack, list_packing_plans
from tests.test_au_i2_fg_warehouse import _so_item, db


def _execution_with_basket(db, qty: int = 12):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-CARTON-ONLY",
        qty=qty,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    execution = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
    )
    basket_id = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=execution.id,
        dry_run=False,
        bundle_size=qty,
        mode="basket_bundles",
    )["created"][0]["id"]
    return tenant, execution, basket_id


def test_basket_cannot_ship_directly(db):
    tenant, _, basket_id = _execution_with_basket(db)
    try:
        direct_ship_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
        assert False, "框码必须禁止直发"
    except FgError as exc:
        assert exc.code == "carton_required"


def test_header_lists_prepack_cartons_created_from_basket(db):
    tenant, execution, basket_id = _execution_with_basket(db)
    created = create_basket_prepack(
        db, tenant.id, basket_id, mode="single_size", pairs_per_carton=12
    )
    plans = list_packing_plans(db, tenant.id, header_id=execution.header_id)
    assert [row["id"] for row in plans] == [created["id"]]
    assert plans[0]["carton_count"] == 1
    assert plans[0]["total_qty"] == 12
