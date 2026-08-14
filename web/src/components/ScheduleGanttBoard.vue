<template>
  <div v-loading="loading" class="gantt" :class="{ fill }">
    <div v-if="!workdays.length" class="gantt-empty">没有可显示的日期</div>
    <div v-else-if="!rows.length" class="gantt-empty">
      <p>甘特还是空的。</p>
      <p class="muted">勾选待排款后出方案，条子会出现在这里。确认前不下发。</p>
      <button type="button" class="gantt-empty-cta" @click="emit('pickPending')">从待排勾选</button>
    </div>
    <div v-else class="gantt-scroll">
      <div class="gantt-grid" :style="gridStyle">
        <div class="gantt-corner">款色 / 指令</div>
        <div
          v-for="(d, i) in workdays"
          :key="d.date"
          class="gantt-day"
          :class="{
            'is-today': d.date === today,
            'is-off': !isSchedulable(d),
            'is-holiday': !!d.is_holiday && !isSchedulable(d),
            'is-blackout': !!d.is_blackout,
            'is-makeup': !!d.is_makeup && isSchedulable(d),
          }"
        >
          <span class="gantt-dow">{{ weekdayLabel(d.date) }}</span>
          <strong>{{ dayHeading(d.date, i) }}</strong>
          <span v-if="dayMark(d)" class="gantt-day-mark">{{ dayMark(d) }}</span>
        </div>

        <template v-if="load.length">
          <div class="gantt-load-label">负荷</div>
          <div
            v-for="d in workdays"
            :key="`load-${d.date}`"
            class="gantt-load-cell"
            :class="[loadTone(d.date), { 'is-today': d.date === today, 'is-off': !isSchedulable(d) }]"
            :title="loadTitle(d.date)"
          >
            <span class="gantt-load-fill" :style="{ height: loadHeight(d.date) }" />
          </div>
        </template>

        <template v-for="row in rows" :key="row.key">
          <div
            class="gantt-label"
            :class="[row.kind, { 'is-open': isExpanded(row) }]"
            :title="labelHover(row)"
          >
            <button type="button" class="gantt-label-main" @click="onLabelClick(row)">
              <span class="gantt-label-title">{{ row.title }}</span>
              <span class="gantt-label-sub">{{ row.subtitle }}</span>
              <span class="gantt-pills">
                <span v-for="p in hardPills(row)" :key="p.key" class="gantt-pill" :class="p.cls">{{
                  p.text
                }}</span>
              </span>
            </button>
            <button
              v-if="canReschedule(row)"
              type="button"
              class="gantt-insert gantt-reschedule"
              @click.stop="emit('reschedule', row.header_id)"
            >
              改排
            </button>
            <button
              v-if="row.kind === 'issued' && row.status === 'confirmed' && row.header_id"
              type="button"
              class="gantt-insert"
              @click.stop="emit('insertRush', row.header_id)"
            >
              插急
            </button>
            <ul v-if="isExpanded(row) && (row.sources || []).length" class="gantt-sources">
              <li v-for="s in row.sources" :key="s.sales_order_id" class="gantt-source">
                <span class="gantt-source-txt">
                  {{ s.customer_name || '客户' }}
                  <em>{{ s.sales_order_no }}</em>
                  {{ s.qty || 0 }}双
                </span>
                <button
                  v-if="row.kind === 'draft' && row.jobKey"
                  type="button"
                  class="gantt-drop"
                  @click.stop="onDropSource(row, s)"
                >
                  剔除
                </button>
              </li>
            </ul>
          </div>
          <div
            class="gantt-track"
            :class="[row.kind, { dragging: drag?.key === row.key, draggable: canDrag(row) }]"
            :style="{ minHeight: `${trackHeight(row)}px` }"
            @pointerdown="onPointerDown(row, $event)"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
          >
            <span
              v-for="(d, i) in workdays"
              v-show="!isSchedulable(d)"
              :key="`off-${d.date}`"
              class="gantt-off-col"
              :class="{ blackout: d.is_blackout, holiday: d.is_holiday }"
              :style="{ left: `${i * COL}px` }"
            />
            <span
              v-if="todayIndex >= 0"
              class="gantt-today-col"
              :style="{ left: `${todayIndex * COL}px` }"
            />
            <span
              v-if="drag?.key === row.key && dragHint"
              class="gantt-snap-col"
              :style="{ left: `${dragHint.snapIndex * COL}px` }"
            />
            <el-tooltip
              v-for="bar in barsOf(row)"
              :key="bar.key"
              :content="bar.title"
              placement="top"
              :show-after="200"
              :disabled="!!drag"
            >
              <div
                class="gantt-bar"
                :class="[bar.lane, row.kind, { clickable: row.kind === 'issued', draggable: canDrag(row), done: bar.done, alert: isAlertRow(row) }]"
                :style="barStyle(row, bar)"
                @click="onLabelClick(row)"
              >
                <span class="gantt-bar-name">{{ barDisplayName(bar.name) }}</span>
                <span v-if="bar.done" class="gantt-bar-check" aria-hidden="true">✓</span>
              </div>
            </el-tooltip>
            <el-tooltip
              v-for="bar in previewBarsOf(row)"
              :key="`p-${bar.key}`"
              :content="`推迟后 ${bar.title}`"
              placement="top"
              :show-after="200"
            >
              <div
                class="gantt-bar ghost"
                :class="bar.lane"
                :style="bar.style"
              >
                <span class="gantt-bar-name">{{ barDisplayName(bar.name) }}</span>
              </div>
            </el-tooltip>
          </div>
        </template>
      </div>
    </div>
    <div class="gantt-legend">
      <span class="gantt-leg cut">裁</span>
      <span class="gantt-leg stitch-sole">针底</span>
      <span class="gantt-leg stitch-vamp">针面</span>
      <span class="gantt-leg last">成</span>
      <span class="gantt-leg pack">包</span>
      <span class="muted">淡粉列为休息/停工。加班开后周末可排。未开裁可拖条子改开裁日，或点「改排」。</span>
    </div>
    <Teleport to="body">
      <div
        v-if="dragHint"
        class="gantt-drag-hint"
        :style="{ left: `${dragHint.x + 12}px`, top: `${dragHint.y + 12}px` }"
      >
        开裁挪到 {{ dragHint.cut }}
        <template v-if="dragHint.finish"> · 预计完成 {{ dragHint.finish }}</template>
        <span v-if="dragHint.shift" class="gantt-drag-shift">{{ dragHint.shift }}</span>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const COL = 44
const LABEL = 196
const BAR_H = 20
const BAR_GAP = 2
const BAR_STRIDE = BAR_H + BAR_GAP
const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']

export type GanttDay = {
  date: string
  workday?: boolean
  is_weekend?: boolean
  is_holiday?: boolean
  is_blackout?: boolean
  is_off?: boolean
  is_makeup?: boolean
  label?: string | null
}

export type GanttWindow = {
  process_id?: number
  process_name?: string
  start_date?: string
  end_date?: string
  plan_qty?: number
  completed_qty?: number
  status?: string
}

export type GanttLoadCell = {
  date?: string
  process_name?: string
  utilization?: number | null
  over_capacity?: boolean
}

export type GanttSource = {
  sales_order_id: number
  sales_order_no?: string
  customer_name?: string
  qty?: number
  delivery_date?: string | null
}

export type GanttRow = {
  key: string
  kind: 'draft' | 'issued'
  title: string
  subtitle: string
  status?: string
  kit_hint?: string
  risk_label?: string
  is_rush?: boolean
  header_id?: number
  jobKey?: string
  overridden?: boolean
  locked?: boolean
  impact?: 'push' | 'frozen'
  previewWindows?: GanttWindow[]
  windows?: GanttWindow[]
  sources?: GanttSource[]
}

const props = defineProps<{
  workdays: GanttDay[]
  rows: GanttRow[]
  load?: GanttLoadCell[]
  warnUtilization?: number
  loading?: boolean
  fill?: boolean
}>()

const emit = defineEmits<{
  openHeader: [id: number]
  shiftJob: [payload: { jobKey: string; cutStart: string }]
  shiftIssued: [payload: { headerId: number; cutStart: string }]
  insertRush: [headerId: number]
  reschedule: [headerId: number]
  pickPending: []
  dropSource: [payload: { jobKey: string; salesOrderId: number }]
}>()

const today = new Date().toISOString().slice(0, 10)
const todayIndex = computed(() => props.workdays.findIndex((d) => d.date === today))
const load = computed(() => props.load || [])
const warnAt = computed(() => props.warnUtilization ?? 0.9)

const drag = ref<{
  key: string
  jobKey: string
  headerId: number | null
  startX: number
  colDelta: number
  pointerId: number
  clientX: number
  clientY: number
} | null>(null)

const expanded = ref<Record<string, boolean>>({})

const gridStyle = computed(() => ({
  gridTemplateColumns: `${LABEL}px repeat(${props.workdays.length}, ${COL}px)`,
}))

function isSchedulable(d: GanttDay) {
  return d.workday !== false
}

function dayMark(d: GanttDay) {
  if (d.is_blackout) return '停'
  if (!isSchedulable(d) && d.is_holiday) return '假'
  if (!isSchedulable(d)) return '休'
  if (d.is_makeup) return '班'
  return ''
}

function dayNum(iso: string) {
  return Number(iso.slice(8, 10))
}

function dayHeading(iso: string, index: number) {
  const n = dayNum(iso)
  if (index === 0 || n === 1) return `${Number(iso.slice(5, 7))}/${n}`
  return String(n)
}

function weekdayLabel(iso: string) {
  const d = new Date(`${iso}T00:00:00`)
  return WEEKDAY[d.getDay()] || ''
}

function statusLabel(st?: string) {
  if (st === 'confirmed') return '已下发'
  if (st === 'cut') return '已开裁'
  if (st === 'in_progress') return '生产中'
  return st || '已下发'
}

function kitLabel(h?: string) {
  if (h === 'short') return '缺料'
  if (h === 'empty_bom') return '无BOM'
  return ''
}

function barDisplayName(name: string) {
  if (/针车面|面线/.test(name)) return '面'
  if (/针车底|底线/.test(name)) return '底'
  return name
}

function hardPills(row: GanttRow) {
  const out: { key: string; text: string; cls: string }[] = []
  if (row.is_rush) out.push({ key: 'rush', text: '急', cls: 'rush' })
  if (row.kind === 'draft' && (row.sources?.length || 0) > 1) {
    out.push({ key: 'src', text: `${row.sources!.length}家`, cls: 'draft' })
  }
  const kit = kitLabel(row.kit_hint)
  if (kit) out.push({ key: 'kit', text: kit, cls: 'kit' })
  if (row.impact === 'push') out.push({ key: 'push', text: '将推迟', cls: 'risk' })
  if (row.impact === 'frozen') out.push({ key: 'frozen', text: '已开裁', cls: 'issued' })
  if (row.risk_label && row.risk_label !== '正常') out.push({ key: 'risk', text: row.risk_label, cls: 'risk' })
  if (row.kind === 'issued' && (row.status === 'cut' || row.status === 'in_progress')) {
    out.push({ key: 'st', text: statusLabel(row.status), cls: 'issued' })
  }
  return out.slice(0, 3)
}

function labelHover(row: GanttRow) {
  const bits = [row.title, row.subtitle]
  if (row.kind === 'draft') {
    bits.push(row.overridden ? '草稿 · 已改期' : '草稿')
    const n = row.sources?.length || 0
    if (n > 1) bits.push(`${n}家客户，点开可剔除`)
    else if (n === 1) bits.push('点开看来源')
  } else bits.push(statusLabel(row.status))
  if (row.is_rush) bits.push('急单')
  const kit = kitLabel(row.kit_hint)
  if (kit) bits.push(kit)
  if (row.impact === 'push') bits.push('将推迟')
  if (
    row.impact === 'frozen' ||
    (row.kind === 'issued' && (row.status === 'cut' || row.status === 'in_progress'))
  ) {
    bits.push('已开裁，不能再并入')
  }
  if (row.risk_label && row.risk_label !== '正常') bits.push(row.risk_label)
  return bits.filter(Boolean).join(' · ')
}

function mdLabel(iso: string) {
  return `${Number(iso.slice(5, 7))}月${Number(iso.slice(8, 10))}日`
}

function indexOfDate(iso: string) {
  const days = props.workdays
  if (!iso || !days.length) return -1
  let i0 = days.findIndex((x) => x.date >= iso)
  if (i0 < 0) i0 = iso < days[0].date ? 0 : days.length - 1
  return i0
}

function snapIndex(i0: number, delta: number) {
  const days = props.workdays
  if (!days.length || i0 < 0) return -1
  let i = Math.max(0, Math.min(days.length - 1, i0 + delta))
  const step = delta >= 0 ? 1 : -1
  while (days[i] && !isSchedulable(days[i])) {
    i += step
    if (i < 0 || i >= days.length) return -1
  }
  return i
}

const dragHint = computed(() => {
  const d = drag.value
  if (!d) return null
  const row = props.rows.find((r) => r.key === d.key)
  if (!row) return null
  const days = props.workdays
  const first = String(row.windows?.[0]?.start_date || '').slice(0, 10)
  let last = ''
  for (const w of row.windows || []) {
    const end = String(w.end_date || '').slice(0, 10)
    if (end > last) last = end
  }
  const cutIdx = snapIndex(indexOfDate(first), d.colDelta)
  if (cutIdx < 0) return null
  const finishIdx = snapIndex(indexOfDate(last || first), d.colDelta)
  const cut = days[cutIdx]?.date
  const finish = finishIdx >= 0 ? days[finishIdx]?.date : last
  if (!cut) return null
  let shift = ''
  if (first && cut !== first) {
    const n = Math.round(
      (new Date(`${cut}T00:00:00`).getTime() - new Date(`${first}T00:00:00`).getTime()) / 86400000,
    )
    shift = n > 0 ? `推迟 ${n} 天` : `提前 ${-n} 天`
  }
  return {
    cut: mdLabel(cut),
    finish: finish ? mdLabel(finish) : '',
    shift,
    snapIndex: cutIdx,
    x: d.clientX,
    y: d.clientY,
  }
})

function processLane(name?: string) {
  const n = name || ''
  if (/裁/.test(n)) return 'cut'
  if (/针车面|面线/.test(n)) return 'stitch-vamp'
  if (/针车底|底线/.test(n)) return 'stitch-sole'
  if (/针|车缝|针车/.test(n)) return 'stitch'
  if (/成|成型|组底/.test(n)) return 'last'
  if (/包|包装/.test(n)) return 'pack'
  return 'other'
}

function laneOrder(lane: string) {
  if (lane === 'stitch-sole') return 0
  if (lane === 'stitch') return 1
  if (lane === 'stitch-vamp') return 2
  return 3
}

function isAlertRow(row: GanttRow) {
  if (row.impact === 'push') return true
  const risk = row.risk_label || ''
  return risk === '预计逾期' || risk === '产能不足'
}

function peakLoad(iso: string) {
  const rows = load.value.filter((r) => String(r.date || '').slice(0, 10) === iso)
  if (!rows.length) return null
  const forming = rows.filter((r) => /成|成型/.test(r.process_name || ''))
  const pool = forming.length ? forming : rows
  let peak = pool[0]
  for (const r of pool) {
    if ((r.utilization ?? -1) > (peak.utilization ?? -1)) peak = r
  }
  return peak
}

function loadTone(iso: string) {
  const day = props.workdays.find((d) => d.date === iso)
  if (day && !isSchedulable(day)) return 'is-rest'
  const p = peakLoad(iso)
  if (!p || p.utilization == null) return ''
  if (p.over_capacity || p.utilization > 1) return 'is-over'
  if (p.utilization >= warnAt.value) return 'is-warn'
  return 'is-ok'
}

function loadHeight(iso: string) {
  const p = peakLoad(iso)
  if (!p || p.utilization == null) return '0%'
  return `${Math.min(100, Math.round(p.utilization * 100))}%`
}

function loadTitle(iso: string) {
  const p = peakLoad(iso)
  if (!p || p.utilization == null) return iso
  const pct = Math.round(p.utilization * 100)
  return `${iso} ${p.process_name || ''} ${pct}%${p.over_capacity ? ' 超产' : ''}`
}

function barsOf(row: GanttRow) {
  return windowsToBars(row.windows, row.kind === 'issued')
}

function previewBarsOf(row: GanttRow) {
  return windowsToBars(row.previewWindows, false)
}

function isProcessDone(w: GanttWindow) {
  const plan = Number(w.plan_qty || 0)
  const done = Number(w.completed_qty || 0)
  return w.status === 'completed' || (plan > 0 && done >= plan)
}

function windowTitle(w: GanttWindow, name: string, start: string, end: string, withProgress: boolean) {
  const range = `${start.slice(5)}–${end.slice(5)}`
  if (!withProgress) return `${name} ${range}`
  const plan = Number(w.plan_qty || 0)
  const done = Number(w.completed_qty || 0)
  if (plan <= 0 && done <= 0) return `${name} ${range}`
  if (isProcessDone(w)) return `${name} 已完成 ${done}/${plan}双 · ${range}`
  return `${name} ${done}/${plan}双 · ${range}`
}

function windowsToBars(windows?: GanttWindow[], withProgress = false) {
  const days = props.workdays
  const raw: {
    key: string
    name: string
    lane: string
    title: string
    done: boolean
    i0: number
    i1: number
    stack: number
    style: Record<string, string>
  }[] = []
  for (const w of windows || []) {
    const start = String(w.start_date || '').slice(0, 10)
    const end = String(w.end_date || '').slice(0, 10)
    if (!start || !end) continue
    const runs: number[][] = []
    let run: number[] = []
    days.forEach((d, i) => {
      if (d.date >= start && d.date <= end && isSchedulable(d)) {
        if (!run.length || run[run.length - 1] === i - 1) run.push(i)
        else {
          runs.push(run)
          run = [i]
        }
      }
    })
    if (run.length) runs.push(run)
    const name = w.process_name || '工序'
    const done = withProgress && isProcessDone(w)
    runs.forEach((idx, n) => {
      const i0 = idx[0]
      const i1 = idx[idx.length - 1]
      raw.push({
        key: `${w.process_id || name}-${start}-${n}`,
        name,
        lane: processLane(name),
        title: windowTitle(w, name, start, end, withProgress),
        done,
        i0,
        i1,
        stack: 0,
        style: {},
      })
    })
  }
  raw.sort((a, b) => a.i0 - b.i0 || a.i1 - b.i1 || laneOrder(a.lane) - laneOrder(b.lane))
  const laneEnds: number[] = []
  for (const bar of raw) {
    let stack = laneEnds.findIndex((end) => bar.i0 > end)
    if (stack < 0) {
      stack = laneEnds.length
      laneEnds.push(bar.i1)
    } else {
      laneEnds[stack] = bar.i1
    }
    bar.stack = stack
    bar.style = {
      left: `${bar.i0 * COL + 1}px`,
      width: `${(bar.i1 - bar.i0 + 1) * COL - 2}px`,
      top: `${8 + stack * BAR_STRIDE}px`,
    }
  }
  return raw
}

function trackHeight(row: GanttRow) {
  const n = Math.max(
    1,
    ...windowsToBars(row.windows).map((b) => b.stack + 1),
    ...windowsToBars(row.previewWindows).map((b) => b.stack + 1),
  )
  return 16 + n * BAR_STRIDE
}

function barStyle(row: GanttRow, bar: { style: Record<string, string> }) {
  const delta = drag.value?.key === row.key ? drag.value.colDelta : 0
  return {
    ...bar.style,
    transform: delta ? `translateX(${delta * COL}px)` : undefined,
  }
}

function onLabelClick(row: GanttRow) {
  if (drag.value) return
  if (row.kind === 'issued' && row.header_id) {
    emit('openHeader', row.header_id)
    return
  }
  if (row.kind === 'draft' && (row.sources?.length || 0)) {
    expanded.value = { ...expanded.value, [row.key]: !expanded.value[row.key] }
  }
}

function isExpanded(row: GanttRow) {
  return !!expanded.value[row.key]
}

function onDropSource(row: GanttRow, s: GanttSource) {
  if (row.kind !== 'draft' || !row.jobKey || !s.sales_order_id) return
  emit('dropSource', { jobKey: row.jobKey, salesOrderId: s.sales_order_id })
}

function canReschedule(row: GanttRow) {
  return row.kind === 'issued' && !!row.header_id && row.status === 'confirmed' && !row.locked
}

function canDrag(row: GanttRow) {
  if (row.kind === 'draft' && row.jobKey) return true
  return canReschedule(row)
}

function onPointerDown(row: GanttRow, e: PointerEvent) {
  if (!canDrag(row)) return
  if (e.button != null && e.button !== 0) return
  const el = e.currentTarget as HTMLElement
  el.setPointerCapture(e.pointerId)
  drag.value = {
    key: row.key,
    jobKey: row.jobKey || '',
    headerId: row.header_id || null,
    startX: e.clientX,
    colDelta: 0,
    pointerId: e.pointerId,
    clientX: e.clientX,
    clientY: e.clientY,
  }
}

function onPointerMove(e: PointerEvent) {
  if (!drag.value || e.pointerId !== drag.value.pointerId) return
  drag.value.colDelta = Math.round((e.clientX - drag.value.startX) / COL)
  drag.value.clientX = e.clientX
  drag.value.clientY = e.clientY
}

function onPointerUp(e: PointerEvent) {
  if (!drag.value || e.pointerId !== drag.value.pointerId) return
  const d = drag.value
  drag.value = null
  if (!d.colDelta) return
  const row = props.rows.find((r) => r.key === d.key)
  const first = String(row?.windows?.[0]?.start_date || '').slice(0, 10)
  const i = snapIndex(indexOfDate(first), d.colDelta)
  const cut = i >= 0 ? props.workdays[i]?.date : ''
  if (!cut || cut === first) return
  if (row.kind === 'issued' && d.headerId) {
    emit('shiftIssued', { headerId: d.headerId, cutStart: cut })
    return
  }
  if (d.jobKey) emit('shiftJob', { jobKey: d.jobKey, cutStart: cut })
}
</script>

<style scoped>
.gantt {
  --lane-cut-bg: #fef3c7;
  --lane-cut-ink: #854d0e;
  --lane-cut-bar: #f59e0b;
  --lane-stitch-bg: #e0f2fe;
  --lane-stitch-ink: #0369a1;
  --lane-stitch-bar: #0284c7;
  --lane-stitch-sole-bg: #d6edfc;
  --lane-stitch-sole-ink: #0369a1;
  --lane-stitch-sole-bar: #0369a1;
  --lane-stitch-vamp-bg: #f0f9ff;
  --lane-stitch-vamp-ink: #0284c7;
  --lane-stitch-vamp-bar: #38bdf8;
  --lane-last-bg: #e0e7ff;
  --lane-last-ink: #3730a3;
  --lane-last-bar: #6366f1;
  --lane-pack-bg: #f1f5f9;
  --lane-pack-ink: #334155;
  --lane-pack-bar: #64748b;
  --lane-other-bg: #f8fafc;
  --lane-other-ink: #475569;
  --lane-other-bar: #94a3b8;
  --gantt-off: #fff0f0;
  display: flex;
  flex-direction: column;
  min-height: 180px;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.gantt.fill {
  height: 100%;
  min-height: 0;
}
.gantt-empty {
  padding: 36px 20px;
  text-align: center;
  color: #334155;
  font-size: 14px;
}
.gantt.fill .gantt-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.gantt-empty p {
  margin: 0 0 6px;
}
.gantt-empty-cta {
  margin-top: 12px;
  border: 0;
  border-radius: 8px;
  padding: 8px 16px;
  background: #0076ff;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.gantt-empty-cta:hover {
  background: #005fcc;
}
.gantt-scroll {
  overflow: auto;
  max-height: min(52vh, 520px);
}
.gantt.fill .gantt-scroll {
  flex: 1;
  min-height: 0;
  max-height: none;
}
.gantt-grid {
  display: grid;
  width: max-content;
  min-width: 100%;
}
.gantt-corner,
.gantt-day,
.gantt-label,
.gantt-track,
.gantt-load-label,
.gantt-load-cell {
  border-bottom: 1px solid #e8edf4;
  border-right: 1px solid #eef2f7;
}
.gantt-corner {
  position: sticky;
  top: 0;
  left: 0;
  z-index: 6;
  background: #f7f9fc;
  padding: 8px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.04em;
  box-shadow: 1px 1px 0 #e8edf4;
}
.gantt-day {
  position: sticky;
  top: 0;
  z-index: 5;
  background: #f7f9fc;
  text-align: center;
  padding: 6px 0 8px;
  font-size: 12px;
  color: #334155;
  box-shadow: 0 1px 0 #e8edf4;
}
.gantt-day strong {
  display: block;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.gantt-dow {
  display: block;
  font-size: 10px;
  color: #94a3b8;
  line-height: 1.2;
}
.gantt-day.is-today,
.gantt-cell.is-today {
  background: #e8f3ff;
}
.gantt-day.is-today strong {
  color: #005fcc;
}
.gantt-day.is-off,
.gantt-day.is-holiday,
.gantt-day.is-blackout {
  background: var(--gantt-off);
  color: #94a3b8;
}
.gantt-day.is-blackout .gantt-day-mark {
  color: #b91c1c;
  font-weight: 700;
  opacity: 1;
}
.gantt-day.is-makeup strong {
  color: #0f766e;
}
.gantt-day-mark {
  display: block;
  font-size: 9px;
  line-height: 1;
  color: inherit;
  opacity: 0.85;
}
.gantt-label {
  grid-column: 1;
  position: sticky;
  left: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 10px;
  background: #fff;
  border: 0;
  border-bottom: 1px solid #e8edf4;
  border-right: 1px solid #eef2f7;
  text-align: left;
  min-height: 56px;
  box-sizing: border-box;
}
.gantt-label-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.gantt-label.issued:hover,
.gantt-label.draft:hover {
  background: #e8f3ff;
}
.gantt-label.draft {
  background: #fffdf6;
}
.gantt-label.draft:hover {
  background: #fff7ed;
}
.gantt-label-title {
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
  max-width: 176px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gantt-label-sub {
  font-size: 10px;
  color: #94a3b8;
  max-width: 176px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gantt-pills {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
  margin-top: 2px;
}
.gantt-pill {
  font-size: 10px;
  line-height: 1.4;
  padding: 0 5px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.gantt-pill.draft {
  background: #fff7ed;
  color: #c2410c;
  border-color: #fed7aa;
}
.gantt-pill.issued {
  background: #e8f3ff;
  color: #005fcc;
  border-color: #b3d4ff;
}
.gantt-pill.rush {
  background: #fef2f2;
  color: #b91c1c;
  border-color: #fecaca;
}
.gantt-pill.kit,
.gantt-pill.risk {
  background: #fffbeb;
  color: #92400e;
  border-color: #fde68a;
}
.gantt-track {
  grid-column: 2 / -1;
  position: relative;
  min-height: 56px;
  background-image: repeating-linear-gradient(
    90deg,
    transparent 0,
    transparent 43px,
    #eef2f7 43px,
    #eef2f7 44px
  );
}
.gantt-track.draft,
.gantt-track.draggable {
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.gantt-track.draft {
  background-color: #fffdf6;
}
.gantt-track.dragging {
  cursor: grabbing;
}
.gantt-load-label {
  position: sticky;
  left: 0;
  z-index: 3;
  background: #f7f9fc;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}
.gantt-load-cell {
  position: relative;
  height: 28px;
  background: #f7f9fc;
}
.gantt-load-cell.is-today {
  background: #e8f3ff;
}
.gantt-load-fill {
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: 3px;
  border-radius: 1px 1px 0 0;
  background: #94a3b8;
}
.gantt-load-cell.is-ok .gantt-load-fill {
  background: #94a3b8;
}
.gantt-load-cell.is-warn .gantt-load-fill {
  background: #eab308;
}
.gantt-load-cell.is-over .gantt-load-fill {
  background: #ef4444;
}
.gantt-load-cell.is-off,
.gantt-load-cell.is-rest {
  background: var(--gantt-off);
}
.gantt-load-cell.is-rest .gantt-load-fill {
  display: none;
}
.gantt-bar.ghost {
  height: 16px;
  line-height: 16px;
  opacity: 0.55;
  border: 1px dashed var(--lane-bar);
  pointer-events: none;
  font-size: 10px;
  box-shadow: none;
  filter: none;
}
.gantt-bar.ghost::before {
  display: none;
}
.gantt-insert {
  margin-top: 2px;
  border: 0;
  background: transparent;
  padding: 0;
  font-size: 11px;
  font-weight: 600;
  color: #b91c1c;
  cursor: pointer;
}
.gantt-insert:hover {
  text-decoration: underline;
}
.gantt-reschedule {
  color: #005fcc;
}
.gantt-sources {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.gantt-source {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 4px;
  width: 100%;
}
.gantt-source-txt {
  font-size: 11px;
  line-height: 1.35;
  color: #334155;
  min-width: 0;
}
.gantt-source-txt em {
  font-style: normal;
  color: #64748b;
  margin: 0 2px;
}
.gantt-drop {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  padding: 0;
  font-size: 11px;
  font-weight: 600;
  color: #c2410c;
  cursor: pointer;
}
.gantt-drop:hover {
  text-decoration: underline;
}
.gantt-off-col,
.gantt-off-col.holiday,
.gantt-off-col.blackout {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 44px;
  background: var(--gantt-off);
  pointer-events: none;
  z-index: 0;
}
.gantt-snap-col {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 44px;
  border-left: 1px dashed #0076ff;
  background: rgba(0, 118, 255, 0.08);
  pointer-events: none;
  z-index: 2;
}
.gantt-today-col {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 44px;
  background: rgba(0, 118, 255, 0.08);
  pointer-events: none;
}
.gantt-bar {
  --lane-bg: var(--lane-other-bg);
  --lane-ink: var(--lane-other-ink);
  --lane-bar: var(--lane-other-bar);
  position: absolute;
  top: 16px;
  height: 20px;
  z-index: 1;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  background: var(--lane-bg);
  color: var(--lane-ink);
  font-size: 11px;
  font-weight: 500;
  line-height: 20px;
  padding: 0 8px 0 9px;
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: box-shadow 0.12s ease, filter 0.12s ease, opacity 0.12s ease;
}
.gantt-bar::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--lane-bar);
  border-radius: 4px 0 0 4px;
}
.gantt-bar.draft {
  opacity: 0.92;
}
.gantt-bar.clickable {
  cursor: pointer;
}
.gantt-bar.draggable {
  cursor: grab;
}
.gantt-bar.cut {
  --lane-bg: var(--lane-cut-bg);
  --lane-ink: var(--lane-cut-ink);
  --lane-bar: var(--lane-cut-bar);
  color: #854d0e;
  font-weight: 600;
}
.gantt-bar.stitch {
  --lane-bg: var(--lane-stitch-bg);
  --lane-ink: var(--lane-stitch-ink);
  --lane-bar: var(--lane-stitch-bar);
}
.gantt-bar.stitch-sole {
  --lane-bg: var(--lane-stitch-sole-bg);
  --lane-ink: var(--lane-stitch-sole-ink);
  --lane-bar: var(--lane-stitch-sole-bar);
}
.gantt-bar.stitch-vamp {
  --lane-bg: var(--lane-stitch-vamp-bg);
  --lane-ink: var(--lane-stitch-vamp-ink);
  --lane-bar: var(--lane-stitch-vamp-bar);
}
.gantt-bar.pack {
  --lane-bg: var(--lane-pack-bg);
  --lane-ink: var(--lane-pack-ink);
  --lane-bar: var(--lane-pack-bar);
}
.gantt-bar.last {
  --lane-bg: var(--lane-last-bg);
  --lane-ink: var(--lane-last-ink);
  --lane-bar: var(--lane-last-bar);
}
.gantt-bar.other {
  --lane-bg: var(--lane-other-bg);
  --lane-ink: var(--lane-other-ink);
  --lane-bar: var(--lane-other-bar);
}
.gantt-bar.done {
  opacity: 0.6;
}
.gantt-track:hover .gantt-bar:not(.ghost) {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.55),
    0 0 0 1px rgba(15, 23, 42, 0.08),
    0 1px 4px rgba(15, 23, 42, 0.08);
}
.gantt-bar:hover,
.gantt-track:hover .gantt-bar:not(.ghost):hover,
.gantt-track.dragging .gantt-bar:not(.ghost) {
  z-index: 5;
  filter: brightness(1.03);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 0 0 1px rgba(255, 255, 255, 0.95),
    0 3px 10px rgba(15, 23, 42, 0.18);
}
.gantt-bar.done:hover {
  opacity: 0.85;
}
.gantt-bar.alert {
  animation: gantt-alert-pulse 1.6s ease-in-out infinite;
  box-shadow: 0 0 0 2px #ef4444;
}
.gantt-bar.alert:hover,
.gantt-track.dragging .gantt-bar.alert {
  animation: none;
  z-index: 6;
  box-shadow:
    0 0 0 2px #ef4444,
    0 3px 10px rgba(15, 23, 42, 0.18);
}
.gantt-bar-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: inherit;
}
.gantt-bar-check {
  flex-shrink: 0;
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  color: #059669;
}
.gantt-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-top: 1px solid #e8edf4;
  font-size: 12px;
}
.gantt-leg {
  --lane-bg: var(--lane-other-bg);
  --lane-bar: var(--lane-other-bar);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #334155;
}
.gantt-leg::before {
  content: '';
  width: 16px;
  height: 10px;
  box-sizing: border-box;
  border-radius: 3px;
  background: var(--lane-bg);
  border-left: 3px solid var(--lane-bar);
}
.gantt-leg.cut {
  --lane-bg: var(--lane-cut-bg);
  --lane-bar: var(--lane-cut-bar);
}
.gantt-leg.stitch,
.gantt-leg.stitch-sole {
  --lane-bg: var(--lane-stitch-sole-bg);
  --lane-bar: var(--lane-stitch-sole-bar);
}
.gantt-leg.stitch-vamp {
  --lane-bg: var(--lane-stitch-vamp-bg);
  --lane-bar: var(--lane-stitch-vamp-bar);
}
.gantt-leg.last {
  --lane-bg: var(--lane-last-bg);
  --lane-bar: var(--lane-last-bar);
}
.gantt-leg.pack {
  --lane-bg: var(--lane-pack-bg);
  --lane-bar: var(--lane-pack-bar);
}
.muted {
  color: #64748b;
  font-weight: 400;
}
@keyframes gantt-alert-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.95);
  }
  50% {
    box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.28);
  }
}
@media (prefers-reduced-motion: reduce) {
  .gantt-bar {
    transition: none;
  }
  .gantt-bar.alert {
    animation: none;
    box-shadow: 0 0 0 2px #ef4444;
  }
}
</style>

<style>
.gantt-drag-hint {
  position: fixed;
  z-index: 4000;
  pointer-events: none;
  padding: 8px 12px;
  background: #0f172a;
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.28);
  white-space: nowrap;
}
.gantt-drag-shift {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  font-weight: 500;
  color: #cbd5e1;
}
</style>
