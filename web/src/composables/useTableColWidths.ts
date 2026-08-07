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
   * 列宽铺满容器：按基准宽度等比例缩放（变宽/变窄都缩放），
   * 并用 ResizeObserver 响应侧栏折叠等容器变化。
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
  const fitToContainer = options?.fitToContainer === true
  /** fitToContainer 时弹性列也参与持久化与等比缩放 */
  const persistFlex = fitToContainer
  const widths = ref<Record<string, number>>(loadWidths(tableKey, flexKey, persistFlex))
  /** 等比缩放后的展示宽度（不写回 localStorage） */
  const displayWidths = ref<Record<string, number>>({})

  let resizeObserver: ResizeObserver | null = null
  let lastBodyWidth = 0
  let relayoutTimer: ReturnType<typeof setTimeout> | null = null

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

  function stripFlexFromWidths(src: Record<string, number>): Record<string, number> {
    if (persistFlex || !flexKey || src[flexKey] == null) return src
    const next = { ...src }
    delete next[flexKey]
    return next
  }

  function baseWidthForColumn(key: string, col: any, isFlex: boolean): number {
    const saved = widths.value[key]
    if (saved != null && saved > 0) return Math.floor(saved)
    if (isFlex) {
      return (
        columnRealWidth(col) ??
        columnFixedWidth(col) ??
        flexDefaultMin
      )
    }
    return (
      columnFixedWidth(col) ??
      columnRealWidth(col) ??
      minWidthForKey(key)
    )
  }

  /**
   * 按基准宽度等比例缩放，使可调列总宽正好铺满容器。
   * 展示宽度写入 displayWidths / 列 store，不覆盖用户基准 widths。
   */
  function fitColumnsToContainer(): boolean {
    if (!fitToContainer) return false
    const table = tableRef?.value as any
    const el = tableEl()
    const cols: any[] = table?.store?.states?.columns?.value
    if (!el || !Array.isArray(cols) || !cols.length) return false

    const bodyWidth = el.clientWidth
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

    const scale = available / baseTotal
    const scalable = items.filter((i) => !i.reserved)
    let used = 0

    // 先按比例取整，再按小数部分分配余量，避免 1px 缝隙
    const ranked = scalable.map((item) => {
      const exact = item.base * scale
      const floored = Math.max(minWidthForKey(item.key), Math.floor(exact))
      return { item, exact, floored, frac: exact - Math.floor(exact) }
    })
    for (const row of ranked) {
      row.item.display = row.floored
      used += row.floored
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
    } else if (leftover < 0) {
      // 触碰 min 后可能略超，从最宽列回收
      const pool = ranked
        .slice()
        .sort((a, b) => b.item.display - a.item.display)
      for (const row of pool) {
        if (leftover >= 0) break
        const min = minWidthForKey(row.item.key)
        const room = row.item.display - min
        if (room <= 0) continue
        const take = Math.min(room, -leftover)
        row.item.display -= take
        leftover += take
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

  function scheduleRelayout() {
    if (relayoutTimer != null) clearTimeout(relayoutTimer)
    // 侧栏折叠有 0.18s transition，稍作防抖再量宽
    relayoutTimer = setTimeout(() => {
      relayoutTimer = null
      relayoutTable()
    }, 50)
  }

  function onWindowResize() {
    if (!fitToContainer) return
    scheduleRelayout()
  }

  function observeTable() {
    if (!fitToContainer || typeof ResizeObserver === 'undefined') return
    resizeObserver?.disconnect()
    const el = tableEl()
    if (!el) return
    resizeObserver = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0]?.contentRect?.width || el.clientWidth || 0)
      if (!w || Math.abs(w - lastBodyWidth) < 1) return
      scheduleRelayout()
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
      nextTick(() => observeTable())
      // 等表格挂载完成后再观察一次
      setTimeout(() => observeTable(), 0)
    }
  })

  onUnmounted(() => {
    if (fitToContainer) window.removeEventListener('resize', onWindowResize)
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
      relayoutTable()
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

    const next: Record<string, number> = stripFlexFromWidths({ ...widths.value, [key]: w })
    const neighbor = delta !== 0 ? findRightNeighbor(key) : null

    if (neighbor) {
      const neighborIsFlex = !!(flexKey && neighbor.key === flexKey)
      if (neighborIsFlex && !fitToContainer) {
        if (delta > 0) {
          const flexVisual = columnRealWidth(neighbor.column) ?? flexDefaultMin
          const room = Math.max(0, flexVisual - flexDefaultMin)
          const actual = Math.min(delta, room)
          w = prev + actual
          next[key] = w
        }
        applyColumnPixels(column, key, next[key])
        resetFlexColumn(neighbor.column)
      } else {
        const neighborPrev =
          displayWidths.value[neighbor.key] ??
          widths.value[neighbor.key] ??
          columnFixedWidth(neighbor.column) ??
          columnRealWidth(neighbor.column) ??
          minWidthForKey(neighbor.key)
        const neighborMin = minWidthForKey(neighbor.key)
        if (delta > 0) {
          const actual = Math.min(delta, Math.max(0, neighborPrev - neighborMin))
          w = prev + actual
          next[key] = w
          next[neighbor.key] = neighborPrev - actual
        } else {
          next[neighbor.key] = neighborPrev - delta
        }
        applyColumnPixels(column, key, next[key])
        applyColumnPixels(neighbor.column, neighbor.key, next[neighbor.key])
      }
    } else {
      applyColumnPixels(column, key, next[key])
    }

    // 拖拽后的展示宽作为新的基准比例，再等比铺满容器
    widths.value = next
    saveWidths(tableKey, next, flexKey, persistFlex)
    displayWidths.value = { ...displayWidths.value, ...next }
    relayoutTable()
  }

  return { colWidth, flexColMinWidth, onHeaderDragend, relayoutTable, widths }
}
