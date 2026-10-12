"""待采购只减实数：报工、按码完成、仓库、在途、车间实点。"""

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
    ProcessSizeOutput,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    WorkLog,
    WorkLogStatus,
    WorkshopMaterialCount,
)
from app.services.purchase_demand_service import (
    PurchaseDemandError,
    adjust_workshop_count,
    list_purchase_demand,
    list_workshop_count_targets,
    require_workshop_counts,
    save_workshop_count,
)


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
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="贴底",
        code="SOLE",
        default_price=Decimal("1"),
        sort_order=1,
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
            ),
            OrderMaterialRequirement(
                tenant_id=tenant.id,
                header_id=header.id,
                supplier_product_id=leather.id,
                qty_per_pair=Decimal("1"),
                required_qty=Decimal("10"),
                consume_process_id=proc.id,
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
    assert sole_40["orders"][0]["usage_by_size"] is True
    assert sole_40["workshop_counted"] is False
    assert Decimal(str(sole_40["to_buy_qty"])) == Decimal("6")
    assert Decimal(str(leather["demand_qty"])) == Decimal("7")
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("7")


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
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("3")


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
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("5")
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
    assert Decimal(str(leather["to_buy_qty"])) == Decimal("4")
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
    assert Decimal(str(by_key[(sole_id, size_40)]["to_buy_qty"])) == Decimal("5")
    assert Decimal(str(by_key[(leather_id, None)]["workshop_qty"])) == Decimal("2")
    assert Decimal(str(by_key[(leather_id, None)]["to_buy_qty"])) == Decimal("5")
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
    # 生产需求：A 面皮还要 7，B 还要 10；实际需求按单减车间 = (7-4)+(10-1)=12
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
    assert Decimal(str(rows[0]["actual_demand_qty"])) == Decimal("12")
