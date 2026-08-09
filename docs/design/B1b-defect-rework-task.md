# B1b 设计：不良 → 返修任务

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §7 B1b  

---

## 1. 目标与边界

**目标**  
登记不良后可「派返修」生成个人返修任务 → 列表筛未完成 → 责任人返修报工或后台完成 → 任务关闭并可关不良。

**不做 / 禁区**

- **集体返修**（`report_service`：集体工序 + `report_type=rework` 直接拒；派任务亦拒集体工序）  
- 自动改合格数账本语义  
- 复杂 APS / 返修排产  

---

## 2. 主路径

1. 不良开放 + 处置为返修（或派时改为返修）  
2. 「派返修」：指定返修工人、工序（默认责任工序）、数量（默认不良 qty）  
3. 生成 `rework_tasks`（pending）  
4. `/admin/defects` 可筛「未完成返修」  
5. 完成：后台「完成」或个人 `report_type=rework` 匹配单/工序/人后自动勾连完成  
6. 任务 done 时可同步关闭不良  

---

## 3. 数据 `rework_tasks`

| 字段 | 说明 |
|------|------|
| defect_event_id | 关联不良 |
| order_id / process_id / worker_id | 生产单、返修工序、承接人 |
| color_id / size_id | 可选，自不良带出 |
| qty | 返修双数 |
| status | pending / done / cancelled |
| completed_work_log_id | 可选 |
| note / created_at / completed_at | |

---

## 4. API

| 方法 | 路径 |
|------|------|
| POST | `/defect-events/{id}/rework-tasks` |
| GET | `/rework-tasks?status=pending` |
| POST | `/rework-tasks/{id}/complete` |
| POST | `/rework-tasks/{id}/cancel` |
| GET | `/defect-events?pending_rework=true` |

---

## 5. 任务

| ID | 内容 | 状态 |
|----|------|------|
| B1b-T1 | 模型 + 服务 | ✅ |
| B1b-T2 | API + 报工勾连 | ✅ |
| B1b-T3 | DefectsAdminView 派/筛/完成 | ✅ |
| B1b-T4 | 单测 + 集体返修仍禁回归 | ✅ |

---

## 6. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿并开干 |
| 2026-08-09 | 落地：API/UI/报工勾连；集体工序返修按类型硬拦 |
| 2026-08-09 | **走查通过**：230711 开线→派返修→后台完成关不良；脏污→派→返修报工勾连 #2；成型返修仍禁 |
