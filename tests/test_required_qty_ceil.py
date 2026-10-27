"""用量 × 双数：需料量保留 2 位小数，不再向上取整。"""

from decimal import Decimal

from app.services.material_service import calc_required_qty, calc_required_qty_sized


def test_calc_required_qty_keeps_two_decimals():
    # 0.3 × 10 = 3
    assert calc_required_qty(Decimal("0.3"), 10, Decimal("0"), Decimal("0")) == Decimal("3.00")
    # 0.33 × 10 = 3.3，不再进到 4
    assert calc_required_qty(Decimal("0.33"), 10, Decimal("0"), Decimal("0")) == Decimal("3.30")
    # 整数用量不放大
    assert calc_required_qty(Decimal("2"), 50, Decimal("0"), Decimal("0")) == Decimal("100.00")
    # 1.005 → 1.01；1.004 → 1.00
    assert calc_required_qty(Decimal("1.005"), 1, Decimal("0"), Decimal("0")) == Decimal("1.01")
    assert calc_required_qty(Decimal("1.004"), 1, Decimal("0"), Decimal("0")) == Decimal("1.00")


def test_calc_required_qty_sized_keeps_two_decimals():
    # 0.25 × 10 × 1.1 = 2.75，不再进到 3
    assert calc_required_qty_sized(
        Decimal("0.25"), 10, Decimal("1.1"), Decimal("0"), Decimal("0")
    ) == Decimal("2.75")
