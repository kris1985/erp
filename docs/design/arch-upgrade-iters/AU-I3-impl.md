# AU-I3 实现设计：排产切主 · 变更回滚

> **状态：** ✅ M1–M4 已落地（双轨关闭清单仍待产品关闸）  
> **需求：** [`AU-I3-schedule-change-rollback.md`](./AU-I3-schedule-change-rollback.md)  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md)  
> **验收：** [`ACCEPTANCE.md`](./ACCEPTANCE.md) §D  
> **依赖：** AU-I1（可产色码 + `create_execution`）；回滚叠 AU-I2 FG 语义  
> **原则：** 只荐人确认、非静默；不改写旧 MO `ScheduleDraft` 引擎本波。

---

## 0. 切片

| 切片 | 内容 | 可演示 | 状态 |
|------|------|--------|------|
| **I3-M1** | 色码可产池 → HITL 草案 → 确认落规格执行单 | 勾选两 SO → 草案 → 确认出 XE | ✅ |
| **I3-M2** | 插单/急单冲击未开工交期（HITL） | 已开工交期不动 | ✅ |
| **I3-M3** | 未开工改量；已开工禁改码；补码新单 | 改码拦截 | ✅ |
| **I3-M4** | 停产释放池与料；返修勾平；双轨关闭清单 | G3/G4 | ✅（双轨清单文档化，关旧入口未切） |

推荐：**M1 → M2 → M3 → M4**。

---

## 1. I3-M1 领域契约

```text
list_producible（色码需求池）
  → propose：按 (product,color,size) 分组，落 execution_schedule_drafts（不占 allocated）
  → 人确认
  → 各组 create_execution(commit=False) → 一次 commit
```

确认前剩余可产不变；确认后与手工合单同效果（分配 + 桥接生产单）。

**不做（M1）：** 插单、停产回滚、关 1∶1、改写 MO 倒排草稿。

---

## 2. 数据模型（M1）

```text
execution_schedule_drafts
  id, tenant_id
  status: draft | confirmed | discarded
  note, payload(JSON), created_by, created_at, confirmed_at
```

`payload.groups[]`：`own_product_id, color_id, size_id, total_qty, items[{sales_order_line_item_id, qty, …}]`

---

## 3. API（M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/schedule/color-pool` | 色码可产（包装 list_producible） |
| POST | `/schedule/execution-drafts` | 生成草案 |
| GET | `/schedule/execution-drafts/{id}` | 草案详情 |
| POST | `/schedule/execution-drafts/{id}/confirm` | 确认落执行单 |
| POST | `/schedule/execution-drafts/{id}/discard` | 丢弃 |

---

## 4. 单测（M1）

| 文件 | 覆盖 |
|------|------|
| `test_au_i3_execution_schedule.py` | 两来源一组；确认前不占；确认后 ratio；超量/discard 拒绝 |

---

**进度：** I3-M1 ✅（色码池 + 草案 HITL + 确认落执行单）。  
**进度：** I3-M2 ✅（急单仿真/确认；未开工延后；已开工冻结）。  
**进度：** I3-M3 ✅（未开工改量；已开工禁改码/改量；补码新单）。  
**进度：** I3-M4 ✅（停产 HITL 释放可产/料/未报工筐；返修冻结入库勾平）。  
**下一步：** 双轨关闭需产品关 SO→1∶1 闸门后再勾 §3；合批弱化另波。  
**回链：** README / AU-I3 需求文头。

---

## 5. I3-M2 领域契约

```text
simulate_rush_insert(execution_id, push_days)
  insert 标记将加急
  peers:
    started (在制/完成/有完成量/已开裁) → frozen（交期不动）
    未开工且 delivery >= insert.delivery → +push_days
confirm → is_rush + 写交期（再校验 started）；桥接生产单同步
```

API：
| 方法 | 路径 |
|------|------|
| POST | `/schedule/execution-rush/simulate` |
| POST | `/schedule/execution-rush/confirm` |

扩表：`spec_execution_orders.is_rush / rush_reason / rushed_at`  
单测：`test_au_i3_rush_insert.py`

---

## 6. I3-M3 领域契约

```text
change_execution_qty（未开工）
  替换全部现有分配 qty → 重算 ratio → 调整 allocated_qty → 同步桥接单 qty/材料
  dry_run 可预览
  started → started_block（减产/停产 → M4；补码 → 新单）

change_execution_size
  started → size_change_blocked
  未开工 → 引导取消重排（禁止无痕改 size_id）

create_supplement_execution
  = create_execution（备注强制带「补码」）
  占用可产剩余；不改已有已开工单
```

API：
| 方法 | 路径 |
|------|------|
| POST | `/executions/{id}/change-qty` |
| POST | `/executions/{id}/change-size` |
| POST | `/executions/supplement` |

`execution_out.started` 暴露开工态。  
单测：`test_au_i3_execution_change.py`

---

## 7. I3-M4 领域契约

```text
simulate_halt / confirm_halt（已开工）
  floor = 已入库/已出货 + 不可作废在制
  voidable = open 且无报工流水
  target=null → 减至 floor；target=0 且 floor=0 → cancelled + 取消桥接单 + release_unused_arrived
  释放 allocated_qty；同步 shop qty / sync_requirements；可选 void_trace_unit

carrier_available_qty（G4）
  qty − 未关闭 rework 冻结
  部分 scrap → 扣减 qty；整卡 scrap → scrapped
  warehouse_basket：有返修冻结则 rework_frozen
```

API：
| 方法 | 路径 |
|------|------|
| POST | `/executions/{id}/halt/simulate` |
| POST | `/executions/{id}/halt/confirm` |

单测：`test_au_i3_execution_halt.py`

### 双轨关闭条件（§3）现状盘点（本切片不关旧入口）

| 条件 | 现状 |
|------|------|
| 新单默认色码可产 → 执行单 | 池/草案/合单已有；SO「下生产」1∶1 仍活 |
| 齐套/领料/报工/出货认执行或销售色码 | 执行路径已接；桥接 `orders` 仍是料/报工主键 |
| 旧 orders 1∶1 只读/迁移 | 未关 |
| 合批非报工/出货主体 | 话术有；合批打印/API 仍在 |
| §11.5 闭环加测 | G3/G4 单测已补；端到端 UI 未宣称 |

**关闸条件：** 产品确认默认走执行单 + 关掉/只读 SO→1∶1 后再勾 ACCEPTANCE「双轨关闭清单」。
