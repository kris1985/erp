<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">生产流转卡</h1>
      <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
      <template v-else-if="card">
        <div class="card-block">
          <div style="font-weight: 700; font-size: 18px">{{ card.header_no }}</div>
          <div class="muted" style="margin-top: 4px">
            {{ card.product_code || '—' }} · {{ card.color_name || '—' }} · {{ card.total_qty || 0 }} 双
          </div>
          <div class="muted">
            {{ customerLabel }} · 交期 {{ card.delivery_date || '—' }}
          </div>
          <div class="muted">销售单 {{ salesLabel || '—' }}</div>
          <div class="muted" style="margin-top: 8px">
            裁断扫流转卡；针车扫框码；包装扫箱唛。
          </div>
        </div>

        <div class="card-block cutting-panel">
          <div class="panel-title">裁断工作台</div>
          <div class="muted">当前状态：{{ statusLabel }}</div>
          <div class="cut-actions">
            <van-button size="small" plain type="primary" @click="openIssue">1. 领料</van-button>
            <van-button size="small" plain type="primary" :disabled="!canStartCut" :loading="starting" @click="startCutting">2. 开始开裁</van-button>
            <van-button size="small" type="primary" :disabled="!canReportCut" @click="openCutReport">3. 裁断报工</van-button>
          </div>
          <div class="muted" style="margin-top: 8px">领料不会自动开裁；报工完成后再生成框码。</div>
        </div>

        <div v-if="workReqs.length" class="card-block">
          <div style="font-weight: 600; margin-bottom: 8px">客户做货要求</div>
          <div v-for="(wr, i) in workReqs" :key="wr.sales_order_id || i" class="req-item">
            <div class="muted" style="margin-bottom: 4px">
              <span v-if="wr.sales_order_no">{{ wr.sales_order_no }}</span>
              <span v-if="wr.brand_name"> · {{ wr.brand_name }}</span>
            </div>
            <img v-if="wr.logo_url" class="req-logo" :src="wr.logo_url" alt="logo" />
            <p v-if="wr.notes" class="req-notes">{{ wr.notes }}</p>
            <img v-if="wr.image_url" class="req-img" :src="wr.image_url" alt="要求图" />
            <div
              v-if="!(wr.logo_url || wr.notes || wr.image_url)"
              class="muted"
            >
              未填文字要求
            </div>
          </div>
        </div>

        <div class="card-block">
          <div style="font-weight: 600; margin-bottom: 8px">工艺路线</div>
          <div v-for="(p, idx) in card.processes || []" :key="p.id || idx" class="proc-row">
            <span class="proc-seq">{{ idx + 1 }}</span>
            <span>{{ p.label || p.process_name }}</span>
            <span class="muted">{{ p.completed_qty || 0 }}/{{ p.plan_qty || 0 }}</span>
          </div>
          <div v-if="!(card.processes || []).length" class="muted">暂无工序</div>
        </div>

        <div class="card-block">
          <div style="font-weight: 600; margin-bottom: 8px">
            本单框编号 · {{ (card.baskets || []).length }} 框
          </div>
          <div v-for="b in card.baskets || []" :key="b.id" class="basket-row">
            <span class="code">{{ b.code }}</span>
            <span class="muted">
              {{ [b.color_name, b.size_value].filter(Boolean).join('/') || '—' }} · {{ b.qty }}双
            </span>
          </div>
          <div v-if="!(card.baskets || []).length" class="muted">尚未开裁生框</div>
        </div>

        <div class="action-stack">
          <van-button type="primary" round block @click="goForming">成型报工</van-button>
          <van-button type="primary" plain round block @click="goPacking">包装报工</van-button>
        </div>

        <div v-if="cartons.length" class="card-block" style="margin-top: 12px">
          <div style="font-weight: 600; margin-bottom: 8px">箱唛（包装扫箱）</div>
          <van-cell
            v-for="c in cartons"
            :key="c.id"
            clickable
            :title="c.code"
            :label="`第 ${c.seq} 箱 · ${c.total_qty} 双${c.reported_work_log_id ? ' · 已报' : ''}`"
            is-link
            @click="goCarton(c.code)"
          />
        </div>
      </template>
    </div>

    <van-popup v-model:show="issueVisible" position="bottom" round :style="{ height: '78%' }">
      <div class="sheet">
        <div class="sheet-title">按生产单领料</div>
        <van-field v-model.number="issuePairs" type="digit" label="本次双数" @blur="loadIssueCandidates" />
        <div v-if="issueLoading" class="sheet-tip">正在计算领料数量…</div>
        <van-field
          v-for="row in issueCandidates"
          :key="row.id"
          v-model="issueDraft[row.id]"
          type="number"
          :label="row.material_name || row.material_code || `物料 ${row.id}`"
          :placeholder="`建议 ${row.suggested_qty || 0}`"
        />
        <div v-if="!issueLoading && !issueCandidates.length" class="sheet-tip">没有可领物料，可能尚未生成用料需求或已领完。</div>
        <van-button block round type="primary" :loading="issuePosting" @click="submitIssue">提交领料申请</van-button>
      </div>
    </van-popup>

    <van-popup v-model:show="reportVisible" position="bottom" round :style="{ height: '82%' }">
      <div class="sheet">
        <div class="sheet-title">裁断报工</div>
        <div class="sheet-tip">按尺码填写本次实际合格数和不良数。</div>
        <div v-for="row in cutRows" :key="row.id || row.size_value" class="size-report-row">
          <div class="size-name">{{ row.size_value || '未分码' }}<small>计划 {{ row.qty }}</small></div>
          <van-field v-model="row.qualified_qty" type="digit" label="合格" />
          <van-field v-model="row.defect_qty" type="digit" label="不良" />
        </div>
        <van-field v-model.number="basketPairs" type="digit" label="每框双数" />
        <van-button block round type="primary" :loading="reportPosting" @click="submitCutReport">报工并生成框码</van-button>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()

const card = ref<any>(null)
const cartons = ref<any[]>([])
const error = ref('')
const starting = ref(false)
const issueVisible = ref(false)
const issueLoading = ref(false)
const issuePosting = ref(false)
const issuePairs = ref(0)
const issueCandidates = ref<any[]>([])
const issueDraft = ref<Record<number, string>>({})
const reportVisible = ref(false)
const reportPosting = ref(false)
const cutRows = ref<any[]>([])
const basketPairs = ref(40)

const statusLabel = computed(() => ({
  draft: '草稿', confirmed: '待开裁', cut: '已开裁', in_progress: '生产中', completed: '已完成', cancelled: '已取消',
} as Record<string, string>)[String(card.value?.status || '')] || card.value?.status || '—')
const canStartCut = computed(() => card.value?.status === 'confirmed')
const canReportCut = computed(() => ['cut', 'in_progress'].includes(card.value?.status))
const cuttingProcess = computed(() => {
  const ps = card.value?.processes || []
  return ps.find((p: any) => /裁|冲|下料/.test(String(p.process_name || p.label || ''))) || ps[0]
})

const workReqs = computed(() => {
  const list = card.value?.work_requirements
  return Array.isArray(list) ? list : []
})

const customerLabel = computed(() => {
  const c = card.value
  if (!c) return '—'
  if (Array.isArray(c.customers) && c.customers.length) return c.customers.join(' / ')
  return c.customer_name || '—'
})

const salesLabel = computed(() => {
  const c = card.value
  if (!c) return ''
  if (Array.isArray(c.sales_order_nos) && c.sales_order_nos.length) {
    return c.sales_order_nos.join(' / ')
  }
  return c.sales_order_no || ''
})

function goForming() {
  const id = Number(card.value?.header_id || route.params.id)
  router.push({ path: '/line-report', query: { header_id: String(id) } })
}

function goPacking() {
  if (cartons.value.length) {
    showToast('请点选下方箱唛报工，或继续扫箱唛')
    return
  }
  showToast('本单尚未生成箱唛，请先在后台装箱')
}

function goCarton(code: string) {
  if (!code) return
  router.push(`/carton-report/${encodeURIComponent(code)}`)
}

async function refreshCard() {
  const id = Number(route.params.id)
  const res: any = await http.get(`/executions/headers/${id}/flow-card`)
  card.value = res.data
}

async function openIssue() {
  issuePairs.value = Number(card.value?.total_qty || 0)
  issueVisible.value = true
  await loadIssueCandidates()
}

async function loadIssueCandidates() {
  issueLoading.value = true
  try {
    const res: any = await http.get('/stock-issues/candidates', { params: { header_id: card.value.header_id, pairs: issuePairs.value || undefined } })
    issueCandidates.value = res.data?.lines || []
    const draft: Record<number, string> = {}
    for (const row of issueCandidates.value) draft[row.id] = Number(row.suggested_qty || 0) > 0 ? String(row.suggested_qty) : ''
    issueDraft.value = draft
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '领料数据加载失败')
  } finally { issueLoading.value = false }
}

async function submitIssue() {
  const lines = issueCandidates.value.map((row: any) => ({ requirement_id: row.id, qty: Number(issueDraft.value[row.id]) })).filter((x: any) => x.qty > 0)
  if (!lines.length) return showToast('请填写领料数量')
  issuePosting.value = true
  try {
    await http.post('/stock-issues', { doc_type: 'issue', header_id: card.value.header_id, lines })
    showToast('领料申请已提交，待仓管确认')
    issueVisible.value = false
  } catch (e: any) { showToast(e?.response?.data?.detail || '提交失败') }
  finally { issuePosting.value = false }
}

async function startCutting() {
  starting.value = true
  try {
    await http.post(`/executions/headers/${card.value.header_id}/start-cutting`)
    await refreshCard()
    showToast('已开裁')
  } catch (e: any) { showToast(e?.response?.data?.detail || '开裁失败') }
  finally { starting.value = false }
}

function openCutReport() {
  cutRows.value = (card.value?.items || []).map((x: any) => ({
    ...x,
    qualified_qty: String(Math.max(0, Number(x.qty || 0) - Number(x.cut_reported_qty || 0)) || ''),
    defect_qty: '0',
  }))
  reportVisible.value = true
}

async function submitCutReport() {
  const rows = cutRows.value.filter((x: any) => Number(x.qualified_qty) > 0 || Number(x.defect_qty) > 0)
  if (!rows.length) return showToast('请填写报工数量')
  if (!cuttingProcess.value?.process_name) return showToast('未找到裁断工序')
  reportPosting.value = true
  try {
    const reportIds: number[] = []
    for (const row of rows) {
      const reportRes: any = await http.post('/reports', {
        worker_id: 0,
        header_id: card.value.header_id,
        process_name: cuttingProcess.value.process_name,
        color_name: row.color_name || card.value.color_name,
        size_value: row.size_value,
        qualified_qty: Number(row.qualified_qty || 0),
        defect_qty: Number(row.defect_qty || 0),
        source: 'flow_card_cutting',
        create_trace_bundle: false,
      })
      if (reportRes.data?.need_confirm) throw new Error(reportRes.data?.message || '报工数量超过计划，请到报工页面确认')
      reportIds.push(...(reportRes.data?.work_log_ids || [reportRes.data?.work_log_id]).filter(Boolean))
    }
    await refreshCard()
    const targets: Record<number, number> = {}
    for (const item of card.value?.items || []) {
      if (item.size_id) targets[Number(item.size_id)] = Number(item.cut_reported_qty || 0)
    }
    const res: any = await http.post(
      `/executions/headers/${card.value.header_id}/cut-cards`,
      { target_qty_by_size: targets, new_batch: true, report_ids: reportIds },
      { params: { dry_run: false, only_missing: true, bundle_size: basketPairs.value || 40 } },
    )
    await refreshCard()
    reportVisible.value = false
    const batch = (res.data?.batches || [])[0]
    const batchId = Number((res.data?.batch_ids || [])[0] || 0)
    showToast(`本批报工成功：${batch?.batch_no || ''}，新增 ${res.data?.to_create || 0} 个框码`)
    if (batchId) {
      window.open(
        `${window.location.origin}/admin/executions/print/${card.value.header_id}?mode=basket-labels&batch_id=${batchId}`,
        '_blank',
      )
    }
  } catch (e: any) { showToast(e?.response?.data?.detail || '报工失败') }
  finally { reportPosting.value = false }
}

async function loadCartons(headerId: number) {
  try {
    const res: any = await http.get(`/executions/headers/${headerId}/packing-plans`)
    const plans = res.data?.items || []
    const latest = plans[0]
    if (!latest?.id) {
      cartons.value = []
      return
    }
    const detail: any = await http.get(`/packing-plans/${latest.id}`)
    cartons.value = detail.data?.cartons || detail.data?.items || []
  } catch {
    cartons.value = []
  }
}

onMounted(async () => {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '流转卡无效'
    return
  }
  try {
    await refreshCard()
    await loadCartons(id)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '流转卡不存在或无权查看'
  }
})
</script>

<style scoped>
.req-item + .req-item {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #eee;
}
.req-logo {
  max-height: 40px;
  max-width: 120px;
  object-fit: contain;
  margin-bottom: 6px;
}
.req-notes {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.5;
  font-size: 14px;
}
.req-img {
  margin-top: 8px;
  max-width: 100%;
  border-radius: 6px;
}
.proc-row,
.basket-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
}
.proc-row:last-child,
.basket-row:last-child {
  border-bottom: none;
}
.proc-seq {
  width: 20px;
  color: #888;
  text-align: center;
}
.proc-row .muted,
.basket-row .muted {
  margin-left: auto;
  font-size: 12px;
}
.code {
  font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.action-stack {
  margin: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cutting-panel {
  border-left: 4px solid #1989fa;
}
.panel-title,
.sheet-title {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 8px;
}
.cut-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 12px;
}
.sheet {
  padding: 20px 16px 28px;
  overflow-y: auto;
  height: 100%;
  box-sizing: border-box;
}
.sheet-tip {
  color: #888;
  font-size: 13px;
  padding: 8px 0 12px;
}
.size-report-row {
  border-top: 1px solid #eee;
  padding: 8px 0;
}
.size-name {
  font-weight: 700;
  padding: 0 16px;
}
.size-name small {
  margin-left: 8px;
  color: #888;
  font-weight: 400;
}
</style>
