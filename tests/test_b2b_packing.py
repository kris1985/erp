"""B2b：配码装箱 — 单码/混码合计一致 + 验箱错码拦。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
from app.services import packing_service
from app.services.packing_service import PackingError


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed(db):
    tenant = Tenant(name="装箱厂")
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="红", code="R")
    c2 = Color(tenant_id=tenant.id, name="黑", code="BK")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    s38 = Size(tenant_id=tenant.id, size_value="38", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="箱唛款", quote_price=Decimal("68"))
    db.add_all([c1, c2, s37, s38, product])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="PK-001",
        customer_name="箱唛客户",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=30,
        delivery_date=date.today() + timedelta(days=7),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add_all(
        [
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s37.id, qty=10
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s38.id, qty=8
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c2.id, size_id=s37.id, qty=12
            ),
        ]
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "c1": c1,
        "c2": c2,
        "s37": s37,
        "s38": s38,
    }


def test_single_size_pack_totals(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["mode"] == "single_size"
    assert plan["carton_count"] == 3
    assert sum(c["total_qty"] for c in plan["cartons"]) == 30
    for c in plan["cartons"]:
        assert len(c["lines"]) == 1


def test_mixed_pack_and_label_fields(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["carton_count"] == 3
    assert plan["cartons"][0]["order_no"] == "PK-001"
    assert plan["cartons"][0]["product_code"] == "箱唛款"
    assert plan["cartons"][0]["customer_name"] == "箱唛客户"
    assert plan["cartons"][0]["code"].startswith("CTN-PK-001-")


def test_verify_blocks_wrong_and_accepts_match(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    carton = plan["cartons"][0]
    line = carton["lines"][0]
    with pytest.raises(PackingError) as ei:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"] + 1}],
        )
    assert ei.value.code in ("over_pack", "wrong_size")

    with pytest.raises(PackingError) as ei2:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[
                {
                    "color_id": ctx["c2"].id,
                    "size_id": ctx["s38"].id,
                    "qty": line["qty"],
                }
            ],
        )
    assert ei2.value.code in ("wrong_size", "mismatch")

    ok = packing_service.verify_packing_carton(
        db,
        ctx["tenant"].id,
        carton["id"],
        lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"]}],
    )
    assert ok["verified_at"]


def test_carton_report_creates_work_log_and_dedups(db):
    """扫箱唛报工：装一箱报一箱，报工量=箱内双数，一箱只报一次。"""
    from decimal import Decimal as D

    from app.models import (
        Employee,
        ExecutionHeader,
        OrderProcess,
        OwnProductLabor,
        PackingCarton,
        PackingMode,
        PackingPlan,
        PackingPlanStatus,
        ProcessDefinition,
        ProcessSegment,
        ProcessType,
        WorkLog,
    )
    from app.services import report_service
    from app.services.segment_service import ensure_default_segments

    tenant = Tenant(name="扫箱报工厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    packing_seg = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "packing"
        )
    )
    box = ProcessDefinition(
        tenant_id=tenant.id, name="装箱", code="BX1", segment_id=packing_seg.id, type=ProcessType.personal
    )
    db.add(box)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SP-BOX")
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id, own_product_id=product.id, process_id=box.id,
            process_name="装箱", unit_price=D("0.20"), sort_order=0,
        )
    )
    db.flush()
    worker = Employee(tenant_id=tenant.id, name="装箱工", is_active=True)
    db.add(worker)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="EH-BOX", own_product_id=product.id, total_qty=100,
    )
    db.add(header)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id, header_id=header.id, process_id=box.id, process_name="装箱",
        process_type=ProcessType.personal, segment_id=packing_seg.id, plan_qty=100,
    )
    db.add(op)
    db.flush()
    plan = PackingPlan(
        tenant_id=tenant.id, header_id=header.id, mode=PackingMode.single_size,
        pairs_per_carton=12, status=PackingPlanStatus.draft,
    )
    db.add(plan)
    db.flush()
    carton = PackingCarton(
        tenant_id=tenant.id, plan_id=plan.id, seq=1, code="CTN-EH-BOX-0001", total_qty=12,
    )
    db.add(carton)
    db.commit()

    res = report_service.submit_carton_report(
        db, tenant_id=tenant.id, worker_id=worker.id, carton_code="CTN-EH-BOX-0001",
    )
    assert res["ok"] is True
    assert res["qualified_qty"] == 12
    assert res["work_log_id"]

    log = db.get(WorkLog, res["work_log_id"])
    assert log is not None
    assert log.worker_id == worker.id
    assert log.header_id == header.id
    assert log.qualified_qty == 12
    assert log.process_id == box.id

    carton = db.get(PackingCarton, carton.id)
    assert carton.reported_work_log_id == log.id
    op = db.get(OrderProcess, op.id)
    assert op.completed_qty == 12

    # 重复扫同一箱 → 拦截
    from app.services.report_service import ReportError

    with pytest.raises(ReportError) as ei:
        report_service.submit_carton_report(
            db, tenant_id=tenant.id, worker_id=worker.id, carton_code="CTN-EH-BOX-0001",
        )
    assert ei.value.code == "carton_reported"


def test_assortment_pack_from_sales_order_line(db):
    """订单配码装箱：每箱=配码，箱数=订单箱数；箱唛带配码文案。"""
    from datetime import date as d
    from decimal import Decimal as D

    from app.models import (
        SalesOrder,
        SalesOrderLine,
        SalesOrderLineItem,
        SalesOrderLineStatus,
        SalesOrderStatus,
    )

    ctx = _seed(db)
    tenant = ctx["tenant"]
    order = ctx["order"]
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-PK-001",
        customer_name="箱唛客户",
        ordered_at=d.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    # 配码 37×2 / 38×4，箱数 5 → 绝对 10 / 20
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=order.own_product_id,
        color_id=ctx["c1"].id,
        carton_qty=5,
        total_qty=30,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
        unit_price=D("68"),
        brand_name="品牌红标",
        customer_sku="CUS-RED-01",
        fabric="网布鞋面",
        lining="透气内里",
    )
    db.add(line)
    db.flush()
    db.add_all(
        [
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=line.id,
                color_id=ctx["c1"].id,
                size_id=ctx["s37"].id,
                qty=10,
            ),
            SalesOrderLineItem(
                tenant_id=tenant.id,
                sales_order_line_id=line.id,
                color_id=ctx["c1"].id,
                size_id=ctx["s38"].id,
                qty=20,
            ),
        ]
    )
    order.sales_order_line_id = line.id
    db.get(OwnProduct, order.own_product_id).image_url = "/uploads/box-product.png"
    # 与销售配码一致的绝对色码（便于旧单码路径校验；assortment 走销售行）
    for it in list(
        db.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).all()
    ):
        db.delete(it)
    db.flush()
    db.add_all(
        [
            OrderItem(
                tenant_id=tenant.id,
                order_id=order.id,
                color_id=ctx["c1"].id,
                size_id=ctx["s37"].id,
                qty=10,
            ),
            OrderItem(
                tenant_id=tenant.id,
                order_id=order.id,
                color_id=ctx["c1"].id,
                size_id=ctx["s38"].id,
                qty=20,
            ),
        ]
    )
    order.total_qty = 30
    db.commit()

    plan = packing_service.create_packing_plan(
        db,
        tenant.id,
        order.id,
        mode="assortment",
        pairs_per_carton=12,  # 忽略，由配码合计决定
    )
    assert plan["mode"] == "assortment"
    assert plan["carton_count"] == 5
    assert plan["pairs_per_carton"] == 6
    assert plan["total_qty"] == 30
    assert plan["assortment"] == "37×2 / 38×4"
    for c in plan["cartons"]:
        assert c["total_qty"] == 6
        assert c["assortment"] == "37×2 / 38×4"
        by_size = {ln["size_value"]: ln["qty"] for ln in c["lines"]}
        assert by_size == {"37": 2, "38": 4}

    # 箱码冻结销售归属；入库后成品仓以箱为实物账，并按客户品牌汇总。
    from app.models import PackingCarton
    from app.services.fg_service import list_fg_cartons, warehouse_carton

    first = db.get(PackingCarton, plan["cartons"][0]["id"])
    assert first.sales_order_id == so.id
    assert first.sales_order_line_id == line.id
    assert first.customer_name == "箱唛客户"
    assert first.brand_name == "品牌红标"
    assert first.customer_sku == "CUS-RED-01"
    line.brand_name = "订单后改品牌"
    so.customer_name = "订单后改客户"
    db.commit()
    frozen = packing_service.get_packing_carton(db, tenant.id, first.id)
    assert frozen["customer_name"] == "箱唛客户"
    assert frozen["brand_name"] == "品牌红标"
    first.reported_work_log_id = 999
    db.commit()
    warehouse_carton(db, tenant_id=tenant.id, carton_id=first.id)

    warehouse = list_fg_cartons(db, tenant_id=tenant.id)
    assert warehouse["carton_count"] == 1
    assert warehouse["qty"] == 6
    assert warehouse["items"][0]["code"] == first.code
    assert warehouse["items"][0]["brand_name"] == "品牌红标"
    assert warehouse["items"][0]["customer_sku"] == "CUS-RED-01"
    assert warehouse["items"][0]["product_image_url"] == "/uploads/box-product.png"
    assert warehouse["items"][0]["color_name"] == "红"
    assert warehouse["items"][0]["fabric"] == "网布鞋面"
    assert warehouse["items"][0]["lining"] == "透气内里"
    assert warehouse["items"][0]["assortment"] == "37×2 / 38×4"
    assert warehouse["summaries"] == [
        {
            "customer_id": None,
            "customer_name": "箱唛客户",
            "brand_id": None,
            "brand_name": "品牌红标",
            "customer_sku": "CUS-RED-01",
            "own_product_id": order.own_product_id,
            "product_code": "箱唛款",
            "carton_count": 1,
            "qty": 6,
        }
    ]


def test_header_assortment_uses_only_its_allocated_full_cartons(db):
    """订单拆到多张生产单时，本生产单只生成自身分配到的完整配码箱。"""
    from app.models import (
        ExecutionAllocation,
        ExecutionHeader,
        SalesOrder,
        SalesOrderLine,
        SalesOrderLineItem,
        SalesOrderLineStatus,
        SalesOrderStatus,
        SpecExecutionOrder,
    )

    ctx = _seed(db)
    so = SalesOrder(
        tenant_id=ctx["tenant"].id,
        order_no="SO-SPLIT-PACK",
        customer_name="拆单客户",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=ctx["tenant"].id,
        sales_order_id=so.id,
        own_product_id=ctx["order"].own_product_id,
        color_id=ctx["c1"].id,
        carton_qty=5,
        total_qty=30,
        notes="外箱贴客户条码",
        delivery_date=date.today() + timedelta(days=9),
        status=SalesOrderLineStatus.scheduled,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item37 = SalesOrderLineItem(
        tenant_id=ctx["tenant"].id,
        sales_order_line_id=line.id,
        color_id=ctx["c1"].id,
        size_id=ctx["s37"].id,
        qty=10,
        allocated_qty=4,
    )
    item38 = SalesOrderLineItem(
        tenant_id=ctx["tenant"].id,
        sales_order_line_id=line.id,
        color_id=ctx["c1"].id,
        size_id=ctx["s38"].id,
        qty=20,
        allocated_qty=8,
    )
    db.add_all([item37, item38])
    db.flush()
    header = ExecutionHeader(
        tenant_id=ctx["tenant"].id,
        header_no="EH-SPLIT-PACK",
        own_product_id=ctx["order"].own_product_id,
        color_id=ctx["c1"].id,
        total_qty=12,
    )
    db.add(header)
    db.flush()
    exe37 = SpecExecutionOrder(
        tenant_id=ctx["tenant"].id,
        execution_no="EH-SPLIT-PACK-37",
        header_id=header.id,
        own_product_id=ctx["order"].own_product_id,
        color_id=ctx["c1"].id,
        size_id=ctx["s37"].id,
        total_qty=4,
    )
    exe38 = SpecExecutionOrder(
        tenant_id=ctx["tenant"].id,
        execution_no="EH-SPLIT-PACK-38",
        header_id=header.id,
        own_product_id=ctx["order"].own_product_id,
        color_id=ctx["c1"].id,
        size_id=ctx["s38"].id,
        total_qty=8,
    )
    db.add_all([exe37, exe38])
    db.flush()
    db.add_all([
        ExecutionAllocation(
            tenant_id=ctx["tenant"].id,
            execution_id=exe37.id,
            sales_order_id=so.id,
            sales_order_line_id=line.id,
            sales_order_line_item_id=item37.id,
            qty=4,
            ratio=Decimal("1"),
        ),
        ExecutionAllocation(
            tenant_id=ctx["tenant"].id,
            execution_id=exe38.id,
            sales_order_id=so.id,
            sales_order_line_id=line.id,
            sales_order_line_item_id=item38.id,
            qty=8,
            ratio=Decimal("1"),
        ),
    ])
    db.commit()

    sources = packing_service.list_header_packing_sources(db, ctx["tenant"].id, header.id)
    assert sources[0]["carton_qty"] == 2
    assert sources[0]["allocated_qty"] == 12
    assert sources[0]["packable"] is True
    assert sources[0]["product_code"] == "箱唛款"
    assert sources[0]["customer_name"] == "拆单客户"
    assert sources[0]["line_notes"] == "外箱贴客户条码"
    assert sources[0]["delivery_date"] == (date.today() + timedelta(days=9)).isoformat()
    assert [(cell["size_value"], cell["qty"]) for cell in sources[0]["assortment_lines"]] == [
        ("37", 2),
        ("38", 4),
    ]

    with pytest.raises(PackingError) as wrong_mode:
        packing_service.create_packing_plan(
            db,
            ctx["tenant"].id,
            header_id=header.id,
            mode="mixed",
            pairs_per_carton=12,
        )
    assert wrong_mode.value.code == "assortment_required"

    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        header_id=header.id,
        mode="assortment",
        pairs_per_carton=1,
        sales_order_line_id=line.id,
    )
    assert plan["carton_count"] == 2
    assert plan["total_qty"] == 12
    assert all(c["sales_order_no"] == "SO-SPLIT-PACK" for c in plan["cartons"])
    assert all(c["line_notes"] == "外箱贴客户条码" for c in plan["cartons"])

    from app.models import PackingCarton

    db.get(PackingCarton, plan["cartons"][0]["id"]).reported_work_log_id = 999
    db.commit()
    with pytest.raises(PackingError) as in_use:
        packing_service.create_packing_plan(
            db,
            ctx["tenant"].id,
            header_id=header.id,
            mode="assortment",
            pairs_per_carton=1,
            sales_order_line_id=line.id,
        )
    assert in_use.value.code == "packing_plan_in_use"


def test_warehouse_carton_by_box(db):
    """按箱入库：必须先报工；FG++、标记 warehoused_at，禁止重复入库。"""
    from app.models import FgStock, PackingCarton
    from app.services.fg_service import FgError, warehouse_carton

    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    carton = plan["cartons"][0]

    with pytest.raises(FgError) as ei:
        warehouse_carton(
            db,
            tenant_id=ctx["tenant"].id,
            carton_id=carton["id"],
        )
    assert ei.value.code == "carton_not_reported"

    carton_row = db.get(PackingCarton, carton["id"])
    carton_row.reported_work_log_id = 999  # 本测试只验证箱状态闸门；完整报工链路见上方用例
    db.commit()

    out = warehouse_carton(
        db,
        tenant_id=ctx["tenant"].id,
        carton_id=carton["id"],
    )
    assert out["code"] == carton["code"]
    assert out["warehoused_at"]
    assert sum(ln["qty"] for ln in out["lines"]) == carton["total_qty"]

    stocks = list(
        db.scalars(
            select(FgStock).where(FgStock.tenant_id == ctx["tenant"].id)
        ).all()
    )
    assert sum(int(s.qty or 0) for s in stocks) == carton["total_qty"]

    refreshed = packing_service.get_packing_carton(db, ctx["tenant"].id, carton["id"])
    assert refreshed["warehoused_at"]

    with pytest.raises(FgError) as ei:
        warehouse_carton(db, tenant_id=ctx["tenant"].id, carton_id=carton["id"])
    assert ei.value.code == "already_warehoused"


def test_scan_carton_ship_deducts_fg_and_creates_confirmed_shipment(db):
    """扫箱出库：必须先入库；扣 FG、落出货单/应收，并禁止重复扫。"""
    from app.models import FgLedger, FgStock, PackingCarton, Receivable, Shipment, ShipmentStatus
    from app.services.fg_service import FgError, ship_warehoused_carton, warehouse_carton

    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    carton = plan["cartons"][0]

    with pytest.raises(FgError) as before_in:
        ship_warehoused_carton(
            db, tenant_id=ctx["tenant"].id, carton_id=carton["id"]
        )
    assert before_in.value.code == "carton_not_warehoused"

    row = db.get(PackingCarton, carton["id"])
    row.reported_work_log_id = 999
    db.commit()
    warehouse_carton(db, tenant_id=ctx["tenant"].id, carton_id=row.id)

    result = ship_warehoused_carton(
        db, tenant_id=ctx["tenant"].id, carton_id=row.id, note="扫码发货"
    )
    assert result["status"] == "shipped"
    assert result["shipment_id"]
    shipment = db.get(Shipment, result["shipment_id"])
    assert shipment.status == ShipmentStatus.shipped
    assert int(shipment.total_qty) == carton["total_qty"]
    assert db.scalar(select(Receivable).where(Receivable.shipment_id == shipment.id)) is not None
    assert sum(
        int(stock.qty or 0)
        for stock in db.scalars(select(FgStock).where(FgStock.tenant_id == ctx["tenant"].id))
    ) == 0
    ledgers = list(
        db.scalars(
            select(FgLedger).where(
                FgLedger.tenant_id == ctx["tenant"].id,
                FgLedger.ref_type == "carton_ship",
                FgLedger.ref_id == row.id,
            )
        ).all()
    )
    assert sum(int(item.qty) for item in ledgers) == carton["total_qty"]

    with pytest.raises(FgError) as duplicate:
        ship_warehoused_carton(db, tenant_id=ctx["tenant"].id, carton_id=row.id)
    assert duplicate.value.code == "already_shipped"


def test_batch_ship_warehoused_cartons(db):
    """批量出库先统一预检，再逐箱扣库存并生成各自出货记录。"""
    from app.models import FgStock, PackingCarton
    from app.services.fg_service import list_fg_cartons, ship_warehoused_cartons, warehouse_carton

    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    carton_ids = [row["id"] for row in plan["cartons"][:2]]
    for index, carton_id in enumerate(carton_ids, start=1):
        carton = db.get(PackingCarton, carton_id)
        carton.reported_work_log_id = 900 + index
        db.commit()
        warehouse_carton(db, tenant_id=ctx["tenant"].id, carton_id=carton_id)

    result = ship_warehoused_cartons(
        db,
        tenant_id=ctx["tenant"].id,
        carton_ids=carton_ids,
        note="批量扫码出库",
    )
    assert result["requested_count"] == 2
    assert result["success_count"] == 2
    assert result["failed_count"] == 0
    assert result["total_qty"] == 24
    assert all(db.get(PackingCarton, carton_id).shipment_id for carton_id in carton_ids)
    shipped = list_fg_cartons(db, tenant_id=ctx["tenant"].id, status="shipped")
    assert shipped["carton_count"] == 2
    assert shipped["qty"] == 24
    assert {row["id"] for row in shipped["items"]} == set(carton_ids)
    assert all(row["shipment_no"] for row in shipped["items"])
    assert all(row["shipped_at"] for row in shipped["items"])
    assert sum(
        int(stock.qty or 0)
        for stock in db.scalars(select(FgStock).where(FgStock.tenant_id == ctx["tenant"].id))
    ) == 0
