#!/usr/bin/env python3
"""工序段重构数据迁移（P4 34.1-34.10）。

用法（生产机，已激活 venv、工作目录为安装根）:
  python scripts/migrate_process_segments.py

幂等：可重复执行（34.7 有幂等测试）。逐租户事务提交。
行为（与 docs/工序段重构任务清单.md P4 对齐）：
  34.1 默认 5 段（截断/针车/成型/包装/铲皮）
  34.2 工序按名称映射段（未匹配留 null，输出清单，D18 未分段）
  34.3 部门按名称映射段（未匹配留空）
  34.4 班组 segment_id 从部门回填
  34.5 OwnProductMaterial.consume_process_id → consume_segment_id
  34.6 MaterialCategory.default_consume_process_id → default_consume_segment_id
  34.7 OrderMaterialRequirement 回填 consume_segment_id/name
  34.8 OrderProcess 回填 segment_id
  34.9 WorkLog 回填 segment_id（从 OrderProcess 查）
  34.10 存量租户补默认组 + enable_teams 推断（存在任意 Team 即 true，B4/D21）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.db_schema import ensure_schema
from app.models import (
    Department,
    MaterialCategory,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProductMaterial,
    ProcessDefinition,
    Team,
    Tenant,
    WorkLog,
)
from app.services.segment_service import (
    DEPARTMENT_SEGMENT_MAP,
    PROCESS_SEGMENT_MAP,
    ensure_default_segments,
)


def _segment_by_code(db, tenant_id: int, code: str):
    from app.models import ProcessSegment

    return db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant_id,
            ProcessSegment.code == code,
        )
    )


def migrate_tenant(db, tenant_id: int) -> dict:
    """单租户迁移，返回统计。调用方负责 commit。"""
    from app.models import ProcessSegment

    stats: dict = {"segments_created": 0, "unmatched_processes": []}

    # ---- 34.1 默认段 ----
    stats["segments_created"] = ensure_default_segments(db, tenant_id)

    # ---- 34.2 工序按名称映射段 ----
    procs = db.scalars(
        select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant_id)
    ).all()
    for p in procs:
        if p.segment_id:
            continue
        code = PROCESS_SEGMENT_MAP.get(p.name)
        if not code:
            stats["unmatched_processes"].append(p.name)
            continue
        seg = _segment_by_code(db, tenant_id, code)
        if seg:
            p.segment_id = seg.id

    # ---- 34.3 部门按名称映射段（包含匹配：如"针车部"含"针车"） ----
    depts = db.scalars(
        select(Department).where(Department.tenant_id == tenant_id)
    ).all()
    for d in depts:
        if d.process_segment_id:
            continue
        code = next(
            (c for k, c in DEPARTMENT_SEGMENT_MAP.items() if k in d.name),
            None,
        )
        if not code:
            continue
        seg = _segment_by_code(db, tenant_id, code)
        if seg:
            d.process_segment_id = seg.id

    # ---- 34.4 班组 segment_id 从部门回填 ----
    teams = db.scalars(select(Team).where(Team.tenant_id == tenant_id)).all()
    for t in teams:
        if t.segment_id or not t.department_id:
            continue
        dep = db.get(Department, t.department_id)
        if dep and dep.process_segment_id:
            t.segment_id = dep.process_segment_id

    # ---- 34.5 OwnProductMaterial.consume_process_id → consume_segment_id ----
    opm_rows = db.scalars(
        select(OwnProductMaterial).where(
            OwnProductMaterial.tenant_id == tenant_id,
            OwnProductMaterial.consume_process_id.is_not(None),
        )
    ).all()
    for row in opm_rows:
        if row.consume_segment_id:
            continue
        proc = db.get(ProcessDefinition, row.consume_process_id)
        if proc and proc.segment_id:
            row.consume_segment_id = proc.segment_id

    # ---- 34.6 MaterialCategory 默认段 ----
    cats = db.scalars(
        select(MaterialCategory).where(
            MaterialCategory.tenant_id == tenant_id,
            MaterialCategory.default_consume_process_id.is_not(None),
        )
    ).all()
    for c in cats:
        if c.default_consume_segment_id:
            continue
        proc = db.get(ProcessDefinition, c.default_consume_process_id)
        if proc and proc.segment_id:
            c.default_consume_segment_id = proc.segment_id

    # ---- 34.7 OrderMaterialRequirement 回填（段 + 段名快照） ----
    omr_rows = db.scalars(
        select(OrderMaterialRequirement).where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.consume_process_id.is_not(None),
        )
    ).all()
    for row in omr_rows:
        if row.consume_segment_id:
            continue
        proc = db.get(ProcessDefinition, row.consume_process_id)
        if proc and proc.segment_id:
            seg = db.get(ProcessSegment, proc.segment_id)
            row.consume_segment_id = proc.segment_id
            if seg:
                row.consume_segment_name = seg.name

    # ---- 34.8 OrderProcess 回填 ----
    op_rows = db.scalars(
        select(OrderProcess).where(OrderProcess.tenant_id == tenant_id)
    ).all()
    for row in op_rows:
        if row.segment_id:
            continue
        proc = db.get(ProcessDefinition, row.process_id)
        if proc and proc.segment_id:
            row.segment_id = proc.segment_id

    # ---- 34.9 WorkLog 回填（从 OrderProcess 查） ----
    wl_rows = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.segment_id.is_(None),
        )
    ).all()
    for row in wl_rows:
        op = db.get(OrderProcess, row.order_process_id)
        if op and op.segment_id:
            row.segment_id = op.segment_id

    # ---- 34.10 存量租户补默认组 + enable_teams 推断（B4/D21） ----
    had_teams = (
        db.scalar(
            select(func.count()).select_from(Team).where(Team.tenant_id == tenant_id)
        )
        or 0
    ) > 0
    # 补默认组：每个挂段部门下若无任何班组，建 is_default 组（无组长，B1）
    seg_depts = db.scalars(
        select(Department).where(
            Department.tenant_id == tenant_id,
            Department.process_segment_id.is_not(None),
        )
    ).all()
    created_default_teams = 0
    for dep in seg_depts:
        has_team = (
            db.scalar(
                select(func.count()).select_from(Team).where(
                    Team.tenant_id == tenant_id,
                    Team.department_id == dep.id,
                )
            )
            or 0
        ) > 0
        if has_team:
            continue
        seg = db.get(ProcessSegment, dep.process_segment_id)
        name = f"{seg.name if seg else '默认'}组"
        # 组名唯一（uq_teams_tenant_name）；冲突时加后缀
        clash = db.scalar(
            select(Team).where(Team.tenant_id == tenant_id, Team.name == name)
        )
        if clash:
            name = f"{name}{clash.id}"
        db.add(
            Team(
                tenant_id=tenant_id,
                name=name,
                leader_worker_id=dep.leader_id,  # 可空（B1）
                department_id=dep.id,
                segment_id=dep.process_segment_id,
                is_default=True,
                is_active=True,
            )
        )
        created_default_teams += 1

    # enable_teams：按原始班组数推断（有班组即 true，无才 false）；
    # 已存在的值不覆盖（幂等，B4/D21）
    from app.models import Tenant as TenantModel

    tenant = db.get(TenantModel, tenant_id)
    settings = dict(tenant.settings_json or {})
    if "enable_teams" not in settings:
        settings["enable_teams"] = bool(had_teams)
        tenant.settings_json = settings

    stats["default_teams_created"] = created_default_teams
    stats["enable_teams"] = settings.get("enable_teams", bool(had_teams))
    return stats


def main() -> int:
    print("==> ensure_schema (工序段字段)")
    ensure_schema()

    db = SessionLocal()
    try:
        tenants = list(db.scalars(select(Tenant).order_by(Tenant.id)).all())
        print(f"==> migrate process segments for {len(tenants)} tenant(s)")
        for t in tenants:
            stats = migrate_tenant(db, t.id)
            db.commit()
            print(
                f"    tenant {t.id} ({t.name}): segments_created={stats['segments_created']}, "
                f"default_teams_created={stats['default_teams_created']}, "
                f"enable_teams={stats['enable_teams']}"
            )
            if stats["unmatched_processes"]:
                print(
                    f"      未匹配工序（留 null，D18 未分段）: "
                    f"{sorted(set(stats['unmatched_processes']))}"
                )
        print("==> done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
