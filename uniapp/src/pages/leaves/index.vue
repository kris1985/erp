<template>
  <app-nav-bar />
  <view class="page h5-leave">
    <view v-if="!canSee" class="h5-leave-empty">没有请假登记权限</view>
    <template v-else>
      <view v-if="!editing">
        <view class="h5-leave-bar">
          <picker mode="date" fields="month" :value="month" @change="month = String($event.detail.value).slice(0, 7); load()">
            <text>{{ month }}</text>
          </picker>
          <text v-if="canWrite" class="h5-leave-add" @click="openCreate">＋ 登记</text>
        </view>
        <view v-if="!rows.length" class="h5-leave-empty">这个月还没有请假</view>
        <view v-for="row in rows" :key="row.id" class="card h5-leave-card" @click="openEdit(row)">
          <strong>{{ row.worker_name }}</strong>
          <text>{{ rangeText(row) }}</text>
          <text>{{ Number(row.days || 0).toFixed(1) }} 天</text>
          <view class="h5-leave-flags">
            <text>工资</text><text v-if="row.pay_salary" class="hook">✓</text>
            <text>餐补</text><text v-if="row.pay_meal" class="hook">✓</text>
            <text>住宿补</text><text v-if="row.pay_housing" class="hook">✓</text>
            <text>其它补</text><text v-if="row.pay_other" class="hook">✓</text>
          </view>
        </view>
      </view>
      <view v-else class="card h5-leave-card">
        <text class="h5-leave-title">{{ form.id ? '编辑请假' : '登记请假' }}</text>
        <view class="h5-leave-field" @click="pickWorker">
          <text>员工</text>
          <text>{{ workerName || '选择员工' }}</text>
        </view>
        <view class="h5-leave-field">
          <text>开始</text>
          <picker mode="date" :value="form.start_date" @change="form.start_date = $event.detail.value"><text>{{ form.start_date || '日期' }}</text></picker>
          <text :class="{ on: form.start_half === 'am' }" @click="form.start_half = 'am'">上午</text>
          <text :class="{ on: form.start_half === 'pm' }" @click="form.start_half = 'pm'">下午</text>
        </view>
        <view class="h5-leave-field">
          <text>结束</text>
          <picker mode="date" :value="form.end_date" @change="form.end_date = $event.detail.value"><text>{{ form.end_date || '日期' }}</text></picker>
          <text :class="{ on: form.end_half === 'am' }" @click="form.end_half = 'am'">上午</text>
          <text :class="{ on: form.end_half === 'pm' }" @click="form.end_half = 'pm'">下午</text>
        </view>
        <text class="h5-leave-hint">同一天只选上午或下午是半天，上午到下午是一天。不勾工资就按日工资扣，日工资四舍五入到元。</text>
        <view class="h5-leave-chips">
          <text :class="{ on: form.pay_salary }" @click="form.pay_salary = !form.pay_salary">工资</text>
          <text :class="{ on: form.pay_meal }" @click="form.pay_meal = !form.pay_meal">餐补</text>
          <text :class="{ on: form.pay_housing }" @click="form.pay_housing = !form.pay_housing">住宿补</text>
          <text :class="{ on: form.pay_other }" @click="form.pay_other = !form.pay_other">其它补</text>
        </view>
        <input v-model="form.notes" class="h5-leave-note" placeholder="请假原因" />
        <view class="h5-leave-actions">
          <text @click="editing = false">返回</text>
          <text v-if="form.id && canWrite" class="danger" @click="remove">删除</text>
          <text v-if="canWrite" class="primary" @click="save">保存</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { del, get, patch, post } from '../../services/http'
import { getProfile } from '../../services/storage'

const profile = ref(getProfile())
const canSee = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('leaves') || features.includes('leaves_write')
})
const canWrite = computed(() => (profile.value?.featurePermissions || []).includes('leaves_write'))
const month = ref(new Date().toISOString().slice(0, 7))
const rows = ref<any[]>([])
const workers = ref<any[]>([])
const editing = ref(false)
const form = ref<any>(emptyForm())

const workerName = computed(() => workers.value.find((row) => row.id === form.value.worker_id)?.name || '')

function emptyForm() {
  const today = new Date().toISOString().slice(0, 10)
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
function monthRange(value: string) {
  const [year, mon] = value.split('-').map(Number)
  const last = new Date(year, mon, 0).getDate()
  const pad = String(mon).padStart(2, '0')
  return { date_from: `${year}-${pad}-01`, date_to: `${year}-${pad}-${String(last).padStart(2, '0')}` }
}
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
async function load() {
  profile.value = getProfile()
  if (!canSee.value) return
  try {
    const range = monthRange(month.value)
    rows.value = await get<any[]>('/leaves', range)
    const staff: any = await get('/workers', { page: 1, page_size: 500, is_active: true })
    workers.value = staff?.items || []
  } catch (error: any) {
    toast(error?.message || '加载失败')
  } finally {
    uni.stopPullDownRefresh()
  }
}
function openCreate() {
  if (!canWrite.value) return
  form.value = emptyForm()
  editing.value = true
}
function openEdit(row: any) {
  form.value = { ...row, notes: row.notes || '' }
  editing.value = true
}
function pickWorker() {
  if (!workers.value.length) {
    toast('没有可选员工')
    return
  }
  uni.showActionSheet({
    itemList: workers.value.slice(0, 20).map((row) => row.name),
    success: (result) => {
      form.value.worker_id = workers.value[result.tapIndex]?.id
    },
  })
}
async function save() {
  if (!form.value.worker_id || !form.value.start_date || !form.value.end_date) {
    toast('请选择员工和时间')
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
  try {
    if (form.value.id) await patch(`/leaves/${form.value.id}`, body)
    else await post('/leaves', body)
    toast('已保存')
    editing.value = false
    await load()
  } catch (error: any) {
    toast(error?.message || '保存失败')
  }
}
function remove() {
  uni.showModal({
    title: '删除请假',
    content: '删除这条请假？',
    success: async (result) => {
      if (!result.confirm || !form.value.id) return
      try {
        await del(`/leaves/${form.value.id}`)
        editing.value = false
        await load()
      } catch (error: any) {
        toast(error?.message || '删除失败')
      }
    },
  })
}
onShow(load)
onPullDownRefresh(load)
</script>

<style scoped>
.h5-leave { padding: 24rpx; }
.h5-leave-empty { padding: 80rpx 0; text-align: center; color: #8b93a7; }
.h5-leave-bar, .h5-leave-field, .h5-leave-actions, .h5-leave-chips { display: flex; align-items: center; gap: 16rpx; flex-wrap: wrap; }
.h5-leave-bar { justify-content: space-between; margin-bottom: 20rpx; }
.h5-leave-add, .primary { color: #0057c2; font-weight: 700; }
.h5-leave-card { display: flex; flex-direction: column; gap: 8rpx; margin-bottom: 16rpx; padding: 24rpx; }
.h5-leave-flags { display: flex; gap: 20rpx; color: #5c6578; font-size: 24rpx; }
.h5-leave-flags .hook { color: #067a3e; font-weight: 700; }
.h5-leave-title { font-size: 32rpx; font-weight: 700; }
.h5-leave-field { margin-top: 20rpx; }
.h5-leave-field text.on, .h5-leave-chips text.on { color: #0057c2; font-weight: 700; }
.h5-leave-chips { margin-top: 20rpx; }
.h5-leave-chips text { padding: 8rpx 20rpx; border-radius: 999rpx; background: #f3f5f8; }
.h5-leave-hint { display: block; margin-top: 16rpx; color: #8b93a7; font-size: 24rpx; }
.h5-leave-note { margin-top: 16rpx; padding: 16rpx; background: #f7f8fa; border-radius: 12rpx; }
.h5-leave-actions { margin-top: 24rpx; justify-content: flex-end; }
.danger { color: #c03639; }
</style>
