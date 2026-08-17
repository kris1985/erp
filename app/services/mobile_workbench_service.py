"""Mobile operations workbench: compact, role-scoped incoming-material tasks."""

from __future__ import annotations

from app.models import Employee
from app.services import customer_supply_service, iqc_service, purchase_service, rbac_service


ROLE_NAMES = {
    "manager": "厂长", "warehouse": "采购仓管", "finance": "财务",
    "workshop": "车间主管", "merchandiser": "跟单", "admin": "管理员",
}


def _num(value) -> float:
    return float(value or 0)


def workbench_overview(db, user: Employee) -> dict:
    """Only expose queues the user's effective menu permissions permit."""
    perms = set(rbac_service.get_user_permissions(db, user))
    roles = rbac_service.list_user_role_codes(db, user)
    can_purchase = "menu.purchase_orders" in perms
    can_customer = "menu.customer_supply" in perms
    can_iqc = "menu.purchase_orders" in perms or "menu.defects" in perms
    tasks: list[dict] = []
    counts = {"purchase_receive": 0, "customer_receive": 0, "iqc": 0, "due_today": 0, "overdue": 0}

    if can_purchase:
        for po in purchase_service.list_pos(db, user.tenant_id):
            if po.get("status") not in ("ordered", "shipped", "partial_received"):
                continue
            alert = po.get("delivery_alert")
            if alert in ("overdue", "due_soon"):
                key = "overdue" if alert == "overdue" else "due_today"
                counts[key] += 1
                tasks.append({"kind": "delivery_risk", "source": "采购", "status": po.get("delivery_alert_label") or "预计未到", "severity": alert, "title": "采购来料未到", "meta": f"预计 {po.get('expected_date') or '—'} · 可能影响生产安排", "action_label": "跟进到货", "to": f"/po-receive/{po['id']}"})
            open_qty = sum(max(0, _num(x.get("qty")) - _num(x.get("received_qty"))) for x in po.get("lines") or [])
            # 一个业务事件在行动中心只出现一次：有交期风险时优先引导跟进，
            # 否则才显示常规到货登记，避免用户看到两条重复待办。
            if open_qty > 0 and alert not in ("overdue", "due_soon"):
                counts["purchase_receive"] += 1
                tasks.append({"kind": "purchase_receive", "source": "采购", "status": "待到货登记", "severity": "info", "title": "采购来料", "meta": f"待登记 {open_qty:g} · 到货后需检验", "action_label": "登记到货", "to": f"/po-receive/{po['id']}"})

    if can_customer:
        for row in customer_supply_service.list_customer_supply(db, user.tenant_id, owed_only=True)[:20]:
            counts["customer_receive"] += 1
            tasks.append({"kind": "customer_receive", "source": "客供", "status": "待到货登记", "severity": "warning" if row.get("is_rush") else "info", "title": row.get("supplier_product_name") or row.get("supplier_product_code") or "客供来料", "meta": f"尚欠 {_num(row.get('owed_qty')):g} · 到货后需检验", "action_label": "登记到货", "id": row["id"]})

    if can_iqc:
        for row in iqc_service.list_iqc(db, user.tenant_id, status="pending", limit=20):
            counts["iqc"] += 1
            tasks.append({"kind": "iqc", "source": "IQC", "status": "待判定", "severity": "warning", "title": row.get("supplier_product_name") or row.get("supplier_product_code") or "来料", "meta": f"本次到货 {_num(row.get('qty')):g} · 判定后才可入库", "action_label": "去判定", "id": row["id"]})

    severity = {"overdue": 0, "due_soon": 1, "warning": 2, "info": 3}
    tasks.sort(key=lambda x: severity.get(x["severity"], 9))
    return {
        "roles": [{"code": r, "name": ROLE_NAMES.get(r, r)} for r in roles],
        "counts": counts,
        "tasks": tasks[:12],
        "can": {"purchase": can_purchase, "customer": can_customer, "iqc": can_iqc},
    }
