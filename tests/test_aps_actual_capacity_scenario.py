"""A'档验收场景：规划测试数据 → 手工预期 → 引擎排期 → 对比结论。

覆盖优先级链四种形态：
  - 款级实测（A 女鞋 / B 运动鞋同工序不同复杂度）
  - 工序级实测回退（C 新款无款级报工）
  - 标准回退（P3 成型无任何报工）
  - 手动覆盖（P2 current_workers=5 压过一切）
运行：pytest tests/test_aps_actual_capacity_scenario.py -s -v
"""

from datetime import date, datetime, timedelta, time
from decimal import Decimal
from math import ceil

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import OwnProduct, ProcessDefinition, Tenant, WorkLog
from app.services import schedule_engine, schedule_settings


# ---------------------------------------------------------------- 测试数据规划
AS_OF = date.today()
DELIVERY = AS_OF + timedelta(days=30)
QTY = 5000
LOOKBACK = 7

# 工序：单人日产能 / 标准人力
PROCS = {
    "P1裁断": (Decimal("400"), 2),
    "P2针车": (Decimal("300"), 4),
    "P3成型": (Decimal("200"), 3),
}

# 报工史：(款, 工序) -> (worker_ids, 每人每天, 天数)
HISTORY = {
    ("A", "P1裁断"): ([1, 2], 350, 5),
    ("A", "P2针车"): ([1, 2, 3], 150, 5),
    ("B", "P1裁断"): ([3, 4], 320, 4),
    ("B", "P2针车"): ([4, 5, 6], 100, 5),
}

# 订单：款 -> (own_product_code, qty)
ORDERS = {
    "X(A女鞋)": ("A", QTY),
    "Y(B运动鞋)": ("B", QTY),
    "Z(C新款)": ("C", QTY),
}

# 手工预期（优先级链解析后）：(人均, 人数, source) / 天数
# 款级：
#   A.P1: 350×2=700 → ⌈5000/700⌉=8   A.P2: 150×3=450 → ⌈5000/450⌉=12
#   B.P1: 320×2=640 → ⌈5000/640⌉=8   B.P2: 100×3=300 → ⌈5000/300⌉=17
# 工序级（C 款回退）：
#   P1: 6060/18=336.7 → 336.7×4=1346.8 → ⌈5000/1346.8⌉=4
#   P2: 3750/30=125 → 125×6=750 → ⌈5000/750⌉=7
# 标准（P3 无史）：200×3=600 → ⌈5000/600⌉=9
EXPECTED = {
    "X(A女鞋)": {
        "P1裁断": (Decimal("350"), 2, "actual_product", 8),
        "P2针车": (Decimal("150"), 3, "actual_product", 12),
        "P3成型": (Decimal("200"), 3, "standard", 9),
    },
    "Y(B运动鞋)": {
        "P1裁断": (Decimal("320"), 2, "actual_product", 8),
        "P2针车": (Decimal("100"), 3, "actual_product", 17),
        "P3成型": (Decimal("200"), 3, "standard", 9),
    },
    "Z(C新款)": {
        "P1裁断": (Decimal("336.7"), 4, "actual_process", 4),
        "P2针车": (Decimal("125"), 6, "actual_process", 7),
        "P3成型": (Decimal("200"), 3, "standard", 9),
    },
}

# 覆盖场景：P2 手动覆盖 5 人 → 300×5=1500 → ⌈5000/1500⌉=4（全部订单，压过实测）
EXPECTED_OVERRIDE = {
    "P2针车": (Decimal("300"), 5, "override", 4),
}


def _days(qty: int, cap: Decimal, workers: int) -> int:
    return max(1, int(ceil(Decimal(qty) / (cap * Decimal(workers)))))


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
    tenant = Tenant(name="验收厂", settings_json={})
    session.add(tenant)
    session.flush()

    proc_ids: dict[str, int] = {}
    for i, (name, (cap, wk)) in enumerate(PROCS.items()):
        p = ProcessDefinition(
            tenant_id=tenant.id,
            name=name,
            code=f"P{i + 1}",
            default_price=Decimal("0.5"),
            per_worker_capacity=cap,
            standard_workers=wk,
            sort_order=i + 1,
        )
        session.add(p)
        session.flush()
        proc_ids[name] = p.id
    # 未配置产能工序（验证抛错）
    no_cap = ProcessDefinition(
        tenant_id=tenant.id, name="未配置", code="NC", per_worker_capacity=None, standard_workers=1
    )
    session.add(no_cap)
    session.flush()

    product_ids: dict[str, int] = {}
    for code in ("A", "B", "C"):
        p = OwnProduct(tenant_id=tenant.id, product_code=code, is_active=True)
        session.add(p)
        session.flush()
        product_ids[code] = p.id

    # 报工史：created_at 落在近 LOOKBACK 天内
    for (pcode, pname), (workers, per_day, days_cnt) in HISTORY.items():
        for wid in workers:
            for k in range(1, days_cnt + 1):
                session.add(
                    WorkLog(
                        tenant_id=tenant.id,
                        worker_id=wid,
                        order_process_id=999,
                        own_product_id=product_ids[pcode],
                        process_id=proc_ids[pname],
                        qualified_qty=per_day,
                        created_at=datetime.combine(AS_OF - timedelta(days=k), time.min),
                    )
                )
    session.commit()
    yield session, tenant.id, proc_ids, no_cap.id, product_ids
    session.close()


def _route_specs(proc_ids: dict[str, int], plan_qty: int) -> list[schedule_engine.ProcessSpec]:
    return [
        schedule_engine.ProcessSpec(id=-(i + 1), process_id=pid, process_name=name, plan_qty=plan_qty, band=i + 1)
        for i, (name, pid) in enumerate(proc_ids.items())
    ]


def _run_order(
    session, tenant_id, proc_ids, product_ids, *, order_key: str, override: bool = False
):
    pcode = ORDERS[order_key][0]
    if override:
        session.execute(
            __import__("sqlalchemy").update(ProcessDefinition)
            .where(ProcessDefinition.id == proc_ids["P2针车"])
            .values(current_workers=5)
        )
        session.commit()
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = schedule_engine._process_capacity_map(session, tenant_id, cfg, as_of=AS_OF)
    specs = _route_specs(proc_ids, QTY)
    windows = schedule_engine.backward_windows_for_processes(
        specs,
        DELIVERY,
        cap_map,
        as_of=AS_OF,
        own_product_id=product_ids[pcode],
    )
    return cap_map, windows


def _fmt(w) -> str:
    return (
        f"{w.process_name} | {w.days}天 | {w.start_date}~{w.end_date} | "
        f"{w.active_workers}人×{w.avg_per_head}/人/天 | 效率{w.efficiency} | {w.source}"
    )


def test_scenario_main_compare(db, capsys):
    """主场景：款级实测 / 工序级回退 / 标准回退，逐项对比手工预期。"""
    session, tenant_id, proc_ids, _nc, product_ids = db
    print("\n" + "=" * 96)
    print("【主场景】引擎实际排期（5000 双，交期", DELIVERY, "，实测窗口", LOOKBACK, "天）")
    print("=" * 96)
    all_ok = True
    for order_key in ("X(A女鞋)", "Y(B运动鞋)", "Z(C新款)"):
        cap_map, windows = _run_order(session, tenant_id, proc_ids, product_ids, order_key=order_key)
        pcode = ORDERS[order_key][0]
        print(f"\n订单 {order_key}（款 {pcode}）:")
        for w in windows:
            exp_cap, exp_wk, exp_src, exp_days = EXPECTED[order_key][w.process_name]
            ok = (
                w.days == exp_days
                and w.source == exp_src
                and w.active_workers == exp_wk
                and w.avg_per_head == exp_cap
            )
            all_ok = all_ok and ok
            mark = "✔" if ok else "✘"
            print(f"  {mark} 实际: {_fmt(w)}")
            print(f"    预期: {exp_wk}人×{exp_cap}/人/天 | {exp_days}天 | {exp_src}")
        # 结构不变量：P3 完工不超交期；窗口先后不重叠
        last = windows[-1]
        assert last.end_date <= DELIVERY, f"{order_key} 完工超交期"
        for i in range(1, len(windows)):
            assert windows[i - 1].end_date < windows[i].start_date, f"{order_key} 工序窗口重叠"
        # 款级复杂度：A 针车 12 天 < B 针车 17 天
        if order_key == "X(A女鞋)":
            assert [w for w in windows if w.process_name == "P2针车"][0].days == 12
    # 工序级回退：C 新款 P2 = 125×6 → 7 天（非标准 4×300=12 天）
    assert all_ok
    assert EXPECTED["Z(C新款)"]["P2针车"][3] == 7
    assert EXPECTED["X(A女鞋)"]["P2针车"][3] < EXPECTED["Y(B运动鞋)"]["P2针车"][3]
    print("\n结论: 主场景预期与引擎结果" + ("完全一致 ✔" if all_ok else "存在偏差 ✘"))


def test_scenario_override(db, capsys):
    """覆盖场景：P2 current_workers=5 压过款级/工序级实测。"""
    session, tenant_id, proc_ids, _nc, product_ids = db
    print("\n" + "=" * 96)
    print("【覆盖场景】P2 针车 current_workers=5（加人赶工）")
    print("=" * 96)
    all_ok = True
    for order_key in ("X(A女鞋)", "Y(B运动鞋)", "Z(C新款)"):
        cap_map, windows = _run_order(
            session, tenant_id, proc_ids, product_ids, order_key=order_key, override=True
        )
        w2 = [w for w in windows if w.process_name == "P2针车"][0]
        exp_cap, exp_wk, exp_src, exp_days = EXPECTED_OVERRIDE["P2针车"]
        ok = (
            w2.days == exp_days
            and w2.source == exp_src
            and w2.active_workers == exp_wk
            and w2.avg_per_head == exp_cap
        )
        all_ok = all_ok and ok
        mark = "✔" if ok else "✘"
        print(f"  {mark} {order_key} P2针车 实际: {_fmt(w2)}")
        print(f"    预期: {exp_wk}人×{exp_cap}/人/天 | {exp_days}天 | {exp_src}（压过款级/工序级实测）")
    assert all_ok
    print("\n结论: 覆盖场景预期与引擎结果" + ("完全一致 ✔" if all_ok else "存在偏差 ✘"))


def test_scenario_unconfigured_raises(db):
    """未配置单人日产能：仍抛错（回归现状行为）。"""
    session, tenant_id, proc_ids, no_cap_id, _p = db
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = schedule_engine._process_capacity_map(session, tenant_id, cfg, as_of=AS_OF)
    with pytest.raises(ValueError, match="未配置单人日产能"):
        schedule_engine._calc_days(cap_map, no_cap_id, QTY)


def test_scenario_load_capacity(db):
    """负荷口径（工序级）：P2 日产能 = 实测 125×6=750；覆盖后 = 300×5=1500。"""
    session, tenant_id, proc_ids, _nc, _p = db
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    cap_map = schedule_engine._process_capacity_map(session, tenant_id, cfg, as_of=AS_OF)
    assert schedule_engine._daily_capacity(cap_map, proc_ids["P2针车"]) == Decimal("750")
    assert schedule_engine._daily_capacity(cap_map, proc_ids["P3成型"]) == Decimal("600")
    session.execute(
        __import__("sqlalchemy").update(ProcessDefinition)
        .where(ProcessDefinition.id == proc_ids["P2针车"])
        .values(current_workers=5)
    )
    session.commit()
    cap_map2 = schedule_engine._process_capacity_map(session, tenant_id, cfg, as_of=AS_OF)
    assert schedule_engine._daily_capacity(cap_map2, proc_ids["P2针车"]) == Decimal("1500")
