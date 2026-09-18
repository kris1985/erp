#!/usr/bin/env python3
"""从既有收付单据幂等补齐「总账」经营流水（现金口径）。

口径：收款登记 / 付款登记 / 工资 / 日常开支 / 预支；
出货与采购挂账不入账，并作废历史挂账类流水。

用法:
  python scripts/backfill_business_ledger.py           # 全部租户
  python scripts/backfill_business_ledger.py 1         # 指定租户 id

幂等：同一 source_type+source_id 只保留一行；可重复执行。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.db_schema import ensure_schema
from app.models import Tenant
from app.services import ledger_service


def main() -> int:
    ensure_schema()
    tenant_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        if tenant_id is not None:
            t = db.get(Tenant, tenant_id)
            if not t:
                print(f"ERROR: tenant {tenant_id} not found", file=sys.stderr)
                return 1
            results = [
                {
                    "tenant_id": t.id,
                    "tenant_name": t.name,
                    "counts": ledger_service.backfill_tenant(db, t.id),
                }
            ]
        else:
            results = ledger_service.backfill_all_tenants(db)
        db.commit()
        for r in results:
            c = r["counts"]
            print(
                f"tenant {r['tenant_id']} ({r['tenant_name']}): "
                f"voided_accrual={c.get('voided_accrual', 0)} "
                f"payment={c.get('payment', 0)} "
                f"supplier_payment={c.get('supplier_payment', 0)} "
                f"expense={c.get('daily_expense', 0)} "
                f"advance={c.get('advance', 0)} "
                f"salary={c.get('salary', 0)}"
            )
        print("==> backfill_business_ledger done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
