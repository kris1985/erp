"""P0：排产确认是唯一下发路径；无窗口禁止 HTTP 建单；开裁缺料须写原因。"""

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
from app.schemas.api import SalesOrderCreate, SalesOrderLineIn, SalesOrderLineItemIn
from app.services import rbac_service
from app.services.execution_schedule_service import confirm_draft, propose_draft
from app.services.execution_service import (
    ExecutionError,
    create_execution,
    cut_cards_for_header,
)
from app.services.sales_order_service import confirm_sales_order, create_sales_order


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_factory(db):
    tenant = Tenant(name="P0唯一下发厂")
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
        tenant_id=tenant.id, product_code="P0-A-BK", is_active=True, trace_enabled=True
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
    return tenant, product, black, size, sp


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
    return item


def test_accept_sales_does_not_create_execution():
    db = _session()
    tenant, product, black, size, _sp = _seed_factory(db)
    so = create_sales_order(
        db,
        tenant.id,
        SalesOrderCreate(
            order_no="SO-P0-ACC",
            customer_name="客户",
            ordered_at=date.today(),
            lines=[
                SalesOrderLineIn(
                    own_product_id=product.id,
                    color_id=black.id,
                    items=[SalesOrderLineItemIn(size_id=size.id, qty=10)],
                )
            ],
        ),
        created_by=None,
    )
    confirm_sales_order(db, tenant.id, so.id, created_by=None)
    db.commit()
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None
    db.close()


def test_two_sales_same_style_one_job_until_confirm():
    db = _session()
    tenant, product, black, size, _sp = _seed_factory(db)
    a = _so_item(db, tenant, product, black, size, order_no="SO-A", qty=30, customer="甲")
    b = _so_item(db, tenant, product, black, size, order_no="SO-B", qty=20, customer="乙")
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert draft["status"] == "draft"
    assert len(draft["jobs"]) == 1
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None
    windows = list(draft["jobs"][0].get("windows") or [])
    assert windows
    assert all(w.get("start_date") and w.get("end_date") for w in windows)

    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert result["status"] == "confirmed"
    assert result["header_count"] == 1
    header = db.scalar(select(ExecutionHeader).limit(1))
    assert header is not None
    from app.services.material_service import list_header_processes

    procs = list_header_processes(db, tenant.id, header.id)
    by_pid = {int(w["process_id"]): w for w in windows if w.get("process_id")}
    for p in procs:
        w = by_pid.get(int(p.process_id))
        if not w:
            continue
        assert str(p.start_date) == str(w["start_date"])
        assert str(p.end_date) == str(w["end_date"])
    db.close()


def test_http_blocks_direct_create_and_skip_plan():
    db = _session()
    tenant, product, black, size, _sp = _seed_factory(db)
    item = _so_item(db, tenant, product, black, size, order_no="SO-HTTP", qty=8)

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
        body = {
            "items": [{"sales_order_line_item_id": item.id, "qty": 8}],
        }
        r1 = client.post("/api/v1/executions", json=body, headers=headers)
        assert r1.status_code == 400
        assert "排产" in str(r1.json().get("detail") or "")

        r2 = client.post("/api/v1/executions/headers", json=body, headers=headers)
        assert r2.status_code == 400

        r3 = client.post("/api/v1/executions/supplement", json=body, headers=headers)
        assert r3.status_code == 400

        r4 = client.post("/api/v1/schedule/confirm-production", json=body, headers=headers)
        assert r4.status_code == 400
        assert "跳过" in str(r4.json().get("detail") or "") or "方案" in str(r4.json().get("detail") or "")

        assert db.scalar(select(ExecutionHeader.id).limit(1)) is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cut_requires_reason_when_first_kit_short():
    db = _session()
    tenant, product, black, size, _sp = _seed_factory(db)
    item = _so_item(db, tenant, product, black, size, order_no="SO-CUT", qty=10)
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    header_id = exe.header_id
    preview = cut_cards_for_header(db, tenant_id=tenant.id, header_id=header_id, dry_run=True)
    assert preview.get("first_kit_ok") is False
    assert preview.get("empty_bom") is False

    with pytest.raises(ExecutionError) as ei:
        cut_cards_for_header(db, tenant_id=tenant.id, header_id=header_id, dry_run=False)
    assert ei.value.code == "first_kit_blocked"

    ok = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=header_id,
        dry_run=False,
        skip_kit_reason="先裁已到的面料，底料明日到",
    )
    assert (ok.get("to_create") or 0) >= 0
    header = db.get(ExecutionHeader, header_id)
    assert header and "开裁缺料原因" in (header.notes or "")
    db.close()
