from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


# 通用 JSON：MySQL/SQLite/Postgres 均可；MySQL 存为 JSON 列
JsonType = JSON


class UserRole(str, PyEnum):
    admin = "admin"
    manager = "manager"
    leader = "leader"


class WorkerRole(str, PyEnum):
    worker = "worker"
    leader = "leader"


class SalaryModel(str, PyEnum):
    pure_piece = "pure_piece"
    base_plus_piece = "base_plus_piece"
    hourly = "hourly"
    fixed = "fixed"


class ProcessType(str, PyEnum):
    personal = "personal"
    group = "group"


class OrderStatus(str, PyEnum):
    draft = "draft"
    confirmed = "confirmed"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class OrderProcessStatus(str, PyEnum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


class ReportType(str, PyEnum):
    normal = "normal"
    rework = "rework"
    supplement = "supplement"
    tail = "tail"
    group = "group"


class WorkLogSource(str, PyEnum):
    voice = "voice"
    qrcode = "qrcode"
    manual = "manual"


class WorkLogStatus(str, PyEnum):
    valid = "valid"
    appealed = "appealed"
    corrected = "corrected"
    void = "void"


class TraceUnitType(str, PyEnum):
    bundle = "bundle"
    piece = "piece"


class TraceUnitStatus(str, PyEnum):
    open = "open"
    in_process = "in_process"
    done = "done"
    scrapped = "scrapped"
    split = "split"


class TraceUnitAction(str, PyEnum):
    create = "create"
    report = "report"
    inspect = "inspect"
    split = "split"
    transfer = "transfer"


class DefectDisposition(str, PyEnum):
    rework = "rework"
    scrap = "scrap"
    concession = "concession"


class DefectEventStatus(str, PyEnum):
    open = "open"
    closed = "closed"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(50))
    contact_mobile: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    corpid: Mapped[Optional[str]] = mapped_column(String(100))
    # 租户级配置：inventory（池+分配+领料开关）等
    settings_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 存角色编码（系统：admin/manager/leader，或租户自定义）
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    wechat_unionid: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Team(Base):
    """班组：组长绑员工账号 User；一人一组（见 TeamMember 唯一约束）。"""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_teams_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    leader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "worker_id", name="uq_team_members_worker"),
        UniqueConstraint("team_id", "worker_id", name="uq_team_members_team_worker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True, nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    team: Mapped["Team"] = relationship(back_populates="members")


class TenantRole(Base):
    """租户角色：内置三角色 + 可新增自定义角色。"""

    __tablename__ = "tenant_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_tenant_roles_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    # API 鉴权天花板：admin / manager / leader
    base_role: Mapped[str] = mapped_column(String(32), nullable=False, default="leader")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RolePermission(Base):
    """租户级角色授权：角色编码 × 权限码。base_role=admin 运行时视为全部。"""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", "perm_code", name="uq_role_permissions"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    perm_code: Mapped[str] = mapped_column(String(80), nullable=False)


class Partner(Base):
    """往来单位：客户 / 品牌方 / 供应商（可多选角色）。"""

    __tablename__ = "partners"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_partners_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_name: Mapped[Optional[str]] = mapped_column(String(50))
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_brand: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contacts: Mapped[list["PartnerContact"]] = relationship(
        back_populates="partner", cascade="all, delete-orphan", order_by="PartnerContact.sort_order"
    )


class PartnerContact(Base):
    """往来单位联系人（供应商等可多人）。"""

    __tablename__ = "partner_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(50))
    mobile: Mapped[Optional[str]] = mapped_column(String(20))
    wechat: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    partner: Mapped["Partner"] = relationship(back_populates="contacts")


class MaterialCategory(Base):
    """物料分类（皮料、五金扣等）。"""

    __tablename__ = "material_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_material_categories_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PricingUnit(Base):
    """计价单位（双、米、公斤等）。"""

    __tablename__ = "pricing_units"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_pricing_units_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Position(Base):
    """员工职位/工种（车工、裁剪、质检等）。"""

    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_positions_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupplierProduct(Base):
    """供应商产品（物料/商品档案）。"""

    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("tenant_id", "product_code", name="uq_supplier_products_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("material_categories.id"), index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(255))
    internal_code: Mapped[Optional[str]] = mapped_column(String(50))
    pricing_unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pricing_units.id"), index=True)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OwnProduct(Base):
    """自己产品开发：成品档案 + 物料成本。"""

    __tablename__ = "own_products"
    __table_args__ = (UniqueConstraint("tenant_id", "product_code", name="uq_own_products_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(255))
    material_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    quote_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    order_qty: Mapped[int] = mapped_column(Integer, default=0)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    other_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 开启后：合格报工可一键打捆标，便于质量追溯
    trace_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    colors: Mapped[list["OwnProductColor"]] = relationship(
        back_populates="own_product", cascade="all, delete-orphan"
    )
    materials: Mapped[list["OwnProductMaterial"]] = relationship(
        back_populates="own_product",
        cascade="all, delete-orphan",
        order_by="OwnProductMaterial.sort_order",
    )
    labors: Mapped[list["OwnProductLabor"]] = relationship(
        back_populates="own_product",
        cascade="all, delete-orphan",
        order_by="OwnProductLabor.sort_order",
    )
    other_costs: Mapped[list["OwnProductOtherCost"]] = relationship(
        back_populates="own_product",
        cascade="all, delete-orphan",
        order_by="OwnProductOtherCost.sort_order",
    )
    quotes: Mapped[list["OwnProductQuote"]] = relationship(
        back_populates="own_product",
        cascade="all, delete-orphan",
        order_by="OwnProductQuote.sort_order",
    )


class OwnProductColor(Base):
    """自己产品可选成品颜色。"""

    __tablename__ = "own_product_colors"
    __table_args__ = (
        UniqueConstraint("own_product_id", "color_id", name="uq_own_product_colors"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("colors.id"), index=True, nullable=False)

    own_product: Mapped["OwnProduct"] = relationship(back_populates="colors")


class OwnProductMaterial(Base):
    """自己产品物料明细（供应商产品 + 数量 + 单价快照）。"""

    __tablename__ = "own_product_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    own_product: Mapped["OwnProduct"] = relationship(back_populates="materials")


class OwnProductLabor(Base):
    """产品工序报价（兼人工成本）：建单路线 + 报工/计件单价。"""

    __tablename__ = "own_product_labors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    process_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("process_definitions.id"), index=True, nullable=True
    )
    process_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    own_product: Mapped["OwnProduct"] = relationship(back_populates="labors")


class OwnProductOtherCost(Base):
    """自己产品其它成本明细（自定义项目名 + 金额）。"""

    __tablename__ = "own_product_other_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    own_product: Mapped["OwnProduct"] = relationship(back_populates="other_costs")


class OwnProductQuote(Base):
    """自己产品按客户报价（同一产品可给多个客户不同价）。"""

    __tablename__ = "own_product_quotes"
    __table_args__ = (
        UniqueConstraint("own_product_id", "partner_id", name="uq_own_product_quotes_partner"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True, nullable=False)
    quote_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    own_product: Mapped["OwnProduct"] = relationship(back_populates="quotes")


class Color(Base):
    __tablename__ = "colors"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_colors_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)


class Size(Base):
    __tablename__ = "sizes"
    __table_args__ = (UniqueConstraint("tenant_id", "size_value", name="uq_sizes_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    size_value: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    mobile: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    wechat_openid: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    wechat_unionid: Mapped[Optional[str]] = mapped_column(String(100))
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[WorkerRole] = mapped_column(Enum(WorkerRole, native_enum=False), default=WorkerRole.worker)
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"), index=True)
    salary_model: Mapped[SalaryModel] = mapped_column(Enum(SalaryModel, native_enum=False), default=SalaryModel.pure_piece)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    base_quota: Mapped[int] = mapped_column(Integer, default=0)
    # 银行代发
    bank_account: Mapped[Optional[str]] = mapped_column(String(40))
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_name: Mapped[Optional[str]] = mapped_column(String(50))  # 收款户名，空则用姓名
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProcessDefinition(Base):
    __tablename__ = "process_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_process_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[ProcessType] = mapped_column(Enum(ProcessType, native_enum=False), default=ProcessType.personal)
    default_price: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PurchaseOrderStatus(str, PyEnum):
    draft = "draft"
    ordered = "ordered"
    shipped = "shipped"
    partial_received = "partial_received"
    received = "received"
    cancelled = "cancelled"


class ShipmentStatus(str, PyEnum):
    draft = "draft"
    shipped = "shipped"
    void = "void"


class ReceivableStatus(str, PyEnum):
    open = "open"
    partial = "partial"
    settled = "settled"
    void = "void"


class PaymentStatus(str, PyEnum):
    posted = "posted"
    void = "void"


class PaymentMethod(str, PyEnum):
    wechat = "wechat"
    alipay = "alipay"
    bank = "bank"
    cash = "cash"
    other = "other"


class SharedLedgerType(str, PyEnum):
    receive_surplus = "receive_surplus"
    unallocated_receive = "unallocated_receive"
    allocate_to_order = "allocate_to_order"  # 池 → 订单占用（齐套）
    issue_to_order = "issue_to_order"
    release_from_order = "release_from_order"  # 停单/改量释放回池
    adjust = "adjust"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("tenant_id", "order_no", name="uq_orders_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    # 遗留字段：旧库 NOT NULL；新库可空。写入时兼容回填
    style_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, native_enum=False), default=OrderStatus.confirmed)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notes: Mapped[Optional[str]] = mapped_column(Text)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    other_cost_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    # 急单/插单：人为加急，列表置顶；非自动排产
    is_rush: Mapped[bool] = mapped_column(Boolean, default=False)
    rush_reason: Mapped[Optional[str]] = mapped_column(String(255))
    rushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    processes: Mapped[list["OrderProcess"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    material_requirements: Mapped[list["OrderMaterialRequirement"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[int] = mapped_column(ForeignKey("sizes.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_qty: Mapped[int] = mapped_column(Integer, default=0)
    shipped_qty: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped["Order"] = relationship(back_populates="items")


class OrderProcess(Base):
    __tablename__ = "order_processes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id"), index=True, nullable=False)
    process_name: Mapped[str] = mapped_column(String(50), nullable=False)
    process_type: Mapped[ProcessType] = mapped_column(Enum(ProcessType, native_enum=False), default=ProcessType.personal)
    plan_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_qty: Mapped[int] = mapped_column(Integer, default=0)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[OrderProcessStatus] = mapped_column(
        Enum(OrderProcessStatus, native_enum=False), default=OrderProcessStatus.pending
    )
    assigned_worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), index=True)
    assigned_group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="processes")
    assignments: Mapped[list["OrderProcessAssignment"]] = relationship(
        back_populates="order_process", cascade="all, delete-orphan"
    )


class OrderProcessAssignment(Base):
    """一工序可派多人；quota_qty 为个人可报上限（None=不限，0=不可报，请假可改）。

    三种互斥粒度（同一工序不可混用）：
    - 整工序：color/size/trace_unit 均为空
    - 色码：color+size 非空，无捆
    - 捆：trace_unit_id 非空，无色码
    share_weight：集体报工拆账权重（空/≤0 视为 1；均分=人人相同权重）。
    """

    __tablename__ = "order_process_assignments"
    __table_args__ = (
        UniqueConstraint(
            "order_process_id",
            "worker_id",
            "color_id",
            "size_id",
            "trace_unit_id",
            name="uq_opa_process_worker_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    order_process_id: Mapped[int] = mapped_column(ForeignKey("order_processes.id"), index=True, nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"), index=True)
    size_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sizes.id"), index=True)
    trace_unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trace_units.id"), index=True)
    quota_qty: Mapped[Optional[int]] = mapped_column(Integer)  # None=不限
    share_weight: Mapped[Optional[int]] = mapped_column(Integer)  # 集体拆账权重，空=1
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order_process: Mapped["OrderProcess"] = relationship(back_populates="assignments")


class WorkLog(Base):
    __tablename__ = "work_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    order_process_id: Mapped[int] = mapped_column(ForeignKey("order_processes.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    # 遗留字段：旧库 style_id NOT NULL；兼容写入
    style_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sizes.id"))
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType, native_enum=False), default=ReportType.normal)
    qualified_qty: Mapped[int] = mapped_column(Integer, default=0)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0)
    # 报工锁价：落库后工资只认此单价；旧数据为空时结算回落现价
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    group_detail: Mapped[Optional[Any]] = mapped_column(JsonType)
    original_text: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[WorkLogSource] = mapped_column(Enum(WorkLogSource, native_enum=False), default=WorkLogSource.manual)
    station_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    trace_unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trace_units.id"), index=True)
    status: Mapped[WorkLogStatus] = mapped_column(Enum(WorkLogStatus, native_enum=False), default=WorkLogStatus.valid)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    review_note: Mapped[Optional[str]] = mapped_column(String(255))


class SalaryMonthLock(Base):
    """月结锁账：锁定后该月报工作废/更正/申诉审结受限。"""

    __tablename__ = "salary_month_locks"
    __table_args__ = (UniqueConstraint("tenant_id", "year_month", name="uq_salary_month_locks"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    locked_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SalaryAcknowledgement(Base):
    """工资电子确认（轻量电子签）：员工对锁定月结签字确认。"""

    __tablename__ = "salary_acknowledgements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "worker_id", "year_month", name="uq_salary_ack_worker_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True, nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)
    total_wage: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    confirm_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 手输姓名视同签字
    signature_data: Mapped[Optional[str]] = mapped_column(Text)  # 可选手写轨迹 base64
    source: Mapped[str] = mapped_column(String(20), default="h5")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    note: Mapped[Optional[str]] = mapped_column(String(255))


class TraceUnit(Base):
    """追溯单元：一期捆标 bundle；二期可拆 piece（单双）。"""

    __tablename__ = "trace_units"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_trace_units_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    unit_type: Mapped[TraceUnitType] = mapped_column(
        Enum(TraceUnitType, native_enum=False), default=TraceUnitType.bundle
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trace_units.id"), index=True)
    serial_no: Mapped[Optional[str]] = mapped_column(String(40))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    own_product_id: Mapped[int] = mapped_column(ForeignKey("own_products.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sizes.id"))
    current_process_id: Mapped[Optional[int]] = mapped_column(ForeignKey("process_definitions.id"), index=True)
    status: Mapped[TraceUnitStatus] = mapped_column(
        Enum(TraceUnitStatus, native_enum=False), default=TraceUnitStatus.open
    )
    created_from_work_log_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_by_worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    logs: Mapped[list["TraceUnitLog"]] = relationship(
        back_populates="trace_unit", cascade="all, delete-orphan", order_by="TraceUnitLog.id"
    )


class TraceUnitLog(Base):
    """捆/件过站流水。"""

    __tablename__ = "trace_unit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    trace_unit_id: Mapped[int] = mapped_column(ForeignKey("trace_units.id"), index=True, nullable=False)
    action: Mapped[TraceUnitAction] = mapped_column(Enum(TraceUnitAction, native_enum=False), nullable=False)
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), index=True)
    station_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stations.id"), index=True)
    process_id: Mapped[Optional[int]] = mapped_column(ForeignKey("process_definitions.id"), index=True)
    work_log_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    qty: Mapped[Optional[int]] = mapped_column(Integer)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    trace_unit: Mapped["TraceUnit"] = relationship(back_populates="logs")


class DefectEvent(Base):
    """不良事件：追责用；与 WorkLog.defect_qty 汇总并存。"""

    __tablename__ = "defect_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    trace_unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trace_units.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sizes.id"))
    found_process_id: Mapped[Optional[int]] = mapped_column(ForeignKey("process_definitions.id"), index=True)
    responsible_process_id: Mapped[Optional[int]] = mapped_column(ForeignKey("process_definitions.id"), index=True)
    responsible_worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), index=True)
    defect_type: Mapped[str] = mapped_column(String(40), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    disposition: Mapped[DefectDisposition] = mapped_column(
        Enum(DefectDisposition, native_enum=False), default=DefectDisposition.rework
    )
    found_by_worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), index=True)
    found_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    source_work_log_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[DefectEventStatus] = mapped_column(
        Enum(DefectEventStatus, native_enum=False), default=DefectEventStatus.open
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PendingSlot(Base):
    """Short-lived multi-turn slot filling / confirm state."""

    __tablename__ = "pending_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    actor_key: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # worker:{id} or openid:...
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    slots: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Station(Base):
    """车间工位：贴二维码，扫码报工绑定工序。"""

    __tablename__ = "stations"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_station_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id"), index=True, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OrderMaterialRequirement(Base):
    """订单用料快照（按单齐套主账）。"""

    __tablename__ = "order_material_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    qty_per_pair: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("1"))
    loss_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    required_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    arrived_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    issued_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    is_customer_supplied: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    order: Mapped["Order"] = relationship(back_populates="material_requirements")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_no", name="uq_purchase_orders_no"),
        UniqueConstraint("public_token", name="uq_purchase_orders_public_token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    po_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 公开扫码预览用不可猜令牌（免登录只读）
    public_token: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True, nullable=False)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        Enum(PurchaseOrderStatus, native_enum=False), default=PurchaseOrderStatus.draft
    )
    expected_date: Mapped[Optional[date]] = mapped_column(Date)
    ordered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    logistics_company: Mapped[Optional[str]] = mapped_column(String(100))
    tracking_no: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    order_material_requirement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("order_material_requirements.id"), index=True
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class SharedMaterialStock(Base):
    """轻量公用库存（按供应商产品，不绑订单）。"""

    __tablename__ = "shared_material_stocks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_product_id", name="uq_shared_material_stock"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    avg_unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SharedMaterialLedger(Base):
    __tablename__ = "shared_material_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    ledger_type: Mapped[SharedLedgerType] = mapped_column(
        Enum(SharedLedgerType, native_enum=False), nullable=False
    )
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    ref_type: Mapped[Optional[str]] = mapped_column(String(40))
    ref_id: Mapped[Optional[int]] = mapped_column(Integer)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class MaterialRelease(Base):
    """发车间确认流水（轻量登记；强制领料租户改走 stock_docs）。"""

    __tablename__ = "material_releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    order_material_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("order_material_requirements.id"), index=True, nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    deduct_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class StockDocType(str, PyEnum):
    issue = "issue"  # 领料：占用 → 已发
    return_mat = "return_mat"  # 退料：已发 → 回池（并减少占用）


class StockDocStatus(str, PyEnum):
    pending = "pending"  # 车间已提报，待仓管确认
    posted = "posted"
    void = "void"


class StockDoc(Base):
    """领退料单（强制领料模式）。"""

    __tablename__ = "stock_docs"
    __table_args__ = (UniqueConstraint("tenant_id", "doc_no", name="uq_stock_docs_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    doc_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_type: Mapped[StockDocType] = mapped_column(Enum(StockDocType, native_enum=False), nullable=False)
    status: Mapped[StockDocStatus] = mapped_column(
        Enum(StockDocStatus, native_enum=False), default=StockDocStatus.posted
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    lines: Mapped[list["StockDocLine"]] = relationship(
        back_populates="stock_doc", cascade="all, delete-orphan"
    )


class StockDocLine(Base):
    __tablename__ = "stock_doc_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    stock_doc_id: Mapped[int] = mapped_column(ForeignKey("stock_docs.id"), index=True, nullable=False)
    order_material_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("order_material_requirements.id"), index=True, nullable=False
    )
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True, nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))

    stock_doc: Mapped["StockDoc"] = relationship(back_populates="lines")


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("tenant_id", "shipment_no", name="uq_shipments_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    shipment_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, native_enum=False), default=ShipmentStatus.draft
    )
    ship_date: Mapped[Optional[date]] = mapped_column(Date)
    logistics_company: Mapped[Optional[str]] = mapped_column(String(100))
    tracking_no: Mapped[Optional[str]] = mapped_column(String(100))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    total_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lines: Mapped[list["ShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )


class ShipmentLine(Base):
    __tablename__ = "shipment_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True, nullable=False)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[int] = mapped_column(ForeignKey("sizes.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)

    shipment: Mapped["Shipment"] = relationship(back_populates="lines")


class Receivable(Base):
    __tablename__ = "receivables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    shipment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shipments.id"), index=True)
    receivable_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    adjustment: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    received_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    status: Mapped[ReceivableStatus] = mapped_column(
        Enum(ReceivableStatus, native_enum=False), default=ReceivableStatus.open
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False), default=PaymentMethod.other
    )
    voucher_no: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False), default=PaymentStatus.posted
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True, nullable=False)
    receivable_id: Mapped[int] = mapped_column(ForeignKey("receivables.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    payment: Mapped["Payment"] = relationship(back_populates="allocations")
