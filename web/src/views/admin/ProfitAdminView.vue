<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">利润复盘</h1>
        <p class="page-desc">估算毛利 · 收入 − 材料 − 人工 − 其它</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="订单 / 客户 / 产品"
          style="width: 200px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="customerId"
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
        <el-date-picker
          v-model="monthVal"
          type="month"
          value-format="YYYY-MM"
          placeholder="出货月份"
          :disabled="!!dateRange?.length"
          @change="search"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="出货起"
          end-placeholder="出货止"
          unlink-panels
          clearable
          style="width: 260px"
          @change="onDateRangeChange"
        />
        <el-checkbox v-model="lossOnly" @change="search">仅看亏损</el-checkbox>
        <div class="spacer" />
        <el-button @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="profit-table"
          :data="orders"
          stripe
          border
          show-summary
          :summary-method="getSummaries"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 110)" resizable />
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 120)"
            resizable
          />
          <el-table-column
            prop="product_code"
            label="产品"
            :width="colWidth('product_code', 120)"
            resizable
          />
          <el-table-column
            prop="shipped_qty"
            label="已出货"
            :width="colWidth('shipped_qty', 80)"
            align="right"
            resizable
          />
          <el-table-column
            prop="revenue"
            label="收入"
            :width="colWidth('revenue', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.revenue) }}</template>
          </el-table-column>
          <el-table-column
            prop="material_cost"
            label="材料"
            :width="colWidth('material_cost', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.material_cost) }}</template>
          </el-table-column>
          <el-table-column
            prop="labor_cost"
            label="人工"
            :width="colWidth('labor_cost', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.labor_cost) }}</template>
          </el-table-column>
          <el-table-column
            prop="other_cost"
            label="其它"
            :width="colWidth('other_cost', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.other_cost) }}</template>
          </el-table-column>
          <el-table-column
            column-key="margin"
            label="毛利率"
            :width="colWidth('margin', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ formatMargin(row.gross_margin) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="gross_profit"
            label="毛利"
            :width="colWidth('gross_profit', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span :class="Number(row.gross_profit) < 0 ? 'profit-neg' : ''">
                {{ formatMoney(row.gross_profit) }}
              </span>
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
      <p class="view-hint muted">金额为估算毛利（按筛选结果合计），供经营参考</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('profit-orders', tableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const monthVal = ref(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`)
const dateRange = ref<[string, string] | null>(null)
const keyword = ref('')
const customerId = ref<number | null>(null)
const lossOnly = ref(false)
const customers = ref<any[]>([])
const orders = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const ym = computed(() => {
  if (dateRange.value?.length === 2) return { year: undefined, month: undefined }
  const [y, m] = (monthVal.value || '').split('-').map(Number)
  return { year: y || undefined, month: m || undefined }
})

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatMargin(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'shipped_qty') return String(s.shipped_qty ?? 0)
    if (key === 'revenue') return formatMoney(s.revenue)
    if (key === 'material_cost') return formatMoney(s.material_cost)
    if (key === 'labor_cost') return formatMoney(s.labor_cost)
    if (key === 'other_cost') return formatMoney(s.other_cost)
    if (key === 'gross_profit') return formatMoney(s.gross_profit)
    return ''
  })
}

function buildParams() {
  const params: Record<string, any> = {
    page: page.value,
    page_size: pageSize.value,
    keyword: keyword.value.trim() || undefined,
    customer_id: customerId.value || undefined,
    loss_only: lossOnly.value || undefined,
  }
  if (dateRange.value?.length === 2) {
    params.date_from = dateRange.value[0]
    params.date_to = dateRange.value[1]
  } else {
    params.year = ym.value.year
    params.month = ym.value.month
  }
  return params
}

async function load() {
  const res: any = await http.get('/profit-report', { params: buildParams() })
  orders.value = res.data?.orders || res.data?.items || []
  total.value = res.data?.total ?? orders.value.length
  summary.value = res.data?.summary || {}
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function search() {
  page.value = 1
  void load()
}

function onDateRangeChange() {
  search()
}

function resetFilters() {
  keyword.value = ''
  customerId.value = null
  lossOnly.value = false
  dateRange.value = null
  monthVal.value = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`
  search()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function loadCustomers() {
  const res: any = await http.get('/partners', {
    params: { role: 'customer_brand', active_only: true, page_size: 200 },
  })
  customers.value = res.data?.items || []
}

onMounted(async () => {
  await Promise.all([loadCustomers(), load()])
  measureTableHeight()
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
</style>
