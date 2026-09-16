"""模具楦头按分类跳过领退料、齐套缺料与采购。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Employee,
    ExecutionHeader,
    MaterialCategory,
    OrderMaterialRequirement,
    OwnProduct,
    Partner,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
)
from app.services import inventory_settings, material_service, stock_doc_service
from app.services.material_service import MaterialError, kit_row_dict


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="工装测试厂")
    db.add(tenant)
    db.flush()
    user = Employee(tenant_id=tenant.id, name="仓管", mobile="13900001111", is_active=True)
    db.add(user)
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True)
    cat_tool = MaterialCategory(tenant_id=tenant.id, name="模具楦头", sort_order=1)
    cat_leather = MaterialCategory(tenant_id=tenant.id, name="皮料", sort_order=2)
    product = OwnProduct(tenant_id=tenant.id, product_code="GC-TOOL")
    db.add_all([supplier, cat_tool, cat_leather, product])
    db.flush()
    last = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="LAST-01",
        name="36楦",
        category_id=cat_tool.id,
    )
    leather = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="LEA-01",
        name="牛皮",
        category_id=cat_leather.id,
    )
    db.add_all([last, leather])
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-TOOL-1",
        own_product_id=product.id,
        total_qty=100,
        completed_qty=0,
        status=SpecExecutionStatus.confirmed,
        delivery_date=date(2026, 10, 1),
    )
    db.add(header)
    db.flush()
    req_last = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        supplier_product_id=last.id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("2"),
        arrived_qty=Decimal("0"),
        issued_qty=Decimal("0"),
        is_customer_supplied=False,
        sort_order=0,
    )
    req_leather = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        supplier_product_id=leather.id,
        qty_per_pair=Decimal("0.2"),
        required_qty=Decimal("20"),
        arrived_qty=Decimal("0"),
        issued_qty=Decimal("0"),
        is_customer_supplied=False,
        sort_order=1,
    )
    db.add_all([req_last, req_leather])
    db.commit()
    try:
        yield db, tenant, header, req_last, req_leather, last, leather
    finally:
        db.close()


def test_tooling_kit_row_always_ok(ctx):
    db, tenant, _header, req_last, req_leather, _last, _leather = ctx
    last_row = kit_row_dict(db, tenant.id, req_last, include_shared=False)
    assert last_row["is_tooling"] is True
    assert last_row["kit_ok"] is True
    assert last_row["shortage_qty"] == 0
    assert last_row["to_buy_qty"] == 0
    leather_row = kit_row_dict(db, tenant.id, req_leather, include_shared=False)
    assert leather_row["is_tooling"] is False
    assert leather_row["kit_ok"] is False
    assert leather_row["shortage_qty"] == Decimal("20")


def test_tooling_skipped_in_issue_gate_and_stock_lines(ctx):
    db, tenant, header, req_last, req_leather, _last, _leather = ctx
    inventory_settings.save_inventory_patch(db, tenant.id, {"issue_required": True})

    # 仅工装：不挡报工
    req_leather.required_qty = Decimal("0")
    db.commit()
    stock_doc_service.assert_issue_gate_for_header(db, tenant.id, header.id)
    stock_doc_service.assert_posted_issue_for_header(db, tenant.id, header.id)

    # 有皮料：仍要求领料
    req_leather.required_qty = Decimal("20")
    db.commit()
    with pytest.raises(MaterialError) as blocked:
        stock_doc_service.assert_issue_gate_for_header(db, tenant.id, header.id)
    assert blocked.value.code == "issue_required"

    lines = stock_doc_service.list_issue_candidates(
        db, tenant.id, header_id=header.id
    )["lines"]
    codes = {row["supplier_product_code"] for row in lines}
    assert "LAST-01" not in codes
    assert "LEA-01" in codes

    with pytest.raises(MaterialError) as tooling_err:
        stock_doc_service.submit_stock_doc(
            db,
            tenant.id,
            doc_type="issue",
            header_id=header.id,
            lines=[{"requirement_id": req_last.id, "qty": 1}],
        )
    assert tooling_err.value.code == "tooling"
