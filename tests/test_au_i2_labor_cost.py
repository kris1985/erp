"""AU-I2 M4：入库按 ratio 归集人工成本线索；与计件可对账。"""

from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Color,
    OrderProcess,
    OwnProduct,
    ReportType,
    SalesLineLaborAllocation,
    Size,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Worker,
)
from app.services.execution_service import create_execution, cut_cards_for_execution
from app.services.fg_service import (
    list_execution_labor_allocations,
    header_piecework_total,
    split_money_by_ratio,
    warehouse_basket,
)
from tests.test_au_i2_fg_warehouse import _so_item, db


def _seed_piecework(db, *, tenant_id: int, header_id: int, product_id: int, qty: int, price: Decimal):
    worker = Worker(tenant_id=tenant_id, name="计件工")
    db.add(worker)
    db.flush()
    op = db.scalar(select(OrderProcess).where(OrderProcess.header_id == header_id).limit(1))
    assert op is not None
    db.add(
        WorkLog(
            tenant_id=tenant_id,
            worker_id=worker.id,
            order_id=None,
            header_id=header_id,
            order_process_id=op.id,
            own_product_id=product_id,
            process_id=op.process_id,
            qualified_qty=qty,
            unit_price=price,
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
        )
    )
    db.commit()


def test_split_money_by_ratio_last_eats_remainder():
    shares = split_money_by_ratio(Decimal("10.00"), [Decimal("0.6"), Decimal("0.4")])
    assert shares == [Decimal("6.00"), Decimal("4.00")]
    shares2 = split_money_by_ratio(Decimal("10.01"), [Decimal("0.6"), Decimal("0.4")])
    assert sum(shares2) == Decimal("10.01")
    assert shares2[0] == Decimal("6.00")
    assert shares2[1] == Decimal("4.01")


def test_warehouse_allocates_labor_by_ratio(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-LC-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-LC-B",
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
    basket_id = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=50,
        mode="basket_bundles",
    )["created"][0]["id"]
    # 计件 50×2.00 = 100.00 → 入库按 0.6/0.4 归集 60/40
    _seed_piecework(
        db,
        tenant_id=tenant.id,
        header_id=int(exe.header_id),
        product_id=product.id,
        qty=50,
        price=Decimal("2.00"),
    )
    assert header_piecework_total(db, tenant.id, int(exe.header_id)) == Decimal("100.00")

    result = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=basket_id)
    by_so = {row["sales_order_no"]: row["labor_amount"] for row in result["labor_splits"]}
    assert by_so == {"SO-LC-A": Decimal("60.00"), "SO-LC-B": Decimal("40.00")}

    db.refresh(a)
    db.refresh(b)
    assert Decimal(a.labor_cost) == Decimal("60.00")
    assert Decimal(b.labor_cost) == Decimal("40.00")

    clue = list_execution_labor_allocations(db, tenant_id=tenant.id, execution_id=exe.id)
    assert clue["shop_order_piecework_total"] == Decimal("100.00")
    assert clue["allocated_labor_total"] == Decimal("100.00")
    assert clue["unallocated_labor"] == Decimal("0.00")
    assert len(clue["items"]) == 2
    assert db.scalar(select(SalesLineLaborAllocation).limit(1)) is not None


def test_multi_basket_last_eats_labor_residual(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-LC-ONE",
        qty=50,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db, tenant_id=tenant.id, items=[{"sales_order_line_item_id": item.id, "qty": 50}]
    )
    created = cut_cards_for_execution(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=25,
        mode="basket_bundles",
    )["created"]
    assert len(created) == 2
    _seed_piecework(
        db,
        tenant_id=tenant.id,
        header_id=int(exe.header_id),
        product_id=product.id,
        qty=50,
        price=Decimal("1.00"),
    )
    r1 = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=created[0]["id"])
    r2 = warehouse_basket(db, tenant_id=tenant.id, trace_unit_id=created[1]["id"])
    total = sum(Decimal(x["labor_amount"]) for x in r1["labor_splits"] + r2["labor_splits"])
    assert total == Decimal("50.00")
    clue = list_execution_labor_allocations(db, tenant_id=tenant.id, execution_id=exe.id)
    assert clue["unallocated_labor"] == Decimal("0.00")
