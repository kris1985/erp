# 后续待办（备料 / 库存架构）

> **产品定稿（2026-08）**：库存只认池；订单靠分配；领料是升级开关。  
> 到货若 PO 行已挂订单 → **自动分配**（跟单体感保留，不是第二套库存模型）。  
> 前端用 **capabilities** 控菜单是否存在；RBAC 控谁能点。

---

## 定稿模型

```text
到货 → 一律进池（唯一库存真相）
     → 分配到订单（齐套只看已分配；PO 挂单到货可自动分配）
     → 领料发车间（默认不强制；issue_required 开通后强制）
```

| 概念 | 含义 | 不是 |
|------|------|------|
| **池** | 材料库存唯一余额 | 余料垃圾桶（旧 A 叙事） |
| **分配** | 账上归哪个订单（齐套/缺料/停单） | 领料发车间 |
| **领料** | 货发给车间；可开关强制 | 分配的别名 |

**废弃对外叙事**：A/B/C 三套到货哲学。对内不再维护 `order_first` 作为长期模式。

过渡期（现网）：`arrived_qty` 仍可当作「已分配到订单」的投影；`receive_po` 尚未改成先入池再写分配流水前，行为可暂像旧挂单，但产品与配置按本模型描述。

---

## 租户配置

```text
tenant.settings_json.inventory
  model: "pool_allocate"              # 固定；仅作版本标识
  auto_allocate_on_receive: true      # PO 行挂订单时到货自动分配
  issue_required: false               # true = 强制领退料 + 闸门（原「C」）
  kit_include_unallocated_pool: false # 齐套是否把「未分配池」算可用（默认否：必须先分配）
  cost_basis: "po_received" | "issued"
  capabilities:                       # 可由上面字段推导，也可显式覆盖
    shared_pool: true                 # 库存池菜单（始终）
    allocate_ui: false→true           # 「分配到订单」菜单/齐套页按钮（中期-2）
    stock_docs: false                 # 领退料单（随 issue_required）
    issue_gate: false                 # 开裁前校验已领（随 issue_required）
    warehouse_dim: false              # 多仓货位（更后）
```

推导规则：

- `issue_required=true` → `stock_docs=true`、`issue_gate=true`、建议 `cost_basis=issued`
- 默认租户：`issue_required=false`，`allocate_ui` 在分配 API/页就绪前保持 `false`（菜单不出现空页）

登录与 `/auth/me` 下发完整 `inventory` 对象（含 capabilities）。

---

## 权限 vs 能力

| 层 | 来源 | 作用 |
|----|------|------|
| capabilities | 租户 inventory | 功能/菜单是否存在 |
| permissions | 角色 RBAC | 谁能操作已存在功能 |

`visible = hasCapability(cap?) && hasPermission(perm)`  
无 capability 时 API 亦拒绝（`capability_disabled`）。

---

## 前端菜单（采购备料 / 仓储）

| 菜单 | path | perm | cap | 默认 |
|------|------|------|-----|------|
| 缺料 | `/admin/material-shortages` | `menu.material_shortages` | — | ✅ |
| 采购单 | `/admin/purchase-orders` | `menu.purchase_orders` | — | ✅ |
| **库存池**（原公用库存） | `/admin/shared-materials` | `menu.shared_materials` | `shared_pool` | ✅ |
| 分配到订单 | `/admin/stock-allocate` | `menu.stock_allocate` | `allocate_ui` | 中期-2 开 |
| 领退料单 | `/admin/stock-issues` | `menu.stock_issues` | `stock_docs` | `issue_required` 时 |
| 库存模式（说明/开关） | `/admin/inventory-settings` | admin | — | ✅ 只读+远期开关展示 |
| 仓库货位 | `/admin/warehouses` | `menu.warehouses` | `warehouse_dim` | 更后 |

页内（同一路由，按 cap 显隐）：

| 位置 | 默认（不强制领料） | `issue_required` |
|------|-------------------|------------------|
| 齐套 Tab | 需求/已分配/缺/待采；轻量「发车间登记」 | 隐藏轻量登记 → 领/补领/退料 |
| 齐套 Tab | `allocate_ui` 后：「从池分配」 | 同左 |
| 到货 | 入池；挂单行自动分配；展示订单号+拆分建议 | 同左 |
| 停单 | 未发占用释放回池 | + 已发未耗走退料 |
| 利润 | `cost_basis=po_received` | 默认 `issued` |

---

## 前端结构

```text
web/src/
  stores/auth.ts                 # inventory + hasCapability()
  inventory/types.ts             # InventoryConfig 类型
  layouts/AdminLayout.vue        # perm ∧ cap；库存池文案
  router/index.ts                # meta.capability
  views/admin/InventorySettingsAdminView.vue
  views/admin/StockAllocateAdminView.vue   # 中期-2
  views/admin/StockIssuesAdminView.vue     # 强制领料时
```

---

## 后端结构

```text
app/services/inventory_settings.py   # 默认值、合并、capabilities 推导
Tenant.settings_json                 # 存 inventory 等
receive_po → 目标：入池 +（可选）自动分配流水
allocate API                         # 中期-2
stock issue/return docs              # issue_required
停单释放回池                         # 近期
```

编码约定：

1. 到货/分配/领退/停单释放只走 service，前端不写库存字段  
2. 池增减集中（现 `adjust_shared_stock` + ledger；演进后仍单一入口）  
3. 齐套读「需求 / 已分配 /（可选）未分配池」投影  
4. 采购明细保留订单挂钩，便于自动分配  
5. 不建完整 WMS；不默认强制领料  
6. 菜单 = capability ∧ permission  
7. **配置必须接到 service**；仅改文案/菜单不算切换模型  
8. 派工「未分配池」（配额）≠ 物料「库存池/分配」——文案勿混  

---

## 全局补全（此前方案偏单点，此处补齐）

> 结论：骨架只解决「怎么讲、怎么显隐」。**齐套/到货/利润/取消/看板仍按旧语义跑**。未定不变量与全链路挂钩前，不要宣称已切换模型。

### 1. 不变量（必须写死，否则全局会串账）

```text
物理库存（池余额） + Σ(未完工单已分配未发) + Σ(已发在制…)  = 可解释的账实关系
issued ≤ allocated
在途 = PO 订购 − PO 实收（不要用 arrived 反推在途）
齐套默认：required − allocated（不得把整池全额借给每一单）
```

现网大坑：`kit` 对每个订单都减**整池** `shared_qty` → 多单同时齐套/零待采，**池被重复占用**。这是全局正确性第一优先，比菜单更要紧。

### 2. 全链路挂钩（建单→出货→停单）

| 环节 | 现网 | 定稿后必须 |
|------|------|------------|
| 建单/改量 | 改订单量**不重算**物料需求 | 改量触发重算；已分配 > 新需求 → 回收或拦截 |
| BOM 刷新 | 可保留 arrived/issued | 保留「已分配/已发」进度，需求按新 BOM |
| 齐套标签 | 订单列表/详情含池；**筛选只看 arrived**（自相矛盾） | 标签=筛选=看板=`同一套`齐套函数 |
| 车间看板待料 | 跟 kit（含池） | 跟同一套；急单抢池靠分配优先级，不能静默双吃 |
| 缺料→PO | 已挂订单行 | 保留；待采基于「未分配缺口」 |
| 到货 | 有单行直接 `arrived+=`，余量进池 | **一律入池** → 自动/手动分配；`arrived` 仅投影 |
| 发车间 | 登记可不扣库存 | 默认轻量；`issue_required` 时正式领料扣分配 |
| 报工/开裁 | **无料闸门** | 仅 `issue_gate` 时拦；挂钩点要定（首道？扫码报工？） |
| 出货 | 不校验材料 | 明确：出货不卡料（或仅提示），避免和财务口径缠死 |
| 取消/停单 | **材料不回流** | 未发分配→回池；已发→退料或报废；向导必做 |
| 利润 | 按 PO 实收挂单，忽略池均价/发料 | 读 `cost_basis`；从池领用要能落到订单成本（防双重计或不计） |

工资/计件：**不耦合**材料（保持）。

### 3. 角色与职责（全局分工）

| 动作 | 建议角色 | 说明 |
|------|----------|------|
| 采购到货（入池） | 主管/仓兼采购 | 今日即 PO receive |
| 分配/回收 | 主管（组长只读或缺料） | `stock_allocate` 开后写入默认授权 |
| 轻量发车间 | 组长/主管 | `issue_required=false` |
| 领退料过账 | 仓管/主管 | 仅强制领料租户 |
| 改 arrived 手工 | 应收紧或废除 | 否则绕过分配账 |

API 无 capability 时拒写（现仅藏菜单，**supply_chain 未校验**）。

### 4. 成本全局规则（防双计）

- 挂单采购实收进成本时，同批货不得因「又从池发料」再计一次。  
- 无 PO、纯池料发给某单：用池 `avg_unit_cost` 计入该单。  
- `cost_basis=issued`：以发料−退料为准；未发占用不算完工成本。  
- 客供：占齐套、**不进材料成本**（规则要写进 kit 与 finance）。

### 5. 迁移与双读（全局上线风险）

不可「某一天 receive 改入池」而不处理历史 `arrived_qty`，否则：**池+arrived 双算齐套**。

建议顺序：

1. 先修「多单重复吃池」+ 齐套三入口一致（仍可用 arrived 投影）  
2. 停单释放回池  
3. 加分配流水 / `allocated` 缓存；历史 arrived → 视为已分配；池按「实物−占用」回填或对账  
4. 再改 `receive_po` 真·入池+自动分配  
5. 最后开 `allocate_ui`；租户关掉「未分配池算齐套」  

双读期：配置 `inventory.cutover_phase`（可选）或仅内部 feature，避免老板一键翻车。

### 6. 方案仍易漏的边界

- **客供料**：如何「分配」而不走池采购  
- **改单减量 / 超分配**：自动回收还是人工确认  
- **急单**：分配队列优先级（交期/`is_rush`）  
- **色码 BOM**：需求按总双数，色料会错——分配再精也救不了需求错（单独立项，勿假装库存模型能解决）  
- **退料 / 反冲领料**：ledger 类型与停单联动  
- **派工「未分配池」文案**：与物料分配撞名  
- **种子数据 / 演示脚本**：仍教旧路径，上线前要改  
- **测试**：现无材料齐套/到货/取消回流用例  

### 7. 全局验收标准（做完中期应能答「是」）

1. 同 SKU 池=10，两单各缺 10 → **不能同时齐套**（除非真分配互斥）  
2. 到货后池与订单占用可对上账；取消后未用料回池  
3. 订单列表齐套 = 缺料页 = 看板待料  
4. 利润口径与库存来源一致、可切换且不双计  
5. 关 `issue_required` 时生产不被领料卡住；打开后闸门点明确且可测  

---

## 实施清单

### 骨架（本次落地）

- [x] 定稿文档：池 + 分配 + `issue_required`
- [x] `Tenant.settings_json` + `inventory_settings` 服务
- [x] `/auth/login`、`/auth/me` 下发 `inventory`
- [x] 前端 `hasCapability` + 菜单 cap；「公用库存」→「库存池」
- [x] admin「库存模式」说明页（只读；强制领料标记远期）

### 全局正确性（优先于炫功能）

- [x] **齐套唯一函数**：列表筛选 / 标签 / 缺料 / 看板共用 `KitContext`（池按急单/交期拆分承诺）
- [x] **禁止多单重复占用整池**（可承诺量拆分，急单优先）
- [x] 配置项 `kit_include_unallocated_pool` 接入 kit（`resolve_include_shared`）
- [x] 写接口 capability 校验（分配/领料 API 已在 supply_chain / stock_doc_service 校验）
- [x] 订单取消 → 未发占用释放回池
- [x] 订单改量 → 重算需求 + 超额占用回池
- [x] 成本：`cost_basis` 接入利润（`po_received` / `issued`）；客供不计材料成本
- [x] 术语：库存池 / 池承诺 / 池余额（缺料页）；派工「未分配池」仍为配额语义
- [x] 迁移：arrived→已分配投影的对账报告与切仓标记（不强制改写历史占用）
- [x] 材料路径自动化测试（`tests/test_material_kit.py`）

### 近期（体验）

- [x] 到货弹窗展示订单号
- [x] 总量到货 → 建议拆到分订单行
- [x] 齐套与 `kit_include_unallocated_pool` 文案/默认一致（过渡期默认仍可开，切真分配后关）

### 中期-2（真·入池 + 分配）

- [x] `receive_po`：先入池；挂单行自动分配（`allocate_to_order` 流水；`arrived_qty` 作占用投影）
- [x] 手动分配/回收 API + `allocate_ui`（菜单「分配到订单」+ 订单齐套页）
- [x] manager/leader 默认授权含 `stock_allocate`
- [x] 在途只认 PO 未收量（`in_transit_qty_for_requirement`）
- [x] 历史数据对账/双读期（旧「直接挂 arrived」存量）→ `GET /inventory-settings/reconcile` + 切仓标记

### 远期（强制领料）

- [x] 领退料单；`issue_required` 可开（库存模式开关 + `/admin/stock-issues` + 订单齐套页领/退）
- [x] 闸门挂钩点：`submit_report` 前 `assert_issue_gate`（关键料须已领）
- [x] 隐藏轻量发车间；利润默认按发料（开强制领料时 `cost_basis=issued`）
- [ ] （更后）`warehouse_dim`；色码级 BOM 单独立项

---

## 明确不做

- 完整 WMS（货位、盘点、强制 FIFO）
- 默认强制领料
- 长期保留 A/B/C 三套到货故事
- 为未开通能力复制三套页面
- 同一租户并行两套库存真相
- 用库存模型「顺便解决」色码 BOM 不准（需求层另做）
- 材料与工资账耦合

---

# 派工 / 报工 / 工资 / 工序定价

> **节奏：先做近期 → 再做中期；AI 暂不做。**  
> 三角色勿混：**派工=闸门**；**报工=事实账本**；**工资=valid 报工兑现**。  
> 三池勿混：进度 / 派工配额 / 工资。验收：派得清 → 报得进拦得住 → 工资对得上。

## 产品结论（决策备忘）

1. 报工锁价已落地；改价只影响新报工；不上完整价格版本库（仅强审计/频繁改价时再议）。  
2. 定价绑产品；类型在工序主数据；建单拷贝结构/类型，不拷贝单价。  
3. 派工配额 ≠ 月度底薪定额。  
4. 返修政策若改，派工/报工/工资一起定。  
5. 排产只走「**建议草稿 → 人工确认 → 写 assignment**」；确认前不改派工/报工/工资。  
6. 对外话术：「排产助手 / 规则方案 → 人工确认 → 派工」；**不上 MES 级 APS**。AI（DeepAgents）只调规则引擎工具，永不自动落库。

---

## 排产（怎么做）

> 教材能力（倒排/正排/工序联动/换线/瓶颈/插单）当**计划原则**，不一次性做成系统。  
> 已有「眼睛」：交期与交期风险、瓶颈工序看板、齐套、报工进度、`is_rush` 人工插单。  
> 缺的是「手」：建议时间窗与拆量草稿；**先规则，后可选 AI 增强**。

### 原则

1. **默认倒排**（交期倒推各工序最晚开工/完工窗）；**正排作对照**（有粗产能后再算可能完工日，晚于交期则提示加班/外发）。  
2. 硬约束用**确定性规则**（交期、工序顺序、齐套、配额）；AI 最多做解释与方案生成，**永不跳过确认、永不自动落库**。  
3. 插单继续人工规则（`is_rush` + 沟通交期）；系统可列「挤压哪些单 / 补排选项」，不做全自动重排。  
4. 进度反馈复用报工账本，不另造汇报体系。  
5. 验收：人改草稿比从零排快；确认后与手工派工同路径可审计；**关掉 AI 后规则草稿仍可用**。

### 节奏

| 阶段 | 做什么 | 不做什么 |
|------|--------|----------|
| 现在 | 规则引擎方案 + 排产助手（DeepAgents/DeepSeek，工具白名单） | 不上 MES APS、无人值守落库 |
| 中期 | 粗产能主数据打磨、瓶颈提示、方案对比体验 | 不自动改配额/交期/工资 |
| 中期后 | 历史节拍自学习默认工期/产能；问数技能并入军师壳 | 不把 AI 绑成主引擎 |

### 中期待办（排产草稿）

- [x] 规则倒排：交期 + 工序顺序 + 粗工期 → 各工序建议开工/完工窗（仅草稿）
- [x] 自动拆数量 → 派工草稿 → 人确认保存（写 assignment）
- [x] 工序 `default_days` + 工作日/节假日倒排；粗产能正排/标红/日负荷
- [x] 智能方案对比（保交期/保现场/只排齐套）→ 采用进草稿
- [x] 插单仿真三套方案 + 影响清单
- [x] 排产助手 Agent：DeepAgents + DeepSeek；多轮 checkpoint；长期记忆；禁文件系统
- [ ] 看板瓶颈节奏提示（展示层）
- [x] 只读计划日历（按月·天格子；已确认 OrderProcess；2025/2026 法定节假日与调休）

### 工序用料归属（已落地）

- [x] 分类 `default_consume_process_id` + BOM `consume_process_id` + 订单快照
- [x] 齐套 `first_kit_ok` / `by_process`；确认排产接首道/分段闸门
- [x] 管理端：分类/产品 BOM/订单用料/排产页

### 明确不做（排产）

- 完整 MES 排产中心、换线/换模精细扣除、跨车间强制日物流平衡
- AI 自动派工 / AI 改工资 / 无人值守自动落库
- 把进度、派工配额、工资三池合成一个「智能排产数」

---

## 一、近期（先做完再进中期）

### 1.1 工资与规则

- [x] （可选）租户配置：未派是否可报、返修是否计薪、超计划确认

### 1.2 工序 CRUD 约束

- [x] 工序硬删引用校验（目前以停用 `is_active` 为主，无硬删入口）
- [x] 产品加工序「同步到在制单」显式开关（默认不同步，保持现状）

---

## 二、中期（近期完成后再做）

### 2.1 优先

- [ ] **集体返修**（先定薪政策再放开）

### 2.2 其后

- [ ] assignment 挂 `station_id` + 扫码校验
- [x] 排产建议草稿（见上方「排产」专节：倒排优先 → 确认写 assignment）
- [ ] 产线维度与负荷看板（有需求再做）
- [ ] 完整价格版本表（仅强审计/频繁改价时）

---

## 三、人事：奖惩 + 请假（已定稿，以后再做）

> 方案定稿于 2026-08；**暂不实现**。Cursor 计划副本：`.cursor/plans/奖惩请假管理_cccc6c97.plan.md`（若本地有）。

### 约定

- **奖惩**：金额自动计入对应 `year_month` 应发；该月已月结锁定后不可增改删
- **请假**：管理端登记，`pending → approved / rejected`；`admin` / `manager` 审批。员工 H5 自助提交后续再接
- **全勤奖**：作为奖惩类型手工录入（不做自动规则引擎）

### 数据模型

**`worker_adjustments`（奖惩）**

- `tenant_id`, `worker_id`, `year_month`（YYYY-MM）
- `kind`: `reward` | `penalty`
- `category`: `full_attendance` 全勤奖 / `overtime` 加班奖 / `late` 迟到扣款 / `other`
- `amount`（正数；结算时 reward 加、penalty 减）
- `title`, `notes`, `created_by`, `created_at`

**`leave_requests`（请假）**

- `tenant_id`, `worker_id`
- `leave_type`: `personal` / `sick` / `annual` / `other`
- `start_date`, `end_date`, `days`
- `reason`
- `status`: `pending` | `approved` | `rejected` | `cancelled`
- `reviewed_by`, `reviewed_at`, `review_note`
- `created_by`, `created_at`

### 后端

- 新建 `app/services/hr_service.py`、`app/api/v1/hr.py` 并注册路由
- 奖惩：`GET/POST/PATCH/DELETE /worker-adjustments`（写前校验月结未锁）；列表带奖励/扣罚/净额汇总
- 请假：`GET/POST /leave-requests`，`POST /{id}/approve|reject|cancel`
- 工资：`month_salary` / `month_salary_all` 加 `adjustment_net`，`total_wage = settle + adjustment_net`；导出 CSV 加奖惩列

### 前端 / 权限

人事工资菜单新增：

- `menu.adjustments` → `/admin/adjustments` · `AdjustmentsAdminView.vue`
- `menu.leaves` → `/admin/leaves` · `LeavesAdminView.vue`
- `btn.adjustments.write`、`btn.leaves.approve`（manager 默认有）

工资列表增加「奖惩」列与合计行净额。

### 实现顺序（以后开做时）

1. Models + hr_service + API
2. Salary 结算接入奖惩
3. 权限 / 路由 / 侧栏
4. 两个 Admin 页 + 工资页列

---

## 暂不做 / 明确不做

- **AI 派工、AI 改工资、无人值守自动落库**（排产 AI 仅允许「建议层 + 确认」，见「排产」专节）
- 完整 MES 排产中心、复杂价目审批流
- 三池强行合成一个数
