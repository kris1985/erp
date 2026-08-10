"""精简 Streamable HTTP MCP 协议处理（tools 能力）。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.mcp.scopes import SERVER_META, ServerId, key_allows_server
from app.mcp.tools import call_tool, list_tool_defs
from app.services.mcp_keys import VerifiedMcpKey

PROTOCOL_VERSION_FALLBACK = "2025-03-26"


def handle_jsonrpc(
    db: Session,
    *,
    server: ServerId,
    principal: VerifiedMcpKey,
    message: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], int]:
    """
    处理单条 JSON-RPC。
    返回 (response_body_or_None, http_status)。
    notification → (None, 202)；request → (jsonrpc result/error, 200)。
    """
    if not isinstance(message, dict):
        return _rpc_error(None, -32600, "Invalid Request"), 400

    method = message.get("method")
    msg_id = message.get("id", _MISSING)
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    is_notification = msg_id is _MISSING

    if not key_allows_server(principal.scopes, server):
        if is_notification:
            return None, 403
        return _rpc_error(msg_id, -32001, f"API Key 无权限访问 MCP「{server}」"), 403

    if method == "initialize":
        if is_notification:
            return None, 202
        return _rpc_result(msg_id, _initialize_result(server, params)), 200

    if method in ("notifications/initialized", "initialized"):
        return None, 202

    if method == "ping":
        if is_notification:
            return None, 202
        return _rpc_result(msg_id, {}), 200

    if method == "tools/list":
        if is_notification:
            return None, 202
        return _rpc_result(msg_id, {"tools": list_tool_defs(server)}), 200

    if method == "tools/call":
        if is_notification:
            return None, 202
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not name:
            return _rpc_error(msg_id, -32602, "缺少 tools/call.name"), 200
        if not isinstance(arguments, dict):
            return _rpc_error(msg_id, -32602, "arguments 须为对象"), 200
        result = call_tool(
            db,
            tenant_id=principal.tenant_id,
            server=server,
            name=name,
            arguments=arguments,
        )
        return _rpc_result(msg_id, result), 200

    if is_notification:
        return None, 202
    return _rpc_error(msg_id, -32601, f"Method not found: {method}"), 200


def _initialize_result(server: ServerId, params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    client_version = str(params.get("protocolVersion") or "").strip()
    supported = settings.mcp_protocol_version or PROTOCOL_VERSION_FALLBACK
    # 客户端声明的版本若非空，优先回显以利握手；否则用服务端配置
    version = client_version or supported
    meta = SERVER_META[server]
    return {
        "protocolVersion": version,
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {
            "name": meta["name"],
            "version": "0.1.0",
            "title": meta["title"],
        },
        "instructions": (
            f"{meta['description']} "
            "先 list_metrics / tools/list，再 query_metric 或排产只读工具；"
            "禁止编造数据；确认生产/排产/采购须在 ERP 界面人工操作。"
        ),
    }


_MISSING = object()


def _rpc_result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
    }
    if msg_id is not _MISSING:
        body["id"] = msg_id
    else:
        body["id"] = None
    return body
