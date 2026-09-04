<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">应付 / 供应商欠款</h1>
        <p class="page-desc">供应商余额 = 应付发生 − 实际付款；账龄按最早到期自动推算</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card payables-tabs" @tab-change="onTabChange">
      <el-tab-pane label="供应商汇总" name="summary" lazy>
        <div class="payables-panel">
          <div class="admin-toolbar">
            <el-select
              v-model="summaryFilters.supplier_id"
              clearable
              filterable
              placeholder="全部供应商"
              style="width: 180px"
              @change="searchSummary"
            >
              <el-option
                v-for="c in suppliers"
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
                prop="supplier_name"
                label="供应商"
                :width="colWidth('supplier_name', 140)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                prop="amount"
                label="累计应付"
                :width="colWidth('amount', 110)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column
                prop="paid_amount"
                label="累计付款"
                :width="colWidth('paid_amount', 110)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.paid_amount) }}</template>
              </el-table-column>
              <el-table-column
                prop="unallocated_credit"
                label="未分单付款"
                :width="colWidth('unallocated_credit', 120)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.unallocated_credit) }}</template>
              </el-table-column>
              <el-table-column
                prop="balance"
                label="供应商余额"
                :width="colWidth('balance', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.balance) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_not_due"
                label="未到期"
                :width="colWidth('aging_not_due', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.not_due) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_od_0_30"
                label="逾期0-30"
                :width="colWidth('aging_od_0_30', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.overdue_0_30) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_od_31_60"
                label="逾期31-60"
                :width="colWidth('aging_od_31_60', 110)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.overdue_31_60) }}</template>
              </el-table-column>
              <el-table-column
                column-key="aging_od_60"
                label="逾期60+"
                :width="colWidth('aging_od_60', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.aging?.overdue_60_plus) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="175" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openSupplierDetail(row)">明细</el-button>
                  <el-button link @click="openSupplierStatement(row)">对账</el-button>
                  <el-button link @click="openSupplierPayment(row)">付款</el-button>
                </template>
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

      <el-tab-pane label="应付明细" name="detail" lazy>
        <div class="payables-panel">
          <el-alert
            title="明细用于解释应付来源；供应商总额付款未指定分单时，不会虚构到某张到货单。真实余额以“供应商汇总”为准。"
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
          />
          <div class="admin-toolbar">
            <el-input
              v-model="detailFilters.keyword"
              clearable
              placeholder="供应商 / 采购单号"
              style="width: 180px"
              @clear="searchDetail"
              @keyup.enter="searchDetail"
            />
            <el-select
              v-model="detailFilters.supplier_id"
              clearable
              filterable
              placeholder="全部供应商"
              style="width: 180px"
              @change="searchDetail"
            >
              <el-option
                v-for="c in suppliers"
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
              <el-option label="未付" value="open" />
              <el-option label="部分已付" value="partial" />
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
              class="payables-detail-table"
              :data="rows"
              stripe
              border
              show-summary
              :summary-method="getDetailSummaries"
              :max-height="tableMaxHeight1"
              @header-dragend="onHeaderDragend1"
            >
              <el-table-column
                prop="payable_date"
                label="挂账日"
                :width="colWidth1('payable_date', 110)"
                resizable
              />
              <el-table-column
                prop="due_date"
                label="到期日"
                :width="colWidth1('due_date', 110)"
                resizable
              />
              <el-table-column
                prop="payment_term_days"
                label="账期"
                :width="colWidth1('payment_term_days', 70)"
                align="right"
                resizable
              >
                <template #default="{ row }">
                  {{ Number(row.payment_term_days) > 0 ? `${row.payment_term_days}天` : '现结' }}
                </template>
              </el-table-column>
              <el-table-column
                prop="supplier_name"
                label="供应商"
                :width="colWidth1('supplier_name', 120)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                column-key="po_no"
                label="采购单号"
                :width="colWidth1('po_no', 120)"
                show-overflow-tooltip
                resizable
              >
                <template #default="{ row }">
                  {{ row.po_no || (row.purchase_order_id ? `#${row.purchase_order_id}` : '—') }}
                </template>
              </el-table-column>
              <el-table-column
                prop="amount"
                label="应付"
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
                prop="paid_amount"
                label="逐单已付"
                :width="colWidth1('paid_amount', 90)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMoney(row.paid_amount) }}</template>
              </el-table-column>
              <el-table-column
                prop="balance"
                label="逐单余款"
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
                <template #default="{ row }">{{ apStatusLabel(row.status) }}</template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="100" :resizable="false">
                <template #default="{ row }">
                  <el-button
                    v-if="row.status !== 'void'"
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

type PayablesTab = 'summary' | 'detail'

const route = useRoute()
const router = useRouter()
const tab = ref<PayablesTab>('summary')

const summaryTableRef = ref<{ doLayout?: () => void } | null>(null)
const listTableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const {
  tableHostRef: tableHostRef1,
  tableMaxHeight: tableMaxHeight1,
  measureTableHeight: measureTableHeight1,
} = useTableMaxHeight()
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'payables-summary',
  summaryTableRef,
  { flexKey: 'supplier_name', flexDefaultMin: 140, fitToContainer: true },
)
const {
  colWidth: colWidth1,
  onHeaderDragend: onHeaderDragend1,
  relayoutTable: relayoutListTable,
} = useTableColWidths('payables-list', listTableRef, {
  flexKey: 'supplier_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})

const suppliers = ref<any[]>([])
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
  supplier_id: null as number | null,
  with_balance_only: true,
})

const detailFilters = reactive({
  keyword: '',
  supplier_id: null as number | null,
  status: '' as string,
  dateRange: null as [string, string] | null,
})

const AP_STATUS: Record<string, string> = {
  open: '未付',
  partial: '部分已付',
  settled: '已结清',
  void: '已作废',
}

function apStatusLabel(s: string) {
  return AP_STATUS[s] || s || '—'
}

function ageBucketLabel(s: string) {
  if (s === 'not_due') return '未到期'
  if (s === 'overdue_0_30') return '逾期0–30天'
  if (s === 'overdue_31_60') return '逾期31–60天'
  if (s === 'overdue_60_plus') return '逾期60天以上'
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
    if (key === 'paid_amount') return formatMoney(s.paid_amount)
    if (key === 'balance') return formatMoney(s.balance)
    return ''
  })
}

function pickDefaultTab(): PayablesTab {
  const q = String(route.query.tab || '')
  if (q === 'detail' || q === 'list') return 'detail'
  if (q === 'summary' || q === 'supplier') return 'summary'
  return 'summary'
}

function syncQuery(next: PayablesTab) {
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: route.path, query: { ...route.query, tab: next } })
}

function onTabChange(name: string | number) {
  const next = String(name) as PayablesTab
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

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function loadRows() {
  const params: Record<string, any> = {
    page: page.value,
    page_size: pageSize.value,
    keyword: detailFilters.keyword.trim() || undefined,
    supplier_id: detailFilters.supplier_id || undefined,
    status: detailFilters.status || undefined,
  }
  if (detailFilters.dateRange?.length === 2) {
    params.date_from = detailFilters.dateRange[0]
    params.date_to = detailFilters.dateRange[1]
  }
  const res: any = await http.get('/payables', { params })
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
  const res: any = await http.get('/payables/supplier-summary', {
    params: {
      page: summaryPage.value,
      page_size: summaryPageSize.value,
      supplier_id: summaryFilters.supplier_id || undefined,
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
  summaryFilters.supplier_id = null
  summaryFilters.with_balance_only = true
  searchSummary()
}

function searchDetail() {
  page.value = 1
  void loadRows()
}

function resetDetailFilters() {
  detailFilters.keyword = ''
  detailFilters.supplier_id = null
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
  const { value: amountValue } = await ElMessageBox.prompt('调账金额（可为负，如扣款）', '应付调账', {
    inputValue: '0',
    inputValidator: (value) => {
      const amount = Number(value)
      if (!Number.isFinite(amount) || amount === 0) return '请输入非零调账金额'
      return true
    },
  })
  const amount = Number(amountValue)
  const { value: reason } = await ElMessageBox.prompt('请填写退货、品质扣款、补差等具体原因', '调账原因', {
    inputPlaceholder: '调账原因（必填）',
    inputValidator: (value) => value.trim() ? true : '请填写调账原因',
  })
  const nextBalance = Number(row.balance || 0) + amount
  await ElMessageBox.confirm(
    `本次调整 ${formatMoney(amount)}，调整后指定到单余款 ${formatMoney(nextBalance)}。原因：${reason}`,
    '确认应付调账',
    { type: 'warning' },
  )
  await http.post(`/payables/${row.id}/adjust`, {
    adjustment_delta: amount,
    notes: reason.trim(),
  })
  ElMessage.success('已调账')
  await Promise.all([loadRows(), loadSummary()])
}

function openSupplierDetail(row: any) {
  detailFilters.supplier_id = row.supplier_id || null
  detailFilters.keyword = row.supplier_id ? '' : String(row.supplier_name || '')
  page.value = 1
  tab.value = 'detail'
  syncQuery('detail')
  void loadRows()
}

function openSupplierStatement(row: any) {
  void router.replace({
    path: '/admin/settlements',
    query: {
      section: 'statements',
      partner_type: 'supplier',
      partner_id: String(row.supplier_id || ''),
      generate: '1',
    },
  })
}

function openSupplierPayment(row: any) {
  void router.replace({
    path: '/admin/settlements',
    query: {
      section: 'cash',
      flow: 'payments',
      partner_id: String(row.supplier_id || ''),
      partner_name: String(row.supplier_name || ''),
      open: '1',
    },
  })
}

onMounted(async () => {
  tab.value = pickDefaultTab()
  syncQuery(tab.value)
  await loadSuppliers()
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
.payables-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.payables-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
