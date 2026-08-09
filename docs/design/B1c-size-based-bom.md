# B1c 设计：按码用量 BOM（关键料）L1+L2

> **状态：** 已验收（T1–T6；2026-08-09 走查签字：单测 `test_b1c_size_bom` + UI 尺码列）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md) §4.1 / §7 B1c  
> **原则：** 大底这条链「需求→缺料→采购→池」按码闭环；未按码料零回归；不上全仓 WMS。

---

## 0. 定稿拍板（建议默认）

| # | 项 | 定稿 |
|---|-----|------|
| 1 | 库存/池 | **轻量 B**：仅 `usage_by_size=true` 的料，池键 = `(tenant, supplier_product_id, size_id)`；其它料不变 |
| 2 | 缺系数的码 | **禁止刷新 BOM**（或返回明确错误列出缺码）；码表可一键「按 sizes 补全 coeff=1」降低摩擦 |
| 3 | 码段 | **P1 只做精确 `size_id`**；码段 from–to → v1.1 |
| 4 | PO 行 | **加可空 `size_id`**；按码需求生成草稿时 **必填** |
| 5 | 标记位置 | **BOM 行**为硬开关；分类可配「建议按码 + 默认码表」仅预填 |

---

## 1. 目标与边界

**目标（中小厂场景）**  
PMC/采购能按码看到大底缺多少、采多少、池里各码剩多少；面料等仍按总双。

**不做**

- L3 按色、L∞ 全矩阵、楦刀模专档、全仓货位 WMS  
- 合批/合单/报工主体变更  
- 未标记料任何行为变化  

---

## 2. 端到端怎么走（业务）

```text
① 建码表「大底通用」：为 35–45 各填 coeff（多为 1，大码可 1.05）
② 产品 BOM：大底行勾选「按码用量」并绑码表；面料行不勾
③ 确认生产单（或刷新 BOM）
    → 面料：1 行 = 单耗 × 总双 × (1+损耗)
    → 大底：每码 1 行 = 单耗 × 该码双数 × coeff × (1+损耗)
④ 齐套/缺料：大底按码列出短缺；面料一行
⑤ 从缺料建采购：大底每码一行 PO，带 size_id
⑥ 到货入池：按码入账（同料号不同码不相占）
⑦ 分配/领料：按码需求扣按码池
```

---

## 3. 数据怎么改

### 3.1 新表

```text
material_size_usage_tables
  id, tenant_id, name, notes, created_at

material_size_usage_coeffs
  id, tenant_id, table_id, size_id, coeff  # Decimal
  UNIQUE(table_id, size_id)
```

### 3.2 改表

| 表 | 字段 |
|----|------|
| `own_product_materials` | `usage_by_size BOOL DEFAULT 0`；`size_usage_table_id NULL` |
| `order_material_requirements` | `usage_by_size BOOL`；`size_id NULL`；逻辑唯一见下 |
| `purchase_order_lines` | `size_id NULL` |
| `shared_material_stocks` | `size_id NULL`；唯一键改为 `(tenant_id, supplier_product_id, size_id)`（未按码 size_id 固定 NULL） |
| `shared_material_ledgers`（若有） | 同步带 `size_id`，与库存流水一致 |

**需求行合并键**

```text
未按码：(order_id, supplier_product_id, size_id IS NULL)
按码：  (order_id, supplier_product_id, size_id)
```

**池键约定**

```text
未按码料 / 历史行：size_id = NULL（与今天一行一料等价）
按码料：size_id = 具体码；分配时需求行 size 必须匹配池 size
禁止：用 NULL 池去满足带 size 的需求（或反之）
```

迁移：现有库存全部 `size_id=NULL`；上线后仅新按码入池产生带码余额。

### 3.3 公式

```text
未按码：required = qty_per_pair × order.total_qty × (1+loss%) + loss_fixed

按码：对每个 order_item.size_id
  若码表无该 size → 刷新失败（列出缺失码）
  required(size) = qty_per_pair × item.qty × coeff(size) × (1+loss%)
  + loss_fixed 仅加在首码行一次（不按码拆、不重复加）
```

---

## 4. 代码改哪里（实现地图）

| 层 | 文件/点 | 做什么 |
|----|---------|--------|
| 模型/迁移 | `models` + `db_schema` | 上表字段与唯一约束 |
| 算料 | `material_service.calc_required_qty` / `refresh_from_bom` / `recalculate_required` | 分支按码展开；缺码报错 |
| 齐套池 | `build_pool_credits` / allocate / deallocate | 键含 size；只匹配同码 |
| 缺料 | `list_shortages` | 输出 `size_id` / `size_value` |
| 采购 | `create_drafts_from_shortages` | PO 行写入 `size_id` |
| MRP/接单 | `simulate_mrp_from_bom` 等 | 按码吃 `order_items`/`line items` |
| API/Schema | materials、BOM、PO、stock | 进出参带新字段 |
| UI | 码表页；产品 BOM 开关；用料/缺料/采购列尺码 | 见 §5 |
| 单测 | 未按码回归；37/42 不同需求；同料异码池不互占；PO 带码 | 必过 |

---

## 5. UI 主路径

1. **主数据 → 用量码表**：新建、按租户尺码填系数、「一键补全缺失码=1」  
2. **自有产品 → BOM**：行开关 + 选码表；开启无表则保存失败  
3. **生产单 → 用料**：尺码列；刷新按钮吃新逻辑  
4. **缺料 / 采购草稿**：尺码列；确认草稿可见码  
5. **池库存**（若有界面）：按码料显示尺码余额  

---

## 6. 分阶段落地（仍是一个 B1c，内部分批）

```text
批次 1（能算对）
  码表 + BOM 标记 + refresh 按码展开 + 单测回归
批次 2（能采对）
  缺料展示 + PO.size_id + 从缺料建草稿
批次 3（能齐套不串码）
  池/流水 size_id + 分配匹配 + 入池出池带码
批次 4
  BOM/码表 UI + 样例大底数据 + 走查
```

批次 1–2 即可演示「不再按总双采大底」；批次 3 才达到中小厂「发料不串码」。

---

## 7. 验收（对照总纲 + 现场）

- [x] 同款 37 要 100、42 要 80，大底需求两行且数量可验算  
- [x] 面料仍一行 = 总双逻辑，与改前一致  
- [x] 缺料/PO 能看出码；确认出货无关（B0a 不动）  
- [x] 池：42 有货不能拿去齐 37 的大底需求  
- [x] 缺码表系数时刷新失败，并提示缺哪些码  
- [x] 样例：一面料（按双）+ 一大底（按码）走通采购建议  

**走查签字：** 2026-08-09 · 证据 `tests/test_b1c_size_bom.py`（5 项）+ 缺料/采购「尺码」列；附带 B0a `test_shipments_shippable` 未回归。

---

## 8. 生产任务单（点头后开）

| ID | 内容 | 状态 |
|----|------|------|
| B1c-T1 | migration：码表、BOM 标记、req.size、PO.size、stock.size 唯一键 | ✅ |
| B1c-T2 | refresh/重算按码 + 缺码拦截 + 未按码回归单测 | ✅ |
| B1c-T3 | 缺料 API/UI + 采购草稿写 size | ✅ |
| B1c-T4 | 池分配/入出池按码匹配 + 单测不串码 | ✅ |
| B1c-T5 | 码表维护页 + BOM UI | ✅ |
| B1c-T6 | seed 样例 + 走查签字 | ✅ |

---

## 9. 修订

| 日期 | 说明 |
|------|------|
| 2026-08-09 | 初稿 |
| 2026-08-09 | **定稿建议**：轻量 B（仅按码料池按码）+ PO 带码 + 缺系数禁刷新 + P1 精确码 + 仅 BOM 标记 |
| 2026-08-09 | **编码落地**：T1–T5（模型/刷新/缺料采购/池/码表+BOM UI）；单测 `tests/test_b1c_size_bom.py` |
| 2026-08-09 | 分类「建议按码」+ 默认码表「大底通用」种子（导入分类/码表按钮、seed_demo） |
| 2026-08-09 | 计划损耗：BOM/用料 `loss_rate% + loss_fixed_qty`；按码固定损耗只落首码行 |
| 2026-08-09 | 默认码表仅「大底通用」一张；建议按码挂 **大底 / 中底 / 鞋垫**（包装、内里不挂） |
| 2026-08-09 | **T6 走查通过**：§7 全勾；进入 A1a |
