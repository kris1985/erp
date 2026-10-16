"""物料色卡单价、供应商变更历史。"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Employee,
    Partner,
    SupplierProduct,
    SupplierProductPriceHistory,
    SupplierProductSupplierHistory,
)

_PRICE_QUANT = Decimal("0.0001")


def catalog_approved(product) -> bool:
    return (getattr(product, "approval_status", None) or "approved") == "approved"


def unapproved_catalog_label(db: Session, tenant_id: int, product_ids) -> str | None:
    """未审批通过的色卡不能新选用。没有问题返回 None。"""
    ids: list[int] = []
    for raw in product_ids or []:
        if raw is None:
            continue
        try:
            num = int(raw)
        except (TypeError, ValueError):
            continue
        if num > 0 and num not in ids:
            ids.append(num)
    if not ids:
        return None
    rows = db.scalars(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.id.in_(ids),
        )
    ).all()
    pending = [row for row in rows if not catalog_approved(row)]
    if not pending:
        return None
    names = [((row.name or "").strip() or row.product_code) for row in pending[:3]]
    return f"「{'、'.join(names)}」尚未审批通过，不能使用"


def prices_equal(left, right) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return Decimal(str(left)).quantize(_PRICE_QUANT) == Decimal(str(right)).quantize(_PRICE_QUANT)


def record_catalog_price_change(
    db: Session,
    product: SupplierProduct,
    new_price,
    *,
    source: str,
    changed_by: int | None = None,
    purchase_order_id: int | None = None,
    po_no: str | None = None,
) -> bool:
    """单价有变化时写下历史并改色卡。没变化返回 False。"""
    if prices_equal(product.unit_price, new_price):
        return False
    stored = None if new_price is None else Decimal(str(new_price)).quantize(_PRICE_QUANT)
    db.add(
        SupplierProductPriceHistory(
            tenant_id=product.tenant_id,
            supplier_product_id=product.id,
            old_price=product.unit_price,
            new_price=stored,
            purchase_order_id=purchase_order_id,
            po_no=po_no,
            changed_by=changed_by,
            source=source,
        )
    )
    product.unit_price = stored
    return True


def price_history_product_ids(db: Session, tenant_id: int, product_ids: list[int]) -> set[int]:
    if not product_ids:
        return set()
    rows = db.scalars(
        select(SupplierProductPriceHistory.supplier_product_id)
        .where(
            SupplierProductPriceHistory.tenant_id == tenant_id,
            SupplierProductPriceHistory.supplier_product_id.in_(product_ids),
        )
        .distinct()
    ).all()
    return {int(item) for item in rows}


def _history_item(history, employee_name) -> dict:
    changed_at = history.changed_at.isoformat(sep=" ", timespec="minutes") if history.changed_at else None
    return {
        "id": history.id,
        "old_price": history.old_price,
        "new_price": history.new_price,
        "po_no": history.po_no,
        "source": history.source,
        "changed_by_name": employee_name,
        "changed_at": changed_at,
    }


def price_histories_for_products(db: Session, tenant_id: int, product_ids: list[int]) -> dict[int, list[dict]]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(SupplierProductPriceHistory, Employee.name)
        .outerjoin(Employee, Employee.id == SupplierProductPriceHistory.changed_by)
        .where(
            SupplierProductPriceHistory.tenant_id == tenant_id,
            SupplierProductPriceHistory.supplier_product_id.in_(product_ids),
        )
        .order_by(SupplierProductPriceHistory.id.desc())
    ).all()
    grouped: dict[int, list[dict]] = {}
    for history, employee_name in rows:
        grouped.setdefault(int(history.supplier_product_id), []).append(
            _history_item(history, employee_name)
        )
    return grouped


def list_catalog_price_history(db: Session, tenant_id: int, product_id: int) -> list[dict]:
    return price_histories_for_products(db, tenant_id, [product_id]).get(product_id, [])


def _partner_name(db: Session, tenant_id: int, partner_id: int | None) -> str | None:
    if not partner_id:
        return None
    partner = db.get(Partner, int(partner_id))
    if partner is None or partner.tenant_id != tenant_id:
        return None
    return (partner.name or "").strip() or None


def record_catalog_supplier_change(
    db: Session,
    product: SupplierProduct,
    new_partner_id,
    *,
    source: str,
    changed_by: int | None = None,
) -> bool:
    """供应商有变化时写下历史并改色卡。没变化返回 False。"""
    if not product.id or new_partner_id is None:
        return False
    new_id = int(new_partner_id)
    old_id = int(product.partner_id or 0)
    if new_id == old_id:
        return False
    db.add(
        SupplierProductSupplierHistory(
            tenant_id=product.tenant_id,
            supplier_product_id=product.id,
            old_partner_id=old_id or None,
            new_partner_id=new_id,
            old_partner_name=_partner_name(db, product.tenant_id, old_id),
            new_partner_name=_partner_name(db, product.tenant_id, new_id),
            changed_by=changed_by,
            source=source,
        )
    )
    product.partner_id = new_id
    return True


def supplier_histories_for_products(db: Session, tenant_id: int, product_ids: list[int]) -> dict[int, list[dict]]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(SupplierProductSupplierHistory, Employee.name)
        .outerjoin(Employee, Employee.id == SupplierProductSupplierHistory.changed_by)
        .where(
            SupplierProductSupplierHistory.tenant_id == tenant_id,
            SupplierProductSupplierHistory.supplier_product_id.in_(product_ids),
        )
        .order_by(SupplierProductSupplierHistory.id.desc())
    ).all()
    grouped: dict[int, list[dict]] = {}
    for history, employee_name in rows:
        changed_at = history.changed_at.isoformat(sep=" ", timespec="minutes") if history.changed_at else None
        grouped.setdefault(int(history.supplier_product_id), []).append(
            {
                "id": history.id,
                "old_partner_id": history.old_partner_id,
                "new_partner_id": history.new_partner_id,
                "old_partner_name": history.old_partner_name,
                "new_partner_name": history.new_partner_name,
                "source": history.source,
                "changed_by_name": employee_name,
                "changed_at": changed_at,
            }
        )
    return grouped
