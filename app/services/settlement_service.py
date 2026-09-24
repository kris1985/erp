"""周期对账与余额制往来结算。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountStatement,
    AccountStatementLine,
    AccountStatementStatus,
    Color,
    OwnProduct,
    PackingCarton,
    PackingCartonLine,
    Partner,
    PartnerSettlementPolicy,
    Payable,
    PayableStatus,
    Payment,
    PaymentStatus,
    PricingUnit,
    Receivable,
    ReceivableStatus,
    PurchaseOrder,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SettlementCycle,
    SettlementDirection,
    SettlementDueRule,
    SettlementMode,
    SettlementPolicyTemplate,
    Shipment,
    ShipmentLine,
    Size,
    SubcontractOrder,
    SupplierProduct,
    SupplierPayment,
    Tenant,
)


ZERO = Decimal("0")

POLICY_FIELDS = (
    "settlement_mode", "cycle_type", "cutoff_day", "reconciliation_day",
    "due_rule", "term_days", "due_months", "fixed_due_day", "basis_type",
    "holiday_rule", "is_active", "notes",
)


class SettlementError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _direction(value: str | SettlementDirection) -> SettlementDirection:
    try:
        return value if isinstance(value, SettlementDirection) else SettlementDirection(value)
    except ValueError as exc:
        raise SettlementError("invalid_direction", "往来方向仅支持 customer 或 supplier") from exc


def _policy_for(
    db: Session,
    tenant_id: int,
    partner_id: int,
    direction: SettlementDirection,
) -> PartnerSettlementPolicy | None:
    return db.scalar(
        select(PartnerSettlementPolicy).where(
            PartnerSettlementPolicy.tenant_id == tenant_id,
            PartnerSettlementPolicy.partner_id == partner_id,
            PartnerSettlementPolicy.direction == direction,
            PartnerSettlementPolicy.is_active.is_(True),
        )
    )


def policy_out(policy: PartnerSettlementPolicy) -> dict:
    return {
        "id": policy.id,
        "partner_id": policy.partner_id,
        "direction": _enum_value(policy.direction),
        "settlement_mode": _enum_value(policy.settlement_mode),
        "cycle_type": _enum_value(policy.cycle_type),
        "cutoff_day": int(policy.cutoff_day or 31),
        "reconciliation_day": policy.reconciliation_day,
        "due_rule": _enum_value(policy.due_rule),
        "term_days": int(policy.term_days or 0),
        "due_months": int(policy.due_months or 0),
        "fixed_due_day": policy.fixed_due_day,
        "basis_type": policy.basis_type,
        "holiday_rule": policy.holiday_rule,
        "is_active": bool(policy.is_active),
        "notes": policy.notes,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def template_out(template: SettlementPolicyTemplate) -> dict:
    return {
        "id": template.id,
        "name": template.name,
        "direction": _enum_value(template.direction),
        "settlement_mode": _enum_value(template.settlement_mode),
        "cycle_type": _enum_value(template.cycle_type),
        "cutoff_day": int(template.cutoff_day or 31),
        "reconciliation_day": template.reconciliation_day,
        "due_rule": _enum_value(template.due_rule),
        "term_days": int(template.term_days or 0),
        "due_months": int(template.due_months or 0),
        "fixed_due_day": template.fixed_due_day,
        "basis_type": template.basis_type,
        "holiday_rule": template.holiday_rule,
        "is_default": bool(template.is_default),
        "is_active": bool(template.is_active),
        "notes": template.notes,
    }


def list_policy_templates(
    db: Session, tenant_id: int, *, direction: str | None = None, active_only: bool = False
) -> list[dict]:
    q = select(SettlementPolicyTemplate).where(SettlementPolicyTemplate.tenant_id == tenant_id)
    if direction:
        q = q.where(SettlementPolicyTemplate.direction == _direction(direction))
    if active_only:
        q = q.where(SettlementPolicyTemplate.is_active.is_(True))
    rows = db.scalars(
        q.order_by(SettlementPolicyTemplate.direction, SettlementPolicyTemplate.is_default.desc(), SettlementPolicyTemplate.id)
    ).all()
    return [template_out(row) for row in rows]


def get_default_policy_template(
    db: Session, tenant_id: int, direction: str
) -> dict | None:
    row = db.scalar(
        select(SettlementPolicyTemplate).where(
            SettlementPolicyTemplate.tenant_id == tenant_id,
            SettlementPolicyTemplate.direction == _direction(direction),
            SettlementPolicyTemplate.is_default.is_(True),
            SettlementPolicyTemplate.is_active.is_(True),
        )
    )
    return template_out(row) if row else None


def upsert_policy_template(
    db: Session,
    tenant_id: int,
    *,
    template_id: int | None = None,
    name: str,
    direction: str,
    is_default: bool = False,
    **policy,
) -> dict:
    side = _direction(direction)
    clean_name = (name or "").strip()
    if not clean_name:
        raise SettlementError("template_name_required", "请填写模板名称")
    values = {
        "settlement_mode": policy.get("settlement_mode", "balance_forward"),
        "cycle_type": policy.get("cycle_type", "monthly"),
        "cutoff_day": policy.get("cutoff_day", 31),
        "reconciliation_day": policy.get("reconciliation_day"),
        "due_rule": policy.get("due_rule", "cutoff_days"),
        "term_days": policy.get("term_days", 0),
        "due_months": policy.get("due_months", 0),
        "fixed_due_day": policy.get("fixed_due_day"),
        "basis_type": policy.get("basis_type", "business_date"),
        "holiday_rule": policy.get("holiday_rule", "none"),
        "is_active": policy.get("is_active", True),
        "notes": policy.get("notes"),
    }
    try:
        mode = SettlementMode(values["settlement_mode"])
        cycle = SettlementCycle(values["cycle_type"])
        due = SettlementDueRule(values["due_rule"])
    except ValueError as exc:
        raise SettlementError("invalid_policy", "结算模式、周期或到期规则不合法") from exc
    cutoff_day = int(values["cutoff_day"] or 31)
    fixed_due_day = values["fixed_due_day"]
    reconciliation_day = values["reconciliation_day"]
    if not 1 <= cutoff_day <= 31:
        raise SettlementError("invalid_cutoff_day", "截账日必须在1到31之间")
    if reconciliation_day is not None and not 1 <= int(reconciliation_day) <= 31:
        raise SettlementError("invalid_reconciliation_day", "对账日必须在1到31之间")
    if due == SettlementDueRule.fixed_day and fixed_due_day is None:
        raise SettlementError("fixed_due_day_required", "固定日到期规则必须填写固定收付款日")
    if fixed_due_day is not None and not 1 <= int(fixed_due_day) <= 31:
        raise SettlementError("invalid_fixed_due_day", "固定收付款日必须在1到31之间")
    row = db.get(SettlementPolicyTemplate, template_id) if template_id else None
    if template_id and (not row or row.tenant_id != tenant_id):
        raise SettlementError("template_not_found", "结算模板不存在")
    duplicate = db.scalar(
        select(SettlementPolicyTemplate).where(
            SettlementPolicyTemplate.tenant_id == tenant_id,
            SettlementPolicyTemplate.direction == side,
            SettlementPolicyTemplate.name == clean_name,
            SettlementPolicyTemplate.id != (template_id or 0),
        )
    )
    if duplicate:
        raise SettlementError("template_name_exists", "同方向下已存在同名模板")
    if not row:
        row = SettlementPolicyTemplate(
            tenant_id=tenant_id,
            name=clean_name,
            direction=side,
        )
        db.add(row)
    if is_default:
        for other in db.scalars(
            select(SettlementPolicyTemplate).where(
                SettlementPolicyTemplate.tenant_id == tenant_id,
                SettlementPolicyTemplate.direction == side,
                SettlementPolicyTemplate.id != (template_id or 0),
            )
        ).all():
            other.is_default = False
    row.name = clean_name
    row.direction = side
    row.settlement_mode = mode
    row.cycle_type = cycle
    row.cutoff_day = cutoff_day
    row.reconciliation_day = int(reconciliation_day) if reconciliation_day is not None else None
    row.due_rule = due
    row.term_days = max(0, int(values["term_days"] or 0))
    row.due_months = max(0, int(values["due_months"] or 0))
    row.fixed_due_day = int(fixed_due_day) if fixed_due_day is not None else None
    row.basis_type = values["basis_type"] or "business_date"
    row.holiday_rule = values["holiday_rule"] or "none"
    row.is_default = bool(is_default)
    row.is_active = bool(values["is_active"])
    row.notes = values["notes"]
    db.commit()
    db.refresh(row)
    return template_out(row)


def delete_policy_template(db: Session, tenant_id: int, template_id: int) -> None:
    row = db.get(SettlementPolicyTemplate, template_id)
    if not row or row.tenant_id != tenant_id:
        raise SettlementError("template_not_found", "结算模板不存在")
    db.delete(row)
    db.commit()


def template_policy_payload(template: dict) -> dict:
    return {key: template.get(key) for key in POLICY_FIELDS}


def get_policy(
    db: Session,
    tenant_id: int,
    partner_id: int,
    direction: str | SettlementDirection,
) -> dict:
    side = _direction(direction)
    partner = db.get(Partner, partner_id)
    if not partner or partner.tenant_id != tenant_id:
        raise SettlementError("partner_not_found", "往来单位不存在")
    policy = _policy_for(db, tenant_id, partner_id, side)
    if policy:
        return policy_out(policy)
    # 旧数据虚拟策略：不立即写库，保留原 payment_term_days 的到期逻辑。
    return {
        "id": None,
        "partner_id": partner_id,
        "direction": side.value,
        "settlement_mode": SettlementMode.balance_forward.value,
        "cycle_type": SettlementCycle.monthly.value,
        "cutoff_day": 31,
        "reconciliation_day": None,
        "due_rule": SettlementDueRule.cutoff_days.value,
        "term_days": int(partner.payment_term_days or 0),
        "due_months": 0,
        "fixed_due_day": None,
        "basis_type": "business_date",
        "holiday_rule": "none",
        "is_active": True,
        "notes": None,
        "legacy_fallback": True,
    }


def upsert_policy(
    db: Session,
    tenant_id: int,
    partner_id: int,
    direction: str,
    *,
    settlement_mode: str = "balance_forward",
    cycle_type: str = "monthly",
    cutoff_day: int = 31,
    reconciliation_day: int | None = None,
    due_rule: str = "cutoff_days",
    term_days: int = 0,
    due_months: int = 0,
    fixed_due_day: int | None = None,
    basis_type: str = "business_date",
    holiday_rule: str = "none",
    is_active: bool = True,
    notes: str | None = None,
    commit: bool = True,
) -> dict:
    side = _direction(direction)
    partner = db.get(Partner, partner_id)
    if not partner or partner.tenant_id != tenant_id:
        raise SettlementError("partner_not_found", "往来单位不存在")
    if side == SettlementDirection.customer and not (partner.is_customer or partner.is_brand):
        raise SettlementError("invalid_partner_role", "该往来单位不是客户")
    if side == SettlementDirection.supplier and not (partner.is_supplier or partner.is_subcontractor):
        raise SettlementError("invalid_partner_role", "该往来单位不是供应商或外加工厂")
    try:
        mode = SettlementMode(settlement_mode)
        cycle = SettlementCycle(cycle_type)
        due = SettlementDueRule(due_rule)
    except ValueError as exc:
        raise SettlementError("invalid_policy", "结算模式、周期或到期规则不合法") from exc
    if not 1 <= int(cutoff_day) <= 31:
        raise SettlementError("invalid_cutoff_day", "截账日必须在1到31之间")
    if reconciliation_day is not None and not 1 <= int(reconciliation_day) <= 31:
        raise SettlementError("invalid_reconciliation_day", "对账日必须在1到31之间")
    if fixed_due_day is not None and not 1 <= int(fixed_due_day) <= 31:
        raise SettlementError("invalid_fixed_due_day", "固定付款日必须在1到31之间")
    if due == SettlementDueRule.fixed_day and fixed_due_day is None:
        raise SettlementError("fixed_due_day_required", "固定日到期规则必须填写固定付款日")
    if int(term_days) < 0 or int(due_months) < 0:
        raise SettlementError("invalid_term", "账期天数和月份不能为负数")

    policy = db.scalar(
        select(PartnerSettlementPolicy).where(
            PartnerSettlementPolicy.tenant_id == tenant_id,
            PartnerSettlementPolicy.partner_id == partner_id,
            PartnerSettlementPolicy.direction == side,
        )
    )
    if not policy:
        policy = PartnerSettlementPolicy(
            tenant_id=tenant_id,
            partner_id=partner_id,
            direction=side,
        )
        db.add(policy)
    policy.settlement_mode = mode
    policy.cycle_type = cycle
    policy.cutoff_day = int(cutoff_day)
    policy.reconciliation_day = (
        int(reconciliation_day) if reconciliation_day is not None else None
    )
    policy.due_rule = due
    policy.term_days = int(term_days)
    policy.due_months = int(due_months)
    policy.fixed_due_day = int(fixed_due_day) if fixed_due_day is not None else None
    policy.basis_type = (basis_type or "business_date").strip()
    policy.holiday_rule = (holiday_rule or "none").strip()
    policy.is_active = bool(is_active)
    policy.notes = notes
    if commit:
        db.commit()
        db.refresh(policy)
    else:
        db.flush()
    return policy_out(policy)


def _add_months(base: date, months: int, day: int) -> date:
    month_index = base.year * 12 + (base.month - 1) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(day, monthrange(year, month)[1]))


def calculate_due_date(
    policy: PartnerSettlementPolicy | dict | None,
    *,
    business_date: date,
    fallback_term_days: int = 0,
) -> date:
    """按显式结算政策计算到期日；无政策时兼容发生日+N天。"""
    if policy is None:
        return business_date + timedelta(days=max(0, int(fallback_term_days)))

    def read(name: str, default=None):
        return policy.get(name, default) if isinstance(policy, dict) else getattr(policy, name, default)

    due_rule = _enum_value(read("due_rule", SettlementDueRule.cutoff_days))
    term_days = max(0, int(read("term_days", 0) or 0))
    if due_rule in {
        SettlementDueRule.transaction_days.value,
        SettlementDueRule.cutoff_days.value,
    }:
        return business_date + timedelta(days=term_days)
    fixed_day = int(read("fixed_due_day", 31) or 31)
    due_months = max(0, int(read("due_months", 0) or 0))
    candidate = _add_months(business_date, due_months, fixed_day)
    if due_months == 0 and candidate < business_date:
        candidate = _add_months(business_date, 1, fixed_day)
    return candidate


def settlement_cycle_end(
    policy: PartnerSettlementPolicy | dict | None, business_date: date
) -> date:
    """返回一笔业务所属结算周期的截账日。"""
    if policy is None:
        return business_date

    def read(name: str, default=None):
        return policy.get(name, default) if isinstance(policy, dict) else getattr(policy, name, default)

    cycle = _enum_value(read("cycle_type", SettlementCycle.per_transaction))
    if cycle == SettlementCycle.per_transaction.value:
        return business_date
    last_day = monthrange(business_date.year, business_date.month)[1]
    if cycle == SettlementCycle.semimonthly.value:
        return (
            date(business_date.year, business_date.month, 15)
            if business_date.day <= 15
            else date(business_date.year, business_date.month, last_day)
        )
    if cycle == SettlementCycle.ten_day.value:
        day = 10 if business_date.day <= 10 else 20 if business_date.day <= 20 else last_day
        return date(business_date.year, business_date.month, day)

    cutoff = max(1, min(31, int(read("cutoff_day", 31) or 31)))
    this_cutoff = date(
        business_date.year,
        business_date.month,
        min(cutoff, last_day),
    )
    if business_date <= this_cutoff:
        return this_cutoff
    next_month = _add_months(business_date, 1, 1)
    next_last = monthrange(next_month.year, next_month.month)[1]
    return date(next_month.year, next_month.month, min(cutoff, next_last))


def effective_due_date(
    db: Session,
    tenant_id: int,
    partner_id: int,
    direction: str | SettlementDirection,
    *,
    business_date: date,
    fallback_term_days: int = 0,
) -> date:
    policy = _policy_for(db, tenant_id, partner_id, _direction(direction))
    due_basis = business_date
    if policy and policy.due_rule != SettlementDueRule.transaction_days:
        due_basis = settlement_cycle_end(policy, business_date)
    return calculate_due_date(
        policy,
        business_date=due_basis,
        fallback_term_days=fallback_term_days,
    )


def _next_statement_no(
    db: Session, tenant_id: int, direction: SettlementDirection, period_end: date
) -> str:
    prefix = f"DZ-{direction.value[0].upper()}-{period_end:%Y%m}"
    count = int(
        db.scalar(
            select(func.count())
            .select_from(AccountStatement)
            .where(
                AccountStatement.tenant_id == tenant_id,
                AccountStatement.statement_no.like(f"{prefix}-%"),
            )
        )
        or 0
    )
    return f"{prefix}-{count + 1:04d}"


def _signed_line(
    statement: AccountStatement,
    *,
    tenant_id: int,
    source_type: str,
    source_id: int | None,
    business_date: date,
    document_no: str | None,
    description: str | None,
    amount: Decimal,
    sort_order: int,
) -> None:
    debit = amount if amount >= ZERO else ZERO
    credit = -amount if amount < ZERO else ZERO
    statement.lines.append(
        AccountStatementLine(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            business_date=business_date,
            document_no=document_no,
            description=description,
            debit_amount=_money(debit),
            credit_amount=_money(credit),
            disputed_amount=ZERO,
            sort_order=sort_order,
        )
    )


def generate_statement(
    db: Session,
    tenant_id: int,
    *,
    partner_id: int,
    direction: str,
    period_start: date,
    period_end: date,
    statement_date: date | None = None,
    due_date: date | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict:
    side = _direction(direction)
    if period_start > period_end:
        raise SettlementError("invalid_period", "对账期间开始日期不能晚于结束日期")
    partner = db.get(Partner, partner_id)
    if not partner or partner.tenant_id != tenant_id:
        raise SettlementError("partner_not_found", "往来单位不存在")
    if side == SettlementDirection.supplier and not partner.is_subcontractor:
        raise SettlementError(
            "supplier_statement_moved",
            "供应商对账单请在应付页面勾选待结算明细生成",
        )
    duplicate = db.scalar(
        select(AccountStatement).where(
            AccountStatement.tenant_id == tenant_id,
            AccountStatement.partner_id == partner_id,
            AccountStatement.direction == side,
            AccountStatement.period_start == period_start,
            AccountStatement.period_end == period_end,
            AccountStatement.status != AccountStatementStatus.void,
        )
    )
    if duplicate:
        raise SettlementError("duplicate_period", "该往来单位此期间已有对账单")

    opening = ZERO
    current = ZERO
    adjustment = ZERO
    period_settlement = ZERO
    source_rows: list[dict] = []

    if side == SettlementDirection.customer:
        documents = list(
            db.scalars(
                select(Receivable).where(
                    Receivable.tenant_id == tenant_id,
                    Receivable.customer_id == partner_id,
                    Receivable.status != ReceivableStatus.void,
                    Receivable.receivable_date <= period_end,
                )
            ).all()
        )
        settlements = list(
            db.scalars(
                select(Payment).where(
                    Payment.tenant_id == tenant_id,
                    Payment.customer_id == partner_id,
                    Payment.status == PaymentStatus.posted,
                    Payment.payment_date <= period_end,
                )
            ).all()
        )
        for ar in documents:
            base = _money(ar.amount)
            adj = _money(ar.adjustment)
            if ar.receivable_date < period_start:
                opening += base + adj
                continue
            current += base
            adjustment += adj
            shipment = db.get(Shipment, ar.shipment_id) if ar.shipment_id else None
            shipment_no = shipment.shipment_no if shipment else None
            document_no = shipment_no or ar.sales_order_no
            description = (
                f"销售单 {ar.sales_order_no} · 出货货款"
                if ar.sales_order_no
                else "本期出货货款"
            )
            source_rows.append(
                {
                    "source_type": "receivable",
                    "source_id": ar.id,
                    "business_date": ar.receivable_date,
                    "document_no": document_no,
                    "description": description,
                    "amount": base,
                }
            )
            if adj:
                source_rows.append(
                    {
                        "source_type": "receivable_adjustment",
                        "source_id": ar.id,
                        "business_date": ar.receivable_date,
                        "document_no": document_no,
                        "description": ar.notes or "退货/扣款/金额调整",
                        "amount": adj,
                    }
                )
        for payment in settlements:
            amount = _money(payment.amount)
            if payment.payment_date < period_start:
                opening -= amount
                continue
            period_settlement += amount
            source_rows.append(
                {
                    "source_type": "payment",
                    "source_id": payment.id,
                    "business_date": payment.payment_date,
                    "document_no": payment.voucher_no or f"SK-{payment.id}",
                    "description": "客户回款",
                    "amount": -amount,
                }
            )
    else:
        documents = list(
            db.scalars(
                select(Payable).where(
                    Payable.tenant_id == tenant_id,
                    Payable.supplier_id == partner_id,
                    Payable.status != PayableStatus.void,
                    Payable.payable_date <= period_end,
                )
            ).all()
        )
        settlements = list(
            db.scalars(
                select(SupplierPayment).where(
                    SupplierPayment.tenant_id == tenant_id,
                    SupplierPayment.supplier_id == partner_id,
                    SupplierPayment.status == PaymentStatus.posted,
                    SupplierPayment.payment_date <= period_end,
                )
            ).all()
        )
        for ap in documents:
            base = _money(ap.amount)
            adj = _money(ap.adjustment)
            if ap.payable_date < period_start:
                opening += base + adj
                continue
            current += base
            adjustment += adj
            purchase_order = db.get(PurchaseOrder, ap.purchase_order_id) if ap.purchase_order_id else None
            subcontract_order = db.get(SubcontractOrder, ap.subcontract_order_id) if ap.subcontract_order_id else None
            ref = purchase_order.po_no if purchase_order else subcontract_order.subcontract_no if subcontract_order else None
            payable_description = "外协加工费" if ap.subcontract_order_id else "采购入库货款"
            source_rows.append(
                {
                    "source_type": "payable",
                    "source_id": ap.id,
                    "business_date": ap.payable_date,
                    "document_no": ref,
                    "description": ap.notes or payable_description,
                    "amount": base,
                }
            )
            if adj:
                source_rows.append(
                    {
                        "source_type": "payable_adjustment",
                        "source_id": ap.id,
                        "business_date": ap.payable_date,
                        "document_no": ref,
                        "description": ap.notes or "退货/扣款/金额调整",
                        "amount": adj,
                    }
                )
        for payment in settlements:
            amount = _money(payment.amount)
            if payment.payment_date < period_start:
                opening -= amount
                continue
            period_settlement += amount
            source_rows.append(
                {
                    "source_type": "supplier_payment",
                    "source_id": payment.id,
                    "business_date": payment.payment_date,
                    "document_no": payment.voucher_no or f"FK-{payment.id}",
                    "description": "供应商付款",
                    "amount": -amount,
                }
            )

    policy = _policy_for(db, tenant_id, partner_id, side)
    legacy_days = int(partner.payment_term_days or 0)
    actual_due = due_date or calculate_due_date(
        policy,
        business_date=period_end,
        fallback_term_days=legacy_days,
    )
    statement = AccountStatement(
        tenant_id=tenant_id,
        statement_no=_next_statement_no(db, tenant_id, side, period_end),
        partner_id=partner_id,
        partner_name=partner.short_name or partner.name,
        direction=side,
        period_start=period_start,
        period_end=period_end,
        statement_date=statement_date or date.today(),
        due_date=actual_due,
        opening_balance=_money(opening),
        current_amount=_money(current),
        adjustment_amount=_money(adjustment),
        period_settlement_amount=_money(period_settlement),
        closing_balance=_money(opening + current + adjustment - period_settlement),
        status=AccountStatementStatus.draft,
        notes=notes,
        created_by=user_id,
    )
    db.add(statement)
    if opening:
        _signed_line(
            statement,
            tenant_id=tenant_id,
            source_type="opening_balance",
            source_id=None,
            business_date=period_start,
            document_no=None,
            description="期初余额",
            amount=opening,
            sort_order=0,
        )
    for index, item in enumerate(
        sorted(source_rows, key=lambda row: (row["business_date"], row["source_type"], row["source_id"])),
        start=1,
    ):
        _signed_line(statement, tenant_id=tenant_id, sort_order=index, **item)
    db.commit()
    return statement_out(db, tenant_id, statement.id, with_lines=True)


def statement_settled_amount(db: Session, statement: AccountStatement) -> Decimal:
    if statement.direction == SettlementDirection.customer:
        amount = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenant_id == statement.tenant_id,
                Payment.statement_id == statement.id,
                Payment.status == PaymentStatus.posted,
            )
        )
    else:
        amount = db.scalar(
            select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(
                SupplierPayment.tenant_id == statement.tenant_id,
                SupplierPayment.statement_id == statement.id,
                SupplierPayment.status == PaymentStatus.posted,
            )
        )
    return _money(amount)


def refresh_statement_status(db: Session, statement_id: int) -> None:
    statement = db.get(AccountStatement, statement_id)
    if not statement or statement.status in {
        AccountStatementStatus.draft,
        AccountStatementStatus.disputed,
        AccountStatementStatus.void,
    }:
        return
    paid = statement_settled_amount(db, statement)
    closing = _money(statement.closing_balance)
    if closing <= ZERO or paid >= closing:
        statement.status = AccountStatementStatus.settled
    elif paid > ZERO:
        statement.status = AccountStatementStatus.partial
    else:
        statement.status = AccountStatementStatus.confirmed


def _shipment_statement_items(db: Session, shipment_id: int | None) -> list[dict]:
    """客户对账打印用的本次实际出货货品明细。"""
    if not shipment_id:
        return []
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        return []
    shipment_lines = list(
        db.scalars(
            select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.id)
        ).all()
    )
    item_ids = {
        int(row.sales_order_line_item_id)
        for row in shipment_lines
        if row.sales_order_line_item_id
    }
    items = {
        row.id: row
        for row in db.scalars(
            select(SalesOrderLineItem).where(SalesOrderLineItem.id.in_(item_ids or {-1}))
        ).all()
    }
    sales_line_ids = {row.sales_order_line_id for row in items.values()}
    sales_lines = {
        row.id: row
        for row in db.scalars(
            select(SalesOrderLine).where(SalesOrderLine.id.in_(sales_line_ids or {-1}))
        ).all()
    }
    sales_order_ids = {sl.sales_order_id for sl in sales_lines.values()}
    sales_orders = {
        row.id: row
        for row in db.scalars(
            select(SalesOrder).where(SalesOrder.id.in_(sales_order_ids or {-1}))
        ).all()
    }
    own_product_ids = {
        int(sales_line.own_product_id)
        for sales_line in sales_lines.values()
        if sales_line.own_product_id
    }
    own_products = {
        row.id: row
        for row in db.scalars(
            select(OwnProduct).where(OwnProduct.id.in_(own_product_ids or {-1}))
        ).all()
    }
    cartons = list(
        db.scalars(select(PackingCarton).where(PackingCarton.shipment_id == shipment.id)).all()
    )
    carton_ids = {carton.id for carton in cartons}
    carton_line_rows = list(
        db.scalars(
            select(PackingCartonLine).where(
                PackingCartonLine.carton_id.in_(carton_ids or {-1})
            )
        ).all()
    )
    carton_lines: dict[int, list[PackingCartonLine]] = {}
    for row in carton_line_rows:
        carton_lines.setdefault(row.carton_id, []).append(row)
    carton_counts: dict[int | None, int] = {}
    for carton in cartons:
        carton_counts[carton.sales_order_line_id] = carton_counts.get(carton.sales_order_line_id, 0) + 1

    grouped: dict[int | None, list[ShipmentLine]] = {}
    for row in shipment_lines:
        item = items.get(row.sales_order_line_item_id) if row.sales_order_line_item_id else None
        line_id = item.sales_order_line_id if item else None
        grouped.setdefault(line_id, []).append(row)

    result: list[dict] = []
    for line_id, rows in grouped.items():
        sales_line = sales_lines.get(line_id) if line_id else None
        matching_cartons = [c for c in cartons if c.sales_order_line_id == line_id]
        if not matching_cartons and len(grouped) == 1:
            matching_cartons = cartons
        carton_count = len(matching_cartons)
        qty = sum(int(row.qty or 0) for row in rows)
        size_qty: dict[tuple[int | None, int], int] = {}
        color_ids: set[int] = set()
        size_ids: set[int] = set()
        for row in rows:
            if row.color_id:
                color_ids.add(int(row.color_id))
            size_ids.add(int(row.size_id))
            key = (int(row.color_id) if row.color_id else None, int(row.size_id))
            size_qty[key] = size_qty.get(key, 0) + int(row.qty or 0)
        colors = {
            row.id: row.name
            for row in db.scalars(select(Color).where(Color.id.in_(color_ids or {-1}))).all()
        }
        sizes = {
            row.id: (row.size_value, int(row.sort_order or 0))
            for row in db.scalars(select(Size).where(Size.id.in_(size_ids or {-1}))).all()
        }
        carton_signatures = {
            tuple(
                sorted(
                    (
                        int(row.color_id) if row.color_id else None,
                        int(row.size_id),
                        int(row.qty or 0),
                    )
                    for row in carton_lines.get(carton.id, [])
                    if int(row.qty or 0) > 0
                )
            )
            for carton in matching_cartons
        }
        per_carton = (
            bool(carton_count)
            and len(carton_signatures) == 1
            and bool(next(iter(carton_signatures), ()))
            and sum(sum(part[2] for part in signature) for signature in carton_signatures) * carton_count == qty
        )
        size_breakdown_qty: dict[str, int] = {}
        for (color_id, size_id), amount in sorted(
            size_qty.items(), key=lambda pair: (sizes.get(pair[0][1], (str(pair[0][1]), 0))[1], sizes.get(pair[0][1], (str(pair[0][1]), 0))[0])
        ):
            display_qty = amount // carton_count if per_carton else amount
            size_value = sizes.get(size_id, (str(size_id), 0))[0]
            size_breakdown_qty[size_value] = size_breakdown_qty.get(size_value, 0) + display_qty
        size_breakdown = [
            {"size_value": size_value, "qty": amount}
            for size_value, amount in size_breakdown_qty.items()
        ]
        assortment_parts = [
            f"{row['size_value']}×{row['qty']}" for row in size_breakdown
        ]
        # 对账金额必须与已过账出货单口径完全一致，不能重新套用后来修改的订单价格。
        unit_price = _money(shipment.unit_price)
        customer_sku = None
        brand_name = None
        if matching_cartons:
            customer_sku = matching_cartons[0].customer_sku
            brand_name = matching_cartons[0].brand_name
        customer_sku = customer_sku or (sales_line.customer_sku if sales_line else None)
        brand_name = brand_name or (sales_line.brand_name if sales_line else None)
        own_product = (
            own_products.get(int(sales_line.own_product_id))
            if sales_line and sales_line.own_product_id
            else None
        )
        product_code = own_product.product_code if own_product else None
        image_url = own_product.image_url if own_product else None
        sales_order = (
            sales_orders.get(sales_line.sales_order_id)
            if sales_line else None
        )
        result.append(
            {
                "shipment_no": shipment.shipment_no,
                "sales_order_no": sales_order.order_no if sales_order else None,
                "brand_name": brand_name,
                "product_code": product_code,
                "image_url": image_url,
                "customer_sku": customer_sku,
                "color_name": "/".join(colors[color_id] for color_id in sorted(colors)) or None,
                "assortment": " / ".join(assortment_parts),
                "assortment_label": "每箱配码" if per_carton else "出货尺码",
                "size_breakdown": size_breakdown,
                "carton_count": carton_count or None,
                "qty": qty,
                "unit_price": unit_price,
                "amount": _money(unit_price * qty),
            }
        )
    return result


def _payable_statement_items(db: Session, payable_id: int | None) -> list[dict]:
    """供应商对账用的采购到货/外协验收快照明细。"""
    if not payable_id:
        return []
    payable = db.scalar(
        select(Payable)
        .where(Payable.id == payable_id)
        .options(selectinload(Payable.lines))
    )
    if not payable:
        return []
    if not payable.lines and payable.purchase_order_id:
        return _legacy_purchase_payable_items(db, payable)
    grouped: dict[tuple, dict] = {}
    for line in payable.lines or []:
        key = (
            line.source_type,
            line.source_document_no,
            line.item_code,
            line.item_name,
            line.process_name,
            line.customer_sku,
            line.color_name,
            line.unit_name,
            str(line.unit_price or 0),
        )
        item = grouped.setdefault(
            key,
            {
                "source_type": line.source_type,
                "source_document_no": line.source_document_no,
                "item_code": line.item_code,
                "item_name": line.item_name,
                "process_name": line.process_name,
                "customer_sku": line.customer_sku,
                "color_name": line.color_name,
                "unit_name": line.unit_name,
                "qty": ZERO,
                "unit_price": _money(line.unit_price),
                "amount": ZERO,
                "size_qty": {},
            },
        )
        qty = _money(line.qty)
        item["qty"] += qty
        item["amount"] += _money(line.amount)
        if line.size_value:
            size_value = str(line.size_value)
            item["size_qty"][size_value] = item["size_qty"].get(size_value, ZERO) + qty
    result = []
    for item in grouped.values():
        size_qty = item.pop("size_qty")
        item["size_breakdown"] = [
            {"size_value": size, "qty": qty}
            for size, qty in sorted(
                size_qty.items(),
                key=lambda pair: pair[0],
            )
        ]
        item["qty"] = _money(item["qty"])
        item["amount"] = _money(item["amount"])
        result.append(item)
    return result


def _legacy_purchase_payable_items(db: Session, payable: Payable) -> list[dict]:
    """为上线前没有 PayableLine 快照的采购应付还原一行到货明细。

    老数据是一条采购到货行生成一笔应付。按同一采购单内的应付金额与
    ``累计到货数量 × 采购单价`` 做一一匹配；无法可靠匹配时宁可返回空，
    避免把供应商金额挂到错误物料上。
    """
    po = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == payable.purchase_order_id)
        .options(selectinload(PurchaseOrder.lines))
    )
    if not po:
        return []
    sibling_payables = list(
        db.scalars(
            select(Payable).where(
                Payable.tenant_id == payable.tenant_id,
                Payable.purchase_order_id == po.id,
            ).order_by(Payable.id)
        ).all()
    )
    available_lines = sorted(po.lines, key=lambda row: row.id)
    matched_line = None
    for sibling in sibling_payables:
        sibling_amount = _money(sibling.amount)
        candidate_index = next(
            (
                index
                for index, line in enumerate(available_lines)
                if _money(line.received_qty * line.unit_price) == sibling_amount
            ),
            None,
        )
        if candidate_index is None:
            continue
        candidate = available_lines.pop(candidate_index)
        if sibling.id == payable.id:
            matched_line = candidate
            break
    if not matched_line:
        return []

    product = db.get(SupplierProduct, matched_line.supplier_product_id)
    color = db.get(Color, product.color_id) if product and product.color_id else None
    size = db.get(Size, matched_line.size_id) if matched_line.size_id else None
    unit = db.get(PricingUnit, product.pricing_unit_id) if product and product.pricing_unit_id else None
    qty = _money(matched_line.received_qty)
    return [{
        "source_type": "purchase_receive",
        "source_document_no": po.po_no,
        "item_code": product.product_code if product else None,
        "item_name": product.name if product else None,
        "process_name": None,
        "customer_sku": None,
        "color_name": color.name if color else None,
        "unit_name": unit.name if unit else None,
        "qty": qty,
        "unit_price": _money(matched_line.unit_price),
        "amount": _money(payable.amount),
        "size_breakdown": ([{"size_value": size.size_value, "qty": qty}] if size else []),
    }]


def statement_out(
    db: Session, tenant_id: int, statement_id: int, *, with_lines: bool = False
) -> dict:
    query = select(AccountStatement).where(
        AccountStatement.id == statement_id, AccountStatement.tenant_id == tenant_id
    )
    if with_lines:
        query = query.options(selectinload(AccountStatement.lines))
    statement = db.scalar(query)
    if not statement:
        raise SettlementError("statement_not_found", "对账单不存在")
    settled = statement_settled_amount(db, statement)
    closing = _money(statement.closing_balance)
    remaining = max(ZERO, closing - settled)
    tenant = db.get(Tenant, tenant_id)
    partner = db.get(Partner, statement.partner_id)
    primary_contact = None
    if partner:
        active_contacts = [contact for contact in partner.contacts if contact.is_active]
        primary_contact = next(
            (contact for contact in active_contacts if contact.is_primary),
            active_contacts[0] if active_contacts else None,
        )
    result = {
        "id": statement.id,
        "statement_no": statement.statement_no,
        "partner_id": statement.partner_id,
        "partner_name": statement.partner_name,
        "direction": _enum_value(statement.direction),
        "partner_type": (
            "customer"
            if statement.direction == SettlementDirection.customer
            else "subcontractor" if partner and partner.is_subcontractor else "supplier"
        ),
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "statement_date": statement.statement_date,
        "due_date": statement.due_date,
        "opening_balance": statement.opening_balance,
        "current_amount": statement.current_amount,
        "adjustment_amount": statement.adjustment_amount,
        "period_settlement_amount": statement.period_settlement_amount,
        "closing_balance": statement.closing_balance,
        "settled_amount": settled,
        "remaining_amount": _money(remaining),
        "status": _enum_value(statement.status),
        "statement_kind": statement.statement_kind or "period",
        "notes": statement.notes,
        "confirmed_at": statement.confirmed_at,
        "created_at": statement.created_at,
        "issuer_name": tenant.name if tenant else None,
        "issuer_contact_name": tenant.contact_person if tenant else None,
        "issuer_contact_mobile": tenant.contact_mobile if tenant else None,
        "issuer_address": tenant.address if tenant else None,
        "issuer_bank_name": tenant.bank_name if tenant else None,
        "issuer_bank_account": tenant.bank_account if tenant else None,
        "issuer_bank_account_name": tenant.bank_account_name if tenant else None,
        "partner_full_name": partner.name if partner else statement.partner_name,
        "partner_address": partner.address if partner else None,
        "partner_contact_name": primary_contact.name if primary_contact else None,
        "partner_contact_mobile": primary_contact.mobile if primary_contact else None,
        "settlement_policy": get_policy(
            db, tenant_id, statement.partner_id, _enum_value(statement.direction)
        ),
    }
    if with_lines:
        result["lines"] = []
        for line in statement.lines:
            line_out = {
                "id": line.id,
                "source_type": line.source_type,
                "source_id": line.source_id,
                "business_date": line.business_date,
                "document_no": line.document_no,
                "description": line.description,
                "debit_amount": line.debit_amount,
                "credit_amount": line.credit_amount,
                "disputed_amount": line.disputed_amount,
                "sort_order": line.sort_order,
            }
            if line.source_type == "receivable" and line.source_id:
                receivable = db.get(Receivable, line.source_id)
                line_out["shipment_items"] = _shipment_statement_items(
                    db, receivable.shipment_id if receivable else None
                )
                from app.services.sales_settlement_service import receivable_item

                item = receivable_item(db, line.source_id)
                line_out["customer_items"] = [item] if item else []
            elif line.source_type == "after_sales_return" and line.source_id:
                from app.services.sales_settlement_service import return_item

                item = return_item(db, line.source_id)
                line_out["customer_items"] = [item] if item else []
                if item:
                    line_out["shipment_items"] = [
                        {
                            "shipment_no": item.get("return_no"),
                            "sales_order_no": item.get("sales_order_no"),
                            "product_code": item.get("factory_model"),
                            "image_url": item.get("image_url"),
                            "color_name": item.get("color_name"),
                            "qty": item.get("qty"),
                            "unit_price": item.get("unit_price"),
                            "amount": item.get("amount"),
                        }
                    ]
            elif line.source_type == "payable" and line.source_id:
                line_out["supplier_items"] = _payable_statement_items(db, line.source_id)
            elif line.source_type == "payable_line" and line.source_id:
                from app.services.subcontract_settlement_service import subcontract_line_item

                item = subcontract_line_item(db, line.source_id)
                if item is None:
                    from app.services.purchase_settlement_service import payable_line_item

                    item = payable_line_item(db, line.source_id)
                line_out["supplier_items"] = [item] if item else []
            elif line.source_type == "payable_remainder" and line.source_id:
                from app.services.subcontract_settlement_service import subcontract_remainder_item

                item = subcontract_remainder_item(db, line.source_id)
                if item is None:
                    from app.services.purchase_settlement_service import remainder_item

                    item = remainder_item(db, line.source_id)
                line_out["supplier_items"] = [item] if item else []
            result["lines"].append(line_out)
    return result


def list_statements(
    db: Session,
    tenant_id: int,
    *,
    partner_id: int | None = None,
    direction: str | None = None,
    partner_type: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    query = select(AccountStatement).where(
        AccountStatement.tenant_id == tenant_id,
        AccountStatement.statement_kind.notin_(("purchase", "sales", "subcontract")),
    )
    if partner_id:
        query = query.where(AccountStatement.partner_id == partner_id)
    if direction:
        query = query.where(AccountStatement.direction == _direction(direction))
    if partner_type:
        query = query.join(Partner, Partner.id == AccountStatement.partner_id)
        if partner_type == "customer":
            query = query.where(Partner.is_customer.is_(True) | Partner.is_brand.is_(True))
        elif partner_type == "supplier":
            query = query.where(
                Partner.is_supplier.is_(True),
                Partner.is_subcontractor.is_(False),
            )
        elif partner_type == "subcontractor":
            query = query.where(Partner.is_subcontractor.is_(True))
        else:
            raise SettlementError("invalid_partner_type", "往来类型仅支持客户、供应商或外加工厂")
    if date_from and date_to and date_from > date_to:
        raise SettlementError("invalid_date_range", "开始日期不能晚于结束日期")
    # 查询与所选日期范围有交集的对账期间。
    if date_from:
        query = query.where(AccountStatement.period_end >= date_from)
    if date_to:
        query = query.where(AccountStatement.period_start <= date_to)
    if status:
        try:
            query = query.where(AccountStatement.status == AccountStatementStatus(status))
        except ValueError as exc:
            raise SettlementError("invalid_status", "对账单状态不合法") from exc
    rows = list(
        db.scalars(query.order_by(AccountStatement.period_end.desc(), AccountStatement.id.desc())).all()
    )
    return [statement_out(db, tenant_id, row.id) for row in rows]


def confirm_statement(db: Session, tenant_id: int, statement_id: int) -> dict:
    statement = db.get(AccountStatement, statement_id)
    if not statement or statement.tenant_id != tenant_id:
        raise SettlementError("statement_not_found", "对账单不存在")
    if statement.status == AccountStatementStatus.void:
        raise SettlementError("statement_void", "已作废对账单不能确认")
    statement.status = AccountStatementStatus.confirmed
    statement.confirmed_at = datetime.now()
    db.flush()
    refresh_statement_status(db, statement.id)
    db.commit()
    return statement_out(db, tenant_id, statement.id, with_lines=True)


def void_statement(db: Session, tenant_id: int, statement_id: int) -> dict:
    statement = db.get(AccountStatement, statement_id)
    if not statement or statement.tenant_id != tenant_id:
        raise SettlementError("statement_not_found", "对账单不存在")
    kind = statement.statement_kind or "period"
    if statement.direction == SettlementDirection.supplier and kind != "purchase":
        partner = db.get(Partner, statement.partner_id)
        if not partner or not partner.is_subcontractor:
            raise SettlementError("statement_frozen", "供应商期间对账单已封存")
    if kind == "purchase":
        from app.services.purchase_settlement_service import void_purchase_statement

        try:
            return void_purchase_statement(db, tenant_id, statement_id)
        except Exception as exc:
            from app.services.ap_service import ApError

            if isinstance(exc, ApError):
                raise SettlementError(exc.code, exc.message) from exc
            raise
    if kind == "subcontract":
        from app.services.subcontract_settlement_service import void_subcontract_statement

        try:
            return void_subcontract_statement(db, tenant_id, statement_id)
        except Exception as exc:
            from app.services.ap_service import ApError

            if isinstance(exc, ApError):
                raise SettlementError(exc.code, exc.message) from exc
            raise
    if statement_settled_amount(db, statement) > ZERO:
        raise SettlementError("statement_has_payment", "对账单已有收付款，须先作废相关收付款")
    statement.status = AccountStatementStatus.void
    db.commit()
    return statement_out(db, tenant_id, statement.id, with_lines=True)
