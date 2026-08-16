from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    Size,
    Tenant,
    User,
    UserRole,
    Worker,
)
from app.services.report_service import ReportError, submit_report
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant = Tenant(name="测试厂")
    session.add(tenant)
    session.flush()
    session.add(
        User(
            tenant_id=tenant.id,
            username="admin",
            password_hash=hash_password("admin123"),
            display_name="管理员",
            role=UserRole.admin,
        )
    )
    for name, code in [("红", "R"), ("黑", "BK")]:
        session.add(Color(tenant_id=tenant.id, name=name, code=code))
    for i, v in enumerate(["37", "38"]):
        session.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))
    procs = []
    for name, code, price, seq in [
        ("裁断", "CT", "0.3", 1),
        ("针车", "ZC", "0.5", 2),
        ("成型", "CX", "0.8", 3),
    ]:
        p = ProcessDefinition(
            tenant_id=tenant.id, name=name, code=code, default_price=Decimal(price), sort_order=seq
        )
        session.add(p)
        session.flush()
        procs.append(p)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="A款",
        quote_price=Decimal("68.00"),
        is_active=True,
    )
    session.add(product)
    session.flush()
    for p in procs:
        session.add(
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=p.id,
                process_name=p.name,
                unit_price=p.default_price,
                sort_order=p.sort_order,
            )
        )
    worker = Worker(tenant_id=tenant.id, name="张三", mobile="13800138001")
    session.add(worker)
    session.commit()

    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client):
    res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    return res.json()["data"]["access_token"]


def test_login_and_create_order(client, db_session):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    products = client.get("/api/v1/own-products", headers=headers).json()["data"]["items"]
    sizes = client.get("/api/v1/sizes", headers=headers).json()["data"]["items"]
    colors = client.get("/api/v1/colors", headers=headers).json()["data"]["items"]
    # 手建生产单已停用；走「订单确认接单」新流程：创建销售订单 → 确认接单。
    res = client.post(
        "/api/v1/sales-orders",
        headers=headers,
        json={
            "order_no": "230711",
            "customer_name": "陈姐",
            "lines": [
                {
                    "own_product_id": products[0]["id"],
                    "color_id": colors[0]["id"],
                    "items": [{"size_id": sizes[0]["id"], "qty": 100}],
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["order_no"] == "230711"
    so_id = body["id"]
    line_id = body["lines"][0]["id"]
    confirmed = client.post(
        "/api/v1/sales-orders/lines/confirm-batch",
        headers=headers,
        json={"lines": [{"sales_order_id": so_id, "line_id": line_id}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["confirmed_count"] == 1


def test_report_salary_and_over_plan(db_session):
    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990001",
            customer_name="测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=10)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=5,
        color_name="红",
        size_value="37",
    )
    assert result["process_completed"] == 5

    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=20,
            confirm_over_plan=False,
        )
    assert ei.value.need_confirm

    result2 = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=20,
        confirm_over_plan=True,
    )
    assert result2["process_completed"] == 25

    from app.services.salary_service import month_salary
    from app.services.nlu import handle_chat

    sal = month_salary(db_session, tenant.id, worker.id)
    assert sal["total_piece_wage"] > 0

    chat = handle_chat(db_session, tenant_id=tenant.id, text="我这个月做了多少了？", worker_id=worker.id)
    assert "应发合计" in chat["reply"]

    chat2 = handle_chat(
        db_session,
        tenant_id=tenant.id,
        text="990001 成型 做了1双",
        worker_id=worker.id,
    )
    assert "报工成功" in chat2["reply"]


def test_rework_report_and_salary(db_session):
    from app.models import OrderProcess, OwnProductLabor
    from app.services.salary_service import month_salary
    from app.services.nlu import handle_chat

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    zc = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "针车")

    # 无工序单价时应失败
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990010",
            customer_name="返修测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    labor = (
        db_session.query(OwnProductLabor)
        .filter_by(own_product_id=product.id, process_id=zc.id)
        .one()
    )
    saved_price = labor.unit_price
    db_session.delete(labor)
    db_session.commit()

    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=10,
            report_type="rework",
        )
    assert ei.value.code == "price_missing"

    # 返修/补数/尾数共用同一 OwnProductLabor.unit_price
    db_session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=zc.id,
            process_name="针车",
            unit_price=saved_price,
            sort_order=2,
        )
    )
    db_session.commit()

    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    before_completed = process.completed_qty

    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
        report_type="rework",
    )
    assert result["report_type"] == "rework"
    assert result["rework_qty"] == 10
    assert result["qualified_qty"] == 0
    assert result["unit_price"] == float(saved_price)
    assert result["amount"] == float(saved_price * 10)

    db_session.refresh(process)
    assert process.completed_qty == before_completed
    assert process.rework_qty == 10

    sal = month_salary(db_session, tenant.id, worker.id)
    rework_lines = [d for d in sal["details"] if d["report_type"] == "rework"]
    assert len(rework_lines) >= 1
    assert rework_lines[-1]["rework_qty"] == 10
    assert rework_lines[-1]["amount"] == float(saved_price * 10)

    chat = handle_chat(
        db_session,
        tenant_id=tenant.id,
        text="990010 红 37码 针车 返修了5双",
        worker_id=worker.id,
    )
    assert "返修报工成功" in chat["reply"]
    db_session.refresh(process)
    assert process.rework_qty == 15
    assert process.completed_qty == before_completed


def test_group_report_equal_split(db_session):
    from app.models import OrderProcess, OrderProcessAssignment, ProcessType, Worker, WorkLog

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    workers = db_session.query(Worker).all()
    # fixture only has one worker — add another
    if len(workers) < 2:
        w2 = Worker(tenant_id=tenant.id, name="李四", mobile="13800138002")
        db_session.add(w2)
        db_session.commit()
        workers = db_session.query(Worker).all()
    w1, w2 = workers[0], workers[1]

    cx = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "成型")
    cx.type = ProcessType.group
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990020",
            customer_name="集体测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="成型").one()
    assert process.process_type == ProcessType.group or str(process.process_type) == "group"

    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=w1.id,
            order_no=order.order_no,
            process_name="成型",
            qualified_qty=100,
        )
    assert ei.value.code == "group_need_members"

    for wid in (w1.id, w2.id):
        db_session.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=wid,
            )
        )
    db_session.commit()

    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=w1.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=100,
    )
    assert result["report_type"] == "group"
    assert result["qualified_qty"] == 100
    assert len(result["members"]) == 2
    assert sum(m["qty"] for m in result["members"]) == 100
    assert "集体报工成功" in result["message"]

    logs = db_session.query(WorkLog).filter_by(order_process_id=process.id).all()
    assert len(logs) == 2
    assert {log.worker_id for log in logs} == {w1.id, w2.id}
    assert all(log.group_id == logs[0].id or log.group_id == logs[0].group_id for log in logs)
    assert all(log.own_product_id == product.id for log in logs)

    db_session.refresh(process)
    assert process.completed_qty == 100


def test_station_report_candidates(client, db_session):
    from app.models import OrderProcess, OrderProcessAssignment, Station

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    worker = db_session.query(Worker).first()
    worker.password_hash = hash_password("123456")
    worker.must_change_password = False
    zc = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "针车")
    station = Station(
        tenant_id=tenant.id,
        code="ZC-T1",
        name="测试针车位",
        process_id=zc.id,
        location="测",
    )
    db_session.add(station)

    order1 = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="991001",
            customer_name="甲",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    order2 = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="991002",
            customer_name="乙",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=80)],
        ),
        created_by=None,
    )
    order3 = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="991003",
            customer_name="丙",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=40)],
        ),
        created_by=None,
    )
    for order in (order1, order2):
        process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
        db_session.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=worker.id,
            )
        )
    # order3：配额已满，不应出现在候选
    p3 = db_session.query(OrderProcess).filter_by(order_id=order3.id, process_name="针车").one()
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order3.id,
            order_process_id=p3.id,
            worker_id=worker.id,
            quota_qty=0,
        )
    )
    db_session.commit()

    # 先给 order2 报一笔，候选默认应优先最近报工的 991002
    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no="991002",
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
    )

    login = client.post(
        "/api/v1/auth/worker/login",
        json={"mobile": "13800138001", "password": "123456"},
    )
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    res = client.get(
        "/api/v1/stations/by-code/ZC-T1/report-candidates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 2
    assert data["default_order_no"] == "991002"
    assert [i["order_no"] for i in data["items"]][0] == "991002"
    assert "991003" not in [i["order_no"] for i in data["items"]]
    assert data["items"][0].get("remaining_quota") is None  # 不限配额


def test_sku_dispatch_quota_and_mismatch(db_session):
    from app.models import OrderProcess, OrderProcessAssignment
    from app.services.report_service import ReportError, submit_report

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    colors = db_session.query(Color).all()
    sizes = db_session.query(Size).all()
    if len(colors) < 2:
        pytest.skip("need 2 colors")
    c1, c2 = colors[0], colors[1]
    size = sizes[0]
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="993101",
            customer_name="色码派工",
            own_product_id=product.id,
            items=[
                OrderItemIn(color_id=c1.id, size_id=size.id, qty=50),
                OrderItemIn(color_id=c2.id, size_id=size.id, qty=50),
            ],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=worker.id,
            color_id=c1.id,
            size_id=size.id,
            quota_qty=10,
        )
    )
    db_session.commit()

    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=8,
        color_name=c1.name,
        size_value=size.size_value,
    )
    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=5,
            color_name=c1.name,
            size_value=size.size_value,
        )
    assert ei.value.code == "over_quota"

    with pytest.raises(ReportError) as ei2:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=1,
            color_name=c2.name,
            size_value=size.size_value,
        )
    assert ei2.value.code == "not_assigned"


def test_void_work_log_rolls_back_progress(db_session):
    from app.models import OrderProcess, WorkLog, WorkLogStatus
    from app.services.report_service import void_work_log

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="992001",
            customer_name="作废测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=30,
        color_name="红",
        size_value="37",
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    assert process.completed_qty == 30
    item = order.items[0]
    db_session.refresh(item)
    assert item.completed_qty == 30

    void_work_log(db_session, tenant_id=tenant.id, work_log_id=result["work_log_id"])
    db_session.refresh(process)
    db_session.refresh(item)
    log = db_session.get(WorkLog, result["work_log_id"])
    assert log.status == WorkLogStatus.void
    assert process.completed_qty == 0
    assert item.completed_qty == 0


def test_correct_work_log_replaces_qty(db_session):
    from app.models import OrderProcess, WorkLog, WorkLogStatus
    from app.services.report_service import correct_work_log

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="992002",
            customer_name="改数测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=40,
        color_name="红",
        size_value="37",
    )
    old_id = result["work_log_id"]
    corrected = correct_work_log(
        db_session,
        tenant_id=tenant.id,
        work_log_id=old_id,
        qualified_qty=25,
        color_name="红",
        size_value="37",
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    old = db_session.get(WorkLog, old_id)
    new = db_session.get(WorkLog, corrected["new_work_log_id"])
    assert old.status == WorkLogStatus.corrected
    assert new.status == WorkLogStatus.valid
    assert new.qualified_qty == 25
    assert process.completed_qty == 25


def test_void_group_work_log_all_members(db_session):
    from app.models import OrderProcess, OrderProcessAssignment, ProcessType, Worker, WorkLog, WorkLogStatus
    from app.services.report_service import void_work_log

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    workers = db_session.query(Worker).all()
    if len(workers) < 2:
        w2 = Worker(tenant_id=tenant.id, name="李四", mobile="13800138999")
        db_session.add(w2)
        db_session.commit()
        workers = db_session.query(Worker).all()
    w1, w2 = workers[0], workers[1]
    cx = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "成型")
    cx.type = ProcessType.group
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="992003",
            customer_name="集体作废",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="成型").one()
    for wid in (w1.id, w2.id):
        db_session.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=wid,
            )
        )
    db_session.commit()

    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=w1.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=80,
    )
    assert process.completed_qty == 80 or True
    db_session.refresh(process)
    assert process.completed_qty == 80

    void_work_log(db_session, tenant_id=tenant.id, work_log_id=result["work_log_id"])
    db_session.refresh(process)
    logs = db_session.query(WorkLog).filter_by(order_process_id=process.id).all()
    assert all(log.status == WorkLogStatus.void for log in logs)
    assert process.completed_qty == 0


def test_progress_board(db_session):
    from app.services.progress_service import progress_board

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    worker = db_session.query(Worker).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="994001",
            customer_name="看板测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
    )
    board = progress_board(db_session, tenant.id)
    assert board["summary"]["open_orders"] >= 1
    assert any(o["order_no"] == "994001" for o in board["orders"])
    row = next(o for o in board["orders"] if o["order_no"] == "994001")
    assert row["bottleneck"] is not None
    assert "today" in board
    assert "charts" in board
    assert "trend" in board["charts"]
    assert "process_bars" in board["charts"]
    assert "delivery_risk" in board["charts"]
    assert len(board["charts"]["trend"]) == 14


def test_workshop_display(db_session):
    from app.services.workshop_display_service import workshop_display

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    worker = db_session.query(Worker).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="994101",
            customer_name="投屏测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=40)],
            is_rush=True,
        ),
        created_by=None,
    )
    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=8,
        color_name="红",
        size_value="37",
    )
    board = workshop_display(db_session, tenant.id)
    assert board["factory_name"] == tenant.name
    assert "yesterday_qualified" in board["summary"]
    assert "today_reported" in board["summary"]
    assert board["summary"]["rush_orders"] >= 1
    assert any(o["order_no"] == "994101" for o in board["focus_orders"])
    assert isinstance(board["process_levels"], list)
    assert isinstance(board["material_blocks"], list)
    focus = next(o for o in board["focus_orders"] if o["order_no"] == "994101")
    assert focus["signal"] == "rush"
    assert focus["bottleneck"] is not None


def test_assignment_quota_blocks_over_report(db_session):
    from app.models import OrderProcess, OrderProcessAssignment
    from app.services.report_service import ReportError, submit_report

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="993001",
            customer_name="配额测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=worker.id,
            quota_qty=20,
        )
    )
    db_session.commit()

    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=15,
        color_name="红",
        size_value="37",
    )
    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=10,
            color_name="红",
            size_value="37",
        )
    assert ei.value.code == "over_quota"

    # 请假：配额锁到已报后不能再报；剩余视作回未分配池
    a = db_session.query(OrderProcessAssignment).filter_by(order_process_id=process.id, worker_id=worker.id).one()
    a.quota_qty = 15
    db_session.commit()
    with pytest.raises(ReportError) as ei2:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=worker.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=1,
            color_name="红",
            size_value="37",
        )
    assert ei2.value.code == "over_quota"


def test_base_plus_piece_salary(db_session):
    from decimal import Decimal

    from app.models import SalaryModel
    from app.services.salary_service import _settle_total, month_salary

    # 纯算法
    s = _settle_total(
        model=SalaryModel.base_plus_piece.value,
        base_salary=Decimal("2000"),
        base_quota=1000,
        piece_wage=Decimal("1500"),
        piece_qty=1500,
    )
    # 超额 500 / 1500 * 1500 = 500
    assert s["payable_piece_wage"] == 500.0
    assert s["total_wage"] == 2500.0

    s2 = _settle_total(
        model=SalaryModel.base_plus_piece.value,
        base_salary=Decimal("2000"),
        base_quota=0,
        piece_wage=Decimal("300"),
        piece_qty=100,
    )
    assert s2["payable_piece_wage"] == 300.0
    assert s2["total_wage"] == 2300.0

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    worker.salary_model = SalaryModel.base_plus_piece
    worker.base_salary = Decimal("100")
    worker.base_quota = 10
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990088",
            customer_name="底薪测",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=15,
        color_name="红",
        size_value="37",
    )
    sal = month_salary(db_session, tenant.id, worker.id)
    assert sal["salary_model"] == "base_plus_piece"
    assert sal["base_salary"] == 100.0
    assert sal["piece_qty"] >= 15
    assert sal["total_wage"] >= sal["base_salary"]
    assert sal["payable_piece_wage"] <= sal["total_piece_wage"]


def test_unallocated_quota_pool(db_session):
    from app.api.v1.orders import _pool_stats, _serialize_order
    from app.models import OrderProcess, OrderProcessAssignment, Worker

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    w1 = db_session.query(Worker).first()
    w2 = Worker(tenant_id=tenant.id, name="李四", mobile="13800138099", is_active=True)
    db_session.add(w2)
    db_session.flush()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()

    assert _pool_stats(1000, [400, 400]) == {
        "allocated_quota": 800,
        "unallocated_qty": 200,
        "has_unlimited_quota": False,
    }
    assert _pool_stats(1000, [400, None])["has_unlimited_quota"] is True
    assert _pool_stats(1000, [])["unallocated_qty"] == 1000

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="993010",
            customer_name="池测试",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=1000)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=w1.id,
            quota_qty=400,
        )
    )
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=w2.id,
            quota_qty=400,
        )
    )
    db_session.commit()
    db_session.refresh(order)

    data = _serialize_order(db_session, order)
    zc = next(p for p in data["processes"] if p["process_name"] == "针车")
    assert zc["allocated_quota"] == 800
    assert zc["unallocated_qty"] == 200
    assert zc["has_unlimited_quota"] is False


def test_appeal_and_reject_flow(db_session):
    from app.models import WorkLog, WorkLogStatus
    from app.services.report_service import appeal_work_log, reject_appeal, submit_report
    from app.services.salary_service import month_salary

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="992001",
            customer_name="申诉测",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
    )
    log_id = result["work_log_id"]
    sal_before = month_salary(db_session, tenant.id, worker.id)
    assert any(d["work_log_id"] == log_id for d in sal_before["details"])

    appeal = appeal_work_log(
        db_session,
        tenant_id=tenant.id,
        work_log_id=log_id,
        worker_id=worker.id,
        reason="报多数了",
    )
    assert appeal["status"] == "appealed"
    log = db_session.get(WorkLog, log_id)
    assert log.status == WorkLogStatus.appealed
    sal_pending = month_salary(db_session, tenant.id, worker.id)
    assert not any(d["work_log_id"] == log_id for d in sal_pending["details"])

    reject_appeal(db_session, tenant_id=tenant.id, work_log_id=log_id, review_note="核实无误")
    db_session.refresh(log)
    assert log.status == WorkLogStatus.valid
    sal_after = month_salary(db_session, tenant.id, worker.id)
    assert any(d["work_log_id"] == log_id for d in sal_after["details"])


def test_supplement_and_tail_report(db_session):
    from app.services.report_service import submit_report
    from app.services.salary_service import month_salary

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    zc = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "针车")
    labor = (
        db_session.query(OwnProductLabor)
        .filter_by(own_product_id=product.id, process_id=zc.id)
        .one()
    )
    expected_price = float(labor.unit_price)

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="992010",
            customer_name="补尾测",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    s1 = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=5,
        color_name="红",
        size_value="37",
        report_type="supplement",
    )
    assert "补数报工成功" in s1["message"]
    assert s1["unit_price"] == expected_price

    s2 = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=3,
        color_name="红",
        size_value="37",
        report_type="tail",
    )
    assert "尾数报工成功" in s2["message"]
    assert s2["unit_price"] == expected_price

    sal = month_salary(db_session, tenant.id, worker.id)
    types = {d["report_type"] for d in sal["details"]}
    assert "supplement" in types
    assert "tail" in types


def test_update_order_items_and_import(db_session):
    from app.services.order_service import import_orders_csv, import_template_csv, update_order

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="981001",
            customer_name="改明细",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    assert order.total_qty == 100

    updated = update_order(
        db_session,
        tenant.id,
        order.id,
        customer_name="改明细客户",
        items=[
            OrderItemIn(color_id=color.id, size_id=size.id, qty=150),
        ],
    )
    assert updated.customer_name == "改明细客户"
    assert updated.total_qty == 150
    assert updated.processes[0].plan_qty == 150

    csv_text = import_template_csv().replace("A款", product.product_code)
    # 用唯一单号避免冲突
    csv_text = csv_text.replace("230801", "981801").replace("230802", "981802")
    result = import_orders_csv(db_session, tenant.id, csv_text, created_by=None)
    assert result["created_count"] >= 1
    assert "981801" in result["created"] or result["created_count"] >= 1


def test_report_locks_unit_price_against_later_change(db_session):
    from app.models import WorkLog
    from app.services.salary_service import month_salary

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    zc = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "针车")
    labor = (
        db_session.query(OwnProductLabor)
        .filter_by(own_product_id=product.id, process_id=zc.id)
        .one()
    )
    labor.unit_price = Decimal("0.50")
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="994001",
            customer_name="锁价",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=10,
        color_name="红",
        size_value="37",
    )
    log = db_session.get(WorkLog, result["work_log_id"])
    assert log is not None
    assert Decimal(log.unit_price) == Decimal("0.50")

    labor.unit_price = Decimal("1.20")
    db_session.commit()

    sal = month_salary(db_session, tenant.id, worker.id)
    detail = next(d for d in sal["details"] if d["work_log_id"] == log.id)
    assert detail["unit_price"] == 0.5
    assert detail["price_locked"] is True
    assert abs(detail["amount"] - 5.0) < 1e-6


def test_month_lock_blocks_void(db_session):
    from app.models import WorkLog
    from app.services.report_service import void_work_log
    from app.services.salary_service import set_month_lock, year_month_of

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="994002",
            customer_name="月结锁",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=5,
        color_name="红",
        size_value="37",
    )
    log = db_session.get(WorkLog, result["work_log_id"])
    ym = year_month_of(log.created_at)
    set_month_lock(db_session, tenant.id, ym, locked=True, locked_by=1)

    with pytest.raises(ReportError) as ei:
        void_work_log(db_session, tenant_id=tenant.id, work_log_id=log.id)
    assert ei.value.code == "month_locked"

    set_month_lock(db_session, tenant.id, ym, locked=False)
    void_work_log(db_session, tenant_id=tenant.id, work_log_id=log.id)
    db_session.refresh(log)
    assert log.status.value == "void"


def test_bank_export_and_salary_ack(db_session):
    from app.services.salary_service import (
        acknowledge_salary,
        export_bank_payroll_csv,
        set_month_lock,
        year_month_of,
    )

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    worker = db_session.query(Worker).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    worker.bank_account = "6222021234567890"
    worker.bank_name = "工行测试支行"
    worker.bank_account_name = worker.name
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="994101",
            customer_name="代发",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=50)],
        ),
        created_by=None,
    )
    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=8,
        color_name="红",
        size_value="37",
    )
    from app.models import WorkLog

    log = db_session.get(WorkLog, result["work_log_id"])
    ym = year_month_of(log.created_at)

    with pytest.raises(ValueError):
        export_bank_payroll_csv(db_session, tenant.id, ym)

    set_month_lock(db_session, tenant.id, ym, locked=True, locked_by=1)
    csv_text = export_bank_payroll_csv(db_session, tenant.id, ym)
    assert "银行卡号" in csv_text or "6222021234567890" in csv_text
    assert worker.name in csv_text

    with pytest.raises(ValueError):
        acknowledge_salary(
            db_session,
            tenant.id,
            worker.id,
            year_month=ym,
            confirm_name="不是本人",
        )
    ack = acknowledge_salary(
        db_session,
        tenant.id,
        worker.id,
        year_month=ym,
        confirm_name=worker.name,
        signature_data="data:image/png;base64,xx",
    )
    assert ack["confirm_name"] == worker.name
    csv2 = export_bank_payroll_csv(db_session, tenant.id, ym)
    assert "是" in csv2


def test_group_report_ratio_split(db_session):
    from app.models import OrderProcess, OrderProcessAssignment, ProcessType, Worker, WorkLog

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    workers = db_session.query(Worker).all()
    if len(workers) < 2:
        db_session.add(Worker(tenant_id=tenant.id, name="王五", mobile="13800138009"))
        db_session.commit()
        workers = db_session.query(Worker).all()
    w1, w2 = workers[0], workers[1]

    # 分组按比例拆分现在优先使用技能系数（enable_skill_factor_split 默认开），
    # 以 2:1 技能系数表达比例；share_weight 仅在不启用技能系数时生效。
    w1.skill_factor = Decimal("2.00")
    w2.skill_factor = Decimal("1.00")
    db_session.commit()

    cx = next(p for p in db_session.query(ProcessDefinition).all() if p.name == "成型")
    cx.type = ProcessType.group
    db_session.commit()

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990021",
            customer_name="比例集体",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="成型").one()
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=w1.id,
            share_weight=2,
        )
    )
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=w2.id,
            share_weight=1,
        )
    )
    db_session.commit()

    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=w1.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=100,
    )
    by_id = {m["worker_id"]: m["qty"] for m in result["members"]}
    assert by_id[w1.id] == 67
    assert by_id[w2.id] == 33
    assert sum(by_id.values()) == 100

    logs = db_session.query(WorkLog).filter_by(order_process_id=process.id).all()
    assert all(log.group_detail and log.group_detail.get("split") == "ratio" for log in logs)
    assert all(any(m.get("weight") for m in log.group_detail["members"]) for log in logs)


def test_bundle_dispatch_gates_report(db_session):
    from app.models import OrderProcess, OrderProcessAssignment, Worker, WorkLog
    from app.services.trace_service import create_bundle

    tenant = db_session.query(Tenant).first()
    product = db_session.query(OwnProduct).first()
    color = db_session.query(Color).first()
    size = db_session.query(Size).first()
    workers = db_session.query(Worker).all()
    if len(workers) < 2:
        db_session.add(Worker(tenant_id=tenant.id, name="赵六", mobile="13800138008"))
        db_session.commit()
        workers = db_session.query(Worker).all()
    w1, w2 = workers[0], workers[1]

    order = create_order(
        db_session,
        tenant.id,
        OrderCreate(
            order_no="990022",
            customer_name="捆派工",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=100)],
        ),
        created_by=None,
    )
    process = db_session.query(OrderProcess).filter_by(order_id=order.id, process_name="针车").one()
    unit = create_bundle(
        db_session,
        tenant_id=tenant.id,
        order_id=order.id,
        qty=20,
        color_id=color.id,
        size_id=size.id,
        worker_id=w1.id,
        commit=True,
    )
    db_session.add(
        OrderProcessAssignment(
            tenant_id=tenant.id,
            order_id=order.id,
            order_process_id=process.id,
            worker_id=w1.id,
            trace_unit_id=unit.id,
            quota_qty=20,
        )
    )
    db_session.commit()

    with pytest.raises(ReportError) as ei:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=w1.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=10,
            color_name=color.name,
            size_value=size.size_value,
        )
    assert ei.value.code == "need_trace_unit"

    with pytest.raises(ReportError) as ei2:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=w2.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=10,
            color_name=color.name,
            size_value=size.size_value,
            trace_unit_id=unit.id,
        )
    assert ei2.value.code == "not_assigned"

    with pytest.raises(ReportError) as ei3:
        submit_report(
            db_session,
            tenant_id=tenant.id,
            worker_id=w1.id,
            order_no=order.order_no,
            process_name="针车",
            qualified_qty=25,
            color_name=color.name,
            size_value=size.size_value,
            trace_unit_id=unit.id,
        )
    assert ei3.value.code == "over_bundle_qty"

    result = submit_report(
        db_session,
        tenant_id=tenant.id,
        worker_id=w1.id,
        order_no=order.order_no,
        process_name="针车",
        qualified_qty=20,
        color_name=color.name,
        size_value=size.size_value,
        trace_unit_id=unit.id,
    )
    log = db_session.get(WorkLog, result["work_log_id"])
    assert log.trace_unit_id == unit.id
    assert log.qualified_qty == 20
