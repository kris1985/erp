"""备料交付与经营：齐套、采购、出货、应收、回款、利润。"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Optional

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import User
from app.schemas.common import normalize_page, ok, page_payload, paginate_sequence
from app.services import finance_service, material_service, purchase_service, shipment_service
from app.services.order_service import OrderError, get_order

router = APIRouter(tags=["supply-chain"])


def _http(exc: Exception):
    msg = getattr(exc, "message", str(exc))
    raise HTTPException(status_code=400, detail=msg) from exc


# ----- materials / kit -----


class MaterialPatch(BaseModel):
    loss_rate: Optional[Decimal] = None
    qty_per_pair: Optional[Decimal] = None
    is_customer_supplied: Optional[bool] = None
    notes: Optional[str] = None
    arrived_qty: Optional[Decimal] = None
    consume_process_id: Optional[int] = None
    clear_consume_process: bool = False


class MaterialAdd(BaseModel):
    supplier_product_id: int
    qty_per_pair: Decimal = Decimal("1")
    loss_rate: Decimal = Decimal("0")
    is_customer_supplied: bool = False


class ReleaseIn(BaseModel):
    qty: Decimal = Field(gt=0)
    deduct_shared: bool = False


class AllocateIn(BaseModel):
    qty: Decimal = Field(gt=0)


class ShortagePurchaseIn(BaseModel):
    order_ids: Optional[list[int]] = None
    requirement_ids: Optional[list[int]] = None
    include_shared: bool = True


class SharedAdjustIn(BaseModel):
    supplier_product_id: int
    qty_delta: Decimal
    unit_cost: Optional[Decimal] = None
    note: str = Field(min_length=1)


@router.get("/orders/{order_id}/materials")
def api_order_materials(
    order_id: int,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = material_service.get_order_kit(
            db, user.tenant_id, order_id, include_shared=include_shared
        )
        db.commit()
        return ok(data)
    except material_service.MaterialError as e:
        _http(e)


@router.post("/orders/{order_id}/materials/refresh")
def api_refresh_materials(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = get_order(db, user.tenant_id, order_id)
        material_service.refresh_from_bom(db, user.tenant_id, order, keep_progress=True)
        db.commit()
        return ok(material_service.get_order_kit(db, user.tenant_id, order_id))
    except (OrderError, material_service.MaterialError) as e:
        _http(e)


@router.post("/orders/{order_id}/materials/recalculate")
def api_recalc_materials(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = get_order(db, user.tenant_id, order_id)
        material_service.recalculate_required(db, user.tenant_id, order)
        db.commit()
        return ok(material_service.get_order_kit(db, user.tenant_id, order_id))
    except (OrderError, material_service.MaterialError) as e:
        _http(e)


@router.post("/orders/{order_id}/materials")
def api_add_material(
    order_id: int,
    body: MaterialAdd,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            material_service.add_requirement(
                db,
                user.tenant_id,
                order_id,
                supplier_product_id=body.supplier_product_id,
                qty_per_pair=body.qty_per_pair,
                loss_rate=body.loss_rate,
                is_customer_supplied=body.is_customer_supplied,
            )
        )
    except material_service.MaterialError as e:
        _http(e)


@router.patch("/orders/{order_id}/materials/{req_id}")
def api_patch_material(
    order_id: int,
    req_id: int,
    body: MaterialPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        data = body.model_dump(exclude_unset=True)
        clear = bool(data.pop("clear_consume_process", False))
        if clear:
            data["clear_consume_process"] = True
            data.pop("consume_process_id", None)
        return ok(material_service.patch_requirement(db, user.tenant_id, req_id, **data))
    except material_service.MaterialError as e:
        _http(e)


@router.delete("/orders/{order_id}/materials/{req_id}")
def api_del_material(
    order_id: int,
    req_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        material_service.delete_requirement(db, user.tenant_id, req_id)
        return ok({"deleted": True})
    except material_service.MaterialError as e:
        _http(e)


@router.post("/orders/{order_id}/materials/{req_id}/release")
def api_release_material(
    order_id: int,
    req_id: int,
    body: ReleaseIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            material_service.release_to_workshop(
                db,
                user.tenant_id,
                order_id,
                req_id,
                body.qty,
                deduct_shared=body.deduct_shared,
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        _http(e)


def _require_cap(db: Session, tenant_id: int, code: str) -> None:
    from app.services import inventory_settings

    inv = inventory_settings.get_inventory_by_tenant_id(db, tenant_id)
    if not inventory_settings.has_capability(inv, code):
        raise HTTPException(status_code=403, detail=f"capability_disabled:{code}")


@router.post("/orders/{order_id}/materials/{req_id}/allocate")
def api_allocate_material(
    order_id: int,
    req_id: int,
    body: AllocateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _require_cap(db, user.tenant_id, "allocate_ui")
    try:
        return ok(
            material_service.allocate_from_pool(
                db,
                user.tenant_id,
                order_id,
                req_id,
                body.qty,
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        _http(e)


@router.post("/orders/{order_id}/materials/{req_id}/deallocate")
def api_deallocate_material(
    order_id: int,
    req_id: int,
    body: AllocateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _require_cap(db, user.tenant_id, "allocate_ui")
    try:
        return ok(
            material_service.deallocate_to_pool(
                db,
                user.tenant_id,
                order_id,
                req_id,
                body.qty,
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        _http(e)


@router.get("/stock-allocate/candidates")
def api_allocate_candidates(
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _require_cap(db, user.tenant_id, "allocate_ui")
    return ok(material_service.list_allocate_candidates(db, user.tenant_id, keyword=keyword))


class StockDocCreateIn(BaseModel):
    doc_type: str  # issue | return_mat
    order_id: int
    notes: Optional[str] = None
    lines: list[dict]  # [{requirement_id, qty}]


@router.get("/stock-issues")
def api_list_stock_docs(
    order_id: Optional[int] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _require_cap(db, user.tenant_id, "stock_docs")
    from app.services import stock_doc_service

    return ok(
        stock_doc_service.list_stock_docs(
            db,
            user.tenant_id,
            order_id=order_id,
            doc_type=doc_type,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/stock-issues/candidates")
def api_stock_issue_candidates(
    order_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _require_cap(db, user.tenant_id, "stock_docs")
    from app.services import stock_doc_service

    try:
        return ok(stock_doc_service.list_issue_candidates(db, user.tenant_id, order_id))
    except material_service.MaterialError as e:
        _http(e)


@router.post("/stock-issues")
def api_submit_stock_doc(
    body: StockDocCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """车间提报：生成待确认领/退料单。"""
    _require_cap(db, user.tenant_id, "stock_docs")
    from app.services import stock_doc_service

    try:
        return ok(
            stock_doc_service.submit_stock_doc(
                db,
                user.tenant_id,
                doc_type=body.doc_type,
                order_id=body.order_id,
                lines=body.lines,
                notes=body.notes,
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        _http(e)


@router.post("/stock-issues/{doc_id}/confirm")
def api_confirm_stock_doc(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """仓管确认过账。"""
    _require_cap(db, user.tenant_id, "stock_docs")
    from app.services import stock_doc_service

    try:
        return ok(stock_doc_service.confirm_stock_doc(db, user.tenant_id, doc_id, user_id=user.id))
    except material_service.MaterialError as e:
        _http(e)


@router.post("/stock-issues/{doc_id}/void")
def api_void_stock_doc(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """作废待确认单。"""
    _require_cap(db, user.tenant_id, "stock_docs")
    from app.services import stock_doc_service

    try:
        return ok(stock_doc_service.void_stock_doc(db, user.tenant_id, doc_id, user_id=user.id))
    except material_service.MaterialError as e:
        _http(e)


@router.get("/material-shortages")
def api_shortages(
    order_ids: Optional[str] = None,
    include_shared: bool = True,
    keyword: Optional[str] = None,
    partner_id: Optional[int] = None,
    order_no: Optional[str] = None,
    rush_only: bool = False,
    hide_purchased: bool = True,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ids = [int(x) for x in order_ids.split(",") if x.strip().isdigit()] if order_ids else None
    rows = material_service.list_shortages(
        db,
        user.tenant_id,
        order_ids=ids,
        include_shared=include_shared,
        keyword=keyword,
        partner_id=partner_id,
        order_no=order_no,
        rush_only=rush_only,
        hide_purchased=hide_purchased,
    )
    return ok(paginate_sequence(rows, page, page_size))


@router.post("/purchase-orders/from-shortages")
def api_po_from_shortages(
    body: ShortagePurchaseIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.create_drafts_from_shortages(
                db,
                user.tenant_id,
                order_ids=body.order_ids,
                requirement_ids=body.requirement_ids,
                include_shared=body.include_shared,
                user_id=user.id,
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/orders/{order_id}/purchase-drafts")
def api_order_purchase_drafts(
    order_id: int,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.create_drafts_from_shortages(
                db,
                user.tenant_id,
                order_ids=[order_id],
                include_shared=include_shared,
                user_id=user.id,
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


# ----- purchase orders -----


class PoUpdate(BaseModel):
    expected_date: Optional[date] = None
    logistics_company: Optional[str] = None
    tracking_no: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[list[dict]] = None


class PoSummaryPriceIn(BaseModel):
    supplier_product_id: int
    unit_price: Decimal


class PoReceiveIn(BaseModel):
    lines: list[dict]  # [{line_id, qty}]


class PoShipIn(BaseModel):
    logistics_company: Optional[str] = None
    tracking_no: Optional[str] = None


class PoSplitIn(BaseModel):
    line_ids: list[int]


@router.get("/purchase-orders")
def api_list_po(
    status: Optional[str] = None,
    partner_id: Optional[int] = None,
    order_id: Optional[int] = None,
    delivery_alert: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = purchase_service.list_pos(
        db,
        user.tenant_id,
        status=status,
        partner_id=partner_id,
        order_id=order_id,
        delivery_alert=delivery_alert,
    )
    return ok(paginate_sequence(rows, page, page_size))


@router.get("/purchase-orders/{po_id}")
def api_get_po(po_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return ok(purchase_service._po_out(db, purchase_service.get_po(db, user.tenant_id, po_id)))
    except purchase_service.PurchaseError as e:
        _http(e)


@router.get("/purchase-orders/{po_id}/qr.png")
def api_po_qr_png(
    po_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """采购单二维码：扫码打开公开只读预览页（免登录）。"""
    try:
        po = purchase_service.get_po(db, user.tenant_id, po_id)
        token = purchase_service.ensure_public_token(db, po)
        db.commit()
    except purchase_service.PurchaseError as e:
        _http(e)
    base = str(request.base_url).rstrip("/")
    url = f"{base}/po/{token}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="po_{po.po_no}.png"'},
    )


@router.get("/purchase-orders/{po_id}/export")
def api_export_po(
    po_id: int,
    request: Request,
    internal: bool = Query(False, description="是否含内部分订单明细"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出采购单 Excel（版式对齐打印预览）。"""
    from datetime import datetime
    from urllib.parse import quote

    from app.services.purchase_order_export import build_purchase_order_workbook

    try:
        po = purchase_service.get_po(db, user.tenant_id, po_id)
        token = purchase_service.ensure_public_token(db, po)
        db.commit()
        detail = purchase_service._po_out(db, po)
    except purchase_service.PurchaseError as e:
        _http(e)
    base = str(request.base_url).rstrip("/")
    public_url = f"{base}/po/{token}"
    content = build_purchase_order_workbook(
        detail,
        include_internal=internal,
        public_url=public_url,
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    po_no = detail.get("po_no") or str(po_id)
    filename = f"采购单_{po_no}_{stamp}.xlsx"
    ascii_name = f"po_{po_id}_{stamp}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/public/purchase-orders/{token}")
def api_public_po(token: str, db: Session = Depends(get_db)):
    """公开采购单预览（免登录，只读供应商联）。"""
    try:
        po = purchase_service.get_po_by_public_token(db, token)
        return ok(purchase_service.public_po_out(db, po))
    except purchase_service.PurchaseError as e:
        raise HTTPException(status_code=404, detail=getattr(e, "message", str(e))) from e


@router.get("/public/purchase-orders/{token}/qr.png")
def api_public_po_qr(token: str, request: Request, db: Session = Depends(get_db)):
    """公开二维码图（免登录）。"""
    try:
        po = purchase_service.get_po_by_public_token(db, token)
    except purchase_service.PurchaseError as e:
        raise HTTPException(status_code=404, detail=getattr(e, "message", str(e))) from e
    base = str(request.base_url).rstrip("/")
    url = f"{base}/po/{po.public_token}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="po_{po.po_no}.png"'},
    )


@router.patch("/purchase-orders/{po_id}")
def api_patch_po(
    po_id: int,
    body: PoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.update_po(
                db,
                user.tenant_id,
                po_id,
                expected_date=body.expected_date,
                logistics_company=body.logistics_company,
                tracking_no=body.tracking_no,
                notes=body.notes,
                lines=body.lines,
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


@router.patch("/purchase-orders/{po_id}/summary-price")
def api_po_summary_price(
    po_id: int,
    body: PoSummaryPriceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """草稿：按物料改汇总单价，同步到分订单行。"""
    try:
        return ok(
            purchase_service.set_summary_unit_price(
                db,
                user.tenant_id,
                po_id,
                body.supplier_product_id,
                body.unit_price,
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/submit")
def api_submit_po(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(purchase_service.submit_po(db, user.tenant_id, po_id))
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/ship")
def api_ship_po(
    po_id: int,
    body: PoShipIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.mark_shipped(
                db,
                user.tenant_id,
                po_id,
                logistics_company=body.logistics_company,
                tracking_no=body.tracking_no,
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/receive")
def api_receive_po(
    po_id: int,
    body: PoReceiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.receive_po(
                db, user.tenant_id, po_id, body.lines, user_id=user.id
            )
        )
    except (purchase_service.PurchaseError, material_service.MaterialError) as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/cancel")
def api_cancel_po(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(purchase_service.cancel_po(db, user.tenant_id, po_id))
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/close-open")
def api_close_po(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(purchase_service.close_open_qty(db, user.tenant_id, po_id))
    except purchase_service.PurchaseError as e:
        _http(e)


@router.post("/purchase-orders/{po_id}/split")
def api_split_po(
    po_id: int,
    body: PoSplitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            purchase_service.split_lines_to_new_po(
                db, user.tenant_id, po_id, body.line_ids, user_id=user.id
            )
        )
    except purchase_service.PurchaseError as e:
        _http(e)


# ----- shared stock -----


@router.get("/shared-materials")
def api_shared_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ok(material_service.list_shared_stocks(db, user.tenant_id))


@router.get("/shared-materials/ledgers")
def api_shared_ledgers(
    supplier_product_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        material_service.list_shared_ledgers(
            db,
            user.tenant_id,
            supplier_product_id=supplier_product_id,
            limit=limit,
        )
    )


@router.post("/shared-materials/adjust")
def api_shared_adjust(
    body: SharedAdjustIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="调整库存须填写备注")
    try:
        stock = material_service.adjust_shared_stock(
            db,
            user.tenant_id,
            body.supplier_product_id,
            body.qty_delta,
            unit_cost=body.unit_cost,
            note=note,
            user_id=user.id,
        )
        db.commit()
        return ok(
            {
                "supplier_product_id": stock.supplier_product_id,
                "qty": stock.qty,
                "avg_unit_cost": stock.avg_unit_cost,
            }
        )
    except material_service.MaterialError as e:
        _http(e)


# ----- shipments -----


class ShipmentCreate(BaseModel):
    order_id: int
    lines: list[dict]
    ship_date: Optional[date] = None
    logistics_company: Optional[str] = None
    tracking_no: Optional[str] = None
    notes: Optional[str] = None
    confirm: bool = False


@router.get("/shipments")
def api_list_shipments(
    order_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = shipment_service.list_shipments(db, user.tenant_id, order_id=order_id, status=status)
    return ok(paginate_sequence(rows, page, page_size))


@router.get("/orders/{order_id}/delivery")
def api_order_delivery(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return ok(shipment_service.order_delivery_summary(db, user.tenant_id, order_id))
    except shipment_service.ShipmentError as e:
        _http(e)


@router.post("/shipments")
def api_create_shipment(
    body: ShipmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            shipment_service.create_shipment(
                db,
                user.tenant_id,
                order_id=body.order_id,
                lines=body.lines,
                ship_date=body.ship_date,
                logistics_company=body.logistics_company,
                tracking_no=body.tracking_no,
                notes=body.notes,
                user_id=user.id,
                confirm=body.confirm,
            )
        )
    except shipment_service.ShipmentError as e:
        _http(e)


@router.post("/shipments/{shipment_id}/confirm")
def api_confirm_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(shipment_service.confirm_shipment(db, user.tenant_id, shipment_id))
    except shipment_service.ShipmentError as e:
        _http(e)


@router.post("/shipments/{shipment_id}/void")
def api_void_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(shipment_service.void_shipment(db, user.tenant_id, shipment_id))
    except shipment_service.ShipmentError as e:
        _http(e)


# ----- finance -----


class ArAdjustIn(BaseModel):
    adjustment_delta: Decimal
    notes: Optional[str] = None


class PaymentCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str
    amount: Decimal
    payment_date: date
    method: str = "other"
    voucher_no: Optional[str] = None
    notes: Optional[str] = None
    allocations: list[dict]


@router.get("/receivables")
def api_list_ar(
    customer_id: Optional[int] = None,
    order_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = finance_service.list_receivables(
        db, user.tenant_id, customer_id=customer_id, order_id=order_id, status=status
    )
    return ok(paginate_sequence(rows, page, page_size))


@router.get("/receivables/customer-summary")
def api_ar_customer_summary(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = finance_service.customer_ar_summary(db, user.tenant_id)
    return ok(paginate_sequence(rows, page, page_size))


@router.post("/receivables/{ar_id}/adjust")
def api_ar_adjust(
    ar_id: int,
    body: ArAdjustIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            finance_service.adjust_receivable(
                db, user.tenant_id, ar_id, body.adjustment_delta, notes=body.notes
            )
        )
    except finance_service.FinanceError as e:
        _http(e)


@router.get("/payments")
def api_list_payments(
    customer_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    rows = finance_service.list_payments(db, user.tenant_id, customer_id=customer_id)
    return ok(paginate_sequence(rows, page, page_size))


@router.post("/payments")
def api_create_payment(
    body: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            finance_service.create_payment(
                db,
                user.tenant_id,
                customer_id=body.customer_id,
                customer_name=body.customer_name,
                amount=body.amount,
                payment_date=body.payment_date,
                method=body.method,
                voucher_no=body.voucher_no,
                notes=body.notes,
                allocations=body.allocations,
                user_id=user.id,
            )
        )
    except finance_service.FinanceError as e:
        _http(e)


@router.post("/payments/{payment_id}/void")
def api_void_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(finance_service.void_payment(db, user.tenant_id, payment_id, user_id=user.id))
    except finance_service.FinanceError as e:
        _http(e)


@router.get("/orders/{order_id}/profit")
def api_order_profit(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return ok(finance_service.order_profit(db, user.tenant_id, order_id))
    except finance_service.FinanceError as e:
        _http(e)


@router.get("/profit-report")
def api_profit_report(
    year: Optional[int] = None,
    month: Optional[int] = None,
    customer_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = finance_service.profit_report(
        db, user.tenant_id, year=year, month=month, customer_id=customer_id
    )
    orders = data.get("orders") or []
    paged = paginate_sequence(orders, page, page_size)
    return ok(
        {
            "year": data.get("year"),
            "month": data.get("month"),
            "summary": data.get("summary"),
            "orders": paged["items"],
            "items": paged["items"],
            "total": paged["total"],
            "page": paged["page"],
            "page_size": paged["page_size"],
        }
    )


@router.get("/business-kpi")
def api_business_kpi(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services import team_service

    if team_service.is_team_scoped(db, user):
        raise HTTPException(status_code=403, detail="组长账号不可查看经营财务")
    return ok(finance_service.business_kpi(db, user.tenant_id, year=year, month=month))
