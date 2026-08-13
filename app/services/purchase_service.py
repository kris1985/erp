"""采购单：按供应商拆单、合并多订单行、到货回写。"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Order,
    OrderMaterialRequirement,
    Partner,
    PartnerContact,
    PricingUnit,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedLedgerType,
    SupplierProduct,
    Tenant,
)
from app.services.material_service import (
    MaterialError,
    adjust_shared_stock,
    list_shortages,
    ordered_qty_for_requirement,
)

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
                "received_qty": Decimal("0"),
                "unit_price": ln.get("unit_price") or Decimal("0"),
                "last_purchase_price": ln.get("last_purchase_price"),
                "catalog_price": ln.get("catalog_price"),
                "line_ids": [],
                "allocations": [],
                "price_mixed": False,
            }
            by_sp[sp_id] = bucket
        bucket["qty"] += Decimal(str(ln.get("qty") or 0))
        bucket["received_qty"] += Decimal(str(ln.get("received_qty") or 0))
        bucket["line_ids"].append(ln["id"])
        price = Decimal(str(ln.get("unit_price") or 0))
        if price != Decimal(str(bucket["unit_price"] or 0)):
            bucket["price_mixed"] = True
        bucket["allocations"].append(
            {
                "line_id": ln["id"],
                "order_id": ln.get("order_id"),
                "order_no": ln.get("order_no"),
                "qty": ln.get("qty"),
                "received_qty": ln.get("received_qty"),
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

    partner = db.get(Partner, po.partner_id)
    tenant = db.get(Tenant, po.tenant_id)
    contact = _primary_partner_contact(db, po.tenant_id, po.partner_id) if partner else None
    lines_out = []
    size_ids = {getattr(ln, "size_id", None) for ln in po.lines if getattr(ln, "size_id", None)}
    size_map = {
        s.id: s.size_value
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids or [-1]))).all()
    } if size_ids else {}
    for ln in po.lines:
        sp = db.get(SupplierProduct, ln.supplier_product_id)
        order = db.get(Order, ln.order_id) if ln.order_id else None
        last = last_purchase_price(db, po.tenant_id, ln.supplier_product_id)
        unit = db.get(PricingUnit, sp.pricing_unit_id) if sp and sp.pricing_unit_id else None
        color = db.get(Color, sp.color_id) if sp and sp.color_id else None
        size_id = getattr(ln, "size_id", None)
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
                "order_no": order.order_no if order else None,
                "order_material_requirement_id": ln.order_material_requirement_id,
                "sales_order_id": getattr(ln, "sales_order_id", None),
                "sales_order_line_id": getattr(ln, "sales_order_line_id", None),
                "qty": ln.qty,
                "unit_price": ln.unit_price,
                "received_qty": ln.received_qty,
                "size_id": size_id,
                "size_value": size_map.get(size_id) if size_id else None,
                "last_purchase_price": last,
                "catalog_price": sp.unit_price if sp else None,
            }
        )
    summary_lines = _build_summary_lines(lines_out)
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
        "status_label": {
            "draft": "待下单",
            "ordered": "已下单",
            "shipped": "已下单",
            "partial_received": "部分到货",
            "received": "已到齐",
            "cancelled": "已取消",
        }.get(str(status), str(status)),
        "expected_date": po.expected_date,
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
    touched = 0
    for ln in po.lines:
        if ln.supplier_product_id == supplier_product_id:
            ln.unit_price = price
            touched += 1
    if not touched:
        raise PurchaseError("line_not_found", "该物料不在本采购单中")
    db.commit()
    return _po_out(db, get_po(db, tenant_id, po_id))


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


def list_pos(
    db: Session,
    tenant_id: int,
    *,
    status: str | None = None,
    partner_id: int | None = None,
    order_id: int | None = None,
    delivery_alert: str | None = None,
) -> list[dict]:
    q = (
        select(PurchaseOrder)
        .where(PurchaseOrder.tenant_id == tenant_id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.id.desc())
    )
    if status:
        q = q.where(PurchaseOrder.status == PurchaseOrderStatus(status))
    if partner_id:
        q = q.where(PurchaseOrder.partner_id == partner_id)
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
    shortages = list_shortages(
        db,
        tenant_id,
        order_ids=order_ids,
        include_shared=include_shared,
        hide_purchased=False,
    )
    if requirement_ids:
        allow = set(requirement_ids)
        shortages = [s for s in shortages if s["id"] in allow]
    # group by partner_id；同一缺料行只允许生成一次草稿（已有未取消采购则跳过）
    by_partner: dict[int, list[dict]] = {}
    for s in shortages:
        if s.get("has_purchase") or Decimal(str(s.get("draft_qty") or 0)) > 0 or Decimal(
            str(s.get("ordered_qty") or 0)
        ) > 0:
            continue
        need = Decimal(str(s.get("to_buy_qty") or 0))
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
            db.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=po.id,
                    supplier_product_id=s["supplier_product_id"],
                    order_id=s["order_id"],
                    order_material_requirement_id=s["id"],
                    qty=s["buy_qty"],
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


def submit_po(db: Session, tenant_id: int, po_id: int) -> dict:
    po = get_po(db, tenant_id, po_id)
    if po.status != PurchaseOrderStatus.draft:
        raise PurchaseError("invalid_status", "仅草稿可下单")
    if not po.lines:
        raise PurchaseError("empty", "采购明细为空")
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
) -> dict:
    """到货过账。

    默认（iqc_before_pool）：生成待检 IQC，**不入池**；合格/让步后再入池与齐套。
    skip_iqc=True 或配置关闭：沿用旧路径直入池。

    receives: [{line_id, qty}] 本次到货数量。
    """
    from app.services.inventory_settings import get_inventory_by_tenant_id
    from app.services import iqc_service

    po = get_po(db, tenant_id, po_id)
    if po.status in (PurchaseOrderStatus.draft, PurchaseOrderStatus.cancelled, PurchaseOrderStatus.received):
        raise PurchaseError("invalid_status", "当前状态不可到货")

    inv = get_inventory_by_tenant_id(db, tenant_id)
    auto_allocate = bool(inv.get("auto_allocate_on_receive", True))
    use_iqc = bool(inv.get("iqc_before_pool", True)) and not skip_iqc

    by_id = {ln.id: ln for ln in po.lines}
    iqc_created: list[int] = []

    for item in receives:
        ln = by_id.get(item["line_id"])
        if not ln:
            raise PurchaseError("line_not_found", f"明细不存在: {item['line_id']}")
        qty = Decimal(str(item["qty"]))
        if qty <= 0:
            continue

        if use_iqc:
            rec = iqc_service.create_pending_from_receive(
                db, tenant_id, po, ln, qty, user_id=user_id
            )
            iqc_created.append(rec.id)
            continue

        open_qty = max(Decimal("0"), ln.qty - (ln.received_qty or Decimal("0")))
        # 允许超收：整笔入池；可分配量不超过本行未收订购量
        alloc_cap = open_qty
        ln.received_qty = (ln.received_qty or Decimal("0")) + qty

        # 1) 全部进池（按码行入对应码池）
        line_size_id = getattr(ln, "size_id", None)
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

        # 2) 挂单行自动分配（从池扣到订单占用）
        if auto_allocate and ln.order_material_requirement_id and alloc_cap > 0:
            req = db.get(OrderMaterialRequirement, ln.order_material_requirement_id)
            if req:
                alloc = min(qty, alloc_cap)
                if alloc > 0:
                    adjust_shared_stock(
                        db,
                        tenant_id,
                        ln.supplier_product_id,
                        -alloc,
                        size_id=line_size_id,
                        unit_cost=ln.unit_price,
                        ledger_type=SharedLedgerType.allocate_to_order,
                        ref_type="purchase_allocate",
                        ref_id=po.id,
                        order_id=ln.order_id,
                        user_id=user_id,
                        note=f"PO {po.po_no} 自动分配到订单",
                    )
                    req.arrived_qty = (req.arrived_qty or Decimal("0")) + alloc

    if not use_iqc:
        total_recv = sum((ln.received_qty or Decimal("0") for ln in po.lines), Decimal("0"))
        if total_recv <= 0:
            pass
        elif all((ln.received_qty or 0) >= ln.qty for ln in po.lines):
            po.status = PurchaseOrderStatus.received
        else:
            po.status = PurchaseOrderStatus.partial_received

        from app.services.ap_service import create_payable_for_receive

        create_payable_for_receive(db, tenant_id, po, receives)

    db.commit()
    out = _po_out(db, get_po(db, tenant_id, po_id))
    if use_iqc:
        out["iqc_pending_ids"] = iqc_created
        out["iqc_pending_count"] = len(iqc_created)
        out["iqc_message"] = "已生成待检，合格/让步后才入池与齐套"
    return out


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
