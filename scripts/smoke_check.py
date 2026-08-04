#!/usr/bin/env python3
"""MVP smoke: login → chat report → salary."""
import sys
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

with httpx.Client(base_url=BASE, timeout=20) as c:
    assert c.get("/api/health").json()["ok"]
    token = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    workers = c.get("/api/v1/workers", headers=h).json()["data"]["items"]
    wid = workers[0]["id"]
    chat = c.post(
        "/api/v1/chat",
        headers=h,
        json={"text": "230711 红 37码 针车 做了10双", "worker_id": wid},
    ).json()["data"]
    assert "报工成功" in chat["reply"] or "超额" in chat["reply"]
    sal = c.get(f"/api/v1/salary/{wid}", headers=h).json()["data"]
    assert "total_piece_wage" in sal
    # SPA index
    assert c.get("/").status_code == 200
    print("SMOKE OK", chat["reply"][:60])
