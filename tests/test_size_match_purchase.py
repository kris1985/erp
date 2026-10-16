"""订单楦底跟配套：大底按配套码生成采购需求，其它物料仍按客户码。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    ExecutionHeader,
    MaterialCategory,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    SalesOrder,
    SalesOrderLine,
    SpecExecutionOrder,
    SpecExecutionStatus,
    SupplierProduct,
    Size,
    Tenant,
)
from app.services import material_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_outsole_requirement_uses_matched_size(db):
    tenant = Tenant(name="配套厂")
    db.add(tenant)
    db.flush()
    supplier = Partner(tenant_id=tenant.id, name="底厂", is_supplier=True, is_active=True)
    outsole_cat = MaterialCategory(tenant_id=tenant.id, name="大底", suggest_usage_by_size=True)
    leather_cat = MaterialCategory(tenant_id=tenant.id, name="皮料")
    product = OwnProduct(tenant_id=tenant.id, product_code="SM-1")
    size36 = Size(tenant_id=tenant.id, size_value="36", sort_order=36)
    size37 = Size(tenant_id=tenant.id, size_value="37", sort_order=37)
    db.add_all([supplier, outsole_cat, leather_cat, product, size36, size37])
    db.flush()
    sole = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="SOLE",
        name="大底",
        category_id=outsole_cat.id,
    )
    leather = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="LEA",
        name="面皮",
        category_id=leather_cat.id,
    )
    db.add_all([sole, leather])
    db.flush()
    db.add_all(
        [
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=sole.id,
                qty=Decimal("1"),
                usage_by_size=True,
                sort_order=1,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=leather.id,
                qty=Decimal("1"),
                usage_by_size=True,
                sort_order=2,
            ),
        ]
    )
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-SM",
        customer_name="客户",
        ordered_at=date(2026, 10, 15),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        total_qty=30,
        size_matches={"outsole": {str(size36.id): size37.id}},
    )
    db.add(line)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="EH-SM",
        own_product_id=product.id,
        sales_order_line_id=line.id,
        total_qty=30,
        status=SpecExecutionStatus.confirmed,
    )
    db.add(header)
    db.flush()
    db.add_all(
        [
            SpecExecutionOrder(
                tenant_id=tenant.id,
                execution_no="EX-36",
                header_id=header.id,
                own_product_id=product.id,
                size_id=size36.id,
                total_qty=10,
                status=SpecExecutionStatus.confirmed,
            ),
            SpecExecutionOrder(
                tenant_id=tenant.id,
                execution_no="EX-37",
                header_id=header.id,
                own_product_id=product.id,
                size_id=size37.id,
                total_qty=20,
                status=SpecExecutionStatus.confirmed,
            ),
        ]
    )
    db.commit()

    rows = material_service.refresh_from_bom_for_header(db, tenant.id, header, keep_progress=False)
    sole_rows = [row for row in rows if row.supplier_product_id == sole.id]
    leather_rows = [row for row in rows if row.supplier_product_id == leather.id]
    assert [(row.size_id, int(row.required_qty)) for row in sole_rows] == [(size37.id, 30)]
    assert sorted((row.size_id, int(row.required_qty)) for row in leather_rows) == [
        (size36.id, 10),
        (size37.id, 20),
    ]
