<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印箱唛</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="carton">
      <div class="label-card">
        <div class="brand">箱唛</div>
        <div class="head">
          <div class="meta">
            <div><span>客户</span><b>{{ carton.customer_name || '—' }}</b></div>
            <div><span>订单号</span><b class="primary-value">{{ carton.sales_order_no || '—' }}</b></div>
            <div><span>客户型号</span><b>{{ carton.customer_sku || '—' }}</b></div>
            <div v-if="carton.brand_name"><span>品牌</span><b>{{ carton.brand_name }}</b></div>
            <div><span>颜色</span><b>{{ colorLabel }}</b></div>
          </div>
          <div class="qr-box">
            <img v-if="qrSrc" class="qr" :src="qrSrc" alt="箱码二维码" />
            <small>扫箱号</small>
          </div>
        </div>
        <div class="summary">
          <div><span>箱号</span><strong>{{ carton.seq }} OF {{ carton.carton_count || '—' }}</strong></div>
          <div><span>总数</span><strong>{{ carton.total_qty }} 双</strong></div>
        </div>
        <table class="size-matrix">
          <tbody>
            <tr>
              <th>尺码</th>
              <td v-for="cell in sizeMatrix" :key="`size-${cell.size}`">{{ cell.size }}</td>
            </tr>
            <tr>
              <th>双数</th>
              <td v-for="cell in sizeMatrix" :key="`qty-${cell.size}`"><strong>{{ cell.qty }}</strong></td>
            </tr>
          </tbody>
        </table>
        <div v-if="carton.line_notes" class="notes"><span>备注</span><b>{{ carton.line_notes }}</b></div>
        <div class="trace-footer">
          <div><span>内部生产单</span><b>{{ carton.order_no || '—' }}</b></div>
          <div><span>工厂型号</span><b>{{ carton.product_code || '—' }}</b></div>
          <div><span>箱码</span><b class="code">{{ carton.code }}</b></div>
        </div>
        <div v-if="carton.verified_at" class="verified">已验箱 {{ formatTime(carton.verified_at) }}</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()
const carton = ref<any>(null)
const error = ref('')

const qrSrc = computed(() => {
  const code = carton.value?.code
  if (!code) return ''
  return `/api/v1/packing-cartons/by-code/${encodeURIComponent(code)}/qr.png`
})

const sizeMatrix = computed(() => {
  const lines = carton.value?.lines || []
  const grouped = new Map<string, number>()
  for (const line of lines) {
    const size = String(line.size_value || '').trim()
    if (!size) continue
    grouped.set(size, Number(grouped.get(size) || 0) + Number(line.qty || 0))
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => {
      const na = Number(a)
      const nb = Number(b)
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
      return a.localeCompare(b, 'zh')
    })
    .map(([size, qty]) => ({ size, qty }))
})

const colorLabel = computed(() => {
  const colors = [...new Set((carton.value?.lines || []).map((line: any) => line.color_name).filter(Boolean))]
  return colors.join(' / ') || '—'
})

function formatTime(v?: string) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : ''
}

async function load() {
  error.value = ''
  const id = Number(route.params.id)
  try {
    const res: any = await http.get(`/packing-cartons/${id}`)
    carton.value = res.data
    document.title = `箱唛 ${carton.value?.code || id}`
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  }
}

function doPrint() {
  window.print()
}

function closeOrBack() {
  if (window.history.length > 1) router.back()
  else window.close()
}

onMounted(load)
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding: 16px;
}
.actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.actions button {
  border: 1px solid #cbd5e1;
  background: #fff;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.actions .ghost {
  background: transparent;
}
.err {
  color: #b91c1c;
}
.label-card {
  width: 380px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #111;
  padding: 14px 16px 16px;
}
.brand {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-align: center;
  margin-bottom: 10px;
}
.head {
  display: grid;
  grid-template-columns: 1fr 112px;
  gap: 10px;
  align-items: start;
  margin-bottom: 10px;
}
.meta {
  display: grid;
  gap: 4px;
  font-size: 13px;
}
.meta div {
  display: grid;
  grid-template-columns: 52px 1fr;
  gap: 8px;
}
.meta span {
  color: #64748b;
}
.meta b {
  font-weight: 650;
}
.primary-value {
  font-size: 15px;
  line-height: 1.2;
  word-break: break-all;
}
.code {
  word-break: break-all;
}
.qr-box {
  text-align: center;
}
.qr {
  width: 104px;
  height: 104px;
  display: block;
  margin: 0 auto;
  image-rendering: pixelated;
}
.qr-box small {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #64748b;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 4px 0 10px;
  border: 1px solid #111;
}
.summary > div {
  display: grid;
  gap: 2px;
  padding: 7px 10px;
  text-align: center;
}
.summary > div + div {
  border-left: 1px solid #111;
}
.summary span {
  color: #64748b;
  font-size: 11px;
}
.summary strong {
  font-size: 20px;
  line-height: 1.15;
}
th,
td {
  border: 1px solid #111;
  padding: 4px 6px;
  text-align: left;
}
.size-matrix {
  table-layout: fixed;
}
.size-matrix th {
  width: 48px;
  background: #f3f4f6;
  text-align: center;
}
.size-matrix td {
  text-align: center;
  font-size: 14px;
  padding: 6px 2px;
}
.notes,
.trace-footer > div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
}
.notes {
  margin-top: 9px;
  padding: 6px 8px;
  border: 1px solid #111;
  font-size: 12px;
}
.notes span,
.trace-footer span {
  color: #64748b;
}
.trace-footer {
  display: grid;
  gap: 3px;
  margin-top: 9px;
  padding-top: 7px;
  border-top: 1px dashed #94a3b8;
  font-size: 11px;
}
.trace-footer b {
  font-weight: 600;
}
.verified {
  margin-top: 8px;
  font-size: 12px;
  color: #166534;
}
@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    background: #fff;
    padding: 0;
  }
  .label-card {
    border-color: #000;
    width: 100%;
    max-width: 95mm;
  }
}
</style>
