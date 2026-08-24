<template>
  <view class="page">
    <view class="month-row">
      <text>工资月份</text>
      <picker mode="date" fields="month" :value="month" @change="changeMonth">
        <text class="month-picker">{{ month.replace('-', '年') }}月 ›</text>
      </picker>
    </view>
    <view v-if="loading" class="empty-state">加载中…</view>
    <template v-else-if="salary">
      <view class="salary-card">
        <text class="salary-label">{{ salary.is_locked ? '应发合计' : '本月预估' }}</text>
        <text class="salary-amount">¥{{ money(salary.total_wage ?? salary.total_piece_wage) }}</text>
        <text class="salary-state">{{ salary.is_locked ? '已月结' : '待核算，实际以月结为准' }}</text>
      </view>
      <view class="salary-grid">
        <view class="card salary-summary"><text>底薪</text><strong>¥{{ money(salary.base_salary) }}</strong></view>
        <view class="card salary-summary"><text>计件金额</text><strong>¥{{ money(salary.payable_piece_wage ?? salary.total_piece_wage) }}</strong></view>
      </view>
      <view class="salary-detail-head"><view><text class="section-title">计件明细</text><text>{{ (salary.details || []).length }} 条</text></view><text @click="goWorklogs">查看全部记录</text></view>
      <view v-if="!groupedDetails.length" class="empty-state salary-empty">暂无明细</view>
      <view v-for="group in groupedDetails" :key="group.key" class="salary-day">
        <view class="salary-day__head"><text>{{ group.label }}</text><text>当日金额 ¥{{ money(group.amount) }}</text></view>
        <view v-for="row in group.items" :key="row.work_log_id" class="card record-card salary-day__entry">
          <view class="record-head"><text class="record-title">{{ row.order_no }} · {{ row.process_name }}</text><text class="salary-line-amount">¥{{ money(row.amount) }}</text></view>
          <text class="record-meta">{{ detailType(row.report_type) }} · {{ detailQuantity(row) }} · 单价 ¥{{ money(row.unit_price) }}</text>
        </view>
      </view>
    </template>
    <view v-else class="empty-state">暂无工资数据</view>
    <MobileTabBar active="salary" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'
import MobileTabBar from '../../components/MobileTabBar.vue'

const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const salary = ref<any>(null)
const loading = ref(false)
const money = (value: unknown) => Number(value || 0).toFixed(2)
const groupedDetails = computed(() => {
  const groups = new Map<string, { key: string; label: string; amount: number; items: any[] }>()
  const details = [...(salary.value?.details || [])].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  for (const row of details) {
    const key = String(row.created_at || '').slice(0, 10) || 'unknown'
    const group = groups.get(key) || { key, label: formatDay(row.created_at), amount: 0, items: [] }
    group.items.push(row)
    group.amount += Number(row.amount || 0)
    groups.set(key, group)
  }
  return [...groups.values()]
})
const detailType = (value: string) => ({ normal: '正常', rework: '返修', group: '集体', supplement: '补数', tail: '尾数' } as any)[value] || value
const detailQuantity = (row: any) => row.report_type === 'rework' ? `返修 ${row.rework_qty || 0}` : `合格 ${row.qualified_qty || 0}`
function formatDay(value?: string) {
  const raw = String(value || '').slice(0, 10)
  const parts = raw.split('-')
  if (parts.length !== 3) return raw || '日期未知'
  const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
  const nowDate = new Date()
  const yesterday = new Date(nowDate.getFullYear(), nowDate.getMonth(), nowDate.getDate() - 1)
  const prefix = date.toDateString() === nowDate.toDateString() ? '今天 · ' : date.toDateString() === yesterday.toDateString() ? '昨天 · ' : ''
  return `${prefix}${Number(parts[1])}月${Number(parts[2])}日`
}
function goWorklogs() { uni.redirectTo({ url: '/pages/worklogs/index' }) }

async function load() {
  const workerId = getProfile()?.id
  if (!workerId) return
  loading.value = true
  try {
    salary.value = await get(`/salary/${workerId}`, { year_month: month.value })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '工资加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function changeMonth(event: any) {
  month.value = event.detail.value
  void load()
}

onShow(load)
</script>
