<template>
  <app-nav-bar />
  <view class="page h5-po" :class="{ 'h5-po--sub': mode !== 'list' }">
    <view v-if="!canSee" class="h5-home-empty">没有物料采购权限</view>

    <template v-else-if="mode === 'list'">
      <view class="card h5-po-search">
        <input :value="keyword" confirm-type="search" placeholder="采购单号、供应商、物料、生产单" @input="onKeyword" @confirm="search" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>
      <view class="h5-po-stats">
        <view v-for="item in statusItems" :key="item.value || 'all'" class="h5-po-stat" :class="[item.tone, { on: status === item.value && !expectedOnly }]" @click="setStatus(item.value)">
          <text>{{ item.label }}</text>
          <strong>{{ statCount(item.value) }}</strong>
        </view>
      </view>
      <text class="h5-po-expect" :class="{ on: expectedOnly }" @click="toggleExpected">预期未到货 {{ expectedCount }} 单</text>

      <view v-if="loading && !rows.length" class="h5-home-empty">加载中…</view>
      <view v-else-if="!rows.length" class="h5-home-empty">没有匹配的采购单</view>
      <view v-else>
        <view v-for="row in rows" :key="row.id" class="card h5-po-card" @click="openDetail(row.id)">
          <view class="h5-po-card__top">
            <strong>{{ row.po_no }}</strong>
            <text class="h5-po-status" :class="statusTone(row.status)">{{ statusLabel(row.status) }}</text>
          </view>
          <text class="h5-po-meta">{{ row.partner_name || '未填供应商' }}</text>
          <text class="h5-po-meta">{{ materialBrief(row) }}</text>
          <view class="h5-po-card__foot">
            <text>¥{{ money(row.summary_total_amount) }}</text>
            <text v-if="row.expected_date" :class="{ overdue: row.delivery_alert === 'overdue' }">{{ dateText(row.expected_date) }}</text>
          </view>
          <text v-if="row.delivery_alert_label" class="h5-po-alert" :class="row.delivery_alert">{{ row.delivery_alert_label }}</text>
        </view>
        <view class="h5-po-more">{{ rows.length >= total ? `共 ${total} 单` : '上拉加载更多' }}</view>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-po-hero">
        <view>
          <strong>{{ current.po_no }}</strong>
          <text>{{ current.partner_name || '未填供应商' }}</text>
        </view>
        <text class="h5-po-status" :class="statusTone(current.status)">{{ statusLabel(current.status) }}</text>
      </view>
      <view class="card h5-po-facts">
        <view><text>金额</text><strong>¥{{ money(current.summary_total_amount) }}</strong></view>
        <view><text>反馈时间</text><strong>{{ timeText(current.ordered_at) }}</strong></view>
        <view><text>协商到货</text><strong>{{ dateText(current.expected_date) }}</strong></view>
        <view><text>交期</text><strong :class="alertClass(current)">{{ current.delivery_alert_label || '正常' }}</strong></view>
      </view>
      <text v-if="current.notes" class="h5-po-note">{{ current.notes }}</text>

      <view v-for="line in detailLines" :key="line.supplier_product_id" class="card h5-po-mat">
        <view class="h5-po-mat__head">
          <image v-if="line.image_url" :src="displayImageUrl(line.image_url)" mode="aspectFill" @click="previewImage(line.image_url)" />
          <view v-else class="h5-po-swatch">{{ swatch(line) }}</view>
          <view>
            <strong>{{ line.supplier_product_name || line.supplier_product_code }}</strong>
            <text>{{ lineMeta(line) }}</text>
          </view>
        </view>
        <view class="h5-po-metrics">
          <view><text>数量</text><strong>{{ formatNum(baseQty(line.qty, line.loss_qty)) }}</strong></view>
          <view><text>损耗</text><strong>{{ formatNum(line.loss_qty) }}</strong></view>
          <view><text>未收</text><strong>{{ formatNum(line.open_qty) }}</strong></view>
          <view><text>金额</text><strong>¥{{ money(line.amount) }}</strong></view>
        </view>
        <scroll-view v-if="line.parts.length" class="h5-po-run" scroll-x :show-scrollbar="false">
          <view class="h5-po-run__track">
            <view v-for="part in line.parts" :key="part.size" class="h5-po-run__cell">
              <text>{{ part.size }}</text>
              <strong>{{ formatNum(baseQty(part.qty, part.loss)) }}</strong>
              <text class="h5-po-run__plus">{{ Number(part.loss) ? `损耗 ${formatNum(part.loss)}` : '' }}</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <view v-if="canFeedback || canLoss || canReceive" class="cut-sticky-bar h5-po-bar">
        <button v-if="canLoss" class="h5-po-ghost" @click="openLoss">添加损耗</button>
        <button v-if="canFeedback" class="primary-button h5-po-primary" @click="openFeedback">下单反馈</button>
        <button v-if="canReceive" class="primary-button h5-po-primary" @click="openReceive">到货登记</button>
      </view>
    </template>

    <template v-else-if="mode === 'feedback' && current">
      <text class="h5-po-hint">填写协商到货日期和单价。单价不能高于色卡。确认后这张单变成已反馈。</text>
      <picker mode="date" :value="expectedDate || todayText" @change="onExpected">
        <view class="card h5-po-field">
          <text>协商到货日期</text>
          <strong :class="{ need: !expectedDate }">{{ expectedDate || '必填' }}</strong>
        </view>
      </picker>
      <text v-if="feedbackError" class="h5-po-error">{{ feedbackError }}</text>
      <view v-for="line in feedbackRows" :key="line.supplier_product_id" class="card h5-po-mat">
        <view class="h5-po-mat__head">
          <view>
            <strong>{{ line.supplier_product_name || line.supplier_product_code }}</strong>
            <text>{{ lineMeta(line) }} · 采购 {{ formatNum(purchaseQty(line.qty, line.loss_qty)) }}</text>
          </view>
          <text class="h5-po-amount">¥{{ money(lineAmount(line)) }}</text>
        </view>
        <scroll-view v-if="line.parts.length" class="h5-po-run" scroll-x :show-scrollbar="false">
          <view class="h5-po-run__track">
            <view v-for="part in line.parts" :key="part.size" class="h5-po-run__cell">
              <text>{{ part.size }}</text>
              <strong>{{ formatNum(purchaseQty(part.qty, part.loss)) }}</strong>
              <text class="h5-po-run__plus">{{ Number(part.loss) ? `损耗 ${formatNum(part.loss)}` : '' }}</text>
            </view>
          </view>
        </scroll-view>
        <view class="h5-po-price">
          <text>单价</text>
          <input :value="shownPrice(line)" type="digit" placeholder="0.00" @input="onPrice(line, $event)" />
        </view>
        <text v-if="line.catalog_price != null && line.catalog_price !== ''" class="h5-po-sub">色卡单价 ¥{{ money(line.catalog_price) }}</text>
        <text v-if="priceOver(line)" class="h5-po-error">{{ priceOver(line) }}</text>
        <text v-if="line.price_mixed" class="h5-po-sub">分订单单价不一致，保存后会统一</text>
      </view>
      <view class="cut-sticky-bar h5-po-bar">
        <button class="h5-po-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-po-primary" :loading="saving" :disabled="feedbackBlocked" @click="confirmFeedback">确认下单反馈</button>
      </view>
    </template>

    <template v-else-if="mode === 'loss' && current">
      <text class="h5-po-hint">填写多买多少。有码数时按码填写，下单反馈时会加进采购数量。</text>
      <view v-for="line in lossRows" :key="line.supplier_product_id" class="card h5-po-mat">
        <view class="h5-po-mat__head">
          <view>
            <strong>{{ line.supplier_product_name || line.supplier_product_code }}</strong>
            <text>{{ lineMeta(line) }} · 原数量 {{ formatNum(line.qty) }}</text>
          </view>
        </view>
        <view v-if="line.parts.length" class="h5-po-grid">
          <view v-for="part in line.parts" :key="part.size" class="h5-po-grid__cell">
            <text>{{ part.size }}</text>
            <text class="h5-po-sub">数量 {{ formatNum(part.qty) }}</text>
            <input :value="line.size_loss[part.size]" type="digit" placeholder="损耗" @input="onSizeLoss(line, part.size, $event)" />
          </view>
        </view>
        <view v-else class="h5-po-price">
          <text>损耗</text>
          <input :value="line.loss_qty" type="digit" placeholder="0" @input="onLossQty(line, $event)" />
        </view>
      </view>
      <view class="cut-sticky-bar h5-po-bar">
        <button class="h5-po-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-po-primary" :loading="saving" @click="saveLoss">保存损耗</button>
      </view>
    </template>

    <template v-else-if="mode === 'receive' && current">
      <text class="h5-po-hint">默认填的是未收数量，可以改小。超过未收会按未收上限登记。</text>
      <view class="card h5-po-field h5-po-field--input">
        <text>送货单号</text>
        <input :value="deliveryNote" maxlength="80" placeholder="选填" @input="deliveryNote = inputValue($event)" />
      </view>
      <view v-for="batch in receiveRows" :key="batch.supplier_product_id" class="card h5-po-mat">
        <view class="h5-po-mat__head">
          <image v-if="batch.image_url" :src="displayImageUrl(batch.image_url)" mode="aspectFill" />
          <view v-else class="h5-po-swatch">{{ swatch(batch) }}</view>
          <view>
            <strong>{{ batch.supplier_product_name || batch.supplier_product_code }}</strong>
            <text>未收合计 {{ formatNum(batch.open_total) }}{{ batch.pricing_unit_name ? ` ${batch.pricing_unit_name}` : '' }}</text>
          </view>
        </view>
        <view v-if="batch.has_sizes" class="h5-po-grid">
          <view v-for="part in batch.parts" :key="part.size" class="h5-po-grid__cell">
            <text>{{ part.size }}</text>
            <text class="h5-po-sub">未收 {{ formatNum(part.open) }}</text>
            <input :value="part.qty" type="digit" placeholder="本次" @input="onReceiveSize(part, $event)" />
          </view>
        </view>
        <view v-else class="h5-po-price">
          <text>本次到货</text>
          <input :value="batch.total_qty" type="digit" placeholder="0" @input="onReceiveTotal(batch, $event)" />
        </view>
      </view>
      <view class="cut-sticky-bar h5-po-bar">
        <button class="h5-po-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-po-primary" :loading="saving" @click="confirmReceive">确认到货</button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onBackPress, onLoad, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { get, patch, post } from '../../services/http'
import { getProfile } from '../../services/storage'

type Mode = 'list' | 'detail' | 'feedback' | 'loss' | 'receive'

const profile = ref(getProfile())
const mode = ref<Mode>('list')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const status = ref('draft')
const expectedOnly = ref(false)
const expectedCount = ref(0)
const stats = ref<{ total: number; by_status: Record<string, number> }>({ total: 0, by_status: {} })
const current = ref<any>(null)
const expectedDate = ref('')
const feedbackError = ref('')
const priceDrafts = reactive<Record<string, string>>({})
const feedbackRows = ref<any[]>([])
const lossRows = ref<any[]>([])
const receiveRows = ref<any[]>([])
const receiveLines = ref<any[]>([])
const deliveryNote = ref('')
const launch = reactive({ id: 0, action: '' })
let loaded = false

const statusItems = [
  { value: 'draft', label: '未反馈', tone: 'is-draft' },
  { value: 'ordered', label: '已反馈', tone: 'is-ordered' },
  { value: 'partial_received', label: '部分到货', tone: 'is-partial' },
  { value: 'received', label: '已到齐', tone: 'is-done' },
  { value: 'cancelled', label: '已取消', tone: 'is-cancel' },
  { value: '', label: '全部', tone: '' },
]
const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.some(code => code === 'purchase_orders' || code.startsWith('purchase_orders_')))
const canFeedback = computed(() => features.value.includes('purchase_orders_submit') && current.value?.status === 'draft')
const canLoss = computed(() => features.value.includes('purchase_orders_loss') && current.value?.status === 'draft')
const canReceive = computed(() => features.value.includes('purchase_orders_receive') && ['ordered', 'shipped', 'partial_received'].includes(current.value?.status))
const todayText = computed(() => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
})
const detailLines = computed(() => (current.value?.summary_lines || []).map((line: any) => ({
  ...line,
  parts: sizePartsOf(current.value, line.supplier_product_id),
})))
const feedbackBlocked = computed(() => feedbackRows.value.some(line => priceOver(line)))

function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function inputValue(event: any) {
  return String(event?.detail?.value ?? '')
}
function round4(value: number) {
  return Math.round(value * 10000) / 10000
}
function formatNum(value: any) {
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/\.?0+$/, '')
}
function money(value: any) {
  const number = Number(value)
  return Number.isNaN(number) ? '0.00' : number.toFixed(2)
}
function dateText(value?: string) {
  return value ? String(value).slice(0, 10) : '未约到货'
}
function timeText(value?: string) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
}
function statusLabel(value: string) {
  return ({ draft: '未反馈', ordered: '已反馈', shipped: '已反馈', partial_received: '部分到货', received: '已到齐', cancelled: '已取消' } as Record<string, string>)[value] || value || '—'
}
function statusTone(value: string) {
  if (value === 'draft') return 'is-draft'
  if (value === 'ordered' || value === 'shipped') return 'is-ordered'
  if (value === 'partial_received') return 'is-partial'
  if (value === 'received') return 'is-done'
  return 'is-cancel'
}
function alertClass(row: any) {
  if (row?.delivery_alert === 'overdue') return 'overdue'
  if (row?.delivery_alert === 'due_soon') return 'soon'
  return ''
}
function statCount(value: string) {
  if (!value) return stats.value.total || 0
  return stats.value.by_status?.[value] || 0
}
function swatch(row: any) {
  return String(row?.supplier_product_name || row?.supplier_product_code || '料').trim().slice(0, 1)
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function lineMeta(line: any) {
  return [line.supplier_product_code, line.color_name, line.pricing_unit_name].filter(Boolean).join(' · ')
}
function materialBrief(row: any) {
  const names = (row.summary_lines || []).map((line: any) => line.supplier_product_name || line.supplier_product_code).filter(Boolean)
  if (!names.length) return '没有物料'
  const head = names.slice(0, 2).join('、')
  return names.length > 2 ? `${head} 等 ${names.length} 种` : head
}
function sizePartsOf(po: any, productId: number) {
  const map = new Map<string, any>()
  for (const line of po?.lines || []) {
    if (Number(line.supplier_product_id) !== Number(productId) || !line.size_value) continue
    const size = String(line.size_value)
    const part = map.get(size) || { size, qty: 0, loss: 0, sort: Number(line.size_sort_order || 0) }
    part.qty = round4(part.qty + Number(line.qty || 0))
    part.loss = round4(part.loss + Number(line.loss_qty || 0))
    map.set(size, part)
  }
  return [...map.values()].sort((a, b) => a.sort - b.sort || String(a.size).localeCompare(String(b.size), 'zh-CN', { numeric: true }))
}
function baseQty(qty: any, loss: any) {
  const total = Number(qty || 0)
  const extra = Number(loss || 0)
  if (current.value?.status && current.value.status !== 'draft' && extra > 0 && total >= extra) return round4(total - extra)
  return total
}
function purchaseQty(qty: any, loss: any) {
  return round4(Number(qty || 0) + Number(loss || 0))
}
function catalogCeiling(line: any) {
  if (line?.catalog_price == null || line.catalog_price === '') return null
  const number = Number(line.catalog_price)
  return Number.isFinite(number) ? Math.round(number * 100) / 100 : null
}
function shownPrice(line: any) {
  const key = String(line.supplier_product_id)
  return Object.prototype.hasOwnProperty.call(priceDrafts, key) ? priceDrafts[key] : formatNum(line.unit_price)
}
function priceNumber(line: any) {
  const number = Number(shownPrice(line))
  return Number.isFinite(number) ? number : 0
}
function priceOver(line: any) {
  const ceiling = catalogCeiling(line)
  if (ceiling == null) return ''
  return Math.round(priceNumber(line) * 100) / 100 > ceiling ? `不能高于色卡单价 ¥${money(ceiling)}` : ''
}
function lineAmount(line: any) {
  return purchaseQty(line.qty, line.loss_qty) * priceNumber(line)
}

function onKeyword(event: any) {
  keyword.value = inputValue(event)
}
function clearKeyword() {
  keyword.value = ''
  search()
}
function setStatus(next: string) {
  status.value = next
  expectedOnly.value = false
  search()
}
function toggleExpected() {
  expectedOnly.value = !expectedOnly.value
  if (expectedOnly.value) status.value = ''
  search()
}
function search() {
  void load(true)
}
async function loadStats() {
  try {
    stats.value = await get('/purchase-orders/status-stats')
  } catch {
    // 数量条失败时列表仍可用
  }
}
async function load(reset = true) {
  if (reset) {
    page.value = 1
    loading.value = true
  }
  try {
    const query: Record<string, string | number | boolean> = { page: page.value, page_size: 20 }
    if (status.value) query.status = status.value
    const text = keyword.value.trim()
    if (text) query.keyword = text
    if (expectedOnly.value) query.expected_unreceived = true
    const data: any = await get('/purchase-orders', query)
    const items = Array.isArray(data?.items) ? data.items : []
    rows.value = reset ? items : rows.value.concat(items)
    total.value = Number(data?.total ?? rows.value.length)
    expectedCount.value = Number(data?.expected_unreceived_count || 0)
    if (reset) await loadStats()
  } catch (error: any) {
    toast(error?.message || '采购单加载失败')
  } finally {
    loading.value = false
    uni.stopPullDownRefresh()
  }
}
async function openDetail(id: number, next?: Mode) {
  try {
    current.value = await get(`/purchase-orders/${id}`)
    const receivable = ['ordered', 'shipped', 'partial_received'].includes(current.value?.status)
    if (next === 'receive' && canReceive.value && receivable) {
      prepareReceive()
      mode.value = 'receive'
      return
    }
    mode.value = 'detail'
  } catch (error: any) {
    toast(error?.message || '采购单加载失败')
  }
}
function openFeedback() {
  for (const key of Object.keys(priceDrafts)) delete priceDrafts[key]
  feedbackError.value = ''
  expectedDate.value = ''
  feedbackRows.value = (current.value?.summary_lines || []).map((line: any) => ({
    ...line,
    parts: sizePartsOf(current.value, line.supplier_product_id),
  }))
  mode.value = 'feedback'
}
function onExpected(event: any) {
  expectedDate.value = inputValue(event)
}
function onPrice(line: any, event: any) {
  priceDrafts[String(line.supplier_product_id)] = inputValue(event)
  feedbackError.value = ''
}
async function confirmFeedback() {
  if (!current.value) return
  if (!expectedDate.value) return toast('请填写协商到货日期')
  if (feedbackBlocked.value) return
  saving.value = true
  feedbackError.value = ''
  try {
    for (const line of feedbackRows.value) {
      const key = String(line.supplier_product_id)
      if (!Object.prototype.hasOwnProperty.call(priceDrafts, key)) continue
      const price = priceNumber(line)
      if (Math.round(price * 100) === Math.round(Number(line.unit_price || 0) * 100)) continue
      current.value = await patch(`/purchase-orders/${current.value.id}/summary-price`, {
        supplier_product_id: line.supplier_product_id,
        unit_price: price,
      })
    }
    await patch(`/purchase-orders/${current.value.id}`, { expected_date: expectedDate.value, notes: current.value.notes })
    await post(`/purchase-orders/${current.value.id}/submit`, {})
    toast('已反馈')
    await openDetail(current.value.id)
    void load(true)
  } catch (error: any) {
    feedbackError.value = error?.message || '不能下单'
  } finally {
    saving.value = false
  }
}

function openLoss() {
  lossRows.value = (current.value?.summary_lines || []).map((line: any) => {
    const parts = sizePartsOf(current.value, line.supplier_product_id)
    const sizeLoss: Record<string, string> = {}
    for (const part of parts) sizeLoss[part.size] = Number(part.loss) ? formatNum(part.loss) : ''
    return { ...line, parts, size_loss: sizeLoss, loss_qty: Number(line.loss_qty) ? formatNum(line.loss_qty) : '' }
  })
  mode.value = 'loss'
}
function onLossQty(line: any, event: any) {
  line.loss_qty = inputValue(event)
}
function onSizeLoss(line: any, size: string, event: any) {
  line.size_loss[size] = inputValue(event)
}
async function saveLoss() {
  if (!current.value) return
  saving.value = true
  try {
    let latest = current.value
    for (const line of lossRows.value) {
      if (line.parts.length) {
        for (const part of line.parts) {
          latest = await patch(`/purchase-orders/${current.value.id}/summary-loss`, {
            supplier_product_id: line.supplier_product_id,
            loss_qty: Number(line.size_loss[part.size] || 0),
            size_value: part.size,
          })
        }
        continue
      }
      latest = await patch(`/purchase-orders/${current.value.id}/summary-loss`, {
        supplier_product_id: line.supplier_product_id,
        loss_qty: Number(line.loss_qty || 0),
      })
    }
    current.value = latest
    toast('已记下损耗')
    mode.value = 'detail'
  } catch (error: any) {
    toast(error?.message || '保存损耗失败')
  } finally {
    saving.value = false
  }
}

function openReceive() {
  prepareReceive()
  mode.value = 'receive'
}
function prepareReceive() {
  deliveryNote.value = ''
  const lines = (current.value?.lines || []).map((line: any) => {
    const open = Math.max(0, Number(line.open_qty ?? (Number(line.qty) - Number(line.received_qty || 0) - Number(line.pending_iqc_qty || 0))))
    return { ...line, open_qty: open, this_qty: 0 }
  })
  receiveLines.value = lines
  const groups = new Map<number, any>()
  for (const line of lines) {
    const id = Number(line.supplier_product_id)
    const batch = groups.get(id) || {
      supplier_product_id: id,
      supplier_product_code: line.supplier_product_code,
      supplier_product_name: line.supplier_product_name,
      image_url: line.image_url,
      pricing_unit_name: line.pricing_unit_name,
      open_total: 0,
      total_qty: '',
      has_sizes: false,
      parts: [] as any[],
    }
    batch.open_total = round4(batch.open_total + Number(line.open_qty || 0))
    if (line.size_value) {
      batch.has_sizes = true
      const size = String(line.size_value)
      const part = batch.parts.find((item: any) => item.size === size) || { size, open: 0, qty: '', sort: Number(line.size_sort_order || 0) }
      if (!batch.parts.includes(part)) batch.parts.push(part)
      part.open = round4(part.open + Number(line.open_qty || 0))
      part.qty = formatNum(part.open)
    }
    groups.set(id, batch)
  }
  receiveRows.value = [...groups.values()].map(batch => {
    batch.parts.sort((a: any, b: any) => a.sort - b.sort || String(a.size).localeCompare(String(b.size), 'zh-CN', { numeric: true }))
    if (!batch.has_sizes) batch.total_qty = formatNum(batch.open_total)
    return batch
  })
}
function onReceiveTotal(batch: any, event: any) {
  batch.total_qty = inputValue(event)
}
function onReceiveSize(part: any, event: any) {
  part.qty = inputValue(event)
}
async function confirmReceive() {
  if (!current.value) return
  const items: { supplier_product_id: number; qty: number; size_value?: string }[] = []
  for (const batch of receiveRows.value) {
    if (batch.has_sizes) {
      for (const part of batch.parts) {
        const amount = Number(part.qty || 0)
        if (amount > 0) {
          items.push({
            supplier_product_id: Number(batch.supplier_product_id),
            size_value: String(part.size),
            qty: amount,
          })
        }
      }
    } else if (Number(batch.total_qty || 0) > 0) {
      items.push({
        supplier_product_id: Number(batch.supplier_product_id),
        qty: Number(batch.total_qty),
      })
    }
  }
  if (!items.length) return toast('请填写本次到货数量')
  saving.value = true
  try {
    await post(`/purchase-orders/${current.value.id}/receive`, {
      items,
      delivery_note_no: deliveryNote.value || undefined,
    })
    toast('到货已登记')
    await openDetail(current.value.id)
    void load(true)
  } catch (error: any) {
    toast(error?.message || '到货登记失败')
  } finally {
    saving.value = false
  }
}

function goBack() {
  if (mode.value === 'feedback' || mode.value === 'loss' || mode.value === 'receive') {
    mode.value = 'detail'
    return
  }
  if (mode.value !== 'list') {
    mode.value = 'list'
    void load(true)
  }
}
onBackPress(() => {
  if (mode.value !== 'list') {
    goBack()
    return true
  }
  return false
})
onReachBottom(() => {
  if (mode.value !== 'list' || rows.value.length >= total.value || loading.value) return
  page.value += 1
  void load(false)
})
onPullDownRefresh(() => {
  if (mode.value === 'list') void load(true)
  else uni.stopPullDownRefresh()
})
onLoad((query: any) => {
  launch.id = Number(query?.id || 0)
  launch.action = String(query?.action || '')
})
onShow(async () => {
  profile.value = getProfile()
  if (!canSee.value) return
  if (!loaded) {
    loaded = true
    await load(true)
  }
  if (!launch.id) return
  const id = launch.id
  const action = launch.action
  launch.id = 0
  launch.action = ''
  await openDetail(id, action === 'receive' ? 'receive' : 'detail')
})
</script>

<style scoped lang="scss">
.h5-po-search,
.h5-po-card,
.h5-po-hero,
.h5-po-facts,
.h5-po-mat,
.h5-po-field { margin-bottom: 16rpx; }
.h5-po-search { display: flex; align-items: center; gap: 16rpx; padding: 8rpx 8rpx 8rpx 24rpx; }
.h5-po-search input,
.h5-po-price input,
.h5-po-field input,
.h5-po-grid input { min-width: 0; height: 72rpx; color: #181b23; font-size: 32rpx; }
.h5-po-search input { flex: 1; }
.h5-po-search > text { color: #0057c2; font-size: 30rpx; font-weight: 700; }
.h5-po-stats { display: flex; gap: 8rpx; width: 100%; margin: 8rpx 0 12rpx; }
.h5-po-stat { display: flex; flex: 1; flex-direction: column; align-items: center; min-width: 0; padding: 14rpx 0; border-radius: 20rpx; background: #fff; }
.h5-po-stat text { color: #727786; font-size: 26rpx; white-space: nowrap; }
.h5-po-stat strong { margin-top: 4rpx; color: #181b23; font-size: 34rpx; font-variant-numeric: tabular-nums; }
.h5-po-stat.on { background: rgba(0, 87, 194, 0.12); }
.h5-po-stat.on text,
.h5-po-stat.on strong { color: #0057c2; }
.h5-po-stat.is-draft strong { color: #7d5400; }
.h5-po-stat.is-partial strong { color: #9a3412; }
.h5-po-stat.is-done strong { color: #266d00; }
.h5-po-expect { display: inline-flex; margin: 0 0 16rpx; padding: 8rpx 18rpx; border-radius: 999rpx; background: #fff; color: #414755; font-size: 28rpx; }
.h5-po-expect.on { background: rgba(186, 26, 26, 0.1); color: #ba1a1a; font-weight: 700; }
.h5-po-card,
.h5-po-hero,
.h5-po-mat,
.h5-po-facts,
.h5-po-field { padding: 20rpx 24rpx; }
.h5-po-card__top,
.h5-po-hero,
.h5-po-mat__head,
.h5-po-field,
.h5-po-price { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-po-card__top strong,
.h5-po-hero strong,
.h5-po-mat__head strong { color: #181b23; font-size: 34rpx; }
.h5-po-meta,
.h5-po-mat__head text,
.h5-po-sub,
.h5-po-hint,
.h5-po-note,
.h5-po-more { color: #414755; font-size: 28rpx; line-height: 1.45; }
.h5-po-meta,
.h5-po-mat__head text,
.h5-po-sub,
.h5-po-note { display: block; margin-top: 6rpx; }
.h5-po-card__foot { display: flex; justify-content: space-between; margin-top: 14rpx; color: #181b23; font-size: 30rpx; font-weight: 700; }
.h5-po-status { flex-shrink: 0; padding: 4rpx 14rpx; border-radius: 999rpx; background: #f5f7fa; color: #414755; font-size: 26rpx; font-weight: 700; }
.h5-po-status.is-draft { background: rgba(125, 84, 0, 0.12); color: #7d5400; }
.h5-po-status.is-ordered { background: rgba(0, 87, 194, 0.12); color: #0057c2; }
.h5-po-status.is-partial { background: rgba(154, 52, 18, 0.12); color: #9a3412; }
.h5-po-status.is-done { background: rgba(38, 109, 0, 0.12); color: #266d00; }
.h5-po-alert { display: inline-flex; margin-top: 12rpx; font-size: 28rpx; font-weight: 700; }
.h5-po-alert.overdue,
.overdue,
.h5-po-error { color: #ba1a1a; }
.h5-po-alert.due_soon,
.soon { color: #7d5400; }
.h5-po-error,
.h5-po-hint,
.h5-po-note { display: block; margin: 0 4rpx 16rpx; line-height: 1.5; }
.h5-po-error { margin-top: 8rpx; font-size: 28rpx; font-weight: 700; }
.h5-po-more { padding: 8rpx 0 24rpx; text-align: center; }
.h5-po-hero view { min-width: 0; }
.h5-po-facts view { display: flex; align-items: center; justify-content: space-between; min-height: 76rpx; border-bottom: 1rpx solid #e0e2ed; }
.h5-po-facts view:last-child { border-bottom: 0; }
.h5-po-facts text { color: #414755; font-size: 30rpx; }
.h5-po-facts strong { color: #181b23; font-size: 32rpx; }
.h5-po-mat__head image,
.h5-po-swatch { width: 88rpx; height: 88rpx; border-radius: 18rpx; background: #f5f7fa; }
.h5-po-swatch { display: flex; flex: 0 0 88rpx; align-items: center; justify-content: center; color: #414755; font-size: 36rpx; font-weight: 750; }
.h5-po-mat__head view { min-width: 0; }
.h5-po-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8rpx; margin-top: 16rpx; }
.h5-po-metrics text { display: block; color: #727786; font-size: 26rpx; }
.h5-po-metrics strong { display: block; margin-top: 2rpx; color: #181b23; font-size: 30rpx; font-variant-numeric: tabular-nums; }
.h5-po-run { width: 100%; height: 132rpx; margin-top: 12rpx; white-space: nowrap; }
.h5-po-run__track { display: inline-flex; gap: 8rpx; height: 132rpx; }
.h5-po-run__cell { display: inline-flex; flex: 0 0 104rpx; flex-direction: column; align-items: center; justify-content: center; width: 104rpx; min-height: 120rpx; padding: 8rpx 6rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-po-run__cell text { color: #727786; font-size: 24rpx; }
.h5-po-run__cell strong { margin: 4rpx 0; color: #181b23; font-size: 30rpx; }
.h5-po-run__plus { min-height: 24rpx; color: #7d5400; font-size: 22rpx; }
.h5-po-amount { color: #181b23; font-size: 32rpx; font-weight: 750; }
.h5-po-price { margin-top: 12rpx; }
.h5-po-price text,
.h5-po-field > text { flex: 0 0 200rpx; color: #414755; font-size: 30rpx; }
.h5-po-price input,
.h5-po-field--input input,
.h5-po-grid input { flex: 1; padding: 0 16rpx; border-radius: 14rpx; background: #f5f7fa; text-align: right; }
.h5-po-field strong { color: #181b23; font-size: 32rpx; }
.h5-po-field strong.need { color: #ba1a1a; font-weight: 500; }
.h5-po-grid { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 16rpx; }
.h5-po-grid__cell { display: flex; flex-direction: column; box-sizing: border-box; width: calc((100% - 24rpx) / 3); padding: 12rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-po-grid__cell > text:first-child { color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-po-grid input { width: 100%; margin-top: 8rpx; text-align: center; background: #fff; }
.h5-po-bar { display: flex; gap: 12rpx; }
.h5-po-bar .h5-po-ghost,
.h5-po-bar .h5-po-primary { flex: 1; width: auto; height: 84rpx; margin: 0; border: 0; border-radius: 16rpx; font-size: 32rpx; font-weight: 750; line-height: 84rpx; }
.h5-po-ghost { background: #f5f7fa; color: #181b23; }
.h5-po-primary { margin-top: 0; }
.h5-po-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.92); }
.h5-po-ghost::after,
.h5-po-primary::after { border: 0; }
.h5-po--sub { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
</style>
