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
            <div><span>内部单号</span><b>{{ carton.order_no || '—' }}</b></div>
            <div><span>货号</span><b>{{ carton.product_code || '—' }}</b></div>
            <div>
              <span>箱号</span>
              <b>{{ carton.seq }} / {{ carton.carton_count || '—' }}</b>
            </div>
            <div><span>箱码</span><b class="code">{{ carton.code }}</b></div>
            <div><span>合计</span><b>{{ carton.total_qty }} 双</b></div>
          </div>
          <div class="qr-box">
            <img v-if="qrSrc" class="qr" :src="qrSrc" alt="箱码二维码" />
            <small>扫箱号</small>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>颜色</th>
              <th>尺码</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ln in carton.lines || []" :key="ln.id">
              <td>{{ ln.color_name || '—' }}</td>
              <td>{{ ln.size_value || '—' }}</td>
              <td class="num">{{ ln.qty }}</td>
            </tr>
          </tbody>
        </table>
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
th,
td {
  border: 1px solid #111;
  padding: 4px 6px;
  text-align: left;
}
th.num,
td.num {
  text-align: right;
  width: 64px;
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
