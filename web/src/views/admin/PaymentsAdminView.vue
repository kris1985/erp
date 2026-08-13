<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">回款登记</h1>
        <p class="page-desc">收款并核销到应收（禁止超额）</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="客户 / 凭证号"
          style="width: 180px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.customer_id"
          clearable
          filterable
          placeholder="全部客户"
          style="width: 180px"
          @change="search"
        >
          <el-option
            v-for="c in customers"
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
          start-placeholder="回款起"
          end-placeholder="回款止"
          unlink-panels
          clearable
          style="width: 260px"
          @change="search"
        />
        <div class="spacer" />
        <el-button @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" @click="openCreate">登记回款</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="payments-table"
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
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 120)"
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
            resizable
          />
          <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">{{ paymentStatusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column column-key="核销" label="核销" :width="colWidth('核销', 180)" resizable>
            <template #default="{ row }">
              <div v-for="a in row.allocations" :key="a.id" class="muted">
                应收#{{ a.receivable_id }} · {{ formatMoney(a.amount) }}
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

    <el-dialog v-model="visible" title="登记回款" width="720px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="客户">
          <el-select
            v-model="form.customer_id"
            filterable
            clearable
            placeholder="选择客户以筛选未收应收"
            style="width: 100%"
            @change="onFormCustomerChange"
          >
            <el-option
              v-for="c in customers"
              :key="c.id"
              :label="c.short_name || c.name"
              :value="c.id"
            />
          </el-select>
          <el-input
            v-model="form.customer_name"
            placeholder="客户显示名"
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
          <span style="font-weight: 600">核销到应收（未收）</span>
          <div class="spacer" />
          <el-input
            v-model="dialogArKeyword"
            clearable
            placeholder="筛选应收：客户 / 销售单号"
            style="width: 200px"
            @clear="loadOpenAr"
            @keyup.enter="loadOpenAr"
          />
          <el-button @click="loadOpenAr">筛选</el-button>
        </div>
        <el-table
          :data="openAr"
          border
          size="small"
          max-height="320"
          @selection-change="onSel"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column type="selection" width="48" />
          <el-table-column prop="id" label="应收ID" :width="colWidth1('id', 80)" resizable />
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth1('customer_name', 100)"
            resizable
          />
          <el-table-column
            column-key="sales_order_no"
            label="销售单号"
            :width="colWidth1('sales_order_no', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              {{ row.sales_order_no || '—' }}
            </template>
          </el-table-column>
          <el-table-column
            column-key="order_no"
            label="内部单号"
            :width="colWidth1('order_no', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              {{ row.order_no || (row.order_id ? `#${row.order_id}` : '—') }}
            </template>
          </el-table-column>
          <el-table-column prop="balance" label="未收" :width="colWidth1('balance', 90)" align="right" resizable>
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
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('payments-list', tableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('payments-detail')

const customers = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const openAr = ref<any[]>([])
const selected = ref<any[]>([])
const visible = ref(false)
const saving = ref(false)
const dialogArKeyword = ref('')

const filters = reactive({
  keyword: '',
  customer_id: null as number | null,
  status: '' as string,
  method: '' as string,
  dateRange: null as [string, string] | null,
})

const form = reactive({
  customer_id: null as number | null,
  customer_name: '',
  amount: 0,
  payment_date: new Date().toISOString().slice(0, 10),
  method: 'wechat',
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
    customer_id: filters.customer_id || undefined,
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
  const res: any = await http.get('/payments', { params: buildListParams() })
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
  filters.customer_id = null
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
    : openAr.value.filter((r) => Number(r.alloc) > 0)
  form.amount = source.reduce((s, r) => s + Number(r.alloc || 0), 0)
}

function onFormCustomerChange(id: number | null) {
  const c = customers.value.find((x) => x.id === id)
  form.customer_name = c ? c.short_name || c.name : form.customer_name
  void loadOpenAr()
}

async function loadOpenAr() {
  const res: any = await http.get('/receivables', {
    params: {
      page: 1,
      page_size: 200,
      customer_id: form.customer_id || undefined,
      keyword: dialogArKeyword.value.trim() || undefined,
      status: undefined,
    },
  })
  const items = res.data?.items || (Array.isArray(res.data) ? res.data : [])
  openAr.value = items
    .filter((r: any) => r.status === 'open' || r.status === 'partial')
    .map((r: any) => ({ ...r, alloc: Number(r.balance) }))
  selected.value = []
  syncAmount()
}

async function openCreate() {
  form.customer_id = filters.customer_id
  const c = customers.value.find((x) => x.id === form.customer_id)
  form.customer_name = c ? c.short_name || c.name : ''
  form.amount = 0
  form.payment_date = new Date().toISOString().slice(0, 10)
  form.method = 'wechat'
  form.voucher_no = ''
  dialogArKeyword.value = ''
  selected.value = []
  visible.value = true
  await loadOpenAr()
}

async function submit() {
  const allocations = (selected.value.length ? selected.value : openAr.value.filter((r) => r.alloc > 0))
    .filter((r) => Number(r.alloc) > 0)
    .map((r) => ({ receivable_id: r.id, amount: r.alloc }))
  if (!allocations.length) {
    ElMessage.warning('请选择要核销的应收并填写金额')
    return
  }
  const sum = allocations.reduce((s, a) => s + Number(a.amount), 0)
  form.amount = sum
  const first = openAr.value.find((x) => x.id === allocations[0].receivable_id)
  const customerName =
    form.customer_name || first?.customer_name || ''
  if (!customerName) {
    ElMessage.warning('请填写客户')
    return
  }
  saving.value = true
  try {
    await http.post('/payments', {
      customer_id: form.customer_id || first?.customer_id || null,
      customer_name: customerName,
      amount: form.amount,
      payment_date: form.payment_date,
      method: form.method,
      voucher_no: form.voucher_no || undefined,
      allocations,
    })
    ElMessage.success('回款已登记')
    visible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function voidPay(row: any) {
  await http.post(`/payments/${row.id}/void`)
  ElMessage.success('已作废')
  await load()
}

async function loadCustomers() {
  const res: any = await http.get('/partners', {
    params: { role: 'customer_brand', active_only: true, page_size: 200 },
  })
  customers.value = res.data?.items || []
}

onMounted(async () => {
  await loadCustomers()
  await load()
})
</script>
