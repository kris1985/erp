<template>
  <div class="wb">
    <header class="wb-hero">
      <div class="wb-hero-copy">
        <p class="wb-kicker">{{ todayLabel }}</p>
        <h1 class="wb-title">工作台</h1>
      </div>
      <div class="wb-hero-actions">
        <button type="button" class="wb-btn" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button v-if="canSchedule" type="button" class="wb-btn" @click="$router.push('/admin/schedule')">
          排产
        </button>
        <button v-if="canPurchase" type="button" class="wb-btn" @click="$router.push('/admin/purchase')">
          采购
        </button>
        <button
          v-if="canSchedule"
          type="button"
          class="wb-btn wb-btn-accent"
          @click="$router.push({ path: '/admin/schedule-assistant', query: { ask: 'today' } })"
        >
          AI分析
        </button>
        <button type="button" class="wb-btn wb-btn-primary" @click="openBoard">投屏</button>
      </div>
    </header>

    <!-- A2b：质量预警浅层（款×工序不良率突增 chip） -->
    <section v-if="canQualityAlerts && (qualityAlerts.length || qualityAlertsLoading)" class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">质量预警</h2>
        <span class="wb-section-hint">{{ qualityAlertsSummary || '款×工序不良率突增，悬停看抽检建议' }}</span>
      </div>
      <div v-if="qualityAlertsLoading" class="wb-today-skel">加载质量预警…</div>
      <div v-else class="wb-quality-chips">
        <el-tooltip
          v-for="(a, idx) in qualityAlerts"
          :key="idx"
          :content="a.suggestion"
          placement="top"
          effect="dark"
        >
          <button
            type="button"
            class="wb-quality-chip"
            :class="'sev-' + (a.severity || 'medium')"
            @click="$router.push('/admin/defects')"
          >
            {{ a.chip_label }}
          </button>
        </el-tooltip>
      </div>
    </section>

    <!-- 今日关注 -->
    <section class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">今日关注</h2>
        <span class="wb-section-hint">点击跳转到对应处理区</span>
      </div>
      <div class="wb-attention">
        <button
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.risk, 'danger')"
          @click="$router.push('/admin/executions')"
        >
          <span class="wb-tile-label">交期风险</span>
          <span class="wb-tile-value">{{ alerts.risk }}</span>
          <span class="wb-tile-foot">可能延误交付</span>
        </button>
        <button
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.dueToday, 'warn')"
          @click="$router.push('/admin/executions')"
        >
          <span class="wb-tile-label">今日交期</span>
          <span class="wb-tile-value">{{ alerts.dueToday }}</span>
          <span class="wb-tile-foot">当天必须闭环</span>
        </button>
        <button
          v-if="canShortage"
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.shortage, 'warn')"
          @click="$router.push({ path: '/admin/purchase', query: { tab: 'buy' } })"
        >
          <span class="wb-tile-label">待买</span>
          <span class="wb-tile-value">{{ alerts.shortage }}</span>
          <span class="wb-tile-foot">接单后还没买</span>
        </button>
        <button
          v-if="canPurchase"
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.poOverdue, 'danger')"
          @click="$router.push({ path: '/admin/purchase', query: { tab: 'orders' } })"
        >
          <span class="wb-tile-label">采购逾期</span>
          <span class="wb-tile-value">{{ alerts.poOverdue }}</span>
          <span class="wb-tile-foot">在途未到货</span>
        </button>
      </div>
    </section>

    <!-- 概览：今日产量 -->
    <section class="wb-overview">
      <div class="wb-card wb-overview-prod">
        <div class="wb-card-head">
          <h3 class="wb-card-title">今日产量</h3>
          <span class="wb-chip">在制 {{ board?.summary?.open_orders ?? 0 }} 单</span>
        </div>
        <div class="wb-metric-row">
          <div class="wb-metric">
            <div class="wb-metric-label">合格</div>
            <div class="wb-metric-value is-ok">{{ board?.summary?.today_qualified ?? 0 }}</div>
          </div>
          <div class="wb-metric">
            <div class="wb-metric-label">不良</div>
            <div class="wb-metric-value is-bad">{{ board?.summary?.today_defect ?? 0 }}</div>
          </div>
          <div class="wb-metric">
            <div class="wb-metric-label">不良率</div>
            <div class="wb-metric-value">{{ defectRate }}</div>
          </div>
        </div>
      </div>

    </section>

    <!-- 处理区 -->
    <section v-if="canShortage" class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">马上处理</h2>
      </div>
      <div class="wb-mid">
        <div class="wb-card wb-panel">
          <div class="wb-card-head">
            <h3 class="wb-card-title">待买 Top</h3>
            <button type="button" class="wb-link" @click="$router.push({ path: '/admin/purchase', query: { tab: 'buy' } })">去买料</button>
          </div>
          <div class="table-scroll">
            <el-table :data="shortagePreview" stripe border size="small" empty-text="没有要买的料">
              <el-table-column prop="order_no" label="销售单" min-width="96" show-overflow-tooltip />
              <el-table-column label="物料" min-width="110" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.supplier_product_name || row.material_name || row.sku_name || '—' }}
                </template>
              </el-table-column>
              <el-table-column label="待采" width="72" align="right">
                <template #default="{ row }">
                  {{ row.to_buy_qty ?? row.shortage_qty ?? '—' }}
                </template>
              </el-table-column>
              <el-table-column label="" width="48">
                <template #default="{ row }">
                  <span v-if="row.is_rush" class="wb-pill wb-pill-danger">急</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <p v-if="alerts.shortage > shortagePreview.length" class="wb-more">
            共 {{ alerts.shortage }} 行，仅展示前 {{ shortagePreview.length }} 行
          </p>
        </div>

      </div>
    </section>

    <section class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">趋势</h2>
      </div>
      <div class="chart-grid">
        <div class="wb-card">
          <h3 class="wb-card-title">近 14 日产量</h3>
          <div ref="trendEl" class="chart-box" />
        </div>
        <div class="wb-card">
          <h3 class="wb-card-title">近 14 日各段产量</h3>
          <div ref="processEl" class="chart-box" />
        </div>
        <div class="wb-card">
          <h3 class="wb-card-title">交期风险构成</h3>
          <div ref="riskEl" class="chart-box" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const canSchedule = computed(() => auth.hasPermission('menu.schedule'))
const canQualityAlerts = computed(() => auth.hasPermission('menu.work_logs'))
const canShortage = computed(
  () => auth.hasPermission('menu.material_shortages') || auth.hasPermission('menu.purchase_orders'),
)
const canPurchase = computed(() => auth.hasPermission('menu.purchase_orders'))

const board = ref<any>(null)
const shortages = ref<any[]>([])
const loading = ref(false)
const qualityAlerts = ref<any[]>([])
const qualityAlertsSummary = ref('')
const qualityAlertsLoading = ref(false)
const trendEl = ref<HTMLElement | null>(null)
const processEl = ref<HTMLElement | null>(null)
const riskEl = ref<HTMLElement | null>(null)

const alerts = reactive({
  risk: 0,
  dueToday: 0,
  shortage: 0,
  poOverdue: 0,
})

let trendChart: echarts.ECharts | null = null
let processChart: echarts.ECharts | null = null
let riskChart: echarts.ECharts | null = null

const COLORS = {
  qualified: '#0d9488',
  defect: '#ea580c',
  risk: ['#dc2626', '#ea580c', '#ca8a04', '#0d9488', '#64748b'],
}

const todayLabel = computed(() => {
  const d = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 · 周${week}`
})

const defectRate = computed(() => {
  const q = Number(board.value?.summary?.today_qualified || 0)
  const bad = Number(board.value?.summary?.today_defect || 0)
  const total = q + bad
  if (!total) return '—'
  return `${((bad / total) * 100).toFixed(1)}%`
})

const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function toneClass(n: number, tone: 'warn' | 'danger') {
  if (!n) return ''
  return tone === 'danger' ? 'is-danger' : 'is-warn'
}

async function loadQualityAlerts() {
  if (!canQualityAlerts.value) {
    qualityAlerts.value = []
    qualityAlertsSummary.value = ''
    return
  }
  qualityAlertsLoading.value = true
  try {
    const res: any = await http.post(
      '/schedule/agent/metrics/query',
      { metric_id: 'analytics.quality_alerts', params: {} },
      { silent: true } as any,
    )
    const payload = res?.data
    if (payload?.error) {
      qualityAlerts.value = []
      return
    }
    const analysis = payload?.data?.analysis_id ? payload.data : payload
    const inner = analysis?.data || {}
    qualityAlerts.value = Array.isArray(inner.alerts) ? inner.alerts.slice(0, 5) : []
    qualityAlertsSummary.value = String(analysis?.summary || '')
  } catch {
    qualityAlerts.value = []
  } finally {
    qualityAlertsLoading.value = false
  }
}

const shortagePreview = computed(() => {
  const rows = [...shortages.value]
  rows.sort((a, b) => {
    const rush = Number(!!b.is_rush) - Number(!!a.is_rush)
    if (rush) return rush
    return Number(b.to_buy_qty ?? b.shortage_qty ?? 0) - Number(a.to_buy_qty ?? a.shortage_qty ?? 0)
  })
  return rows.slice(0, 8)
})

function renderCharts() {
  const charts = board.value?.charts
  if (!charts) return

  if (trendEl.value) {
    trendChart = trendChart || echarts.init(trendEl.value)
    const dates = (charts.trend || []).map((d: any) => String(d.date).slice(5))
    trendChart.setOption({
      color: [COLORS.qualified, COLORS.defect],
      tooltip: { trigger: 'axis' },
      legend: { data: ['合格', '不良'], bottom: 0, icon: 'circle', itemWidth: 8 },
      grid: { left: 36, right: 12, top: 16, bottom: 36, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      series: [
        {
          name: '合格',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          areaStyle: { color: 'rgba(13,148,136,0.12)' },
          data: (charts.trend || []).map((d: any) => d.qualified),
        },
        {
          name: '不良',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: (charts.trend || []).map((d: any) => d.defect),
        },
      ],
    })
  }

  if (processEl.value) {
    processChart = processChart || echarts.init(processEl.value)
    const segmentDaily = charts.segment_daily || {}
    const dates = (segmentDaily.dates || []).map((d: string) => String(d).slice(5))
    const seriesRows = Array.isArray(segmentDaily.series) ? segmentDaily.series : []
    processChart.setOption({
      color: ['#0076ff', '#0d9488', '#ea580c', '#7c3aed', '#ca8a04', '#64748b'],
      tooltip: { trigger: 'axis' },
      legend: {
        data: seriesRows.map((r: any) => r.segment_name),
        bottom: 0,
        type: 'scroll',
        icon: 'circle',
        itemWidth: 8,
      },
      grid: { left: 36, right: 12, top: 16, bottom: 40, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      series: seriesRows.map((r: any) => ({
        name: r.segment_name,
        type: 'bar',
        barMaxWidth: 18,
        emphasis: { focus: 'series' },
        data: r.data || [],
      })),
    }, true)
  }

  if (riskEl.value) {
    riskChart = riskChart || echarts.init(riskEl.value)
    const rows = charts.delivery_risk || []
    riskChart.setOption({
      color: COLORS.risk,
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, type: 'scroll', icon: 'circle', itemWidth: 8 },
      series: [
        {
          name: '交期',
          type: 'pie',
          radius: ['42%', '66%'],
          center: ['50%', '46%'],
          padAngle: 2,
          itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 },
          data: rows.map((r: any) => ({ name: r.label, value: r.count })),
          label: { color: '#475569', fontSize: 11, formatter: '{b}\n{c}' },
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
    const tasks: Promise<any>[] = [http.get('/progress/board'), loadQualityAlerts()]
    const idx = { board: 0, shortage: -1, po: -1 }

    if (canShortage.value) {
      idx.shortage = tasks.length
      tasks.push(
        http
          .get('/sales-orders/demand-shortages', { params: { include_shared: true } })
          .catch(() => null),
      )
    }
    if (canPurchase.value) {
      idx.po = tasks.length
      tasks.push(
        http
          .get('/purchase-orders', { params: { delivery_alert: 'overdue', page: 1, page_size: 1 } })
          .catch(() => null),
      )
    }

    const results = await Promise.all(tasks)
    board.value = results[idx.board]?.data || null

    const today = todayStr()
    const orders = board.value?.orders || []
    alerts.risk = Number(board.value?.summary?.at_risk_orders || 0)
    alerts.dueToday = orders.filter((o: any) => String(o.delivery_date || '').slice(0, 10) === today).length

    if (idx.shortage >= 0) {
      const s = results[idx.shortage]
      const data = s?.data || {}
      const list = (data.lines || []).filter(
        (r: any) => Number(r.to_buy_qty ?? r.shortage_qty ?? 0) > 0,
      )
      shortages.value = list.map((r: any) => ({
        ...r,
        order_no: (r.sources || []).map((x: any) => x.order_no).filter(Boolean)[0] || '—',
        to_buy_qty: r.to_buy_qty ?? r.shortage_qty,
      }))
      alerts.shortage = Number(data.to_buy_lines ?? list.length)
    } else {
      shortages.value = []
      alerts.shortage = 0
    }

    alerts.poOverdue =
      idx.po >= 0
        ? Number(results[idx.po]?.data?.total ?? results[idx.po]?.data?.items?.length ?? 0)
        : 0

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
.wb {
  --wb-ink: #0f172a;
  --wb-muted: #64748b;
  --wb-line: #e6ebf2;
  --wb-soft: #f4f7fb;
  --wb-card: #ffffff;
  --wb-accent: #0076ff;
  --wb-ok: #0d9488;
  --wb-warn: #d97706;
  --wb-danger: #dc2626;
  color: var(--wb-ink);
  padding-bottom: 8px;
}

.wb-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
  padding: 18px 20px;
  border-radius: 18px;
  background:
    radial-gradient(1200px 240px at 0% 0%, rgba(0, 118, 255, 0.12), transparent 55%),
    linear-gradient(180deg, #ffffff 0%, #f7faff 100%);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.wb-kicker {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--wb-muted);
}

.wb-title {
  margin: 0;
  font-size: 28px;
  font-weight: 750;
  letter-spacing: -0.03em;
  line-height: 1.15;
}

.wb-hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.wb-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--wb-line);
  background: #fff;
  color: var(--wb-ink);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.12s ease;
}

.wb-btn:hover:not(:disabled) {
  border-color: #b3d4ff;
  background: #f0f7ff;
  transform: translateY(-1px);
}

.wb-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.wb-btn-accent {
  border-color: #b3d4ff;
  background: #e8f3ff;
  color: #005fcc;
}

.wb-btn-primary {
  border-color: transparent;
  background: var(--wb-accent);
  color: #fff;
}

.wb-btn-primary:hover:not(:disabled) {
  background: #005fcc;
  border-color: transparent;
}

.wb-section {
  margin-bottom: 22px;
}

.wb-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.wb-section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.wb-section-hint {
  font-size: 12px;
  color: var(--wb-muted);
}

.wb-today-skel {
  padding: 16px 18px;
  border-radius: 14px;
  background: var(--wb-soft);
  color: var(--wb-ink);
  font-size: 13px;
}

.wb-quality-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.wb-quality-chip {
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #9a3412;
  border-radius: 999px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.15s ease;
}

.wb-quality-chip:hover {
  box-shadow: 0 4px 12px rgba(154, 52, 18, 0.15);
  transform: translateY(-1px);
}

.wb-quality-chip.sev-high {
  border-color: #fecaca;
  background: #fef2f2;
  color: var(--wb-danger);
}

.wb-attention {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.wb-tile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-height: 108px;
  padding: 14px 14px 12px;
  border: 1px solid var(--wb-line);
  border-radius: 16px;
  background: var(--wb-card);
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.12s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}

.wb-tile::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: #cbd5e1;
}

.wb-tile:hover {
  transform: translateY(-2px);
  border-color: #c7dbf8;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.wb-tile.is-warn::before {
  background: var(--wb-warn);
}

.wb-tile.is-danger::before {
  background: var(--wb-danger);
}

.wb-tile.is-warn {
  background: linear-gradient(180deg, #fffdf7 0%, #fff 70%);
}

.wb-tile.is-danger {
  background: linear-gradient(180deg, #fff8f8 0%, #fff 70%);
}

.wb-tile-label {
  font-size: 12px;
  color: var(--wb-muted);
}

.wb-tile-value {
  font-size: 28px;
  font-weight: 750;
  letter-spacing: -0.03em;
  line-height: 1;
}

.wb-tile-foot {
  margin-top: auto;
  font-size: 11px;
  color: #94a3b8;
}

.wb-overview {
  margin-bottom: 22px;
}

.wb-card {
  background: var(--wb-card);
  border: 1px solid var(--wb-line);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  min-width: 0;
}

.wb-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.wb-card-title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 700;
}

.wb-card-head .wb-card-title {
  margin: 0;
}

.wb-chip {
  font-size: 11px;
  color: #005fcc;
  background: #e8f3ff;
  border-radius: 999px;
  padding: 3px 9px;
}

.wb-link {
  border: none;
  background: transparent;
  color: var(--wb-accent);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.wb-link:hover {
  text-decoration: underline;
}

.wb-metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.wb-metric {
  padding: 12px;
  border-radius: 12px;
  background: var(--wb-soft);
  min-width: 0;
}

.wb-metric-label {
  font-size: 12px;
  color: var(--wb-muted);
  margin-bottom: 6px;
}

.wb-metric-value {
  font-size: 22px;
  font-weight: 720;
  letter-spacing: -0.02em;
  line-height: 1.1;
  word-break: break-all;
}

.wb-metric-value.is-ok {
  color: var(--wb-ok);
}

.wb-metric-value.is-bad {
  color: var(--wb-danger);
}

.wb-mid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

.wb-panel {
  display: flex;
  flex-direction: column;
}

.wb-pill {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 11px;
  background: #e2e8f0;
  color: #334155;
}

.wb-pill-danger {
  background: #fee2e2;
  color: #b91c1c;
}

.wb-more {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--wb-muted);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.chart-box {
  height: 240px;
  width: 100%;
}

.table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.table-scroll :deep(.el-table) {
  width: 100%;
}

@media (max-width: 1280px) {
  .wb-attention {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chart-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 720px) {
  .wb-hero {
    flex-direction: column;
    align-items: stretch;
  }

  .wb-attention {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .wb-title {
    font-size: 24px;
  }
}
</style>
