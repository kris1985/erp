#!/usr/bin/env python3
"""运行车间经营诊断报告（周报/月报/单项分析）。

示例：
  .venv/bin/python scripts/run_analytics_report.py --kind weekly
  .venv/bin/python scripts/run_analytics_report.py --kind monthly
  .venv/bin/python scripts/run_analytics_report.py --kind delivery_risk
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.db_schema import ensure_schema
from app.models import Tenant
from app.services import analytics


def _resolve_tenant(db, name: str | None):
    settings = get_settings()
    tenant_name = (name or settings.default_tenant_name or "").strip()
    q = select(Tenant)
    if tenant_name:
        q = q.where(Tenant.name == tenant_name)
    tenant = db.scalars(q.order_by(Tenant.id)).first()
    if not tenant:
        raise SystemExit(f"未找到租户：{tenant_name or '(any)'}")
    return tenant


def main() -> int:
    parser = argparse.ArgumentParser(description="ERP 经营诊断分析")
    parser.add_argument(
        "--kind",
        default="weekly",
        choices=sorted(analytics.ANALYSIS_RUNNERS.keys()),
        help="分析类型",
    )
    parser.add_argument("--tenant", default=None, help="租户名称，默认取配置")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--year-month", default=None, help="YYYY-MM，用于人效")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        tenant = _resolve_tenant(db, args.tenant)
        params: dict = {}
        if args.year is not None:
            params["year"] = args.year
        if args.month is not None:
            params["month"] = args.month
        if args.days is not None:
            params["days"] = args.days
        if args.year_month:
            params["year_month"] = args.year_month

        result = analytics.run_analysis(db, tenant.id, args.kind, params=params)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0

        print(f"# {result.get('title') or args.kind}")
        print(f"租户：{tenant.name}  日期：{result.get('as_of')}")
        print()
        print(f"**结论：** {result.get('summary')}")
        print()
        for i, ins in enumerate(result.get("insights") or [], 1):
            sev = ins.get("severity") or "info"
            print(f"{i}. [{sev}] {ins.get('text')}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
