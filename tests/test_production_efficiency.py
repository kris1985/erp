"""生产效率：单款平均效率矩阵。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AttendanceDay,
    Employee,
    OrderProcess,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    ReportType,
    SalaryModel,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
)
from app.services import production_efficiency_service, segment_service


LOCAL_OFFSET = timedelta(hours=8)


@pytest.fixture()
def eff_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="效率厂")
    session.add(tenant)
    session.flush()
    segment_service.ensure_default_segments(session, tenant.id)
    cut = session.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    forming = session.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "forming"
        )
    )
    p_mark = ProcessDefinition(
        tenant_id=tenant.id,
        name="划线",
        code="HX",
        type=ProcessType.personal,
        segment_id=cut.id,
        sort_order=1,
        default_price=Decimal("1"),
    )
    p_cut = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CD",
        type=ProcessType.personal,
        segment_id=cut.id,
        sort_order=2,
        default_price=Decimal("1"),
    )
    p_mid = ProcessDefinition(
        tenant_id=tenant.id,
        name="拉中帮",
        code="LZB",
        type=ProcessType.personal,
        segment_id=forming.id,
        sort_order=1,
        default_price=Decimal("1"),
    )
    product = OwnProduct(tenant_id=tenant.id, product_code="15515-5", quote_price=Decimal("10"))
    worker = Employee(
        tenant_id=tenant.id,
        name="张三",
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    session.add_all([p_mark, p_cut, p_mid, product, worker])
    session.commit()
    yield session, tenant, worker, product, p_mark, p_cut, p_mid
    session.close()


def _utc(day: date, hour=10) -> datetime:
    return datetime(day.year, day.month, day.day, hour) - LOCAL_OFFSET


def _att(db, tenant_id, employee_id, day, minutes=480):
    db.add(
        AttendanceDay(
            tenant_id=tenant_id,
            employee_id=employee_id,
            work_date=day,
            work_minutes=minutes,
            status="normal",
            source_provider="local",
            clock_in_at=_utc(day, 8),
            clock_out_at=_utc(day, 8) + timedelta(minutes=minutes),
        )
    )


def _log(db, *, tenant_id, worker_id, process_id, product_id, day, qty):
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
            report_type=ReportType.normal,
            qualified_qty=Decimal(str(qty)),
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=_utc(day, 11),
        )
    )


def test_model_avg_matrix_by_date_and_segment(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 480)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_cut.id, product_id=product.id, day=d1, qty=64)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d2, qty=48)
    db.commit()

    result = production_efficiency_service.model_avg_efficiency_matrix(
        db,
        tenant.id,
        date_from=d1,
        date_to=d2,
        product_codes=["15515-5"],
    )
    assert result["unit"] == "双/人/小时"
    assert result["product_codes"] == ["15515-5"]
    seg_names = [c["segment_name"] for c in result["columns"]]
    assert "截断" in seg_names
    assert "成型" in seg_names
    cut_col = next(c for c in result["columns"] if c["segment_code"] == "cut")
    assert [p["process_name"] for p in cut_col["processes"]] == ["划线", "裁断"]

    by_date = {r["work_date"]: r["values"] for r in result["rows"]}
    assert by_date["2026-09-15"][str(p_mark.id)] == 5.0  # 40/8
    assert by_date["2026-09-15"][str(p_cut.id)] == 8.0  # 64/8
    assert by_date["2026-09-16"][str(p_mark.id)] == 6.0  # 48/8
    # 日期倒序：较新的在前
    assert result["rows"][0]["work_date"] == "2026-09-16"
    assert result["rows"][1]["work_date"] == "2026-09-15"
    assert result["averages"][str(p_mark.id)] == 5.5
    assert result["averages"][str(p_cut.id)] == 8.0
    assert result["averages"][str(p_mid.id)] is None


def test_person_avg_matrix_no_product_filter_and_desc(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 240)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d2, qty=20)
    db.commit()

    result = production_efficiency_service.person_avg_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d2
    )
    assert "product_codes" not in result
    assert [r["work_date"] for r in result["rows"]] == ["2026-09-16", "2026-09-15"]
    assert result["rows"][0]["values"][str(p_mark.id)] == 5.0  # 20/4h
    assert result["rows"][1]["values"][str(p_mark.id)] == 5.0  # 40/8h
    assert result["averages"][str(p_mark.id)] == 5.0


def test_efficiency_matrix_skips_days_without_reports(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    d3 = date(2026, 9, 17)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 480)  # 仅出勤无报工
    _att(db, tenant.id, worker.id, d3, 480)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d3, qty=48)
    db.commit()

    result = production_efficiency_service.person_avg_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d3
    )
    assert [r["work_date"] for r in result["rows"]] == ["2026-09-17", "2026-09-15"]


def test_process_team_efficiency_multiplies_by_workers(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    worker2 = Employee(
        tenant_id=tenant.id,
        name="李四",
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    db.add(worker2)
    db.flush()
    d1 = date(2026, 9, 15)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker2.id, d1, 480)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker2.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    db.commit()

    result = production_efficiency_service.process_team_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d1
    )
    assert result["unit"] == "双/小时"
    cell = result["rows"][0]["values"][str(p_mark.id)]
    # 单人平均 = 80/16h = 5；多人 = 5*2 = 10
    assert cell["efficiency"] == 10.0
    assert cell["workers"] == 2
    assert result["averages"][str(p_mark.id)] == 10.0


def test_personal_output_by_segment_worker_and_loss(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    from sqlalchemy import select

    cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    d1 = date(2026, 9, 15)
    _att(db, tenant.id, worker.id, d1, 480)
    _log(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        process_id=p_mark.id,
        product_id=product.id,
        day=d1,
        qty=40,
    )
    # 带损失的报工
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=0,
        process_id=p_cut.id,
        process_name="裁断",
        plan_qty=100,
    )
    db.add(op)
    db.flush()
    db.add(
        WorkLog(
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_id=0,
            order_process_id=op.id,
            own_product_id=product.id,
            process_id=p_cut.id,
            report_type=ReportType.normal,
            qualified_qty=Decimal("20"),
            defect_qty=Decimal("1"),
            loss_amount=Decimal("10"),
            loss_borne_percent=50,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=_utc(d1, 12),
        )
    )
    db.commit()

    result = production_efficiency_service.personal_output_matrix(
        db, tenant.id, date_from=d1, date_to=d1, segment_id=cut.id
    )
    assert result["unit"] == "双/小时"
    assert result["loss_unit"] == "元"
    assert result["segment_id"] == cut.id
    names = [p["process_name"] for p in result["columns"]]
    assert "划线" in names and "裁断" in names
    mark = next(p for p in result["columns"] if p["process_name"] == "划线")
    cut_col = next(p for p in result["columns"] if p["process_name"] == "裁断")
    assert mark["workers"][0]["employee_name"] == "张三"
    row = result["rows"][0]
    assert row["values"][mark["workers"][0]["qty_key"]] == 5.0  # 40/8h
    assert row["values"][cut_col["workers"][0]["qty_key"]] == 2.5  # 20/8h
    assert row["values"][cut_col["workers"][0]["loss_key"]] == 5.0


def test_pooled_average_differs_from_daily_arithmetic_mean(eff_db):
    """工时波动时，期间加权 ≠ 每日效率算术平均。"""
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 120)  # 2h
    _att(db, tenant.id, worker.id, d2, 600)  # 10h
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=100)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d2, qty=100)
    db.commit()

    result = production_efficiency_service.person_avg_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d2
    )
    by_date = {r["work_date"]: r["values"] for r in result["rows"]}
    assert by_date["2026-09-15"][str(p_mark.id)] == 50.0  # 100/2h
    assert by_date["2026-09-16"][str(p_mark.id)] == 10.0  # 100/10h
    arithmetic_mean = (50.0 + 10.0) / 2
    assert arithmetic_mean == 30.0
    assert result["averages"][str(p_mark.id)] == round(200 / 12, 3)  # 16.667


def test_process_team_pooled_average_with_varying_workers(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    worker2 = Employee(
        tenant_id=tenant.id,
        name="李四",
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    db.add(worker2)
    db.flush()
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker2.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 240)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=80)
    _log(db, tenant_id=tenant.id, worker_id=worker2.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=80)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d2, qty=20)
    db.commit()

    result = production_efficiency_service.process_team_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d2
    )
    by_date = {r["work_date"]: r["values"] for r in result["rows"]}
    assert by_date["2026-09-15"][str(p_mark.id)]["efficiency"] == 20.0  # 160/8h
    assert by_date["2026-09-16"][str(p_mark.id)]["efficiency"] == 5.0  # 20/4h
    # 期间加权 = 180 / (8h产线 + 4h产线) = 15；≠ 每日算术平均 (20+5)/2
    assert result["averages"][str(p_mark.id)] == 15.0


def test_personal_output_averages_qty_daily_loss_total(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    from sqlalchemy import select

    cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 480)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d2, qty=60)
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=0,
        process_id=p_cut.id,
        process_name="裁断",
        plan_qty=100,
    )
    db.add(op)
    db.flush()
    for day, loss_amt in ((d1, Decimal("10")), (d2, Decimal("6"))):
        db.add(
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_id=0,
                order_process_id=op.id,
                own_product_id=product.id,
                process_id=p_cut.id,
                report_type=ReportType.normal,
                qualified_qty=Decimal("20"),
                defect_qty=Decimal("1"),
                loss_amount=loss_amt,
                loss_borne_percent=50,
                status=WorkLogStatus.valid,
                source=WorkLogSource.manual,
                created_at=_utc(day, 12),
            )
        )
    db.commit()

    result = production_efficiency_service.personal_output_matrix(
        db, tenant.id, date_from=d1, date_to=d2, segment_id=cut.id
    )
    mark = next(p for p in result["columns"] if p["process_name"] == "划线")
    cut_col = next(p for p in result["columns"] if p["process_name"] == "裁断")
    qty_key = mark["workers"][0]["qty_key"]
    loss_key = cut_col["workers"][0]["loss_key"]
    assert result["averages"][qty_key] == 6.25  # (40+60)/16h 期间加权
    assert result["averages"][loss_key] == 8.0  # 5+3 期间合计


def test_model_avg_matrix_unknown_product_empty(eff_db):
    db, tenant, *_ = eff_db
    result = production_efficiency_service.model_avg_efficiency_matrix(
        db,
        tenant.id,
        date_from=date(2026, 9, 15),
        date_to=date(2026, 9, 15),
        product_codes=["NO-SUCH"],
    )
    assert result["columns"] == []
    assert result["rows"] == []


def test_recent_reported_products_ordered_by_last_report(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    product_b = OwnProduct(tenant_id=tenant.id, product_code="B-款", quote_price=Decimal("10"))
    db.add(product_b)
    db.flush()
    d1 = date(2026, 9, 14)
    d2 = date(2026, 9, 16)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=10)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product_b.id, day=d2, qty=12)
    db.commit()

    result = production_efficiency_service.recent_reported_products(
        db, tenant.id, date_from=d1, date_to=d2
    )
    codes = [i["product_code"] for i in result["items"]]
    assert codes == ["B-款", "15515-5"]


def test_format_hours_minutes():
    assert production_efficiency_service.format_hours_minutes(480) == "8小时0分"
    assert production_efficiency_service.format_hours_minutes(90) == "1小时30分"
    assert production_efficiency_service.format_hours_minutes(45) == "0小时45分"
    assert production_efficiency_service.format_hours_minutes(0) is None
    assert production_efficiency_service.format_hours_minutes(None) is None


def test_format_minutes_seconds_per_pair():
    assert production_efficiency_service.format_minutes_seconds_per_pair(240, 480) == "2分00秒"
    assert production_efficiency_service.format_minutes_seconds_per_pair(200, 480) == "2分24秒"
    assert production_efficiency_service.format_minutes_seconds_per_pair(0, 480) is None
    assert production_efficiency_service.format_minutes_seconds_per_pair(100, 0) is None


def test_department_efficiency_matrix_hours_qty_and_pace(eff_db):
    db, tenant, worker, product, p_mark, p_cut, p_mid = eff_db
    stitch = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )
    packing = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "packing"
        )
    )
    p_stitch = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        segment_id=stitch.id,
        sort_order=1,
        default_price=Decimal("1"),
    )
    p_pack = ProcessDefinition(
        tenant_id=tenant.id,
        name="包装",
        code="BZ",
        type=ProcessType.personal,
        segment_id=packing.id,
        sort_order=1,
        default_price=Decimal("1"),
    )
    db.add_all([p_stitch, p_pack])
    db.flush()

    d1 = date(2026, 9, 15)
    d2 = date(2026, 9, 16)
    _att(db, tenant.id, worker.id, d1, 480)
    _att(db, tenant.id, worker.id, d2, 240)
    # 裁断段：划线40 + 裁断40 = 80双 / 480分钟 → 6分00秒
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mark.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_cut.id, product_id=product.id, day=d1, qty=40)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_stitch.id, product_id=product.id, day=d1, qty=60)
    # 次日成型 20双 / 240分钟 → 12分00秒；裁断再报 40双，便于断言平均≠累计
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_mid.id, product_id=product.id, day=d2, qty=20)
    _log(db, tenant_id=tenant.id, worker_id=worker.id, process_id=p_cut.id, product_id=product.id, day=d2, qty=40)
    db.commit()

    result = production_efficiency_service.department_efficiency_matrix(
        db, tenant.id, date_from=d1, date_to=d2
    )
    assert result["unit"] == "分秒"
    names = [c["department_name"] for c in result["columns"]]
    assert names == ["裁断部", "面部", "成型部", "包装部"]

    cut = next(c for c in result["columns"] if c["segment_code"] == "cut")
    stitch_col = next(c for c in result["columns"] if c["segment_code"] == "stitch")
    forming = next(c for c in result["columns"] if c["segment_code"] == "forming")

    by_date = {r["work_date"]: r["values"] for r in result["rows"]}
    assert [r["work_date"] for r in result["rows"]] == ["2026-09-16", "2026-09-15"]

    cut_d1 = by_date["2026-09-15"][str(cut["segment_id"])]
    assert cut_d1["workers"] == 1
    assert cut_d1["work_hours"] == 8.0
    assert cut_d1["work_time"] == "8小时0分"
    assert cut_d1["qty"] == 80.0
    assert cut_d1["efficiency"] == "6分00秒"

    stitch_d1 = by_date["2026-09-15"][str(stitch_col["segment_id"])]
    assert stitch_d1["workers"] == 1
    assert stitch_d1["qty"] == 60.0
    assert stitch_d1["efficiency"] == "8分00秒"

    forming_d2 = by_date["2026-09-16"][str(forming["segment_id"])]
    assert forming_d2["workers"] == 1
    assert forming_d2["work_hours"] == 4.0
    assert forming_d2["work_time"] == "4小时0分"
    assert forming_d2["qty"] == 20.0
    assert forming_d2["efficiency"] == "12分00秒"

    cut_d2 = by_date["2026-09-16"][str(cut["segment_id"])]
    assert cut_d2["workers"] == 1
    assert cut_d2["work_hours"] == 4.0
    assert cut_d2["qty"] == 40.0

    # 裁断两日平均：人数 (1+1)/2；工时 (8+4)/2；产量 (80+40)/2；单双工时按累计 720分钟/120双
    cut_avg = result["averages"][str(cut["segment_id"])]
    assert cut_avg["workers"] == 1
    assert cut_avg["work_hours"] == 6.0
    assert cut_avg["work_time"] == "6小时0分"
    assert cut_avg["qty"] == 60
    assert cut_avg["efficiency"] == "6分00秒"
    assert result["averages"][str(forming["segment_id"])]["efficiency"] == "12分00秒"