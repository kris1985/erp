<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">利润复盘</h1>
        <p class="page-desc">{{ pageDesc }}</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="admin-tabs profit-tabs" @tab-change="onTabChange">
      <el-tab-pane label="订单利润" name="orders" />
      <el-tab-pane label="成本分析" name="cost" />
    </el-tabs>

    <!-- 订单利润 -->
    <div v-show="activeTab === 'orders'" class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="销售单 / 客户 / 产品 / 退货单"
          style="width: 220px"
          @clear="searchOrders"
          @keyup.enter="searchOrders"
        />
        <el-select
          v-model="customerId"
          clearable
          filterable
          placeholder="全部客户"
          style="width: 180px"
          @change="searchOrders"
        >
          <el-option
            v-for="c in customers"
            :key="c.id"
            :label="c.short_name || c.name"
            :value="c.id"
          />
        </el-select>
        <el-date-picker
          v-model="monthVal"
          type="month"
          value-format="YYYY-MM"
          placeholder="全部月份"
          clearable
          :disabled="!!dateRange?.length"
          @change="searchOrders"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="起"
          end-placeholder="止"
          unlink-panels
          clearable
          style="width: 260px"
          @change="onOrderDateRangeChange"
        />
        <el-checkbox v-model="lossOnly" @change="searchOrders">仅看亏损</el-checkbox>
        <div class="spacer" />
        <el-button @click="searchOrders">查询</el-button>
        <el-button @click="resetOrderFilters">重置</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="profit-table"
          :data="orders"
          v-loading="ordersLoading"
          stripe
          border
          show-summary
          :summary-method="getOrderSummaries"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="order_date"
            label="下单日期"
            :width="colWidth('order_date', 110)"
            resizable
          >
            <template #default="{ row }">{{ row.order_date || '—' }}</template>
          </el-table-column>
          <el-table-column prop="order_no" label="订单号" :width="colWidth('order_no', 110)" resizable>
            <template #default="{ row }">{{ row.order_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 110)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="factory_model"
            label="工厂型号"
            :width="colWidth('factory_model', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.factory_model || row.product_code || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="image"
            label="图片"
            :width="colWidth('image', 72)"
            align="center"
            class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="contain"
                class="product-thumb"
                preview-teleported
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="color" label="颜色" :width="colWidth('color', 80)" resizable>
            <template #default="{ row }">{{ row.color || '—' }}</template>
          </el-table-column>
          <el-table-column prop="brand" label="品牌" :width="colWidth('brand', 90)" resizable>
            <template #default="{ row }">{{ row.brand || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="shipped_qty"
            label="出货数量"
            :width="colWidth('shipped_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ row.row_type === 'return' ? '—' : row.shipped_qty ?? '—' }}
            </template>
          </el-table-column>
          <el-table-column
            prop="unit_price"
            label="单价"
            :width="colWidth('unit_price', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column
            prop="total_price"
            label="总价"
            :width="colWidth('total_price', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.total_price) }}</template>
          </el-table-column>
          <el-table-column
            prop="material_cost"
            label="物料"
            :width="colWidth('material_cost', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ row.row_type === 'return' ? '—' : formatMoney(row.material_cost) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="piecework_labor"
            label="计件人工"
            :width="colWidth('piecework_labor', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.piecework_labor) }}</template>
          </el-table-column>
          <el-table-column
            prop="commission"
            label="提成"
            :width="colWidth('commission', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.commission) }}</template>
          </el-table-column>
          <el-table-column
            prop="profit"
            label="利润"
            :width="colWidth('profit', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span
                v-if="row.row_type !== 'return'"
                :class="Number(row.profit) < 0 ? 'profit-neg' : ''"
              >
                {{ formatMoney(row.profit) }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="margin"
            label="毛利率"
            :width="colWidth('margin', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ row.row_type === 'return' ? '—' : formatMargin(row.gross_margin) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="allocated_cost"
            label="综合分摊"
            :width="colWidth('allocated_cost', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.allocated_cost) }}</template>
          </el-table-column>
          <el-table-column
            prop="return_no"
            label="退货单号"
            :width="colWidth('return_no', 110)"
            resizable
          >
            <template #default="{ row }">{{ row.return_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="return_qty"
            label="退货数量"
            :width="colWidth('return_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ row.return_qty === null || row.return_qty === undefined ? '—' : row.return_qty }}
            </template>
          </el-table-column>
          <el-table-column
            prop="loss_amount"
            label="损失金额"
            :width="colWidth('loss_amount', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span
                v-if="row.loss_amount !== null && row.loss_amount !== undefined"
                class="profit-neg"
              >
                {{ formatMoney(row.loss_amount) }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <p class="view-hint muted">
        利润 = 总价 − 物料 − 计件人工 − 提成；退货行「下单日期」为退货日期；综合分摊取成本分析无日期段口径 × 出货双数
      </p>
    </div>

    <!-- 成本分析 -->
    <div v-show="activeTab === 'cost'" class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="costMonthVal"
          type="month"
          value-format="YYYY-MM"
          placeholder="开支月份"
          :disabled="!!costDateRange?.length"
          @change="loadCost"
        />
        <el-date-picker
          v-model="costDateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开支起"
          end-placeholder="开支止"
          unlink-panels
          clearable
          style="width: 260px"
          @change="onCostDateRangeChange"
        />
        <div class="spacer" />
        <div class="cost-kpi-group" v-loading="costLoading">
          <div class="dev-cost-kpi">
            <span>{{ formatCostKpiPrefix('开发成本', devCost) }}</span>
            <span class="cost-kpi-result">{{ formatCostKpiResult(devCost) }}</span>
          </div>
          <div class="dev-cost-kpi">
            <span>{{ formatCostKpiPrefix('综合分摊', allocatedCost) }}</span>
            <span class="cost-kpi-result">{{ formatCostKpiResult(allocatedCost) }}</span>
          </div>
        </div>
      </div>
      <div ref="costTableHostRef">
        <!-- 动态多级表头须用 :key remount，否则异步加载后只剩「日期」列 -->
        <el-table
          v-if="costHeaders.length"
          :key="costTableRenderKey"
          ref="costTableRef"
          class="cost-analysis-table"
          :data="costRows"
          stripe
          border
          style="width: 100%"
          show-summary
          :summary-method="getCostSummaries"
          :max-height="costTableMaxHeight"
          v-loading="costLoading"
          @header-dragend="onCostHeaderDragend"
        >
          <el-table-column
            prop="date"
            label="日期"
            :width="costColWidth('date', 110)"
            fixed
            resizable
          />
          <el-table-column
            v-for="dept in costHeaders"
            :key="`dept-${dept.department_id}`"
            :label="dept.department_name"
            align="center"
          >
            <el-table-column
              v-for="col in dept.children"
              :key="cellKey(dept.department_id, col.key)"
              :column-key="cellKey(dept.department_id, col.key)"
              :prop="cellKey(dept.department_id, col.key)"
              :label="col.label"
              :width="costColWidth(cellKey(dept.department_id, col.key), 100)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ formatCostCell(row[cellKey(dept.department_id, col.key)]) }}
              </template>
            </el-table-column>
          </el-table-column>
        </el-table>
        <div v-else-if="!costLoading" class="cost-empty muted">所选期间暂无成本数据</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type ProfitTab = 'orders' | 'cost'

const route = useRoute()
const router = useRouter()

const activeTab = ref<ProfitTab>('orders')
const pageDesc = computed(() =>
  activeTab.value === 'cost'
    ? '综合成本分析 · 按部门按日统计开支'
    : '订单利润分析 · 含退货 · 利润 = 总价 − 物料 − 计件 − 提成',
)

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('profit-orders-v2', tableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 110,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const costTableRef = ref<{ doLayout?: () => void } | null>(null)
const {
  colWidth: costColWidth,
  onHeaderDragend: onCostHeaderDragend,
  relayoutTable: relayoutCostTable,
} = useTableColWidths('profit-cost-analysis-v3', costTableRef, {
  flexKey: 'date',
  flexDefaultMin: 110,
  fitToContainer: true,
})
const {
  tableHostRef: costTableHostRef,
  tableMaxHeight: costTableMaxHeight,
  measureTableHeight: measureCostTableHeight,
} = useTableMaxHeight()

function cellKey(departmentId: number, cat: string) {
  return `${departmentId}_${cat}`
}

function currentMonth() {
  return `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`
}

const monthVal = ref<string | null>(null)
const dateRange = ref<[string, string] | null>(null)
const keyword = ref('')
const customerId = ref<number | null>(null)
const lossOnly = ref(false)
const customers = ref<any[]>([])
const orders = ref<any[]>([])
const summary = ref<any>({})
const ordersLoading = ref(false)

const costMonthVal = ref(currentMonth())
const costDateRange = ref<[string, string] | null>(null)
const costHeaders = ref<
  { department_id: number; department_name: string; children: { key: string; label: string }[] }[]
>([])
const costRows = ref<Record<string, any>[]>([])
const costSummary = ref<Record<string, number>>({})
const costLoading = ref(false)
const costLoaded = ref(false)
type CostKpi = {
  total_expense?: number
  shipped_qty?: number
  unit_cost?: number | null
} | null
const devCost = ref<CostKpi>(null)
const allocatedCost = ref<CostKpi>(null)

const costTableRenderKey = computed(() =>
  costHeaders.value
    .map((h) => `${h.department_id}:${(h.children || []).map((c) => c.key).join(',')}`)
    .join('|') || 'empty',
)

/** 后端 cell key 为 `deptId:cat`，前端列 prop 用 `_` 避免路径歧义 */
function normalizeCellKey(raw: string) {
  return String(raw || '').replace(':', '_')
}

function flattenCostPayload(data: any) {
  const headers = (data?.headers || []) as typeof costHeaders.value
  const summaryRaw = (data?.summary || {}) as Record<string, number>
  const summary: Record<string, number> = {}
  for (const [k, v] of Object.entries(summaryRaw)) {
    summary[normalizeCellKey(k)] = Number(v) || 0
  }
  const rows = ((data?.rows || []) as { date: string; values?: Record<string, number> }[]).map(
    (r) => {
      const flat: Record<string, any> = { date: r.date }
      for (const [k, v] of Object.entries(r.values || {})) {
        flat[normalizeCellKey(k)] = v
      }
      return flat
    },
  )
  return {
    headers,
    rows,
    summary,
    devCost: data?.dev_cost || null,
    allocatedCost: data?.allocated_cost || null,
  }
}

const ym = computed(() => {
  if (dateRange.value?.length === 2) return { year: undefined, month: undefined }
  const [y, m] = (monthVal.value || '').split('-').map(Number)
  return { year: y || undefined, month: m || undefined }
})

const costYm = computed(() => {
  if (costDateRange.value?.length === 2) return { year: undefined, month: undefined }
  const [y, m] = (costMonthVal.value || '').split('-').map(Number)
  return { year: y || undefined, month: m || undefined }
})

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatCostCell(v: any) {
  if (v === null || v === undefined || v === '' || Number(v) === 0) return ''
  return formatMoney(v)
}

function formatCostKpiPrefix(label: string, info: CostKpi) {
  if (!info) return `${label}=¥— ÷ — 双=`
  const expense = formatMoney(info.total_expense)
  const qty = Number(info.shipped_qty || 0).toLocaleString('zh-CN')
  return `${label}=¥${expense} ÷ ${qty} 双=`
}

function formatCostKpiResult(info: CostKpi) {
  if (!info) return '¥—/双'
  const qty = Number(info.shipped_qty || 0)
  if (info.unit_cost === null || info.unit_cost === undefined || qty <= 0) return '¥—/双'
  return `¥${formatMoney(info.unit_cost)}/双`
}

function formatMargin(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function getOrderSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'shipped_qty') return String(s.shipped_qty ?? 0)
    if (key === 'total_price' || key === 'revenue') return formatMoney(s.revenue)
    if (key === 'material_cost') return formatMoney(s.material_cost)
    if (key === 'piecework_labor') return formatMoney(s.piecework_labor)
    if (key === 'commission') return formatMoney(s.commission)
    if (key === 'profit') return formatMoney(s.profit)
    if (key === 'allocated_cost') return formatMoney(s.allocated_cost)
    if (key === 'return_qty') return String(s.return_qty ?? 0)
    if (key === 'loss_amount') return formatMoney(s.loss_amount)
    return ''
  })
}

function getCostSummaries({ columns }: { columns: any[] }) {
  const s = costSummary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (!key || key === 'date') return ''
    const n = s[key]
    if (n === null || n === undefined || Number(n) === 0) return ''
    return formatMoney(n)
  })
}

function buildOrderParams() {
  const params: Record<string, any> = {
    keyword: keyword.value.trim() || undefined,
    customer_id: customerId.value || undefined,
    loss_only: lossOnly.value || undefined,
  }
  if (dateRange.value?.length === 2) {
    params.date_from = dateRange.value[0]
    params.date_to = dateRange.value[1]
  } else if (ym.value.year) {
    params.year = ym.value.year
    params.month = ym.value.month
  }
  return params
}

function buildCostParams() {
  const params: Record<string, any> = {}
  if (costDateRange.value?.length === 2) {
    params.date_from = costDateRange.value[0]
    params.date_to = costDateRange.value[1]
  } else {
    params.year = costYm.value.year
    params.month = costYm.value.month
  }
  return params
}

async function loadOrders() {
  ordersLoading.value = true
  try {
    const res: any = await http.get('/profit-report', {
      params: buildOrderParams(),
      timeout: 60000,
    })
    orders.value = res.data?.orders || res.data?.items || []
    summary.value = res.data?.summary || {}
  } catch {
    orders.value = []
    summary.value = {}
  } finally {
    ordersLoading.value = false
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

async function loadCost() {
  costLoading.value = true
  try {
    const res: any = await http.get('/cost-analysis', { params: buildCostParams() })
    const flat = flattenCostPayload(res.data)
    costHeaders.value = flat.headers
    costRows.value = flat.rows
    costSummary.value = flat.summary
    devCost.value = flat.devCost
    allocatedCost.value = flat.allocatedCost
    costLoaded.value = true
  } finally {
    costLoading.value = false
  }
  // remount 后需再测宽，铺满容器
  void nextTick(() => {
    void nextTick(() => {
      measureCostTableHeight()
      relayoutCostTable()
    })
  })
}

watch(costTableRenderKey, () => {
  void nextTick(() => {
    measureCostTableHeight()
    relayoutCostTable()
  })
})

function searchOrders() {
  void loadOrders()
}

function onOrderDateRangeChange() {
  searchOrders()
}

function onCostDateRangeChange() {
  void loadCost()
}

function resetOrderFilters() {
  keyword.value = ''
  customerId.value = null
  lossOnly.value = false
  dateRange.value = null
  monthVal.value = null
  searchOrders()
}

function pickTab(): ProfitTab {
  const q = String(route.query.tab || '')
  return q === 'cost' ? 'cost' : 'orders'
}

function syncTabQuery(tab: ProfitTab) {
  const cur = String(route.query.tab || '')
  const next = tab === 'orders' ? undefined : tab
  if ((cur || undefined) === next) return
  const query = { ...route.query }
  if (next) query.tab = next
  else delete query.tab
  router.replace({ path: '/admin/profit', query })
}

async function onTabChange(name: string | number) {
  const tab = String(name) as ProfitTab
  activeTab.value = tab
  syncTabQuery(tab)
  if (tab === 'cost' && !costLoaded.value) {
    await loadCost()
  } else if (tab === 'cost') {
    void nextTick(() => {
      measureCostTableHeight()
      relayoutCostTable()
    })
  } else {
    void nextTick(() => {
      measureTableHeight()
      relayoutTable()
    })
  }
}

async function loadCustomers() {
  const res: any = await http.get('/partners', {
    params: { role: 'customer_brand', active_only: true, page_size: 200 },
  })
  customers.value = res.data?.items || []
}

watch(
  () => route.query.tab,
  () => {
    const next = pickTab()
    if (next !== activeTab.value) {
      activeTab.value = next
      if (next === 'cost' && !costLoaded.value) void loadCost()
    }
  },
)

onMounted(async () => {
  activeTab.value = pickTab()
  syncTabQuery(activeTab.value)
  if (activeTab.value === 'cost') {
    await Promise.all([loadCustomers(), loadCost()])
  } else {
    await Promise.all([loadCustomers(), loadOrders()])
  }
  measureTableHeight()
  measureCostTableHeight()
})
</script>

<style scoped>
.profit-neg {
  color: #dc2626;
  font-weight: 600;
}
.view-hint {
  margin: 8px 0 0;
  font-size: 12px;
}
.profit-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.cost-analysis-table :deep(.el-table__header th) {
  text-align: center;
}
.cost-empty {
  padding: 24px 8px;
  font-size: 13px;
}
.cost-kpi-group {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.dev-cost-kpi {
  display: inline-flex;
  align-items: baseline;
  min-height: 26px;
  padding: 0 4px;
  font-size: 13px;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}
.cost-kpi-result {
  margin-left: 2px;
  font-size: 18px;
  font-weight: 700;
  color: var(--el-color-primary);
  line-height: 1.2;
}
.product-thumb {
  width: 44px;
  height: 44px;
  display: block;
  margin: 0 auto;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
:deep(td.mat-image-col) {
  padding: 4px !important;
}
</style>
