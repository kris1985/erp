"""工序段重构（P0/P4）：默认段 seed、迁移幂等、无组长默认组、段字段输出。

覆盖任务清单：
  2.11/C2 ensure_default_segments per-tenant 幂等
  34.1-34.10 迁移脚本幂等（38.7）+ 字段回填
  B1/1.16 无组长默认组（leader_worker_id 可空，_team_out 容错）
  5.3 _team_out 输出 segment_id / segment_name / is_default
  4.3 段级齐套过滤（首段含 unlabeled，其它段仅显式归属）
"""

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    DefectEvent,
    Department,
    Employee,
    ExecutionHeader,
    MaterialCategory,
    OwnProduct,
    OwnProductLabor,
    ProcessType,
    ProductionBatch,
    ProductionBatchStatus,
    ReportType,
    TeamMember,
    WorkLog,
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
    labor = OwnProductLabor(
        tenant_id=tenant.id,
        own_product_id=0,
        process_id=p1.id,
        process_name="针车",
        unit_price=Decimal("1"),
    )
    db.add(labor)
    db.commit()
    return tenant, dep, p1, p2, team, labor


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
    tenant, dep, p1, p2, team, labor = _seed_tenant(db)

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
    # 34.11：工艺路线劳动行段回填
    labor = db.get(OwnProductLabor, labor.id)
    assert labor.segment_id == seg_stitch.id

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
    assert (tenant_row.settings_json.get("org") or {}).get("enable_teams") is True  # 原有班组 → true（org 命名空间）
    db.close()


def test_migration_creates_leaderless_default_team_for_teamless_dept():
    from scripts.migrate_process_segments import migrate_tenant

    db = _db()
    tenant, dep, p1, p2, _team, _labor = _seed_tenant(db, with_team=False)

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
    assert (tenant_row.settings_json.get("org") or {}).get("enable_teams") is False  # 原无班组 → false
    db.close()


def test_team_out_includes_segment_fields():
    db = _db()
    tenant, dep, p1, p2, team, _labor = _seed_tenant(db)
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


def test_kit_scope_by_segment_first_includes_unlabeled():
    """4.3/D16：段级齐套过滤——首段含 unlabeled，其它段仅匹配显式归属；
    by_process 仍按 process_id 索引（D16）。"""
    from app.services import material_service
    from app.services.segment_service import ensure_default_segments

    db = _db()
    tenant = Tenant(name="齐套厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    seg_cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    seg_forming = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "forming"
        )
    )

    cut = ProcessDefinition(
        tenant_id=tenant.id, name="裁断", code="CUT", segment_id=seg_cut.id
    )
    form = ProcessDefinition(
        tenant_id=tenant.id, name="成型", code="FORM", segment_id=seg_forming.id
    )
    db.add_all([cut, form])
    db.flush()

    order = Order(
        tenant_id=tenant.id,
        order_no="SO-SEG",
        customer_name="客户",
        own_product_id=0,
        total_qty=10,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=cut.id,
            process_name="裁断",
            plan_qty=10,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=form.id,
            process_name="成型",
            plan_qty=10,
        )
    )
    db.flush()

    # 面布 → 显式裁断段；大底 → 显式成型段；辅料 → 未标注（unlabeled）
    def _req(sp_id: int, seg_id: int | None) -> OrderMaterialRequirement:
        return OrderMaterialRequirement(
            tenant_id=tenant.id,
            order_id=order.id,
            supplier_product_id=sp_id,
            consume_segment_id=seg_id,
            consume_segment_name=None,
            required_qty=Decimal("1"),
        )

    db.add_all(
        [
            _req(1, seg_cut.id),
            _req(2, seg_forming.id),
            _req(3, None),  # unlabeled
        ]
    )
    db.commit()

    # 段级范围断言
    cut_scope = [
        r
        for r in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.order_id == order.id
            )
        ).all()
        if material_service.row_in_process_scope(
            r, cut.id, first_process_id=cut.id, db=db
        )
    ]
    assert {r.supplier_product_id for r in cut_scope} == {1, 3}  # 显式裁断 + unlabeled
    form_scope = [
        r
        for r in db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.order_id == order.id
            )
        ).all()
        if material_service.row_in_process_scope(
            r, form.id, first_process_id=cut.id, db=db
        )
    ]
    assert {r.supplier_product_id for r in form_scope} == {2}  # 仅显式成型段
    db.close()


def test_default_team_and_leader_sync_and_segment_cascade():
    """5.5/5.6/5.7：默认组幂等、负责人同步默认组组长、部门改段级联班组。"""
    from app.services import org_settings, team_service
    from app.services.segment_service import ensure_default_segments

    db = _db()
    tenant = Tenant(name="组织厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    seg_cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    seg_stitch = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )
    dep = Department(tenant_id=tenant.id, name="截断部", process_segment_id=seg_cut.id)
    db.add(dep)
    db.commit()

    # 5.5：创建默认组（无组长）
    t1 = team_service.ensure_default_team(db, tenant.id, dep)
    assert t1.is_default is True
    assert t1.leader_worker_id is None
    t2 = team_service.ensure_default_team(db, tenant.id, dep)  # 幂等
    assert t2.id == t1.id

    # 5.6：部门设负责人 → 默认组 leader 同步；反向不同步
    leader = Employee(tenant_id=tenant.id, name="段长", is_active=True)
    db.add(leader)
    db.flush()
    dep.leader_id = leader.id
    team_service.sync_default_team_leader(db, tenant.id, dep)
    db.commit()
    t1 = db.get(Team, t1.id)
    assert t1.leader_worker_id == leader.id
    # 反向不同步：手工换组长不写回部门
    t1.leader_worker_id = None
    db.commit()
    team_service.sync_default_team_leader(db, tenant.id, dep)  # leader_id 仍在，应补回
    t1 = db.get(Team, t1.id)
    assert t1.leader_worker_id == leader.id
    dep2 = db.get(Department, dep.id)
    assert dep2.leader_id == leader.id  # 部门字段未被覆盖

    # 5.7：部门改段 → 班组段级联
    dep = db.get(Department, dep.id)
    dep.process_segment_id = seg_stitch.id
    team_service.sync_teams_segment_for_department(db, tenant.id, dep)
    db.commit()
    t1 = db.get(Team, t1.id)
    assert t1.segment_id == seg_stitch.id

    # 6.x：开关与叫法
    assert org_settings.enable_teams(db, tenant.id) is False
    org_settings.set_enable_teams(db, tenant.id, True)
    assert org_settings.enable_teams(db, tenant.id) is True
    assert org_settings.is_skiving_enabled(db, tenant.id) is False
    org_settings.set_skiving_enabled(db, tenant.id, True)
    assert org_settings.is_skiving_enabled(db, tenant.id) is True
    assert org_settings.get_team_label(db, tenant.id) == "班组"
    org_settings.set_team_label(db, tenant.id, "产线")
    assert org_settings.get_team_label(db, tenant.id) == "产线"
    org_settings.set_team_label(db, tenant.id, "乱写")  # 非法值回落默认
    assert org_settings.get_team_label(db, tenant.id) == "班组"
    db.close()


def test_update_team_syncs_segment_on_department_change():
    """5.2：换部门 → 段自动同步。"""
    from app.services import team_service
    from app.services.segment_service import ensure_default_segments

    db = _db()
    tenant = Tenant(name="换段厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    seg_cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    seg_stitch = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "stitch"
        )
    )
    d_cut = Department(tenant_id=tenant.id, name="截断部", process_segment_id=seg_cut.id)
    d_stitch = Department(tenant_id=tenant.id, name="针车部", process_segment_id=seg_stitch.id)
    db.add_all([d_cut, d_stitch])
    db.commit()

    out = team_service.create_team(db, tenant.id, name="一组", department_id=d_cut.id)
    assert out["segment_id"] == seg_cut.id  # 建组自动继承（5.1）
    out2 = team_service.update_team(
        db, tenant.id, out["id"], department_id=d_stitch.id
    )
    assert out2["segment_id"] == seg_stitch.id  # 换部门段跟随（5.2）
    db.close()


def test_line_report_group_split_progress_defect_and_batch():
    """P7 41.1：线产量报工 = 集体拆分(技能系数) + 段内进度 + 不良登记 + 批次确认。"""
    from app.services import report_service
    from app.services.segment_service import ensure_default_segments

    db = _db()
    tenant = Tenant(name="成型线厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    seg_cut = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "cut"
        )
    )
    seg_form = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "forming"
        )
    )

    # 工序：裁断(cut) + 成型段两道（贴底/脱楦）
    cut = ProcessDefinition(tenant_id=tenant.id, name="裁断", code="C1", segment_id=seg_cut.id)
    stick = ProcessDefinition(tenant_id=tenant.id, name="贴底", code="F1", segment_id=seg_form.id)
    last = ProcessDefinition(tenant_id=tenant.id, name="脱楦", code="F2", segment_id=seg_form.id)
    db.add_all([cut, stick, last])
    db.flush()

    # 产品 + 人工单价
    product = OwnProduct(tenant_id=tenant.id, product_code="SP-1")
    db.add(product)
    db.flush()
    db.add_all(
        [
            OwnProductMaterial(tenant_id=tenant.id, own_product_id=product.id, supplier_product_id=0),
        ]
    )
    db.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id, own_product_id=product.id, process_id=stick.id,
                process_name="贴底", unit_price=Decimal("1.00"), sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id, own_product_id=product.id, process_id=last.id,
                process_name="脱楦", unit_price=Decimal("0.50"), sort_order=1,
            ),
        ]
    )
    db.flush()

    # 班组（成型段）+ 成员（不同技能系数）
    leader = Employee(tenant_id=tenant.id, name="成型组长", is_active=True, skill_factor=Decimal("1.2"))
    w1 = Employee(tenant_id=tenant.id, name="贴底工", is_active=True, skill_factor=Decimal("1.0"))
    w2 = Employee(tenant_id=tenant.id, name="刷胶工", is_active=True, skill_factor=Decimal("0.8"))
    db.add_all([leader, w1, w2])
    db.flush()
    team = Team(
        tenant_id=tenant.id, name="成型A线", leader_worker_id=leader.id,
        segment_id=seg_form.id, is_active=True,
    )
    db.add(team)
    db.flush()
    for w in (w1, w2):
        db.add(TeamMember(tenant_id=tenant.id, team_id=team.id, worker_id=w.id))
    db.flush()

    # 执行单头 + 工序（成型段两道）
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="EH-1", own_product_id=product.id, total_qty=100,
    )
    db.add(header)
    db.flush()
    op_stick = OrderProcess(
        tenant_id=tenant.id, header_id=header.id, process_id=stick.id, process_name="贴底",
        process_type=ProcessType.personal, segment_id=seg_form.id, plan_qty=100,
    )
    op_last = OrderProcess(
        tenant_id=tenant.id, header_id=header.id, process_id=last.id, process_name="脱楦",
        process_type=ProcessType.personal, segment_id=seg_form.id, plan_qty=100,
    )
    db.add_all([op_stick, op_last])
    db.flush()

    # 批次
    batch = ProductionBatch(
        tenant_id=tenant.id, batch_no="B-1", header_id=header.id,
        product_id=product.id, qty=100, status=ProductionBatchStatus.open,
    )
    db.add(batch)
    db.commit()

    # 执行线产量报工：合格97、不良3（返修1）
    res = report_service.submit_line_report(
        db,
        tenant_id=tenant.id,
        operator_id=leader.id,
        header_id=header.id,
        team_id=team.id,
        qualified_qty=97,
        defect_qty=3,
        rework_qty=1,
        batch_id=batch.id,
    )
    assert res["ok"] is True
    assert res["work_log_count"] == 3  # 组长 + 两名组员（组长参与分成，D24）

    # ① 集体拆分：权重 1.2 : 1.0 : 0.8（合计 3.0），总额=97
    logs = db.scalars(
        select(WorkLog).where(
            WorkLog.tenant_id == tenant.id, WorkLog.header_id == header.id
        )
    ).all()
    by_worker = {l.worker_id: l for l in logs}
    assert set(by_worker) == {leader.id, w1.id, w2.id}
    assert sum(l.qualified_qty for l in logs) == 97
    assert by_worker[leader.id].qualified_qty > by_worker[w1.id].qualified_qty > by_worker[w2.id].qualified_qty
    assert all(l.report_type == ReportType.group for l in logs)
    assert all(l.segment_id == seg_form.id for l in logs)
    assert all(l.batch_id == batch.id for l in logs)
    assert logs[0].group_detail["kind"] == "line_report"
    assert set(logs[0].group_detail["process_ids"]) == {op_stick.id, op_last.id}

    # ③ 段内进度：两道工序都推进
    op_stick = db.get(OrderProcess, op_stick.id)
    op_last = db.get(OrderProcess, op_last.id)
    assert op_stick.completed_qty == 97 and op_last.completed_qty == 97
    assert op_stick.defect_qty == 3 and op_last.defect_qty == 3

    # ② 不良登记（不自动扣工资）
    defect = db.scalar(select(DefectEvent).where(DefectEvent.tenant_id == tenant.id))
    assert defect is not None
    assert defect.qty == 3
    assert defect.batch_id == batch.id
    assert defect.found_process_id == stick.id

    # ④ 批次 confirmed
    batch = db.get(ProductionBatch, batch.id)
    assert batch.status == ProductionBatchStatus.confirmed

    # ⑤ 工资链路：金额=97×贴底单价(1.0)
    assert res["amount"] == 97.0
    db.close()


def test_api_process_segments_crud_and_org_setup():
    """API 层（12.1/18A）：process-segments CRUD + /org/setup 幂等。"""
    from fastapi.testclient import TestClient

    from app.auth import create_access_token
    from app.db import get_db
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    from app.models import Tenant as T2, Employee as E2

    tenant = T2(name="API厂")
    db.add(tenant)
    db.flush()
    admin = E2(tenant_id=tenant.id, name="管理员", mobile="13900000001", is_active=True)
    db.add(admin)
    db.commit()

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    token = create_access_token(admin)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    # /org/setup simple 模式
    r = client.post("/api/v1/org/setup", json={"mode": "simple"}, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["skipped"] is False
    r2 = client.post("/api/v1/org/setup", json={"mode": "simple"}, headers=headers)  # 幂等
    assert r2.json()["data"]["skipped"] is True

    # process-segments 列表 = 5（铲皮段默认创建，按 skiving_enabled 控制显示）
    r = client.get("/api/v1/process-segments", headers=headers)
    items = r.json()["data"]["items"]
    assert len(items) == 5
    assert {x["name"] for x in items} == {"截断", "针车", "成型", "包装", "铲皮"}

    # CRUD：新建 → 改 → 停用删除
    r = client.post(
        "/api/v1/process-segments",
        json={"name": "试产段", "code": "TRIAL", "sort_order": 99},
        headers=headers,
    )
    assert r.status_code == 200
    seg_id = r.json()["data"]["id"]
    r = client.patch(
        f"/api/v1/process-segments/{seg_id}",
        json={"name": "试产段2"},
        headers=headers,
    )
    assert r.json()["data"]["name"] == "试产段2"
    # 挂引用后删除 → 停用而非删
    from app.models import ProcessSegment as PS

    seg = db.get(PS, seg_id)
    seg.is_active = True
    dep = Department(tenant_id=tenant.id, name="试产部", process_segment_id=seg_id)
    db.add(dep)
    db.commit()
    r = client.delete(f"/api/v1/process-segments/{seg_id}", headers=headers)
    assert r.json()["data"]["deactivated"] is True
    app.dependency_overrides.clear()
    db.close()


def test_seed_default_processes_idempotent_and_segmented():
    """seed_default_processes：27 类常用工序按段归类；幂等（二跑 created=0）。"""
    from scripts.seed_default_processes import DEFAULT_PROCESSES, seed_default_processes

    db = _db()
    tenant = Tenant(name="工序厂")
    db.add(tenant)
    db.flush()

    created1 = seed_default_processes(db, tenant.id)
    created2 = seed_default_processes(db, tenant.id)
    assert created1 == len(DEFAULT_PROCESSES)
    assert created2 == 0

    procs = db.scalars(
        select(ProcessDefinition).where(ProcessDefinition.tenant_id == tenant.id)
    ).all()
    assert len(procs) == len(DEFAULT_PROCESSES)
    # 每道工序都挂段且产能可用（排产前提）
    assert all(p.segment_id for p in procs)
    assert all(p.per_worker_capacity and p.per_worker_capacity > 0 for p in procs)
    # 成型段工序为集体计件
    seg_form = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "forming"
        )
    )
    form_procs = [p for p in procs if p.segment_id == seg_form.id]
    assert form_procs and all(p.type == ProcessType.group for p in form_procs)
    db.close()
