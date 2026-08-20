"""B2a 外发演示数据：3 家外协厂 + 1 张外发单（发料/收回闭环）。幂等。

可单独运行：`python scripts/seed_subcontract_demo.py`
也会被 `scripts/seed_demo.py` 末尾调用，跑主 seed 即开箱可见。
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.db_schema import ensure_schema
from app.models import (
    ExecutionHeader,
    Order,
    OwnProduct,
    Partner,
    ProcessDefinition,
    SubcontractOrder,
    Tenant,
)
from app.services.subcontract_out_service import (
    create_subcontract_order,
    issue_subcontract,
    receive_subcontract,
)

FACTORIES = [
    ("鼎盛针车", "鼎盛针车", 30),
    ("宏发成型", "宏发成型", 15),
    ("顺达包装", "顺达包装", 0),
]
DEMO_SUBCONTRACT_NO = "SC-DEMO-01"


def seed_b2a(db, tenant_id: int) -> None:
    """幂等：外协厂 + 一张外发单（发 100 收 60 → 欠 40 / 损耗 40 / 应付 150）。"""
    # 1. 外协厂（is_subcontractor）
    factory_ids: dict[str, int] = {}
    for name, short, term in FACTORIES:
        p = db.scalar(select(Partner).where(Partner.tenant_id == tenant_id, Partner.name == name))
        if not p:
            p = Partner(
                tenant_id=tenant_id,
                name=name,
                short_name=short,
                is_supplier=True,
                is_subcontractor=True,
                is_active=True,
                payment_term_days=term,
            )
            db.add(p)
            db.flush()
        else:
            p.is_subcontractor = True
            p.is_supplier = True
            p.is_active = True
        factory_ids[name] = p.id

    # 2. 工序（针车优先）
    proc = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.tenant_id == tenant_id, ProcessDefinition.name == "针车"
        )
    )
    if not proc:
        proc = db.scalar(
            select(ProcessDefinition)
            .where(ProcessDefinition.tenant_id == tenant_id)
            .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
        )

    # 3. 关联追溯：优先复用已有执行单头；其次已有生产单；都没有则不挂（不新建空头）
    product = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == tenant_id).order_by(OwnProduct.id)
    )
    header = db.scalar(
        select(ExecutionHeader)
        .where(ExecutionHeader.tenant_id == tenant_id)
        .order_by(ExecutionHeader.id)
    )
    order = None
    if not header:
        order = db.scalar(select(Order).where(Order.tenant_id == tenant_id).order_by(Order.id))

    # 4. 外发单
    existing = db.scalar(
        select(SubcontractOrder).where(
            SubcontractOrder.tenant_id == tenant_id,
            SubcontractOrder.subcontract_no == DEMO_SUBCONTRACT_NO,
        )
    )
    if existing:
        return
    if not proc or not factory_ids.get("鼎盛针车"):
        return
    sc_order = create_subcontract_order(
        db,
        tenant_id,
        partner_id=factory_ids["鼎盛针车"],
        process_id=proc.id,
        header_id=header.id if header else None,
        order_id=order.id if (order and not header) else None,
        own_product_id=product.id if product else None,
        total_qty=100,
        unit_price=Decimal("2.50"),
        notes="演示：发 100 收 60，欠 40，损耗 40",
    )
    sc_order.subcontract_no = DEMO_SUBCONTRACT_NO
    db.commit()
    issue_subcontract(db, tenant_id, sc_order.id, qty=100, note="首批外发")
    receive_subcontract(db, tenant_id, sc_order.id, qty=60, defect_qty=2, note="首轮收回")
    print(
        f"[B2a] 外发单 {sc_order.subcontract_no}：发 100 / 收 60 / 欠 40 / 损耗 40 / 应付 {60 * 2.5:.2f}"
    )


def seed():
    settings = get_settings()
    Path("data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        if not tenant:
            print("无演示租户，请先跑 scripts/seed_demo.py")
            return
        seed_b2a(db, tenant.id)
        db.commit()
        print("B2a 外发演示数据 OK：鼎盛针车 / 宏发成型 / 顺达包装（外协厂）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
