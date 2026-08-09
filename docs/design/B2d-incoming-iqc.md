# B2d 设计：来料 IQC

> **状态：** ✅ 走查通过（2026-08-09）  
> **总纲：** [`product-roadmap.md`](../product-roadmap.md)  

## 走查证据

| 项 | 结果 |
|----|------|
| 到货 → 待检 | `iqc_pending_count=1`，池不变 |
| 不合格 | 池 qty 不变 |
| 合格 | 池 +3；单测 4 passed |
| UI | `/admin/material-iqc` |

## 主路径

采购到货默认待检；合格/让步入池；不合格不入池。`iqc_before_pool` 默认开；`skip_iqc` 可直入池。
