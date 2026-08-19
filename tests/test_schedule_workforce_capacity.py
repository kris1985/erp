"""A'档：报工实测产能优先、配置兜底（覆盖 > 款级实测 > 工序级实测 > 标准）。

用例：覆盖优先 / 款级复杂度 / 工序级回退 / 无史回退 / 未配置抛错 / 窗口参数 / 阈值防失真。
"""

from datetime import date, datetime, timedelta, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    OwnProduct,
    ProcessDefinition,
    Tenant,
    WorkLog,
)
from app.services import schedule_engine, schedule_settings


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
    tenant = Tenant(name="实测厂", settings_json={})
    session.add(tenant)
    session.flush()
    ct = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("0.8"),
        per_worker_capacity=Decimal("30"),
        standard_workers=1,
        sort_order=1,
    )
    no_cap = ProcessDefinition(
        tenant_id=tenant.id,
        name="未配产能",
        code="NC",
        default_price=Decimal("0.1"),
        per_worker_capacity=None,
        standard_workers=1,
        sort_order=2,
    )
    session.add_all([ct, no_cap])
    session.flush()
    prod_a = OwnProduct(tenant_id=tenant.id, product_code="E1", is_active=True)
    prod_b = OwnProduct(tenant_id=tenant.id, product_code="E2", is_active=True)
    session.add_all([prod_a, prod_b])
    session.commit()
    yield session, tenant.id, ct.id, no_cap.id, prod_a.id, prod_b.id
    session.close()


def _report(session, tenant_id, process_id, product_id, worker_id, qty, days_ago):
    session.add(
        WorkLog(
            tenant_id=tenant_id,
            worker_id=worker_id,
            order_process_id=999,
            own_product_id=product_id,
            process_id=process_id,
            qualified_qty=qty,
            created_at=datetime.combine(date.today() - timedelta(days=days_ago), time.min),
        )
    )


def _seed_reports(session, tenant_id, process_id, product_id, *, workers, per_day, days=4):
    """每人每天 per_day 双、连续 days 天（工作日不限，直接用自然日）。"""
    for wid in workers:
        for k in range(1, days + 1):
            _report(session, tenant_id, process_id, product_id, wid, per_day, k)
    session.commit()


def _cap_map(session, tenant_id, cfg, **kw):
    return schedule_engine._process_capacity_map(
        session, tenant_id, cfg, as_of=kw.get("as_of", date.today())
    )


def test_no_history_falls_back_to_standard(db):
    session, tenant_id, ct_id, _nc, prod_a, _b = db
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)
    pc = cap_map[ct_id]
    assert pc.process_actual is None
    assert pc.product_actual is None
    days = schedule_engine._calc_days(cap_map, ct_id, 100, own_product_id=prod_a)
    assert days == 4  # ⌈100/30⌉，无史回退标准公式
    cap, workers, src, st = schedule_engine._effective_capacity(pc, prod_a)
    assert src == "standard"
    assert workers == 1


def test_actual_product_level_and_complexity(db):
    session, tenant_id, ct_id, _nc, prod_a, prod_b = db
    # E1 人均 25（3 人 × 4 天 × 25），E2 人均 12（3 人 × 4 天 × 12）——同工序不同款复杂度不同
    _seed_reports(session, tenant_id, ct_id, prod_a, workers=[1, 2, 3], per_day=25)
    _seed_reports(session, tenant_id, ct_id, prod_b, workers=[4, 5, 6], per_day=12)
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)

    assert cap_map[ct_id].process_actual is not None
    assert set((cap_map[ct_id].product_actual or {}).keys()) == {prod_a, prod_b}

    # 款级：E1 → ⌈100/(25×3)⌉=2 天；E2 → ⌈100/(12×3)⌉=3 天（复杂度差异进入产能）
    days_a = schedule_engine._calc_days(cap_map, ct_id, 100, own_product_id=prod_a)
    days_b = schedule_engine._calc_days(cap_map, ct_id, 100, own_product_id=prod_b)
    assert days_a == 2
    assert days_b == 3

    cap, workers, src, st = schedule_engine._effective_capacity(cap_map[ct_id], prod_a)
    assert src == "actual_product"
    assert workers == 3
    assert cap == Decimal("25")


def test_product_without_history_falls_back_to_process_actual(db):
    session, tenant_id, ct_id, _nc, prod_a, prod_b = db
    # 只有 E1 有报工；E3 无报工 → 工序级实测兜底
    _seed_reports(session, tenant_id, ct_id, prod_a, workers=[1, 2, 3], per_day=25)
    prod_c = OwnProduct(tenant_id=tenant_id, product_code="E3", is_active=True)
    session.add(prod_c)
    session.commit()
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)

    cap, workers, src, st = schedule_engine._effective_capacity(cap_map[ct_id], prod_c.id)
    assert src == "actual_process"
    assert workers == 3  # 工序级活跃人数
    assert cap == Decimal("25")  # 工序级实测人均


def test_override_beats_actual(db):
    session, tenant_id, ct_id, _nc, prod_a, _b = db
    _seed_reports(session, tenant_id, ct_id, prod_a, workers=[1, 2, 3], per_day=25)
    ct = session.get(ProcessDefinition, ct_id)
    ct.current_workers = 2
    session.commit()
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)

    cap, workers, src, st = schedule_engine._effective_capacity(cap_map[ct_id], prod_a)
    assert src == "override"
    assert workers == 2
    assert cap == Decimal("30")  # 覆盖只用标准单人产能 × 覆盖人数
    # 300 双：覆盖 ⌈300/(30×2)⌉=5 天；若不覆盖按实测 ⌈300/(25×3)⌉=4 天
    assert schedule_engine._calc_days(cap_map, ct_id, 300, own_product_id=prod_a) == 5
    # 负荷口径也吃覆盖：日产能 = 30×2
    assert schedule_engine._daily_capacity(cap_map, ct_id) == Decimal("60")


def test_lookback_zero_disables_actual(db):
    session, tenant_id, ct_id, _nc, prod_a, _b = db
    _seed_reports(session, tenant_id, ct_id, prod_a, workers=[1, 2, 3], per_day=25)
    schedule_settings.save_schedule_patch(
        session, tenant_id, {"actual_capacity_lookback_days": 0}
    )
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)
    assert cap_map[ct_id].process_actual is None
    cap, workers, src, st = schedule_engine._effective_capacity(cap_map[ct_id], prod_a)
    assert src == "standard"
    assert workers == 1


def test_min_threshold_blocks_sparse_actual(db):
    session, tenant_id, ct_id, _nc, prod_a, _b = db
    # 只有 1 人报 1 天（低于 min_workers=2 / min_person_days=3）→ 视为无史
    _report(session, tenant_id, ct_id, prod_a, 1, 25, 1)
    session.commit()
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)
    assert cap_map[ct_id].process_actual is None
    assert cap_map[ct_id].product_actual is None


def test_missing_capacity_still_raises(db):
    session, tenant_id, _ct, no_cap, prod_a, _b = db
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)
    with pytest.raises(ValueError, match="未配置单人日产能"):
        schedule_engine._calc_days(cap_map, no_cap, 100, own_product_id=prod_a)


def test_window_carries_capacity_source(db):
    from app.services.schedule_engine import ProcessSpec

    session, tenant_id, ct_id, _nc, prod_a, _b = db
    _seed_reports(session, tenant_id, ct_id, prod_a, workers=[1, 2, 3], per_day=25)
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = _cap_map(session, tenant_id, cfg)
    specs = [
        ProcessSpec(id=-1, process_id=ct_id, process_name="针车", plan_qty=100, band=1)
    ]
    windows = schedule_engine.backward_windows_for_processes(
        specs,
        date.today() + timedelta(days=20),
        cap_map,
        as_of=date.today(),
        own_product_id=prod_a,
    )
    assert len(windows) == 1
    w = windows[0]
    assert w.days == 2
    assert w.source == "actual_product"
    assert w.active_workers == 3
    assert w.avg_per_head == Decimal("25")
    assert w.efficiency == Decimal("0.83")  # 25/30 保留两位
    d = w.to_dict()
    assert d["source"] == "actual_product"
    assert d["avg_per_head"] == 25.0
