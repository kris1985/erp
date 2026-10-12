<template>
  <view class="page h5-home-page">
    <view class="h5-home-hero"><text class="h5-kicker">铁玉兰管家</text><text class="h5-greeting">{{ greeting }}，{{ firstName }}</text><text class="h5-date">{{ dateLabel }}</text></view>
    <view v-if="overview?.mode === 'worker' && overview.month" class="card h5-month" @click="openPage('/pages/salary/index')"><view><text class="h5-month__label">{{ overview.month.is_locked ? '本月工资已锁定' : '本月待核算' }}</text><text class="h5-month__hint">{{ overview.month.is_locked ? '可前往工资页核对确认' : '实际以月结锁定为准' }}</text></view><strong>¥{{ money(overview.month.amount) }}</strong></view>
    <view class="h5-home-cards">
      <view class="card h5-home-card" @click="openPage('/pages/tasks/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">任务</text><text class="h5-home-card__hint">已领取的生产任务</text></view>
        <strong>{{ tasks.length }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view class="card h5-home-card" @click="openPage('/pages/defects/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">报废记录</text><text class="h5-home-card__hint">待主管确认的报废</text></view>
        <strong :class="{ danger: pendingDefectCount > 0 }">{{ pendingDefectCount }}</strong>
        <text class="h5-home-card__go">›</text>
      </view>
      <view v-if="canIssue" class="card h5-home-card" @click="openPage('/pages/material-pickups/index')">
        <view class="h5-home-card__main"><text class="h5-home-card__label">领料</text><text class="h5-home-card__hint">从色卡选择，可一次领多种</text></view>
        <strong :class="{ danger: pendingPickupCount > 0 }">{{ pendingPickupCount }}</strong>
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
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'
const profile = ref(getProfile()), overview = ref<any>(null)
const defects = ref<any[]>([]), pendingPickupCount = ref(0), expenseCount = ref(0)
const canIssue = computed(() => (profile.value?.featurePermissions || []).includes('material_issue'))
const canExpense = computed(() => (profile.value?.featurePermissions || []).includes('expense') || (profile.value?.permissions || []).includes('menu.daily_expenses') || profile.value?.role === 'admin')
const firstName = computed(() => String(profile.value?.displayName || '同事').trim().slice(0, 6))
const greeting = computed(() => { const h = new Date().getHours(); return h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好' })
const dateLabel = computed(() => { const d = new Date(); return `${d.getMonth() + 1}月${d.getDate()}日 · 周${['日','一','二','三','四','五','六'][d.getDay()]}` })
const tasks = computed(() => overview.value?.tasks || [])
const pendingDefectCount = computed(() => defects.value.filter(row => row.needs_my_confirm).length)
const money = (v: unknown) => Number(v || 0).toFixed(2)
function openPage(url: string) { uni.navigateTo({ url }) }
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
  await loadDefects()
  await loadPickups()
  await loadExpenses()
}
onShow(load)
</script>
