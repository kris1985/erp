"""产品开发按段授权：基础数据、工艺路线、客户报价、品牌报价互不代替。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Color, Department, Employee, ProcessSegment, RolePermission, Tenant, TenantRole
from app.services.department_scope import list_segment_leaf_departments
from app.services import rbac_service
from app.services.rbac_service import _OWN_PRODUCT_ACTION_MARKER, _OWN_PRODUCT_SECTION_MARKER


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _login(client: TestClient, username: str, password: str) -> dict:
    token = client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": password},
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_legacy_write_splits_into_section_permissions():
    db = _session()
    tenant = Tenant(name="分段权限厂")
    db.add(tenant)
    db.flush()
    rbac_service.ensure_system_roles(db, tenant.id)
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="dev_legacy",
        name="旧开发",
        base_role="manager",
        is_active=True,
    ))
    db.flush()
    for code in ("menu.own_products", "btn.own_products.write", "mobile.own_products.write"):
        db.add(RolePermission(tenant_id=tenant.id, role="dev_legacy", perm_code=code))
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant.id,
            RolePermission.perm_code.in_([_OWN_PRODUCT_SECTION_MARKER, _OWN_PRODUCT_ACTION_MARKER]),
        )
    )
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    codes = set(rbac_service.get_role_permissions(db, tenant.id, "dev_legacy"))
    for code in (
        "btn.own_products.basic_create",
        "btn.own_products.basic_edit",
        "btn.own_products.route",
        "btn.own_products.quote",
        "btn.own_products.brand_quote",
        "mobile.own_products.basic_create",
        "mobile.own_products.basic_edit",
        "mobile.own_products.route",
        "mobile.own_products.quote",
        "mobile.own_products.brand_quote",
        "btn.own_products.delete",
        "btn.own_products.copy",
        "btn.own_products.export",
        "btn.own_products.history",
        "mobile.own_products.delete",
        "mobile.own_products.copy",
        "mobile.own_products.export",
        "mobile.own_products.history",
    ):
        assert code in codes
    db.close()


def test_quote_permission_cannot_change_basic_data_or_route():
    db = _session()
    tenant = Tenant(name="报价权限厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    quoter = Employee(
        tenant_id=tenant.id,
        username="quoter",
        name="报价员",
        password_hash=hash_password("quoter123"),
        is_active=True,
    )
    db.add_all([admin, quoter])
    db.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(black)
    db.commit()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        rbac_service.set_employee_roles(db, admin, ["admin"])
        db.add(TenantRole(
            tenant_id=tenant.id,
            code="quoter",
            name="报价员",
            base_role="manager",
            is_active=True,
        ))
        db.commit()
        rbac_service.set_role_permissions(db, tenant.id, "quoter", [
            "menu.own_products",
            "btn.own_products.quote",
        ])
        rbac_service.set_employee_roles(db, quoter, ["quoter"])

        client = TestClient(app)
        admin_headers = _login(client, "admin", "admin123")
        created = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SHOE-Q",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [black.id],
            },
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]

        headers = _login(client, "quoter", "quoter123")
        denied_create = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SHOE-Q2",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [black.id],
            },
            headers=headers,
        )
        assert denied_create.status_code == 403

        denied_info = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"fabric": "牛皮"},
            headers=headers,
        )
        assert denied_info.status_code == 403

        denied_route = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"labors": []},
            headers=headers,
        )
        assert denied_route.status_code == 403

        denied_brand = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"brand_quotes": []},
            headers=headers,
        )
        assert denied_brand.status_code == 403

        quoted = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"quotes": []},
            headers=headers,
        )
        assert quoted.status_code == 200, quoted.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_basic_create_can_enter_route_on_new_product_only():
    db = _session()
    tenant = Tenant(name="录入含工艺厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    creator = Employee(
        tenant_id=tenant.id,
        username="creator",
        name="录入",
        password_hash=hash_password("creator123"),
        is_active=True,
    )
    db.add_all([admin, creator])
    db.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(black)
    db.commit()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        rbac_service.set_employee_roles(db, admin, ["admin"])
        db.add(TenantRole(
            tenant_id=tenant.id,
            code="creator",
            name="只录入",
            base_role="manager",
            is_active=True,
        ))
        db.commit()
        rbac_service.set_role_permissions(db, tenant.id, "creator", [
            "menu.own_products",
            "btn.own_products.basic_create",
        ])
        rbac_service.set_employee_roles(db, creator, ["creator"])
        client = TestClient(app)
        headers = _login(client, "creator", "creator123")
        body = {
            "product_code": "NEW-ROUTE",
            "product_year": 2026,
            "season": "SP",
            "color_ids": [black.id],
            "labors": [{"process_name": "裁断", "unit_price": "4", "sort_order": 0}],
        }
        created = client.post("/api/v1/own-products", json=body, headers=headers)
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]
        assert created.json()["data"]["labors"][0]["process_name"] == "裁断"
        updated = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={"labors": [{"process_name": "针车", "unit_price": "5", "sort_order": 0}]},
            headers=headers,
        )
        assert updated.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_delete_export_copy_and_history_are_separate():
    db = _session()
    tenant = Tenant(name="产品动作权限厂")
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
        name="编辑",
        password_hash=hash_password("editor123"),
        is_active=True,
    )
    db.add_all([admin, editor])
    db.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(black)
    db.commit()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        rbac_service.ensure_system_roles(db, tenant.id)
        clerk = set(rbac_service.get_role_permissions(db, tenant.id, "clerk"))
        assert "btn.own_products.export" in clerk
        assert "btn.own_products.history" in clerk
        assert "btn.own_products.delete" not in clerk
        assert "btn.own_products.copy" not in clerk
        kept = [code for code in clerk if code != "btn.own_products.history"]
        rbac_service.set_role_permissions(db, tenant.id, "clerk", kept)
        rbac_service.ensure_system_roles(db, tenant.id)
        after = set(rbac_service.get_role_permissions(db, tenant.id, "clerk"))
        assert "btn.own_products.history" not in after
        assert "btn.own_products.export" in after

        rbac_service.set_employee_roles(db, admin, ["admin"])
        db.add(TenantRole(
            tenant_id=tenant.id,
            code="editor",
            name="只编辑",
            base_role="manager",
            is_active=True,
        ))
        db.commit()
        rbac_service.set_role_permissions(db, tenant.id, "editor", [
            "menu.own_products",
            "btn.own_products.basic_edit",
        ])
        rbac_service.set_employee_roles(db, editor, ["editor"])

        client = TestClient(app)
        admin_headers = _login(client, "admin", "admin123")
        created = client.post(
            "/api/v1/own-products",
            json={"product_code": "ACT-1", "product_year": 2026, "season": "SP", "color_ids": [black.id]},
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]
        headers = _login(client, "editor", "editor123")
        assert client.delete(f"/api/v1/own-products/{product_id}", headers=headers).status_code == 403
        assert client.get(f"/api/v1/own-products/{product_id}/export", headers=headers).status_code == 403
        assert client.get(f"/api/v1/own-products/{product_id}/versions", headers=headers).status_code == 403
        denied_copy = client.post(
            "/api/v1/own-products",
            json={"product_code": "ACT-COPY", "product_year": 2026, "season": "SP", "color_ids": [black.id]},
            headers=headers,
        )
        assert denied_copy.status_code == 403

        rbac_service.set_role_permissions(db, tenant.id, "editor", [
            "menu.own_products",
            "btn.own_products.basic_edit",
            "btn.own_products.delete",
            "btn.own_products.export",
            "btn.own_products.copy",
            "btn.own_products.history",
        ])
        assert client.get(f"/api/v1/own-products/{product_id}/versions", headers=headers).status_code == 200
        exported = client.get(f"/api/v1/own-products/{product_id}/export", headers=headers)
        assert exported.status_code == 200, exported.text
        copied = client.post(
            "/api/v1/own-products",
            json={"product_code": "ACT-COPY", "product_year": 2026, "season": "SP", "color_ids": [black.id]},
            headers=headers,
        )
        assert copied.status_code == 200, copied.text
        removed = client.delete(f"/api/v1/own-products/{product_id}", headers=headers)
        assert removed.status_code == 200, removed.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_inactive_segment_departments_stay_available_for_product_route():
    db = _session()
    tenant = Tenant(name="停用工序段厂")
    db.add(tenant)
    db.flush()
    segment = ProcessSegment(
        tenant_id=tenant.id,
        name="面部",
        code="mianbu",
        sort_order=1,
        is_active=False,
    )
    db.add(segment)
    db.flush()
    db.add(Department(
        tenant_id=tenant.id,
        name="面部对组",
        process_segment_id=segment.id,
        is_active=True,
    ))
    db.commit()
    assert list_segment_leaf_departments(db, tenant.id) == []
    leaves = list_segment_leaf_departments(db, tenant.id, include_inactive=True)
    assert [row["name"] for row in leaves] == ["面部对组"]
    db.close()
