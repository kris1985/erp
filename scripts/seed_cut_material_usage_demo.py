"""给已有裁断报工的款补上裁断物料和已签收领料，方便经营报告看用量。

只动 2026-09 有裁断报工的款。面料、皮料、超纤标成裁断段；大底、鞋带等不动。
领料按各人 9 月裁断报工双数来，张三偏省、王五接近标准、赵六略费。
重复执行不会再插一遍领料单。
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Employee,
    ExecutionHeader,
    MaterialCategory,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductMaterial,
    PricingUnit,
    ProcessSegment,
    SpecExecutionStatus,
    SupplierProduct,
    WarehousePickup,
    WarehousePickupKind,
    WarehousePickupLine,
    WarehousePickupStatus,
)
from app.services.attendance_service import LOCAL_OFFSET

TENANT_ID = 1
CUT_CATEGORIES = {"面料网布", "皮料", "超纤革"}
# 相对单双用量的领料系数：省料 / 接近标准 / 略费
WORKER_FACTOR = {
    "张三": Decimal("0.94"),
    "王五": Decimal("1.03"),
    "赵六": Decimal("1.15"),
}
# 皮料更费一点，超纤略省
CATEGORY_NUDGE = {
    "面料网布": Decimal("1.00"),
    "皮料": Decimal("1.06"),
    "超纤革": Decimal("0.96"),
}
SIGN_DAY = {
    "A款": date(2026, 9, 8),
    "B款": date(2026, 9, 10),
    "C款": date(2026, 9, 12),
    "OP-BOOT-01": date(2026, 9, 14),
    "OP-RUN-01": date(2026, 9, 15),
    "OP-SLIP-02": date(2026, 9, 16),
}
# 9 月裁断合格双数（与现有报工一致）
SEPTEMBER_PAIRS = {
    "A款": {"张三": 218, "王五": 290, "赵六": 183},
    "B款": {"张三": 129, "王五": 267, "赵六": 317},
    "C款": {"张三": 258, "王五": 217, "赵六": 88},
    "OP-BOOT-01": {"张三": 153, "王五": 91, "赵六": 243},
    "OP-RUN-01": {"张三": 121, "王五": 92, "赵六": 323},
    "OP-SLIP-02": {"张三": 226, "王五": 29, "赵六": 50},
}


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 9, 20) - LOCAL_OFFSET


def _qty(budget: Decimal, pairs: int, factor: Decimal) -> Decimal:
    raw = budget * Decimal(pairs) * factor
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def seed() -> None:
    db = SessionLocal()
    try:
        cut = db.scalar(
            select(ProcessSegment).where(
                ProcessSegment.tenant_id == TENANT_ID,
                ProcessSegment.code == "cut",
            )
        )
        if cut is None:
            raise SystemExit("没有裁断工序段")
        cats = {
            row.id: row.name
            for row in db.scalars(select(MaterialCategory).where(MaterialCategory.tenant_id == TENANT_ID)).all()
        }
        units = {
            row.id: row.name
            for row in db.scalars(select(PricingUnit).where(PricingUnit.tenant_id == TENANT_ID)).all()
        }
        created_docs = 0
        for code, people in SEPTEMBER_PAIRS.items():
            product = db.scalar(
                select(OwnProduct).where(
                    OwnProduct.tenant_id == TENANT_ID,
                    OwnProduct.product_code == code,
                )
            )
            if product is None:
                print(f"跳过，没有款 {code}")
                continue
            materials = []
            for bom in db.scalars(
                select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product.id)
            ).all():
                sp = db.get(SupplierProduct, bom.supplier_product_id)
                if sp is None:
                    continue
                cat_name = cats.get(sp.category_id)
                if cat_name not in CUT_CATEGORIES:
                    continue
                if bom.consume_segment_id is None:
                    bom.consume_segment_id = cut.id
                elif bom.consume_segment_id != cut.id:
                    continue
                materials.append((bom, sp, cat_name))
            if not materials:
                print(f"跳过，{code} 没有面料/皮料/超纤")
                continue

            header_no = f"CU-DEMO-{code}"[:50]
            header = db.scalar(
                select(ExecutionHeader).where(
                    ExecutionHeader.tenant_id == TENANT_ID,
                    ExecutionHeader.header_no == header_no,
                )
            )
            if header is None:
                header = ExecutionHeader(
                    tenant_id=TENANT_ID,
                    header_no=header_no,
                    own_product_id=product.id,
                    total_qty=sum(people.values()),
                    status=SpecExecutionStatus.cancelled,
                    notes="裁断用料演示，不进入在制生产单",
                )
                db.add(header)
                db.flush()

            req_by_sp: dict[int, OrderMaterialRequirement] = {}
            for bom, sp, _cat in materials:
                req = db.scalar(
                    select(OrderMaterialRequirement).where(
                        OrderMaterialRequirement.tenant_id == TENANT_ID,
                        OrderMaterialRequirement.header_id == header.id,
                        OrderMaterialRequirement.supplier_product_id == sp.id,
                    )
                )
                if req is None:
                    req = OrderMaterialRequirement(
                        tenant_id=TENANT_ID,
                        header_id=header.id,
                        supplier_product_id=sp.id,
                        qty_per_pair=bom.qty,
                        consume_segment_id=cut.id,
                        consume_segment_name=cut.name,
                    )
                    db.add(req)
                    db.flush()
                req_by_sp[sp.id] = req

            day = SIGN_DAY[code]
            for name, pairs in people.items():
                employee = db.scalar(
                    select(Employee).where(Employee.tenant_id == TENANT_ID, Employee.name == name)
                )
                if employee is None or pairs <= 0:
                    continue
                doc_no = f"CU2609-{code}-{employee.id}"[:50]
                exists = db.scalar(
                    select(WarehousePickup.id).where(
                        WarehousePickup.tenant_id == TENANT_ID,
                        WarehousePickup.doc_no == doc_no,
                    )
                )
                if exists:
                    continue
                factor = WORKER_FACTOR[name]
                pickup = WarehousePickup(
                    tenant_id=TENANT_ID,
                    doc_no=doc_no,
                    kind=WarehousePickupKind.production,
                    status=WarehousePickupStatus.signed,
                    header_id=header.id,
                    picker_employee_id=employee.id,
                    picker_name=employee.name,
                    signed_at=_at(day),
                    notes="裁断领料",
                )
                db.add(pickup)
                db.flush()
                for bom, sp, cat_name in materials:
                    qty = _qty(Decimal(bom.qty), pairs, factor * CATEGORY_NUDGE[cat_name])
                    if qty <= 0:
                        continue
                    db.add(
                        WarehousePickupLine(
                            tenant_id=TENANT_ID,
                            pickup_id=pickup.id,
                            supplier_product_id=sp.id,
                            requirement_id=req_by_sp[sp.id].id,
                            material_name=sp.name or sp.product_code,
                            material_code=sp.product_code,
                            unit_name=units.get(sp.pricing_unit_id),
                            qty=qty,
                        )
                    )
                created_docs += 1
                print(f"{code} {name} {pairs}双 {day.isoformat()} {doc_no}")
        db.commit()
        print(f"新增领料单 {created_docs} 张")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
