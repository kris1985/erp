<template>
  <view class="page h5-prog" :class="{ 'h5-prog--sub': mode === 'detail' }">
    <template v-if="mode === 'list'">
      <view class="card h5-prog-search">
        <input :value="keyword" confirm-type="search" placeholder="搜生产单号、客户、型号" @input="onKeyword" @confirm="reload" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>
      <scroll-view class="h5-prog-tabs" scroll-x :show-scrollbar="false">
        <text v-for="item in statuses" :key="item.value" :class="{ on: status === item.value }" @click="selectStatus(item.value)">{{ item.label }}</text>
      </scroll-view>

      <view v-if="loading && !rows.length" class="h5-prog-empty">正在加载生产进度…</view>
      <view v-else-if="!rows.length" class="h5-prog-empty">{{ keyword ? '没有匹配的生产单' : '没有生产单' }}</view>
      <view v-for="row in rows" :key="row.id" class="card h5-prog-card" @click="openFlow(row)">
        <view class="h5-prog-card__row">
          <image v-if="row.product_image_url" class="h5-prog-thumb" :src="displayImageUrl(row.product_image_url)" mode="aspectFill" />
          <view v-else class="h5-prog-thumb h5-prog-thumb--empty">款</view>
          <view class="h5-prog-card__main">
            <view class="h5-prog-card__top">
              <strong>{{ row.header_no }}</strong>
              <view class="h5-prog-card__badges">
                <text v-if="row.warehouse_status" :class="['h5-chip', warehouseClass(row.warehouse_status)]">{{ row.warehouse_status }}</text>
                <text :class="['h5-prog-status', `is-${row.status}`]">{{ statusLabel(row.status) }}</text>
              </view>
            </view>
            <text class="h5-prog-meta">{{ row.customer_name }}</text>
            <text class="h5-prog-meta">{{ row.product_code || '—' }}<text v-if="row.color_name"> · {{ row.color_name }}</text></text>
            <view v-if="row.is_rush || showRiskLabel(row)" class="h5-prog-tags">
              <text v-if="row.is_rush" class="h5-chip h5-chip--bad">急单</text>
              <text v-if="showRiskLabel(row)" class="h5-chip h5-chip--warn">{{ row.risk_label }}</text>
            </view>
          </view>
        </view>
        <view class="h5-prog-stats">
          <view><text>数量</text><strong>{{ row.total_qty || 0 }}</strong></view>
          <view><text>已出货</text><strong>{{ row.shipped_qty || 0 }}</strong></view>
          <view><text>交货日期</text><strong>{{ dateText(row.delivery_date) }}</strong></view>
          <view><text>预计交货日期</text><strong>{{ dateText(row.projected_finish) }}</strong></view>
        </view>
        <view class="h5-prog-segs">
          <view v-for="(segment, index) in segmentBars(row)" :key="`${row.id}-${segment.id}-${index}`" class="h5-prog-seg" :class="{ current: segment.current, done: segment.doneAll }">
            <text class="h5-prog-seg__name">{{ segment.name }}</text>
            <view class="h5-prog-seg__meter">
              <text class="h5-prog-seg__done">{{ pairText(segment.done) }}</text>
              <view class="h5-prog-seg__track"><view :style="{ width: `${segment.percent}%` }" /></view>
              <text class="h5-prog-seg__plan">{{ pairText(segment.plan) }}</text>
            </view>
          </view>
          <text v-if="!segmentBars(row).length" class="h5-prog-seg__empty">还没有工序段</text>
        </view>
      </view>
      <view v-if="rows.length" class="h5-prog-more">{{ finished ? `共 ${total} 单` : loadingMore ? '加载中…' : '上拉加载更多' }}</view>
    </template>

    <template v-else-if="current">
      <view class="card h5-prog-hero">
        <view class="h5-prog-card__row">
          <image v-if="current.product_image_url" :src="displayImageUrl(current.product_image_url)" mode="aspectFill" @click="previewImage(current.product_image_url)" />
          <view v-else class="h5-prog-hero__empty">款</view>
          <view class="h5-prog-hero__copy">
            <view class="h5-prog-card__top">
              <strong>{{ current.header_no }}</strong>
              <view class="h5-prog-card__badges">
                <text v-if="current.warehouse_status" :class="['h5-chip', warehouseClass(current.warehouse_status)]">{{ current.warehouse_status }}</text>
                <text :class="['h5-prog-status', `is-${current.status}`]">{{ statusLabel(current.status) }}</text>
              </view>
            </view>
            <text>{{ current.customer_name }}</text>
            <text>{{ current.product_code || '—' }}<text v-if="current.color_name"> · {{ current.color_name }}</text></text>
          </view>
        </view>
        <view class="h5-prog-stats">
          <view><text>数量</text><strong>{{ current.total_qty || 0 }}</strong></view>
          <view><text>已出货</text><strong>{{ current.shipped_qty || 0 }}</strong></view>
          <view><text>交货日期</text><strong>{{ dateText(current.delivery_date) }}</strong></view>
          <view><text>预计交货日期</text><strong>{{ dateText(current.projected_finish) }}</strong></view>
        </view>
      </view>

      <text class="h5-prog-section">工序段</text>
      <view v-if="!segments.length" class="h5-prog-empty">还没有工序</view>
      <view v-for="(segment, segmentIndex) in segments" :key="`${segment.name}-${segmentIndex}`" class="card h5-prog-segment" :class="{ current: segment.current, done: segment.doneAll }">
        <view class="h5-prog-segment__head">
          <strong>{{ segment.name }}</strong>
          <text>{{ pairText(segment.done) }}/{{ pairText(segment.plan) }}</text>
        </view>
        <view class="h5-prog-seg__track h5-prog-seg__track--wide"><view :style="{ width: `${segment.percent}%` }" /></view>
        <view v-for="(row, index) in segment.rows" :key="`${segment.name}-${index}`" class="h5-prog-step" :class="{ current: row.is_current, done: row.is_done }">
          <view>
            <strong>{{ row.label }}</strong>
            <text v-if="row.is_current">进行中</text>
          </view>
          <text>{{ pairText(row.completed_qty) }}/{{ pairText(row.plan_qty) }}</text>
        </view>
      </view>

      <text class="h5-prog-section">去办理</text>
      <view class="card h5-prog-links">
        <view v-for="item in links" :key="item.action" class="h5-prog-link" @click="openAction(item.action)">
          <view><strong>{{ item.title }}</strong><text>{{ item.hint }}</text></view>
          <text class="h5-prog-link__go">›</text>
        </view>
      </view>
    </template>
    <view v-else class="h5-prog-empty">正在加载生产进度…</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onBackPress, onLoad, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { appPageForTarget, encodeTarget } from '../../services/scanner'
import { getProfile } from '../../services/storage'

const statuses = [
  { value: 'active', label: '未完成' },
  { value: 'confirmed', label: '待生产' },
  { value: 'production', label: '生产中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
  { value: 'all', label: '全部' },
]
const statusText: Record<string, string> = {
  draft: '草稿',
  confirmed: '待生产',
  cut: '生产中',
  in_progress: '生产中',
  completed: '已完成',
  cancelled: '已取消',
}

const profile = ref(getProfile())
const mode = ref<'list' | 'detail'>('list')
const openedFromLink = ref(false)
const status = ref('active')
const keyword = ref('')
const rows = ref<any[]>([])
const current = ref<any>(null)
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const finished = ref(false)
let listSeq = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null

function countsOnRoute(proc: any) {
  const routeIds = new Set((proc?.route_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean))
  if (proc?.route_department_shared || !routeIds.size) return true
  const assigned = (proc?.assigned_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean)
  if (!assigned.length) return true
  return assigned.some((id: number) => routeIds.has(id))
}
function bottleneck(procs: any[]) {
  const effective = procs.filter(row => Number(row?.plan_qty || 0) > 0)
  if (!effective.length) return null
  const plan = Math.max(...effective.map(row => Math.max(0, Number(row.plan_qty || 0))))
  if (!plan) return null
  const rate = Math.min(...effective.map(row => {
    const itemPlan = Number(row.plan_qty || 0)
    const completed = Math.max(0, Number(row.completed_qty || 0))
    return Math.min(1, completed / itemPlan)
  }))
  return { plan, done: Math.round((Math.min(plan, plan * rate) + Number.EPSILON) * 100) / 100 }
}
function segmentBars(row: any) {
  const build = (filterRoute: boolean) => {
    const groups: { id: string; name: string; rows: any[] }[] = []
    for (const proc of row?.processes || []) {
      if (filterRoute && !countsOnRoute(proc)) continue
      const id = String(proc.segment_id ?? 'unlabeled')
      const name = proc.segment_name || '未分段'
      const last = groups[groups.length - 1]
      if (!last || last.id !== id) groups.push({ id, name, rows: [proc] })
      else last.rows.push(proc)
    }
    return groups.map(group => {
      const stage = bottleneck(group.rows)
      const plan = stage?.plan || 0
      const done = stage?.done || 0
      return {
        ...group,
        plan,
        done,
        percent: plan ? Math.min(100, Math.round(done / plan * 100)) : 0,
        current: group.rows.some(item => item.is_current),
        doneAll: plan > 0 && done >= plan,
      }
    })
  }
  const filtered = build(true)
  return filtered.length ? filtered : build(false)
}
const segments = computed(() => segmentBars(current.value))
const links = computed(() => {
  const features = profile.value?.featurePermissions || []
  const items = [
    { action: 'report', title: '报工', hint: '登记本次合格产量' },
    { action: 'defect', title: '报废', hint: '登记报废数量' },
  ]
  if (features.includes('material_issue')) items.push({ action: 'issue', title: '领料', hint: '提交本段领料' })
  if (features.includes('subcontract_out')) items.push({ action: 'subcontract', title: '外发', hint: '创建外发加工单' })
  return items
})

function showRiskLabel(row: any) {
  const label = String(row?.risk_label || '')
  return !!label && label !== '必延期'
}
function warehouseClass(value: string) {
  if (value === '齐套') return 'h5-chip--ok'
  if (value === '待买') return 'h5-chip--warn'
  return 'h5-chip--bad'
}
function statusLabel(value: string) {
  return statusText[value] || value || '—'
}
function dateText(value?: string) {
  const text = String(value || '').slice(0, 10)
  if (!text) return '未定'
  const parts = text.split('-')
  if (parts.length < 3) return text
  return `${Number(parts[1])}月${Number(parts[2])}日`
}
function pairText(value: unknown) {
  const number = Number(value || 0)
  return Number.isInteger(number) ? String(number) : String(Math.round(number * 10) / 10)
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
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}

async function loadList(reset = false) {
  if (!reset && (loading.value || loadingMore.value || finished.value)) return
  const seq = ++listSeq
  if (reset) {
    page.value = 1
    finished.value = false
    loading.value = true
  } else {
    loadingMore.value = true
    page.value += 1
  }
  try {
    const query: Record<string, unknown> = { status: status.value, page: page.value, page_size: 20 }
    const q = keyword.value.trim()
    if (q) query.q = q
    const result: any = await get('/executions/mobile', query)
    if (seq !== listSeq) return
    const items = result?.items || []
    rows.value = reset ? items : rows.value.concat(items)
    total.value = Number(result?.total || 0)
    finished.value = rows.value.length >= total.value || items.length < 20
  } catch (error: any) {
    if (!reset) page.value = Math.max(1, page.value - 1)
    toast(error?.message || '生产进度加载失败')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
    }
    uni.stopPullDownRefresh()
  }
}
function reload() {
  loadList(true)
}
function selectStatus(value: string) {
  if (status.value === value) return
  status.value = value
  rows.value = []
  loadList(true)
}
function onKeyword(event: any) {
  keyword.value = String(event?.detail?.value || '')
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadList(true), 300)
}
function clearKeyword() {
  keyword.value = ''
  loadList(true)
}
function openDetail(row: any) {
  current.value = row
  mode.value = 'detail'
  uni.setNavigationBarTitle({ title: row.header_no || '生产进度' })
}
function openFlow(row: any) {
  uni.navigateTo({
    url: appPageForTarget({
      kind: 'flow-card',
      code: String(row.id),
      h5Path: `/flow-card/${row.id}`,
      label: '生产流转卡',
    }),
  })
}
async function loadLinkedDetail(headerId: number) {
  try {
    const result: any = await get('/executions/mobile', { header_id: headerId, status: 'all', page: 1, page_size: 1 })
    const row = (result?.items || [])[0]
    if (!row) {
      toast('生产单不存在')
      uni.navigateBack()
      return
    }
    openDetail(row)
  } catch (error: any) {
    toast(error?.message || '生产进度加载失败')
    uni.navigateBack()
  }
}
function openAction(action: string) {
  if (!current.value?.id) return
  const target = encodeTarget({
    kind: 'flow-card',
    code: String(current.value.id),
    h5Path: `/flow-card/${current.value.id}`,
    label: '生产流转卡',
  })
  uni.navigateTo({ url: `/pages/report/index?target=${target}&action=${action}` })
}

onBackPress(() => {
  if (openedFromLink.value || mode.value !== 'detail') return false
  mode.value = 'list'
  uni.setNavigationBarTitle({ title: '生产进度' })
  return true
})
onPullDownRefresh(() => {
  if (mode.value !== 'list') {
    uni.stopPullDownRefresh()
    return
  }
  loadList(true)
})
onReachBottom(() => {
  if (mode.value === 'list') loadList(false)
})
onLoad((query) => {
  const headerId = Number(query?.header_id || 0)
  if (!headerId) return
  openedFromLink.value = true
  mode.value = 'detail'
  loadLinkedDetail(headerId)
})
onShow(() => {
  profile.value = getProfile()
  if (mode.value === 'list') loadList(true)
})
</script>

<style scoped>
.h5-prog--sub { padding-bottom: 48rpx; }
.h5-prog-empty,
.h5-prog-more { padding: 36rpx 0 48rpx; color: #727786; font-size: 24rpx; text-align: center; }
.h5-prog-search { display: flex; align-items: center; gap: 16rpx; margin-bottom: 18rpx; padding: 6rpx 8rpx 6rpx 28rpx; }
.h5-prog-search input { flex: 1; height: 76rpx; color: #181b23; font-size: 28rpx; }
.h5-prog-search text { padding-right: 16rpx; color: #0057c2; font-size: 26rpx; }
.h5-prog-tabs { width: 100%; margin-bottom: 18rpx; white-space: nowrap; }
.h5-prog-tabs text { display: inline-flex; align-items: center; height: 56rpx; margin-right: 12rpx; padding: 0 22rpx; border-radius: 999rpx; background: #fff; color: #414755; font-size: 24rpx; }
.h5-prog-tabs text.on { background: #0057c2; color: #fff; font-weight: 700; }
.h5-prog-card,
.h5-prog-hero { margin-bottom: 18rpx; padding: 22rpx 22rpx 18rpx; }
.h5-prog-card__row { display: flex; gap: 18rpx; }
.h5-prog-thumb,
.h5-prog-hero image,
.h5-prog-hero__empty { flex: none; width: 120rpx; height: 120rpx; border-radius: 22rpx; background: #f5f7fa; }
.h5-prog-thumb--empty,
.h5-prog-hero__empty { display: flex; align-items: center; justify-content: center; color: #727786; font-size: 28rpx; font-weight: 750; }
.h5-prog-card__main,
.h5-prog-hero__copy { flex: 1; min-width: 0; }
.h5-prog-card__top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-prog-card__badges { display: flex; flex: none; align-items: center; gap: 8rpx; }
.h5-prog-card__top strong,
.h5-prog-hero__copy strong { overflow: hidden; color: #181b23; font-size: 28rpx; font-weight: 750; letter-spacing: 0.4rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-status { flex: none; padding: 4rpx 12rpx; border-radius: 999rpx; background: rgba(0, 87, 194, 0.1); color: #0057c2; font-size: 20rpx; font-weight: 700; }
.h5-prog-status.is-completed { background: rgba(38, 109, 0, 0.1); color: #266d00; }
.h5-prog-status.is-cancelled { background: #e0e2ed; color: #727786; }
.h5-prog-meta { display: block; margin-top: 6rpx; overflow: hidden; color: #414755; font-size: 24rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-hero__copy { display: flex; flex-direction: column; align-items: flex-start; }
.h5-prog-hero__copy .h5-prog-card__top { align-self: stretch; width: 100%; }
.h5-prog-hero__copy > text { margin-top: 6rpx; color: #414755; font-size: 24rpx; }
.h5-prog-tags { display: flex; flex-wrap: wrap; gap: 8rpx; margin-top: 12rpx; }
.h5-chip { padding: 2rpx 12rpx; border-radius: 999rpx; font-size: 20rpx; font-weight: 700; line-height: 1.6; }
.h5-chip--ok { background: rgba(38, 109, 0, 0.1); color: #266d00; }
.h5-chip--warn { background: rgba(125, 84, 0, 0.1); color: #7d5400; }
.h5-chip--bad { background: rgba(186, 26, 26, 0.1); color: #ba1a1a; }
.h5-prog-stats { display: flex; margin-top: 18rpx; padding-top: 16rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-stats view { flex: 1; min-width: 0; }
.h5-prog-stats view + view { padding-left: 16rpx; border-left: 1rpx solid #e0e2ed; }
.h5-prog-stats text { display: block; color: #727786; font-size: 20rpx; }
.h5-prog-stats strong { display: block; margin-top: 4rpx; overflow: hidden; color: #181b23; font-size: 26rpx; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-segs { display: flex; gap: 10rpx; width: 100%; margin-top: 16rpx; }
.h5-prog-seg { display: flex; flex: 1; align-items: center; justify-content: center; gap: 6rpx; min-width: 0; padding: 18rpx 8rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-prog-seg.current { background: rgba(0, 87, 194, 0.08); }
.h5-prog-seg.done { background: rgba(38, 109, 0, 0.08); }
.h5-prog-seg__name { color: #414755; font-size: 22rpx; font-weight: 650; line-height: 1.15; letter-spacing: 2rpx; writing-mode: vertical-rl; text-orientation: upright; }
.h5-prog-seg.current .h5-prog-seg__name,
.h5-prog-seg.current .h5-prog-seg__done,
.h5-prog-seg.current .h5-prog-seg__plan { color: #0057c2; }
.h5-prog-seg.done .h5-prog-seg__name,
.h5-prog-seg.done .h5-prog-seg__done,
.h5-prog-seg.done .h5-prog-seg__plan { color: #266d00; }
.h5-prog-seg__meter { display: flex; flex: 1; flex-direction: column; align-items: center; min-width: 0; }
.h5-prog-seg__done,
.h5-prog-seg__plan { color: #181b23; font-size: 30rpx; font-weight: 750; line-height: 1.1; }
.h5-prog-seg__track { width: 100%; height: 4rpx; margin: 8rpx 0; overflow: hidden; border-radius: 999rpx; background: #e0e2ed; }
.h5-prog-seg__track view { height: 100%; border-radius: inherit; background: #8eb6e8; }
.h5-prog-seg.current .h5-prog-seg__track view { background: #0057c2; }
.h5-prog-seg.done .h5-prog-seg__track view,
.h5-prog-segment.done .h5-prog-seg__track view { background: #266d00; }
.h5-prog-seg__track--wide { width: auto; height: 8rpx; margin: 0 0 8rpx; background: #e0e2ed; }
.h5-prog-segment.current .h5-prog-seg__track view { background: #0057c2; }
.h5-prog-seg__empty { color: #727786; font-size: 22rpx; }
.h5-prog-section { display: block; margin: 10rpx 8rpx 12rpx; color: #727786; font-size: 22rpx; font-weight: 700; letter-spacing: 2rpx; }
.h5-prog-segment { margin-bottom: 14rpx; padding: 8rpx 22rpx 12rpx; border-left: 8rpx solid #e0e2ed; }
.h5-prog-links { margin-bottom: 14rpx; padding: 4rpx 22rpx; }
.h5-prog-segment.current { border-left-color: #0057c2; }
.h5-prog-segment.done { border-left-color: #266d00; }
.h5-prog-segment__head,
.h5-prog-step,
.h5-prog-link { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-prog-segment__head { min-height: 68rpx; }
.h5-prog-segment__head strong { color: #181b23; font-size: 28rpx; }
.h5-prog-segment__head text { color: #414755; font-size: 24rpx; font-weight: 650; }
.h5-prog-step { min-height: 76rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-step view { display: flex; flex-direction: column; }
.h5-prog-step strong { color: #181b23; font-size: 26rpx; font-weight: 650; }
.h5-prog-step view text,
.h5-prog-step > text,
.h5-prog-link text { color: #727786; font-size: 22rpx; }
.h5-prog-step.current strong,
.h5-prog-step.current > text { color: #0057c2; }
.h5-prog-step.done strong { color: #266d00; }
.h5-prog-link { min-height: 96rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-link:first-child { border-top: 0; }
.h5-prog-link strong { display: block; color: #181b23; font-size: 30rpx; }
.h5-prog-link__go { color: #0057c2; font-size: 36rpx; }
</style>
