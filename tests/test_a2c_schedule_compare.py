"""A2c 排产方案对比卡：验证 generate_proposals 的 risks/load 字段足以在
前端算出「延期单数 / 负荷峰」两个对比指标，且不同策略下数字确实不同。"""

from datetime import date, timedelta

from app.services import schedule_engine, schedule_settings

from tests.test_schedule_engine import _order, db  # noqa: F401  (复用现有 fixture/helper)


def test_a2c_compare_card_fields(db, capsys):
    session, tenant_id, product_id, ct_id, cx_id = db
    schedule_settings.save_schedule_patch(
        session, tenant_id, {"daily_capacity_by_process": {str(ct_id): 20, str(cx_id): 20}}
    )
    delivery_soon = date.today() + timedelta(days=3)
    delivery_far = date.today() + timedelta(days=60)
    _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-RUSH", qty=400, delivery=delivery_soon, rush=True)
    _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-NORM", qty=200, delivery=delivery_far)

    props = schedule_engine.generate_proposals(session, tenant_id)
    assert len(props) >= 2

    def headline(p):
        risks = p.get("risks") or {}
        late_count = (risks.get("late", 0) or 0) + (risks.get("capacity_blocked", 0) or 0)
        load = p.get("load") or []
        peak = None
        over_days = 0
        for row in load:
            if row.get("over_capacity"):
                over_days += 1
            u = row.get("utilization")
            if u is None:
                continue
            if peak is None or u > peak["utilization"]:
                peak = row
        return {
            "strategy": p["strategy"],
            "title": p["title"],
            "late_count": late_count,
            "peak_util_pct": round(peak["utilization"] * 100) if peak else None,
            "peak_process": peak.get("process_name") if peak else None,
            "peak_date": peak.get("date") if peak else None,
            "over_days": over_days,
        }

    headlines = [headline(p) for p in props]
    with capsys.disabled():
        print("\n=== A2c 排产方案对比卡 · 走查证据 ===")
        for h in headlines:
            print(
                f"[{h['title']}({h['strategy']})] 延期单数={h['late_count']} "
                f"负荷峰={h['peak_util_pct']}% @ {h['peak_process']} {h['peak_date']} "
                f"超产能天数={h['over_days']}"
            )

    # 两套方案至少能算出负荷峰，证明前端「compare card」有真实数据可对比。
    assert any(h["peak_util_pct"] is not None for h in headlines)
    by_strategy = {h["strategy"]: h for h in headlines}
    # 保交期：置顶硬排，产能超限只标红不顺延 → 应出现明显负荷峰。
    assert by_strategy["delivery_first"]["peak_util_pct"] is not None
    assert by_strategy["delivery_first"]["over_days"] > 0
    # 保现场：顺延避冲突 → 不应再出现超产能天数（用交期换负荷）。
    assert by_strategy["capacity_first"]["over_days"] == 0
