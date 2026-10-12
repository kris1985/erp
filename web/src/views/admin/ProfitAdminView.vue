<template>
  <div>
    <!-- 订单利润 -->
    <div v-show="activeTab === 'orders'" class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.order_no"
          clearable
          placeholder="订单号"
          style="width: 140px"
          @input="scheduleOrderSearch"
          @clear="searchOrders"
          @keyup.enter="searchOrders"
        />
        <el-input
          v-model="filters.customer_name"
          clearable
          placeholder="客户"
          style="width: 140px"
          @input="scheduleOrderSearch"
          @clear="searchOrders"
          @keyup.enter="searchOrders"
        />
        <el-input
          v-model="filters.factory_model"
          clearable
          placeholder="工厂型号"
          style="width: 140px"
          @input="scheduleOrderSearch"
          @clear="searchOrders"
          @keyup.enter="searchOrders"
        />
        <el-input
          v-model="filters.brand"
          clearable
          placeholder="品牌"
          style="width: 120px"
          @input="scheduleOrderSearch"
          @clear="searchOrders"
          @keyup.enter="searchOrders"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="起"
          end-placeholder="止"
          unlink-panels
          clearable
          style="width: 220px"
          @change="onOrderDateRangeChange"
        />
        <el-checkbox v-model="lossOnly" @change="searchOrders">仅看亏损</el-checkbox>
        <div class="spacer" />
        <div class="dev-cost-kpi" v-loading="ordersLoading">
          <span>综合利润=¥{{ formatMoney(summary.profit) }} − ¥{{ formatMoney(summary.allocated_cost) }} − ¥{{ formatMoney(summary.loss_amount) }}=</span>
          <span
            class="cost-kpi-result"
            :class="{ 'profit-neg': Number(comprehensiveProfit) < 0 }"
          >
            ¥{{ formatMoney(comprehensiveProfit) }}
          </span>
        </div>
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
            prop="total_qty"
            label="总数"
            :width="colWidth('total_qty', 80)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ row.row_type === 'return' ? '—' : row.total_qty ?? '—' }}
            </template>
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
          <el-table-column label="模具分摊" align="center">
            <el-table-column
              prop="mold_last"
              label="楦头"
              :width="colWidth('mold_last', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row.row_type === 'return' ? '—' : formatMoney(row.mold_last) }}
              </template>
            </el-table-column>
            <el-table-column
              prop="mold_sole"
              label="鞋底"
              :width="colWidth('mold_sole', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row.row_type === 'return' ? '—' : formatMoney(row.mold_sole) }}
              </template>
            </el-table-column>
            <el-table-column
              prop="mold_heel"
              label="鞋跟"
              :width="colWidth('mold_heel', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row.row_type === 'return' ? '—' : formatMoney(row.mold_heel) }}
              </template>
            </el-table-column>
            <el-table-column
              prop="mold_knife"
              label="刀模"
              :width="colWidth('mold_knife', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row.row_type === 'return' ? '—' : formatMoney(row.mold_knife) }}
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column
            prop="piecework_labor"
            label="计件工资"
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
              <span v-if="row.loss_amount !== null && row.loss_amount !== undefined">
                {{ formatMoney(row.loss_amount) }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 成本分析 -->
    <div v-show="activeTab === 'cost'" class="admin-card">
      <el-tabs v-model="costSection" class="admin-tabs" @tab-change="onCostSectionChange">
        <el-tab-pane label="综合成本分析" name="summary" />
        <el-tab-pane label="模具成本分析" name="mold" />
      </el-tabs>
      <div v-show="costSection === 'summary'">
      <div class="admin-toolbar cost-toolbar">
        <el-date-picker
          v-model="costMonthVal"
          type="month"
          value-format="YYYY-MM"
          placeholder="全部月份"
          clearable
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
          @change="onCostDateRangeChange"
        />
      </div>
      <div class="cost-chart-row">
        <div v-show="costHeaders.length" ref="costChartEl" class="cost-chart" />
        <div class="cost-kpi-side" v-loading="costLoading">
          <div v-for="item in costKpiItems" :key="item.label" class="dev-cost-kpi">
            <span class="cost-kpi-label">
              {{ item.label }}
              <el-tooltip :content="item.tip" placement="top">
                <el-icon class="kpi-tip" @click.stop><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <span>{{ formatCostKpiBody(item.info) }}</span>
            <span class="cost-kpi-result">{{ formatCostKpiResult(item.info) }}</span>
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
            :resizable="false"
          >
            <el-table-column
              v-for="col in dept.children"
              :key="cellKey(dept.department_id, col.key)"
              :column-key="cellKey(dept.department_id, col.key)"
              :prop="cellKey(dept.department_id, col.key)"
              :label="col.label"
              :width="costColWidth(cellKey(dept.department_id, col.key), col.key === 'fixed_salary' ? 100 : 108)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <span :class="{ 'cost-in': Number(row[cellKey(dept.department_id, col.key)]) < 0 }">
                  {{ formatCostCell(row[cellKey(dept.department_id, col.key)]) }}
                </span>
              </template>
            </el-table-column>
          </el-table-column>
        </el-table>
        <div v-else-if="!costLoading" class="cost-empty muted">所选期间暂无成本数据</div>
      </div>
      </div>
      <MoldCostAnalysisPanel v-if="costSection === 'mold'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { QuestionFilled } from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import http from '@/api/http'
import MoldCostAnalysisPanel from '@/views/admin/MoldCostAnalysisPanel.vue'

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type ProfitTab = 'orders' | 'cost'
type CostColumn = { key: string; label: string; children?: CostColumn[] }

const route = useRoute()
const router = useRouter()

const activeTab = ref<ProfitTab>('orders')
const costSection = ref<'summary' | 'mold'>('summary')

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
} = useTableColWidths('profit-cost-analysis-v5', costTableRef, {
  fitToContainer: false,
  groupEdgeResize: true,
})
const {
  tableHostRef: costTableHostRef,
  tableMaxHeight: costTableMaxHeight,
  measureTableHeight: measureCostTableHeight,
} = useTableMaxHeight()

function cellKey(departmentId: number, cat: string) {
  return `${departmentId}_${cat}`
}

const costChartEl = ref<HTMLElement | null>(null)
let costChart: echarts.ECharts | null = null

const COST_CATEGORY_COLORS: Record<string, string> = {
  fixed_salary: '#1d4ed8',
  仓库领料: '#0f766e',
  辅料耗材: '#c2410c',
  复版收费: '#059669',
  交通费: '#d97706',
  住宿费: '#7c3aed',
  餐饮费: '#db2777',
  礼品费: '#be123c',
  房租: '#4338ca',
  水电: '#0891b2',
  鞋材物料: '#65a30d',
  鞋样资讯: '#ca8a04',
  机器采购: '#475569',
  机器维修: '#b45309',
  快递物流费: '#0284c7',
  办公用品: '#4f46e5',
  其它: '#94a3b8',
}
const COST_COLOR_FALLBACK = ['#0ea5e9', '#f97316', '#84cc16', '#e11d48', '#6366f1', '#14b8a6', '#a16207']

function costCategoryColor(key: string, index: number) {
  return COST_CATEGORY_COLORS[key] || COST_COLOR_FALLBACK[index % COST_COLOR_FALLBACK.length]
}

function costChartCategories() {
  const seen = new Set<string>()
  const categories: { key: string; label: string }[] = []
  for (const dept of costHeaders.value) {
    for (const col of dept.children || []) {
      if (seen.has(col.key)) continue
      seen.add(col.key)
      categories.push({ key: col.key, label: col.label })
    }
  }
  return categories
}

function renderCostChart() {
  const el = costChartEl.value
  if (!el || !costHeaders.value.length) {
    costChart?.clear()
    return
  }
  costChart = costChart || echarts.init(el)
  const depts = costHeaders.value
  const categories = costChartCategories()
  costChart.setOption(
    {
      color: categories.map((cat, index) => costCategoryColor(cat.key, index)),
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        extraCssText: 'white-space: nowrap;',
        formatter(params: unknown) {
          const rows = (Array.isArray(params) ? params : [params]) as {
            axisValue?: string
            marker?: string
            seriesName?: string
            value?: number
          }[]
          const visible = rows.filter((row) => Number(row.value) !== 0)
          const total = visible.reduce((sum, row) => sum + Number(row.value || 0), 0)
          const lines = visible.map(
            (row) => `${row.marker || ''}${row.seriesName}　${formatMoney(row.value)}`,
          )
          const perPair = formatDeptPerPair(total)
          return [`${rows[0]?.axisValue || ''}`, ...lines, `合计　${formatMoney(total)}`, perPair].join('<br/>')
        },
      },
      legend: {
        type: 'scroll',
        top: 0,
        icon: 'roundRect',
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#64748b', fontSize: 12 },
      },
      grid: { left: 12, right: 16, top: 40, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: depts.map((dept) => dept.department_name),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#334155', fontSize: 12 },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8',
          fontSize: 11,
          formatter: (value: number) =>
            Math.abs(value) >= 10000 ? `${Number((value / 10000).toFixed(1))}万` : String(value),
        },
        splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
      },
      series: categories.map((cat) => ({
        name: cat.label,
        type: 'bar',
        stack: 'cost',
        barMaxWidth: 42,
        emphasis: { focus: 'series' },
        data: depts.map((dept) => Number(costSummary.value[cellKey(dept.department_id, cat.key)] || 0)),
      })),
    },
    true,
  )
}

function resizeCostChart() {
  costChart?.resize()
}

const dateRange = ref<[string, string] | null>(null)
const filters = ref({
  order_no: '',
  customer_name: '',
  factory_model: '',
  brand: '',
})
const lossOnly = ref(false)
const orders = ref<any[]>([])
const summary = ref<any>({})
const ordersLoading = ref(false)
let orderSearchTimer: ReturnType<typeof setTimeout> | null = null

const comprehensiveProfit = computed(() => {
  const s = summary.value || {}
  const profit = Number(s.profit || 0)
  const allocated = Number(s.allocated_cost || 0)
  const loss = Number(s.loss_amount || 0)
  return profit - allocated - loss
})

const costMonthVal = ref<string | null>(null)
const costDateRange = ref<[string, string] | null>(null)
const costHeaders = ref<
  { department_id: number; department_name: string; children: CostColumn[] }[]
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
const rentCost = ref<CostKpi>(null)
const utilityCost = ref<CostKpi>(null)
const fixedSalaryCost = ref<CostKpi>(null)
const auxMaterialCost = ref<CostKpi>(null)
const devCost = ref<CostKpi>(null)
const allocatedCost = ref<CostKpi>(null)

const costKpiItems = computed(() => [
  { label: '房租成本', tip: '期间房租总额 ÷ 期间出货双数', info: rentCost.value },
  { label: '水电成本', tip: '期间水电总额 ÷ 期间出货双数', info: utilityCost.value },
  { label: '开发成本', tip: '开发部固定工资、报销、仓库领料、对账后的底模、鞋跟模具、楦头、其它模具与复版收费。复版收费是进账，记负数', info: devCost.value },
  { label: '固定工资分摊', tip: '期间固定工资总额 ÷ 期间出货双数', info: fixedSalaryCost.value },
  { label: '辅料耗材分摊', tip: '期间生产领退辅料耗材总额 ÷ 期间出货双数。退料冲减', info: auxMaterialCost.value },
  { label: '综合分摊', tip: '计件/提成/鞋用主料/大货模具以外的所有开支成本分摊', info: allocatedCost.value },
])

function costHeaderSig(cols: CostColumn[]): string {
  return cols
    .map((col) => (col.children?.length ? `${col.key}(${costHeaderSig(col.children)})` : col.key))
    .join(',')
}

const costTableRenderKey = computed(
  () =>
    costHeaders.value
      .map((h) => `${h.department_id}:${costHeaderSig(h.children || [])}`)
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
  const rows = ((data?.rows || []) as { date: string; values?: Record<string, number> }[])
    .map((r) => {
      const flat: Record<string, any> = { date: r.date }
      for (const [k, v] of Object.entries(r.values || {})) {
        flat[normalizeCellKey(k)] = v
      }
      return flat
    })
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
  return {
    headers,
    rows,
    summary,
    rentCost: data?.rent_cost || null,
    utilityCost: data?.utility_cost || null,
    fixedSalaryCost: data?.fixed_salary_cost || null,
    auxMaterialCost: data?.aux_material_cost || null,
    devCost: data?.dev_cost || null,
    allocatedCost: data?.allocated_cost || null,
  }
}

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

function formatCostKpiBody(info: CostKpi) {
  if (!info) return '=¥— ÷ — 双='
  const expense = formatMoney(info.total_expense)
  const qty = Number(info.shipped_qty || 0).toLocaleString('zh-CN')
  return `=¥${expense} ÷ ${qty} 双=`
}

function formatCostKpiResult(info: CostKpi) {
  if (!info) return '¥—/双'
  const qty = Number(info.shipped_qty || 0)
  if (info.unit_cost === null || info.unit_cost === undefined || qty <= 0) return '¥—/双'
  return `¥${formatMoney(info.unit_cost)}/双`
}

/** 部门柱合计 ÷ 期间出货双数，四舍五入到分。 */
function formatDeptPerPair(total: number) {
  const qty = Number(allocatedCost.value?.shipped_qty || 0)
  const unit = qty > 0 ? Math.round((total / qty) * 100) / 100 : null
  const info: CostKpi = { total_expense: total, shipped_qty: qty, unit_cost: unit }
  return `部门成本　${formatCostKpiBody(info)} ${formatCostKpiResult(info)}`
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
    if (key === 'total_qty') return String(s.total_qty ?? 0)
    if (key === 'shipped_qty') return String(s.shipped_qty ?? 0)
    if (key === 'total_price' || key === 'revenue') return formatMoney(s.revenue)
    if (key === 'material_cost') return formatMoney(s.material_cost)
    if (key === 'mold_last') return formatMoney(s.mold_last)
    if (key === 'mold_sole') return formatMoney(s.mold_sole)
    if (key === 'mold_heel') return formatMoney(s.mold_heel)
    if (key === 'mold_knife') return formatMoney(s.mold_knife)
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
    order_no: filters.value.order_no.trim() || undefined,
    customer_name: filters.value.customer_name.trim() || undefined,
    factory_model: filters.value.factory_model.trim() || undefined,
    brand: filters.value.brand.trim() || undefined,
    loss_only: lossOnly.value || undefined,
  }
  if (dateRange.value?.length === 2) {
    params.date_from = dateRange.value[0]
    params.date_to = dateRange.value[1]
  }
  return params
}

function buildCostParams() {
  const params: Record<string, any> = {}
  if (costDateRange.value?.length === 2) {
    params.date_from = costDateRange.value[0]
    params.date_to = costDateRange.value[1]
  } else if (costYm.value.year) {
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
    rentCost.value = flat.rentCost
    utilityCost.value = flat.utilityCost
    fixedSalaryCost.value = flat.fixedSalaryCost
    auxMaterialCost.value = flat.auxMaterialCost
    devCost.value = flat.devCost
    allocatedCost.value = flat.allocatedCost
    costLoaded.value = true
  } finally {
    costLoading.value = false
  }
  // remount 后需再测宽，铺满容器
  void nextTick(() => {
    void nextTick(() => {
      renderCostChart()
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
  if (orderSearchTimer) {
    clearTimeout(orderSearchTimer)
    orderSearchTimer = null
  }
  void loadOrders()
}

function scheduleOrderSearch() {
  if (orderSearchTimer) clearTimeout(orderSearchTimer)
  orderSearchTimer = setTimeout(searchOrders, 350)
}

function onOrderDateRangeChange() {
  searchOrders()
}

function onCostDateRangeChange() {
  void loadCost()
}

function pickTab(): ProfitTab {
  const q = String(route.query.tab || '')
  return q === 'cost' ? 'cost' : 'orders'
}

function pickCostSection(): 'summary' | 'mold' {
  return String(route.query.section || '') === 'mold' ? 'mold' : 'summary'
}

function onCostSectionChange(name: string | number) {
  const section = name === 'mold' ? 'mold' : 'summary'
  costSection.value = section
  if (route.path !== '/admin/profit') return
  const query = { ...route.query, tab: 'cost' }
  if (section === 'mold') query.section = 'mold'
  else delete query.section
  if (String(route.query.section || '') === String(query.section || '') && String(route.query.tab || '') === 'cost') {
    relayoutAfterSection(section)
    return
  }
  router.replace({ path: '/admin/profit', query })
}

function relayoutAfterSection(section: 'summary' | 'mold') {
  void nextTick(() => {
    if (section === 'summary') {
      renderCostChart()
      resizeCostChart()
      measureCostTableHeight()
      relayoutCostTable()
    }
  })
}

function syncTabQuery(tab: ProfitTab) {
  if (route.path !== '/admin/profit') return
  if (String(route.query.tab || '') === tab) return
  router.replace({ path: '/admin/profit', query: { ...route.query, tab } })
}

watch(
  () => [route.query.tab, route.query.section],
  () => {
    const next = pickTab()
    const section = pickCostSection()
    const tabChanged = next !== activeTab.value
    const sectionChanged = section !== costSection.value
    if (!tabChanged && !sectionChanged) return
    activeTab.value = next
    costSection.value = section
    if (next === 'cost' && !costLoaded.value) void loadCost()
    void nextTick(() => {
      if (next === 'cost' && section === 'summary') {
        renderCostChart()
        resizeCostChart()
        measureCostTableHeight()
        relayoutCostTable()
      } else if (next !== 'cost') {
        measureTableHeight()
        relayoutTable()
      }
    })
  },
)

onMounted(async () => {
  activeTab.value = pickTab()
  costSection.value = pickCostSection()
  syncTabQuery(activeTab.value)
  if (activeTab.value === 'cost') {
    await loadCost()
  } else {
    await loadOrders()
  }
  measureTableHeight()
  measureCostTableHeight()
  window.addEventListener('resize', resizeCostChart)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeCostChart)
  costChart?.dispose()
  costChart = null
})
</script>

<style scoped>
.profit-neg {
  color: #dc2626;
  font-weight: 600;
}
.profit-table :deep(.el-table__header th.is-group) {
  text-align: center;
}
.cost-in {
  color: #059669;
}
.view-hint {
  margin: 8px 0 0;
  font-size: 12px;
}
.cost-toolbar :deep(.el-date-editor) {
  flex: none;
}
.cost-toolbar :deep(.el-date-editor--month) {
  --el-date-editor-width: 148px;
  width: 148px;
}
.cost-toolbar :deep(.el-date-editor--daterange) {
  --el-date-editor-width: 220px;
  width: 220px;
}
.cost-chart-row {
  display: flex;
  align-items: stretch;
  gap: 12px;
  margin: 0 0 12px;
}
.cost-chart {
  flex: 1 1 auto;
  min-width: 0;
  height: 300px;
  background: #fff;
  border-radius: 12px;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}
.cost-kpi-side {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
  min-width: 280px;
  padding: 16px 18px;
  background: #fff;
  border-radius: 12px;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}
.cost-analysis-table :deep(.el-table__header th) {
  text-align: center;
}
.cost-empty {
  padding: 24px 8px;
  font-size: 13px;
}
.dev-cost-kpi {
  display: inline-flex;
  align-items: center;
  padding: 0;
  font-size: 13px;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}
.cost-kpi-label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.kpi-tip {
  font-size: 14px;
  color: #909399;
  cursor: help;
  vertical-align: middle;
}
.kpi-tip:hover {
  color: var(--el-color-primary);
}
.cost-kpi-result {
  margin-left: 2px;
  font-size: 16px;
  font-weight: 700;
  color: var(--el-color-primary);
  line-height: 1.2;
}
.cost-kpi-result.profit-neg {
  color: #dc2626;
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
