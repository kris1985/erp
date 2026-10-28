<template>
  <view class="page bench-page">
    <view class="home-nav">
      <text>铁玉兰管家</text>
    </view>
    <view class="mast">
      <view>
        <text class="mast__hello">{{ hello }}</text>
        <text class="mast__name">{{ who }}</text>
        <text v-if="tenantName" class="mast__tenant">{{ tenantName }}</text>
      </view>
      <view class="home-avatar" @click="openPage('/pages/mine/index')">
        <text>{{ avatarText }}</text>
      </view>
    </view>

    <!-- 打卡是每天进厂的第一件事，做成裁断台上的圆形按钮 -->
    <view class="bench">
      <view class="bench__top">
        <text>今日班次</text>
        <text class="bench__record" @click="openPage('/pages/attendance/index')">记录</text>
      </view>
      <view v-if="todayLoading && !today" class="bench__times">
        <text class="bench__empty">正在读取班次…</text>
      </view>
      <view v-else-if="!(today?.slots || []).length" class="bench__times">
        <text class="bench__empty">今天没有排班</text>
      </view>
      <view v-else class="bench__times">
        <text v-for="slot in today.slots" :key="slot.id" :class="{ now: slot.id === clockButton.slot_id }">{{ slot.start }}–{{ slot.end }}</text>
      </view>
      <view v-if="showPunch" class="bench__punch" :class="{ off: !clockButton.enabled }" @click="punchSlot(clockButton)">
        <text>{{ punching ? '…' : punchWord }}</text>
      </view>
      <text v-if="today?.clock_site" class="bench__place" :class="{ far: distanceMeters != null && !inRange }" @click="locate">{{ placeText }}</text>
    </view>

    <view class="apps">
      <view v-for="tile in apps" :key="tile.key" class="app" hover-class="tile--on" @tap="openPage(tile.url)">
        <view class="app__icon">
          <image class="app__mark" :src="tile.icon" mode="aspectFit" />
          <text v-if="tile.badge" class="app__badge">{{ tile.badge }}</text>
        </view>
        <text class="app__label">{{ tile.label }}</text>
      </view>
    </view>

    <view class="home-scan" hover-class="tile--on" @click="startScan">
      <image src="/static/icons/qrcode.svg" mode="aspectFit" />
    </view>
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onHide, onPullDownRefresh, onShow, onUnload } from '@dcloudio/uni-app'
import { syncProfile } from '../../services/auth'
import { get, post } from '../../services/http'
import { currentLocation } from '../../services/locate'
import { appPageForTarget, parseScanText } from '../../services/scanner'
import { getProfile, getToken } from '../../services/storage'
type HomeTile = { key: string; label: string; icon: string; url: string; badge?: string }
const profile = ref(getProfile()), overview = ref<any>(null), today = ref<any>(null)
const todayLoading = ref(true)
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
const canLeaves = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('leaves') || features.includes('leaves_write')
})
const canPartners = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('partners') || features.includes('partners_write')
})
const canWarehouse = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('shared_materials') || features.includes('shared_materials_write')
})
const canPurchase = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('purchase_orders') || features.includes('purchase_orders_write')
})
const canCutUsage = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('cut_material_usage') || features.includes('cut_material_usage_write')
})
const canOwnProducts = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('own_products') || features.includes('own_products_write') || features.includes('own_products_approve')
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
  return inRange.value ? `距打卡位置 ${away}` : `距打卡位置 ${away}，超出 ${site.radius_meters} 米`
})
const clockButton = computed(() => {
  const slots = today.value?.slots || []
  const next = today.value?.next_action
  if (next) return { ...next, enabled: true }
  const pending: any[] = []
  for (const slot of slots) {
    for (const action of [slot.on_action, slot.off_action]) {
      if (!action || action.label === '已打卡' || action.label === '—') continue
      pending.push(action)
    }
  }
  // 还没到的时段优先；都过了就提示刚刚错过的那段，而不是早上那段。
  const upcoming = pending.find(action => String(action.label || '').endsWith('后'))
  const missed = [...pending].reverse().find(action => action.label === '已过时间')
  const action = upcoming || missed || pending[0]
  if (action) return { ...action, enabled: Boolean(action.enabled) }
  return { enabled: false, label: '已完成', reason: '今天的班次都已打卡', slot_id: '', punch_type: '' }
})
const punchWord = computed(() => {
  const action = clockButton.value
  if (action?.punch_type === 'on_duty') return '上班'
  if (action?.punch_type === 'off_duty') return '下班'
  return '完成'
})
const hello = computed(() => {
  const hour = new Date().getHours()
  if (hour < 11) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
const who = computed(() => profile.value?.displayName || '同事')
const tenantName = computed(() => profile.value?.tenantName || '')
const avatarText = computed(() => who.value.trim().slice(0, 1) || '我')
const apps = computed(() => {
  const tiles: HomeTile[] = [
    { key: 'orders', label: '生产进度', icon: '/static/icons/home-progress.svg', url: '/pages/orders/index', badge: progressCount.value ? String(progressCount.value) : '' },
    { key: 'defects', label: '报废记录', icon: '/static/icons/home-scrap.svg', url: '/pages/defects/index', badge: pendingDefectCount.value ? String(pendingDefectCount.value) : '' },
    { key: 'piece', label: '计件', icon: '/static/icons/home-piece.svg', url: '/pages/worklogs/index', badge: overview.value?.today?.record_count ? String(overview.value.today.record_count) : '' },
  ]
  if (canIssue.value) tiles.push({ key: 'issue', label: '领料', icon: '/static/icons/home-issue.svg', url: '/pages/material-pickups/index', badge: pendingPickupCount.value ? String(pendingPickupCount.value) : '' })
  if (canPrep.value) tiles.push({ key: 'prep', label: '备料', icon: '/static/icons/home-prep.svg', url: '/pages/material-prep/index' })
  if (canWarehouse.value) tiles.push({ key: 'warehouse', label: '物料仓', icon: '/static/icons/home-warehouse.svg', url: '/pages/warehouse/index' })
  if (canPurchase.value) tiles.push({ key: 'purchase', label: '物料采购', icon: '/static/icons/home-purchase.svg', url: '/pages/purchase/index' })
  if (canCutUsage.value) tiles.push({ key: 'cut', label: '裁断用料', icon: '/static/icons/home-cut.svg', url: '/pages/cut-usage/index' })
  if (canOwnProducts.value) tiles.push({ key: 'product', label: '产品开发', icon: '/static/icons/home-product.svg', url: '/pages/own-products/index' })
  if (canCatalog.value) tiles.push({ key: 'catalog', label: '物料色卡', icon: '/static/icons/home-swatch.svg', url: '/pages/supplier-products/index', badge: pendingCatalogCount.value ? String(pendingCatalogCount.value) : '' })
  if (canExpense.value) tiles.push({ key: 'expense', label: '报销', icon: '/static/icons/home-receipt.svg', url: '/pages/expenses/index', badge: expenseCount.value ? String(expenseCount.value) : '' })
  if (canPartners.value) tiles.push({ key: 'partners', label: '合作商', icon: '/static/icons/home-partners.svg', url: '/pages/partners/index' })
  if (canAttendance.value) tiles.push({ key: 'rules', label: '考勤规则', icon: '/static/icons/home-clock.svg', url: '/pages/attendance-rules/index' })
  if (canLeaves.value) tiles.push({ key: 'leaves', label: '请假登记', icon: '/static/icons/home-clock.svg', url: '/pages/leaves/index' })
  tiles.push({ key: 'salary', label: '工资', icon: '/static/icons/home-wage.svg', url: '/pages/salary/index' })
  return tiles
})
const showPunch = computed(() => Boolean(today.value && ((today.value.slots || []).length || today.value.next_action)))
function openPage(url: string) { uni.navigateTo({ url }) }
let scanning = false
function startScan() {
  if (scanning) return
  scanning = true
  uni.scanCode({
    scanType: ['qrCode', 'barCode'],
    autoDecodeCharset: true,
    success: (result) => {
      const target = parseScanText(result.result)
      if (target) uni.navigateTo({ url: appPageForTarget(target) })
      else uni.showToast({ title: '无法识别该二维码', icon: 'none' })
    },
    fail: (error) => {
      if (!String(error.errMsg || '').includes('cancel')) uni.showToast({ title: '扫码失败，请检查相机权限', icon: 'none' })
    },
    complete: () => { scanning = false },
  })
}
function locate() {
  if (!today.value?.clock_site?.configured) return Promise.resolve()
  locating.value = true
  locationError.value = ''
  return currentLocation()
    .then((point) => {
      here.value = point
    })
    .catch((error: any) => {
      here.value = null
      locationError.value = error?.message || '定位失败，请允许使用位置后再点这里'
    })
    .finally(() => {
      locating.value = false
    })
}
async function loadToday() {
  const ticket = ++todayTicket
  if (!today.value) todayLoading.value = true
  try {
    const data = await get('/attendance/today')
    if (ticket !== todayTicket) return
    today.value = data
    if (data?.clock_site?.configured && !here.value) locate()
  } catch (error: any) {
    if (ticket !== todayTicket) return
    if (getToken()) uni.showToast({ title: error?.message || '打卡状态加载失败', icon: 'none' })
  } finally {
    if (ticket === todayTicket) todayLoading.value = false
  }
}
async function punchSlot(action: any) {
  if (!action || punching.value) return
  if (!action.enabled) {
    uni.showToast({ title: action.reason || '现在不能打这个卡', icon: 'none' })
    return
  }
  if (!inRange.value) {
    if (!here.value) await locate()
    if (!inRange.value) {
      uni.showToast({ title: placeText.value, icon: 'none' })
      return
    }
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
let loadTicket = 0
let todayTicket = 0
async function load() {
  const ticket = ++loadTicket
  if (!getToken()) {
    uni.reLaunch({ url: '/pages/login/index' })
    return
  }
  profile.value = getProfile()
  // 班次和账号信息一起读。不要等首页其它接口，否则中途被下一次 onShow 打断时，加载提示会一直停着。
  const todayTask = loadToday()
  try {
    const me: any = await get('/auth/me')
    if (ticket !== loadTicket) return
    syncProfile(me)
    profile.value = getProfile()
    if (profile.value?.mustChangePassword) {
      uni.reLaunch({ url: '/pages/change-password/index' })
      return
    }
  } catch {
    if (!getToken() || ticket !== loadTicket) return
  }
  try { overview.value = await get('/home/overview') }
  catch (e: any) {
    if (getToken()) uni.showToast({ title: e?.message || '首页加载失败', icon: 'none' })
  }
  if (ticket !== loadTicket || !getToken()) return
  await todayTask
  if (ticket !== loadTicket) return
  if (homeVisible) setStatusBarHidden(true)
  await loadProgress()
  await loadDefects()
  await loadPickups()
  await loadCatalog()
  await loadExpenses()
}
let homeVisible = false
let statusBarHidden = false
let ignoreStatusBarHide = false
let statusBarTimer: ReturnType<typeof setTimeout> | undefined
function setStatusBarHidden(hidden: boolean) {
  // 安装包里才能藏系统信号、时间、电量。小程序和浏览器不允许改状态栏。
  // 已经是目标状态就不要再设，否则全屏切换会反复触发 onHide/onShow，把班次请求冲掉。
  // #ifdef APP-PLUS
  if (statusBarHidden === hidden) return
  statusBarHidden = hidden
  ignoreStatusBarHide = true
  try {
    plus.navigator.setFullscreen(hidden)
  } catch {
    ignoreStatusBarHide = false
  }
  setTimeout(() => { ignoreStatusBarHide = false }, 500)
  // #endif
}
onShow(() => {
  homeVisible = true
  if (statusBarTimer) {
    clearTimeout(statusBarTimer)
    statusBarTimer = undefined
  }
  // 先读班次，再藏状态栏。藏状态栏和请求放在一起时，安装包会丢掉这次回调，刷新才看得到。
  void load()
})
onHide(() => {
  if (ignoreStatusBarHide) return
  homeVisible = false
  // 藏状态栏时页面会先闪一次 onHide。确认不是马上又显示回来，再恢复状态栏。
  statusBarTimer = setTimeout(() => {
    if (!homeVisible) setStatusBarHidden(false)
  }, 400)
})
onUnload(() => {
  homeVisible = false
  if (statusBarTimer) clearTimeout(statusBarTimer)
  setStatusBarHidden(false)
})
onPullDownRefresh(async () => {
  try { await load() }
  finally { uni.stopPullDownRefresh() }
})
</script>
<style scoped lang="scss">
.bench-page { padding-bottom: calc(168rpx + env(safe-area-inset-bottom)); background: #f2f5f9; }
.home-scan { position: fixed; z-index: 30; left: 50%; bottom: calc(28rpx + env(safe-area-inset-bottom)); display: flex; align-items: center; justify-content: center; width: 112rpx; height: 112rpx; margin-left: -56rpx; border-radius: 50%; background: #102e72; box-shadow: 0 14rpx 32rpx rgba(16, 46, 114, 0.28); }
.home-scan image { width: 52rpx; height: 52rpx; }
.home-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 64rpx;
  margin: -16rpx -32rpx 0;
  padding-top: var(--status-bar-height);
  box-sizing: content-box;
  background: #f2f5f9;
}
.home-nav text {
  color: #132033;
  font-size: 34rpx;
  font-weight: 750;
  line-height: 64rpx;
}
.mast { display: flex; align-items: center; justify-content: space-between; gap: 24rpx; margin: 12rpx 4rpx 28rpx; }
.mast__hello, .mast__name, .mast__tenant { display: block; }
.mast__hello { color: #667386; font-size: 24rpx; }
.mast__name { margin-top: 4rpx; color: #132033; font-size: 44rpx; font-weight: 750; line-height: 1.15; }
.mast__tenant { margin-top: 8rpx; color: #667386; font-size: 24rpx; }
.home-avatar { display: flex; flex: 0 0 88rpx; align-items: center; justify-content: center; width: 88rpx; height: 88rpx; border-radius: 50%; background: #102e72; }
.home-avatar text { color: #f4f7fc; font-size: 36rpx; font-weight: 750; line-height: 1; }
.bench { margin-bottom: 8rpx; padding: 28rpx 28rpx 32rpx; border-radius: 36rpx; background: linear-gradient(145deg, #0049a3, #0a78ff); box-shadow: 0 16rpx 36rpx rgba(0, 87, 194, 0.22); }
.bench__top, .bench__times { display: flex; align-items: center; }
.bench__top { justify-content: space-between; color: rgba(255, 255, 255, 0.72); font-size: 22rpx; }
.bench__record { color: #fff; font-size: 24rpx; font-weight: 700; }
.bench__times { flex-wrap: wrap; gap: 8rpx 16rpx; min-height: 44rpx; margin-top: 18rpx; padding-bottom: 22rpx; border-bottom: 1rpx dashed rgba(255, 255, 255, 0.35); }
.bench__times text { flex: none; color: rgba(255, 255, 255, 0.72); font-size: 26rpx; font-variant-numeric: tabular-nums; text-align: center; white-space: nowrap; }
.bench__times text.now { color: #fff; font-weight: 750; }
.bench__empty { flex: none !important; color: rgba(255, 255, 255, 0.72) !important; text-align: left !important; }
.bench__punch { display: flex; align-items: center; justify-content: center; width: 148rpx; height: 148rpx; margin: 28rpx auto 0; border-radius: 50%; background: #fff; box-shadow: 0 12rpx 28rpx rgba(0, 40, 110, 0.18); }
.bench__punch text { color: #173f9a; font-size: 34rpx; font-weight: 750; }
.bench__punch.off { background: rgba(255, 255, 255, 0.12); box-shadow: none; }
.bench__punch.off text { color: rgba(255, 255, 255, 0.55); }
.bench__place { display: block; margin-top: 18rpx; color: rgba(255, 255, 255, 0.92); font-size: 24rpx; line-height: 1.4; text-align: center; }
.bench__place.far { color: #ffe08a; }
.apps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 36rpx 8rpx; margin-top: 32rpx; }
.app { display: flex; flex-direction: column; align-items: center; }
.app__icon { position: relative; display: flex; align-items: center; justify-content: center; width: 96rpx; height: 96rpx; border-radius: 28rpx; background: linear-gradient(160deg, #2f6ad8 0%, #1847ae 100%); box-shadow: 0 10rpx 18rpx rgba(18, 54, 122, 0.16); }
.app__mark { width: 54rpx; height: 54rpx; pointer-events: none; }
.app__badge { position: absolute; top: -8rpx; right: -10rpx; min-width: 32rpx; padding: 0 8rpx; border-radius: 999rpx; background: #c53636; color: #fff; font-size: 20rpx; font-weight: 700; line-height: 32rpx; text-align: center; }
.app__label { margin-top: 12rpx; color: #132033; font-size: 28rpx; font-weight: 650; line-height: 1.2; text-align: center; }
</style>
<style>
.tile--on { opacity: 0.72; }
</style>
