<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">应收 / 客户欠款</h1>
        <p class="page-desc">出货挂账 · 账龄 · 调账</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card receivables-tabs" @tab-change="onTabChange">
      <el-tab-pane label="客户汇总" name="summary" lazy>
        <div class="receivables-panel">
          <div class="admin-toolbar">
            <el-select
              v-model="summaryFilters.customer_id"
              clearable
              filterable
              placeholder="全部客户"
              style="width: 180px"
              @change="searchSummary"
            >
              <el-option
                v-for="c in customers"
                :key="c.id"
                :label="c.short_name || c.name"
                :value="c.id"
              />
            </el-select>
            <el-checkbox v-model="summaryFilters.with_balance_only" @change="searchSummary">
              仅有欠款
            </el-checkbox>
            <div class="spacer" />
            <el-button @click="searchSummary">查询</el-button>
            <el-button @click="resetSummaryFilters">重置</el-button>
          </div>
          <div ref="tableHostRef">
            <el-table
              ref="summaryTableRef"
              :data="summary"
              stripe
              border
              size="small"
              :max-height="tableMaxHeight"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column
                prop="customer_name"
                label="客户"
                :width="colWidth('customer_name', 140)"
                resizable
              />
              <el-table-column
                prop="balance"
                label="未收"
                :width="colWidth('balance', 100)"
                align="right"
                resizable
              />
              <el-table-column
                column-key="aging_0_30"
                label="0-30天"
                :width="colWidth('aging_0_30', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.['0-30']) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_31_60"
                label="31-60天"
                :width="colWidth('aging_31_60', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.['31-60']) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_60_plus"
                label="60+天"
                :width="colWidth('aging_60_plus', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.['60+']) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div class="admin-pagination">
            <el-pagination
              v-model:current-page="summaryPage"
              v-model:page-size="summaryPageSize"
              background
              layout="total, sizes, prev, pager, next"
              :total="summaryTotal"
              :page-sizes="[10, 20, 50, 100]"
              @current-change="loadSummary"
              @size-change="onSummaryPageSizeChange"
            />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="应收明细" name="detail" lazy>
        <div class="receivables-panel">
          <div class="admin-toolbar">
            <el-input
              v-model="detailFilters.keyword"
              clearable
              placeholder="客户 / 订单号"
              style="width: 180px"
              @clear="searchDetail"
              @keyup.enter="searchDetail"
            />
            <el-select
              v-model="detailFilters.customer_id"
              clearable
              filterable
              placeholder="全部客户"
              style="width: 180px"
              @change="searchDetail"
            >
              <el-option
                v-for="c in customers"
                :key="c.id"
                :label="c.short_name || c.name"
                :value="c.id"
              />
            </el-select>
            <el-select
              v-model="detailFilters.status"
              clearable
              placeholder="全部状态"
              style="width: 130px"
              @change="searchDetail"
            >
              <el-option label="未收" value="open" />
              <el-option label="部分已收" value="partial" />
              <el-option label="已结清" value="settled" />
              <el-option label="已作废" value="void" />
            </el-select>
            <el-date-picker
              v-model="detailFilters.dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="日期起"
              end-placeholder="日期止"
              unlink-panels
              clearable
              style="width: 260px"
              @change="searchDetail"
            />
            <div class="spacer" />
            <el-button @click="searchDetail">查询</el-button>
            <el-button @click="resetDetailFilters">重置</el-button>
          </div>
          <div ref="tableHostRef1">
            <el-table
              ref="listTableRef"
              class="receivables-detail-table"
              :data="rows"
              stripe
              border
              show-summary
              :summary-method="getDetailSummaries"
              :max-height="tableMaxHeight1"
              @header-dragend="onHeaderDragend1"
            >
              <el-table-column
                prop="receivable_date"
                label="日期"
                :width="colWidth1('receivable_date', 110)"
                resizable
              />
              <el-table-column
                prop="customer_name"
                label="客户"
                :width="colWidth1('customer_name', 120)"
                resizable
              />
              <el-table-column
                column-key="order_no"
                label="生产单号"
                :width="colWidth1('order_no', 120)"
                resizable
              >
                <template #default="{ row }">
                  {{ row.order_no || (row.order_id ? `#${row.order_id}` : '—') }}
                </template>
              </el-table-column>
              <el-table-column
                prop="amount"
                label="应收"
                :width="colWidth1('amount', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column
                prop="adjustment"
                label="调账"
                :width="colWidth1('adjustment', 80)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.adjustment) }}</template>
              </el-table-column>
              <el-table-column
                prop="received_amount"
                label="已收"
                :width="colWidth1('received_amount', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.received_amount) }}</template>
              </el-table-column>
              <el-table-column
                prop="balance"
                label="未收"
                :width="colWidth1('balance', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.balance) }}</template>
              </el-table-column>
              <el-table-column column-key="aging" label="账龄" :width="colWidth1('aging', 90)" resizable>
                <template #default="{ row }">{{ ageBucketLabel(row.age_bucket) }}</template>
              </el-table-column>
              <el-table-column column-key="status" label="状态" :width="colWidth1('status', 90)" resizable>
                <template #default="{ row }">{{ arStatusLabel(row.status) }}</template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="100" :resizable="false">
                <template #default="{ row }">
                  <el-button
                    v-if="row.status !== 'void' && row.status !== 'settled'"
                    link
                    type="primary"
                    @click="adjust(row)"
                  >
                    调账
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
              @current-change="loadRows"
              @size-change="onPageSizeChange"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type ReceivablesTab = 'summary' | 'detail'

const route = useRoute()
const router = useRouter()
const tab = ref<ReceivablesTab>('summary')

const summaryTableRef = ref<{ doLayout?: () => void } | null>(null)
const listTableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const {
  tableHostRef: tableHostRef1,
  tableMaxHeight: tableMaxHeight1,
  measureTableHeight: measureTableHeight1,
} = useTableMaxHeight()
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'receivables-summary',
  summaryTableRef,
  { flexKey: 'customer_name', flexDefaultMin: 140, fitToContainer: true },
)
const {
  colWidth: colWidth1,
  onHeaderDragend: onHeaderDragend1,
  relayoutTable: relayoutListTable,
} = useTableColWidths('receivables-list', listTableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})

const customers = ref<any[]>([])
const rows = ref<any[]>([])
const detailSummary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summary = ref<any[]>([])
const summaryTotal = ref(0)
const summaryPage = ref(1)
const summaryPageSize = ref(20)

const summaryFilters = reactive({
  customer_id: null as number | null,
  with_balance_only: true,
})

const detailFilters = reactive({
  keyword: '',
  customer_id: null as number | null,
  status: '' as string,
  dateRange: null as [string, string] | null,
})

const AR_STATUS: Record<string, string> = {
  open: '未收',
  partial: '部分已收',
  settled: '已结清',
  void: '已作废',
}

function arStatusLabel(s: string) {
  return AR_STATUS[s] || s || '—'
}

function ageBucketLabel(s: string) {
  if (s === '0-30') return '0–30天'
  if (s === '31-60') return '31–60天'
  if (s === '60+') return '60天以上'
  return s || '—'
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getDetailSummaries({ columns }: { columns: any[] }) {
  const s = detailSummary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'amount') return formatMoney(s.amount)
    if (key === 'adjustment') return formatMoney(s.adjustment)
    if (key === 'received_amount') return formatMoney(s.received_amount)
    if (key === 'balance') return formatMoney(s.balance)
    return ''
  })
}

function pickDefaultTab(): ReceivablesTab {
  const q = String(route.query.tab || '')
  if (q === 'detail' || q === 'list') return 'detail'
  if (q === 'summary' || q === 'customer') return 'summary'
  return 'summary'
}

function syncQuery(next: ReceivablesTab) {
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/receivables', query: { ...route.query, tab: next } })
}

function onTabChange(name: string | number) {
  const next = String(name) as ReceivablesTab
  tab.value = next
  syncQuery(next)
  void nextTick(() => {
    if (next === 'summary') {
      measureTableHeight()
      relayoutTable()
    } else {
      measureTableHeight1()
      relayoutListTable()
      if (!rows.value.length) void loadRows()
    }
  })
}

async function loadCustomers() {
  const res: any = await http.get('/partners', {
    params: { role: 'customer_brand', active_only: true, page_size: 200 },
  })
  customers.value = res.data?.items || []
}

async function loadRows() {
  const params: Record<string, any> = {
    page: page.value,
    page_size: pageSize.value,
    keyword: detailFilters.keyword.trim() || undefined,
    customer_id: detailFilters.customer_id || undefined,
    status: detailFilters.status || undefined,
  }
  if (detailFilters.dateRange?.length === 2) {
    params.date_from = detailFilters.dateRange[0]
    params.date_to = detailFilters.dateRange[1]
  }
  const res: any = await http.get('/receivables', { params })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  detailSummary.value = payload?.summary || {}
  void nextTick(() => {
    measureTableHeight1()
    relayoutListTable()
  })
}

async function loadSummary() {
  const res: any = await http.get('/receivables/customer-summary', {
    params: {
      page: summaryPage.value,
      page_size: summaryPageSize.value,
      customer_id: summaryFilters.customer_id || undefined,
      with_balance_only: summaryFilters.with_balance_only || undefined,
    },
  })
  const payload = res.data
  summary.value = payload?.items || (Array.isArray(payload) ? payload : [])
  summaryTotal.value = payload?.total ?? summary.value.length
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function searchSummary() {
  summaryPage.value = 1
  void loadSummary()
}

function resetSummaryFilters() {
  summaryFilters.customer_id = null
  summaryFilters.with_balance_only = true
  searchSummary()
}

function searchDetail() {
  page.value = 1
  void loadRows()
}

function resetDetailFilters() {
  detailFilters.keyword = ''
  detailFilters.customer_id = null
  detailFilters.status = ''
  detailFilters.dateRange = null
  searchDetail()
}

function onPageSizeChange() {
  page.value = 1
  void loadRows()
}

function onSummaryPageSizeChange() {
  summaryPage.value = 1
  void loadSummary()
}

async function adjust(row: any) {
  const { value } = await ElMessageBox.prompt('调账金额（可为负，如折让）', '应收调账', {
    inputValue: '0',
  })
  await http.post(`/receivables/${row.id}/adjust`, { adjustment_delta: Number(value) })
  ElMessage.success('已调账')
  await Promise.all([loadRows(), loadSummary()])
}

onMounted(async () => {
  tab.value = pickDefaultTab()
  syncQuery(tab.value)
  await loadCustomers()
  await loadSummary()
  if (tab.value === 'detail') await loadRows()
})

watch(
  () => route.query.tab,
  () => {
    const next = pickDefaultTab()
    if (next !== tab.value) tab.value = next
  },
)
</script>

<style scoped>
.receivables-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.receivables-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
