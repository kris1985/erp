# 架构升级 · 迭代需求索引

> **状态：** ✅ AU-I0～I3 切片已落地（I3 双轨关闸/合批弱化仍开放） · 2026-08-12  
> **总纲：** [`../architecture-upgrade-merge-order-carriers.md`](../architecture-upgrade-merge-order-carriers.md)  
> **验收清单：** [`ACCEPTANCE.md`](./ACCEPTANCE.md)  
> **原则：** 按优先级串行；每迭代可演示、可回滚话术；**不一次改账本主键**。合单（I1）之前先立载体与工艺（I0）。

---

## 优先级总览

| 优先级 | 迭代 | 一句话 | 依赖 | 文档 |
|--------|------|--------|------|------|
| **P0** | [AU-I0](./AU-I0-route-carriers-dispatch.md) | 部件/整鞋工艺 + 筐捆双码 + 派工/组拆分/质检骨架 | 无（可叠现网生产单） | 必做 · 先开 |
| **P1** | [AU-I1](./AU-I1-merge-execution.md) | 有分配合单 + 齐套领料主体 + 进度/成本时机 | **I0** | ✅ · [实现设计](./AU-I1-impl.md) |
| **P2** | [AU-I2](./AU-I2-fg-direct-ship-packing.md) | 成品入库/直发 + 预装箱时序 + 成本归集 | **I1**（至少分配+载体） | ✅ · [实现设计](./AU-I2-impl.md) |
| **P3** | [AU-I3](./AU-I3-schedule-change-rollback.md) | 排产池切色码主输入 + 插单/变更/异常回滚 + 双轨收口 | **I1**；插单叠现网排产 | ✅ · [实现设计](./AU-I3-impl.md)（双轨关闸待产品） |
| **P3+** | [AU-I3plus](./AU-I3plus-production-line.md) | 可选产线维度与负荷 | I0 班组；不阻塞 I1–I3 | 可选 |

**统一验收勾选：** [`ACCEPTANCE.md`](./ACCEPTANCE.md)  
**AU-I0 实现设计：** [`AU-I0-impl.md`](./AU-I0-impl.md)  
**AU-I1 实现设计：** [`AU-I1-impl.md`](./AU-I1-impl.md)  
**AU-I2 实现设计：** [`AU-I2-impl.md`](./AU-I2-impl.md)  
**AU-I3 实现设计：** [`AU-I3-impl.md`](./AU-I3-impl.md)  
**执行单（方案 C · 一款一头多码明细）：** [`AU-execution-task-C.md`](./AU-execution-task-C.md)  
**出货改挂销售单（去桥接 · 出货刀）：** [`AU-ship-from-sales.md`](./AU-ship-from-sales.md)  
**齐套/锁料认执行单（去桥接 · 料刀）：** [`AU-kit-from-execution.md`](./AU-kit-from-execution.md)  
**干掉生产单（去桥接终局）：** [`AU-kill-shop-order.md`](./AU-kill-shop-order.md)  
**状态流转（销售/明细/执行 + 进度展示）：** [`lifecycle-status-flow.md`](./lifecycle-status-flow.md)  
**排产默认体验（方案甘特 · 确认才下发）：** [`../schedule-ux.md`](../schedule-ux.md)

```text
AU-I0 ──► AU-I1 ──► AU-I2
              │
              └──► AU-I3
AU-I3plus 可与 I1+ 并行（默认关）
```

---

## 建议排期节奏

| 波次 | 做啥 | 演示口径 |
|------|------|----------|
| 第 1 波 | **AU-I0** | 一款两段工艺；开裁出筐+捆；针车扫筐分活；合帮后只扫筐；组报工可拆人 |
| 第 2 波 | **AU-I1** | 两销售同色码合一张执行单；筐上印比例；产量回写勾平；领料认执行单 |
| 第 3 波 | **AU-I2** | 筐完工入库或直发；预装箱后打唛；直发流水净库存不变 |
| 第 4 波 | **AU-I3** | 可产池排色码；急单重算未开工；停产释放池与料；旧 1∶1 路径可关 |
| 按需 | **AU-I3plus** | 多成型线挂线看负荷；关开关与现在一致 |

---

## 闭环断环 ↔ 迭代

| 断环 | 补丁 | 迭代 |
|------|------|------|
| G1 齐套/领料主体 | P1-6 | **AU-I1** |
| G2 装箱 vs 出货时序 | P2-4 | **AU-I2** |
| G3/G4 变更与返修回滚 | P3-6 | **AU-I3**（质检骨架在 I0） |
| G5 人工成本归集 | P2-5 | **AU-I2** |

详见总纲 [§11](./architecture-upgrade-merge-order-carriers.md)。

---

## 全局非目标（各迭代共用）

- 整库按外部草案重建  
- 无分配硬合单  
- 排产静默落库  
- 产线当账本主体  
- 削弱多租户 / 应收应付 / 计件月结  

---

**维护：** 某迭代开干时把该文档状态改为 🚧，验收通过改 ✅，并回链 PR。  
**总纲同步：** 总纲 §5 Epic 编号与本文 AU-I* 一一对应（P0≈I0 …）。
