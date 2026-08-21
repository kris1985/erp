#!/usr/bin/env python3
"""对着本地库跑经营全链路，默认保留单据（不清库）。

用法:
  .venv/bin/python scripts/walkthrough_lifecycle.py
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.db_schema import ensure_schema
from app.models import (
    Color,
    ExecutionHeader,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    OwnProductPart,
    Partner,
    Payable,
    ProcessDefinition,
    ProcessType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Receivable,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SalaryMonthLock,
    SharedMaterialStock,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
    Employee,
)
from app.schemas.api import SalesOrderCreate, SalesOrderLineIn, SalesOrderLineItemIn
from app.services import iqc_service, purchase_service, stock_doc_service
from app.services.execution_schedule_service import confirm_draft, propose_draft
from app.services.execution_service import cut_cards_for_execution
from app.services.fg_service import ship_warehoused_basket, warehouse_basket
from app.services.material_service import allocate_from_pool_for_header, get_header_kit
from app.services.packing_service import create_basket_prepack
from app.services.purchase_service import generate_po_no, new_public_token
from app.services.report_service import submit_report
from app.services.salary_service import month_salary
from app.services.sales_order_service import (
    confirm_sales_order,
    create_sales_order,
    serialize_sales_order,
    simulate_sales_order_lines_mrp,
)

TENANT_ID = 1
QTY = 12
PRODUCT_CODE = "OP-RUN-01"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _enum(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _pool_qty(db, tenant_id: int, sp_id: int, size_id: int | None = None) -> Decimal:
    q = select(SharedMaterialStock).where(
        SharedMaterialStock.tenant_id == tenant_id,
        SharedMaterialStock.supplier_product_id == sp_id,
    )
    if size_id is None:
        q = q.where(SharedMaterialStock.size_id.is_(None))
    else:
        q = q.where(SharedMaterialStock.size_id == size_id)
    row = db.scalar(q)
    return Decimal(str(row.qty)) if row else Decimal("0")


def _basket_id(db, created: list[dict]) -> int | None:
    for row in created:
        tu = db.get(TraceUnit, row["id"])
        if tu and str(getattr(tu.unit_type, "value", tu.unit_type)) == TraceUnitType.basket.value:
            return tu.id
    return None


def _assert_so(db, so, line, item, *, so_stored, so_display, line_display, allocated, produced, shipped):
    db.refresh(so)
    db.refresh(line)
    db.refresh(item)
    ser = serialize_sales_order(db, so.tenant_id, so)
    ln = next(x for x in ser["lines"] if x["id"] == line.id)
    it = next(x for x in ln["items"] if x["id"] == item.id)
    ok = (
        ser["status"] == so_stored
        and ser["display_status"] == so_display
        and ln["display_status"] == line_display
        and int(it["allocated_qty"]) == allocated
        and int(it["produced_qty"]) == produced
        and int(it["shipped_qty"]) == shipped
    )
    check(
        f"状态 {so_display}",
        ok,
        f"so={ser['status']}/{ser['display_status']} line={ln['display_status']} "
        f"alloc/prod/ship={it['allocated_qty']}/{it['produced_qty']}/{it['shipped_qty']}",
    )
    return ok


def walkthrough(db) -> int:
    ensure_schema()
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    order_no = f"SO-LC-{stamp}"

    actor = db.scalar(
        select(Employee)
        .where(Employee.tenant_id == TENANT_ID, Employee.is_active.is_(True))
        .order_by(Employee.id)
    )
    if not actor:
        check("主数据 操作人", False, "当前租户无有效员工")
        return 1
    actor_id = int(actor.id)

    product = db.scalar(
        select(OwnProduct).where(
            OwnProduct.tenant_id == TENANT_ID,
            OwnProduct.product_code == PRODUCT_CODE,
            OwnProduct.is_active.is_(True),
        )
    )
    if not product:
        check("主数据 产品", False, f"无 {PRODUCT_CODE}")
        return 1
    product.trace_enabled = True
    color = db.scalar(
        select(Color).where(Color.tenant_id == TENANT_ID, Color.name == "黑")
    ) or db.scalar(select(Color).where(Color.tenant_id == TENANT_ID).limit(1))
    size = db.scalar(
        select(Size).where(Size.tenant_id == TENANT_ID, Size.size_value == "40")
    ) or db.scalar(select(Size).where(Size.tenant_id == TENANT_ID).limit(1))
    customer = db.scalar(
        select(Partner).where(
            Partner.tenant_id == TENANT_ID,
            Partner.is_customer.is_(True),
            Partner.is_active.is_(True),
        )
    )
    workers = list(
        db.scalars(
            select(Employee).where(Employee.tenant_id == TENANT_ID, Employee.is_active.is_(True)).limit(4)
        ).all()
    )
    bom = list(
        db.scalars(
            select(OwnProductMaterial)
            .where(
                OwnProductMaterial.tenant_id == TENANT_ID,
                OwnProductMaterial.own_product_id == product.id,
            )
            .order_by(OwnProductMaterial.sort_order, OwnProductMaterial.id)
        ).all()
    )
    parts = db.scalar(
        select(OwnProductPart.id).where(
            OwnProductPart.tenant_id == TENANT_ID,
            OwnProductPart.own_product_id == product.id,
        )
    )
    if not all([color, size, customer, workers, bom, parts]):
        check("主数据就绪", False, "缺色/码/客户/工人/BOM/部件")
        return 1
    db.commit()
    check(
        "主数据就绪",
        True,
        f"{product.product_code} / {color.name} / {size.size_value} / {customer.name}",
    )

    # --- 1 建单 ---
    so = create_sales_order(
        db,
        TENANT_ID,
        SalesOrderCreate(
            order_no=order_no,
            customer_id=customer.id,
            ordered_at=date.today(),
            notes="全链路走查（保留数据）",
            lines=[
                SalesOrderLineIn(
                    own_product_id=product.id,
                    color_id=color.id,
                    unit_price=product.quote_price or Decimal("69"),
                    items=[SalesOrderLineItemIn(size_id=size.id, qty=QTY)],
                )
            ],
        ),
        created_by=actor_id,
    )
    line = so.lines[0]
    item = line.items[0]
    _assert_so(
        db, so, line, item,
        so_stored="draft", so_display="pending_confirm", line_display="pending_confirm",
        allocated=0, produced=0, shipped=0,
    )

    # --- 2 接单 ---
    so = confirm_sales_order(db, TENANT_ID, so.id, created_by=actor_id)
    db.refresh(line)
    check("接单不建执行单", line.execution_header_id is None, f"so={so.order_no}")
    _assert_so(
        db, so, line, item,
        so_stored="confirmed", so_display="pending_schedule", line_display="pending_schedule",
        allocated=0, produced=0, shipped=0,
    )

    mrp = simulate_sales_order_lines_mrp(
        db, TENANT_ID, [(so.id, line.id)], include_shared=True, shortages_only=False
    )
    check("接单后可算 MRP", bool(mrp.get("lines")), f"shortage_lines={mrp.get('shortage_lines')}")

    # --- 3 采购：按缺口下单；若池已覆盖也至少买一行便于页面可见 ---
    buy_rows = [x for x in (mrp.get("lines") or []) if Decimal(str(x.get("shortage_qty") or 0)) > 0]
    if not buy_rows:
        first = bom[0]
        sp0 = db.get(SupplierProduct, first.supplier_product_id)
        buy_rows = [
            {
                "supplier_product_id": first.supplier_product_id,
                "partner_id": sp0.partner_id if sp0 else None,
                "shortage_qty": (first.qty or Decimal("1")) * QTY,
                "unit_price": first.unit_price or (sp0.unit_price if sp0 else Decimal("0")),
                "size_id": None,
            }
        ]
    pos: list[PurchaseOrder] = []
    by_partner: dict[int, list] = {}
    for row in buy_rows:
        pid = row.get("partner_id")
        if not pid:
            sp = db.get(SupplierProduct, row["supplier_product_id"])
            pid = sp.partner_id if sp else None
        if not pid:
            continue
        by_partner.setdefault(int(pid), []).append(row)
    for partner_id, rows in by_partner.items():
        po = PurchaseOrder(
            tenant_id=TENANT_ID,
            po_no=generate_po_no(db, TENANT_ID),
            public_token=new_public_token(),
            partner_id=partner_id,
            status=PurchaseOrderStatus.draft,
            expected_date=date.today(),
            notes=f"全链路走查 {order_no}",
        )
        db.add(po)
        db.flush()
        for row in rows:
            db.add(
                PurchaseOrderLine(
                    tenant_id=TENANT_ID,
                    purchase_order_id=po.id,
                    supplier_product_id=row["supplier_product_id"],
                    qty=Decimal(str(row["shortage_qty"])),
                    unit_price=Decimal(str(row.get("unit_price") or 0)),
                    received_qty=Decimal("0"),
                    sales_order_id=so.id,
                    sales_order_line_id=line.id,
                    size_id=row.get("size_id"),
                )
            )
        db.commit()
        submitted = purchase_service.submit_po(db, TENANT_ID, po.id)
        check(f"采购下单 {po.po_no}", submitted["status"] == "ordered", submitted["status"])
        pos.append(po)

    # --- 4 入库 + IQC ---
    for po in pos:
        po = db.get(PurchaseOrder, po.id)
        receives = [{"line_id": ln.id, "qty": float(ln.qty)} for ln in po.lines]
        recv = purchase_service.receive_po(db, TENANT_ID, po.id, receives, user_id=actor_id)
        pending_ids = recv.get("iqc_pending_ids") or []
        if pending_ids:
            for iqc_id in pending_ids:
                iqc_service.decide_iqc(db, TENANT_ID, iqc_id, decision="pass", user_id=actor_id)
            check(f"IQC 合格入池 {po.po_no}", True, f"iqc={len(pending_ids)}")
        else:
            check(f"到货直入池 {po.po_no}", True, "skip_iqc_or_off")
        db.refresh(po)
        check(
            f"采购入库 {po.po_no}",
            _enum(po.status) in ("received", "partial_received"),
            _enum(po.status),
        )
    check(
        "应付已生成",
        any(db.scalar(select(Payable).where(Payable.purchase_order_id == po.id)) for po in pos),
        f"po={len(pos)}",
    )

    # --- 5 排产 ---
    draft = propose_draft(
        db,
        tenant_id=TENANT_ID,
        selections=[{"sales_order_line_item_id": item.id, "qty": QTY}],
        note=f"全链路走查 {order_no}",
        created_by=actor_id,
    )
    confirmed = confirm_draft(db, tenant_id=TENANT_ID, draft_id=draft["id"], created_by=actor_id)
    exe = db.get(SpecExecutionOrder, confirmed["executions"][0]["id"])
    header = db.get(ExecutionHeader, exe.header_id)
    db.refresh(line)
    _assert_so(
        db, so, line, item,
        so_stored="confirmed", so_display="pending_production", line_display="pending_production",
        allocated=QTY, produced=0, shipped=0,
    )
    check(
        "执行单已排产",
        _enum(header.status) == "confirmed" and _enum(exe.status) == "confirmed",
        f"{header.header_no} / {exe.execution_no}",
    )

    # --- 6 锁料 ---
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.header_id == header.id,
                OrderMaterialRequirement.is_customer_supplied.is_(False),
            )
        ).all()
    )
    for req in reqs:
        need = (req.required_qty or Decimal("0")) - (req.arrived_qty or Decimal("0"))
        if need <= 0:
            continue
        size_id = req.size_id if getattr(req, "usage_by_size", False) else None
        free = _pool_qty(db, TENANT_ID, req.supplier_product_id, size_id)
        take = min(need, free)
        if take <= 0:
            continue
        allocate_from_pool_for_header(
            db, TENANT_ID, header.id, req.id, take, user_id=actor_id, commit=True
        )
    kit = get_header_kit(db, TENANT_ID, header.id)
    check("锁料后齐套", bool(kit.get("kit_ok")), f"header={header.header_no}")

    # --- 7/8 领料 + 出库 ---
    issue_lines = []
    for req in reqs:
        db.refresh(req)
        open_qty = (req.arrived_qty or Decimal("0")) - (req.issued_qty or Decimal("0"))
        if open_qty > 0:
            issue_lines.append({"requirement_id": req.id, "qty": open_qty})
    if issue_lines:
        pending = stock_doc_service.submit_stock_doc(
            db,
            TENANT_ID,
            doc_type="issue",
            header_id=header.id,
            lines=issue_lines,
            user_id=actor_id,
            notes=f"全链路走查领料 {order_no}",
        )
        check("领料提报", pending["status"] == "pending", pending.get("doc_no") or "")
        posted = stock_doc_service.confirm_stock_doc(db, TENANT_ID, pending["id"])
        check("出库过账", posted["status"] == "posted", posted.get("doc_no") or "")
    else:
        check("领料出库", False, "无已锁占用可发")

    # --- 9 开裁 ---
    cut = cut_cards_for_execution(
        db,
        tenant_id=TENANT_ID,
        execution_id=exe.id,
        dry_run=False,
        bundle_size=QTY,
        mode="basket_bundles",
    )
    created = cut.get("created") or []
    basket_id = _basket_id(db, created)
    db.refresh(header)
    db.refresh(exe)
    check(
        "开裁出筐",
        bool(basket_id) and _enum(header.status) == "cut",
        f"basket={basket_id} header={_enum(header.status)} created={len(created)}",
    )
    _assert_so(
        db, so, line, item,
        so_stored="confirmed", so_display="in_progress", line_display="in_progress",
        allocated=QTY, produced=0, shipped=0,
    )

    # --- 报工：个人工序全报；集体成型带两人 ---
    labors = list(
        db.scalars(
            select(OwnProductLabor)
            .where(
                OwnProductLabor.tenant_id == TENANT_ID,
                OwnProductLabor.own_product_id == product.id,
            )
            .order_by(OwnProductLabor.sort_order, OwnProductLabor.id)
        ).all()
    )
    w0, w1 = workers[0], workers[1] if len(workers) > 1 else workers[0]
    first_report = True
    for labor in labors:
        proc = db.get(ProcessDefinition, labor.process_id)
        ptype = getattr(proc, "type", None) if proc else None
        ptype_v = ptype.value if hasattr(ptype, "value") else str(ptype or "personal")
        kwargs = dict(
            tenant_id=TENANT_ID,
            worker_id=w0.id,
            header_id=header.id,
            process_name=labor.process_name,
            qualified_qty=QTY,
            color_name=color.name,
            size_value=size.size_value,
            create_trace_bundle=False,
            confirm_over_plan=True,
        )
        if ptype_v == ProcessType.group.value:
            kwargs["member_ids"] = [w0.id, w1.id]
        submit_report(db, **kwargs)
        if first_report:
            db.refresh(header)
            db.refresh(exe)
            check(
                "首报工→生产中",
                _enum(header.status) == "in_progress",
                f"{labor.process_name} header={_enum(header.status)}",
            )
            first_report = False
    db.refresh(exe)
    db.refresh(header)
    check(
        "末道后执行完成",
        _enum(exe.status) == "completed",
        f"completed_qty={exe.completed_qty} status={_enum(exe.status)}",
    )

    sal = month_salary(db, TENANT_ID, w0.id)
    check(
        "工资可算",
        Decimal(str(sal.get("total_piece_wage") or 0)) > 0,
        f"{w0.name} ¥{sal.get('total_piece_wage')}",
    )

    # --- 预装 + 成品入库 + 出货 ---
    pre = create_basket_prepack(db, TENANT_ID, basket_id, pairs_per_carton=QTY)
    check("预装箱", int(pre.get("carton_count") or 0) >= 1, f"plan={pre.get('id')}")
    wh = warehouse_basket(db, tenant_id=TENANT_ID, trace_unit_id=basket_id, note="全链路走查入库")
    check("成品入库", wh.get("status") == "warehoused" and int(wh.get("qty") or 0) == QTY, str(wh.get("qty")))
    _assert_so(
        db, so, line, item,
        so_stored="confirmed", so_display="in_progress", line_display="in_progress",
        allocated=QTY, produced=QTY, shipped=0,
    )
    ship = ship_warehoused_basket(db, tenant_id=TENANT_ID, trace_unit_id=basket_id, note="全链路走查出货")
    db.refresh(so)
    db.refresh(line)
    db.refresh(item)
    check(
        "FG 出货",
        ship.get("status") == "shipped" and int(item.shipped_qty or 0) == QTY,
        f"shipments={len(ship.get('shipments') or [])}",
    )
    check(
        "销售交清",
        so.status == SalesOrderStatus.completed and line.status == SalesOrderLineStatus.completed,
        f"so={_enum(so.status)} line={_enum(line.status)}",
    )
    recv = db.scalar(select(Receivable).where(Receivable.sales_order_no == order_no))
    check("应收生成", recv is not None, f"id={getattr(recv, 'id', None)}")
    unit = db.get(TraceUnit, basket_id)
    check("筐已出货", unit is not None and unit.status == TraceUnitStatus.shipped, str(getattr(unit, "status", None)))

    print("\n=== 保留数据（未清库）===")
    print(f"  销售单  {order_no}  id={so.id}")
    print(f"  执行单  {header.header_no}  id={header.id}")
    print(f"  码明细  {exe.execution_no}  id={exe.id}")
    print(f"  采购单  {', '.join(p.po_no for p in pos)}")
    print(f"  筐      id={basket_id}")
    print("  可在「销售订单 / 执行单 / 采购 / 成品仓 / 出货 / 工资」页查看")
    return 0 if all(ok for _, ok, _ in results) else 1


def main() -> int:
    print("==> 全链路走查（保留数据，不清库） tenant", TENANT_ID)
    db = SessionLocal()
    lock_row = None
    restore_locked = False
    try:
        if os.getenv("WALKTHROUGH_TEMP_UNLOCK_MONTH") == "1":
            ym = datetime.utcnow().strftime("%Y-%m")
            lock_row = db.scalar(
                select(SalaryMonthLock).where(
                    SalaryMonthLock.tenant_id == TENANT_ID,
                    SalaryMonthLock.year_month == ym,
                )
            )
            restore_locked = bool(lock_row and lock_row.is_locked)
            if restore_locked:
                lock_row.is_locked = False
                db.commit()
                print(f"[INFO] 临时解锁 {ym}，走查结束后恢复")
        code = walkthrough(db)
    finally:
        if restore_locked and lock_row is not None:
            lock_row.is_locked = True
            db.commit()
            print(f"[INFO] 已恢复 {lock_row.year_month} 月结锁定")
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
