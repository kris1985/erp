"""B2e：补码/改码/尾数向导 — 差异预览、拦截、材料重算、发货影响、变更记录回退。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Order,
    OrderChangeLog,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)
from app.schemas.api import SizeAdjustItemIn
from app.services import order_service
from app.services.order_service import OrderError


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    tenant = Tenant(name="补改码厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    s38 = Size(tenant_id=tenant.id, size_value="38", sort_order=0)
    s39 = Size(tenant_id=tenant.id, size_value="39", sort_order=1)
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    proc = ProcessDefinition(
        tenant_id=tenant.id, name="裁断", code="CT", default_price=Decimal("0.3"), sort_order=1
    )
    db.add_all([color, s38, s39, partner, proc])
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="B2E-1", is_active=True)
    db.add(product)
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-B2E",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("10"),
        is_active=True,
    )
    db.add(sp)
    db.flush()
    db.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("10"),
            line_total=Decimal("10"),
            sort_order=0,
        )
    )
    db.commit()

    order = Order(
        tenant_id=tenant.id,
        order_no="B2E-O1",
        customer_name="客户甲",
        own_product_id=product.id,
        total_qty=10,
        delivery_date=date(2026, 8, 20),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            color_id=color.id,
            size_id=s38.id,
            qty=10,
            completed_qty=0,
            shipped_qty=0,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=proc.id,
            process_name="裁断",
            plan_qty=10,
            completed_qty=0,
            defect_qty=0,
            status=OrderProcessStatus.pending,
            process_type=ProcessType.personal,
        )
    )
    db.flush()
    from app.services import material_service

    material_service.ensure_material_snapshot(db, tenant.id, order)
    db.commit()

    yield {
        "db": db,
        "tenant_id": tenant.id,
        "order_id": order.id,
        "color_id": color.id,
        "s38_id": s38.id,
        "s39_id": s39.id,
        "sp_id": sp.id,
    }
    db.close()


def test_delta_add_new_size_replenish(ctx):
    """补码：新增一个尺码行。"""
    db = ctx["db"]
    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s39_id"], qty=5)],
        mode="delta",
        note="客户临时加5双39码",
    )
    assert result["dry_run"] is False
    assert result["total_qty_before"] == 10
    assert result["total_qty_after"] == 15
    row = result["items"][0]
    assert row["is_new"] is True
    assert row["before_qty"] == 0
    assert row["after_qty"] == 5
    assert row["delta_qty"] == 5

    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    assert order.total_qty == 15
    assert len(order.items) == 2
    assert order.processes[0].plan_qty == 15


def test_replace_existing_qty_change_code(ctx):
    """改码：把某色码计划数替换为目标值。"""
    db = ctx["db"]
    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=7)],
        mode="replace",
    )
    assert result["total_qty_after"] == 7
    row = result["items"][0]
    assert row["before_qty"] == 10
    assert row["after_qty"] == 7
    assert row["delta_qty"] == -3

    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    assert order.total_qty == 7
    assert order.items[0].qty == 7


def test_dry_run_previews_without_writing(ctx):
    db = ctx["db"]
    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=-4)],
        mode="delta",
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["total_qty_before"] == 10
    assert result["total_qty_after"] == 6
    assert result["items"][0]["after_qty"] == 6

    # 预览不落库
    fresh = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    assert fresh.total_qty == 10
    assert fresh.items[0].qty == 10


def test_below_completed_blocks_commit_but_not_preview(ctx):
    db = ctx["db"]
    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    order.items[0].completed_qty = 8
    db.commit()

    preview = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=5)],
        mode="replace",
        dry_run=True,
    )
    assert preview["has_blocking"] is True
    assert preview["items"][0]["below_completed"] is True

    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(
            db,
            ctx["tenant_id"],
            ctx["order_id"],
            items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=5)],
            mode="replace",
        )
    assert ei.value.code == "qty_below_completed"


def test_negative_result_qty_rejected(ctx):
    db = ctx["db"]
    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(
            db,
            ctx["tenant_id"],
            ctx["order_id"],
            items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=-20)],
            mode="delta",
        )
    assert ei.value.code == "negative_qty"


def test_material_recalc_releases_excess_to_pool(ctx):
    """尾数向导减码后应触发 sync_requirements_after_qty_change 释放多占的材料。"""
    db = ctx["db"]
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == ctx["order_id"])
    )
    req.arrived_qty = Decimal("10")
    db.commit()

    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=4)],
        mode="replace",
    )
    assert result["requirement_count"] >= 1
    assert result["released"], "应释放超额占用回池"

    db.refresh(req)
    assert req.required_qty == Decimal("4.0000")
    assert req.arrived_qty == Decimal("4")
    stock = db.scalar(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == ctx["tenant_id"],
            SharedMaterialStock.supplier_product_id == ctx["sp_id"],
        )
    )
    assert stock.qty == Decimal("6")


def test_delivery_impact_flag_when_already_shipped(ctx):
    db = ctx["db"]
    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    order.items[0].shipped_qty = 6
    db.commit()

    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=-4)],
        mode="delta",
        dry_run=True,
    )
    row = result["items"][0]
    assert row["after_qty"] == 6
    assert row["shipped_qty"] == 6
    assert row["delivery_impact"] is True
    assert result["has_delivery_impact"] is True


def test_change_log_created_via_b2c_when_present(ctx):
    """B2c OrderChangeLog 已落地：写入正式变更版本，附带向导备注；订单 notes 不受影响。"""
    db = ctx["db"]
    result = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=2)],
        mode="delta",
        note="尾数补齐",
    )
    assert result["change_logged"] is True
    assert result["change_log_id"] is not None
    assert "尾数补齐" in result["summary"]

    log = db.get(OrderChangeLog, result["change_log_id"])
    assert log is not None
    assert log.order_id == ctx["order_id"]
    assert log.version_no == 1
    assert "qty" in log.change_type
    assert "尾数补齐" in log.summary

    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    assert not order.notes

    # 再调一次，版本号递增
    result2 = order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=1)],
        mode="delta",
    )
    log2 = db.get(OrderChangeLog, result2["change_log_id"])
    assert log2.version_no == 2


def test_dry_run_does_not_write_change_log(ctx):
    db = ctx["db"]
    order_service.adjust_order_sizes(
        db,
        ctx["tenant_id"],
        ctx["order_id"],
        items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=2)],
        mode="delta",
        dry_run=True,
    )
    count = db.scalar(
        select(OrderChangeLog).where(OrderChangeLog.order_id == ctx["order_id"])
    )
    assert count is None


def test_cancelled_order_rejected(ctx):
    db = ctx["db"]
    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    order.status = OrderStatus.cancelled
    db.commit()
    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(
            db,
            ctx["tenant_id"],
            ctx["order_id"],
            items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=1)],
        )
    assert ei.value.code == "cancelled"


def test_completed_order_rejected(ctx):
    db = ctx["db"]
    order = order_service.get_order(db, ctx["tenant_id"], ctx["order_id"])
    order.status = OrderStatus.completed
    db.commit()
    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(
            db,
            ctx["tenant_id"],
            ctx["order_id"],
            items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=1)],
        )
    assert ei.value.code == "completed"


def test_empty_items_rejected(ctx):
    db = ctx["db"]
    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(db, ctx["tenant_id"], ctx["order_id"], items=[])
    assert ei.value.code == "empty_items"


def test_invalid_mode_rejected(ctx):
    db = ctx["db"]
    with pytest.raises(OrderError) as ei:
        order_service.adjust_order_sizes(
            db,
            ctx["tenant_id"],
            ctx["order_id"],
            items=[SizeAdjustItemIn(color_id=ctx["color_id"], size_id=ctx["s38_id"], qty=1)],
            mode="bogus",
        )
    assert ei.value.code == "invalid_mode"
