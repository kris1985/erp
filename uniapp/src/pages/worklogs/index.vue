<template>
  <app-nav-bar>
    <template #right>
      <view v-if="canPiece" class="worklogs-nav-switch">
        <text :class="{ on: viewMode === 'list' }" @click="switchView('list')">明细</text>
        <text :class="{ on: viewMode === 'summary' }" @click="switchView('summary')">汇总</text>
      </view>
    </template>
  </app-nav-bar>
  <view class="page mobile-list-page">
    <view v-if="!canPiece" class="empty-state">没有报工记录权限</view>
    <template v-else>
      <template v-if="viewMode === 'summary'">
        <view v-if="summaryLoading" class="empty-state">加载中…</view>
        <view v-else-if="summaryError" class="empty-state">
          <text>{{ summaryError }}</text>
          <button class="retry-button" @click="loadSummary">重新加载</button>
        </view>
        <view v-else-if="!summaryDays.length" class="card flow-history-panel">
          <view class="cut-history-empty">暂无汇总数据</view>
        </view>
        <view v-else class="summary-table">
          <view class="summary-table__row is-head">
            <view class="summary-table__cell is-date">日期</view>
            <view
              v-for="col in summaryColumns"
              :key="col.key"
              class="summary-table__cell"
            >{{ col.name }}</view>
          </view>
          <view v-for="row in summaryTableRows" :key="row.date" class="summary-table__row">
            <view class="summary-table__cell is-date">
              <text class="summary-table__num">{{ row.dateLabel }}</text>
            </view>
            <view
              v-for="cell in row.cells"
              :key="cell.key"
              class="summary-table__cell"
            >
              <template v-if="cell.qty != null">
                <text class="summary-table__num">{{ cell.qty }}</text>
                <text>双/</text>
                <text class="summary-table__num">{{ cell.people }}</text>
                <text>人</text>
              </template>
            </view>
          </view>
        </view>
      </template>

      <template v-else>
        <view v-if="loading" class="empty-state">加载中…</view>
        <view v-else-if="errorMessage" class="empty-state">
          <text>{{ errorMessage }}</text>
          <button class="retry-button" @click="load">重新加载</button>
        </view>
        <view v-else-if="!reportOrders.length" class="card flow-history-panel worklogs-detail">
          <view class="cut-history-empty">暂无报工记录</view>
        </view>
        <view v-else class="worklogs-detail">
          <view v-for="order in reportOrders" :key="order.key" class="card flow-history-panel report-day">
            <view class="report-day__head report-order">
              <image
                v-if="order.imageUrl"
                class="report-order__photo"
                :src="displayImageUrl(order.imageUrl)"
                mode="aspectFill"
                @click.stop="previewImage(order.imageUrl)"
              />
              <view v-else class="report-order__photo report-order__photo--empty">款</view>
              <view class="report-order__copy">
                <text class="report-order__no">{{ order.name }}</text>
                <text class="report-order__meta">{{ order.meta }}</text>
              </view>
              <strong>计划 {{ order.planQty }}双</strong>
            </view>
            <view v-for="segment in order.segments" :key="segment.key" class="report-day__seg">
              <view class="report-day__seg-head" @click="toggleSegment(order.key, segment.key)">
                <text>{{ segment.name }}</text>
                <view class="report-day__seg-side">
                  <strong>{{ segment.total }}双</strong>
                  <view class="fold-chevron" :class="{ 'is-open': segmentOpen(order.key, segment.key) }" />
                </view>
              </view>
              <view v-if="segmentOpen(order.key, segment.key)">
                <view v-for="batch in segment.batches" :key="batch.key" class="report-work-day">
                  <view class="report-fold-row report-work-day__head" @click="toggleBatch(order.key, segment.key, batch.key)">
                    <text>{{ batch.timeLabel }}</text>
                    <strong>{{ batch.total }}双</strong>
                    <view class="fold-chevron" :class="{ 'is-open': batchOpen(order.key, segment.key, batch.key) }" />
                  </view>
                  <view v-if="batchOpen(order.key, segment.key, batch.key)">
                    <view v-for="row in batch.rows" :key="row.id" class="cut-history-report">
                      <view>
                        <strong>{{ row.worker_name || '—' }}</strong>
                        <text>{{ row.process_name || '工序' }}</text>
                      </view>
                      <text>{{ rowQty(row) }}</text>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </view>
      </template>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'

type BatchGroup = { key: string; timeLabel: string; latest: string; total: string; rows: any[] }
type SegmentGroup = { key: string; name: string; sort: number; total: string; batches: BatchGroup[] }
type OrderGroup = {
  key: string
  name: string
  latest: string
  planQty: string
  imageUrl: string
  meta: string
  segments: SegmentGroup[]
}
type SummarySegment = {
  segment_key: string
  segment_name: string
  sort?: number
  completed_qty: number
  worker_count: number
}
type SummaryDay = {
  date: string
  label: string
  completed_qty: number
  worker_count: number
  segments: SummarySegment[]
}
type SummaryColumn = { key: string; name: string; sort: number }

const profile = ref(getProfile())
const canPiece = computed(() => (profile.value?.featurePermissions || []).includes('piecework'))
const viewMode = ref<'list' | 'summary'>('list')
const loading = ref(false)
const rows = ref<any[]>([])
const errorMessage = ref('')
const summaryLoading = ref(false)
const summaryError = ref('')
const summaryDays = ref<SummaryDay[]>([])
const openSegments = ref<Record<string, boolean>>({})
const openBatches = ref<Record<string, boolean>>({})

function segmentOpenKey(orderKey: string, segmentKey: string) {
  return `${orderKey}:${segmentKey}`
}

function segmentOpen(orderKey: string, segmentKey: string) {
  return !!openSegments.value[segmentOpenKey(orderKey, segmentKey)]
}

function toggleSegment(orderKey: string, segmentKey: string) {
  const key = segmentOpenKey(orderKey, segmentKey)
  openSegments.value = { ...openSegments.value, [key]: !openSegments.value[key] }
}

function batchOpenKey(orderKey: string, segmentKey: string, batchKey: string) {
  return `${orderKey}:${segmentKey}:${batchKey}`
}

function batchOpen(orderKey: string, segmentKey: string, batchKey: string) {
  return !!openBatches.value[batchOpenKey(orderKey, segmentKey, batchKey)]
}

function toggleBatch(orderKey: string, segmentKey: string, batchKey: string) {
  const key = batchOpenKey(orderKey, segmentKey, batchKey)
  openBatches.value = { ...openBatches.value, [key]: !openBatches.value[key] }
}

function trimReportQty(value: number) {
  return Number(value.toFixed(4)).toString()
}

function formatQty(value: unknown) {
  return trimReportQty(Number(value || 0))
}

/** 汇总表日期：去掉年份前两位，如 26/10/29 */
function formatSummaryDate(value?: string) {
  const parts = String(value || '').split('-')
  if (parts.length !== 3) return value || '—'
  const year = parts[0].length === 4 ? parts[0].slice(2) : parts[0]
  return `${year}/${parts[1]}/${parts[2]}`
}

const summaryColumns = computed<SummaryColumn[]>(() => {
  const map = new Map<string, SummaryColumn>()
  for (const day of summaryDays.value) {
    for (const segment of day.segments || []) {
      const key = String(segment.segment_key || '')
      if (!key || map.has(key)) continue
      map.set(key, {
        key,
        name: segment.segment_name || '未分段',
        sort: Number(segment.sort ?? 999999),
      })
    }
  }
  return [...map.values()].sort(
    (a, b) => a.sort - b.sort || a.name.localeCompare(b.name, 'zh-CN'),
  )
})

const summaryTableRows = computed(() => {
  const columns = summaryColumns.value
  return summaryDays.value.map((day) => {
    const byKey = new Map((day.segments || []).map((segment) => [segment.segment_key, segment]))
    return {
      date: day.date,
      dateLabel: formatSummaryDate(day.date),
      cells: columns.map((col) => {
        const segment = byKey.get(col.key)
        if (!segment) return { key: col.key, qty: null as string | null, people: '' }
        const qty = Number(segment.completed_qty || 0)
        const people = Number(segment.worker_count || 0)
        if (!qty && !people) return { key: col.key, qty: null as string | null, people: '' }
        return { key: col.key, qty: formatQty(qty), people: String(people) }
      }),
    }
  })
})

/**
 * 一次报工唯一标识：
 * - 多道工序批量提交：共用 report_batch_id
 * - 历史批量数据没有批次号时：同生产单、同工序段、同一秒写入的视为一次
 * - 单工序集体拆分：group_id
 * - 个人单工序：记录 id
 */
function reportBatchKey(row: any) {
  if (row.report_batch_id != null && row.report_batch_id !== '') return `b:${row.report_batch_id}`
  const created = String(row.created_at || '').replace('T', ' ').slice(0, 19)
  const segment = segmentKeyOf(row)
  if (created) return `s:${orderKeyOf(row)}:${segment}:${created}`
  if (row.group_id != null && row.group_id !== '') return `g:${row.group_id}`
  return `w:${row.id}`
}

function reportTimeKey(value?: string) {
  return String(value || '').replace('T', ' ').slice(0, 16) || '未记时间'
}

function reportTimeLabel(value?: string) {
  const key = reportTimeKey(value)
  const [datePart, clock] = key.split(' ')
  const [year, month, day] = String(datePart || '').split('-').map(Number)
  if (!year || !month || !day) return key
  const dayText = year === new Date().getFullYear() ? `${month}月${day}日` : `${year}年${month}月${day}日`
  return clock ? `${dayText} ${clock}` : dayText
}

function orderKeyOf(row: any) {
  return String(row.order_no || row.header_no || 'none')
}

function orderNameOf(row: any) {
  return row.order_no || row.header_no || '未关联生产单'
}

function rememberLabel(list: string[], value: unknown) {
  const text = String(value || '').trim()
  if (text && !list.includes(text)) list.push(text)
}

function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}

function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}

function segmentKeyOf(row: any) {
  return String(row.segment_id ?? row.segment_name ?? 'none')
}

function segmentNameOf(row: any) {
  return row.segment_name || '未分段'
}

function segmentSortOf(row: any) {
  return row.segment_id == null ? 999999 : Number(row.segment_sort_order ?? row.segment_id ?? 999999)
}

function qtyOf(row: any) {
  if (row.report_type === 'rework') return Number(row.rework_qty || 0)
  return Number(row.qualified_qty || 0)
}

function rowQty(row: any) {
  const qty = qtyOf(row)
  const defect = Number(row.defect_qty || 0)
  return `${trimReportQty(qty)}双${defect ? ` · 不良${trimReportQty(defect)}` : ''}`
}

/** 报工总数：按工序分别合计后取最大，不把各工序相加。 */
function reportTotal(list: any[]) {
  const byProcess = new Map<string, number>()
  for (const row of list) {
    const key = String(row.process_id ?? row.process_name ?? 'none')
    const qty = qtyOf(row)
    if (!Number.isFinite(qty)) continue
    byProcess.set(key, (byProcess.get(key) || 0) + qty)
  }
  const totals = [...byProcess.values()]
  return totals.length ? Math.max(...totals) : 0
}

const reportOrders = computed<OrderGroup[]>(() => {
  const orders = new Map<string, {
    key: string
    name: string
    latest: string
    planQty: number
    imageUrl: string
    productCodes: string[]
    colorNames: string[]
    segments: Map<string, {
      key: string
      name: string
      sort: number
      batches: Map<string, { key: string; timeLabel: string; latest: string; rows: any[] }>
    }>
  }>()
  const sorted = [...rows.value].sort(
    (a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')) || Number(b.id || 0) - Number(a.id || 0),
  )
  for (const row of sorted) {
    const created = String(row.created_at || '')
    const oKey = orderKeyOf(row)
    let order = orders.get(oKey)
    if (!order) {
      order = {
        key: oKey,
        name: orderNameOf(row),
        latest: '',
        planQty: Number(row.plan_qty || 0),
        imageUrl: '',
        productCodes: [],
        colorNames: [],
        segments: new Map(),
      }
      orders.set(oKey, order)
    }
    if (created > order.latest) order.latest = created
    if (!order.planQty && Number(row.plan_qty || 0)) order.planQty = Number(row.plan_qty || 0)
    const imageUrl = String(row.product_image_url || '').trim()
    if (!order.imageUrl && imageUrl) order.imageUrl = imageUrl
    rememberLabel(order.productCodes, row.product_code)
    rememberLabel(order.colorNames, row.color_name)

    const sKey = segmentKeyOf(row)
    let segment = order.segments.get(sKey)
    if (!segment) {
      segment = {
        key: sKey,
        name: segmentNameOf(row),
        sort: segmentSortOf(row),
        batches: new Map(),
      }
      order.segments.set(sKey, segment)
    }

    const bKey = reportBatchKey(row)
    let batch = segment.batches.get(bKey)
    if (!batch) {
      batch = {
        key: bKey,
        timeLabel: reportTimeLabel(created),
        latest: created,
        rows: [],
      }
      segment.batches.set(bKey, batch)
    }
    if (created > batch.latest) {
      batch.latest = created
      batch.timeLabel = reportTimeLabel(created)
    }
    batch.rows.push(row)
  }

  return [...orders.values()]
    .sort((a, b) => b.latest.localeCompare(a.latest) || a.name.localeCompare(b.name, 'zh-CN'))
    .map((order) => ({
      key: order.key,
      name: order.name,
      latest: order.latest,
      planQty: trimReportQty(order.planQty),
      imageUrl: order.imageUrl,
      meta: [order.productCodes.join('、'), order.colorNames.join('、')].filter(Boolean).join(' · ') || '—',
      segments: [...order.segments.values()]
        .sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name, 'zh-CN'))
        .map((segment) => {
          const segmentRows = [...segment.batches.values()].flatMap((batch) => batch.rows)
          return {
            key: segment.key,
            name: segment.name,
            sort: segment.sort,
            total: trimReportQty(reportTotal(segmentRows)),
            batches: [...segment.batches.values()]
              .sort((a, b) => b.latest.localeCompare(a.latest))
              .map((batch) => ({
                key: batch.key,
                timeLabel: batch.timeLabel,
                latest: batch.latest,
                total: trimReportQty(reportTotal(batch.rows)),
                rows: [...batch.rows].sort(
                  (a, b) => String(a.process_name || '').localeCompare(String(b.process_name || ''), 'zh-CN')
                    || String(a.worker_name || '').localeCompare(String(b.worker_name || ''), 'zh-CN'),
                ),
              })),
          }
        }),
    }))
})

function switchView(mode: 'list' | 'summary') {
  viewMode.value = mode
  if (mode === 'summary') void loadSummary()
  else void load()
}

async function load() {
  profile.value = getProfile()
  if (!canPiece.value) {
    rows.value = []
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data: any = await get('/work-logs', { page_size: 200, exclude_completed: true })
    const items = data?.items ?? data?.data?.items ?? []
    rows.value = Array.isArray(items) ? items : []
    openSegments.value = {}
    openBatches.value = {}
  } catch (error: any) {
    errorMessage.value = error?.message || '报工记录加载失败'
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  profile.value = getProfile()
  if (!canPiece.value) {
    summaryDays.value = []
    summaryLoading.value = false
    return
  }
  summaryLoading.value = true
  summaryError.value = ''
  try {
    const data: any = await get('/work-logs/segment-daily-summary', { days: 30, exclude_completed: true })
    const days = data?.days ?? data?.data?.days ?? []
    summaryDays.value = Array.isArray(days) ? days : []
  } catch (error: any) {
    summaryError.value = error?.message || '汇总加载失败'
  } finally {
    summaryLoading.value = false
  }
}

onShow(() => {
  if (viewMode.value === 'summary') void loadSummary()
  else void load()
})
</script>

<style scoped>
.worklogs-nav-switch {
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 1px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.16);
}
.worklogs-nav-switch text {
  min-width: 32px;
  padding: 1px 6px;
  border-radius: 5px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
  text-align: center;
}
.worklogs-nav-switch text.on {
  background: #fff;
  color: #0e4fa8;
}
.summary-table {
  display: flex;
  flex-direction: column;
  width: 100%;
  overflow: hidden;
  background: #fff;
  border: 2rpx solid #1a1a1a;
}
.summary-table__row {
  display: flex;
  align-items: stretch;
  border-bottom: 2rpx solid #1a1a1a;
}
.summary-table__row:last-child {
  border-bottom: 0;
}
.summary-table__row.is-head {
  background: #f7f7f7;
}
.summary-table__cell {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  min-width: 0;
  min-height: 64rpx;
  padding: 8rpx 4rpx;
  border-right: 2rpx solid #1a1a1a;
  box-sizing: border-box;
  color: #1a1a1a;
  font-size: 22rpx;
  line-height: 1.3;
  text-align: center;
}
.summary-table__cell:last-child {
  border-right: 0;
}
.summary-table__cell.is-date {
  flex: 0 0 120rpx;
  width: 120rpx;
}
.summary-table__row.is-head .summary-table__cell {
  font-weight: 700;
}
.summary-table__num {
  font-weight: 700;
}
.worklogs-detail .report-order {
  align-items: center;
  min-height: 0;
  padding: 14rpx 20rpx 14rpx 16rpx;
}
.worklogs-detail .report-order__photo {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 112rpx;
  height: 112rpx;
  border-radius: 16rpx;
  background: #fff;
}
.worklogs-detail .report-order__photo--empty {
  color: #8aa0bd;
  font-size: 24rpx;
  font-weight: 700;
}
.worklogs-detail .report-order__copy {
  flex: 1;
  min-width: 0;
}
.worklogs-detail .report-order__no {
  display: block;
  overflow: hidden;
  font-size: 30rpx;
  font-weight: 800;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.worklogs-detail .report-order__meta {
  display: block;
  margin-top: 6rpx;
  overflow: hidden;
  color: #3d5f8a;
  font-size: 24rpx;
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.worklogs-detail .report-order > strong {
  flex: none;
  white-space: nowrap;
}
.worklogs-detail .report-day__head strong,
.worklogs-detail .report-day__seg-head strong {
  font-size: 26rpx;
}
.worklogs-detail .report-day__seg-head > text {
  font-size: 28rpx;
}
.worklogs-detail .cut-history-empty {
  font-size: 25rpx;
}
.worklogs-detail .cut-history-report strong {
  font-size: 27rpx;
}
.worklogs-detail .cut-history-report text {
  font-size: 23rpx;
}
.worklogs-detail .cut-history-report > text {
  color: #1a1a1a;
  font-size: 26rpx;
  font-weight: 400;
}
.worklogs-detail .fold-chevron {
  width: 36rpx;
  height: 36rpx;
  flex-basis: 36rpx;
}
.worklogs-detail .fold-chevron::before {
  width: 14rpx;
  height: 14rpx;
}
.report-fold-row {
  display: grid;
  grid-template-columns: 1fr 1fr 48rpx;
  align-items: center;
  column-gap: 8rpx;
}
.report-fold-row > text,
.report-fold-row > strong {
  min-width: 0;
  text-align: center;
}
.report-fold-row > .fold-chevron {
  justify-self: center;
}
.worklogs-detail .report-day__seg-head > text {
  text-align: left;
}
.report-work-day {
  margin: 8rpx 72rpx 10rpx 56rpx;
}
.report-work-day__head {
  min-height: 56rpx;
  margin: 0;
  padding: 0 12rpx;
  border-radius: 12rpx;
  background: #fff6df;
}
.report-work-day__head text {
  color: #8a6a1a;
  font-size: 26rpx;
  font-weight: 700;
}
.report-work-day__head strong {
  color: #a07a28;
  font-size: 24rpx;
  font-weight: 600;
}
.report-work-day__head .fold-chevron::before {
  border-color: #a07a28;
}
.report-work-day .cut-history-report {
  margin-left: 8rpx;
  padding-left: 12rpx;
}
</style>
