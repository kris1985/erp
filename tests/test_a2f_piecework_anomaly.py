"""A2f：计件/成本异常核对——高亮异常报工行，不改工资引擎口径。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
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
    Size,
    Tenant,
    Employee,
)
from app.services import piecework_anomaly, report_service, salary_service


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


def _seed(db, *, plan_qty: int = 100):
    tenant = Tenant(name="核对厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    worker = Employee(tenant_id=tenant.id, name="李四", mobile="13900000002", is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="AF-01", quote_price=Decimal("80"))
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        sort_order=1,
        type=ProcessType.personal,
    )
    db.add_all([color, size, worker, product, zc])
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=zc.id,
            process_name="针车",
            unit_price=Decimal("2.0"),
            sort_order=1,
        )
    )
    order = Order(
        tenant_id=tenant.id,
        order_no="AF-001",
        customer_name="测试客户",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=plan_qty,
        delivery_date=date.today() + timedelta(days=10),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            color_id=color.id,
            size_id=size.id,
            qty=plan_qty,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=zc.id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=plan_qty,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {
        "tenant": tenant,
        "color": color,
        "size": size,
        "worker": worker,
        "product": product,
        "zc": zc,
        "order": order,
    }


def test_clean_reports_have_no_anomaly(db):
    ctx = _seed(db, plan_qty=100)
    report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=10,
    )
    result = piecework_anomaly.list_anomalies(db, ctx["tenant"].id)
    assert result["total"] == 0
    assert result["items"] == []


def test_qty_over_plan_and_process_over_plan_flagged(db):
    ctx = _seed(db, plan_qty=10)
    result_report = report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=50,
        confirm_over_plan=True,
    )
    result = piecework_anomaly.list_anomalies(db, ctx["tenant"].id)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["work_log_id"] == result_report["work_log_id"]
    codes = item["reason_codes"]
    assert "qty_over_plan" in codes
    assert "process_over_plan" in codes


def test_price_outlier_flagged(db):
    ctx = _seed(db, plan_qty=100)
    # 工序参考单价 2.0，锁价 12.0，明显偏离（6x）
    report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=5,
        unit_price_override=Decimal("12.0"),
    )
    result = piecework_anomaly.list_anomalies(db, ctx["tenant"].id)
    assert result["total"] == 1
    assert "price_outlier" in result["items"][0]["reason_codes"]


def test_void_in_locked_month_flagged(db):
    ctx = _seed(db, plan_qty=100)
    reported = report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=5,
    )
    report_service.void_work_log(
        db,
        tenant_id=ctx["tenant"].id,
        work_log_id=reported["work_log_id"],
        review_note="测试作废",
    )
    ym = salary_service.year_month_of(None)
    salary_service.set_month_lock(db, ctx["tenant"].id, ym, locked=True)

    result = piecework_anomaly.list_anomalies(db, ctx["tenant"].id)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["status"] == "void"
    assert "void_in_locked_month" in item["reason_codes"]


def test_date_range_filters_out_unrelated_window(db):
    ctx = _seed(db, plan_qty=10)
    report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=50,
        confirm_over_plan=True,
    )
    yesterday = date.today() - timedelta(days=1)
    result = piecework_anomaly.list_anomalies(
        db, ctx["tenant"].id, date_from=yesterday - timedelta(days=5), date_to=yesterday
    )
    assert result["total"] == 0
    assert result["message"] == "无异常报工，月底核对干净"
