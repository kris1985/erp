#!/usr/bin/env python3
"""把两个真实待入库箱走完报工/入库，形成“同工厂型号、不同客户品牌”演示。

默认只预览；传入 --apply 才写入。目标箱必须已有销售明细且尚未出货。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee, PackingCarton, PackingPlan, Partner, SalesOrder, SalesOrderLine
from app.services.fg_service import warehouse_carton
from app.services.report_service import submit_carton_report


BRAND_BY_CUSTOMER = {
    "美步": ("轻跃运动", "MB-OPRUN-01"),
    "欧恋": ("北辰运动", "OL-OPRUN-01"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--worker-id", type=int, default=28)
    parser.add_argument("--carton-ids", type=int, nargs="+", default=[512, 513])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        worker = db.get(Employee, args.worker_id)
        if not worker or worker.tenant_id != args.tenant_id or not worker.is_active:
            raise RuntimeError("演示报工人员不存在或未启用")

        targets: list[tuple[PackingCarton, SalesOrderLine, SalesOrder, str, str]] = []
        product_ids: set[int] = set()
        for carton_id in args.carton_ids:
            carton = db.get(PackingCarton, carton_id)
            if not carton or carton.tenant_id != args.tenant_id:
                raise RuntimeError(f"箱 {carton_id} 不存在")
            if carton.shipment_id:
                raise RuntimeError(f"箱 {carton.code} 已出货，不能作为在库演示")
            plan = db.get(PackingPlan, carton.plan_id)
            line = db.get(SalesOrderLine, plan.sales_order_line_id) if plan else None
            sales_order = db.get(SalesOrder, line.sales_order_id) if line else None
            if not plan or not line or not sales_order:
                raise RuntimeError(f"箱 {carton.code} 缺销售来源")
            config = BRAND_BY_CUSTOMER.get(sales_order.customer_name)
            if not config:
                raise RuntimeError(f"客户 {sales_order.customer_name} 未配置演示品牌")
            brand_name, customer_sku = config
            targets.append((carton, line, sales_order, brand_name, customer_sku))
            product_ids.add(int(line.own_product_id))
        if len(product_ids) != 1:
            raise RuntimeError("目标箱不是同一工厂型号，不能演示同款多品牌")

        for carton, _, sales_order, brand_name, customer_sku in targets:
            print(
                f"{carton.code}: 客户={sales_order.customer_name}, "
                f"品牌={brand_name}, 客户货号={customer_sku}, 数量={carton.total_qty}"
            )
        if not args.apply:
            print("当前为预览；确认后加 --apply 执行。")
            return 0

        for carton, line, sales_order, brand_name, customer_sku in targets:
            brand = db.scalar(
                select(Partner).where(
                    Partner.tenant_id == args.tenant_id,
                    Partner.name == brand_name,
                )
            )
            if not brand:
                brand = Partner(
                    tenant_id=args.tenant_id,
                    name=brand_name,
                    short_name=brand_name,
                    is_brand=True,
                    is_active=True,
                    notes="成品仓同款多品牌演示",
                )
                db.add(brand)
                db.flush()
            else:
                brand.is_brand = True
                brand.is_active = True

            line.brand_id = brand.id
            line.brand_name = brand_name
            line.customer_sku = customer_sku
            carton.sales_order_id = sales_order.id
            carton.sales_order_line_id = line.id
            carton.customer_id = sales_order.customer_id
            carton.customer_name = sales_order.customer_name
            carton.brand_id = brand.id
            carton.brand_name = brand_name
            carton.customer_sku = customer_sku
        db.commit()

        for carton, _, _, _, _ in targets:
            if not carton.reported_work_log_id:
                submit_carton_report(
                    db,
                    tenant_id=args.tenant_id,
                    worker_id=args.worker_id,
                    carton_code=carton.code,
                )
            db.refresh(carton)
            if not carton.warehoused_at:
                warehouse_carton(
                    db,
                    tenant_id=args.tenant_id,
                    carton_id=carton.id,
                    note="同款多品牌成品仓演示入库",
                    created_by=args.worker_id,
                )
        print(f"完成：{len(targets)} 箱已按品牌归属入库")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
