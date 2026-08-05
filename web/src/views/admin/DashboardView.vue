<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">进度看板</h1>
        <p class="page-desc">产量 · 交期 · 瓶颈</p>
      </div>
      <div class="page-hero-actions">
        <el-button type="primary" @click="openBoard">投屏</el-button>
      </div>
    </header>
    <div class="admin-card" style="margin-bottom: 16px">
      <div class="admin-toolbar" style="align-items: center; gap: 24px; flex-wrap: wrap">
        <el-statistic title="今日合格" :value="board?.summary?.today_qualified ?? 0" />
        <el-statistic title="今日不良" :value="board?.summary?.today_defect ?? 0" />
        <el-statistic title="在制订单" :value="board?.summary?.open_orders ?? 0" />
        <el-statistic title="急单" :value="board?.summary?.rush_orders ?? 0" />
        <el-statistic title="交期风险" :value="board?.summary?.at_risk_orders ?? 0" />
        <div class="spacer" />
        <el-button @click="load" :loading="loading">刷新</el-button>
        <el-button type="primary" @click="$router.push('/admin/orders')">去订单</el-button>
      </div>
      <p v-if="board?.message" class="muted" style="margin: 8px 0 0">{{ board.message }}</p>
    </div>
    <div class="admin-card" style="margin-bottom: 16px">
      <div style="font-weight: 600; margin-bottom: 8px">本月经营</div>
      <div class="admin-toolbar" style="align-items: center; gap: 24px; flex-wrap: wrap">
        <el-statistic title="本月出货额" :value="Number(kpi?.shipment_amount || 0)" />
        <el-statistic title="本月回款额" :value="Number(kpi?.payment_amount || 0)" />
        <el-statistic title="本月毛利(估)" :value="Number(kpi?.gross_profit || 0)" />
        <el-statistic title="客户欠款" :value="Number(kpi?.customer_ar_balance || 0)" />
      </div>
    </div>

    <div class="chart-grid" style="margin-bottom: 16px">
      <div class="admin-card">
        <div style="font-weight: 600; margin-bottom: 8px">近 14 日产量趋势</div>
        <div ref="trendEl" class="chart-box" />
      </div>
      <div class="admin-card">
        <div style="font-weight: 600; margin-bottom: 8px">近 7 日工序产量</div>
        <div ref="processEl" class="chart-box" />
      </div>
      <div class="admin-card">
        <div style="font-weight: 600; margin-bottom: 8px">交期风险分布</div>
        <div ref="riskEl" class="chart-box" />
      </div>
    </div>

    <div class="board-grid">
      <div class="admin-card">
        <div style="font-weight: 600; margin-bottom: 12px">在制订单</div>
        <el-table :data="board?.orders || []" stripe border size="small" empty-text="暂无在制订单">
          <el-table-column prop="order_no" label="订单" width="130">
            <template #default="{ row }">
              {{ row.order_no }}
              <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 4px">插单</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="customer_name" label="客户" width="100" />
          <el-table-column prop="product_code" label="产品" width="120" />
          <el-table-column label="交期" width="110">
            <template #default="{ row }">
              <span :style="row.at_risk ? 'color:#c45656;font-weight:600' : ''">
                {{ row.delivery_date || '—' }}
              </span>
              <el-tag v-if="row.at_risk" size="small" type="danger" style="margin-left: 4px">风险</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="总进度" width="140">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.min(100, Number(row.overall_percent) || 0)"
                :stroke-width="12"
                :status="row.overall_percent >= 100 ? 'success' : undefined"
              />
            </template>
          </el-table-column>
          <el-table-column label="瓶颈工序" min-width="160">
            <template #default="{ row }">
              <template v-if="row.bottleneck">
                {{ row.bottleneck.process_name }}
                · 剩 {{ row.bottleneck.remain_qty }}
                （{{ row.bottleneck.percent }}%）
              </template>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="各工序" min-width="220">
            <template #default="{ row }">
              <div v-for="p in row.processes" :key="p.process_name" class="muted" style="line-height: 1.5">
                {{ p.process_name }} {{ p.completed_qty }}/{{ p.plan_qty }}
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div>
        <div class="admin-card" style="margin-bottom: 16px">
          <div style="font-weight: 600; margin-bottom: 12px">工序瓶颈</div>
          <el-table :data="board?.bottlenecks || []" stripe border size="small" empty-text="暂无瓶颈">
            <el-table-column prop="process_name" label="工序" />
            <el-table-column prop="order_count" label="卡住单数" width="90" />
            <el-table-column prop="remain_qty" label="剩余量" width="80" />
          </el-table>
          <p class="muted" style="margin: 8px 0 0">按「在制单中进度最低的未完成工序」汇总</p>
        </div>

        <div class="admin-card">
          <div style="font-weight: 600; margin-bottom: 12px">今日分工序</div>
          <el-table :data="board?.today?.by_process || []" stripe border size="small" empty-text="今日暂无报工">
            <el-table-column prop="process_name" label="工序" />
            <el-table-column prop="qualified_qty" label="合格" width="80" />
            <el-table-column prop="defect_qty" label="不良" width="80" />
          </el-table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import http from '@/api/http'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const board = ref<any>(null)
const kpi = ref<any>(null)
const loading = ref(false)
const trendEl = ref<HTMLElement | null>(null)
const processEl = ref<HTMLElement | null>(null)
const riskEl = ref<HTMLElement | null>(null)

let trendChart: echarts.ECharts | null = null
let processChart: echarts.ECharts | null = null
let riskChart: echarts.ECharts | null = null

const COLORS = {
  qualified: '#2f6f5e',
  defect: '#c45c26',
  process: '#3d5a80',
  risk: ['#b91c1c', '#c45c26', '#ca8a04', '#2f6f5e', '#64748b'],
}

function renderCharts() {
  const charts = board.value?.charts
  if (!charts) return

  if (trendEl.value) {
    trendChart = trendChart || echarts.init(trendEl.value)
    const dates = (charts.trend || []).map((d: any) => String(d.date).slice(5))
    trendChart.setOption({
      color: [COLORS.qualified, COLORS.defect],
      tooltip: { trigger: 'axis' },
      legend: { data: ['合格', '不良'], bottom: 0 },
      grid: { left: 40, right: 16, top: 24, bottom: 40 },
      xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          name: '合格',
          type: 'line',
          smooth: true,
          data: (charts.trend || []).map((d: any) => d.qualified),
        },
        {
          name: '不良',
          type: 'line',
          smooth: true,
          data: (charts.trend || []).map((d: any) => d.defect),
        },
      ],
    })
  }

  if (processEl.value) {
    processChart = processChart || echarts.init(processEl.value)
    const rows = charts.process_bars || []
    processChart.setOption({
      color: [COLORS.process],
      tooltip: { trigger: 'axis' },
      grid: { left: 48, right: 16, top: 24, bottom: 28 },
      xAxis: {
        type: 'category',
        data: rows.map((r: any) => r.process_name),
        axisLabel: { fontSize: 11 },
      },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          name: '合格',
          type: 'bar',
          barMaxWidth: 36,
          data: rows.map((r: any) => r.qualified_qty),
        },
      ],
    })
  }

  if (riskEl.value) {
    riskChart = riskChart || echarts.init(riskEl.value)
    const rows = charts.delivery_risk || []
    riskChart.setOption({
      color: COLORS.risk,
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, type: 'scroll' },
      series: [
        {
          name: '交期',
          type: 'pie',
          radius: ['38%', '62%'],
          center: ['50%', '46%'],
          data: rows.map((r: any) => ({ name: r.label, value: r.count })),
          label: { formatter: '{b}\n{c}' },
        },
      ],
    })
  }
}

function onResize() {
  trendChart?.resize()
  processChart?.resize()
  riskChart?.resize()
}

function openBoard() {
  window.open('/board', '_blank')
}

async function load() {
  loading.value = true
  try {
    const [res, k]: any[] = await Promise.all([
      http.get('/progress/board'),
      http.get('/business-kpi'),
    ])
    board.value = res.data
    kpi.value = k.data
    await nextTick()
    renderCharts()
  } finally {
    loading.value = false
  }
}

watch(
  () => board.value?.charts,
  async () => {
    await nextTick()
    renderCharts()
  },
)

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  processChart?.dispose()
  riskChart?.dispose()
})
</script>

<style scoped>
.chart-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.chart-box {
  height: 240px;
  width: 100%;
}
.board-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
}
@media (max-width: 1200px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
  .board-grid {
    grid-template-columns: 1fr;
  }
}
</style>
