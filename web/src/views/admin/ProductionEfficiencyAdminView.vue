<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">生产效率</h1>
        <p class="page-desc">单款 / 单人 / 多人 / 个人 / 部门 · 按日人效</p>
      </div>
    </header>
    <div class="admin-card">
      <el-tabs v-model="activeTab" class="record-tabs" @tab-change="onTabChange">
        <el-tab-pane label="单款平均效率" name="model_avg" />
        <el-tab-pane label="单人平均效率" name="person_avg" />
        <el-tab-pane label="工序多人效率" name="process_team" />
        <el-tab-pane label="个人效率" name="personal" />
        <el-tab-pane label="部门效率" name="department" />
      </el-tabs>

      <div class="admin-toolbar eff-toolbar">
        <div class="eff-toolbar-left">
          <div class="eff-date-wrap">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              size="small"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始"
              end-placeholder="结束"
              clearable
              @change="onDateRangeChange"
            />
          </div>
          <template v-if="activeTab === 'model_avg'">
            <div class="product-code-group">
              <button
                v-for="p in visibleRecentProducts"
                :key="p.product_id"
                type="button"
                class="product-code-item"
                :class="{ 'is-active': selectedProductCode === p.product_code }"
                @click="selectProductCode(p.product_code)"
              >
                {{ p.product_code }}
              </button>
            </div>
            <el-button
              v-if="recentProducts.length > PRODUCT_VISIBLE_LIMIT"
              link
              type="primary"
              class="product-more-btn"
              @click="productsExpanded = !productsExpanded"
            >
              {{ productsExpanded ? '收起' : `显示更多（${recentProducts.length - PRODUCT_VISIBLE_LIMIT}）` }}
            </el-button>
          </template>
          <el-radio-group
            v-if="activeTab === 'personal'"
            v-model="personalSegmentId"
            size="small"
            class="personal-seg-group"
            @change="load"
          >
            <el-radio-button
              v-for="s in personalSegments"
              :key="s.segment_id"
              :value="s.segment_id"
            >
              {{ s.segment_name }}
            </el-radio-button>
          </el-radio-group>
          <el-checkbox
            v-if="activeTab === 'personal'"
            v-model="includeInactive"
            @change="load"
          >
            显示离职员工
          </el-checkbox>
        </div>
        <div class="spacer" />
        <span class="muted">{{ unitText }}</span>
      </div>

      <p v-if="activeTab === 'model_avg' && !loading && !recentProducts.length" class="view-hint warn">
        暂无报工工厂型号
      </p>
      <p v-if="!loading && !leafColumns.length" class="view-hint warn">
        {{ emptyHint }}
      </p>

      <div v-loading="loading" ref="tableHostRef" class="admin-table-host eff-table-host">
        <!-- 部门效率：部门 → 上班时间 / 产量 / 效率（′″/双） -->
        <table v-if="activeTab === 'department'" class="eff-matrix">
          <colgroup>
            <col :style="{ width: colWidthPx('work_date', 110) }" />
            <template v-for="dept in departmentColumns" :key="`cg-d-${dept.segment_id}`">
              <col :style="{ width: colWidthPx(deptHoursKey(dept.segment_id), 88) }" />
              <col :style="{ width: colWidthPx(deptQtyKey(dept.segment_id), 80) }" />
              <col :style="{ width: colWidthPx(deptEffKey(dept.segment_id), 110) }" />
            </template>
          </colgroup>
          <thead>
            <tr>
              <th class="sticky-col date-col" rowspan="2">
                日期
                <span class="col-resizer" @mousedown.prevent="startResize('work_date', $event)" />
              </th>
              <th
                v-for="dept in departmentColumns"
                :key="`dh-${dept.segment_id}`"
                class="seg-head"
                colspan="3"
              >
                {{ dept.department_name }}
              </th>
            </tr>
            <tr>
              <template v-for="dept in departmentColumns" :key="`dw-${dept.segment_id}`">
                <th class="proc-head">
                  上班时间
                  <span
                    class="col-resizer"
                    @mousedown.prevent="startResize(deptHoursKey(dept.segment_id), $event)"
                  />
                </th>
                <th class="proc-head">
                  产量
                  <span
                    class="col-resizer"
                    @mousedown.prevent="startResize(deptQtyKey(dept.segment_id), $event)"
                  />
                </th>
                <th class="proc-head">
                  效率
                  <span
                    class="col-resizer"
                    @mousedown.prevent="startResize(deptEffKey(dept.segment_id), $event)"
                  />
                </th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.work_date" :class="{ 'is-avg': row._isAvg }">
              <td class="sticky-col date-col">{{ row.work_date }}</td>
              <template v-for="dept in departmentColumns" :key="`${row.work_date}-d-${dept.segment_id}`">
                <td class="num-cell">{{ formatDeptHours(row[deptHoursKey(dept.segment_id)]) }}</td>
                <td class="num-cell">{{ formatDeptQty(row[deptQtyKey(dept.segment_id)]) }}</td>
                <td class="num-cell">{{ formatDeptEff(row[deptEffKey(dept.segment_id)]) }}</td>
              </template>
            </tr>
            <tr v-if="!tableRows.length && !loading">
              <td class="sticky-col date-col muted" :colspan="1 + leafColumns.length">暂无数据</td>
            </tr>
          </tbody>
        </table>

        <!-- 个人效率：工序 → 员工 / 损失 -->
        <table v-else-if="activeTab === 'personal'" class="eff-matrix">
          <colgroup>
            <col :style="{ width: colWidthPx('work_date', 110) }" />
            <template v-for="proc in personalColumns" :key="`cg-${proc.process_id}`">
              <template v-for="w in proc.workers" :key="`cg-${w.qty_key}`">
                <col :style="{ width: colWidthPx(w.qty_key, 72) }" />
                <col :style="{ width: colWidthPx(w.loss_key, 64) }" />
              </template>
            </template>
          </colgroup>
          <thead>
            <tr>
              <th class="sticky-col date-col" rowspan="2">
                日期
                <span class="col-resizer" @mousedown.prevent="startResize('work_date', $event)" />
              </th>
              <th
                v-for="proc in personalColumns"
                :key="`ph-${proc.process_id}`"
                class="seg-head"
                :colspan="Math.max((proc.workers?.length || 0) * 2, 1)"
              >
                {{ proc.process_name }}
              </th>
            </tr>
            <tr>
              <template v-for="proc in personalColumns" :key="`pw-${proc.process_id}`">
                <template v-for="w in proc.workers" :key="w.qty_key">
                  <th class="proc-head">
                    {{ w.employee_name }}
                    <span class="col-resizer" @mousedown.prevent="startResize(w.qty_key, $event)" />
                  </th>
                  <th class="proc-head loss-head">
                    损失
                    <span class="col-resizer" @mousedown.prevent="startResize(w.loss_key, $event)" />
                  </th>
                </template>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.work_date" :class="{ 'is-avg': row._isAvg }">
              <td class="sticky-col date-col">{{ row.work_date }}</td>
              <template v-for="proc in personalColumns" :key="`${row.work_date}-${proc.process_id}`">
                <template v-for="w in proc.workers" :key="`${row.work_date}-${w.qty_key}`">
                  <td class="num-cell">{{ formatEffNum(row[w.qty_key]) }}</td>
                  <td class="num-cell">{{ formatLoss(row[w.loss_key]) }}</td>
                </template>
              </template>
            </tr>
            <tr v-if="!tableRows.length && !loading">
              <td class="sticky-col date-col muted" :colspan="1 + leafColumns.length">暂无数据</td>
            </tr>
          </tbody>
        </table>

        <!-- 其余页签：工序段 → 工序 -->
        <table v-else class="eff-matrix">
          <colgroup>
            <col :style="{ width: colWidthPx('work_date', 110) }" />
            <col
              v-for="col in leafColumns"
              :key="col.key"
              :style="{ width: colWidthPx(col.key, 96) }"
            />
          </colgroup>
          <thead>
            <tr>
              <th class="sticky-col date-col" rowspan="2">
                日期
                <span class="col-resizer" @mousedown.prevent="startResize('work_date', $event)" />
              </th>
              <th
                v-for="seg in segmentColumns"
                :key="`seg-${seg.segment_id}`"
                class="seg-head"
                :colspan="Math.max(seg.processes?.length || 0, 1)"
              >
                {{ seg.segment_name }}
              </th>
            </tr>
            <tr>
              <template v-for="seg in segmentColumns" :key="`seg-proc-${seg.segment_id}`">
                <th
                  v-for="proc in seg.processes"
                  :key="`proc-${proc.process_id}`"
                  class="proc-head"
                >
                  {{ proc.process_name }}
                  <span
                    class="col-resizer"
                    @mousedown.prevent="startResize(`p_${proc.process_id}`, $event)"
                  />
                </th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.work_date" :class="{ 'is-avg': row._isAvg }">
              <td class="sticky-col date-col">{{ row.work_date }}</td>
              <td
                v-for="col in leafColumns"
                :key="`${row.work_date}-${col.key}`"
                class="num-cell"
              >
                {{ formatCell(row[col.key], row._isAvg) }}
              </td>
            </tr>
            <tr v-if="!tableRows.length && !loading">
              <td class="sticky-col date-col muted" :colspan="1 + leafColumns.length">暂无数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import http from '@/api/http'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const STORAGE_KEY = 'erp_admin_col_widths:production-eff-matrix'
const MIN_COL = 48
const DEFAULT_DATE = 110
const DEFAULT_PROC = 96
const PRODUCT_VISIBLE_LIMIT = 10

const activeTab = ref<'model_avg' | 'person_avg' | 'process_team' | 'personal' | 'department'>(
  'model_avg',
)
const loading = ref(false)
const recentProducts = ref<{ product_id: number; product_code: string; last_reported_at?: string }[]>([])
const selectedProductCode = ref<string>('')
const productsExpanded = ref(false)
const matrix = ref<any>({ columns: [], rows: [], averages: {}, unit: '双/人/小时' })
const dateRange = ref<string[] | null>([])
const personalSegmentId = ref<number | undefined>(undefined)
const includeInactive = ref(false)
const colWidths = ref<Record<string, number>>(loadColWidths())

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const tableMaxHeightPx = computed(() => `${tableMaxHeight.value || 480}px`)

const unitText = computed(() => {
  if (activeTab.value === 'department') {
    return `上班时间：${matrix.value.work_time_unit || '小时'} · 产量：${matrix.value.qty_unit || '双'} · 效率：′″/双`
  }
  if (activeTab.value === 'personal') {
    return `单位：${matrix.value.unit || '双/小时'} · 损失单位：${matrix.value.loss_unit || '元'}`
  }
  if (activeTab.value === 'process_team') return `单位：${matrix.value.unit || '双/小时'}`
  return `单位：${matrix.value.unit || '双/人/小时'}`
})

const emptyHint = computed(() => {
  if (activeTab.value === 'personal') {
    return '该工序段暂无报工员工列。可调整日期段或勾选显示离职员工。'
  }
  if (activeTab.value === 'department') {
    return '暂无部门列。请先在「主数据 / 工序」维护工序，并归属到工序段。'
  }
  return '暂无可用工序列。请先在「主数据 / 工序」维护工序，并归属到工序段。'
})

const segmentColumns = computed(() =>
  activeTab.value === 'personal' || activeTab.value === 'department'
    ? []
    : (matrix.value.columns || []).filter((s: any) => (s.processes || []).length > 0),
)

const personalColumns = computed(() =>
  activeTab.value === 'personal' ? matrix.value.columns || [] : [],
)

const departmentColumns = computed(() =>
  activeTab.value === 'department' ? matrix.value.columns || [] : [],
)

const personalSegments = computed(() => matrix.value.segments || [])

const visibleRecentProducts = computed(() =>
  productsExpanded.value
    ? recentProducts.value
    : recentProducts.value.slice(0, PRODUCT_VISIBLE_LIMIT),
)

function deptHoursKey(segmentId: number | string) {
  return `d_${segmentId}_hours`
}
function deptQtyKey(segmentId: number | string) {
  return `d_${segmentId}_qty`
}
function deptEffKey(segmentId: number | string) {
  return `d_${segmentId}_eff`
}

const leafColumns = computed(() => {
  if (activeTab.value === 'personal') {
    const cols: { key: string; label: string }[] = []
    for (const proc of personalColumns.value) {
      for (const w of proc.workers || []) {
        cols.push({ key: w.qty_key, label: w.employee_name })
        cols.push({ key: w.loss_key, label: '损失' })
      }
    }
    return cols
  }
  if (activeTab.value === 'department') {
    const cols: { key: string; label: string }[] = []
    for (const dept of departmentColumns.value) {
      cols.push({ key: deptHoursKey(dept.segment_id), label: '上班时间' })
      cols.push({ key: deptQtyKey(dept.segment_id), label: '产量' })
      cols.push({ key: deptEffKey(dept.segment_id), label: '效率' })
    }
    return cols
  }
  const cols: { key: string; label: string; segment: string }[] = []
  for (const seg of segmentColumns.value) {
    for (const proc of seg.processes || []) {
      cols.push({
        key: `p_${proc.process_id}`,
        label: proc.process_name,
        segment: seg.segment_name,
      })
    }
  }
  return cols
})

function flattenDeptValues(values: Record<string, any> | undefined, target: Record<string, any>) {
  for (const [sid, cell] of Object.entries(values || {})) {
    if (!cell || typeof cell !== 'object') continue
    target[deptHoursKey(sid)] = cell.work_hours
    target[deptQtyKey(sid)] = cell.qty
    target[deptEffKey(sid)] = cell.efficiency
  }
}

const tableRows = computed(() => {
  const rows = (matrix.value.rows || []).map((r: any) => {
    const item: Record<string, any> = { work_date: r.work_date, _isAvg: false, ...(r.values || {}) }
    if (activeTab.value === 'department') {
      flattenDeptValues(r.values, item)
    } else if (activeTab.value !== 'personal') {
      for (const [pid, val] of Object.entries(r.values || {})) {
        item[`p_${pid}`] = val
      }
    }
    return item
  })
  if (!rows.length) return rows
  const avgLabel = '平均'
  const avg: Record<string, any> = { work_date: avgLabel, _isAvg: true }
  if (activeTab.value === 'personal') {
    Object.assign(avg, matrix.value.averages || {})
  } else if (activeTab.value === 'department') {
    flattenDeptValues(matrix.value.averages, avg)
  } else {
    for (const [pid, val] of Object.entries(matrix.value.averages || {})) {
      avg[`p_${pid}`] = val
    }
  }
  rows.unshift(avg)
  return rows
})

function loadColWidths(): Record<string, number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, number> = {}
    for (const [k, v] of Object.entries(parsed || {})) {
      if (typeof v === 'number' && Number.isFinite(v) && v >= MIN_COL) out[k] = Math.floor(v)
    }
    return out
  } catch {
    return {}
  }
}

function saveColWidths() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(colWidths.value))
  } catch {
    // ignore
  }
}

function colWidthPx(key: string, fallback: number) {
  const w = colWidths.value[key] ?? fallback
  return `${w}px`
}

let dragKey: string | null = null
let dragStartX = 0
let dragStartW = 0

function onDragMove(ev: MouseEvent) {
  if (!dragKey) return
  const next = Math.max(MIN_COL, Math.floor(dragStartW + (ev.clientX - dragStartX)))
  colWidths.value = { ...colWidths.value, [dragKey]: next }
}

function onDragEnd() {
  if (!dragKey) return
  dragKey = null
  saveColWidths()
  document.body.classList.remove('eff-col-resizing')
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
}

function startResize(key: string, ev: MouseEvent) {
  dragKey = key
  dragStartX = ev.clientX
  dragStartW =
    colWidths.value[key] ?? (key === 'work_date' ? DEFAULT_DATE : DEFAULT_PROC)
  document.body.classList.add('eff-col-resizing')
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}

function formatEffNum(value: any) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return value
  return n.toFixed(3)
}

function formatLoss(value: any) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function formatCell(value: any, isAvg = false) {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') {
    const eff = value.efficiency
    const workers = Number(value.workers || 0)
    if (eff == null) return '—'
    if (!isAvg && workers > 1) return `${formatEffNum(eff)}/${workers}人`
    return formatEffNum(eff)
  }
  return formatEffNum(value)
}

function formatDeptHours(value: any) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(1)
}

function formatDeptQty(value: any) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function formatDeptEff(value: any) {
  if (value == null || value === '') return '—'
  return String(value)
}

function localDateText(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function ensureDateRange() {
  if (dateRange.value?.length === 2) return
  const to = new Date()
  const from = new Date()
  from.setDate(to.getDate() - 6)
  dateRange.value = [localDateText(from), localDateText(to)]
}

async function loadRecentProducts() {
  try {
    const res: any = await http.get('/production-efficiency/recent-products')
    recentProducts.value = res.data?.items || []
    const codes = new Set(recentProducts.value.map((p) => p.product_code))
    if (!selectedProductCode.value || !codes.has(selectedProductCode.value)) {
      selectedProductCode.value = recentProducts.value[0]?.product_code || ''
    }
    if (recentProducts.value.length <= PRODUCT_VISIBLE_LIMIT) {
      productsExpanded.value = false
    }
  } catch {
    recentProducts.value = []
  }
}

function selectProductCode(code: string) {
  if (selectedProductCode.value === code) return
  selectedProductCode.value = code
  void loadMatrix()
}

async function loadMatrix() {
  loading.value = true
  try {
    if (activeTab.value === 'model_avg' && !selectedProductCode.value) {
      matrix.value = { columns: [], rows: [], averages: {}, unit: '双/人/小时' }
      measureTableHeight()
      return
    }
    const path =
      activeTab.value === 'person_avg'
        ? '/production-efficiency/person-avg'
        : activeTab.value === 'process_team'
          ? '/production-efficiency/process-team'
          : activeTab.value === 'personal'
            ? '/production-efficiency/personal'
            : activeTab.value === 'department'
              ? '/production-efficiency/department'
              : '/production-efficiency/model-avg'
    const params: Record<string, string | number | boolean | undefined> = {
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
    }
    if (activeTab.value === 'model_avg' && selectedProductCode.value) {
      params.product_code = selectedProductCode.value
    }
    if (activeTab.value === 'personal') {
      if (personalSegmentId.value) params.segment_id = personalSegmentId.value
      params.include_inactive = includeInactive.value
    }
    const res: any = await http.get(path, { params })
    matrix.value = res.data || { columns: [], rows: [], averages: {} }
    if (activeTab.value === 'personal') {
      if (!personalSegmentId.value && matrix.value.segment_id) {
        personalSegmentId.value = matrix.value.segment_id
      }
    }
    measureTableHeight()
  } finally {
    loading.value = false
  }
}

async function load() {
  if (activeTab.value === 'model_avg' && !recentProducts.value.length) {
    await loadRecentProducts()
  }
  await loadMatrix()
}

async function onDateRangeChange() {
  await loadMatrix()
}

async function onTabChange() {
  if (activeTab.value === 'model_avg') {
    await loadRecentProducts()
  }
  await loadMatrix()
}

onMounted(async () => {
  ensureDateRange()
  if (activeTab.value === 'model_avg') {
    await loadRecentProducts()
  }
  await loadMatrix()
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  document.body.classList.remove('eff-col-resizing')
})
</script>

<style scoped>
.eff-table-host {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: auto;
  max-height: v-bind(tableMaxHeightPx);
  background: #fff;
  border-radius: 12px;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}

.eff-matrix {
  border-collapse: collapse;
  table-layout: fixed;
  width: max-content;
  min-width: 100%;
  font-size: 13px;
  color: var(--ws-table-text, #1f2937);
  background: #fff;
}

.eff-matrix th,
.eff-matrix td {
  border-right: 1px solid #dce3ed;
  border-bottom: 1px solid #dce3ed;
  padding-left: 0;
  padding-right: 0;
  white-space: nowrap;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
}

.eff-matrix th {
  padding-top: 12px;
  padding-bottom: 12px;
  background: var(--ws-table-header, #f7f9fc);
  color: var(--ws-table-muted, #64748b);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  line-height: 1.35;
}

.eff-matrix td {
  padding-top: 13px;
  padding-bottom: 13px;
}

.eff-matrix thead th {
  position: sticky;
  top: 0;
  z-index: 2;
}

.eff-matrix thead tr:nth-child(2) th {
  top: 41px;
}

.eff-matrix .sticky-col {
  position: sticky;
  left: 0;
  z-index: 3;
  background: #fff;
}

.eff-matrix thead .sticky-col {
  z-index: 4;
  background: var(--ws-table-header, #f7f9fc);
}

.date-col,
.proc-head {
  position: relative;
}

.seg-head {
  background: #eef3f9 !important;
}

.loss-head {
  color: var(--ws-table-muted, #64748b);
  font-weight: 600;
}

.num-cell {
  font-variant-numeric: tabular-nums;
}

.col-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 7px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
  user-select: none;
}

.col-resizer:hover,
.col-resizer:active {
  background: color-mix(in srgb, var(--el-color-primary) 35%, transparent);
}

.eff-matrix tbody tr:nth-child(even) td {
  background: var(--ws-table-stripe, #eef2f7);
}

.eff-matrix tbody tr:nth-child(even) .sticky-col {
  background: var(--ws-table-stripe, #eef2f7);
}

.eff-matrix tbody tr:not(.is-avg):hover td {
  background: var(--ws-table-hover, #d6e8ff);
}

.eff-matrix tbody tr:not(.is-avg):hover .sticky-col {
  background: var(--ws-table-hover, #d6e8ff);
}

.eff-matrix tbody tr.is-avg td {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  background: var(--ws-table-stripe, #eef2f7);
}

.eff-matrix tbody tr.is-avg .sticky-col {
  font-weight: 700;
  background: var(--ws-table-stripe, #eef2f7);
}

.view-hint {
  margin: 0 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.view-hint.warn {
  color: var(--el-color-warning);
}

.muted {
  color: var(--el-text-color-secondary);
}

.eff-toolbar {
  flex-wrap: nowrap;
  align-items: center;
  gap: 12px;
}

.eff-toolbar-left {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 12px;
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
}

.product-code-group,
.personal-seg-group {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
}

.product-code-item {
  appearance: none;
  border: 0;
  outline: none;
  background: transparent;
  box-shadow: none;
  margin: 0;
  padding: 4px 8px;
  border-radius: 4px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.2;
  cursor: pointer;
  white-space: nowrap;
}

.product-code-item:hover {
  color: var(--el-color-primary);
}

.product-code-item.is-active {
  color: #fff;
  background: var(--el-color-primary);
  font-weight: 600;
}

.product-more-btn {
  margin-left: 0;
  height: 24px;
  padding: 0 4px;
  flex: 0 0 auto;
  white-space: nowrap;
}

.eff-date-wrap {
  flex: 0 0 auto;
  display: inline-flex;
}

.eff-date-wrap :deep(.el-date-editor--daterange) {
  --el-date-editor-width: 232px;
  width: 232px !important;
  max-width: 232px;
}

.eff-date-wrap :deep(.el-date-editor--daterange .el-input__wrapper) {
  justify-content: flex-start;
  gap: 0;
  padding-left: 6px;
  padding-right: 4px;
}

.eff-date-wrap :deep(.el-date-editor--daterange .el-range-input) {
  width: 74px !important;
  flex: 0 0 74px;
  font-size: 12px;
}

.eff-date-wrap :deep(.el-date-editor--daterange .el-range-separator) {
  flex: 0 0 auto;
  width: auto;
  padding: 0 2px;
  font-size: 12px;
}

.eff-date-wrap :deep(.el-date-editor--daterange .el-range__icon) {
  margin-left: 2px;
}

.eff-date-wrap :deep(.el-date-editor--daterange .el-range__close-icon) {
  display: inline-flex;
  flex: 0 0 auto;
  margin-left: 0;
}
</style>

<style>
body.eff-col-resizing {
  cursor: col-resize !important;
  user-select: none !important;
}
</style>
