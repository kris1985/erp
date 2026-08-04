from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    display_name: str
    role: str
    tenant_id: int


class WorkerCreate(BaseModel):
    name: str
    mobile: Optional[str] = None
    role: str = "worker"


class WorkerOut(BaseModel):
    id: int
    name: str
    mobile: Optional[str] = None
    role: str
    wechat_openid: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class ProcessCreate(BaseModel):
    name: str
    code: str
    default_price: Decimal = Decimal("0")
    sort_order: int = 0
    type: str = "personal"


class ProcessOut(BaseModel):
    id: int
    name: str
    code: str
    default_price: Decimal
    sort_order: int
    type: str
    is_active: bool

    model_config = {"from_attributes": True}


class StyleCreate(BaseModel):
    style_code: str
    style_name: str
    default_color: Optional[str] = None


class StyleOut(BaseModel):
    id: int
    style_code: str
    style_name: str
    default_color: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class RouteCreate(BaseModel):
    style_id: int
    process_id: int
    seq: int
    price: Decimal
    price_type: str = "normal"


class RouteOut(BaseModel):
    id: int
    style_id: int
    process_id: int
    seq: int
    price: Decimal
    price_type: str
    is_active: bool

    model_config = {"from_attributes": True}


class ColorOut(BaseModel):
    id: int
    name: str
    code: str

    model_config = {"from_attributes": True}


class SizeOut(BaseModel):
    id: int
    size_value: str
    sort_order: int

    model_config = {"from_attributes": True}


class OrderItemIn(BaseModel):
    color_id: Optional[int] = None
    size_id: int
    qty: int = Field(gt=0)


class OrderCreate(BaseModel):
    order_no: Optional[str] = None
    customer_name: str
    style_id: int
    delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: list[OrderItemIn]


class OrderItemOut(BaseModel):
    id: int
    color_id: Optional[int] = None
    size_id: int
    qty: int
    completed_qty: int

    model_config = {"from_attributes": True}


class OrderProcessOut(BaseModel):
    id: int
    process_id: int
    process_name: str
    plan_qty: int
    completed_qty: int
    defect_qty: int
    status: str

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    order_no: str
    customer_name: str
    style_id: int
    total_qty: int
    delivery_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    items: list[OrderItemOut] = []
    processes: list[OrderProcessOut] = []

    model_config = {"from_attributes": True}


class ReportRequest(BaseModel):
    worker_id: int
    order_no: str
    process_name: str
    color_name: Optional[str] = None
    size_value: Optional[str] = None
    qualified_qty: int = Field(ge=0)
    defect_qty: int = Field(ge=0, default=0)
    original_text: Optional[str] = None
    source: str = "manual"
    confirm_over_plan: bool = False


class ChatRequest(BaseModel):
    text: str
    worker_id: Optional[int] = None
    openid: Optional[str] = None
    confirm: bool = False


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    need_confirm: bool = False
    data: Optional[dict] = None
