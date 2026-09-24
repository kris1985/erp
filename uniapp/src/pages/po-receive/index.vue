<template>
  <view class="page mobile-receive-page">
    <view class="mobile-page-head"><view><text>登记到货</text><text>{{ detail?.po_no || '采购来料' }}</text></view></view>
    <view v-if="loading" class="empty-state">正在加载采购单…</view>
    <view v-else-if="error" class="card report-error">{{ error }}</view>
    <template v-else-if="detail">
      <view class="card receive-po-card"><view><strong>{{ detail.po_no }}</strong><text>{{ detail.status_label || detail.status }}</text></view><text>{{ detail.partner_name || '—' }}{{ detail.expected_date ? ` · 预计 ${detail.expected_date}` : '' }}</text></view>
      <view v-if="!canReceive" class="card report-warning">当前状态不可登记到货</view>
      <template v-else>
        <text class="receive-hint">点击“填入未收”可快速登记全部剩余数量；确认后直接入库。</text>
        <view class="card receive-row-native">
          <view><strong>送货单号</strong><text>选填</text></view>
          <view class="receive-input"><input v-model="deliveryNoteNo" placeholder="送货单号" /></view>
        </view>
        <view class="receive-list">
          <view v-for="batch in batches" :key="batch.key" class="card receive-row-native">
            <view><strong>{{ batch.supplier_product_code || '—' }} · {{ batch.supplier_product_name || '' }}</strong><text>{{ batch.size_value || '通码' }} · 未收 {{ num(batch.open_total) }} {{ batch.pricing_unit_name || '' }}</text></view>
            <view class="receive-input"><input v-model="batch.total_qty_str" type="digit" placeholder="0" /><button @click="batch.total_qty_str = String(batch.open_total)">填入未收</button></view>
          </view>
        </view>
        <button class="primary-button" :loading="submitting" :disabled="!hasQty" @click="submitReceive">确认到货</button>
      </template>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const poId = ref(0), detail = ref<any>(null), batches = ref<any[]>([]), loading = ref(true), submitting = ref(false), error = ref(''), deliveryNoteNo = ref('')
const canReceive = computed(() => ['ordered', 'shipped', 'partial_received'].includes(detail.value?.status))
const hasQty = computed(() => batches.value.some(x => Number(x.total_qty_str) > 0))
const num = (v: unknown) => { const n = Number(v); return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '') }

function buildBatches(lines: any[]) {
  const map = new Map<string, any>()
  for (const line of lines) {
    const open = Math.max(0, Number(line.open_qty ?? (Number(line.qty) - Number(line.received_qty || 0) - Number(line.pending_iqc_qty || 0))))
    const key = `${line.supplier_product_id}:${line.size_id || 0}`
    if (!map.has(key)) map.set(key, { key, supplier_product_code: line.supplier_product_code, supplier_product_name: line.supplier_product_name, pricing_unit_name: line.pricing_unit_name, size_value: line.size_value, open_total: 0, total_qty_str: '0', lines: [] })
    const batch = map.get(key); batch.open_total += open; batch.lines.push({ ...line, open_qty: open })
  }
  return [...map.values()].map(x => ({ ...x, total_qty_str: String(x.open_total) }))
}
function split(batch: any) {
  const total = Math.max(0, Number(batch.total_qty_str) || 0)
  if (!total || !batch.lines.length) return []
  const openSum = batch.lines.reduce((s: number, x: any) => s + Number(x.open_qty || 0), 0)
  let left = total
  return batch.lines.map((line: any, index: number) => {
    const qty = index === batch.lines.length - 1 ? left : Math.min(Number(line.open_qty || 0), Math.round(total * Number(line.open_qty || 0) / (openSum || 1)))
    left -= qty
    return { line_id: line.id, qty }
  }).filter((x: any) => x.qty > 0)
}
async function load() {
  loading.value = true; error.value = ''
  try { detail.value = await get(`/purchase-orders/${poId.value}`); batches.value = buildBatches(detail.value?.lines || []) }
  catch (e: any) { error.value = e?.message || '采购单不存在或无权查看' }
  finally { loading.value = false }
}
function submitReceive() {
  const lines = batches.value.flatMap(split)
  if (!lines.length) return uni.showToast({ title: '请填写到货数量', icon: 'none' })
  uni.showModal({ title: '确认到货', content: `本次登记 ${lines.length} 行，提交后直接入库。`, success: async result => {
    if (!result.confirm) return
    submitting.value = true
    try { await post(`/purchase-orders/${poId.value}/receive`, { lines, delivery_note_no: deliveryNoteNo.value || undefined }); uni.showToast({ title: '到货成功', icon: 'success' }); await load() }
    catch (e: any) { uni.showToast({ title: e?.message || '到货失败', icon: 'none' }) }
    finally { submitting.value = false }
  } })
}
onLoad(query => { poId.value = Number(query?.id || 0); if (!poId.value) { error.value = '采购单链接无效'; loading.value = false } else load() })
</script>
