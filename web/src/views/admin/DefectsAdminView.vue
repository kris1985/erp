<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">质量不良</h1>
        <p class="page-desc">不良事件 · 派返修 · 品质追溯（捆级线索，非鉴定）</p>
      </div>
    </header>
    <div class="admin-card">
      <el-tabs v-model="mainTab" @tab-change="onTabChange">
        <el-tab-pane label="列表" name="list" />
        <el-tab-pane label="追溯" name="trace" />
      </el-tabs>

      <template v-if="mainTab === 'list'">
        <div class="admin-toolbar">
          <el-input
            v-model="filters.order_no"
            clearable
            placeholder="订单号"
            style="width: 140px"
            @change="reload"
          />
          <el-select
            v-model="filters.responsible_worker_id"
            clearable
            filterable
            placeholder="责任人（线索）"
            style="width: 150px"
            @change="reload"
          >
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <el-select
            v-model="filters.defect_type"
            clearable
            placeholder="类型"
            style="width: 120px"
            @change="reload"
          >
            <el-option
              v-for="t in defectTypes"
              :key="t.code"
              :label="t.name"
              :value="t.code"
            />
          </el-select>
          <el-select
            v-model="filters.status"
            clearable
            placeholder="状态"
            style="width: 110px"
            @change="reload"
          >
            <el-option label="开放" value="open" />
            <el-option label="已关闭" value="closed" />
          </el-select>
          <el-select
            v-model="filters.trace_quality"
            clearable
            placeholder="追溯强度"
            style="width: 120px"
            @change="reload"
          >
            <el-option label="强" value="strong" />
            <el-option label="部分" value="partial" />
            <el-option label="弱" value="weak" />
          </el-select>
          <el-checkbox v-model="filters.pending_rework" @change="reload">未完成返修</el-checkbox>
          <el-button @click="load">刷新</el-button>
          <div class="spacer" />
          <el-button type="primary" @click="openCreate">无码登记</el-button>
        </div>

        <div v-if="summaryText" class="muted" style="margin-bottom: 12px">{{ summaryText }}</div>

        <div ref="tableHostRef">
          <el-table
            :data="rows"
            stripe
            border
            :max-height="tableMaxHeight"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
            <el-table-column prop="created_at" label="时间" :width="colWidth('created_at', 170)" resizable>
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 100)" resizable />
            <el-table-column prop="trace_code" label="捆标" :width="colWidth('trace_code', 120)" resizable />
            <el-table-column column-key="trace_quality" label="追溯" :width="colWidth('trace_quality', 72)" resizable>
              <template #default="{ row }">
                <el-tag size="small" :type="traceQualityTag(row.trace_quality)" effect="plain">
                  {{ traceQualityLabel(row.trace_quality) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column column-key="color_size" label="色码" :width="colWidth('color_size', 100)" resizable>
              <template #default="{ row }">
                {{ row.color_name || '—' }} {{ row.size_value || '' }}
              </template>
            </el-table-column>
            <el-table-column prop="defect_type_name" label="类型" :width="colWidth('defect_type_name', 90)" resizable />
            <el-table-column prop="qty" label="数量" :width="colWidth('qty', 70)" resizable />
            <el-table-column
              prop="responsible_process_name"
              label="责任工序"
              :width="colWidth('responsible_process_name', 100)"
              resizable
            />
            <el-table-column
              prop="responsible_worker_name"
              label="责任线索"
              :width="colWidth('responsible_worker_name', 90)"
              resizable
            />
            <el-table-column prop="disposition" label="处置" :width="colWidth('disposition', 90)" resizable>
              <template #default="{ row }">{{ dispLabel(row.disposition) }}</template>
            </el-table-column>
            <el-table-column column-key="rework" label="返修任务" :width="colWidth('rework', 140)" resizable>
              <template #default="{ row }">
                <template v-if="row.pending_rework_task_id">
                  #{{ row.pending_rework_task_id }}
                  {{ row.pending_rework_worker_name || '' }}
                  ×{{ row.pending_rework_qty }}
                </template>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" :width="colWidth('status', 80)" resizable>
              <template #default="{ row }">{{ row.status === 'closed' ? '已关闭' : '开放' }}</template>
            </el-table-column>
            <el-table-column prop="note" label="备注" :width="colWidth('note', 120)" show-overflow-tooltip resizable />
            <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 260)" resizable>
              <template #default="{ row }">
                <el-button link type="primary" @click="openTraceFromRow(row)">打开追溯</el-button>
                <el-button
                  v-if="row.status !== 'closed' && !row.pending_rework_task_id"
                  link
                  type="primary"
                  @click="openDispatch(row)"
                >
                  派返修
                </el-button>
                <el-button
                  v-if="row.pending_rework_task_id"
                  link
                  type="success"
                  @click="completeRework(row)"
                >
                  完成
                </el-button>
                <el-button
                  v-if="row.pending_rework_task_id"
                  link
                  type="warning"
                  @click="cancelRework(row)"
                >
                  取消任务
                </el-button>
                <el-button
                  v-if="row.status !== 'closed'"
                  link
                  type="primary"
                  @click="closeEvent(row)"
                >
                  关闭
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="admin-pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            background
            layout="total, sizes, prev, pager, next"
            :total="total"
            :page-sizes="[10, 20, 50]"
            @current-change="load"
            @size-change="
              () => {
                page = 1
                load()
              }
            "
          />
        </div>
      </template>

      <template v-else>
        <div class="admin-toolbar">
          <el-input
            v-model="traceQuery"
            clearable
            placeholder="生产单号 / 捆标码 / 不良 ID"
            style="width: 320px"
            @keyup.enter="runTrace"
          />
          <el-button type="primary" :loading="traceLoading" @click="runTrace">查询</el-button>
        </div>
        <div v-if="!traceResult && !traceLoading" class="muted trace-empty">
          输入生产单号、流转卡码或不良事件 ID。需按筐报工后才有流水。
        </div>
        <template v-if="traceResult">
          <div class="trace-order">
            <strong>{{ traceResult.order?.order_no }}</strong>
            <span class="muted">
              · {{ traceResult.order?.customer_name || '—' }} ·
              {{ traceResult.order?.product_code || '—' }} · 交期
              {{ traceResult.order?.delivery_date || '—' }}
            </span>
          </div>
          <div class="trace-grid">
            <div class="trace-col">
              <div class="trace-col-title">捆标</div>
              <el-table
                :data="traceResult.units_summary?.items || []"
                size="small"
                border
                stripe
                highlight-current-row
                max-height="360"
                @current-change="onFocusUnit"
              >
                <el-table-column prop="code" label="码" min-width="110" />
                <el-table-column prop="qty" label="数" width="56" />
                <el-table-column label="色码" width="90">
                  <template #default="{ row }">
                    {{ row.color_name || '—' }} {{ row.size_value || '' }}
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态" width="88" />
              </el-table>
              <div class="muted" style="margin-top: 6px">
                共 {{ traceResult.units_summary?.total || 0 }} 捆
              </div>
            </div>
            <div class="trace-col">
              <div class="trace-col-title">
                时间线
                <span v-if="traceResult.focus_unit" class="muted">
                  · {{ traceResult.focus_unit.code }}
                </span>
              </div>
              <el-table
                v-if="traceResult.focus_unit"
                :data="traceResult.focus_unit.logs || []"
                size="small"
                border
                stripe
                max-height="360"
              >
                <el-table-column prop="created_at" label="时间" width="150">
                  <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column prop="action" label="动作" width="72" />
                <el-table-column prop="process_name" label="工序" width="90" />
                <el-table-column prop="worker_name" label="工人" width="80" />
                <el-table-column prop="qty" label="数" width="48" />
                <el-table-column prop="note" label="备注" min-width="100" show-overflow-tooltip />
              </el-table>
              <div v-else class="muted">点左侧捆查看流水</div>
            </div>
            <div class="trace-col">
              <div class="trace-col-title">不良事件（仅 DefectEvent）</div>
              <el-table
                :data="traceResult.defects_summary || []"
                size="small"
                border
                stripe
                max-height="360"
              >
                <el-table-column prop="id" label="ID" width="56" />
                <el-table-column prop="defect_type_name" label="类型" width="72" />
                <el-table-column prop="qty" label="数" width="48" />
                <el-table-column prop="responsible_worker_name" label="线索" width="72" />
                <el-table-column column-key="tq" label="追溯" width="64">
                  <template #default="{ row }">
                    {{ traceQualityLabel(row.trace_quality) }}
                  </template>
                </el-table-column>
                <el-table-column label="返修" min-width="100">
                  <template #default="{ row }">
                    <span v-if="row.pending_rework_task_id">
                      #{{ row.pending_rework_task_id }} {{ row.pending_rework_worker_name }}
                    </span>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="88" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      v-if="row.status !== 'closed' && !row.pending_rework_task_id"
                      link
                      type="primary"
                      @click="openDispatch(row)"
                    >
                      派返修
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </template>
      </template>
    </div>

    <el-dialog v-model="createVisible" title="无码登记不良" width="520px">
      <el-form label-width="100px">
        <el-form-item label="订单号" required>
          <el-input v-model="form.order_no" placeholder="如 230711" @change="onOrderNoChange" />
        </el-form-item>
        <el-form-item label="捆标" :required="createBundlesActive">
          <el-select
            v-model="form.trace_unit_id"
            clearable
            filterable
            style="width: 100%"
            :placeholder="createBundlesActive ? '本单有进行中捆，必须选择' : '可选'"
            @change="onCreateBundleChange"
          >
            <el-option
              v-for="u in createBundles"
              :key="u.id"
              :label="`${u.code} · ${u.color_name || ''} ${u.size_value || ''} ×${u.qty} (${u.status})`"
              :value="u.id"
            />
          </el-select>
          <div v-if="createBundlesActive" class="muted" style="margin-top: 4px; color: #c45656">
            本单有进行中捆，必须选捆（硬拦）
          </div>
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.defect_type" style="width: 100%">
            <el-option v-for="t in defectTypes" :key="t.code" :label="t.name" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" required>
          <el-input-number v-model="form.qty" :min="1" />
        </el-form-item>
        <el-form-item label="责任工序">
          <el-select
            v-model="form.responsible_process_id"
            clearable
            filterable
            style="width: 100%"
            @change="onCreateProcessChange"
          >
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任线索">
          <el-select v-model="form.responsible_worker_id" clearable filterable style="width: 100%">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <div v-if="suggestHint" class="muted" style="margin-top: 4px">{{ suggestHint }}</div>
          <div
            v-if="suggestCandidates.length"
            class="suggest-cands"
          >
            <el-button
              v-for="c in suggestCandidates"
              :key="c.worker_id"
              size="small"
              @click="form.responsible_worker_id = c.worker_id"
            >
              {{ c.worker_name || c.worker_id }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="处置">
          <el-select v-model="form.disposition" style="width: 100%">
            <el-option label="返修" value="rework" />
            <el-option label="报废" value="scrap" />
            <el-option label="让步接收" value="concession" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createEvent">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dispatchVisible" title="派返修任务" width="480px">
      <el-form label-width="100px">
        <el-form-item label="不良">
          <span
            >#{{ dispatchRow?.id }} · {{ dispatchRow?.order_no }} ·
            {{ dispatchRow?.defect_type_name }} ×{{ dispatchRow?.qty }}</span
          >
        </el-form-item>
        <el-form-item label="返修工人" required>
          <el-select v-model="dispatchForm.worker_id" filterable style="width: 100%">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="返修工序" required>
          <el-select v-model="dispatchForm.process_id" filterable style="width: 100%">
            <el-option v-for="p in personalProcesses" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" required>
          <el-input-number v-model="dispatchForm.qty" :min="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dispatchForm.note" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dispatchVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitDispatch">派发</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const route = useRoute()
const router = useRouter()

const { colWidth, onHeaderDragend } = useTableColWidths('defects-list')
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const mainTab = ref<'list' | 'trace'>('list')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const workers = ref<any[]>([])
const processes = ref<any[]>([])
const defectTypes = ref<{ code: string; name: string }[]>([])
const summary = ref<{ by_worker: any[]; by_type: any[] }>({ by_worker: [], by_type: [] })
const filters = reactive({
  order_no: '',
  responsible_worker_id: null as number | null,
  defect_type: '',
  status: '',
  pending_rework: false,
  trace_quality: '' as string,
})
const createVisible = ref(false)
const dispatchVisible = ref(false)
const dispatchRow = ref<any>(null)
const saving = ref(false)
const form = reactive({
  order_no: '',
  trace_unit_id: null as number | null,
  defect_type: '',
  qty: 1,
  responsible_process_id: null as number | null,
  responsible_worker_id: null as number | null,
  disposition: 'rework',
  note: '',
})
const createBundles = ref<any[]>([])
const createOrderId = ref<number | null>(null)
const suggestHint = ref('')
const suggestCandidates = ref<any[]>([])
const dispatchForm = reactive({
  worker_id: null as number | null,
  process_id: null as number | null,
  qty: 1,
  note: '',
})

const traceQuery = ref('')
const traceLoading = ref(false)
const traceResult = ref<any>(null)

const personalProcesses = computed(() =>
  processes.value.filter((p: any) => p.type !== 'group'),
)

const createBundlesActive = computed(() =>
  createBundles.value.some((u) => u.status === 'open' || u.status === 'in_process'),
)

const summaryText = computed(() => {
  const parts: string[] = []
  if (summary.value.by_type?.length) {
    parts.push(
      '类型：' + summary.value.by_type.slice(0, 4).map((x) => `${x.name}${x.qty}`).join('、'),
    )
  }
  if (summary.value.by_worker?.length) {
    parts.push(
      '责任线索：' +
        summary.value.by_worker.slice(0, 4).map((x) => `${x.name}${x.qty}`).join('、'),
    )
  }
  return parts.join(' · ')
})

function formatTime(v?: string) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : ''
}

function dispLabel(d: string) {
  const map: Record<string, string> = { rework: '返修', scrap: '报废', concession: '让步' }
  return map[d] || d
}

function traceQualityLabel(q?: string) {
  if (q === 'strong') return '强'
  if (q === 'partial') return '部分'
  if (q === 'weak') return '弱'
  return '—'
}

function traceQualityTag(q?: string) {
  if (q === 'strong') return 'success'
  if (q === 'partial') return 'warning'
  if (q === 'weak') return 'info'
  return 'info'
}

function reload() {
  page.value = 1
  void load()
}

async function load() {
  const res: any = await http.get('/defect-events', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      order_no: filters.order_no || undefined,
      responsible_worker_id: filters.responsible_worker_id || undefined,
      defect_type: filters.defect_type || undefined,
      status: filters.status || undefined,
      pending_rework: filters.pending_rework || undefined,
      trace_quality: filters.trace_quality || undefined,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total || 0
  summary.value = res.data?.summary || { by_worker: [], by_type: [] }
}

async function loadMeta() {
  const [wRes, pRes, tRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/processes'),
    http.get('/defect-types'),
  ])
  workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
  processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
  defectTypes.value = tRes.data?.items || []
}

async function loadBundlesForOrderNo(orderNo: string) {
  createBundles.value = []
  createOrderId.value = null
  if (!orderNo.trim()) return
  try {
    const oRes: any = await http.get('/orders', {
      params: { order_no: orderNo.trim(), page_size: 5 },
    })
    const order = (oRes.data?.items || []).find((x: any) => x.order_no === orderNo.trim())
    if (!order) return
    createOrderId.value = order.id
    const uRes: any = await http.get(`/orders/${order.id}/trace-units`)
    createBundles.value = uRes.data?.items || []
  } catch {
    createBundles.value = []
  }
}

function openCreate() {
  form.order_no = filters.order_no || ''
  form.trace_unit_id = null
  form.defect_type = defectTypes.value[0]?.code || ''
  form.qty = 1
  form.responsible_process_id = null
  form.responsible_worker_id = null
  form.disposition = 'rework'
  form.note = ''
  suggestHint.value = ''
  suggestCandidates.value = []
  createVisible.value = true
  void loadBundlesForOrderNo(form.order_no)
}

function onOrderNoChange() {
  form.trace_unit_id = null
  void loadBundlesForOrderNo(form.order_no)
}

async function onCreateBundleChange() {
  await refreshSuggest()
}

async function onCreateProcessChange() {
  await refreshSuggest()
}

async function refreshSuggest() {
  suggestHint.value = ''
  suggestCandidates.value = []
  if (!form.trace_unit_id || !form.responsible_process_id) return
  try {
    const res: any = await http.get(`/trace-units/${form.trace_unit_id}/suggest-responsible`, {
      params: { process_id: form.responsible_process_id },
    })
    const d = res.data || {}
    suggestHint.value = [d.basis, d.confidence ? `置信 ${d.confidence}` : '']
      .filter(Boolean)
      .join(' · ')
    suggestCandidates.value = d.candidates || []
    if (d.worker_id && !form.responsible_worker_id) {
      form.responsible_worker_id = d.worker_id
    }
  } catch {
    /* ignore */
  }
}

function openDispatch(row: any) {
  dispatchRow.value = row
  dispatchForm.worker_id = row.responsible_worker_id || null
  dispatchForm.process_id = row.responsible_process_id || null
  dispatchForm.qty = row.qty || 1
  dispatchForm.note = ''
  dispatchVisible.value = true
}

async function createEvent() {
  if (!form.order_no.trim() || !form.defect_type || !form.qty) {
    ElMessage.warning('请填写订单、类型和数量')
    return
  }
  if (createBundlesActive.value && !form.trace_unit_id) {
    ElMessage.warning('本单有进行中捆，请选择捆标')
    return
  }
  saving.value = true
  try {
    await http.post('/defect-events', {
      order_no: form.order_no.trim(),
      trace_unit_id: form.trace_unit_id || null,
      defect_type: form.defect_type,
      qty: form.qty,
      responsible_process_id: form.responsible_process_id,
      responsible_worker_id: form.responsible_worker_id,
      disposition: form.disposition,
      note: form.note || null,
      auto_suggest_worker: !form.responsible_worker_id,
    })
    ElMessage.success('已登记')
    createVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '登记失败')
  } finally {
    saving.value = false
  }
}

async function submitDispatch() {
  if (!dispatchRow.value?.id || !dispatchForm.worker_id || !dispatchForm.process_id) {
    ElMessage.warning('请选择返修工人和工序')
    return
  }
  saving.value = true
  try {
    await http.post(`/defect-events/${dispatchRow.value.id}/rework-tasks`, {
      worker_id: dispatchForm.worker_id,
      process_id: dispatchForm.process_id,
      qty: dispatchForm.qty,
      note: dispatchForm.note || null,
    })
    ElMessage.success('已派返修')
    dispatchVisible.value = false
    await load()
    if (mainTab.value === 'trace' && traceQuery.value) await runTrace()
  } finally {
    saving.value = false
  }
}

async function completeRework(row: any) {
  await ElMessageBox.confirm(`完成后将关闭不良 #${row.id}，确认？`, '完成返修')
  await http.post(`/rework-tasks/${row.pending_rework_task_id}/complete`, { close_defect: true })
  ElMessage.success('返修已完成')
  await load()
}

async function cancelRework(row: any) {
  await ElMessageBox.confirm(`取消返修任务 #${row.pending_rework_task_id}？`, '确认')
  await http.post(`/rework-tasks/${row.pending_rework_task_id}/cancel`)
  ElMessage.success('已取消任务')
  await load()
}

async function closeEvent(row: any) {
  await ElMessageBox.confirm(`关闭不良 #${row.id}？`, '确认')
  await http.patch(`/defect-events/${row.id}`, { status: 'closed' })
  ElMessage.success('已关闭')
  await load()
}

async function runTrace() {
  const q = traceQuery.value.trim()
  if (!q) {
    ElMessage.warning('请输入查询')
    return
  }
  traceLoading.value = true
  try {
    const res: any = await http.get('/quality-trace', { params: { q } })
    traceResult.value = res.data
    await syncTraceQuery(q)
  } catch (e: any) {
    traceResult.value = null
    ElMessage.error(e?.response?.data?.detail || '未找到')
  } finally {
    traceLoading.value = false
  }
}

async function onFocusUnit(row: any | null) {
  if (!row?.id || !traceResult.value?.order?.id) return
  try {
    const res: any = await http.get(`/trace-units/${row.id}`)
    traceResult.value = {
      ...traceResult.value,
      focus_unit_id: row.id,
      focus_unit: res.data,
      defects_summary: (traceResult.value.order_defects_summary || []).filter(
        (d: any) => d.trace_unit_id === row.id,
      ),
    }
  } catch {
    /* ignore */
  }
}

function openTraceFromRow(row: any) {
  const q = row.trace_code || String(row.id)
  mainTab.value = 'trace'
  traceQuery.value = q
  void runTrace()
  void syncTraceQuery(q, 'trace')
}

async function syncTraceQuery(q: string, mode: 'list' | 'trace' = 'trace') {
  await router.replace({
    path: '/admin/defects',
    query: {
      ...route.query,
      mode,
      q: q || undefined,
      product_code: route.query.product_code,
      process_id: route.query.process_id,
    },
  })
}

function onTabChange(name: string | number) {
  const mode = String(name) === 'trace' ? 'trace' : 'list'
  void router.replace({
    path: '/admin/defects',
    query: {
      mode,
      q: mode === 'trace' ? traceQuery.value || undefined : undefined,
      product_code: route.query.product_code,
      process_id: route.query.process_id,
    },
  })
  if (mode === 'list') {
    nextTick(() => measureTableHeight())
  }
}

function applyRouteQuery() {
  const mode = String(route.query.mode || '') === 'trace' ? 'trace' : 'list'
  mainTab.value = mode
  if (route.query.q) {
    traceQuery.value = String(route.query.q)
  }
  if (mode === 'trace' && traceQuery.value) {
    void runTrace()
  }
}

watch(
  () => route.query,
  () => applyRouteQuery(),
)

onMounted(async () => {
  await loadMeta()
  applyRouteQuery()
  if (mainTab.value === 'list') {
    await load()
    measureTableHeight()
  }
})
</script>

<style scoped>
.spacer {
  flex: 1;
}
.trace-empty {
  padding: 24px 8px;
}
.trace-order {
  margin-bottom: 12px;
}
.trace-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr 1.2fr;
  gap: 12px;
}
.trace-col-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.suggest-cands {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
@media (max-width: 1100px) {
  .trace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
