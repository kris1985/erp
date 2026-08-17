"""P1：草稿展开来源后可剔除客户；条子/负荷重算；已开裁禁止并入。不做改本次数量。"""

from datetime import date
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
    ExecutionAllocation,
    ExecutionHeader,
    OwnProduct,
    OwnProductLabor,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SupplierProduct,
    Tenant,
    Employee,
)
from app.services import rbac_service
from app.services.execution_schedule_service import (
    ExecutionScheduleError,
    confirm_draft,
    drop_draft_sources,
    propose_draft,
)
from app.services.execution_service import (
    ExecutionError,
    create_execution,
    cut_cards_for_header,
    list_producible,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_factory(db):
    tenant = Tenant(name="P1拆并厂")
    db.add(tenant)
    db.flush()
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
    black = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=1)
    db.add_all([black, size])
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
    )
    db.add_all([partner, proc])
    db.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="P1-A-BK", is_active=True, trace_enabled=True
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("2"),
        is_active=True,
    )
    db.add(sp)
    db.flush()
    db.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("2"),
            line_total=Decimal("2"),
            sort_order=0,
        )
    )
    db.commit()
    return tenant, product, black, size


def _so_item(db, tenant, product, color, size, *, order_no, qty, customer="客户甲"):
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no=order_no,
        customer_name=customer,
        status=SalesOrderStatus.confirmed,
        ordered_at=date.today(),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        status=SalesOrderLineStatus.pending,
        total_qty=qty,
        delivery_date=date.today(),
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant.id,
        sales_order_line_id=line.id,
        color_id=color.id,
        size_id=size.id,
        qty=qty,
        allocated_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return so, item


def test_propose_exposes_sales_sources():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-A", qty=30, customer="甲")
    so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-B", qty=20, customer="乙")
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert len(draft["jobs"]) == 1
    job = draft["jobs"][0]
    assert job["total_qty"] == 50
    sources = job["sources"]
    assert {s["sales_order_id"] for s in sources} == {so_a.id, so_b.id}
    by_cust = {s["customer_name"]: s["qty"] for s in sources}
    assert by_cust == {"甲": 30, "乙": 20}
    db.close()


def test_drop_one_customer_rebuilds_job_and_confirm_leaves_the_rest():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-A", qty=30, customer="甲")
    so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-B", qty=20, customer="乙")
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    job_key = draft["jobs"][0]["key"]
    qty_before = draft["jobs"][0]["total_qty"]
    windows_before = list(draft["jobs"][0].get("windows") or [])
    assert qty_before == 50
    assert windows_before

    out = drop_draft_sources(
        db,
        tenant_id=tenant.id,
        draft_id=draft["id"],
        job_key=job_key,
        sales_order_ids=[so_b.id],
    )
    assert out["status"] == "draft"
    assert len(out["jobs"]) == 1
    job = out["jobs"][0]
    assert job["total_qty"] == 30
    assert job["total_qty"] != qty_before
    assert [s["customer_name"] for s in job["sources"]] == ["甲"]
    assert job["sources"][0]["qty"] == 30
    assert job.get("windows")
    picked = next((p for p in out["proposals"] if p.get("strategy") == out["strategy"]), None)
    assert picked and picked.get("load") is not None
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None

    confirmed = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert confirmed["execution_count"] == 1
    db.refresh(a)
    db.refresh(b)
    assert a.allocated_qty == 30
    assert b.allocated_qty == 0
    so_ids = set(
        db.scalars(select(ExecutionAllocation.sales_order_id)).all()
    )
    assert so_ids == {so_a.id}
    pool = list_producible(db, tenant_id=tenant.id)
    remaining_sos = {
        s["sales_order_id"] for row in pool for s in (row.get("sources") or [])
    }
    assert so_b.id in remaining_sos
    assert so_a.id not in remaining_sos
    db.close()


def test_drop_last_source_refused():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-A", qty=30, customer="甲")
    so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-B", qty=20, customer="乙")
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    job_key = draft["jobs"][0]["key"]
    drop_draft_sources(
        db,
        tenant_id=tenant.id,
        draft_id=draft["id"],
        job_key=job_key,
        sales_order_ids=[so_b.id],
    )
    with pytest.raises(ExecutionScheduleError) as ei:
        drop_draft_sources(
            db,
            tenant_id=tenant.id,
            draft_id=draft["id"],
            job_key=job_key,
            sales_order_ids=[so_a.id],
        )
    assert ei.value.code == "empty_groups"
    db.close()


def test_cannot_append_to_cut_header():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    _so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-CUT-A", qty=10, customer="甲")
    _so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-CUT-B", qty=8, customer="乙")
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": a.id, "qty": 10}],
    )
    header_id = exe.header_id
    cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=header_id,
        dry_run=False,
        skip_kit_reason="测试开裁后禁止并入",
    )
    with pytest.raises(ExecutionError) as ei:
        create_execution(
            db,
            tenant_id=tenant.id,
            items=[{"sales_order_line_item_id": b.id, "qty": 8}],
            header_id=header_id,
        )
    assert ei.value.code == "header_started"
    db.refresh(b)
    assert b.allocated_qty == 0
    db.close()


def test_drop_sources_http():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-HTTP-A", qty=30, customer="甲")
    so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-HTTP-B", qty=20, customer="乙")
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post("/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}).json()[
            "data"
        ]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post(
            f"/api/v1/schedule/execution-drafts/{draft['id']}/drop-sources",
            json={"job_key": draft["jobs"][0]["key"], "sales_order_ids": [so_b.id]},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["jobs"][0]["total_qty"] == 30
        assert [s["customer_name"] for s in body["jobs"][0]["sources"]] == ["甲"]
        assert body["jobs"][0]["sources"][0]["sales_order_id"] == so_a.id
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_split_style_keys_two_jobs_two_headers():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    _so_a, a = _so_item(db, tenant, product, black, size, order_no="SO-SP-A", qty=30, customer="甲")
    _so_b, b = _so_item(db, tenant, product, black, size, order_no="SO-SP-B", qty=20, customer="乙")
    style_key = f"{product.id}-{black.id}"
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
        split_style_keys=[style_key],
    )
    assert len(draft["jobs"]) == 2
    by_cust = {j.get("customer_name"): j["total_qty"] for j in draft["jobs"]}
    assert by_cust == {"甲": 30, "乙": 20}
    for j in draft["jobs"]:
        assert j.get("windows")
        assert "::" in str(j["key"])
    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert result["header_count"] == 2
    db.refresh(a)
    db.refresh(b)
    assert a.allocated_qty == 30
    assert b.allocated_qty == 20
    headers = list(db.scalars(select(ExecutionHeader)).all())
    assert len(headers) == 2
    db.close()


def test_same_customer_two_orders_stay_one_job_when_split():
    db = _session()
    tenant, product, black, size = _seed_factory(db)
    _so1, a = _so_item(db, tenant, product, black, size, order_no="SO-SAME-1", qty=10, customer="甲")
    _so2, b = _so_item(db, tenant, product, black, size, order_no="SO-SAME-2", qty=12, customer="甲")
    style_key = f"{product.id}-{black.id}"
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 10},
            {"sales_order_line_item_id": b.id, "qty": 12},
        ],
        split_style_keys=[style_key],
    )
    assert len(draft["jobs"]) == 1
    assert draft["jobs"][0]["total_qty"] == 22
    assert draft["jobs"][0]["customer_name"] == "甲"
    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert result["header_count"] == 1
    db.close()
