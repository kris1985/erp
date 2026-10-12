"""给成本分析补演示数据：部门固定工资、日常开支、采购/仓库物料、销售出货提成。

幂等：已有同标记的员工、开支、领料单、出货单会跳过。
用法：
  .venv/bin/python scripts/seed_cost_analysis_demo.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models import (
    DailyExpense,
    Department,
    Employee,
    OrderMaterialRequirement,
    OwnProductCommission,
    SalaryModel,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    StockDoc,
    StockDocLine,
    StockDocStatus,
    StockDocType,
)
from app.services.attendance_service import LOCAL_OFFSET
from app.services.cost_analysis_service import cost_analysis_report
from app.services.expense_service import DEFAULT_CATEGORIES, create_expense
from app.services.shipment_service import ShipmentError, create_shipment

MARKER = "【成本演示】"
TENANT_NAME = "演示鞋厂"

# 一级部门上的坐班人员：固定工资记在月末
STAFF = (
    ("马丽", "采购部", Decimal("6800")),
    ("钱进", "财务部", Decimal("7500")),
    ("何静", "人事部", Decimal("6200")),
    ("周研", "开发部", Decimal("9800")),
    ("陈仓", "仓库", Decimal("5600")),
    ("吴婷", "销售部", Decimal("7200")),
    ("郑凯", "办公室", Decimal("8600")),
)

EXPENSE_KINDS = {
    "采购部": ("差旅费", "样品运费", "供应商招待"),
    "财务部": ("银行手续费", "办公用品", "审计咨询"),
    "生产部": ("劳保用品", "设备维修", "车间耗材"),
    "人事部": ("招聘费", "员工体检", "培训费"),
    "开发部": ("打样费", "外发设计", "试样材料"),
    "仓库": ("仓储杂费", "叉车维修", "包装辅料"),
    "销售部": ("客户招待", "展会费", "样品快递"),
    "办公室": ("水电物业", "网络通讯", "办公耗材"),
}
EXPENSE_BASE = {
    "差旅费": 860,
    "样品运费": 240,
    "供应商招待": 680,
    "银行手续费": 45,
    "办公用品": 180,
    "审计咨询": 3200,
    "劳保用品": 560,
    "设备维修": 1480,
    "车间耗材": 320,
    "招聘费": 900,
    "员工体检": 1260,
    "培训费": 2100,
    "打样费": 760,
    "外发设计": 1800,
    "试样材料": 430,
    "仓储杂费": 260,
    "叉车维修": 890,
    "包装辅料": 540,
    "客户招待": 1280,
    "展会费": 3600,
    "样品快递": 95,
    "水电物业": 4200,
    "网络通讯": 680,
    "办公耗材": 210,
}

# 销售单 SO-MB：已确认、欠交充足，出货后提成按出货日记入销售部/开发部
SHIP_ORDER_ID = 69
SHIP_DATES = (
    date(2026, 9, 4),
    date(2026, 9, 8),
    date(2026, 9, 11),
    date(2026, 9, 15),
    date(2026, 9, 18),
    date(2026, 9, 22),
    date(2026, 9, 25),
)
SHIP_QTY = 18


def _tenant(db):
    from app.models import Tenant

    tenant = db.scalar(select(Tenant).where(Tenant.name == TENANT_NAME))
    if not tenant:
        raise SystemExit(f"找不到租户 {TENANT_NAME}")
    return tenant


def _dept_by_name(db, tenant_id: int) -> dict[str, Department]:
    rows = db.scalars(select(Department).where(Department.tenant_id == tenant_id)).all()
    return {d.name: d for d in rows}


def _ensure_staff(db, tenant_id: int, depts: dict[str, Department]) -> dict[str, Employee]:
    by_name: dict[str, Employee] = {}
    for name, dept_name, salary in STAFF:
        dept = depts.get(dept_name)
        if not dept:
            raise SystemExit(f"缺少部门 {dept_name}")
        emp = db.scalar(
            select(Employee).where(Employee.tenant_id == tenant_id, Employee.name == name)
        )
        if emp:
            by_name[name] = emp
            continue
        emp = Employee(
            tenant_id=tenant_id,
            name=name,
            department_id=dept.id,
            salary_model=SalaryModel.fixed,
            base_salary=salary,
            hire_date=date(2026, 1, 6),
            is_active=True,
        )
        db.add(emp)
        db.flush()
        by_name[name] = emp
        print(f"  员工 {name} → {dept_name} 固定 {salary}")
    db.commit()
    return by_name


def _expense_dates() -> list[date]:
    days: list[date] = []
    cursor = date(2026, 7, 3)
    end = date(2026, 9, 26)
    i = 0
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=2 if i % 3 else 3)
        i += 1
    return days


def _seed_expenses(db, tenant_id: int, depts: dict[str, Department], staff: dict[str, Employee]) -> int:
    dept_names = list(EXPENSE_KINDS)
    reimbursers = {
        "采购部": staff["马丽"],
        "财务部": staff["钱进"],
        "人事部": staff["何静"],
        "开发部": staff["周研"],
        "仓库": staff["陈仓"],
        "销售部": staff["吴婷"],
        "办公室": staff["郑凯"],
    }
    prod = db.scalar(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.name == "张媛")
    )
    if not prod:
        raise SystemExit("缺少生产部报销人「张媛」")
    reimbursers["生产部"] = prod

    created = 0
    for i, day in enumerate(_expense_dates()):
        dept_name = dept_names[i % len(dept_names)]
        kinds = EXPENSE_KINDS[dept_name]
        kind = kinds[i % len(kinds)]
        reason = f"{MARKER}{kind}"
        dept = depts[dept_name]
        exists = db.scalar(
            select(DailyExpense.id).where(
                DailyExpense.tenant_id == tenant_id,
                DailyExpense.department_id == dept.id,
                DailyExpense.expense_date == day,
                DailyExpense.reason == reason,
            )
        )
        if exists:
            continue
        base = EXPENSE_BASE[kind]
        amount = Decimal(base + (i * 37) % 160).quantize(Decimal("0.01"))
        category = DEFAULT_CATEGORIES[i % len(DEFAULT_CATEGORIES)]
        lines = [
            {
                "category": category,
                "occurred_on": day,
                "amount": amount,
                "description": reason,
            }
        ]
        if i % 4 == 0:
            extra_kind = kinds[(i + 1) % len(kinds)]
            lines.append(
                {
                    "category": DEFAULT_CATEGORIES[(i + 1) % len(DEFAULT_CATEGORIES)],
                    "occurred_on": day,
                    "amount": Decimal(EXPENSE_BASE[extra_kind] // 3 + 20),
                    "description": f"{MARKER}{extra_kind}",
                }
            )
        create_expense(
            db,
            tenant_id,
            department_id=dept.id,
            employee_id=reimbursers[dept_name].id,
            reason=reason,
            lines=lines,
            fund_account="cash" if amount < 200 else "bank",
        )
        created += 1
    print(f"  开支 {created} 笔")
    return created


def _seed_material(db, tenant_id: int, buyers: Employee, keeper: Employee) -> int:
    reqs = list(
        db.scalars(
            select(OrderMaterialRequirement)
            .where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.unit_price > 0,
                OrderMaterialRequirement.is_customer_supplied.is_(False),
            )
            .order_by(OrderMaterialRequirement.id)
            .limit(6)
        ).all()
    )
    if len(reqs) < 2:
        print("  物料跳过：没有可用的订单用料")
        return 0

    days: list[date] = []
    cursor = date(2026, 7, 8)
    while cursor <= date(2026, 9, 24):
        days.append(cursor)
        cursor += timedelta(days=4)

    created = 0
    for i, day in enumerate(days):
        is_return = i % 5 == 4
        doc_type = StockDocType.return_mat if is_return else StockDocType.issue
        prefix = "CADR" if is_return else "CADI"
        doc_no = f"{prefix}{day.strftime('%y%m%d')}{i + 1:02d}"
        if db.scalar(select(StockDoc.id).where(StockDoc.tenant_id == tenant_id, StockDoc.doc_no == doc_no)):
            continue
        req = reqs[i % len(reqs)]
        qty = Decimal("6") if is_return else Decimal(str(8 + (i % 5) * 4))
        creator = keeper if i % 2 else buyers
        posted_at = datetime.combine(day, time(10, 30)) - LOCAL_OFFSET
        doc = StockDoc(
            tenant_id=tenant_id,
            doc_no=doc_no,
            doc_type=doc_type,
            status=StockDocStatus.posted,
            notes=f"{MARKER}{'退料' if is_return else '领料'}",
            created_by=creator.id,
            posted_at=posted_at,
        )
        db.add(doc)
        db.flush()
        db.add(
            StockDocLine(
                tenant_id=tenant_id,
                stock_doc_id=doc.id,
                order_material_requirement_id=req.id,
                supplier_product_id=req.supplier_product_id,
                qty=qty,
                unit_cost=req.unit_price,
            )
        )
        created += 1
    db.commit()
    print(f"  物料单 {created} 张（不改已发数量）")
    return created


def _ensure_commission(db, tenant_id: int, employee_id: int, product_id: int, amount: Decimal) -> None:
    row = db.scalar(
        select(OwnProductCommission).where(
            OwnProductCommission.tenant_id == tenant_id,
            OwnProductCommission.own_product_id == product_id,
            OwnProductCommission.employee_id == employee_id,
        )
    )
    if row:
        return
    db.add(
        OwnProductCommission(
            tenant_id=tenant_id,
            own_product_id=product_id,
            employee_id=employee_id,
            amount=amount,
            sort_order=0,
        )
    )


def _seed_shipments(db, tenant_id: int, sales: Employee, dev: Employee) -> int:
    so = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == SHIP_ORDER_ID, SalesOrder.tenant_id == tenant_id)
        .options(selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items))
    )
    if not so:
        print("  出货跳过：销售单不存在")
        return 0
    product_ids = {ln.own_product_id for ln in so.lines or [] if ln.own_product_id}
    # 8 月已出货的 OP-RUN-01，让销售/开发提成落在原出货日
    from app.models import OwnProduct

    run = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == "OP-RUN-01")
    )
    if run:
        product_ids.add(run.id)
        _ensure_commission(db, tenant_id, sales.id, run.id, Decimal("1.50"))
        _ensure_commission(db, tenant_id, dev.id, run.id, Decimal("0.40"))
    for pid in product_ids:
        if run and pid == run.id:
            continue
        _ensure_commission(db, tenant_id, sales.id, pid, Decimal("1.20"))
        _ensure_commission(db, tenant_id, dev.id, pid, Decimal("0.35"))
    db.commit()

    created = 0
    for day in SHIP_DATES:
        exists = db.scalar(
            select(Shipment.id).where(
                Shipment.tenant_id == tenant_id,
                Shipment.ship_date == day,
                Shipment.notes == f"{MARKER}出货",
            )
        )
        if exists:
            continue
        so = db.scalar(
            select(SalesOrder)
            .where(SalesOrder.id == SHIP_ORDER_ID, SalesOrder.tenant_id == tenant_id)
            .options(selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items))
        )
        candidates = []
        for ln in so.lines or []:
            for it in ln.items or []:
                remain = int(it.qty or 0) - int(it.shipped_qty or 0)
                produced = int(getattr(it, "produced_qty", 0) or 0)
                shippable = remain if produced <= 0 else max(0, min(remain, produced - int(it.shipped_qty or 0)))
                if shippable > 0:
                    candidates.append((it.id, shippable))
        if not candidates:
            print(f"  {day} 无可出数量，停止继续出货")
            break
        item_id, shippable = max(candidates, key=lambda x: x[1])
        qty = min(SHIP_QTY, shippable)
        try:
            create_shipment(
                db,
                tenant_id,
                sales_order_id=so.id,
                lines=[{"sales_order_line_item_id": item_id, "qty": qty}],
                ship_date=day,
                notes=f"{MARKER}出货",
                confirm=True,
            )
        except ShipmentError as err:
            db.rollback()
            print(f"  {day} 出货失败：{err}")
            break
        created += 1
        print(f"  出货 {day} {qty} 双")
    return created


# 报销类型直接写在明细上，方便成本分析按列展开。金额为演示数。
TYPED_EXPENSES = (
    ("采购部", "马丽", date(2026, 9, 2), "交通费", "860"),
    ("采购部", "马丽", date(2026, 9, 9), "餐饮费", "420"),
    ("采购部", "马丽", date(2026, 9, 19), "礼品费", "680"),
    ("财务部", "钱进", date(2026, 9, 3), "办公用品", "260"),
    ("财务部", "钱进", date(2026, 9, 12), "快递物流费", "180"),
    ("财务部", "钱进", date(2026, 9, 22), "水电", "960"),
    ("生产部", "张波", date(2026, 9, 5), "鞋材物料", "1480"),
    ("生产部", "张波", date(2026, 9, 15), "机器维修", "1280"),
    ("生产部", "张波", date(2026, 9, 26), "车间耗材", "540"),
    ("人事部", "何静", date(2026, 9, 6), "餐饮费", "360"),
    ("人事部", "何静", date(2026, 9, 16), "礼品费", "520"),
    ("人事部", "何静", date(2026, 9, 24), "交通费", "210"),
    ("开发部", "周研", date(2026, 9, 4), "鞋样资讯", "1860"),
    ("开发部", "周研", date(2026, 9, 11), "鞋材物料", "940"),
    ("开发部", "周研", date(2026, 9, 21), "快递物流费", "150"),
    ("开发部", "周研", date(2026, 9, 28), "机器采购", "3200"),
    ("仓库", "陈仓", date(2026, 9, 8), "办公用品", "190"),
    ("仓库", "陈仓", date(2026, 9, 18), "水电", "430"),
    ("销售部", "吴婷", date(2026, 9, 7), "交通费", "640"),
    ("销售部", "吴婷", date(2026, 9, 13), "住宿费", "880"),
    ("销售部", "吴婷", date(2026, 9, 23), "餐饮费", "510"),
    ("办公室", "郑凯", date(2026, 9, 1), "房租", "12000"),
    ("办公室", "郑凯", date(2026, 9, 10), "水电", "2100"),
    ("办公室", "郑凯", date(2026, 9, 20), "办公用品", "340"),
)

# 已确认的开发部领料。只补成本记录，不扣现有库存。
DEV_PICKUPS = (
    (date(2026, 9, 3), (("HR-MESH-01", "18"),)),
    (date(2026, 9, 8), (("TD-RB-001", "24"), ("TD-MD-010", "40"))),
    (date(2026, 9, 12), (("HR-SF-11", "12"),)),
    (date(2026, 9, 18), (("XF-NL-01", "10"), ("HR-THREAD-1", "4"))),
    (date(2026, 9, 24), (("TD-RB-001", "16"), ("HR-MESH-01", "10"))),
    (date(2026, 9, 29), (("LX-BOX-01", "80"), ("LX-TAG-02", "200"))),
)


def _seed_typed_expenses(db, tenant_id: int, depts: dict[str, Department]) -> int:
    created = 0
    for dept_name, emp_name, day, category, amount in TYPED_EXPENSES:
        dept = depts.get(dept_name)
        if not dept:
            print(f"  跳过开支：没有部门 {dept_name}")
            continue
        emp = db.scalar(
            select(Employee).where(Employee.tenant_id == tenant_id, Employee.name == emp_name)
        )
        if not emp:
            print(f"  跳过开支：没有员工 {emp_name}")
            continue
        reason = f"{MARKER}分类 {dept_name} {category}"
        exists = db.scalar(
            select(DailyExpense.id).where(
                DailyExpense.tenant_id == tenant_id,
                DailyExpense.department_id == dept.id,
                DailyExpense.expense_date == day,
                DailyExpense.reason == reason,
            )
        )
        if exists:
            continue
        create_expense(
            db,
            tenant_id,
            department_id=dept.id,
            employee_id=emp.id,
            reason=reason,
            lines=[
                {
                    "category": category,
                    "occurred_on": day,
                    "amount": Decimal(amount),
                    "description": reason,
                }
            ],
            fund_account="bank",
        )
        created += 1
    print(f"  分类开支 {created} 笔")
    return created


def _seed_dev_pickups(db, tenant_id: int, keeper_id: int | None) -> int:
    from app.models import (
        SharedLedgerType,
        SharedMaterialLedger,
        SupplierProduct,
        WarehousePickup,
        WarehousePickupKind,
        WarehousePickupLine,
        WarehousePickupStatus,
    )

    products = {
        row.product_code: row
        for row in db.scalars(
            select(SupplierProduct).where(SupplierProduct.tenant_id == tenant_id)
        ).all()
    }
    created = 0
    for day, lines in DEV_PICKUPS:
        doc_no = f"DVDEMO{day.strftime('%m%d')}"
        if db.scalar(
            select(WarehousePickup.id).where(
                WarehousePickup.tenant_id == tenant_id,
                WarehousePickup.doc_no == doc_no,
            )
        ):
            continue
        resolved = []
        for code, qty_text in lines:
            product = products.get(code)
            if not product:
                print(f"  跳过领料 {doc_no}：没有物料 {code}")
                resolved = []
                break
            resolved.append((product, Decimal(qty_text)))
        if not resolved:
            continue
        signed_at = datetime.combine(day, time(2, 0))
        pickup = WarehousePickup(
            tenant_id=tenant_id,
            doc_no=doc_no,
            kind=WarehousePickupKind.dev,
            status=WarehousePickupStatus.signed,
            notes=f"{MARKER}开发领料",
            picker_name="周研",
            signed_at=signed_at,
            created_by=keeper_id,
            created_at=signed_at,
        )
        db.add(pickup)
        db.flush()
        for product, qty in resolved:
            unit = Decimal(str(product.unit_price or 0))
            db.add(
                WarehousePickupLine(
                    tenant_id=tenant_id,
                    pickup_id=pickup.id,
                    supplier_product_id=product.id,
                    material_name=product.name or product.product_code,
                    material_code=product.product_code,
                    qty=qty,
                )
            )
            db.add(
                SharedMaterialLedger(
                    tenant_id=tenant_id,
                    supplier_product_id=product.id,
                    ledger_type=SharedLedgerType.dev_issue,
                    qty_delta=-qty,
                    unit_cost=unit,
                    balance_after=Decimal("0"),
                    ref_type="warehouse_pickup",
                    ref_id=pickup.id,
                    note=f"{MARKER}开发领料 {doc_no}",
                    created_by=keeper_id,
                    created_at=signed_at,
                )
            )
        created += 1
    db.commit()
    print(f"  开发领料 {created} 张（不扣库存）")
    return created


def main() -> None:
    db = SessionLocal()
    try:
        tenant = _tenant(db)
        depts = _dept_by_name(db, tenant.id)
        print("员工")
        staff = _ensure_staff(db, tenant.id, depts)
        print("开支")
        _seed_expenses(db, tenant.id, depts, staff)
        print("分类开支")
        _seed_typed_expenses(db, tenant.id, depts)
        print("开发领料")
        _seed_dev_pickups(db, tenant.id, staff["陈仓"].id)
        print("物料")
        _seed_material(db, tenant.id, staff["马丽"], staff["陈仓"])
        print("提成与出货")
        _seed_shipments(db, tenant.id, staff["吴婷"], staff["周研"])
        report = cost_analysis_report(db, tenant.id)
        print(
            f"成本分析 {report['date_from']} ~ {report['date_to']}："
            f"{len(report['rows'])} 天，"
            + "、".join(
                f"{h['department_name']}({'/'.join(c['label'] for c in h['children'])})"
                for h in report["headers"]
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
