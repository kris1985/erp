import { nextTick, onMounted, onUnmounted, ref, type Ref } from 'vue'

const STORAGE_PREFIX = 'erp_admin_col_widths:'
const MIN_COL_WIDTH = 32
const MIN_SIZE_COL_WIDTH = 22

/** 不参与持久化、不可拖的列 key */
const RESERVED_COL_KEYS = new Set(['actions', 'selection', 'expand', 'col', '_fill'])

function minWidthForKey(key: string): number {
  if (key.startsWith('size_')) return MIN_SIZE_COL_WIDTH
  // 状态标签（待确认 / 生产中 等三字）
  if (key === 'status_w' || key === 'status') return 72
  return MIN_COL_WIDTH
}

function sanitizeWidths(
  raw: Record<string, number>,
  flexKey?: string,
  persistFlex = false,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(raw)) {
    if (RESERVED_COL_KEYS.has(k)) continue
    if (flexKey && k === flexKey && !persistFlex) continue
    const min = minWidthForKey(k)
    if (typeof v === 'number' && Number.isFinite(v) && v >= min) {
      out[k] = Math.floor(v)
    }
  }
  return out
}

function loadWidths(tableKey: string, flexKey?: string, persistFlex = false): Record<string, number> {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + tableKey)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    return sanitizeWidths(parsed as Record<string, number>, flexKey, persistFlex)
  } catch {
    return {}
  }
}

function saveWidths(
  tableKey: string,
  widths: Record<string, number>,
  flexKey?: string,
  persistFlex = false,
) {
  try {
    localStorage.setItem(
      STORAGE_PREFIX + tableKey,
      JSON.stringify(sanitizeWidths(widths, flexKey, persistFlex)),
    )
  } catch {
    // ignore quota / private mode
  }
}

/** Resolve stable column key from Element Plus table column context. */
export function columnKeyFromCtx(column: any): string | null {
  if (!column) return null
  const key = column.property ?? column.prop ?? column.columnKey ?? column.rawColumnKey
  if (key == null || String(key) === '') return null
  return String(key)
}

function columnFixedWidth(column: any): number | null {
  const w = column?.width
  if (typeof w === 'number' && Number.isFinite(w) && w > 0) return Math.floor(w)
  return null
}

function columnRealWidth(column: any): number | null {
  const w = column?.realWidth ?? column?.width ?? column?.minWidth
  if (typeof w === 'number' && Number.isFinite(w) && w > 0) return Math.floor(w)
  return null
}

type TableLayoutRef = Ref<{ doLayout?: () => void; store?: any; $el?: HTMLElement } | null | undefined>

export type TableColWidthsOptions = {
  /**
   * 弹性列 key（只绑 min-width，不持久化宽度，始终吃掉剩余空间）。
   * 开启 fitToContainer 时改为参与等比例缩放，可持久化。
   */
  flexKey?: string
  /** 弹性列默认 min-width / 等比缩放基准 */
  flexDefaultMin?: number
  /**
   * 列宽适配容器，使列宽之和等于容器宽度。
   * 容器更宽时，多出的宽度各列均分；更窄时等比例缩小。表格保持 100% 宽且不出现横向滚动条。
   * 侧栏折叠/展开：动画期间表格不重排，只用 transform 跟着变宽；结束后再按真实宽度铺一次列。
   * 拖列不会触发本适配（只与右邻互换）。
   */
  fitToContainer?: boolean
}

/**
 * Persist el-table column widths in localStorage (per tableKey).
 *
 * Required for all new admin tables — see `.cursor/rules/admin-table-col-widths.mdc`.
 *
 * Drag behavior: width delta is taken from / given to the immediate right
 * resizable column (Excel-like). Falls back to flexKey when there is no neighbor.
 */
export function useTableColWidths(
  tableKey: string,
  tableRef?: TableLayoutRef,
  options?: TableColWidthsOptions,
) {
  const flexKey = options?.flexKey
  const flexDefaultMin = options?.flexDefaultMin ?? 100
  const fitToContainer = options?.fitToContainer !== false
  /** fitToContainer 时弹性列也参与持久化与等比缩放 */
  const persistFlex = fitToContainer
  const widths = ref<Record<string, number>>(loadWidths(tableKey, flexKey, persistFlex))
  /** 未拖拽过的列的原始基准。不能用展示宽回读，否则均分会被再加一遍。 */
  const intrinsicBases = new Map<string, number>()
  /** 等比缩放后的展示宽度（不写回 localStorage） */
  const displayWidths = ref<Record<string, number>>({})

  let resizeObserver: ResizeObserver | null = null
  let lastBodyWidth = 0
  let relayoutTimer: ReturnType<typeof setTimeout> | null = null
  /** 侧栏动画中：列宽已按目标宽度铺好，忽略裁切窗口带来的尺寸回调 */
  let asideAnimating = false
  let fitting = false
  /** 侧栏动画结束后的短窗口：丢掉紧跟着的二次排版，避免右侧再闪一次 */
  let quietUntil = 0

  function colWidth(key: string, defaultWidth?: number | string): number | string | undefined {
    const shown = displayWidths.value[key]
    if (shown != null && shown > 0) return shown
    if (flexKey && key === flexKey && !fitToContainer) return undefined
    const saved = widths.value[key]
    if (saved != null && saved > 0) return saved
    return defaultWidth
  }

  /** 弹性列 min-width；fitToContainer 时返回展示宽以便用 :width 绑定 */
  function flexColMinWidth(key: string, defaultMin = flexDefaultMin): number {
    if (fitToContainer) {
      const shown = displayWidths.value[key]
      if (shown != null && shown > 0) return shown
      const saved = widths.value[key]
      if (saved != null && saved > 0) return saved
    }
    return defaultMin
  }

  function resetFlexColumn(column: any | null | undefined) {
    if (!column) return
    column.width = undefined
    column.realWidth = undefined
    column.minWidth = flexDefaultMin
  }

  function applyColumnPixels(column: any, key: string, w: number) {
    if (!column) return
    if (flexKey && key === flexKey && !fitToContainer) {
      resetFlexColumn(column)
      return
    }
    column.width = w
    column.realWidth = w
  }

  function tableEl(): HTMLElement | null {
    const t = tableRef?.value as any
    if (!t) return null
    return (t.$el as HTMLElement) || null
  }

  /**
   * 可视宽度用表体滚动视口，避开右侧竖向滚动条。
   * 列宽铺到外框时，最后一列会画进滚动条下面，看起来像被挡住。
   */
  function layoutWidth(el: HTMLElement): number {
    const wrap = el.querySelector('.el-table__body-wrapper .el-scrollbar__wrap') as HTMLElement | null
    const wrapWidth = wrap?.clientWidth ?? 0
    if (wrapWidth > 0) return wrapWidth
    return el.clientWidth
  }

  function stripFlexFromWidths(src: Record<string, number>): Record<string, number> {
    if (persistFlex || !flexKey || src[flexKey] == null) return src
    const next = { ...src }
    delete next[flexKey]
    return next
  }

  function baseWidthForColumn(key: string, col: any, isFlex: boolean): number {
    const saved = widths.value[key]
    if (saved != null && saved > 0) return Math.floor(saved)
    const known = intrinsicBases.get(key)
    if (known != null && known > 0) return known
    const measured = Math.floor(
      isFlex
        ? (columnRealWidth(col) ?? columnFixedWidth(col) ?? flexDefaultMin)
        : (columnFixedWidth(col) ?? columnRealWidth(col) ?? minWidthForKey(key)),
    )
    if (displayWidths.value[key] == null) intrinsicBases.set(key, measured)
    return intrinsicBases.get(key) ?? measured
  }

  /**
   * 按基准宽度适配容器，展示宽之和等于容器宽度（不出现横向滚动条）：
   * - 容器更宽：多出来的宽度各列均分（操作/勾选列不参与）
   * - 容器更窄：等比例缩小铺满；能守住最小列宽时优先守住
   * 展示宽度写入 displayWidths / 列 store，不覆盖用户基准 widths。
   */
  function fitColumnsToContainer(targetWidth?: number): boolean {
    if (!fitToContainer) return false
    const table = tableRef?.value as any
    const el = tableEl()
    const cols: any[] = table?.store?.states?.columns?.value
    if (!el || !Array.isArray(cols) || !cols.length) return false

    const bodyWidth = targetWidth && targetWidth > 0 ? targetWidth : layoutWidth(el)
    if (!bodyWidth) return false
    lastBodyWidth = bodyWidth

    type Item = {
      key: string
      col: any
      base: number
      display: number
      reserved: boolean
      isFlex: boolean
    }
    const items: Item[] = []
    let reservedTotal = 0
    let baseTotal = 0

    for (const col of cols) {
      const key = columnKeyFromCtx(col)
      const isFlex = !!(flexKey && key === flexKey)
      const reserved =
        !key ||
        RESERVED_COL_KEYS.has(key) ||
        col.type === 'selection' ||
        col.type === 'expand'
      if (reserved) {
        const current =
          columnFixedWidth(col) ??
          columnRealWidth(col) ??
          (key === 'selection' || col.type === 'selection' ? 48 : 80)
        const w = Math.floor(current)
        items.push({
          key: key || `anon-${items.length}`,
          col,
          base: w,
          display: w,
          reserved: true,
          isFlex: false,
        })
        reservedTotal += w
        continue
      }
      const base = baseWidthForColumn(key!, col, isFlex)
      items.push({ key: key!, col, base, display: base, reserved: false, isFlex })
      baseTotal += base
    }

    const available = Math.max(0, bodyWidth - reservedTotal)
    if (baseTotal <= 0 || available <= 0) return false

    const scalable = items.filter((i) => !i.reserved)

    if (available >= baseTotal) {
      // 侧栏折叠后多出的宽度，各数据列均分，不按原列宽比例放大
      const extra = available - baseTotal
      const share = Math.floor(extra / scalable.length)
      let rem = extra - share * scalable.length
      for (const item of scalable) {
        const add = share + (rem > 0 ? 1 : 0)
        if (rem > 0) rem -= 1
        item.display = item.base + add
      }
    } else {
      const scale = available / baseTotal
      let used = 0

      // 缩小时等比例取整；最小列宽把总和撑过容器时再扣回，避免横向滚动条。
      const ranked = scalable.map((item) => {
        const exact = item.base * scale
        const floorLimit = minWidthForKey(item.key)
        const floored = Math.max(floorLimit, Math.floor(exact))
        return { item, exact, floored, frac: exact - Math.floor(exact), floorLimit }
      })
      for (const row of ranked) {
        row.item.display = row.floored
        used += row.floored
      }

      if (used > available) {
        let over = used - available
        const bySlack = ranked
          .slice()
          .sort((a, b) => b.floored - b.floorLimit - (a.floored - a.floorLimit))
        for (const row of bySlack) {
          if (over <= 0) break
          const slack = row.floored - row.floorLimit
          if (slack <= 0) continue
          const cut = Math.min(slack, over)
          row.floored -= cut
          row.item.display = row.floored
          over -= cut
        }
        if (over > 0) {
          const byWidth = ranked.slice().sort((a, b) => b.floored - a.floored)
          while (over > 0) {
            let progressed = false
            for (const row of byWidth) {
              if (over <= 0) break
              if (row.floored <= 1) continue
              row.floored -= 1
              row.item.display = row.floored
              over -= 1
              progressed = true
            }
            if (!progressed) break
          }
        }
        used = ranked.reduce((sum, row) => sum + row.item.display, 0)
      }

      let leftover = available - used
      if (leftover > 0) {
        ranked
          .slice()
          .sort((a, b) => b.frac - a.frac)
          .forEach((row) => {
            if (leftover <= 0) return
            row.item.display += 1
            leftover -= 1
          })
      }
    }

    const nextDisplay: Record<string, number> = {}
    for (const item of items) {
      if (item.reserved) continue
      nextDisplay[item.key] = item.display
      applyColumnPixels(item.col, item.key, item.display)
    }
    displayWidths.value = nextDisplay
    return true
  }

  function relayoutTable() {
    nextTick(() => {
      fitColumnsToContainer()
      tableRef?.value?.doLayout?.()
      requestAnimationFrame(() => {
        fitColumnsToContainer()
        tableRef?.value?.doLayout?.()
        setTimeout(() => {
          fitColumnsToContainer()
          tableRef?.value?.doLayout?.()
        }, 0)
      })
    })
  }

  /**
   * 在本次绘制前把列宽铺进当前容器。
   * 不能拖到下一帧：侧栏先变窄时，旧列宽会先被裁掉一截，右边就闪一下。
   */
  function syncFit() {
    if (fitting) return
    const el = tableEl()
    if (!el) return
    const w = layoutWidth(el)
    if (!w || Math.abs(w - lastBodyWidth) < 1) return
    fitting = true
    try {
      fitColumnsToContainer()
      tableRef?.value?.doLayout?.()
    } finally {
      fitting = false
    }
  }

  function scheduleRelayout(delayMs = 120) {
    if (asideAnimating) return
    if (relayoutTimer != null) clearTimeout(relayoutTimer)
    relayoutTimer = setTimeout(() => {
      relayoutTimer = null
      if (asideAnimating) return
      relayoutTable()
    }, delayMs)
  }

  function followsAsideWidth(el: HTMLElement): boolean {
    if (!el.closest('.admin-content')) return false
    const host = el.parentElement
    const shell = host?.parentElement
    if (!host || !shell) return false
    return Math.abs(host.offsetWidth - shell.clientWidth) <= 24
  }

  function onWindowResize() {
    if (!fitToContainer) return
    scheduleRelayout(150)
  }

  /** 页面已钉在目标宽度上，这里只铺一次列，动画过程中不再重排 */
  function onAsidePrepare() {
    if (!fitToContainer) return
    const el = tableEl()
    if (!el || !followsAsideWidth(el)) return
    asideAnimating = true
    if (relayoutTimer != null) {
      clearTimeout(relayoutTimer)
      relayoutTimer = null
    }
    fitColumnsToContainer()
    tableRef?.value?.doLayout?.()
  }

  function onAsideFinish() {
    if (!asideAnimating) return
    asideAnimating = false
    quietUntil = performance.now() + 120
    const el = tableEl()
    if (!el) return
    const w = layoutWidth(el)
    if (w && Math.abs(w - lastBodyWidth) >= 2) syncFit()
  }

  function observeTable() {
    if (!fitToContainer || typeof ResizeObserver === 'undefined') return
    resizeObserver?.disconnect()
    const el = tableEl()
    if (!el) return
    resizeObserver = new ResizeObserver(() => {
      if (asideAnimating) return
      if (performance.now() < quietUntil) return
      const w = Math.floor(layoutWidth(el) || 0)
      if (!w || Math.abs(w - lastBodyWidth) < 1) return
      scheduleRelayout(120)
    })
    resizeObserver.observe(el)
  }

  onMounted(() => {
    if (flexKey && !persistFlex && widths.value[flexKey] != null) {
      widths.value = stripFlexFromWidths(widths.value)
      saveWidths(tableKey, widths.value, flexKey, persistFlex)
    }
    relayoutTable()
    if (fitToContainer) {
      window.addEventListener('resize', onWindowResize)
      window.addEventListener('admin-aside-prepare', onAsidePrepare)
      window.addEventListener('admin-aside-finish', onAsideFinish)
      nextTick(() => {
        observeTable()
      })
      // 等表格挂载完成后再观察一次
      setTimeout(() => {
        observeTable()
      }, 0)
    }
  })

  onUnmounted(() => {
    if (fitToContainer) window.removeEventListener('resize', onWindowResize)
    window.removeEventListener('admin-aside-prepare', onAsidePrepare)
    window.removeEventListener('admin-aside-finish', onAsideFinish)
    resizeObserver?.disconnect()
    resizeObserver = null
    if (relayoutTimer != null) clearTimeout(relayoutTimer)
  })

  /** 紧邻右侧可调列（跳过操作/勾选等保留列） */
  function findRightNeighbor(draggedKey: string): { key: string; column: any | null } | null {
    const cols = tableRef?.value?.store?.states?.columns?.value
    if (Array.isArray(cols) && cols.length) {
      const idx = cols.findIndex((c: any) => columnKeyFromCtx(c) === draggedKey)
      if (idx >= 0) {
        for (let i = idx + 1; i < cols.length; i++) {
          const column = cols[i]
          const key = columnKeyFromCtx(column)
          if (key && !RESERVED_COL_KEYS.has(key)) return { key, column }
        }
      }
    }
    if (flexKey && flexKey !== draggedKey) return { key: flexKey, column: null }
    return null
  }

  function onHeaderDragend(newWidth: number, oldWidth: number, column: any) {
    const key = columnKeyFromCtx(column)
    if (!key || RESERVED_COL_KEYS.has(key) || !Number.isFinite(newWidth) || newWidth <= 0) return

    // 非 fit 模式拖弹性列：保持弹性，不写入固定宽
    if (flexKey && key === flexKey && !fitToContainer) {
      resetFlexColumn(column)
      const next = stripFlexFromWidths({ ...widths.value })
      widths.value = next
      saveWidths(tableKey, next, flexKey, persistFlex)
      nextTick(() => tableRef?.value?.doLayout?.())
      return
    }

    const minW = minWidthForKey(key)
    const prev =
      displayWidths.value[key] ??
      widths.value[key] ??
      (Number.isFinite(oldWidth) && oldWidth > 0 ? Math.max(minW, Math.floor(oldWidth)) : null) ??
      columnFixedWidth(column) ??
      columnRealWidth(column) ??
      Math.max(minW, Math.floor(newWidth))

    let w = Math.max(minW, Math.floor(newWidth))
    const delta = w - prev
    if (delta === 0) return

    const neighbor = findRightNeighbor(key)
    if (fitToContainer && !neighbor) {
      applyColumnPixels(column, key, prev)
      nextTick(() => tableRef?.value?.doLayout?.())
      return
    }

    const baseOf = (colKey: string, displayFallback: number) => {
      const saved = widths.value[colKey]
      if (saved != null && saved > 0) return saved
      const known = intrinsicBases.get(colKey)
      if (known != null && known > 0) return known
      return displayFallback
    }

    let applied = delta
    if (neighbor) {
      const neighborPrev =
        displayWidths.value[neighbor.key] ??
        widths.value[neighbor.key] ??
        columnFixedWidth(neighbor.column) ??
        columnRealWidth(neighbor.column) ??
        minWidthForKey(neighbor.key)
      const neighborMin = minWidthForKey(neighbor.key)
      if (delta > 0) {
        applied = Math.min(delta, Math.max(0, neighborPrev - neighborMin))
      } else {
        applied = -Math.min(-delta, Math.max(0, prev - minW))
      }
      const next: Record<string, number> = stripFlexFromWidths({
        ...widths.value,
        [key]: Math.max(1, baseOf(key, prev) + applied),
        [neighbor.key]: Math.max(1, baseOf(neighbor.key, neighborPrev) - applied),
      })
      widths.value = next
      saveWidths(tableKey, next, flexKey, persistFlex)
      if (fitToContainer) {
        lastBodyWidth = 0
        fitColumnsToContainer()
      } else {
        applyColumnPixels(column, key, prev + applied)
        applyColumnPixels(neighbor.column, neighbor.key, neighborPrev - applied)
        displayWidths.value = { ...displayWidths.value, [key]: prev + applied, [neighbor.key]: neighborPrev - applied }
      }
      nextTick(() => tableRef?.value?.doLayout?.())
      return
    }

    const next: Record<string, number> = stripFlexFromWidths({ ...widths.value, [key]: w })
    applyColumnPixels(column, key, next[key])
    widths.value = next
    saveWidths(tableKey, next, flexKey, persistFlex)
    displayWidths.value = { ...displayWidths.value, ...next }
    nextTick(() => tableRef?.value?.doLayout?.())
  }

  return { colWidth, flexColMinWidth, onHeaderDragend, relayoutTable, widths }
}
