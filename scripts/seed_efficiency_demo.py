"""为生产效率报表造一批多天、多工序、多人的报工+考勤演示数据。

可重复执行：会先清掉 source_type=eff_demo 的考勤与 original_text 前缀 [eff-demo] 的报工，再重建。
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (
    AttendanceDay,
    AttendancePunch,
    Employee,
    OrderProcess,
    OwnProduct,
    ProcessDefinition,
    ProcessSegment,
    ReportType,
    SalaryModel,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
)


LOCAL_OFFSET = timedelta(hours=8)
DEMO_TAG = "[eff-demo]"
DAYS = 14
RNG = random.Random(20260916)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_today() -> date:
    return (_now_utc() + LOCAL_OFFSET).date()


def _utc_at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute)) - LOCAL_OFFSET


def _salary_value(emp: Employee) -> str:
    m = emp.salary_model
    return m.value if hasattr(m, "value") else str(m or "")


def main() -> None:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).order_by(Tenant.id.asc()).limit(1))
        if not tenant:
            print("无租户，请先 seed 工厂数据")
            return
        tid = tenant.id

        # 清理旧演示
        old_logs = db.scalars(
            select(WorkLog.id).where(
                WorkLog.tenant_id == tid,
                WorkLog.original_text.like(f"{DEMO_TAG}%"),
            )
        ).all()
        if old_logs:
            db.execute(delete(WorkLog).where(WorkLog.id.in_(old_logs)))
        db.execute(
            delete(AttendancePunch).where(
                AttendancePunch.tenant_id == tid,
                AttendancePunch.source_type == "eff_demo",
            )
        )
        # 仅清演示重建的考勤日（source_provider=eff_demo）
        demo_days = db.scalars(
            select(AttendanceDay.id).where(
                AttendanceDay.tenant_id == tid,
                AttendanceDay.source_provider == "eff_demo",
            )
        ).all()
        if demo_days:
            db.execute(delete(AttendanceDay).where(AttendanceDay.id.in_(demo_days)))
        db.commit()

        workers = [
            e
            for e in db.scalars(
                select(Employee)
                .where(Employee.tenant_id == tid, Employee.is_active.is_(True))
                .order_by(Employee.id.asc())
            ).all()
            if _salary_value(e) != SalaryModel.fixed.value
        ][:12]
        products = db.scalars(
            select(OwnProduct)
            .where(OwnProduct.tenant_id == tid, OwnProduct.is_active.is_(True))
            .order_by(OwnProduct.id.asc())
            .limit(6)
        ).all()
        segments = db.scalars(
            select(ProcessSegment)
            .where(ProcessSegment.tenant_id == tid, ProcessSegment.is_active.is_(True))
            .order_by(ProcessSegment.sort_order.asc())
        ).all()
        processes_by_seg: dict[int, list[ProcessDefinition]] = {}
        all_procs: list[ProcessDefinition] = []
        for seg in segments:
            procs = db.scalars(
                select(ProcessDefinition)
                .where(
                    ProcessDefinition.tenant_id == tid,
                    ProcessDefinition.segment_id == seg.id,
                    ProcessDefinition.is_active.is_not(False),
                )
                .order_by(ProcessDefinition.sort_order.asc())
            ).all()
            processes_by_seg[seg.id] = list(procs)
            all_procs.extend(procs)

        if not workers or not products or not all_procs:
            print("员工/产品/工序不足，无法造数")
            return

        # 每工序一个可复用 order_process（避免重复建）
        op_by_process: dict[int, OrderProcess] = {}
        for proc in all_procs:
            op = db.scalar(
                select(OrderProcess)
                .where(
                    OrderProcess.tenant_id == tid,
                    OrderProcess.process_id == proc.id,
                )
                .limit(1)
            )
            if not op:
                op = OrderProcess(
                    tenant_id=tid,
                    order_id=0,
                    process_id=proc.id,
                    process_name=proc.name,
                    plan_qty=99999,
                )
                db.add(op)
                db.flush()
            op_by_process[proc.id] = op

        today = _local_today()
        # 按工序段分配固定工人池，个人效率页更好看
        pools: dict[int, list[Employee]] = {}
        idx = 0
        for seg in segments:
            n = max(3, min(5, len(workers) // max(len(segments), 1)))
            pool = []
            for _ in range(n):
                pool.append(workers[idx % len(workers)])
                idx += 1
            pools[seg.id] = pool

        inserted_logs = 0
        inserted_att = 0
        # 同一人同一天只建一条考勤/打卡（flush 前 query 看不到 pending）
        att_by_key: dict[tuple[int, date], AttendanceDay] = {}
        punch_keys_seen: set[str] = set()
        for days_ago in range(0, DAYS):
            work_date = today - timedelta(days=days_ago)
            # 约 1/5 天整厂无报工，验证「无报工日不显示」
            if days_ago in {3, 8, 11}:
                continue

            for seg in segments:
                procs = processes_by_seg.get(seg.id) or []
                if not procs:
                    continue
                pool = pools[seg.id]
                # 每天该段抽若干工序有活（至少 1 个）
                k = min(len(procs), max(1, RNG.randint(1, min(4, len(procs)))))
                active_procs = RNG.sample(procs, k=k)
                for proc in active_procs:
                    # 每工序至少 1 人
                    wk = min(len(pool), max(1, RNG.randint(1, min(4, len(pool)))))
                    day_workers = RNG.sample(pool, k=wk)
                    for wi, emp in enumerate(day_workers):
                        # 出勤
                        in_utc = _utc_at(work_date, 8, 0 + wi * 3)
                        out_utc = _utc_at(work_date, 17, 30 + wi * 2)
                        punch_key = f"eff_demo:{emp.id}:{work_date.isoformat()}"
                        for punch_type, check_time in (("on_duty", in_utc), ("off_duty", out_utc)):
                            key = f"{punch_key}:{punch_type}"
                            if key in punch_keys_seen:
                                continue
                            exists = db.scalar(
                                select(AttendancePunch.id).where(
                                    AttendancePunch.tenant_id == tid,
                                    AttendancePunch.external_record_key == key,
                                )
                            )
                            if exists:
                                punch_keys_seen.add(key)
                                continue
                            db.add(
                                AttendancePunch(
                                    tenant_id=tid,
                                    employee_id=emp.id,
                                    work_date=work_date,
                                    punch_type=punch_type,
                                    check_time=check_time,
                                    time_result="normal",
                                    location_result="not_required",
                                    source_provider="eff_demo",
                                    external_corp_id="",
                                    external_user_id=str(emp.id),
                                    external_record_key=key,
                                    source_type="eff_demo",
                                    raw_payload={"source": "eff_demo"},
                                )
                            )
                            punch_keys_seen.add(key)
                        att_key = (emp.id, work_date)
                        day = att_by_key.get(att_key)
                        if day is None:
                            day = db.scalar(
                                select(AttendanceDay).where(
                                    AttendanceDay.tenant_id == tid,
                                    AttendanceDay.employee_id == emp.id,
                                    AttendanceDay.work_date == work_date,
                                )
                            )
                        if not day:
                            day = AttendanceDay(
                                tenant_id=tid,
                                employee_id=emp.id,
                                work_date=work_date,
                                source_provider="eff_demo",
                            )
                            db.add(day)
                            inserted_att += 1
                        att_by_key[att_key] = day
                        day.clock_in_at = in_utc
                        day.clock_out_at = out_utc
                        day.work_minutes = int((out_utc - in_utc).total_seconds() // 60)
                        day.status = "normal"
                        day.source_provider = "eff_demo"
                        day.raw_count = 2

                        product = RNG.choice(products)
                        qty = Decimal(str(RNG.randint(20, 90) + wi * 5))
                        defect = Decimal("0")
                        loss_amount = Decimal("0")
                        loss_pct = 0
                        if RNG.random() < 0.18:
                            defect = Decimal(str(RNG.choice([1, 2, 3])))
                            loss_amount = Decimal(str(RNG.choice([8, 12, 20, 30])))
                            loss_pct = RNG.choice([30, 50, 100])

                        created = _utc_at(work_date, 10 + wi, RNG.randint(0, 50))
                        db.add(
                            WorkLog(
                                tenant_id=tid,
                                worker_id=emp.id,
                                order_id=op_by_process[proc.id].order_id,
                                order_process_id=op_by_process[proc.id].id,
                                own_product_id=product.id,
                                process_id=proc.id,
                                segment_id=seg.id,
                                report_type=ReportType.normal,
                                qualified_qty=qty,
                                defect_qty=defect,
                                unit_price=Decimal(str(RNG.choice(["0.8", "1.2", "1.5", "2.0"]))),
                                loss_amount=loss_amount,
                                loss_borne_percent=loss_pct,
                                status=WorkLogStatus.valid,
                                source=WorkLogSource.manual,
                                original_text=f"{DEMO_TAG} {work_date} {emp.name} {proc.name} {product.product_code} {qty}",
                                created_at=created,
                            )
                        )
                        inserted_logs += 1

            db.flush()

        db.commit()
        print(
            f"效率演示数据已写入租户「{tenant.name}」: "
            f"报工 {inserted_logs} 笔, 新建考勤日 {inserted_att} 行, "
            f"覆盖约 {DAYS} 天（跳过部分无报工日）, 工人 {len(workers)} 人, 工序 {len(all_procs)} 个"
        )
        print("请打开「生产效率」各页签，日期段选近两周查看效果。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
