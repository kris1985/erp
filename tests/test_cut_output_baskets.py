from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    BasketJourney,
    CutOutput,
    CutOutputContribution,
    CutOutputStatus,
    Employee,
    ExecutionHeader,
    OrderProcess,
    OrderProcessStatus,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    ReusableBasket,
    ReusableBasketStatus,
    SpecExecutionStatus,
    Tenant,
    WorkLog,
)
from app.services.cut_output_service import (
    CutOutputError,
    bind_basket,
    confirm_output,
    create_basket,
    cut_report_quote,
    update_basket,
)
from app.services.salary_service import month_salary


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="永久框测试厂")
    db.add(tenant)
    db.flush()
    segment = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", sort_order=1)
    db.add(segment)
    db.flush()
    process_def = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        type=ProcessType.personal,
        default_price=Decimal("1.20"),
        sort_order=1,
        segment_id=segment.id,
    )
    db.add(process_def)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="CUT-BASKET", is_active=True)
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=process_def.id,
            process_name="裁断",
            unit_price=Decimal("1.20"),
            sort_order=0,
        )
    )
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="PO-CUT-001",
        own_product_id=product.id,
        total_qty=100,
        status=SpecExecutionStatus.cut,
    )
    db.add(header)
    db.flush()
    process = OrderProcess(
        tenant_id=tenant.id,
        header_id=header.id,
        process_id=process_def.id,
        process_name="裁断",
        process_type=ProcessType.personal,
        plan_qty=100,
        completed_qty=0,
        status=OrderProcessStatus.pending,
        segment_id=segment.id,
    )
    a = Employee(tenant_id=tenant.id, name="王强", mobile="13700001001")
    b = Employee(tenant_id=tenant.id, name="李华", mobile="13700001002")
    db.add_all([process, a, b])
    db.commit()
    for code in ("K100", "K101", "K102"):
        create_basket(db, tenant.id, basket_code=code, location="裁断", user_id=a.id)
    yield db, tenant, header, process, a, b
    db.close()


def test_one_cut_output_can_bind_multiple_reusable_baskets(ctx):
    db, tenant, header, process, a, _b = ctx
    draft = bind_basket(
        db,
        tenant.id,
        header_id=header.id,
        basket_code="K100",
        reporter_id=a.id,
        qualified_pairs=100,
        qty=40,
    )
    draft = bind_basket(
        db,
        tenant.id,
        header_id=header.id,
        basket_code="K101",
        reporter_id=a.id,
        qualified_pairs=100,
        qty=40,
    )
    draft = bind_basket(
        db,
        tenant.id,
        header_id=header.id,
        basket_code="K102",
        reporter_id=a.id,
        qualified_pairs=100,
        qty=20,
    )
    assert [row["qty"] for row in draft["baskets"]] == [40, 40, 20]
    assert draft["loaded_pairs"] == 100
    assert len(list(db.scalars(select(BasketJourney)).all())) == 3


def test_cut_report_quote_returns_product_process_unit_price(ctx):
    db, tenant, header, _process, _a, _b = ctx
    quote = cut_report_quote(db, tenant.id, header.id)
    assert quote["process_id"] > 0
    assert quote["process_name"] == "裁断"
    assert quote["unit_price"] == 1.2


def test_component_contributions_do_not_duplicate_cut_progress(ctx):
    db, tenant, header, process, a, b = ctx
    draft = None
    for code in ("K100", "K101", "K102"):
        qty = 40 if code != "K102" else 20
        draft = bind_basket(
            db,
            tenant.id,
            header_id=header.id,
            basket_code=code,
            reporter_id=a.id,
            qualified_pairs=100,
            completion_mode="component",
            qty=qty,
        )
    result = confirm_output(
        db,
        tenant.id,
        draft["id"],
        reporter_id=a.id,
        qualified_pairs=100,
        defect_pairs=0,
        completion_mode="component",
        contributions=[
            {"worker_id": a.id, "credited_pairs": 100, "component_group": "部件A"},
            {"worker_id": b.id, "credited_pairs": 100, "component_group": "部件B"},
        ],
    )
    db.refresh(process)
    assert result["status"] == "confirmed"
    assert process.completed_qty == 100
    assert db.scalar(select(WorkLog.qualified_qty)) == 100
    contributions = list(db.scalars(select(CutOutputContribution)).all())
    assert [row.credited_pairs for row in contributions] == [100, 100]
    assert [row.wage for row in contributions] == [Decimal("120.00"), Decimal("120.00")]
    salary_a = month_salary(db, tenant.id, a.id)
    salary_b = month_salary(db, tenant.id, b.id)
    assert salary_a["piece_qty"] == 100
    assert salary_b["piece_qty"] == 100
    assert salary_a["total_piece_wage"] == 120.0
    assert salary_b["total_piece_wage"] == 120.0
    assert salary_a["details"][0]["component_group"] == "部件A"
    assert all(row.status == ReusableBasketStatus.in_transit for row in db.scalars(select(ReusableBasket)))


def test_busy_basket_cannot_be_bound_to_another_output(ctx):
    db, tenant, header, _process, a, b = ctx
    bind_basket(
        db,
        tenant.id,
        header_id=header.id,
        basket_code="K100",
        reporter_id=a.id,
        qualified_pairs=40,
        qty=40,
    )
    with pytest.raises(CutOutputError, match="已有货物"):
        bind_basket(
            db,
            tenant.id,
            header_id=header.id,
            basket_code="K100",
            reporter_id=b.id,
            qualified_pairs=40,
            qty=40,
        )
    assert db.scalar(select(CutOutput.status).where(CutOutput.reported_by == a.id)) == CutOutputStatus.draft
    basket = db.scalar(select(ReusableBasket).where(ReusableBasket.basket_code == "K100"))
    with pytest.raises(CutOutputError, match="不能手工改变状态"):
        update_basket(db, tenant.id, basket.id, status="maintenance")


def test_idle_basket_can_be_maintained_and_disabled(ctx):
    db, tenant, _header, _process, _a, _b = ctx
    basket = db.scalar(select(ReusableBasket).where(ReusableBasket.basket_code == "K101"))
    result = update_basket(
        db,
        tenant.id,
        basket.id,
        location="维修区",
        status="maintenance",
    )
    assert result["location"] == "维修区"
    assert result["status"] == "maintenance"
    result = update_basket(db, tenant.id, basket.id, is_active=False)
    assert result["status"] == "disabled"
    assert result["is_active"] is False
    result = update_basket(db, tenant.id, basket.id, is_active=True)
    assert result["status"] == "idle"
    assert result["is_active"] is True
