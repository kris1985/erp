<template>
  <app-nav-bar />
  <view class="page h5-at">
    <view class="card h5-at-cal">
      <view class="h5-at-cal__head">
        <text @click="shiftMonth(-1)">‹</text>
        <strong>{{ monthTitle }}</strong>
        <text @click="shiftMonth(1)">›</text>
      </view>
      <view class="h5-at-cal__week"><text v-for="name in weekNames" :key="name">{{ name }}</text></view>
      <view class="h5-at-cal__grid">
        <view v-for="(cell, index) in cells" :key="cell?.date || `blank-${index}`" class="h5-at-day" :class="dayClass(cell)" @click="cell && selectDay(cell.date)">
          <text v-if="cell">{{ cell.day }}</text>
          <view v-if="cell && cell.status !== 'rest' && cell.status !== 'open'" class="h5-at-dot" :class="`is-${cell.status}`" />
        </view>
      </view>
    </view>

    <view v-if="detail" class="card h5-at-detail">
      <text class="h5-at-detail__title">{{ detailTitle }}</text>
      <text v-if="!detail.slots.length" class="h5-at-empty">这天没有排班</text>
      <view v-for="slot in detail.slots" :key="slot.id" class="h5-at-slot">
        <view class="h5-at-slot__head">
          <strong v-if="showSlotLabel(slot)">{{ slot.label }}</strong>
          <text class="h5-at-slot__range">{{ slot.start }}–{{ slot.end }}</text>
        </view>
        <view class="h5-at-slot__times">
          <view><text>上班</text><strong>{{ hm(slot.clock_in_at) }}</strong></view>
          <view><text>下班</text><strong>{{ hm(slot.clock_out_at) }}</strong></view>
        </view>
      </view>
      <text v-if="detail.is_today" class="h5-at-place" :class="{ far: distanceMeters != null && !inRange }" @click="locate">{{ placeText }}</text>
    </view>
    <view v-else class="h5-at-empty">正在加载…</view>

    <view v-if="detail?.is_today && detail.next_action" class="cut-sticky-bar h5-at-bar">
      <button class="primary-button h5-at-go" :disabled="!!punching" @click="punch(detail.next_action)">{{ punching === detail.next_action.label ? '打卡中…' : detail.next_action.label }}</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'
import { currentLocation } from '../../services/locate'

const weekNames = ['一', '二', '三', '四', '五', '六', '日']
const month = ref(currentMonth())
const calendarDays = ref<any[]>([])
const selected = ref(todayText())
const detail = ref<any>(null)
const punching = ref('')
const locating = ref(false)
const locationError = ref('')
const here = ref<{ latitude: number; longitude: number } | null>(null)

const monthTitle = computed(() => {
  const [year, mon] = month.value.split('-')
  return `${year}年${Number(mon)}月`
})
const cells = computed(() => {
  const days = calendarDays.value
  if (!days.length) return []
  const first = new Date(`${days[0].date}T00:00:00`)
  const lead = (first.getDay() + 6) % 7
  return [...Array(lead).fill(null), ...days]
})
const detailTitle = computed(() => {
  const text = String(detail.value?.work_date || '')
  const parts = text.split('-')
  if (parts.length < 3) return '打卡记录'
  const date = new Date(`${text}T00:00:00`)
  const week = weekNames[(date.getDay() + 6) % 7]
  return `${Number(parts[1])}月${Number(parts[2])}日 周${week}${detail.value?.is_today ? ' · 今天' : ''}`
})
const distanceMeters = computed(() => {
  const site = detail.value?.clock_site
  if (!site?.configured || !here.value) return null
  return haversine(here.value.latitude, here.value.longitude, Number(site.latitude), Number(site.longitude))
})
const inRange = computed(() => {
  const site = detail.value?.clock_site
  return !!site?.configured && distanceMeters.value != null && distanceMeters.value <= Number(site.radius_meters || 300)
})
const placeText = computed(() => {
  const site = detail.value?.clock_site
  if (!detail.value?.is_today) return '过去的日期只能查看'
  if (!site?.configured) return '工厂还没设置打卡地点'
  if (locating.value) return '正在定位…'
  if (locationError.value) return locationError.value
  if (distanceMeters.value == null) return '点这里获取定位'
  const away = distanceMeters.value < 1000 ? `${Math.round(distanceMeters.value)} 米` : `${(distanceMeters.value / 1000).toFixed(1)} 公里`
  return inRange.value ? `距打卡位置 ${away}` : `距打卡位置 ${away}，超出 ${site.radius_meters} 米`
})

function currentMonth(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}
function todayText() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
function showSlotLabel(slot: any) {
  const label = String(slot?.label || '').trim()
  return !!label && !/^第\s*\d+\s*段$/.test(label)
}
function hm(value?: string) {
  const matched = String(value || '').match(/(\d{2}:\d{2})/)
  return matched ? matched[1] : '—'
}
function haversine(lat1: number, lng1: number, lat2: number, lng2: number) {
  const radius = 6371000
  const p1 = lat1 * Math.PI / 180
  const p2 = lat2 * Math.PI / 180
  const dPhi = (lat2 - lat1) * Math.PI / 180
  const dLng = (lng2 - lng1) * Math.PI / 180
  const chord = Math.sin(dPhi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dLng / 2) ** 2
  return 2 * radius * Math.asin(Math.sqrt(chord))
}
function dayClass(cell: any) {
  if (!cell) return 'is-blank'
  return {
    'is-today': cell.is_today,
    'is-selected': cell.date === selected.value,
    'is-rest': cell.status === 'rest',
  }
}
function shiftMonth(step: number) {
  const [year, mon] = month.value.split('-').map(Number)
  const next = new Date(year, mon - 1 + step, 1)
  month.value = currentMonth(next)
  loadCalendar()
}
function selectDay(date: string) {
  selected.value = date
  loadDay()
}
function locate() {
  if (!detail.value?.is_today || !detail.value?.clock_site?.configured) return Promise.resolve()
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
async function loadCalendar() {
  try {
    const result: any = await get('/attendance/calendar', { month: month.value })
    calendarDays.value = result?.days || []
  } catch (error: any) {
    uni.showToast({ title: error?.message || '日历加载失败', icon: 'none' })
  }
}
async function loadDay() {
  try {
    detail.value = await get('/attendance/day', { work_date: selected.value })
    if (detail.value?.is_today && detail.value?.clock_site?.configured && !here.value) locate()
  } catch (error: any) {
    uni.showToast({ title: error?.message || '打卡记录加载失败', icon: 'none' })
  } finally {
    uni.stopPullDownRefresh()
  }
}
async function punch(action: any) {
  if (!action || punching.value) return
  if (!inRange.value) {
    if (!here.value) await locate()
    if (!inRange.value) {
      uni.showToast({ title: placeText.value, icon: 'none' })
      return
    }
  }
  punching.value = action.label
  try {
    detail.value = await post('/attendance/clock', {
      punch_type: action.punch_type,
      slot_id: action.slot_id,
      latitude: here.value?.latitude,
      longitude: here.value?.longitude,
    })
    uni.showToast({ title: '已打卡', icon: 'success' })
    await loadCalendar()
  } catch (error: any) {
    uni.showToast({ title: error?.message || '打卡失败', icon: 'none' })
    await loadDay()
  } finally {
    punching.value = ''
  }
}
async function load() {
  await loadCalendar()
  await loadDay()
}

onShow(load)
onPullDownRefresh(load)
</script>

<style scoped>
.h5-at { padding-bottom: 180rpx; }
.h5-at-cal,
.h5-at-detail { margin-bottom: 16rpx; padding: 22rpx 18rpx 16rpx; }
.h5-at-cal__head { display: flex; align-items: center; justify-content: space-between; padding: 0 12rpx 12rpx; }
.h5-at-cal__head text { width: 64rpx; color: #0057c2; font-size: 40rpx; text-align: center; }
.h5-at-cal__head strong { color: #181b23; font-size: 32rpx; }
.h5-at-cal__week,
.h5-at-cal__grid { display: grid; grid-template-columns: repeat(7, 1fr); }
.h5-at-cal__week text { color: #727786; font-size: 22rpx; text-align: center; }
.h5-at-day { display: flex; flex-direction: column; align-items: center; height: 84rpx; padding-top: 8rpx; }
.h5-at-day text { display: flex; align-items: center; justify-content: center; width: 52rpx; height: 52rpx; border-radius: 50%; color: #181b23; font-size: 26rpx; }
.h5-at-day.is-rest text { color: #727786; }
.h5-at-day.is-today text { color: #0057c2; font-weight: 750; }
.h5-at-day.is-selected text { background: #0057c2; color: #fff; }
.h5-at-dot { width: 8rpx; height: 8rpx; margin-top: 4rpx; border-radius: 50%; background: #0057c2; }
.h5-at-dot.is-done { background: #266d00; }
.h5-at-dot.is-partial { background: #7d5400; }
.h5-at-dot.is-missing { background: #ba1a1a; }
.h5-at-detail__title { display: block; margin-bottom: 8rpx; color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-at-empty { display: block; padding: 20rpx 8rpx; color: #727786; font-size: 24rpx; }
.h5-at-slot { padding: 16rpx 8rpx; border-top: 1rpx solid #e0e2ed; }
.h5-at-slot__head,
.h5-at-slot__times { display: flex; align-items: center; justify-content: space-between; }
.h5-at-slot__head strong { color: #181b23; font-size: 28rpx; }
.h5-at-slot__head text,
.h5-at-slot__times text { color: #727786; font-size: 22rpx; }
.h5-at-slot__head .h5-at-slot__range { color: #181b23; font-size: 32rpx; font-weight: 750; }
.h5-at-slot__times { margin-top: 12rpx; }
.h5-at-slot__times view { flex: 1; }
.h5-at-slot__times view + view { padding-left: 16rpx; border-left: 1rpx solid #e0e2ed; }
.h5-at-slot__times strong { display: block; margin-top: 4rpx; color: #181b23; font-size: 34rpx; font-weight: 750; }
.h5-at-place { display: block; margin-top: 12rpx; color: #414755; font-size: 24rpx; }
.h5-at-place.far { color: #9a5b00; }
.h5-at-bar { display: flex; flex-direction: column; align-items: center; gap: 8rpx; }
.h5-at-go { margin-top: 0; }
.h5-at-bar text { color: #0057c2; font-size: 26rpx; font-weight: 700; }
</style>
