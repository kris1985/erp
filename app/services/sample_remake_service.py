"""复版明细：样品寄送单（单头 + 多行样品）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import OwnProduct, Partner, SampleRemake, SampleRemakeLine
from app.schemas.common import page_payload


def _money(value: Decimal | float | int | str | None) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError) as err:
        raise ValueError("unit_price_invalid") from err
    return amount.quantize(Decimal("0.0001"))


def _text(value: str | None, *, limit: int) -> str:
    return (value or "").strip()[:limit]


def _optional(value: str | None, *, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] or None


def _next_delivery_no(db: Session, tenant_id: int, day: date) -> str:
    prefix = f"FB{day.strftime('%Y%m%d')}"
    rows = db.scalars(
        select(SampleRemake.delivery_no).where(
            SampleRemake.tenant_id == tenant_id,
            SampleRemake.delivery_no.like(f"{prefix}%"),
        )
    ).all()
    seq = 0
    for no in rows:
        tail = (no or "")[len(prefix) :]
        if tail.isdigit():
            seq = max(seq, int(tail))
    return f"{prefix}{seq + 1:03d}"


def _customer(db: Session, tenant_id: int, customer_id: int) -> Partner:
    partner = db.get(Partner, customer_id)
    if (
        partner is None
        or partner.tenant_id != tenant_id
        or not partner.is_customer
        or not partner.is_active
    ):
        raise ValueError("customer_not_found")
    return partner


def _line_out(line: SampleRemakeLine) -> dict:
    qty = int(line.qty or 0)
    unit = Decimal(line.unit_price or 0)
    total = (unit * qty).quantize(Decimal("0.01"))
    return {
        "id": line.id,
        "sort_order": line.sort_order,
        "brand": line.brand or "",
        "own_product_id": line.own_product_id,
        "factory_model": line.factory_model or "",
        "image_url": line.image_url,
        "color": line.color or "",
        "qty": qty,
        "unit_price": float(unit),
        "total_price": float(total),
    }


def _out(row: SampleRemake) -> dict:
    lines = [_line_out(line) for line in row.lines or []]
    return {
        "id": row.id,
        "remake_date": row.remake_date.isoformat() if row.remake_date else None,
        "delivery_no": row.delivery_no,
        "courier_company": row.courier_company or "",
        "tracking_no": row.tracking_no or "",
        "customer_id": row.customer_id,
        "customer_name": row.customer_name or "",
        "line_count": len(lines),
        "total_qty": sum(line["qty"] for line in lines),
        "total_amount": float(sum(Decimal(str(line["total_price"])) for line in lines)),
        "statement_id": row.statement_id,
        "lines": lines,
    }


def _load(db: Session, tenant_id: int, remake_id: int) -> SampleRemake:
    row = db.scalar(
        select(SampleRemake)
        .options(selectinload(SampleRemake.lines))
        .where(SampleRemake.tenant_id == tenant_id, SampleRemake.id == remake_id)
    )
    if row is None:
        raise ValueError("not_found")
    return row


def _normalize_lines(db: Session, tenant_id: int, lines: list[dict]) -> list[dict]:
    if not lines:
        raise ValueError("lines_required")
    cleaned: list[dict] = []
    for raw in lines:
        factory_model = _text(raw.get("factory_model"), limit=80)
        if not factory_model:
            raise ValueError("factory_model_required")
        brand = _text(raw.get("brand"), limit=100)
        color = _text(raw.get("color"), limit=50)
        try:
            qty = int(raw.get("qty") or 0)
        except (TypeError, ValueError) as err:
            raise ValueError("qty_invalid") from err
        if qty <= 0:
            raise ValueError("qty_invalid")
        unit_price = _money(raw.get("unit_price"))
        if unit_price < 0:
            raise ValueError("unit_price_invalid")
        own_product_id = raw.get("own_product_id")
        product_id: int | None = None
        if own_product_id not in (None, "", 0):
            try:
                product_id = int(own_product_id)
            except (TypeError, ValueError) as err:
                raise ValueError("product_not_found") from err
            product = db.get(OwnProduct, product_id)
            if product is None or product.tenant_id != tenant_id:
                raise ValueError("product_not_found")
        raw_image = str(raw.get("image_url") or "").strip()
        if len(raw_image) > 255:
            raise ValueError("image_too_long")
        image_url = raw_image or None
        cleaned.append(
            {
                "brand": brand,
                "own_product_id": product_id,
                "factory_model": factory_model,
                "image_url": image_url,
                "color": color,
                "qty": qty,
                "unit_price": unit_price,
            }
        )
    return cleaned


def _apply_lines(row: SampleRemake, tenant_id: int, lines: list[dict]) -> None:
    row.lines.clear()
    for index, line in enumerate(lines):
        row.lines.append(
            SampleRemakeLine(
                tenant_id=tenant_id,
                sort_order=index,
                brand=line["brand"],
                own_product_id=line["own_product_id"],
                factory_model=line["factory_model"],
                image_url=line["image_url"],
                color=line["color"],
                qty=line["qty"],
                unit_price=line["unit_price"],
            )
        )


def _delivery_no(
    db: Session,
    tenant_id: int,
    day: date,
    delivery_no: str | None,
    *,
    exclude_id: int | None = None,
) -> str:
    text = (delivery_no or "").strip()
    if not text:
        return _next_delivery_no(db, tenant_id, day)
    if len(text) > 40:
        raise ValueError("delivery_no_too_long")
    taken_q = select(SampleRemake.id).where(
        SampleRemake.tenant_id == tenant_id,
        SampleRemake.delivery_no == text,
    )
    if exclude_id is not None:
        taken_q = taken_q.where(SampleRemake.id != exclude_id)
    taken = db.scalar(taken_q)
    if taken:
        raise ValueError("delivery_no_taken")
    return text


def list_remakes(
    db: Session,
    tenant_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(SampleRemake).where(SampleRemake.tenant_id == tenant_id)
    if date_from is not None:
        q = q.where(SampleRemake.remake_date >= date_from)
    if date_to is not None:
        q = q.where(SampleRemake.remake_date <= date_to)
    if customer_id is not None:
        q = q.where(SampleRemake.customer_id == customer_id)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        line_match = exists().where(
            SampleRemakeLine.remake_id == SampleRemake.id,
            or_(
                SampleRemakeLine.brand.ilike(like),
                SampleRemakeLine.factory_model.ilike(like),
                SampleRemakeLine.color.ilike(like),
            ),
        )
        q = q.where(
            or_(
                SampleRemake.delivery_no.ilike(like),
                SampleRemake.tracking_no.ilike(like),
                SampleRemake.courier_company.ilike(like),
                SampleRemake.customer_name.ilike(like),
                line_match,
            )
        )
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.scalars(
        q.options(selectinload(SampleRemake.lines))
        .order_by(SampleRemake.remake_date.desc(), SampleRemake.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return page_payload([_out(row) for row in rows], int(total), page, page_size)


def get_remake(db: Session, tenant_id: int, remake_id: int) -> dict:
    return _out(_load(db, tenant_id, remake_id))


def create_remake(
    db: Session,
    tenant_id: int,
    *,
    remake_date: date,
    delivery_no: str | None,
    courier_company: str | None,
    tracking_no: str | None,
    customer_id: int,
    lines: list[dict],
    created_by: int | None,
) -> dict:
    partner = _customer(db, tenant_id, customer_id)
    cleaned = _normalize_lines(db, tenant_id, lines)
    number = _delivery_no(db, tenant_id, remake_date, delivery_no)
    row = SampleRemake(
        tenant_id=tenant_id,
        remake_date=remake_date,
        delivery_no=number,
        courier_company=_optional(courier_company, limit=50),
        tracking_no=_optional(tracking_no, limit=80),
        customer_id=partner.id,
        customer_name=partner.name,
        created_by=created_by,
    )
    _apply_lines(row, tenant_id, cleaned)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise ValueError("delivery_no_taken") from err
    return get_remake(db, tenant_id, row.id)


def _ensure_editable(row: SampleRemake) -> None:
    if row.statement_id:
        raise ValueError("already_statemented")


def update_remake(
    db: Session,
    tenant_id: int,
    remake_id: int,
    *,
    remake_date: date,
    delivery_no: str | None,
    courier_company: str | None,
    tracking_no: str | None,
    customer_id: int,
    lines: list[dict],
) -> dict:
    row = _load(db, tenant_id, remake_id)
    _ensure_editable(row)
    partner = _customer(db, tenant_id, customer_id)
    cleaned = _normalize_lines(db, tenant_id, lines)
    row.remake_date = remake_date
    row.delivery_no = _delivery_no(
        db, tenant_id, remake_date, delivery_no, exclude_id=row.id
    )
    row.courier_company = _optional(courier_company, limit=50)
    row.tracking_no = _optional(tracking_no, limit=80)
    row.customer_id = partner.id
    row.customer_name = partner.name
    _apply_lines(row, tenant_id, cleaned)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise ValueError("delivery_no_taken") from err
    return get_remake(db, tenant_id, remake_id)


def delete_remake(db: Session, tenant_id: int, remake_id: int) -> dict:
    row = _load(db, tenant_id, remake_id)
    _ensure_editable(row)
    db.delete(row)
    db.commit()
    return {"id": remake_id}
