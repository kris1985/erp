<template>
  <view class="page h5-home-page">
    <view v-if="loading" class="h5-home-empty">加载中…</view>
    <view v-else-if="!defects.length" class="h5-home-empty">暂无报废记录</view>
    <view v-else class="h5-defect-list">
      <view v-for="row in defects" :key="row.id" class="card h5-defect-row">
        <view class="h5-defect-head">
          <view><strong>{{ row.order_no || '未关联生产单' }}</strong><text>{{ formatTime(row.created_at) }}</text></view>
          <text :class="['h5-defect-status', { confirmed: row.status === 'closed', pending: row.needs_my_confirm }]">{{ defectStatusText(row) }}</text>
        </view>
        <view class="h5-defect-content">
          <view class="h5-defect-visual">
            <image v-if="row.product_image_url" class="h5-defect-photo" :src="displayImageUrl(row.product_image_url)" mode="aspectFill" @click="previewDefectPhotos([row.product_image_url])" />
            <view v-else class="h5-defect-photo h5-defect-photo--empty">暂无图片</view>
            <image
              v-if="row.photo_urls?.length"
              class="h5-defect-scene"
              :src="displayImageUrl(row.photo_urls[0])"
              mode="aspectFill"
              @click.stop="previewDefectPhotos(row.photo_urls)"
            />
          </view>
          <view class="h5-defect-detail">
            <view class="h5-defect-product"><text>工厂型号</text><strong>{{ row.product_code || '—' }}</strong></view>
            <view class="h5-defect-meta"><text>{{ row.brand_name || '未填品牌' }}</text><text>{{ defectFoundLabel(row) }}</text></view>
            <view class="h5-defect-size">
              <text v-for="size in defectSizeRows(row)" :key="size.id || size.size_id">{{ size.size_value || '—' }}码 左{{ size.left_qty || 0 }} 右{{ size.right_qty || 0 }}</text>
              <strong>共 {{ row.qty || 0 }}</strong>
            </view>
            <view class="h5-defect-loss"><text>损失</text><strong>¥{{ money(row.loss_amount) }}</strong><text v-if="responsibilityText(row)">{{ responsibilityText(row) }}</text></view>
          </view>
        </view>
        <view class="h5-defect-foot">
          <text>登记人：{{ row.found_by_worker_name || row.found_by_user_name || '—' }}</text>
          <button v-if="canConfirm && row.needs_my_confirm" :loading="confirmingId === row.id" @click.stop="confirmDefect(row)">主管确认</button>
        </view>
      </view>
    </view>
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'

const profile = ref(getProfile())
const defects = ref<any[]>([]), loading = ref(false), confirmingId = ref<number | null>(null)
const canConfirm = computed(() => ['admin', 'manager', 'leader'].includes(profile.value?.role || '') || Boolean(profile.value?.isLeader))
const money = (v: unknown) => Number(v || 0).toFixed(2)
function defectSizeRows(row: any) {
  return Array.isArray(row?.sizes) && row.sizes.length
    ? row.sizes
    : [{ id: row?.id, size_id: row?.size_id, size_value: row?.size_value, left_qty: row?.left_qty, right_qty: row?.right_qty, qty: row?.qty }]
}
function defectFoundLabel(row: any) {
  if (row?.manual_materials?.finished_goods) return '成品报废'
  return row?.found_process_name || '未填发现工序'
}
function defectStatusText(row: any) {
  if (row.status === 'closed') return '已确认'
  if (row.needs_my_confirm) return '待主管确认'
  return '已登记'
}
const formatTime = (v?: string) => {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 16).replace('T', ' ')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewDefectPhotos(urls: string[]) {
  const resolved = (urls || []).map(displayImageUrl).filter(Boolean)
  if (resolved.length) uni.previewImage({ urls: resolved, current: resolved[0] })
}
function responsibilityText(row: any) {
  const workers = (row.responsibilities || []).map((item: any) => `${item.worker_name || '员工'} ¥${money(item.deduction_amount)}`)
  const employeeAmount = (row.responsibilities || []).reduce((sum: number, item: any) => sum + Number(item.deduction_amount || 0), 0)
  const companyAmount = Math.max(0, Number(row.loss_amount || 0) - employeeAmount)
  return [`公司 ¥${money(companyAmount)}`, ...workers].join(' · ')
}
async function load() {
  loading.value = true
  profile.value = getProfile()
  try {
    const result: any = await get('/defect-events', { page_size: 50 })
    defects.value = result?.items || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '报废记录加载失败', icon: 'none' })
  } finally { loading.value = false }
}
function confirmDefect(row: any) {
  uni.showModal({
    title: '确认报废',
    content: `确认 ${row.order_no || ''} ${row.size_value || ''}码，共${row.qty || 0}只报废？确认后报工入账，材料计入仓库生产需求，然后才能打印补单。`,
    success: async result => {
      if (!result.confirm) return
      confirmingId.value = row.id
      try {
        await post(`/defect-events/${row.id}/supervisor-confirm`, {})
        uni.showToast({ title: '已确认', icon: 'success' })
        await load()
      } catch (e: any) {
        uni.showToast({ title: e?.message || '确认失败', icon: 'none' })
      } finally { confirmingId.value = null }
    },
  })
}
onShow(load)
</script>
