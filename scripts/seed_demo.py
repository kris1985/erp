"""Seed demo tenant, admin, masters, and a sample order."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.auth import hash_password
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Color,
    ProcessDefinition,
    Size,
    Style,
    StyleProcessRoute,
    Tenant,
    User,
    UserRole,
    Worker,
    WorkerRole,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order


def seed():
    settings = get_settings()
    Path("data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        if not tenant:
            tenant = Tenant(name=settings.default_tenant_name, contact_person="老板", contact_mobile="13800000000")
            db.add(tenant)
            db.flush()

        admin = db.scalar(
            select(User).where(User.tenant_id == tenant.id, User.username == settings.admin_username)
        )
        if not admin:
            db.add(
                User(
                    tenant_id=tenant.id,
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    display_name="管理员",
                    role=UserRole.admin,
                )
            )

        if not db.scalar(select(Color).where(Color.tenant_id == tenant.id)):
            for name, code in [("红", "R"), ("黑", "BK"), ("白", "W")]:
                db.add(Color(tenant_id=tenant.id, name=name, code=code))

        if not db.scalar(select(Size).where(Size.tenant_id == tenant.id)):
            for i, v in enumerate(["36", "37", "38", "39", "40"]):
                db.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))

        processes = {
            "裁断": ("CT", Decimal("0.30"), 1),
            "针车": ("ZC", Decimal("0.50"), 2),
            "成型": ("CX", Decimal("0.80"), 3),
            "包装": ("BZ", Decimal("0.20"), 4),
        }
        process_ids = {}
        for name, (code, price, seq) in processes.items():
            p = db.scalar(
                select(ProcessDefinition).where(
                    ProcessDefinition.tenant_id == tenant.id, ProcessDefinition.code == code
                )
            )
            if not p:
                p = ProcessDefinition(
                    tenant_id=tenant.id,
                    name=name,
                    code=code,
                    default_price=price,
                    sort_order=seq,
                )
                db.add(p)
                db.flush()
            process_ids[name] = p.id

        style = db.scalar(select(Style).where(Style.tenant_id == tenant.id, Style.style_code == "A款"))
        if not style:
            style = Style(tenant_id=tenant.id, style_code="A款", style_name="A款红色运动鞋", default_color="红")
            db.add(style)
            db.flush()
            for name, (_, price, seq) in processes.items():
                db.add(
                    StyleProcessRoute(
                        tenant_id=tenant.id,
                        style_id=style.id,
                        process_id=process_ids[name],
                        seq=seq,
                        price=price,
                        price_type="normal",
                    )
                )

        for name, mobile in [("张三", "13800138001"), ("李四", "13800138002"), ("王五", "13800138003")]:
            if not db.scalar(select(Worker).where(Worker.tenant_id == tenant.id, Worker.name == name)):
                db.add(
                    Worker(
                        tenant_id=tenant.id,
                        name=name,
                        mobile=mobile,
                        role=WorkerRole.worker,
                    )
                )

        db.commit()

        from app.models import Order

        if not db.scalar(select(Order).where(Order.tenant_id == tenant.id, Order.order_no == "230711")):
            colors = {c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant.id))}
            sizes = {s.size_value: s.id for s in db.scalars(select(Size).where(Size.tenant_id == tenant.id))}
            create_order(
                db,
                tenant.id,
                OrderCreate(
                    order_no="230711",
                    customer_name="陈姐",
                    style_id=style.id,
                    delivery_date=date.today() + timedelta(days=7),
                    notes="演示订单",
                    items=[
                        OrderItemIn(color_id=colors["红"], size_id=sizes["37"], qty=400),
                        OrderItemIn(color_id=colors["红"], size_id=sizes["38"], qty=400),
                        OrderItemIn(color_id=colors["红"], size_id=sizes["39"], qty=400),
                    ],
                ),
                created_by=None,
            )

        print("Seed OK. admin / admin123, sample order 230711")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
