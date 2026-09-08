<template>
  <main class="receipt-print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>
    <article v-else-if="detail" class="sheet">
      <header class="document-header">
        <div>
          <p>SUBCONTRACT RECEIPT</p>
          <h1>外发收货单</h1>
        </div>
        <div class="document-no">
          <span>外发厂</span><strong>{{ detail.partner_name || '—' }}</strong>
          <span>外发单号</span><strong>{{ detail.subcontract_no || '—' }}</strong>
        </div>
      </header>

      <section class="base-grid">
        <div><span>生产单号</span><strong>{{ detail.linked_no || '—' }}</strong></div>
        <div><span>工厂型号</span><strong>{{ detail.product_code || '—' }}</strong></div>
        <div><span>颜色</span><strong>{{ detail.color_name || '—' }}</strong></div>
        <div><span>工序</span><strong>{{ detail.process_name || '—' }}</strong></div>
        <div><span>外发日期</span><strong>{{ formatDate(detail.created_at) }}</strong></div>
        <div><span>交货日期</span><strong>{{ detail.delivery_date || '—' }}</strong></div>
      </section>

      <table class="summary-table">
        <thead>
          <tr>
            <th>数量(双)</th>
            <th>完工(双)</th>
            <th>工价(元/双)</th>
            <th>加工费(元)</th>
            <th>报废(双)</th>
            <th>材料单价(元/双)</th>
            <th>损失金额(元)</th>
            <th>分担损失(元)</th>
            <th>应付(元)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{{ formatQty(detail.total_qty) }}</td>
            <td>{{ formatQty(detail.received_qty) }}</td>
            <td>{{ formatMoney(detail.unit_price) }}</td>
            <td>{{ formatMoney(detail.processing_fee) }}</td>
            <td class="defect-cell">{{ formatQty(detail.loss_qty) }}</td>
            <td>{{ formatMoney(detail.material_unit_price) }}</td>
            <td>{{ formatMoney(detail.loss_amount) }}</td>
            <td>{{ formatMoney(detail.shared_loss_amount) }}</td>
            <td>{{ formatMoney(detail.payable_amount) }}</td>
          </tr>
        </tbody>
      </table>

      <footer class="signatures">
        <span>外发厂确认：</span>
        <span>验收人：</span>
        <span>验收日期：</span>
      </footer>
    </article>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)
const error = ref('')

function formatQty(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/\.?0+$/, '')
}
function formatMoney(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}
function formatDate(value: unknown) {
  return value ? String(value).replace('T', ' ').slice(0, 10) : '—'
}
function doPrint() { window.print() }
function closeOrBack() { if (window.opener) window.close(); else router.back() }

async function load() {
  const id = Number(route.params.id)
  if (!id) { error.value = '外发单无效'; return }
  try {
    const detailRes: any = await http.get(`/subcontract-orders/${id}`)
    detail.value = detailRes.data
    document.title = `外发收货单-${detail.value?.subcontract_no || id}`
    setTimeout(() => window.print(), 500)
  } catch (requestError: any) {
    error.value = requestError?.response?.data?.detail || '外发收货单加载失败'
  }
}

onMounted(load)
</script>

<style scoped>
.receipt-print-page { min-height: 100vh; padding: 20px; background: #eef1f4; color: #111827; font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.actions { width: 190mm; margin: 0 auto 14px; }
.actions button { margin-right: 8px; padding: 7px 16px; border: 1px solid #172033; border-radius: 5px; background: #172033; color: #fff; cursor: pointer; }
.actions .ghost { background: #fff; color: #172033; }
.error { padding: 40px; color: #b91c1c; text-align: center; }
.sheet { box-sizing: border-box; width: 190mm; min-height: 267mm; margin: 0 auto; padding: 12mm; background: #fff; box-shadow: 0 6px 30px rgba(15, 23, 42, .12); }
.document-header { display: flex; align-items: flex-start; justify-content: space-between; }
.document-header p { margin: 0 0 3px; color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 2px; }
h1 { margin: 0; font-size: 28px; letter-spacing: 7px; }
.document-no { display: grid; grid-template-columns: auto auto; gap: 2mm 4mm; align-items: center; font-size: 11px; }
.document-no span { color: #64748b; }
.document-no strong { min-width: 42mm; font-size: 13px; }
.base-grid { display: grid; margin-top: 5mm; grid-template-columns: 1fr 1fr; border-top: 1px solid #9ca3af; border-left: 1px solid #9ca3af; }
.base-grid > div { display: flex; min-height: 10mm; padding: 1.6mm 2.5mm; flex-direction: column; justify-content: center; gap: .8mm; border-right: 1px solid #9ca3af; border-bottom: 1px solid #9ca3af; }
.base-grid > div:nth-child(-n + 2) { background: #f1f5f9; }
.base-grid span { color: #64748b; font-size: 9px; }
.base-grid strong { font-size: 13px; }
.summary-table { width: 100%; margin-top: 5mm; border-collapse: collapse; table-layout: fixed; }
.summary-table th, .summary-table td { border: 1px solid #9ca3af; padding: 2mm 1.2mm; text-align: center; }
.summary-table th { background: #f1f5f9; color: #111827; font-size: 10px; font-weight: 700; line-height: 1.35; }
.summary-table td { min-height: 10mm; font-size: 12px; font-weight: 700; }
.summary-table .defect-cell { color: #b42318; }
.signatures { display: grid; margin-top: 16mm; grid-template-columns: repeat(3, 1fr); gap: 8mm; color: #475569; font-size: 11px; }
@media print {
  @page { size: A4 portrait; margin: 10mm; }
  .no-print { display: none !important; }
  .receipt-print-page { min-height: 0; padding: 0; background: #fff; }
  .sheet { width: 190mm; min-height: 277mm; padding: 10mm; box-shadow: none; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
</style>

<style>
body:has(.receipt-print-page) #app { max-width: none; width: 100%; margin: 0; }
@media print { html, body { margin: 0; padding: 0; } }
</style>
