<template>
  <view class="page h5-home-page">
    <view class="h5-home-hero"><text class="h5-kicker">铁玉兰管家</text><text class="h5-greeting">{{ greeting }}，{{ firstName }}</text><text class="h5-date">{{ dateLabel }}</text></view>
    <view v-if="overview?.mode === 'worker' && overview.month" class="card h5-month"><view><text class="h5-month__label">{{ overview.month.is_locked ? '本月工资已锁定' : '本月待核算' }}</text><text class="h5-month__hint">{{ overview.month.is_locked ? '可前往工资页核对确认' : '实际以月结锁定为准' }}</text></view><strong>¥{{ money(overview.month.amount) }}</strong></view>
    <view class="h5-home-tabs">
      <view :class="['h5-home-tab', { active: activeTab === 'tasks' }]" @click="activeTab = 'tasks'"><text>任务</text><text v-if="tasks.length" class="h5-home-tab__count">{{ tasks.length }}</text></view>
      <view :class="['h5-home-tab', { active: activeTab === 'defects' }]" @click="activeTab = 'defects'"><text>报废记录</text><text v-if="pendingDefectCount" class="h5-home-tab__count h5-home-tab__count--alert">{{ pendingDefectCount }}</text></view>
    </view>
    <template v-if="activeTab === 'tasks'">
      <view v-if="loading" class="h5-home-empty">加载中…</view>
      <view v-else-if="!tasks.length" class="h5-home-empty">暂无已领取任务，扫码后可领取</view>
      <view v-else>
      <view v-for="(row, index) in tasks" :key="`${row.header_id}-${row.segment_id}`" class="card h5-task-row" @click="openTask(row)">
        <view class="h5-task-main">
          <text class="h5-task-index">{{ index + 1 }}</text>
          <view class="h5-task-body">
            <view class="h5-task-top">
              <strong>{{ row.header_no }}</strong>
              <text class="h5-task-chip">{{ row.task_name }}</text>
            </view>
            <view class="h5-task-info">
              <view><text>工厂型号</text><strong>{{ row.product_code || '—' }}</strong></view>
              <view><text>颜色</text><strong>{{ row.color_name || '—' }}</strong></view>
              <view><text>交期</text><strong>{{ formatDate(row.delivery_date) }}</strong></view>
            </view>
            <view class="h5-task-tags">
              <text class="h5-task-tag">数量 {{ row.qty || 0 }} 双</text>
              <text class="h5-task-tag h5-task-tag--done">完工 {{ row.completed_qty || 0 }} 双</text>
            </view>
          </view>
        </view>
      </view>
      </view>
    </template>
    <template v-else>
      <view v-if="defectsLoading" class="h5-home-empty">加载中…</view>
      <view v-else-if="!defects.length" class="h5-home-empty">暂无报废记录</view>
      <view v-else class="h5-defect-list">
        <view v-for="row in defects" :key="row.id" class="card h5-defect-row">
          <view class="h5-defect-head">
            <view><strong>{{ row.order_no || '未关联生产单' }}</strong><text>{{ formatTime(row.created_at) }}</text></view>
            <text :class="['h5-defect-status', { confirmed: row.status === 'closed', pending: row.needs_my_confirm }]">{{ defectStatusText(row) }}</text>
          </view>
          <view class="h5-defect-content">
            <view class="h5-defect-visual">
              <image v-if="row.product_image_url" class="h5-defect-photo" :src="displayImageUrl(row.product_image_url)" mode="aspectFill" @click="previewDefectPhotos([row.product_image_url])" />
              <view v-else class="h5-defect-photo h5-defect-photo--empty">暂无图片</view>
              <image
                v-if="row.photo_urls?.length"
                class="h5-defect-scene"
                :src="displayImageUrl(row.photo_urls[0])"
                mode="aspectFill"
                @click.stop="previewDefectPhotos(row.photo_urls)"
              />
            </view>
            <view class="h5-defect-detail">
              <view class="h5-defect-product"><text>工厂型号</text><strong>{{ row.product_code || '—' }}</strong></view>
              <view class="h5-defect-meta"><text>{{ row.brand_name || '未填品牌' }}</text><text>{{ row.found_process_name || '未填发现工序' }}</text></view>
              <view class="h5-defect-size"><strong>{{ row.size_value || '—' }}码</strong><text>左脚 {{ row.left_qty || 0 }}</text><text>右脚 {{ row.right_qty || 0 }}</text><text>共 {{ row.qty || 0 }}</text></view>
              <view class="h5-defect-loss"><text>损失</text><strong>¥{{ money(row.loss_amount) }}</strong><text v-if="responsibilityText(row)">{{ responsibilityText(row) }}</text></view>
            </view>
          </view>
          <view class="h5-defect-foot">
            <text>登记人：{{ row.found_by_worker_name || row.found_by_user_name || '—' }}</text>
            <button v-if="canConfirmDefects && row.needs_my_confirm" :loading="confirmingId === row.id" @click.stop="confirmDefect(row)">主管确认</button>
          </view>
        </view>
      </view>
    </template>
    <MobileTabBar active="home" />
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import MobileTabBar from '../../components/MobileTabBar.vue'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'
import { appPageForTarget } from '../../services/scanner'
const profile = ref(getProfile()), overview = ref<any>(null), loading = ref(false)
const activeTab = ref<'tasks' | 'defects'>('tasks')
const defects = ref<any[]>([]), defectsLoading = ref(false), confirmingId = ref<number | null>(null)
const canConfirmDefects = computed(() => ['admin', 'manager', 'leader'].includes(profile.value?.role || '') || Boolean(profile.value?.isLeader))
const firstName = computed(() => String(profile.value?.displayName || '同事').trim().slice(0, 6))
const greeting = computed(() => { const h = new Date().getHours(); return h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好' })
const dateLabel = computed(() => { const d = new Date(); return `${d.getMonth() + 1}月${d.getDate()}日 · 周${['日','一','二','三','四','五','六'][d.getDay()]}` })
const tasks = computed(() => overview.value?.tasks || [])
const pendingDefectCount = computed(() => defects.value.filter(row => row.needs_my_confirm).length)
const money = (v: unknown) => Number(v || 0).toFixed(2)
function defectStatusText(row: any) {
  if (row.status === 'closed') return '已确认'
  if (row.needs_my_confirm) return '待主管确认'
  return '已登记'
}
const formatDate = (v?: string) => {
  const raw = String(v || '').trim()
  if (!raw) return '—'
  return raw.slice(0, 10)
}
const formatTime = (v?: string) => {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 16).replace('T', ' ')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewDefectPhotos(urls: string[]) {
  const resolved = (urls || []).map(displayImageUrl).filter(Boolean)
  if (resolved.length) uni.previewImage({ urls: resolved, current: resolved[0] })
}
function responsibilityText(row: any) {
  const workers = (row.responsibilities || []).map((item: any) => `${item.worker_name || '员工'} ¥${money(item.deduction_amount)}`)
  const employeeAmount = (row.responsibilities || []).reduce((sum: number, item: any) => sum + Number(item.deduction_amount || 0), 0)
  const companyAmount = Math.max(0, Number(row.loss_amount || 0) - employeeAmount)
  return [`公司 ¥${money(companyAmount)}`, ...workers].join(' · ')
}
function openTask(row: any) {
  const segment = row.segment_code === 'stitch' || row.segment_code === 'forming' || row.segment_code === 'cut' ? row.segment_code : 'cut'
  uni.navigateTo({
    url: appPageForTarget({
      kind: 'flow-card',
      code: String(row.header_id),
      h5Path: `/flow-card/${row.header_id}`,
      label: '生产流转卡',
      segmentCode: segment,
    }),
  })
}
async function loadDefects() {
  defectsLoading.value = true
  try {
    const result: any = await get('/defect-events', { page_size: 50 })
    defects.value = result?.items || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '报废记录加载失败', icon: 'none' })
  } finally { defectsLoading.value = false }
}
function confirmDefect(row: any) {
  uni.showModal({
    title: '确认报废',
    content: `确认 ${row.order_no || ''} ${row.size_value || ''}码，共${row.qty || 0}只报废？确认后将按已登记金额计入损失。`,
    success: async result => {
      if (!result.confirm) return
      confirmingId.value = row.id
      try {
        await post(`/defect-events/${row.id}/supervisor-confirm`, {})
        uni.showToast({ title: '已确认', icon: 'success' })
        await loadDefects()
      } catch (e: any) {
        uni.showToast({ title: e?.message || '确认失败', icon: 'none' })
      } finally { confirmingId.value = null }
    },
  })
}
async function load() {
  loading.value = true
  profile.value = getProfile()
  try { overview.value = await get('/home/overview') }
  catch (e: any) { uni.showToast({ title: e?.message || '首页加载失败', icon: 'none' }) }
  finally { loading.value = false }
  await loadDefects()
}
onShow(load)
</script>
