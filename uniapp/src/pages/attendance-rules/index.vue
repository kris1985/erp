<template>
  <app-nav-bar />
  <view class="page h5-ar">
    <view v-if="!canSee" class="h5-ar-empty">没有考勤规则权限</view>
    <template v-else-if="form">
      <scroll-view class="h5-ar-tabs" scroll-x :show-scrollbar="false">
        <text v-for="item in sections" :key="item.value" :class="{ on: section === item.value }" @click="section = item.value">{{ item.label }}</text>
      </scroll-view>

      <template v-if="section === 'site'">
        <view class="card h5-ar-card">
          <text class="h5-ar-title">打卡地点</text>
          <text class="h5-ar-hint">人在这个点的范围内才能上班、下班打卡，范围 5–500 米。114.56 这类数填在经度，纬度一般是 20–50。</text>
          <view class="h5-ar-field"><text>经度</text><input :value="form.clock_site.longitude" :disabled="!canWrite" type="text" placeholder="如 114.56" @input="setSite('longitude', $event)" /></view>
          <view class="h5-ar-field"><text>纬度</text><input :value="form.clock_site.latitude" :disabled="!canWrite" type="text" placeholder="如 30.50" @input="setSite('latitude', $event)" /></view>
          <view class="h5-ar-field"><text>范围（米）</text><input :value="form.clock_site.radius_meters" :disabled="!canWrite" type="number" placeholder="300" @input="setSite('radius_meters', $event)" /></view>
          <view v-if="canWrite" class="h5-ar-link" @click="fillHere">用当前定位填入</view>
        </view>
      </template>

      <template v-else-if="section === 'schedule'">
        <view class="card h5-ar-card">
          <text class="h5-ar-title">固定休息日</text>
          <view class="h5-ar-chips">
            <text :class="{ on: form.rest_day_mode === 'weekly' }" @click="setMode('weekly')">每周</text>
            <text :class="{ on: form.rest_day_mode === 'monthly' }" @click="setMode('monthly')">每月</text>
          </view>
          <view v-if="form.rest_day_mode === 'weekly'" class="h5-ar-chips">
            <text v-for="day in weekdays" :key="day.value" :class="{ on: form.weekly_rest_days.includes(day.value) }" @click="toggleDay('weekly_rest_days', day.value)">{{ day.label }}</text>
          </view>
          <view v-else class="h5-ar-chips">
            <text v-for="day in 31" :key="day" :class="{ on: form.monthly_rest_days.includes(day) }" @click="toggleDay('monthly_rest_days', day)">{{ day }}</text>
          </view>
        </view>
        <view class="card h5-ar-card">
          <text class="h5-ar-title">上下班时间段</text>
          <view v-for="(row, index) in form.work_periods" :key="`work-${index}`" class="h5-ar-period">
            <picker mode="time" :value="row.start || '08:00'" :disabled="!canWrite" @change="row.start = $event.detail.value"><text>{{ row.start || '开始' }}</text></picker>
            <text class="h5-ar-to">至</text>
            <picker mode="time" :value="row.end || '12:00'" :disabled="!canWrite" @change="row.end = $event.detail.value"><text>{{ row.end || '结束' }}</text></picker>
            <text v-if="canWrite" class="h5-ar-del" @click="form.work_periods.splice(index, 1)">删除</text>
          </view>
          <view v-if="canWrite" class="h5-ar-link" @click="form.work_periods.push({ start: '08:00', end: '12:00' })">＋ 添加时段</view>
        </view>
      </template>

      <template v-else-if="section === 'exception'">
        <view class="card h5-ar-card">
          <text class="h5-ar-title">特殊放假</text>
          <text class="h5-ar-hint">精确到小时，覆盖平时的休息日</text>
          <view v-for="(row, index) in form.special_holidays" :key="`hol-${index}`" class="h5-ar-span">
            <view class="h5-ar-period">
              <picker mode="date" :value="datePart(row.start)" :disabled="!canWrite" @change="setDate(row, 'start', $event.detail.value)"><text>{{ datePart(row.start) || '开始日期' }}</text></picker>
              <picker mode="selector" :range="hours" :value="hourIndex(row.start)" :disabled="!canWrite" @change="setHour(row, 'start', hours[$event.detail.value])"><text>{{ hourPart(row.start) }}时</text></picker>
            </view>
            <view class="h5-ar-period">
              <picker mode="date" :value="datePart(row.end)" :disabled="!canWrite" @change="setDate(row, 'end', $event.detail.value)"><text>{{ datePart(row.end) || '结束日期' }}</text></picker>
              <picker mode="selector" :range="hours" :value="hourIndex(row.end)" :disabled="!canWrite" @change="setHour(row, 'end', hours[$event.detail.value])"><text>{{ hourPart(row.end) }}时</text></picker>
              <text v-if="canWrite" class="h5-ar-del" @click="form.special_holidays.splice(index, 1)">删除</text>
            </view>
          </view>
          <view v-if="canWrite" class="h5-ar-link" @click="form.special_holidays.push(emptySpan())">＋ 添加放假</view>
        </view>
        <view class="card h5-ar-card">
          <text class="h5-ar-title">特殊加班</text>
          <view v-for="(row, index) in form.special_overtimes" :key="`sot-${index}`" class="h5-ar-span">
            <view class="h5-ar-period">
              <picker mode="date" :value="datePart(row.start)" :disabled="!canWrite" @change="setDate(row, 'start', $event.detail.value)"><text>{{ datePart(row.start) || '开始日期' }}</text></picker>
              <picker mode="selector" :range="hours" :value="hourIndex(row.start)" :disabled="!canWrite" @change="setHour(row, 'start', hours[$event.detail.value])"><text>{{ hourPart(row.start) }}时</text></picker>
            </view>
            <view class="h5-ar-period">
              <picker mode="date" :value="datePart(row.end)" :disabled="!canWrite" @change="setDate(row, 'end', $event.detail.value)"><text>{{ datePart(row.end) || '结束日期' }}</text></picker>
              <picker mode="selector" :range="hours" :value="hourIndex(row.end)" :disabled="!canWrite" @change="setHour(row, 'end', hours[$event.detail.value])"><text>{{ hourPart(row.end) }}时</text></picker>
              <text v-if="canWrite" class="h5-ar-del" @click="form.special_overtimes.splice(index, 1)">删除</text>
            </view>
          </view>
          <view v-if="canWrite" class="h5-ar-link" @click="form.special_overtimes.push(emptySpan())">＋ 添加加班</view>
        </view>
      </template>

      <template v-else>
        <view class="card h5-ar-card">
          <view class="h5-ar-switch"><text>启用扣款</text><switch :checked="led.enabled" :disabled="!canWrite" color="#0057c2" @change="led.enabled = $event.detail.value" /></view>
          <template v-if="led.enabled">
            <view class="h5-ar-field"><text>宽限（分钟）</text><input :value="String(led.grace_minutes ?? 0)" :disabled="!canWrite" type="number" @input="led.grace_minutes = num($event)" /></view>
            <view class="h5-ar-field"><text>每月免费次数</text><input :value="String(led.monthly_free_times ?? 0)" :disabled="!canWrite" type="number" @input="led.monthly_free_times = num($event)" /></view>
            <view class="h5-ar-field"><text>单日封顶（元，空为不限）</text><input :value="led.daily_cap_amount ?? ''" :disabled="!canWrite" type="digit" @input="setCap($event)" /></view>
            <view class="h5-ar-switch"><text>同日迟到与早退分别扣</text><switch :checked="led.count_late_and_early_separate" :disabled="!canWrite" color="#0057c2" @change="led.count_late_and_early_separate = $event.detail.value" /></view>
            <view class="h5-ar-switch"><text>早退与迟到同一规则</text><switch :checked="led.same_rule_for_early" :disabled="!canWrite" color="#0057c2" @change="led.same_rule_for_early = $event.detail.value" /></view>
          </template>
        </view>
        <view v-if="led.enabled" class="card h5-ar-card">
          <view v-if="!led.same_rule_for_early" class="h5-ar-chips">
            <text :class="{ on: penaltySide === 'late' }" @click="penaltySide = 'late'">迟到</text>
            <text :class="{ on: penaltySide === 'early' }" @click="penaltySide = 'early'">早退</text>
          </view>
          <text class="h5-ar-title">{{ penaltySide === 'early' && !led.same_rule_for_early ? '早退扣款' : '扣款方式' }}</text>
          <view class="h5-ar-chips">
            <text v-for="item in modes" :key="item.value" :class="{ on: rule.mode === item.value }" @click="canWrite && (rule.mode = item.value)">{{ item.label }}</text>
          </view>
          <view v-if="rule.mode === 'fixed_amount'" class="h5-ar-field"><text>每次扣款（元）</text><input :value="String(rule.fixed_amount ?? 0)" :disabled="!canWrite" type="digit" @input="rule.fixed_amount = num($event)" /></view>
          <template v-else-if="rule.mode === 'per_minute'">
            <view class="h5-ar-field"><text>每分钟（元）</text><input :value="String(rule.amount_per_minute ?? 0)" :disabled="!canWrite" type="digit" @input="rule.amount_per_minute = num($event)" /></view>
            <view class="h5-ar-switch"><text>不足一分钟按一分钟</text><switch :checked="rule.round_up_minutes" :disabled="!canWrite" color="#0057c2" @change="rule.round_up_minutes = $event.detail.value" /></view>
          </template>
          <template v-else>
            <view v-for="(tier, index) in rule.tiers" :key="`${penaltySide}-${index}`" class="h5-ar-tier">
              <view class="h5-ar-period">
                <input :value="tier.up_to_minutes ?? ''" :disabled="!canWrite" type="number" placeholder="及以上" @input="setTierLimit(tier, $event)" />
                <text>分钟内</text>
                <text v-if="canWrite" class="h5-ar-del" @click="rule.tiers.splice(index, 1)">删除</text>
              </view>
              <view class="h5-ar-chips">
                <text v-for="item in deductTypes" :key="item.value" :class="{ on: tier.deduct_type === item.value }" @click="canWrite && (tier.deduct_type = item.value)">{{ item.label }}</text>
              </view>
              <view v-if="tier.deduct_type === 'amount'" class="h5-ar-field"><text>金额（元）</text><input :value="String(tier.amount ?? 0)" :disabled="!canWrite" type="digit" @input="tier.amount = num($event)" /></view>
              <view v-else-if="tier.deduct_type === 'day_fraction'" class="h5-ar-field"><text>日薪比例（0–1）</text><input :value="String(tier.day_fraction ?? 0.5)" :disabled="!canWrite" type="digit" @input="tier.day_fraction = num($event)" /></view>
            </view>
            <view v-if="canWrite" class="h5-ar-link" @click="rule.tiers.push({ up_to_minutes: null, deduct_type: 'amount', amount: 0, day_fraction: null })">＋ 添加一档</view>
          </template>
        </view>
      </template>

      <view v-if="canWrite" class="cut-sticky-bar"><button class="primary-button h5-ar-save" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button></view>
      <view v-else class="h5-ar-empty">当前账号只能查看</view>
    </template>
    <view v-else class="h5-ar-empty">正在加载考勤规则…</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { get, patch } from '../../services/http'
import { getProfile } from '../../services/storage'

const sections = [
  { value: 'site', label: '打卡地点' },
  { value: 'schedule', label: '作息' },
  { value: 'exception', label: '例外' },
  { value: 'penalty', label: '扣款' },
]
const weekdays = [
  { value: 1, label: '一' }, { value: 2, label: '二' }, { value: 3, label: '三' },
  { value: 4, label: '四' }, { value: 5, label: '五' }, { value: 6, label: '六' }, { value: 7, label: '日' },
]
const modes = [
  { value: 'fixed_amount', label: '每次固定' },
  { value: 'per_minute', label: '按分钟' },
  { value: 'tiered', label: '阶梯' },
]
const deductTypes = [
  { value: 'amount', label: '金额' },
  { value: 'day_fraction', label: '日薪比例' },
  { value: 'half_day', label: '半天' },
  { value: 'full_day', label: '全天' },
]
const hours = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, '0'))

const profile = ref(getProfile())
const section = ref('site')
const form = ref<any>(null)
const saving = ref(false)
const penaltySide = ref<'late' | 'early'>('late')
const canSee = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('attendance_rules') || features.includes('attendance_rules_write')
})
const canWrite = computed(() => (profile.value?.featurePermissions || []).includes('attendance_rules_write'))
const led = computed(() => form.value?.late_early_deduction || {})
const rule = computed(() => {
  const late = led.value
  if (penaltySide.value === 'early' && late.same_rule_for_early === false) return late.early || late
  return late
})

function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function inputValue(event: any) {
  return String(event?.detail?.value ?? '')
}
function num(event: any) {
  const text = inputValue(event).trim()
  const value = Number(text)
  return text && !Number.isNaN(value) ? value : 0
}
function setSite(key: 'longitude' | 'latitude' | 'radius_meters', event: any) {
  form.value.clock_site[key] = inputValue(event)
}
function setMode(mode: 'weekly' | 'monthly') {
  if (canWrite.value) form.value.rest_day_mode = mode
}
function toggleDay(key: 'weekly_rest_days' | 'monthly_rest_days', day: number) {
  if (!canWrite.value) return
  const list: number[] = form.value[key]
  const index = list.indexOf(day)
  if (index >= 0) list.splice(index, 1)
  else list.push(day)
  list.sort((a, b) => a - b)
}
function todayText() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}
function emptySpan() {
  const day = todayText()
  return { start: `${day} 08:00`, end: `${day} 18:00` }
}
function datePart(value?: string) {
  return String(value || '').slice(0, 10)
}
function hourPart(value?: string) {
  return String(value || '').slice(11, 13) || '08'
}
function hourIndex(value?: string) {
  return Math.max(0, hours.indexOf(hourPart(value)))
}
function setDate(row: any, key: 'start' | 'end', date: string) {
  row[key] = `${date} ${hourPart(row[key])}:00`
}
function setHour(row: any, key: 'start' | 'end', hour: string) {
  row[key] = `${datePart(row[key]) || todayText()} ${hour}:00`
}
function setCap(event: any) {
  const text = inputValue(event).trim()
  led.value.daily_cap_amount = text === '' ? null : Number(text)
}
function setTierLimit(tier: any, event: any) {
  const text = inputValue(event).trim()
  tier.up_to_minutes = text === '' ? null : Math.max(1, Number(text) || 1)
}
function blankCoord(value: unknown) {
  return String(value ?? '').trim() === ''
}
function toHour(value: string) {
  const text = String(value || '').trim().replace('T', ' ')
  return text.length >= 13 ? `${text.slice(0, 13)}:00` : text
}
function validate() {
  const site = form.value.clock_site
  const lngBlank = blankCoord(site.longitude)
  const latBlank = blankCoord(site.latitude)
  if (lngBlank !== latBlank) return '经度和纬度要一起填'
  if (!lngBlank) {
    const longitude = Number(site.longitude)
    const latitude = Number(site.latitude)
    if (Number.isNaN(longitude) || longitude < -180 || longitude > 180) return '经度须在 -180 到 180'
    if (Number.isNaN(latitude) || latitude < -90 || latitude > 90) return latitude > 90 ? '纬度不能超过 90，114 这类数请填到经度' : '纬度须在 -90 到 90'
  }
  const radius = Number(site.radius_meters)
  if (!radius || radius < 5 || radius > 500) return '打卡范围须在 5 到 500 米'
  if (form.value.rest_day_mode === 'weekly' && !form.value.weekly_rest_days.length) return '请选择每周休息日'
  if (form.value.rest_day_mode === 'monthly' && !form.value.monthly_rest_days.length) return '请选择每月休息日'
  for (const [list, label] of [[form.value.work_periods, '上下班']] as const) {
    for (let index = 0; index < list.length; index += 1) {
      const row = list[index]
      if (!row.start || !row.end) return `${label}第 ${index + 1} 段请填完整`
      if (row.start >= row.end) return `${label}第 ${index + 1} 段开始须早于结束`
    }
  }
  for (const [list, label] of [[form.value.special_holidays, '特殊放假'], [form.value.special_overtimes, '特殊加班']] as const) {
    for (let index = 0; index < list.length; index += 1) {
      const row = list[index]
      if (!datePart(row.start) || !datePart(row.end)) return `${label}第 ${index + 1} 段请填完整`
      if (toHour(row.start) >= toHour(row.end)) return `${label}第 ${index + 1} 段开始须早于结束`
    }
  }
  return ''
}
function dumpRule(ruleValue: any) {
  return {
    mode: ruleValue.mode,
    fixed_amount: Number(ruleValue.fixed_amount || 0),
    amount_per_minute: Number(ruleValue.amount_per_minute || 0),
    round_up_minutes: !!ruleValue.round_up_minutes,
    tiers: (ruleValue.tiers || []).map((tier: any) => ({
      up_to_minutes: tier.up_to_minutes == null || tier.up_to_minutes === '' ? null : Number(tier.up_to_minutes),
      deduct_type: tier.deduct_type,
      amount: tier.amount == null ? null : Number(tier.amount),
      day_fraction: tier.day_fraction == null ? null : Number(tier.day_fraction),
    })),
    daily_cap_amount: ruleValue.daily_cap_amount == null || ruleValue.daily_cap_amount === '' ? null : Number(ruleValue.daily_cap_amount),
  }
}
function apply(data: any) {
  const site = data?.clock_site || {}
  form.value = {
    ...data,
    weekly_rest_days: [...(data?.weekly_rest_days || [])],
    monthly_rest_days: [...(data?.monthly_rest_days || [])],
    work_periods: (data?.work_periods || []).map((row: any) => ({ ...row })),
    special_holidays: (data?.special_holidays || []).map((row: any) => ({ ...row })),
    special_overtimes: (data?.special_overtimes || []).map((row: any) => ({ ...row })),
    clock_site: {
      longitude: site.longitude == null ? '' : String(site.longitude),
      latitude: site.latitude == null ? '' : String(site.latitude),
      radius_meters: String(site.radius_meters || 300),
    },
    late_early_deduction: data?.late_early_deduction || {},
  }
}
function fillHere() {
  uni.getLocation({
    type: 'wgs84',
    isHighAccuracy: true,
    success: (res) => {
      form.value.clock_site.longitude = Number(res.longitude).toFixed(6)
      form.value.clock_site.latitude = Number(res.latitude).toFixed(6)
      toast('已填入当前定位，保存后生效')
    },
    fail: () => toast('定位失败，请允许使用位置'),
  })
}
async function load() {
  profile.value = getProfile()
  if (!canSee.value) {
    uni.stopPullDownRefresh()
    return
  }
  try {
    apply(await get('/attendance-rules'))
  } catch (error: any) {
    toast(error?.message || '考勤规则加载失败')
  } finally {
    uni.stopPullDownRefresh()
  }
}
async function save() {
  const message = validate()
  if (message) {
    toast(message)
    return
  }
  const site = form.value.clock_site
  const late = form.value.late_early_deduction
  saving.value = true
  try {
    apply(await patch('/attendance-rules', {
      rest_day_mode: form.value.rest_day_mode,
      weekly_rest_days: form.value.weekly_rest_days,
      monthly_rest_days: form.value.monthly_rest_days,
      work_periods: form.value.work_periods,
      special_holidays: form.value.special_holidays.map((row: any) => ({ start: toHour(row.start), end: toHour(row.end) })),
      special_overtimes: form.value.special_overtimes.map((row: any) => ({ start: toHour(row.start), end: toHour(row.end) })),
      clock_site: {
        longitude: blankCoord(site.longitude) ? null : Number(site.longitude),
        latitude: blankCoord(site.latitude) ? null : Number(site.latitude),
        radius_meters: Number(site.radius_meters),
      },
      late_early_deduction: {
        enabled: !!late.enabled,
        grace_minutes: Number(late.grace_minutes || 0),
        monthly_free_times: Number(late.monthly_free_times || 0),
        count_late_and_early_separate: !!late.count_late_and_early_separate,
        same_rule_for_early: late.same_rule_for_early !== false,
        ...dumpRule(late),
        early: dumpRule(late.early || late),
      },
    }))
    toast('已保存')
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

onShow(load)
onPullDownRefresh(load)
</script>

<style scoped>
.h5-ar { padding-bottom: 160rpx; }
.h5-ar-empty { padding: 48rpx 0; color: #727786; font-size: 26rpx; text-align: center; }
.h5-ar-tabs { width: 100%; margin-bottom: 18rpx; white-space: nowrap; }
.h5-ar-tabs text,
.h5-ar-chips text { display: inline-flex; align-items: center; height: 56rpx; margin: 0 12rpx 12rpx 0; padding: 0 22rpx; border-radius: 999rpx; background: #fff; color: #414755; font-size: 24rpx; }
.h5-ar-tabs text.on,
.h5-ar-chips text.on { background: #0057c2; color: #fff; font-weight: 700; }
.h5-ar-card { margin-bottom: 16rpx; padding: 22rpx 24rpx; }
.h5-ar-title { display: block; color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-ar-hint { display: block; margin-top: 8rpx; color: #727786; font-size: 22rpx; line-height: 1.5; }
.h5-ar-field { display: flex; flex-direction: column; gap: 8rpx; margin-top: 18rpx; }
.h5-ar-field text { color: #727786; font-size: 22rpx; }
.h5-ar-field input,
.h5-ar-tier input { height: 72rpx; padding: 0 20rpx; border-radius: 16rpx; background: #f5f7fa; color: #181b23; font-size: 28rpx; }
.h5-ar-link { margin-top: 18rpx; color: #0057c2; font-size: 26rpx; font-weight: 700; }
.h5-ar-chips { display: flex; flex-wrap: wrap; margin-top: 16rpx; }
.h5-ar-period { display: flex; align-items: center; gap: 16rpx; min-height: 72rpx; margin-top: 8rpx; }
.h5-ar-period text,
.h5-ar-to { color: #181b23; font-size: 28rpx; }
.h5-ar-to,
.h5-ar-del { color: #727786; font-size: 24rpx; }
.h5-ar-del { margin-left: auto; color: #ba1a1a; }
.h5-ar-span { margin-top: 12rpx; padding-top: 8rpx; border-top: 1rpx solid #e0e2ed; }
.h5-ar-switch { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; min-height: 84rpx; color: #181b23; font-size: 28rpx; }
.h5-ar-tier { margin-top: 16rpx; padding-top: 8rpx; border-top: 1rpx solid #e0e2ed; }
.h5-ar-tier input { flex: 1; }
.h5-ar-save { margin-top: 0; }
</style>
