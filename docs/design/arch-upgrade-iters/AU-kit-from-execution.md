# 去桥接 · 齐套/领料/锁料认执行单

> **状态：** ✅ M1+M2 已落地 · 2026-08-13  
> **前置：** 方案 C 执行单头；出货已认销售（[`AU-ship-from-sales.md`](./AU-ship-from-sales.md)）  
> **目标：** 缺料汇总 / 锁料 / 齐套读口 / 领退料 **对人暴露执行单头**；账本数量仍挂桥接 `order_id` 双写。

---

## 1. 裁决

| 问题 | 裁决 |
|------|------|
| 齐套看谁？ | **执行单头** `GET …/headers/{id}/materials`；内部 `shop_order_id` → 现网 `get_order_kit` |
| 锁料/回收？ | 执行单头路径为主；旧 `/orders/{id}/materials/…/allocate` 保留 shim |
| 缺料列表？ | 主显 `header_no`；生产单号降为次要 |
| 用料行？ | 增 `header_id`；多码共桥接不钉单一 `execution_id`（可空） |
| 领退料单？ | `stock_docs.header_id` 双写；`order_id` 仍必填过渡 |

---

## 2. 切片

| 切片 | 内容 |
|------|------|
| **M1** | schema `header_id`；stamp；`get_header_kit`；创建执行单时回写 |
| **M2** | 头级 allocate/deallocate API；缺料/锁料候选带 header；执行单详情用料+锁料；UI 文案 |
| **M3**（可后） | 采购草稿按 `header_ids`；强制领料建单选执行单 |

本波做 **M1+M2**（已落地）：
- `order_material_requirements.header_id` / `stock_docs.header_id`
- `GET/POST /executions/headers/{id}/materials…`
- 缺料/锁料列表主显执行单号；执行单详情可锁料
- 测试：`tests/test_au_kit_from_execution.py`
