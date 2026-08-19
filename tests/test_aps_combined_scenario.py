"""A'档联合验收场景：缺料齐套 + 急单插单 × 实测产能叠加。

验证三件事同时成立：
  1) 缺料单（O3 款 C，大底 T+10 到料）在任何方案下都不得早于 T+10 开工（等料闸门）；
  2) 实测产能贯穿插单仿真：急单 O4 与普通单同样按款级/工序级实测算天数；
  3) 插单三种策略（保交期/保现场/折中）的冲击行为与预期一致。

运行：pytest tests/test_aps_combined_scenario.py -s -v
"""

from datetime import date, datetime, timedelta, time
from decimal import Decimal
from math import ceil

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
    WorkLog,
)
from app.services import schedule_engine

AS_OF = date.today()
LOOKBACK = 7

# 工序与报工史与主验收场景一致
PROCS = {
    "P1裁断": (Decimal("400"), 2),
    "P2针车": (Decimal("300"), 4),
    "P3成型": (Decimal("200"), 3),
}
HISTORY = {
    ("A", "P1裁断"): ([1, 2], 350, 5),
    ("A", "P2针车"): ([1, 2, 3], 150, 5),
    ("B", "P1裁断"): ([3, 4], 320, 4),
    ("B", "P2针车"): ([4, 5, 6], 100, 5),
}

# 手工预期天数（5000 双 / 3000 双）
DAYS = {
    # (款, 工序) -> 预期天数
    ("A", "P1裁断"): ceil(5000 / (350 * 2)),   # 8
    ("A", "P2针车"): ceil(5000 / (150 * 3)),   # 12
    ("B", "P2针车"): ceil(5000 / (100 * 3)),   # 17
    ("C", "P1裁断"): ceil(5000 / (336.7 * 4)),  # 4（工序级回退）
    ("C", "P2针车"): ceil(5000 / (125 * 6)),   # 7（工序级回退）
    ("A", "P3成型"): ceil(5000 / (200 * 3)),   # 9（标准）
    ("RUSH-A", "P1裁断"): ceil(3000 / (350 * 2)),  # 5（急单同款级）
    ("RUSH-A", "P2针车"): ceil(3000 / (150 * 3)),  # 7
    ("RUSH-A", "P3成型"): ceil(3000 / (200 * 3)),  # 5
}


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
    tenant = Tenant(name="联合验收厂", settings_json={})
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))

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

    product_ids: dict[str, int] = {}
    for code in ("A", "B", "C"):
        p = OwnProduct(tenant_id=tenant.id, product_code=code, is_active=True)
        session.add(p)
        session.flush()
        product_ids[code] = p.id

    # 款 C 的 BOM：面料（大底），T+10 到料 → 缺料单
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-C",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("6"),
        is_active=True,
    )
    session.add(sp)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product_ids["C"],
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("6"),
            line_total=Decimal("6"),
            sort_order=0,
            consume_process_id=proc_ids["P1裁断"],
        )
    )
    session.flush()

    # 报工史
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
    yield session, tenant.id, proc_ids, product_ids, sp.id, partner.id
    session.close()


def _order(
    session,
    tenant_id,
    proc_ids,
    product_id,
    *,
    order_no: str,
    qty: int,
    delivery: date,
    rush: bool = False,
    eta_days: int | None = None,
    sp_id: int | None = None,
    partner_id: int | None = None,
) -> Order:
    size = session.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=delivery,
        status=OrderStatus.confirmed,
        is_rush=rush,
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(tenant_id=tenant_id, order_id=order.id, size_id=size.id, qty=qty, completed_qty=0)
    )
    for name, pid in proc_ids.items():
        session.add(
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=pid,
                process_name=name,
                process_type=ProcessType.personal,
                plan_qty=qty,
                status=OrderProcessStatus.pending,
            )
        )
    if eta_days is not None:
        po = PurchaseOrder(
            tenant_id=tenant_id,
            po_no=f"PO-{order_no}",
            partner_id=partner_id,
            status=PurchaseOrderStatus.ordered,
            expected_date=AS_OF + timedelta(days=eta_days),
            ordered_at=AS_OF,
        )
        session.add(po)
        session.flush()
        session.add(
            PurchaseOrderLine(
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                supplier_product_id=sp_id,
                qty=Decimal("3000"),  # 只到 3000，缺口 2000 → 仍缺料
                received_qty=Decimal("0"),
                unit_price=Decimal("6"),
            )
        )
    session.commit()
    return order


def _plan_by_order(variant: dict, order_id: int):
    return next((o for o in variant["orders"] if o.get("order_id") == order_id), None)


def _win(plan, pname: str):
    return next((w for w in plan["windows"] if w["process_name"] == pname), None)


def test_combined_kit_rush_actuals(db, capsys):
    session, tenant_id, proc_ids, product_ids, sp_id, partner_id = db

    # ---- 订单 ----
    o1 = _order(session, tenant_id, proc_ids, product_ids["A"], order_no="O1-女鞋", qty=5000, delivery=AS_OF + timedelta(days=30))
    o2 = _order(session, tenant_id, proc_ids, product_ids["B"], order_no="O2-运动鞋", qty=5000, delivery=AS_OF + timedelta(days=30))
    o3 = _order(
        session, tenant_id, proc_ids, product_ids["C"], order_no="O3-新款缺料", qty=5000,
        delivery=AS_OF + timedelta(days=30), eta_days=10, sp_id=sp_id, partner_id=partner_id,
    )
    o4 = _order(session, tenant_id, proc_ids, product_ids["A"], order_no="O4-急单", qty=3000, delivery=AS_OF + timedelta(days=25), rush=True)

    kit_ready = AS_OF + timedelta(days=10)

    variants = schedule_engine.simulate_insert(session, tenant_id, o4.id, as_of=AS_OF)
    assert [v["strategy"] for v in variants] == ["protect_delivery", "protect_floor", "compromise"]

    print("\n" + "=" * 100)
    print("【联合场景】缺料齐套(T+10) + 急单插单(O4) × 实测产能   as_of =", AS_OF)
    print("=" * 100)
    for v in variants:
        title = v["title"]
        o4_plan = _plan_by_order(v, o4.id)
        print(f"\n—— {title}（{v['strategy']}）——")
        for o in v["orders"]:
            label = {
                o1.id: "O1-女鞋5000", o2.id: "O2-运动鞋5000", o3.id: "O3-新款缺料5000", o4.id: "O4-急单3000",
            }.get(o["order_id"], str(o["order_id"]))
            bits = []
            for w in o["windows"]:
                eff = f"/{float(w['efficiency']) * 100:.0f}%" if w.get("efficiency") is not None else ""
                bits.append(
                    f"{w['process_name']}:{w['days']}天({w['start_date']}~{w['end_date']},"
                    f"{w['active_workers']}人×{w['avg_per_head']}{eff},{w['source']})"
                )
            notes = o.get("notes") or []
            print(f"  {label} 完工{o['projected_finish']} [{o['risk_label']}]")
            print(f"      {' | '.join(bits)}")
            if notes:
                print(f"      备注: {'；'.join(notes)}")

    # ---- 断言 1：等料闸门（三策略下 O3 首道都不得早于 T+10）----
    for v in variants:
        o3p = _plan_by_order(v, o3.id)
        assert o3p is not None
        first_start = date.fromisoformat(o3p["windows"][0]["start_date"])
        assert first_start >= kit_ready, (
            f"{v['strategy']} 下 O3 首道 {first_start} 早于齐套日 {kit_ready}"
        )
        assert any("等料" in n for n in (o3p.get("notes") or [])), v["strategy"]

    # ---- 断言 2：实测产能贯穿插单仿真 ----
    for v in variants:
        o4p = _plan_by_order(v, o4.id)
        assert _win(o4p, "P2针车")["days"] == DAYS[("RUSH-A", "P2针车")] == 7, "急单按款级实测排"
        assert _win(o4p, "P2针车")["source"] == "actual_product"
        o2p = _plan_by_order(v, o2.id)
        assert _win(o2p, "P2针车")["days"] == DAYS[("B", "P2针车")] == 17, "复杂度差异保持"
        o3p = _plan_by_order(v, o3.id)
        assert _win(o3p, "P2针车")["days"] == DAYS[("C", "P2针车")] == 7, "新款工序级回退"

    # ---- 断言 3：保交期 vs 保现场 ----
    pd = next(v for v in variants if v["strategy"] == "protect_delivery")
    pf = next(v for v in variants if v["strategy"] == "protect_floor")
    # 方案序列语义：保交期插单置顶、保现场插单置后
    pd_orders = [o["order_id"] for o in pd["orders"]]
    pf_orders = [o["order_id"] for o in pf["orders"]]
    assert pd_orders[0] == o4.id
    assert pf_orders[-1] == o4.id
    # 急单置顶 → 急单完工更早；置后 → 更晚
    o4_finish_pd = date.fromisoformat(_plan_by_order(pd, o4.id)["projected_finish"])
    o4_finish_pf = date.fromisoformat(_plan_by_order(pf, o4.id)["projected_finish"])
    assert o4_finish_pd < o4_finish_pf, (
        f"急单应保交期更早：{o4_finish_pd} vs 保现场 {o4_finish_pf}"
    )
    # 保现场把缺料单 O3 压到更晚（保现场优先普通单，牺牲等料单）
    o3_finish_pd = date.fromisoformat(_plan_by_order(pd, o3.id)["projected_finish"])
    o3_finish_pf = date.fromisoformat(_plan_by_order(pf, o3.id)["projected_finish"])
    assert o3_finish_pf >= o3_finish_pd, (
        f"保现场应把缺料单压后：pd {o3_finish_pd} vs pf {o3_finish_pf}"
    )
    # 引擎特性（如实记录）：simulate_insert 的日期级挤延不在此场景出现——
    #   delivery_first 锚定日期只标风险（allow_shift=False），
    #   capacity_first 插单置后不影响前单；
    # 真正的"日期级挤延"发生在急单确认落库（_apply_rush_impact_locked 移动已下发单窗口）。
    for v in variants:
        delays = [i for i in v["impacts"] if int(i.get("delay_days") or 0) > 0]
        print(f"  {v['strategy']} impact: {v['summary'].split('。')[1] if '。' in v['summary'] else v['summary']}")
        print(f"      日期级挤延 {len(delays)} 张：{[(i['order_no'], i['delay_days']) for i in delays]}")
    print(f"\n缺料单 O3 完工: 保交期 {o3_finish_pd} / 保现场 {o3_finish_pf}")
    print(f"急单 O4 完工:   保交期 {o4_finish_pd} / 保现场 {o4_finish_pf}")

    print("\n结论: 联合场景（缺料齐套 × 急单插单 × 实测产能）预期全部成立 ✔")
