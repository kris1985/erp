<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">付款登记</h1>
        <p class="page-desc">付款并核销到应付（禁止超额）</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="供应商 / 凭证号"
          style="width: 180px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.supplier_id"
          clearable
          filterable
          placeholder="全部供应商"
          style="width: 180px"
          @change="search"
        >
          <el-option
            v-for="c in suppliers"
            :key="c.id"
            :label="c.short_name || c.name"
            :value="c.id"
          />
        </el-select>
        <el-select
          v-model="filters.status"
          clearable
          placeholder="全部状态"
          style="width: 120px"
          @change="search"
        >
          <el-option label="已入账" value="posted" />
          <el-option label="已作废" value="void" />
        </el-select>
        <el-select
          v-model="filters.method"
          clearable
          placeholder="全部方式"
          style="width: 120px"
          @change="search"
        >
          <el-option label="微信" value="wechat" />
          <el-option label="支付宝" value="alipay" />
          <el-option label="银行" value="bank" />
          <el-option label="现金" value="cash" />
          <el-option label="其它" value="other" />
        </el-select>
        <el-date-picker
          v-model="filters.dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="付款起"
          end-placeholder="付款止"
          unlink-panels
          clearable
          style="width: 260px"
          @change="search"
        />
        <div class="spacer" />
        <el-button @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" @click="openCreate">登记付款</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="supplier-payments-table"
          :data="rows"
          stripe
          border
          show-summary
          :summary-method="getSummaries"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="payment_date"
            label="日期"
            :width="colWidth('payment_date', 110)"
            resizable
          />
          <el-table-column
            prop="supplier_name"
            label="供应商"
            :width="colWidth('supplier_name', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column prop="amount" label="金额" :width="colWidth('amount', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column column-key="方式" label="方式" :width="colWidth('方式', 90)" resizable>
            <template #default="{ row }">{{ methodLabel(row.method) }}</template>
          </el-table-column>
          <el-table-column
            prop="voucher_no"
            label="凭证号"
            :width="colWidth('voucher_no', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">{{ paymentStatusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column column-key="核销" label="核销" :width="colWidth('核销', 180)" resizable>
            <template #default="{ row }">
              <div v-for="a in row.allocations" :key="a.id" class="muted">
                应付#{{ a.payable_id }} · {{ formatMoney(a.amount) }}
              </div>
              <span v-if="!(row.allocations || []).length" class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="80" :resizable="false">
            <template #default="{ row }">
              <el-button v-if="row.status === 'posted'" link type="danger" @click="voidPay(row)">
                作废
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
          :page-sizes="[10, 20, 50, 100]"
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="visible" title="登记付款" width="720px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="供应商">
          <el-select
            v-model="form.supplier_id"
            filterable
            clearable
            placeholder="选择供应商以筛选未付应付"
            style="width: 100%"
            @change="onFormSupplierChange"
          >
            <el-option
              v-for="c in suppliers"
              :key="c.id"
              :label="c.short_name || c.name"
              :value="c.id"
            />
          </el-select>
          <el-input
            v-model="form.supplier_name"
            placeholder="供应商显示名"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker
            v-model="form.payment_date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="方式">
          <el-select v-model="form.method" style="width: 100%">
            <el-option label="微信" value="wechat" />
            <el-option label="支付宝" value="alipay" />
            <el-option label="银行" value="bank" />
            <el-option label="现金" value="cash" />
            <el-option label="其它" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="凭证号">
          <el-input v-model="form.voucher_no" />
        </el-form-item>
        <el-form-item label="金额">
          <span>{{ formatMoney(form.amount) }}</span>
          <span class="muted" style="margin-left: 8px">（按下方核销合计）</span>
        </el-form-item>
        <div class="admin-toolbar" style="margin-bottom: 8px">
          <span style="font-weight: 600">核销到应付（未付）</span>
          <div class="spacer" />
          <el-input
            v-model="dialogApKeyword"
            clearable
            placeholder="筛选供应商 / 采购单"
            style="width: 200px"
            @clear="loadOpenAp"
            @keyup.enter="loadOpenAp"
          />
          <el-button @click="loadOpenAp">筛选</el-button>
        </div>
        <el-table
          :data="openAp"
          border
          size="small"
          max-height="320"
          @selection-change="onSel"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column type="selection" width="48" />
          <el-table-column prop="id" label="应付ID" :width="colWidth1('id', 80)" resizable />
          <el-table-column
            prop="supplier_name"
            label="供应商"
            :width="colWidth1('supplier_name', 100)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            column-key="po_no"
            label="采购单号"
            :width="colWidth1('po_no', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              {{ row.po_no || (row.purchase_order_id ? `#${row.purchase_order_id}` : '—') }}
            </template>
          </el-table-column>
          <el-table-column prop="balance" label="未付" :width="colWidth1('balance', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.balance) }}</template>
          </el-table-column>
          <el-table-column column-key="本次核销" label="本次核销" :width="colWidth1('本次核销', 140)" resizable>
            <template #default="{ row }">
              <el-input-number
                v-model="row.alloc"
                :min="0"
                :max="Number(row.balance)"
                size="small"
                @change="syncAmount"
              />
            </template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'supplier-payments-list',
  tableRef,
  {
    flexKey: 'supplier_name',
    flexDefaultMin: 120,
    fitToContainer: true,
  },
)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths(
  'supplier-payments-detail',
)

const suppliers = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const openAp = ref<any[]>([])
const selected = ref<any[]>([])
const visible = ref(false)
const saving = ref(false)
const dialogApKeyword = ref('')

const filters = reactive({
  keyword: '',
  supplier_id: null as number | null,
  status: '' as string,
  method: '' as string,
  dateRange: null as [string, string] | null,
})

const form = reactive({
  supplier_id: null as number | null,
  supplier_name: '',
  amount: 0,
  payment_date: new Date().toISOString().slice(0, 10),
  method: 'bank',
  voucher_no: '',
})

const PAYMENT_STATUS: Record<string, string> = {
  posted: '已入账',
  void: '已作废',
}

const METHOD_LABEL: Record<string, string> = {
  wechat: '微信',
  alipay: '支付宝',
  bank: '银行',
  cash: '现金',
  other: '其它',
}

function paymentStatusLabel(s: string) {
  return PAYMENT_STATUS[s] || s || '—'
}

function methodLabel(s: string) {
  return METHOD_LABEL[s] || s || '—'
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'amount') return formatMoney(s.amount)
    return ''
  })
}

function buildListParams() {
  const params: Record<string, any> = {
    page: page.value,
    page_size: pageSize.value,
    keyword: filters.keyword.trim() || undefined,
    supplier_id: filters.supplier_id || undefined,
    status: filters.status || undefined,
    method: filters.method || undefined,
  }
  if (filters.dateRange?.length === 2) {
    params.date_from = filters.dateRange[0]
    params.date_to = filters.dateRange[1]
  }
  return params
}

async function load() {
  const res: any = await http.get('/supplier-payments', { params: buildListParams() })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  summary.value = payload?.summary || {}
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function search() {
  page.value = 1
  void load()
}

function resetFilters() {
  filters.keyword = ''
  filters.supplier_id = null
  filters.status = ''
  filters.method = ''
  filters.dateRange = null
  search()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function onSel(v: any[]) {
  selected.value = v
  syncAmount()
}

function syncAmount() {
  const source = selected.value.length
    ? selected.value
    : openAp.value.filter((r) => Number(r.alloc) > 0)
  form.amount = source.reduce((s, r) => s + Number(r.alloc || 0), 0)
}

function onFormSupplierChange(id: number | null) {
  const c = suppliers.value.find((x) => x.id === id)
  form.supplier_name = c ? c.short_name || c.name : form.supplier_name
  void loadOpenAp()
}

async function loadOpenAp() {
  const res: any = await http.get('/payables', {
    params: {
      page: 1,
      page_size: 200,
      supplier_id: form.supplier_id || undefined,
      keyword: dialogApKeyword.value.trim() || undefined,
    },
  })
  const items = res.data?.items || (Array.isArray(res.data) ? res.data : [])
  openAp.value = items
    .filter((r: any) => r.status === 'open' || r.status === 'partial')
    .map((r: any) => ({ ...r, alloc: Number(r.balance) }))
  selected.value = []
  syncAmount()
}

async function openCreate() {
  form.supplier_id = filters.supplier_id
  const c = suppliers.value.find((x) => x.id === form.supplier_id)
  form.supplier_name = c ? c.short_name || c.name : ''
  form.amount = 0
  form.payment_date = new Date().toISOString().slice(0, 10)
  form.method = 'bank'
  form.voucher_no = ''
  dialogApKeyword.value = ''
  selected.value = []
  visible.value = true
  await loadOpenAp()
}

async function submit() {
  const allocations = (selected.value.length ? selected.value : openAp.value.filter((r) => r.alloc > 0))
    .filter((r) => Number(r.alloc) > 0)
    .map((r) => ({ payable_id: r.id, amount: r.alloc }))
  if (!allocations.length) {
    ElMessage.warning('请选择要核销的应付并填写金额')
    return
  }
  const sum = allocations.reduce((s, a) => s + Number(a.amount), 0)
  form.amount = sum
  const first = openAp.value.find((x) => x.id === allocations[0].payable_id)
  const supplierName = form.supplier_name || first?.supplier_name || ''
  if (!supplierName) {
    ElMessage.warning('请填写供应商')
    return
  }
  saving.value = true
  try {
    await http.post('/supplier-payments', {
      supplier_id: form.supplier_id || first?.supplier_id || null,
      supplier_name: supplierName,
      amount: form.amount,
      payment_date: form.payment_date,
      method: form.method,
      voucher_no: form.voucher_no || undefined,
      allocations,
    })
    ElMessage.success('付款已登记')
    visible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function voidPay(row: any) {
  await http.post(`/supplier-payments/${row.id}/void`)
  ElMessage.success('已作废')
  await load()
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

onMounted(async () => {
  await loadSuppliers()
  await load()
})
</script>
