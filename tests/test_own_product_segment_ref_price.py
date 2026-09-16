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
from app.models import Color, Employee, OwnProductLabor, ProcessSegment, Tenant
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
    # 段10 工序价为0 → 用参考价 2.3；段20 有工序价 → 1.5；段30 无工序 → 0.8
    assert _compute_labor_cost(labors, refs) == Decimal("4.6000")


def test_normalize_segment_ref_prices_drops_zero_rejects_negative():
    assert _normalize_segment_ref_prices(None) is None
    assert _normalize_segment_ref_prices({"1": 0, "2": "0.00"}) is None
    out = _normalize_segment_ref_prices({"3": "1.25", "4": 0})
    assert out == {"3": 1.25}
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
                "season": "SS",
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
        # 裁断仅参考价 2.5 + 针车工序价为0故用参考价 3.0
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
