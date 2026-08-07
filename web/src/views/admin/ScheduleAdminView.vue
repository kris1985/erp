<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">排产</h1>
        <p class="page-desc">待排池 · 倒排草稿 · 计划月历（只读，含节假日）</p>
      </div>
    </header>

    <el-tabs v-model="mainTab" class="admin-card" @tab-change="onTabChange">
      <el-tab-pane label="待排池" name="pool">
        <div class="admin-toolbar">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="单号/客户/产品"
            style="width: 200px"
            @clear="loadPool"
            @keyup.enter="loadPool"
          />
          <el-checkbox v-model="filters.rush_only" @change="loadPool">仅急单</el-checkbox>
          <el-checkbox v-model="filters.hide_first_kit_blocked" @change="loadPool">隐藏首道缺料</el-checkbox>
          <el-button @click="loadPool">刷新</el-button>
          <el-button type="primary" :disabled="!selectedIds.length" :loading="creating" @click="createDraft">
            生成倒排草稿（{{ selectedIds.length }}）
          </el-button>
        </div>

        <div ref="tableHostRef">
          <el-table
            ref="tableRef"
            v-loading="loading"
            :data="pool"
            border
            stripe
            :max-height="tableMaxHeight"
            @selection-change="onSelect"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column type="selection" width="48" />
            <el-table-column prop="order_no" label="生产单" :width="colWidth('order_no', 120)" resizable />
            <el-table-column
              column-key="product_image"
              label="图片"
              :width="colWidth('product_image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default="{ row }">
                <el-image
                  v-if="row.product_image_url"
                  :src="row.product_image_url"
                  :preview-src-list="[row.product_image_url]"
                  preview-teleported
                  fit="contain"
                  class="product-thumb"
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column prop="product_code" label="产品" :width="colWidth('product_code', 120)" resizable>
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="customer_name"
              label="客户"
              :min-width="flexColMinWidth('customer_name', 100)"
              resizable
            />
            <el-table-column prop="total_qty" label="数量" :width="colWidth('total_qty', 72)" align="right" resizable />
            <el-table-column prop="delivery_date" label="交期" :width="colWidth('delivery_date', 110)" resizable />
            <el-table-column column-key="rush" label="急" :width="colWidth('rush', 56)" align="center" resizable>
              <template #default="{ row }">
                <el-tag v-if="row.is_rush" type="danger" size="small">急</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column column-key="kit" label="齐套" :width="colWidth('kit', 120)" resizable>
              <template #default="{ row }">
                <el-tag :type="row.kit_ok ? 'success' : 'danger'" size="small" effect="plain">
                  整单{{ row.kit_ok ? '齐' : '缺' }}
                </el-tag>
                <el-tag
                  :type="row.first_kit_ok ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                  style="margin-left: 4px"
                >
                  首道{{ row.first_kit_ok ? '齐' : '缺' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column column-key="sched" label="排产" :width="colWidth('sched', 90)" resizable>
              <template #default="{ row }">
                {{ scheduleLabel(row.schedule_status) }}
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="draft" style="margin-top: 16px">
          <div class="admin-toolbar">
            <strong>草稿 #{{ draft.id }}</strong>
            <el-tag size="small">{{ draft.status }}</el-tag>
            <span class="muted" style="font-size: 12px">勾选「纳入」可分段；确认后写入工序开工/完工日</span>
            <div style="flex: 1" />
            <el-button v-if="draft.status === 'draft'" :loading="saving" @click="discardDraft">作废</el-button>
            <el-button
              v-if="draft.status === 'draft'"
              type="primary"
              :loading="saving"
              @click="confirmDraft"
            >
              确认排产
            </el-button>
          </div>
          <el-table :data="draft.lines || []" border stripe size="small" @header-dragend="onHeaderDragend1">
            <el-table-column
              column-key="included"
              label="纳入"
              :width="colWidth1('included', 64)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <el-checkbox
                  :model-value="row.included"
                  :disabled="draft.status !== 'draft'"
                  @change="(v: boolean) => patchLine(row, { included: v })"
                />
              </template>
            </el-table-column>
            <el-table-column prop="order_no" label="生产单" :width="colWidth1('order_no', 110)" resizable />
            <el-table-column prop="product_code" label="产品" :width="colWidth1('product_code', 110)" resizable>
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column prop="process_name" label="工序" :width="colWidth1('process_name', 100)" resizable>
              <template #default="{ row }">
                {{ row.process_name }}
                <el-tag v-if="row.is_first" size="small" type="warning" style="margin-left: 4px">首道</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="plan_qty" label="数量" :width="colWidth1('plan_qty', 72)" align="right" resizable />
            <el-table-column column-key="start_date" label="开工" :width="colWidth1('start_date', 140)" resizable>
              <template #default="{ row }">
                <el-date-picker
                  v-if="draft.status === 'draft'"
                  :model-value="row.start_date"
                  type="date"
                  value-format="YYYY-MM-DD"
                  style="width: 100%"
                  @update:model-value="(v: string) => patchLine(row, { start_date: v })"
                />
                <span v-else>{{ row.start_date || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column column-key="end_date" label="完工" :width="colWidth1('end_date', 140)" resizable>
              <template #default="{ row }">
                <el-date-picker
                  v-if="draft.status === 'draft'"
                  :model-value="row.end_date"
                  type="date"
                  value-format="YYYY-MM-DD"
                  style="width: 100%"
                  @update:model-value="(v: string) => patchLine(row, { end_date: v })"
                />
                <span v-else>{{ row.end_date || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column column-key="kit" label="工序齐套" :min-width="flexColMinWidth1('kit', 90)" resizable>
              <template #default="{ row }">
                <el-tag :type="row.process_kit_ok ? 'success' : 'danger'" size="small" effect="plain">
                  {{ row.process_kit_ok ? '齐' : '缺' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="计划日历" name="calendar">
        <div class="admin-toolbar">
          <el-button @click="shiftMonth(-1)">上一月</el-button>
          <el-button @click="goThisMonth">本月</el-button>
          <el-button @click="shiftMonth(1)">下一月</el-button>
          <strong style="margin-left: 8px">{{ monthLabel }}</strong>
          <div style="flex: 1" />
          <span class="cal-legend">
            <span class="cal-leg holiday">节假日</span>
            <span class="cal-leg off">周末休</span>
            <span class="cal-leg makeup">调休班</span>
          </span>
          <span class="muted" style="font-size: 12px; margin-left: 8px">只读 · 点击工序打开生产单</span>
          <el-button :loading="calLoading" @click="loadCalendar">刷新</el-button>
        </div>

        <div v-loading="calLoading" class="cal-month">
          <div class="cal-dow" v-for="w in WEEKDAY" :key="w">周{{ w }}</div>
          <div
            v-for="day in monthDays"
            :key="day.key"
            class="cal-cell"
            :class="{
              'is-today': day.isToday,
              'is-other': !day.inMonth,
              'is-off': day.isOff,
              'is-holiday': day.isHoliday,
              'is-makeup': day.isMakeup,
            }"
          >
            <div class="cal-cell-head">
              <strong class="cal-date">{{ day.dayNum }}</strong>
              <span v-if="day.label" class="cal-badge" :class="{ holiday: day.isHoliday, makeup: day.isMakeup }">
                {{ day.label }}
              </span>
              <span v-if="day.items.length" class="cal-count">{{ day.items.length }}</span>
            </div>
            <div class="cal-cell-body">
              <button
                v-for="it in day.items.slice(0, 4)"
                :key="`${it.order_process_id}-${day.key}`"
                type="button"
                class="cal-chip"
                :class="{ rush: it.is_rush }"
                :title="`${it.process_name} · ${it.order_no} · ${it.product_code || ''} · ${it.plan_qty}双`"
                @click="openOrder(it.order_id)"
              >
                <span class="cal-chip-name">{{ it.process_name }}</span>
                <span class="cal-chip-meta">{{ it.order_no }}</span>
              </button>
              <div v-if="day.items.length > 4" class="cal-more">+{{ day.items.length - 4 }}</div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const route = useRoute()
const router = useRouter()
const tableRef = ref()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('schedule-pool', tableRef, {
  flexKey: 'customer_name',
})
const { colWidth: colWidth1, flexColMinWidth: flexColMinWidth1, onHeaderDragend: onHeaderDragend1 } =
  useTableColWidths('schedule-draft')

const mainTab = ref('pool')
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)
const calLoading = ref(false)
const pool = ref<any[]>([])
const selectedIds = ref<number[]>([])
const draft = ref<any>(null)
const filters = reactive({
  keyword: '',
  rush_only: false,
  hide_first_kit_blocked: false,
})
const pendingSelectIds = ref<number[]>([])
const monthCursor = ref(startOfMonth(new Date()))
const calByDate = ref<Record<string, any[]>>({})
const calDayMeta = ref<Record<string, any>>({})

const WEEKDAY = ['一', '二', '三', '四', '五', '六', '日']

function pad(n: number) {
  return String(n).padStart(2, '0')
}

function toYmd(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function addMonths(d: Date, n: number) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1)
}

function addDays(d: Date, n: number) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  x.setDate(x.getDate() + n)
  return x
}

/** 月视图网格起点：当月 1 号所在周的周一 */
function monthGridStart(month: Date) {
  const first = startOfMonth(month)
  const day = first.getDay() // 0 Sun
  const diff = day === 0 ? -6 : 1 - day
  return addDays(first, diff)
}

function monthGridEnd(month: Date) {
  return addDays(monthGridStart(month), 41) // 6 周
}

const monthLabel = computed(() => {
  const d = monthCursor.value
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
})

const monthDays = computed(() => {
  const today = toYmd(new Date())
  const y = monthCursor.value.getFullYear()
  const m = monthCursor.value.getMonth()
  const start = monthGridStart(monthCursor.value)
  return Array.from({ length: 42 }, (_, i) => {
    const d = addDays(start, i)
    const key = toYmd(d)
    const meta = calDayMeta.value[key] || {}
    return {
      key,
      dayNum: d.getDate(),
      inMonth: d.getFullYear() === y && d.getMonth() === m,
      isToday: key === today,
      isOff: !!meta.is_off,
      isHoliday: !!meta.is_holiday,
      isMakeup: !!meta.is_makeup_workday,
      label: meta.label || null,
      items: calByDate.value[key] || [],
    }
  })
})

function scheduleLabel(s: string) {
  return (
    ({ none: '未排', drafted: '有草稿', partial: '部分', scheduled: '已排' } as Record<string, string>)[s] ||
    s ||
    '—'
  )
}

function onSelect(rows: any[]) {
  selectedIds.value = rows.map((r) => r.order_id)
}

function applyPendingSelection() {
  const ids = new Set(pendingSelectIds.value)
  if (!ids.size || !tableRef.value) return
  const table = tableRef.value as any
  for (const row of pool.value) {
    if (ids.has(row.order_id)) {
      table.toggleRowSelection?.(row, true)
    }
  }
  pendingSelectIds.value = []
}

async function loadPool() {
  loading.value = true
  try {
    const res: any = await http.get('/schedule/pool', {
      params: {
        keyword: filters.keyword || undefined,
        rush_only: filters.rush_only || undefined,
        hide_first_kit_blocked: filters.hide_first_kit_blocked || undefined,
      },
    })
    pool.value = res.data?.items || []
    void nextTick(() => {
      measureTableHeight()
      applyPendingSelection()
    })
  } finally {
    loading.value = false
  }
}

async function loadCalendar() {
  calLoading.value = true
  try {
    const from = toYmd(monthGridStart(monthCursor.value))
    const to = toYmd(monthGridEnd(monthCursor.value))
    const res: any = await http.get('/schedule/calendar', {
      params: { date_from: from, date_to: to },
    })
    calByDate.value = res.data?.by_date || {}
    calDayMeta.value = res.data?.day_meta || {}
  } catch (e: any) {
    const d = e?.response?.data?.detail
    ElMessage.error(typeof d === 'object' ? d.message || JSON.stringify(d) : d || e?.message || '加载失败')
    calByDate.value = {}
    calDayMeta.value = {}
  } finally {
    calLoading.value = false
  }
}

function shiftMonth(delta: number) {
  monthCursor.value = addMonths(monthCursor.value, delta)
  void loadCalendar()
}

function goThisMonth() {
  monthCursor.value = startOfMonth(new Date())
  void loadCalendar()
}

function onTabChange(name: string | number) {
  if (name === 'calendar') void loadCalendar()
  if (name === 'pool') void nextTick(measureTableHeight)
}

function openOrder(orderId: number) {
  router.push({ path: '/admin/orders', query: { open: String(orderId) } })
}

async function createDraft() {
  creating.value = true
  try {
    const res: any = await http.post('/schedule/drafts', { order_ids: selectedIds.value })
    draft.value = res.data
    ElMessage.success('已生成倒排草稿')
    await loadPool()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '生成失败')
  } finally {
    creating.value = false
  }
}

async function patchLine(row: any, payload: Record<string, unknown>) {
  if (!draft.value || draft.value.status !== 'draft') return
  saving.value = true
  try {
    const res: any = await http.patch(`/schedule/drafts/${draft.value.id}/lines/${row.id}`, payload)
    draft.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '修改失败')
  } finally {
    saving.value = false
  }
}

async function confirmDraft() {
  try {
    await ElMessageBox.confirm(
      '确认后将开工/完工日写入工序计划。不自动派工，请之后在订单里派人。首道缺料会阻断。',
      '确认排产',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const res: any = await http.post(`/schedule/drafts/${draft.value.id}/confirm`, {
      require_first_kit: true,
    })
    draft.value = res.data
    ElMessage.success('已确认排产')
    await loadPool()
    if (mainTab.value === 'calendar') await loadCalendar()
  } catch (e: any) {
    const d = e?.response?.data?.detail
    ElMessage.error(typeof d === 'object' ? d.message || JSON.stringify(d) : d || e?.message || '确认失败')
  } finally {
    saving.value = false
  }
}

async function discardDraft() {
  try {
    await ElMessageBox.confirm('作废当前草稿？', '作废', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    await http.post(`/schedule/drafts/${draft.value.id}/discard`)
    draft.value = null
    ElMessage.success('已作废')
    await loadPool()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '作废失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  const raw = String(route.query.order_ids || '')
  pendingSelectIds.value = raw
    .split(',')
    .map((x) => Number(x.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)
  if (route.query.tab === 'calendar') {
    mainTab.value = 'calendar'
    void loadCalendar()
  }
  void loadPool()
})

watch(
  () => route.query.order_ids,
  (v) => {
    const raw = String(v || '')
    pendingSelectIds.value = raw
      .split(',')
      .map((x) => Number(x.trim()))
      .filter((n) => Number.isFinite(n) && n > 0)
    if (pendingSelectIds.value.length) {
      mainTab.value = 'pool'
      void loadPool()
    }
  },
)
</script>

<style scoped>
.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
:deep(td.mat-image-col) {
  padding: 2px !important;
}
:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}
:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}
:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.muted {
  color: var(--el-text-color-secondary);
}
.cal-legend {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}
.cal-leg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.cal-leg::before {
  content: '';
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.cal-leg.holiday::before {
  background: #fecaca;
  border: 1px solid #f87171;
}
.cal-leg.off::before {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
}
.cal-leg.makeup::before {
  background: #dbeafe;
  border: 1px solid #60a5fa;
}
.cal-month {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 1px;
  background: var(--el-border-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  min-height: 560px;
}
.cal-dow {
  background: #f8fafc;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  text-align: center;
}
.cal-cell {
  background: #fff;
  min-height: 110px;
  display: flex;
  flex-direction: column;
  padding: 6px;
  gap: 4px;
}
.cal-cell.is-other {
  background: #fafafa;
  opacity: 0.55;
}
.cal-cell.is-off {
  background: #f8fafc;
}
.cal-cell.is-holiday {
  background: #fff1f2;
}
.cal-cell.is-makeup {
  background: #eff6ff;
}
.cal-cell.is-today {
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
}
.cal-cell-head {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 20px;
}
.cal-date {
  font-size: 13px;
  color: #0f172a;
}
.cal-cell.is-holiday .cal-date {
  color: #dc2626;
}
.cal-badge {
  font-size: 11px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 3px;
  background: #e2e8f0;
  color: #475569;
}
.cal-badge.holiday {
  background: #fecaca;
  color: #b91c1c;
}
.cal-badge.makeup {
  background: #bfdbfe;
  color: #1d4ed8;
}
.cal-count {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}
.cal-cell-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  overflow: hidden;
}
.cal-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  text-align: left;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 4px;
  padding: 2px 5px;
  cursor: pointer;
  min-width: 0;
  transition: background 0.15s ease;
}
.cal-chip:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}
.cal-chip.rush {
  background: #fff7ed;
  border-color: #fed7aa;
}
.cal-chip-name {
  font-size: 11px;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cal-chip-meta {
  font-size: 10px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.cal-more {
  font-size: 11px;
  color: #64748b;
  padding: 0 2px;
}
@media (max-width: 1100px) {
  .cal-month {
    min-height: 0;
  }
  .cal-cell {
    min-height: 88px;
  }
}
</style>
