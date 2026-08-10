"""对外 MCP Streamable HTTP 路由：/mcp/{intake|schedule|supply|ops}。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.mcp.protocol import handle_jsonrpc
from app.mcp.scopes import SERVER_META, is_valid_server
from app.services import mcp_keys
from app.services.mcp_keys import McpKeyError, VerifiedMcpKey

router = APIRouter(tags=["mcp"])


def _origin_allowed(origin: Optional[str]) -> bool:
    settings = get_settings()
    raw = (settings.mcp_allowed_origins or "").strip()
    if raw == "*":
        return True
    allowed = {o.strip() for o in raw.split(",") if o.strip()}
    if not origin:
        # 无 Origin：典型服务端 Agent / curl；在非 * 配置下仍放行（靠 API Key）
        return True
    return origin in allowed


def _extract_api_key(request: Request) -> Optional[str]:
    """兼容多种外部平台传参：

    - Authorization: Bearer mcp_…
    - Authorization: mcp_…（企微等「API key 填进 Authorization」常见写法）
    - X-Api-Key / X-MCP-Key: mcp_…
    """
    auth = (request.headers.get("authorization") or "").strip()
    if auth:
        lower = auth.lower()
        if lower.startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return token
        if auth.startswith("mcp_"):
            return auth
    for header in ("x-api-key", "x-mcp-key"):
        val = (request.headers.get(header) or "").strip()
        if val:
            if val.lower().startswith("bearer "):
                val = val[7:].strip()
            if val:
                return val
    return None


def _verify_request_key(db: Session, request: Request) -> VerifiedMcpKey:
    raw = _extract_api_key(request)
    if not raw:
        raise McpKeyError("invalid_token", "未提供 API Key")
    return mcp_keys.verify_bearer(db, raw)


@router.get("/mcp")
def mcp_index():
    """人类可读发现页（非 MCP 协议）。"""
    settings = get_settings()
    return {
        "ok": True,
        "enabled": bool(settings.mcp_enabled),
        "transport": "streamable-http",
        "auth": "Authorization: Bearer mcp_… 或 Authorization: mcp_…",
        "servers": [
            {
                "id": sid,
                "url": f"/mcp/{sid}",
                **SERVER_META[sid],
            }
            for sid in SERVER_META
        ],
        "note": "外部 Agent 请 POST JSON-RPC 到各 server URL；勿走站内车间军师 SSE。",
    }


@router.api_route("/mcp/{server}", methods=["GET", "POST", "DELETE"])
async def mcp_endpoint(
    server: str,
    request: Request,
    db: Session = Depends(get_db),
    origin: Optional[str] = Header(default=None, alias="Origin"),
):
    settings = get_settings()
    if not settings.mcp_enabled:
        return JSONResponse({"error": "mcp_disabled", "message": "MCP 已关闭"}, status_code=503)

    if not is_valid_server(server):
        return JSONResponse(
            {"error": "unknown_server", "message": f"未知 MCP：{server}", "servers": list(SERVER_META)},
            status_code=404,
        )

    if not _origin_allowed(origin):
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Invalid Origin"}, "id": None},
            status_code=403,
        )

    if request.method == "GET":
        # 2026-07-28 起 Streamable HTTP 可无长连接 GET；返回发现信息便于探测
        return {
            "server": server,
            **SERVER_META[server],  # type: ignore[index]
            "transport": "streamable-http",
            "methods": ["POST"],
            "auth": "Bearer mcp_… 或 mcp_…",
        }

    if request.method == "DELETE":
        # 无会话态；兼容部分客户端结束会话的 DELETE
        return Response(status_code=204)

    # POST
    try:
        principal = _verify_request_key(db, request)
    except McpKeyError as e:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": e.message}, "id": None},
            status_code=401,
        )

    try:
        body: Any = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )

    if isinstance(body, list):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Batch not supported; send one message per POST"},
                "id": None,
            },
            status_code=400,
        )

    resp, status = handle_jsonrpc(
        db,
        server=server,  # type: ignore[arg-type]
        principal=principal,
        message=body if isinstance(body, dict) else {},
    )
    if resp is None:
        return Response(status_code=status)
    return JSONResponse(resp, status_code=status)
