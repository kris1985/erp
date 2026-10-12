"""底模：独立档案，不送货，手工录入后直接挂供应商待结算。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Partner, Payable, PayableLine, PayableStatus, SoleMold, SoleMoldEntry
from app.services.ap_service import _refresh_ap_status


SOURCE = "sole_mold"


class SoleMoldError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _supplier_name(partner: Partner) -> str:
    return (partner.short_name or partner.name or "").strip() or f"供应商#{partner.id}"


def list_molds(db: Session, tenant_id: int, *, keyword: str | None = None) -> list[dict]:
    query = select(SoleMold).where(SoleMold.tenant_id == tenant_id, SoleMold.is_active.is_(True))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.where((SoleMold.code.like(like)) | (SoleMold.name.like(like)))
    rows = db.scalars(query.order_by(SoleMold.code, SoleMold.id)).all()
    return [{"id": row.id, "code": row.code, "name": row.name} for row in rows]


def create_entry(
    db: Session,
    tenant_id: int,
    *,
    code: str,
    name: str,
    supplier_id: int,
    unit_price,
    qty: int,
    ordered_at: datetime,
    user_id: int | None,
) -> dict:
    code = (code or "").strip()
    name = (name or "").strip()
    if not code:
        raise SoleMoldError("code", "请填写编号")
    if len(code) > 50:
        raise SoleMoldError("code", "编号不能超过50个字")
    if not name:
        raise SoleMoldError("name", "请填写名称")
    if len(name) > 100:
        raise SoleMoldError("name", "名称不能超过100个字")
    qty = int(qty or 0)
    if qty <= 0:
        raise SoleMoldError("qty", "请填写数量")
    price = _money(unit_price)
    if price <= 0:
        raise SoleMoldError("price", "请填写单价")
    if ordered_at is None:
        raise SoleMoldError("ordered_at", "请填写下单时间")
    partner = db.get(Partner, supplier_id)
    if (
        not partner
        or partner.tenant_id != tenant_id
        or not partner.is_supplier
        or not partner.is_active
    ):
        raise SoleMoldError("supplier", "请选择供应商")

    mold = db.scalar(select(SoleMold).where(SoleMold.tenant_id == tenant_id, SoleMold.code == code))
    if mold is None:
        mold = SoleMold(tenant_id=tenant_id, code=code, name=name, is_active=True)
        db.add(mold)
        db.flush()
    else:
        mold.name = name
        mold.is_active = True

    supplier_label = _supplier_name(partner)
    amount = _money(Decimal(qty) * price)
    booked = ordered_at.date()
    ap = Payable(
        tenant_id=tenant_id,
        supplier_id=partner.id,
        supplier_name=supplier_label,
        purchase_order_id=None,
        payable_date=booked,
        due_date=booked,
        payment_term_days=0,
        amount=amount,
        adjustment=Decimal("0"),
        paid_amount=Decimal("0"),
        status=PayableStatus.open,
        notes=f"底模 {code}",
        delivery_note_no=None,
    )
    db.add(ap)
    db.flush()
    entry = SoleMoldEntry(
        tenant_id=tenant_id,
        sole_mold_id=mold.id,
        supplier_id=partner.id,
        supplier_name=supplier_label,
        unit_price=price,
        qty=qty,
        ordered_at=ordered_at,
        payable_id=ap.id,
        created_by=user_id,
        created_at=datetime.now(),
    )
    db.add(entry)
    db.flush()
    db.add(
        PayableLine(
            tenant_id=tenant_id,
            payable_id=ap.id,
            source_type=SOURCE,
            source_ref_id=entry.id,
            source_document_no=None,
            item_code=mold.code,
            item_name=name,
            unit_name="套",
            qty=Decimal(qty),
            unit_price=price,
            amount=amount,
            sort_order=0,
        )
    )
    _refresh_ap_status(ap)
    db.commit()
    return {
        "id": entry.id,
        "sole_mold_id": mold.id,
        "code": mold.code,
        "name": name,
        "supplier_id": partner.id,
        "supplier_name": supplier_label,
        "unit_price": float(price),
        "qty": qty,
        "ordered_at": ordered_at,
        "amount": float(amount),
        "payable_id": ap.id,
    }
