"""D25/P7 开裁分批：默认自动批次号 / 分批拆批 / 补裁复用 / 报工带批次。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    ProductionBatch,
    ProductionBatchStatus,
    Size,
    Tenant,
    TraceUnit,
    WorkLog,
    Employee,
)
from app.services import report_service, trace_service


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
    tenant = Tenant(name="分批厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    worker = Employee(tenant_id=tenant.id, name="张三", mobile="13900000011", is_active=True)
    product = OwnProduct(
        tenant_id=tenant.id, product_code="BATCH-01", quote_price=Decimal("80"), trace_enabled=True
    )
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
        type=ProcessType.personal,
    )
    db.add_all([color, worker, product, zc])
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=zc.id,
            process_name="针车",
            unit_price=Decimal("1.5"),
            sort_order=1,
        )
    )
    sizes = []
    for i, sv in enumerate(("40", "41")):
        s = Size(tenant_id=tenant.id, size_value=sv, sort_order=i)
        db.add(s)
        sizes.append(s)
    db.flush()

    order = Order(
        tenant_id=tenant.id,
        order_no="BATCH-ORD-1",
        customer_name="客A",
        own_product_id=product.id,
        total_qty=170,
        delivery_date=date.today() + timedelta(days=14),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    for s, qty in zip(sizes, (120, 50)):
        db.add(
            OrderItem(
                tenant_id=tenant.id,
                order_id=order.id,
                color_id=color.id,
                size_id=s.id,
                qty=qty,
            )
        )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=zc.id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=170,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {"tenant": tenant, "order": order, "worker": worker, "product": product}


def _batch_rows(db, tenant_id, order_id):
    return list(
        db.scalars(
            select(ProductionBatch)
            .where(ProductionBatch.tenant_id == tenant_id, ProductionBatch.order_id == order_id)
            .order_by(ProductionBatch.id)
        ).all()
    )


def test_default_batch_created_on_cut(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    assert data["to_create"] == 5
    batches = _batch_rows(db, ctx["tenant"].id, ctx["order"].id)
    # 不分批 → 一个默认批次号，全部筐挂它
    assert len(batches) == 1
    assert batches[0].batch_no == "BATCH-ORD-1-01"
    assert batches[0].qty == 170
    assert batches[0].status == ProductionBatchStatus.open
    assert data["batches"] == [
        {"batch_no": "BATCH-ORD-1-01", "qty": 170, "unit_count": 5}
    ]
    basket_ids = {c["batch_id"] for c in data["created"]}
    assert basket_ids == {batches[0].id}
    assert all(
        u.batch_id == batches[0].id
        for u in db.scalars(
            select(TraceUnit).where(TraceUnit.tenant_id == ctx["tenant"].id)
        ).all()
    )


def test_dry_run_previews_batches_without_write(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=True,
        batch_qtys=[80, 130],
    )
    # 5 筐：40/40/40/40/10 → 贪心：批1=80(2筐)、批2=90(3筐)，最后一批吃余数
    assert data["batches"] == [
        {"batch_no": "BATCH-ORD-1-01", "qty": 80, "unit_count": 2},
        {"batch_no": "BATCH-ORD-1-02", "qty": 90, "unit_count": 3},
    ]
    # 预览不落库
    assert db.scalar(select(func.count()).select_from(ProductionBatch)) == 0
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 0


def test_split_into_batches(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
        batch_qtys=[80, 130],
    )
    batches = _batch_rows(db, ctx["tenant"].id, ctx["order"].id)
    assert [b.batch_no for b in batches] == ["BATCH-ORD-1-01", "BATCH-ORD-1-02"]
    assert [b.qty for b in batches] == [80, 90]
    units = db.scalars(
        select(TraceUnit)
        .where(TraceUnit.tenant_id == ctx["tenant"].id)
        .order_by(TraceUnit.id)
    ).all()
    # 前 2 筐（40+40=80）挂批1，后 3 筐（40+40+10=90）挂批2
    assert [u.batch_id for u in units] == [batches[0].id] * 2 + [batches[1].id] * 3
    # 响应 created 带 batch_id
    assert [c["batch_id"] for c in data["created"]] == [batches[0].id] * 2 + [batches[1].id] * 3


def test_second_cut_reuses_active_batch(db):
    ctx = _seed(db)
    trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    first = _batch_rows(db, ctx["tenant"].id, ctx["order"].id)
    assert len(first) == 1

    # 补裁（新增筐）不分批 → 复用活动批次，不重复建批
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
        only_missing=False,
    )
    assert data["to_create"] == 5
    batches = _batch_rows(db, ctx["tenant"].id, ctx["order"].id)
    assert len(batches) == 1 and batches[0].id == first[0].id
    assert {c["batch_id"] for c in data["created"]} == {first[0].id}


def test_report_carries_batch_and_advances_status(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
        batch_qtys=[80, 130],
    )
    batches = _batch_rows(db, ctx["tenant"].id, ctx["order"].id)
    basket = data["created"][0]  # 批1的筐

    res = report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=40,
        color_name="黑",
        size_value="40",
        source="qrcode",
        report_type="normal",
        trace_unit_id=basket["id"],
        confirm_over_plan=True,
    )
    assert res["work_log_id"]
    log = db.get(WorkLog, res["work_log_id"])
    assert log.batch_id == batches[0].id
    # 批次状态机：open → in_production（首笔报工）
    db.refresh(batches[0])
    assert batches[0].status == ProductionBatchStatus.in_production
