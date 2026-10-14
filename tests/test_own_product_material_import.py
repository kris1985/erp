"""产品开发物料 Excel 导入解析。"""

from decimal import Decimal
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    Employee,
    MaterialCategory,
    Partner,
    PricingUnit,
    ProcessSegment,
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


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "产品物料"
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_product_materials_against_color_card():
    session = _session()
    tenant = Tenant(name="开发厂")
    session.add(tenant)
    session.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="裁断", code="cut", is_active=True)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", is_active=True)
    session.add_all([cut, stitch])
    session.flush()
    supplier = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    category = MaterialCategory(
        tenant_id=tenant.id,
        name="皮料",
        is_active=True,
        default_consume_segment_id=cut.id,
    )
    color = Color(tenant_id=tenant.id, name="黑皮", code="BK")
    unit = PricingUnit(tenant_id=tenant.id, name="米", is_active=True)
    session.add_all([supplier, category, color, unit])
    session.flush()
    active = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        category_id=category.id,
        color_id=color.id,
        pricing_unit_id=unit.id,
        product_code="SP-1",
        name="黑皮",
        unit_price=Decimal("12.5"),
        is_active=True,
    )
    second = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        category_id=category.id,
        product_code="SP-2",
        name="里布",
        unit_price=Decimal("3"),
        is_active=True,
    )
    stopped = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="SP-OFF",
        name="停用料",
        is_active=False,
    )
    user = Employee(tenant_id=tenant.id, name="管理员", username="admin", is_active=True)
    session.add_all([active, second, stopped, user])
    session.commit()

    content = _xlsx(
        [
            ["物料编号", "用量", "消耗部门"],
            ["SP-1", 2, "针车部"],
            ["SP-2", None, None],
            ["NOPE", 1, "针车"],
            ["SP-1", 3, "裁断"],
            ["SP-OFF", 1, "针车"],
        ]
    )
    client = _client(session)
    try:
        headers = {"Authorization": f"Bearer {create_access_token(user)}"}
        template = client.get("/api/v1/own-products/materials/import-template", headers=headers)
        assert template.status_code == 200
        assert template.content[:2] == b"PK"

        res = client.post(
            "/api/v1/own-products/materials/import",
            headers=headers,
            files={
                "file": (
                    "产品物料.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["failed"] == 3
        assert len(body["items"]) == 2
        first, blank = body["items"]
        assert "bom_color_name" not in first
        assert first["qty"] == "2"
        assert first["qty_set"] is True
        assert first["consume_segment_set"] is True
        assert first["consume_segment_id"] == stitch.id
        assert first["supplier_product"]["product_code"] == "SP-1"
        assert first["supplier_product"]["name"] == "黑皮"
        assert first["supplier_product"]["unit_price"] == "12.5"
        assert first["supplier_product"]["category_id"] == category.id
        assert blank["supplier_product"]["product_code"] == "SP-2"
        assert blank["qty_set"] is False
        assert blank["consume_segment_set"] is False
        messages = [item["message"] for item in body["errors"]]
        assert "物料不存在" in messages
        assert any("重复" in item for item in messages)
        assert "物料已停用" in messages
    finally:
        app.dependency_overrides.clear()
