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
    const top = (tableEl || host).getBoundingClientRect().top
    const parent = host.parentElement
    let reserved = bottomGap
    if (parent) {
      for (const sel of reserveSelectors) {
        const el = parent.querySelector(sel) as HTMLElement | null
        if (el && !host.contains(el)) reserved += el.offsetHeight || 0
      }
    }
    tableMaxHeight.value = Math.max(minHeight, Math.floor(window.innerHeight - top - reserved))
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
