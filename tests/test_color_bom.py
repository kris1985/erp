"""配色 BOM：空色 ∪ 本色展开；无效配色拒绝；全空行兼容现网。"""

from decimal import Decimal

import pytest
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
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductColor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    SpecExecutionOrder,
    SpecExecutionStatus,
    Size,
    SupplierProduct,
    Tenant,
    User,
    UserRole,
)
from app.services import material_service
from app.services.material_service import filter_bom_for_colorway


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="配色BOM厂")
    session.add(tenant)
    session.flush()
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    white = Color(tenant_id=tenant.id, name="白", code="WH")
    session.add_all([black, white])
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=1)
    session.add(size)
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    proc = ProcessDefinition(
        tenant_id=tenant.id, name="成型", code="CX", default_price=Decimal("1"), sort_order=1
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="A-BK", is_active=True)
    session.add(product)
    session.flush()
    session.add(
        OwnProductColor(
            tenant_id=tenant.id, own_product_id=product.id, color_id=black.id
        )
    )
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="SOLE-1",
        name="大底",
        partner_id=partner.id,
        unit_price=Decimal("10"),
        is_active=True,
    )
    leather_bk = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-BK",
        name="黑皮",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    leather_wh = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-WH",
        name="白皮",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    session.add_all([sole, leather_bk, leather_wh])
    session.flush()
    session.add_all(
        [
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=sole.id,
                qty=Decimal("1"),
                unit_price=Decimal("10"),
                line_total=Decimal("10"),
                sort_order=0,
                color_id=None,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=leather_bk.id,
                qty=Decimal("0.5"),
                unit_price=Decimal("2"),
                line_total=Decimal("1"),
                sort_order=1,
                color_id=black.id,
            ),
            OwnProductMaterial(
                tenant_id=tenant.id,
                own_product_id=product.id,
                supplier_product_id=leather_wh.id,
                qty=Decimal("0.5"),
                unit_price=Decimal("2"),
                line_total=Decimal("1"),
                sort_order=2,
                color_id=white.id,
            ),
        ]
    )
    session.commit()
    yield (
        session,
        tenant.id,
        product.id,
        black.id,
        white.id,
        sole.id,
        leather_bk.id,
        leather_wh.id,
        proc.id,
        size.id,
    )
    session.close()


def _order(session, tenant_id, product_id, proc_id, *, color_id, size_id, qty=100):
    order = Order(
        tenant_id=tenant_id,
        order_no="PO-CB-1",
        customer_name="客户",
        own_product_id=product_id,
        total_qty=qty,
        status=OrderStatus.confirmed,
    )
    session.add(order)
    session.flush()
    session.add_all(
        [
            OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                color_id=color_id,
                size_id=size_id,
                qty=qty,
            ),
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=proc_id,
                process_name="成型",
                status=OrderProcessStatus.pending,
                plan_qty=qty,
            ),
        ]
    )
    session.commit()
    session.refresh(order)
    return order


def test_filter_null_union_this_color(db):
    session, _t, product_id, black_id, white_id, sole_id, leather_bk_id, leather_wh_id, _p, _s = db
    mats = list(
        session.scalars(
            select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product_id)
        ).all()
    )
    black_rows = filter_bom_for_colorway(mats, black_id)
    assert {m.supplier_product_id for m in black_rows} == {sole_id, leather_bk_id}

    white_rows = filter_bom_for_colorway(mats, white_id)
    assert {m.supplier_product_id for m in white_rows} == {sole_id, leather_wh_id}

    all_rows = filter_bom_for_colorway(mats, None)
    assert {m.supplier_product_id for m in all_rows} == {sole_id, leather_bk_id, leather_wh_id}


def test_refresh_from_bom_excludes_other_colorway(db):
    session, tenant_id, product_id, black_id, _w, sole_id, leather_bk_id, leather_wh_id, proc_id, size_id = db
    order = _order(session, tenant_id, product_id, proc_id, color_id=black_id, size_id=size_id)

    rows = material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    session.commit()
    sp_ids = {r.supplier_product_id for r in rows}
    assert sole_id in sp_ids
    assert leather_bk_id in sp_ids
    assert leather_wh_id not in sp_ids
    sole = next(r for r in rows if r.supplier_product_id == sole_id)
    leather = next(r for r in rows if r.supplier_product_id == leather_bk_id)
    assert sole.required_qty == Decimal("100.0000")
    assert leather.required_qty == Decimal("50.0000")


def test_all_null_bom_matches_current_behavior(db):
    session, tenant_id, product_id, black_id, _w, sole_id, leather_bk_id, leather_wh_id, proc_id, size_id = db
    for m in session.scalars(
        select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == product_id)
    ):
        m.color_id = None
    session.commit()
    order = _order(session, tenant_id, product_id, proc_id, color_id=black_id, size_id=size_id)

    rows = material_service.refresh_from_bom(session, tenant_id, order, keep_progress=False)
    assert {r.supplier_product_id for r in rows} == {sole_id, leather_bk_id, leather_wh_id}


def test_header_refresh_uses_header_color(db):
    session, tenant_id, product_id, black_id, _w, sole_id, leather_bk_id, leather_wh_id, _p, size_id = db
    header = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="EH-CB-1",
        own_product_id=product_id,
        color_id=black_id,
        total_qty=80,
        status=SpecExecutionStatus.confirmed,
    )
    session.add(header)
    session.flush()
    session.add(
        SpecExecutionOrder(
            tenant_id=tenant_id,
            execution_no="EX-CB-1",
            header_id=header.id,
            own_product_id=product_id,
            color_id=black_id,
            size_id=size_id,
            total_qty=80,
            status=SpecExecutionStatus.confirmed,
        )
    )
    session.commit()
    session.refresh(header)

    rows = material_service.refresh_from_bom_for_header(
        session, tenant_id, header, keep_progress=False
    )
    sp_ids = {r.supplier_product_id for r in rows}
    assert sp_ids == {sole_id, leather_bk_id}


def test_simulate_mrp_uses_demand_color(db):
    session, tenant_id, product_id, black_id, _w, sole_id, leather_bk_id, leather_wh_id, _p, _s = db
    result = material_service.simulate_mrp_from_bom(
        session,
        tenant_id,
        [
            {
                "key": "d1",
                "label": "黑",
                "order_no": "SO-1",
                "product_code": "A-BK",
                "own_product_id": product_id,
                "total_qty": 10,
                "color_id": black_id,
            }
        ],
        include_shared=False,
    )
    sp_ids = {ln["supplier_product_id"] for ln in result["lines"]}
    assert sole_id in sp_ids
    assert leather_bk_id in sp_ids
    assert leather_wh_id not in sp_ids


def test_kit_hint_ignores_other_colorway_shortage(db):
    session, tenant_id, product_id, black_id, _w, sole_id, leather_bk_id, leather_wh_id, _p, _s = db
    from app.models import SharedMaterialStock
    from app.services import inventory_settings

    inventory_settings.save_inventory_patch(
        session, tenant_id, {"kit_include_unallocated_pool": True}
    )
    session.add_all(
        [
            SharedMaterialStock(
                tenant_id=tenant_id, supplier_product_id=sole_id, size_id=None, qty=Decimal("100")
            ),
            SharedMaterialStock(
                tenant_id=tenant_id,
                supplier_product_id=leather_bk_id,
                size_id=None,
                qty=Decimal("100"),
            ),
        ]
    )
    session.commit()

    assert (
        material_service.estimate_sku_kit_hint(
            session, tenant_id, own_product_id=product_id, qty=10, color_id=black_id
        )
        == "ready"
    )
    assert (
        material_service.estimate_sku_kit_hint(
            session, tenant_id, own_product_id=product_id, qty=10, color_id=None
        )
        == "short"
    )


def test_api_rejects_unbound_bom_color():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="配色API厂")
    db.add(tenant)
    db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            username="admin",
            display_name="管理员",
            password_hash=hash_password("admin123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    white = Color(tenant_id=tenant.id, name="白", code="WH")
    db.add_all([black, white])
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    db.add(partner)
    db.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="皮",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    db.add(sp)
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()[
            "data"
        ]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        bad = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "A-BK",
                "color_ids": [black.id],
                "materials": [
                    {"supplier_product_id": sp.id, "qty": 1, "color_id": white.id},
                ],
            },
            headers=headers,
        )
        assert bad.status_code == 400
        assert "配色" in str(bad.json().get("detail") or "")
        db.rollback()

        ok = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "A-BK",
                "color_ids": [black.id],
                "materials": [
                    {"supplier_product_id": sp.id, "qty": 1, "color_id": black.id},
                    {"supplier_product_id": sp.id, "qty": 1},
                ],
            },
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        mats = ok.json()["data"]["materials"]
        by_scope = {(m.get("bom_color_id"), m.get("bom_color_name")) for m in mats}
        assert (None, None) in by_scope
        assert (black.id, "黑") in by_scope
    finally:
        app.dependency_overrides.clear()
        db.close()
