"""对外 MCP Server：Streamable HTTP + API Key，供外部 AI Agent 只读调用。"""

from app.mcp.scopes import MCP_SERVERS, ServerId

__all__ = ["MCP_SERVERS", "ServerId"]
