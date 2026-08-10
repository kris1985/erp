# 对外 MCP Server（外部 AI Agent）

> 站内「车间军师」是 DeepAgents + SSE；本页是给**外部 Agent**用的 **Streamable HTTP MCP**。  
> 原则：只读白名单、禁止编数、落库仍走 ERP 界面 HITL。  
> 管理页：后台 **系统 → MCP 密钥**（`/admin/mcp-keys`，管理员）。

## 端点

| Server | URL | 角色面 |
|--------|-----|--------|
| 接单参谋 | `POST /mcp/intake` | 销售/老板 |
| 排产参谋 | `POST /mcp/schedule` | PMC |
| 齐套供应链 | `POST /mcp/supply` | 采购/PMC |
| 厂务简报 | `POST /mcp/ops` | 厂长/老板 |

发现页：`GET /mcp`

传输：**Streamable HTTP**（单 POST，响应 `application/json`）。  
鉴权：`Authorization: Bearer mcp_…`

## 发 Key（管理员）

```http
POST /api/v1/mcp-keys
Authorization: Bearer <后台 JWT>
Content-Type: application/json

{"name":"partner-agent","scopes":["intake","ops"]}
```

响应里的 `api_key` **只出现一次**；之后只能看到 `key_prefix`。吊销：`DELETE /api/v1/mcp-keys/{id}`。

`scopes`：`intake` / `schedule` / `supply` / `ops`，或 `*`。

## 客户端握手示例

```bash
curl -s https://YOUR_HOST/mcp/ops \
  -H "Authorization: Bearer mcp_xxx" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"0"}}}'
```

常用方法：`initialize` → `tools/list` → `tools/call`。

通用工具：`list_metrics`、`query_metric`。  
`schedule` 额外：`get_schedule_pool`、`get_schedule_settings`、`get_daily_load`、`generate_schedule_proposals`、`simulate_insert_order`（均不落库）。

## 配置

| 环境变量 | 含义 | 默认 |
|----------|------|------|
| `MCP_ENABLED` | 总开关 | `true` |
| `MCP_ALLOWED_ORIGINS` | Origin 白名单，`*` 任意 | `*` |
| `MCP_PROTOCOL_VERSION` | 默认协议版本 | `2025-03-26` |

## 明确不做

- 不暴露站内军师对话 / 记忆写库
- 不提供确认生产、确认排产、下 PO、放货等写工具
- 不做 NL2SQL；指标必须在白名单内
