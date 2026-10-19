"""待采购只减实数：报工、按码完成、仓库、车间实点，以及本单已下单未到货。"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Employee,
    ExecutionHeader,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ProcessSizeOutput,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
    WorkLog,
    WorkLogStatus,
    WorkshopMaterialCount,
    WorkshopMaterialCountLog,
)
from app.services.purchase_demand_service import (
    PurchaseDemandError,
    adjust_workshop_count,
    dismiss_purchase_demand,
    list_purchase_demand,
    list_workshop_count_targets,
    progress_header_shortage_counts,
    progress_requirement_balance,
    require_workshop_counts,
    save_workshop_count,
)
from app.services.sales_order_service import list_demand_shortages


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="待采购厂")
    session.add(tenant)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="M-1", is_active=True)
    partner = Partner(tenant_id=tenant.id, name="底厂", is_supplier=True, is_active=True)
    session.add_all([product, partner])
    session.flush()
    segment = ProcessSegment(tenant_id=tenant.id, name="底部", code="cx", sort_order=1)
    session.add(segment)
    session.flush()
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="贴底",
        code="SOLE",
        default_price=Decimal("1"),
        sort_order=1,
        segment_id=segment.id,
    )
    session.add(proc)
    session.flush()
    size_40 = Size(tenant_id=tenant.id, size_value="40", sort_order=40)
    size_42 = Size(tenant_id=tenant.id, size_value="42", sort_order=42)
    session.add_all([size_40, size_42])
    session.flush()
    sole = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="SOLE",
        name="大底",
        unit_price=Decimal("8"),
        is_active=True,
    )
    leather = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=partner.id,
        product_code="LEA",
        name="面皮",
        unit_price=Decimal("20"),
        is_active=True,
    )
    session.add_all([sole, leather])
    session.flush()
    worker = Employee(tenant_id=tenant.id, name="张三")
    session.add(worker)
    session.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-1",
        own_product_id=product.id,
        total_qty=10,
        status=SpecExecutionStatus.confirmed,
    )
    session.add(header)
    session.flush()
    session.add_all(
        [
            SpecExecutionOrder(
                tenant_id=tenant.id,
                execution_no="XE-1-40",
                header_id=header.id,
                own_product_id=product.id,
                size_id=size_40.id,
                total_qty=6,
            ),
            SpecExecutionOrder(
                tenant_id=tenant.id,
                execution_no="XE-1-42",
                header_id=header.id,
                own_product_id=product.id,
                size_id=size_42.id,
                total_qty=4,
            ),
        ]
    )
    order_process = OrderProcess(
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=proc.id,
        process_name="贴底",
        plan_qty=10,
    )
    session.add(order_process)
    session.flush()
    session.add_all(
        [
            OrderMaterialRequirement(
                tenant_id=tenant.id,
                header_id=header.id,
                supplier_product_id=sole.id,
                qty_per_pair=Decimal("1"),
                required_qty=Decimal("6"),
                usage_by_size=True,
                size_id=size_40.id,
                consume_process_id=proc.id,
                consume_segment_id=segment.id,
            ),
            OrderMaterialRequirement(
                tenant_id=tenant.id,
                header_id=header.id,
                supplier_product_id=sole.id,
                qty_per_pair=Decimal("1"),
                required_qty=Decimal("4"),
                usage_by_size=True,
                size_id=size_42.id,
                consume_process_id=proc.id,
                consume_segment_id=segment.id,
            ),
            OrderMaterialRequirement(
                tenant_id=tenant.id,
                header_id=header.id,
                supplier_product_id=leather.id,
                qty_per_pair=Decimal("1"),
                required_qty=Decimal("10"),
                consume_process_id=proc.id,
                consume_segment_id=segment.id,
            ),
        ]
    )
    session.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            header_id=header.id,
            order_process_id=order_process.id,
            own_product_id=product.id,
            process_id=proc.id,
            qualified_qty=Decimal("3"),
            status=WorkLogStatus.valid,
        )
    )
    session.add(
        ProcessSizeOutput(
            tenant_id=tenant.id,
            header_id=header.id,
            process_id=proc.id,
            size_id=size_40.id,
            qty=2,
        )
    )
    session.commit()
    return session, tenant.id, sole.id, leather.id, size_40.id


def test_sized_completion_does_not_follow_total_work_report():
    db, tenant_id, sole_id, leather_id, size_40 = _session()
    data = list_purchase_demand(db, tenant_id)
    by_key = {(row["supplier_product_id"], row["size_id"]): row for row in data["lines"]}
    sole_40 = by_key[(sole_id, size_40)]
    leather = by_key[(leather_id, None)]
    assert Decimal(str(sole_40["demand_qty"])) == Decimal("6")
    assert sole_40["orders"][0]["plan_qty"] == 10
    assert sole_40["orders"][0]["usage_by_size"] is True
    assert sole_40["workshop_counted"] is False
    assert Decimal(str(sole_40["to_buy_qty"])) == Decimal("6")
    assert Decimal(str(leather["demand_qty"])) == Decimal("7")
    assert Decimal(str(leather["required_qty"])) == Decimal("10")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("10")
    assert leather["orders"][0]["reported_qty"] == 3


def test_reported_qty_uses_consume_segment_when_process_is_empty():
    db, tenant_id, _, leather_id, _ = _session()
    for req in db.scalars(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.supplier_product_id == leather_id)
    ).all():
        req.consume_process_id = None
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id and not row["size_id"])
    assert leather["orders"][0]["reported_qty"] == 3
    assert Decimal(str(leather["demand_qty"])) == Decimal("7")


def test_progress_warehouse_claimed_in_schedule_order():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    first = db.scalar(select(ExecutionHeader).where(ExecutionHeader.header_no == "XE-1"))
    first.schedule_sequence = 2
    second = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-2",
        own_product_id=first.own_product_id,
        total_qty=4,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=1,
    )
    db.add(second)
    db.flush()
    db.add(
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=second.id,
            supplier_product_id=leather_id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("4"),
        )
    )
    db.add(SharedMaterialStock(tenant_id=tenant_id, supplier_product_id=leather_id, qty=Decimal("5")))
    db.add(
        WorkshopMaterialCount(
            tenant_id=tenant_id,
            header_id=first.id,
            supplier_product_id=leather_id,
            qty=Decimal("2"),
        )
    )
    db.commit()

    balance = progress_requirement_balance(db, tenant_id)
    second_req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == second.id)
    )
    first_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.header_id == first.id,
            OrderMaterialRequirement.supplier_product_id == leather_id,
        )
    )
    assert balance[second_req.id]["demand_qty"] == Decimal("4")
    assert balance[second_req.id]["shortage_qty"] == Decimal("4")
    assert balance[second_req.id]["to_buy"] is True
    assert balance[first_req.id]["demand_qty"] == Decimal("7")
    assert balance[first_req.id]["shortage_qty"] == Decimal("5")
    assert balance[first_req.id]["to_buy"] is True
    counts = progress_header_shortage_counts(db, tenant_id)
    assert counts[second.id] >= 1
    assert counts[first.id] >= 1

    pooled = list_purchase_demand(db, tenant_id, only_shortage=False)
    leather = next(row for row in pooled["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["required_qty"])) == Decimal("14")
    assert Decimal(str(leather["alert_qty"])) == Decimal("5")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("9")


def test_only_purchased_headers_occupy_warehouse_in_schedule_order():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    first = db.scalar(select(ExecutionHeader).where(ExecutionHeader.header_no == "XE-1"))
    first.schedule_sequence = 2
    second = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-2",
        own_product_id=first.own_product_id,
        total_qty=4,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=1,
    )
    db.add(second)
    db.flush()
    second_req = OrderMaterialRequirement(
        tenant_id=tenant_id,
        header_id=second.id,
        supplier_product_id=leather_id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("4"),
    )
    db.add(second_req)
    db.add(SharedMaterialStock(tenant_id=tenant_id, supplier_product_id=leather_id, qty=Decimal("5")))
    db.add(
        WorkshopMaterialCount(
            tenant_id=tenant_id,
            header_id=first.id,
            supplier_product_id=leather_id,
            qty=Decimal("2"),
        )
    )
    db.flush()
    first_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.header_id == first.id,
            OrderMaterialRequirement.supplier_product_id == leather_id,
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-XE1",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=leather_id,
            order_material_requirement_id=first_req.id,
            qty=Decimal("5"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()

    balance = progress_requirement_balance(db, tenant_id)
    # XE-2 没有采购单，但现存、在途和车间剩余已经盖住，待买里不出现。按实际需求占用。
    assert balance[second_req.id]["to_buy"] is False
    assert balance[second_req.id]["shortage_qty"] == Decimal("0")
    assert balance[second_req.id]["warehouse_qty"] == Decimal("5")
    assert balance[second_req.id]["workshop_qty"] == Decimal("2")
    assert balance[second_req.id]["total_usage_qty"] == Decimal("4")
    assert balance[first_req.id]["to_buy"] is False
    assert balance[first_req.id]["shortage_qty"] == Decimal("4")
    assert balance[first_req.id]["warehouse_qty"] == Decimal("3")
    assert balance[first_req.id]["workshop_qty"] == Decimal("0")
    assert balance[first_req.id]["task_qty"] == Decimal("7")
    assert balance[first_req.id]["usage_qty"] == Decimal("1")
    assert balance[first_req.id]["total_usage_qty"] == Decimal("7")
    po2 = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-XE2",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po2)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po2.id,
            supplier_product_id=leather_id,
            order_material_requirement_id=second_req.id,
            qty=Decimal("4"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()
    balance = progress_requirement_balance(db, tenant_id)
    assert balance[first_req.id]["warehouse_qty"] == Decimal("3")
    assert balance[first_req.id]["workshop_qty"] == Decimal("0")


def test_dismissed_requirement_leaves_buy_list_only():
    db, tenant_id, sole_id, leather_id, _size_40 = _session()
    leather_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    assert dismiss_purchase_demand(db, tenant_id, [leather_req.id]) == 1
    buy = list_demand_shortages(db, tenant_id)
    buy_ids = {row["supplier_product_id"] for row in buy["lines"]}
    assert leather_id not in buy_ids
    assert sole_id in buy_ids
    still = list_purchase_demand(db, tenant_id)
    leather = next(row for row in still["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("10")


def test_unissued_allocation_counts_as_warehouse():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    req.arrived_qty = Decimal("4")
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["warehouse_qty"])) == Decimal("4")
    assert Decimal(str(leather["required_qty"])) == Decimal("10")
    assert Decimal(str(leather["alert_qty"])) == Decimal("4")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("6")


def test_unlinked_in_transit_does_not_reduce_to_buy():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-T",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=leather_id,
            qty=Decimal("6"),
            unit_price=Decimal("20"),
            received_qty=Decimal("0"),
        )
    )
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["demand_qty"])) == Decimal("7")
    assert Decimal(str(leather["alert_qty"])) == Decimal("6")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("4")


def test_purchased_header_not_listed_beside_a_new_order():
    """同一物料还要给新生产单买时，已经采购过的生产单不再出现在待买。"""
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    product = db.scalar(select(OwnProduct))
    bought = db.scalar(select(OrderMaterialRequirement).where(OrderMaterialRequirement.supplier_product_id == leather_id))
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-OLD",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=leather_id,
            order_material_requirement_id=bought.id,
            qty=Decimal("10"),
            unit_price=Decimal("20"),
        )
    )
    fresh = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-NEW",
        own_product_id=product.id,
        total_qty=8,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(fresh)
    db.flush()
    proc = db.scalar(select(ProcessDefinition))
    db.add(
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=fresh.id,
            supplier_product_id=leather_id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("8"),
            consume_process_id=proc.id,
        )
    )
    db.commit()

    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert {row["header_no"] for row in leather["orders"]} == {"XE-NEW"}


def test_linked_draft_leaves_buy_list():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-DRAFT",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
    )
    db.add(po)
    db.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant_id,
        purchase_order_id=po.id,
        supplier_product_id=leather_id,
        order_material_requirement_id=req.id,
        qty=Decimal("4"),
        unit_price=Decimal("20"),
    )
    db.add(line)
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    assert all(row["supplier_product_id"] != leather_id for row in data["lines"])
    assert all(row["supplier_product_id"] != _sole_id for row in data["lines"])
    buy = list_demand_shortages(db, tenant_id)
    assert all(row["supplier_product_id"] != leather_id for row in buy["lines"])
    assert all(row["supplier_product_id"] != _sole_id for row in buy["lines"])
    kept = list_purchase_demand(db, tenant_id, only_shortage=False)
    sole_orders = [
        order
        for row in kept["lines"]
        if row["supplier_product_id"] == _sole_id
        for order in row["orders"]
    ]
    assert sole_orders and all(order["has_purchase"] for order in sole_orders)
    from app.services.material_service import _attach_stock_alerts

    rows = [
        {
            "supplier_product_id": leather_id,
            "size_id": None,
            "on_hand_qty": Decimal("0"),
            "in_transit_qty": Decimal("0"),
        },
        {
            "supplier_product_id": _sole_id,
            "size_id": _size_40,
            "on_hand_qty": Decimal("0"),
            "in_transit_qty": Decimal("0"),
        },
    ]
    _attach_stock_alerts(db, tenant_id, rows)
    # 草稿未反馈也算实际需求：面皮生产需求 7，不按采购数量 4 截断。
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("7")
    # 只给面皮开了采购单，同单大底也按生产用量计入实际需求。
    assert Decimal(str(rows[1]["actual_demand_qty"])) == Decimal("6")


def test_unlinked_draft_counts_in_alert_like_warehouse():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-DRAFT-FREE",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=leather_id,
            qty=Decimal("7"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    # 未挂生产单的草稿也进仓库在途，待买预警取同一笔。
    assert Decimal(str(leather["alert_qty"])) == Decimal("7")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("3")


def test_confirmed_purchase_reduces_to_buy_until_received():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-LINKED",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    line = PurchaseOrderLine(
        tenant_id=tenant_id,
        purchase_order_id=po.id,
        supplier_product_id=leather_id,
        order_material_requirement_id=req.id,
        qty=Decimal("4"),
        unit_price=Decimal("20"),
        received_qty=Decimal("0"),
    )
    db.add(line)
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    assert all(row["supplier_product_id"] != leather_id for row in data["lines"])
    assert all(row["supplier_product_id"] != _sole_id for row in data["lines"])

    kept = list_purchase_demand(db, tenant_id, only_shortage=False)
    leather = next(row for row in kept["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["orders"][0]["purchased_qty"])) == Decimal("4")
    assert Decimal(str(leather["orders"][0]["unpurchased_qty"])) == Decimal("0")


def test_stock_and_workshop_count_reduce_to_buy_once():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    db.add(
        SharedMaterialStock(
            tenant_id=tenant_id,
            supplier_product_id=leather_id,
            qty=Decimal("2"),
        )
    )
    db.commit()
    before = list_purchase_demand(db, tenant_id)
    leather = next(row for row in before["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["required_qty"])) == Decimal("10")
    assert Decimal(str(leather["alert_qty"])) == Decimal("2")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("8")
    assert leather["workshop_counted"] is False

    save_workshop_count(
        db,
        tenant_id,
        header_id=header.id,
        supplier_product_id=leather_id,
        size_id=None,
        qty=Decimal("1"),
        user_id=None,
    )
    after = list_purchase_demand(db, tenant_id)
    leather = next(row for row in after["lines"] if row["supplier_product_id"] == leather_id)
    assert leather["workshop_counted"] is True
    assert Decimal(str(leather["workshop_qty"])) == Decimal("1")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("8")
    assert leather["orders"][0]["workshop_qty"] == "1"
    assert leather["orders"][0]["issued_qty"] == "0"
    assert db.scalar(select(WorkshopMaterialCount.id)) is not None


def test_report_must_count_workshop_before_submit():
    db, tenant_id, sole_id, leather_id, size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    proc = db.scalar(select(ProcessDefinition))
    size_42 = db.scalar(select(Size).where(Size.size_value == "42"))
    targets = list_workshop_count_targets(db, tenant_id, header.id, {proc.id})
    labels = {row["label"] for row in targets}
    assert labels == {"大底 40码", "大底 42码", "面皮"}
    other = ProcessDefinition(
        tenant_id=tenant_id,
        name="裁断",
        code="CUT",
        default_price=Decimal("1"),
        segment_id=None,
    )
    db.add(other)
    db.flush()
    assert list_workshop_count_targets(db, tenant_id, header.id, {other.id}) == []
    try:
        require_workshop_counts(db, tenant_id, header.id, {proc.id}, None, None)
        raise AssertionError("missing count should block")
    except PurchaseDemandError as exc:
        assert exc.code == "workshop_count_required"
    require_workshop_counts(
        db,
        tenant_id,
        header.id,
        {proc.id},
        [
            {"supplier_product_id": sole_id, "size_id": size_40, "qty": "1"},
            {"supplier_product_id": sole_id, "size_id": size_42.id, "qty": "0"},
            {"supplier_product_id": leather_id, "size_id": None, "qty": "2"},
        ],
        None,
    )
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    by_key = {(row["supplier_product_id"], row["size_id"]): row for row in data["lines"]}
    assert Decimal(str(by_key[(sole_id, size_40)]["to_buy_qty"])) == Decimal("6")
    assert Decimal(str(by_key[(leather_id, None)]["workshop_qty"])) == Decimal("2")
    assert Decimal(str(by_key[(leather_id, None)]["to_buy_qty"])) == Decimal("10")
    count = db.scalar(
        select(WorkshopMaterialCount).where(
            WorkshopMaterialCount.header_id == header.id,
            WorkshopMaterialCount.supplier_product_id == leather_id,
        )
    )
    assert count is not None
    assert Decimal(str(count.qty)) == Decimal("2")


def test_issue_and_return_adjust_workshop_per_header():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    adjust_workshop_count(
        db,
        tenant_id,
        header_id=header.id,
        supplier_product_id=leather_id,
        size_id=None,
        delta=Decimal("5"),
    )
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    req.issued_qty = Decimal("5")
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert leather["orders"][0]["issued_qty"] == "5"
    assert leather["orders"][0]["workshop_qty"] == "5"
    assert Decimal(str(leather["workshop_qty"])) == Decimal("5")

    adjust_workshop_count(
        db,
        tenant_id,
        header_id=header.id,
        supplier_product_id=leather_id,
        size_id=None,
        delta=Decimal("-2"),
    )
    req.issued_qty = Decimal("3")
    db.commit()
    after = list_purchase_demand(db, tenant_id)
    leather = next(row for row in after["lines"] if row["supplier_product_id"] == leather_id)
    assert leather["orders"][0]["issued_qty"] == "3"
    assert leather["orders"][0]["workshop_qty"] == "3"


def test_workshop_remaining_isolated_by_header():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    product = db.scalar(select(OwnProduct))
    header_a = db.scalar(select(ExecutionHeader))
    header_b = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-2",
        own_product_id=product.id,
        total_qty=10,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(header_b)
    db.flush()
    proc = db.scalar(select(ProcessDefinition))
    db.add(
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=header_b.id,
            supplier_product_id=leather_id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("10"),
            consume_process_id=proc.id,
        )
    )
    save_workshop_count(
        db,
        tenant_id,
        header_id=header_a.id,
        supplier_product_id=leather_id,
        size_id=None,
        qty=Decimal("4"),
        user_id=None,
        commit=False,
    )
    save_workshop_count(
        db,
        tenant_id,
        header_id=header_b.id,
        supplier_product_id=leather_id,
        size_id=None,
        qty=Decimal("1"),
        user_id=None,
        commit=False,
    )
    db.commit()
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    by_header = {row["header_id"]: row for row in leather["orders"]}
    assert by_header[header_a.id]["workshop_qty"] == "4"
    assert by_header[header_b.id]["workshop_qty"] == "1"
    assert Decimal(str(leather["workshop_qty"])) == Decimal("5")
    # 两张单都还没下采购单，实际需求不算待买里的量。
    from app.services.material_service import _attach_stock_alerts

    rows = [
        {
            "supplier_product_id": leather_id,
            "size_id": None,
            "on_hand_qty": Decimal("0"),
            "in_transit_qty": Decimal("0"),
        }
    ]
    _attach_stock_alerts(db, tenant_id, rows)
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("0")
    assert rows[0]["alert_orders"] == []

    partner = db.scalar(select(Partner))
    req_a = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.header_id == header_a.id,
            OrderMaterialRequirement.supplier_product_id == leather_id,
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-A",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            supplier_product_id=leather_id,
            order_material_requirement_id=req_a.id,
            qty=Decimal("2"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()
    _attach_stock_alerts(db, tenant_id, rows)
    # A 已下采购单。生产需求 7（用量 10 减报工 3），车间剩余 4，实际需求 3。采购单只下了 2，不截断。B 仍在待买，不算。
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("3")
    assert [order["header_id"] for order in rows[0]["alert_orders"]] == [header_a.id]


def test_workshop_qty_sums_each_persons_latest_count():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    proc = db.scalar(select(ProcessDefinition))
    first = Employee(tenant_id=tenant_id, name="甲")
    second = Employee(tenant_id=tenant_id, name="乙")
    db.add_all([first, second])
    db.commit()
    save_workshop_count(
        db, tenant_id, header_id=header.id, supplier_product_id=leather_id,
        size_id=None, qty=Decimal("300"), user_id=first.id,
    )
    save_workshop_count(
        db, tenant_id, header_id=header.id, supplier_product_id=leather_id,
        size_id=None, qty=Decimal("40"), user_id=second.id,
    )
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["workshop_qty"])) == Decimal("340")
    assert leather["orders"][0]["workshop_qty"] == "340"
    own = {
        row["label"]: row["last_qty"]
        for row in list_workshop_count_targets(db, tenant_id, header.id, {proc.id}, employee_id=first.id)
    }
    other = {
        row["label"]: row["last_qty"]
        for row in list_workshop_count_targets(db, tenant_id, header.id, {proc.id}, employee_id=second.id)
    }
    assert own["面皮"] == "300"
    assert other["面皮"] == "40"


def test_report_prefix_adds_pickups_after_last_count():
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    proc = db.scalar(select(ProcessDefinition))
    worker = Employee(tenant_id=tenant_id, name="胡可")
    db.add(worker)
    db.commit()
    save_workshop_count(
        db, tenant_id, header_id=header.id, supplier_product_id=leather_id,
        size_id=None, qty=Decimal("10"), user_id=worker.id,
    )
    counted_at = db.scalar(
        select(WorkshopMaterialCountLog.created_at).where(WorkshopMaterialCountLog.counted_by == worker.id)
    )
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.supplier_product_id == leather_id)
    )

    def pickup(doc_no, when, qty):
        row = WarehousePickup(
            tenant_id=tenant_id, doc_no=doc_no, kind=WarehousePickupKind.production,
            status=WarehousePickupStatus.signed, header_id=header.id,
            picker_employee_id=worker.id, picker_name=worker.name, signed_at=when,
        )
        db.add(row)
        db.flush()
        db.add(WarehousePickupLine(
            tenant_id=tenant_id, pickup_id=row.id, supplier_product_id=leather_id,
            requirement_id=req.id, material_name="面皮", material_code="L", qty=qty,
        ))

    pickup("PK-BEFORE", counted_at - timedelta(hours=8, minutes=5), Decimal("100"))
    pickup("PK-AFTER", counted_at - timedelta(hours=8) + timedelta(minutes=1), Decimal("100"))
    db.commit()
    rows = {
        row["label"]: row["last_qty"]
        for row in list_workshop_count_targets(db, tenant_id, header.id, {proc.id}, employee_id=worker.id)
    }
    assert rows["面皮"] == "110"
    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["orders"][0]["workshop_qty"])) == Decimal("110")


def test_order_absent_from_buy_list_counts_as_actual_demand():
    """材料够用、整单不在待买里时，计入仓库实际需求，生产单不再显示待买。"""
    db, tenant_id, sole_id, leather_id, size_40 = _session()
    size_42 = db.scalar(select(Size).where(Size.size_value == "42"))
    db.add_all(
        [
            SharedMaterialStock(tenant_id=tenant_id, supplier_product_id=leather_id, qty=Decimal("10")),
            SharedMaterialStock(
                tenant_id=tenant_id, supplier_product_id=sole_id, size_id=size_40, qty=Decimal("6")
            ),
            SharedMaterialStock(
                tenant_id=tenant_id, supplier_product_id=sole_id, size_id=size_42.id, qty=Decimal("4")
            ),
        ]
    )
    db.commit()
    header = db.scalar(select(ExecutionHeader))
    buy = list_purchase_demand(db, tenant_id)
    assert buy["to_buy_lines"] == 0
    from app.services.material_service import _attach_stock_alerts

    rows = [
        {
            "supplier_product_id": leather_id,
            "size_id": None,
            "on_hand_qty": Decimal("10"),
            "in_transit_qty": Decimal("0"),
        }
    ]
    _attach_stock_alerts(db, tenant_id, rows)
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("7")
    assert [order["header_id"] for order in rows[0]["alert_orders"]] == [header.id]
    balance = progress_requirement_balance(db, tenant_id)
    leather_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    assert balance[leather_req.id]["to_buy"] is False


def test_fully_consumed_order_leaves_to_buy_while_another_stays():
    """一笔单材料被报工扣完、不在待买里，计入实际需求且不显示待买。另一笔仍待买的不算。"""
    db, tenant_id, sole_id, leather_id, _size_40 = _session()
    for req in db.scalars(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.supplier_product_id == sole_id)
    ).all():
        db.delete(req)
    log = db.scalar(select(WorkLog))
    log.qualified_qty = Decimal("10")
    header = db.scalar(select(ExecutionHeader))
    product = db.scalar(select(OwnProduct))
    other = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-2",
        own_product_id=product.id,
        total_qty=4,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(other)
    db.flush()
    other_req = OrderMaterialRequirement(
        tenant_id=tenant_id,
        header_id=other.id,
        supplier_product_id=leather_id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("4"),
    )
    db.add(other_req)
    db.commit()

    buy = list_purchase_demand(db, tenant_id)
    leather = next(row for row in buy["lines"] if row["supplier_product_id"] == leather_id)
    assert {row["header_id"] for row in leather["orders"]} == {other.id}
    balance = progress_requirement_balance(db, tenant_id)
    used_req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert balance[used_req.id]["to_buy"] is False
    assert balance[other_req.id]["to_buy"] is True
    from app.services.material_service import _attach_stock_alerts

    rows = [
        {
            "supplier_product_id": leather_id,
            "size_id": None,
            "on_hand_qty": Decimal("0"),
            "in_transit_qty": Decimal("0"),
        }
    ]
    _attach_stock_alerts(db, tenant_id, rows)
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("0")
    assert [order["header_id"] for order in rows[0]["alert_orders"]] == [header.id]
