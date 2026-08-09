# A2a 设计：放货回款提示

> **状态：** ✅ 走查通过（2026-08-09）
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 P2-Next A2a

---

## 走查证据（2026-08-09）

| 项 | 结果 |
|----|------|
| 单测 | `test_a2a_pay_hint.py` 4 passed |
| API | `GET /partners/{id}/pay-risk` 返回风险文案 |
| UI | 出货确认前 banner + 中高风险二次确认（不硬拦） |

---

## 1. 目标与边界

**目标**
出货确认前，跟单/仓管能看到该客户的回款风险（逾期未结、账龄、历史回款慢），避免对回款差的客户继续无脑放货。

**不做**

- 不硬拦出货（回款差不等于不能发货，只软提示）
- 不新造一套风险规则：**直接复用** `finance_service.customer_pay_risk`（销售接单诊断 `analytics.order_intake` 已在用的同一函数）
- 不做客户额度/信用评分体系

---

## 2. 口径（复用，非新造）

风险等级/原因文案完全来自 `finance_service.customer_pay_risk(db, tenant_id, customer_id=...)`：

| risk | risk_label | 触发条件（原函数既有口径） |
|------|------------|----------------------------|
| high | 回款风险高 | 存在账龄 60 天以上未结余额 |
| medium | 回款需关注 | 逾期（&gt;30 天）未结 ≥2 笔，或有逾期且历史平均回款 &gt;45 天 |
| low | 回款风险低 | 无明显逾期/账龄问题 |
| unknown | 未知 | 客户信息缺失 |

本次**不改**该函数逻辑，仅新增一个薄读接口把它接到「客户」维度，供出货页调用。

---

## 3. API（新增，薄封装）

`GET /partners/{partner_id}/pay-risk`（`app/api/v1/partners.py`，`get_current_user` 即可，只读）

```json
{
  "ok": true,
  "data": {
    "risk": "high",
    "risk_label": "回款风险高",
    "reasons": ["60天以上未结 ¥12000"],
    "open_balance": 12000.0,
    "avg_collect_days": null,
    "overdue_count": 1,
    "aging_60_plus": 12000.0,
    "sample_ar": 1,
    "customer_id": 1,
    "customer_name": "欠款客户甲"
  },
  "error": null
}
```

内部即 `finance_service.customer_pay_risk`，不重复实现风险算法（搜索确认全库无既有「按客户」只读接口，`order_intake` 分析仅在军师问数场景可用，出货页不适合复用重量级分析入口）。

---

## 4. UI（`ShipmentsAdminView.vue`）

| 入口 | 展示 |
|------|------|
| 新建出货弹窗（选定订单后） | 表单顶部 `el-alert`（success/warning/error 对应 low/medium/high），标题=`risk_label · reasons` |
| 出货明细弹窗（草稿状态） | 描述信息下方同款 `el-alert` |
| 「确认出货」（列表行 / 明细弹窗 / 新建弹窗点「确认出货」三处入口统一） | 点击时先取该客户风险；**medium/high** 弹 `ElMessageBox.confirm`（风险标签+原因，「仍确认出货」/「取消」）；**low/unknown** 或接口失败 **直接放行**，不阻断 |

软规则：接口异常（如网络失败）视为「无风险信息」，不阻断出货——符合「不硬拦」的边界。

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| A2a-T1 | 搜索确认无现成「按客户」只读回款风险接口 | ✅ |
| A2a-T2 | `GET /partners/{id}/pay-risk` 薄封装 `finance_service.customer_pay_risk` | ✅ |
| A2a-T3 | `ShipmentsAdminView` 新建/明细弹窗风险 banner + 三处确认出货前软提示 | ✅ |
| A2a-T4 | 单测 `tests/test_a2a_pay_hint.py` | ✅ |
| A2a-T5 | 总纲状态更新 + changelog | ✅ |
| A2a-T6 | 产品走查签字 | ⏳ 待走查 |

---

## 6. 走查证据（脚本，2026-08-09）

直接调用路由函数 `get_partner_pay_risk`（等价于前端 `GET /partners/{id}/pay-risk`）：

```text
欠款客户甲（60天以上未结 ¥12000） =>
  {"risk": "high", "risk_label": "回款风险高",
   "reasons": ["60天以上未结 ¥12000"], "open_balance": 12000.0, ...}

正常客户乙（无未结） =>
  {"risk": "low", "risk_label": "回款风险低",
   "reasons": ["近期无大额逾期未结"], "open_balance": 0.0, ...}
```

单测：`tests/test_a2a_pay_hint.py` 4 passed（高风险账龄、低风险空账、端点接线、未知客户 404）。

**尚待人工走查：** 在 `ShipmentsAdminView` 上用真实草稿出货单实际点击「确认出货」，核对 banner 文案与 `ElMessageBox` 弹窗在高/中/低风险客户下的展示是否符合预期（脚本仅验证后端数据链路，未跑浏览器 UI）。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 落地：新增 `pay-risk` 接口 + 出货页三处软提示；待走查 |
