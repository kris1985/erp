"""模具成本分析。

楦、鞋底模具来自产品开发上的编号，鞋跟模具来自产品上的鞋跟型号。
刀模编号与工厂型号相同。数量和金额只取生产部的模具到货，开发部不计。
楦、鞋底、鞋跟、刀模至少有一项金额才列入，只填了编号但没有金额的型号不出现。
分摊 = 金额 / 该组合并单元格覆盖的出货数量。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Department,
    OwnProduct,
    SupplierProduct,
    ToolingItem,
    ToolingReceiptLine,
    ToolingReceiptSize,
)
from app.services.salary_service import shipped_qty_by_product

KIND_LAST = "shoe_last"
KIND_SOLE = "sole_mold"
KIND_KNIFE = "knife_die"
HEEL_KINDS = ("heel_mold", "other_mold")
_CENT = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _num(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    amount = _q2(value)
    if amount == 0:
        return None
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount)


def _unit_cost(amount: Decimal | None, shipped_qty: int) -> Decimal:
    """分摊单价：金额 / 该组合并覆盖的出货双数，四舍五入到分。"""
    if amount is None or shipped_qty <= 0:
        return Decimal("0.00")
    money = _q2(amount)
    if money == 0:
        return Decimal("0.00")
    return (money / Decimal(shipped_qty)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _share_text(amount: Decimal | None, shipped_qty: int) -> str | None:
    unit = _unit_cost(amount, shipped_qty)
    if unit == 0:
        return None
    text = format(unit, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}元/双"


def _production_department_ids(db: Session, tenant_id: int) -> set[int]:
    """使用部门本身或它的一级部门名称带「生产」才计入。开发部排除。"""
    rows = list(db.scalars(select(Department).where(Department.tenant_id == tenant_id)).all())
    by_id = {row.id: row for row in rows}

    def root_name(dept: Department) -> str:
        seen: set[int] = set()
        current = dept
        while current.parent_id and current.parent_id in by_id and current.id not in seen:
            seen.add(current.id)
            current = by_id[current.parent_id]
        return current.name or ""

    return {row.id for row in rows if "生产" in root_name(row)}


def _tooling_totals(db: Session, tenant_id: int) -> dict[tuple[str, str], tuple[Decimal, Decimal]]:
    """(kind, code) -> (数量, 金额)。只汇总生产部到货，金额 = 数量 × 单价。"""
    department_ids = _production_department_ids(db, tenant_id)
    if not department_ids:
        return {}
    rows = db.execute(
        select(
            ToolingItem.kind,
            ToolingItem.code,
            ToolingReceiptLine.unit_price,
            func.coalesce(func.sum(ToolingReceiptSize.qty), 0),
        )
        .join(ToolingReceiptLine, ToolingReceiptLine.tooling_item_id == ToolingItem.id)
        .join(ToolingReceiptSize, ToolingReceiptSize.line_id == ToolingReceiptLine.id)
        .where(
            ToolingItem.tenant_id == tenant_id,
            ToolingReceiptLine.tenant_id == tenant_id,
            ToolingReceiptLine.department_id.in_(department_ids),
        )
        .group_by(ToolingReceiptLine.id, ToolingItem.kind, ToolingItem.code, ToolingReceiptLine.unit_price)
    ).all()
    totals: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for kind, code, price, qty in rows:
        key = (str(kind), str(code or "").strip())
        if not key[1]:
            continue
        prev_qty, prev_amt = totals.get(key, (Decimal("0"), Decimal("0")))
        line_qty = Decimal(str(qty or 0))
        totals[key] = (prev_qty + line_qty, prev_amt + line_qty * Decimal(str(price or 0)))
    return totals


def _cost(totals: dict[tuple[str, str], tuple[Decimal, Decimal]], kind: str, code: str | None):
    text = (code or "").strip()
    if not text:
        return None, None
    qty, amount = totals.get((kind, text), (Decimal("0"), Decimal("0")))
    if qty == 0 and amount == 0:
        return None, None
    return qty, amount


def _heel_cost(totals, codes: list[str]):
    qty = Decimal("0")
    amount = Decimal("0")
    found = False
    for code in codes:
        for kind in HEEL_KINDS:
            line_qty, line_amt = totals.get((kind, code), (Decimal("0"), Decimal("0")))
            if line_qty == 0 and line_amt == 0:
                continue
            qty += line_qty
            amount += line_amt
            found = True
            break
    if not found:
        return None, None
    return qty, amount


def _draft_rows(db: Session, tenant_id: int) -> list[dict]:
    products = list(
        db.scalars(
            select(OwnProduct)
            .where(OwnProduct.tenant_id == tenant_id)
            .order_by(OwnProduct.product_code, OwnProduct.id)
        ).all()
    )
    card_ids = {
        cid
        for product in products
        for cid in (product.heel_model_id, product.heel_model_2_id)
        if cid
    }
    cards = {}
    if card_ids:
        cards = {
            row.id: (row.product_code or "").strip()
            for row in db.scalars(
                select(SupplierProduct).where(
                    SupplierProduct.tenant_id == tenant_id,
                    SupplierProduct.id.in_(card_ids),
                )
            ).all()
        }
    shipped = shipped_qty_by_product(
        db, tenant_id, date_from=date(2000, 1, 1), date_to=date(2100, 12, 31)
    )
    totals = _tooling_totals(db, tenant_id)

    drafted: list[dict] = []
    for product in products:
        last_code = (product.shoe_last or "").strip()
        sole_code = (product.sole_mold or "").strip()
        heel_codes = []
        for cid in (product.heel_model_id, product.heel_model_2_id):
            code = cards.get(cid) if cid else ""
            if code and code not in heel_codes:
                heel_codes.append(code)
        heel_code = " / ".join(heel_codes)
        knife_code = (product.product_code or "").strip()
        last_qty, last_amt = _cost(totals, KIND_LAST, last_code)
        sole_qty, sole_amt = _cost(totals, KIND_SOLE, sole_code)
        heel_qty, heel_amt = _heel_cost(totals, heel_codes)
        knife_qty, knife_amt = _cost(totals, KIND_KNIFE, knife_code)
        shipped_qty = int(shipped.get(product.id) or 0)
        if not any([last_amt, sole_amt, heel_amt, knife_amt]):
            continue
        identity = f"p{product.id}"
        drafted.append(
            {
                "product_id": product.id,
                "last_code": last_code or None,
                "last_qty": last_qty,
                "last_amount": last_amt,
                "last_key": last_code or identity,
                "sole_code": sole_code or None,
                "sole_qty": sole_qty,
                "sole_amount": sole_amt,
                "sole_key": f"{last_code or identity}|{sole_code or identity}",
                "heel_code": heel_code or None,
                "heel_qty": heel_qty,
                "heel_amount": heel_amt,
                "heel_key": f"{last_code or identity}|{sole_code or identity}|{heel_code or identity}",
                "knife_code": knife_code or None,
                "knife_qty": knife_qty,
                "knife_amount": knife_amt,
                "factory_model": knife_code or None,
                "shipped_qty": shipped_qty,
            }
        )

    drafted.sort(
        key=lambda row: (
            row["last_code"] or "\uffff",
            row["sole_code"] or "\uffff",
            row["heel_code"] or "\uffff",
            row["factory_model"] or "",
            row["product_id"],
        )
    )
    return drafted


def mold_cost_report(db: Session, tenant_id: int) -> dict:
    drafted = _draft_rows(db, tenant_id)

    def _fill_share(key_name: str, amount_name: str, share_name: str) -> None:
        index = 0
        while index < len(drafted):
            key = drafted[index][key_name]
            end = index + 1
            while end < len(drafted) and drafted[end][key_name] == key:
                end += 1
            amount = drafted[index][amount_name]
            covered = sum(int(row["shipped_qty"] or 0) for row in drafted[index:end])
            share = _share_text(amount, covered)
            for row in drafted[index:end]:
                row[share_name] = share
            index = end

    _fill_share("last_key", "last_amount", "last_share")
    _fill_share("sole_key", "sole_amount", "sole_share")
    _fill_share("heel_key", "heel_amount", "heel_share")
    for row in drafted:
        row["knife_share"] = _share_text(row["knife_amount"], int(row["shipped_qty"] or 0))
        row["last_qty"] = _num(row["last_qty"])
        row["last_amount"] = _num(row["last_amount"])
        row["sole_qty"] = _num(row["sole_qty"])
        row["sole_amount"] = _num(row["sole_amount"])
        row["heel_qty"] = _num(row["heel_qty"])
        row["heel_amount"] = _num(row["heel_amount"])
        row["knife_qty"] = _num(row["knife_qty"])
        row["knife_amount"] = _num(row["knife_amount"])

    rows = [{key: value for key, value in row.items() if key != "product_id"} for row in drafted]
    return {"rows": rows}


def mold_unit_costs_by_product(db: Session, tenant_id: int) -> dict[int, dict[str, Decimal]]:
    """每个产品的模具分摊单价（元/双）：楦头、鞋底、鞋跟、刀模。

    单价与模具成本分析的「分摊」相同。订单金额 = 单价 × 该单出货数量。
    """
    drafted = _draft_rows(db, tenant_id)

    def grouped(key_name: str, amount_name: str) -> dict[int, Decimal]:
        units: dict[int, Decimal] = {}
        index = 0
        while index < len(drafted):
            key = drafted[index][key_name]
            end = index + 1
            while end < len(drafted) and drafted[end][key_name] == key:
                end += 1
            covered = sum(int(row["shipped_qty"] or 0) for row in drafted[index:end])
            unit = _unit_cost(drafted[index][amount_name], covered)
            for row in drafted[index:end]:
                units[int(row["product_id"])] = unit
            index = end
        return units

    last_units = grouped("last_key", "last_amount")
    sole_units = grouped("sole_key", "sole_amount")
    heel_units = grouped("heel_key", "heel_amount")
    result: dict[int, dict[str, Decimal]] = {}
    for row in drafted:
        product_id = int(row["product_id"])
        result[product_id] = {
            "last": last_units.get(product_id, Decimal("0.00")),
            "sole": sole_units.get(product_id, Decimal("0.00")),
            "heel": heel_units.get(product_id, Decimal("0.00")),
            "knife": _unit_cost(row["knife_amount"], int(row["shipped_qty"] or 0)),
        }
    return result
