"""物料仓当场领料：开单不出库，领料人用手机扫码确认后才扣库存或过账。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    Employee,
    ExecutionHeader,
    OrderMaterialRequirement,
    MaterialCategory,
    OwnProduct,
    Partner,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
)
from app.services.material_service import _shared_qty
from app.services import warehouse_pickup_service as pickup_svc


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _world():
    session = _session()
    tenant = Tenant(name="物料仓")
    session.add(tenant)
    session.flush()
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    session.add(partner)
    session.flush()
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        is_active=True,
    )
    cloth = SupplierProduct(
        tenant_id=tenant.id,
        product_code="CLOTH-1",
        name="面料",
        partner_id=partner.id,
        is_active=True,
    )
    clerk = Employee(tenant_id=tenant.id, name="仓管", username="admin", is_active=True)
    picker = Employee(tenant_id=tenant.id, name="开发员", mobile="13800004001", is_active=True)
    session.add_all([sole, cloth, clerk, picker])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SHOE-1")
    session.add(product)
    session.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="PD-1001",
        own_product_id=product.id,
        total_qty=20,
        status=SpecExecutionStatus.confirmed,
    )
    session.add(header)
    session.flush()
    req = OrderMaterialRequirement(
        tenant_id=tenant.id,
        header_id=header.id,
        supplier_product_id=sole.id,
        qty_per_pair=Decimal("1"),
        required_qty=Decimal("20"),
        arrived_qty=Decimal("0"),
        issued_qty=Decimal("0"),
    )
    session.add(req)
    session.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=sole.id,
            qty=Decimal("12"),
            avg_unit_cost=Decimal("2"),
        )
    )
    session.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=cloth.id,
            qty=Decimal("8"),
            avg_unit_cost=Decimal("1"),
        )
    )
    session.commit()
    return session, tenant, sole, cloth, clerk, picker, header, req


def test_production_header_search_matches_number_or_style():
    session, tenant, _sole, _cloth, _clerk, _picker, header, _req = _world()
    product = session.get(OwnProduct, header.own_product_id)
    done = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="PD-1000",
        own_product_id=product.id,
        total_qty=8,
        status=SpecExecutionStatus.completed,
        schedule_sequence=1,
    )
    first = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="PD-0999",
        own_product_id=product.id,
        total_qty=6,
        status=SpecExecutionStatus.cut,
        schedule_sequence=1,
    )
    session.add_all([done, first])
    session.commit()
    listed = pickup_svc.search_production_headers(session, tenant.id, "")
    assert [row["header_no"] for row in listed["items"]] == ["PD-0999", "PD-1001"]
    assert listed["items"][1]["product_code"] == "SHOE-1"
    by_no = pickup_svc.search_production_headers(session, tenant.id, "1001")
    assert by_no["items"][0]["header_id"] == header.id
    by_style = pickup_svc.search_production_headers(session, tenant.id, "shoe")
    assert [row["header_no"] for row in by_style["items"]] == ["PD-0999", "PD-1001"]
    assert pickup_svc.search_production_headers(session, tenant.id, "没有这张")["items"] == []
    header.status = SpecExecutionStatus.cancelled
    session.commit()
    assert pickup_svc.search_production_headers(session, tenant.id, "PD-1001")["items"] == []


def test_dev_pickup_deducts_pool_only_after_phone_confirm():
    session, tenant, _sole, cloth, clerk, picker, _header, _req = _world()
    created = pickup_svc.create_dev_pickup(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
        notes="打样",
    )
    assert created["status"] == "pending"
    assert created["picker_name"] == ""
    assert created["doc_no"].startswith("DV")
    assert created["sign_token"]
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")

    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["status"] == "signed"
    assert signed["picker_name"] == "开发员"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("6")
    ledger = session.scalar(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.tenant_id == tenant.id,
            SharedMaterialLedger.supplier_product_id == cloth.id,
            SharedMaterialLedger.ledger_type == SharedLedgerType.dev_issue,
        )
    )
    assert ledger is not None
    assert ledger.ref_id == created["id"]
    assert ledger.unit_cost == Decimal("1")
    assert created["doc_no"] in (ledger.note or "")

    with pytest.raises(pickup_svc.WarehousePickupError) as again:
        pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert again.value.code == "already_signed"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("6")


def test_dev_pickup_rejects_short_stock_before_opening_slip():
    session, tenant, _sole, cloth, clerk, _picker, _header, _req = _world()
    with pytest.raises(pickup_svc.WarehousePickupError) as short:
        pickup_svc.create_dev_pickup(
            session,
            tenant.id,
            clerk.id,
            lines=[{"supplier_product_id": cloth.id, "qty": Decimal("9")}],
        )
    assert short.value.code == "insufficient_shared"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")


def _mark_auxiliary(session, tenant, product):
    cat = MaterialCategory(tenant_id=tenant.id, name="包装辅料", is_auxiliary=True)
    session.add(cat)
    session.flush()
    product.category_id = cat.id
    session.commit()


def test_aux_pickup_deducts_pool_like_dev_with_its_own_ledger():
    session, tenant, _sole, cloth, clerk, picker, _header, _req = _world()
    _mark_auxiliary(session, tenant, cloth)
    created = pickup_svc.create_aux_pickup(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("3")}],
        notes="车间辅料",
    )
    assert created["kind"] == "aux"
    assert created["kind_label"] == "生产领辅料耗材"
    assert created["status"] == "pending"
    assert created["doc_no"].startswith("AX")
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")

    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["status"] == "signed"
    assert signed["kind_label"] == "生产领辅料耗材"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("5")
    ledger = session.scalar(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.tenant_id == tenant.id,
            SharedMaterialLedger.supplier_product_id == cloth.id,
            SharedMaterialLedger.ledger_type == SharedLedgerType.aux_issue,
        )
    )
    assert ledger is not None
    assert ledger.ref_id == created["id"]
    assert "生产领辅料耗材" in (ledger.note or "")
    assert session.scalar(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.ledger_type == SharedLedgerType.dev_issue,
        )
    ) is None


def test_production_pickup_posts_only_after_phone_confirm():
    session, tenant, sole, _cloth, clerk, picker, header, req = _world()
    preview = pickup_svc.preview_production(session, tenant.id, "1001")
    assert preview["header_no"] == "PD-1001"
    assert len(preview["lines"]) == 1
    assert preview["lines"][0]["material_name"] == "大底"

    created = pickup_svc.create_production_pickup(
        session,
        tenant.id,
        clerk.id,
        header_no="PD-1001",
        lines=[{"requirement_id": req.id, "qty": Decimal("4")}],
    )
    assert created["status"] == "pending"
    assert not created["stock_doc_id"]
    session.refresh(req)
    assert req.issued_qty == Decimal("0")
    assert _shared_qty(session, tenant.id, sole.id) == Decimal("12")

    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["kind"] == "production"
    assert signed["picker_name"] == "开发员"
    assert signed["stock_doc_id"]
    session.refresh(req)
    session.refresh(header)
    assert req.issued_qty == Decimal("4")
    assert _shared_qty(session, tenant.id, sole.id) == Decimal("8")
    assert header.status == SpecExecutionStatus.cut


def test_api_warehouse_pickup_sign_on_phone():
    session, tenant, _sole, cloth, clerk, picker, _header, _req = _world()
    stranger = Employee(tenant_id=tenant.id, name="外人", mobile="13800004009", is_active=True)
    session.add(stranger)
    session.commit()

    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    try:
        denied = client.post(
            "/api/v1/warehouse-pickups",
            json={"kind": "dev", "lines": [{"supplier_product_id": cloth.id, "qty": 1}]},
            headers={"Authorization": f"Bearer {create_worker_token(stranger)}"},
        )
        assert denied.status_code == 403
        created = client.post(
            "/api/v1/warehouse-pickups",
            json={
                "kind": "dev",
                "origin": "http://127.0.0.1:5173",
                "lines": [{"supplier_product_id": cloth.id, "qty": 1}],
            },
            headers={"Authorization": f"Bearer {create_worker_token(clerk)}"},
        )
        assert created.status_code == 200
        body = created.json()["data"]
        assert body["status"] == "pending"
        assert body["picker_name"] == ""
        assert body["sign_url"] == f"http://127.0.0.1:5173/pickup-sign/{body['sign_token']}"
        assert body["qr_png"].startswith("data:image/png;base64,")
        assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")
        signed = client.post(
            f"/api/v1/warehouse-pickups/by-token/{body['sign_token']}/sign",
            headers={"Authorization": f"Bearer {create_worker_token(picker)}"},
        )
        assert signed.status_code == 200
        assert signed.json()["data"]["picker_name"] == "开发员"
        assert _shared_qty(session, tenant.id, cloth.id) == Decimal("7")
    finally:
        app.dependency_overrides.clear()


def test_dev_return_puts_stock_back_only_after_confirm_and_not_past_issued():
    session, tenant, _sole, cloth, clerk, picker, _header, _req = _world()
    issued = pickup_svc.create_dev_pickup(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("3")}],
    )
    pickup_svc.sign_pickup(session, tenant.id, issued["sign_token"], picker)
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("5")

    with pytest.raises(pickup_svc.WarehousePickupError) as none:
        pickup_svc.create_aux_return(
            session,
            tenant.id,
            clerk.id,
            lines=[{"supplier_product_id": cloth.id, "qty": Decimal("1")}],
        )
    assert none.value.code == "exceed_returnable"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("5")

    created = pickup_svc.create_dev_return(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
    )
    assert created["kind"] == "dev_return"
    assert created["kind_label"] == "开发部退料"
    assert created["doc_no"].startswith("DR")
    assert created["status"] == "pending"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("5")

    with pytest.raises(pickup_svc.WarehousePickupError) as reserved:
        pickup_svc.create_dev_return(
            session,
            tenant.id,
            clerk.id,
            lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
        )
    assert reserved.value.code == "exceed_returnable"

    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["status"] == "signed"
    assert signed["picker_name"] == "开发员"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("7")
    ledger = session.scalar(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.tenant_id == tenant.id,
            SharedMaterialLedger.supplier_product_id == cloth.id,
            SharedMaterialLedger.ledger_type == SharedLedgerType.dev_return,
        )
    )
    assert ledger is not None
    assert ledger.qty_delta == Decimal("2")
    assert ledger.ref_id == created["id"]
    assert "开发部退料" in (ledger.note or "")


def test_aux_pickup_rejects_material_outside_auxiliary_category():
    session, tenant, _sole, cloth, clerk, _picker, _header, _req = _world()
    with pytest.raises(pickup_svc.WarehousePickupError) as blocked:
        pickup_svc.create_aux_pickup(
            session,
            tenant.id,
            clerk.id,
            lines=[{"supplier_product_id": cloth.id, "qty": Decimal("1")}],
        )
    assert blocked.value.code == "not_auxiliary"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")


def test_aux_return_uses_its_own_issued_qty():
    session, tenant, _sole, cloth, clerk, picker, _header, _req = _world()
    _mark_auxiliary(session, tenant, cloth)
    issued = pickup_svc.create_aux_pickup(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
    )
    pickup_svc.sign_pickup(session, tenant.id, issued["sign_token"], picker)
    created = pickup_svc.create_aux_return(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
    )
    assert created["kind_label"] == "生产退辅料"
    assert created["doc_no"].startswith("AR")
    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["kind_label"] == "生产退辅料"
    assert _shared_qty(session, tenant.id, cloth.id) == Decimal("8")
    assert session.scalar(
        select(SharedMaterialLedger).where(
            SharedMaterialLedger.ledger_type == SharedLedgerType.aux_return,
        )
    ) is not None


def test_production_return_reverses_issued_qty_after_confirm():
    session, tenant, sole, _cloth, clerk, picker, _header, req = _world()
    issued = pickup_svc.create_production_pickup(
        session,
        tenant.id,
        clerk.id,
        header_no="PD-1001",
        lines=[{"requirement_id": req.id, "qty": Decimal("4")}],
    )
    pickup_svc.sign_pickup(session, tenant.id, issued["sign_token"], picker)
    session.refresh(req)
    assert req.issued_qty == Decimal("4")

    with pytest.raises(pickup_svc.WarehousePickupError) as too_much:
        pickup_svc.create_production_return(
            session,
            tenant.id,
            clerk.id,
            header_no="PD-1001",
            lines=[{"requirement_id": req.id, "qty": Decimal("5")}],
        )
    assert too_much.value.code == "exceed_returnable"
    session.refresh(req)
    assert req.issued_qty == Decimal("4")
    assert _shared_qty(session, tenant.id, sole.id) == Decimal("8")

    created = pickup_svc.create_production_return(
        session,
        tenant.id,
        clerk.id,
        header_no="PD-1001",
        lines=[{"requirement_id": req.id, "qty": Decimal("1")}],
    )
    assert created["kind"] == "production_return"
    assert created["kind_label"] == "生产退主料"
    assert created["doc_no"].startswith("PR")
    assert created["status"] == "pending"
    session.refresh(req)
    assert req.issued_qty == Decimal("4")

    signed = pickup_svc.sign_pickup(session, tenant.id, created["sign_token"], picker)
    assert signed["status"] == "signed"
    assert signed["stock_doc_id"]
    session.refresh(req)
    assert req.issued_qty == Decimal("3")
    assert _shared_qty(session, tenant.id, sole.id) == Decimal("9")


def test_collapse_production_size_lines_merges_same_material():
    lines = [
        {
            "requirement_id": 1,
            "supplier_product_id": 9,
            "size_id": 2,
            "size_value": "36",
            "material_name": "大底",
            "required_qty": "10",
            "issued_qty": "1",
            "pool_qty": "4",
            "max_issue_qty": "4",
            "returnable_qty": "1",
        },
        {
            "requirement_id": 2,
            "supplier_product_id": 9,
            "size_id": 1,
            "size_value": "35",
            "material_name": "大底",
            "required_qty": "6",
            "issued_qty": "0",
            "pool_qty": "2",
            "max_issue_qty": "2",
            "returnable_qty": "0",
        },
        {
            "requirement_id": 3,
            "supplier_product_id": 8,
            "size_id": None,
            "size_value": "",
            "material_name": "面料",
            "required_qty": "3",
            "issued_qty": "0",
            "pool_qty": "3",
            "max_issue_qty": "3",
            "returnable_qty": "0",
        },
    ]
    merged = pickup_svc.collapse_production_size_lines(lines)
    assert len(merged) == 2
    assert merged[0]["requirement_id"] is None
    assert merged[0]["size_label"] == "35、36"
    assert merged[0]["required_qty"] == "16"
    assert merged[0]["issued_qty"] == "1"
    assert merged[0]["max_issue_qty"] == "6"
    assert merged[0]["returnable_qty"] == "1"
    assert [part["size_value"] for part in merged[0]["parts"]] == ["35", "36"]
    assert [part["issued_qty"] for part in merged[0]["parts"]] == ["0", "1"]
    assert [part["required_qty"] for part in merged[0]["parts"]] == ["6", "10"]
    assert merged[1]["requirement_id"] == 3
    assert "parts" not in merged[1]
    assert "size_label" not in merged[1]


def test_list_pickup_lines_include_color_and_category():
    session, tenant, _sole, cloth, clerk, _picker, _header, _req = _world()
    color = Color(tenant_id=tenant.id, name="黑色", code="BK")
    category = MaterialCategory(tenant_id=tenant.id, name="面料类")
    session.add_all([color, category])
    session.flush()
    cloth.color_id = color.id
    cloth.category_id = category.id
    session.commit()
    pickup_svc.create_dev_pickup(
        session,
        tenant.id,
        clerk.id,
        lines=[{"supplier_product_id": cloth.id, "qty": Decimal("2")}],
    )
    data = pickup_svc.list_pickups(session, tenant.id, page_size=10)
    line = data["items"][0]["lines"][0]
    assert line["material_code"] == "CLOTH-1"
    assert line["material_name"] == "面料"
    assert line["color_name"] == "黑色"
    assert line["category_name"] == "面料类"
    assert line["qty"] == "2"
