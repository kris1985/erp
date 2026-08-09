"""造「智能排产方案」对比数据（幂等）。

目标：点「智能方案」时三套策略指标明显不同——
  · 保交期 delivery_first：近交期硬排 → 超产能天数 / 负荷峰偏高
  · 保现场 capacity_first：顺延避峰 → 超产能≈0，但延期/偏紧可能更多
  · 只排齐套 kit_ready：跳过未齐套单（需池内同时有齐套+缺料）

用法：
  .venv/bin/python scripts/seed_demo.py          # 若尚无主数据
  .venv/bin/python scripts/seed_schedule_proposals.py

订单前缀 SP-；款号「排产测-对比」。
手测：排产池筛「排产测」或勾选 SP-* → 智能方案，看对比卡延期单数 / 负荷峰。
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.db_schema import ensure_schema
from app.models import (
    Color,
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    Size,
    SupplierProduct,
    Tenant,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services import material_service, schedule_engine, schedule_settings
from app.services.order_service import create_order

PRODUCT_CODE = "排产测-对比"
PREFIX = "SP-"
# 合理日产能：全厂演示不至于四位数负荷峰；勾选 SP-* 仍可看出策略差
DAILY_CAP = 500


def _ensure_product(db, tenant_id: int) -> OwnProduct:
    product = db.scalar(
        select(OwnProduct).where(
            OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == PRODUCT_CODE
        )
    )
    if not product:
        product = OwnProduct(
            tenant_id=tenant_id,
            product_code=PRODUCT_CODE,
            quote_price=Decimal("96"),
            is_active=True,
        )
        db.add(product)
        db.flush()

    processes = list(
        db.scalars(
            select(ProcessDefinition)
            .where(ProcessDefinition.tenant_id == tenant_id, ProcessDefinition.is_active.is_(True))
            .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
        ).all()
    )
    if not processes:
        raise RuntimeError("无工序，请先 seed_demo.py")

    for i, p in enumerate(processes):
        labor = db.scalar(
            select(OwnProductLabor).where(
                OwnProductLabor.own_product_id == product.id,
                OwnProductLabor.process_id == p.id,
            )
        )
        if not labor:
            db.add(
                OwnProductLabor(
                    tenant_id=tenant_id,
                    own_product_id=product.id,
                    process_id=p.id,
                    process_name=p.name,
                    unit_price=Decimal("1.0"),
                    sort_order=i,
                )
            )

    if not db.scalar(
        select(OwnProductMaterial.id).where(OwnProductMaterial.own_product_id == product.id).limit(1)
    ):
        partner = db.scalar(
            select(Partner).where(Partner.tenant_id == tenant_id, Partner.is_supplier.is_(True))
        )
        if not partner:
            partner = Partner(
                tenant_id=tenant_id, name="排产测供应商", is_supplier=True, is_active=True
            )
            db.add(partner)
            db.flush()
        for i, (code, name, price, qty) in enumerate(
            [
                ("SP-MAT-UPPER", "排产测面料", Decimal("3.2"), Decimal("1.2")),
                ("SP-MAT-SOLE", "排产测大底", Decimal("9.5"), Decimal("1")),
            ]
        ):
            sp = db.scalar(
                select(SupplierProduct).where(
                    SupplierProduct.tenant_id == tenant_id,
                    SupplierProduct.product_code == code,
                )
            )
            if not sp:
                sp = SupplierProduct(
                    tenant_id=tenant_id,
                    partner_id=partner.id,
                    product_code=code,
                    name=name,
                    unit_price=price,
                    is_active=True,
                )
                db.add(sp)
                db.flush()
            db.add(
                OwnProductMaterial(
                    tenant_id=tenant_id,
                    own_product_id=product.id,
                    supplier_product_id=sp.id,
                    qty=qty,
                    unit_price=price,
                    line_total=(qty * price).quantize(Decimal("0.0001")),
                    loss_rate=Decimal("0.02"),
                    sort_order=i,
                )
            )
    db.flush()
    return product


def _fill_kit(db, tenant_id: int, order: Order, *, full: bool) -> None:
    material_service.ensure_material_snapshot(db, tenant_id, order)
    db.flush()
    rows = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                OrderMaterialRequirement.order_id == order.id,
            )
        ).all()
    )
    for row in rows:
        if row.is_customer_supplied:
            continue
        row.arrived_qty = (row.required_qty or Decimal("0")) if full else Decimal("0")
    db.flush()


def _upsert_order(
    db,
    tenant_id: int,
    *,
    order_no: str,
    product_id: int,
    customer: str,
    delivery: date,
    color_id: int,
    size_map: dict[str, int],
    qtys: list[tuple[str, int]],
    is_rush: bool = False,
    kit_full: bool = True,
    notes: str = "",
) -> Order:
    existing = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))
    if existing:
        existing.delivery_date = delivery
        existing.is_rush = is_rush
        existing.notes = notes or existing.notes
        if existing.status == OrderStatus.cancelled:
            existing.status = OrderStatus.confirmed
        # 清掉已排日期，保证仍在待排池
        for p in existing.processes or []:
            p.start_date = None
            p.end_date = None
        from app.models import ScheduleStatus

        if hasattr(existing, "schedule_status"):
            existing.schedule_status = ScheduleStatus.none
        _fill_kit(db, tenant_id, existing, full=kit_full)
        return existing

    items = [
        OrderItemIn(color_id=color_id, size_id=size_map.get(sv) or next(iter(size_map.values())), qty=q)
        for sv, q in qtys
    ]
    order = create_order(
        db,
        tenant_id,
        OrderCreate(
            order_no=order_no,
            customer_name=customer,
            own_product_id=product_id,
            delivery_date=delivery,
            is_rush=is_rush,
            rush_reason="排产对比急单" if is_rush else None,
            notes=notes or "智能方案对比测试",
            items=items,
        ),
        created_by=None,
    )
    _fill_kit(db, tenant_id, order, full=kit_full)
    return order


def _headline(p: dict) -> dict:
    risks = p.get("risks") or {}
    load = p.get("load") or []
    peak = None
    over_days = 0
    for row in load:
        if row.get("over_capacity"):
            over_days += 1
        u = row.get("utilization")
        if u is None:
            continue
        if peak is None or u > peak["utilization"]:
            peak = row
    return {
        "title": p.get("title"),
        "strategy": p.get("strategy"),
        "late": risks.get("late", 0),
        "tight": risks.get("tight", 0),
        "capacity": risks.get("capacity_blocked", 0),
        "kit_blocked": risks.get("kit_blocked", 0),
        "orders": len(p.get("orders") or []),
        "peak_pct": round(peak["utilization"] * 100) if peak else None,
        "over_days": over_days,
        "summary": (p.get("summary") or "")[:120],
    }


def seed() -> None:
    settings = get_settings()
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    today = date.today()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        if not tenant:
            raise RuntimeError("无演示租户，请先 seed_demo.py")

        colors = {
            c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant.id))
        }
        if "黑" not in colors:
            raise RuntimeError("缺颜色「黑」")
        size_map = {
            s.size_value: s.id for s in db.scalars(select(Size).where(Size.tenant_id == tenant.id))
        }
        processes = list(
            db.scalars(
                select(ProcessDefinition).where(
                    ProcessDefinition.tenant_id == tenant.id,
                    ProcessDefinition.is_active.is_(True),
                )
            ).all()
        )
        product = _ensure_product(db, tenant.id)

        # 压产能 + 短工期：放大策略差异
        schedule_settings.save_schedule_patch(
            db,
            tenant.id,
            {
                "default_process_days": 2,
                "tight_days": 2,
                "daily_capacity_by_process": {str(p.id): DAILY_CAP for p in processes},
                "default_daily_capacity": DAILY_CAP,
                "load_warn_utilization": 0.85,
            },
        )

        black = colors["黑"]
        specs = [
            # 近交期大单堆叠 → 保交期必超产能
            dict(
                order_no=f"{PREFIX}HOT1",
                customer="华东急单",
                delivery=today + timedelta(days=5),
                qtys=[("38", 140), ("39", 120)],  # 260
                is_rush=True,
                kit_full=True,
                notes="急·近交期·齐套",
            ),
            dict(
                order_no=f"{PREFIX}HOT2",
                customer="外贸批",
                delivery=today + timedelta(days=6),
                qtys=[("37", 100), ("38", 120)],  # 220
                kit_full=True,
                notes="近交期·齐套",
            ),
            dict(
                order_no=f"{PREFIX}HOT3",
                customer="经销商甲",
                delivery=today + timedelta(days=7),
                qtys=[("39", 90), ("40", 110)],  # 200
                kit_full=True,
                notes="近交期·齐套",
            ),
            # 远交期小单：保现场可往后排
            dict(
                order_no=f"{PREFIX}COLD",
                customer="备货客",
                delivery=today + timedelta(days=40),
                qtys=[("38", 80)],
                kit_full=True,
                notes="远交期·齐套",
            ),
            # 缺料：激活「只排齐套」
            dict(
                order_no=f"{PREFIX}WAIT",
                customer="等料客",
                delivery=today + timedelta(days=6),
                qtys=[("38", 80), ("39", 60)],  # 140
                kit_full=False,
                notes="近交期·缺料 → 只排齐套应跳过",
            ),
        ]

        ids = []
        for s in specs:
            o = _upsert_order(
                db,
                tenant.id,
                order_no=s["order_no"],
                product_id=product.id,
                customer=s["customer"],
                delivery=s["delivery"],
                color_id=black,
                size_map=size_map,
                qtys=s["qtys"],
                is_rush=bool(s.get("is_rush")),
                kit_full=bool(s.get("kit_full", True)),
                notes=s.get("notes") or "",
            )
            ids.append(o.id)

        db.commit()

        pack = schedule_engine.generate_proposals(
            db, tenant.id, order_ids=ids, hide_scheduled=False
        )
        props = pack.get("items") or []
        print("=== 智能排产对比数据就绪 ===")
        print(f"租户: {tenant.name}  款: {PRODUCT_CODE}  日产能: {DAILY_CAP}双/工序")
        print(f"订单: {', '.join(s['order_no'] for s in specs)}")
        print(f"方案数: {len(props)}")
        for h in [_headline(p) for p in props]:
            print(
                f"  [{h['title']}/{h['strategy']}] "
                f"排{h['orders']}单 逾期={h['late']} 偏紧={h['tight']} "
                f"产能冲突={h.get('capacity', h.get('kit_blocked'))} 超产能天={h['over_days']} "
                f"负荷峰={h['peak_pct']}%"
            )
            print(f"    {h['summary']}")

        by = {p["strategy"]: _headline(p) for p in props}
        if "delivery_first" in by and "capacity_first" in by:
            d, c = by["delivery_first"], by["capacity_first"]
            differ = (
                d["over_days"] != c["over_days"]
                or d["late"] != c["late"]
                or (d["peak_pct"] or 0) != (c["peak_pct"] or 0)
            )
            print("保交期 vs 保现场 指标有区别:" , "✅" if differ else "⚠️ 仍相近，可再压产能或加大近交期量")
        if "kit_ready" in by:
            print(
                f"只排齐套订单数={by['kit_ready']['orders']} "
                f"(应少于全量 {len(ids)})"
            )
        print()
        print("手测：排产池关键词「排产测」或勾选 SP-HOT* + SP-COLD + SP-WAIT → 智能方案")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
