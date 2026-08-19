from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    """登录标识：用户名或手机号（跨租户匹配）。"""

    identifier: str
    password: str


class TenantSelectRequest(BaseModel):
    """多租户命中时，选择具体工厂完成登录。"""

    identifier: str
    password: str
    tenant_id: int


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    display_name: str
    role: str
    tenant_id: int


class EmployeeCreate(BaseModel):
    name: str
    mobile: Optional[str] = None
    # 登录账号（可空：纯工人无账号）
    username: Optional[str] = None
    password: Optional[str] = None
    # 后台角色（可空：无后台权限）
    roles: Optional[list[str]] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    salary_model: str = "pure_piece"
    base_salary: Decimal = Decimal("0")
    base_quota: int = 0
    skill_factor: Decimal = Decimal("1.00")
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_name: Optional[str] = None

    @model_validator(mode="after")
    def _check_username_password(self):
        """用户名可空（纯手机号登录）；密码可不填（后端用默认密码）。"""
        username = (self.username or "").strip()
        if not username and self.password:
            raise ValueError("设置密码必须填写用户名")
        return self


class EmployeeOut(BaseModel):
    id: int
    name: str
    mobile: Optional[str] = None
    username: Optional[str] = None
    has_account: bool = False
    roles: list[str] = []
    role_names: list[str] = []
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    position_id: Optional[int] = None
    position_name: Optional[str] = None
    salary_model: str = "pure_piece"
    base_salary: Decimal = Decimal("0")
    base_quota: int = 0
    skill_factor: Decimal = Decimal("1.00")
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_name: Optional[str] = None
    wechat_openid: Optional[str] = None
    ext_source: Optional[str] = None
    ext_user_id: Optional[str] = None
    is_active: bool
    must_change_password: bool = False

    model_config = {"from_attributes": True}


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    roles: Optional[list[str]] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    salary_model: Optional[str] = None
    base_salary: Optional[Decimal] = None
    base_quota: Optional[int] = None
    skill_factor: Optional[Decimal] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_name: Optional[str] = None
    is_active: Optional[bool] = None
    # 重置为系统默认密码，并要求下次登录改密
    reset_password: Optional[bool] = None


class DepartmentCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    manager_employee_id: Optional[int] = None
    sort_order: int = 0


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    manager_employee_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    manager_employee_id: Optional[int] = None
    manager_name: Optional[str] = None
    manager_mobile: Optional[str] = None
    sort_order: int = 0
    is_active: bool
    employee_count: int = 0

    model_config = {"from_attributes": True}


class SalaryConfirmRequest(BaseModel):
    year_month: str
    confirm_name: str = Field(min_length=1, max_length=50)
    signature_data: Optional[str] = None  # 可选手写签 base64
    note: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class ProcessCreate(BaseModel):
    name: str
    code: str
    default_price: Decimal = Decimal("0")
    per_worker_capacity: Optional[Decimal] = None
    standard_workers: Optional[int] = 1
    current_workers: Optional[int] = None
    sort_order: int = 0
    type: str = "personal"


class ProcessUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    default_price: Optional[Decimal] = None
    per_worker_capacity: Optional[Decimal] = None
    standard_workers: Optional[int] = None
    current_workers: Optional[int] = None
    sort_order: Optional[int] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None


class ProcessOut(BaseModel):
    id: int
    name: str
    code: str
    default_price: Decimal
    per_worker_capacity: Optional[Decimal] = None
    standard_workers: Optional[int] = None
    current_workers: Optional[int] = None
    sort_order: int
    type: str
    is_active: bool

    model_config = {"from_attributes": True}


class PartnerContactCreate(BaseModel):
    name: str
    title: Optional[str] = None
    mobile: Optional[str] = None
    wechat: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False
    sort_order: int = 0
    is_active: bool = True


class PartnerContactUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    mobile: Optional[str] = None
    wechat: Optional[str] = None
    email: Optional[str] = None
    is_primary: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PartnerContactOut(BaseModel):
    id: int
    partner_id: int
    name: str
    title: Optional[str] = None
    mobile: Optional[str] = None
    wechat: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False
    sort_order: int = 0
    is_active: bool = True

    model_config = {"from_attributes": True}


class PartnerCreate(BaseModel):
    name: str
    short_name: Optional[str] = None
    is_customer: bool = False
    is_supplier: bool = False
    is_brand: bool = False
    payment_term_days: int = 0
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True
    contacts: list[PartnerContactCreate] = []


class PartnerUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    is_customer: Optional[bool] = None
    is_supplier: Optional[bool] = None
    is_brand: Optional[bool] = None
    payment_term_days: Optional[int] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PartnerOut(BaseModel):
    id: int
    name: str
    short_name: Optional[str] = None
    is_customer: bool = False
    is_supplier: bool = False
    is_brand: bool = False
    payment_term_days: int = 0
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True
    contacts_count: int = 0
    primary_contact: Optional[PartnerContactOut] = None
    contacts: list[PartnerContactOut] = []

    model_config = {"from_attributes": True}


class SupplierProductCreate(BaseModel):
    product_code: str
    name: Optional[str] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    internal_code: Optional[str] = None
    pricing_unit_id: Optional[int] = None
    unit_price: Optional[Decimal] = None
    color_id: Optional[int] = None
    partner_id: int
    is_active: bool = True
    min_stock_qty: Optional[Decimal] = None


class SupplierProductUpdate(BaseModel):
    product_code: Optional[str] = None
    name: Optional[str] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    internal_code: Optional[str] = None
    pricing_unit_id: Optional[int] = None
    unit_price: Optional[Decimal] = None
    color_id: Optional[int] = None
    partner_id: Optional[int] = None
    is_active: Optional[bool] = None
    min_stock_qty: Optional[Decimal] = None


class SupplierProductOut(BaseModel):
    id: int
    product_code: str
    name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    image_url: Optional[str] = None
    internal_code: Optional[str] = None
    pricing_unit_id: Optional[int] = None
    pricing_unit_name: Optional[str] = None
    unit_price: Optional[Decimal] = None
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    partner_id: int
    partner_name: Optional[str] = None
    is_active: bool = True
    min_stock_qty: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MaterialCategoryCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_active: bool = True
    default_consume_process_id: Optional[int] = None
    suggest_usage_by_size: bool = False
    default_size_usage_table_id: Optional[int] = None


class MaterialCategoryUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    default_consume_process_id: Optional[int] = None
    suggest_usage_by_size: Optional[bool] = None
    default_size_usage_table_id: Optional[int] = None


class MaterialCategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    is_active: bool = True
    default_consume_process_id: Optional[int] = None
    default_consume_process_name: Optional[str] = None
    suggest_usage_by_size: bool = False
    default_size_usage_table_id: Optional[int] = None
    default_size_usage_table_name: Optional[str] = None

    model_config = {"from_attributes": True}


class PricingUnitCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_active: bool = True


class PricingUnitUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PricingUnitOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    is_active: bool = True

    model_config = {"from_attributes": True}


class PositionCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_active: bool = True


class PositionUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PositionOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    is_active: bool = True

    model_config = {"from_attributes": True}


class OtherCostItemCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_active: bool = True


class OtherCostItemUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class OtherCostItemOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    is_active: bool = True

    model_config = {"from_attributes": True}


class ColorCreate(BaseModel):
    name: str
    code: Optional[str] = None


class ColorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None


class ColorOut(BaseModel):
    id: int
    name: str
    code: str

    model_config = {"from_attributes": True}


class OwnProductMaterialIn(BaseModel):
    supplier_product_id: int
    qty: Decimal = Decimal("1")
    sort_order: int = 0
    consume_process_id: Optional[int] = None
    usage_by_size: bool = False
    size_usage_table_id: Optional[int] = None
    loss_rate: Decimal = Decimal("0")
    loss_fixed_qty: Decimal = Decimal("0")
    # 配色 BOM：空=整款共用；有值=仅该成品色
    color_id: Optional[int] = None


class OwnProductMaterialOut(BaseModel):
    id: int
    supplier_product_id: int
    supplier_product_code: Optional[str] = None
    supplier_product_name: Optional[str] = None
    image_url: Optional[str] = None
    internal_code: Optional[str] = None
    color_name: Optional[str] = None
    partner_name: Optional[str] = None
    pricing_unit_name: Optional[str] = None
    qty: Decimal
    unit_price: Decimal
    line_total: Decimal
    sort_order: int = 0
    consume_process_id: Optional[int] = None
    consume_process_name: Optional[str] = None
    # bom 覆盖 / category 默认 / unlabeled（算首道）
    consume_source: Optional[str] = None
    usage_by_size: bool = False
    size_usage_table_id: Optional[int] = None
    size_usage_table_name: Optional[str] = None
    loss_rate: Decimal = Decimal("0")
    loss_fixed_qty: Decimal = Decimal("0")
    bom_color_id: Optional[int] = None
    bom_color_name: Optional[str] = None

    model_config = {"from_attributes": True}


class PartDefinitionCreate(BaseModel):
    code: str
    name: str
    source: str = "裁断"  # 裁断 | 外购 | 其他
    is_active: bool = True


class PartDefinitionUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    source: Optional[str] = None
    is_active: Optional[bool] = None


class PartDefinitionOut(BaseModel):
    id: int
    code: str
    name: str
    source: str = "裁断"
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OwnProductPartIn(BaseModel):
    part_id: int
    pieces_per_pair: int = 1
    sort_order: int = 0
    source_supplier_product_id: Optional[int] = None


class OwnProductPartOut(BaseModel):
    id: int
    part_id: int
    part_code: Optional[str] = None
    part_name: Optional[str] = None
    part_source: Optional[str] = None
    pieces_per_pair: int = 1
    sort_order: int = 0
    source_supplier_product_id: Optional[int] = None

    model_config = {"from_attributes": True}


class OwnProductLaborIn(BaseModel):
    process_name: str
    unit_price: Decimal = Decimal("0")
    sort_order: int = 0
    # personal | group；新建工序时写入主数据，已存在工序可用来同步类型
    process_type: str = "personal"
    # 非空=部件路线；空=整鞋段
    part_id: Optional[int] = None
    is_kit_checkpoint: bool = False


class OwnProductLaborOut(BaseModel):
    id: int
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    process_type: str = "personal"
    unit_price: Decimal
    sort_order: int = 0
    part_id: Optional[int] = None
    is_kit_checkpoint: bool = False

    model_config = {"from_attributes": True}


class OwnProductOtherCostIn(BaseModel):
    name: str
    amount: Decimal = Decimal("0")
    sort_order: int = 0


class OwnProductOtherCostOut(BaseModel):
    id: int
    name: str
    amount: Decimal
    sort_order: int = 0

    model_config = {"from_attributes": True}


class OwnProductQuoteIn(BaseModel):
    partner_id: int
    quote_price: Decimal = Decimal("0")
    sort_order: int = 0


class OwnProductQuoteOut(BaseModel):
    id: int
    partner_id: int
    partner_name: Optional[str] = None
    partner_short_name: Optional[str] = None
    quote_price: Decimal
    sort_order: int = 0

    model_config = {"from_attributes": True}


class OwnProductCreate(BaseModel):
    product_code: str
    image_url: Optional[str] = None
    fabric: Optional[str] = None
    lining: Optional[str] = None
    color_ids: list[int]
    parts: list[OwnProductPartIn] = []
    materials: list[OwnProductMaterialIn] = []
    labors: list[OwnProductLaborIn] = []
    quotes: list[OwnProductQuoteIn] = []
    other_costs: list[OwnProductOtherCostIn] = []
    quote_price: Optional[Decimal] = None
    order_qty: int = 0
    is_active: bool = True
    trace_enabled: bool = False


class OwnProductUpdate(BaseModel):
    product_code: Optional[str] = None
    image_url: Optional[str] = None
    fabric: Optional[str] = None
    lining: Optional[str] = None
    color_ids: Optional[list[int]] = None
    parts: Optional[list[OwnProductPartIn]] = None
    materials: Optional[list[OwnProductMaterialIn]] = None
    labors: Optional[list[OwnProductLaborIn]] = None
    quotes: Optional[list[OwnProductQuoteIn]] = None
    other_costs: Optional[list[OwnProductOtherCostIn]] = None
    quote_price: Optional[Decimal] = None
    order_qty: Optional[int] = None
    is_active: Optional[bool] = None
    trace_enabled: Optional[bool] = None
    # 显式开关：把产品工序结构同步到在制执行单（及遗留生产单）
    sync_labors_to_open_orders: Optional[bool] = False


class OwnProductOut(BaseModel):
    id: int
    product_code: str
    image_url: Optional[str] = None
    fabric: Optional[str] = None
    lining: Optional[str] = None
    color_ids: list[int] = []
    colors: list[ColorOut] = []
    parts: list[OwnProductPartOut] = []
    materials: list[OwnProductMaterialOut] = []
    labors: list[OwnProductLaborOut] = []
    quotes: list[OwnProductQuoteOut] = []
    other_costs: list[OwnProductOtherCostOut] = []
    material_cost: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    other_cost: Decimal = Decimal("0")
    quote_price: Optional[Decimal] = None
    order_qty: int = 0
    is_active: bool = True
    trace_enabled: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OwnProductBatchQuoteExportIn(BaseModel):
    product_ids: list[int] = Field(min_length=1)
    partner_id: Optional[int] = None


class SizeCreate(BaseModel):
    size_value: str
    sort_order: int = 0
    is_active: bool = True


class SizeUpdate(BaseModel):
    size_value: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SizeOut(BaseModel):
    id: int
    size_value: str
    sort_order: int
    is_active: bool = True

    model_config = {"from_attributes": True}


class OrderItemIn(BaseModel):
    color_id: Optional[int] = None
    size_id: int
    qty: int = Field(gt=0)


class OrderCreate(BaseModel):
    order_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    own_product_id: int
    delivery_date: Optional[date] = None
    notes: Optional[str] = None
    unit_price: Optional[Decimal] = None
    other_cost_amount: Optional[Decimal] = None
    is_rush: bool = False
    rush_reason: Optional[str] = None
    items: list[OrderItemIn]


class OrderStatusUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    delivery_date: Optional[date] = None
    items: Optional[list[OrderItemIn]] = None
    unit_price: Optional[Decimal] = None
    other_cost_amount: Optional[Decimal] = None
    is_rush: Optional[bool] = None
    rush_reason: Optional[str] = None


class OrderItemOut(BaseModel):
    id: int
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    size_id: int
    size_value: Optional[str] = None
    qty: int
    completed_qty: int
    shipped_qty: int = 0

    model_config = {"from_attributes": True}


class SizeAdjustItemIn(BaseModel):
    """B2e 补码/改码单行：replace 模式 qty=目标计划数；delta 模式 qty=变化量（可负，补码为正/减码为负）。"""

    color_id: Optional[int] = None
    size_id: int
    qty: int


class SizeAdjustRequest(BaseModel):
    items: list[SizeAdjustItemIn]
    mode: str = "delta"  # replace|delta
    note: Optional[str] = None
    # 预览：只算差异与影响，不落库、不触发材料重算
    dry_run: bool = False


class SizeAdjustItemOut(BaseModel):
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    size_id: int
    size_value: Optional[str] = None
    before_qty: int
    after_qty: int
    delta_qty: int
    completed_qty: int = 0
    shipped_qty: int = 0
    is_new: bool = False
    below_completed: bool = False
    over_shipped: bool = False
    # 该行已有发货且本次改动数量，需要跟单知会/核对发货单
    delivery_impact: bool = False


class SizeAdjustResult(BaseModel):
    dry_run: bool
    order_id: int
    order_no: str
    mode: str
    total_qty_before: int
    total_qty_after: int
    items: list[SizeAdjustItemOut]
    has_blocking: bool = False
    has_delivery_impact: bool = False
    released: list[dict] = []
    requirement_count: int = 0
    change_log_id: Optional[int] = None
    change_logged: bool = False
    summary: Optional[str] = None
    order: Optional[dict] = None


class AssignmentQuotaOut(BaseModel):
    worker_id: int
    worker_name: str
    quota_qty: Optional[int] = None
    reported_qty: int = 0
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    size_id: Optional[int] = None
    size_value: Optional[str] = None
    trace_unit_id: Optional[int] = None
    trace_code: Optional[str] = None
    bundle_qty: Optional[int] = None
    share_weight: Optional[int] = None


class OrderProcessOut(BaseModel):
    id: int
    process_id: int
    process_name: str
    plan_qty: int
    completed_qty: int
    defect_qty: int
    rework_qty: int = 0
    process_type: str = "personal"
    assigned_worker_ids: list[int] = []
    assigned_worker_names: list[str] = []
    assignments: list[AssignmentQuotaOut] = []
    # process = 整工序；sku = 按色码；bundle = 按捆（同一工序不可混用）
    dispatch_mode: str = "process"
    # 未分配池：plan - 已派配额合计；有人「不限」时为 null（仅 process 模式）
    allocated_quota: Optional[int] = None
    unallocated_qty: Optional[int] = None
    has_unlimited_quota: bool = False
    # 兼容旧字段：多人时取第一人
    assigned_worker_id: Optional[int] = None
    assigned_worker_name: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class AssignmentQuotaIn(BaseModel):
    worker_id: int
    quota_qty: Optional[int] = None
    color_id: Optional[int] = None
    size_id: Optional[int] = None
    trace_unit_id: Optional[int] = None
    share_weight: Optional[int] = None


class OrderProcessAssign(BaseModel):
    """整表替换该工序派工；空表示清空（不限制报工）。

    优先用 assignments（含配额）；仅传 worker_ids 时配额为不限（整工序）。
    同一工序 assignments 须同为整工序 / 色码 / 捆之一，不可混用。
    """

    worker_ids: list[int] = []
    assignments: Optional[list[AssignmentQuotaIn]] = None


class OrderOut(BaseModel):
    id: int
    order_no: str
    customer_id: Optional[int] = None
    customer_name: str
    own_product_id: int
    product_code: Optional[str] = None
    product_image_url: Optional[str] = None
    trace_enabled: bool = False
    sales_order_id: Optional[int] = None
    sales_order_no: Optional[str] = None
    sales_order_line_id: Optional[int] = None
    total_qty: int
    delivery_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    unit_price: Optional[Decimal] = None
    other_cost_amount: Optional[Decimal] = None
    is_rush: bool = False
    rush_reason: Optional[str] = None
    rushed_at: Optional[datetime] = None
    # K4：执行单内部桥接壳（勿当生产主体）
    is_bridge: bool = False
    kit_ok: Optional[bool] = None
    # ISO 日期字符串或空；列表/详情统一字段名
    kit_ready_date: Optional[str] = None
    kit_ready_label: Optional[str] = None
    # A1b 风险条
    risk_level: Optional[str] = None  # red|yellow|green|none
    risk_label: Optional[str] = None
    risk_reasons: list[dict] = []
    at_risk: Optional[bool] = None
    created_at: datetime
    items: list[OrderItemOut] = []
    processes: list[OrderProcessOut] = []

    model_config = {"from_attributes": True}


class SalesOrderLineItemIn(BaseModel):
    size_id: int
    qty: int = Field(gt=0)


def _empty_str_to_none(v: object) -> object:
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


class SalesOrderLineIn(BaseModel):
    own_product_id: int
    color_id: int
    fabric: Optional[str] = None
    lining: Optional[str] = None
    customer_sku: Optional[str] = None
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    delivery_date: Optional[date] = None
    unit_price: Optional[Decimal] = None
    notes: Optional[str] = None
    items: list[SalesOrderLineItemIn]
    # 仅新增时有效：插到该明细上方；空则追加到末尾
    insert_before_line_id: Optional[int] = None

    @field_validator("delivery_date", mode="before")
    @classmethod
    def _delivery_date_empty(cls, v: object) -> object:
        return _empty_str_to_none(v)


class SalesOrderCreate(BaseModel):
    order_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    ordered_at: Optional[date] = None
    notes: Optional[str] = None
    brand_logo_url: Optional[str] = None
    notes_image_url: Optional[str] = None
    lines: list[SalesOrderLineIn] = []

    @field_validator("ordered_at", mode="before")
    @classmethod
    def _ordered_at_empty(cls, v: object) -> object:
        return _empty_str_to_none(v)

    @field_validator(
        "order_no", "customer_name", "notes", "brand_logo_url", "notes_image_url", mode="before"
    )
    @classmethod
    def _blank_str_to_none(cls, v: object) -> object:
        return _empty_str_to_none(v)


class SalesOrderUpdate(BaseModel):
    order_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    ordered_at: Optional[date] = None
    notes: Optional[str] = None
    brand_logo_url: Optional[str] = None
    notes_image_url: Optional[str] = None
    lines: Optional[list[SalesOrderLineIn]] = None

    @field_validator("ordered_at", mode="before")
    @classmethod
    def _ordered_at_empty(cls, v: object) -> object:
        return _empty_str_to_none(v)

    @field_validator(
        "order_no", "customer_name", "notes", "brand_logo_url", "notes_image_url", mode="before"
    )
    @classmethod
    def _blank_str_to_none(cls, v: object) -> object:
        return _empty_str_to_none(v)

class SalesOrderLineConfirmRef(BaseModel):
    sales_order_id: int
    line_id: int


class SalesOrderLinesConfirmBatchIn(BaseModel):
    lines: list[SalesOrderLineConfirmRef]


class SalesOrderLinesSimulateMrpIn(BaseModel):
    lines: list[SalesOrderLineConfirmRef]
    include_shared: bool = True
    shortages_only: bool = False


class SalesOrderLineItemOut(BaseModel):
    id: int
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    size_id: int
    size_value: Optional[str] = None
    qty: int

    model_config = {"from_attributes": True}


class SalesOrderLineOut(BaseModel):
    id: int
    own_product_id: int
    product_code: Optional[str] = None
    product_image_url: Optional[str] = None
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    fabric: Optional[str] = None
    lining: Optional[str] = None
    customer_sku: Optional[str] = None
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    delivery_date: Optional[date] = None
    unit_price: Optional[Decimal] = None
    notes: Optional[str] = None
    total_qty: int
    color_summary: Optional[str] = None
    status: str
    production_order_id: Optional[int] = None
    production_order_no: Optional[str] = None
    items: list[SalesOrderLineItemOut] = []

    model_config = {"from_attributes": True}


class SalesOrderOut(BaseModel):
    id: int
    order_no: str
    customer_id: Optional[int] = None
    customer_name: str
    ordered_at: date
    status: str
    notes: Optional[str] = None
    brand_logo_url: Optional[str] = None
    notes_image_url: Optional[str] = None
    created_at: datetime
    lines: list[SalesOrderLineOut] = []

    model_config = {"from_attributes": True}


class ReportRequest(BaseModel):
    worker_id: int
    order_no: Optional[str] = None
    # K3：可直接认执行单头；与 order_no 二选一（也可同时，以 header_id 为准）
    header_id: Optional[int] = None
    process_name: str
    color_name: Optional[str] = None
    size_value: Optional[str] = None
    qualified_qty: int = Field(ge=0)
    defect_qty: int = Field(ge=0, default=0)
    original_text: Optional[str] = None
    source: str = "manual"
    confirm_over_plan: bool = False
    report_type: str = "normal"
    # 集体计件成员；空则用该工序派工名单
    member_ids: Optional[list[int]] = None
    station_id: Optional[int] = None
    # 扫捆报工：挂到已有追溯单元
    trace_unit_id: Optional[int] = None
    # 报工成功后是否打捆（款开启追溯且合格>0 时默认 True）
    create_trace_bundle: Optional[bool] = None
    # AU-I0：组长代报（可批量选人，数量均分）
    proxy: bool = False
    beneficiary_worker_id: Optional[int] = None
    beneficiary_worker_ids: Optional[list[int]] = None
    # 组报工拆分（可选；空则按技能系数/均分预填）
    shares: Optional[list[dict]] = None

    @model_validator(mode="after")
    def _need_order_or_header(self):
        if not (self.order_no and str(self.order_no).strip()) and not self.header_id:
            raise ValueError("order_no 或 header_id 必填其一")
        return self


class LineReportRequest(BaseModel):
    """成型段线产量报工（P7 41.2，D22-D24）：组长/统计员按线报产量。"""

    header_id: int
    color_name: Optional[str] = None
    team_id: int
    qualified_qty: int = Field(ge=0)
    defect_qty: int = Field(ge=0, default=0)
    rework_qty: int = Field(ge=0, default=0)
    defect_type: str = "质检不良"
    batch_id: Optional[int] = None
    note: Optional[str] = None
    confirm_over_plan: bool = False


class WorkLogStatusUpdate(BaseModel):
    status: str
    review_note: Optional[str] = None


class WorkLogAppealRequest(BaseModel):
    reason: Optional[str] = None


class WorkLogCorrectRequest(BaseModel):
    qualified_qty: int = Field(ge=0, default=0)
    defect_qty: int = Field(ge=0, default=0)
    rework_qty: int = Field(ge=0, default=0)
    color_name: Optional[str] = None
    size_value: Optional[str] = None
    review_note: Optional[str] = None


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


class ProductionLineCreate(BaseModel):
    name: str
    department_id: Optional[int] = None
    sort_order: int = 0


class ProductionLineUpdate(BaseModel):
    name: Optional[str] = None
    department_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ProductionLineOut(BaseModel):
    id: int
    name: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    sort_order: int = 0
    is_active: bool
    team_count: int = 0

    model_config = {"from_attributes": True}


class StationCreate(BaseModel):
    code: str
    name: str
    process_id: int
    location: Optional[str] = None


class StationUpdate(BaseModel):
    name: Optional[str] = None
    process_id: Optional[int] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class StationOut(BaseModel):
    id: int
    code: str
    name: str
    process_id: int
    process_name: Optional[str] = None
    process_type: Optional[str] = None
    location: Optional[str] = None
    is_active: bool
    scan_path: Optional[str] = None

    model_config = {"from_attributes": True}


class StationReportSku(BaseModel):
    color_id: Optional[int] = None
    color_name: Optional[str] = None
    size_id: Optional[int] = None
    size_value: Optional[str] = None
    qty: int = 0


class StationReportCandidate(BaseModel):
    order_id: Optional[int] = None
    order_no: str
    header_id: Optional[int] = None
    customer_name: Optional[str] = None
    plan_qty: int
    completed_qty: int
    status: str
    process_status: str
    assigned_to_me: bool = True
    last_reported_at: Optional[datetime] = None
    items: list[StationReportSku] = []
    last_color_name: Optional[str] = None
    last_size_value: Optional[str] = None
    # None=不限；数字=剩余可报（配额用尽的不进列表）
    remaining_quota: Optional[int] = None
