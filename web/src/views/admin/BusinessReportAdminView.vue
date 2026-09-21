<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">经营报告</h1>
        <p class="page-desc">
          按日期范围汇总出货、利润、报废与开发成本 · 综合利润 = 利润 − 综合分摊 − 生产损失 − 售后损失
        </p>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始"
          end-placeholder="结束"
          unlink-panels
          :clearable="false"
          style="width: 260px"
          @change="load"
        />
        <el-button @click="load">刷新</el-button>
      </div>

      <div v-loading="loading" class="report-kpi-grid">
        <div class="report-kpi">
          <div class="report-kpi-label">出货量</div>
          <div class="report-kpi-value">{{ formatQty(report.shipped_qty) }}</div>
          <div class="report-kpi-hint">已确认出货双数</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">
            综合利润
            <el-tooltip :content="comprehensiveHint" placement="top">
              <el-icon class="kpi-tip"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <div
            class="report-kpi-value"
            :class="{ 'is-neg': Number(report.comprehensive_profit || 0) < 0 }"
          >
            ¥{{ formatMoney(report.comprehensive_profit) }}
          </div>
          <div class="report-kpi-hint">{{ comprehensiveHint }}</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">
            报废率
            <el-tooltip content="报废双数 ÷ (出货双数 + 报废双数)" placement="top">
              <el-icon class="kpi-tip"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <div class="report-kpi-value">{{ formatRate(report.scrap_rate) }}</div>
          <div class="report-kpi-hint">{{ scrapHint }}</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">生产损失（公司承担）</div>
          <div class="report-kpi-value">¥{{ formatMoney(report.production_loss) }}</div>
          <div class="report-kpi-hint">报废记录按公司承担比例汇总</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">售后损失（公司承担）</div>
          <div class="report-kpi-value">¥{{ formatMoney(report.after_sales_loss) }}</div>
          <div class="report-kpi-hint">退款 + 修复 + 重做成本</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">开发支出</div>
          <div class="report-kpi-value">¥{{ formatMoney(report.dev_expense) }}</div>
          <div class="report-kpi-hint">开发部期间全部费用</div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">
            开发成本
            <el-tooltip content="开发支出 ÷ 期间出货双数" placement="top">
              <el-icon class="kpi-tip"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <div class="report-kpi-value">{{ formatUnitCost(report.dev_unit_cost) }}</div>
          <div class="report-kpi-hint">
            ¥{{ formatMoney(report.dev_expense) }} ÷ {{ formatQty(report.shipped_qty) }} 双
          </div>
        </div>

        <div class="report-kpi">
          <div class="report-kpi-label">
            综合分摊
            <el-tooltip content="期间全部费用（不含计件、提成）÷ 期间出货双数" placement="top">
              <el-icon class="kpi-tip"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <div class="report-kpi-value">{{ formatUnitCost(report.allocated_unit_cost) }}</div>
          <div class="report-kpi-hint">
            ¥{{ formatMoney(report.allocated_total) }} ÷ {{ formatQty(report.shipped_qty) }} 双
          </div>
        </div>
      </div>

      <div class="report-loss-head">
        <h2 class="report-loss-title">亏损订单</h2>
        <span class="report-loss-hint">期间出货且利润为负 · 利润 = 总价 − 物料 − 计件 − 提成</span>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="lossOrders"
          stripe
          border
          style="width: 100%"
          show-summary
          :summary-method="getLossSummaries"
          :max-height="tableMaxHeight"
          v-loading="loading"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="order_no"
            label="亏损订单号"
            :width="colWidth('order_no', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.order_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="customer_name"
            label="关联客户"
            :width="colWidth('customer_name', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.customer_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="brand_name"
            label="关联品牌"
            :width="colWidth('brand_name', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.brand_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="factory_model"
            label="工厂型号"
            :width="colWidth('factory_model', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.factory_model || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="loss_amount"
            label="亏损金额"
            :width="colWidth('loss_amount', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span class="loss-amount">¥{{ formatMoney(row.loss_amount) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="report-now-block">
        <div class="report-loss-head">
          <h2 class="report-loss-title">当前</h2>
          <span class="report-loss-hint">按此刻统计，不受上方日期影响</span>
        </div>
        <div v-loading="loading" class="report-kpi-grid report-kpi-grid-now">
        <div class="report-kpi">
          <div class="report-kpi-label">现有员工</div>
          <div class="report-kpi-value">{{ formatQty(snapshot.employee_count) }} 名</div>
          <div class="report-kpi-hint">当前在职</div>
        </div>
        <div class="report-kpi">
          <div class="report-kpi-label">迟到早退</div>
          <div class="report-kpi-value">{{ formatQty(snapshot.late_early_times) }} 人次</div>
          <div class="report-kpi-hint">
            共计 {{ formatQty(snapshot.late_early_minutes) }} 分钟 · 今日
          </div>
        </div>
        <div class="report-kpi">
          <div class="report-kpi-label">现有未出货</div>
          <div class="report-kpi-value">{{ formatQty(snapshot.unshipped_qty) }} 双</div>
          <div class="report-kpi-hint">已确认尚未出完</div>
        </div>
        <div class="report-kpi">
          <div class="report-kpi-label">
            预计利润
            <el-tooltip content="未出货双数 ×（单价 − 物料 − 计件 − 提成）" placement="top">
              <el-icon class="kpi-tip"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <div
            class="report-kpi-value"
            :class="{ 'is-neg': Number(snapshot.projected_profit || 0) < 0 }"
          >
            ¥{{ formatMoney(snapshot.projected_profit) }}
          </div>
          <div class="report-kpi-hint">按未出货 {{ formatQty(snapshot.unshipped_qty) }} 双估算</div>
        </div>
        <div class="report-kpi">
          <div class="report-kpi-label">逾期双数</div>
          <div class="report-kpi-value">{{ formatQty(snapshot.overdue_qty) }} 双</div>
          <div class="report-kpi-hint">交期已过尚未出完</div>
        </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type LossOrder = {
  order_no?: string | null
  customer_name?: string | null
  brand_name?: string | null
  factory_model?: string | null
  loss_amount?: number
}

type Snapshot = {
  as_of?: string | null
  employee_count?: number
  late_early_times?: number
  late_early_minutes?: number
  unshipped_qty?: number
  projected_profit?: number
  overdue_qty?: number
}

type Report = {
  shipped_qty?: number
  profit?: number
  comprehensive_profit?: number
  scrap_qty?: number
  scrap_rate?: number | null
  production_loss?: number
  after_sales_loss?: number
  dev_expense?: number
  dev_unit_cost?: number | null
  allocated_total?: number
  allocated_unit_cost?: number | null
  loss_orders?: LossOrder[]
  snapshot?: Snapshot
}

function localYmd(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function currentMonthRange(): [string, string] {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return [localYmd(start), localYmd(end)]
}

const dateRange = ref<[string, string]>(currentMonthRange())
const loading = ref(false)
const report = ref<Report>({})
const lossOrders = computed(() => report.value.loss_orders || [])
const snapshot = computed(() => report.value.snapshot || {})

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'business-report-loss-orders',
  tableRef,
  {
    flexKey: 'customer_name',
    flexDefaultMin: 140,
    fitToContainer: true,
  },
)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight({
  minHeight: 200,
  reserveSelectors: ['.admin-pagination', '.view-hint', '.report-now-block'],
})

const comprehensiveHint = computed(() => {
  const r = report.value || {}
  return `¥${formatMoney(r.profit)} − ¥${formatMoney(r.allocated_total)} − ¥${formatMoney(r.production_loss)} − ¥${formatMoney(r.after_sales_loss)}`
})

const scrapHint = computed(() => {
  const r = report.value || {}
  const scrap = Number(r.scrap_qty || 0)
  const shipped = Number(r.shipped_qty || 0)
  if (shipped <= 0) {
    return scrap ? `本期无出货，报废 ${formatQty(scrap)} 双` : '报废双数 ÷ (出货双数 + 报废双数)'
  }
  return `${formatQty(scrap)} 报废 / ${formatQty(shipped + scrap)} 双`
})

function formatMoney(v: unknown) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatQty(v: unknown) {
  const n = Number(v || 0)
  if (Number.isNaN(n)) return '0'
  return n.toLocaleString('zh-CN')
}

function formatRate(v: unknown) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function formatUnitCost(v: unknown) {
  if (v === null || v === undefined || v === '') return '¥—/双'
  const n = Number(v)
  if (Number.isNaN(n)) return '¥—/双'
  return `¥${formatMoney(n)}/双`
}

function getLossSummaries({ columns }: { columns: any[] }) {
  const rows = lossOrders.value
  const total = rows.reduce((sum, row) => sum + Number(row.loss_amount || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 0) return rows.length ? `合计 ${rows.length} 单` : '暂无亏损订单'
    const key = col.property || col.columnKey
    if (key === 'loss_amount') return rows.length ? `¥${formatMoney(total)}` : ''
    return ''
  })
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (dateRange.value?.length === 2) {
      params.date_from = dateRange.value[0]
      params.date_to = dateRange.value[1]
    }
    const res: any = await http.get('/business-report', { params, timeout: 60000 })
    report.value = res.data || {}
  } catch {
    report.value = {}
  } finally {
    loading.value = false
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.report-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.report-kpi {
  min-width: 0;
  padding: 16px 18px;
  background: #fff;
  border-radius: 12px;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}
.report-kpi-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #64748b;
}
.report-kpi-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 720;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}
.report-kpi-value.is-neg {
  color: #dc2626;
}
.report-kpi-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.4;
  word-break: break-all;
}
.kpi-tip {
  font-size: 14px;
  color: #909399;
  cursor: help;
}
.kpi-tip:hover {
  color: var(--el-color-primary);
}
.report-kpi-grid-now {
  margin-top: 4px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}
.report-now-block {
  padding-top: 40px;
}
.report-now-block .report-loss-head {
  margin-top: 0;
}
@media (max-width: 1100px) {
  .report-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .report-kpi-grid-now {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .report-kpi-grid {
    grid-template-columns: 1fr;
  }
}
.report-loss-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin: 20px 0 12px;
}
.report-loss-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.report-loss-hint {
  font-size: 12px;
  color: #94a3b8;
  min-width: 0;
  line-height: 1.4;
}
.loss-amount {
  color: #dc2626;
  font-variant-numeric: tabular-nums;
}
</style>
