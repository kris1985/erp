"""物料色卡审批：未通过不能用，通过后锁定，审批人仍可改。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Employee, EmployeeRoleAssignment, Partner, SupplierProduct, Tenant
from app.services.purchase_service import PurchaseError, create_catalog_purchase_drafts


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(session):
    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _setup():
    session = _session()
    tenant = Tenant(name="色卡厂")
    session.add(tenant)
    session.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    writer = Employee(tenant_id=tenant.id, name="仓管", username="wh", is_active=True)
    approver = Employee(tenant_id=tenant.id, name="管理员", username="admin", is_active=True)
    session.add_all([partner, writer, approver])
    session.flush()
    session.add(
        EmployeeRoleAssignment(tenant_id=tenant.id, employee_id=writer.id, role_code="warehouse")
    )
    session.commit()
    return session, partner, writer, approver


def test_catalog_approval_locks_edit_and_delete():
    session, partner, writer, approver = _setup()
    client = _client(session)
    writer_headers = {"Authorization": f"Bearer {create_access_token(writer)}"}
    approver_headers = {"Authorization": f"Bearer {create_access_token(approver)}"}
    try:
        created = client.post(
            "/api/v1/supplier-products",
            headers=writer_headers,
            json={"product_code": "ML-P", "name": "待审皮", "partner_id": partner.id},
        )
        assert created.status_code == 200, created.text
        product = created.json()["data"]
        assert product["approval_status"] == "pending"
        product_id = product["id"]

        renamed = client.patch(
            f"/api/v1/supplier-products/{product_id}",
            headers=writer_headers,
            json={"name": "待审皮2"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["data"]["approval_status"] == "pending"

        denied = client.post(
            f"/api/v1/supplier-products/{product_id}/approve",
            headers=writer_headers,
        )
        assert denied.status_code == 403

        approved = client.post(
            f"/api/v1/supplier-products/{product_id}/approve",
            headers=approver_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["approval_status"] == "approved"

        blocked = client.patch(
            f"/api/v1/supplier-products/{product_id}",
            headers=writer_headers,
            json={"name": "不能改"},
        )
        assert blocked.status_code == 400
        assert "不能修改" in blocked.json()["detail"]

        blocked_delete = client.delete(
            f"/api/v1/supplier-products/{product_id}",
            headers=writer_headers,
        )
        assert blocked_delete.status_code == 400
        assert "不能删除" in blocked_delete.json()["detail"]

        edited = client.patch(
            f"/api/v1/supplier-products/{product_id}",
            headers=approver_headers,
            json={"name": "审批人改过"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["name"] == "审批人改过"
        assert edited.json()["data"]["approval_status"] == "approved"

        approver_delete = client.delete(
            f"/api/v1/supplier-products/{product_id}",
            headers=approver_headers,
        )
        assert approver_delete.status_code == 400

        pending = client.post(
            "/api/v1/supplier-products",
            headers=writer_headers,
            json={"product_code": "ML-D", "name": "可删", "partner_id": partner.id},
        )
        assert pending.status_code == 200, pending.text
        pending_id = pending.json()["data"]["id"]
        removed = client.delete(
            f"/api/v1/supplier-products/{pending_id}",
            headers=writer_headers,
        )
        assert removed.status_code == 200, removed.text

        listed = client.get(
            "/api/v1/supplier-products",
            headers=writer_headers,
            params={"approved_only": True, "page_size": 50},
        )
        assert listed.status_code == 200, listed.text
        codes = {item["product_code"] for item in listed.json()["data"]["items"]}
        assert "ML-P" in codes
        assert "ML-D" not in codes
    finally:
        app.dependency_overrides.clear()


def test_pending_catalog_cannot_be_purchased():
    session, partner, _writer, _approver = _setup()
    product = SupplierProduct(
        tenant_id=partner.tenant_id,
        partner_id=partner.id,
        product_code="ML-BUY",
        name="未审",
        is_active=True,
        approval_status="pending",
    )
    session.add(product)
    session.commit()
    try:
        create_catalog_purchase_drafts(
            session,
            partner.tenant_id,
            [{"supplier_product_id": product.id, "qty": "1"}],
        )
        raise AssertionError("未审批色卡不应能购买")
    except PurchaseError as exc:
        assert exc.code == "not_approved"
