"""模具独立建档：到货登记加库存，并生成供应商待结算。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Department, Employee, Partner, PayableLine, Size, SupplierProduct, Tenant
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(db):
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    token = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin", "password": "admin123"},
    ).json()["data"]["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_tooling_receive_creates_stock_and_supplier_pending():
    db = _session()
    tenant = Tenant(name="楦头仓")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    supplier = Partner(tenant_id=tenant.id, name="楦头厂", short_name="楦厂", is_supplier=True, is_active=True)
    other = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True, is_active=True)
    db.add_all([admin, supplier, other])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    s33 = Size(tenant_id=tenant.id, size_value="33", sort_order=33, is_active=True)
    s34 = Size(tenant_id=tenant.id, size_value="34", sort_order=34, is_active=True)
    db.add_all([s33, s34])
    card = SupplierProduct(
        tenant_id=tenant.id,
        product_code="CARD-1",
        name="色卡皮",
        partner_id=other.id,
        is_active=True,
    )
    db.add(card)
    production = Department(tenant_id=tenant.id, name="生产部", is_active=True, sort_order=1)
    develop = Department(tenant_id=tenant.id, name="开发部", is_active=True, sort_order=2)
    finance = Department(tenant_id=tenant.id, name="财务部", is_active=True, sort_order=3)
    db.add_all([production, develop, finance])
    db.flush()
    workshop = Department(
        tenant_id=tenant.id,
        name="生产一组",
        parent_id=production.id,
        is_active=True,
    )
    db.add(workshop)
    db.commit()

    try:
        client, headers = _client(db)
        departments = client.get("/api/v1/tooling/departments", headers=headers)
        assert departments.status_code == 200, departments.text
        assert [row["name"] for row in departments.json()["data"]["items"]] == ["生产部", "开发部"]

        child = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": workshop.id,
                        "code": "336-1",
                        "unit_price": "10",
                        "sizes": [{"size_id": s33.id, "qty": 1}],
                    }
                ],
            },
            headers=headers,
        )
        assert child.status_code == 400
        assert "一级部门" in child.json()["detail"]

        other_dept = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": finance.id,
                        "code": "336-1",
                        "unit_price": "10",
                        "sizes": [{"size_id": s33.id, "qty": 1}],
                    }
                ],
            },
            headers=headers,
        )
        assert other_dept.status_code == 400
        assert "开发" in other_dept.json()["detail"]

        created = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "delivery_note_no": "SH-9",
                "lines": [
                    {
                        "department_id": production.id,
                        "code": "336-1",
                        "unit_price": "10",
                        "sizes": [
                            {"size_id": s33.id, "qty": 7},
                            {"size_id": s34.id, "qty": 8},
                        ],
                    },
                    {
                        "department_id": develop.id,
                        "code": "337-1",
                        "unit_price": "8",
                        "sizes": [{"size_id": s33.id, "qty": 2}],
                    },
                ],
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        assert body["amount"] == 166
        assert body["kind"] == "shoe_last"
        assert [row["name"] for row in body["departments"]] == ["生产部", "开发部"]
        first = next(row for row in body["items"] if row["code"] == "336-1")
        assert first["kind"] == "shoe_last"
        assert first["department_name"] == "生产部"
        assert first["name"] is None
        assert first["total_qty"] == 15
        assert first["sizes"][str(s33.id)] == 7

        listed = client.get("/api/v1/tooling/items", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 2

        pending = client.get(
            "/api/v1/payables/pending-lines",
            params={"supplier_id": supplier.id},
            headers=headers,
        )
        assert pending.status_code == 200, pending.text
        rows = pending.json()["data"]["items"]
        assert len(rows) == 3
        assert {row["item_code"] for row in rows} == {"336-1", "337-1"}
        assert {row["size_value"] for row in rows} == {"33", "34"}
        assert rows[0]["source_type"] == "tooling_receive"
        assert rows[0]["supplier_name"] == "楦厂"
        assert rows[0]["delivery_note_no"] == "SH-9"
        assert sum(float(row["amount"]) for row in rows) == 166
        assert pending.json()["data"]["balance"]["pending_amount"] in (166, "166", "166.0000")

        line_ids = [row["line_id"] for row in rows]
        statement = client.post(
            "/api/v1/payables/purchase-statements",
            json={
                "supplier_id": supplier.id,
                "line_ids": line_ids,
                "remainder_payable_ids": [],
                "statement_no": "XT-STMT-1",
                "statement_date": date.today().isoformat(),
            },
            headers=headers,
        )
        assert statement.status_code == 200, statement.text
        assert float(statement.json()["data"]["current_amount"]) == 166

        again = client.get(
            "/api/v1/payables/pending-lines",
            params={"supplier_id": supplier.id, "item_code": "336-1"},
            headers=headers,
        )
        assert again.json()["data"]["items"] == []

        second = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": develop.id,
                        "code": "336-1",
                        "unit_price": "20",
                        "sizes": [{"size_id": s33.id, "qty": 1}],
                    }
                ],
            },
            headers=headers,
        )
        assert second.status_code == 200, second.text
        item = next(row for row in second.json()["data"]["items"] if row["code"] == "336-1")
        assert item["department_name"] == "开发部"
        assert item["sizes"][str(s33.id)] == 1
        assert item["total_qty"] == 1
        assert item["amount"] == 20

        listed_again = client.get("/api/v1/tooling/items", headers=headers)
        split_rows = [
            row for row in listed_again.json()["data"]["items"] if row["code"] == "336-1"
        ]
        assert {row["department_name"] for row in split_rows} == {"生产部", "开发部"}
        assert len(split_rows) == 2

        history = client.get("/api/v1/tooling/receipts", headers=headers)
        assert history.status_code == 200, history.text
        history_rows = history.json()["data"]["items"]
        assert len(history_rows) == 3
        assert {row["department_name"] for row in history_rows} == {"生产部", "开发部"}
        assert all(row["statemented"] for row in history_rows if row["code"] == "337-1")
        open_row = next(
            row for row in history_rows if row["code"] == "336-1" and row["department_name"] == "开发部"
        )
        assert open_row["statemented"] is False

        clash = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "knife_die",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": production.id,
                        "code": "336-1",
                        "unit_price": "20",
                        "sizes": [{"size_id": s33.id, "qty": 1}],
                    }
                ],
            },
            headers=headers,
        )
        assert clash.status_code == 400
        assert "楦头" in clash.json()["detail"]

        stated = next(row for row in history_rows if row["code"] == "337-1")
        blocked = client.put(
            f"/api/v1/tooling/receipts/{stated['receipt_id']}",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "delivery_note_no": "SH-9",
                "lines": [
                    {
                        "department_id": production.id,
                        "code": "336-1",
                        "unit_price": "10",
                        "sizes": [
                            {"size_id": s33.id, "qty": 7},
                            {"size_id": s34.id, "qty": 9},
                        ],
                    },
                    {
                        "department_id": develop.id,
                        "code": "337-1",
                        "unit_price": "8",
                        "sizes": [{"size_id": s33.id, "qty": 2}],
                    },
                ],
            },
            headers=headers,
        )
        assert blocked.status_code == 400
        assert "对账" in blocked.json()["detail"]

        detail = client.get(f"/api/v1/tooling/receipts/{open_row['receipt_id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["statemented"] is False
        assert detail.json()["data"]["lines"][0]["code"] == "336-1"

        updated = client.put(
            f"/api/v1/tooling/receipts/{open_row['receipt_id']}",
            json={
                "kind": "shoe_last",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": production.id,
                        "code": "336-1",
                        "unit_price": "25",
                        "sizes": [{"size_id": s33.id, "qty": 4}],
                    }
                ],
            },
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["amount"] == 100
        listed_fixed = client.get("/api/v1/tooling/items", headers=headers)
        code_rows = [row for row in listed_fixed.json()["data"]["items"] if row["code"] == "336-1"]
        assert {row["department_name"] for row in code_rows} == {"生产部"}
        assert code_rows[0]["sizes"][str(s33.id)] == 11
        assert code_rows[0]["sizes"][str(s34.id)] == 8

        ledgers = client.get(f"/api/v1/tooling/items/{item['id']}/ledgers", headers=headers)
        sources = [row["source_type"] for row in ledgers.json()["data"]["items"]]
        assert sources.count("receive") == 3
        assert "adjust" not in sources

        open_lines = db.scalars(
            select(PayableLine).where(
                PayableLine.tenant_id == tenant.id,
                PayableLine.source_type == "tooling_receive",
                PayableLine.statement_id.is_(None),
            )
        ).all()
        assert len(open_lines) == 1
        assert float(open_lines[0].amount) == 100
        assert float(open_lines[0].qty) == 4
        assert db.get(SupplierProduct, card.id) is not None
    finally:
        app.dependency_overrides.clear()


def test_tooling_accepts_sole_mold_and_other_mold():
    db = _session()
    tenant = Tenant(name="模具仓")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True, is_active=True)
    db.add_all([admin, supplier])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    dept = Department(tenant_id=tenant.id, name="开发部", is_active=True, sort_order=1)
    db.add_all([size, dept])
    db.commit()

    try:
        client, headers = _client(db)
        for kind, code, label, unit in (
            ("sole_mold", "DM-1", "底模", "套"),
            ("other_mold", "QT-1", "其它模具", "套"),
        ):
            created = client.post(
                "/api/v1/tooling/receipts",
                json={
                    "kind": kind,
                    "supplier_id": supplier.id,
                    "lines": [
                        {
                            "department_id": dept.id,
                            "code": code,
                            "unit_price": "8",
                            "sizes": [{"size_id": size.id, "qty": 2}],
                        }
                    ],
                },
                headers=headers,
            )
            assert created.status_code == 200, created.text
            body = created.json()["data"]
            assert body["kind"] == kind
            assert body["kind_label"] == label
            item = body["items"][0]
            assert item["kind_label"] == label
            assert item["unit_name"] == unit

        rejected = client.post(
            "/api/v1/tooling/receipts",
            json={
                "kind": "last",
                "supplier_id": supplier.id,
                "lines": [
                    {
                        "department_id": dept.id,
                        "code": "BAD",
                        "unit_price": "1",
                        "sizes": [{"size_id": size.id, "qty": 1}],
                    }
                ],
            },
            headers=headers,
        )
        assert rejected.status_code == 400
        assert "其它模具" in rejected.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_knife_die_can_only_use_production_department():
    db = _session()
    tenant = Tenant(name="刀模仓")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    supplier = Partner(tenant_id=tenant.id, name="刀模厂", is_supplier=True, is_active=True)
    db.add_all([admin, supplier])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    production = Department(tenant_id=tenant.id, name="生产部", is_active=True, sort_order=1)
    develop = Department(tenant_id=tenant.id, name="开发部", is_active=True, sort_order=2)
    db.add_all([size, production, develop])
    db.commit()

    payload = {
        "kind": "knife_die",
        "supplier_id": supplier.id,
        "lines": [
            {
                "department_id": develop.id,
                "code": "DM-1",
                "unit_price": "12",
                "sizes": [{"size_id": size.id, "qty": 1}],
            }
        ],
    }
    try:
        client, headers = _client(db)
        rejected = client.post("/api/v1/tooling/receipts", json=payload, headers=headers)
        assert rejected.status_code == 400
        assert "生产" in rejected.json()["detail"]

        payload["lines"][0]["department_id"] = production.id
        created = client.post("/api/v1/tooling/receipts", json=payload, headers=headers)
        assert created.status_code == 200, created.text
        assert created.json()["data"]["items"][0]["department_name"] == "生产部"
    finally:
        app.dependency_overrides.clear()


def test_tooling_qty_accepts_half_and_rejects_other_decimals():
    db = _session()
    tenant = Tenant(name="半只仓")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    supplier = Partner(tenant_id=tenant.id, name="楦头厂", is_supplier=True, is_active=True)
    db.add_all([admin, supplier])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    size = Size(tenant_id=tenant.id, size_value="36", sort_order=36, is_active=True)
    develop = Department(tenant_id=tenant.id, name="开发部", is_active=True, sort_order=1)
    db.add_all([size, develop])
    db.commit()

    def payload(qty):
        return {
            "kind": "shoe_last",
            "supplier_id": supplier.id,
            "lines": [
                {
                    "department_id": develop.id,
                    "code": "HALF-1",
                    "unit_price": "20",
                    "sizes": [{"size_id": size.id, "qty": qty}],
                }
            ],
        }

    try:
        client, headers = _client(db)
        rejected = client.post("/api/v1/tooling/receipts", json=payload("0.3"), headers=headers)
        assert rejected.status_code == 400
        assert "0.5" in rejected.json()["detail"]

        created = client.post("/api/v1/tooling/receipts", json=payload("0.5"), headers=headers)
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        item = body["items"][0]
        assert item["sizes"][str(size.id)] == 0.5
        assert item["total_qty"] == 0.5
        assert body["amount"] == 10

        again = client.post("/api/v1/tooling/receipts", json=payload("1.5"), headers=headers)
        assert again.status_code == 200, again.text
        stock = again.json()["data"]["items"][0]
        assert stock["sizes"][str(size.id)] == 2
        assert stock["total_qty"] == 2
        assert again.json()["data"]["amount"] == 30
    finally:
        app.dependency_overrides.clear()
