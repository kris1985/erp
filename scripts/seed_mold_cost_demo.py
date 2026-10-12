"""给模具成本分析补一组演示数据：同一楦下两套鞋底/鞋跟，刀模编号等于工厂型号。

幂等：已有同编号的产品、到货单、出货单会跳过。
用法：
  .venv/bin/python scripts/seed_mold_cost_demo.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.db_schema import ensure_schema
from app.models import (
    Department,
    Order,
    OrderStatus,
    OwnProduct,
    Partner,
    Shipment,
    ShipmentStatus,
    Size,
    SupplierProduct,
    Tenant,
    ToolingLedger,
    ToolingReceipt,
    ToolingReceiptLine,
    ToolingStock,
)
from app.services.mold_cost_service import mold_cost_report
from app.services.tooling_service import receive

MARKER = "【模具成本演示】"

# 楦 x123 覆盖全部出货；d123a/g123a 覆盖前三款（2000 双），d123b/g123b 覆盖后三款（2450 双）。
UPPERS = (
    ("45677", "d123a", "g123a", 1000, Decimal("100")),
    ("345635", "d123a", "g123a", 700, Decimal("110")),
    ("57856", "d123a", "g123a", 300, Decimal("100")),
    ("67", "d123b", "g123b", 900, Decimal("100")),
    ("46746", "d123b", "g123b", 800, Decimal("100")),
    ("46748", "d123b", "g123b", 750, Decimal("100")),
)


def _tenant(db) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.name == "演示鞋厂"))
    if tenant is None:
        tenant = db.scalar(select(Tenant).order_by(Tenant.id))
    if tenant is None:
        raise SystemExit("没有租户，先启动一次服务")
    return tenant


def _dept(db, tenant_id: int, name: str) -> Department:
    dept = db.scalar(
        select(Department).where(
            Department.tenant_id == tenant_id,
            Department.parent_id.is_(None),
            Department.name == name,
        )
    )
    if dept is None:
        raise SystemExit(f"没有一级部门 {name}")
    return dept


def _supplier(db, tenant_id: int) -> Partner:
    partner = db.scalar(
        select(Partner).where(
            Partner.tenant_id == tenant_id,
            Partner.is_supplier.is_(True),
            Partner.is_active.is_(True),
        )
    )
    if partner is None:
        raise SystemExit("没有供应商")
    return partner


def _size(db, tenant_id: int) -> Size:
    size = db.scalar(select(Size).where(Size.tenant_id == tenant_id, Size.is_active.is_(True)))
    if size is None:
        raise SystemExit("没有尺码")
    return size


def _heel_card(db, tenant_id: int, supplier_id: int, code: str) -> SupplierProduct:
    card = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.product_code == code,
        )
    )
    if card:
        return card
    card = SupplierProduct(
        tenant_id=tenant_id,
        product_code=code,
        name=f"鞋跟{code}",
        partner_id=supplier_id,
        is_active=True,
    )
    db.add(card)
    db.flush()
    return card


def _ensure_product(db, tenant_id: int, code: str, last: str, sole: str, heel_id: int) -> OwnProduct:
    product = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == code)
    )
    if product is None:
        product = OwnProduct(
            tenant_id=tenant_id,
            product_code=code,
            product_year=2026,
            season="AU",
            shoe_last=last,
            sole_mold=sole,
            heel_model_id=heel_id,
            is_active=True,
        )
        db.add(product)
        db.flush()
        return product
    product.shoe_last = last
    product.sole_mold = sole
    product.heel_model_id = heel_id
    return product


def _ensure_shipment(db, tenant_id: int, product: OwnProduct, qty: int) -> None:
    shipment_no = f"MC-{product.product_code}"
    if db.scalar(
        select(Shipment.id).where(Shipment.tenant_id == tenant_id, Shipment.shipment_no == shipment_no)
    ):
        return
    order = Order(
        tenant_id=tenant_id,
        order_no=f"MC-{product.product_code}",
        customer_name="模具演示客户",
        own_product_id=product.id,
        total_qty=qty,
        status=OrderStatus.completed,
        notes=MARKER,
    )
    db.add(order)
    db.flush()
    db.add(
        Shipment(
            tenant_id=tenant_id,
            shipment_no=shipment_no,
            order_id=order.id,
            customer_name="模具演示客户",
            status=ShipmentStatus.shipped,
            ship_date=date(2026, 10, 8),
            total_qty=qty,
            amount=Decimal("0"),
            notes=MARKER,
        )
    )


def _move_demo_receipts_to_production(db, tenant_id: int, prod_id: int) -> None:
    """早先演示到货记在开发部，改挂到生产部，库存跟着走。"""
    receipts = list(
        db.scalars(
            select(ToolingReceipt).where(
                ToolingReceipt.tenant_id == tenant_id,
                ToolingReceipt.notes.like(f"{MARKER}%"),
            )
        ).all()
    )
    for receipt in receipts:
        lines = list(
            db.scalars(
                select(ToolingReceiptLine).where(ToolingReceiptLine.receipt_id == receipt.id)
            ).all()
        )
        for line in lines:
            old_id = line.department_id
            if old_id == prod_id:
                continue
            line.department_id = prod_id
            sizes = list(line.sizes or [])
            for size_row in sizes:
                if old_id is None:
                    continue
                source = db.scalar(
                    select(ToolingStock).where(
                        ToolingStock.tooling_item_id == line.tooling_item_id,
                        ToolingStock.department_id == old_id,
                        ToolingStock.size_id == size_row.size_id,
                    )
                )
                if source is not None:
                    source.qty = Decimal(str(source.qty or 0)) - Decimal(str(size_row.qty or 0))
                    if source.qty <= 0:
                        db.delete(source)
                target = db.scalar(
                    select(ToolingStock).where(
                        ToolingStock.tooling_item_id == line.tooling_item_id,
                        ToolingStock.department_id == prod_id,
                        ToolingStock.size_id == size_row.size_id,
                    )
                )
                if target is None:
                    db.add(
                        ToolingStock(
                            tenant_id=tenant_id,
                            tooling_item_id=line.tooling_item_id,
                            department_id=prod_id,
                            size_id=size_row.size_id,
                            qty=Decimal(str(size_row.qty or 0)),
                        )
                    )
                else:
                    target.qty = Decimal(str(target.qty or 0)) + Decimal(str(size_row.qty or 0))
        ledgers = list(
            db.scalars(
                select(ToolingLedger).where(
                    ToolingLedger.tenant_id == tenant_id,
                    ToolingLedger.source_type == "receive",
                    ToolingLedger.source_ref_id == receipt.id,
                )
            ).all()
        )
        for ledger in ledgers:
            ledger.department_id = prod_id
    db.commit()


def _ensure_receipt(db, tenant_id: int, supplier_id: int, dept_id: int, size_id: int, kind: str, lines: list[dict]) -> None:
    note = f"{MARKER}{kind}"
    if db.scalar(
        select(ToolingReceipt.id).where(ToolingReceipt.tenant_id == tenant_id, ToolingReceipt.notes == note)
    ):
        return
    receive(
        db,
        tenant_id,
        kind=kind,
        supplier_id=supplier_id,
        receipt_date=date(2026, 10, 1),
        delivery_note_no=None,
        notes=note,
        lines=[
            {
                "code": line["code"],
                "department_id": dept_id,
                "unit_price": line["price"],
                "sizes": [(size_id, line["qty"])],
            }
            for line in lines
        ],
        user_id=None,
    )


def main() -> None:
    ensure_schema()
    db = SessionLocal()
    try:
        tenant = _tenant(db)
        prod = _dept(db, tenant.id, "生产部")
        _move_demo_receipts_to_production(db, tenant.id, prod.id)
        supplier = _supplier(db, tenant.id)
        size = _size(db, tenant.id)
        heels = {
            code: _heel_card(db, tenant.id, supplier.id, code).id
            for code in ("g123a", "g123b")
        }
        products = []
        for code, sole, heel, shipped, knife_price in UPPERS:
            product = _ensure_product(db, tenant.id, code, "x123", sole, heels[heel])
            _ensure_shipment(db, tenant.id, product, shipped)
            products.append((product, knife_price))
        db.commit()

        _ensure_receipt(
            db,
            tenant.id,
            supplier.id,
            prod.id,
            size.id,
            "shoe_last",
            [{"code": "x123", "price": Decimal("30"), "qty": 500}],
        )
        _ensure_receipt(
            db,
            tenant.id,
            supplier.id,
            prod.id,
            size.id,
            "sole_mold",
            [
                {"code": "d123a", "price": Decimal("5000"), "qty": 6},
                {"code": "d123b", "price": Decimal("5500"), "qty": 6},
            ],
        )
        _ensure_receipt(
            db,
            tenant.id,
            supplier.id,
            prod.id,
            size.id,
            "heel_mold",
            [
                {"code": "g123a", "price": Decimal("300"), "qty": 6},
                {"code": "g123b", "price": Decimal("350"), "qty": 6},
            ],
        )
        _ensure_receipt(
            db,
            tenant.id,
            supplier.id,
            prod.id,
            size.id,
            "knife_die",
            [
                {"code": product.product_code, "price": price, "qty": 6}
                for product, price in products
            ],
        )
        report = mold_cost_report(db, tenant.id)
        demo_codes = {code for code, *_rest in UPPERS}
        demo_rows = [row for row in report["rows"] if row["factory_model"] in demo_codes]
        print(f"模具成本分析演示行 {len(demo_rows)} 条")
        for row in demo_rows:
            print(
                f"  {row['factory_model']} 楦{row['last_code']} {row['last_share']} "
                f"底{row['sole_code']} {row['sole_share']} 跟{row['heel_code']} {row['heel_share']} "
                f"刀{row['knife_share']} 出货{row['shipped_qty']}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
