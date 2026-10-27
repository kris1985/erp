<template>
  <app-nav-bar />
  <view class="page h5-cut" :class="{ 'h5-cut--bar': showApply }">
    <view v-if="!canSee" class="card h5-cut-empty"><strong>没有裁断用料权限</strong><text>请让管理员在手机功能里勾选</text></view>

    <!-- 打开即列出全部用料，型号写在每一组上 -->
    <template v-else-if="mode === 'usage'">
      <view class="card h5-cut-search">
        <input v-model="keyword" confirm-type="search" placeholder="搜索工厂型号" />
      </view>
      <view v-if="usageLoading && !colors.length" class="h5-cut-empty">正在汇总裁断用料…</view>
      <view v-else-if="!colors.length" class="card h5-cut-empty"><strong>还没有裁断领料或报工</strong><text>签收领料、合格报工之后会出现在这里</text></view>
      <view v-else-if="!visibleColors.length" class="card h5-cut-empty"><strong>没有匹配的工厂型号</strong></view>
      <view v-else class="h5-cut-list">
        <view v-for="color in visibleColors" :key="color.own_product_id" class="card h5-cut-color">
          <view class="h5-cut-color__head">
            <image v-if="color.image_url" :src="displayImageUrl(color.image_url)" mode="aspectFill" @click="previewImage(color.image_url)" />
            <view v-else class="h5-cut-ph">{{ swatch(color.factory_model) }}</view>
            <view class="h5-cut-color__title">
              <strong>{{ color.factory_model || '未填型号' }}</strong>
              <text>{{ color.order_color_name || '未分色' }} · {{ formatQty(color.total_pairs) }} 双</text>
            </view>
          </view>
          <view
            v-for="material in color.materials || []"
            :key="materialKey(color, material)"
            class="h5-cut-mat"
            @click="openMaterial(color, material)"
          >
            <view class="h5-cut-mat__top">
              <image v-if="material.image_url" :src="displayImageUrl(material.image_url)" mode="aspectFill" @click.stop="previewImage(material.image_url)" />
              <view v-else class="h5-cut-ph">{{ swatch(material.material_name || material.material_code) }}</view>
              <view class="h5-cut-mat__body">
                <view class="h5-cut-mat__title">
                  <strong>{{ material.material_name || material.material_code || '未命名物料' }}</strong>
                  <text v-if="material.material_code && material.material_name">{{ material.material_code }}</text>
                  <text v-if="material.color_name">{{ material.color_name }}</text>
                  <text v-if="!material.on_bom" class="h5-cut-tag">未在产品用料</text>
                </view>
                <view class="h5-cut-line">
                  <view><text>预算</text><strong>{{ perPairText(material.budget_qty, material.unit_name) }}</strong></view>
                  <view><text>实际</text><strong :class="usageClass(material)">{{ formatQty(material.average_usage) }}</strong></view>
                </view>
              </view>
            </view>
          </view>
        </view>
      </view>
    </template>

    <!-- 物料下的领料人：消耗、报工、每双用量 -->
    <template v-else-if="mode === 'people' && currentMaterial">
      <view class="card h5-cut-hero">
        <view class="h5-cut-hero__top">
          <image v-if="currentMaterial.image_url" :src="displayImageUrl(currentMaterial.image_url)" mode="aspectFill" @click="previewImage(currentMaterial.image_url)" />
          <view v-else class="h5-cut-ph">{{ swatch(currentMaterial.material_name) }}</view>
          <view class="h5-cut-hero__main">
            <strong>{{ currentMaterial.material_name || currentMaterial.material_code || '未命名物料' }}</strong>
            <text>{{ materialMeta(currentMaterial) }}</text>
            <text>{{ [currentColor?.factory_model, currentColor?.order_color_name || '未分色'].filter(Boolean).join(' · ') }} · 报工 {{ formatQty(currentColor?.total_pairs) }} 双</text>
          </view>
          <view v-if="canOpenHistory" class="h5-cut-history-btn" @click="openHistory">
            <image src="/static/icons/history.svg" mode="aspectFit" />
          </view>
        </view>
        <view class="h5-cut-pair">
          <view>
            <text>预算用量</text>
            <strong>{{ usageText(currentMaterial.budget_qty, currentMaterial.unit_name) }}</strong>
          </view>
          <view>
            <text>实际平均</text>
            <strong :class="usageClass(currentMaterial)">{{ usageText(currentMaterial.average_usage, currentMaterial.unit_name) }}</strong>
          </view>
        </view>
      </view>
      <view v-if="!people.length" class="card h5-cut-empty"><strong>还没有人领过这颗料</strong></view>
      <view v-else class="h5-cut-list">
        <view v-for="person in people" :key="person.id" class="card h5-cut-person">
          <strong class="h5-cut-person__name">{{ person.name }}</strong>
          <view class="h5-cut-metrics">
            <view><text>消耗/报工</text><strong>{{ consumedText(person) }}</strong></view>
            <view><text>每双用量</text><strong>{{ usageText(person.pickup?.usage_per_pair, currentMaterial.unit_name) }}</strong></view>
          </view>
        </view>
      </view>
    </template>

    <!-- 一个人的领料、退料、报工流水 -->
    <template v-else-if="mode === 'records'">
      <view v-if="!records.length" class="card h5-cut-empty"><strong>没有领退或报工记录</strong></view>
      <view v-else class="h5-cut-list">
        <view v-for="record in records" :key="record.event_key || record.work_log_id" class="card h5-cut-rec">
          <view class="h5-cut-rec__head">
            <text :class="`h5-cut-kind h5-cut-kind--${record.kind}`">{{ kindLabel(record.kind) }}</text>
            <text>{{ record.reported_at || '—' }}</text>
          </view>
          <strong>{{ record.header_no || '—' }}</strong>
          <view class="h5-cut-metrics">
            <view v-if="record.issued_qty != null"><text>领料</text><strong>{{ record.issued_qty }}</strong></view>
            <view v-if="record.opening_qty != null"><text>上次剩余</text><strong>{{ record.opening_qty }}</strong></view>
            <view v-if="record.return_qty != null"><text>退仓库</text><strong>{{ record.return_qty }}</strong></view>
            <view v-if="record.consumed_qty != null"><text>消耗</text><strong>{{ record.consumed_qty }}</strong></view>
            <view v-if="record.pairs != null"><text>报工</text><strong>{{ record.pairs }} 双</strong></view>
            <view><text>车间剩余</text><strong>{{ record.remain_qty ?? '—' }}</strong></view>
          </view>
        </view>
      </view>
    </template>

    <!-- 产品用量变更记录 -->
    <template v-else-if="mode === 'history'">
      <view v-if="historyLoading" class="h5-cut-empty">正在读取用量历史…</view>
      <view v-else-if="!history.length" class="card h5-cut-empty"><strong>还没有用量变更</strong></view>
      <view v-else class="h5-cut-list">
        <view v-for="item in history" :key="item.id" class="card h5-cut-history">
          <view class="h5-cut-person__head">
            <strong>{{ historyChange(item) }}</strong>
            <text>{{ historyTime(item.changed_at) }}</text>
          </view>
          <text class="h5-cut-history__meta">{{ [sourceLabel(item.source), item.changed_by_name].filter(Boolean).join(' · ') || '用量变更' }}</text>
        </view>
      </view>
    </template>

    <view v-if="showApply" class="cut-sticky-bar h5-cut-bar">
      <button class="primary-button" :disabled="applying" @click="applyAverage">{{ applying ? '正在写入…' : '应用到产品用量' }}</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onBackPress, onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'

type CutRecord = {
  kind: string
  event_key?: string
  work_log_id?: number
  reported_at?: string
  sort_at?: string
  header_no?: string
  issued_qty?: string | null
  opening_qty?: string | null
  return_qty?: string | null
  remain_qty?: string | null
  consumed_qty?: string | null
  pairs?: string | null
}
type CutPickup = {
  issued_qty?: string
  return_qty?: string
  consumed_qty?: string
  usage_per_pair?: string | null
  records?: CutRecord[]
}
type CutMaterial = {
  supplier_product_id?: number | null
  material_code?: string | null
  material_name?: string | null
  image_url?: string | null
  color_name?: string | null
  unit_name?: string | null
  on_bom?: boolean
  budget_qty?: string | null
  average_usage?: string | null
  pickups?: Record<string, CutPickup>
}
type CutColor = {
  own_product_id: number
  factory_model: string
  order_color_name?: string | null
  image_url?: string | null
  total_pairs?: string
  employees?: { id: number; name: string; pairs?: string }[]
  materials?: CutMaterial[]
}
type HistoryItem = {
  id: number
  old_qty?: string | number | null
  new_qty?: string | number | null
  source?: string
  changed_by_name?: string | null
  changed_at?: string | null
}
type PersonRow = {
  id: number
  name: string
  pairs: string
  pickup: CutPickup
  records: CutRecord[]
}

const profile = ref(getProfile())
const mode = ref<'usage' | 'people' | 'records' | 'history'>('usage')
const keyword = ref('')
const usageLoading = ref(false)
const historyLoading = ref(false)
const applying = ref(false)
const colors = ref<CutColor[]>([])
const currentColor = ref<CutColor | null>(null)
const currentMaterial = ref<CutMaterial | null>(null)
const currentPerson = ref<PersonRow | null>(null)
const history = ref<HistoryItem[]>([])
let usageRequest = 0

const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('cut_material_usage') || features.value.includes('cut_material_usage_write'))
const canWrite = computed(() => features.value.includes('cut_material_usage_write'))
const visibleColors = computed(() => {
  const word = keyword.value.trim().toLowerCase()
  if (!word) return colors.value
  return colors.value.filter((color) => (color.factory_model || '').toLowerCase().includes(word))
})
const people = computed(() => peopleOf(currentColor.value, currentMaterial.value))
const records = computed(() => recordsDesc(currentPerson.value?.records || []))
const canOpenHistory = computed(() => Boolean(currentColor.value?.own_product_id && currentMaterial.value?.supplier_product_id))
const showApply = computed(() => mode.value === 'people' && canWrite.value && canApply(currentMaterial.value))

watch(mode, syncTitle)

function syncTitle() {
  const title = mode.value === 'people'
      ? (currentMaterial.value?.material_name || currentMaterial.value?.material_code || '物料')
      : mode.value === 'records'
        ? (currentPerson.value?.name || '明细')
        : mode.value === 'history'
          ? '用量历史'
          : '裁断用料'
  uni.setNavigationBarTitle({ title })
}

function swatch(value?: string | null) {
  return String(value || '料').trim().slice(0, 1)
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url?: string | null) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function formatQty(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return String(Number(amount.toFixed(4)))
}
function perPairText(value: string | number | null | undefined, unit?: string | null) {
  const text = formatQty(value)
  if (text === '—') return text
  return unit ? `${text}${unit}/双` : `${text}/双`
}
function usageText(value: string | number | null | undefined, unit?: string | null) {
  const text = formatQty(value)
  if (text === '—') return text
  return unit ? `${text} ${unit}/双` : `${text}/双`
}
function usageClass(material?: CutMaterial | null) {
  const actual = Number(material?.average_usage)
  const budget = Number(material?.budget_qty)
  if (!Number.isFinite(actual) || !Number.isFinite(budget)) return ''
  if (actual - budget > 0.00005) return 'high'
  return ''
}
function materialMeta(material: CutMaterial) {
  return [material.material_code, material.color_name, material.unit_name].filter(Boolean).join(' · ') || '—'
}
function materialKey(color: CutColor, material: CutMaterial) {
  return `${color.own_product_id}-${material.supplier_product_id || material.material_code || material.material_name}`
}
function canApply(material?: CutMaterial | null) {
  return Boolean(material?.on_bom && material.supplier_product_id && formatQty(material.average_usage) !== '—')
}
function peopleOf(color?: CutColor | null, material?: CutMaterial | null): PersonRow[] {
  if (!color || !material) return []
  return (color.employees || []).flatMap((employee) => {
    const pickup = material.pickups?.[String(employee.id)]
    if (!pickup) return []
    const issued = Number(pickup.issued_qty || 0)
    const returned = Number(pickup.return_qty || 0)
    const moved = (pickup.records || []).some((row) => row.kind === 'issue' || row.kind === 'return')
    if (!(issued > 0 || returned > 0 || moved)) return []
    return [{
      id: employee.id,
      name: employee.name || '未命名',
      pairs: employee.pairs || '0',
      pickup,
      records: pickup.records || [],
    }]
  })
}
function consumedText(person: PersonRow) {
  const unit = currentMaterial.value?.unit_name
  const used = formatQty(person.pickup.consumed_qty)
  const amount = used === '—' ? '0' : used
  return `${unit ? `${amount} ${unit}` : amount}/${formatQty(person.pairs)}双`
}
function recordsDesc(rows: CutRecord[]) {
  return [...rows].sort((a, b) => String(b.sort_at || b.reported_at || '').localeCompare(String(a.sort_at || a.reported_at || '')) || Number(b.work_log_id || 0) - Number(a.work_log_id || 0))
}
function kindLabel(kind: string) {
  if (kind === 'issue') return '领料'
  if (kind === 'return') return '退料'
  return '报工'
}
function sourceLabel(source?: string) {
  if (source === 'cut_average') return ''
  if (source === 'product_create') return '产品创建'
  if (source === 'history_restore') return '历史回填'
  return source ? '产品保存' : ''
}
function historyTime(value?: string | null) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}
function historyChange(item: HistoryItem) {
  const unit = currentMaterial.value?.unit_name
  const next = usageText(item.new_qty, unit)
  if (item.old_qty == null || item.old_qty === '') return `改成 ${next}`
  return `由 ${usageText(item.old_qty, unit)} 改成 ${next}`
}

async function loadUsage() {
  const request = ++usageRequest
  usageLoading.value = true
  try {
    const data = await get<{ models?: CutColor[] }>('/business-report/cut-material-usage', undefined, 60000)
    if (request !== usageRequest) return
    const rows = data?.models || []
    colors.value = rows
    if (currentColor.value && currentMaterial.value) {
      const color = rows.find((row) => row.own_product_id === currentColor.value?.own_product_id) || null
      const material = color?.materials?.find((row) => row.supplier_product_id === currentMaterial.value?.supplier_product_id) || null
      currentColor.value = color
      currentMaterial.value = material
      if (currentPerson.value && material) {
        currentPerson.value = peopleOf(color, material).find((row) => row.id === currentPerson.value?.id) || currentPerson.value
      }
    }
  } catch (error: any) {
    if (request !== usageRequest) return
    uni.showToast({ title: error?.message || '用料汇总失败', icon: 'none' })
  } finally {
    if (request === usageRequest) usageLoading.value = false
  }
}
function openMaterial(color: CutColor, material: CutMaterial) {
  currentColor.value = color
  currentMaterial.value = material
  currentPerson.value = null
  mode.value = 'people'
}
async function openHistory() {
  mode.value = 'history'
  await loadHistory()
}
async function loadHistory() {
  const productId = currentColor.value?.own_product_id
  const supplierId = currentMaterial.value?.supplier_product_id
  if (!productId || !supplierId) return
  historyLoading.value = true
  try {
    const data = await get<{ items?: HistoryItem[] }>('/own-products/material-usage-history', {
      own_product_id: productId,
      supplier_product_id: supplierId,
      limit: 30,
    })
    history.value = data?.items || []
  } catch (error: any) {
    uni.showToast({ title: error?.message || '用量历史读取失败', icon: 'none' })
  } finally {
    historyLoading.value = false
  }
}

function applyAverage() {
  const material = currentMaterial.value
  const color = currentColor.value
  if (!material || !color || !canApply(material) || applying.value) return
  const name = material.material_name || material.material_code || '这颗物料'
  uni.showModal({
    title: '应用到产品用量',
    content: `把「${name}」的用量由 ${usageText(material.budget_qty, material.unit_name)} 改成 ${usageText(material.average_usage, material.unit_name)}`,
    confirmText: '确认',
    success: async (result) => {
      if (!result.confirm) return
      applying.value = true
      try {
        const data = await post<{ changed?: boolean; qty?: string | number }>('/business-report/cut-material-usage/apply', {
          own_product_id: color.own_product_id,
          supplier_product_id: material.supplier_product_id,
        })
        uni.showToast({ title: data?.changed ? `已改为 ${formatQty(data.qty)}` : '产品用量已经是这个数', icon: 'none' })
        await loadUsage()
      } catch (error: any) {
        uni.showToast({ title: error?.message || '写入失败', icon: 'none' })
      } finally {
        applying.value = false
      }
    },
  })
}

function goBack() {
  if (mode.value === 'records' || mode.value === 'history') {
    mode.value = 'people'
    return
  }
  if (mode.value === 'people') mode.value = 'usage'
}
onBackPress(() => {
  if (mode.value !== 'usage') {
    goBack()
    return true
  }
  return false
})
onPullDownRefresh(async () => {
  try {
    if (mode.value === 'history') await loadHistory()
    else await loadUsage()
  } finally {
    uni.stopPullDownRefresh()
  }
})
onShow(() => {
  profile.value = getProfile()
  if (!canSee.value || colors.value.length || usageLoading.value) return
  void loadUsage()
})
</script>

<style scoped lang="scss">
.h5-cut-search {
  margin-bottom: 16rpx;
  padding: 8rpx 24rpx;
}
.h5-cut-search input {
  height: 80rpx;
  font-size: 30rpx;
}
.h5-cut-empty {
  padding: 48rpx 32rpx;
  color: #414755;
  text-align: center;
}
.h5-cut-empty strong,
.h5-cut-empty text {
  display: block;
}
.h5-cut-empty text {
  margin-top: 8rpx;
  color: #727786;
  font-size: 24rpx;
}
.h5-cut-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}
.h5-cut-mat__top,
.h5-cut-hero__top {
  display: flex;
  align-items: center;
  gap: 20rpx;
}
.h5-cut-hero {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  margin-bottom: 32rpx;
}
.h5-cut-hero .h5-cut-pair {
  margin-top: 0;
  padding-top: 20rpx;
  border-top: 1rpx solid rgba(60, 60, 67, 0.1);
}
.h5-cut-hero__main {
  flex: 1;
  min-width: 0;
}
.h5-cut-history-btn {
  display: flex;
  flex: 0 0 64rpx;
  align-items: center;
  justify-content: center;
  width: 64rpx;
  height: 64rpx;
  border-radius: 18rpx;
  background: #e8f0fe;
}
.h5-cut-hero .h5-cut-history-btn image {
  width: 36rpx;
  height: 36rpx;
  flex: 0 0 36rpx;
  border-radius: 0;
  background: transparent;
}
.h5-cut-person__name {
  display: block;
  color: #181b23;
  font-size: 30rpx;
}
.h5-cut-mat__top {
  align-items: flex-start;
}
.h5-cut-mat__body {
  flex: 1;
  min-width: 0;
}
.h5-cut-color__head image,
.h5-cut-mat image,
.h5-cut-hero image,
.h5-cut-ph {
  width: 88rpx;
  height: 88rpx;
  flex: 0 0 88rpx;
  border-radius: 20rpx;
  background: #f5f7fa;
}
.h5-cut-ph {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0057c2;
  font-size: 32rpx;
  font-weight: 700;
}
.h5-cut-mat__title {
  display: flex;
  align-items: center;
  gap: 12rpx;
  min-width: 0;
}
.h5-cut-mat__title strong,
.h5-cut-hero strong,
.h5-cut-rec strong,
.h5-cut-history strong {
  display: block;
  overflow: hidden;
  color: #181b23;
  font-size: 30rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.h5-cut-color {
  padding: 0 0 4rpx;
  overflow: hidden;
}
.h5-cut-person__head,
.h5-cut-rec__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.h5-cut-color__head {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 20rpx 24rpx;
  background: #e8f0fe;
}
.h5-cut-color__title {
  flex: 1;
  min-width: 0;
}
.h5-cut-color__title strong {
  display: block;
  overflow: hidden;
  color: #181b23;
  font-size: 30rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.h5-cut-color__title text {
  display: block;
  margin-top: 4rpx;
  color: #727786;
  font-size: 24rpx;
}
.h5-cut-mat,
.h5-cut-person,
.h5-cut-rec,
.h5-cut-history,
.h5-cut-hero,
.h5-cut-link {
  padding: 24rpx;
}
.h5-cut-mat {
  border-top: 1rpx solid rgba(60, 60, 67, 0.1);
}
.h5-cut-mat__title > text {
  flex: 0 0 auto;
  margin-top: 0;
  color: #727786;
  font-size: 24rpx;
  white-space: nowrap;
}
.h5-cut-mat__title strong {
  flex: 0 1 auto;
  min-width: 0;
}
.h5-cut-line {
  display: flex;
  gap: 88rpx;
  margin-top: 8rpx;
}
.h5-cut-line view {
  display: flex;
  align-items: baseline;
  gap: 8rpx;
}
.h5-cut-line text {
  color: #727786;
  font-size: 24rpx;
}
.h5-cut-line strong {
  color: #181b23;
  font-size: 28rpx;
}
.h5-cut-line strong.high {
  color: #ba1a1a;
}
.h5-cut-hero text,
.h5-cut-history__meta,
.h5-cut-person__head text,
.h5-cut-rec__head text {
  display: block;
  margin-top: 4rpx;
  color: #727786;
  font-size: 24rpx;
}
.h5-cut-tag {
  flex: 0 0 auto;
  padding: 4rpx 12rpx;
  border-radius: 999rpx;
  background: #f5f7fa;
  color: #727786;
  font-size: 22rpx;
}
.h5-cut-pair,
.h5-cut-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16rpx;
}
.h5-cut-pair {
  margin-top: 20rpx;
}
.h5-cut-pair--card {
  margin: 0 0 16rpx;
  padding: 24rpx;
  border-radius: 32rpx;
  background: #fff;
  box-shadow: 0 8rpx 24rpx rgba(0, 0, 0, 0.05);
}
.h5-cut-pair text,
.h5-cut-metrics text {
  display: block;
  color: #727786;
  font-size: 22rpx;
}
.h5-cut-pair strong,
.h5-cut-metrics strong {
  display: block;
  margin-top: 4rpx;
  color: #181b23;
  font-size: 30rpx;
}
.h5-cut-pair strong.high,
.h5-cut-metrics strong.high {
  color: #ba1a1a;
}
.h5-cut-metrics {
  margin-top: 16rpx;
}
.h5-cut-link {
  margin-top: 16rpx;
  color: #0057c2;
  font-size: 28rpx;
  font-weight: 700;
  text-align: center;
}
.h5-cut-kind {
  margin-top: 0 !important;
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
  background: #e8f0fe;
  color: #0057c2 !important;
  font-size: 22rpx;
  font-weight: 700;
}
.h5-cut-kind--return {
  background: #f3eee4;
  color: #7d5400 !important;
}
.h5-cut-kind--report {
  background: #e8f5e4;
  color: #266d00 !important;
}
.h5-cut--bar {
  padding-bottom: calc(180rpx + env(safe-area-inset-bottom));
}
.h5-cut-bar .primary-button {
  margin-top: 0;
}
</style>
