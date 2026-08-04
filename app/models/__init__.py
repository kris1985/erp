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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


JsonType = JSON().with_variant(JSONB(), "postgresql")


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


class PriceType(str, PyEnum):
    normal = "normal"
    rework = "rework"
    supplement = "supplement"
    tail = "tail"


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


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(50))
    contact_mobile: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    corpid: Mapped[Optional[str]] = mapped_column(String(100))
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
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False), default=UserRole.admin)
    wechat_unionid: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Style(Base):
    __tablename__ = "styles"
    __table_args__ = (UniqueConstraint("tenant_id", "style_code", name="uq_styles_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    style_code: Mapped[str] = mapped_column(String(50), nullable=False)
    style_name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_color: Mapped[Optional[str]] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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
    role: Mapped[WorkerRole] = mapped_column(Enum(WorkerRole, native_enum=False), default=WorkerRole.worker)
    salary_model: Mapped[SalaryModel] = mapped_column(Enum(SalaryModel, native_enum=False), default=SalaryModel.pure_piece)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    base_quota: Mapped[int] = mapped_column(Integer, default=0)
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


class StyleProcessRoute(Base):
    __tablename__ = "style_process_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id"), index=True, nullable=False)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id"), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    price_type: Mapped[PriceType] = mapped_column(Enum(PriceType, native_enum=False), default=PriceType.normal)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("tenant_id", "order_no", name="uq_orders_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id"), index=True, nullable=False)
    total_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, native_enum=False), default=OrderStatus.confirmed)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    processes: Mapped[list["OrderProcess"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[int] = mapped_column(ForeignKey("sizes.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_qty: Mapped[int] = mapped_column(Integer, default=0)

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
    assigned_group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="processes")


class WorkLog(Base):
    __tablename__ = "work_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    order_process_id: Mapped[int] = mapped_column(ForeignKey("order_processes.id"), index=True, nullable=False)
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id"), index=True, nullable=False)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id"), index=True, nullable=False)
    color_id: Mapped[Optional[int]] = mapped_column(ForeignKey("colors.id"))
    size_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sizes.id"))
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType, native_enum=False), default=ReportType.normal)
    qualified_qty: Mapped[int] = mapped_column(Integer, default=0)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    group_detail: Mapped[Optional[Any]] = mapped_column(JsonType)
    original_text: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[WorkLogSource] = mapped_column(Enum(WorkLogSource, native_enum=False), default=WorkLogSource.manual)
    station_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[WorkLogStatus] = mapped_column(Enum(WorkLogStatus, native_enum=False), default=WorkLogStatus.valid)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    review_note: Mapped[Optional[str]] = mapped_column(String(255))


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
