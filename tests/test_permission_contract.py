from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Employee, EmployeeRoleAssignment, RolePermission, Tenant, TenantRole
from app.permissions import permission_catalog


def test_every_web_permission_is_wired_into_frontend():
    """权限矩阵中的菜单/按钮不能成为只可勾选、实际无作用的幽灵权限。"""
    web_root = Path(__file__).resolve().parents[1] / "web" / "src"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in web_root.rglob("*")
        if path.suffix in {".ts", ".vue"}
    )
    expected = {
        item["code"]
        for item in permission_catalog()
        if item["code"].startswith(("menu.", "btn."))
    }
    missing = sorted(code for code in expected if code not in source)
    assert missing == [], f"前端未接入权限码：{missing}"


def test_permission_codes_are_unique():
    codes = [item["code"] for item in permission_catalog()]
    assert len(codes) == len(set(codes))


def test_menu_permission_does_not_grant_role_write():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="权限测试厂")
    db.add(tenant)
    db.flush()
    employee = Employee(
        tenant_id=tenant.id,
        name="只读角色管理员",
        username="role_reader",
        password_hash=hash_password("123456"),
        is_active=True,
    )
    db.add(employee)
    db.flush()
    db.add(TenantRole(tenant_id=tenant.id, code="role_reader", name="角色只读", base_role="manager", is_active=True))
    db.add(EmployeeRoleAssignment(tenant_id=tenant.id, employee_id=employee.id, role_code="role_reader"))
    db.add(RolePermission(tenant_id=tenant.id, role="role_reader", perm_code="menu.roles"))
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(employee)}"}
        assert client.get("/api/v1/roles", headers=headers).status_code == 200
        denied = client.post("/api/v1/roles", json={"name": "不能创建"}, headers=headers)
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.clear()
        db.close()
