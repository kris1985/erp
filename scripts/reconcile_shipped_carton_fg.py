#!/usr/bin/env python3
"""补齐“箱已出货但成品账未扣减”的历史流水。

默认只预览；传入 --apply 才写入。脚本按箱幂等：已有正式/修复出库流水不会重复处理。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FgLedger, FgStock, PackingCarton


RECONCILE_REF_TYPE = "reconcile_shipped_carton"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        inbound = list(
            db.scalars(
                select(FgLedger)
                .join(
                    PackingCarton,
                    (PackingCarton.id == FgLedger.ref_id)
                    & (FgLedger.ref_type == "carton_warehouse"),
                )
                .where(
                    FgLedger.tenant_id == args.tenant_id,
                    FgLedger.direction == "in",
                    PackingCarton.tenant_id == args.tenant_id,
                    PackingCarton.warehoused_at.is_not(None),
                    PackingCarton.shipment_id.is_not(None),
                )
                .order_by(FgLedger.ref_id, FgLedger.id)
            ).all()
        )
        candidates: list[tuple[FgLedger, FgStock]] = []
        for entry in inbound:
            already_out = db.scalar(
                select(FgLedger.id).where(
                    FgLedger.tenant_id == args.tenant_id,
                    FgLedger.ref_id == entry.ref_id,
                    FgLedger.direction == "out",
                    FgLedger.ref_type.in_(("carton_ship", RECONCILE_REF_TYPE)),
                ).limit(1)
            )
            if already_out:
                continue
            stock = db.get(FgStock, entry.fg_stock_id)
            if not stock or stock.tenant_id != args.tenant_id:
                raise RuntimeError(f"箱 {entry.ref_id} 对应成品结存不存在")
            if int(stock.qty or 0) < int(entry.qty or 0):
                raise RuntimeError(
                    f"箱 {entry.ref_id} 待冲销 {entry.qty}，但结存仅 {stock.qty}，已停止"
                )
            candidates.append((entry, stock))

        carton_ids = sorted({int(entry.ref_id) for entry, _ in candidates})
        qty = sum(int(entry.qty or 0) for entry, _ in candidates)
        print(f"待修复：{len(carton_ids)} 箱 / {qty} 双；箱ID={carton_ids}")
        if not args.apply:
            print("当前为预览；确认后加 --apply 执行。")
            return 0

        for entry, stock in candidates:
            stock.qty = int(stock.qty or 0) - int(entry.qty or 0)
            db.add(
                FgLedger(
                    tenant_id=args.tenant_id,
                    fg_stock_id=entry.fg_stock_id,
                    direction="out",
                    qty=int(entry.qty or 0),
                    order_id=entry.order_id,
                    execution_id=entry.execution_id,
                    trace_unit_id=entry.trace_unit_id,
                    ref_type=RECONCILE_REF_TYPE,
                    ref_id=entry.ref_id,
                    note="历史箱已出货，补记成品出库流水",
                )
            )
        db.commit()
        print(f"修复完成：{len(carton_ids)} 箱 / {qty} 双")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
