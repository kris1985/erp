"""往来单位：客户 / 品牌方 / 供应商 + 多联系人。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import Partner, PartnerContact, User
from app.schemas.api import (
    PartnerContactCreate,
    PartnerContactOut,
    PartnerContactUpdate,
    PartnerCreate,
    PartnerOut,
    PartnerUpdate,
)
from app.schemas.common import ok

router = APIRouter(prefix="/partners", tags=["partners"])


def _contact_out(c: PartnerContact) -> PartnerContactOut:
    return PartnerContactOut.model_validate(c)


def _partner_out(p: Partner, *, with_contacts: bool = False) -> dict:
    contacts = list(p.contacts or [])
    active = [c for c in contacts if c.is_active]
    primary = next((c for c in active if c.is_primary), None) or (active[0] if active else None)
    out = PartnerOut(
        id=p.id,
        name=p.name,
        short_name=p.short_name,
        is_customer=bool(p.is_customer),
        is_supplier=bool(p.is_supplier),
        is_brand=bool(p.is_brand),
        address=p.address,
        notes=p.notes,
        is_active=bool(p.is_active),
        contacts_count=len(active),
        primary_contact=_contact_out(primary) if primary else None,
        contacts=[_contact_out(c) for c in contacts] if with_contacts else [],
    )
    return out.model_dump(mode="json")


def _clear_other_primary(db: Session, partner_id: int, keep_id: int | None) -> None:
    rows = db.scalars(
        select(PartnerContact).where(
            PartnerContact.partner_id == partner_id,
            PartnerContact.is_primary.is_(True),
        )
    ).all()
    for row in rows:
        if keep_id is None or row.id != keep_id:
            row.is_primary = False


def _ensure_partner(db: Session, tenant_id: int, partner_id: int) -> Partner:
    p = db.scalar(
        select(Partner)
        .where(Partner.id == partner_id, Partner.tenant_id == tenant_id)
        .options(selectinload(Partner.contacts))
    )
    if not p:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    return p


@router.get("")
def list_partners(
    role: str | None = Query(None, description="customer|supplier|brand"),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        select(Partner)
        .where(Partner.tenant_id == user.tenant_id)
        .options(selectinload(Partner.contacts))
        .order_by(Partner.id.desc())
    )
    if active_only:
        q = q.where(Partner.is_active.is_(True))
    if role == "customer":
        q = q.where(Partner.is_customer.is_(True))
    elif role == "supplier":
        q = q.where(Partner.is_supplier.is_(True))
    elif role == "brand":
        q = q.where(Partner.is_brand.is_(True))
    elif role == "customer_brand":
        q = q.where((Partner.is_customer.is_(True)) | (Partner.is_brand.is_(True)))
    elif role:
        raise HTTPException(status_code=400, detail="role 可选 customer/supplier/brand/customer_brand")
    rows = db.scalars(q).all()
    items = [_partner_out(p, with_contacts=True) for p in rows]
    return ok({"items": items, "total": len(items)})


@router.post("")
def create_partner(
    body: PartnerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    if not (body.is_customer or body.is_supplier or body.is_brand):
        raise HTTPException(status_code=400, detail="请至少选择一种角色：客户/供应商/品牌方")
    exists = db.scalar(
        select(Partner).where(Partner.tenant_id == user.tenant_id, Partner.name == body.name.strip())
    )
    if exists:
        raise HTTPException(status_code=400, detail="同名往来单位已存在")
    p = Partner(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        short_name=(body.short_name or "").strip() or None,
        is_customer=body.is_customer,
        is_supplier=body.is_supplier,
        is_brand=body.is_brand,
        address=body.address,
        notes=body.notes,
        is_active=body.is_active,
    )
    db.add(p)
    db.flush()
    primary_seen = False
    for i, c in enumerate(body.contacts):
        is_primary = bool(c.is_primary) and not primary_seen
        if is_primary:
            primary_seen = True
        db.add(
            PartnerContact(
                tenant_id=user.tenant_id,
                partner_id=p.id,
                name=c.name.strip(),
                title=c.title,
                mobile=c.mobile,
                wechat=c.wechat,
                email=c.email,
                is_primary=is_primary,
                sort_order=c.sort_order if c.sort_order else i,
                is_active=c.is_active,
            )
        )
    if body.contacts and not primary_seen:
        first = db.scalar(
            select(PartnerContact)
            .where(PartnerContact.partner_id == p.id)
            .order_by(PartnerContact.id)
        )
        if first:
            first.is_primary = True
    db.commit()
    p = _ensure_partner(db, user.tenant_id, p.id)
    return ok(_partner_out(p, with_contacts=True))


@router.get("/{partner_id}")
def get_partner(partner_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _ensure_partner(db, user.tenant_id, partner_id)
    return ok(_partner_out(p, with_contacts=True))


@router.patch("/{partner_id}")
def update_partner(
    partner_id: int,
    body: PartnerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = _ensure_partner(db, user.tenant_id, partner_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        data["name"] = data["name"].strip()
        other = db.scalar(
            select(Partner).where(
                Partner.tenant_id == user.tenant_id,
                Partner.name == data["name"],
                Partner.id != partner_id,
            )
        )
        if other:
            raise HTTPException(status_code=400, detail="同名往来单位已存在")
    if "short_name" in data and data["short_name"] is not None:
        data["short_name"] = data["short_name"].strip() or None
    for k, v in data.items():
        setattr(p, k, v)
    if not (p.is_customer or p.is_supplier or p.is_brand):
        raise HTTPException(status_code=400, detail="请至少保留一种角色")
    db.commit()
    p = _ensure_partner(db, user.tenant_id, partner_id)
    return ok(_partner_out(p, with_contacts=True))


@router.get("/{partner_id}/contacts")
def list_contacts(partner_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _ensure_partner(db, user.tenant_id, partner_id)
    items = [_contact_out(c).model_dump(mode="json") for c in p.contacts]
    return ok({"items": items, "total": len(items)})


@router.post("/{partner_id}/contacts")
def create_contact(
    partner_id: int,
    body: PartnerContactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = _ensure_partner(db, user.tenant_id, partner_id)
    c = PartnerContact(
        tenant_id=user.tenant_id,
        partner_id=p.id,
        name=body.name.strip(),
        title=body.title,
        mobile=body.mobile,
        wechat=body.wechat,
        email=body.email,
        is_primary=bool(body.is_primary),
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(c)
    db.flush()
    if c.is_primary:
        _clear_other_primary(db, p.id, c.id)
    elif not any(x.is_primary for x in p.contacts if x.id != c.id):
        c.is_primary = True
    db.commit()
    db.refresh(c)
    return ok(_contact_out(c).model_dump(mode="json"))


@router.patch("/{partner_id}/contacts/{contact_id}")
def update_contact(
    partner_id: int,
    contact_id: int,
    body: PartnerContactUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    _ensure_partner(db, user.tenant_id, partner_id)
    c = db.get(PartnerContact, contact_id)
    if not c or c.tenant_id != user.tenant_id or c.partner_id != partner_id:
        raise HTTPException(status_code=404, detail="联系人不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        data["name"] = data["name"].strip()
    for k, v in data.items():
        setattr(c, k, v)
    if c.is_primary:
        _clear_other_primary(db, partner_id, c.id)
    db.commit()
    db.refresh(c)
    return ok(_contact_out(c).model_dump(mode="json"))


@router.delete("/{partner_id}/contacts/{contact_id}")
def delete_contact(
    partner_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    p = _ensure_partner(db, user.tenant_id, partner_id)
    c = db.get(PartnerContact, contact_id)
    if not c or c.tenant_id != user.tenant_id or c.partner_id != partner_id:
        raise HTTPException(status_code=404, detail="联系人不存在")
    was_primary = c.is_primary
    db.delete(c)
    db.flush()
    if was_primary:
        nxt = db.scalar(
            select(PartnerContact)
            .where(PartnerContact.partner_id == partner_id, PartnerContact.is_active.is_(True))
            .order_by(PartnerContact.sort_order, PartnerContact.id)
        )
        if nxt:
            nxt.is_primary = True
    db.commit()
    return ok({"deleted": True, "partner_id": p.id})
