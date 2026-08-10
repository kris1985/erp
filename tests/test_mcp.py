"""对外 MCP Streamable HTTP + API Key。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Tenant
from app.services import mcp_keys


@pytest.fixture()
def client_and_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="MCP厂")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    yield client, session, tenant.id
    app.dependency_overrides.clear()
    session.close()


def _rpc(client, server: str, method: str, params=None, *, api_key: str | None, msg_id=1):
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(f"/mcp/{server}", json=body, headers=headers)


def test_mcp_index(client_and_db):
    client, _, _ = client_and_db
    r = client.get("/mcp")
    assert r.status_code == 200
    data = r.json()
    assert data["transport"] == "streamable-http"
    assert len(data["servers"]) == 4


def test_mcp_requires_api_key(client_and_db):
    client, _, _ = client_and_db
    r = _rpc(client, "ops", "initialize", api_key=None)
    assert r.status_code == 401


def test_mcp_raw_authorization_without_bearer(client_and_db):
    """企微等平台常把裸 key 填进 Authorization，不带 Bearer。"""
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="raw", scopes=["ops"])
    r = client.post(
        "/mcp/ops",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": raw},
    )
    assert r.status_code == 200
    assert "tools" in r.json()["result"]


def test_mcp_x_api_key_header(client_and_db):
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="xkey", scopes=["ops"])
    r = client.post(
        "/mcp/ops",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"X-Api-Key": raw},
    )
    assert r.status_code == 200


def test_mcp_initialize_and_tools(client_and_db):
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="ops", scopes=["ops"])

    r = _rpc(
        client,
        "ops",
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        api_key=raw,
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["serverInfo"]["name"] == "erp-ops"
    assert "tools" in result["capabilities"]

    r2 = _rpc(client, "ops", "tools/list", api_key=raw, msg_id=2)
    assert r2.status_code == 200
    names = {t["name"] for t in r2.json()["result"]["tools"]}
    assert "list_metrics" in names
    assert "query_metric" in names
    assert "get_schedule_pool" not in names


def test_mcp_scope_isolation(client_and_db):
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="intake-only", scopes=["intake"])

    # intake key 访问 schedule → 403
    r = _rpc(client, "schedule", "tools/list", api_key=raw)
    assert r.status_code == 403

    r2 = _rpc(client, "intake", "tools/list", api_key=raw, msg_id=2)
    assert r2.status_code == 200
    names = {t["name"] for t in r2.json()["result"]["tools"]}
    assert "list_metrics" in names


def test_mcp_schedule_extra_tools(client_and_db):
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="pmc", scopes=["schedule"])
    r = _rpc(client, "schedule", "tools/list", api_key=raw)
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert "generate_schedule_proposals" in names
    assert "simulate_insert_order" in names


def test_mcp_query_metric_server_allowlist(client_and_db):
    client, db, tenant_id = client_and_db
    _, raw = mcp_keys.create_key(db, tenant_id, name="supply", scopes=["supply"])
    r = _rpc(
        client,
        "supply",
        "tools/call",
        {
            "name": "query_metric",
            "arguments": {"metric_id": "analytics.order_intake", "params": {}},
        },
        api_key=raw,
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert "forbidden_metric" in text or "不可查" in text


def test_revoke_key(client_and_db):
    client, db, tenant_id = client_and_db
    row, raw = mcp_keys.create_key(db, tenant_id, name="tmp", scopes=["*"])
    mcp_keys.revoke_key(db, tenant_id, row.id)
    r = _rpc(client, "ops", "ping", api_key=raw)
    assert r.status_code == 401
