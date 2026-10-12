import { nextTick, onMounted, onUnmounted, ref, type Ref } from 'vue'

export type UseTableMaxHeightOptions = {
  /** 保底高度，默认 280 */
  minHeight?: number
  /** 底部预留（分页等之外），默认 8 */
  bottomGap?: number
  /**
   * 相对 host 父节点查找的底部预留元素（高度计入扣减）。
   * 默认 `.admin-pagination`、`.view-hint`
   */
  reserveSelectors?: string[]
}

function firstVisibleTable(host: HTMLElement): HTMLElement | null {
  const tables = host.querySelectorAll('.el-table')
  for (const node of tables) {
    const el = node as HTMLElement
    if (el.getClientRects().length > 0) return el
  }
  return (tables[0] as HTMLElement | undefined) ?? null
}

/**
 * 列表主表按视口剩余高度设置 el-table max-height（参考订单管理页）。
 *
 * 用法：用 tableHostRef 包住主表；分页等放在 host 的兄弟节点（同属 admin-card）。
 * host 会自动加上 `admin-table-host`，配合 admin.css 把分页顶到底部。
 */
export function useTableMaxHeight(options: UseTableMaxHeightOptions = {}) {
  const minHeight = options.minHeight ?? 280
  const bottomGap = options.bottomGap ?? 8
  const reserveSelectors = options.reserveSelectors ?? ['.admin-pagination', '.view-hint']

  const tableHostRef = ref<HTMLElement | null>(null)
  const tableMaxHeight = ref(480)

  function measureTableHeight() {
    const host = tableHostRef.value
    if (!host) return
    host.classList.add('admin-table-host')
    // host 可能包住 tabs/toolbar；优先用当前可见表格顶边，避免 max-height 过大撑出视口
    const tableEl = firstVisibleTable(host)
    const anchorRect = (tableEl || host).getBoundingClientRect()
    const top = anchorRect.top
    const parent = host.parentElement
    // 用分页实际顶边，而不是「窗口高度 − 分页高度」。
    // 内容区还有底部内边距时，后一种算法会把表格多算一截，压住页码顶部。
    let limitBottom = window.innerHeight - bottomGap
    if (parent) {
      const parentRect = parent.getBoundingClientRect()
      const padBottom = Number.parseFloat(getComputedStyle(parent).paddingBottom) || 0
      const parentLimit = parentRect.bottom - padBottom
      // 父节点比表格底边更低，说明下面还有分页，或卡片已被撑到视口。
      // 父节点只是包住当前表格时，底边会贴着表格；这时若拿它当上限，高度会被锁在初次测量值。
      const hugsTable = parentLimit - anchorRect.bottom < 48
      if (!hugsTable) {
        limitBottom = Math.min(limitBottom, parentLimit)
      }
      for (const sel of reserveSelectors) {
        const el = parent.querySelector(sel) as HTMLElement | null
        if (!el || host.contains(el)) continue
        const rect = el.getBoundingClientRect()
        if (rect.height > 0) limitBottom = Math.min(limitBottom, rect.top)
      }
    }
    tableMaxHeight.value = Math.max(minHeight, Math.floor(limitBottom - top))
  }

  function scheduleMeasure() {
    void nextTick(measureTableHeight)
  }

  onMounted(() => {
    window.addEventListener('resize', measureTableHeight)
    scheduleMeasure()
  })

  onUnmounted(() => {
    window.removeEventListener('resize', measureTableHeight)
  })

  return {
    tableHostRef: tableHostRef as Ref<HTMLElement | null>,
    tableMaxHeight,
    measureTableHeight,
    scheduleMeasure,
  }
}
