#!/usr/bin/env python3
"""清本地租户业务单数据，并走查 AU 主路径收口。

用法:
  .venv/bin/python scripts/walkthrough_au_main_path.py           # 清库 + 走查
  .venv/bin/python scripts/walkthrough_au_main_path.py --purge-only
  .venv/bin/python scripts/walkthrough_au_main_path.py --skip-purge
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal, engine
from app.db_schema import ensure_schema
from app.models import (
    Color,
    FgLedger,
    OwnProduct,
    PackingPlanStatus,
    Partner,
    Receivable,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
)
from app.services.execution_service import (
    create_execution,
    create_execution_from_sales_line,
    cut_cards_for_execution,
    cut_cards_for_header,
    list_execution_headers,
)
from app.services.fg_service import (
    direct_ship_basket,
    list_fg_ledgers,
    list_fg_stocks,
    ship_warehoused_basket,
    warehouse_basket,
)
from app.services.packing_service import create_basket_prepack, list_shipment_packing_cartons
from app.services.sales_order_service import confirm_sales_order_line


TENANT_ID = 1

# 业务单据 / 流水（保留主数据：款/色/码/伙伴/员工/权限等）
PURGE_TABLES = [
    "payment_allocations",
    "payments",
    "supplier_payment_allocations",
    "supplier_payments",
    "receivables",
    "payables",
    "shipment_lines",
    "shipments",
    "packing_carton_lines",
    "packing_cartons",
    "packing_plans",
    "fg_ledgers",
    "fg_stocks",
    "sales_line_labor_allocations",
    "work_log_group_shares",
    "work_logs",
    "defect_events",
    "rework_tasks",
    "trace_unit_logs",
    "order_process_assignments",
    "material_releases",
    "material_iqc_records",
    "customer_supply_receipts",
    "stock_doc_lines",
    "stock_docs",
    "shared_material_ledgers",
    "order_change_logs",
    "order_material_requirements",
    "order_processes",
    "order_items",
    "merge_batch_members",
    "merge_batches",
    "execution_allocations",
    "schedule_draft_assignments",
    "schedule_draft_lines",
    "schedule_drafts",
    "execution_schedule_drafts",
    "pending_slots",
    "purchase_order_lines",
    "purchase_orders",
    "sales_order_line_items",
    "sales_order_lines",
    "sales_orders",
    "spec_execution_orders",
    "execution_headers",
    "trace_units",
    "orders",
    "salary_acknowledgements",
    "other_cost_items",
]


results: list[tuple[str, bool, str]] = []


def retry_deadlock(fn, *, tries: int = 4, label: str = "op"):
    last = None
    for i in range(tries):
        try:
            return fn()
        except OperationalError as e:
            last = e
            if "Deadlock" not in str(e) and "1213" not in str(e):
                raise
            print(f"  ! deadlock on {label}, retry {i + 1}/{tries}")
            time.sleep(0.3 * (i + 1))
    raise last  # type: ignore[misc]


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def purge_tenant_orders(tenant_id: int = TENANT_ID) -> None:
    ensure_schema()
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        existing = {r[0] for r in conn.execute(text("SHOW TABLES")).fetchall()}
        for table in PURGE_TABLES:
            if table not in existing:
                continue
            cols = {
                r[0]
                for r in conn.execute(text(f"SHOW COLUMNS FROM `{table}`")).fetchall()
            }
            if "tenant_id" in cols:
                n = conn.execute(
                    text(f"DELETE FROM `{table}` WHERE tenant_id=:tid"),
                    {"tid": tenant_id},
                ).rowcount
            else:
                # 少数明细表无 tenant_id，整表清（本库单租户演示）
                n = conn.execute(text(f"DELETE FROM `{table}`")).rowcount
            print(f"  purged {table}: {n}")
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    print("==> purge done")


def _pick_masters(db):
    product = db.scalar(
        select(OwnProduct).where(
            OwnProduct.tenant_id == TENANT_ID,
            OwnProduct.product_code == "OP-RUN-01",
            OwnProduct.is_active.is_(True),
        )
    ) or db.scalar(
        select(OwnProduct).where(
            OwnProduct.tenant_id == TENANT_ID,
            OwnProduct.trace_enabled.is_(True),
            OwnProduct.is_active.is_(True),
        )
    )
    if not product:
        raise RuntimeError("无可用自有产品（需 trace_enabled）")
    product.trace_enabled = True
    color = db.scalar(
        select(Color).where(Color.tenant_id == TENANT_ID, Color.name == "黑")
    ) or db.scalar(select(Color).where(Color.tenant_id == TENANT_ID).limit(1))
    size = db.scalar(
        select(Size).where(Size.tenant_id == TENANT_ID, Size.size_value == "40")
    ) or db.scalar(select(Size).where(Size.tenant_id == TENANT_ID).limit(1))
    partner = db.scalar(
        select(Partner).where(
            Partner.tenant_id == TENANT_ID,
            Partner.is_customer.is_(True),
            Partner.is_active.is_(True),
        )
    )
    if not color or not size:
        raise RuntimeError("缺颜色或尺码主数据")
    return product, color, size, partner


def _make_so_item(db, *, order_no: str, qty: int, product, color, size, partner, customer_name: str):
    so = SalesOrder(
        tenant_id=TENANT_ID,
        order_no=order_no,
        customer_id=partner.id if partner else None,
        customer_name=customer_name,
        ordered_at=date.today(),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=TENANT_ID,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=qty,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=TENANT_ID,
        sales_order_line_id=line.id,
        color_id=color.id,
        size_id=size.id,
        qty=qty,
        allocated_qty=0,
        produced_qty=0,
        shipped_qty=0,
    )
    db.add(item)
    db.flush()
    return so, line, item


def walkthrough(db) -> int:
    product, color, size, partner = _pick_masters(db)
    db.commit()
    check(
        "主数据就绪",
        True,
        f"{product.product_code} / {color.name} / {size.size_value}",
    )

    # --- Path A: 确认接单 → 建执行单头 → 开裁 → 预装 → 入库留仓 ---
    so_a, line_a, item_a = _make_so_item(
        db,
        order_no="SO-WALK-WH",
        qty=24,
        product=product,
        color=color,
        size=size,
        partner=partner,
        customer_name=(partner.short_name or partner.name) if partner else "走查客户甲",
    )
    db.commit()
    so_a = confirm_sales_order_line(
        db, tenant_id=TENANT_ID, sales_order_id=so_a.id, line_id=line_a.id, created_by=1
    )
    check(
        "A1 确认接单",
        so_a is not None and so_a.status == SalesOrderStatus.confirmed,
        f"so={so_a.order_no} status={so_a.status}",
    )
    db.refresh(line_a)
    hdr = create_execution_from_sales_line(
        db,
        tenant_id=TENANT_ID,
        sales_order=so_a,
        line=line_a,
        created_by=1,
        commit=True,
    )
    check("A1b 执行单头已建", bool(hdr), getattr(hdr, "header_no", None) or "")
    if not hdr:
        return 1
    cut = cut_cards_for_header(
        db,
        tenant_id=TENANT_ID,
        header_id=int(hdr.id),
        dry_run=False,
        bundle_size=24,
        mode="basket_bundles",
    )
    created = cut.get("created") or []
    baskets = [u for u in created if u.get("unit_type") == "basket" or u.get("unit_type") == TraceUnitType.basket.value]
    # created may not include unit_type — fetch
    if not baskets and created:
        baskets = created
    basket_ids = []
    for row in created:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == "basket":
            basket_ids.append(tu.id)
    check("A2 开裁出筐", bool(basket_ids), f"baskets={basket_ids} created={len(created)}")
    if not basket_ids:
        return 1
    basket_wh = basket_ids[0]
    pre = create_basket_prepack(db, TENANT_ID, basket_wh, pairs_per_carton=12)
    check(
        "A3 预装箱",
        pre.get("id") and int(pre.get("carton_count") or pre.get("cartons") and len(pre["cartons"]) or 0) >= 1
        or bool(pre.get("id")),
        f"plan={pre.get('id')} cartons≈{pre.get('carton_count') or len(pre.get('cartons') or [])}",
    )
    wh = warehouse_basket(db, tenant_id=TENANT_ID, trace_unit_id=basket_wh, note="走查入库")
    check(
        "A4 成品入库",
        wh.get("status") == "warehoused" and int(wh.get("qty") or 0) == 24,
        f"fg_qty={wh.get('fg_qty')} splits={wh.get('produced_splits')}",
    )
    stocks = list_fg_stocks(db, tenant_id=TENANT_ID, only_positive=True)
    check("A5 成品仓有结存", any(int(s["qty"]) >= 24 for s in stocks), str(stocks[:2]))
    ledgers = list_fg_ledgers(db, tenant_id=TENANT_ID, fg_stock_id=stocks[0]["id"]) if stocks else []
    check("A6 入库流水", any(x["direction"] == "in" and x["qty"] == 24 for x in ledgers), f"n={len(ledgers)}")

    # --- Path B: 合单 → 预装 → 入库 → 从 FG 出货 ---
    _, _, item_b1 = _make_so_item(
        db,
        order_no="SO-WALK-A",
        qty=30,
        product=product,
        color=color,
        size=size,
        partner=partner,
        customer_name="走查客户A",
    )
    _, _, item_b2 = _make_so_item(
        db,
        order_no="SO-WALK-B",
        qty=20,
        product=product,
        color=color,
        size=size,
        partner=partner,
        customer_name="走查客户B",
    )
    db.commit()
    # mark confirmed-ish for allocation (create_execution expects items available)
    for it in (item_b1, item_b2):
        so_line = db.get(SalesOrderLine, it.sales_order_line_id)
        so = db.get(SalesOrder, so_line.sales_order_id)
        so.status = SalesOrderStatus.confirmed
        so_line.status = SalesOrderLineStatus.in_production
    db.commit()

    exe = create_execution(
        db,
        tenant_id=TENANT_ID,
        items=[
            {"sales_order_line_item_id": item_b1.id, "qty": 30},
            {"sales_order_line_item_id": item_b2.id, "qty": 20},
        ],
    )
    check("B1 合单执行", bool(exe and exe.id), f"execution_no={exe.execution_no}")
    cut_b = retry_deadlock(
        lambda: cut_cards_for_execution(
            db,
            tenant_id=TENANT_ID,
            execution_id=exe.id,
            dry_run=False,
            bundle_size=50,
            mode="basket_bundles",
        ),
        label="cut_b",
    )
    b_basket = None
    for row in cut_b.get("created") or []:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == "basket":
            b_basket = tu.id
            break
    check("B2 合单开裁", bool(b_basket), f"basket={b_basket}")
    create_basket_prepack(db, TENANT_ID, b_basket, pairs_per_carton=10)
    warehouse_basket(db, tenant_id=TENANT_ID, trace_unit_id=b_basket, note="合单入库")
    ship = ship_warehoused_basket(db, tenant_id=TENANT_ID, trace_unit_id=b_basket, note="走查FG出货")
    check(
        "B3 从成品仓出货",
        ship.get("status") == "shipped" and ship.get("fg_qty") is not None,
        f"fg_qty={ship.get('fg_qty')} shipments={len(ship.get('shipments') or [])}",
    )
    nos = {row["sales_order_no"]: row.get("total_qty") for row in (ship.get("shipments") or [])}
    check("B4 按销售拆出货", nos.get("SO-WALK-A") == 30 and nos.get("SO-WALK-B") == 20, str(nos))
    check(
        "B5 预装落成",
        (ship.get("prepack") or {}).get("status") == PackingPlanStatus.confirmed.value
        or (ship.get("prepack") or {}).get("status") == "confirmed",
        str(ship.get("prepack")),
    )
    sh0 = (ship.get("shipments") or [{}])[0].get("id")
    cartons = list_shipment_packing_cartons(db, TENANT_ID, sh0) if sh0 else []
    check("B6 出货箱唛可列", bool(cartons), f"n={len(cartons)}")
    recv_a = db.scalar(select(Receivable).where(Receivable.sales_order_no == "SO-WALK-A"))
    check("B7 应收生成", recv_a is not None, f"id={getattr(recv_a, 'id', None)}")
    db.refresh(item_b1)
    db.refresh(item_b2)
    check(
        "B8 销售已出回写",
        int(item_b1.shipped_qty or 0) == 30 and int(item_b2.shipped_qty or 0) == 20,
        f"{item_b1.shipped_qty}/{item_b2.shipped_qty}",
    )

    # --- Path C: 直发 ---
    _, _, item_c = _make_so_item(
        db,
        order_no="SO-WALK-DS",
        qty=12,
        product=product,
        color=color,
        size=size,
        partner=partner,
        customer_name="走查直发客户",
    )
    so_line_c = db.get(SalesOrderLine, item_c.sales_order_line_id)
    so_c = db.get(SalesOrder, so_line_c.sales_order_id)
    so_c.status = SalesOrderStatus.confirmed
    so_line_c.status = SalesOrderLineStatus.in_production
    db.commit()
    exe_c = create_execution(
        db, tenant_id=TENANT_ID, items=[{"sales_order_line_item_id": item_c.id, "qty": 12}]
    )
    cut_c = cut_cards_for_execution(
        db,
        tenant_id=TENANT_ID,
        execution_id=exe_c.id,
        dry_run=False,
        bundle_size=12,
        mode="basket_bundles",
    )
    c_basket = None
    for row in cut_c.get("created") or []:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == "basket":
            c_basket = tu.id
            break
    create_basket_prepack(db, TENANT_ID, c_basket, pairs_per_carton=12)
    # 临时开启直发（走查后恢复）
    from app.services import shop_floor_settings as sfs

    before_flag = bool(sfs.get_shop_floor_by_tenant_id(db, TENANT_ID).get("allow_direct_ship"))
    sfs.save_shop_floor_patch(db, TENANT_ID, {"allow_direct_ship": True})
    fg_before = {
        (s["own_product_id"], s["color_id"], s["size_id"]): int(s["qty"])
        for s in list_fg_stocks(db, tenant_id=TENANT_ID)
    }
    try:
        ds = direct_ship_basket(db, tenant_id=TENANT_ID, trace_unit_id=c_basket, note="走查直发")
    finally:
        sfs.save_shop_floor_patch(db, TENANT_ID, {"allow_direct_ship": before_flag})
    fg_after = {
        (s["own_product_id"], s["color_id"], s["size_id"]): int(s["qty"])
        for s in list_fg_stocks(db, tenant_id=TENANT_ID)
    }
    key = (product.id, color.id, size.id)
    check(
        "C1 直发完成",
        ds.get("status") == "shipped",
        f"shipments={len(ds.get('shipments') or [])}",
    )
    check(
        "C2 直发 FG 净增 0",
        fg_before.get(key, 0) == fg_after.get(key, 0),
        f"before={fg_before.get(key, 0)} after={fg_after.get(key, 0)}",
    )
    led_c = list(
        db.scalars(select(FgLedger).where(FgLedger.trace_unit_id == c_basket)).all()
    )
    dirs = {(x.direction, int(x.qty)) for x in led_c}
    check("C3 直发流水有入有出", ("in", 12) in dirs and ("out", 12) in dirs, str(dirs))

    # leftover FG from path A should still be 24 (path B shipped its own 50)
    left = next(
        (
            s
            for s in list_fg_stocks(db, tenant_id=TENANT_ID, only_positive=True)
            if s["own_product_id"] == product.id and s["size_id"] == size.id
        ),
        None,
    )
    check(
        "D1 走查留仓 24 双仍在成品仓",
        left is not None and int(left["qty"]) == 24,
        str(left),
    )
    unit_a = db.get(TraceUnit, basket_wh)
    check(
        "D2 留仓筐状态 warehoused",
        unit_a is not None and unit_a.status == TraceUnitStatus.warehoused,
        str(getattr(unit_a, "status", None)),
    )

    # 失败条件抽检：无预装不可从 FG 出货（另开一小筐）
    _, _, item_x = _make_so_item(
        db,
        order_no="SO-WALK-GATE",
        qty=6,
        product=product,
        color=color,
        size=size,
        partner=partner,
        customer_name="闸门",
    )
    so_line_x = db.get(SalesOrderLine, item_x.sales_order_line_id)
    so_x = db.get(SalesOrder, so_line_x.sales_order_id)
    so_x.status = SalesOrderStatus.confirmed
    so_line_x.status = SalesOrderLineStatus.in_production
    db.commit()
    exe_x = create_execution(
        db, tenant_id=TENANT_ID, items=[{"sales_order_line_item_id": item_x.id, "qty": 6}]
    )
    cut_x = cut_cards_for_execution(
        db,
        tenant_id=TENANT_ID,
        execution_id=exe_x.id,
        dry_run=False,
        bundle_size=6,
        mode="basket_bundles",
    )
    x_basket = None
    for row in cut_x.get("created") or []:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == "basket":
            x_basket = tu.id
            break
    warehouse_basket(db, tenant_id=TENANT_ID, trace_unit_id=x_basket)
    blocked = False
    try:
        ship_warehoused_basket(db, tenant_id=TENANT_ID, trace_unit_id=x_basket)
    except Exception as e:
        blocked = "prepack" in str(getattr(e, "code", "")) or "预装" in str(e)
    check("H1 无预装不可 FG 出货", blocked, "prepack_required")

    return 0 if all(ok for _, ok, _ in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge-only", action="store_true")
    parser.add_argument("--skip-purge", action="store_true")
    args = parser.parse_args()

    if not args.skip_purge:
        print("==> purging transactional data for tenant", TENANT_ID)
        purge_tenant_orders(TENANT_ID)
    if args.purge_only:
        return 0

    db = SessionLocal()
    try:
        code = walkthrough(db)
    finally:
        db.close()

    print("\n=== summary ===")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"passed={passed} failed={failed}")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    return code


if __name__ == "__main__":
    sys.exit(main())
