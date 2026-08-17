"""工资 vs 实际人工成本对账：应发工资 vs 当月报工计件总额（同源口径）差异根因分解。

覆盖：纯计件一致 / 底薪差异 / 定额折算 / 非在职员工报工 / 返修不计薪 /
月结锁定后签名完成度（all_acknowledged / unacknowledged）/ AI 分析入口。
"""

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
    SalaryModel,
    Size,
    Tenant,
    Worker,
)
from app.services import analytics, report_service, salary_service


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


def _seed(db, *, workers: list[Worker] | None = None, plan_qty: int = 1000):
    tenant = Tenant(name="对账厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    product = OwnProduct(tenant_id=tenant.id, product_code="AF-01", quote_price=Decimal("80"))
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        sort_order=1,
        type=ProcessType.personal,
    )
    db.add_all([color, size, product, zc])
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
    db.add(OrderItem(tenant_id=tenant.id, order_id=order.id, color_id=color.id, size_id=size.id, qty=plan_qty))
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
    if workers is None:
        workers = [Worker(tenant_id=tenant.id, name="张三", mobile="13900000001", is_active=True)]
    db.add_all(workers)
    db.commit()
    return {
        "tenant": tenant,
        "color": color,
        "size": size,
        "product": product,
        "zc": zc,
        "order": order,
        "workers": workers,
    }


def _report(db, ctx, worker, qty: int, *, rework: bool = False, plan_qty: int = 1000):
    report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=worker.id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=qty,
        confirm_over_plan=qty > plan_qty,
        report_type="rework" if rework else "normal",
    )


def _ym() -> str:
    return salary_service.year_month_of(None)


def test_pure_piece_payroll_matches_labor_cost(db):
    ctx = _seed(db)
    w = ctx["workers"][0]
    _report(db, ctx, w, 10)
    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id)
    assert result["variance"]["amount"] == pytest.approx(0.0, abs=0.01)
    assert result["variance"]["explained"] is True
    assert result["payroll"]["count"] == 1
    assert result["labor_cost"]["total"] == pytest.approx(20.0)  # 10 × 2.0
    assert result["payroll"]["total_wage"] == pytest.approx(20.0)
    assert result["breakdown_nonzero"] == []


def test_fixed_salary_base_creates_variance(db):
    ctx = _seed(
        db,
        workers=[
            Worker(
                tenant_id=1,
                name="李四",
                mobile="13900000002",
                is_active=True,
                salary_model=SalaryModel.fixed,
                base_salary=Decimal("3000.00"),
            )
        ],
    )
    w = ctx["workers"][0]
    _report(db, ctx, w, 10)  # 报工计件 20 元，但工资只发底薪
    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id)
    # 应发 = 底薪 3000；人工成本 = 计件 20；差异 = +2980，全部来自底薪 bucket
    assert result["payroll"]["total_wage"] == pytest.approx(3000.0)
    assert result["labor_cost"]["total"] == pytest.approx(20.0)
    assert result["variance"]["amount"] == pytest.approx(2980.0, abs=0.01)
    buckets = {b["key"]: b["amount"] for b in result["breakdown_nonzero"]}
    assert buckets.get("base_salary") == pytest.approx(3000.0)
    assert buckets.get("fixed_piece_unpaid") == pytest.approx(-20.0, abs=0.01)
    assert result["variance"]["explained"] is True


def test_base_plus_piece_quota_reduction_bucket(db):
    ctx = _seed(
        db,
        workers=[
            Worker(
                tenant_id=1,
                name="王五",
                mobile="13900000003",
                is_active=True,
                salary_model=SalaryModel.base_plus_piece,
                base_salary=Decimal("2000.00"),
                base_quota=10,
            )
        ],
    )
    w = ctx["workers"][0]
    _report(db, ctx, w, 100)  # 计件全额 200 元；定额 10，超额 90/100 → 应发计件 180
    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id)
    # 应发 = 2000 + 180 = 2180；人工成本 = 200；差异 = +1980 = 底薪 2000 − 定额折算 20
    assert result["payroll"]["total_wage"] == pytest.approx(2180.0, abs=0.01)
    assert result["labor_cost"]["total"] == pytest.approx(200.0, abs=0.01)
    assert result["variance"]["amount"] == pytest.approx(1980.0, abs=0.01)
    buckets = {b["key"]: b["amount"] for b in result["breakdown_nonzero"]}
    assert buckets.get("base_salary") == pytest.approx(2000.0)
    assert buckets.get("quota_reduction") == pytest.approx(-20.0, abs=0.01)
    assert result["variance"]["explained"] is True


def test_inactive_worker_logs_bucket(db):
    ctx = _seed(db)
    w = ctx["workers"][0]
    _report(db, ctx, w, 10)
    # 报工后停用：工资应发不再计此人，但人工成本仍含其报工
    w.is_active = False
    db.commit()
    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id)
    assert result["payroll"]["count"] == 0
    assert result["labor_cost"]["total"] == pytest.approx(20.0)
    assert result["labor_cost"]["inactive_workers_piece"] == pytest.approx(20.0)
    buckets = {b["key"]: b["amount"] for b in result["breakdown_nonzero"]}
    assert buckets.get("inactive_worker_logs") == pytest.approx(-20.0, abs=0.01)


def test_unpaid_rework_reported(db):
    from app.services import reporting_settings

    ctx = _seed(db)
    w = ctx["workers"][0]
    # 该租户设置返修不计薪
    reporting_settings.save_reporting_patch(db, ctx["tenant"].id, {"rework_pays": False})
    _report(db, ctx, w, 10)
    _report(db, ctx, w, 3, rework=True)
    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id)
    # 返修 3×2=6 元不计薪：应发 = 20，人工成本 = 20，无差异
    assert result["payroll"]["total_wage"] == pytest.approx(20.0)
    assert result["labor_cost"]["total"] == pytest.approx(20.0)
    assert result["labor_cost"]["unpaid_rework_count"] == 1
    assert result["labor_cost"]["unpaid_rework_amount"] == pytest.approx(6.0, abs=0.01)
    assert result["variance"]["amount"] == pytest.approx(0.0, abs=0.01)


def test_locked_month_signature_completion(db):
    ctx = _seed(db)
    w = ctx["workers"][0]
    _report(db, ctx, w, 10)
    ym = _ym()
    salary_service.set_month_lock(db, ctx["tenant"].id, ym, locked=True)

    overview = salary_service.month_salary_all(db, ctx["tenant"].id, ym)
    assert overview["is_locked"] is True
    assert overview["all_acknowledged"] is False
    assert len(overview["unacknowledged"]) == 1
    assert overview["unacknowledged"][0]["worker_id"] == w.id

    salary_service.acknowledge_salary(
        db,
        ctx["tenant"].id,
        w.id,
        year_month=ym,
        confirm_name=w.name,
    )
    overview2 = salary_service.month_salary_all(db, ctx["tenant"].id, ym)
    assert overview2["acknowledged_count"] == 1
    assert overview2["all_acknowledged"] is True
    assert overview2["unacknowledged"] == []

    result = salary_service.reconcile_salary_cost(db, ctx["tenant"].id, ym)
    assert result["signature"]["all_acknowledged"] is True
    assert result["signature"]["unacknowledged"] == []


def test_analytics_ai_entry_insights(db):
    ctx = _seed(
        db,
        workers=[
            Worker(
                tenant_id=1,
                name="赵六",
                mobile="13900000004",
                is_active=True,
                salary_model=SalaryModel.fixed,
                base_salary=Decimal("5000.00"),
            )
        ],
    )
    w = ctx["workers"][0]
    _report(db, ctx, w, 50)
    ym = _ym()
    result = analytics.analyze_salary_cost_reconcile(db, ctx["tenant"].id, year_month=ym)
    assert result["analysis_id"] == "salary_cost_reconcile"
    assert result["title"] == "工资与人工成本对账"
    assert result["insights"]
    assert "应发工资" in result["summary"]
    assert result["chart"]["type"] == "bar"
    bucket_texts = " ".join(i["text"] for i in result["insights"])
    assert "底薪部分" in bucket_texts

    # 指标入口注册：workshop_metrics 可直接查询
    from app.services import workshop_metrics

    metric = workshop_metrics.query_metric(
        db,
        ctx["tenant"].id,
        "analytics.salary_cost_reconcile",
        params={"year_month": ym},
        permission_codes=["menu.salary"],
    )
    assert metric["metric_id"] == "analytics.salary_cost_reconcile"
    assert metric["data"]["analysis_id"] == "salary_cost_reconcile"


def test_api_salary_reconcile_endpoint(db):
    from fastapi.testclient import TestClient

    from app.auth import create_access_token
    from app.db import get_db
    from app.main import app
    from app.models import User

    ctx = _seed(
        db,
        workers=[
            Worker(
                tenant_id=1,
                name="钱七",
                mobile="13900000005",
                is_active=True,
                salary_model=SalaryModel.fixed,
                base_salary=Decimal("4000.00"),
            )
        ],
    )
    w = ctx["workers"][0]
    _report(db, ctx, w, 25)
    admin = User(
        tenant_id=ctx["tenant"].id,
        username="boss",
        password_hash="x",
        display_name="老板",
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    token = create_access_token(admin)
    res = client.get(
        "/api/v1/salary/reconcile",
        headers={"Authorization": f"Bearer {token}"},
        params={"year_month": _ym()},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["payroll"]["total_wage"] == pytest.approx(4000.0)
    assert data["labor_cost"]["total"] == pytest.approx(50.0)
    assert data["variance"]["amount"] == pytest.approx(3950.0, abs=0.01)
    assert {b["key"] for b in data["breakdown_nonzero"]} == {"base_salary", "fixed_piece_unpaid"}
    app.dependency_overrides.clear()
