"""永久框裁断产出：一次产出、多框装载、多人计件贡献。

裁断生产进度只认 CutOutput.qualified_pairs 一次；永久框每次绑定生成 BasketJourney，
避免复用框码覆盖历史。现场无需生产批次码。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BasketJourney,
    BasketJourneyStatus,
    CutCompletionMode,
    CutOutput,
    CutOutputBasket,
    CutOutputContribution,
    CutOutputStatus,
    Employee,
    ExecutionAllocation,
    ExecutionHeader,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    ProcessDefinition,
    ProcessSegment,
    ReportType,
    ReusableBasket,
    ReusableBasketStatus,
    SalaryModel,
    SalesOrderLine,
    SpecExecutionOrder,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
)
from app.services.order_service import get_labor_unit_price


class CutOutputError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum(value):
    return value.value if hasattr(value, "value") else str(value)


def _new_no(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"


def _get_header(db: Session, tenant_id: int, header_id: int) -> ExecutionHeader:
    row = db.get(ExecutionHeader, header_id)
    if not row or row.tenant_id != tenant_id:
        raise CutOutputError("header_not_found", "生产单不存在")
    if _enum(row.status) in ("cancelled", "completed"):
        raise CutOutputError("header_closed", "已取消或已完成生产单不能裁断报工")
    return row


def _cut_process(db: Session, tenant_id: int, header: ExecutionHeader) -> OrderProcess:
    cut_segment_id = db.scalar(
        select(ProcessSegment.id).where(
            ProcessSegment.tenant_id == tenant_id,
            ProcessSegment.code == "cut",
            ProcessSegment.is_active.is_(True),
        )
    )
    q = select(OrderProcess).where(
        OrderProcess.tenant_id == tenant_id,
        OrderProcess.header_id == header.id,
        OrderProcess.part_id.is_(None),
    )
    if cut_segment_id:
        q = q.where(OrderProcess.segment_id == int(cut_segment_id))
    process = db.scalar(q.order_by(OrderProcess.id).limit(1))
    if not process:
        raise CutOutputError("cut_process_not_found", "该生产单未配置裁断工序")
    return process


def cut_report_quote(
    db: Session,
    tenant_id: int,
    header_id: int,
    *,
    order_process_id: int | None = None,
) -> dict:
    """截断扫码报工计件报价；仅供登录后的现场报工页展示。"""
    header = _get_header(db, tenant_id, header_id)
    process = _cut_process(db, tenant_id, header)
    if order_process_id is not None:
        selected = db.get(OrderProcess, int(order_process_id))
        if (
            not selected
            or selected.tenant_id != tenant_id
            or not (
                selected.header_id == header.id
                or (header.shop_order_id and selected.order_id == int(header.shop_order_id))
            )
            or selected.segment_id != process.segment_id
        ):
            raise CutOutputError("process_not_found", "所选工序不属于当前裁断工序段")
        process = selected
    price = get_labor_unit_price(
        db,
        tenant_id,
        header.own_product_id,
        process.process_id,
    )
    if price is None:
        raise CutOutputError("price_missing", f"工序{process.process_name}未配置计件单价")
    return {
        "process_id": process.process_id,
        "process_name": process.process_name,
        "unit_price": float(price),
    }


def _sales_line_ids(db: Session, tenant_id: int, header_id: int) -> list[int]:
    return list(
        db.scalars(
            select(ExecutionAllocation.sales_order_line_id)
            .join(SpecExecutionOrder, SpecExecutionOrder.id == ExecutionAllocation.execution_id)
            .where(
                ExecutionAllocation.tenant_id == tenant_id,
                SpecExecutionOrder.header_id == header_id,
            )
            .distinct()
        ).all()
    )


def _resolve_sales_line(
    db: Session,
    tenant_id: int,
    header: ExecutionHeader,
    sales_order_line_id: int | None,
) -> SalesOrderLine | None:
    line_ids = _sales_line_ids(db, tenant_id, header.id)
    chosen = sales_order_line_id or header.sales_order_line_id
    if chosen:
        line = db.get(SalesOrderLine, int(chosen))
        if not line or line.tenant_id != tenant_id:
            raise CutOutputError("sales_line_not_found", "销售订单明细不存在")
        if line_ids and line.id not in set(line_ids):
            raise CutOutputError("sales_line_mismatch", "品牌/销售订单明细不属于该生产单")
        return line
    if len(line_ids) == 1:
        return db.get(SalesOrderLine, line_ids[0])
    if len(line_ids) > 1:
        raise CutOutputError("sales_line_required", "合单包含多个品牌或订单明细，请先选择本次框的品牌归属")
    return None


def create_basket(
    db: Session,
    tenant_id: int,
    *,
    basket_code: str,
    location: str | None,
    user_id: int | None,
) -> dict:
    code = (basket_code or "").strip().upper()
    if not code:
        raise CutOutputError("basket_code_required", "请填写框号")
    exists = db.scalar(
        select(ReusableBasket).where(
            ReusableBasket.tenant_id == tenant_id,
            ReusableBasket.basket_code == code,
        )
    )
    if exists:
        raise CutOutputError("basket_exists", f"框号{code}已存在")
    row = ReusableBasket(
        tenant_id=tenant_id,
        basket_code=code,
        location=(location or "").strip() or None,
        status=ReusableBasketStatus.idle,
        created_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return basket_out(db, row)


def basket_out(db: Session, row: ReusableBasket) -> dict:
    journey = db.get(BasketJourney, row.current_journey_id) if row.current_journey_id else None
    header = db.get(ExecutionHeader, journey.header_id) if journey else None
    line = db.get(SalesOrderLine, journey.sales_order_line_id) if journey and journey.sales_order_line_id else None
    return {
        "id": row.id,
        "basket_code": row.basket_code,
        "status": _enum(row.status),
        "location": row.location,
        "is_active": bool(row.is_active),
        "current_journey_id": row.current_journey_id,
        "journey": (
            {
                "id": journey.id,
                "journey_no": journey.journey_no,
                "header_id": journey.header_id,
                "header_no": header.header_no if header else None,
                "sales_order_line_id": journey.sales_order_line_id,
                "brand_name": line.brand_name if line else None,
                "qty": journey.qty,
                "status": _enum(journey.status),
            }
            if journey
            else None
        ),
    }


def get_basket_by_code(db: Session, tenant_id: int, basket_code: str) -> dict:
    row = db.scalar(
        select(ReusableBasket).where(
            ReusableBasket.tenant_id == tenant_id,
            ReusableBasket.basket_code == basket_code.strip().upper(),
        )
    )
    if not row:
        raise CutOutputError("basket_not_found", "框码不存在或尚未建档")
    return basket_out(db, row)


def get_basket(db: Session, tenant_id: int, basket_id: int) -> ReusableBasket:
    row = db.get(ReusableBasket, basket_id)
    if not row or row.tenant_id != tenant_id:
        raise CutOutputError("basket_not_found", "框码不存在")
    return row


def list_baskets(db: Session, tenant_id: int, *, status: str | None = None) -> dict:
    q = select(ReusableBasket).where(ReusableBasket.tenant_id == tenant_id)
    if status and status in ReusableBasketStatus.__members__:
        q = q.where(ReusableBasket.status == ReusableBasketStatus(status))
    rows = list(db.scalars(q.order_by(ReusableBasket.basket_code)).all())
    return {"items": [basket_out(db, row) for row in rows]}


def update_basket(
    db: Session,
    tenant_id: int,
    basket_id: int,
    *,
    location: str | None = None,
    status: str | None = None,
    is_active: bool | None = None,
) -> dict:
    row = get_basket(db, tenant_id, basket_id)
    if row.current_journey_id and (status is not None or is_active is False):
        raise CutOutputError("basket_busy", "框内仍有在制品，不能手工改变状态或停用")
    if status is not None:
        if status not in ReusableBasketStatus.__members__:
            raise CutOutputError("invalid_status", "框状态无效")
        target = ReusableBasketStatus(status)
        if target in (
            ReusableBasketStatus.bound,
            ReusableBasketStatus.in_transit,
            ReusableBasketStatus.on_line,
            ReusableBasketStatus.waiting_qc,
        ):
            raise CutOutputError("managed_status", "装框和流转状态只能由扫码业务自动更新")
        row.status = target
        row.is_active = target != ReusableBasketStatus.disabled
    if is_active is not None:
        row.is_active = bool(is_active)
        if not row.is_active:
            row.status = ReusableBasketStatus.disabled
        elif row.status == ReusableBasketStatus.disabled:
            row.status = ReusableBasketStatus.idle
    if location is not None:
        row.location = location.strip() or None
    db.commit()
    db.refresh(row)
    return basket_out(db, row)


def _draft_out(db: Session, output: CutOutput) -> dict:
    basket_rows = list(
        db.scalars(
            select(CutOutputBasket)
            .where(CutOutputBasket.cut_output_id == output.id)
            .order_by(CutOutputBasket.sequence, CutOutputBasket.id)
        ).all()
    )
    baskets = []
    for link in basket_rows:
        journey = db.get(BasketJourney, link.basket_journey_id)
        basket = db.get(ReusableBasket, journey.basket_id) if journey else None
        baskets.append(
            {
                "id": link.id,
                "basket_journey_id": link.basket_journey_id,
                "basket_id": basket.id if basket else None,
                "basket_code": basket.basket_code if basket else None,
                "qty": link.qty,
                "sequence": link.sequence,
            }
        )
    contributions = list(
        db.scalars(
            select(CutOutputContribution).where(CutOutputContribution.cut_output_id == output.id)
        ).all()
    )
    worker_map = {
        worker.id: worker.name
        for worker in db.scalars(
            select(Employee).where(Employee.id.in_([x.worker_id for x in contributions] or [0]))
        ).all()
    }
    header = db.get(ExecutionHeader, output.header_id)
    line = db.get(SalesOrderLine, output.sales_order_line_id) if output.sales_order_line_id else None
    return {
        "id": output.id,
        "output_no": output.output_no,
        "header_id": output.header_id,
        "header_no": header.header_no if header else None,
        "sales_order_line_id": output.sales_order_line_id,
        "brand_name": line.brand_name if line else None,
        "qualified_pairs": output.qualified_pairs,
        "defect_pairs": output.defect_pairs,
        "completion_mode": _enum(output.completion_mode),
        "status": _enum(output.status),
        "reported_by": output.reported_by,
        "loaded_pairs": sum(int(x.qty or 0) for x in basket_rows),
        "remaining_pairs": max(0, int(output.qualified_pairs or 0) - sum(int(x.qty or 0) for x in basket_rows)),
        "baskets": baskets,
        "contributions": [
            {
                "id": row.id,
                "worker_id": row.worker_id,
                "worker_name": worker_map.get(row.worker_id),
                "process_id": row.process_id,
                "material_requirement_id": row.material_requirement_id,
                "component_group": row.component_group,
                "credited_pairs": row.credited_pairs,
                "unit_price": float(row.unit_price or 0),
                "wage": float(row.wage or 0),
            }
            for row in contributions
        ],
        "created_at": output.created_at.isoformat() if output.created_at else None,
        "confirmed_at": output.confirmed_at.isoformat() if output.confirmed_at else None,
    }


def _active_draft(
    db: Session, tenant_id: int, *, header_id: int, reporter_id: int, sales_order_line_id: int | None
) -> CutOutput | None:
    q = select(CutOutput).where(
        CutOutput.tenant_id == tenant_id,
        CutOutput.header_id == header_id,
        CutOutput.reported_by == reporter_id,
        CutOutput.status == CutOutputStatus.draft,
    )
    if sales_order_line_id is None:
        q = q.where(CutOutput.sales_order_line_id.is_(None))
    else:
        q = q.where(CutOutput.sales_order_line_id == sales_order_line_id)
    return db.scalar(q.order_by(CutOutput.id.desc()).limit(1))


def bind_basket(
    db: Session,
    tenant_id: int,
    *,
    header_id: int,
    basket_code: str,
    reporter_id: int,
    qualified_pairs: int,
    defect_pairs: int = 0,
    completion_mode: str = "complete",
    sales_order_line_id: int | None = None,
    qty: int,
) -> dict:
    if qualified_pairs <= 0 or defect_pairs < 0:
        raise CutOutputError("invalid_qty", "请填写有效的合格数量")
    if completion_mode not in CutCompletionMode.__members__:
        raise CutOutputError("invalid_mode", "完成方式无效")
    header = _get_header(db, tenant_id, header_id)
    process = _cut_process(db, tenant_id, header)
    line = _resolve_sales_line(db, tenant_id, header, sales_order_line_id)
    basket = db.scalar(
        select(ReusableBasket).where(
            ReusableBasket.tenant_id == tenant_id,
            ReusableBasket.basket_code == basket_code.strip().upper(),
        )
    )
    if not basket or not basket.is_active:
        raise CutOutputError("basket_not_found", "框码不存在、未启用或尚未建档")

    output = _active_draft(
        db,
        tenant_id,
        header_id=header.id,
        reporter_id=reporter_id,
        sales_order_line_id=line.id if line else None,
    )
    if basket.current_journey_id:
        journey = db.get(BasketJourney, basket.current_journey_id)
        existing = db.scalar(
            select(CutOutputBasket).where(CutOutputBasket.basket_journey_id == journey.id)
        ) if journey else None
        if output and existing and existing.cut_output_id == output.id:
            # 同一草稿内重复扫同一框：按本次数量改写，避免静默沿用旧装框合计。
            other = int(
                db.scalar(
                    select(func.coalesce(func.sum(CutOutputBasket.qty), 0)).where(
                        CutOutputBasket.cut_output_id == output.id,
                        CutOutputBasket.id != existing.id,
                    )
                )
                or 0
            )
            assign_qty = int(qty)
            if assign_qty <= 0:
                raise CutOutputError("invalid_basket_qty", "装框数量无效")
            if other + assign_qty > int(qualified_pairs):
                raise CutOutputError(
                    "basket_over_output",
                    f"本次最多还可装{max(0, int(qualified_pairs) - other)}双",
                )
            existing.qty = assign_qty
            if journey:
                journey.qty = assign_qty
            output.qualified_pairs = int(qualified_pairs)
            output.defect_pairs = int(defect_pairs)
            output.completion_mode = CutCompletionMode(completion_mode)
            db.commit()
            db.refresh(output)
            return _draft_out(db, output)
        raise CutOutputError("basket_busy", f"{basket.basket_code}当前已有货物，不能重复绑定")
    if _enum(basket.status) != ReusableBasketStatus.idle.value:
        raise CutOutputError("basket_busy", f"{basket.basket_code}当前状态不是空闲")

    if output is None:
        output = CutOutput(
            tenant_id=tenant_id,
            output_no=_new_no("CO"),
            header_id=header.id,
            order_id=header.shop_order_id,
            sales_order_line_id=line.id if line else None,
            brand_id=line.brand_id if line else None,
            process_id=process.process_id,
            qualified_pairs=int(qualified_pairs),
            defect_pairs=int(defect_pairs),
            completion_mode=CutCompletionMode(completion_mode),
            status=CutOutputStatus.draft,
            reported_by=reporter_id,
        )
        db.add(output)
        db.flush()
    else:
        output.qualified_pairs = int(qualified_pairs)
        output.defect_pairs = int(defect_pairs)
        output.completion_mode = CutCompletionMode(completion_mode)

    loaded = int(
        db.scalar(
            select(func.coalesce(func.sum(CutOutputBasket.qty), 0)).where(
                CutOutputBasket.cut_output_id == output.id
            )
        )
        or 0
    )
    remaining = max(0, int(qualified_pairs) - loaded)
    assign_qty = int(qty)
    if remaining <= 0:
        raise CutOutputError("output_full", "本次合格数量已经全部装框")
    if assign_qty <= 0:
        raise CutOutputError("invalid_basket_qty", "装框数量无效")
    if assign_qty > remaining:
        raise CutOutputError("basket_over_output", f"本次最多还可装{remaining}双")

    journey = BasketJourney(
        tenant_id=tenant_id,
        journey_no=_new_no("BJ"),
        basket_id=basket.id,
        header_id=header.id,
        order_id=header.shop_order_id,
        sales_order_line_id=line.id if line else None,
        brand_id=line.brand_id if line else None,
        current_segment_id=process.segment_id,
        qty=assign_qty,
        status=BasketJourneyStatus.assembling,
        bound_by=reporter_id,
    )
    db.add(journey)
    db.flush()
    sequence = int(
        db.scalar(select(func.count()).select_from(CutOutputBasket).where(CutOutputBasket.cut_output_id == output.id))
        or 0
    ) + 1
    db.add(
        CutOutputBasket(
            tenant_id=tenant_id,
            cut_output_id=output.id,
            basket_journey_id=journey.id,
            qty=assign_qty,
            sequence=sequence,
        )
    )
    basket.current_journey_id = journey.id
    basket.status = ReusableBasketStatus.bound
    db.commit()
    db.refresh(output)
    return _draft_out(db, output)


def update_basket_qty(
    db: Session, tenant_id: int, output_id: int, link_id: int, *, qty: int, reporter_id: int
) -> dict:
    output = db.get(CutOutput, output_id)
    if not output or output.tenant_id != tenant_id:
        raise CutOutputError("output_not_found", "裁断产出单不存在")
    if output.status != CutOutputStatus.draft or output.reported_by != reporter_id:
        raise CutOutputError("output_locked", "只能修改自己的草稿产出单")
    link = db.get(CutOutputBasket, link_id)
    if not link or link.cut_output_id != output.id or qty <= 0:
        raise CutOutputError("invalid_basket_qty", "装框明细或数量无效")
    journey = db.get(BasketJourney, link.basket_journey_id)
    other = int(
        db.scalar(
            select(func.coalesce(func.sum(CutOutputBasket.qty), 0)).where(
                CutOutputBasket.cut_output_id == output.id,
                CutOutputBasket.id != link.id,
            )
        )
        or 0
    )
    if other + qty > output.qualified_pairs:
        raise CutOutputError("basket_over_output", "装框合计不能超过本次合格数量")
    link.qty = int(qty)
    if journey:
        journey.qty = int(qty)
    db.commit()
    return _draft_out(db, output)


def remove_basket(
    db: Session, tenant_id: int, output_id: int, link_id: int, *, reporter_id: int
) -> dict:
    output = db.get(CutOutput, output_id)
    if not output or output.tenant_id != tenant_id:
        raise CutOutputError("output_not_found", "裁断产出单不存在")
    if output.status != CutOutputStatus.draft or output.reported_by != reporter_id:
        raise CutOutputError("output_locked", "只能修改自己的草稿产出单")
    link = db.get(CutOutputBasket, link_id)
    if not link or link.cut_output_id != output.id:
        raise CutOutputError("basket_link_not_found", "装框明细不存在")
    journey = db.get(BasketJourney, link.basket_journey_id)
    basket = db.get(ReusableBasket, journey.basket_id) if journey else None
    db.delete(link)
    if journey:
        journey.status = BasketJourneyStatus.void
        journey.released_by = reporter_id
        journey.released_at = datetime.now(timezone.utc)
    if basket:
        basket.current_journey_id = None
        basket.status = ReusableBasketStatus.idle
    db.commit()
    return _draft_out(db, output)


def confirm_output(
    db: Session,
    tenant_id: int,
    output_id: int,
    *,
    reporter_id: int,
    qualified_pairs: int,
    defect_pairs: int,
    completion_mode: str,
    contributions: list[dict],
) -> dict:
    output = db.get(CutOutput, output_id)
    if not output or output.tenant_id != tenant_id:
        raise CutOutputError("output_not_found", "裁断产出单不存在")
    if output.status != CutOutputStatus.draft or output.reported_by != reporter_id:
        raise CutOutputError("output_locked", "裁断产出单已确认或不属于当前报工人")
    if qualified_pairs <= 0 or defect_pairs < 0:
        raise CutOutputError("invalid_qty", "请填写有效的合格数量")
    if completion_mode not in CutCompletionMode.__members__:
        raise CutOutputError("invalid_mode", "完成方式无效")
    mode = CutCompletionMode(completion_mode)
    loaded = int(
        db.scalar(
            select(func.coalesce(func.sum(CutOutputBasket.qty), 0)).where(
                CutOutputBasket.cut_output_id == output.id
            )
        )
        or 0
    )
    if loaded != int(qualified_pairs):
        raise CutOutputError("basket_qty_mismatch", f"装框合计{loaded}双，必须等于合格{qualified_pairs}双")
    if not contributions:
        contributions = [{"worker_id": reporter_id, "credited_pairs": qualified_pairs}]
    parsed: list[dict] = []
    for item in contributions:
        wid = int(item.get("worker_id") or 0)
        pairs = int(item.get("credited_pairs") or 0)
        worker = db.get(Employee, wid)
        if not worker or worker.tenant_id != tenant_id or not worker.is_active:
            raise CutOutputError("worker_not_found", f"参与人员不存在或未启用：{wid}")
        salary_model = _enum(worker.salary_model)
        if salary_model == SalaryModel.fixed.value:
            raise CutOutputError("fixed_salary", f"{worker.name}为包月员工，不参与裁断计件")
        if pairs <= 0:
            raise CutOutputError("invalid_contribution", f"{worker.name}的计件双数必须大于0")
        req_id = int(item.get("material_requirement_id") or 0) or None
        if req_id:
            req = db.get(OrderMaterialRequirement, req_id)
            if not req or req.tenant_id != tenant_id or int(req.header_id or 0) != output.header_id:
                raise CutOutputError("material_mismatch", "参与人员选择的物料不属于当前生产单")
        process_id = int(item.get("process_id") or output.process_id)
        price = get_labor_unit_price(db, tenant_id, _get_header(db, tenant_id, output.header_id).own_product_id, process_id)
        if price is None:
            raise CutOutputError("price_missing", f"工序{process_id}未配置计件单价")
        parsed.append(
            {
                "worker_id": wid,
                "credited_pairs": pairs,
                "material_requirement_id": req_id,
                "component_group": (item.get("component_group") or "").strip() or None,
                "process_id": process_id,
                "unit_price": Decimal(price),
            }
        )
    if mode in (CutCompletionMode.complete, CutCompletionMode.quantity_split):
        if sum(row["credited_pairs"] for row in parsed) != qualified_pairs:
            raise CutOutputError("contribution_mismatch", "一人完成或按数量分工时，人员双数合计必须等于合格双数")
    elif any(row["credited_pairs"] < qualified_pairs for row in parsed):
        raise CutOutputError("component_incomplete", "按不同部件分工时，每位人员本次可配双数不能少于成筐合格双数")

    header = _get_header(db, tenant_id, output.header_id)
    process = _cut_process(db, tenant_id, header)
    if int(process.completed_qty or 0) + qualified_pairs > int(process.plan_qty or 0):
        remain = max(0, int(process.plan_qty or 0) - int(process.completed_qty or 0))
        raise CutOutputError("over_plan", f"裁断工序本次最多还可报{remain}双")

    output.qualified_pairs = int(qualified_pairs)
    output.defect_pairs = int(defect_pairs)
    output.completion_mode = mode
    for old in db.scalars(
        select(CutOutputContribution).where(CutOutputContribution.cut_output_id == output.id)
    ).all():
        db.delete(old)
    for row in parsed:
        wage = (row["unit_price"] * Decimal(row["credited_pairs"])).quantize(Decimal("0.01"))
        db.add(
            CutOutputContribution(
                tenant_id=tenant_id,
                cut_output_id=output.id,
                worker_id=row["worker_id"],
                process_id=row["process_id"],
                material_requirement_id=row["material_requirement_id"],
                component_group=row["component_group"],
                credited_pairs=row["credited_pairs"],
                unit_price=row["unit_price"],
                wage=wage,
            )
        )

    # 一条零计价产出流水负责生产统计；个人计件由 contribution 明细承担，避免多人重复推进进度。
    log = WorkLog(
        tenant_id=tenant_id,
        worker_id=reporter_id,
        order_id=header.shop_order_id,
        header_id=header.id,
        order_process_id=process.id,
        own_product_id=header.own_product_id,
        style_id=header.own_product_id,
        process_id=process.process_id,
        color_id=header.color_id,
        size_id=None,
        report_type=ReportType.normal,
        qualified_qty=qualified_pairs,
        defect_qty=defect_pairs,
        rework_qty=0,
        unit_price=Decimal("0"),
        original_text=f"裁断成筐报工 {output.output_no}",
        source=WorkLogSource.cut_basket,
        segment_id=process.segment_id,
        status=WorkLogStatus.valid,
    )
    db.add(log)
    db.flush()
    output.output_work_log_id = log.id
    output.status = CutOutputStatus.confirmed
    output.confirmed_at = datetime.now(timezone.utc)
    process.completed_qty = int(process.completed_qty or 0) + qualified_pairs
    process.defect_qty = Decimal(process.defect_qty or 0) + Decimal(defect_pairs)
    if process.actual_start is None:
        process.actual_start = datetime.now(timezone.utc)
    process.status = (
        OrderProcessStatus.completed
        if process.completed_qty >= process.plan_qty
        else OrderProcessStatus.in_progress
    )
    if process.status == OrderProcessStatus.completed:
        process.actual_end = datetime.now(timezone.utc)
    if header.shop_order_id:
        order = db.get(Order, header.shop_order_id)
        if order and order.status == OrderStatus.confirmed:
            order.status = OrderStatus.in_progress
    for link in db.scalars(
        select(CutOutputBasket).where(CutOutputBasket.cut_output_id == output.id)
    ).all():
        journey = db.get(BasketJourney, link.basket_journey_id)
        if journey:
            journey.status = BasketJourneyStatus.ready
            journey.qty = link.qty
            basket = db.get(ReusableBasket, journey.basket_id)
            if basket:
                basket.status = ReusableBasketStatus.in_transit
    db.commit()
    db.refresh(output)
    return _draft_out(db, output)


def cancel_output(db: Session, tenant_id: int, output_id: int, *, reporter_id: int) -> dict:
    output = db.get(CutOutput, output_id)
    if not output or output.tenant_id != tenant_id:
        raise CutOutputError("output_not_found", "裁断产出单不存在")
    if output.status != CutOutputStatus.draft or output.reported_by != reporter_id:
        raise CutOutputError("output_locked", "只能取消自己的草稿产出单")
    for link in db.scalars(
        select(CutOutputBasket).where(CutOutputBasket.cut_output_id == output.id)
    ).all():
        journey = db.get(BasketJourney, link.basket_journey_id)
        basket = db.get(ReusableBasket, journey.basket_id) if journey else None
        if journey:
            journey.status = BasketJourneyStatus.void
            journey.released_by = reporter_id
            journey.released_at = datetime.now(timezone.utc)
        if basket:
            basket.current_journey_id = None
            basket.status = ReusableBasketStatus.idle
    output.status = CutOutputStatus.void
    db.commit()
    return _draft_out(db, output)


def get_output(db: Session, tenant_id: int, output_id: int) -> dict:
    output = db.get(CutOutput, output_id)
    if not output or output.tenant_id != tenant_id:
        raise CutOutputError("output_not_found", "裁断产出单不存在")
    return _draft_out(db, output)


def list_outputs(db: Session, tenant_id: int, *, header_id: int) -> dict:
    rows = list(
        db.scalars(
            select(CutOutput)
            .where(CutOutput.tenant_id == tenant_id, CutOutput.header_id == header_id)
            .order_by(CutOutput.id.desc())
        ).all()
    )
    return {"items": [_draft_out(db, row) for row in rows]}
