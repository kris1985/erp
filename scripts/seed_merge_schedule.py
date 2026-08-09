"""造「合批 + 排产」可测数据（幂等，可重复跑）。

依赖：先有演示租户主数据（颜色/尺码/工序）。建议：
  .venv/bin/python scripts/seed_demo.py
  .venv/bin/python scripts/seed_merge_schedule.py

场景（订单号前缀 MS-）：
  白/同款/交期窗内/齐套 → 合批推荐一组（MS-W1~W3 + 急单 MS-WR）
  黑/同款/窗内/齐套 → 另一组合批（MS-K1~K2）
  白/交期窗外 → 不并进窗内组（MS-W-FAR）
  白/未齐套 → 不进合批推荐（MS-W-BLOCK）
  另款同色 → 不能合批（MS-OTHER）

同时写入排产粗产能，便于周负荷/智能方案有数可看。
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
from app.db import SessionLocal, engine
from app.db_schema import ensure_schema
from app.db import Base
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
from app.services import material_service, schedule_settings
from app.services.order_service import create_order


PRODUCT_CODE = "合批测-轻跑"
PREFIX = "MS-"


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
            quote_price=Decimal("88"),
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
        raise RuntimeError("无工序主数据，请先跑 scripts/seed_demo.py")

    for i, p in enumerate(processes):
        labor = db.scalar(
            select(OwnProductLabor).where(
                OwnProductLabor.tenant_id == tenant_id,
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
                    unit_price=Decimal("0.8") + Decimal(i) * Decimal("0.2"),
                    sort_order=i,
                )
            )

    # 若尚无 BOM：挂两条常用料（从现有供应商产品挑，或新建）
    bom_n = db.scalar(
        select(OwnProductMaterial.id)
        .where(OwnProductMaterial.own_product_id == product.id)
        .limit(1)
    )
    if not bom_n:
        sps = list(
            db.scalars(
                select(SupplierProduct)
                .where(SupplierProduct.tenant_id == tenant_id, SupplierProduct.is_active.is_(True))
                .limit(2)
            ).all()
        )
        if len(sps) < 2:
            partner = db.scalar(
                select(Partner).where(Partner.tenant_id == tenant_id, Partner.is_supplier.is_(True))
            )
            if not partner:
                partner = Partner(
                    tenant_id=tenant_id,
                    name="合批测供应商",
                    is_supplier=True,
                    is_active=True,
                )
                db.add(partner)
                db.flush()
            for code, name, price in [
                ("MS-MAT-MESH", "合批测网布", Decimal("2.5")),
                ("MS-MAT-SOLE", "合批测大底", Decimal("8.0")),
            ]:
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
                sps.append(sp)
        for i, sp in enumerate(sps[:2]):
            qty = Decimal("1") if i == 0 else Decimal("2")
            unit_price = Decimal(sp.unit_price or 0)
            db.add(
                OwnProductMaterial(
                    tenant_id=tenant_id,
                    own_product_id=product.id,
                    supplier_product_id=sp.id,
                    qty=qty,
                    unit_price=unit_price,
                    line_total=(qty * unit_price).quantize(Decimal("0.0001")),
                    loss_rate=Decimal("0.03"),
                    sort_order=i,
                )
            )
        product.material_cost = Decimal("0")
    db.flush()
    return product


def _ensure_other_product(db, tenant_id: int, processes: list[ProcessDefinition]) -> OwnProduct:
    code = "合批测-异款"
    product = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == code)
    )
    if not product:
        product = OwnProduct(
            tenant_id=tenant_id, product_code=code, quote_price=Decimal("72"), is_active=True
        )
        db.add(product)
        db.flush()
    for i, p in enumerate(processes[:3] or processes):
        exists = db.scalar(
            select(OwnProductLabor).where(
                OwnProductLabor.own_product_id == product.id,
                OwnProductLabor.process_id == p.id,
            )
        )
        if not exists:
            db.add(
                OwnProductLabor(
                    tenant_id=tenant_id,
                    own_product_id=product.id,
                    process_id=p.id,
                    process_name=p.name,
                    unit_price=Decimal("0.6"),
                    sort_order=i,
                )
            )
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
        if full:
            row.arrived_qty = row.required_qty or Decimal("0")
        else:
            # 故意零到货 → 缺料未齐套
            row.arrived_qty = Decimal("0")
    db.flush()


def _create_if_absent(
    db,
    tenant_id: int,
    *,
    order_no: str,
    product_id: int,
    customer: str,
    delivery: date,
    color_id: int,
    size_id: int,
    qtys: list[tuple[str, int]],
    is_rush: bool = False,
    notes: str = "",
    kit_full: bool = True,
) -> Order | None:
    existing = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))
    if existing:
        # 仍可刷新齐套状态，便于反复测
        _fill_kit(db, tenant_id, existing, full=kit_full)
        if existing.status == OrderStatus.cancelled:
            existing.status = OrderStatus.confirmed
        return existing

    sizes = {s.size_value: s.id for s in db.scalars(select(Size).where(Size.tenant_id == tenant_id))}
    items = []
    for size_val, qty in qtys:
        sid = sizes.get(size_val) or size_id
        items.append(OrderItemIn(color_id=color_id, size_id=sid, qty=qty))

    order = create_order(
        db,
        tenant_id,
        OrderCreate(
            order_no=order_no,
            customer_name=customer,
            own_product_id=product_id,
            delivery_date=delivery,
            is_rush=is_rush,
            rush_reason="合批测急单" if is_rush else None,
            notes=notes or "合批/排产测试单",
            items=items,
        ),
        created_by=None,
    )
    _fill_kit(db, tenant_id, order, full=kit_full)
    return order


def seed() -> None:
    settings = get_settings()
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    today = date.today()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        if not tenant:
            raise RuntimeError(f"找不到租户 {settings.default_tenant_name}，请先跑 seed_demo.py")

        colors = {
            c.name: c for c in db.scalars(select(Color).where(Color.tenant_id == tenant.id)).all()
        }
        if "白" not in colors or "黑" not in colors:
            raise RuntimeError("缺少颜色「白/黑」，请先跑 seed_demo.py")
        sizes = list(db.scalars(select(Size).where(Size.tenant_id == tenant.id)).all())
        if not sizes:
            raise RuntimeError("缺少尺码，请先跑 seed_demo.py")
        size38 = next((s for s in sizes if s.size_value == "38"), sizes[0])

        processes = list(
            db.scalars(
                select(ProcessDefinition).where(
                    ProcessDefinition.tenant_id == tenant.id,
                    ProcessDefinition.is_active.is_(True),
                )
            ).all()
        )
        product = _ensure_product(db, tenant.id)
        other = _ensure_other_product(db, tenant.id, processes)

        # 排产粗产能 + 合批旋钮（与 seed_schedule_proposals 对齐，避免互相覆盖失真）
        cap = {str(p.id): 500 for p in processes}
        schedule_settings.save_schedule_patch(
            db,
            tenant.id,
            {
                "default_process_days": 1,
                "tight_days": 2,
                "daily_capacity_by_process": cap,
                "default_daily_capacity": 500,
                "merge_delivery_window_days": 7,
                "merge_require_same_color": True,
                "merge_min_qty": 0,
                "load_warn_utilization": 0.9,
                "allow_schedule_on_non_workdays": False,
            },
        )

        white = colors["白"].id
        black = colors["黑"].id

        specs = [
            # —— 白·同款·齐套·窗内（应荐合批）——
            dict(
                order_no=f"{PREFIX}W1",
                customer="陈姐",
                delivery=today + timedelta(days=3),
                color_id=white,
                qtys=[("37", 120), ("38", 180)],
                kit_full=True,
                notes="白·齐套·交期近 → 合批主成员",
            ),
            dict(
                order_no=f"{PREFIX}W2",
                customer="李姐",
                delivery=today + timedelta(days=5),
                color_id=white,
                qtys=[("38", 100), ("39", 100)],
                kit_full=True,
                notes="白·齐套·同窗",
            ),
            dict(
                order_no=f"{PREFIX}W3",
                customer="王总",
                delivery=today + timedelta(days=6),
                color_id=white,
                qtys=[("37", 80), ("40", 70)],
                kit_full=True,
                notes="白·齐套·同窗",
            ),
            dict(
                order_no=f"{PREFIX}WR",
                customer="急单客",
                delivery=today + timedelta(days=4),
                color_id=white,
                qtys=[("38", 60)],
                kit_full=True,
                is_rush=True,
                notes="白·急·齐套·同窗",
            ),
            # —— 白·齐套·窗外 ——
            dict(
                order_no=f"{PREFIX}W-FAR",
                customer="远交期客",
                delivery=today + timedelta(days=21),
                color_id=white,
                qtys=[("38", 200)],
                kit_full=True,
                notes="白·齐套·交期窗外，不并进近窗组",
            ),
            # —— 白·未齐套 ——
            dict(
                order_no=f"{PREFIX}W-BLOCK",
                customer="等料客",
                delivery=today + timedelta(days=4),
                color_id=white,
                qtys=[("38", 150)],
                kit_full=False,
                notes="白·缺料 → 合批推荐应跳过",
            ),
            # —— 黑·同款·齐套·窗内 ——
            dict(
                order_no=f"{PREFIX}K1",
                customer="黑款客甲",
                delivery=today + timedelta(days=2),
                color_id=black,
                qtys=[("39", 110), ("40", 90)],
                kit_full=True,
                notes="黑·齐套·同窗",
            ),
            dict(
                order_no=f"{PREFIX}K2",
                customer="黑款客乙",
                delivery=today + timedelta(days=5),
                color_id=black,
                qtys=[("38", 130)],
                kit_full=True,
                notes="黑·齐套·同窗",
            ),
            # —— 异款 ——
            dict(
                order_no=f"{PREFIX}OTHER",
                customer="异款客",
                delivery=today + timedelta(days=4),
                color_id=white,
                qtys=[("38", 90)],
                kit_full=True,
                notes="异款同色 → 不能与轻跑合批",
                product_id=other.id,
            ),
        ]

        created = []
        for s in specs:
            o = _create_if_absent(
                db,
                tenant.id,
                order_no=s["order_no"],
                product_id=s.get("product_id", product.id),
                customer=s["customer"],
                delivery=s["delivery"],
                color_id=s["color_id"],
                size_id=size38.id,
                qtys=s["qtys"],
                is_rush=bool(s.get("is_rush")),
                notes=s.get("notes") or "",
                kit_full=bool(s.get("kit_full", True)),
            )
            if o:
                created.append(o.order_no)

        db.commit()

        # 自检推荐
        from app.services import merge_suggest_service

        sug = merge_suggest_service.suggest_merge_batches(db, tenant.id)
        print("=== 合批/排产测试数据就绪 ===")
        print(f"租户: {tenant.name} (id={tenant.id})")
        print(f"款号: {PRODUCT_CODE} / 异款: 合批测-异款")
        print(f"订单: {', '.join(created)}")
        print(f"合批推荐组数: {len(sug.get('items') or [])}")
        for it in sug.get("items") or []:
            nos = [o.get("order_no") for o in it.get("orders") or []]
            print(
                f"  · {it.get('product_code')} {it.get('color_name') or ''} "
                f"{it.get('order_count')}单/{it.get('total_qty')}双 → {', '.join(nos)}"
            )
        print("跳过:", sug.get("skipped"))
        print()
        print("建议手测：")
        print("  1) 排产 → 合批推荐：应见白组(MS-W*)与黑组(MS-K*)；不见 W-BLOCK / OTHER 混入")
        print("  2) 排产池勾选白组 → 智能方案；不勾选点车间军师 → 读待排池建议")
        print("  3) 按合批筛选：采纳一组后池下拉可见合批号")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
