"""待采购只减实数：报工、按码完成、仓库、车间实点，以及本单已下单未到货。"""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    DefectDisposition,
    DefectEvent,
    Department,
    Employee,
    ExecutionHeader,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessAssignedDepartment,
    OwnProduct,
    OwnProductLabor,
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
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
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
    progress_header_warehouse_flags,
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
        completed_qty=Decimal("3"),
        segment_id=segment.id,
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


def test_segment_reported_qty_follows_progress_completion():
    """工序段报工与生产进度完工相同：最低完成率折算，未派到路线的工序不计入。"""
    db, tenant_id, _, leather_id, _ = _session()
    header = db.scalar(select(ExecutionHeader))
    product = db.scalar(select(OwnProduct))
    segment = db.scalar(select(ProcessSegment))
    leading = db.scalar(select(OrderProcess))
    leading.plan_qty = 10
    leading.completed_qty = Decimal("10")
    log = db.scalar(select(WorkLog))
    log.qualified_qty = Decimal("100")
    narrow_def = ProcessDefinition(
        tenant_id=tenant_id,
        name="拉中帮",
        code="MID",
        default_price=Decimal("1"),
        sort_order=2,
        segment_id=segment.id,
    )
    idle_def = ProcessDefinition(
        tenant_id=tenant_id,
        name="清洁",
        code="CLEAN",
        default_price=Decimal("1"),
        sort_order=3,
        segment_id=segment.id,
    )
    route_dept = Department(tenant_id=tenant_id, name="底部甲")
    other_dept = Department(tenant_id=tenant_id, name="底部乙")
    db.add_all([narrow_def, idle_def, route_dept, other_dept])
    db.flush()
    narrow = OrderProcess(
        tenant_id=tenant_id,
        header_id=header.id,
        process_id=narrow_def.id,
        process_name="拉中帮",
        plan_qty=4,
        completed_qty=Decimal("2"),
        segment_id=segment.id,
    )
    idle = OrderProcess(
        tenant_id=tenant_id,
        header_id=header.id,
        process_id=idle_def.id,
        process_name="清洁",
        plan_qty=10,
        completed_qty=Decimal("0"),
        segment_id=segment.id,
    )
    db.add_all([narrow, idle])
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product.id,
            process_id=idle_def.id,
            process_name="清洁",
            unit_price=Decimal("1"),
            department_id=route_dept.id,
        )
    )
    db.add(
        OrderProcessAssignedDepartment(
            tenant_id=tenant_id,
            order_process_id=idle.id,
            department_id=other_dept.id,
        )
    )
    db.commit()

    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id and not row["size_id"])
    # 段任务 10，完成率 min(10/10, 2/4)=0.5，完工 5。清洁未派到路线，不把完工打成 0。
    assert leather["orders"][0]["reported_qty"] == 5
    assert Decimal(str(leather["demand_qty"])) == Decimal("5")


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


def test_warehouse_status_uses_production_demand_without_transit():
    """齐套、缺料按仓库生产需求，不算在途。按码不减车间剩余，不分码要减。"""
    db, tenant_id, sole_id, leather_id, size_40 = _session()
    partner = db.scalar(select(Partner))
    header = db.scalar(select(ExecutionHeader))
    sole = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == sole_id,
            OrderMaterialRequirement.size_id == size_40,
        )
    )
    leather = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    sole.issued_qty = Decimal("1")
    db.add(
        WorkshopMaterialCount(
            tenant_id=tenant_id,
            header_id=header.id,
            supplier_product_id=sole_id,
            size_id=size_40,
            qty=Decimal("10"),
        )
    )
    db.add(
        WorkshopMaterialCount(
            tenant_id=tenant_id,
            header_id=header.id,
            supplier_product_id=leather_id,
            qty=Decimal("4"),
        )
    )
    db.add(SharedMaterialStock(tenant_id=tenant_id, supplier_product_id=sole_id, size_id=size_40, qty=Decimal("3")))
    db.add(SharedMaterialStock(tenant_id=tenant_id, supplier_product_id=leather_id, qty=Decimal("2")))
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-TRANSIT",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
    )
    db.add(po)
    db.flush()
    db.add_all(
        [
            PurchaseOrderLine(
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                supplier_product_id=sole_id,
                order_material_requirement_id=sole.id,
                size_id=size_40,
                qty=Decimal("20"),
                unit_price=Decimal("8"),
            ),
            PurchaseOrderLine(
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                supplier_product_id=leather_id,
                order_material_requirement_id=leather.id,
                qty=Decimal("20"),
                unit_price=Decimal("20"),
            ),
        ]
    )
    db.commit()

    balance = progress_requirement_balance(db, tenant_id)
    # 按码：6 − 领料 1 = 5，现存 3，在途 20 和车间 10 都不抵缺口。
    assert balance[sole.id]["shortage_qty"] == Decimal("2")
    assert balance[sole.id]["on_hand_qty"] == Decimal("3")
    assert balance[sole.id]["to_buy"] is False
    # 不分码：总用量 7 − 车间 4 = 3，现存 2，在途不抵。
    assert balance[leather.id]["shortage_qty"] == Decimal("1")
    assert balance[leather.id]["on_hand_qty"] == Decimal("2")
    assert balance[leather.id]["to_buy"] is False
    flags = progress_header_warehouse_flags(db, tenant_id)
    assert flags[header.id]["to_buy"] is False
    assert flags[header.id]["shortage_lines"] > 0


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
    # XE-2 还在待买里，库存盖住也不占用仓库。采购之后才按顺序占用。
    assert balance[second_req.id]["to_buy"] is True
    assert balance[second_req.id]["shortage_qty"] == Decimal("4")
    assert balance[second_req.id]["warehouse_qty"] == Decimal("5")
    assert balance[second_req.id]["workshop_qty"] == Decimal("2")
    assert balance[second_req.id]["total_usage_qty"] == Decimal("4")
    assert balance[first_req.id]["to_buy"] is False
    assert balance[first_req.id]["shortage_qty"] == Decimal("0")
    assert balance[first_req.id]["warehouse_qty"] == Decimal("5")
    assert balance[first_req.id]["workshop_qty"] == Decimal("2")
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


def test_negative_alert_is_not_added_to_to_buy():
    """已采购单把库存预警打成负数时，另一张待买单只按自己的总用量买。"""
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    product = db.scalar(select(OwnProduct))
    proc = db.scalar(select(ProcessDefinition))
    bought = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-SHORT",
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
            qty=Decimal("1"),
            unit_price=Decimal("20"),
        )
    )
    header_b = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-OPEN",
        own_product_id=product.id,
        total_qty=4,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(header_b)
    db.flush()
    db.add(
        OrderMaterialRequirement(
            tenant_id=tenant_id,
            header_id=header_b.id,
            supplier_product_id=leather_id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("4"),
            consume_process_id=proc.id,
        )
    )
    db.commit()

    data = list_purchase_demand(db, tenant_id)
    leather = next(row for row in data["lines"] if row["supplier_product_id"] == leather_id)
    assert Decimal(str(leather["alert_qty"])) < 0
    assert Decimal(str(leather["required_qty"])) == Decimal("4")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("4")


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


def test_unsubscribe_keeps_header_off_buy_list_and_warehouse_to_buy():
    """退订后生产单不回到待买，仓库字段也不再是待买。直接取消采购单则可以回到待买。"""
    from app.services.purchase_service import cancel_po, unsubscribe_po

    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    partner = db.scalar(select(Partner))
    header = db.scalar(select(ExecutionHeader))
    req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-UNSUB",
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

    unsubscribe_po(db, tenant_id, po.id, [{"line_id": line.id, "qty": Decimal("4")}])
    db.refresh(po)
    assert po.status == PurchaseOrderStatus.cancelled
    buy = list_purchase_demand(db, tenant_id)
    assert all(header.id not in {order["header_id"] for order in row["orders"]} for row in buy["lines"])
    assert progress_requirement_balance(db, tenant_id)[req.id]["to_buy"] is False
    assert progress_header_warehouse_flags(db, tenant_id)[header.id]["to_buy"] is False

    other = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-CANCEL",
        own_product_id=header.own_product_id,
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
    db.flush()
    cancelled = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-CANCEL",
        partner_id=partner.id,
        status=PurchaseOrderStatus.draft,
    )
    db.add(cancelled)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant_id,
            purchase_order_id=cancelled.id,
            supplier_product_id=leather_id,
            order_material_requirement_id=other_req.id,
            qty=Decimal("4"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()
    cancel_po(db, tenant_id, cancelled.id)
    after_cancel = list_purchase_demand(db, tenant_id)
    assert any(order["header_id"] == other.id for row in after_cancel["lines"] for order in row["orders"])
    assert progress_header_warehouse_flags(db, tenant_id)[other.id]["to_buy"] is True


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


def test_first_report_shows_issued_balance_before_any_count():
    """领过料但还没人报工清点时，输入框前显示车间余额，而不是空。"""
    db, tenant_id, _sole_id, leather_id, _size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    proc = db.scalar(select(ProcessDefinition))
    issuer = Employee(tenant_id=tenant_id, name="仓管")
    reporter = Employee(tenant_id=tenant_id, name="裁断")
    db.add_all([issuer, reporter])
    db.commit()
    adjust_workshop_count(
        db, tenant_id, header_id=header.id, supplier_product_id=leather_id,
        size_id=None, delta=Decimal("126"), user_id=issuer.id,
    )
    db.commit()
    rows = {
        row["label"]: row["last_qty"]
        for row in list_workshop_count_targets(db, tenant_id, header.id, {proc.id}, employee_id=reporter.id)
    }
    assert rows["面皮"] == "126"


def test_zero_to_buy_order_can_be_purchased_without_showing_the_po():
    """待采购都是 0 时仍可生成采购。采购单不显示。采购前不算实际需求，采购后才算。"""
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
    shown = [row for row in buy["lines"] if any(order["header_id"] == header.id for order in row["orders"])]
    assert shown
    assert all(Decimal(str(row["to_buy_qty"])) == Decimal("0") for row in shown)

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
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("0")
    assert rows[0]["alert_orders"] == []

    ids = []
    for row in shown:
        ids.extend(int(item) for item in (row.get("requirement_ids") or []) if int(item) > 0)
        for order in row["orders"]:
            if order.get("requirement_id"):
                ids.append(int(order["requirement_id"]))
    from app.services.purchase_service import count_pos_by_status, create_drafts_from_shortages, list_pos

    assert create_drafts_from_shortages(db, tenant_id, requirement_ids=ids) == []
    po_id = db.scalar(select(PurchaseOrder.id))
    assert po_id is not None
    lines = db.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po_id)
    ).all()
    assert lines
    assert all(line.qty == 0 for line in lines)
    assert list_pos(db, tenant_id) == []
    stats = count_pos_by_status(db, tenant_id)
    assert stats["by_status"]["draft"] == 0
    assert stats["total"] == 0

    after = list_purchase_demand(db, tenant_id)
    assert all(
        header.id not in {order["header_id"] for order in row["orders"]}
        for row in after["lines"]
    )
    _attach_stock_alerts(db, tenant_id, rows)
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("7")
    assert [order["header_id"] for order in rows[0]["alert_orders"]] == [header.id]


def test_covered_material_stays_beside_material_that_still_needs_buying():
    """同一生产单里，待采购为 0 的物料也留在待买，不跟还有缺口的料一起丢掉。"""
    db, tenant_id, sole_id, leather_id, size_40 = _session()
    size_42 = db.scalar(select(Size).where(Size.size_value == "42"))
    db.add_all(
        [
            SharedMaterialStock(
                tenant_id=tenant_id, supplier_product_id=sole_id, size_id=size_40, qty=Decimal("6")
            ),
            SharedMaterialStock(
                tenant_id=tenant_id, supplier_product_id=sole_id, size_id=size_42.id, qty=Decimal("4")
            ),
        ]
    )
    db.commit()
    buy = list_purchase_demand(db, tenant_id)
    leather = next(row for row in buy["lines"] if row["supplier_product_id"] == leather_id)
    soles = [row for row in buy["lines"] if row["supplier_product_id"] == sole_id]
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("10")
    assert soles
    assert all(Decimal(str(row["to_buy_qty"])) == Decimal("0") for row in soles)


def test_order_on_buy_list_does_not_count_as_actual_demand():
    """材料够用、待采购为 0 的生产单仍在待买里，不计入仓库实际需求，也不占用进度库存。"""
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
    assert any(order["header_id"] == header.id for row in buy["lines"] for order in row["orders"])
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
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("0")
    assert rows[0]["alert_orders"] == []
    balance = progress_requirement_balance(db, tenant_id)
    leather_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    assert balance[leather_req.id]["to_buy"] is True


def test_fully_consumed_order_leaves_to_buy_while_another_stays():
    """一笔单材料被报工扣完、不在待买里，计入实际需求且不显示待买。另一笔仍待买的不算。"""
    db, tenant_id, sole_id, leather_id, _size_40 = _session()
    for req in db.scalars(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.supplier_product_id == sole_id)
    ).all():
        db.delete(req)
    log = db.scalar(select(WorkLog))
    log.qualified_qty = Decimal("10")
    done = db.scalar(select(OrderProcess))
    done.completed_qty = Decimal("10")
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


def test_confirmed_scrap_rolls_into_main_order_and_stays_out_of_buy_list():
    """已确认报废补料加到主单用量，不单列报废行，也不抬高待买。"""
    db, tenant_id, _sole_id, leather_id, size_40 = _session()
    header = db.scalar(select(ExecutionHeader))
    proc = db.scalar(select(OrderProcess))
    leather_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == leather_id
        )
    )
    db.add(
        DefectEvent(
            tenant_id=tenant_id,
            header_id=header.id,
            found_process_id=proc.process_id,
            size_id=size_40,
            defect_type="scrap",
            qty=2,
            disposition=DefectDisposition.scrap,
            replacement_source="internal",
            scrap_confirmed_at=datetime(2026, 10, 23, 8, 0, 0),
        )
    )
    db.commit()

    buy = list_demand_shortages(db, tenant_id)
    leather = next(row for row in buy["lines"] if row["supplier_product_id"] == leather_id)
    assert [row["header_no"] for row in leather["orders"]] == ["XE-1"]
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("10")
    assert all(not str(row["header_no"] or "").endswith("报废") for row in leather["orders"])

    partner = db.scalar(select(Partner))
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no="PO-SCRAP",
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
            order_material_requirement_id=leather_req.id,
            qty=Decimal("7"),
            unit_price=Decimal("20"),
        )
    )
    db.commit()

    demand = list_purchase_demand(db, tenant_id, only_shortage=False)
    leather = next(row for row in demand["lines"] if row["supplier_product_id"] == leather_id)
    assert [row["header_no"] for row in leather["orders"]] == ["XE-1"]
    assert leather["orders"][0]["plan_qty"] == 10
    assert leather["orders"][0]["scrap_qty"] == 1
    assert Decimal(str(leather["orders"][0]["demand_qty"])) == Decimal("8")

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
    assert [order["header_no"] for order in rows[0]["alert_orders"]] == ["XE-1"]
    assert rows[0]["alert_orders"][0]["plan_qty"] == 10
    assert rows[0]["alert_orders"][0]["scrap_qty"] == 1
    assert Decimal(str(rows[0]["alert_orders"][0]["demand_qty"])) == Decimal("8")
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("8")
    bought = list_demand_shortages(db, tenant_id)
    assert all(row["supplier_product_id"] != leather_id for row in bought["lines"])

    sole_req = db.scalar(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.supplier_product_id == _sole_id,
            OrderMaterialRequirement.size_id == size_40,
        )
    )
    issue = StockDoc(
        tenant_id=tenant_id,
        doc_no="LL-SIZE",
        doc_type=StockDocType.issue,
        status=StockDocStatus.posted,
        header_id=header.id,
    )
    returned = StockDoc(
        tenant_id=tenant_id,
        doc_no="TL-SIZE",
        doc_type=StockDocType.return_mat,
        status=StockDocStatus.posted,
        header_id=header.id,
    )
    db.add_all([issue, returned])
    db.flush()
    db.add_all(
        [
            StockDocLine(
                tenant_id=tenant_id,
                stock_doc_id=issue.id,
                order_material_requirement_id=sole_req.id,
                supplier_product_id=_sole_id,
                qty=Decimal("2"),
            ),
            StockDocLine(
                tenant_id=tenant_id,
                stock_doc_id=returned.id,
                order_material_requirement_id=sole_req.id,
                supplier_product_id=_sole_id,
                qty=Decimal("1"),
            ),
        ]
    )
    db.commit()
    sized = [
        {
            "supplier_product_id": _sole_id,
            "size_id": size_40,
            "on_hand_qty": Decimal("0"),
            "in_transit_qty": Decimal("0"),
        }
    ]
    _attach_stock_alerts(db, tenant_id, sized)
    order = sized[0]["alert_orders"][0]
    assert order["required_qty"] == "6"
    assert order["picked_qty"] == "2"
    assert order["returned_qty"] == "1"
    assert order["scrap_material_qty"] == "1"
    # 6 - 2 + 1 + 1
    assert Decimal(str(sized[0]["actual_demand_qty"])) == Decimal("6")
