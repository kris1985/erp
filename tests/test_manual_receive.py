"""物料仓手工入库：同步色卡和供应商，并增加库存。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    Employee,
    EmployeeRoleAssignment,
    MaterialCategory,
    Partner,
    PricingUnit,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SharedLedgerType,
    SharedMaterialLedger,
    SharedMaterialStock,
    Size,
    SupplierProduct,
    Tenant,
)


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
    tenant = Tenant(name="入库厂")
    session.add(tenant)
    session.flush()
    user = Employee(tenant_id=tenant.id, name="仓管", username="admin", is_active=True)
    category = MaterialCategory(tenant_id=tenant.id, name="皮料", is_active=True)
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="38", is_active=True)
    unit = PricingUnit(tenant_id=tenant.id, name="米", is_active=True)
    customer = Partner(tenant_id=tenant.id, name="老客户", is_customer=True, is_active=True)
    session.add_all([user, category, color, size, unit, customer])
    session.commit()
    return session, user


def test_manual_receive_creates_supplier_color_card_and_stock():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    category = session.scalar(select(MaterialCategory))
    color = session.scalar(select(Color))
    unit = session.scalar(select(PricingUnit))
    try:
        res = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-001",
                "name": "黑皮",
                "supplier_name": "新皮料商",
                "qty": "12.5",
                "category_id": category.id,
                "color_id": color.id,
                "pricing_unit_id": unit.id,
                "unit_price": "3.5",
                "image_url": "/uploads/black.jpg",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["product_created"] is True
        assert body["partner_created"] is True
        assert Decimal(str(body["qty"])) == Decimal("12.5")

        product = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "ML-001"))
        partner = session.get(Partner, product.partner_id)
        assert product.name == "黑皮"
        assert product.category_id == category.id
        assert product.color_id == color.id
        assert product.pricing_unit_id == unit.id
        assert product.unit_price == Decimal("3.5000") or product.unit_price == Decimal("3.5")
        assert product.image_url == "/uploads/black.jpg"
        assert partner.name == "新皮料商"
        assert partner.is_supplier is True

        listed = client.get("/api/v1/shared-materials", headers=headers)
        rows = listed.json()["data"]
        assert len(rows) == 1
        assert rows[0]["supplier_product_code"] == "ML-001"
        assert rows[0]["partner_name"] == "新皮料商"
        assert rows[0]["category_name"] == "皮料"

        ledger = session.scalar(select(SharedMaterialLedger))
        assert ledger.ledger_type == SharedLedgerType.manual_receive
        assert ledger.qty_delta == Decimal("12.5")
        assert ledger.note == "手工入库"
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_updates_card_adds_qty_and_reuses_supplier():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    category = session.scalar(select(MaterialCategory))
    color = session.scalar(select(Color))
    size = session.scalar(select(Size))
    try:
        first = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-002",
                "name": "原名",
                "supplier_name": "新皮料商",
                "qty": "2",
                "unit_price": "1",
                "image_url": "/uploads/old.jpg",
            },
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-002",
                "name": "新名",
                "supplier_name": "新皮料商",
                "qty": "3",
                "category_id": category.id,
                "color_id": color.id,
                "size_id": size.id,
                "unit_price": "4",
            },
        )
        assert second.status_code == 200, second.text
        body = second.json()["data"]
        assert body["product_created"] is False
        assert body["partner_created"] is False
        assert Decimal(str(body["qty"])) == Decimal("3")

        session.expire_all()
        product = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "ML-002"))
        assert product.name == "新名"
        assert product.image_url == "/uploads/old.jpg"
        assert product.unit_price == Decimal("4.0000") or product.unit_price == Decimal("4")
        partners = session.scalars(select(Partner).where(Partner.name == "新皮料商")).all()
        assert len(partners) == 1
        stocks = session.scalars(select(SharedMaterialStock).order_by(SharedMaterialStock.id)).all()
        assert len(stocks) == 2
        assert stocks[0].size_id is None
        assert stocks[0].qty == Decimal("2")
        assert stocks[1].size_id == size.id
        assert stocks[1].qty == Decimal("3")
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_marks_existing_partner_as_supplier():
    session, user = _setup()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        res = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-003",
                "name": "扣件",
                "supplier_name": "老客户",
                "qty": "1",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["partner_created"] is False
        session.expire_all()
        partner = session.scalar(select(Partner).where(Partner.name == "老客户"))
        assert partner.is_customer is True
        assert partner.is_supplier is True
        assert session.scalar(select(Partner.id).where(Partner.name == "老客户").limit(1))
    finally:
        app.dependency_overrides.clear()


def test_manual_receive_rejects_bad_qty_and_foreign_category():
    session, user = _setup()
    other = Tenant(name="别厂")
    session.add(other)
    session.flush()
    foreign = MaterialCategory(tenant_id=other.id, name="别类", is_active=True)
    session.add(foreign)
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        empty = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={"product_code": "ML-004", "name": "扣件", "supplier_name": "甲", "qty": "0"},
        )
        assert empty.status_code == 400
        assert "数量" in empty.json()["detail"]

        bad = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-004",
                "name": "扣件",
                "supplier_name": "甲",
                "qty": "1",
                "category_id": foreign.id,
            },
        )
        assert bad.status_code == 400
        assert "分类" in bad.json()["detail"]
        assert session.scalar(select(SupplierProduct.id)) is None
    finally:
        app.dependency_overrides.clear()


def test_count_sets_on_hand_and_zero_row_can_be_deleted():
    session, user = _setup()
    session.add(EmployeeRoleAssignment(tenant_id=user.tenant_id, employee_id=user.id, role_code="admin"))
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        created = client.post(
            "/api/v1/shared-materials/manual-receive",
            headers=headers,
            json={
                "product_code": "ML-COUNT",
                "name": "盘点皮",
                "supplier_name": "皮商",
                "qty": "8",
            },
        )
        assert created.status_code == 200, created.text
        product = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "ML-COUNT"))

        counted = client.post(
            "/api/v1/shared-materials/adjust",
            headers=headers,
            json={
                "supplier_product_id": product.id,
                "on_hand_qty": "5",
                "note": "盘亏",
            },
        )
        assert counted.status_code == 200, counted.text
        assert Decimal(str(counted.json()["data"]["on_hand_qty"])) == Decimal("5")
        stock = session.scalar(select(SharedMaterialStock))
        assert stock.qty == Decimal("5")
        ledger = session.scalar(
            select(SharedMaterialLedger).where(SharedMaterialLedger.ledger_type == SharedLedgerType.adjust)
        )
        assert ledger.qty_delta == Decimal("-3")
        assert ledger.note == "盘亏"

        blocked = client.delete(f"/api/v1/shared-materials/{stock.id}", headers=headers)
        assert blocked.status_code == 400
        assert "现存量" in blocked.json()["detail"]

        bad_note = client.post(
            "/api/v1/shared-materials/adjust",
            headers=headers,
            json={"supplier_product_id": product.id, "on_hand_qty": "5", "note": "随便写"},
        )
        assert bad_note.status_code == 400

        zeroed = client.post(
            "/api/v1/shared-materials/adjust",
            headers=headers,
            json={"supplier_product_id": product.id, "on_hand_qty": "0"},
        )
        assert zeroed.status_code == 200, zeroed.text
        session.refresh(stock)
        assert stock.qty == Decimal("0")

        removed = client.delete(f"/api/v1/shared-materials/{stock.id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert session.get(SharedMaterialStock, stock.id) is None
        listed = client.get("/api/v1/shared-materials", headers=headers)
        assert listed.json()["data"] == []
    finally:
        app.dependency_overrides.clear()


def test_shared_stock_in_transit_hover_lists_open_purchase_qty():
    session, user = _setup()
    supplier = Partner(tenant_id=user.tenant_id, name="皮商", is_supplier=True, is_active=True)
    session.add(supplier)
    session.flush()
    product = SupplierProduct(
        tenant_id=user.tenant_id,
        product_code="ML-TR",
        name="在途皮",
        partner_id=supplier.id,
    )
    session.add(product)
    session.flush()
    session.add(
        SharedMaterialStock(
            tenant_id=user.tenant_id,
            supplier_product_id=product.id,
            qty=Decimal("1"),
            avg_unit_cost=Decimal("0"),
        )
    )
    ordered = PurchaseOrder(
        tenant_id=user.tenant_id,
        po_no="PO-A",
        partner_id=supplier.id,
        status=PurchaseOrderStatus.ordered,
    )
    partial = PurchaseOrder(
        tenant_id=user.tenant_id,
        po_no="PO-B",
        partner_id=supplier.id,
        status=PurchaseOrderStatus.partial_received,
    )
    draft = PurchaseOrder(
        tenant_id=user.tenant_id,
        po_no="PO-D",
        partner_id=supplier.id,
        status=PurchaseOrderStatus.draft,
    )
    session.add_all([ordered, partial, draft])
    session.flush()
    session.add_all(
        [
            PurchaseOrderLine(
                tenant_id=user.tenant_id,
                purchase_order_id=ordered.id,
                supplier_product_id=product.id,
                qty=Decimal("10"),
                received_qty=Decimal("4"),
            ),
            PurchaseOrderLine(
                tenant_id=user.tenant_id,
                purchase_order_id=ordered.id,
                supplier_product_id=product.id,
                qty=Decimal("2"),
                received_qty=Decimal("0"),
            ),
            PurchaseOrderLine(
                tenant_id=user.tenant_id,
                purchase_order_id=partial.id,
                supplier_product_id=product.id,
                qty=Decimal("5"),
                received_qty=Decimal("2"),
            ),
            PurchaseOrderLine(
                tenant_id=user.tenant_id,
                purchase_order_id=draft.id,
                supplier_product_id=product.id,
                qty=Decimal("9"),
                received_qty=Decimal("0"),
            ),
        ]
    )
    session.commit()
    from app.services.material_service import list_shared_stocks

    rows = list_shared_stocks(session, user.tenant_id)
    row = next(item for item in rows if item["supplier_product_code"] == "ML-TR")
    assert row["in_transit_qty"] == Decimal("11")
    assert [(item["po_no"], item["qty"]) for item in row["in_transit_orders"]] == [
        ("PO-A", Decimal("8")),
        ("PO-B", Decimal("3")),
    ]
