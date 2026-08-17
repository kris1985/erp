"""Rule-based NLU for MVP: report / salary / progress / bind."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PendingSlot, Employee
from app.services import progress_service, salary_service
from app.services.report_service import ReportError, submit_report


def _get_pending(db: Session, tenant_id: int, actor_key: str) -> PendingSlot | None:
    return db.scalar(
        select(PendingSlot).where(PendingSlot.tenant_id == tenant_id, PendingSlot.actor_key == actor_key)
    )


def _set_pending(db: Session, tenant_id: int, actor_key: str, intent: str, slots: dict) -> None:
    row = _get_pending(db, tenant_id, actor_key)
    if row:
        row.intent = intent
        row.slots = slots
    else:
        db.add(PendingSlot(tenant_id=tenant_id, actor_key=actor_key, intent=intent, slots=slots))
    db.commit()


def _clear_pending(db: Session, tenant_id: int, actor_key: str) -> None:
    row = _get_pending(db, tenant_id, actor_key)
    if row:
        db.delete(row)
        db.commit()


def parse_report_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    if any(k in text for k in ("返修", "返工")):
        slots["report_type"] = "rework"
    elif any(k in text for k in ("补数", "补了")):
        slots["report_type"] = "supplement"
    elif "尾数" in text:
        slots["report_type"] = "tail"
    elif any(k in text for k in ("集体", "一起做", "小组")):
        slots["report_type"] = "group"

    order = re.search(r"(?:订单)?(\d{6,})", text)
    if order:
        slots["order_no"] = order.group(1)

    color = re.search(r"([红黑白蓝绿灰棕米色]+)", text)
    if color:
        slots["color_name"] = color.group(1)

    size = re.search(r"(\d{2})\s*码", text)
    if size:
        slots["size_value"] = size.group(1)

    process = re.search(r"(裁断|针车|成型|包装|贴合|鞋面|中底|大底)", text)
    if process:
        slots["process_name"] = process.group(1)

    rework_qty = re.search(r"(?:返修了?|返工了?)\s*(\d+)\s*双?", text)
    supplement_qty = re.search(r"(?:补数了?|补了)\s*(\d+)\s*双?", text)
    tail_qty = re.search(r"尾数了?\s*(\d+)\s*双?", text)
    if rework_qty:
        slots["qualified_qty"] = int(rework_qty.group(1))
        slots["report_type"] = "rework"
    elif supplement_qty:
        slots["qualified_qty"] = int(supplement_qty.group(1))
        slots["report_type"] = "supplement"
    elif tail_qty:
        slots["qualified_qty"] = int(tail_qty.group(1))
        slots["report_type"] = "tail"
    else:
        qty = re.search(r"(?:做了|完成|报工|合格)?\s*(\d+)\s*双", text)
        if qty:
            slots["qualified_qty"] = int(qty.group(1))
        else:
            qty2 = re.search(r"(?:再干|再做)\s*(\d+)", text)
            if qty2:
                slots["qualified_qty"] = int(qty2.group(1))

    defect = re.search(r"(?:废了|不良|报废)\s*(\d+)", text)
    if defect:
        slots["defect_qty"] = int(defect.group(1))
    else:
        slots.setdefault("defect_qty", 0)

    slots.setdefault("report_type", "normal")
    return slots


def detect_intent(text: str) -> str:
    t = text.strip()
    if any(k in t for k in ("工资", "做了多少", "计件", "这个月")):
        return "salary"
    if any(k in t for k in ("今天产量", "整体产量", "进度最慢", "进度")) or re.search(r"\d{6,}.*进度", t):
        return "progress"
    if any(k in t for k in ("绑定", "我是", "我叫")):
        return "bind"
    if any(k in t for k in ("确认", "继续", "是的", "好的")):
        return "confirm"
    if (
        parse_report_slots(t).get("qualified_qty")
        or any(k in t for k in ("报工", "做了", "再干", "返修", "返工", "集体", "补数", "尾数"))
    ):
        return "report"
    return "unknown"

def handle_chat(
    db: Session,
    *,
    tenant_id: int,
    text: str,
    worker_id: int | None = None,
    openid: str | None = None,
    confirm: bool = False,
) -> dict:
    actor_key = f"worker:{worker_id}" if worker_id else f"openid:{openid or 'anon'}"
    text = (text or "").strip()
    pending = _get_pending(db, tenant_id, actor_key)

    # Binding flow when no worker
    if worker_id is None and openid:
        worker = db.scalar(select(Employee).where(Employee.tenant_id == tenant_id, Employee.wechat_openid == openid))
        if worker:
            worker_id = worker.id
            actor_key = f"worker:{worker_id}"
        else:
            return _handle_bind(db, tenant_id, text, openid)

    if worker_id is None:
        return {
            "reply": "请先选择工人身份，或在微信中完成绑定（发送：我是张三 13800138000）",
            "intent": "bind",
            "need_confirm": False,
            "data": None,
        }

    intent = detect_intent(text)
    if confirm or intent == "confirm":
        if pending and pending.intent == "report_confirm":
            slots = dict(pending.slots or {})
            _clear_pending(db, tenant_id, actor_key)
            try:
                result = submit_report(
                    db,
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                    order_no=slots["order_no"],
                    process_name=slots["process_name"],
                    qualified_qty=int(slots["qualified_qty"]),
                    defect_qty=int(slots.get("defect_qty") or 0),
                    color_name=slots.get("color_name"),
                    size_value=slots.get("size_value"),
                    original_text=text,
                    source="voice",
                    confirm_over_plan=True,
                    report_type=str(slots.get("report_type") or "normal"),
                    member_ids=slots.get("member_ids"),
                )
                return {"reply": result["message"], "intent": "report", "need_confirm": False, "data": result}
            except ReportError as e:
                return {"reply": e.message, "intent": "report", "need_confirm": e.need_confirm, "data": e.data}
        return {"reply": "当前没有待确认的操作。", "intent": "confirm", "need_confirm": False, "data": None}

    if intent == "salary":
        data = salary_service.month_salary(db, tenant_id, worker_id)
        return {"reply": data["message"], "intent": "salary", "need_confirm": False, "data": data}

    if intent == "progress":
        order_m = re.search(r"(\d{6,})", text)
        if "今天" in text or "整体产量" in text:
            data = progress_service.today_output(db, tenant_id)
        elif "最慢" in text:
            data = progress_service.slowest_orders(db, tenant_id)
        elif order_m:
            data = progress_service.order_progress(db, tenant_id, order_m.group(1))
            if data.get("error"):
                return {"reply": data["error"], "intent": "progress", "need_confirm": False, "data": data}
        else:
            data = progress_service.today_output(db, tenant_id)
        return {"reply": data["message"], "intent": "progress", "need_confirm": False, "data": data}

    if intent == "bind":
        return _handle_bind(db, tenant_id, text, openid, worker_id=worker_id)

    # report
    slots = parse_report_slots(text)
    if pending and pending.intent == "report_slots":
        merged = dict(pending.slots or {})
        merged.update({k: v for k, v in slots.items() if v is not None})
        slots = merged

    missing = [k for k in ("order_no", "process_name", "qualified_qty") if not slots.get(k)]
    if missing:
        _set_pending(db, tenant_id, actor_key, "report_slots", slots)
        labels = {"order_no": "订单号", "process_name": "工序", "qualified_qty": "合格数量"}
        ask = "、".join(labels[m] for m in missing)
        return {
            "reply": f"还缺：{ask}。例如：230711 红 37码 针车 做了100双",
            "intent": "report",
            "need_confirm": False,
            "data": {"slots": slots, "missing": missing},
        }

    try:
        result = submit_report(
            db,
            tenant_id=tenant_id,
            worker_id=worker_id,
            order_no=str(slots["order_no"]),
            process_name=str(slots["process_name"]),
            qualified_qty=int(slots["qualified_qty"]),
            defect_qty=int(slots.get("defect_qty") or 0),
            color_name=slots.get("color_name"),
            size_value=slots.get("size_value"),
            original_text=text,
            source="voice",
            confirm_over_plan=False,
            report_type=str(slots.get("report_type") or "normal"),
            member_ids=slots.get("member_ids"),
        )
        _clear_pending(db, tenant_id, actor_key)
        return {"reply": result["message"], "intent": "report", "need_confirm": False, "data": result}
    except ReportError as e:
        if e.need_confirm:
            _set_pending(db, tenant_id, actor_key, "report_confirm", e.data)
            return {"reply": e.message + " 回复「确认」继续。", "intent": "report", "need_confirm": True, "data": e.data}
        return {"reply": e.message, "intent": "report", "need_confirm": False, "data": e.data}


def _handle_bind(
    db: Session,
    tenant_id: int,
    text: str,
    openid: str | None,
    worker_id: int | None = None,
) -> dict:
    if worker_id and not openid:
        return {"reply": "已是登录工人，无需绑定。", "intent": "bind", "need_confirm": False, "data": None}
    if not openid:
        return {"reply": "缺少微信身份，无法绑定。", "intent": "bind", "need_confirm": False, "data": None}

    name_m = re.search(r"(?:我是|我叫|绑定)\s*([^\d\s]{2,4})", text)
    mobile_m = re.search(r"(1\d{10})", text)
    if not name_m and not mobile_m:
        return {
            "reply": "请发送：我是张三 13800138000，完成身份绑定。",
            "intent": "bind",
            "need_confirm": False,
            "data": None,
        }

    q = select(Employee).where(Employee.tenant_id == tenant_id, Employee.is_active.is_(True))
    if mobile_m:
        worker = db.scalar(q.where(Employee.mobile == mobile_m.group(1)))
    else:
        worker = db.scalar(q.where(Employee.name == name_m.group(1)))
    if not worker:
        return {"reply": "未找到匹配工人，请联系组长在后台录入后再绑定。", "intent": "bind", "need_confirm": False, "data": None}

    worker.wechat_openid = openid
    db.commit()
    return {
        "reply": f"绑定成功，你好 {worker.name}！直接说「订单号 工序 做了xx双」即可报工。",
        "intent": "bind",
        "need_confirm": False,
        "data": {"worker_id": worker.id, "worker_name": worker.name},
    }
