<template>
  <view class="page h5-home-page">
    <view class="card h5-clock-strip">
      <view class="h5-clock-strip__body">
        <view class="h5-clock-strip__record">
          <text class="h5-clock-strip__title">打卡</text>
          <text class="h5-clock-strip__link" @click="openPage('/pages/attendance/index')">记录</text>
        </view>
        <view class="h5-clock-strip__main">
          <view v-if="!(today?.slots || []).length" class="h5-clock-strip__times">
            <text class="h5-clock-strip__empty">今天没有排班</text>
          </view>
          <template v-else>
            <view class="h5-clock-strip__times">
              <text v-for="slot in today.slots" :key="slot.id" :class="{ now: slot.id === clockButton.slot_id }">{{ slot.start }}-{{ slot.end }}</text>
            </view>
            <view class="h5-clock-strip__go" :class="{ off: !clockButton.enabled }" @click="punchSlot(clockButton)">{{ punching ? '…' : punchWord }}</view>
          </template>
        </view>
      </view>
      <text v-if="placeHint" class="h5-clock-strip__place" @click="locate">{{ placeHint }}</text>
    </view>
    <view v-if="overview?.mode === 'worker' && overview.month" class="card h5-month" @click="openPage('/pages/salary/index')"><view><text class="h5-month__label">{{ overview.month.is_locked ? '本月工资已锁定' : '本月待核算' }}</text><text class="h5-month__hint">{{ overview.month.is_locked ? '可前往工资页核对确认' : '实际以月结锁定为准' }}</text></view><strong>¥{{ money(overview.month.amount) }}</strong></view>
    <view class="h5-home-cards">
      <view class="card h5-home-card" @click="openPage('/pages/orders/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">生产进度</text><text class="h5-home-card__hint">看交期和工序，点进去可报工、报废</text></view>
        <strong>{{ progressCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view class="card h5-home-card" @click="openPage('/pages/defects/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">报废记录</text><text class="h5-home-card__hint">待主管确认的报废</text></view>
        <strong :class="{ danger: pendingDefectCount > 0 }">{{ pendingDefectCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canPrep" class="card h5-home-card" @click="openPage('/pages/material-prep/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">备料</text><text class="h5-home-card__hint">按生产单备第一段物料，扫码确认领料人</text></view>
        <strong>备</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canIssue" class="card h5-home-card" @click="openPage('/pages/material-pickups/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">领料</text><text class="h5-home-card__hint">从色卡选择，可一次领多种</text></view>
        <strong :class="{ danger: pendingPickupCount > 0 }">{{ pendingPickupCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canAttendance" class="card h5-home-card" @click="openPage('/pages/attendance-rules/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">考勤规则</text><text class="h5-home-card__hint">休息日、上下班、打卡范围</text></view>
        <strong>设置</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canPartners" class="card h5-home-card" @click="openPage('/pages/partners/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">合作商</text><text class="h5-home-card__hint">客户、供应商，点一下就能打电话</text></view>
        <strong>拨打</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canCatalog" class="card h5-home-card" @click="openPage('/pages/supplier-products/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">物料色卡</text><text class="h5-home-card__hint">{{ pendingCatalogCount ? '有色卡待审批' : '查色卡、新增、审批、购买' }}</text></view>
        <strong :class="{ danger: pendingCatalogCount > 0 }">{{ pendingCatalogCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canExpense" class="card h5-home-card" @click="openPage('/pages/expenses/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">报销</text><text class="h5-home-card__hint">提交后待财务付款</text></view>
        <strong :class="{ danger: expenseCount > 0 }">{{ expenseCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view class="card h5-home-card" @click="openPage('/pages/worklogs/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">计件</text><text class="h5-home-card__hint">今天的计件记录</text></view>
        <strong>{{ overview?.today?.record_count ?? 0 }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view class="card h5-home-card" @click="openPage('/pages/salary/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">工资</text><text class="h5-home-card__hint">{{ overview?.month?.is_locked ? '本月工资已锁定' : '本月预估与结算' }}</text></view>
        <strong>{{ overview?.month ? `¥${money(overview.month.amount)}` : '—' }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
    </view>
    <MobileTabBar active="home" />
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import MobileTabBar from '../../components/MobileTabBar.vue'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'
const profile = ref(getProfile()), overview = ref<any>(null), today = ref<any>(null)
const punching = ref(false)
const locating = ref(false)
const locationError = ref('')
const here = ref<{ latitude: number; longitude: number } | null>(null)
const defects = ref<any[]>([]), pendingPickupCount = ref(0), expenseCount = ref(0), pendingCatalogCount = ref(0), progressCount = ref(0)
const canIssue = computed(() => (profile.value?.featurePermissions || []).includes('material_issue'))
const canPrep = computed(() => (profile.value?.featurePermissions || []).includes('material_prep'))
const canAttendance = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('attendance_rules') || features.includes('attendance_rules_write')
})
const canPartners = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('partners') || features.includes('partners_write')
})
const canCatalog = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('supplier_products') || features.includes('supplier_products_write') || features.includes('supplier_products_approve')
})
const canExpense = computed(() => (profile.value?.featurePermissions || []).includes('expense') || (profile.value?.permissions || []).includes('menu.daily_expenses') || profile.value?.role === 'admin')
const pendingDefectCount = computed(() => defects.value.filter(row => row.needs_my_confirm).length)
const distanceMeters = computed(() => {
  const site = today.value?.clock_site
  if (!site?.configured || !here.value) return null
  const radius = 6371000
  const p1 = here.value.latitude * Math.PI / 180
  const p2 = Number(site.latitude) * Math.PI / 180
  const dPhi = (Number(site.latitude) - here.value.latitude) * Math.PI / 180
  const dLng = (Number(site.longitude) - here.value.longitude) * Math.PI / 180
  const chord = Math.sin(dPhi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dLng / 2) ** 2
  return 2 * radius * Math.asin(Math.sqrt(chord))
})
const inRange = computed(() => {
  const site = today.value?.clock_site
  return !!site?.configured && distanceMeters.value != null && distanceMeters.value <= Number(site.radius_meters || 300)
})
const placeText = computed(() => {
  const site = today.value?.clock_site
  if (!site) return '正在读取打卡地点…'
  if (!site.configured) return '工厂还没设置打卡地点'
  if (locating.value) return '正在定位…'
  if (locationError.value) return locationError.value
  if (distanceMeters.value == null) return '点这里获取定位'
  const away = distanceMeters.value < 1000 ? `${Math.round(distanceMeters.value)} 米` : `${(distanceMeters.value / 1000).toFixed(1)} 公里`
  return inRange.value ? `距离厂区 ${away}，可以打卡` : `距离厂区 ${away}，超出 ${site.radius_meters} 米`
})
const money = (v: unknown) => Number(v || 0).toFixed(2)
const clockButton = computed(() => {
  const slots = today.value?.slots || []
  const next = today.value?.next_action
  if (next) return { ...next, enabled: true }
  for (const slot of slots) {
    for (const action of [slot.on_action, slot.off_action]) {
      if (!action || action.label === '已打卡' || action.label === '—') continue
      return { ...action, enabled: false }
    }
  }
  return { enabled: false, label: '已完成', reason: '今天的班次都已打卡', slot_id: '', punch_type: '' }
})
const punchWord = computed(() => {
  const action = clockButton.value
  if (action?.punch_type === 'on_duty') return '上班'
  if (action?.punch_type === 'off_duty') return '下班'
  return '完成'
})
const placeHint = computed(() => (!today.value || inRange.value ? '' : placeText.value))
function openPage(url: string) { uni.navigateTo({ url }) }
function locate() {
  if (!today.value?.clock_site?.configured) return
  locating.value = true
  locationError.value = ''
  uni.getLocation({
    type: 'wgs84',
    isHighAccuracy: true,
    success: (res) => {
      here.value = { latitude: Number(res.latitude), longitude: Number(res.longitude) }
      locating.value = false
    },
    fail: () => {
      here.value = null
      locating.value = false
      locationError.value = '定位失败，请允许使用位置后再点这里'
    },
  })
}
async function loadToday() {
  try {
    today.value = await get('/attendance/today')
    if (today.value?.clock_site?.configured && !here.value) locate()
  } catch (error: any) {
    uni.showToast({ title: error?.message || '打卡状态加载失败', icon: 'none' })
  }
}
async function punchSlot(action: any) {
  if (!action || punching.value) return
  if (!action.enabled) {
    uni.showToast({ title: action.reason || '现在不能打这个卡', icon: 'none' })
    return
  }
  if (!inRange.value) {
    uni.showToast({ title: placeText.value, icon: 'none' })
    return
  }
  punching.value = true
  try {
    today.value = await post('/attendance/clock', {
      punch_type: action.punch_type,
      slot_id: action.slot_id,
      latitude: here.value?.latitude,
      longitude: here.value?.longitude,
    })
    uni.showToast({ title: '已打卡', icon: 'success' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '打卡失败', icon: 'none' })
    await loadToday()
  } finally {
    punching.value = false
  }
}
async function loadProgress() {
  try {
    const result: any = await get('/executions/mobile', { status: 'active', page: 1, page_size: 1 })
    progressCount.value = Number(result?.total || 0)
  } catch { progressCount.value = 0 }
}
async function loadDefects() {
  try {
    const result: any = await get('/defect-events', { page_size: 50 })
    defects.value = result?.items || []
  } catch { defects.value = [] }
}
async function loadPickups() {
  if (!canIssue.value) {
    pendingPickupCount.value = 0
    return
  }
  try {
    const result: any = await get('/misc-material-pickups', { page_size: 1 })
    pendingPickupCount.value = Number(result?.pending_count || 0)
  } catch { pendingPickupCount.value = 0 }
}
async function loadCatalog() {
  if (!canCatalog.value) {
    pendingCatalogCount.value = 0
    return
  }
  try {
    const result: any = await get('/supplier-products', { approval_status: 'pending', page: 1, page_size: 1 })
    pendingCatalogCount.value = Number(result?.total || 0)
  } catch { pendingCatalogCount.value = 0 }
}
async function loadExpenses() {
  if (!canExpense.value) {
    expenseCount.value = 0
    return
  }
  try {
    const result: any = await get('/daily-expenses', { status: 'pending' })
    expenseCount.value = Number(result?.summary?.count || 0)
  } catch { expenseCount.value = 0 }
}
async function load() {
  profile.value = getProfile()
  try { overview.value = await get('/home/overview') }
  catch (e: any) { uni.showToast({ title: e?.message || '首页加载失败', icon: 'none' }) }
  await loadToday()
  await loadProgress()
  await loadDefects()
  await loadPickups()
  await loadCatalog()
  await loadExpenses()
}
onShow(load)
</script>
<style scoped>
.h5-clock-strip { margin-bottom: 14rpx; padding: 16rpx 16rpx 14rpx 0; }
.h5-clock-strip__body { display: flex; align-items: stretch; }
.h5-clock-strip__record { display: flex; flex: none; flex-direction: column; align-items: center; justify-content: center; width: 96rpx; border-right: 1rpx solid #e0e2ed; }
.h5-clock-strip__title { color: #181b23; font-size: 28rpx; font-weight: 750; line-height: 1.2; }
.h5-clock-strip__link { margin-top: 4rpx; color: #0057c2; font-size: 22rpx; font-weight: 650; line-height: 1.2; }
.h5-clock-strip__main { display: flex; flex: 1; flex-direction: column; gap: 12rpx; min-width: 0; padding-left: 12rpx; }
.h5-clock-strip__times { display: flex; align-items: center; min-width: 0; min-height: 36rpx; }
.h5-clock-strip__times text { flex: 1; min-width: 0; overflow: hidden; color: #414755; font-size: 24rpx; font-variant-numeric: tabular-nums; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.h5-clock-strip__times text.now { color: #0057c2; font-weight: 750; }
.h5-clock-strip__times .h5-clock-strip__empty { flex: none; color: #727786; font-size: 24rpx; }
.h5-clock-strip__go { display: flex; align-items: center; justify-content: center; height: 68rpx; border-radius: 12rpx; background: #0057c2; color: #fff; font-size: 30rpx; font-weight: 750; }
.h5-clock-strip__go.off { background: #e0e2ed; color: #727786; }
.h5-clock-strip__place { display: block; padding: 10rpx 8rpx 0 108rpx; overflow: hidden; color: #727786; font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
</style>
