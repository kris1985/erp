<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">外发记录</h1>
        <p class="page-desc">外发工序单 · 验收 · 报废 · 加工费应付</p>
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
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          placeholder="外加工厂"
          style="width: 150px"
          @change="search"
        >
          <el-option v-for="p in partners" :key="p.id" :label="p.short_name || p.name" :value="p.id" />
        </el-select>
        <el-date-picker
          v-model="filters.date_range"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 250px"
          @change="search"
        />
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
          <el-table-column prop="linked_no" label="生产单号" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.linked_no || '—' }}</template>
          </el-table-column>
          <el-table-column prop="product_code" label="工厂型号" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ row.product_code || '—' }}</template>
          </el-table-column>
          <el-table-column prop="subcontract_no" label="外发单号" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.subcontract_no }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="外发时间" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="delivery_date" label="交货时间" min-width="100">
            <template #default="{ row }">{{ row.delivery_date || '—' }}</template>
          </el-table-column>
          <el-table-column prop="partner_name" label="外加工厂" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="openPartnerInfo(row)">
                {{ row.partner_name || '—' }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column prop="process_name" label="工序" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.process_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="total_qty" label="数量" min-width="66" align="right" />
          <el-table-column prop="received_qty" label="完工" min-width="66" align="right" />
          <el-table-column prop="unit_price" label="工价" min-width="72" align="right">
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="processing_fee" label="加工费" min-width="88" align="right">
            <template #default="{ row }">{{ formatMoney(row.processing_fee) }}</template>
          </el-table-column>
          <el-table-column prop="loss_qty" label="报废" min-width="66" align="right">
            <template #default="{ row }">
              <span :class="{ 'is-loss': Number(row.loss_qty) > 0 }">{{ row.loss_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="material_unit_price" label="材料单价" min-width="88" align="right">
            <template #default="{ row }">{{ formatMoney(row.material_unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="loss_amount" label="损失金额" min-width="88" align="right">
            <template #default="{ row }">
              <el-tooltip :content="`废品 ${formatMoney(row.loss_qty)} × 工价 ${formatMoney(row.unit_price)}`" placement="top">
                <span>{{ formatMoney(row.loss_amount) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="shared_loss_amount" label="分担损失" min-width="88" align="right">
            <template #default="{ row }">
              <el-tooltip :content="`公司承担 ${formatMoney(row.company_loss_amount)}`" placement="top">
                <span>{{ formatMoney(row.shared_loss_amount) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="payable_amount" label="应付" min-width="88" align="right">
            <template #default="{ row }">{{ formatMoney(row.payable_amount) }}</template>
          </el-table-column>
          <el-table-column column-key="status" label="状态" min-width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="56" align="center" fixed="right">
            <template #default="{ row }">
              <el-dropdown trigger="click" placement="bottom-end" @command="command => handleAction(command, row)">
                <el-button link class="more-action" aria-label="更多操作">•••</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit" :disabled="Number(row.receipt_count) > 0 || row.status === 'cancelled'">修改</el-dropdown-item>
                    <el-dropdown-item
                      command="delete"
                      :disabled="Number(row.issue_count) > 0 || Number(row.receipt_count) > 0"
                    >删除</el-dropdown-item>
                    <el-dropdown-item command="print">打印外发单</el-dropdown-item>
                    <el-dropdown-item command="receipt-print" :disabled="Number(row.receipt_count) <= 0">打印外发收货单</el-dropdown-item>
                    <el-dropdown-item command="receive" :disabled="row.status === 'draft' || row.status === 'cancelled' || Number(row.outstanding_qty) <= 0">验收</el-dropdown-item>
                    <el-dropdown-item command="flows">流水</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
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
        <el-form-item label="生产单" required>
          <el-select
            v-model="editDraft.header_id"
            filterable
            placeholder="先选择生产单"
            style="width: 100%"
            @change="handleHeaderChange"
          >
            <el-option v-for="h in executions" :key="h.id" :label="`${h.header_no} · ${h.product_code || ''}`" :value="h.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="工序" required>
          <el-select
            v-model="editDraft.order_process_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            :disabled="!editDraft.header_id"
            placeholder="从生产单工艺路由中选择，可多选"
            style="width: 100%"
          >
            <el-option v-for="p in routeProcesses" :key="p.id" :label="p.label || p.process_name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="外加工厂" required>
          <el-select v-model="editDraft.partner_id" filterable placeholder="选择外加工厂" style="width: 100%">
            <el-option v-for="p in partners" :key="p.id" :label="p.short_name || p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="外发数量（双）" required>
          <el-input-number v-model="editDraft.total_qty" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="交货时间">
          <el-date-picker v-model="editDraft.delivery_date" type="date" value-format="YYYY-MM-DD" placeholder="选择交货日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="材料单价（元/双）">
          <el-input-number v-model="editDraft.material_unit_price" :min="0" :precision="2" :step="0.1" @change="materialPriceManual = true" />
          <div class="muted" style="margin-top: 6px">{{ materialPriceHint }}</div>
        </el-form-item>
        <el-form-item label="工价（元/双）">
          <el-input-number v-model="editDraft.unit_price" :min="0" :precision="2" :step="0.1" />
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

    <!-- 验收 -->
    <el-dialog v-model="receiveVisible" title="验收登记" width="440px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="外发单">{{ receiveRow?.subcontract_no }}</el-form-item>
        <el-form-item label="待验收">{{ receiveRow?.outstanding_qty }}</el-form-item>
        <el-form-item label="完工数量" required>
          <el-input-number v-model="receiveQty" :min="1" :max="Number(receiveRow?.outstanding_qty || 1)" :step="1" />
        </el-form-item>
        <el-form-item label="废品">
          <strong>{{ receiveRow?.loss_qty || 0 }}</strong>
          <span class="receive-calc-note">来自报废记录，仅显示</span>
        </el-form-item>
        <el-form-item label="损失金额">
          <strong>{{ formatMoney(receiveLossAmount) }}</strong>
          <span class="receive-calc-note">废品数量 × 工价</span>
        </el-form-item>
        <el-form-item label="分担损失">
          <el-input-number v-model="receiveSharedLossAmount" :min="0" :max="receiveRemainingShareable" :precision="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="公司承担">
          <strong>{{ formatMoney(receiveCompanyLossAmount) }}</strong>
        </el-form-item>
        <el-form-item label="预计应付">
          <strong>{{ formatMoney(receivePayableAmount) }}</strong>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="receiveNote" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReceive">确认验收</el-button>
      </template>
    </el-dialog>

    <!-- 流水 -->
    <el-dialog v-model="flowsVisible" title="发料 / 验收流水" width="980px" destroy-on-close>
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
        <el-tab-pane label="验收流水" name="receipts">
          <el-table :data="receipts" size="small" border stripe>
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column prop="qty" label="完工" width="70" align="right" />
            <el-table-column prop="shared_loss_amount" label="分担损失" width="90" align="right">
              <template #default="{ row }">{{ formatMoney(row.shared_loss_amount) }}</template>
            </el-table-column>
            <el-table-column prop="payable_amount" label="应付" width="80" align="right">
              <template #default="{ row }">{{ formatMoney(row.payable_amount) }}</template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="160">
              <template #default="{ row }">{{ row.note || '—' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="partnerVisible" title="外加工厂信息" width="620px" destroy-on-close>
      <div v-loading="partnerLoading">
        <el-descriptions v-if="partnerDetail" :column="2" border>
          <el-descriptions-item label="名称">{{ partnerDetail.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="简称">{{ partnerDetail.short_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="主要联系人">
            {{ partnerDetail.primary_contact?.name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="联系电话">
            {{ partnerDetail.primary_contact?.mobile || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="地址" :span="2">{{ partnerDetail.address || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ partnerDetail.notes || '—' }}</el-descriptions-item>
        </el-descriptions>
        <template v-if="partnerDetail?.contacts?.length">
          <h3 class="partner-contact-title">联系人</h3>
          <el-table :data="partnerDetail.contacts" size="small" border>
            <el-table-column prop="name" label="姓名" min-width="90" />
            <el-table-column prop="title" label="职务" min-width="90">
              <template #default="{ row }">{{ row.title || '—' }}</template>
            </el-table-column>
            <el-table-column prop="mobile" label="电话" min-width="120">
              <template #default="{ row }">{{ row.mobile || '—' }}</template>
            </el-table-column>
            <el-table-column prop="wechat" label="微信" min-width="110">
              <template #default="{ row }">{{ row.wechat || '—' }}</template>
            </el-table-column>
          </el-table>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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
  partner_id: null as number | null,
  date_range: [] as string[],
})

const partners = ref<any[]>([])
const executions = ref<any[]>([])
const routeProcesses = ref<any[]>([])

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'issued', label: '已发料' },
  { value: 'partial_received', label: '部分验收' },
  { value: 'received', label: '已完工' },
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

function formatTime(v: any) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : '—'
}

const editVisible = ref(false)
const editDraft = reactive({
  id: null as number | null,
  partner_id: null as number | null,
  order_process_ids: [] as number[],
  header_id: null as number | null,
  total_qty: 1,
  unit_price: 0,
  material_unit_price: 0,
  delivery_date: '',
  notes: '',
})
const materialPriceManual = ref(false)
const materialPriceQuote = ref<{ material_amount?: number; labor_amount?: number } | null>(null)
const materialPriceHint = computed(() => {
  const quote = materialPriceQuote.value
  if (!quote) return '选择工序后按材料+外发前工资计算，可改'
  const material = Number(quote.material_amount || 0).toFixed(2)
  const labor = Number(quote.labor_amount || 0).toFixed(2)
  return `材料 ¥${material} + 工资 ¥${labor} / 双${materialPriceManual.value ? '（已手改）' : ''}`
})

const receiveVisible = ref(false)
const receiveRow = ref<any>(null)
const receiveQty = ref(1)
const receiveSharedLossAmount = ref(0)
const receiveNote = ref('')
const receiveLossAmount = computed(() => Number(receiveRow.value?.loss_qty || 0) * Number(receiveRow.value?.unit_price || 0))
const receiveRemainingShareable = computed(() => Math.max(0, Number(receiveRow.value?.remaining_shared_loss_amount ?? (receiveLossAmount.value - Number(receiveRow.value?.shared_loss_amount || 0)))))
const receiveCompanyLossAmount = computed(() => Math.max(0, receiveRemainingShareable.value - Number(receiveSharedLossAmount.value || 0)))
const receivePayableAmount = computed(() => Math.max(0, Number(receiveQty.value || 0) * Number(receiveRow.value?.unit_price || 0) - Number(receiveSharedLossAmount.value || 0)))

const flowsVisible = ref(false)
const flowTab = ref('issues')
const issues = ref<any[]>([])
const receipts = ref<any[]>([])
const partnerVisible = ref(false)
const partnerLoading = ref(false)
const partnerDetail = ref<any>(null)

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/subcontract-orders', {
      params: {
        keyword: filters.keyword || undefined,
        status: filters.status || undefined,
        partner_id: filters.partner_id || undefined,
        date_from: filters.date_range?.[0] || undefined,
        date_to: filters.date_range?.[1] || undefined,
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
  const [p, exe] = await Promise.allSettled([
    http.get('/partners', { params: { role: 'subcontractor', page_size: 500 } }),
    http.get('/executions', { params: { page_size: 100 } }),
  ])
  partners.value = p.status === 'fulfilled' ? p.value.data?.items || [] : []
  executions.value = exe.status === 'fulfilled' ? exe.value.data?.items || [] : []
}

async function loadRouteProcesses(headerId: number | null) {
  if (!headerId) {
    routeProcesses.value = []
    return
  }
  const res: any = await http.get(`/executions/headers/${headerId}/processes`)
  routeProcesses.value = res.data?.items || []
}

async function handleHeaderChange(headerId: number | null) {
  editDraft.order_process_ids = []
  await loadRouteProcesses(headerId)
  const header = executions.value.find(item => Number(item.id) === Number(headerId))
  if (header && !editDraft.id) editDraft.total_qty = Number(header.total_qty || 1)
  materialPriceQuote.value = null
  if (!materialPriceManual.value) editDraft.material_unit_price = 0
}

async function refreshMaterialUnitPrice() {
  if (!editDraft.header_id || !editDraft.order_process_ids.length) {
    materialPriceQuote.value = null
    if (!editDraft.id && !materialPriceManual.value) editDraft.material_unit_price = 0
    return
  }
  try {
    const res: any = await http.get('/subcontract-orders/price-quote', {
      params: {
        header_id: editDraft.header_id,
        order_process_ids: editDraft.order_process_ids.join(','),
      },
    })
    materialPriceQuote.value = res.data || null
    if (!editDraft.id && !materialPriceManual.value) {
      editDraft.material_unit_price = Number(res.data?.material_unit_price || 0)
    }
  } catch {
    materialPriceQuote.value = null
  }
}

watch(() => [...editDraft.order_process_ids], () => {
  void refreshMaterialUnitPrice()
})

function startCreate() {
  editDraft.id = null
  editDraft.partner_id = null
  editDraft.order_process_ids = []
  editDraft.header_id = null
  routeProcesses.value = []
  editDraft.total_qty = 1
  editDraft.unit_price = 0
  editDraft.material_unit_price = 0
  editDraft.delivery_date = ''
  editDraft.notes = ''
  materialPriceManual.value = false
  materialPriceQuote.value = null
  editVisible.value = true
}

async function openDetail(row: any) {
  editDraft.id = row.id
  editDraft.partner_id = row.partner_id
  editDraft.order_process_ids = [...(row.order_process_ids || [])]
  editDraft.header_id = row.header_id
  editDraft.total_qty = row.total_qty
  editDraft.unit_price = Number(row.unit_price ?? 0)
  editDraft.material_unit_price = Number(row.material_unit_price ?? 0)
  editDraft.delivery_date = row.delivery_date || ''
  editDraft.notes = row.notes || ''
  await loadRouteProcesses(editDraft.header_id)
  materialPriceManual.value = true
  await refreshMaterialUnitPrice()
  editVisible.value = true
}

async function submitEdit() {
  if (!editDraft.header_id) {
    ElMessage.warning('请先选择生产单')
    return
  }
  if (!editDraft.order_process_ids.length) {
    ElMessage.warning('请从生产单工艺路由中选择工序')
    return
  }
  if (!editDraft.partner_id) {
    ElMessage.warning('请选择外加工厂')
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
      order_process_ids: editDraft.order_process_ids,
      header_id: editDraft.header_id || null,
      total_qty: editDraft.total_qty,
      unit_price: editDraft.unit_price ?? 0,
      material_unit_price: editDraft.material_unit_price ?? 0,
      delivery_date: editDraft.delivery_date || null,
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

function openReceive(row: any) {
  receiveRow.value = row
  receiveQty.value = Number(row.outstanding_qty || 1)
  receiveSharedLossAmount.value = 0
  receiveNote.value = ''
  receiveVisible.value = true
}

async function submitReceive() {
  if (!receiveRow.value) return
  if (!receiveQty.value || receiveQty.value <= 0) {
    ElMessage.warning('完工数量须大于 0')
    return
  }
  if (Number(receiveSharedLossAmount.value || 0) > receiveRemainingShareable.value) {
    ElMessage.warning('分担损失不能大于剩余损失金额')
    return
  }
  saving.value = true
  try {
    await http.post(`/subcontract-orders/${receiveRow.value.id}/receipts`, {
      qty: receiveQty.value,
      shared_loss_amount: receiveSharedLossAmount.value || 0,
      note: receiveNote.value || null,
    })
    ElMessage.success('验收完成，应付已登记')
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

function printSubcontract(row: any) {
  const opened = window.open(
    `${window.location.origin}/admin/subcontract-orders/print/${Number(row.id)}`,
    '_blank',
  )
  if (!opened) ElMessage.warning('请允许弹出窗口以打印外发单')
}

function printSubcontractReceipt(row: any) {
  const opened = window.open(
    `${window.location.origin}/admin/subcontract-orders/receipt-print/${Number(row.id)}`,
    '_blank',
  )
  if (!opened) ElMessage.warning('请允许弹出窗口以打印外发收货单')
}

function handleAction(command: string, row: any) {
  if (command === 'edit') void openDetail(row)
  else if (command === 'delete') void deleteSubcontract(row)
  else if (command === 'print') printSubcontract(row)
  else if (command === 'receipt-print') printSubcontractReceipt(row)
  else if (command === 'receive') openReceive(row)
  else if (command === 'flows') void openFlows(row)
}

async function deleteSubcontract(row: any) {
  const confirmed = await ElMessageBox.confirm(
    `确认删除外发单 ${row.subcontract_no}？`,
    '删除外发单',
    {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '返回',
    },
  ).catch(() => false)
  if (!confirmed) return
  try {
    await http.delete(`/subcontract-orders/${Number(row.id)}`)
    ElMessage.success('已删除')
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '删除失败')
  }
}

async function openPartnerInfo(row: any) {
  if (!row.partner_id) return
  partnerVisible.value = true
  partnerLoading.value = true
  partnerDetail.value = null
  try {
    const res: any = await http.get(`/partners/${Number(row.partner_id)}`)
    partnerDetail.value = res.data
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '加载外加工厂信息失败')
  } finally {
    partnerLoading.value = false
  }
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
.is-loss {
  color: #e6a23c;
  font-weight: 600;
}
.receive-calc-note {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
.partner-contact-title {
  margin: 18px 0 10px;
  font-size: 15px;
}
.more-action {
  min-width: 32px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}
</style>
