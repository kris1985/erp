"""灌入更真实的演示数据：多款式/工人/订单 + 近 14 日报工。

可重复执行：已有数据会跳过或补齐。用法：
  python scripts/seed_demo.py && python scripts/seed_rich_demo.py
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, update

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal, engine
from app.db_schema import ensure_schema
from app.db import Base
from app.models import (
    Color,
    MaterialCategory,
    Order,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductColor,
    OwnProductLabor,
    OwnProductMaterial,
    OwnProductOtherCost,
    OwnProductQuote,
    Partner,
    PartnerContact,
    PricingUnit,
    ProcessDefinition,
    ProcessType,
    ReportType,
    SalaryModel,
    Size,
    Station,
    SupplierProduct,
    Tenant,
    WorkLog,
    Worker,
    WorkerRole,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services.order_service import create_order
from app.services.report_service import ReportError, submit_report
from scripts.seed_demo import seed as seed_basic

random.seed(20260731)


def _ensure_labor(
    db,
    tenant_id: int,
    own_product_id: int,
    process_id: int,
    process_name: str,
    sort_order: int,
    unit_price: Decimal,
):
    labor = db.scalar(
        select(OwnProductLabor).where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id == own_product_id,
            OwnProductLabor.process_id == process_id,
        )
    )
    if not labor:
        db.add(
            OwnProductLabor(
                tenant_id=tenant_id,
                own_product_id=own_product_id,
                process_id=process_id,
                process_name=process_name,
                unit_price=unit_price,
                sort_order=sort_order,
            )
        )
    else:
        labor.process_name = process_name
        labor.unit_price = unit_price
        labor.sort_order = sort_order


def _ensure_own_product(
    db,
    tenant_id: int,
    code: str,
    process_prices: dict[str, Decimal],
    process_ids: dict,
    *,
    quote_price: Decimal | None = None,
) -> OwnProduct:
    product = db.scalar(
        select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == code)
    )
    if not product:
        product = OwnProduct(
            tenant_id=tenant_id,
            product_code=code,
            quote_price=quote_price,
            is_active=True,
        )
        db.add(product)
        db.flush()
    elif quote_price is not None and product.quote_price is None:
        product.quote_price = quote_price
    labor_total = Decimal("0")
    for i, (pname, price) in enumerate(process_prices.items(), start=1):
        _ensure_labor(db, tenant_id, product.id, process_ids[pname], pname, i, price)
        labor_total += price
    product.labor_cost = labor_total.quantize(Decimal("0.0001"))
    product.is_active = True
    return product


def _ensure_partner(
    db,
    tenant_id: int,
    name: str,
    *,
    short_name: str | None = None,
    is_customer=False,
    is_supplier=False,
    is_brand=False,
    address: str | None = None,
    notes: str | None = None,
    contacts: list[dict] | None = None,
) -> Partner:
    p = db.scalar(select(Partner).where(Partner.tenant_id == tenant_id, Partner.name == name))
    if not p:
        p = Partner(
            tenant_id=tenant_id,
            name=name,
            short_name=short_name,
            is_customer=is_customer,
            is_supplier=is_supplier,
            is_brand=is_brand,
            address=address,
            notes=notes,
        )
        db.add(p)
        db.flush()
    else:
        p.short_name = short_name or p.short_name
        p.is_customer = p.is_customer or is_customer
        p.is_supplier = p.is_supplier or is_supplier
        p.is_brand = p.is_brand or is_brand
        if address:
            p.address = address
        if notes:
            p.notes = notes
    existing = {c.name: c for c in db.scalars(
        select(PartnerContact).where(PartnerContact.partner_id == p.id)
    ).all()}
    for i, c in enumerate(contacts or []):
        if c["name"] in existing:
            row = existing[c["name"]]
            row.title = c.get("title") or row.title
            row.mobile = c.get("mobile") or row.mobile
            row.wechat = c.get("wechat") or row.wechat
            row.is_primary = bool(c.get("is_primary")) or row.is_primary
            continue
        db.add(
            PartnerContact(
                tenant_id=tenant_id,
                partner_id=p.id,
                name=c["name"],
                title=c.get("title"),
                mobile=c.get("mobile"),
                wechat=c.get("wechat"),
                is_primary=bool(c.get("is_primary")),
                sort_order=i,
            )
        )
    db.flush()
    primaries = [
        c
        for c in db.scalars(select(PartnerContact).where(PartnerContact.partner_id == p.id)).all()
        if c.is_primary
    ]
    if not primaries:
        first = db.scalar(
            select(PartnerContact).where(PartnerContact.partner_id == p.id).order_by(PartnerContact.id)
        )
        if first:
            first.is_primary = True
    elif len(primaries) > 1:
        for c in primaries[1:]:
            c.is_primary = False
    return p


def _migrate_order_customers(db, tenant_id: int) -> None:
    """历史订单客户名 → partners，并回填 customer_id。"""
    partners = db.scalars(select(Partner).where(Partner.tenant_id == tenant_id)).all()
    by_name = {p.name: p for p in partners}
    by_short = {p.short_name: p for p in partners if p.short_name}

    names = db.scalars(
        select(Order.customer_name).where(Order.tenant_id == tenant_id).distinct()
    ).all()
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        p = by_name.get(name) or by_short.get(name)
        if not p:
            for short, partner in by_short.items():
                if short and short in name:
                    p = partner
                    break
        if not p:
            p = _ensure_partner(
                db,
                tenant_id,
                name,
                short_name=name[:20],
                is_customer=True,
                contacts=[{"name": "跟单", "title": "跟单", "is_primary": True}],
            )
            by_name[p.name] = p
        else:
            p.is_customer = True
        db.execute(
            update(Order)
            .where(
                Order.tenant_id == tenant_id,
                Order.customer_name == name,
                Order.customer_id.is_(None),
            )
            .values(customer_id=p.id)
        )


def _seed_partners_and_products(db, tenant_id: int, process_ids: dict) -> dict[str, Partner]:
    brand_ol = _ensure_partner(
        db, tenant_id, "温州欧恋贸易有限公司",
        short_name="欧恋", is_customer=True, is_brand=True,
        address="温州鹿城区",
        contacts=[
            {"name": "林经理", "title": "业务", "mobile": "13900001101", "is_primary": True},
            {"name": "小陈", "title": "跟单", "mobile": "13900001102"},
        ],
    )
    brand_chen = _ensure_partner(
        db, tenant_id, "广州陈姐档口",
        short_name="陈姐", is_customer=True,
        contacts=[{"name": "陈姐", "title": "老板", "mobile": "13900001201", "is_primary": True}],
    )
    brand_li = _ensure_partner(
        db, tenant_id, "杭州李姐女鞋",
        short_name="李姐", is_customer=True, is_brand=True,
        contacts=[{"name": "李姐", "title": "老板", "mobile": "13900001301", "is_primary": True}],
    )
    _ensure_partner(
        db, tenant_id, "厦门海丝进出口",
        short_name="海丝", is_customer=True,
        contacts=[{"name": "阿海", "title": "采购", "mobile": "13900001401", "is_primary": True}],
    )
    _ensure_partner(
        db, tenant_id, "义乌小商品城·阿强",
        short_name="阿强", is_customer=True,
        contacts=[{"name": "阿强", "title": "老板", "is_primary": True}],
    )
    _ensure_partner(
        db, tenant_id, "东莞美步鞋业",
        short_name="美步", is_customer=True, is_brand=True,
        contacts=[{"name": "美姐", "title": "跟单", "mobile": "13900001501", "is_primary": True}],
    )

    _ensure_partner(
        db, tenant_id, "晋江腾达鞋材",
        short_name="腾达鞋材", is_supplier=True, address="晋江陈埭",
        notes="鞋底、中底",
        contacts=[
            {"name": "老蔡", "title": "业务", "mobile": "13700002101", "wechat": "cai_tengda", "is_primary": True},
            {"name": "阿敏", "title": "跟单", "mobile": "13700002102"},
            {"name": "财务小周", "title": "财务", "mobile": "13700002103"},
        ],
    )
    _ensure_partner(
        db, tenant_id, "东莞华瑞面料",
        short_name="华瑞面料", is_supplier=True, address="东莞厚街",
        notes="网布、超纤",
        contacts=[
            {"name": "王姐", "title": "业务", "mobile": "13700002201", "is_primary": True},
            {"name": "阿杰", "title": "仓管", "mobile": "13700002202"},
        ],
    )
    _ensure_partner(
        db, tenant_id, "温州立信辅料",
        short_name="立信辅料", is_supplier=True, address="温州龙湾",
        notes="鞋带、魔术贴、包装",
        contacts=[
            {"name": "立哥", "title": "业务", "mobile": "13700002301", "is_primary": True},
            {"name": "小玲", "title": "跟单", "mobile": "13700002302"},
            {"name": "会计小张", "title": "财务", "mobile": "13700002303"},
        ],
    )
    _ensure_partner(
        db, tenant_id, "泉州兴发皮革",
        short_name="兴发皮革", is_supplier=True, address="泉州晋江",
        notes="牛皮、二层皮",
        contacts=[
            {"name": "老兴", "title": "业务", "mobile": "13700002401", "is_primary": True},
            {"name": "阿芬", "title": "跟单", "mobile": "13700002402"},
        ],
    )
    _ensure_partner(
        db, tenant_id, "永嘉精工五金",
        short_name="精工五金", is_supplier=True, address="温州永嘉",
        notes="气眼、鞋扣、饰钉",
        contacts=[
            {"name": "精哥", "title": "业务", "mobile": "13700002501", "is_primary": True},
            {"name": "小美", "title": "仓管", "mobile": "13700002502"},
        ],
    )
    db.commit()

    _seed_supplier_products(db, tenant_id)

    _migrate_order_customers(db, tenant_id)
    db.commit()
    return {"欧恋": brand_ol, "陈姐": brand_chen, "李姐": brand_li}


def _ensure_named(
    db,
    model,
    tenant_id: int,
    name: str,
    *,
    sort_order: int = 0,
):
    row = db.scalar(select(model).where(model.tenant_id == tenant_id, model.name == name))
    if not row:
        row = model(tenant_id=tenant_id, name=name, sort_order=sort_order, is_active=True)
        db.add(row)
        db.flush()
    return row


_COLOR_RGB = {
    "黑": (42, 45, 52),
    "白": (245, 246, 248),
    "深蓝": (36, 74, 138),
    "卡其": (176, 148, 104),
    "米白": (236, 228, 210),
    "红": (180, 54, 54),
}

_CATEGORY_ACCENT = {
    "皮料": (120, 78, 52),
    "面料网布": (70, 110, 160),
    "超纤革": (90, 90, 100),
    "鞋底中底": (55, 55, 60),
    "鞋垫内里": (130, 150, 170),
    "五金扣": (150, 150, 155),
    "拉链": (80, 90, 100),
    "线材": (100, 100, 110),
    "鞋带魔术贴": (60, 70, 80),
    "装饰件": (170, 150, 90),
    "包装材料": (140, 160, 145),
}


def _ensure_sp_demo_image(
    product_code: str,
    *,
    name: str | None = None,
    color_name: str | None = None,
    category: str | None = None,
) -> str:
    """优先使用已下载的真实物料图；没有时再生成占位图。"""
    uploads = Path(get_settings().uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in product_code)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        dest = uploads / f"sp_{safe}{ext}"
        if dest.is_file() and dest.stat().st_size > 1000:
            return f"/uploads/{dest.name}"

    # 回退：生成一张可区分的占位图
    from PIL import Image, ImageDraw, ImageFont

    dest = uploads / f"sp_{safe}.png"
    url = f"/uploads/{dest.name}"
    fill = _COLOR_RGB.get(color_name or "", _CATEGORY_ACCENT.get(category or "", (90, 120, 160)))
    luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    ink = (28, 32, 40) if luminance > 160 else (255, 255, 255)
    muted = (70, 76, 88) if luminance > 160 else (220, 224, 232)

    img = Image.new("RGB", (480, 480), fill)
    draw = ImageDraw.Draw(img)
    stripe = tuple(min(255, c + 18) for c in fill)
    for y in range(0, 480, 24):
        draw.rectangle([0, y, 480, y + 8], fill=stripe)
    draw.rounded_rectangle([28, 28, 452, 452], radius=28, outline=ink, width=3)
    draw.rounded_rectangle([40, 40, 440, 440], radius=22, outline=muted, width=1)

    font_paths = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    font_title = font_code = font_meta = None
    for fp in font_paths:
        if not Path(fp).exists():
            continue
        try:
            font_title = ImageFont.truetype(fp, 36)
            font_code = ImageFont.truetype(fp, 22)
            font_meta = ImageFont.truetype(fp, 20)
            break
        except OSError:
            continue
    if font_title is None:
        font_title = font_code = font_meta = ImageFont.load_default()

    title = (name or product_code)[:10]
    meta = " · ".join(x for x in [color_name, category] if x) or "物料"

    def _center_text(text: str, y: int, font, fill_color):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((480 - tw) / 2, y), text, font=font, fill=fill_color)

    _center_text(title, 180, font_title, ink)
    _center_text(product_code, 240, font_code, muted)
    _center_text(meta, 290, font_meta, muted)
    img.save(dest, format="PNG", optimize=True)
    return url


def _ensure_supplier_product(
    db,
    tenant_id: int,
    product_code: str,
    *,
    partner_id: int,
    category_id: int | None = None,
    pricing_unit_id: int | None = None,
    color_id: int | None = None,
    name: str | None = None,
    internal_code: str | None = None,
    unit_price: Decimal | None = None,
    image_url: str | None = None,
):
    p = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.product_code == product_code,
        )
    )
    if not p:
        p = SupplierProduct(
            tenant_id=tenant_id,
            product_code=product_code,
            partner_id=partner_id,
        )
        db.add(p)
        db.flush()
    p.partner_id = partner_id
    p.category_id = category_id
    p.pricing_unit_id = pricing_unit_id
    p.color_id = color_id
    p.name = name
    p.internal_code = internal_code
    p.unit_price = unit_price
    if image_url:
        p.image_url = image_url
    p.is_active = True
    return p


def _seed_supplier_products(db, tenant_id: int) -> None:
    """物料分类 / 计价单位 / 供应商产品演示数据。"""
    categories = {
        name: _ensure_named(db, MaterialCategory, tenant_id, name, sort_order=i)
        for i, name in enumerate(
            [
                "皮料",
                "面料网布",
                "超纤革",
                "鞋底中底",
                "鞋垫内里",
                "五金扣",
                "拉链",
                "线材",
                "胶水化工",
                "鞋带魔术贴",
                "装饰件",
                "包装材料",
                "模具楦头",
                "其他辅料",
            ]
        )
    }
    units = {
        name: _ensure_named(db, PricingUnit, tenant_id, name, sort_order=i)
        for i, name in enumerate(["双", "米", "码", "公斤", "个", "套", "卷", "打", "片"])
    }
    colors = {
        c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant_id)).all()
    }
    suppliers = {
        p.short_name: p
        for p in db.scalars(
            select(Partner).where(Partner.tenant_id == tenant_id, Partner.is_supplier.is_(True))
        ).all()
        if p.short_name
    }
    db.flush()

    catalog = [
        # code, name, supplier, category, unit, color, internal, unit_price
        ("TD-RB-001", "橡胶大底", "腾达鞋材", "鞋底中底", "双", "黑", "厂内-大底黑", "8.50"),
        ("TD-RB-002", "橡胶大底", "腾达鞋材", "鞋底中底", "双", "白", "厂内-大底白", "8.80"),
        ("TD-MD-010", "EVA中底", "腾达鞋材", "鞋底中底", "双", "米白", "厂内-中底", "3.20"),
        ("TD-YG-003", "TPR沿条", "腾达鞋材", "鞋底中底", "米", None, "厂内-沿条", "1.15"),
        ("HR-MESH-01", "飞织网布", "华瑞面料", "面料网布", "米", "黑", "飞织黑", "12.00"),
        ("HR-MESH-02", "飞织网布", "华瑞面料", "面料网布", "米", "白", "飞织白", "12.00"),
        ("HR-MESH-03", "飞织网布", "华瑞面料", "面料网布", "米", "深蓝", "飞织蓝", "13.50"),
        ("HR-SF-11", "超纤革1.2", "华瑞面料", "超纤革", "米", "黑", "超纤1.2黑", "18.00"),
        ("HR-SF-12", "超纤革1.2", "华瑞面料", "超纤革", "米", "卡其", "超纤1.2卡其", "18.50"),
        ("LX-LACE-01", "扁鞋带120", "立信辅料", "鞋带魔术贴", "双", "黑", "扁带120", "0.35"),
        ("LX-LACE-02", "扁鞋带120", "立信辅料", "鞋带魔术贴", "双", "白", "扁带120白", "0.35"),
        ("LX-VL-05", "魔术贴25mm", "立信辅料", "鞋带魔术贴", "米", "黑", "魔术贴25mm", "0.80"),
        ("LX-BOX-01", "天地盖鞋盒", "立信辅料", "包装材料", "个", None, "天地盖鞋盒", "1.20"),
        ("LX-TAG-02", "吊牌", "立信辅料", "包装材料", "个", None, "吊牌", "0.08"),
        ("XF-NL-01", "头层牛皮", "兴发皮革", "皮料", "尺", "黑", "头层牛皮黑", "6.80"),
        ("XF-NL-02", "头层牛皮", "兴发皮革", "皮料", "尺", "米白", "头层牛皮米白", "7.20"),
        ("XF-SL-03", "二层皮", "兴发皮革", "皮料", "尺", "卡其", "二层皮卡其", "3.50"),
        ("JG-EYE-01", "气眼5mm", "精工五金", "五金扣", "千个", "黑", "气眼5mm黑", "28.00"),
        ("JG-EYE-02", "气眼5mm", "精工五金", "五金扣", "千个", "白", "气眼5mm银", "30.00"),
        ("JG-BUCK-03", "D扣25mm", "精工五金", "五金扣", "个", "黑", "D扣25mm", "0.45"),
        ("JG-DECO-04", "金属标牌", "精工五金", "装饰件", "个", "黑", "金属标牌", "0.90"),
        ("LX-ZIP-01", "尼龙拉链#5", "立信辅料", "拉链", "条", "黑", "尼龙拉链#5", "1.10"),
        ("HR-THREAD-1", "邦线40s", "华瑞面料", "线材", "卷", "黑", "邦线40s", "15.00"),
        ("TD-PAD-01", "EVA鞋垫", "腾达鞋材", "鞋垫内里", "双", "黑", "EVA鞋垫", "1.60"),
    ]

    # 皮料常用「尺」不在默认单位里，补上
    if "尺" not in units:
        units["尺"] = _ensure_named(db, PricingUnit, tenant_id, "尺", sort_order=20)
    if "千个" not in units:
        units["千个"] = _ensure_named(db, PricingUnit, tenant_id, "千个", sort_order=21)
    if "条" not in units:
        units["条"] = _ensure_named(db, PricingUnit, tenant_id, "条", sort_order=22)
    db.flush()

    for code, name, supplier_key, cat_name, unit_name, color_name, internal, price in catalog:
        partner = suppliers.get(supplier_key)
        if not partner:
            continue
        image_url = _ensure_sp_demo_image(
            code, name=name, color_name=color_name, category=cat_name
        )
        _ensure_supplier_product(
            db,
            tenant_id,
            code,
            partner_id=partner.id,
            category_id=categories[cat_name].id if cat_name in categories else None,
            pricing_unit_id=units[unit_name].id if unit_name in units else None,
            color_id=colors.get(color_name) if color_name else None,
            name=name,
            internal_code=internal,
            unit_price=Decimal(price),
            image_url=image_url,
        )
    db.commit()
    _seed_own_products(db, tenant_id)


def _seed_own_products(db, tenant_id: int) -> None:
    """自己产品开发演示：成品编号 + 多色 + 供应商物料 + 工序人工成本。"""
    colors = {
        c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant_id)).all()
    }
    sp_by_code = {
        p.product_code: p
        for p in db.scalars(
            select(SupplierProduct).where(SupplierProduct.tenant_id == tenant_id)
        ).all()
    }
    process_by_name = {
        p.name: p
        for p in db.scalars(
            select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant_id)
        ).all()
    }
    customers = {
        (p.short_name or p.name): p
        for p in db.scalars(
            select(Partner).where(
                Partner.tenant_id == tenant_id,
                (Partner.is_customer.is_(True)) | (Partner.is_brand.is_(True)),
            )
        ).all()
    }

    uploads_dir = Path(get_settings().uploads_dir)

    material_sets = [
        [
            ("HR-MESH-01", "1.2"),
            ("HR-SF-11", "0.4"),
            ("TD-RB-001", "1"),
            ("TD-MD-010", "1"),
            ("LX-LACE-01", "1"),
            ("JG-EYE-01", "0.012"),
        ],
        [
            ("XF-NL-01", "2.5"),
            ("HR-SF-11", "0.3"),
            ("TD-RB-001", "1"),
            ("LX-ZIP-01", "1"),
            ("JG-BUCK-03", "2"),
            ("TD-PAD-01", "1"),
        ],
        [
            ("HR-MESH-01", "1.0"),
            ("TD-PAD-01", "1"),
            ("LX-LACE-01", "1"),
            ("TD-RB-001", "1"),
        ],
        [
            ("XF-NL-01", "1.8"),
            ("HR-SF-11", "0.5"),
            ("TD-MD-010", "1"),
            ("JG-EYE-01", "0.01"),
            ("LX-ZIP-01", "1"),
        ],
    ]
    labor_sets = [
        [("裁断", "2.50"), ("针车", "4.80"), ("成型", "3.20"), ("包装", "1.50")],
        [("裁断", "3.00"), ("针车", "5.50"), ("成型", "4.00"), ("包装", "1.80")],
        [("裁断", "2.20"), ("针车", "4.20"), ("成型", "2.80"), ("包装", "1.20")],
        [("裁断", "2.80"), ("针车", "5.00"), ("成型", "3.60"), ("包装", "1.60")],
    ]
    color_sets = [
        ["黑", "白", "深蓝"],
        ["黑", "卡其"],
        ["白", "红"],
        ["黑", "白"],
        ["深蓝", "卡其"],
        ["黑"],
        ["白", "黑", "红"],
        ["卡其", "白"],
    ]
    quote_sets = [
        [("陈姐", "68.00"), ("李姐", "72.00"), ("欧恋", "75.00")],
        [("美步", "98.00"), ("海丝", "105.00"), ("阿强", "92.00")],
        [("陈姐", "58.00"), ("美步", "62.00")],
        [("李姐", "88.00"), ("海丝", "90.00")],
        [("欧恋", "79.00")],
        [("阿强", "55.00"), ("陈姐", "56.00")],
        [("美步", "120.00"), ("李姐", "118.00"), ("海丝", "125.00")],
        [("陈姐", "45.00")],
    ]

    defs = [
        {
            "code": "OP-RUN-01",
            "quote_price": "69.00",
            "order_qty": 1200,
            "color_names": color_sets[0],
            "materials": material_sets[0],
            "labors": labor_sets[0],
            "quotes": quote_sets[0],
        },
        {
            "code": "OP-BOOT-01",
            "quote_price": "99.00",
            "order_qty": 680,
            "color_names": color_sets[1],
            "materials": material_sets[1],
            "labors": labor_sets[1],
            "quotes": quote_sets[1],
        },
        {
            "code": "OP-SLIP-02",
            "quote_price": "59.00",
            "order_qty": 2400,
            "color_names": color_sets[2],
            "materials": material_sets[2],
            "labors": labor_sets[2],
            "quotes": quote_sets[2],
        },
        {
            "code": "OP-HIKE-03",
            "quote_price": "128.00",
            "order_qty": 420,
            "color_names": color_sets[3],
            "materials": material_sets[1],
            "labors": labor_sets[1],
            "quotes": quote_sets[3],
        },
        {
            "code": "OP-KIDS-04",
            "quote_price": "48.00",
            "order_qty": 3600,
            "color_names": color_sets[6],
            "materials": material_sets[2],
            "labors": labor_sets[2],
            "quotes": quote_sets[5],
        },
        {
            "code": "OP-CITY-05",
            "quote_price": "78.00",
            "order_qty": 960,
            "color_names": color_sets[4],
            "materials": material_sets[0],
            "labors": labor_sets[3],
            "quotes": quote_sets[4],
        },
        {
            "code": "OP-SAND-06",
            "quote_price": "42.00",
            "order_qty": 1800,
            "color_names": color_sets[5],
            "materials": material_sets[3],
            "labors": labor_sets[2],
            "quotes": quote_sets[7],
        },
        {
            "code": "OP-PRO-07",
            "quote_price": "156.00",
            "order_qty": 260,
            "color_names": color_sets[0],
            "materials": material_sets[1],
            "labors": labor_sets[1],
            "quotes": quote_sets[6],
        },
        {
            "code": "OP-LITE-08",
            "quote_price": "55.00",
            "order_qty": 2100,
            "color_names": color_sets[7],
            "materials": material_sets[2],
            "labors": labor_sets[0],
            "quotes": quote_sets[2],
        },
        {
            "code": "OP-WINTER-09",
            "quote_price": "138.00",
            "order_qty": 540,
            "color_names": color_sets[1],
            "materials": material_sets[3],
            "labors": labor_sets[3],
            "quotes": quote_sets[1],
        },
        {
            "code": "OP-TRAIN-10",
            "quote_price": "86.00",
            "order_qty": 1500,
            "color_names": color_sets[3],
            "materials": material_sets[0],
            "labors": labor_sets[0],
            "quotes": quote_sets[0],
        },
        {
            "code": "OP-CASUAL-11",
            "quote_price": "66.00",
            "order_qty": 1320,
            "color_names": color_sets[2],
            "materials": material_sets[2],
            "labors": labor_sets[2],
            "quotes": quote_sets[4],
        },
    ]

    for idx, item in enumerate(defs):
        p = db.scalar(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id, OwnProduct.product_code == item["code"]
            )
        )
        if not p:
            p = OwnProduct(
                tenant_id=tenant_id,
                product_code=item["code"],
                material_cost=Decimal("0"),
                quote_price=None,
                labor_cost=Decimal("0"),
                other_cost=Decimal("0"),
                order_qty=0,
                is_active=True,
            )
            db.add(p)
            db.flush()

        # 优先使用百度搜到的真实成品图 op_{code}.jpg
        code = item["code"]
        own_img = None
        if uploads_dir.is_dir():
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                cand = uploads_dir / f"op_{code}{ext}"
                if cand.is_file() and cand.stat().st_size > 1000:
                    own_img = f"/uploads/{cand.name}"
                    break
        if own_img:
            p.image_url = own_img

        p.order_qty = int(item.get("order_qty") or 0)
        p.quote_price = Decimal(item["quote_price"]) if item.get("quote_price") else None

        # 颜色
        existing_colors = {
            c.color_id: c
            for c in db.scalars(
                select(OwnProductColor).where(OwnProductColor.own_product_id == p.id)
            ).all()
        }
        for name in item["color_names"]:
            cid = colors.get(name)
            if not cid or cid in existing_colors:
                continue
            db.add(OwnProductColor(tenant_id=tenant_id, own_product_id=p.id, color_id=cid))

        # 物料：按产品清空后重建，保证演示单价与总价正确
        for old in db.scalars(
            select(OwnProductMaterial).where(OwnProductMaterial.own_product_id == p.id)
        ).all():
            db.delete(old)
        db.flush()

        total = Decimal("0")
        for i, (code, qty_s) in enumerate(item["materials"]):
            sp = sp_by_code.get(code)
            if not sp:
                continue
            qty = Decimal(qty_s)
            unit_price = Decimal(sp.unit_price or 0)
            line = (qty * unit_price).quantize(Decimal("0.0001"))
            total += line
            db.add(
                OwnProductMaterial(
                    tenant_id=tenant_id,
                    own_product_id=p.id,
                    supplier_product_id=sp.id,
                    qty=qty,
                    unit_price=unit_price,
                    line_total=line,
                    sort_order=i,
                )
            )
        p.material_cost = total.quantize(Decimal("0.0001"))

        # 人工工序：清空后按演示单价重建
        for old in db.scalars(
            select(OwnProductLabor).where(OwnProductLabor.own_product_id == p.id)
        ).all():
            db.delete(old)
        db.flush()

        labor_total = Decimal("0")
        for i, (pname, price_s) in enumerate(item["labors"]):
            process = process_by_name.get(pname)
            if not process:
                continue
            unit_price = Decimal(price_s)
            labor_total += unit_price
            db.add(
                OwnProductLabor(
                    tenant_id=tenant_id,
                    own_product_id=p.id,
                    process_id=process.id,
                    process_name=pname,
                    unit_price=unit_price,
                    sort_order=i,
                )
            )
        p.labor_cost = labor_total.quantize(Decimal("0.0001"))

        for old in db.scalars(
            select(OwnProductOtherCost).where(OwnProductOtherCost.own_product_id == p.id)
        ).all():
            db.delete(old)
        db.flush()
        other_items = [("包装辅料", "2.00"), ("运输摊销", "1.50")]
        other_total = Decimal("0")
        for i, (oname, amt_s) in enumerate(other_items):
            amt = Decimal(amt_s)
            other_total += amt
            db.add(
                OwnProductOtherCost(
                    tenant_id=tenant_id,
                    own_product_id=p.id,
                    name=oname,
                    amount=amt,
                    sort_order=i,
                )
            )
        p.other_cost = other_total.quantize(Decimal("0.0001"))

        for old in db.scalars(
            select(OwnProductQuote).where(OwnProductQuote.own_product_id == p.id)
        ).all():
            db.delete(old)
        db.flush()
        for i, (cname, price_s) in enumerate(item.get("quotes") or []):
            partner = customers.get(cname)
            if not partner:
                continue
            db.add(
                OwnProductQuote(
                    tenant_id=tenant_id,
                    own_product_id=p.id,
                    partner_id=partner.id,
                    quote_price=Decimal(price_s),
                    sort_order=i,
                )
            )
        p.is_active = True
    db.commit()


def _ensure_worker(
    db,
    tenant_id: int,
    name: str,
    mobile: str,
    *,
    salary_model=SalaryModel.pure_piece,
    base_salary=Decimal("0"),
    base_quota=0,
    role=WorkerRole.worker,
    must_change=False,
):
    settings = get_settings()
    w = db.scalar(select(Worker).where(Worker.tenant_id == tenant_id, Worker.mobile == mobile))
    if not w:
        w = db.scalar(select(Worker).where(Worker.tenant_id == tenant_id, Worker.name == name))
    if not w:
        w = Worker(tenant_id=tenant_id, name=name, mobile=mobile, role=role)
        db.add(w)
        db.flush()
    w.name = name
    w.mobile = mobile
    w.password_hash = hash_password(settings.worker_default_password)
    # 演示账号：已改过密，避免每次登录都跳改密页
    w.must_change_password = must_change
    w.is_active = True
    w.salary_model = salary_model
    w.base_salary = base_salary
    w.base_quota = base_quota
    w.role = role
    return w


def _ensure_assign(db, tenant_id: int, order: Order, process_name: str, worker_quotas: list[tuple[Worker, int | None]]):
    process = next((p for p in order.processes if p.process_name == process_name), None)
    if not process:
        return
    for worker, quota in worker_quotas:
        row = db.scalar(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.order_process_id == process.id,
                OrderProcessAssignment.worker_id == worker.id,
            )
        )
        if not row:
            db.add(
                OrderProcessAssignment(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    order_process_id=process.id,
                    worker_id=worker.id,
                    quota_qty=quota,
                )
            )
        else:
            # 演示灌数时放宽配额，避免拦报工
            if quota is None or (row.quota_qty is not None and row.quota_qty < (quota or 0)):
                row.quota_qty = quota
    if worker_quotas:
        process.assigned_worker_id = worker_quotas[0][0].id


def _ensure_order(
    db,
    tenant_id: int,
    *,
    order_no: str,
    customer: str,
    own_product_id: int,
    delivery: date | None,
    notes: str,
    items: list[OrderItemIn],
    customer_id: int | None = None,
) -> Order:
    order = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))
    if order:
        order.customer_name = customer
        if customer_id:
            order.customer_id = customer_id
        if delivery:
            order.delivery_date = delivery
        if notes:
            order.notes = notes
        return order
    return create_order(
        db,
        tenant_id,
        OrderCreate(
            order_no=order_no,
            customer_id=customer_id,
            customer_name=customer,
            own_product_id=own_product_id,
            delivery_date=delivery,
            notes=notes,
            items=items,
        ),
        created_by=None,
    )


def _report(
    db,
    *,
    tenant_id: int,
    worker_id: int,
    order_no: str,
    process_name: str,
    qty: int,
    when: datetime,
    color: str | None = None,
    size: str | None = None,
    defect: int = 0,
    report_type: str = "normal",
    source: str = "manual",
    station_id: int | None = None,
    text: str | None = None,
):
    if qty <= 0 and defect <= 0:
        return
    try:
        result = submit_report(
            db,
            tenant_id=tenant_id,
            worker_id=worker_id,
            order_no=order_no,
            process_name=process_name,
            qualified_qty=qty,
            defect_qty=defect,
            color_name=color,
            size_value=size,
            original_text=text or f"{order_no} {process_name} 做了{qty}双",
            source=source,
            confirm_over_plan=True,
            report_type=report_type,
            station_id=station_id,
        )
    except ReportError as e:
        print(f"  skip report {order_no}/{process_name}/{qty}: {e.message}")
        return

    log_ids = list(result.get("work_log_ids") or [])
    if result.get("work_log_id") and result["work_log_id"] not in log_ids:
        log_ids.append(result["work_log_id"])
    if log_ids:
        db.execute(update(WorkLog).where(WorkLog.id.in_(log_ids)).values(created_at=when))
        db.commit()


def seed_rich():
    seed_basic()
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    db = SessionLocal()
    today = date.today()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        assert tenant

        # ---- 色 / 码 ----
        for name, code in [("红", "R"), ("黑", "BK"), ("白", "W"), ("米白", "IV"), ("深蓝", "NB"), ("卡其", "KH")]:
            if not db.scalar(select(Color).where(Color.tenant_id == tenant.id, Color.name == name)):
                db.add(Color(tenant_id=tenant.id, name=name, code=code))
        for i, v in enumerate(["35", "36", "37", "38", "39", "40", "41", "42"]):
            if not db.scalar(select(Size).where(Size.tenant_id == tenant.id, Size.size_value == v)):
                db.add(Size(tenant_id=tenant.id, size_value=v, sort_order=i))
        db.flush()

        process_ids = {
            p.name: p.id
            for p in db.scalars(select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant.id)).all()
        }

        # ---- 订单用产品（A/B/C 款，含工序单价）----
        product_a = _ensure_own_product(
            db,
            tenant.id,
            "A款",
            {"裁断": Decimal("0.30"), "针车": Decimal("0.50"), "成型": Decimal("0.80"), "包装": Decimal("0.20")},
            process_ids,
            quote_price=Decimal("68.00"),
        )
        product_b = _ensure_own_product(
            db,
            tenant.id,
            "B款",
            {"裁断": Decimal("0.35"), "针车": Decimal("0.65"), "成型": Decimal("0.95"), "包装": Decimal("0.25")},
            process_ids,
            quote_price=Decimal("98.00"),
        )
        product_c = _ensure_own_product(
            db,
            tenant.id,
            "C款",
            {"裁断": Decimal("0.45"), "针车": Decimal("0.85"), "成型": Decimal("1.20"), "包装": Decimal("0.30")},
            process_ids,
            quote_price=Decimal("120.00"),
        )
        db.commit()

        # ---- 客户/品牌/供应商 + OP-* 产品开发演示 ----
        partners = _seed_partners_and_products(db, tenant.id, process_ids)

        colors = {c.name: c.id for c in db.scalars(select(Color).where(Color.tenant_id == tenant.id))}
        sizes = {s.size_value: s.id for s in db.scalars(select(Size).where(Size.tenant_id == tenant.id))}

        # ---- 工人 ----
        workers = {
            "张三": _ensure_worker(db, tenant.id, "张三", "13800138001", salary_model=SalaryModel.pure_piece),
            "李四": _ensure_worker(
                db, tenant.id, "李四", "13800138002",
                salary_model=SalaryModel.base_plus_piece, base_salary=Decimal("2000"), base_quota=1000,
            ),
            "王五": _ensure_worker(db, tenant.id, "王五", "13800138003", salary_model=SalaryModel.pure_piece),
            "赵六": _ensure_worker(db, tenant.id, "赵六", "13800138004", salary_model=SalaryModel.pure_piece),
            "陈美丽": _ensure_worker(db, tenant.id, "陈美丽", "13800138005", salary_model=SalaryModel.pure_piece),
            "刘强": _ensure_worker(
                db, tenant.id, "刘强", "13800138006",
                salary_model=SalaryModel.base_plus_piece, base_salary=Decimal("1800"), base_quota=800,
            ),
            "周芳": _ensure_worker(db, tenant.id, "周芳", "13800138007", salary_model=SalaryModel.pure_piece),
            "吴明": _ensure_worker(db, tenant.id, "吴明", "13800138008", role=WorkerRole.leader),
            "孙伟": _ensure_worker(db, tenant.id, "孙伟", "13800138009", salary_model=SalaryModel.fixed, base_salary=Decimal("4500")),
            "郑秀英": _ensure_worker(db, tenant.id, "郑秀英", "13800138010", salary_model=SalaryModel.pure_piece),
        }
        # 演示方便：员工视为已改密
        for w in workers.values():
            w.must_change_password = False
        db.commit()

        # ---- 工位 ----
        for code, name, pname, loc in [
            ("CT-01", "裁断1号机", "裁断", "一车间裁断区"),
            ("CT-02", "裁断2号机", "裁断", "一车间裁断区"),
            ("ZC-01", "针车1号位", "针车", "一车间A排"),
            ("ZC-02", "针车2号位", "针车", "一车间A排"),
            ("ZC-03", "针车3号位", "针车", "一车间B排"),
            ("ZC-04", "针车4号位", "针车", "一车间B排"),
            ("CX-01", "成型小组台", "成型", "二车间"),
            ("CX-02", "成型2号线", "成型", "二车间"),
            ("BZ-01", "包装台", "包装", "成品仓旁"),
        ]:
            if not db.scalar(select(Station).where(Station.tenant_id == tenant.id, Station.code == code)):
                db.add(
                    Station(
                        tenant_id=tenant.id,
                        code=code,
                        name=name,
                        process_id=process_ids[pname],
                        location=loc,
                    )
                )
        db.commit()
        stations = {s.code: s for s in db.scalars(select(Station).where(Station.tenant_id == tenant.id))}

        # 清掉无客户名的临时空单
        junk = db.scalar(
            select(Order).where(Order.tenant_id == tenant.id, Order.order_no == "26072401")
        )
        if junk and (not junk.customer_name or junk.customer_name.strip() == ""):
            junk.status = OrderStatus.cancelled
            junk.notes = (junk.notes or "") + "（演示数据已作废）"

        # ---- 订单画像 ----
        # 急单：交期已过，进度慢 → 看板「交期风险」
        o_rush = _ensure_order(
            db, tenant.id,
            order_no="260718",
            customer="温州欧恋贸易有限公司",
            customer_id=partners["欧恋"].id,
            own_product_id=product_c.id,
            delivery=today - timedelta(days=2),
            notes="客户催货·短靴急单",
            items=[
                OrderItemIn(color_id=colors["黑"], size_id=sizes["37"], qty=200),
                OrderItemIn(color_id=colors["黑"], size_id=sizes["38"], qty=280),
                OrderItemIn(color_id=colors["黑"], size_id=sizes["39"], qty=220),
            ],
        )
        # 主力在制：交期临近
        o_main = _ensure_order(
            db, tenant.id,
            order_no="230711",
            customer="广州陈姐档口",
            customer_id=partners["陈姐"].id,
            own_product_id=product_a.id,
            delivery=today + timedelta(days=3),
            notes="网面跑步鞋·主推单",
            items=[
                OrderItemIn(color_id=colors["红"], size_id=sizes["37"], qty=400),
                OrderItemIn(color_id=colors["红"], size_id=sizes["38"], qty=400),
                OrderItemIn(color_id=colors["红"], size_id=sizes["39"], qty=400),
            ],
        )
        # 并行在制
        o_parallel = _ensure_order(
            db, tenant.id,
            order_no="230712",
            customer="杭州李姐女鞋",
            customer_id=partners["李姐"].id,
            own_product_id=product_a.id,
            delivery=today + timedelta(days=8),
            notes="黑款并行，扫码可换单",
            items=[
                OrderItemIn(color_id=colors["黑"], size_id=sizes["38"], qty=300),
                OrderItemIn(color_id=colors["黑"], size_id=sizes["39"], qty=300),
            ],
        )
        # 老爹鞋新单：刚开工
        o_new = _ensure_order(
            db, tenant.id,
            order_no="260725",
            customer="厦门海丝进出口",
            customer_id=db.scalar(
                select(Partner.id).where(Partner.tenant_id == tenant.id, Partner.short_name == "海丝")
            ),
            own_product_id=product_b.id,
            delivery=today + timedelta(days=14),
            notes="厚底老爹鞋·本周新开",
            items=[
                OrderItemIn(color_id=colors["米白"], size_id=sizes["36"], qty=150),
                OrderItemIn(color_id=colors["米白"], size_id=sizes["37"], qty=250),
                OrderItemIn(color_id=colors["米白"], size_id=sizes["38"], qty=250),
                OrderItemIn(color_id=colors["深蓝"], size_id=sizes["39"], qty=150),
            ],
        )
        # 接近完工
        o_almost = _ensure_order(
            db, tenant.id,
            order_no="260710",
            customer="义乌小商品城·阿强",
            customer_id=db.scalar(
                select(Partner.id).where(Partner.tenant_id == tenant.id, Partner.short_name == "阿强")
            ),
            own_product_id=product_b.id,
            delivery=today + timedelta(days=1),
            notes="尾数包装中",
            items=[
                OrderItemIn(color_id=colors["白"], size_id=sizes["37"], qty=200),
                OrderItemIn(color_id=colors["白"], size_id=sizes["38"], qty=200),
                OrderItemIn(color_id=colors["卡其"], size_id=sizes["39"], qty=100),
            ],
        )
        # 已完成
        o_done = _ensure_order(
            db, tenant.id,
            order_no="260701",
            customer="东莞美步鞋业",
            customer_id=db.scalar(
                select(Partner.id).where(Partner.tenant_id == tenant.id, Partner.short_name == "美步")
            ),
            own_product_id=product_a.id,
            delivery=today - timedelta(days=5),
            notes="已交齐入库",
            items=[
                OrderItemIn(color_id=colors["红"], size_id=sizes["38"], qty=300),
                OrderItemIn(color_id=colors["黑"], size_id=sizes["39"], qty=300),
            ],
        )
        db.commit()
        _migrate_order_customers(db, tenant.id)
        db.commit()

        # 刷新 processes
        for o in (o_rush, o_main, o_parallel, o_new, o_almost, o_done):
            db.refresh(o, attribute_names=["processes", "items"])

        # ---- 派工（宽配额，方便灌数）----
        _ensure_assign(db, tenant.id, o_main, "裁断", [(workers["王五"], None), (workers["孙伟"], None)])
        _ensure_assign(db, tenant.id, o_main, "针车", [(workers["张三"], None), (workers["陈美丽"], None), (workers["周芳"], None)])
        _ensure_assign(db, tenant.id, o_main, "成型", [(workers["张三"], None), (workers["李四"], None), (workers["刘强"], None)])
        _ensure_assign(db, tenant.id, o_main, "包装", [(workers["郑秀英"], None)])

        _ensure_assign(db, tenant.id, o_parallel, "裁断", [(workers["王五"], None)])
        _ensure_assign(db, tenant.id, o_parallel, "针车", [(workers["张三"], None), (workers["赵六"], None)])
        _ensure_assign(db, tenant.id, o_parallel, "成型", [(workers["李四"], None), (workers["刘强"], None)])
        _ensure_assign(db, tenant.id, o_parallel, "包装", [(workers["郑秀英"], None)])

        _ensure_assign(db, tenant.id, o_rush, "裁断", [(workers["王五"], None)])
        _ensure_assign(db, tenant.id, o_rush, "针车", [(workers["陈美丽"], None), (workers["周芳"], None)])
        _ensure_assign(db, tenant.id, o_rush, "成型", [(workers["李四"], None), (workers["刘强"], None)])
        _ensure_assign(db, tenant.id, o_rush, "包装", [(workers["郑秀英"], None)])

        _ensure_assign(db, tenant.id, o_new, "裁断", [(workers["王五"], None), (workers["孙伟"], None)])
        _ensure_assign(db, tenant.id, o_new, "针车", [(workers["赵六"], None), (workers["周芳"], None)])
        _ensure_assign(db, tenant.id, o_new, "成型", [(workers["张三"], None), (workers["李四"], None)])
        _ensure_assign(db, tenant.id, o_new, "包装", [(workers["郑秀英"], None)])

        _ensure_assign(db, tenant.id, o_almost, "裁断", [(workers["王五"], None)])
        _ensure_assign(db, tenant.id, o_almost, "针车", [(workers["张三"], None), (workers["赵六"], None)])
        _ensure_assign(db, tenant.id, o_almost, "成型", [(workers["李四"], None), (workers["刘强"], None)])
        _ensure_assign(db, tenant.id, o_almost, "包装", [(workers["郑秀英"], None), (workers["吴明"], None)])

        _ensure_assign(db, tenant.id, o_done, "裁断", [(workers["王五"], None)])
        _ensure_assign(db, tenant.id, o_done, "针车", [(workers["张三"], None), (workers["陈美丽"], None)])
        _ensure_assign(db, tenant.id, o_done, "成型", [(workers["李四"], None), (workers["刘强"], None)])
        _ensure_assign(db, tenant.id, o_done, "包装", [(workers["郑秀英"], None)])
        db.commit()

        # 若已有较丰富报工则跳过重复灌数（按标记单 260718 的报工量判断）
        existing_rich = db.scalar(
            select(WorkLog.id).where(WorkLog.tenant_id == tenant.id, WorkLog.order_id == o_rush.id).limit(1)
        )
        rich_count = db.scalar(
            select(WorkLog).where(WorkLog.tenant_id == tenant.id).limit(1)
        )
        # 用「急单是否已有足够报工」作幂等
        rush_qty = sum(
            (p.completed_qty for p in o_rush.processes),
            0,
        )
        if rush_qty >= 200 and db.scalar(
            select(WorkLog.id).where(WorkLog.tenant_id == tenant.id, WorkLog.order_id == o_almost.id).limit(1)
        ):
            print("Rich demo work logs already present, skip reporting. Masters/orders refreshed.")
            _seed_supply_chain_demo(db, tenant.id)
            _print_summary(db, tenant.id)
            return

        print("==> Generating work logs over last 14 days …")

        def day_at(offset: int, hour: int, minute: int = 0) -> datetime:
            d = today - timedelta(days=offset)
            return datetime(d.year, d.month, d.day, hour, minute, 0)

        # —— 已完成单：过去两周做完 ——
        for day, process, worker, qty, color, size, src in [
            (18, "裁断", "王五", 300, "红", "38", "manual"),
            (17, "裁断", "王五", 300, "黑", "39", "qrcode"),
            (16, "针车", "张三", 200, "红", "38", "qrcode"),
            (15, "针车", "陈美丽", 200, "红", "38", "voice"),
            (14, "针车", "张三", 200, "黑", "39", "qrcode"),
            (13, "成型", "李四", 300, "红", "38", "manual"),
            (12, "成型", "刘强", 300, "黑", "39", "manual"),
            (11, "包装", "郑秀英", 300, "红", "38", "manual"),
            (10, "包装", "郑秀英", 300, "黑", "39", "qrcode"),
        ]:
            # 成型是集体工序：submit_report 会自动 group
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="260701",
                process_name=process,
                qty=qty,
                when=day_at(day, 9 + (day % 5), 10),
                color=color,
                size=size,
                source=src,
                station_id=(stations.get("ZC-01").id if process == "针车" else None),
            )

        # —— 急单 260718：裁断做完、针车卡住、成型很少 ——
        for day, process, worker, qty, color, size in [
            (9, "裁断", "王五", 250, "黑", "37"),
            (8, "裁断", "王五", 250, "黑", "38"),
            (7, "裁断", "王五", 200, "黑", "39"),
            (6, "针车", "陈美丽", 80, "黑", "37"),
            (5, "针车", "周芳", 70, "黑", "38"),
            (4, "针车", "陈美丽", 60, "黑", "39"),
            (3, "成型", "李四", 40, "黑", "37"),
            (2, "成型", "刘强", 30, "黑", "38"),
        ]:
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="260718",
                process_name=process,
                qty=qty,
                when=day_at(day, 10, 20),
                color=color,
                size=size,
                source=random.choice(["qrcode", "voice", "manual"]),
                defect=random.choice([0, 0, 0, 2, 5]),
                station_id=(stations["ZC-03"].id if process == "针车" else None),
            )
        # 返修几笔
        _report(
            db, tenant_id=tenant.id, worker_id=workers["周芳"].id, order_no="260718",
            process_name="针车", qty=20, when=day_at(1, 15, 0), color="黑", size="38",
            report_type="rework", source="voice", text="260718 黑 38码 针车 返修了20双",
        )

        # —— 主力 230711：裁断近完、针车过半、成型进行中 ——
        plan_main = [
            # day_offset, process, worker, qty, color, size, defect
            (12, "裁断", "王五", 200, "红", "37", 0),
            (11, "裁断", "王五", 200, "红", "38", 0),
            (10, "裁断", "孙伟", 200, "红", "39", 0),
            (9, "裁断", "王五", 250, "红", "37", 3),
            (8, "裁断", "孙伟", 250, "红", "38", 0),
            (7, "针车", "张三", 120, "红", "37", 0),
            (6, "针车", "陈美丽", 100, "红", "38", 2),
            (5, "针车", "周芳", 110, "红", "39", 0),
            (4, "针车", "张三", 130, "红", "37", 0),
            (3, "针车", "陈美丽", 90, "红", "38", 0),
            (2, "针车", "周芳", 100, "红", "39", 4),
            (1, "针车", "张三", 80, "红", "38", 0),
            (0, "针车", "张三", 70, "红", "37", 0),
            (5, "成型", "李四", 80, "红", "37", 0),
            (3, "成型", "刘强", 90, "红", "38", 0),
            (1, "成型", "李四", 70, "红", "39", 0),
            (0, "成型", "刘强", 60, "红", "37", 0),
            (0, "包装", "郑秀英", 40, "红", "37", 0),
        ]
        for day, process, worker, qty, color, size, defect in plan_main:
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="230711",
                process_name=process,
                qty=qty,
                when=day_at(day, 8 + (day % 6), 15 + (qty % 40)),
                color=color,
                size=size,
                defect=defect,
                source="qrcode" if process == "针车" else random.choice(["manual", "voice"]),
                station_id=(stations["ZC-01"].id if process == "针车" and worker == "张三" else None),
            )

        # —— 并行单 230712 ——
        for day, process, worker, qty, color, size in [
            (6, "裁断", "王五", 200, "黑", "38"),
            (5, "裁断", "王五", 200, "黑", "39"),
            (4, "针车", "赵六", 100, "黑", "38"),
            (3, "针车", "张三", 90, "黑", "39"),
            (2, "针车", "赵六", 80, "黑", "38"),
            (1, "成型", "李四", 50, "黑", "38"),
            (0, "针车", "张三", 60, "黑", "39"),
        ]:
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="230712",
                process_name=process,
                qty=qty,
                when=day_at(day, 11, 30),
                color=color,
                size=size,
                source=random.choice(["qrcode", "manual"]),
            )

        # —— 新单 260725：刚裁断 ——
        for day, process, worker, qty, color, size in [
            (2, "裁断", "王五", 150, "米白", "36"),
            (1, "裁断", "孙伟", 200, "米白", "37"),
            (0, "裁断", "王五", 180, "米白", "38"),
            (0, "针车", "赵六", 40, "米白", "37"),
        ]:
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="260725",
                process_name=process,
                qty=qty,
                when=day_at(day, 14, 0),
                color=color,
                size=size,
                source="manual",
            )

        # —— 尾数单 260710：几乎做完 ——
        for day, process, worker, qty, color, size in [
            (10, "裁断", "王五", 250, "白", "37"),
            (9, "裁断", "王五", 250, "白", "38"),
            (8, "裁断", "王五", 100, "卡其", "39"),
            (7, "针车", "张三", 200, "白", "37"),
            (6, "针车", "赵六", 200, "白", "38"),
            (5, "针车", "张三", 100, "卡其", "39"),
            (4, "成型", "李四", 250, "白", "37"),
            (3, "成型", "刘强", 250, "白", "38"),
            (2, "成型", "李四", 100, "卡其", "39"),
            (1, "包装", "郑秀英", 220, "白", "37"),
            (1, "包装", "吴明", 200, "白", "38"),
            (0, "包装", "郑秀英", 60, "卡其", "39"),
        ]:
            _report(
                db,
                tenant_id=tenant.id,
                worker_id=workers[worker].id,
                order_no="260710",
                process_name=process,
                qty=qty,
                when=day_at(day, 9, 45),
                color=color,
                size=size,
                source=random.choice(["qrcode", "manual", "voice"]),
            )
        # 尾数加价演示
        _report(
            db, tenant_id=tenant.id, worker_id=workers["郑秀英"].id, order_no="260710",
            process_name="包装", qty=20, when=day_at(0, 16, 20), color="白", size="38",
            report_type="tail", source="manual", text="260710 白 38码 包装 尾数了20双",
        )

        # 补数演示（主力单）
        _report(
            db, tenant_id=tenant.id, worker_id=workers["张三"].id, order_no="230711",
            process_name="针车", qty=15, when=day_at(0, 17, 5), color="红", size="39",
            report_type="supplement", source="voice", text="230711 红 39码 针车 补数了15双",
            station_id=stations["ZC-01"].id,
        )

        db.commit()
        _seed_trace_demo(db, tenant.id, workers)
        _seed_supply_chain_demo(db, tenant.id)
        _print_summary(db, tenant.id)
    finally:
        db.close()


def _seed_trace_demo(db, tenant_id: int, workers: dict):
    """演示捆标 + 不良：开启一款追溯，从针车报工打捆并登记不良。"""
    from sqlalchemy import func

    from app.models import DefectEvent, TraceUnit
    from app.services import trace_service

    product = db.scalar(
        select(OwnProduct)
        .join(Order, Order.own_product_id == OwnProduct.id)
        .where(Order.tenant_id == tenant_id, Order.order_no == "230711")
        .limit(1)
    )
    if not product:
        product = db.scalar(select(OwnProduct).where(OwnProduct.tenant_id == tenant_id).limit(1))
    if not product:
        return
    product.trace_enabled = True
    db.commit()

    existing = db.scalar(select(TraceUnit).where(TraceUnit.tenant_id == tenant_id).limit(1))
    if existing:
        print(f"trace demo already present: {existing.code}")
        return

    log = db.scalar(
        select(WorkLog)
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.qualified_qty > 0,
            WorkLog.process_id.is_not(None),
        )
        .order_by(WorkLog.id.desc())
        .limit(1)
    )
    if not log:
        return

    unit = trace_service.create_bundle_from_work_log(
        db, tenant_id=tenant_id, work_log_id=log.id, commit=True
    )
    # 再挂一条下游报工流水（演示历程）
    zhang = workers.get("张三")
    if zhang:
        from app.models import TraceUnitAction, TraceUnitLog, TraceUnitStatus

        unit.status = TraceUnitStatus.in_process
        db.add(
            TraceUnitLog(
                tenant_id=tenant_id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.report,
                worker_id=zhang.id,
                process_id=log.process_id,
                qty=min(20, unit.qty),
                note="演示下游报工",
            )
        )
        db.commit()

    defect_count = db.scalar(
        select(func.count()).select_from(DefectEvent).where(DefectEvent.tenant_id == tenant_id)
    )
    if not defect_count:
        process_id = log.process_id
        event = trace_service.create_defect_event(
            db,
            tenant_id=tenant_id,
            defect_type="open_seam",
            qty=2,
            trace_unit_id=unit.id,
            found_process_id=process_id,
            responsible_process_id=process_id,
            disposition="rework",
            found_by_worker_id=workers.get("李四").id if workers.get("李四") else None,
            note="演示：质检开线",
            auto_suggest_worker=True,
        )
        print(f"trace demo: bundle={unit.code} defect=#{event.id}")
    else:
        print(f"trace demo: bundle={unit.code}")


def _seed_shared_pool_for_orders(db, tenant_id: int) -> None:
    """给库存池灌料：覆盖在制单缺口 + 常用物料底仓，方便演示「从池分配」。"""
    from app.models import OrderMaterialRequirement, SharedMaterialStock, SharedLedgerType
    from app.services import material_service

    open_orders = db.scalars(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.status.in_([OrderStatus.confirmed, OrderStatus.in_progress]),
        )
    ).all()
    for order in open_orders:
        material_service.ensure_material_snapshot(db, tenant_id, order)
    db.commit()

    # 各 SKU 在制缺口合计
    need_by_sp: dict[int, Decimal] = {}
    reqs = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.order_id.in_([o.id for o in open_orders] or [-1]),
        )
    ).all()
    for row in reqs:
        if row.is_customer_supplied:
            continue
        need = (row.required_qty or Decimal("0")) - (row.arrived_qty or Decimal("0"))
        if need > 0:
            need_by_sp[row.supplier_product_id] = need_by_sp.get(row.supplier_product_id, Decimal("0")) + need

    # 产品 BOM 用到的物料也给底仓
    bom_sp_ids = {
        m.supplier_product_id
        for m in db.scalars(
            select(OwnProductMaterial).where(OwnProductMaterial.tenant_id == tenant_id)
        ).all()
    }
    all_sps = db.scalars(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.is_active.is_(True),
        )
    ).all()

    topped = 0
    for sp in all_sps:
        stock = db.scalar(
            select(SharedMaterialStock).where(
                SharedMaterialStock.tenant_id == tenant_id,
                SharedMaterialStock.supplier_product_id == sp.id,
            )
        )
        current = stock.qty if stock else Decimal("0")
        open_need = need_by_sp.get(sp.id, Decimal("0"))
        # 目标：缺口 1.5 倍 + 底仓；BOM 料底仓更大
        floor = Decimal("300") if sp.id in bom_sp_ids or open_need > 0 else Decimal("50")
        target = max(open_need * Decimal("1.5") + floor, floor)
        delta = target - current
        if delta <= 0:
            continue
        material_service.adjust_shared_stock(
            db,
            tenant_id,
            sp.id,
            delta,
            unit_cost=sp.unit_price or Decimal("0"),
            note="演示灌池：便于订单分配",
            ledger_type=SharedLedgerType.adjust,
            ref_type="seed_pool",
        )
        topped += 1
    db.commit()
    print(
        f"shared pool: topped {topped} SKU(s); "
        f"open-order material lines={len(reqs)} shortage-skus={len(need_by_sp)}"
    )


def _seed_supply_chain_demo(db, tenant_id: int):
    """齐料→采购到货→发车间→出货→回款演示路径（可重复执行）。"""
    from app.models import PurchaseOrder, Shipment, ShipmentStatus
    from app.services import finance_service, material_service, purchase_service, shipment_service

    # 先灌池，保证多单可分配
    _seed_shared_pool_for_orders(db, tenant_id)

    order = db.scalar(
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_([OrderStatus.confirmed, OrderStatus.in_progress]),
        )
        .order_by(Order.id.desc())
    )
    if not order:
        print("supply chain demo: skip (no open order)")
        return

    if order.unit_price is None:
        product = db.get(OwnProduct, order.own_product_id)
        order.unit_price = (product.quote_price if product and product.quote_price else Decimal("68"))
        db.commit()

    # 演示急单：另取一笔在制单标插单（不影响供应链主路径订单时可共用）
    from datetime import datetime as _dt

    rush = db.scalar(
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_([OrderStatus.confirmed, OrderStatus.in_progress]),
            Order.id != order.id,
        )
        .order_by(Order.id.asc())
    )
    if rush and not getattr(rush, "is_rush", False):
        rush.is_rush = True
        rush.rush_reason = "客户催货（演示）"
        rush.rushed_at = _dt.utcnow()
        db.commit()
        print(f"supply chain: marked rush {rush.order_no}")
    elif not rush and not getattr(order, "is_rush", False):
        order.is_rush = True
        order.rush_reason = "客户催货（演示）"
        order.rushed_at = _dt.utcnow()
        db.commit()
        print(f"supply chain: marked rush {order.order_no}")

    material_service.ensure_material_snapshot(db, tenant_id, order)
    db.commit()

    existing_po = db.scalar(
        select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id).limit(1)
    )
    if not existing_po:
        drafts = purchase_service.create_drafts_from_shortages(
            db, tenant_id, order_ids=[order.id], include_shared=False
        )
        for d in drafts:
            purchase_service.submit_po(db, tenant_id, d["id"])
            po = purchase_service.get_po(db, tenant_id, d["id"])
            purchase_service.receive_po(
                db,
                tenant_id,
                po.id,
                [{"line_id": ln.id, "qty": float(ln.qty)} for ln in po.lines],
            )
        print(f"supply chain: created {len(drafts)} PO(s) and received for {order.order_no}")
    else:
        print("supply chain: PO exists, skip create")

    kit = material_service.get_order_kit(db, tenant_id, order.id)
    db.commit()
    for line in kit.get("lines") or []:
        if float(line.get("issued_qty") or 0) <= 0 and float(line.get("arrived_qty") or 0) > 0:
            try:
                material_service.release_to_workshop(
                    db,
                    tenant_id,
                    order.id,
                    line["id"],
                    Decimal(str(min(float(line["arrived_qty"]), float(line["required_qty"])))),
                    deduct_shared=False,
                )
            except material_service.MaterialError as e:
                # 强制领料开启时跳过轻量发车间
                print(f"supply chain: skip release ({e.code})")
                break

    shipped = db.scalar(
        select(Shipment).where(
            Shipment.tenant_id == tenant_id,
            Shipment.order_id == order.id,
            Shipment.status == ShipmentStatus.shipped,
        )
    )
    if not shipped:
        delivery = shipment_service.order_delivery_summary(db, tenant_id, order.id)
        lines = []
        for it in delivery["items"]:
            q = min(10, int(it["backlog_qty"]))
            if q > 0:
                lines.append({"order_item_id": it["order_item_id"], "qty": q})
        if lines:
            sh = shipment_service.create_shipment(
                db,
                tenant_id,
                order_id=order.id,
                lines=lines,
                confirm=True,
                logistics_company="演示物流",
                tracking_no="DEMO888",
            )
            print(f"supply chain: shipment {sh['shipment_no']} amount={sh['amount']}")
            ars = finance_service.list_receivables(db, tenant_id, order_id=order.id)
            open_ars = [a for a in ars if a["status"] in ("open", "partial") and float(a["balance"]) > 0]
            if open_ars:
                a0 = open_ars[0]
                finance_service.create_payment(
                    db,
                    tenant_id,
                    customer_id=a0.get("customer_id"),
                    customer_name=a0["customer_name"],
                    amount=Decimal(str(a0["balance"])),
                    payment_date=date.today(),
                    method="wechat",
                    allocations=[{"receivable_id": a0["id"], "amount": a0["balance"]}],
                )
                print("supply chain: payment allocated")
    else:
        print(f"supply chain: shipment exists {shipped.shipment_no}")

    pnl = finance_service.order_profit(db, tenant_id, order.id)
    print(
        f"supply chain profit {order.order_no}: revenue={pnl['revenue']} "
        f"gross={pnl['gross_profit']} (estimated)"
    )


def _print_summary(db, tenant_id: int):
    from sqlalchemy import func

    n_orders = db.scalar(select(func.count()).select_from(Order).where(Order.tenant_id == tenant_id))
    n_workers = db.scalar(select(func.count()).select_from(Worker).where(Worker.tenant_id == tenant_id))
    n_logs = db.scalar(select(func.count()).select_from(WorkLog).where(WorkLog.tenant_id == tenant_id))
    n_partners = db.scalar(select(func.count()).select_from(Partner).where(Partner.tenant_id == tenant_id))
    n_contacts = db.scalar(
        select(func.count()).select_from(PartnerContact).where(PartnerContact.tenant_id == tenant_id)
    )
    n_sp = db.scalar(
        select(func.count()).select_from(SupplierProduct).where(SupplierProduct.tenant_id == tenant_id)
    )
    n_own = db.scalar(
        select(func.count()).select_from(OwnProduct).where(OwnProduct.tenant_id == tenant_id)
    )
    from app.models import DefectEvent, SharedMaterialStock, TraceUnit

    n_tu = db.scalar(select(func.count()).select_from(TraceUnit).where(TraceUnit.tenant_id == tenant_id))
    n_de = db.scalar(select(func.count()).select_from(DefectEvent).where(DefectEvent.tenant_id == tenant_id))
    pool_rows = db.scalars(
        select(SharedMaterialStock).where(
            SharedMaterialStock.tenant_id == tenant_id,
            SharedMaterialStock.qty > 0,
        )
    ).all()
    pool_total = sum((r.qty or 0) for r in pool_rows)
    print("\n======== Rich demo ready ========")
    print(
        f"workers={n_workers} partners={n_partners} contacts={n_contacts} "
        f"supplier_products={n_sp} own_products={n_own} orders={n_orders} work_logs={n_logs} "
        f"trace_units={n_tu} defects={n_de}"
    )
    print(f"shared pool: {len(pool_rows)} SKU with stock, qty_sum={pool_total}")
    for o in db.scalars(select(Order).where(Order.tenant_id == tenant_id).order_by(Order.order_no)).all():
        pcts = []
        for p in o.processes:
            pct = round(100 * p.completed_qty / p.plan_qty, 0) if p.plan_qty else 0
            pcts.append(f"{p.process_name}{int(pct)}%")
        st = o.status.value if hasattr(o.status, "value") else o.status
        print(f"  {o.order_no} {o.customer_name} cid={o.customer_id} [{st}] due={o.delivery_date} | {' · '.join(pcts)}")
    print("账号: admin/admin123  员工: 13800138001~010 / 默认密码见 .env")
    print("管理台: 供应商 · 供应商产品 · 产品开发 · 质量不良 · 基础资料")
    print("急单扫码演示: /scan/ZC-01  看板看交期风险: 260718")
    tu = db.scalar(select(TraceUnit).where(TraceUnit.tenant_id == tenant_id).order_by(TraceUnit.id.desc()))
    if tu:
        print(f"捆标演示: /trace/{tu.code}  打印: /trace-print/{tu.code}")


if __name__ == "__main__":
    seed_rich()
