<template>
  <app-nav-bar />
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
        <text class="salary-label">本月合计</text>
        <text class="salary-amount">¥{{ money(monthWage) }}</text>
      </view>
      <view v-if="summaryItems.length" class="salary-grid">
        <view
          v-for="item in summaryItems"
          :key="item.key"
          class="card salary-summary"
          :class="{ 'is-deduct': item.deduct }"
        >
          <text>{{ item.label }}</text>
          <strong>{{ item.value }}</strong>
        </view>
      </view>
      <view class="salary-detail-head"><view><text class="section-title">计件明细</text><text>{{ (salary.details || []).length }} 条</text></view></view>
      <view v-if="!groupedDetails.length" class="empty-state salary-empty">暂无明细</view>
      <view v-for="group in groupedDetails" :key="group.key" class="salary-day">
        <view class="salary-day__head"><text>{{ group.label }}</text><text>当日金额 ¥{{ money(group.amount) }}</text></view>
        <view v-for="row in group.items" :key="detailKey(row)" class="card record-card salary-day__entry">
          <view class="record-head"><text class="record-title">{{ row.order_no }} · {{ row.process_name }}</text><text class="salary-line-amount" :class="{ 'is-deduct': lineAmount(row) < 0 }">{{ formatLine(row) }}</text></view>
          <text class="record-meta">{{ detailType(row.report_type) }} · {{ detailQuantity(row) }}<text v-if="showUnitPrice(row)"> · 单价 ¥{{ money(row.unit_price) }}</text></text>
        </view>
      </view>
    </template>
    <view v-else class="empty-state">暂无工资数据</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'

const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const salary = ref<any>(null)
const loading = ref(false)
const money = (value: unknown) => Number(value || 0).toFixed(2)
const monthWage = computed(() => Number(salary.value?.settled_wage || 0) + Number((salary.value?.unsettled_wage ?? salary.value?.total_wage) || 0))
const attendedDays = computed(() => Number(salary.value?.settled?.attended_days || 0) + Number(salary.value?.unsettled?.attended_days || 0))

/** 已结算 + 未结算，得到本月该项金额。没有拆分时用整月字段。 */
function monthAmount(key: string) {
  const row = salary.value
  if (!row) return 0
  if (row.settled || row.unsettled) {
    const settled = row.settled?.[key]
    const unsettled = row.unsettled?.[key]
    if (settled != null || unsettled != null) return Number(settled || 0) + Number(unsettled || 0)
  }
  return Number(row[key] || 0)
}

const SALARY_MODEL_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  guaranteed_piece: '保底+计件',
  hourly: '计时',
  fixed: '固定工资',
}

/** 档案里填过、或本月有金额，就显示。金额是本月应发，出勤为 0 时可以是 ¥0.00。 */
function showProfileMoney(archive: number, monthValue: number) {
  return archive > 0 || monthValue > 0
}

/**
 * 薪资档案里的计薪项都显示（银行卡除外）。
 * 损失扣款、预支扣款一并显示。
 */
const summaryItems = computed(() => {
  const row = salary.value
  if (!row) return [] as { key: string; label: string; value: string; deduct?: boolean }[]
  const items: { key: string; label: string; value: string; deduct?: boolean }[] = []
  const model = String(row.salary_model || '')
  items.push({
    key: 'model',
    label: '计薪方式',
    value: SALARY_MODEL_LABELS[model] || model || '—',
  })
  const scheduled = Number(row.scheduled_days || 0)
  items.push({
    key: 'attendance',
    label: '考勤天数',
    value: scheduled > 0 ? `${attendedDays.value}/${scheduled} 天` : `${attendedDays.value} 天`,
  })
  const baseLabel = model === 'guaranteed_piece'
    ? '保底金额'
    : model === 'fixed'
      ? '固定工资'
      : model === 'base_plus_piece' || model === 'hourly'
        ? '底薪'
        : ''
  const base = monthAmount('base_salary')
  const baseFull = Number(row.base_salary_full ?? row.base_salary ?? 0)
  if (baseLabel && showProfileMoney(baseFull, base)) items.push({ key: 'base', label: baseLabel, value: `¥${money(base)}` })
  const overtime = monthAmount('overtime_pay')
  const overtimeRate = Number(row.overtime_hourly_rate || 0)
  if (showProfileMoney(overtimeRate, overtime)) items.push({ key: 'overtime', label: '加班费', value: `¥${money(overtime)}` })
  const meal = monthAmount('meal_allowance')
  if (showProfileMoney(Number(row.meal_allowance_daily || 0), meal)) items.push({ key: 'meal', label: '餐费补贴', value: `¥${money(meal)}` })
  const housing = monthAmount('housing_allowance')
  if (showProfileMoney(Number(row.housing_allowance_daily || 0), housing)) items.push({ key: 'housing', label: '住宿补贴', value: `¥${money(housing)}` })
  const piece = monthAmount('payable_piece_wage')
  if (piece > 0) items.push({ key: 'piece', label: '计件金额', value: `¥${money(piece)}` })
  const commission = monthAmount('commission_total')
  if (commission > 0) items.push({ key: 'commission', label: '提成', value: `¥${money(commission)}` })
  const loss = monthAmount('loss_deduction')
  items.push({ key: 'loss', label: '损失扣款', value: loss > 0 ? `-¥${money(loss)}` : `¥${money(0)}`, deduct: loss > 0 })
  const advance = monthAmount('advance_repay')
  items.push({ key: 'advance', label: '预支扣款', value: advance > 0 ? `-¥${money(advance)}` : `¥${money(0)}`, deduct: advance > 0 })
  return items
})
const groupedDetails = computed(() => {
  const groups = new Map<string, { key: string; label: string; amount: number; items: any[] }>()
  const details = [...(salary.value?.details || [])].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  for (const row of details) {
    const key = String(row.created_at || '').slice(0, 10) || 'unknown'
    const group = groups.get(key) || { key, label: formatDay(row.created_at), amount: 0, items: [] }
    group.items.push(row)
    group.amount += lineAmount(row)
    groups.set(key, group)
  }
  return [...groups.values()]
})
const detailType = (value: string) => ({ normal: '正常', rework: '返修', group: '集体', supplement: '补数', tail: '尾数', scrap_deduction: '报废扣款' } as any)[value] || value
const detailQuantity = (row: any) => {
  if (row.report_type === 'scrap_deduction') return `报废 ${row.defect_qty || 0}`
  if (row.report_type === 'rework') return `返修 ${row.rework_qty || 0}`
  return `合格 ${row.qualified_qty || 0}`
}
/** 报废扣款行金额为负，普通计件用净额。 */
function lineAmount(row: any) {
  return Number(row?.net_amount ?? row?.amount ?? 0)
}
function formatLine(row: any) {
  const amount = lineAmount(row)
  if (amount < 0) return `-¥${money(Math.abs(amount))}`
  return `¥${money(amount)}`
}
function showUnitPrice(row: any) {
  return row?.report_type !== 'scrap_deduction' && Number(row?.unit_price || 0) > 0
}
function detailKey(row: any) {
  return [row.work_log_id, row.defect_event_id, row.cut_output_id, row.created_at].filter((part) => part != null && part !== '').join('-')
}
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
