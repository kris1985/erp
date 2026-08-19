"""工序段重构（P0/P4）：默认段 seed、迁移幂等、无组长默认组、段字段输出。

覆盖任务清单：
  2.11/C2 ensure_default_segments per-tenant 幂等
  34.1-34.10 迁移脚本幂等（38.7）+ 字段回填
  B1/1.16 无组长默认组（leader_worker_id 可空，_team_out 容错）
  5.3 _team_out 输出 segment_id / segment_name / is_default
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Department,
    MaterialCategory,
    Order,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProductMaterial,
    ProcessDefinition,
    ProcessSegment,
    Team,
    Tenant,
    WorkLog,
)
from app.services import team_service
from app.services.segment_service import ensure_default_segments


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_tenant(db, name="测试厂", with_team=True):
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    dep = Department(tenant_id=tenant.id, name="针车部")
    db.add(dep)
    db.flush()
    p1 = ProcessDefinition(tenant_id=tenant.id, name="针车", code="P01")
    p2 = ProcessDefinition(tenant_id=tenant.id, name="修边", code="P02")
    db.add_all([p1, p2])
    db.flush()
    team = None
    if with_team:
        team_out = team_service.create_team(
            db, tenant.id, name="针车一组", leader_worker_id=None, department_id=dep.id
        )
        team = db.get(Team, team_out["id"])
    cat = MaterialCategory(tenant_id=tenant.id, name="皮料", default_consume_process_id=p1.id)
    db.add(cat)
    opm = OwnProductMaterial(
        tenant_id=tenant.id, own_product_id=0, supplier_product_id=0, consume_process_id=p1.id
    )
    db.add(opm)
    order = Order(
        tenant_id=tenant.id,
        order_no="SO-T1",
        customer_name="客户A",
        own_product_id=0,
        total_qty=100,
    )
    db.add(order)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id,
        order_id=order.id,
        process_id=p1.id,
        process_name="针车",
        plan_qty=100,
    )
    db.add(op)
    db.flush()
    omr = OrderMaterialRequirement(
        tenant_id=tenant.id, order_id=order.id, supplier_product_id=0, consume_process_id=p1.id
    )
    db.add(omr)
    wl = WorkLog(
        tenant_id=tenant.id,
        worker_id=0,
        order_process_id=op.id,
        own_product_id=0,
        process_id=p1.id,
        qualified_qty=10,
    )
    db.add(wl)
    db.commit()
    return tenant, dep, p1, p2, team


def test_ensure_default_segments_idempotent_and_per_tenant():
    db = _db()
    t1 = Tenant(name="厂一")
    t2 = Tenant(name="厂二")
    db.add_all([t1, t2])
    db.flush()

    assert ensure_default_segments(db, t1.id) == 5
    assert ensure_default_segments(db, t1.id) == 0  # 幂等
    assert ensure_default_segments(db, t2.id) == 5  # per-tenant 隔离

    segs = db.scalars(select(ProcessSegment).where(ProcessSegment.tenant_id == t1.id)).all()
    codes = sorted(s.code for s in segs)
    assert codes == ["cut", "forming", "packing", "skiving", "stitch"]
    skiving = next(s for s in segs if s.code == "skiving")
    assert skiving.is_optional is True
    db.close()


def test_migration_backfills_and_idempotent():
    from scripts.migrate_process_segments import migrate_tenant

    db = _db()
    tenant, dep, p1, p2, team = _seed_tenant(db)

    stats1 = migrate_tenant(db, tenant.id)
    db.commit()
    assert stats1["segments_created"] == 5

    seg_stitch = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )

    # 部门"针车部"包含匹配 → stitch
    dep = db.get(Department, dep.id)
    assert dep.process_segment_id == seg_stitch.id
    # 工序"针车"→ stitch；"修边"未匹配 → null（D18）
    p1 = db.get(ProcessDefinition, p1.id)
    p2 = db.get(ProcessDefinition, p2.id)
    assert p1.segment_id == seg_stitch.id
    assert p2.segment_id is None
    # 班组段从部门回填（34.4）
    team = db.get(Team, team.id)
    assert team.segment_id == seg_stitch.id
    # 分类/BOM/订单快照/报工回填（34.5-34.9）
    cat = db.scalar(select(MaterialCategory).where(MaterialCategory.tenant_id == tenant.id))
    assert cat.default_consume_segment_id == seg_stitch.id
    opm = db.scalar(select(OwnProductMaterial).where(OwnProductMaterial.tenant_id == tenant.id))
    assert opm.consume_segment_id == seg_stitch.id
    op = db.scalar(select(OrderProcess).where(OrderProcess.tenant_id == tenant.id))
    assert op.segment_id == seg_stitch.id
    omr = db.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.tenant_id == tenant.id)
    )
    assert omr.consume_segment_id == seg_stitch.id
    assert omr.consume_segment_name == "针车"
    wl = db.scalar(select(WorkLog).where(WorkLog.tenant_id == tenant.id))
    assert wl.segment_id == seg_stitch.id

    # 幂等：跑第二遍无重复、不覆盖（38.7）
    stats2 = migrate_tenant(db, tenant.id)
    db.commit()
    assert stats2["segments_created"] == 0
    assert stats2["default_teams_created"] == 0
    assert (
        len(db.scalars(select(ProcessSegment).where(ProcessSegment.tenant_id == tenant.id)).all())
        == 5
    )
    tenant_row = db.get(Tenant, tenant.id)
    assert tenant_row.settings_json.get("enable_teams") is True  # 原有班组 → true
    db.close()


def test_migration_creates_leaderless_default_team_for_teamless_dept():
    from scripts.migrate_process_segments import migrate_tenant

    db = _db()
    tenant, dep, p1, p2, _team = _seed_tenant(db, with_team=False)

    # 部门先手工挂段（模拟已映射）
    from app.services.segment_service import ensure_default_segments

    ensure_default_segments(db, tenant.id)
    seg_cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    dep2 = Department(tenant_id=tenant.id, name="截断部", process_segment_id=seg_cut.id)
    db.add(dep2)
    db.commit()

    stats = migrate_tenant(db, tenant.id)
    db.commit()
    assert stats["default_teams_created"] >= 1

    # 两个挂段部门（针车部/截断部）各补一个无组长默认组
    default_teams = db.scalars(
        select(Team).where(Team.tenant_id == tenant.id, Team.is_default.is_(True))
    ).all()
    assert len(default_teams) >= 1
    cut_team = next(t for t in default_teams if t.department_id == dep2.id)
    assert cut_team.leader_worker_id is None  # B1：无组长默认组
    assert cut_team.segment_id == seg_cut.id

    # _team_out 对空组长容错 + 输出段字段（5.3）
    out = next(
        x for x in team_service.list_teams(db, tenant.id) if x["id"] == cut_team.id
    )
    assert out["leader_name"] is None
    assert out["segment_id"] == seg_cut.id
    assert out["segment_name"] == "截断"
    assert out["is_default"] is True

    tenant_row = db.get(Tenant, tenant.id)
    assert tenant_row.settings_json.get("enable_teams") is False  # 原无班组 → false
    db.close()


def test_team_out_includes_segment_fields():
    db = _db()
    tenant, dep, p1, p2, team = _seed_tenant(db)
    from app.services.segment_service import ensure_default_segments

    ensure_default_segments(db, tenant.id)
    seg_stitch = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )
    team = db.get(Team, team.id)
    team.segment_id = seg_stitch.id
    db.commit()

    out = next(x for x in team_service.list_teams(db, tenant.id) if x["id"] == team.id)
    assert out["segment_id"] == seg_stitch.id
    assert out["segment_name"] == "针车"
    assert out["is_default"] is False
    db.close()
