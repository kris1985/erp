<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">登记到货</h1>

      <div v-if="bootError" class="card-block" style="color: #c00">{{ bootError }}</div>

      <div v-else-if="!auth.token || auth.isWorker" class="card-block">
        <p class="muted">请用后台账号登录后再登记到货</p>
        <van-button type="primary" block round @click="goLogin">去登录</van-button>
      </div>

      <div v-else-if="loading" class="card-block muted">加载采购单…</div>

      <template v-else-if="detail">
        <div class="card-block po-card">
          <div class="po-head">
            <div class="po-no">{{ detail.po_no }}</div>
            <div class="po-status">{{ detail.status_label || detail.status }}</div>
          </div>
          <div class="po-meta muted">
            {{ detail.partner_name || '—' }}
            <template v-if="detail.expected_date"> · {{ detail.expected_date }}</template>
            <template v-if="detail.tracking_no"> · {{ detail.tracking_no }}</template>
          </div>
        </div>

        <div v-if="!canReceive" class="card-block" style="color: #c00">
          当前状态不可到货
        </div>

        <template v-else>
          <p class="hint muted">点「未收」可填入；确认后按比例拆到订单行</p>

          <div class="recv-list">
            <div v-for="batch in batches" :key="batch.key" class="recv-row">
              <div class="recv-info">
                <div class="recv-title">
                  <span class="recv-code">{{ batch.supplier_product_code || '—' }}</span>
                  <span class="recv-name">{{ batch.supplier_product_name || '' }}</span>
                  <span v-if="batch.size_value" class="recv-size">{{ batch.size_value }}</span>
                </div>
                <button type="button" class="recv-open" @click="fillOpen(batch)">
                  未收 {{ formatNum(batch.open_total) }}
                  <template v-if="batch.pricing_unit_name">{{ batch.pricing_unit_name }}</template>
                </button>
              </div>
              <input
                v-model="batch.total_qty_str"
                class="recv-qty"
                type="number"
                inputmode="decimal"
                :placeholder="String(batch.open_total)"
              />
            </div>
          </div>

          <div class="big-btn">
            <van-button
              round
              block
              type="primary"
              :loading="submitting"
              :disabled="!hasQty"
              @click="onSubmit"
            >
              确认到货
            </van-button>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type RecvLine = {
  id: number
  supplier_product_id: number
  supplier_product_code?: string
  supplier_product_name?: string
  pricing_unit_name?: string
  order_no?: string
  size_id?: number | null
  size_value?: string | null
  qty: number
  received_qty: number
  open_qty: number
}

type RecvBatch = {
  key: string
  supplier_product_id: number
  supplier_product_code?: string
  supplier_product_name?: string
  pricing_unit_name?: string
  size_id?: number | null
  size_value?: string | null
  open_total: number
  total_qty_str: string
  lines: RecvLine[]
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const submitting = ref(false)
const bootError = ref('')
const detail = ref<any>(null)
const lines = ref<RecvLine[]>([])
const batches = ref<RecvBatch[]>([])

const canReceive = computed(() => {
  const s = detail.value?.status
  return s === 'ordered' || s === 'shipped' || s === 'partial_received'
})

const hasQty = computed(() =>
  batches.value.some((b) => Number(b.total_qty_str) > 0),
)

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function goLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

function fillOpen(batch: RecvBatch) {
  batch.total_qty_str = String(batch.open_total)
}

function buildBatches(recvLines: RecvLine[]) {
  const map = new Map<string, RecvBatch>()
  for (const ln of recvLines) {
    const sizeId = ln.size_id || 0
    const key = `${ln.supplier_product_id}:${sizeId}`
    if (!map.has(key)) {
      map.set(key, {
        key,
        supplier_product_id: ln.supplier_product_id,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        pricing_unit_name: ln.pricing_unit_name,
        size_id: ln.size_id,
        size_value: ln.size_value,
        open_total: 0,
        total_qty_str: '0',
        lines: [],
      })
    }
    const b = map.get(key)!
    b.open_total += ln.open_qty
    b.lines.push(ln)
  }
  for (const b of map.values()) {
    b.total_qty_str = String(b.open_total)
  }
  return [...map.values()]
}

/** 按未收比例拆到各行；超量加到最后一行 */
function splitBatch(batch: RecvBatch): { line_id: number; qty: number }[] {
  const total = Math.max(0, Number(batch.total_qty_str) || 0)
  const recvLines = batch.lines
  if (total <= 0 || !recvLines.length) return []
  const openSum = recvLines.reduce((s, l) => s + (Number(l.open_qty) || 0), 0)
  if (openSum <= 0) {
    return [{ line_id: recvLines[0].id, qty: total }]
  }
  let left = total
  const withOpen = recvLines.filter((l) => Number(l.open_qty) > 0)
  const out: { line_id: number; qty: number }[] = []
  withOpen.forEach((ln, idx) => {
    const open = Number(ln.open_qty) || 0
    if (idx === withOpen.length - 1) {
      out.push({ line_id: ln.id, qty: Math.max(0, left) })
      return
    }
    const share = Math.min(open, Math.round((total * open) / openSum))
    out.push({ line_id: ln.id, qty: share })
    left -= share
  })
  if (left > 0 && out.length) {
    out[out.length - 1].qty += left
  } else if (left > 0) {
    out.push({ line_id: recvLines[0].id, qty: left })
  }
  return out.filter((x) => x.qty > 0)
}

async function load() {
  const id = Number(route.params.id)
  if (!Number.isFinite(id) || id <= 0) {
    bootError.value = '链接无效'
    loading.value = false
    return
  }
  if (!auth.token || auth.isWorker) {
    loading.value = false
    return
  }
  loading.value = true
  bootError.value = ''
  try {
    const res: any = await http.get(`/purchase-orders/${id}`)
    const po = res.data
    detail.value = po
    document.title = po?.po_no ? `${po.po_no} · 到货` : '登记到货'
    lines.value = (po.lines || []).map((ln: any) => {
      const open = Math.max(0, Number(ln.qty) - Number(ln.received_qty || 0))
      return { ...ln, open_qty: open }
    })
    batches.value = buildBatches(lines.value)
  } catch (e: any) {
    bootError.value =
      e?.error?.message || e?.response?.data?.error?.message || e?.response?.data?.detail || '采购单不存在或无权查看'
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  if (!detail.value || !hasQty.value) return
  const payload = batches.value.flatMap(splitBatch)
  if (!payload.length) {
    showToast('请填写本次到货数量')
    return
  }
  try {
    await showConfirmDialog({
      title: '确认到货',
      message: `共 ${payload.length} 行，确认提交？`,
    })
  } catch {
    return
  }
  submitting.value = true
  try {
    const res: any = await http.post(`/purchase-orders/${detail.value.id}/receive`, {
      lines: payload,
    })
    const n = res.data?.iqc_pending_count
    if (n) {
      showToast(`已登记，生成 ${n} 条待检`)
    } else {
      showToast('到货已登记')
    }
    await load()
  } catch (e: any) {
    // http 拦截器已 toast ok:false；网络错误再补一句
    if (e?.message && !e?.error && !e?.response) {
      showToast(e.message)
    }
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-title {
  margin-top: 16px;
  margin-bottom: 16px;
  padding-top: 8px;
  padding-bottom: 4px;
}
.po-card {
  padding: 12px 14px;
  margin-bottom: 10px;
}
.po-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}
.po-no {
  font-weight: 700;
  font-size: 16px;
}
.po-status {
  font-size: 12px;
  color: var(--ws-muted, #64748b);
  flex-shrink: 0;
}
.po-meta {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.35;
}
.hint {
  margin: 0 4px 8px;
  font-size: 12px;
  line-height: 1.35;
}
.recv-list {
  background: var(--ws-bg-elevated, #fff);
  border-radius: var(--ws-radius, 12px);
  box-shadow: var(--ws-shadow-soft, 0 1px 4px rgba(0, 0, 0, 0.06));
  overflow: hidden;
  margin-bottom: 8px;
}
.recv-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}
.recv-row:last-child {
  border-bottom: none;
}
.recv-info {
  flex: 1;
  min-width: 0;
}
.recv-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 6px;
  line-height: 1.3;
}
.recv-code {
  font-weight: 650;
  font-size: 14px;
}
.recv-name {
  font-size: 13px;
  color: var(--ws-ink, #1f2937);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.recv-size {
  font-size: 12px;
  color: var(--ws-muted, #64748b);
  flex-shrink: 0;
}
.recv-open {
  margin-top: 2px;
  padding: 0;
  border: none;
  background: none;
  font-size: 12px;
  color: var(--ws-primary, #1a6b4a);
  line-height: 1.3;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.recv-qty {
  width: 72px;
  flex-shrink: 0;
  height: 36px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  text-align: center;
  font-size: 16px;
  font-weight: 600;
  color: var(--ws-ink, #1f2937);
  background: #f8faf9;
  outline: none;
}
.recv-qty:focus {
  border-color: var(--ws-primary, #1a6b4a);
  background: #fff;
}
.big-btn {
  margin: 16px 4px 28px;
}
</style>
