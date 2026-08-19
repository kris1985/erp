<template>
  <div class="wb">
    <header class="wb-hero">
      <div class="wb-hero-copy">
        <p class="wb-kicker">{{ todayLabel }}</p>
        <h1 class="wb-title">工作台</h1>
        <p class="wb-sub">先看风险，再看产量与经营</p>
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
          车间军师
        </button>
        <button type="button" class="wb-btn wb-btn-primary" @click="openBoard">投屏</button>
      </div>
    </header>

    <!-- A0：今日 3 件事（规则路径，不依赖军师） -->
    <section v-if="canTodayActions" class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">今日 3 件事</h2>
        <span class="wb-section-hint">{{ todayActionsSummary || '可点击跳转处理' }}</span>
      </div>
      <div v-if="todayActionsLoading" class="wb-today-skel">加载今日行动…</div>
      <div v-else-if="todayActionsError" class="wb-today-skel is-muted">{{ todayActionsError }}</div>
      <div v-else class="wb-today3">
        <button
          v-for="(a, idx) in todayTop3"
          :key="a.id || idx"
          type="button"
          class="wb-today-card"
          :class="'sev-' + (a.severity || 'medium')"
          @click="goTodayAction(a)"
        >
          <div class="wb-today-card-top">
            <span class="wb-today-idx">{{ idx + 1 }}</span>
            <span class="wb-today-sev">{{ severityLabel(a.severity) }}</span>
          </div>
          <div class="wb-today-title">{{ a.title }}</div>
          <p class="wb-today-fact">{{ firstFact(a) }}</p>
          <span class="wb-today-go">去处理 →</span>
        </button>
      </div>
    </section>

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
            @click="
              $router.push({
                path: '/admin/defects',
                query: {
                  mode: 'trace',
                  product_code: a.product_code || undefined,
                  process_id: a.process_id != null ? String(a.process_id) : undefined,
                },
              })
            "
          >
            {{ a.chip_label }}
          </button>
        </el-tooltip>
      </div>
    </section>

    <!-- A2e：实耗 vs 标准损耗预警（chip 列表，点击回订单用料页） -->
    <section
      v-if="canLossVariance && (lossVarianceRows.length || lossVarianceLoading)"
      id="loss-variance"
      class="wb-section"
    >
      <div class="wb-section-head">
        <h2 class="wb-section-title">损耗超标</h2>
        <span class="wb-section-hint">
          {{ lossVarianceSummary || '已发料 vs BOM 标准损耗对比，超标点击查看用料明细' }}
        </span>
      </div>
      <div v-if="lossVarianceLoading" class="wb-today-skel">加载损耗预警…</div>
      <div v-else class="wb-quality-chips">
        <el-tooltip
          v-for="(r, idx) in lossVarianceRows"
          :key="idx"
          :content="`单耗 ${r.qty_per_pair} · 标准 ${r.required_qty} · 已发 ${r.issued_qty}`"
          placement="top"
          effect="dark"
        >
          <button
            type="button"
            class="wb-quality-chip wb-loss-chip"
            :class="{ 'sev-high': (r.over_pct ?? 100) >= 30 }"
            @click="$router.push({ path: '/admin/executions', query: { shop_order_id: String(r.order_id) } })"
          >
            {{ r.order_no }} · {{ r.supplier_product_name || r.supplier_product_code || '物料' }}
            {{ r.over_pct != null ? `超${r.over_pct.toFixed(0)}%` : '超标' }}
          </button>
        </el-tooltip>
      </div>
    </section>

    <!-- 今日关注：唯一承载急单/交期等行动指标 -->
    <section class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">今日关注</h2>
        <span class="wb-section-hint">点击跳转到对应处理区</span>
      </div>
      <div class="wb-attention">
        <button
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.rush, 'warn')"
          @click="scrollTo('focus')"
        >
          <span class="wb-tile-label">急单</span>
          <span class="wb-tile-value">{{ alerts.rush }}</span>
          <span class="wb-tile-foot">优先插单跟进</span>
        </button>
        <button
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.risk, 'danger')"
          @click="scrollTo('focus')"
        >
          <span class="wb-tile-label">交期风险</span>
          <span class="wb-tile-value">{{ alerts.risk }}</span>
          <span class="wb-tile-foot">可能延误交付</span>
        </button>
        <button
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.dueToday, 'warn')"
          @click="scrollTo('focus')"
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
        <button
          v-if="canSchedule"
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.loadHot, 'danger')"
          @click="$router.push('/admin/schedule')"
        >
          <span class="wb-tile-label">负荷过载</span>
          <span class="wb-tile-value">{{ alerts.loadHot }}</span>
          <span class="wb-tile-foot">近 14 日工序日</span>
        </button>
        <button
          v-if="canLossVariance"
          type="button"
          class="wb-tile"
          :class="toneClass(alerts.lossVariance, 'warn')"
          @click="scrollTo('loss-variance')"
        >
          <span class="wb-tile-label">损耗超标</span>
          <span class="wb-tile-value">{{ alerts.lossVariance }}</span>
          <span class="wb-tile-foot">实耗超标准损耗行</span>
        </button>
      </div>
    </section>

    <!-- 概览：产量 + 经营，不与关注区重复 -->
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

      <div v-if="showFinance" class="wb-card wb-overview-fin">
        <div class="wb-card-head">
          <h3 class="wb-card-title">本月经营</h3>
          <button type="button" class="wb-link" @click="$router.push('/admin/profit')">利润明细</button>
        </div>
        <div class="wb-metric-row wb-metric-row-4">
          <div class="wb-metric">
            <div class="wb-metric-label">出货额</div>
            <div class="wb-metric-value">{{ formatMoney(kpi?.shipment_amount) }}</div>
          </div>
          <div class="wb-metric">
            <div class="wb-metric-label">回款额</div>
            <div class="wb-metric-value">{{ formatMoney(kpi?.payment_amount) }}</div>
          </div>
          <div class="wb-metric">
            <div class="wb-metric-label">毛利(估)</div>
            <div class="wb-metric-value" :class="{ 'is-neg': Number(kpi?.gross_profit || 0) < 0 }">
              {{ formatMoney(kpi?.gross_profit) }}
            </div>
          </div>
          <div class="wb-metric wb-metric-click" @click="$router.push('/admin/receivables')">
            <div class="wb-metric-label">客户欠款</div>
            <div class="wb-metric-value" :class="{ 'is-neg': Number(kpi?.customer_ar_balance || 0) > 0 }">
              {{ formatMoney(kpi?.customer_ar_balance) }}
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 处理区 -->
    <section class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">马上处理</h2>
      </div>
      <div class="wb-mid">
        <div id="focus" class="wb-card wb-panel">
          <div class="wb-card-head">
            <h3 class="wb-card-title">该盯的单</h3>
            <span class="wb-section-hint">急单 · 风险 · 今日交期</span>
          </div>
          <div v-if="!focusOrders.length" class="wb-empty">暂无重点订单</div>
          <div v-else class="wb-focus-list">
            <button
              v-for="o in focusOrders"
              :key="o.id || o.order_no"
              type="button"
              class="wb-focus"
              @click="$router.push('/admin/executions')"
            >
              <div class="wb-focus-top">
                <span class="wb-focus-no">{{ o.order_no }}</span>
                <span class="wb-focus-tags">
                  <span v-if="o.is_rush" class="wb-pill wb-pill-danger">急单</span>
                  <span v-if="o.at_risk" class="wb-pill wb-pill-warn">交期风险</span>
                  <span v-if="isDueToday(o)" class="wb-pill">今日交期</span>
                </span>
              </div>
              <div class="wb-focus-meta">
                {{ o.customer_name || '—' }} · {{ o.product_code || '—' }} · 交期
                {{ o.delivery_date || '—' }}
              </div>
              <div class="wb-focus-row">
                <div class="wb-progress">
                  <div
                    class="wb-progress-fill"
                    :style="{ width: `${Math.min(100, Number(o.overall_percent) || 0)}%` }"
                  />
                </div>
                <span class="wb-progress-pct">{{ Math.min(100, Number(o.overall_percent) || 0) }}%</span>
              </div>
              <div v-if="o.bottleneck" class="wb-focus-bn">
                瓶颈 {{ o.bottleneck.process_name }} · 剩 {{ o.bottleneck.remain_qty }}
              </div>
            </button>
          </div>
        </div>

        <div v-if="canShortage" class="wb-card wb-panel">
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

        <div v-if="canSchedule" class="wb-card wb-panel">
          <div class="wb-card-head">
            <h3 class="wb-card-title">负荷过载</h3>
            <button type="button" class="wb-link" @click="$router.push('/admin/schedule')">去排产</button>
          </div>
          <div class="table-scroll">
            <el-table :data="loadHotRows" stripe border size="small" empty-text="近 14 日暂无过载">
              <el-table-column prop="date" label="日期" width="100" />
              <el-table-column prop="process_name" label="工序" min-width="80" show-overflow-tooltip />
              <el-table-column label="负荷/产能" min-width="100">
                <template #default="{ row }">
                  {{ row.load_qty }} / {{ row.capacity ?? '—' }}
                </template>
              </el-table-column>
            </el-table>
          </div>
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
          <h3 class="wb-card-title">近 7 日工序产量</h3>
          <div ref="processEl" class="chart-box" />
        </div>
        <div class="wb-card">
          <h3 class="wb-card-title">交期风险构成</h3>
          <div ref="riskEl" class="chart-box" />
        </div>
      </div>
    </section>

    <section class="wb-section">
      <div class="wb-section-head">
        <h2 class="wb-section-title">在制详情</h2>
      </div>
      <div class="board-grid">
        <div class="wb-card wb-main-col">
          <h3 class="wb-card-title">在制订单</h3>
          <div class="table-scroll">
            <el-table
              :data="board?.orders || []"
              stripe
              border
              size="small"
              empty-text="暂无在制订单"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 130)" resizable>
                <template #default="{ row }">
                  {{ row.order_no }}
                  <span v-if="row.is_rush" class="wb-pill wb-pill-danger" style="margin-left: 4px">插单</span>
                </template>
              </el-table-column>
              <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 100)" resizable />
              <el-table-column prop="product_code" label="产品" :width="colWidth('product_code', 120)" resizable />
              <el-table-column column-key="交期" label="交期" :width="colWidth('交期', 110)" resizable>
                <template #default="{ row }">
                  <span :class="{ 'is-risk-text': row.at_risk }">{{ row.delivery_date || '—' }}</span>
                  <span v-if="row.at_risk" class="wb-pill wb-pill-danger" style="margin-left: 4px">风险</span>
                </template>
              </el-table-column>
              <el-table-column column-key="总进度" label="总进度" :width="colWidth('总进度', 140)" resizable>
                <template #default="{ row }">
                  <el-progress
                    :percentage="Math.min(100, Number(row.overall_percent) || 0)"
                    :stroke-width="10"
                    :status="row.overall_percent >= 100 ? 'success' : undefined"
                  />
                </template>
              </el-table-column>
              <el-table-column column-key="瓶颈工序" label="瓶颈工序" :width="colWidth('瓶颈工序', 160)" resizable>
                <template #default="{ row }">
                  <template v-if="row.bottleneck">
                    {{ row.bottleneck.process_name }} · 剩 {{ row.bottleneck.remain_qty }}
                  </template>
                  <span v-else class="wb-muted">—</span>
                </template>
              </el-table-column>
              <el-table-column column-key="各工序" label="各工序段" :width="colWidth('各工序', 220)" resizable>
                <template #default="{ row }">
                  <!-- 工序段重构（29.1/D17）：段级进度 = 段内 completed 之和 / plan 之和 -->
                  <div v-for="g in segmentGroups(row.processes)" :key="g.key" class="wb-muted" style="line-height: 1.45">
                    {{ g.label }} {{ g.completed }}/{{ g.plan }}
                    <span v-if="g.plan" style="color: var(--el-color-primary)">
                      {{ Math.round((g.completed / g.plan) * 100) }}%
                    </span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <div class="wb-side">
          <div class="wb-card wb-side-card">
            <h3 class="wb-card-title">工序瓶颈</h3>
            <div class="table-scroll">
              <el-table
                :data="board?.bottlenecks || []"
                stripe
                border
                size="small"
                empty-text="暂无瓶颈"
                table-layout="fixed"
                @header-dragend="onHeaderDragend1"
              >
                <el-table-column prop="process_name" label="工序" min-width="72" show-overflow-tooltip />
                <el-table-column
                  prop="order_count"
                  label="卡住"
                  :width="colWidth1('order_count', 64)"
                  align="right"
                  resizable
                />
                <el-table-column
                  prop="remain_qty"
                  label="剩余"
                  :width="colWidth1('remain_qty', 64)"
                  align="right"
                  resizable
                />
              </el-table>
            </div>
            <p class="wb-more">按在制单最低未完成工序汇总</p>
          </div>

          <div class="wb-card wb-side-card">
            <h3 class="wb-card-title">今日分工序</h3>
            <div class="table-scroll">
              <el-table
                :data="board?.today?.by_process || []"
                stripe
                border
                size="small"
                empty-text="今日暂无报工"
                table-layout="fixed"
                @header-dragend="onHeaderDragend2"
              >
                <el-table-column prop="process_name" label="工序" min-width="72" show-overflow-tooltip />
                <el-table-column
                  prop="qualified_qty"
                  label="合格"
                  :width="colWidth2('qualified_qty', 64)"
                  align="right"
                  resizable
                />
                <el-table-column
                  prop="defect_qty"
                  label="不良"
                  :width="colWidth2('defect_qty', 64)"
                  align="right"
                  resizable
                />
              </el-table>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { colWidth, onHeaderDragend } = useTableColWidths('dashboard-orders')
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('dashboard-bottlenecks')
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths('dashboard-today-process')

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const canSchedule = computed(() => auth.hasPermission('menu.schedule'))
const canTodayActions = computed(
  () => auth.hasPermission('menu.orders') || auth.hasPermission('menu.schedule'),
)
const canQualityAlerts = computed(() => auth.hasPermission('menu.work_logs'))
const canLossVariance = computed(
  () => auth.hasPermission('menu.material_shortages') || auth.hasPermission('menu.orders'),
)
const canShortage = computed(
  () => auth.hasPermission('menu.material_shortages') || auth.hasPermission('menu.purchase_orders'),
)
const canPurchase = computed(() => auth.hasPermission('menu.purchase_orders'))
const showFinance = computed(
  () =>
    auth.showFinanceHome ||
    auth.hasPermission('menu.profit') ||
    auth.hasPermission('menu.receivables') ||
    auth.hasPermission('menu.payments'),
)

const board = ref<any>(null)
const kpi = ref<any>(null)
const shortages = ref<any[]>([])
const loadHotRows = ref<any[]>([])
const loading = ref(false)
const todayTop3 = ref<any[]>([])
const todayActionsSummary = ref('')
const todayActionsLoading = ref(false)
const todayActionsError = ref('')
const qualityAlerts = ref<any[]>([])
const qualityAlertsSummary = ref('')
const qualityAlertsLoading = ref(false)
const lossVarianceRows = ref<any[]>([])
const lossVarianceSummary = ref('')
const lossVarianceLoading = ref(false)
const trendEl = ref<HTMLElement | null>(null)
const processEl = ref<HTMLElement | null>(null)
const riskEl = ref<HTMLElement | null>(null)

const alerts = reactive({
  rush: 0,
  risk: 0,
  dueToday: 0,
  shortage: 0,
  poOverdue: 0,
  loadHot: 0,
  lossVariance: 0,
})

let trendChart: echarts.ECharts | null = null
let processChart: echarts.ECharts | null = null
let riskChart: echarts.ECharts | null = null

const COLORS = {
  qualified: '#0d9488',
  defect: '#ea580c',
  process: '#0076ff',
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

function segmentGroups(processes: any[] | undefined) {
  // 工序段重构（29.1/D17）：按段聚合，段进度 = completed 之和 / plan 之和；未分段兜底（D18）
  const by = new Map<string, { label: string; completed: number; plan: number }>()
  for (const p of processes || []) {
    const key = p.segment_id != null ? `seg-${p.segment_id}` : 'unlabeled'
    const label = p.segment_name || '未分段'
    if (!by.has(key)) by.set(key, { label, completed: 0, plan: 0 })
    const g = by.get(key)!
    g.completed += Number(p.completed_qty || 0)
    g.plan += Number(p.plan_qty || 0)
  }
  return [...by.values()].map((g, i) => ({ key: String(i), ...g }))
}

function isoDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function isDueToday(o: any) {
  return String(o?.delivery_date || '').slice(0, 10) === todayStr()
}

function toneClass(n: number, tone: 'warn' | 'danger') {
  if (!n) return ''
  return tone === 'danger' ? 'is-danger' : 'is-warn'
}

function severityLabel(sev: string | undefined) {
  if (sev === 'high') return '高优'
  if (sev === 'low') return '低'
  return '中'
}

function firstFact(a: any) {
  const facts = a?.evidence?.facts
  if (Array.isArray(facts) && facts.length) return String(facts[0])
  return String(a?.why || a?.do || '')
}

function goTodayAction(a: any) {
  let path = String(a?.ui_path || '/admin').trim() || '/admin'
  // P1-2 兜底：可排出方案类行动若未带 propose，补上 order_ids + propose
  if (
    (a?.id === 'kit_schedule' || a?.id === 'kit_partial' || a?.id === 'delivery_risk') &&
    path.startsWith('/admin/schedule') &&
    !path.includes('propose=')
  ) {
    const ids = Array.isArray(a?.order_ids) ? a.order_ids.filter((n: any) => Number(n) > 0) : []
    const q = new URLSearchParams()
    if (ids.length) q.set('order_ids', ids.slice(0, 30).join(','))
    q.set('propose', '1')
    path = `/admin/schedule?${q.toString()}`
  }
  router.push(path)
}

async function loadTodayActions() {
  if (!canTodayActions.value) {
    todayTop3.value = []
    todayActionsSummary.value = ''
    todayActionsError.value = ''
    return
  }
  todayActionsLoading.value = true
  todayActionsError.value = ''
  try {
    const res: any = await http.post(
      '/schedule/agent/metrics/query',
      { metric_id: 'analytics.today_actions', params: {} },
      { silent: true } as any,
    )
    const payload = res?.data
    if (payload?.error) {
      todayTop3.value = []
      todayActionsError.value =
        payload.error === 'forbidden' ? '无权限查看今日行动' : payload.message || '今日行动暂不可用'
      return
    }
    const analysis = payload?.data?.analysis_id ? payload.data : payload
    const inner = analysis?.data || {}
    todayTop3.value = Array.isArray(inner.top3) ? inner.top3.slice(0, 3) : []
    todayActionsSummary.value = String(analysis?.summary || '')
    if (!todayTop3.value.length) {
      todayActionsError.value = '暂无今日行动'
    }
  } catch (e: any) {
    todayTop3.value = []
    todayActionsError.value = e?.error?.message || e?.message || '今日行动加载失败'
  } finally {
    todayActionsLoading.value = false
  }
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

async function loadLossVariance() {
  if (!canLossVariance.value) {
    lossVarianceRows.value = []
    lossVarianceSummary.value = ''
    alerts.lossVariance = 0
    return
  }
  lossVarianceLoading.value = true
  try {
    const res: any = await http.get('/analytics/loss-variance', {
      params: { threshold: 0.1, days: 90, limit: 8 },
    })
    const data = res?.data || {}
    lossVarianceRows.value = Array.isArray(data.rows) ? data.rows : []
    lossVarianceSummary.value = String(data.summary || '')
    alerts.lossVariance = Number(data.flagged_count || 0)
  } catch {
    lossVarianceRows.value = []
    alerts.lossVariance = 0
  } finally {
    lossVarianceLoading.value = false
  }
}

const focusOrders = computed(() => {
  const rows = board.value?.orders || []
  const focus = rows.filter((o: any) => o.is_rush || o.at_risk || isDueToday(o))
  return (focus.length ? focus : rows).slice(0, 8)
})

const shortagePreview = computed(() => {
  const rows = [...shortages.value]
  rows.sort((a, b) => {
    const rush = Number(!!b.is_rush) - Number(!!a.is_rush)
    if (rush) return rush
    return Number(b.to_buy_qty ?? b.shortage_qty ?? 0) - Number(a.to_buy_qty ?? a.shortage_qty ?? 0)
  })
  return rows.slice(0, 8)
})

function formatMoney(v: any) {
  const n = Number(v || 0)
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(1)}万`
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
    const rows = charts.process_bars || []
    processChart.setOption({
      color: [COLORS.process],
      tooltip: { trigger: 'axis' },
      grid: { left: 36, right: 12, top: 16, bottom: 28, containLabel: true },
      xAxis: {
        type: 'category',
        data: rows.map((r: any) => r.process_name),
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
          type: 'bar',
          barMaxWidth: 28,
          itemStyle: { borderRadius: [6, 6, 0, 0] },
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
    const from = new Date()
    const to = new Date()
    to.setDate(to.getDate() + 13)

    const tasks: Promise<any>[] = [
      http.get('/progress/board'),
      loadTodayActions(),
      loadQualityAlerts(),
      loadLossVariance(),
    ]
    const idx = { board: 0, kpi: -1, shortage: -1, po: -1, load: -1 }

    if (showFinance.value) {
      idx.kpi = tasks.length
      tasks.push(http.get('/business-kpi').catch(() => null))
    }
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
    if (canSchedule.value) {
      idx.load = tasks.length
      tasks.push(
        http
          .get('/schedule/load', {
            params: { date_from: isoDate(from), date_to: isoDate(to), include_draft_orders: true },
          })
          .catch(() => null),
      )
    }

    const results = await Promise.all(tasks)
    board.value = results[idx.board]?.data || null

    const today = todayStr()
    const orders = board.value?.orders || []
    alerts.rush = Number(board.value?.summary?.rush_orders || 0)
    alerts.risk = Number(board.value?.summary?.at_risk_orders || 0)
    alerts.dueToday = orders.filter((o: any) => String(o.delivery_date || '').slice(0, 10) === today).length

    kpi.value = idx.kpi >= 0 ? results[idx.kpi]?.data || null : null

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

    if (idx.load >= 0) {
      const loadData = results[idx.load]?.data
      loadHotRows.value = (loadData?.bottlenecks || []).slice(0, 8)
      alerts.loadHot = Number((loadData?.bottlenecks || []).length)
    } else {
      loadHotRows.value = []
      alerts.loadHot = 0
    }

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

.wb-sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--wb-muted);
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

.wb-today3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.wb-today-skel {
  padding: 16px 18px;
  border-radius: 14px;
  background: var(--wb-soft);
  color: var(--wb-ink);
  font-size: 13px;
}

.wb-today-skel.is-muted {
  color: var(--wb-muted);
}

.wb-today-card {
  text-align: left;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--wb-line);
  background: var(--wb-card);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.12s ease;
  min-height: 132px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wb-today-card:hover {
  border-color: #bfdbfe;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}

.wb-today-card.sev-high {
  border-color: #fecaca;
  background: linear-gradient(180deg, #fff7f7 0%, #fff 70%);
}

.wb-today-card.sev-low {
  background: linear-gradient(180deg, #f8fafc 0%, #fff 70%);
}

.wb-today-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.wb-today-idx {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  background: #e8f1ff;
  color: var(--wb-accent);
}

.wb-today-sev {
  font-size: 11px;
  color: var(--wb-muted);
}

.wb-today-card.sev-high .wb-today-sev {
  color: var(--wb-danger);
  font-weight: 600;
}

.wb-today-title {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.35;
  color: var(--wb-ink);
}

.wb-today-fact {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--wb-muted);
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wb-today-go {
  font-size: 12px;
  color: var(--wb-accent);
  font-weight: 600;
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

.wb-loss-chip {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.wb-loss-chip:hover {
  box-shadow: 0 4px 12px rgba(29, 78, 216, 0.15);
}

.wb-loss-chip.sev-high {
  border-color: #fecaca;
  background: #fef2f2;
  color: var(--wb-danger);
}

.wb-attention {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
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
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 14px;
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

.wb-metric-row-4 {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.wb-metric {
  padding: 12px;
  border-radius: 12px;
  background: var(--wb-soft);
  min-width: 0;
}

.wb-metric-click {
  cursor: pointer;
  transition: background 0.15s ease;
}

.wb-metric-click:hover {
  background: #e8f3ff;
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

.wb-metric-value.is-neg {
  color: var(--wb-danger);
}

.wb-mid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.wb-panel {
  display: flex;
  flex-direction: column;
  min-height: 320px;
}

.wb-empty {
  flex: 1;
  display: grid;
  place-items: center;
  color: #94a3b8;
  font-size: 13px;
}

.wb-focus-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow: auto;
}

.wb-focus {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: var(--wb-soft);
  border-radius: 12px;
  padding: 11px 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.wb-focus:hover {
  border-color: #b3d4ff;
  background: #f0f7ff;
}

.wb-focus-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.wb-focus-no {
  font-weight: 700;
  font-size: 13px;
}

.wb-focus-tags {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
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

.wb-pill-warn {
  background: #ffedd5;
  color: #c2410c;
}

.wb-focus-meta,
.wb-focus-bn,
.wb-more,
.wb-muted {
  font-size: 12px;
  color: var(--wb-muted);
}

.wb-focus-meta {
  margin-top: 4px;
}

.wb-focus-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.wb-progress {
  flex: 1;
  height: 7px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.wb-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #4da0ff, #0076ff);
}

.wb-progress-pct {
  font-size: 12px;
  font-weight: 650;
  color: #334155;
  min-width: 36px;
  text-align: right;
}

.wb-focus-bn {
  margin-top: 6px;
}

.wb-more {
  margin: 10px 0 0;
}

.is-risk-text {
  color: var(--wb-danger);
  font-weight: 650;
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

.board-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 320px);
  gap: 14px;
  align-items: start;
}

.wb-main-col,
.wb-side {
  min-width: 0;
}

.wb-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.wb-side-card {
  min-width: 0;
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
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .wb-today3 {
    grid-template-columns: 1fr;
  }

  .wb-overview,
  .wb-mid,
  .chart-grid,
  .board-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .wb-metric-row-4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
