"""采购单：按供应商拆单、合并多订单行、到货回写。"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    ExecutionHeader,
    MaterialIqcRecord,
    MaterialIqcStatus,
    Order,
    OrderMaterialRequirement,
    Partner,
    PartnerContact,
    PricingUnit,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderLine,
    SharedLedgerType,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services.material_service import (
    MaterialError,
    adjust_shared_stock,
    is_tooling_supplier_product,
    list_shortages,
    ordered_qty_for_requirement,
)
from app.services.supplier_product_price import catalog_approved, record_catalog_price_change

# 未到齐且未取消时，用于交期告警
_OPEN_DELIVERY_STATUSES = {
    PurchaseOrderStatus.ordered,
    PurchaseOrderStatus.shipped,
    PurchaseOrderStatus.partial_received,
}

_PO_UNSET = object()


class PurchaseError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def generate_po_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = f"PO{today}"
    n = db.scalar(
        select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.po_no.like(f"{prefix}%"),
        )
    )
    return f"{prefix}{(n or 0) + 1:03d}"


def last_purchase_price(db: Session, tenant_id: int, supplier_product_id: int) -> Decimal | None:
    line = db.scalar(
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrderLine.supplier_product_id == supplier_product_id,
            PurchaseOrder.status.in_(
                [
                    PurchaseOrderStatus.ordered,
                    PurchaseOrderStatus.shipped,
                    PurchaseOrderStatus.partial_received,
                    PurchaseOrderStatus.received,
                ]
            ),
        )
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrderLine.id.desc())
        .limit(1)
    )
    return line.unit_price if line else None


def _delivery_alert(po: PurchaseOrder) -> dict:
    """交期告警：overdue 逾期未到 / due_soon 即将到期（2天内）/ none。"""
    status = po.status if isinstance(po.status, PurchaseOrderStatus) else PurchaseOrderStatus(po.status)
    if status not in _OPEN_DELIVERY_STATUSES or not po.expected_date:
        return {
            "delivery_alert": "none",
            "delivery_alert_label": None,
            "overdue_days": 0,
            "days_to_expected": None,
        }
    today = date.today()
    delta = (po.expected_date - today).days
    if delta < 0:
        return {
            "delivery_alert": "overdue",
            "delivery_alert_label": f"逾期未到 {abs(delta)} 天",
            "overdue_days": abs(delta),
            "days_to_expected": delta,
        }
    if delta <= 2:
        label = "今日应到" if delta == 0 else f"{delta} 天后到期"
        return {
            "delivery_alert": "due_soon",
            "delivery_alert_label": label,
            "overdue_days": 0,
            "days_to_expected": delta,
        }
    return {
        "delivery_alert": "none",
        "delivery_alert_label": None,
        "overdue_days": 0,
        "days_to_expected": delta,
    }


def _build_summary_lines(lines_out: list[dict]) -> list[dict]:
    """按物料汇总：对外下单看合计数量与单价，对内仍保留分订单行。"""
    by_sp: dict[int, dict] = {}
    for ln in lines_out:
        sp_id = ln["supplier_product_id"]
        bucket = by_sp.get(sp_id)
        if not bucket:
            bucket = {
                "supplier_product_id": sp_id,
                "supplier_product_code": ln.get("supplier_product_code"),
                "supplier_product_name": ln.get("supplier_product_name"),
                "image_url": ln.get("image_url"),
                "color_name": ln.get("color_name"),
                "pricing_unit_name": ln.get("pricing_unit_name"),
                "qty": Decimal("0"),
                "loss_qty": Decimal("0"),
                "received_qty": Decimal("0"),
                "pending_iqc_qty": Decimal("0"),
                "open_qty": Decimal("0"),
                "unit_price": ln.get("unit_price") or Decimal("0"),
                "last_purchase_price": ln.get("last_purchase_price"),
                "catalog_price": ln.get("catalog_price"),
                "line_ids": [],
                "allocations": [],
                "price_mixed": False,
            }
            by_sp[sp_id] = bucket
        bucket["qty"] += Decimal(str(ln.get("qty") or 0))
        bucket["loss_qty"] += Decimal(str(ln.get("loss_qty") or 0))
        bucket["received_qty"] += Decimal(str(ln.get("received_qty") or 0))
        bucket["pending_iqc_qty"] += Decimal(str(ln.get("pending_iqc_qty") or 0))
        bucket["open_qty"] += Decimal(str(ln.get("open_qty") or 0))
        bucket["line_ids"].append(ln["id"])
        price = Decimal(str(ln.get("unit_price") or 0))
        if price != Decimal(str(bucket["unit_price"] or 0)):
            bucket["price_mixed"] = True
        bucket["allocations"].append(
            {
                "line_id": ln["id"],
                "order_id": ln.get("order_id"),
                "order_no": ln.get("order_no"),
                "header_id": ln.get("header_id"),
                "header_no": ln.get("header_no"),
                "sales_order_id": ln.get("sales_order_id"),
                "sales_order_no": ln.get("sales_order_no"),
                "qty": ln.get("qty"),
                "received_qty": ln.get("received_qty"),
                "pending_iqc_qty": ln.get("pending_iqc_qty"),
                "open_qty": ln.get("open_qty"),
                "unit_price": ln.get("unit_price"),
            }
        )
    summary = list(by_sp.values())
    summary.sort(key=lambda x: (x.get("supplier_product_code") or "", x["supplier_product_id"]))
    for row in summary:
        row["amount"] = (Decimal(str(row["qty"])) * Decimal(str(row["unit_price"] or 0))).quantize(
            Decimal("0.01")
        )
    return summary


def _primary_partner_contact(db: Session, tenant_id: int, partner_id: int) -> PartnerContact | None:
    return db.scalar(
        select(PartnerContact)
        .where(
            PartnerContact.tenant_id == tenant_id,
            PartnerContact.partner_id == partner_id,
            PartnerContact.is_active.is_(True),
        )
        .order_by(PartnerContact.is_primary.desc(), PartnerContact.sort_order, PartnerContact.id)
        .limit(1)
    )


def _po_out(db: Session, po: PurchaseOrder) -> dict:
    from app.models import Size
    from app.services.inventory_settings import get_inventory_for_tenant

    partner = db.get(Partner, po.partner_id)
    tenant = db.get(Tenant, po.tenant_id)
    inventory = get_inventory_for_tenant(tenant)
    contact = _primary_partner_contact(db, po.tenant_id, po.partner_id) if partner else None
    lines_out = []
    line_ids = [ln.id for ln in po.lines]
    pending_iqc_map = {
        int(line_id): Decimal(str(qty or 0))
        for line_id, qty in db.execute(
            select(
                MaterialIqcRecord.purchase_order_line_id,
                func.coalesce(func.sum(MaterialIqcRecord.qty), 0),
            )
            .where(
                MaterialIqcRecord.tenant_id == po.tenant_id,
                MaterialIqcRecord.purchase_order_line_id.in_(line_ids or [-1]),
                MaterialIqcRecord.status == MaterialIqcStatus.pending,
            )
            .group_by(MaterialIqcRecord.purchase_order_line_id)
        ).all()
    }
    size_ids = {getattr(ln, "size_id", None) for ln in po.lines if getattr(ln, "size_id", None)}
    size_by_id = {
        s.id: s
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids or [-1]))).all()
    } if size_ids else {}
    for ln in po.lines:
        sp = db.get(SupplierProduct, ln.supplier_product_id)
        order = db.get(Order, ln.order_id) if ln.order_id else None
        requirement = (
            db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
            if ln.order_material_requirement_id
            else None
        )
        header_id = requirement.header_id if requirement and requirement.header_id else None
        sales_line = (
            db.get(SalesOrderLine, ln.sales_order_line_id)
            if getattr(ln, "sales_order_line_id", None)
            else None
        )
        if not header_id and sales_line and sales_line.execution_header_id:
            header_id = sales_line.execution_header_id
        header = db.get(ExecutionHeader, header_id) if header_id else None
        sales_order_id = getattr(ln, "sales_order_id", None) or (
            header.sales_order_id if header else None
        )
        sales_order = db.get(SalesOrder, sales_order_id) if sales_order_id else None
        last = last_purchase_price(db, po.tenant_id, ln.supplier_product_id)
        unit = db.get(PricingUnit, sp.pricing_unit_id) if sp and sp.pricing_unit_id else None
        color = db.get(Color, sp.color_id) if sp and sp.color_id else None
        size_id = getattr(ln, "size_id", None)
        size = size_by_id.get(size_id) if size_id else None
        pending_iqc_qty = pending_iqc_map.get(ln.id, Decimal("0"))
        open_qty = max(
            Decimal("0"),
            ln.qty - (ln.received_qty or Decimal("0")) - pending_iqc_qty,
        )
        lines_out.append(
            {
                "id": ln.id,
                "supplier_product_id": ln.supplier_product_id,
                "supplier_product_code": sp.product_code if sp else None,
                "supplier_product_name": sp.name if sp else None,
                "image_url": sp.image_url if sp else None,
                "color_id": sp.color_id if sp else None,
                "color_name": color.name if color else None,
                "pricing_unit_id": sp.pricing_unit_id if sp else None,
                "pricing_unit_name": unit.name if unit else None,
                "order_id": ln.order_id,
                "order_no": header.header_no if header else (order.order_no if order else None),
                "is_rush": bool(
                    getattr(header, "is_rush", False) or getattr(order, "is_rush", False)
                ),
                "delivery_date": (
                    header.delivery_date if header and header.delivery_date else (
                        order.delivery_date if order else None
                    )
                ),
                "suggested_arrival_date": (
                    header.delivery_date if header and header.delivery_date else None
                ),
                "header_id": header.id if header else None,
                "header_no": header.header_no if header else None,
                "order_material_requirement_id": ln.order_material_requirement_id,
                "sales_order_id": sales_order_id,
                "sales_order_no": sales_order.order_no if sales_order else None,
                "sales_order_line_id": getattr(ln, "sales_order_line_id", None),
                "qty": ln.qty,
                "loss_qty": getattr(ln, "loss_qty", None) or Decimal("0"),
                "unit_price": ln.unit_price,
                "received_qty": ln.received_qty,
                "pending_iqc_qty": pending_iqc_qty,
                "open_qty": open_qty,
                "size_id": size_id,
                "size_value": size.size_value if size else None,
                "size_sort_order": size.sort_order if size else None,
                "last_purchase_price": last,
                "catalog_price": sp.unit_price if sp else None,
            }
        )
    summary_lines = _build_summary_lines(lines_out)
    suggested_dates = sorted(
        {
            ln["suggested_arrival_date"].isoformat()
            for ln in lines_out
            if ln.get("suggested_arrival_date")
        }
    )
    total_qty = sum((Decimal(str(x["qty"])) for x in summary_lines), Decimal("0"))
    total_amount = sum((Decimal(str(x["amount"])) for x in summary_lines), Decimal("0"))
    alert = _delivery_alert(po)
    status = po.status.value if hasattr(po.status, "value") else po.status
    return {
        "id": po.id,
        "po_no": po.po_no,
        "partner_id": po.partner_id,
        "partner_name": partner.name if partner else None,
        "partner_address": partner.address if partner else None,
        "partner_contact_name": contact.name if contact else None,
        "partner_contact_mobile": contact.mobile if contact else None,
        "buyer_name": tenant.name if tenant else None,
        "buyer_contact_person": tenant.contact_person if tenant else None,
        "buyer_contact_mobile": tenant.contact_mobile if tenant else None,
        "buyer_address": tenant.address if tenant else None,
        "status": status,
        "approval_status": getattr(po, "approval_status", None) or "approved",
        "iqc_before_pool": bool(inventory.get("iqc_before_pool", True)),
        "status_label": {
            "draft": "待下单",
            "ordered": "已下单",
            "shipped": "已下单",
            "partial_received": "部分到货",
            "received": "已到齐",
            "cancelled": "已取消",
        }.get(str(status), str(status)),
        "expected_date": po.expected_date,
        "suggested_arrival_date": suggested_dates[0] if suggested_dates else None,
        "suggested_arrival_dates": suggested_dates,
        "payment_term_days": po.payment_term_days,
        "supplier_payment_term_days": int(partner.payment_term_days or 0) if partner else 0,
        "effective_payment_term_days": (
            int(po.payment_term_days)
            if po.payment_term_days is not None
            else (int(partner.payment_term_days or 0) if partner else 0)
        ),
        "ordered_at": po.ordered_at,
        "logistics_company": po.logistics_company,
        "tracking_no": po.tracking_no,
        "notes": po.notes,
        "created_at": po.created_at,
        "currency": "CNY",
        "tax_note": "单价含税情况以双方约定为准",
        "lines": lines_out,
        "summary_lines": summary_lines,
        "summary_total_qty": total_qty,
        "summary_total_amount": total_amount,
        "public_token": po.public_token,
        "tracking_search_url": (
            f"https://www.baidu.com/s?wd={po.tracking_no}" if po.tracking_no else None
        ),
        **alert,
    }


def set_summary_unit_price(
    db: Session,
    tenant_id: int,
    po_id: int,
    supplier_product_id: int,
    unit_price: Decimal,
) -> dict:
    """草稿：按物料改汇总单价，同步到该物料所有分订单行（便于阶梯价）。"""
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("not_draft", "仅草稿可改单价")
    price = Decimal(str(unit_price))
    if price < 0:
        raise PurchaseError("invalid_price", "单价不能为负")
    product = db.get(SupplierProduct, supplier_product_id)
    catalog = product.unit_price if product is not None else None
    if catalog is not None and price > Decimal(str(catalog)):
        shown = Decimal(str(catalog)).quantize(Decimal("0.01"))
        raise PurchaseError("price_above_catalog", f"单价不能高于物料色卡单价 {shown}")
    touched = 0
    for ln in po.lines:
        if ln.supplier_product_id == supplier_product_id:
            ln.unit_price = price
            touched += 1
    if not touched:
        raise PurchaseError("line_not_found", "该物料不在本采购单中")
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def _clean_qty(value: Decimal) -> Decimal:
    """去掉末尾无意义的 0，整数不带小数。"""
    quantized = Decimal(str(value)).quantize(Decimal("0.0001"))
    if quantized == quantized.to_integral_value():
        return quantized.to_integral_value()
    return Decimal(format(quantized, "f").rstrip("0").rstrip("."))


def _assign_qty(lines: list, target: Decimal, *, field: str = "qty") -> None:
    target = _clean_qty(target)
    if len(lines) == 1:
        setattr(lines[0], field, target)
        return
    old = sum((Decimal(str(ln.qty or 0)) for ln in lines), Decimal("0"))
    if old <= 0:
        setattr(lines[0], field, target)
        for ln in lines[1:]:
            setattr(ln, field, Decimal("0"))
        return
    whole = target == target.to_integral_value() and all(
        Decimal(str(ln.qty or 0)) == Decimal(str(ln.qty or 0)).to_integral_value() for ln in lines
    )
    if whole:
        from decimal import ROUND_DOWN

        total = int(target)
        bases: list[int] = []
        fractions: list[Decimal] = []
        for ln in lines:
            exact = Decimal(str(ln.qty or 0)) / old * target
            base = int(exact.to_integral_value(rounding=ROUND_DOWN))
            bases.append(base)
            fractions.append(exact - Decimal(base))
        left = total - sum(bases)
        for index in sorted(range(len(lines)), key=lambda i: fractions[i], reverse=True):
            if left <= 0:
                break
            bases[index] += 1
            left -= 1
        for ln, qty in zip(lines, bases):
            setattr(ln, field, Decimal(qty))
        return
    allocated = Decimal("0")
    for index, ln in enumerate(lines):
        if index == len(lines) - 1:
            setattr(ln, field, _clean_qty(target - allocated))
        else:
            share = _clean_qty(Decimal(str(ln.qty or 0)) / old * target)
            setattr(ln, field, share)
            allocated += share


def set_summary_qty(
    db: Session,
    tenant_id: int,
    po_id: int,
    supplier_product_id: int,
    qty: Decimal,
    size_value: str | None = None,
) -> dict:
    """草稿：改汇总数量；带码数时只改该码。整数按整数分摊，不补小数。"""
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("not_draft", "仅待下单可改数量")
    target = _clean_qty(Decimal(str(qty)))
    if target < 0 or (size_value is None and target <= 0):
        raise PurchaseError("invalid_qty", "数量必须大于 0")
    lines = [ln for ln in po.lines if ln.supplier_product_id == supplier_product_id]
    if size_value is not None and str(size_value).strip():
        size_ids = set(
            db.scalars(
                select(Size.id).where(
                    Size.tenant_id == tenant_id,
                    Size.size_value == str(size_value).strip(),
                )
            ).all()
        )
        lines = [ln for ln in lines if ln.size_id in size_ids]
        if not lines:
            raise PurchaseError("line_not_found", "该码数不在本物料中")
    elif not lines:
        raise PurchaseError("line_not_found", "该物料不在本采购单中")
    _assign_qty(lines, target)
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def set_summary_loss(
    db: Session,
    tenant_id: int,
    po_id: int,
    supplier_product_id: int,
    loss_qty: Decimal,
    size_value: str | None = None,
) -> dict:
    """草稿：记下多买数量。有码数时只改该码。确认下单时才加进采购数量。"""
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("not_draft", "仅待下单可改损耗")
    target = _clean_qty(Decimal(str(loss_qty)))
    if target < 0:
        raise PurchaseError("invalid_loss", "损耗不能为负")
    lines = [ln for ln in po.lines if ln.supplier_product_id == supplier_product_id]
    if size_value is not None and str(size_value).strip():
        size_ids = set(
            db.scalars(
                select(Size.id).where(
                    Size.tenant_id == tenant_id,
                    Size.size_value == str(size_value).strip(),
                )
            ).all()
        )
        lines = [ln for ln in lines if ln.size_id in size_ids]
        if not lines:
            raise PurchaseError("line_not_found", "该码数不在本物料中")
    elif not lines:
        raise PurchaseError("line_not_found", "该物料不在本采购单中")
    _assign_qty(lines, target, field="loss_qty")
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def _reject_if_price_above_catalog(db: Session, po: PurchaseOrder) -> None:
    """下单前拦住高于物料色卡单价的明细。"""
    product_ids = {int(ln.supplier_product_id) for ln in po.lines if ln.supplier_product_id}
    products = {
        int(row.id): row
        for row in db.scalars(
            select(SupplierProduct).where(SupplierProduct.id.in_(product_ids or [-1]))
        ).all()
    }
    for ln in po.lines:
        if not ln.supplier_product_id:
            continue
        product = products.get(int(ln.supplier_product_id))
        catalog = product.unit_price if product is not None else None
        if catalog is None:
            continue
        if Decimal(str(ln.unit_price or 0)) <= Decimal(str(catalog)):
            continue
        name = (product.name if product and product.name else None) or (
            product.product_code if product else "物料"
        )
        shown = Decimal(str(catalog)).quantize(Decimal("0.01"))
        raise PurchaseError(
            "price_above_catalog",
            f"「{name}」单价不能高于物料色卡单价 {shown}，不能下单",
        )


def _sync_catalog_prices_from_feedback(db: Session, po: PurchaseOrder, changed_by: int | None) -> None:
    """下单反馈的单价和色卡不一致时，改色卡单价并留下历史。"""
    chosen: dict[int, object] = {}
    for ln in po.lines:
        product_id = int(ln.supplier_product_id or 0)
        if product_id:
            chosen[product_id] = ln.unit_price
    for product_id, price in chosen.items():
        product = db.get(SupplierProduct, product_id)
        if product is None or product.tenant_id != po.tenant_id:
            continue
        record_catalog_price_change(
            db,
            product,
            price,
            source="purchase_feedback",
            changed_by=changed_by,
            purchase_order_id=po.id,
            po_no=po.po_no,
        )


def new_public_token() -> str:
    return secrets.token_urlsafe(18)


def ensure_public_token(db: Session, po: PurchaseOrder) -> str:
    """保证采购单有公开扫码令牌；缺失则生成并落库。"""
    if po.public_token:
        return po.public_token
    for _ in range(5):
        token = new_public_token()
        exists = db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.public_token == token))
        if not exists:
            po.public_token = token
            db.flush()
            return token
    raise PurchaseError("token_failed", "无法生成公开令牌")


def get_po(db: Session, tenant_id: int, po_id: int) -> PurchaseOrder:
    po = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id)
        .options(selectinload(PurchaseOrder.lines))
    )
    if not po:
        raise PurchaseError("not_found", "采购单不存在")
    return po


def get_po_by_public_token(db: Session, token: str) -> PurchaseOrder:
    token = (token or "").strip()
    if not token:
        raise PurchaseError("not_found", "采购单不存在")
    po = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.public_token == token)
        .options(selectinload(PurchaseOrder.lines))
    )
    if not po:
        raise PurchaseError("not_found", "采购单不存在或链接无效")
    return po


def public_po_out(db: Session, po: PurchaseOrder) -> dict:
    """免登录预览：品名/数量等，不含单价金额与分订单明细。"""
    full = _po_out(db, po)
    return {
        "po_no": full["po_no"],
        "status": full["status"],
        "status_label": full.get("status_label"),
        "expected_date": full.get("expected_date"),
        "ordered_at": full.get("ordered_at"),
        "notes": full.get("notes"),
        "tax_note": full.get("tax_note"),
        "buyer_name": full.get("buyer_name"),
        "buyer_contact_person": full.get("buyer_contact_person"),
        "buyer_contact_mobile": full.get("buyer_contact_mobile"),
        "buyer_address": full.get("buyer_address"),
        "partner_name": full.get("partner_name"),
        "partner_address": full.get("partner_address"),
        "partner_contact_name": full.get("partner_contact_name"),
        "partner_contact_mobile": full.get("partner_contact_mobile"),
        "summary_lines": [
            {
                "supplier_product_code": x.get("supplier_product_code"),
                "supplier_product_name": x.get("supplier_product_name"),
                "pricing_unit_name": x.get("pricing_unit_name"),
                "qty": x.get("qty"),
            }
            for x in (full.get("summary_lines") or [])
        ],
    }


def _expected_unreceived_clause(today: date | None = None):
    """已下单未到齐，且协商到货日期已到（含当天）。"""
    day = today or date.today()
    return (
        PurchaseOrder.status.in_(list(_OPEN_DELIVERY_STATUSES)),
        PurchaseOrder.expected_date.is_not(None),
        PurchaseOrder.expected_date <= day,
    )


def count_pos_by_status(db: Session, tenant_id: int) -> dict:
    """按采购单状态统计数量。历史「已发货」并入「已下单」。"""
    rows = db.execute(
        select(PurchaseOrder.status, func.count())
        .where(PurchaseOrder.tenant_id == tenant_id)
        .group_by(PurchaseOrder.status)
    ).all()
    keys = ("draft", "ordered", "partial_received", "received", "cancelled")
    by_status = {k: 0 for k in keys}
    total = 0
    for status, n in rows:
        key = status.value if hasattr(status, "value") else str(status or "")
        n_int = int(n or 0)
        total += n_int
        if key == PurchaseOrderStatus.shipped.value:
            by_status["ordered"] += n_int
        elif key in by_status:
            by_status[key] += n_int
    return {"total": total, "by_status": by_status}


def count_expected_unreceived(db: Session, tenant_id: int) -> int:
    """已下单且未到齐，协商到货日期已到的采购单数。"""
    return int(
        db.scalar(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                *_expected_unreceived_clause(),
            )
        )
        or 0
    )


def list_pos(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = None,
    partner_id: int | None = None,
    order_id: int | None = None,
    delivery_alert: str | None = None,
    expected_unreceived: bool = False,
    keyword: str | None = None,
    expected_from: date | None = None,
    expected_to: date | None = None,
    ordered_from: date | None = None,
    ordered_to: date | None = None,
) -> list[dict]:
    q = (
        select(PurchaseOrder)
        .where(PurchaseOrder.tenant_id == tenant_id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.id.desc())
    )
    if expected_unreceived:
        q = q.where(*_expected_unreceived_clause())
    if status:
        if status == PurchaseOrderStatus.ordered.value:
            q = q.where(
                PurchaseOrder.status.in_([PurchaseOrderStatus.ordered, PurchaseOrderStatus.shipped])
            )
        else:
            q = q.where(PurchaseOrder.status == PurchaseOrderStatus(status))
    if partner_id:
        q = q.where(PurchaseOrder.partner_id == partner_id)
    if expected_from:
        q = q.where(PurchaseOrder.expected_date >= expected_from)
    if expected_to:
        q = q.where(PurchaseOrder.expected_date <= expected_to)
    if ordered_from:
        q = q.where(PurchaseOrder.ordered_at >= datetime.combine(ordered_from, datetime.min.time()))
    if ordered_to:
        q = q.where(
            PurchaseOrder.ordered_at < datetime.combine(ordered_to + timedelta(days=1), datetime.min.time())
        )
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        material_hit = (
            select(PurchaseOrderLine.id)
            .join(SupplierProduct, SupplierProduct.id == PurchaseOrderLine.supplier_product_id)
            .where(
                PurchaseOrderLine.tenant_id == tenant_id,
                PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
                or_(
                    SupplierProduct.product_code.ilike(like),
                    SupplierProduct.name.ilike(like),
                ),
            )
            .exists()
        )
        header_hit = (
            select(PurchaseOrderLine.id)
            .join(
                OrderMaterialRequirement,
                OrderMaterialRequirement.id == PurchaseOrderLine.order_material_requirement_id,
            )
            .join(ExecutionHeader, ExecutionHeader.id == OrderMaterialRequirement.header_id)
            .where(
                PurchaseOrderLine.tenant_id == tenant_id,
                PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
                ExecutionHeader.header_no.ilike(like),
            )
            .exists()
        )
        sales_header_hit = (
            select(PurchaseOrderLine.id)
            .join(SalesOrderLine, SalesOrderLine.id == PurchaseOrderLine.sales_order_line_id)
            .join(ExecutionHeader, ExecutionHeader.id == SalesOrderLine.execution_header_id)
            .where(
                PurchaseOrderLine.tenant_id == tenant_id,
                PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
                ExecutionHeader.header_no.ilike(like),
            )
            .exists()
        )
        partner_hit = (
            select(Partner.id)
            .where(Partner.id == PurchaseOrder.partner_id, Partner.name.ilike(like))
            .exists()
        )
        q = q.where(
            or_(
                PurchaseOrder.po_no.ilike(like),
                partner_hit,
                material_hit,
                header_hit,
                sales_header_hit,
            )
        )
    pos = db.scalars(q).all()
    out = []
    for po in pos:
        if order_id and not any(ln.order_id == order_id for ln in po.lines):
            continue
        row = _po_out(db, po)
        if delivery_alert and row.get("delivery_alert") != delivery_alert:
            continue
        out.append(row)
    # 交期告警筛选时逾期优先；默认按新建在前（id desc，与查询一致）
    if delivery_alert:
        out.sort(
            key=lambda r: (
                0 if r.get("delivery_alert") == "overdue" else 1 if r.get("delivery_alert") == "due_soon" else 2,
                -(r.get("overdue_days") or 0),
                -(r.get("id") or 0),
            )
        )
    return out


def _draft_parts(row: dict) -> list[dict]:
    """把这一行待采购拆到每一条用料上，生成草稿后这些待买都不再出现。"""
    buy = Decimal(str(row.get("buy_qty") or 0))
    orders = {
        int(order["requirement_id"]): order
        for order in (row.get("orders") or [])
        if order.get("requirement_id")
    }
    ids = [int(item) for item in (row.get("requirement_ids") or []) if int(item) > 0]
    if not ids and row.get("id"):
        ids = [int(row["id"])]
    weights = []
    for requirement_id in ids:
        order = orders.get(requirement_id) or {}
        weight = Decimal(str(order.get("required_qty") or 0))
        weights.append(weight if weight > 0 else Decimal("1"))
    total = sum(weights, Decimal("0"))
    remaining = buy
    parts = []
    for index, requirement_id in enumerate(ids):
        if index == len(ids) - 1:
            qty = remaining
        else:
            qty = (buy * weights[index] / total).quantize(Decimal("0.0001"))
            if qty > remaining:
                qty = remaining
            remaining -= qty
        if qty <= 0:
            continue
        order = orders.get(requirement_id) or {}
        parts.append(
            {
                "requirement_id": requirement_id,
                "qty": qty,
                "order_id": order.get("order_id", row.get("order_id")),
                "sales_order_id": order.get("sales_order_id", row.get("sales_order_id")),
                "sales_order_line_id": order.get(
                    "sales_order_line_id", row.get("sales_order_line_id")
                ),
            }
        )
    if parts:
        return parts
    return [
        {
            "requirement_id": int(row["id"]),
            "qty": buy,
            "order_id": row.get("order_id"),
            "sales_order_id": row.get("sales_order_id"),
            "sales_order_line_id": row.get("sales_order_line_id"),
        }
    ]


def create_drafts_from_shortages(
    db: Session,
    tenant_id: int,
    *,
    order_ids: list[int] | None = None,
    requirement_ids: list[int] | None = None,
    include_shared: bool = True,
    user_id: int | None = None,
) -> list[dict]:
    # 含已采行以便按 to_buy 过滤；生成时只取仍可采购数量
    if requirement_ids:
        from app.services.purchase_demand_service import lines_for_requirements

        shortages = lines_for_requirements(db, tenant_id, requirement_ids)
    else:
        shortages = list_shortages(
            db,
            tenant_id,
            order_ids=order_ids,
            include_shared=include_shared,
            hide_purchased=False,
        )
    # group by partner_id；同一缺料行只允许生成一次草稿（已有未取消采购则跳过）
    by_partner: dict[int, list[dict]] = {}
    for s in shortages:
        if not s.get("net_demand") and (
            s.get("has_purchase")
            or Decimal(str(s.get("draft_qty") or 0)) > 0
            or Decimal(str(s.get("ordered_qty") or 0)) > 0
        ):
            continue
        need = Decimal(str(s.get("to_buy_qty") or 0))
        if s.get("net_demand"):
            need -= Decimal(str(s.get("draft_qty") or 0))
            if need < 0:
                need = Decimal("0")
        if need <= 0:
            continue
        partner_id = s.get("partner_id")
        if not partner_id:
            raise PurchaseError("no_supplier", f"物料 {s.get('supplier_product_code')} 无供应商")
        by_partner.setdefault(partner_id, []).append({**s, "buy_qty": need})

    created = []
    for partner_id, rows in by_partner.items():
        po = PurchaseOrder(
            tenant_id=tenant_id,
            po_no=generate_po_no(db, tenant_id),
            public_token=new_public_token(),
            partner_id=partner_id,
            status=PurchaseOrderStatus.draft,
            created_by=user_id,
        )
        db.add(po)
        db.flush()
        for s in rows:
            sp = db.get(SupplierProduct, s["supplier_product_id"])
            price = sp.unit_price if sp and sp.unit_price is not None else s.get("unit_price") or Decimal("0")
            for part in _draft_parts(s):
                db.add(
                    PurchaseOrderLine(
                        tenant_id=tenant_id,
                        purchase_order_id=po.id,
                        supplier_product_id=s["supplier_product_id"],
                        order_id=part["order_id"],
                        order_material_requirement_id=part["requirement_id"],
                        sales_order_id=part.get("sales_order_id"),
                        sales_order_line_id=part.get("sales_order_line_id"),
                        qty=part["qty"],
                        unit_price=price,
                        size_id=s.get("size_id"),
                    )
                )
        db.flush()
        created.append(_po_out(db, get_po(db, tenant_id, po.id)))
    db.commit()
    return created


def update_po(
    db: Session,
    tenant_id: int,
    po_id: int,
    *,
    expected_date: date | None = None,
    payment_term_days: int | None | object = _PO_UNSET,
    logistics_company: str | None = None,
    tracking_no: str | None = None,
    notes: str | None = None,
    lines: list[dict] | None = None,
) -> dict:
    po = get_po(db, tenant_id, po_id)

    def _apply_header() -> None:
        if expected_date is not None:
            po.expected_date = expected_date
        if payment_term_days is not _PO_UNSET:
            if payment_term_days is None:
                po.payment_term_days = None
            else:
                po.payment_term_days = max(0, int(payment_term_days))
        if logistics_company is not None:
            po.logistics_company = logistics_company
        if tracking_no is not None:
            po.tracking_no = tracking_no
        if notes is not None:
            po.notes = notes

    if po.status != PurchaseOrderStatus.draft:
        # allow logistics / term update after ordered
        _apply_header()
        if lines is not None:
            raise PurchaseError("not_draft", "仅草稿可改明细")
        db.commit()
        return _po_out(db, get_po(db, tenant_id, po_id))

    _apply_header()
    if lines is not None:
        for ln in list(po.lines):
            db.delete(ln)
        db.flush()
        for item in lines:
            db.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=po.id,
                    supplier_product_id=item["supplier_product_id"],
                    order_id=item.get("order_id"),
                    order_material_requirement_id=item.get("order_material_requirement_id"),
                    qty=Decimal(str(item["qty"])),
                    unit_price=Decimal(str(item.get("unit_price") or 0)),
                    size_id=item.get("size_id"),
                )
            )
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def submit_po(
    db: Session,
    tenant_id: int,
    po_id: int,
    *,
    changed_by: int | None = None,
) -> dict:
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("invalid_status", "仅草稿可下单")
    if not po.lines:
        raise PurchaseError("empty", "采购明细为空")
    _reject_if_price_above_catalog(db, po)
    _sync_catalog_prices_from_feedback(db, po, changed_by)
    for ln in po.lines:
        extra = _clean_qty(Decimal(str(getattr(ln, "loss_qty", None) or 0)))
        if extra > 0:
            ln.qty = _clean_qty(Decimal(str(ln.qty or 0)) + extra)
    po.approval_status = "approved"
    po.status = PurchaseOrderStatus.ordered
    po.ordered_at = datetime.now()
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def mark_shipped(
    db: Session,
    tenant_id: int,
    po_id: int,
    *,
    logistics_company: str | None = None,
    tracking_no: str | None = None,
) -> dict:
    po = get_po(db, tenant_id, po_id)
    if po.status not in (PurchaseOrderStatus.ordered, PurchaseOrderStatus.shipped):
        raise PurchaseError("invalid_status", "当前状态不可标记发货")
    po.status = PurchaseOrderStatus.shipped
    if logistics_company is not None:
        po.logistics_company = logistics_company
    if tracking_no is not None:
        po.tracking_no = tracking_no
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def receive_po(
    db: Session,
    tenant_id: int,
    po_id: int,
    receives: list[dict],
    *,
    user_id: int | None = None,
    skip_iqc: bool = False,
    delivery_note_no: str | None = None,
) -> dict:
    """到货过账：直接入库存池，不按订单分配。不再生成来料 IQC。

    receives: [{line_id, qty}] 本次到货数量。
    """
    from app.models import MaterialIqcRecord, MaterialIqcStatus

    po = get_po(db, tenant_id, po_id)
    if po.status in (PurchaseOrderStatus.draft, PurchaseOrderStatus.cancelled, PurchaseOrderStatus.received):
        raise PurchaseError("invalid_status", "当前状态不可到货")

    _ = skip_iqc

    by_id = {ln.id: ln for ln in po.lines}

    for item in receives:
        ln = by_id.get(item["line_id"])
        if not ln:
            raise PurchaseError("line_not_found", f"明细不存在: {item['line_id']}")
        qty = Decimal(str(item["qty"]))
        if qty <= 0:
            continue

        pending_iqc = Decimal(
            str(
                db.scalar(
                    select(func.coalesce(func.sum(MaterialIqcRecord.qty), 0)).where(
                        MaterialIqcRecord.tenant_id == tenant_id,
                        MaterialIqcRecord.purchase_order_line_id == ln.id,
                        MaterialIqcRecord.status == MaterialIqcStatus.pending,
                    )
                )
                or 0
            )
        )
        open_qty = max(
            Decimal("0"),
            ln.qty - (ln.received_qty or Decimal("0")) - pending_iqc,
        )
        if qty > open_qty:
            raise PurchaseError(
                "over_receive",
                f"本次到货 {qty} 超过该行未收数量 {open_qty}",
            )

        ln.received_qty = (ln.received_qty or Decimal("0")) + qty

        line_size_id = getattr(ln, "size_id", None)
        product = db.get(SupplierProduct, ln.supplier_product_id)
        # 楦头：不进物料仓，直接入模具仓（生产部）；待结算仍走下方采购应付
        if is_tooling_supplier_product(db, product):
            from app.services.tooling_service import ToolingError, apply_purchase_receive_to_tooling

            try:
                apply_purchase_receive_to_tooling(
                    db,
                    tenant_id,
                    product_code=(product.product_code if product else "") or "",
                    size_id=line_size_id,
                    qty=qty,
                    unit_price=ln.unit_price,
                    po_id=po.id,
                    po_no=po.po_no,
                    user_id=user_id,
                )
            except ToolingError as exc:
                raise PurchaseError(exc.code, exc.message) from exc
            continue

        adjust_shared_stock(
            db,
            tenant_id,
            ln.supplier_product_id,
            qty,
            size_id=line_size_id,
            unit_cost=ln.unit_price,
            ledger_type=SharedLedgerType.unallocated_receive,
            ref_type="purchase_receive",
            ref_id=po.id,
            order_id=ln.order_id,
            user_id=user_id,
            note=f"PO {po.po_no} 到货入池",
        )

    total_recv = sum((ln.received_qty or Decimal("0") for ln in po.lines), Decimal("0"))
    if total_recv > 0:
        if all((ln.received_qty or 0) >= ln.qty for ln in po.lines):
            po.status = PurchaseOrderStatus.received
        else:
            po.status = PurchaseOrderStatus.partial_received

        from app.services.ap_service import create_payable_for_receive

        create_payable_for_receive(
            db, tenant_id, po, receives, delivery_note_no=delivery_note_no
        )

    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))



_PLACED_PO = (
    PurchaseOrderStatus.ordered,
    PurchaseOrderStatus.shipped,
    PurchaseOrderStatus.partial_received,
    PurchaseOrderStatus.received,
)


def _po_received_qty(po: PurchaseOrder) -> Decimal:
    return sum((ln.received_qty or Decimal("0") for ln in po.lines), Decimal("0"))


def _requirement_key(req: OrderMaterialRequirement) -> tuple[int, int | None]:
    size_id = int(req.size_id) if req.usage_by_size and req.size_id else None
    return (int(req.supplier_product_id), size_id)


def _po_line_key(line: PurchaseOrderLine) -> tuple[int, int | None]:
    return (int(line.supplier_product_id), int(line.size_id) if line.size_id else None)


def release_purchases_for_header(db: Session, tenant_id: int, header_id: int) -> dict:
    """取消未报工生产单时处理采购。

    待买行标成不再列入。已下单且未到货的采购单整单取消。
    已经到货的采购单保留，不拦住生产单取消。
    待下单的合买只减去本生产单数量，其它生产单的数量留在草稿上。
    """
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.header_id == header_id,
            )
        ).all()
    )
    for req in reqs:
        req.purchase_dismissed = True
    if not reqs:
        return {"cancelled_po_ids": [], "adjusted_po_ids": []}

    our_ids = {int(req.id) for req in reqs}
    qty_left: dict[tuple[int, int | None], Decimal] = {}
    for req in reqs:
        if req.is_customer_supplied:
            continue
        key = _requirement_key(req)
        qty_left[key] = qty_left.get(key, Decimal("0")) + Decimal(str(req.required_qty or 0))
    supplier_ids = {key[0] for key in qty_left}
    if not supplier_ids:
        return {"cancelled_po_ids": [], "adjusted_po_ids": []}

    lines = list(
        db.scalars(
            select(PurchaseOrderLine)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.status != PurchaseOrderStatus.cancelled,
                PurchaseOrderLine.supplier_product_id.in_(supplier_ids),
                PurchaseOrderLine.order_material_requirement_id.is_not(None),
            )
            .options(selectinload(PurchaseOrderLine.purchase_order).selectinload(PurchaseOrder.lines))
        ).all()
    )
    po_by_id: dict[int, PurchaseOrder] = {}
    for line in lines:
        po_by_id[int(line.purchase_order_id)] = line.purchase_order

    cancelled: list[int] = []
    adjusted: list[int] = []

    def _cancel_placed(po: PurchaseOrder) -> None:
        """未到货的已下单采购单取消。已有到货则留下，不拦住生产单取消。"""
        if po.status == PurchaseOrderStatus.cancelled or po.id in cancelled:
            return
        if _po_received_qty(po) > 0:
            return
        po.status = PurchaseOrderStatus.cancelled
        cancelled.append(int(po.id))

    direct_pos = []
    for po in po_by_id.values():
        if any(int(ln.order_material_requirement_id or 0) in our_ids for ln in po.lines):
            direct_pos.append(po)
    for po in direct_pos:
        if po.status in _PLACED_PO:
            _cancel_placed(po)
            for ln in po.lines:
                if int(ln.order_material_requirement_id or 0) in our_ids:
                    qty_left[_po_line_key(ln)] = Decimal("0")
            continue
        if po.status != PurchaseOrderStatus.draft:
            continue
        for ln in list(po.lines):
            if int(ln.order_material_requirement_id or 0) not in our_ids:
                continue
            key = _po_line_key(ln)
            take = min(Decimal(str(ln.qty or 0)), qty_left.get(key, Decimal("0")))
            ln.qty = Decimal(str(ln.qty or 0)) - take
            qty_left[key] = qty_left.get(key, Decimal("0")) - take
            if ln.qty <= 0:
                db.delete(ln)
            else:
                _retarget_po_line(db, tenant_id, ln, header_id)
        adjusted.append(int(po.id))

    db.flush()
    for po in list(po_by_id.values()):
        if po.status != PurchaseOrderStatus.draft or po.id in cancelled:
            continue
        db.expire(po, ["lines"])
        if po.lines:
            continue
        po.status = PurchaseOrderStatus.cancelled
        if po.id not in cancelled:
            cancelled.append(int(po.id))

    for key, left in list(qty_left.items()):
        if left <= 0:
            continue
        drafts = [
            ln
            for ln in lines
            if _po_line_key(ln) == key
            and ln.purchase_order
            and ln.purchase_order.status == PurchaseOrderStatus.draft
            and int(ln.order_material_requirement_id or 0) not in our_ids
            and ln.purchase_order.id not in cancelled
        ]
        drafts.sort(key=lambda ln: Decimal(str(ln.qty or 0)), reverse=True)
        for ln in drafts:
            if left <= 0:
                break
            anchor = db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
            floor = Decimal(str(anchor.required_qty or 0)) if anchor else Decimal("0")
            reducible = Decimal(str(ln.qty or 0)) - floor
            if reducible <= 0:
                continue
            take = min(left, reducible)
            ln.qty = Decimal(str(ln.qty or 0)) - take
            left -= take
            qty_left[key] = left
            if int(ln.purchase_order_id) not in adjusted:
                adjusted.append(int(ln.purchase_order_id))
        placed = [
            ln
            for ln in lines
            if _po_line_key(ln) == key
            and ln.purchase_order
            and ln.purchase_order.status in _PLACED_PO
            and int(ln.order_material_requirement_id or 0) not in our_ids
            and ln.purchase_order.id not in cancelled
        ]
        for ln in placed:
            if left <= 0:
                break
            anchor = db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
            floor = Decimal(str(anchor.required_qty or 0)) if anchor else Decimal("0")
            if Decimal(str(ln.qty or 0)) <= floor:
                continue
            _cancel_placed(ln.purchase_order)
            left = Decimal("0")
            qty_left[key] = left

    db.flush()
    for po in list(po_by_id.values()):
        if po.status != PurchaseOrderStatus.draft or int(po.id) in cancelled:
            continue
        db.expire(po, ["lines"])
        if not po.lines:
            po.status = PurchaseOrderStatus.cancelled
            cancelled.append(int(po.id))
    return {"cancelled_po_ids": cancelled, "adjusted_po_ids": adjusted}


def _retarget_po_line(
    db: Session,
    tenant_id: int,
    line: PurchaseOrderLine,
    header_id: int,
) -> None:
    """合买草稿减去本单后，采购行改挂到还在生产的用料行。"""
    key = _po_line_key(line)
    rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.header_id != header_id,
            OrderMaterialRequirement.supplier_product_id == key[0],
            OrderMaterialRequirement.purchase_dismissed.is_(False),
        )
    ).all()
    for req in rows:
        if _requirement_key(req) == key:
            line.order_material_requirement_id = int(req.id)
            return


def cancel_po(db: Session, tenant_id: int, po_id: int) -> dict:
    po = get_po(db, tenant_id, po_id)
    if po.status == PurchaseOrderStatus.cancelled:
        return _po_out(db, po)
    if po.status == PurchaseOrderStatus.draft:
        po.status = PurchaseOrderStatus.cancelled
        db.commit()
        return _po_out(db, get_po(db, tenant_id, po_id))
    total_recv = sum((ln.received_qty or Decimal("0") for ln in po.lines), Decimal("0"))
    if total_recv > 0:
        # 关闭未交：不整单取消，把未到部分视为取消占用 —— 通过标 cancelled 但保留 received
        # Plan: 已有到货则不可整单取消，走关闭未交
        po.status = PurchaseOrderStatus.received  # treat as closed with what we have
        # Actually better: set cancelled only if no receive; else mark received for received lines
        # Simpler approach per plan: set status to a closed state — use cancelled only when no receive
        raise PurchaseError(
            "has_receive",
            "已有到货，请使用「关闭未交」将状态置为已到齐（按已收数量）",
        )
    po.status = PurchaseOrderStatus.cancelled
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def close_open_qty(db: Session, tenant_id: int, po_id: int) -> dict:
    """关闭未交：已有到货的 PO，把订购量收到已收，释放未到占用。"""
    po = get_po(db, tenant_id, po_id)
    if sum((ln.received_qty or 0) for ln in po.lines) <= 0:
        raise PurchaseError("no_receive", "尚无到货，请直接取消采购单")
    for ln in po.lines:
        if (ln.received_qty or 0) < ln.qty:
            ln.qty = ln.received_qty or Decimal("0")
    po.status = PurchaseOrderStatus.received
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


def split_lines_to_new_po(
    db: Session,
    tenant_id: int,
    po_id: int,
    line_ids: list[int],
    *,
    user_id: int | None = None,
) -> dict:
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("not_draft", "仅草稿可拆单")
    move = [ln for ln in po.lines if ln.id in line_ids]
    if not move:
        raise PurchaseError("no_lines", "未选择明细")
    if len(move) >= len(po.lines):
        raise PurchaseError("all_lines", "不能移出全部明细")
    new_po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no=generate_po_no(db, tenant_id),
        public_token=new_public_token(),
        partner_id=po.partner_id,
        status=PurchaseOrderStatus.draft,
        expected_date=po.expected_date,
        created_by=user_id,
    )
    db.add(new_po)
    db.flush()
    for ln in move:
        ln.purchase_order_id = new_po.id
    db.commit()
    return {
        "original": _po_out(db, get_po(db, tenant_id, po_id)),
        "created": _po_out(db, get_po(db, tenant_id, new_po.id)),
    }


def _median_int(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return int(s[mid])
    return int(round((s[mid - 1] + s[mid]) / 2))


def purchase_lead_time_stats(db: Session, tenant_id: int, *, lookback: int = 80) -> dict:
    """历史采购周期与承诺偏差（天）。

    lead_days: ordered_at → 到齐(updated_at) 的工作日近似用自然日。
    delay_days: 实际到齐 − expected_date（正=晚到）。
    """
    pos = list(
        db.scalars(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.status.in_(
                    [
                        PurchaseOrderStatus.received,
                        PurchaseOrderStatus.partial_received,
                    ]
                ),
                PurchaseOrder.ordered_at.is_not(None),
            )
            .order_by(PurchaseOrder.id.desc())
            .limit(lookback)
            .options(selectinload(PurchaseOrder.lines))
        ).all()
    )
    by_partner: dict[int, list[int]] = {}
    by_sp: dict[int, list[int]] = {}
    delays_partner: dict[int, list[int]] = {}
    delays_sp: dict[int, list[int]] = {}
    all_leads: list[int] = []
    all_delays: list[int] = []

    for po in pos:
        ordered = po.ordered_at.date() if po.ordered_at else None
        # 到齐日代理：updated_at（收货会触发更新）
        arrived = po.updated_at.date() if po.updated_at else None
        if not ordered or not arrived or arrived < ordered:
            continue
        lead = (arrived - ordered).days
        if lead < 0 or lead > 180:
            continue
        all_leads.append(lead)
        by_partner.setdefault(po.partner_id, []).append(lead)
        delay = None
        if po.expected_date:
            delay = (arrived - po.expected_date).days
            if -60 <= delay <= 120:
                all_delays.append(delay)
                delays_partner.setdefault(po.partner_id, []).append(delay)
        for ln in po.lines or []:
            by_sp.setdefault(ln.supplier_product_id, []).append(lead)
            if delay is not None:
                delays_sp.setdefault(ln.supplier_product_id, []).append(delay)

    return {
        "sample_pos": len(pos),
        "default_lead_days": _median_int(all_leads) or 7,
        "default_delay_days": _median_int(all_delays) or 0,
        "lead_by_partner": {k: _median_int(v) for k, v in by_partner.items() if _median_int(v) is not None},
        "lead_by_product": {k: _median_int(v) for k, v in by_sp.items() if _median_int(v) is not None},
        "delay_by_partner": {k: _median_int(v) for k, v in delays_partner.items() if _median_int(v) is not None},
        "delay_by_product": {k: _median_int(v) for k, v in delays_sp.items() if _median_int(v) is not None},
    }


def estimate_material_etas(
    db: Session,
    tenant_id: int,
    shortage_rows: list[dict],
    *,
    as_of: date | None = None,
) -> dict:
    """对缺料行估算预计到料日；齐套日=各缺料行到料日最晚一天。

    优先：在途 PO 的 expected_date + 历史延迟；否则：今日 + 历史采购周期。
    在途按 (supplier_product_id, size_id) 匹配，不串码。
    """
    as_of = as_of or date.today()
    stats = purchase_lead_time_stats(db, tenant_id)
    open_pos = list(
        db.scalars(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.status.in_(list(_OPEN_DELIVERY_STATUSES)),
            )
            .options(selectinload(PurchaseOrder.lines))
        ).all()
    )
    # 键：(supplier_product_id, size_id)；未按码 size_id=None
    in_transit_eta: dict[tuple[int, int | None], date] = {}
    for po in open_pos:
        delay = 0
        if po.partner_id in stats["delay_by_partner"]:
            delay = int(stats["delay_by_partner"][po.partner_id])
        base = po.expected_date or (
            (po.ordered_at.date() + timedelta(days=int(stats["default_lead_days"])))
            if po.ordered_at
            else as_of + timedelta(days=int(stats["default_lead_days"]))
        )
        eta = base + timedelta(days=max(0, delay))
        for ln in po.lines or []:
            left = (ln.qty or Decimal("0")) - (ln.received_qty or Decimal("0"))
            if left <= 0:
                continue
            sp_id = ln.supplier_product_id
            if sp_id is None:
                continue
            size_id = getattr(ln, "size_id", None)
            try:
                size_key = int(size_id) if size_id is not None else None
            except (TypeError, ValueError):
                size_key = None
            key = (int(sp_id), size_key)
            prev = in_transit_eta.get(key)
            if prev is None or eta < prev:
                in_transit_eta[key] = eta

    items: list[dict] = []
    latest: date | None = None
    by_order_latest: dict[int, date] = {}
    for row in shortage_rows:
        sp_id = row.get("supplier_product_id")
        try:
            sp_id = int(sp_id) if sp_id is not None else None
        except (TypeError, ValueError):
            sp_id = None
        partner_id = row.get("partner_id")
        try:
            partner_id = int(partner_id) if partner_id is not None else None
        except (TypeError, ValueError):
            partner_id = None
        size_raw = row.get("size_id")
        try:
            size_id = int(size_raw) if size_raw is not None else None
        except (TypeError, ValueError):
            size_id = None
        order_raw = row.get("order_id")
        try:
            order_id = int(order_raw) if order_raw is not None else None
        except (TypeError, ValueError):
            order_id = None
        shortage = float(row.get("shortage_qty") or 0)
        if shortage <= 0:
            continue

        source = "lead_time"
        transit_key = (sp_id, size_id) if sp_id is not None else None
        if transit_key is not None and transit_key in in_transit_eta:
            eta = in_transit_eta[transit_key]
            source = "in_transit"
        else:
            lead = stats["default_lead_days"]
            if sp_id is not None and sp_id in stats["lead_by_product"]:
                lead = int(stats["lead_by_product"][sp_id])
                source = "product_history"
            elif partner_id is not None and partner_id in stats["lead_by_partner"]:
                lead = int(stats["lead_by_partner"][partner_id])
                source = "partner_history"
            eta = as_of + timedelta(days=max(1, int(lead)))

        eta_s = eta.isoformat()
        items.append(
            {
                "supplier_product_id": sp_id,
                "size_id": size_id,
                "order_id": order_id,
                "material": row.get("material")
                or row.get("supplier_product_name")
                or row.get("supplier_product_code"),
                "partner_id": partner_id,
                "partner_name": row.get("partner_name"),
                "shortage_qty": _dec_safe(row.get("shortage_qty")),
                "eta": eta_s,
                "expected_ready_date": eta_s,
                "expected_ready_label": "预计到料日",
                "source": source,
            }
        )
        if latest is None or eta > latest:
            latest = eta
        if order_id is not None:
            prev_o = by_order_latest.get(order_id)
            if prev_o is None or eta > prev_o:
                by_order_latest[order_id] = eta

    return {
        "as_of": as_of.isoformat(),
        "earliest_start": latest.isoformat() if latest else None,
        "earliest_start_label": "预计齐套日",
        "kit_ready_label": "预计齐套日",
        "blocks_start": bool(latest and latest > as_of),
        "items": items[:50],
        "by_order_id": {str(k): v.isoformat() for k, v in by_order_latest.items()},
        "stats": {
            "sample_pos": stats["sample_pos"],
            "default_lead_days": stats["default_lead_days"],
            "default_delay_days": stats["default_delay_days"],
        },
    }


def annotate_rows_with_etas(
    db: Session,
    tenant_id: int,
    rows: list[dict],
    *,
    as_of: date | None = None,
) -> dict:
    """给缺料行写入 expected_ready_*；返回 estimate 摘要（含 by_order_id 齐套日）。"""
    eta = estimate_material_etas(db, tenant_id, rows, as_of=as_of)
    # 按 (order_id, sp_id, size_id) 回写；同键多行取同一 ETA
    lookup: dict[tuple[int | None, int | None, int | None], str] = {}
    for it in eta.get("items") or []:
        key = (
            it.get("order_id"),
            it.get("supplier_product_id"),
            it.get("size_id"),
        )
        lookup[key] = it.get("expected_ready_date")
    for row in rows:
        shortage = float(row.get("shortage_qty") or 0)
        if shortage <= 0:
            row["expected_ready_date"] = None
            row["expected_ready_label"] = "预计到料日"
            continue
        try:
            oid = int(row["order_id"]) if row.get("order_id") is not None else None
        except (TypeError, ValueError):
            oid = None
        try:
            sp = int(row["supplier_product_id"]) if row.get("supplier_product_id") is not None else None
        except (TypeError, ValueError):
            sp = None
        try:
            sid = int(row["size_id"]) if row.get("size_id") is not None else None
        except (TypeError, ValueError):
            sid = None
        ready = lookup.get((oid, sp, sid))
        row["expected_ready_date"] = ready
        row["expected_ready_label"] = "预计到料日"
    return eta


def _dec_safe(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sum_qty_by_supplier_product(by_key: dict) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for (sp_id, _size_id), qty in (by_key or {}).items():
        out[int(sp_id)] = out.get(int(sp_id), Decimal("0")) + Decimal(str(qty or 0))
    return out


def _stock_replenish_draft_qty(db: Session, tenant_id: int) -> dict[int, Decimal]:
    """已有备库采购草稿占用（不含销售/生产缺料草稿）。"""
    rows = db.execute(
        select(
            PurchaseOrderLine.supplier_product_id,
            func.coalesce(func.sum(PurchaseOrderLine.qty), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.tenant_id == tenant_id,
            PurchaseOrder.status == PurchaseOrderStatus.draft,
            PurchaseOrderLine.sales_order_id.is_(None),
            PurchaseOrderLine.order_material_requirement_id.is_(None),
            PurchaseOrder.notes.like("备库%"),
        )
        .group_by(PurchaseOrderLine.supplier_product_id)
    ).all()
    return {int(sp): Decimal(str(qty or 0)) for sp, qty in rows}


def list_stock_replenishment(
    db: Session,
    tenant_id: int,
    *,
    include_shared: bool = True,
    partner_id: int | None = None,
    keyword: str | None = None,
    below_only: bool = True,
) -> list[dict]:
    """备库建议：物料设了安全库存，且（可选）现有覆盖低于安全库存。"""
    from app.services.material_service import (
        free_pool_after_production_credits,
        in_transit_qty_by_pool_key,
    )

    q = select(SupplierProduct, Partner).join(Partner, Partner.id == SupplierProduct.partner_id).where(
        SupplierProduct.tenant_id == tenant_id,
        SupplierProduct.is_active.is_(True),
        SupplierProduct.min_stock_qty.isnot(None),
        SupplierProduct.min_stock_qty > 0,
    )
    if partner_id:
        q = q.where(SupplierProduct.partner_id == partner_id)
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(
            (SupplierProduct.product_code.ilike(kw))
            | (SupplierProduct.name.ilike(kw))
            | (Partner.name.ilike(kw))
        )
    rows = list(db.execute(q.order_by(SupplierProduct.product_code.asc())).all())
    if not rows:
        return []

    _pool, free_by_key = free_pool_after_production_credits(
        db, tenant_id, include_shared=include_shared
    )
    free_by_sp = _sum_qty_by_supplier_product(free_by_key)
    transit_by_sp = _sum_qty_by_supplier_product(in_transit_qty_by_pool_key(db, tenant_id))
    draft_by_sp = _stock_replenish_draft_qty(db, tenant_id)

    out: list[dict] = []
    for sp, partner in rows:
        min_qty = Decimal(str(sp.min_stock_qty or 0))
        free_qty = free_by_sp.get(int(sp.id), Decimal("0"))
        transit_qty = transit_by_sp.get(int(sp.id), Decimal("0"))
        draft_qty = draft_by_sp.get(int(sp.id), Decimal("0"))
        cover = free_qty + transit_qty + draft_qty
        buy = max(Decimal("0"), min_qty - cover)
        if below_only and buy <= 0:
            continue
        out.append(
            {
                "id": sp.id,
                "supplier_product_id": sp.id,
                "supplier_product_code": sp.product_code,
                "supplier_product_name": sp.name,
                "image_url": sp.image_url,
                "partner_id": sp.partner_id,
                "partner_name": partner.name if partner else None,
                "unit_price": sp.unit_price,
                "min_stock_qty": min_qty,
                "free_pool_qty": free_qty,
                "in_transit_qty": transit_qty,
                "draft_qty": draft_qty,
                "cover_qty": cover,
                "buy_qty": buy,
                "can_create_draft": buy > 0 and bool(sp.partner_id),
            }
        )
    out.sort(key=lambda r: (-float(r["buy_qty"]), r["supplier_product_code"] or ""))
    return out


def create_stock_replenishment_drafts(
    db: Session,
    tenant_id: int,
    supplier_product_ids: list[int] | None = None,
    *,
    include_shared: bool = True,
    user_id: int | None = None,
) -> list[dict]:
    """按安全库存缺口生成备库采购草稿（不挂销售/生产）。"""
    suggestions = list_stock_replenishment(
        db,
        tenant_id,
        include_shared=include_shared,
        below_only=True,
    )
    want = {int(x) for x in (supplier_product_ids or [])} if supplier_product_ids else None
    picks = [
        r
        for r in suggestions
        if float(r.get("buy_qty") or 0) > 0
        and (want is None or int(r["supplier_product_id"]) in want)
    ]
    if not picks:
        raise PurchaseError("no_shortage", "无备库缺口可生成采购草稿（可能已有草稿覆盖）")

    by_partner: dict[int, list[dict]] = {}
    for row in picks:
        partner_id = row.get("partner_id")
        if not partner_id:
            raise PurchaseError(
                "no_supplier",
                f"物料 {row.get('supplier_product_code') or row['supplier_product_id']} 无供应商",
            )
        by_partner.setdefault(int(partner_id), []).append(row)

    created: list[dict] = []
    for partner_id, rows in by_partner.items():
        codes = sorted({str(r.get("supplier_product_code") or "") for r in rows if r.get("supplier_product_code")})
        note = "备库采购" + (f"：{'/'.join(codes[:5])}" if codes else "")
        po = PurchaseOrder(
            tenant_id=tenant_id,
            po_no=generate_po_no(db, tenant_id),
            public_token=new_public_token(),
            partner_id=partner_id,
            status=PurchaseOrderStatus.draft,
            notes=note,
            created_by=user_id,
        )
        db.add(po)
        db.flush()
        for r in rows:
            sp = db.get(SupplierProduct, int(r["supplier_product_id"]))
            price = (
                sp.unit_price
                if sp and sp.unit_price is not None
                else Decimal(str(r.get("unit_price") or 0))
            )
            db.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=po.id,
                    supplier_product_id=int(r["supplier_product_id"]),
                    order_id=None,
                    order_material_requirement_id=None,
                    sales_order_id=None,
                    sales_order_line_id=None,
                    qty=Decimal(str(r["buy_qty"])),
                    unit_price=price,
                    size_id=None,
                )
            )
        db.flush()
        created.append(_po_out(db, get_po(db, tenant_id, po.id)))
    db.commit()
    return created


def create_catalog_purchase_drafts(
    db: Session,
    tenant_id: int,
    lines: list[dict],
    *,
    user_id: int | None = None,
    notes: str | None = None,
) -> list[dict]:
    """色卡批量购买：按供应商拆采购草稿，入库进公用池（不挂销售/生产）。

    可选 size_id：鞋底/垫脚等按码料写入对应码池；未传则进通用池。
    """
    if not lines:
        raise PurchaseError("empty", "请选择要购买的物料")
    prepared: list[tuple[SupplierProduct, Decimal, int | None]] = []
    for item in lines:
        sp_id = int(item.get("supplier_product_id") or 0)
        qty = Decimal(str(item.get("qty") or 0))
        raw_size = item.get("size_id")
        size_id = int(raw_size) if raw_size is not None and str(raw_size).strip() != "" else None
        if sp_id <= 0:
            raise PurchaseError("invalid_line", "物料无效")
        if qty <= 0:
            raise PurchaseError("invalid_qty", "采购数量须大于 0")
        sp = db.get(SupplierProduct, sp_id)
        if not sp or sp.tenant_id != tenant_id or not sp.is_active:
            raise PurchaseError("not_found", f"物料不存在或已停用：{sp_id}")
        if not catalog_approved(sp):
            name = (sp.name or "").strip() or sp.product_code
            raise PurchaseError("not_approved", f"「{name}」尚未审批通过，不能购买")
        if not sp.partner_id:
            raise PurchaseError(
                "no_supplier",
                f"物料 {sp.product_code} 未绑定供应商",
            )
        if size_id is not None:
            sz = db.get(Size, size_id)
            if not sz or sz.tenant_id != tenant_id or not sz.is_active:
                raise PurchaseError("invalid_size", f"尺码无效：{size_id}")
        prepared.append((sp, qty, size_id))

    by_partner: dict[int, list[tuple[SupplierProduct, Decimal, int | None]]] = {}
    for sp, qty, size_id in prepared:
        by_partner.setdefault(int(sp.partner_id), []).append((sp, qty, size_id))

    created: list[dict] = []
    for partner_id, rows in by_partner.items():
        codes = sorted({sp.product_code for sp, _qty, _sid in rows if sp.product_code})
        note = (notes or "").strip() or "色卡批量购买"
        if codes:
            note = f"{note}：{'/'.join(codes[:5])}"
        po = PurchaseOrder(
            tenant_id=tenant_id,
            po_no=generate_po_no(db, tenant_id),
            public_token=new_public_token(),
            partner_id=partner_id,
            status=PurchaseOrderStatus.draft,
            notes=note,
            created_by=user_id,
        )
        db.add(po)
        db.flush()
        for sp, qty, size_id in rows:
            db.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=po.id,
                    supplier_product_id=sp.id,
                    order_id=None,
                    order_material_requirement_id=None,
                    sales_order_id=None,
                    sales_order_line_id=None,
                    qty=qty,
                    unit_price=sp.unit_price if sp.unit_price is not None else Decimal("0"),
                    size_id=size_id,
                )
            )
        db.flush()
        created.append(_po_out(db, get_po(db, tenant_id, po.id)))
    db.commit()
    return created
