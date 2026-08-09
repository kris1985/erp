#!/usr/bin/env python3
"""B2h-M1 走查：对着本地 API（默认 127.0.0.1:8000）跑验收口径。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

BASE = "http://127.0.0.1:8000/api/v1"
results: list[tuple[str, bool, str]] = []


def req(method: str, path: str, token: str | None = None, body: dict | None = None, *, binary=False):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            if binary:
                return resp.status, raw, resp.headers
            return resp.status, json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        if binary:
            return e.code, raw, e.headers
        try:
            payload = json.loads(raw.decode()) if raw else {}
        except json.JSONDecodeError:
            payload = {"detail": raw.decode(errors="replace")}
        return e.code, payload


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    st, login = req("POST", "/auth/login", body={"username": "admin", "password": "admin123"})
    token = (login.get("data") or {}).get("access_token")
    check("登录 admin", st == 200 and bool(token), f"status={st}")
    if not token:
        return 1

    st, orders = req("GET", "/orders?page=1&page_size=50", token)
    items = (orders.get("data") or {}).get("items") or []
    order = next((o for o in items if o.get("trace_enabled")), None)
    if not order:
        for o in items:
            if o.get("items"):
                pid = o.get("own_product_id")
                if pid:
                    req("PATCH", f"/own-products/{pid}", token, {"trace_enabled": True})
                    st2, od = req("GET", f"/orders/{o['id']}", token)
                    order = (od.get("data") if st2 == 200 else None) or o
                    order["trace_enabled"] = True
                    break
    check("找到可开裁生产单", bool(order and order.get("id")), str((order or {}).get("order_no")))
    if not order:
        return 1

    oid = order["id"]
    ono = order["order_no"]

    st, preview = req(
        "POST",
        f"/orders/{oid}/cut-cards",
        token,
        {"dry_run": True, "only_missing": True, "bundle_size": None},
    )
    pdata = preview.get("data") or {}
    check(
        "E1a dry_run 预览",
        st == 200 and "to_create" in pdata,
        f"to_create={pdata.get('to_create')} lines={len(pdata.get('lines') or [])}",
    )

    st, created = req(
        "POST",
        f"/orders/{oid}/cut-cards",
        token,
        {"dry_run": False, "only_missing": True, "bundle_size": None},
    )
    cdata = created.get("data") or {}
    created_units = cdata.get("created") or []
    _, units_resp = req("GET", f"/orders/{oid}/trace-units", token)
    units = (units_resp.get("data") or {}).get("items") or []
    active = [u for u in units if u.get("status") in ("open", "in_process")]
    check(
        "E1 开裁生码",
        st == 200 and (len(created_units) > 0 or len(active) > 0),
        f"new={len(created_units)} active={len(active)} print={cdata.get('print_path')}",
    )

    st, again = req(
        "POST",
        f"/orders/{oid}/cut-cards",
        token,
        {"dry_run": False, "only_missing": True},
    )
    adata = again.get("data") or {}
    check(
        "再次开裁不灌水",
        st == 200 and int(adata.get("to_create") or 0) == 0,
        f"to_create={adata.get('to_create')}",
    )

    target = created_units[0] if created_units else (active[0] if active else None)
    check("有可用主码", bool(target), str((target or {}).get("code")))
    if not target:
        return 1

    code = target["code"]
    uid = target["id"]

    st_qr, blob, hdrs = req("GET", f"/trace-units/by-code/{quote(code)}/qr.png", binary=True)
    ctype = (hdrs.get("Content-Type") or "") if hdrs else ""
    check("打印 QR 可取", st_qr == 200 and "png" in ctype and len(blob) > 100, f"{code} bytes={len(blob)}")

    st, detail = req("GET", f"/trace-units/by-code/{quote(code)}")
    ud = detail.get("data") or {}
    check(
        "扫码落地详情",
        st == 200 and ud.get("order_no") == ono,
        f"order={ud.get('order_no')} color={ud.get('color_name')} size={ud.get('size_value')}",
    )

    st, odetail = req("GET", f"/orders/{oid}", token)
    procs = ((odetail.get("data") or {}).get("processes") or [])
    # 选已派人的工序，并用名单内工人报工
    pname = None
    assigned_ids: list[int] = []
    for p in procs:
        ids = p.get("assigned_worker_ids") or []
        if ids:
            pname = p.get("process_name")
            assigned_ids = ids
            break
    if not pname:
        pname = procs[0]["process_name"] if procs else "针车"

    _, workers = req("GET", "/workers?page=1&page_size=50", token)
    witems = (workers.get("data") or {}).get("items") or []
    w0 = next((w for w in witems if w.get("id") in assigned_ids and w.get("mobile")), None)
    if not w0:
        w0 = next((w for w in witems if w.get("mobile")), None)
    worker_token = None
    wid = None
    mobile = (w0 or {}).get("mobile") or "13800138000"
    if w0 and w0.get("id"):
        req("PATCH", f"/workers/{w0['id']}", token, {"reset_password": True})
    st, wlogin = req(
        "POST",
        "/auth/worker/login",
        body={"mobile": mobile, "password": "123456"},
    )
    data = wlogin.get("data") or {}
    if st == 200 and data.get("access_token"):
        worker_token = data["access_token"]
        wid = data.get("worker_id")
    check(
        "工人登录",
        bool(worker_token and wid),
        f"mobile={mobile} worker_id={wid} process={pname}",
    )

    color_name = ud.get("color_name")
    size_value = ud.get("size_value")

    report_ok = False
    report_detail = ""
    if worker_token and wid:
        st, report = req(
            "POST",
            "/reports",
            worker_token,
            {
                "worker_id": wid,
                "order_no": ono,
                "process_name": pname,
                "qualified_qty": 1,
                "color_name": color_name,
                "size_value": size_value,
                "source": "qrcode",
                "confirm_over_plan": True,
                "trace_unit_id": uid,
                "create_trace_bundle": False,
            },
        )
        if st == 200 and report.get("ok"):
            report_ok = True
            rd = report.get("data") or {}
            report_detail = str(rd.get("message") or rd.get("work_log_id"))
        else:
            report_detail = str(report.get("detail") or report)[:200]
    check("E2 扫主码报工", report_ok, report_detail)

    st, qt = req("GET", f"/quality-trace?q={quote(code)}", token)
    qtd = qt.get("data") or {}
    check(
        "E3 追溯台反查主码",
        st == 200 and bool(qtd.get("order") or qtd.get("focus_unit") or qtd.get("units_summary")),
        f"keys={list(qtd.keys())[:8]}",
    )

    st, one = req(
        "POST",
        "/trace-units",
        token,
        {
            "order_id": oid,
            "qty": 1,
            "color_id": ud.get("color_id"),
            "size_id": ud.get("size_id"),
            "note": "走查作废样",
        },
    )
    void_unit = one.get("data") or {}
    void_id = void_unit.get("id")
    if void_id:
        st, voided = req("POST", f"/trace-units/{void_id}/void", token, {"note": "走查作废"})
        check(
            "E6a void 成功",
            st == 200,
            f"id={void_id} status={(voided.get('data') or {}).get('status')}",
        )
        if worker_token and wid:
            st, bad = req(
                "POST",
                "/reports",
                worker_token,
                {
                    "worker_id": wid,
                    "order_no": ono,
                    "process_name": pname,
                    "qualified_qty": 1,
                    "color_name": color_name,
                    "size_value": size_value,
                    "confirm_over_plan": True,
                    "trace_unit_id": void_id,
                    "create_trace_bundle": False,
                },
            )
            detail_s = str(bad.get("detail") or bad)
            check(
                "E6b 作废后不可报",
                st == 400 and ("作废" in detail_s or "不可报工" in detail_s),
                detail_s[:120],
            )
        else:
            check("E6b 作废后不可报", False, "无工人 token")
    else:
        check("E6a void 成功", False, f"无法创建作废样: {str(one)[:120]}")

    before = len((req("GET", f"/orders/{oid}/trace-units", token)[1].get("data") or {}).get("items") or [])
    if worker_token and wid:
        st, bare = req(
            "POST",
            "/reports",
            worker_token,
            {
                "worker_id": wid,
                "order_no": ono,
                "process_name": pname,
                "qualified_qty": 1,
                "color_name": color_name,
                "size_value": size_value,
                "confirm_over_plan": True,
            },
        )
        after = len((req("GET", f"/orders/{oid}/trace-units", token)[1].get("data") or {}).get("items") or [])
        if st == 200 and bare.get("ok"):
            check("E7 开裁后不静默起捆", after == before, f"before={before} after={after}")
        else:
            check(
                "E7 开裁后不静默起捆（报工未成，软过）",
                before > 0,
                f"status={st} detail={str(bare.get('detail'))[:80]} units={before}",
            )
    else:
        check("E7 开裁后不静默起捆", False, "无工人")

    print_path = cdata.get("print_path") or f"/admin/orders/print/{oid}?mode=main-codes"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:5173{print_path}", timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            check("前端打印路由可达", resp.status == 200 and len(html) > 50, print_path)
    except Exception as e:
        check("前端打印路由可达", False, str(e))

    failed = sum(1 for _, ok, _ in results if not ok)
    print("\n=== SUMMARY ===")
    print(f"passed={len(results) - failed} failed={failed} total={len(results)}")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
