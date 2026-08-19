#!/usr/bin/env python3
"""补齐常用工序（按鞋厂实际场景，按工序段归类）。

用法（生产机，已激活 venv）:
  python scripts/seed_default_processes.py            # 全部租户
  python scripts/seed_default_processes.py 1          # 指定租户

幂等：按 (tenant, code) 存在则跳过；已存在时仅补默认价/产能/人力（不覆盖手工修改的名称/类型）。
每个工序带 per_worker_capacity（双/人/天）+ standard_workers，供排产使用。
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ProcessDefinition, ProcessSegment, ProcessType, Tenant
from app.services.segment_service import ensure_default_segments

# (code, name, segment_code, type, default_price, per_worker_capacity, standard_workers, sort_order)
DEFAULT_PROCESSES: list[tuple[str, str, str, str, str, int, int, int]] = [
    # ---- 截断段 ----
    ("CT", "裁断", "cut", "personal", "0.30", 60, 1, 10),
    ("HL", "划料", "cut", "personal", "0.20", 100, 1, 20),
    ("XB", "修边", "cut", "personal", "0.15", 120, 1, 30),
    ("PB", "片帮", "cut", "personal", "0.25", 80, 1, 40),
    # ---- 针车段 ----
    ("ZC", "针车", "stitch", "personal", "0.50", 50, 2, 10),
    ("CF", "车缝", "stitch", "personal", "0.45", 45, 1, 20),
    ("HHG", "合后跟", "stitch", "personal", "0.30", 60, 1, 30),
    ("SLL", "上拉链", "stitch", "personal", "0.35", 55, 1, 40),
    ("BB", "包边", "stitch", "personal", "0.30", 60, 1, 50),
    ("XXT", "修线头", "stitch", "personal", "0.10", 150, 1, 60),
    ("YB", "验帮", "stitch", "personal", "0.05", 200, 1, 70),
    # ---- 成型段（集体计件，D22）----
    ("CX", "成型", "forming", "group", "0.80", 80, 2, 10),
    ("TX", "套楦", "forming", "group", "0.20", 90, 2, 20),
    ("SJ", "刷胶", "forming", "group", "0.15", 100, 2, 30),
    ("TD", "贴底", "forming", "group", "0.25", 80, 2, 40),
    ("YH", "压合", "forming", "group", "0.10", 120, 2, 50),
    ("TQ", "脱楦", "forming", "group", "0.15", 100, 2, 60),
    ("XJ", "修胶", "forming", "group", "0.10", 120, 2, 70),
    ("DC", "打粗", "forming", "group", "0.15", 100, 2, 80),
    ("CXD", "穿鞋带", "forming", "group", "0.10", 120, 2, 90),
    # ---- 包装段 ----
    ("BZ", "包装", "packing", "personal", "0.20", 100, 1, 10),
    ("GDP", "挂吊牌", "packing", "personal", "0.05", 200, 1, 20),
    ("DNH", "打内盒", "packing", "personal", "0.06", 180, 1, 30),
    ("ZX", "装箱", "packing", "group", "0.08", 150, 2, 40),
    ("FX", "封箱", "packing", "personal", "0.04", 200, 1, 50),
    ("YX", "验箱", "packing", "personal", "0.03", 250, 1, 60),
    # ---- 铲皮段（可选段，is_optional）----
    ("CP", "铲皮", "skiving", "personal", "0.30", 60, 1, 10),
]


def seed_default_processes(db, tenant_id: int) -> int:
    """补齐常用工序；返回新建条数。幂等（按 code）。"""
    ensure_default_segments(db, tenant_id)
    seg_by_code = {
        s.code: s
        for s in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }
    existing = {
        p.code: p
        for p in db.scalars(
            select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant_id)
        ).all()
    }
    created = 0
    for code, name, seg_code, ptype, price, capacity, workers, sort_order in DEFAULT_PROCESSES:
        seg = seg_by_code.get(seg_code)
        p = existing.get(code)
        want_type = ProcessType.group if ptype == "group" else ProcessType.personal
        if p is None:
            p = ProcessDefinition(
                tenant_id=tenant_id,
                name=name,
                code=code,
                default_price=Decimal(price),
                per_worker_capacity=Decimal(capacity),
                standard_workers=workers,
                sort_order=sort_order,
                type=want_type,
                segment_id=seg.id if seg else None,
                is_active=True,
            )
            db.add(p)
            db.flush()
            created += 1
        else:
            # 补默认价/产能/人力/段（不覆盖名称与类型）
            p.default_price = Decimal(price)
            p.per_worker_capacity = Decimal(capacity)
            p.standard_workers = workers
            if seg and not p.segment_id:
                p.segment_id = seg.id
    db.commit()
    return created


def main() -> int:
    tenant_ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        tenants = list(db.scalars(select(Tenant).order_by(Tenant.id)).all())
        if tenant_ids:
            tenants = [t for t in tenants if t.id in tenant_ids]
        print(f"==> seed default processes for {len(tenants)} tenant(s)")
        for t in tenants:
            n = seed_default_processes(db, t.id)
            print(f"    tenant {t.id} ({t.name}): created={n}, total={len(DEFAULT_PROCESSES)} 类")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
