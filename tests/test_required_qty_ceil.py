"""用量 × 双数：需料量向上取整。"""

from decimal import Decimal

from app.services.material_service import calc_required_qty, calc_required_qty_sized


def test_calc_required_qty_ceils_fractional_usage_times_pairs():
    # 0.3 × 10 = 3 整
    assert calc_required_qty(Decimal("0.3"), 10, Decimal("0"), Decimal("0")) == Decimal("3")
    # 0.33 × 10 = 3.3 → 4
    assert calc_required_qty(Decimal("0.33"), 10, Decimal("0"), Decimal("0")) == Decimal("4")
    # 整数用量不放大
    assert calc_required_qty(Decimal("2"), 50, Decimal("0"), Decimal("0")) == Decimal("100")


def test_calc_required_qty_sized_ceils():
    # 0.25 × 10 × 1.1 = 2.75 → 3
    assert calc_required_qty_sized(
        Decimal("0.25"), 10, Decimal("1.1"), Decimal("0"), Decimal("0")
    ) == Decimal("3")
