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
    OwnProductColor,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    Position,
    ProcessDefinition,
    ProcessType,
    PricingUnit,
    SalaryModel,
    Size,
    Station,
    SupplierProduct,
    Team,
    TeamMember,
    Tenant,
    Employee,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order


def _seed_b1c_sample_bom(db, tenant_id: int, product: OwnProduct) -> None:
    """最小 B1c 样例：面料按双 + 大底按码（与 rich seed 编码对齐，便于只跑 seed_demo）。"""
    from app.services.material_service import ensure_default_size_usage_table

    cats = {
        c.name: c
        for c in db.scalars(
            select(MaterialCategory).where(MaterialCategory.tenant_id == tenant_id)
        ).all()
    }
    units = {
        u.name: u
        for u in db.scalars(select(PricingUnit).where(PricingUnit.tenant_id == tenant_id)).all()
    }
    colors = {
        c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant_id)).all()
    }

    def ensure_supplier(name: str, short_name: str) -> Partner:
        p = db.scalar(select(Partner).where(Partner.tenant_id == tenant_id, Partner.name == name))
        if not p:
            p = Partner(
                tenant_id=tenant_id,
                name=name,
                short_name=short_name,
                is_supplier=True,
                is_active=True,
            )
            db.add(p)
            db.flush()
        else:
            p.is_supplier = True
            p.short_name = p.short_name or short_name
        return p

    def ensure_sp(
        code: str,
        *,
        name: str,
        partner_id: int,
        category_id: int | None,
        pricing_unit_id: int | None,
        color_id: int | None,
        unit_price: Decimal,
    ) -> SupplierProduct:
        sp = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == tenant_id, SupplierProduct.product_code == code
            )
        )
        if not sp:
            sp = SupplierProduct(
                tenant_id=tenant_id,
                product_code=code,
                name=name,
                partner_id=partner_id,
                category_id=category_id,
                pricing_unit_id=pricing_unit_id,
                color_id=color_id,
                unit_price=unit_price,
                is_active=True,
            )
            db.add(sp)
            db.flush()
        else:
            sp.name = name
            sp.partner_id = partner_id
            sp.category_id = category_id
            sp.pricing_unit_id = pricing_unit_id
            sp.color_id = color_id
            sp.unit_price = unit_price
            sp.is_active = True
        return sp

    hr = ensure_supplier("华瑞面料", "华瑞面料")
    td = ensure_supplier("腾达鞋材", "腾达鞋材")
    mesh = ensure_sp(
        "HR-MESH-01",
        name="飞织网布",
        partner_id=hr.id,
        category_id=cats["面料网布"].id if "面料网布" in cats else None,
        pricing_unit_id=units["米"].id if "米" in units else None,
        color_id=colors.get("黑"),
        unit_price=Decimal("12.00"),
    )
    sole = ensure_sp(
        "TD-RB-001",
        name="橡胶大底",
        partner_id=td.id,
        category_id=cats["大底"].id if "大底" in cats else None,
        pricing_unit_id=units["双"].id if "双" in units else None,
        color_id=colors.get("黑"),
        unit_price=Decimal("8.50"),
    )
    size_table_id = ensure_default_size_usage_table(db, tenant_id).id

    for old in db.scalars(
        select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product.id)
    ).all():
        db.delete(old)
    db.flush()

    lines = [
        (mesh, Decimal("0.5"), False, Decimal("0.03"), Decimal("0")),
        (sole, Decimal("1"), True, Decimal("0"), Decimal("2")),
    ]
    total = Decimal("0")
    for i, (sp, qty, by_size, loss_rate, loss_fixed) in enumerate(lines):
        unit_price = Decimal(sp.unit_price or 0)
        line = (qty * unit_price).quantize(Decimal("0.0001"))
        total += line
        db.add(
            OwnProductMaterial(
                tenant_id=tenant_id,
                own_product_id=product.id,
                supplier_product_id=sp.id,
                qty=qty,
                unit_price=unit_price,
                line_total=line,
                sort_order=i,
                usage_by_size=by_size,
                size_usage_table_id=size_table_id if by_size else None,
                loss_rate=loss_rate,
                loss_fixed_qty=loss_fixed,
            )
        )
    product.material_cost = total.quantize(Decimal("0.0001"))


def _seed_b1c_walkthrough_order(
    db,
    tenant_id: int,
    product: OwnProduct,
    colors: dict[str, int],
    sizes: dict[str, int],
) -> None:
    """B1c 走查样例单：37×100 + 42×80。"""
    if not sizes.get("37") or not sizes.get("42"):
        return
    if db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == "B1C-WALK")):
        return
    color_id = colors.get("黑") or colors.get("红") or next(iter(colors.values()), None)
    if not color_id:
        return
    order = create_order(
        db,
        tenant_id,
        OrderCreate(
            order_no="B1C-WALK",
            customer_name="B1c走查",
            own_product_id=product.id,
            delivery_date=date.today() + timedelta(days=14),
            notes="B1c样例：面料按双 + 大底按码（37=100 / 42=80）",
            items=[
                OrderItemIn(color_id=color_id, size_id=sizes["37"], qty=100),
                OrderItemIn(color_id=color_id, size_id=sizes["42"], qty=80),
            ],
        ),
        created_by=None,
    )
    # create_order 已 ensure_material_snapshot
    print(f"B1c walkthrough order {order.order_no}: total={order.total_qty}")


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

        from app.services import rbac_service

        rbac_service.ensure_system_roles(db, tenant.id)

        def _ensure_account(username: str, password: str, name: str, role_codes: list[str], *, is_leader: bool = False) -> Employee:
            """合并后：员工档案即账号本体；无账号的纯员工另建。"""
            emp = db.scalar(
                select(Employee).where(Employee.tenant_id == tenant.id, Employee.username == username)
            )
            if not emp:
                emp = Employee(
                    tenant_id=tenant.id,
                    name=name,
                    username=username,
                    password_hash=hash_password(password),
                    must_change_password=False,
                    salary_model=SalaryModel.fixed,
                    is_active=True,
                )
                db.add(emp)
                db.flush()
            rbac_service.set_employee_roles(db, emp, role_codes)
            return emp

        admin = _ensure_account(settings.admin_username, settings.admin_password, "管理员", ["admin"], is_leader=True)
        manager = _ensure_account("manager", "manager123", "厂长", ["manager"])
        # 车间主管账号 = 「针车组长」员工本体（合并后一人一条档案）
        leader = _ensure_account("leader", "leader123", "针车组长", ["workshop"], is_leader=True)

        if not db.scalar(select(Color).where(Color.tenant_id == tenant.id)):
            for name, code in [("红", "R"), ("黑", "BK"), ("白", "W")]:
                db.add(Color(tenant_id=tenant.id, name=name, code=code))

        for i, v in enumerate(["36", "37", "38", "39", "40", "41", "42"]):
            if not db.scalar(
                select(Size).where(Size.tenant_id == tenant.id, Size.size_value == v)
            ):
                db.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))

        default_categories = [
            "皮料",
            "面料网布",
            "超纤革",
            "内里",
            "鞋垫",
            "大底",
            "中底",
            "泡棉海绵",
            "五金扣",
            "拉链",
            "线材",
            "补强胶膜",
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
        db.flush()
        from app.services.material_service import (
            ensure_default_size_usage_table,
            split_legacy_material_categories,
        )

        ensure_default_size_usage_table(db, tenant.id)
        split_legacy_material_categories(db, tenant.id)

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

        from app.models import Department

        # 部门：厂部/开发部/针车部（含子部门组）/成型部/采购部；主管=对应账号员工
        dept_defs = [
            ("厂部", None),
            ("开发部", None),
            ("采购部", None),
            ("针车部", None),
            ("针车一组", "针车部"),
            ("针车二组", "针车部"),
            ("成型部", None),
        ]
        dept_by_name: dict[str, Department] = {}
        for dname, parent in dept_defs:
            dep = db.scalar(
                select(Department).where(Department.tenant_id == tenant.id, Department.name == dname)
            )
            if not dep:
                dep = Department(
                    tenant_id=tenant.id,
                    name=dname,
                    parent_id=dept_by_name[parent].id if parent else None,
                    is_active=True,
                )
                db.add(dep)
                db.flush()
            dept_by_name[dname] = dep
        # 主管：厂长管厂部，车间主管管针车部
        mgr_emp = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "厂长"))
        if mgr_emp:
            dept_by_name["厂部"].manager_employee_id = mgr_emp.id
        leader_emp = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "针车组长"))
        if leader_emp:
            dept_by_name["针车部"].manager_employee_id = leader_emp.id
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
                    per_worker_capacity=60 if name == "裁断" else 50 if name == "针车" else 80 if name == "成型" else 100,
                    standard_workers=1 if name == "裁断" else 2 if name == "针车" else 2 if name == "成型" else 1,
                    sort_order=seq,
                    type=ProcessType.group if name == "成型" else ProcessType.personal,
                )
                db.add(p)
                db.flush()
            else:
                if name == "成型" and p.type != ProcessType.group:
                    p.type = ProcessType.group
                p.per_worker_capacity = 60 if name == "裁断" else 50 if name == "针车" else 80 if name == "成型" else 100
                p.standard_workers = 1 if name == "裁断" else 2 if name == "针车" else 2 if name == "成型" else 1
            process_ids[name] = p.id

        db.flush()
        from app.services.material_service import ensure_default_category_consume_processes

        ensure_default_category_consume_processes(db, tenant.id)
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

        black = db.scalar(
            select(Color).where(Color.tenant_id == tenant.id, Color.name == "黑")
        )
        if black and not db.scalar(
            select(OwnProductColor.id).where(
                OwnProductColor.own_product_id == product.id,
                OwnProductColor.color_id == black.id,
            )
        ):
            db.add(
                OwnProductColor(
                    tenant_id=tenant.id,
                    own_product_id=product.id,
                    color_id=black.id,
                )
            )

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
        _seed_b1c_sample_bom(db, tenant.id, product)

        worker_positions = {"张三": "针车", "李四": "成型", "王五": "裁剪"}
        for name, mobile in [("张三", "13800138001"), ("李四", "13800138002"), ("王五", "13800138003")]:
            w = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == name))
            if not w:
                w = Employee(
                    tenant_id=tenant.id,
                    name=name,
                    mobile=mobile,
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

        # 张三/李四/王五 挂到生产部门（此时员工已创建）
        for wname, dname in (("张三", "针车一组"), ("李四", "成型部"), ("王五", "针车二组")):
            w = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == wname))
            dep = dept_by_name.get(dname)
            if w and dep:
                w.department_id = dep.id

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

        _seed_b1c_walkthrough_order(db, tenant.id, product, colors, sizes)

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
            for w in db.scalars(select(Employee).where(Employee.tenant_id == tenant.id)).all()
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

        # 班组：员工「针车组长」（=leader 账号，车间主管）带「针车一组」，成员含组长与张三
        zhang = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "张三"))
        leader_worker = db.scalar(select(Employee).where(Employee.tenant_id == tenant.id, Employee.name == "针车组长"))
        if not leader_worker:
            leader_worker = Employee(
                tenant_id=tenant.id,
                name="针车组长",
                mobile="13800138000",
                username="leader",
                password_hash=hash_password("leader123"),
                must_change_password=False,
                salary_model=SalaryModel.fixed,
            )
            db.add(leader_worker)
            db.flush()
            rbac_service.set_employee_roles(db, leader_worker, ["workshop"])
        leader_worker.mobile = "13800138000"
        leader_worker.password_hash = hash_password(settings.worker_default_password) if not leader_worker.username else leader_worker.password_hash
        leader_worker.must_change_password = False
        leader_worker.is_active = True
        if leader_worker and zhang:
            team = db.scalar(select(Team).where(Team.tenant_id == tenant.id, Team.name == "针车一组"))
            if not team:
                team = Team(
                    tenant_id=tenant.id,
                    name="针车一组",
                    leader_worker_id=leader_worker.id,
                    is_active=True,
                )
                db.add(team)
                db.flush()
            else:
                team.leader_worker_id = leader_worker.id
                team.is_active = True
            for wid in (leader_worker.id, zhang.id):
                mem = db.scalar(
                    select(TeamMember).where(TeamMember.tenant_id == tenant.id, TeamMember.worker_id == wid)
                )
                if not mem:
                    db.add(TeamMember(tenant_id=tenant.id, team_id=team.id, worker_id=wid))
                elif mem.team_id != team.id:
                    mem.team_id = team.id

        db.commit()

        # 工序段重构：补齐常用工序（按段归类，幂等），供工艺路线/排产使用
        from scripts.seed_default_processes import seed_default_processes

        seed_default_processes(db, tenant.id)

        print(
            f"Seed OK. admin / admin123; manager / manager123; leader / leader123（车间主管）; "
            f"员工手机号登录默认密码 {settings.worker_default_password}（首次须改密）; "
            f"order 230711/230712/B1C-WALK; 工位扫码 /scan/ZC-01（张三针车已派工，可默认/更换）; "
            f"班组「针车一组」组长员工「针车组长」，成员含张三；后台 leader 为车间主管并关联该员工"
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
