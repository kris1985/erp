<template>
  <app-nav-bar />
  <view class="page h5-leave" :class="{ 'h5-leave--dock': showDock }">
    <view v-if="!canSee" class="h5-leave-empty">没有请假登记权限</view>

    <template v-else-if="mode === 'list'">
      <picker mode="date" fields="month" :value="month" @change="onMonth">
        <view class="h5-leave-month">
          <text>{{ monthLabel }}</text>
          <text class="h5-leave-chev">›</text>
        </view>
      </picker>
      <view v-if="!rows.length" class="h5-leave-empty">{{ monthLabel }}还没有请假</view>
      <view v-for="row in rows" :key="row.id" class="card h5-leave-card" @click="openDetail(row)">
        <view class="h5-leave-card__main">
          <text class="h5-leave-name">{{ row.worker_name || '员工' }}</text>
          <text class="h5-leave-meta">{{ rangeText(row) }}</text>
          <text class="h5-leave-meta">{{ payText(row) }}</text>
        </view>
        <view class="h5-leave-days">
          <strong>{{ Number(row.days || 0).toFixed(1) }}</strong>
          <text>天</text>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-leave-hero">
        <text class="h5-leave-name">{{ current.worker_name || '员工' }}</text>
        <text class="h5-leave-hero__days">{{ Number(current.days || 0).toFixed(1) }} 天</text>
        <text class="h5-leave-meta">{{ rangeText(current) }}</text>
      </view>
      <view class="card h5-leave-sheet">
        <view class="h5-leave-line"><text>工资</text><text>{{ current.pay_salary ? '照发' : '按天扣' }}</text></view>
        <view class="h5-leave-line"><text>餐补</text><text>{{ current.pay_meal ? '照发' : '不发' }}</text></view>
        <view class="h5-leave-line"><text>住宿补</text><text>{{ current.pay_housing ? '照发' : '不发' }}</text></view>
        <view class="h5-leave-line"><text>其它补</text><text>{{ current.pay_other ? '照发' : '不发' }}</text></view>
        <view class="h5-leave-line"><text>原因</text><text>{{ current.notes || '—' }}</text></view>
      </view>
    </template>

    <template v-else-if="mode === 'form'">
      <view class="card h5-leave-sheet">
        <view class="h5-leave-field">
          <text class="h5-leave-label">员工<text class="req">*</text></text>
          <view class="h5-leave-pick" :class="{ 'is-empty': !form.worker_id }" @click="mode = 'chooser'">
            <text>{{ workerName || '请选择员工' }}</text>
            <text class="h5-leave-chev">›</text>
          </view>
        </view>
        <view class="h5-leave-field">
          <text class="h5-leave-label">开始<text class="req">*</text></text>
          <picker mode="date" :value="form.start_date" @change="form.start_date = $event.detail.value">
            <view class="h5-leave-pick" :class="{ 'is-empty': !form.start_date }">
              <text>{{ form.start_date || '选择日期' }}</text>
              <text class="h5-leave-chev">›</text>
            </view>
          </picker>
          <view class="h5-leave-halves">
            <text :class="{ on: form.start_half === 'am' }" @click="form.start_half = 'am'">上午</text>
            <text :class="{ on: form.start_half === 'pm' }" @click="form.start_half = 'pm'">下午</text>
          </view>
        </view>
        <view class="h5-leave-field">
          <text class="h5-leave-label">结束<text class="req">*</text></text>
          <picker mode="date" :value="form.end_date" @change="form.end_date = $event.detail.value">
            <view class="h5-leave-pick" :class="{ 'is-empty': !form.end_date }">
              <text>{{ form.end_date || '选择日期' }}</text>
              <text class="h5-leave-chev">›</text>
            </view>
          </picker>
          <view class="h5-leave-halves">
            <text :class="{ on: form.end_half === 'am' }" @click="form.end_half = 'am'">上午</text>
            <text :class="{ on: form.end_half === 'pm' }" @click="form.end_half = 'pm'">下午</text>
          </view>
        </view>
        <view class="h5-leave-count">
          <text>合计</text>
          <strong>{{ previewDays }}</strong>
        </view>
        <text class="h5-leave-hint">只选上午或下午算半天，上午到下午算一天。不照发工资时，按当天日工资扣，四舍五入到元。</text>
        <text class="h5-leave-label">请假期间照发</text>
        <view class="h5-leave-switch" :class="{ on: form.pay_salary }" @click="form.pay_salary = !form.pay_salary">
          <text>工资</text><text>{{ form.pay_salary ? '照发' : '按天扣' }}</text>
        </view>
        <view class="h5-leave-switch" :class="{ on: form.pay_meal }" @click="form.pay_meal = !form.pay_meal">
          <text>餐补</text><text>{{ form.pay_meal ? '照发' : '不发' }}</text>
        </view>
        <view class="h5-leave-switch" :class="{ on: form.pay_housing }" @click="form.pay_housing = !form.pay_housing">
          <text>住宿补</text><text>{{ form.pay_housing ? '照发' : '不发' }}</text>
        </view>
        <view class="h5-leave-switch" :class="{ on: form.pay_other }" @click="form.pay_other = !form.pay_other">
          <text>其它补</text><text>{{ form.pay_other ? '照发' : '不发' }}</text>
        </view>
        <view class="h5-leave-field">
          <text class="h5-leave-label">请假原因</text>
          <input v-model="form.notes" class="h5-leave-input" placeholder="选填" placeholder-style="color:#8b93a7" />
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'chooser'">
      <view class="card h5-leave-search">
        <input v-model="workerQuery" placeholder="搜姓名" placeholder-style="color:#8b93a7" confirm-type="search" />
      </view>
      <view v-if="!workerHits.length" class="h5-leave-empty">没有匹配的员工</view>
      <view v-for="row in workerHits" :key="row.id" class="card h5-leave-option" @click="chooseWorker(row)">
        <text>{{ row.name }}</text>
        <text v-if="row.department_name" class="h5-leave-meta">{{ row.department_name }}</text>
      </view>
    </template>

    <view v-if="showDock" class="cut-sticky-bar h5-leave-dock">
      <button v-if="mode === 'list'" class="primary-button h5-leave-primary" @click="openCreate">登记请假</button>
      <template v-else-if="mode === 'detail'">
        <button class="h5-leave-ghost" @click="remove">删除</button>
        <button class="primary-button h5-leave-primary" @click="openEdit(current)">编辑</button>
      </template>
      <button v-else class="primary-button h5-leave-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onBackPress, onPullDownRefresh, onShow, onUnload } from '@dcloudio/uni-app'
import { del, get, patch, post } from '../../services/http'
import { setPageBackHandler } from '../../services/page-title'
import { getProfile } from '../../services/storage'

type Mode = 'list' | 'detail' | 'form' | 'chooser'

const profile = ref(getProfile())
const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('leaves') || features.value.includes('leaves_write'))
const canWrite = computed(() => features.value.includes('leaves_write'))
const mode = ref<Mode>('list')
const month = ref(todayIso().slice(0, 7))
const rows = ref<any[]>([])
const workers = ref<any[]>([])
const current = ref<any>(null)
const form = ref<any>(emptyForm())
const workerQuery = ref('')
const saving = ref(false)

const monthLabel = computed(() => {
  const [year, mon] = month.value.split('-')
  return `${year}年${Number(mon)}月`
})
const workerName = computed(() => workers.value.find((row) => row.id === form.value.worker_id)?.name || current.value?.worker_name || '')
const workerHits = computed(() => {
  const q = workerQuery.value.trim().toLowerCase()
  return workers.value.filter((row) => !q || String(row.name || '').toLowerCase().includes(q) || String(row.department_name || '').toLowerCase().includes(q))
})
const previewDays = computed(() => {
  const halves = countHalves(form.value.start_date, form.value.start_half, form.value.end_date, form.value.end_half)
  return halves == null ? '时间不对' : `${(halves * 0.5).toFixed(1)} 天`
})
const showDock = computed(() => canSee.value && canWrite.value && mode.value !== 'chooser')

function todayIso() {
  const day = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}
function emptyForm() {
  const today = todayIso()
  return {
    id: null,
    worker_id: null,
    start_date: today,
    end_date: today,
    start_half: 'am',
    end_half: 'pm',
    pay_salary: false,
    pay_meal: false,
    pay_housing: false,
    pay_other: false,
    notes: '',
  }
}
function halfLabel(value: string) {
  return value === 'pm' ? '下午' : '上午'
}
function rangeText(row: any) {
  const start = `${row.start_date} ${halfLabel(row.start_half)}`
  const end = `${row.end_date} ${halfLabel(row.end_half)}`
  return start === end ? start : `${start} 至 ${end}`
}
function payText(row: any) {
  const parts = [
    row.pay_salary ? '工资' : '',
    row.pay_meal ? '餐补' : '',
    row.pay_housing ? '住宿补' : '',
    row.pay_other ? '其它补' : '',
  ].filter(Boolean)
  return parts.length ? `照发${parts.join('、')}` : '工资按天扣'
}
function monthRange(value: string) {
  const [year, mon] = value.split('-').map(Number)
  const last = new Date(year, mon, 0).getDate()
  const pad = String(mon).padStart(2, '0')
  return { date_from: `${year}-${pad}-01`, date_to: `${year}-${pad}-${String(last).padStart(2, '0')}` }
}
/** 与后台一致：每个上午或下午算半天。 */
function countHalves(startDate: string, startHalf: string, endDate: string, endHalf: string) {
  if (!startDate || !endDate) return null
  if (endDate < startDate || (startDate === endDate && startHalf === 'pm' && endHalf === 'am')) return null
  if (startDate === endDate) return startHalf === endHalf ? 1 : 2
  let count = startHalf === 'am' ? 2 : 1
  const cursor = new Date(`${startDate}T00:00:00`)
  const end = new Date(`${endDate}T00:00:00`)
  cursor.setDate(cursor.getDate() + 1)
  while (cursor < end) {
    count += 2
    cursor.setDate(cursor.getDate() + 1)
  }
  count += endHalf === 'pm' ? 2 : 1
  return count
}
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function syncTitle() {
  const titles: Record<Mode, string> = {
    list: '请假登记',
    detail: current.value?.worker_name || '请假',
    form: form.value.id ? '编辑请假' : '登记请假',
    chooser: '选择员工',
  }
  uni.setNavigationBarTitle({ title: titles[mode.value] })
}
async function load() {
  profile.value = getProfile()
  if (!canSee.value) return
  try {
    const listed = await get<any[]>('/leaves', monthRange(month.value))
    rows.value = Array.isArray(listed) ? listed : []
    const staff: any = await get('/employees', { page: 1, page_size: 500, is_active: true })
    workers.value = staff?.items || []
  } catch (error: any) {
    toast(error?.message || '加载失败')
  } finally {
    uni.stopPullDownRefresh()
  }
}
function onMonth(event: any) {
  month.value = String(event?.detail?.value || month.value).slice(0, 7)
  void load()
}
function openCreate() {
  form.value = emptyForm()
  current.value = null
  mode.value = 'form'
}
function openDetail(row: any) {
  current.value = row
  mode.value = 'detail'
}
function openEdit(row: any) {
  form.value = {
    ...emptyForm(),
    ...row,
    notes: row.notes || '',
    start_half: row.start_half || 'am',
    end_half: row.end_half || 'pm',
  }
  mode.value = 'form'
}
function chooseWorker(row: any) {
  form.value.worker_id = row.id
  mode.value = 'form'
}
async function save() {
  if (!form.value.worker_id) {
    toast('请选择员工')
    return
  }
  if (countHalves(form.value.start_date, form.value.start_half, form.value.end_date, form.value.end_half) == null) {
    toast('结束时间不能早于开始时间')
    return
  }
  const body = {
    worker_id: form.value.worker_id,
    start_date: form.value.start_date,
    end_date: form.value.end_date,
    start_half: form.value.start_half,
    end_half: form.value.end_half,
    pay_salary: !!form.value.pay_salary,
    pay_meal: !!form.value.pay_meal,
    pay_housing: !!form.value.pay_housing,
    pay_other: !!form.value.pay_other,
    notes: form.value.notes || null,
  }
  saving.value = true
  try {
    const saved: any = form.value.id ? await patch(`/leaves/${form.value.id}`, body) : await post('/leaves', body)
    current.value = saved
    toast('已保存')
    mode.value = 'detail'
    await load()
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
function remove() {
  const row = current.value
  if (!row?.id) return
  uni.showModal({
    title: '删除请假',
    content: `删除「${row.worker_name || '这条'}」的请假？`,
    success: async (result) => {
      if (!result.confirm) return
      try {
        await del(`/leaves/${row.id}`)
        toast('已删除')
        mode.value = 'list'
        await load()
      } catch (error: any) {
        toast(error?.message || '删除失败')
      }
    },
  })
}
function goBack() {
  if (mode.value === 'chooser') {
    mode.value = 'form'
    return
  }
  if (mode.value === 'form') {
    mode.value = form.value.id ? 'detail' : 'list'
    return
  }
  mode.value = 'list'
}
function handleBack() {
  if (mode.value === 'list') return false
  goBack()
  return true
}

watch(mode, syncTitle)
onBackPress(() => handleBack())
onPullDownRefresh(() => {
  if (mode.value === 'list') void load()
  else uni.stopPullDownRefresh()
})
onShow(() => {
  profile.value = getProfile()
  setPageBackHandler('pages/leaves/index', handleBack)
  syncTitle()
  if (!canSee.value) {
    toast('没有请假登记权限')
    setTimeout(() => uni.navigateBack(), 400)
    return
  }
  if (mode.value === 'list') void load()
})
onUnload(() => setPageBackHandler('pages/leaves/index', null))
</script>

<style scoped>
.h5-leave--dock { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
.h5-leave-empty { padding: 80rpx 0; color: #414755; font-size: 26rpx; text-align: center; }
.h5-leave picker { display: block; width: 100%; }
.h5-leave-month,
.h5-leave-pick,
.h5-leave-input,
.h5-leave-switch {
  box-sizing: border-box;
  width: 100%;
  height: 88rpx;
  padding: 0 24rpx;
  border: 2rpx solid #c5d0e0;
  border-radius: 16rpx;
  background: #f4f7fb;
  color: #181b23;
  font-size: 30rpx;
}
.h5-leave-input { line-height: 84rpx; }
.h5-leave-month,
.h5-leave-pick,
.h5-leave-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.h5-leave-month { margin-bottom: 16rpx; }
.h5-leave-switch { color: #414755; }
.h5-leave-pick.is-empty { color: #8b93a7; }
.h5-leave-pick text:first-child {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.h5-leave-chev { flex: none; color: #0057c2; font-size: 40rpx; line-height: 1; }
.h5-leave-card,
.h5-leave-hero,
.h5-leave-sheet,
.h5-leave-option,
.h5-leave-search { margin-bottom: 16rpx; }
.h5-leave-card,
.h5-leave-hero { display: flex; align-items: center; gap: 16rpx; padding: 24rpx; }
.h5-leave-hero { flex-direction: column; align-items: flex-start; }
.h5-leave-card__main { flex: 1; min-width: 0; }
.h5-leave-name { color: #181b23; font-size: 32rpx; font-weight: 750; }
.h5-leave-meta { display: block; margin-top: 8rpx; color: #414755; font-size: 24rpx; line-height: 1.4; }
.h5-leave-days { display: flex; flex: none; flex-direction: column; align-items: flex-end; color: #0057c2; }
.h5-leave-days strong,
.h5-leave-hero__days { font-size: 40rpx; font-weight: 750; line-height: 1; }
.h5-leave-hero__days { color: #0057c2; }
.h5-leave-days text { margin-top: 4rpx; font-size: 22rpx; }
.h5-leave-sheet { padding: 8rpx 24rpx 28rpx; }
.h5-leave-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24rpx;
  min-height: 88rpx;
  border-bottom: 1rpx solid rgba(60, 60, 67, 0.08);
}
.h5-leave-line text:first-child { flex: none; color: #414755; font-size: 26rpx; }
.h5-leave-line text:last-child { flex: 1; min-width: 0; color: #181b23; font-size: 28rpx; text-align: right; word-break: break-all; }
.h5-leave-field { margin-top: 20rpx; }
.h5-leave-field picker { display: block; width: 100%; }
.h5-leave-label { display: block; margin: 0 0 10rpx; color: #414755; font-size: 26rpx; font-weight: 650; }
.h5-leave-label .req { margin-left: 4rpx; color: #ba1a1a; }
.h5-leave-halves { display: flex; gap: 12rpx; margin-top: 12rpx; }
.h5-leave-halves text {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  height: 80rpx;
  border-radius: 16rpx;
  background: #f4f7fb;
  color: #414755;
  font-size: 30rpx;
}
.h5-leave-halves text.on { background: #0057c2; color: #fff; font-weight: 750; }
.h5-leave-count {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-top: 24rpx;
  color: #181b23;
}
.h5-leave-count strong { color: #0057c2; font-size: 40rpx; }
.h5-leave-hint { display: block; margin-top: 12rpx; color: #414755; font-size: 24rpx; line-height: 1.5; }
.h5-leave-switch { margin-top: 12rpx; }
.h5-leave-switch.on { border-color: #0057c2; background: rgba(0, 87, 194, 0.08); color: #0057c2; font-weight: 750; }
.h5-leave-search { display: flex; align-items: center; padding: 8rpx 8rpx 8rpx 24rpx; }
.h5-leave-search input { flex: 1; height: 72rpx; min-width: 0; color: #181b23; font-size: 28rpx; }
.h5-leave-option { display: flex; align-items: center; justify-content: space-between; min-height: 96rpx; padding: 0 24rpx; color: #181b23; font-size: 30rpx; }
.h5-leave-dock { display: flex; gap: 16rpx; }
.h5-leave-primary,
.h5-leave-ghost {
  flex: 1;
  width: auto;
  height: 84rpx;
  margin: 0;
  border: 0;
  border-radius: 16rpx;
  font-size: 28rpx;
  font-weight: 750;
  line-height: 84rpx;
}
.h5-leave-primary::after,
.h5-leave-ghost::after { border: 0; }
.h5-leave-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.9); }
.h5-leave-ghost { background: #fff; color: #ba1a1a; }
</style>
