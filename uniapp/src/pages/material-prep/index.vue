<template>
  <app-nav-bar />
  <view class="page h5-prep" :class="{ 'h5-prep--detail': mode === 'form' }">
    <template v-if="mode === 'list'">
      <view class="h5-prep-bar">
        <text>未完成的生产单</text>
        <text class="h5-prep-bar__link" @click="openQrs">备料码</text>
      </view>
      <view v-if="!orders.length" class="h5-prep-empty">没有需要备料的生产单</view>
      <view v-for="row in orders" :key="row.header_id" class="card h5-prep-order">
        <view class="h5-prep-order__no">{{ row.header_no }}</view>
        <view class="h5-prep-grid">
          <view><text>工厂型号</text><strong>{{ row.product_code || '—' }}</strong></view>
          <view><text>颜色</text><strong>{{ row.color_name || '—' }}</strong></view>
          <view><text>数量</text><strong>{{ row.total_qty }}</strong></view>
          <view><text>已备</text><strong>{{ row.prepared_pairs }}</strong></view>
        </view>
        <button class="h5-prep-go" @click="openPrep(row)">备料</button>
      </view>
    </template>

    <template v-else-if="mode === 'qrs'">
      <view class="h5-prep-qrs">
        <view v-for="qr in qrs" :key="qr.slot" class="card h5-prep-qr" :class="{ busy: qr.occupied }">
          <image v-if="qr.qr_png" :src="qr.qr_png" mode="aspectFit" />
          <view class="h5-prep-qr__body">
            <text class="h5-prep-qr__slot">备料码 {{ qr.slot }}</text>
            <text class="h5-prep-qr__state">{{ qr.occupied ? `占用 ${qr.header_no} · 备料 ${qr.pairs || 0} 双` : '空闲' }}</text>
            <view v-if="qr.occupied && qr.lines?.length" class="h5-prep-qr__lines">
              <view v-for="line in qr.lines" :key="line.id" class="h5-prep-qr__line">
                <text class="h5-prep-qr__name">{{ line.material_name }}{{ line.color_name ? ` · ${line.color_name}` : '' }}</text>
                <text>{{ line.actual_qty }} {{ line.unit_name }}{{ line.customer_supplied ? ' 客供' : '' }}</text>
              </view>
            </view>
            <button v-if="qr.occupied" class="h5-prep-qr__release" @click="releaseQr(qr)">取消占用</button>
          </view>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'done' && slip">
      <view class="card h5-prep-done">
        <text class="h5-prep-done__slot">已绑定备料码 {{ slip.slot }}</text>
        <text class="h5-prep-done__hint">仓库已按实际数量扣减。把这张码跟物料放在一起，领料人扫码确认。</text>
        <image v-if="slip.qr_png" class="h5-prep-done__img" :src="slip.qr_png" mode="aspectFit" />
        <text>{{ slip.header_no }} · {{ slip.pairs }} 双</text>
      </view>
      <button class="h5-prep-go h5-prep-go--block" @click="backToList">返回列表</button>
    </template>

    <template v-else>
      <view class="card h5-prep-head">
        <text class="h5-prep-order__no">{{ current?.header_no }}</text>
        <text class="h5-prep-head__meta">{{ current?.product_code || '—' }} · {{ current?.color_name || '—' }} · {{ current?.total_qty || 0 }} 双</text>
        <text class="h5-prep-head__meta">已备 {{ current?.prepared_pairs ?? 0 }} 双</text>
        <text class="h5-prep-head__meta">{{ segmentLabel }}</text>
      </view>
      <view class="card h5-prep-pairs">
        <text>双数</text>
        <input v-model="pairs" type="number" placeholder="输入要备的双数" @input="onPairs" />
      </view>
      <view v-if="!pairCount" class="h5-prep-empty">输入双数后显示第一工序段的物料</view>
      <view v-else-if="!materials.length" class="h5-prep-empty">这一段没有可备的物料</view>
      <view v-for="line in materials" :key="line.supplier_product_id" class="card h5-prep-line">
        <image v-if="displayImageUrl(line.image_url)" class="h5-prep-line__img" :src="displayImageUrl(line.image_url)" mode="aspectFill" />
        <view v-else class="h5-prep-line__img h5-prep-line__img--empty">{{ swatch(line) }}</view>
        <view class="h5-prep-line__main">
          <text class="h5-prep-line__code">{{ line.material_code || '—' }}</text>
          <text class="h5-prep-line__name">{{ line.material_name }}</text>
          <view class="h5-prep-line__meta">
            <text>{{ line.color_name || '—' }}</text>
            <text>数量 {{ line.qty }}</text>
            <text>{{ line.unit_name || '' }}</text>
            <text v-if="line.customer_supplied">客供</text>
          </view>
          <view class="h5-prep-line__actual">
            <text>实际数量</text>
            <input :value="line.actual_qty" type="text" @input="onActual(line, $event)" />
          </view>
        </view>
      </view>
      <view v-if="pairCount && materials.length" class="h5-prep-submit">
        <button class="h5-prep-go h5-prep-go--block" :disabled="submitting" @click="submit">{{ submitting ? '提交中…' : '确认备料' }}</button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onBackPress, onLoad, onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const mode = ref<'list' | 'form' | 'qrs' | 'done'>('list')
const orders = ref<any[]>([])
const qrs = ref<any[]>([])
const current = ref<any>(null)
const materials = ref<any[]>([])
const segmentName = ref('')
const pairs = ref('')
const slip = ref<any>(null)
const submitting = ref(false)
const pairCount = computed(() => {
  const value = Number(pairs.value)
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0
})
const segmentLabel = computed(() => (segmentName.value ? `${segmentName.value} · 第一工序段` : '第一工序段'))

function pageOrigin() {
  // 备料码内容是站点上的确认链接，手机扫一扫按路径打开确认页。
  // #ifdef H5
  if (typeof location !== 'undefined') return location.origin
  // #endif
  return ''
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function swatch(line: any) {
  return String(line.material_name || line.material_code || '料').trim().slice(0, 1)
}
function qtyText(value: number) {
  if (!Number.isFinite(value)) return '0'
  const text = value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  return text || '0'
}
function applyPairs() {
  const count = pairCount.value
  materials.value = materials.value.map((line) => {
    const qty = qtyText(Number(line.qty_per_pair || 0) * count)
    return line.dirty ? { ...line, qty } : { ...line, qty, actual_qty: qty }
  })
}
function onPairs() {
  applyPairs()
}
function onActual(line: any, event: any) {
  const value = String(event?.detail?.value ?? '')
  line.dirty = true
  line.actual_qty = value
}

async function loadOrders() {
  orders.value = await get('/material-preps/orders')
}
async function openQrs() {
  mode.value = 'qrs'
  qrs.value = await get(`/material-preps/qrs?origin=${encodeURIComponent(pageOrigin())}`)
}
function releaseQr(qr: any) {
  if (!qr?.occupied) return
  uni.showModal({
    title: '取消占用',
    content: `备料码 ${qr.slot} 取消后，已扣数量会退回仓库。`,
    confirmText: '取消占用',
    success: async (result) => {
      if (!result.confirm) return
      try {
        await post(`/material-preps/qrs/${qr.slot}/release`, {})
        uni.showToast({ title: '已退回仓库', icon: 'none' })
        await openQrs()
      } catch (error: any) {
        uni.showToast({ title: error?.message || '取消失败', icon: 'none' })
      }
    },
  })
}
async function openPrep(row: any) {
  current.value = row
  pairs.value = ''
  materials.value = []
  mode.value = 'form'
  try {
    const data = await get(`/material-preps/orders/${row.header_id}/materials`)
    segmentName.value = data?.segment_name || ''
    materials.value = (data?.lines || []).map((line: any) => ({ ...line, qty: '0', actual_qty: '0', dirty: false }))
  } catch (error: any) {
    uni.showToast({ title: error?.message || '物料加载失败', icon: 'none' })
  }
}
async function submit() {
  if (submitting.value || !current.value) return
  const count = pairCount.value
  if (!count) return uni.showToast({ title: '请输入双数', icon: 'none' })
  const lines = materials.value
    .map((line) => ({
      supplier_product_id: line.supplier_product_id,
      actual_qty: Number(line.actual_qty || 0),
    }))
    .filter((line) => line.actual_qty > 0)
  if (!lines.length) return uni.showToast({ title: '请填写实际数量', icon: 'none' })
  submitting.value = true
  try {
    slip.value = await post('/material-preps', {
      header_id: current.value.header_id,
      pairs: count,
      origin: pageOrigin(),
      lines,
    })
    mode.value = 'done'
    uni.showToast({ title: `已绑定备料码 ${slip.value?.slot || ''}`, icon: 'none' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '备料失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
async function backToList() {
  mode.value = 'list'
  slip.value = null
  await loadOrders()
}

onLoad(() => {
  uni.setNavigationBarTitle({ title: '备料' })
})
onBackPress(() => {
  if (mode.value !== 'form' && mode.value !== 'qrs') return false
  mode.value = 'list'
  return true
})
onShow(() => {
  if (mode.value === 'list') loadOrders().catch((error: any) => uni.showToast({ title: error?.message || '加载失败', icon: 'none' }))
})
onPullDownRefresh(async () => {
  try {
    if (mode.value === 'qrs') await openQrs()
    else if (mode.value === 'list') await loadOrders()
  } finally {
    uni.stopPullDownRefresh()
  }
})
</script>

<style scoped lang="scss">
.h5-prep { padding-bottom: 140rpx; }
.h5-prep-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
  color: #414755;
  font-size: 24rpx;
}
.h5-prep-bar__link { color: #0057c2; }
.h5-prep-empty { padding: 48rpx 0; color: #727786; text-align: center; font-size: 26rpx; }
.h5-prep-order, .h5-prep-head, .h5-prep-pairs, .h5-prep-line, .h5-prep-done, .h5-prep-qr {
  margin-bottom: 16rpx;
  padding: 24rpx;
  background: #fff;
  border-radius: 20rpx;
}
.h5-prep-order__no { color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-prep-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12rpx 20rpx;
  margin-top: 16rpx;
}
.h5-prep-grid text { display: block; color: #727786; font-size: 22rpx; }
.h5-prep-grid strong { color: #181b23; font-size: 28rpx; font-weight: 400; }
.h5-prep-go {
  height: 72rpx;
  margin-top: 18rpx;
  border: 0;
  border-radius: 14rpx;
  background: #0057c2;
  color: #fff;
  font-size: 28rpx;
  font-weight: 750;
  line-height: 72rpx;
}
.h5-prep-go::after { border: 0; }
.h5-prep-go--block { width: 100%; }
.h5-prep-head__meta { display: block; margin-top: 8rpx; color: #414755; font-size: 24rpx; }
.h5-prep-pairs { display: flex; align-items: center; gap: 20rpx; }
.h5-prep-pairs text { color: #181b23; font-size: 28rpx; font-weight: 750; }
.h5-prep-pairs input, .h5-prep-line__actual input {
  flex: 1;
  height: 72rpx;
  padding: 0 20rpx;
  border-radius: 12rpx;
  background: #f5f7fa;
  color: #181b23;
  font-size: 30rpx;
}
.h5-prep-line { display: flex; gap: 16rpx; }
.h5-prep-line__img {
  width: 112rpx;
  height: 112rpx;
  border-radius: 16rpx;
  background: #f5f7fa;
}
.h5-prep-line__img--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0057c2;
  font-size: 40rpx;
  font-weight: 750;
}
.h5-prep-line__main { flex: 1; min-width: 0; }
.h5-prep-line__code { color: #727786; font-size: 22rpx; }
.h5-prep-line__name { display: block; margin-top: 4rpx; color: #181b23; font-size: 28rpx; font-weight: 750; }
.h5-prep-line__meta { display: flex; flex-wrap: wrap; gap: 8rpx 16rpx; margin-top: 8rpx; color: #414755; font-size: 24rpx; }
.h5-prep-line__actual { display: flex; align-items: center; gap: 12rpx; margin-top: 12rpx; }
.h5-prep-line__actual text { color: #181b23; font-size: 24rpx; }
.h5-prep-submit { position: fixed; right: 24rpx; bottom: 24rpx; left: 24rpx; }
.h5-prep-done { text-align: center; }
.h5-prep-done__slot { display: block; color: #181b23; font-size: 40rpx; font-weight: 750; }
.h5-prep-done__hint { display: block; margin: 16rpx 0; color: #414755; font-size: 26rpx; line-height: 1.5; }
.h5-prep-done__img { width: 360rpx; height: 360rpx; margin: 12rpx auto; }
.h5-prep-qrs { display: flex; flex-direction: column; gap: 16rpx; }
.h5-prep-qr { display: flex; gap: 16rpx; align-items: flex-start; }
.h5-prep-qr > image { width: 180rpx; height: 180rpx; flex: none; }
.h5-prep-qr__body { flex: 1; min-width: 0; }
.h5-prep-qr__slot { display: block; color: #181b23; font-size: 32rpx; font-weight: 750; }
.h5-prep-qr__release {
  height: 64rpx;
  margin: 16rpx 0 0;
  padding: 0 20rpx;
  border: 1px solid #e7c4b0;
  border-radius: 10rpx;
  background: #fff;
  color: #9a3412;
  font-size: 28rpx;
  line-height: 62rpx;
}
.h5-prep-qr__release::after { border: 0; }
.h5-prep-qr__state { display: block; margin-top: 6rpx; color: #266d00; font-size: 26rpx; }
.h5-prep-qr.busy .h5-prep-qr__state { color: #7d5400; }
.h5-prep-qr__lines { margin-top: 12rpx; }
.h5-prep-qr__line {
  display: flex;
  justify-content: space-between;
  gap: 12rpx;
  margin-top: 6rpx;
  color: #414755;
  font-size: 28rpx;
}
.h5-prep-qr__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #181b23;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.h5-prep--detail {
  .h5-prep-order__no { font-size: 34rpx; }
  .h5-prep-head__meta { font-size: 28rpx; }
  .h5-prep-empty { font-size: 30rpx; }
  .h5-prep-pairs text { font-size: 32rpx; }
  .h5-prep-pairs input,
  .h5-prep-line__actual input { height: 80rpx; font-size: 34rpx; }
  .h5-prep-line__code { font-size: 26rpx; }
  .h5-prep-line__name { font-size: 32rpx; }
  .h5-prep-line__meta,
  .h5-prep-line__actual text { font-size: 28rpx; }
  .h5-prep-line__img--empty { font-size: 44rpx; }
  .h5-prep-go { height: 80rpx; font-size: 32rpx; line-height: 80rpx; }
}
</style>
