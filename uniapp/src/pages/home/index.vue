<template>
  <view class="page h5-home-page">
    <view class="h5-home-hero"><text class="h5-kicker">铁玉兰管家</text><text class="h5-greeting">{{ greeting }}，{{ firstName }}</text><text class="h5-date">{{ dateLabel }}</text></view>
    <view v-if="overview" class="h5-today">
      <view class="h5-today__head"><view><text class="h5-today__eyebrow">{{ overview.mode === 'leader' ? overview.team_name || '我的班组' : '今日计件' }}</text><text class="h5-today__title">{{ overview.mode === 'leader' ? '今日班组' : '今天完成了多少' }}</text></view><text class="h5-today__status">▤ {{ overview.today?.record_count || 0 }} 条</text></view>
      <view class="h5-today__metrics"><view><strong>{{ overview.today?.qualified || 0 }}</strong><text>合格</text></view><view><strong :class="{ danger: Number(overview.today?.defects || 0) > 0 }">{{ overview.today?.defects || 0 }}</strong><text>不良</text></view><view><strong>{{ overview.mode === 'leader' ? overview.today?.reporter_count || 0 : overview.today?.record_count || 0 }}</strong><text>{{ overview.mode === 'leader' ? '已报工' : '记录' }}</text></view></view>
    </view>
    <view v-if="overview?.mode === 'worker' && overview.month" class="card h5-month"><view><text class="h5-month__label">{{ overview.month.is_locked ? '本月工资已锁定' : '本月待核算' }}</text><text class="h5-month__hint">{{ overview.month.is_locked ? '可前往工资页核对确认' : '实际以月结锁定为准' }}</text></view><strong>¥{{ money(overview.month.amount) }}</strong></view>
    <view v-if="isManagerial" class="mobile-entry-grid">
      <view class="card mobile-entry" @click="goWorkbench"><text class="mobile-entry__icon">▦</text><view><strong>主管工作台</strong><text>待办、物料和现场指标</text></view><text>›</text></view>
      <view class="card mobile-entry" @click="goOrders"><text class="mobile-entry__icon">≡</text><view><strong>生产进度</strong><text>交期、齐套和工序进度</text></view><text>›</text></view>
    </view>
    <view class="h5-section-head"><text>最近计件</text><text class="h5-link" @click="goLogs">查看全部</text></view>
    <view v-if="loading" class="h5-home-empty">加载中…</view><view v-else-if="!overview?.recent?.length" class="h5-home-empty">今天还没有计件记录</view>
    <view v-else><view v-for="row in overview.recent" :key="row.id" class="card h5-recent-row"><view><text class="h5-recent-title">{{ overview.mode === 'leader' ? `${row.worker_name} · ` : '' }}{{ row.process_name }}</text><text class="h5-recent-meta">{{ typeLabel(row.report_type) }} · {{ formatTime(row.created_at) }}</text></view><strong>{{ row.qty }}</strong></view></view>
    <MobileTabBar active="home" />
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import MobileTabBar from '../../components/MobileTabBar.vue'
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'
const profile = ref(getProfile()), overview = ref<any>(null), loading = ref(false)
const isManagerial = computed(() => ['admin', 'manager', 'leader', 'warehouse'].includes(profile.value?.role || ''))
const firstName = computed(() => String(profile.value?.displayName || '同事').trim().slice(0, 6))
const greeting = computed(() => { const h = new Date().getHours(); return h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好' })
const dateLabel = computed(() => { const d = new Date(); return `${d.getMonth() + 1}月${d.getDate()}日 · 周${['日','一','二','三','四','五','六'][d.getDay()]}` })
const money = (v: unknown) => Number(v || 0).toFixed(2)
const typeLabel = (v?: string) => ({ normal: '正常', group: '集体', rework: '返修', supplement: '补数', tail: '尾数' } as any)[v || ''] || '计件'
const formatTime = (v?: string) => { const m = String(v || '').match(/T(\d{2}):(\d{2})/); return m ? `${m[1]}:${m[2]}` : '刚刚' }
const goLogs = () => uni.redirectTo({ url: '/pages/worklogs/index' })
const goWorkbench = () => uni.navigateTo({ url: '/pages/workbench/index' })
const goOrders = () => uni.navigateTo({ url: '/pages/orders/index' })
async function load() { loading.value = true; try { overview.value = await get('/home/overview') } catch (e: any) { uni.showToast({ title: e?.message || '首页加载失败', icon: 'none' }) } finally { loading.value = false } }
onShow(load)
</script>
