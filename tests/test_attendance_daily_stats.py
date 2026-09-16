"""报工统计：部门→工序→员工→型号层级 + 效率。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AttendanceDay,
    Color,
    Department,
    Employee,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    ReportType,
    SalaryModel,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
)
from app.services import attendance_service


LOCAL_OFFSET = timedelta(hours=8)


@pytest.fixture()
def stats_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="报工统计厂")
    session.add(tenant)
    session.flush()
    dept = Department(tenant_id=tenant.id, name="成型部")
    session.add(dept)
    session.flush()
    workers = [
        Employee(
            tenant_id=tenant.id,
            name=name,
            department_id=dept.id,
            salary_model=SalaryModel.pure_piece,
            is_active=True,
        )
        for name in ("张三", "李四", "王二")
    ]
    p_mid = ProcessDefinition(
        tenant_id=tenant.id,
        name="拉中帮",
        code="LZB",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    p_back = ProcessDefinition(
        tenant_id=tenant.id,
        name="拉后帮",
        code="LHB",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    products = [
        OwnProduct(tenant_id=tenant.id, product_code=code, quote_price=Decimal("10"))
        for code in ("23423", "232434", "X-99")
    ]
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    session.add_all([*workers, p_mid, p_back, *products, color])
    session.flush()
    for product in products:
        for proc in (p_mid, p_back):
            session.add(
                OwnProductLabor(
                    tenant_id=tenant.id,
                    own_product_id=product.id,
                    process_id=proc.id,
                    process_name=proc.name,
                    unit_price=Decimal("2.0"),
                )
            )
    session.commit()
    yield session, tenant, dept, workers, p_mid, p_back, products, color
    session.close()


def _utc_on_local_day(work_date: date, hour: int = 10) -> datetime:
    local = datetime(work_date.year, work_date.month, work_date.day, hour, 0, 0)
    return local - LOCAL_OFFSET


def _add_attendance(db, tenant_id, employee_id, work_date, *, minutes=480):
    db.add(
        AttendanceDay(
            tenant_id=tenant_id,
            employee_id=employee_id,
            work_date=work_date,
            clock_in_at=_utc_on_local_day(work_date, 8),
            clock_out_at=_utc_on_local_day(work_date, 8) + timedelta(minutes=minutes),
            work_minutes=minutes,
            status="normal",
            source_provider="local",
        )
    )
    db.flush()


def _add_log(
    db,
    *,
    tenant_id,
    worker_id,
    process_id,
    product_id,
    color_id,
    work_date,
    qty,
    unit_price=Decimal("2.0"),
    loss_amount=Decimal("0"),
    loss_borne_percent=0,
    defect_qty=Decimal("0"),
):
    from app.models import OrderProcess

    op = OrderProcess(
        tenant_id=tenant_id,
        order_id=0,
        process_id=process_id,
        process_name="工序",
        plan_qty=100,
    )
    db.add(op)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant_id,
            worker_id=worker_id,
            order_id=0,
            order_process_id=op.id,
            own_product_id=product_id,
            process_id=process_id,
            color_id=color_id,
            report_type=ReportType.normal,
            qualified_qty=Decimal(str(qty)),
            defect_qty=defect_qty,
            unit_price=unit_price,
            loss_amount=loss_amount,
            loss_borne_percent=loss_borne_percent,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=_utc_on_local_day(work_date, 11),
        )
    )
    db.flush()


def test_report_stats_hierarchy_and_efficiencies(stats_db):
    db, tenant, dept, workers, p_mid, p_back, products, color = stats_db
    zhang, li, wang = workers
    day = date(2026, 9, 15)

    for w in workers:
        _add_attendance(db, tenant.id, w.id, day, minutes=480)

    # 张三：拉中帮 3 个型号
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=zhang.id,
        process_id=p_mid.id,
        product_id=products[0].id,
        color_id=color.id,
        work_date=day,
        qty=80,
    )
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=zhang.id,
        process_id=p_mid.id,
        product_id=products[1].id,
        color_id=color.id,
        work_date=day,
        qty=40,
    )
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=zhang.id,
        process_id=p_mid.id,
        product_id=products[2].id,
        color_id=None,
        work_date=day,
        qty=40,
    )
    # 李四、王二：拉中帮各一款
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=li.id,
        process_id=p_mid.id,
        product_id=products[0].id,
        color_id=color.id,
        work_date=day,
        qty=100,
    )
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=wang.id,
        process_id=p_mid.id,
        product_id=products[0].id,
        color_id=color.id,
        work_date=day,
        qty=60,
    )
    # 拉后帮
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=zhang.id,
        process_id=p_back.id,
        product_id=products[0].id,
        color_id=color.id,
        work_date=day,
        qty=50,
        loss_amount=Decimal("10"),
        loss_borne_percent=50,
        defect_qty=Decimal("1"),
    )
    db.commit()

    result = attendance_service.list_daily_stats(db, tenant.id, work_date=day)
    assert result["total"] == 6

    mid_rows = [r for r in result["items"] if r["process_name"] == "拉中帮"]
    assert len(mid_rows) == 5
    assert mid_rows[0]["_dept_span"] == 6  # 全表同部门，但分页后整页仍同部门
    # 拉中帮 5 行合并工序列
    assert mid_rows[0]["_process_span"] == 5
    assert mid_rows[1]["_process_span"] == 0

    zhang_mid = [r for r in mid_rows if r["employee_id"] == zhang.id]
    assert len(zhang_mid) == 3
    assert zhang_mid[0]["_emp_span"] == 3
    assert zhang_mid[0]["personal_efficiency"] == 20.0  # (80+40+40)/8h
    by_code = {r["product_code"]: r for r in zhang_mid}
    assert by_code["23423"]["model_efficiency"] == 10.0  # 80/8
    assert by_code["232434"]["model_efficiency"] == 5.0  # 40/8
    # 单款平均：型号 23423 在拉中帮 = (张80+李100+王60)/(8+8+8) = 10
    assert by_code["23423"]["model_avg_efficiency"] == 10.0
    assert by_code["232434"]["model_avg_efficiency"] == 5.0  # 仅张三 40/8
    assert sum(r["qty"] for r in mid_rows) == 320
    # 单人平均效率 = 320 / (8+8+8) = 13.33；工序多人效率 = 13.33 * 3
    assert mid_rows[0]["avg_efficiency"] == 13.333
    assert mid_rows[0]["process_efficiency"] == 39.999
    assert mid_rows[0]["process_worker_count"] == 3

    back = [r for r in result["items"] if r["process_name"] == "拉后帮"][0]
    assert back["loss"] == 5.0
    assert back["wage"] == 95.0  # 2*50 - 5
    assert result["summary"]["qty_total"] == 370.0


def test_report_stats_department_filter(stats_db):
    db, tenant, dept, workers, p_mid, _, products, color = stats_db
    day = date(2026, 9, 16)
    _add_attendance(db, tenant.id, workers[0].id, day, minutes=240)
    _add_log(
        db,
        tenant_id=tenant.id,
        worker_id=workers[0].id,
        process_id=p_mid.id,
        product_id=products[0].id,
        color_id=color.id,
        work_date=day,
        qty=40,
    )
    db.commit()

    ok = attendance_service.list_daily_stats(
        db, tenant.id, work_date=day, department_id=dept.id
    )
    assert ok["total"] == 1
    assert ok["items"][0]["model_efficiency"] == 10.0
    assert ok["summary"]["work_date"] == day.isoformat()

    empty = attendance_service.list_daily_stats(
        db, tenant.id, work_date=day, department_id=999999
    )
    assert empty["total"] == 0
