<template>
  <main class="print-page subcontract-print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
    <article v-else-if="detail" class="sheet detail-sheet">
      <header class="sheet-header">
        <div class="title-block">
          <p>OUTSOURCING ORDER</p>
          <h1>外发单</h1>
          <div class="header-meta">
            <span>外发厂：<strong>{{ detail.partner_name || '—' }}</strong></span>
            <span>外发单号：<strong>{{ detail.subcontract_no || '—' }}</strong></span>
          </div>
        </div>
        <div class="qr-block"><img :src="qrSrc" alt="外发收回二维码" /></div>
      </header>

      <section class="meta-section">
        <div class="meta-grid">
          <div><span>生产单号</span><strong>{{ detail.linked_no || '—' }}</strong></div>
          <div><span>工厂型号</span><strong>{{ detail.product_code || '—' }}</strong></div>
          <div><span>颜色</span><strong>{{ detail.color_name || '—' }}</strong></div>
          <div><span>材料单价</span><strong>¥{{ formatMoney(detail.material_unit_price) }} / 双</strong></div>
          <div><span>数量</span><strong>{{ formatNumber(detail.total_qty) }} 双</strong></div>
          <div><span>工价</span><strong>¥{{ formatMoney(detail.unit_price) }} / 双</strong></div>
          <div><span>外发日期</span><strong>{{ formatDate(detail.created_at) }}</strong></div>
          <div><span>交货日期</span><strong>{{ detail.delivery_date || '—' }}</strong></div>
          <div class="wide process-cell"><span>工序</span><strong>{{ detail.process_name || '—' }}</strong></div>
        </div>
      </section>

      <section class="requirements">
        <h2>工艺要求</h2>
        <template v-if="processRequirements.length">
          <div v-for="(row, index) in processRequirements" :key="`${row.process_name}-${index}`" class="requirement-row">
            <span class="requirement-source">{{ row.process_name || `工序 ${index + 1}` }}</span>
            <p>{{ row.requirement_note || '未填写工艺要求备注' }}</p>
          </div>
        </template>
        <p v-else class="empty-requirement">未填写工艺要求</p>
      </section>
    </article>
    <article v-if="detail?.product_image_url" class="sheet image-sheet">
      <h2>产品图片</h2>
      <div class="image-page-content">
        <img :src="detail.product_image_url" alt="产品图片" />
      </div>
    </article>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)
const error = ref('')
const processRequirements = computed(() => Array.isArray(detail.value?.process_requirements) ? detail.value.process_requirements : [])
const qrSrc = computed(() => {
  const id = Number(route.params.id)
  return id ? `/api/v1/subcontract-orders/${id}/qr.png` : ''
})

function formatNumber(value: unknown) {
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
    const res: any = await http.get(`/subcontract-orders/${id}`)
    detail.value = res.data
    document.title = `外发单-${res.data?.linked_no || id}`
    setTimeout(() => window.print(), 500)
  } catch {
    error.value = '外发单不存在或无权查看'
  }
}
onMounted(load)
</script>

<style scoped>
.print-page { min-height: 100vh; padding: 20px; background: #eef1f4; color: #111827; font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.actions { width: 190mm; margin: 0 auto 14px; }
.actions button { margin-right: 8px; padding: 7px 16px; border: 1px solid #172033; border-radius: 5px; background: #172033; color: #fff; cursor: pointer; }
.actions .ghost { background: #fff; color: #172033; }
.error { padding: 40px; color: #b91c1c; text-align: center; }
.sheet { box-sizing: border-box; width: 190mm; min-height: 267mm; margin: 0 auto; padding: 13mm; background: #fff; box-shadow: 0 6px 30px rgba(15, 23, 42, .12); }
.sheet-header { display: flex; align-items: flex-start; justify-content: space-between; padding-bottom: 2mm; }
.sheet-header p { margin: 0 0 3px; color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 2px; }
h1 { margin: 0; font-size: 29px; letter-spacing: 9px; }
.header-meta { display: flex; margin-top: 4mm; align-items: center; gap: 9mm; color: #475569; font-size: 11px; }
.header-meta strong { color: #111827; font-size: 13px; }
.qr-block { display: flex; align-items: center; }
.qr-block img { width: 19mm; height: 19mm; image-rendering: crisp-edges; }
.meta-section { margin-top: 1mm; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #9ca3af; border-left: 1px solid #9ca3af; }
.meta-grid > div { display: flex; min-height: 10mm; box-sizing: border-box; padding: 1.6mm 2.5mm; border-right: 1px solid #9ca3af; border-bottom: 1px solid #9ca3af; flex-direction: column; justify-content: center; gap: .8mm; }
.meta-grid > div:nth-child(-n + 2) { background: #f1f5f9; }
.meta-grid .wide { grid-column: span 2; }
.meta-grid .process-cell { min-height: 12mm; }
.meta-grid span { color: #64748b; font-size: 9px; }
.meta-grid strong { color: #111827; font-size: 13px; line-height: 1.3; }
.requirements { min-height: 82mm; margin-top: 9mm; border: 1px solid #9ca3af; }
.requirements h2 { margin: 0; padding: 3mm 4mm; border-bottom: 1px solid #9ca3af; background: #f1f5f9; font-size: 14px; letter-spacing: 2px; }
.requirement-row { padding: 4mm; border-bottom: 1px dashed #cbd5e1; }
.requirement-row:last-child { border-bottom: 0; }
.requirement-source { display: block; margin-bottom: 2mm; color: #64748b; font-size: 10px; }
.requirement-row p, .empty-requirement { margin: 0; white-space: pre-wrap; font-size: 13px; line-height: 1.9; }
.empty-requirement { padding: 5mm; color: #94a3b8; }
.image-sheet { display: flex; margin-top: 12mm; flex-direction: column; }
.image-sheet h2 { margin: 0; padding-bottom: 5mm; border-bottom: 2px solid #111827; font-size: 20px; letter-spacing: 4px; }
.image-page-content { display: flex; min-height: 225mm; align-items: center; justify-content: center; }
.image-page-content img { display: block; max-width: 145mm; max-height: 205mm; object-fit: contain; }
@media print {
  @page { size: A4 portrait; margin: 10mm; }
  .no-print { display: none !important; }
  .print-page { min-height: 0; padding: 0; background: #fff; }
  .sheet { width: 190mm; min-height: 277mm; padding: 10mm; box-shadow: none; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .image-sheet { margin-top: 0; break-before: page; page-break-before: always; }
}
</style>

<style>
body:has(.subcontract-print-page) #app {
  max-width: none;
  width: 100%;
  margin: 0;
}

@media print {
  html,
  body {
    margin: 0;
    padding: 0;
  }
}
</style>
