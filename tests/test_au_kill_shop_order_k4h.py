"""干掉生产单 K4-H：不归档。占用认 header；变更日志/合批成员 order_id 可空。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    MergeBatch,
    MergeBatchMember,
    MergeBatchStatus,
    OrderChangeLog,
    OrderMaterialRequirement,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services.execution_service import create_execution
from app.services.material_service import list_shared_occupancy


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="K4H厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4H-A", is_active=True, trace_enabled=True
    )
    session.add(product)
    session.flush()
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-K4H",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=early.id,
                process_name=early.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=late.id,
                process_name=late.name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=mat.id,
                qty=Decimal("1"),
                unit_price=Decimal("2"),
                line_total=Decimal("2"),
                sort_order=0,
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def _header_only(db, *, qty: int = 10, order_no: str = "SO-K4H"):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=qty,
        unit_price=Decimal("80"),
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        color_id=color.id,
        size_id=size.id,
        qty=qty,
        allocated_qty=0,
        produced_qty=qty,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    return tenant, header


def test_occupancy_without_shop_order_uses_header_no(db):
    tenant, header = _header_only(db)
    req = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.header_id == header.id)
    )
    assert req is not None
    assert req.order_id is None
    req.arrived_qty = Decimal("8")
    req.issued_qty = Decimal("2")
    db.commit()

    rows = list_shared_occupancy(db, tenant.id, req.supplier_product_id, req.size_id)
    assert len(rows) == 1
    assert rows[0]["header_id"] == header.id
    assert rows[0]["header_no"] == header.header_no
    assert rows[0]["order_no"] == header.header_no
    assert rows[0]["order_id"] is None
    assert rows[0]["occupied_qty"] == Decimal("6")


def test_change_log_and_merge_member_order_id_nullable(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    insp = inspect(db.get_bind())
    change_col = next(c for c in insp.get_columns("order_change_logs") if c["name"] == "order_id")
    member_col = next(c for c in insp.get_columns("merge_batch_members") if c["name"] == "order_id")
    assert change_col.get("nullable") is True
    assert member_col.get("nullable") is True

    log = OrderChangeLog(
        tenant_id=tenant.id,
        order_id=None,
        version_no=1,
        change_type="qty",
        summary="无壳变更",
        before_json={},
        after_json={"qty": 1},
    )
    db.add(log)
    batch = MergeBatch(
        tenant_id=tenant.id,
        batch_no="MB-K4H-1",
        own_product_id=product.id,
        status=MergeBatchStatus.open,
    )
    db.add(batch)
    db.flush()
    db.add(
        MergeBatchMember(
            tenant_id=tenant.id,
            batch_id=batch.id,
            order_id=None,
        )
    )
    db.commit()
    assert log.id
    assert db.scalar(select(MergeBatchMember).where(MergeBatchMember.batch_id == batch.id)).order_id is None
