<template>
  <view class="page h5-home-page h5-pickup-page">
    <view class="card h5-pickup-form">
      <text class="h5-pickup-form__title">新建领料</text>
      <text class="h5-pickup-form__hint">点选色卡后在清单里填数量。搜索框会自动清空，可直接继续添加下一种。</text>
      <input :key="`name-${formEpoch}`" class="h5-pickup-input" :value="keyword" :placeholder="drafts.length ? '继续搜索下一种物料' : '搜索色卡名称、编号或颜色'" @focus="openPicker" @input="onKeyword" />
      <view v-if="pickerOpen && hits.length" class="h5-pickup-hits">
        <view v-for="hit in hits" :key="hit.id" class="h5-pickup-hit" @click="chooseMaterial(hit)">
          <image v-if="hit.image_url" class="h5-pickup-swatch" :src="displayImageUrl(hit.image_url)" mode="aspectFill" />
          <view v-else class="h5-pickup-swatch">{{ swatchText(hit) }}</view>
          <view class="h5-pickup-hit__body">
            <strong>{{ hit.name || hit.product_code }}</strong>
            <text>{{ hitMeta(hit) }}</text>
          </view>
          <text class="h5-pickup-hit__stock">库存 {{ hit.stock_qty }}{{ hit.unit_name || '' }}</text>
        </view>
      </view>
      <view v-else-if="pickerOpen && searched" class="h5-pickup-empty">色卡里没有匹配的物料</view>
      <view v-if="drafts.length" class="h5-pickup-draft">
        <view class="h5-pickup-draft__head"><text>本次物料</text><text>{{ readyCount }} 种</text></view>
        <view v-for="(line, index) in drafts" :key="draftKey(line)" class="h5-pickup-draft-row">
          <view>
            <strong>{{ line.material_name }}</strong>
            <text>{{ line.material_code }}{{ line.color_name ? ` · ${line.color_name}` : '' }}</text>
          </view>
          <view class="h5-pickup-line-qty">
            <input :value="line.qty" :focus="focusLineId === line.supplier_product_id" type="digit" confirm-type="done" placeholder="数量" @input="onLineQty(line, $event)" />
            <text v-if="line.unit_name">{{ line.unit_name }}</text>
          </view>
          <view class="cut-remove-hit cut-remove-hit--icon" @click="removeDraft(index)">
            <image class="cut-remove-icon" src="/static/icons/trash.svg" mode="aspectFit" />
          </view>
        </view>
      </view>
    </view>
    <view class="card h5-pickup-history">
      <view class="h5-pickup-history__toggle" @click="historyOpen = !historyOpen">
        <text>领取记录</text>
        <view>
          <text v-if="pendingCount">{{ pendingCount }} 待领取</text>
          <text :class="['h5-pickup-history__chev', { open: historyOpen }]">›</text>
        </view>
      </view>
      <view v-if="historyOpen" class="h5-pickup-history__body">
        <view v-if="loading" class="h5-pickup-history__empty">加载中…</view>
        <view v-else-if="!pickups.length" class="h5-pickup-history__empty">暂无领料记录</view>
        <view v-else class="h5-pickup-list">
          <view v-for="row in pickups" :key="row.id" class="h5-pickup-row">
            <view class="h5-pickup-head">
              <view>
                <strong>{{ row.doc_no }}</strong>
                <text>{{ row.line_count || row.lines?.length || 0 }} 种物料 · {{ formatTime(row.created_at) }}</text>
              </view>
              <text :class="['h5-defect-status', row.status]">{{ statusText(row) }}</text>
            </view>
            <view class="h5-pickup-lines">
              <view v-for="line in row.lines || []" :key="line.id" class="h5-pickup-line">
                <text>{{ line.material_name }}<text v-if="line.material_code"> {{ line.material_code }}</text></text>
                <strong>{{ line.qty }}{{ line.unit_name || '' }}</strong>
              </view>
            </view>
            <text v-if="row.notes" class="h5-pickup-notes">{{ row.notes }}</text>
            <view v-if="row.status === 'pending'" class="h5-pickup-actions">
              <button class="h5-pickup-cancel" @click="cancelPickup(row)">取消</button>
              <button class="h5-pickup-receive" :loading="receivingId === row.id" @click="receivePickup(row)">确认领取</button>
            </view>
          </view>
        </view>
      </view>
    </view>
    <view class="cut-sticky-bar">
      <button class="primary-button cut-sticky-button" :loading="submitting" :disabled="!readyCount" @click="submitPickup">提交领料{{ readyCount ? ` · ${readyCount} 种` : '' }}</button>
    </view>
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const keyword = ref(''), hits = ref<any[]>([]), formEpoch = ref(0), searched = ref(false), pickerOpen = ref(false), focusLineId = ref(0)
const drafts = ref<any[]>([]), pickups = ref<any[]>([]), loading = ref(false), submitting = ref(false), receivingId = ref<number | null>(null), historyOpen = ref(false)
const pendingCount = computed(() => pickups.value.filter(row => row.status === 'pending').length)
const readyCount = computed(() => drafts.value.filter(line => Number(line.qty) > 0).length)
let ignorePickerFocus = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

function draftKey(line: any) {
  return `id:${line.supplier_product_id}`
}
function swatchText(hit: any) {
  return String(hit.color_name || hit.name || hit.product_code || '料').trim().slice(0, 1)
}
function hitMeta(hit: any) {
  return [hit.product_code, hit.color_name, hit.category_name, hit.partner_name].filter(Boolean).join(' · ')
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function statusText(row: any) {
  if (row.status === 'received') return '已领取'
  if (row.status === 'cancelled') return '已取消'
  return '待领取'
}
const formatTime = (v?: string) => {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 16).replace('T', ' ')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function openPicker() {
  if (ignorePickerFocus) return
  pickerOpen.value = true
  loadMaterials(keyword.value.trim())
}
function onKeyword(event: any) {
  const value = String(event?.detail?.value ?? event?.target?.value ?? '')
  keyword.value = value
  pickerOpen.value = true
  if (searchTimer) clearTimeout(searchTimer)
  const text = value.trim()
  searchTimer = setTimeout(() => loadMaterials(text), 250)
}
async function loadMaterials(text = keyword.value.trim()) {
  try {
    const rows: any = await get('/misc-material-pickups/materials', { keyword: text })
    if (keyword.value.trim() !== text) return
    hits.value = Array.isArray(rows) ? rows : []
    searched.value = true
  } catch {
    if (keyword.value.trim() === text) {
      hits.value = []
      searched.value = true
    }
  }
}
function chooseMaterial(hit: any) {
  ignorePickerFocus = true
  keyword.value = ''
  hits.value = []
  pickerOpen.value = false
  searched.value = false
  formEpoch.value += 1
  drafts.value = drafts.value.filter(item => Number(item.qty) > 0 || item.supplier_product_id === hit.id)
  if (!drafts.value.some(item => item.supplier_product_id === hit.id)) {
    drafts.value.push({
      supplier_product_id: hit.id,
      material_name: hit.name || hit.product_code,
      material_code: hit.product_code || '',
      color_name: hit.color_name || '',
      unit_name: hit.unit_name || '',
      qty: '',
    })
  }
  focusLineId.value = 0
  setTimeout(() => {
    focusLineId.value = hit.id
    ignorePickerFocus = false
  }, 80)
}
function removeDraft(index: number) {
  const line = drafts.value[index]
  if (line?.supplier_product_id === focusLineId.value) focusLineId.value = 0
  drafts.value.splice(index, 1)
}
function onLineQty(line: any, event: any) {
  const value = String(event?.detail?.value ?? event?.target?.value ?? '')
  const amount = Number(value)
  line.qty = amount > 0 ? amount : ''
}
async function load() {
  loading.value = true
  try {
    const result: any = await get('/misc-material-pickups', { page_size: 50 })
    pickups.value = result?.items || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '领料记录加载失败', icon: 'none' })
  } finally { loading.value = false }
}
async function submitPickup() {
  const lines = drafts.value.filter(line => Number(line.qty) > 0)
  if (!lines.length) return uni.showToast({ title: '请先填写数量', icon: 'none' })
  submitting.value = true
  try {
    await post('/misc-material-pickups', {
      lines: lines.map(line => ({
        supplier_product_id: line.supplier_product_id,
        material_name: line.material_name,
        material_code: line.material_code || undefined,
        qty: line.qty,
      })),
    })
    uni.showToast({ title: '已提交，到货后确认领取', icon: 'none' })
    drafts.value = []
    keyword.value = ''
    pickerOpen.value = false
    focusLineId.value = 0
    formEpoch.value += 1
    await load()
  } catch (e: any) {
    uni.showToast({ title: e?.message || '提交失败', icon: 'none' })
  } finally { submitting.value = false }
}
function receivePickup(row: any) {
  const summary = (row.lines || []).map((line: any) => `${line.material_name} ${line.qty}${line.unit_name || ''}`).join('、')
  uni.showModal({
    title: '确认领取',
    content: `确认领取 ${summary}？确认后从公用库存扣减。`,
    success: async result => {
      if (!result.confirm) return
      receivingId.value = row.id
      try {
        await post(`/misc-material-pickups/${row.id}/receive`, {})
        uni.showToast({ title: '已领取', icon: 'success' })
        await load()
      } catch (e: any) {
        uni.showToast({ title: e?.message || '确认失败', icon: 'none' })
      } finally { receivingId.value = null }
    },
  })
}
function cancelPickup(row: any) {
  uni.showModal({
    title: '取消领料',
    content: `取消 ${row.doc_no} 这张领料单？`,
    success: async result => {
      if (!result.confirm) return
      try {
        await post(`/misc-material-pickups/${row.id}/cancel`, {})
        uni.showToast({ title: '已取消', icon: 'none' })
        await load()
      } catch (e: any) {
        uni.showToast({ title: e?.message || '取消失败', icon: 'none' })
      }
    },
  })
}
onShow(load)
</script>
