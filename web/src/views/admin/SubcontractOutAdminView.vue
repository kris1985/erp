<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">外发</h1>
        <p class="page-desc">外发工序单 · 发料 · 收回 · 欠数/损耗 · 加工费应付</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="外发单号"
          style="width: 160px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.status"
          clearable
          placeholder="状态"
          style="width: 130px"
          @change="search"
        >
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-checkbox v-model="filters.outstanding" @change="search">仅欠数（未收回）</el-checkbox>
        <div class="spacer" />
        <el-button :loading="loading" @click="search">查询</el-button>
        <el-button type="primary" @click="startCreate">新建外发单</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
        >
          <el-table-column prop="subcontract_no" label="外发单号" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">{{ row.subcontract_no }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="partner_name" label="外协厂" min-width="100" show-overflow-tooltip />
          <el-table-column prop="process_name" label="工序" min-width="70" show-overflow-tooltip>
            <template #default="{ row }">{{ row.process_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="linked_no" label="关联单" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ row.linked_no || '—' }}</template>
          </el-table-column>
          <el-table-column prop="total_qty" label="外发量(双)" min-width="72" align="right" />
          <el-table-column prop="issued_qty" label="已发(双)" min-width="66" align="right" />
          <el-table-column prop="received_qty" label="已收(双)" min-width="66" align="right" />
          <el-table-column prop="outstanding_qty" label="欠数(双)" min-width="66" align="right">
            <template #default="{ row }">
              <span :class="{ 'is-outstanding': Number(row.outstanding_qty) > 0 }">{{ row.outstanding_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="loss_qty" label="损耗(双)" min-width="66" align="right">
            <template #default="{ row }">
              <span :class="{ 'is-loss': Number(row.loss_qty) > 0 }">{{ row.loss_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="unit_price" label="加工费(元/双)" min-width="92" align="right">
            <template #default="{ row }">{{ Number(row.unit_price ?? 0).toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="payable_amount" label="应付(元)" min-width="90" align="right">
            <template #default="{ row }">{{ formatMoney(row.payable_amount) }}</template>
          </el-table-column>
          <el-table-column column-key="status" label="状态" min-width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" min-width="180">
            <template #default="{ row }">
              <el-button link type="primary" @click="openIssue(row)">发料</el-button>
              <el-button link type="success" @click="openReceive(row)">收回</el-button>
              <el-button link type="primary" @click="openFlows(row)">流水</el-button>
              <el-button
                v-if="row.status === 'draft'"
                link
                type="danger"
                @click="doCancel(row)"
              >取消</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          layout="total, prev, pager, next"
          :total="total"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </div>

    <!-- 新建/编辑 -->
    <el-dialog v-model="editVisible" :title="editDraft.id ? '编辑外发单' : '新建外发单'" width="560px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="外协厂" required>
          <el-select v-model="editDraft.partner_id" filterable placeholder="选择供应商" style="width: 100%">
            <el-option v-for="p in partners" :key="p.id" :label="p.short_name || p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="工序">
          <el-select v-model="editDraft.process_id" clearable filterable placeholder="发出去的工序" style="width: 100%">
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联执行单">
          <el-select v-model="editDraft.header_id" clearable filterable placeholder="可空（追溯用）" style="width: 100%">
            <el-option v-for="h in executions" :key="h.id" :label="`${h.header_no} · ${h.product_code || ''}`" :value="h.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="外发数量（双）" required>
          <el-input-number v-model="editDraft.total_qty" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="加工费单价（元/双）">
          <el-input-number v-model="editDraft.unit_price" :min="0" :precision="1" :step="0.1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editDraft.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 发料 -->
    <el-dialog v-model="issueVisible" title="发料登记" width="420px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="外发单">{{ issueRow?.subcontract_no }}</el-form-item>
        <el-form-item label="外协厂">{{ issueRow?.partner_name }}</el-form-item>
        <el-form-item label="本次发出" required>
          <el-input-number v-model="issueQty" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="issueNote" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitIssue">确认发料</el-button>
      </template>
    </el-dialog>

    <!-- 收回 -->
    <el-dialog v-model="receiveVisible" title="收回登记" width="420px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="外发单">{{ receiveRow?.subcontract_no }}</el-form-item>
        <el-form-item label="未收回">{{ receiveRow?.outstanding_qty }}</el-form-item>
        <el-form-item label="本次收回" required>
          <el-input-number v-model="receiveQty" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="其中不良">
          <el-input-number v-model="receiveDefectQty" :min="0" :step="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="receiveNote" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReceive">确认收回</el-button>
      </template>
    </el-dialog>

    <!-- 流水 -->
    <el-dialog v-model="flowsVisible" title="发料 / 收回流水" width="720px" destroy-on-close>
      <el-tabs v-model="flowTab">
        <el-tab-pane label="发料流水" name="issues">
          <el-table :data="issues" size="small" border stripe>
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column prop="qty" label="数量" width="100" align="right" />
            <el-table-column prop="note" label="备注" min-width="160">
              <template #default="{ row }">{{ row.note || '—' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="收回流水" name="receipts">
          <el-table :data="receipts" size="small" border stripe>
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column prop="qty" label="数量" width="80" align="right" />
            <el-table-column prop="defect_qty" label="不良" width="70" align="right" />
            <el-table-column prop="note" label="备注" min-width="160">
              <template #default="{ row }">{{ row.note || '—' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const tableHostRef = ref<HTMLElement | null>(null)
const { tableMaxHeight } = useTableMaxHeight(tableHostRef)

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({
  keyword: '',
  status: '' as string,
  outstanding: false,
})

const partners = ref<any[]>([])
const processes = ref<any[]>([])
const executions = ref<any[]>([])

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'issued', label: '已发料' },
  { value: 'partial_received', label: '部分收回' },
  { value: 'received', label: '已收回' },
  { value: 'cancelled', label: '已取消' },
]

function statusLabel(s: string) {
  return statusOptions.find((o) => o.value === s)?.label || s || '—'
}
function statusTagType(s: string) {
  if (s === 'received') return 'success'
  if (s === 'partial_received') return 'warning'
  if (s === 'issued') return 'primary'
  if (s === 'cancelled') return 'info'
  return ''
}

function formatMoney(v: any) {
  const n = Number(v ?? 0)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 4 })
}

const editVisible = ref(false)
const editDraft = reactive({
  id: null as number | null,
  partner_id: null as number | null,
  process_id: null as number | null,
  header_id: null as number | null,
  total_qty: 1,
  unit_price: 0,
  notes: '',
})

const issueVisible = ref(false)
const issueRow = ref<any>(null)
const issueQty = ref(1)
const issueNote = ref('')

const receiveVisible = ref(false)
const receiveRow = ref<any>(null)
const receiveQty = ref(1)
const receiveDefectQty = ref(0)
const receiveNote = ref('')

const flowsVisible = ref(false)
const flowTab = ref('issues')
const issues = ref<any[]>([])
const receipts = ref<any[]>([])

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/subcontract-orders', {
      params: {
        keyword: filters.keyword || undefined,
        status: filters.status || undefined,
        outstanding: filters.outstanding,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    rows.value = res.data?.items || []
    total.value = res.data?.total || 0
    await nextTick()
    tableRef.value?.doLayout?.()
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

async function loadMasters() {
  const [p, proc, exe] = await Promise.allSettled([
    http.get('/partners', { params: { role: 'subcontractor', page_size: 500 } }),
    http.get('/processes'),
    http.get('/executions', { params: { limit: 200 } }),
  ])
  partners.value = p.status === 'fulfilled' ? p.value.data?.items || [] : []
  processes.value = proc.status === 'fulfilled' ? proc.value.data?.items || [] : []
  executions.value = exe.status === 'fulfilled' ? exe.value.data?.items || [] : []
}

function startCreate() {
  editDraft.id = null
  editDraft.partner_id = null
  editDraft.process_id = null
  editDraft.header_id = null
  editDraft.total_qty = 1
  editDraft.unit_price = 0
  editDraft.notes = ''
  editVisible.value = true
}

function openDetail(row: any) {
  editDraft.id = row.id
  editDraft.partner_id = row.partner_id
  editDraft.process_id = row.process_id
  editDraft.header_id = row.header_id
  editDraft.total_qty = row.total_qty
  editDraft.unit_price = Number(row.unit_price ?? 0)
  editDraft.notes = row.notes || ''
  editVisible.value = true
}

async function submitEdit() {
  if (!editDraft.partner_id) {
    ElMessage.warning('请选择外协厂')
    return
  }
  if (!editDraft.total_qty || editDraft.total_qty <= 0) {
    ElMessage.warning('外发数量须大于 0')
    return
  }
  saving.value = true
  try {
    const payload: any = {
      partner_id: editDraft.partner_id,
      process_id: editDraft.process_id || null,
      header_id: editDraft.header_id || null,
      total_qty: editDraft.total_qty,
      unit_price: editDraft.unit_price ?? 0,
      notes: editDraft.notes || null,
    }
    if (editDraft.id) {
      await http.patch(`/subcontract-orders/${editDraft.id}`, payload)
    } else {
      await http.post('/subcontract-orders', payload)
    }
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

function openIssue(row: any) {
  issueRow.value = row
  issueQty.value = Number(row.outstanding_qty || row.total_qty || 1)
  issueNote.value = ''
  issueVisible.value = true
}

async function submitIssue() {
  if (!issueRow.value) return
  if (!issueQty.value || issueQty.value <= 0) {
    ElMessage.warning('发料数量须大于 0')
    return
  }
  saving.value = true
  try {
    await http.post(`/subcontract-orders/${issueRow.value.id}/issues`, {
      qty: issueQty.value,
      note: issueNote.value || null,
    })
    ElMessage.success('已发料')
    issueVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

function openReceive(row: any) {
  receiveRow.value = row
  receiveQty.value = Number(row.outstanding_qty || 1)
  receiveDefectQty.value = 0
  receiveNote.value = ''
  receiveVisible.value = true
}

async function submitReceive() {
  if (!receiveRow.value) return
  if (!receiveQty.value || receiveQty.value <= 0) {
    ElMessage.warning('收回数量须大于 0')
    return
  }
  saving.value = true
  try {
    await http.post(`/subcontract-orders/${receiveRow.value.id}/receipts`, {
      qty: receiveQty.value,
      defect_qty: receiveDefectQty.value || 0,
      note: receiveNote.value || null,
    })
    ElMessage.success('已收回（加工费已挂应付）')
    receiveVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function openFlows(row: any) {
  const [i, r] = await Promise.all([
    http.get(`/subcontract-orders/${row.id}/issues`),
    http.get(`/subcontract-orders/${row.id}/receipts`),
  ])
  issues.value = i.data?.items || []
  receipts.value = r.data?.items || []
  flowTab.value = 'issues'
  flowsVisible.value = true
}

async function doCancel(row: any) {
  const ok = await ElMessageBox.confirm(`确认取消外发单 ${row.subcontract_no}？`, '取消外发单', {
    type: 'warning',
    confirmButtonText: '取消外发单',
    cancelButtonText: '返回',
  }).catch(() => false)
  if (!ok) return
  await http.post(`/subcontract-orders/${row.id}/cancel`)
  ElMessage.success('已取消')
  await load()
}

onMounted(() => {
  void loadMasters()
  void load()
})
</script>

<style scoped>
.spacer {
  flex: 1;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.is-outstanding {
  color: #c45656;
  font-weight: 600;
}
.is-loss {
  color: #e6a23c;
  font-weight: 600;
}
</style>
