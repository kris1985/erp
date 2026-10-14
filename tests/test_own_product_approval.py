"""产品开发审批：无审批权限的修改不进在制单；通过后同步物料。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    ExecutionHeader,
    OrderMaterialRequirement,
    OwnProductMaterial,
    Partner,
    ProcessSegment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    Employee,
)
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _login(client: TestClient, username: str, password: str) -> dict:
    token = client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": password},
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_approval_gates_material_sync_to_open_headers():
    db = _session()
    tenant = Tenant(name="审批厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    editor = Employee(
        tenant_id=tenant.id,
        username="editor",
        name="开发",
        password_hash=hash_password("editor123"),
        is_active=True,
    )
    db.add_all([admin, editor])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    rbac_service.set_employee_roles(db, editor, ["manager"])
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add_all([black, partner])
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="牛皮",
        partner_id=partner.id,
        unit_price=Decimal("10"),
    )
    db.add(leather)
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        admin_headers = _login(client, "admin", "admin123")
        created = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SHOE-1",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [black.id],
            },
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        product = created.json()["data"]
        assert product["approval_status"] == "approved"
        product_id = product["id"]

        db.add(
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product_id,
                supplier_product_id=leather.id,
                qty=Decimal("1"),
                unit_price=Decimal("10"),
                line_total=Decimal("10"),
            )
        )
        header = ExecutionHeader(
            tenant_id=tenant.id,
            header_no="XE-APPROVE-1",
            own_product_id=product_id,
            color_id=black.id,
            total_qty=10,
            status=SpecExecutionStatus.in_progress,
        )
        db.add(header)
        db.flush()
        requirement = OrderMaterialRequirement(
            tenant_id=tenant.id,
            header_id=header.id,
            supplier_product_id=leather.id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("10"),
            unit_price=Decimal("10"),
        )
        db.add(requirement)
        db.commit()

        editor_headers = _login(client, "editor", "editor123")
        saved = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"fabric": "牛皮"},
            headers=editor_headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["approval_status"] == "pending"
        db.refresh(requirement)
        assert Decimal(requirement.required_qty) == Decimal("10")

        material = db.scalar(
            select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product_id)
        )
        material.qty = Decimal("2")
        db.commit()

        blocked = client.post(
            f"/api/v1/own-products/{product_id}/approve",
            headers=editor_headers,
        )
        assert blocked.status_code == 403

        approved = client.post(
            f"/api/v1/own-products/{product_id}/approve",
            headers=admin_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["approval_status"] == "approved"
        db.refresh(requirement)
        assert Decimal(requirement.qty_per_pair) == Decimal("2")
        assert Decimal(requirement.required_qty) == Decimal("20")
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_material_save_syncs_open_header_and_drops_removed_material():
    db = _session()
    tenant = Tenant(name="同步厂")
    db.add(tenant)
    db.flush()
    editor = Employee(
        tenant_id=tenant.id,
        username="editor",
        name="开发",
        password_hash=hash_password("editor123"),
        is_active=True,
    )
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add_all([admin, editor])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    rbac_service.set_employee_roles(db, editor, ["manager"])
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add_all([black, partner])
    db.flush()
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="牛皮",
        partner_id=partner.id,
        unit_price=Decimal("10"),
    )
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("8"),
    )
    db.add_all([leather, sole])
    db.flush()
    segment = ProcessSegment(tenant_id=tenant.id, name="裁断", code="CUT", sort_order=1)
    db.add(segment)
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        admin_headers = _login(client, "admin", "admin123")
        created = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SHOE-2",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [black.id],
            },
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]
        header = ExecutionHeader(
            tenant_id=tenant.id,
            header_no="XE-SYNC-1",
            own_product_id=product_id,
            color_id=black.id,
            total_qty=10,
            status=SpecExecutionStatus.in_progress,
        )
        db.add(header)
        db.flush()
        leather_req = OrderMaterialRequirement(
            tenant_id=tenant.id,
            header_id=header.id,
            supplier_product_id=leather.id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("10"),
            unit_price=Decimal("10"),
        )
        sole_req = OrderMaterialRequirement(
            tenant_id=tenant.id,
            header_id=header.id,
            supplier_product_id=sole.id,
            qty_per_pair=Decimal("1"),
            required_qty=Decimal("10"),
            unit_price=Decimal("8"),
        )
        db.add_all([leather_req, sole_req])
        db.flush()
        po = PurchaseOrder(
            tenant_id=tenant.id,
            po_no="PO-SYNC",
            partner_id=partner.id,
            status=PurchaseOrderStatus.draft,
        )
        db.add(po)
        db.flush()
        po_line = PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=sole.id,
            order_material_requirement_id=sole_req.id,
            qty=Decimal("10"),
            unit_price=Decimal("8"),
        )
        db.add(po_line)
        db.commit()

        saved = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={
                "materials": [
                    {
                        "supplier_product_id": leather.id,
                        "qty": "2",
                        "consume_segment_id": segment.id,
                    }
                ]
            },
            headers=_login(client, "editor", "editor123"),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["approval_status"] == "pending"
        db.expire_all()
        left = list(
            db.scalars(
                select(OrderMaterialRequirement).where(
                    OrderMaterialRequirement.header_id == header.id
                )
            ).all()
        )
        assert [row.supplier_product_id for row in left] == [leather.id]
        assert Decimal(left[0].qty_per_pair) == Decimal("2")
        assert Decimal(left[0].required_qty) == Decimal("20")
        db.refresh(po_line)
        assert po_line.order_material_requirement_id is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
