"""物料色卡 Excel 导入。"""

from decimal import Decimal
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Color, Employee, MaterialCategory, Partner, PricingUnit, SupplierProduct, Tenant


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


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "物料色卡"
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_creates_updates_and_reports_bad_rows():
    session = _session()
    tenant = Tenant(name="色卡厂")
    session.add(tenant)
    session.flush()
    supplier = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    stopped = Partner(tenant_id=tenant.id, name="停用商", is_supplier=True, is_active=False)
    category = MaterialCategory(tenant_id=tenant.id, name="皮料", is_active=True)
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    unit = PricingUnit(tenant_id=tenant.id, name="米", is_active=True)
    session.add_all([supplier, stopped, category, color, unit])
    session.flush()
    old = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="SP-OLD",
        name="旧皮",
        unit_price=Decimal("1"),
        is_active=True,
    )
    keep = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="SP-KEEP",
        name="保留名称",
        category_id=category.id,
        unit_price=Decimal("3"),
        is_active=True,
    )
    user = Employee(tenant_id=tenant.id, name="管理员", username="admin", is_active=True)
    session.add_all([old, keep, user])
    session.commit()

    content = _xlsx(
        [
            ["物料编号", "名称", "分类", "颜色", "单价", "计价单位", "供应商"],
            ["SP-NEW", "黑皮", "皮料", "黑", 12.5, "米", "皮料商"],
            ["SP-OLD", "新皮", "皮料", "黑", 8, "米", "皮料商"],
            ["SP-KEEP", None, None, None, 9.5, None, "皮料商"],
            ["SP-BAD", "坏料", "皮料", "黑", 1, "米", "没有的供应商"],
            ["SP-NEW", "重复", "皮料", "黑", 1, "米", "皮料商"],
            ["SP-STOP", "停用", "皮料", "黑", 1, "米", "停用商"],
            [None, None, None, None, None, None, None],
        ]
    )
    client = _client(session)
    try:
        headers = {"Authorization": f"Bearer {create_access_token(user)}"}
        template = client.get("/api/v1/supplier-products/import-template", headers=headers)
        assert template.status_code == 200
        assert template.content[:2] == b"PK"

        res = client.post(
            "/api/v1/supplier-products/import",
            headers=headers,
            files={
                "file": (
                    "物料色卡.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["created"] == 1
        assert body["updated"] == 2
        assert body["failed"] == 3
        messages = {item["message"] for item in body["errors"]}
        assert "供应商不存在" in messages
        assert any("重复" in item for item in messages)
        assert "供应商已停用" in messages

        session.expire_all()
        created = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "SP-NEW"))
        assert created is not None
        assert created.name == "黑皮"
        assert created.category_id == category.id
        assert created.color_id == color.id
        assert created.pricing_unit_id == unit.id
        assert created.partner_id == supplier.id
        assert created.unit_price == Decimal("12.5000")

        updated = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "SP-OLD"))
        assert updated.name == "新皮"
        assert updated.unit_price == Decimal("8.0000")

        kept = session.scalar(select(SupplierProduct).where(SupplierProduct.product_code == "SP-KEEP"))
        assert kept.name == "保留名称"
        assert kept.category_id == category.id
        assert kept.unit_price == Decimal("9.5000")

        missing = client.post(
            "/api/v1/supplier-products/import",
            headers=headers,
            files={"file": ("空.xlsx", _xlsx([["物料编号", "供应商"]]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert missing.status_code == 400
        assert missing.json()["detail"] == "没有可导入的数据"
    finally:
        app.dependency_overrides.clear()
