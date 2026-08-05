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
from app.db_schema import ensure_schema
from app.models import (
    Color,
    MaterialCategory,
    Order,
    OrderProcess,
    OrderProcessAssignment,
    OwnProduct,
    OwnProductLabor,
    Position,
    ProcessDefinition,
    ProcessType,
    PricingUnit,
    SalaryModel,
    Size,
    Station,
    Team,
    TeamMember,
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
    ensure_schema()
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
        manager = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == "manager"))
        if not manager:
            db.add(
                User(
                    tenant_id=tenant.id,
                    username="manager",
                    password_hash=hash_password("manager123"),
                    display_name="车间主管",
                    role=UserRole.manager,
                )
            )
        leader = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == "leader"))
        if not leader:
            db.add(
                User(
                    tenant_id=tenant.id,
                    username="leader",
                    password_hash=hash_password("leader123"),
                    display_name="针车组长",
                    role=UserRole.leader,
                )
            )
            db.flush()

        if not db.scalar(select(Color).where(Color.tenant_id == tenant.id)):
            for name, code in [("红", "R"), ("黑", "BK"), ("白", "W")]:
                db.add(Color(tenant_id=tenant.id, name=name, code=code))

        if not db.scalar(select(Size).where(Size.tenant_id == tenant.id)):
            for i, v in enumerate(["36", "37", "38", "39", "40"]):
                db.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))

        default_categories = [
            "皮料",
            "面料网布",
            "超纤革",
            "鞋底中底",
            "鞋垫内里",
            "五金扣",
            "拉链",
            "线材",
            "胶水化工",
            "鞋带魔术贴",
            "装饰件",
            "包装材料",
            "模具楦头",
            "其他辅料",
        ]
        for i, name in enumerate(default_categories):
            if not db.scalar(
                select(MaterialCategory).where(
                    MaterialCategory.tenant_id == tenant.id, MaterialCategory.name == name
                )
            ):
                db.add(
                    MaterialCategory(
                        tenant_id=tenant.id, name=name, sort_order=i, is_active=True
                    )
                )

        default_units = ["双", "米", "码", "公斤", "个", "套", "卷", "打", "片"]
        for i, name in enumerate(default_units):
            if not db.scalar(
                select(PricingUnit).where(PricingUnit.tenant_id == tenant.id, PricingUnit.name == name)
            ):
                db.add(PricingUnit(tenant_id=tenant.id, name=name, sort_order=i, is_active=True))

        default_positions = ["裁剪", "针车", "成型", "质检", "包装", "仓管", "杂工"]
        for i, name in enumerate(default_positions):
            if not db.scalar(
                select(Position).where(Position.tenant_id == tenant.id, Position.name == name)
            ):
                db.add(Position(tenant_id=tenant.id, name=name, sort_order=i, is_active=True))
        db.flush()
        position_ids = {
            p.name: p.id
            for p in db.scalars(select(Position).where(Position.tenant_id == tenant.id)).all()
        }

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
                    type=ProcessType.group if name == "成型" else ProcessType.personal,
                )
                db.add(p)
                db.flush()
            elif name == "成型" and p.type != ProcessType.group:
                p.type = ProcessType.group
            process_ids[name] = p.id

        db.flush()
        for op in db.scalars(
            select(OrderProcess).where(
                OrderProcess.tenant_id == tenant.id,
                OrderProcess.process_name == "成型",
            )
        ).all():
            op.process_type = ProcessType.group

        product = db.scalar(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant.id, OwnProduct.product_code == "A款")
        )
        if not product:
            product = OwnProduct(
                tenant_id=tenant.id,
                product_code="A款",
                quote_price=Decimal("68.00"),
                is_active=True,
            )
            db.add(product)
            db.flush()

        labor_total = Decimal("0")
        for name, (_, price, seq) in processes.items():
            labor = db.scalar(
                select(OwnProductLabor).where(
                    OwnProductLabor.tenant_id == tenant.id,
                    OwnProductLabor.own_product_id == product.id,
                    OwnProductLabor.process_id == process_ids[name],
                )
            )
            if not labor:
                db.add(
                    OwnProductLabor(
                        tenant_id=tenant.id,
                        own_product_id=product.id,
                        process_id=process_ids[name],
                        process_name=name,
                        unit_price=price,
                        sort_order=seq,
                    )
                )
                labor_total += price
            else:
                labor.process_name = name
                labor.unit_price = price
                labor.sort_order = seq
                labor_total += Decimal(labor.unit_price)
        product.labor_cost = labor_total.quantize(Decimal("0.0001"))

        worker_positions = {"张三": "针车", "李四": "成型", "王五": "裁剪"}
        for name, mobile in [("张三", "13800138001"), ("李四", "13800138002"), ("王五", "13800138003")]:
            w = db.scalar(select(Worker).where(Worker.tenant_id == tenant.id, Worker.name == name))
            if not w:
                w = Worker(
                    tenant_id=tenant.id,
                    name=name,
                    mobile=mobile,
                    role=WorkerRole.worker,
                )
                db.add(w)
                db.flush()
            w.mobile = mobile
            w.password_hash = hash_password(settings.worker_default_password)
            w.must_change_password = True
            w.is_active = True
            pos_name = worker_positions.get(name)
            if pos_name and pos_name in position_ids:
                w.position_id = position_ids[pos_name]
            # 李四演示「底薪+计件」：底薪 2000、定额 1000 双
            if name == "李四":
                w.salary_model = SalaryModel.base_plus_piece
                w.base_salary = Decimal("2000")
                w.base_quota = 1000
            elif name == "张三":
                w.salary_model = SalaryModel.pure_piece
                w.base_salary = Decimal("0")
                w.base_quota = 0

        db.commit()

        colors = {c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant.id))}
        sizes = {s.size_value: s.id for s in db.scalars(select(Size).where(Size.tenant_id == tenant.id))}

        if not db.scalar(select(Order).where(Order.tenant_id == tenant.id, Order.order_no == "230711")):
            create_order(
                db,
                tenant.id,
                OrderCreate(
                    order_no="230711",
                    customer_name="陈姐",
                    own_product_id=product.id,
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

        if not db.scalar(select(Order).where(Order.tenant_id == tenant.id, Order.order_no == "230712")):
            create_order(
                db,
                tenant.id,
                OrderCreate(
                    order_no="230712",
                    customer_name="李姐",
                    own_product_id=product.id,
                    delivery_date=date.today() + timedelta(days=10),
                    notes="演示并行单（扫码可更换）",
                    items=[
                        OrderItemIn(color_id=colors["黑"], size_id=sizes["38"], qty=300),
                        OrderItemIn(color_id=colors["黑"], size_id=sizes["39"], qty=300),
                    ],
                ),
                created_by=None,
            )

        workers = {
            w.name: w
            for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant.id)).all()
        }

        def ensure_assign(order_no: str, process_name: str, worker_names: list[str], quotas: list[int | None] | None = None):
            order = db.scalar(select(Order).where(Order.tenant_id == tenant.id, Order.order_no == order_no))
            if not order:
                return
            process = next((p for p in order.processes if p.process_name == process_name), None)
            if not process:
                return
            for i, wname in enumerate(worker_names):
                w = workers.get(wname)
                if not w:
                    continue
                quota = quotas[i] if quotas and i < len(quotas) else None
                exists = db.scalar(
                    select(OrderProcessAssignment).where(
                        OrderProcessAssignment.order_process_id == process.id,
                        OrderProcessAssignment.worker_id == w.id,
                    )
                )
                if not exists:
                    db.add(
                        OrderProcessAssignment(
                            tenant_id=tenant.id,
                            order_id=order.id,
                            order_process_id=process.id,
                            worker_id=w.id,
                            quota_qty=quota,
                        )
                    )
                else:
                    exists.quota_qty = quota
            if worker_names and worker_names[0] in workers:
                process.assigned_worker_id = workers[worker_names[0]].id

        # 扫码默认选单依赖派工：张三针车带配额并留未分配池；成型集体派张三+李四
        ensure_assign("230711", "针车", ["张三"], [600])  # 计划 1200 → 池 600
        ensure_assign("230712", "针车", ["张三"], [400])
        ensure_assign("230711", "成型", ["张三", "李四"], [600, 600])  # 池 0
        ensure_assign("230711", "裁断", ["王五"], [1000])  # 计划 1200 → 池 200

        demo_stations = [
            ("ZC-01", "针车1号位", "针车", "一车间A排"),
            ("ZC-02", "针车2号位", "针车", "一车间A排"),
            ("CX-01", "成型小组台", "成型", "二车间"),
        ]
        for code, name, pname, loc in demo_stations:
            if not db.scalar(select(Station).where(Station.tenant_id == tenant.id, Station.code == code)):
                db.add(
                    Station(
                        tenant_id=tenant.id,
                        code=code,
                        name=name,
                        process_id=process_ids[pname],
                        location=loc,
                    )
                )

        # 班组：leader 账号带「针车一组」，成员张三
        from app.services import rbac_service

        rbac_service.ensure_system_roles(db, tenant.id)
        leader_user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == "leader"))
        zhang = db.scalar(select(Worker).where(Worker.tenant_id == tenant.id, Worker.name == "张三"))
        if leader_user and zhang:
            team = db.scalar(select(Team).where(Team.tenant_id == tenant.id, Team.name == "针车一组"))
            if not team:
                team = Team(
                    tenant_id=tenant.id,
                    name="针车一组",
                    leader_user_id=leader_user.id,
                    is_active=True,
                )
                db.add(team)
                db.flush()
            else:
                team.leader_user_id = leader_user.id
                team.is_active = True
            mem = db.scalar(
                select(TeamMember).where(TeamMember.tenant_id == tenant.id, TeamMember.worker_id == zhang.id)
            )
            if not mem:
                db.add(TeamMember(tenant_id=tenant.id, team_id=team.id, worker_id=zhang.id))
            elif mem.team_id != team.id:
                mem.team_id = team.id

        db.commit()

        print(
            f"Seed OK. admin / admin123; manager / manager123; leader / leader123; "
            f"员工手机号登录默认密码 {settings.worker_default_password}（首次须改密）; "
            f"order 230711/230712; 工位扫码 /scan/ZC-01（张三针车已派工，可默认/更换）; "
            f"班组「针车一组」组长 leader，成员张三"
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
