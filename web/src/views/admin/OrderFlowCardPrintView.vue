<template>
  <div class="print-page" :class="{ 'label-mode': mode === 'basket-labels' }">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button
        v-if="mode === 'basket-labels' && !(units || []).length"
        type="button"
        @click="goCutCards"
      >
        去开裁生框码
      </button>
      <button type="button" class="ghost" @click="toggleMode">
        {{ mode === 'flow-card' ? '切换到框码标签' : '切换到生产流转卡' }}
      </button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.is_rush" class="watermark">急单</div>
      <div v-else-if="detail.status === 'cancelled'" class="watermark muted">已取消</div>

      <!-- A4 生产流转卡：普通打印机 -->
      <div v-if="mode === 'flow-card'" class="sheet flow-card">
        <div class="flow-head">
          <div class="flow-head-text">
            <h1 class="doc-title">生 产 流 转 卡</h1>
            <p class="doc-sub">
              A4 · 裁断/成型扫此卡报工 · 单号 {{ displayNo }}
            </p>
          </div>
          <div class="flow-qr-box">
            <img
              v-if="flowQrSrc"
              class="flow-qr"
              :src="flowQrSrc"
              alt="流转卡二维码"
            />
            <small>扫码报工</small>
          </div>
        </div>

        <div class="meta-grid">
          <div v-if="executionNo"><strong>生产单：</strong>{{ executionNo }}</div>
          <div v-if="!isHeaderPrint"><strong>内部单号：</strong>{{ detail.order_no }}</div>
          <div><strong>交期：</strong>{{ detail.delivery_date || '—' }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>颜色：</strong>{{ detail.color_name || '—' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>客户：</strong>{{ customerLabel || '—' }}</div>
          <div><strong>关联销售单：</strong>{{ salesOrderLabel || '—' }}</div>
        </div>

        <div class="section-title">色码数量</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序号</th>
              <th>颜色</th>
              <th>尺码</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, idx) in detail.items || []" :key="it.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ it.color_name || detail.color_name || '—' }}</td>
              <td>{{ it.size_value || '—' }}</td>
              <td class="num">{{ it.qty }}</td>
            </tr>
            <tr v-if="!(detail.items || []).length">
              <td colspan="4" class="empty">（无色码明细）</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计：{{ itemsTotal }} 双</strong>
        </div>

        <div class="section-title">客户做货要求</div>
        <div v-if="workReqs.length" class="req-list">
          <div v-for="(wr, i) in workReqs" :key="wr.sales_order_id || i" class="req-block">
            <div class="req-head">
              <span v-if="wr.sales_order_no">销售单 {{ wr.sales_order_no }}</span>
              <span v-if="wr.brand_name"> · 品牌 {{ wr.brand_name }}</span>
              <span v-if="wr.customer_name"> · {{ wr.customer_name }}</span>
            </div>
            <img v-if="wr.logo_url" class="req-logo" :src="wr.logo_url" alt="品牌logo" />
            <p class="req-notes">{{ wr.notes || '（未填文字要求）' }}</p>
            <img v-if="wr.image_url" class="req-img" :src="wr.image_url" alt="做货要求图" />
          </div>
        </div>
        <div v-else class="empty-inline">本单未填做货要求</div>

        <div class="section-title">工艺路线</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th>工序</th>
              <th class="num">计划</th>
              <th class="chk">完成</th>
              <th>签字/日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in processes" :key="p.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ p.label || p.process_name || '—' }}</td>
              <td class="num">{{ p.plan_qty ?? '—' }}</td>
              <td class="chk">□</td>
              <td class="sign-cell" />
            </tr>
            <tr v-if="!processes.length">
              <td colspan="5" class="empty">（无工序，请先在产品工艺维护后同步到生产单）</td>
            </tr>
          </tbody>
        </table>

        <div class="section-title">本单框编号</div>
        <div v-if="unitsLoading" class="empty">加载框码…</div>
        <div v-else-if="!basketUnits.length" class="empty-box">
          <p>尚未开裁生框。请先「开裁」，再打印框码标签贴筐。</p>
        </div>
        <table v-else>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th>框码</th>
              <th>色 / 码</th>
              <th class="num">计划</th>
              <th>批次</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(u, idx) in basketUnits"
              :key="u.id"
              :class="{ 'voided-row': u.status === 'scrapped' }"
            >
              <td class="seq">{{ idx + 1 }}</td>
              <td class="code-cell">{{ u.code }}</td>
              <td>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</td>
              <td class="num">{{ u.qty }}</td>
              <td>{{ u.batch_no || '—' }}</td>
            </tr>
          </tbody>
        </table>

        <p class="foot-note">
          裁断、成型扫本卡二维码报工；针车扫框码；包装扫箱唛。框码请用标签打印机另打。
        </p>
      </div>

      <!-- 框码标签：标签打印机 -->
      <div v-else class="sheet basket-labels">
        <div class="no-print label-hint">
          <p>
            框码标签 · 请选标签打印机 · 建议纸张 60×40mm（可在打印对话框调整）
          </p>
        </div>
        <div v-if="unitsLoading" class="empty">加载框码…</div>
        <div v-else-if="!basketUnits.length" class="empty-box">
          <p>尚未开裁生框。请先「开裁」生成框码后再打印。</p>
        </div>
        <div v-else class="label-stack">
          <div
            v-for="(u, idx) in basketUnits"
            :key="u.id"
            class="basket-label"
            :class="{ voided: u.status === 'scrapped' }"
          >
            <div class="bl-body">
              <div class="bl-kind">框码</div>
              <div class="bl-code">{{ u.code }}</div>
              <div class="bl-meta">
                <div>{{ detail.product_code || '—' }}</div>
                <div>{{ displayNo }}</div>
                <div>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</div>
                <div>{{ u.qty }} 双</div>
                <div v-if="u.batch_no">裁批 {{ shortBatchNo(u.batch_no) }}</div>
                <div>第 {{ idx + 1 }}/{{ basketUnits.length }} 框</div>
                <div v-if="u.status === 'scrapped'" class="void-tag">已作废</div>
              </div>
            </div>
            <img
              v-if="u.status !== 'scrapped'"
              class="bl-qr"
              :src="qrUrl(u.code)"
              :alt="u.code"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()

const detail = ref<any>(null)
const units = ref<any[]>([])
const unitsLoading = ref(false)
const error = ref('')
const mode = ref<'flow-card' | 'basket-labels'>('flow-card')

const isHeaderPrint = computed(
  () =>
    Boolean(route.meta.executionHeader) ||
    String(route.path || '').includes('/admin/executions/print/'),
)

const displayNo = computed(
  () => detail.value?.header_no || detail.value?.execution_no || detail.value?.order_no || '—',
)

const itemsTotal = computed(() =>
  (detail.value?.items || []).reduce((s: number, it: any) => s + Number(it.qty || 0), 0),
)

const basketUnits = computed(() =>
  (units.value || []).filter(
    (u: any) =>
      u.unit_type === 'basket' &&
      (!Number(route.query.batch_id) || Number(u.batch_id) === Number(route.query.batch_id)),
  ),
)

const processes = computed(() => {
  const d = detail.value
  if (!d) return []
  if (Array.isArray(d.processes) && d.processes.length) return d.processes
  if (Array.isArray(d.process_progress) && d.process_progress.length) return d.process_progress
  return []
})

const workReqs = computed(() => {
  const d = detail.value
  if (!d) return []
  if (Array.isArray(d.work_requirements) && d.work_requirements.length) return d.work_requirements
  if (d.work_requirement && Object.keys(d.work_requirement).length) return [d.work_requirement]
  return []
})

const customerLabel = computed(() => {
  const d = detail.value
  if (!d) return ''
  if (Array.isArray(d.customers) && d.customers.length) return d.customers.join(' / ')
  return d.customer_name || ''
})

const salesOrderLabel = computed(() => {
  const d = detail.value
  if (!d) return ''
  if (Array.isArray(d.sales_order_nos) && d.sales_order_nos.length) {
    return d.sales_order_nos.join(' / ')
  }
  return d.sales_order_no || salesOrderSummary.value || ''
})

const executionNo = computed(() => {
  if (isHeaderPrint.value) {
    return detail.value?.header_no || detail.value?.execution_no || null
  }
  const u = (units.value || []).find((x: any) => x.execution_id)
  return u?.execution_no || null
})

const salesOrderSummary = computed(() => {
  const withSrc = (units.value || []).find(
    (x: any) => Array.isArray(x.allocation_sources) && x.allocation_sources.length,
  )
  if (!withSrc) return ''
  return (withSrc.allocation_sources || [])
    .map((s: any) => s.label || `${s.sales_order_no} ${s.qty}`)
    .join(' / ')
})

const flowQrSrc = computed(() => {
  if (!isHeaderPrint.value) return ''
  const id = Number(route.params.id)
  if (!id) return ''
  return `/api/v1/executions/headers/${id}/flow-card/qr.png`
})

function qrUrl(code: string) {
  return `/api/v1/trace-units/by-code/${encodeURIComponent(code)}/qr.png`
}

function shortBatchNo(batchNo: string) {
  const tail = String(batchNo || '').split('-').pop() || ''
  return tail ? tail.padStart(3, '0') : batchNo
}

function doPrint() {
  const prevTitle = document.title
  const prevUrl = `${location.pathname}${location.search}${location.hash}`
  document.title = ''
  try {
    history.replaceState(null, '', '/')
  } catch {
    /* ignore */
  }
  let restored = false
  const restore = () => {
    if (restored) return
    restored = true
    document.title = prevTitle
    try {
      history.replaceState(null, '', prevUrl)
    } catch {
      /* ignore */
    }
  }
  window.addEventListener('afterprint', restore, { once: true })
  window.print()
}

function closeOrBack() {
  if (window.opener) window.close()
  else router.back()
}

function printBasePath() {
  return isHeaderPrint.value ? '/admin/executions/print' : '/admin/orders/print'
}

function parseMode(raw: unknown): 'flow-card' | 'basket-labels' {
  const m = String(raw || 'flow-card')
  // 兼容旧链接
  if (m === 'main-codes' || m === 'basket-labels' || m === 'labels') return 'basket-labels'
  if (m === 'sheet' || m === 'flow-card') return 'flow-card'
  return 'flow-card'
}

function toggleMode() {
  mode.value = mode.value === 'flow-card' ? 'basket-labels' : 'flow-card'
  syncModeQuery()
}

function syncModeQuery() {
  const id = route.params.id
  router.replace({ path: `${printBasePath()}/${id}`, query: { mode: mode.value } })
}

function goCutCards() {
  const id = Number(route.params.id)
  if (!id) return
  if (isHeaderPrint.value) {
    window.opener?.postMessage?.({ type: 'erp-cut-cards', headerId: id }, '*')
    if (!window.opener) {
      router.push({ path: '/admin/executions', query: { header_id: String(id) } })
    }
    return
  }
  window.opener?.postMessage?.({ type: 'erp-cut-cards', orderId: id }, '*')
  if (!window.opener) {
    router.push({ path: '/admin/orders', query: { cut: String(id) } })
  }
}

async function loadUnits(id: number) {
  unitsLoading.value = true
  try {
    if (detail.value?.baskets?.length) {
      units.value = detail.value.baskets
      return
    }
    const res: any = isHeaderPrint.value
      ? await http.get(`/executions/headers/${id}/trace-units`)
      : await http.get(`/orders/${id}/trace-units`)
    units.value = res.data?.items || res.items || []
  } catch {
    units.value = []
  } finally {
    unitsLoading.value = false
  }
}

function mapHeaderDetail(h: any) {
  const sizeLines = h.size_lines || []
  const items = sizeLines.map((s: any, idx: number) => ({
    id: s.id || idx,
    color_name: h.color_name,
    size_value: s.size_value,
    qty: s.total_qty,
  }))
  return {
    ...h,
    order_no: h.header_no || h.execution_no,
    items,
    processes: h.processes || h.process_progress || [],
  }
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '单号无效'
    return
  }
  mode.value = parseMode(route.query.mode)
  try {
    if (isHeaderPrint.value) {
      const res: any = await http.get(`/executions/headers/${id}/flow-card`)
      detail.value = mapHeaderDetail(res.data)
      if (Array.isArray(res.data?.baskets)) {
        units.value = res.data.baskets
      }
    } else {
      const res: any = await http.get(`/orders/${id}`)
      detail.value = res.data
    }
  } catch {
    error.value = '单据不存在或无权查看'
    return
  }
  if (!units.value.length) await loadUnits(id)
  const titlePrefix = mode.value === 'flow-card' ? '流转卡' : '框码'
  document.title =
    displayNo.value && displayNo.value !== '—' ? `${titlePrefix} ${displayNo.value}` : ''
  if (mode.value === 'basket-labels' && (units.value || []).length) {
    setTimeout(() => {
      document.title = ''
      doPrint()
    }, 500)
  }
}

watch(
  () => route.query.mode,
  (m) => {
    mode.value = parseMode(m)
  },
)

onMounted(load)
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 20px;
  background: #fff;
  color: #111;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  position: relative;
}
.actions {
  margin-bottom: 12px;
}
.actions button {
  margin-right: 8px;
  padding: 6px 12px;
  border: 1px solid #ccc;
  background: #0076ff;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.actions button.ghost {
  background: #fff;
  color: #333;
}
.err {
  color: #c45656;
}
.sheet {
  position: relative;
  max-width: 900px;
  margin: 0 auto;
}
.flow-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}
.flow-head-text {
  flex: 1;
}
.flow-qr-box {
  text-align: center;
  flex-shrink: 0;
}
.flow-qr {
  width: 112px;
  height: 112px;
  object-fit: contain;
  display: block;
}
.flow-qr-box small {
  display: block;
  margin-top: 2px;
  color: #555;
  font-size: 11px;
}
.doc-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin: 0;
  letter-spacing: 0.28em;
}
.doc-sub {
  text-align: center;
  margin: 6px 0 0;
  color: #555;
  font-size: 12px;
  letter-spacing: 0.08em;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  margin: 10px 0 14px;
  line-height: 1.7;
}
.meta-grid strong {
  color: #555;
  font-weight: 500;
}
.section-title {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 700;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  border: 1px solid #333;
  padding: 7px 8px;
  text-align: left;
  vertical-align: middle;
}
th {
  background: #f3f4f6;
  font-weight: 600;
}
.seq {
  text-align: center !important;
  width: 48px;
}
.num {
  text-align: right !important;
  width: 72px;
}
.chk {
  text-align: center !important;
  width: 56px;
  font-size: 14px;
}
.sign-cell {
  min-width: 120px;
  height: 28px;
}
.code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.empty {
  text-align: center;
  color: #666;
}
.empty-inline {
  color: #666;
  padding: 8px 0;
}
.empty-box {
  border: 1px dashed #999;
  padding: 24px;
  text-align: center;
  margin: 12px 0;
}
.totals {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
}
.req-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.req-block {
  border: 1px solid #ccc;
  padding: 10px 12px;
}
.req-head {
  font-weight: 600;
  margin-bottom: 6px;
}
.req-logo {
  max-height: 48px;
  max-width: 160px;
  object-fit: contain;
  margin-bottom: 6px;
}
.req-notes {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}
.req-img {
  margin-top: 8px;
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
}
.foot-note {
  margin-top: 16px;
  color: #555;
  font-size: 11px;
}
.voided-row {
  opacity: 0.45;
  text-decoration: line-through;
}
.void-tag {
  color: #c45656;
  font-weight: 600;
}

/* 框码标签（标签打印机） */
.label-hint {
  margin-bottom: 12px;
  color: #555;
  font-size: 13px;
}
.label-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.basket-label {
  width: 60mm;
  min-height: 40mm;
  box-sizing: border-box;
  border: 1px solid #222;
  padding: 3mm;
  display: grid;
  grid-template-columns: 1fr 28mm;
  gap: 2mm;
  align-items: center;
  break-inside: avoid;
  page-break-inside: avoid;
  page-break-after: always;
}
.basket-label:last-child {
  page-break-after: auto;
}
.basket-label.voided {
  opacity: 0.45;
}
.bl-kind {
  font-size: 10px;
  color: #555;
  letter-spacing: 0.12em;
}
.bl-code {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
  margin: 2px 0 4px;
  word-break: break-all;
}
.bl-meta {
  font-size: 11px;
  line-height: 1.45;
  color: #222;
}
.bl-qr {
  width: 26mm;
  height: 26mm;
  object-fit: contain;
}
.watermark {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 0;
  opacity: 0.12;
  font-size: 72px;
  font-weight: 700;
  color: #c45656;
  transform: rotate(-24deg);
}
.watermark.muted {
  color: #888;
}
.sheet > * {
  position: relative;
  z-index: 1;
}

@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
  .print-page:not(.label-mode) {
    padding: 8mm 10mm;
  }
  .sheet {
    max-width: none;
    width: 100%;
    margin: 0 auto;
  }
  .label-mode .sheet {
    max-width: none;
  }
}
</style>

<style>
@page {
  size: A4 portrait;
  margin: 10mm 12mm;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
body:has(.print-page.label-mode) {
  margin: 0;
}
</style>
