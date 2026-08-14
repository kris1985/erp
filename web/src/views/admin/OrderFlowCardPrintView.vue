<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button
        v-if="mode === 'main-codes' && !(units || []).length"
        type="button"
        @click="goCutCards"
      >
        去开裁打主码
      </button>
      <button type="button" class="ghost" @click="toggleMode">
        {{ mode === 'main-codes' ? '查看旧版流转表' : '查看主码标签' }}
      </button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.is_rush" class="watermark">急单</div>
      <div v-else-if="detail.status === 'cancelled'" class="watermark muted">已取消</div>

      <!-- B2h / AU-I0：主码标签（筐=流转卡，捆=扎捆） -->
      <div v-if="mode === 'main-codes'" class="sheet main-codes">
        <h1 class="doc-title">{{ hasBasket ? '生 产 流 转 卡 / 扎 捆' : '货 上 主 码' }}</h1>
        <p class="doc-sub">
          {{
            hasBasket
              ? hasBundle
                ? `开裁 · 筐卡+扎捆 · 扫码报工 · 单号 ${displayNo}`
                : `开裁 · 仅流转卡 · 扫码报工 · 单号 ${displayNo}`
              : `开裁 / 一码一捆 · 扫码报工 · 单号 ${displayNo}`
          }}
          <template v-if="executionNo"> · 执行单 {{ executionNo }}</template>
        </p>

        <div class="meta-grid">
          <div v-if="executionNo"><strong>执行单：</strong>{{ executionNo }}</div>
          <div v-if="!isHeaderPrint"><strong>内部单号：</strong>{{ detail.order_no }}</div>
          <div><strong>交期：</strong>{{ detail.delivery_date || '—' }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>客户：</strong>{{ detail.customer_name || '—' }}</div>
          <div><strong>关联销售单：</strong>{{ salesOrderSummary || detail.sales_order_no || '—' }}</div>
        </div>

        <div v-if="unitsLoading" class="empty">加载主码…</div>
        <div v-else-if="!(units || []).length" class="empty-box">
          <p>尚未开裁生码。请先「开裁打主码」，再打印本页。</p>
          <p class="muted">报工请扫货上主码，勿扫合批号。</p>
        </div>
        <template v-else>
          <div v-if="basketUnits.length" class="section-title">生产流转卡（筐）</div>
          <div v-if="basketUnits.length" class="label-grid">
            <div
              v-for="u in basketUnits"
              :key="u.id"
              class="label-card basket"
              :class="{ voided: u.status === 'scrapped' }"
            >
              <div>
                <div class="label-kind">生产流转卡</div>
                <div class="label-code">{{ u.code }}</div>
                <div class="label-meta">
                  <div>{{ detail.product_code || '—' }}</div>
                  <div>{{ displayNo }}</div>
                  <div>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</div>
                  <div>计划 {{ u.qty }} 双</div>
                  <div v-if="childCount(u.id)" class="muted">含 {{ childCount(u.id) }} 扎捆</div>
                  <div v-if="allocLabel(u)" class="alloc">来源 {{ allocLabel(u) }}</div>
                  <div class="muted">
                    {{ childCount(u.id) ? '合帮后扫此卡' : '未打扎捆：合帮前也可扫此卡报个人或代报' }}
                  </div>
                  <div v-if="u.status === 'scrapped'" class="void-tag">已作废</div>
                </div>
              </div>
              <img
                v-if="u.status !== 'scrapped'"
                class="qr"
                :src="qrUrl(u.code)"
                :alt="u.code"
              />
            </div>
          </div>

          <div class="section-title">{{ hasBasket ? '扎捆码' : '主码（捆）' }}</div>
          <div class="label-grid">
            <div
              v-for="u in bundleUnits"
              :key="u.id"
              class="label-card"
              :class="{ voided: u.status === 'scrapped' }"
            >
              <div>
                <div v-if="u.part_name" class="label-kind">{{ u.part_name }}</div>
                <div class="label-code">{{ u.code }}</div>
                <div class="label-meta">
                  <div>{{ detail.product_code || '—' }}</div>
                  <div>{{ displayNo }}</div>
                  <div>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</div>
                  <div>{{ u.qty }} 双</div>
                  <div v-if="u.parent_code" class="muted">所属筐卡：{{ u.parent_code }}</div>
                  <div class="muted">合帮前扫此码报个人或代报</div>
                  <div v-if="u.status === 'scrapped'" class="void-tag">已作废</div>
                </div>
              </div>
              <img
                v-if="u.status !== 'scrapped'"
                class="qr"
                :src="qrUrl(u.code)"
                :alt="u.code"
              />
            </div>
          </div>
        </template>
        <p class="foot-note">
          {{
            hasBasket
              ? hasBundle
                ? '合帮前扫扎捆码报个人或代报；合帮及之后扫流转卡。补打请用同码。'
                : '未打扎捆：合帮前也可扫流转卡报个人或组长代报。补打请用同码。'
              : '扫码进入本捆报工 / 不良登记。一码一捆，补打请用同码。'
          }}
        </p>
      </div>

      <!-- 旧版对照附录 -->
      <div v-else class="sheet">
        <h1 class="doc-title">生 产 流 转 卡</h1>
        <p class="doc-sub">开裁 / 配码 · 内部单（附录，报工请扫主码页）</p>

        <div class="meta-grid">
          <div><strong>内部单号：</strong>{{ detail.order_no }}</div>
          <div><strong>交期：</strong>{{ detail.delivery_date || '—' }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>客户：</strong>{{ detail.customer_name || '—' }}</div>
          <div>
            <strong>关联销售单：</strong>{{ detail.sales_order_no || '—' }}
          </div>
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
              <td>{{ it.color_name || '—' }}</td>
              <td>{{ it.size_value || '—' }}</td>
              <td class="num">{{ it.qty }}</td>
            </tr>
            <tr v-if="!(detail.items || []).length">
              <td colspan="4" class="empty">（无色码明细，请先在执行单维护色码）</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计：{{ itemsTotal }} 双</strong>
          <span v-if="qtyMismatch" class="warn">（与单头总数量 {{ detail.total_qty }} 不一致，请核对）</span>
        </div>

        <div class="section-title">工序流转</div>
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
            <tr v-for="(p, idx) in detail.processes || []" :key="p.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ p.process_name || '—' }}</td>
              <td class="num">{{ p.plan_qty ?? '—' }}</td>
              <td class="chk">□</td>
              <td class="sign-cell" />
            </tr>
            <tr v-if="!(detail.processes || []).length">
              <td colspan="5" class="empty">（无工序，请先在产品工艺维护后同步到执行单）</td>
            </tr>
          </tbody>
        </table>

        <div class="note">备注：{{ detail.notes || '无' }}</div>
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
const mode = ref<'main-codes' | 'sheet'>('main-codes')

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

const qtyMismatch = computed(() => {
  if (!detail.value) return false
  const head = Number(detail.value.total_qty || 0)
  return head > 0 && itemsTotal.value > 0 && head !== itemsTotal.value
})

const printableUnits = computed(() => units.value || [])
const hasBasket = computed(() =>
  (units.value || []).some((u: any) => u.unit_type === 'basket'),
)
const hasBundle = computed(() =>
  (units.value || []).some((u: any) => u.unit_type !== 'basket'),
)
const basketUnits = computed(() =>
  (units.value || []).filter((u: any) => u.unit_type === 'basket'),
)
const bundleUnits = computed(() =>
  (units.value || []).filter((u: any) => u.unit_type !== 'basket'),
)

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

function childCount(basketId: number) {
  return (units.value || []).filter((u: any) => u.parent_id === basketId).length
}

function allocLabel(u: any) {
  const src = u?.allocation_sources
  if (!Array.isArray(src) || !src.length) return ''
  return src.map((s: any) => s.label || `${s.sales_order_no} ${s.qty}`).join(' / ')
}

function qrUrl(code: string) {
  return `/api/v1/trace-units/by-code/${encodeURIComponent(code)}/qr.png`
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

function toggleMode() {
  mode.value = mode.value === 'main-codes' ? 'sheet' : 'main-codes'
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
  // 无 opener 时回到订单列表由人工开裁
  if (!window.opener) {
    router.push({ path: '/admin/orders', query: { cut: String(id) } })
  }
}

async function loadUnits(id: number) {
  unitsLoading.value = true
  try {
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
    processes: h.processes || [],
  }
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '单号无效'
    return
  }
  const qMode = String(route.query.mode || 'main-codes')
  mode.value = qMode === 'sheet' ? 'sheet' : 'main-codes'
  try {
    if (isHeaderPrint.value) {
      const res: any = await http.get(`/executions/headers/${id}`)
      detail.value = mapHeaderDetail(res.data)
    } else {
      const res: any = await http.get(`/orders/${id}`)
      detail.value = res.data
    }
  } catch {
    error.value = '单据不存在或无权查看'
    return
  }
  await loadUnits(id)
  document.title = displayNo.value && displayNo.value !== '—' ? `主码 ${displayNo.value}` : ''
  if (mode.value === 'main-codes' && (units.value || []).length) {
    setTimeout(() => {
      document.title = ''
      doPrint()
    }, 500)
  }
}

watch(
  () => route.query.mode,
  (m) => {
    mode.value = String(m || 'main-codes') === 'sheet' ? 'sheet' : 'main-codes'
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
.doc-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin: 0;
  letter-spacing: 0.28em;
}
.doc-sub {
  text-align: center;
  margin: 6px 0 16px;
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
.empty {
  text-align: center;
  color: #666;
}
.empty-box {
  border: 1px dashed #999;
  padding: 24px;
  text-align: center;
  margin: 20px 0;
}
.empty-box .muted {
  color: #888;
  font-size: 12px;
}
.totals {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
  line-height: 1.7;
}
.totals .warn {
  margin-left: 8px;
  color: #c45656;
  font-size: 12px;
}
.note {
  margin-top: 12px;
  color: #444;
}
.foot-note {
  margin-top: 16px;
  color: #555;
  font-size: 11px;
}
.label-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 12px;
}
.label-card {
  border: 1px solid #222;
  border-radius: 4px;
  padding: 10px;
  display: grid;
  grid-template-columns: 1fr 96px;
  gap: 8px;
  align-items: center;
  break-inside: avoid;
  page-break-inside: avoid;
}
.label-card.voided {
  opacity: 0.45;
}
.label-kind {
  font-size: 11px;
  color: #555;
  letter-spacing: 0.08em;
  margin-bottom: 2px;
}
.label-code {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.label-card.basket {
  border-width: 2px;
}
.label-meta .muted {
  color: #666;
  font-size: 11px;
}
.label-meta .alloc {
  margin-top: 2px;
  font-weight: 600;
  font-size: 11px;
  line-height: 1.35;
}
.label-meta {
  font-size: 12px;
  line-height: 1.5;
  color: #222;
}
.void-tag {
  color: #c45656;
  font-weight: 600;
}
.qr {
  width: 96px;
  height: 96px;
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
    padding: 8mm 10mm;
  }
  .sheet {
    max-width: none;
    width: 100%;
    margin: 0 auto;
  }
  .label-grid {
    grid-template-columns: repeat(2, 1fr);
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
</style>
