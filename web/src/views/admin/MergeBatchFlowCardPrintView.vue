<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="toggleMode">
        {{ mode === 'main-codes' ? '查看合批流转卡' : '查看货上主码' }}
      </button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <!-- 合批一页全员主码 -->
      <div v-if="mode === 'main-codes'" class="sheet main-codes">
        <h1 class="doc-title">合 批 货 上 主 码</h1>
        <p class="doc-sub">
          {{ detail.batch_no }} · 一码一捆 · 仍分成员单 · 勿扫合批号报工
        </p>

        <div class="meta-grid">
          <div><strong>合批号：</strong>{{ detail.batch_no }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || unitsPayload?.product_code || '—' }}</div>
          <div><strong>成员单数：</strong>{{ detail.member_count ?? 0 }}</div>
          <div><strong>主码枚数：</strong>{{ unitsPayload?.unit_count ?? printableCount }}</div>
        </div>

        <div v-if="unitsLoading" class="empty">加载主码…</div>
        <div v-else-if="!memberUnitGroups.length" class="empty-box">
          <p>成员尚未开裁生码。请在合批详情点「批量开裁打主码」。</p>
        </div>
        <template v-else>
          <div v-for="g in memberUnitGroups" :key="g.order_id" class="member-block">
            <div class="section-title">
              {{ g.order_no }}
              <span class="muted"> · {{ g.customer_name || '—' }} · {{ g.units.length }} 枚</span>
            </div>
            <div v-if="!g.units.length" class="empty">（本单尚无主码）</div>
            <div v-else class="label-grid">
              <div
                v-for="u in g.units"
                :key="u.id"
                class="label-card"
                :class="{ voided: u.status === 'scrapped' }"
              >
                <div class="label-meta-wrap">
                  <div class="label-code">{{ u.code }}</div>
                  <div class="label-meta">
                    <div>{{ detail.product_code || unitsPayload?.product_code || '—' }}</div>
                    <div>{{ g.order_no }}</div>
                    <div v-if="detail.batch_no" class="batch-tag">{{ detail.batch_no }}</div>
                    <div>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</div>
                    <div>{{ u.qty }} 双</div>
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
          </div>
        </template>
        <p class="foot-note">
          贴标前按成员单分堆。扫码进入本捆报工 / 不良；合批号仅对照，不可报工。
        </p>
      </div>

      <!-- 旧合批流转卡 -->
      <div v-else class="sheet">
        <h1 class="doc-title">合 批 流 转 卡</h1>
        <p class="doc-sub">开裁 / 配码 · 合批（领料报工仍分成员单）</p>

        <div class="meta-grid">
          <div><strong>合批号：</strong>{{ detail.batch_no }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>颜色：</strong>{{ detail.color_name || '多色/未锁定' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>成员单数：</strong>{{ detail.member_count ?? 0 }}</div>
          <div><strong>状态：</strong>{{ statusLabel }}</div>
        </div>

        <div class="section-title">成员单</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序号</th>
              <th>成员单号</th>
              <th>客户</th>
              <th>交期</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, idx) in detail.members || []" :key="m.order_id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ m.order_no }}</td>
              <td>{{ m.customer_name || '—' }}</td>
              <td>{{ m.delivery_date || '—' }}</td>
              <td class="num">{{ m.total_qty }}</td>
            </tr>
            <tr v-if="!(detail.members || []).length">
              <td colspan="5" class="empty">（无成员）</td>
            </tr>
          </tbody>
        </table>

        <div class="section-title">汇总色码</div>
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
            <tr
              v-for="(it, idx) in detail.size_summary || []"
              :key="`${it.color_id}-${it.size_id}-${idx}`"
            >
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ it.color_name || '—' }}</td>
              <td>{{ it.size_value || '—' }}</td>
              <td class="num">{{ it.qty }}</td>
            </tr>
            <tr v-if="!(detail.size_summary || []).length">
              <td colspan="4" class="empty">（无汇总色码）</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计：{{ itemsTotal }} 双</strong>
        </div>

        <div class="section-title">工序流转（纸面参考，报工仍分单）</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th>工序</th>
              <th class="num">计划合计</th>
              <th class="chk">完成</th>
              <th>签字/日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in detail.processes || []" :key="p.process_id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ p.process_name || '—' }}</td>
              <td class="num">{{ p.plan_qty ?? '—' }}</td>
              <td class="chk">□</td>
              <td class="sign-cell" />
            </tr>
            <tr v-if="!(detail.processes || []).length">
              <td colspan="5" class="empty">（成员尚无工序，可仅作开裁色码参考）</td>
            </tr>
          </tbody>
        </table>

        <div class="note">备注：{{ detail.note || '无' }}</div>
        <p class="foot-note">报工请扫各单货上主码，勿扫合批号。</p>

        <div class="sign">
          <div>
            <label>开卡 / PMC</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
          <div>
            <label>裁床确认</label>
            <div class="line" />
            <div class="date">日期：________</div>
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
const unitsPayload = ref<any>(null)
const unitsLoading = ref(false)
const error = ref('')
const mode = ref<'main-codes' | 'sheet'>('sheet')

const itemsTotal = computed(() =>
  (detail.value?.size_summary || []).reduce((s: number, it: any) => s + Number(it.qty || 0), 0),
)

const statusLabel = computed(() => {
  const s = detail.value?.status
  if (s === 'open') return '进行中'
  if (s === 'closed') return '已关闭'
  if (s === 'void') return '已作废'
  return s || '—'
})

const memberUnitGroups = computed(() => unitsPayload.value?.members || [])

const printableCount = computed(() =>
  memberUnitGroups.value.reduce((n: number, g: any) => n + (g.units || []).length, 0),
)

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

function toggleMode() {
  const next = mode.value === 'main-codes' ? 'sheet' : 'main-codes'
  mode.value = next
  router.replace({ query: { ...route.query, mode: next } })
}

async function loadUnits(batchId: number) {
  unitsLoading.value = true
  try {
    const res: any = await http.get(`/merge-batches/${batchId}/trace-units`)
    unitsPayload.value = res.data
  } catch {
    unitsPayload.value = null
  } finally {
    unitsLoading.value = false
  }
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '合批无效'
    return
  }
  const qMode = String(route.query.mode || 'sheet')
  mode.value = qMode === 'main-codes' ? 'main-codes' : 'sheet'
  try {
    const res: any = await http.get(`/merge-batches/${id}`)
    detail.value = res.data
  } catch {
    error.value = '合批不存在或无权查看'
    return
  }
  if (mode.value === 'main-codes') {
    await loadUnits(id)
  }
  document.title = detail.value?.batch_no
    ? mode.value === 'main-codes'
      ? `合批主码 ${detail.value.batch_no}`
      : `合批卡 ${detail.value.batch_no}`
    : ''
  const shouldAutoPrint =
    mode.value === 'sheet' ||
    (mode.value === 'main-codes' && printableCount.value > 0)
  if (shouldAutoPrint) {
    setTimeout(() => {
      document.title = ''
      doPrint()
    }, 400)
  }
}

watch(
  () => route.query.mode,
  async (m) => {
    const next = String(m || 'sheet') === 'main-codes' ? 'main-codes' : 'sheet'
    mode.value = next
    const id = Number(route.params.id)
    if (next === 'main-codes' && id && !unitsPayload.value) {
      await loadUnits(id)
    }
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
.section-title .muted {
  font-weight: 400;
  color: #666;
  font-size: 12px;
}
.member-block {
  break-inside: avoid;
  page-break-inside: avoid;
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
}
.sign-cell {
  min-width: 120px;
  height: 28px;
}
.empty {
  text-align: center;
  color: #888;
}
.empty-box {
  margin: 24px 0;
  padding: 20px;
  border: 1px dashed #ccc;
  text-align: center;
  color: #555;
}
.totals {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
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
  margin-top: 8px;
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
.label-code {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.label-meta {
  font-size: 12px;
  line-height: 1.5;
  color: #222;
}
.batch-tag {
  color: #555;
  font-size: 11px;
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
.sign {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  margin-top: 28px;
}
.sign label {
  font-weight: 600;
}
.sign .line {
  margin-top: 28px;
  border-bottom: 1px solid #333;
}
.sign .date {
  margin-top: 8px;
  color: #555;
}

@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
}
</style>
