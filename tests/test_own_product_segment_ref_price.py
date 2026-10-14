"""产品工艺路线段参考价：未填工序价时按参考价计人工成本。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.own_products import _compute_labor_cost, _normalize_segment_ref_prices
from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Color, Department, Employee, OwnProductLabor, ProcessSegment, Tenant
from app.services import rbac_service
from app.services.segment_service import ensure_default_segments


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_compute_labor_cost_falls_back_to_segment_ref():
    labors = [
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="裁断",
            unit_price=Decimal("0"),
            segment_id=10,
        ),
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="针车",
            unit_price=Decimal("1.5"),
            segment_id=20,
        ),
    ]
    refs = {"10": 2.3, "20": 9.9, "30": 0.8}
    # 段10 工序价为 0 → 参考价 2.3；段20 工序价 1.5；段30 没有工序 → 参考价 0.8
    assert _compute_labor_cost(labors, refs) == Decimal("4.6000")


def test_compute_labor_cost_splits_department_prices():
    labors = [
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="针车",
            unit_price=Decimal("1"),
            segment_id=20,
            department_prices={"1": "1.0", "2": "2.5"},
        )
    ]
    # 同一段两个部门不叠加，只计部门 1 的工序价 1.0；无工序的段 30 用参考价 0.4
    refs = {"20:1": 9, "20": 8, "30": 0.4}
    assert _compute_labor_cost(labors, refs) == Decimal("1.4000")


def test_compute_labor_cost_uses_one_segment_ref_when_process_price_is_zero():
    labors = [
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="针车",
            unit_price=Decimal("0"),
            segment_id=20,
            department_prices={"1": 0, "2": 0},
        )
    ]
    # 两个部门工序价都是 0，不叠加，这段参考价只计一次
    refs = {"20:1": 3, "20:2": 4, "20": 9}
    assert _compute_labor_cost(labors, refs) == Decimal("9.0000")


def test_compute_labor_cost_counts_each_department_process():
    labors = [
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="绱鞋",
            unit_price=Decimal("1.2"),
            segment_id=20,
            department_id=1,
        ),
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="贴底",
            unit_price=Decimal("0.8"),
            segment_id=20,
            department_id=2,
        ),
    ]
    # 同一段两个部门不叠加，只计部门 1
    assert _compute_labor_cost(labors, None) == Decimal("1.2000")


def test_compute_labor_cost_uses_segment_ref_per_department_without_process_price():
    labors = [
        OwnProductLabor(
            tenant_id=1,
            own_product_id=1,
            process_name="绱鞋",
            unit_price=Decimal("1.2"),
            segment_id=20,
            department_id=1,
        )
    ]
    # 保存时按部门顺序只计第一个部门的工序价，不把部门 2 的参考价再加进去
    assert _compute_labor_cost(
        labors,
        {"20": 5},
        departments_by_segment={20: [1, 2]},
    ) == Decimal("1.2000")


def test_compute_labor_cost_adds_segment_ref_for_each_department_without_processes():
    # 两个部门都没有工序价，参考价只计一次，不按部门翻倍
    assert _compute_labor_cost(
        [],
        {"20": 9},
        departments_by_segment={20: [1, 2]},
    ) == Decimal("9.0000")


def test_normalize_segment_ref_prices_drops_zero_rejects_negative():
    assert _normalize_segment_ref_prices(None) is None
    assert _normalize_segment_ref_prices({"1": 0, "2": "0.00"}) is None
    out = _normalize_segment_ref_prices({"3": "1.25", "4": 0})
    assert out == {"3": 1.25}
    out_dept = _normalize_segment_ref_prices({"4": 0, "6:8": "2.5"})
    assert out_dept == {"6": 2.5}
    assert _normalize_segment_ref_prices({"6": "1.5", "6:8": "2.5"}) == {"6": 1.5}
    try:
        _normalize_segment_ref_prices({"5": -1})
        assert False, "should reject negative"
    except Exception as e:
        assert getattr(e, "status_code", None) == 400 or "参考价" in str(e)


def test_create_own_product_segment_ref_prices_api():
    db = _session()
    tenant = Tenant(name="参考价厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(admin)
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(color)
    db.commit()

    cut = db.query(ProcessSegment).filter_by(tenant_id=tenant.id, code="cut").one()
    stitch = db.query(ProcessSegment).filter_by(tenant_id=tenant.id, code="stitch").one()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post(
            "/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "REF-01",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 0,
                        "segment_id": stitch.id,
                    }
                ],
                "segment_ref_prices": {
                    str(cut.id): 2.5,
                    str(stitch.id): 3.0,
                },
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert float(data["segment_ref_prices"][str(cut.id)]) == 2.5
        assert float(data["segment_ref_prices"][str(stitch.id)]) == 3.0
        # 裁断没有工序价，用参考价 2.5；针车工序价为 0，用参考价 3.0
        assert float(data["labor_cost"]) == 5.5

        # 填上针车工序价后，该段改用工序价，裁断仍用参考价
        pid = data["id"]
        res2 = client.patch(
            f"/api/v1/own-products/{pid}",
            json={
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 1.2,
                        "segment_id": stitch.id,
                    }
                ],
                "segment_ref_prices": {
                    str(cut.id): 2.5,
                    str(stitch.id): 3.0,
                },
            },
            headers=headers,
        )
        assert res2.status_code == 200, res2.text
        data2 = res2.json()["data"]
        assert float(data2["labor_cost"]) == 3.7  # 2.5 + 1.2
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_same_segment_departments_keep_separate_processes():
    db = _session()
    tenant = Tenant(name="分部门工序厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(admin)
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(color)
    stitch = db.query(ProcessSegment).filter_by(tenant_id=tenant.id, code="stitch").one()
    dept_a = Department(tenant_id=tenant.id, name="针车A", process_segment_id=stitch.id)
    dept_b = Department(tenant_id=tenant.id, name="针车B", process_segment_id=stitch.id)
    db.add_all([dept_a, dept_b])
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post(
            "/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        res = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "DEPT-01",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "labors": [
                    {
                        "process_name": "绱鞋",
                        "unit_price": 1.2,
                        "segment_id": stitch.id,
                        "department_id": dept_a.id,
                    },
                    {
                        "process_name": "贴底",
                        "unit_price": 0.8,
                        "segment_id": stitch.id,
                        "department_id": dept_b.id,
                    },
                ],
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        by_dept = {row["department_id"]: row["process_name"] for row in data["labors"]}
        assert by_dept[dept_a.id] == "绱鞋"
        assert by_dept[dept_b.id] == "贴底"
        assert float(data["labor_cost"]) == 1.2

        dup = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "DEPT-02",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "labors": [
                    {
                        "process_name": "绱鞋",
                        "unit_price": 1,
                        "segment_id": stitch.id,
                        "department_id": dept_a.id,
                    },
                    {
                        "process_name": "绱鞋",
                        "unit_price": 2,
                        "segment_id": stitch.id,
                        "department_id": dept_a.id,
                    },
                ],
            },
            headers=headers,
        )
        assert dup.status_code == 400
        assert "重复" in dup.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_new_process_name_unique_within_segment_only():
    db = _session()
    tenant = Tenant(name="跨段同名工序厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(admin)
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    cut = db.query(ProcessSegment).filter_by(tenant_id=tenant.id, code="cut").one()
    stitch = db.query(ProcessSegment).filter_by(tenant_id=tenant.id, code="stitch").one()
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post(
            "/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created_cut = client.post(
            "/api/v1/processes",
            json={"name": "车线", "code": "SEW-CUT", "segment_id": cut.id},
            headers=headers,
        )
        created_stitch = client.post(
            "/api/v1/processes",
            json={"name": "车线", "code": "SEW-STITCH", "segment_id": stitch.id},
            headers=headers,
        )
        assert created_cut.status_code == 200, created_cut.text
        assert created_stitch.status_code == 200, created_stitch.text
        assert created_cut.json()["data"]["id"] != created_stitch.json()["data"]["id"]
        again = client.post(
            "/api/v1/processes",
            json={"name": "车线", "code": "SEW-STITCH-2", "segment_id": stitch.id},
            headers=headers,
        )
        assert again.status_code == 400
        assert "同名" in again.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
