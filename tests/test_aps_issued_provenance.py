"""A'档已排单追溯：确认下发写入排产依据快照 → 甘特已下发条子回读展示。

覆盖三条链路：
  1) 新流程 `_write_header_windows`（窗口 dict 携带 source → order_processes 列）→ `_load_open_header_rows` 回读；
  2) 旧流程列快照（confirm_draft 用 _cap_info 重算写入）→ `_load_existing_windows` 回读；
  3) 平移/急单挤压（dict 不带 source）不覆盖已存快照。

运行：pytest tests/test_aps_issued_provenance.py -s -v
"""

from datetime import date, datetime, timedelta, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    ExecutionHeader,
    Order,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    ProcessDefinition,
    SpecExecutionStatus,
    Tenant,
    WorkLog,
)
from app.services import schedule_engine, schedule_settings
from app.services import execution_schedule_service as ess

AS_OF = date.today()
LOOKBACK = 7


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="追溯厂", settings_json={})
    session.add(tenant)
    session.flush()
    proc = ProcessDefinition(
        tenant_id=tenant.id, name="针车", code="ZC",
        per_worker_capacity=Decimal("300"), standard_workers=4,
    )
    session.add(proc)
    session.flush()
    prod = OwnProduct(tenant_id=tenant.id, product_code="A", is_active=True)
    session.add(prod)
    session.flush()
    # 款 A 针车实测：3 人 × 4 天 × 150/人/天 → 人均 150、活跃 3
    for wid in (1, 2, 3):
        for k in range(1, 5):
            session.add(
                WorkLog(
                    tenant_id=tenant.id, worker_id=wid, order_process_id=999,
                    own_product_id=prod.id, process_id=proc.id, qualified_qty=150,
                    created_at=datetime.combine(AS_OF - timedelta(days=k), time.min),
                )
            )
    session.commit()
    yield session, tenant.id, proc.id, prod.id
    session.close()


def _window_dicts(session, tenant_id, proc_id, product_id, qty=5000):
    """按实测产能生成窗口 dict（与引擎 to_dict 同构，携带 source 字段）。"""
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = schedule_engine._process_capacity_map(session, tenant_id, cfg, as_of=AS_OF)
    specs = [
        schedule_engine.ProcessSpec(id=-1, process_id=proc_id, process_name="针车", plan_qty=qty, band=1)
    ]
    windows = schedule_engine.backward_windows_for_processes(
        specs, AS_OF + timedelta(days=30), cap_map, as_of=AS_OF, own_product_id=product_id
    )
    return [w.to_dict() for w in windows]


def test_header_windows_roundtrip(db, capsys):
    """新流程：写窗口 dict（带 source）→ 已下发回读可见。"""
    session, tenant_id, proc_id, prod_id = db
    header = ExecutionHeader(
        tenant_id=tenant_id, header_no="EH-1", own_product_id=prod_id,
        total_qty=5000, status=SpecExecutionStatus.confirmed,
        delivery_date=AS_OF + timedelta(days=30),
    )
    session.add(header)
    session.flush()
    op = OrderProcess(
        tenant_id=tenant_id, header_id=header.id, process_id=proc_id,
        process_name="针车", plan_qty=5000, status=OrderProcessStatus.pending,
    )
    session.add(op)
    session.commit()

    dicts = _window_dicts(session, tenant_id, proc_id, prod_id)
    assert dicts[0]["source"] == "actual_product"
    wrote = ess._write_header_windows(session, tenant_id, header.id, dicts)
    assert wrote
    session.commit()

    issued = ess._load_open_header_rows(session, tenant_id)
    row = next(r for r in issued if r["header_id"] == header.id)
    w = row["windows"][0]
    print(f"\n新流程回读: source={w['source']} 活跃={w['active_workers']} "
          f"人均={w['avg_per_head']} 效率={w['efficiency']} 日期={w['start_date']}~{w['end_date']}")
    assert w["source"] == "actual_product"
    assert w["active_workers"] == 3
    assert w["avg_per_head"] == 150.0
    assert w["efficiency"] == 0.5  # 150/300


def test_order_process_snapshot_readback(db):
    """旧流程列快照（confirm_draft 写入路径）→ _load_existing_windows 回读。"""
    session, tenant_id, proc_id, prod_id = db
    order = Order(
        tenant_id=tenant_id, order_no="O-OLD", customer_name="客",
        own_product_id=prod_id, total_qty=5000,
        delivery_date=AS_OF + timedelta(days=30), status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    op = OrderProcess(
        tenant_id=tenant_id, order_id=order.id, process_id=proc_id,
        process_name="针车", plan_qty=5000, status=OrderProcessStatus.pending,
        start_date=AS_OF + timedelta(days=3), end_date=AS_OF + timedelta(days=14),
        # 模拟 confirm_draft 用 _cap_info 重算写入的快照
        capacity_source="actual_product", capacity_active_workers=3,
        capacity_avg_per_head=Decimal("150.00"), capacity_efficiency=Decimal("0.50"),
    )
    session.add(op)
    session.commit()

    windows = schedule_engine._load_existing_windows(session, tenant_id)
    w = next(x for x in windows if x.process_id == proc_id)
    assert w.source == "actual_product"
    assert w.active_workers == 3
    assert w.avg_per_head == Decimal("150.00")
    assert w.efficiency == Decimal("0.50")


def test_shift_without_source_keeps_snapshot(db):
    """平移/急单挤压（dict 不带 source）不得覆盖已存快照。"""
    session, tenant_id, proc_id, prod_id = db
    header = ExecutionHeader(
        tenant_id=tenant_id, header_no="EH-2", own_product_id=prod_id,
        total_qty=5000, status=SpecExecutionStatus.confirmed,
        delivery_date=AS_OF + timedelta(days=30),
    )
    session.add(header)
    session.flush()
    op = OrderProcess(
        tenant_id=tenant_id, header_id=header.id, process_id=proc_id,
        process_name="针车", plan_qty=5000, status=OrderProcessStatus.pending,
        start_date=AS_OF + timedelta(days=3), end_date=AS_OF + timedelta(days=14),
        capacity_source="actual_product", capacity_active_workers=3,
        capacity_avg_per_head=Decimal("150.00"), capacity_efficiency=Decimal("0.50"),
    )
    session.add(op)
    session.commit()

    # 平移场景：窗口 dict 只有日期（_write_header_windows 只写携带的字段）
    shifted = [
        {
            "process_id": proc_id,
            "process_name": "针车",
            "plan_qty": 5000,
            "start_date": (AS_OF + timedelta(days=5)).isoformat(),
            "end_date": (AS_OF + timedelta(days=16)).isoformat(),
        }
    ]
    assert ess._write_header_windows(session, tenant_id, header.id, shifted)
    session.commit()
    session.refresh(op)
    assert op.capacity_source == "actual_product", "无 source 的平移不得覆盖快照"
    assert op.capacity_active_workers == 3
    assert op.capacity_avg_per_head == Decimal("150.00")
    assert op.start_date == AS_OF + timedelta(days=5)
    assert op.end_date == AS_OF + timedelta(days=16)
