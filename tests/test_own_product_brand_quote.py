"""产品特殊品牌报价：新建销售订单行取价品牌 > 客户 > 统一。"""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import OwnProduct, OwnProductBrandQuote, OwnProductQuote, Partner, Tenant
from app.services.sales_order_service import _resolve_line_unit_price


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_resolve_line_unit_price_brand_over_customer_over_unified():
    db = _session()
    tenant = Tenant(name="品牌报价厂")
    db.add(tenant)
    db.flush()
    customer = Partner(
        tenant_id=tenant.id,
        name="客户甲",
        short_name="甲",
        is_customer=True,
        is_active=True,
    )
    db.add(customer)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="BQ-01",
        quote_price=Decimal("100"),
        is_active=True,
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductQuote(
            tenant_id=tenant.id,
            own_product_id=product.id,
            partner_id=customer.id,
            quote_price=Decimal("90"),
        )
    )
    db.add(
        OwnProductBrandQuote(
            tenant_id=tenant.id,
            own_product_id=product.id,
            brand_name="Nike",
            quote_price=Decimal("80"),
        )
    )
    db.commit()

    # 品牌优先
    assert _resolve_line_unit_price(
        db, tenant.id, product.id, customer.id, None, brand_name="nike"
    ) == Decimal("80.00")
    # 无品牌匹配 → 客户价
    assert _resolve_line_unit_price(
        db, tenant.id, product.id, customer.id, None, brand_name="Adidas"
    ) == Decimal("90.00")
    # 无客户 → 统一价
    assert _resolve_line_unit_price(
        db, tenant.id, product.id, None, None, brand_name=None
    ) == Decimal("100.00")
    # 显式单价最高优先
    assert _resolve_line_unit_price(
        db, tenant.id, product.id, customer.id, Decimal("70"), brand_name="Nike"
    ) == Decimal("70.00")
    db.close()
