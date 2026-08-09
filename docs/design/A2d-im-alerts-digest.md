# A2d 设计：IM 预警推送 + 进度日报（v1 stub）

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 P2-Next A2d
> **对象：** 租户级出站 Webhook（企微/钉钉群机器人协议兼容），不接第三方 SDK

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_a2d_im_alerts.py` 18 passed |
| API | settings / preview(alert|digest) 200 |
| 约束 | 只推不改；无 SDK |

---

## 1. 目标与边界

**目标**
异常（缺料 / 交期风险）与进度日报，靠现场吼一嗓子或事后翻 Excel 才知道。A2d 让这些结论可配置地推进企微/钉钉群机器人，PMC/老板不用天天开系统也能第一时间看到。

**只推不改（硬约束）**

- 本功能**只读**既有看板数据（`workshop_display_service`），**不写任何业务单据**、不改齐套/排产/报工/出货account。
- 推送失败（网络/超时/对方 4xx5xx）**绝不阻断**任何主路径；所有异常吞掉记录结果，不抛给调用方。
- 不接入真实企微/钉钉 SDK（不做应用凭证、签名、@人等企业级能力）；只用**群机器人 Webhook**协议最小子集（`POST JSON {msgtype:"text", text:{content}}`），兼容企微/钉钉自定义机器人。

**不做**

- 不做真正的定时任务/调度器（v1 无 cron；`send_alert_if_enabled` / `send_digest_if_enabled` 是留好给未来调度器调用的函数，本迭代 UI 只做「预览」与「试发」两个动作）。
- 不做多渠道路由、告警分级免打扰、失败重试队列。
- 不做消息可点回系统的深链跳转鉴权（v1 文本消息只含单号/摘要，不含可点击链接）。

---

## 2. 数据口径

事件来源统一取自 `workshop_display_service.workshop_display()`（看板同源，避免另开一套统计口径）：

| 事件类型 | 口径 | 来源字段 |
|----------|------|----------|
| `shortage` 缺料 | 订单有 BOM 且未齐套（`material_blocked=true`） | `material_blocks[]` |
| `delivery_risk` 交期风险 | `at_risk=true`（交期 ≤ today+2 且总进度 &lt;90%）或（急单且缺料） | `focus_orders[]` |
| `digest` 进度日报 | 昨日产量 + 今日在制概况 + Top5 重点订单 | `summary` + `focus_orders[:5]` |

租户配置 `events[]` 决定「开启后，哪些类型会被真的推送」；`preview` 接口不受 `events[]` 限制，始终可预览三类内容以便配置前先看效果。

---

## 3. 配置：`tenant.settings_json.im_alerts`

```json
{
  "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
  "enabled": false,
  "events": ["shortage", "delivery_risk", "digest"]
}
```

| 字段 | 说明 |
|------|------|
| `webhook_url` | 企微/钉钉群机器人 Webhook 地址；未填时预览可用，试发/正式推送会报错 |
| `enabled` | 总开关；关闭时 `send_*_if_enabled` 直接跳过（供未来调度器用） |
| `events` | 子开关白名单，取值 `shortage` / `delivery_risk` / `digest` |

默认：`enabled=false`，`events` 全选（首次开启即默认推全部三类，可再关子项）。

---

## 4. 服务：`app/services/im_alerts_service.py`

- `get_im_alerts_for_tenant` / `save_im_alerts_patch`：设置读写，模式与 `inventory_settings.py` / `reporting_settings.py` 一致。
- `collect_shortage_events` / `collect_delivery_risk_events`：从看板派生事件文本。
- `build_alert_payload(db, tenant_id, event_types=None)`：组装缺料+交期风险预警文本（干跑，不发送）。
- `build_daily_digest(db, tenant_id)`：组装进度日报文本（干跑，不发送）。
- `post_json(url, payload, timeout=5)`：`urllib.request` 原生 POST，任何异常均捕获返回 `{ok:false,...}`，不抛出。
- `send_test(db, tenant_id, kind, webhook_url_override=None)`：试发一条（忽略 `enabled`，仍需 `webhook_url`），用于「试发」按钮。
- `send_alert_if_enabled` / `send_digest_if_enabled`：预留给未来定时任务；本迭代不接调度器，UI 不暴露。

---

## 5. API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/im-alerts-settings` | admin | 读取配置 |
| PATCH | `/api/v1/im-alerts-settings` | admin | 改 `webhook_url` / `enabled` / `events` |
| GET | `/api/v1/ops/im-alerts/preview?kind=alert\|digest` | admin | 干跑预览（不发送），返回将要推送的文本与结构化事件 |
| POST | `/api/v1/ops/im-alerts/test-send` | admin | 试发一条到 `webhook_url`（body 可传 `kind` / 临时 `webhook_url` 覆盖，方便填地址后先测不保存） |

---

## 6. UI

`web/src/views/admin/ImAlertsAdminView.vue`：系统设置下新增一页「IM 预警推送」薄卡片。

- 开关 + Webhook 地址输入 + 事件类型多选（缺料 / 交期风险 / 进度日报）
- 「预览」：调 `preview`，Tab 切换预警/日报文本
- 「试发」：调 `test-send`，展示 HTTP 状态与结果；未填地址禁用按钮
- 保存走 PATCH；试发/预览不要求先保存（可用临时地址测通再保存）

---

## 7. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A2d-T1 | `im_alerts_service`：配置读写 + 事件收集 + payload 组装 + `post_json` | ✅ |
| A2d-T2 | API：settings GET/PATCH + `ops/im-alerts/preview` + `test-send` | ✅ |
| A2d-T3 | UI 薄卡片：开关/地址/事件 + 预览 + 试发 | ✅ |
| A2d-T4 | 单测：设置合并、payload 组装、`urlopen` mock 成功/失败、`send_test` 校验 | ✅ |
| A2d-T5 | 总纲状态 → ⚠️ 已实现待走查 | ✅ |
| A2d-T6 | 走查签字（真实企微/钉钉群验证一条预警+一条日报） | ⚠️ 待现场走查 |

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | v1 stub 落地：设置 + 服务 + API + UI + 单测 |
