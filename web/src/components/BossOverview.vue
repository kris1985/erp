<template>
  <div class="boss">
    <div v-if="loading" class="h5-empty">加载中…</div>
    <div v-else-if="teamEmpty" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      尚未配置班组，请联系管理员
    </div>
    <template v-else>
      <p class="h5-section-label">今日预警</p>
      <div class="boss-alerts" :class="{ 'boss-alerts--3': !showFinance }">
        <div class="boss-alert" :class="{ warn: alerts.rush > 0 }">
          <div class="boss-alert__num h5-stat-num">{{ alerts.rush }}</div>
          <div class="boss-alert__cap">急单</div>
        </div>
        <div class="boss-alert" :class="{ danger: alerts.risk > 0 }">
          <div class="boss-alert__num h5-stat-num">{{ alerts.risk }}</div>
          <div class="boss-alert__cap">交期风险</div>
        </div>
        <div class="boss-alert" :class="{ warn: alerts.shortage > 0 }">
          <div class="boss-alert__num h5-stat-num">{{ alerts.shortage }}</div>
          <div class="boss-alert__cap">缺料行</div>
        </div>
        <div v-if="showFinance" class="boss-alert" :class="{ danger: alerts.ar > 0 }">
          <div class="boss-alert__num h5-stat-num boss-alert__num--sm">{{ formatWan(alerts.ar) }}</div>
          <div class="boss-alert__cap">客户欠款</div>
        </div>
      </div>

      <template v-if="showFinance">
        <p class="h5-section-label">本月经营</p>
        <div class="boss-money card-block">
          <div class="boss-money__item">
            <div class="muted">出货额</div>
            <div class="h5-stat-num boss-money__val">¥{{ formatMoney(kpi?.shipment_amount) }}</div>
          </div>
          <div class="boss-money__item">
            <div class="muted">回款额</div>
            <div class="h5-stat-num boss-money__val">¥{{ formatMoney(kpi?.payment_amount) }}</div>
          </div>
          <div class="boss-money__item">
            <div class="muted">毛利(估)</div>
            <div
              class="h5-stat-num boss-money__val"
              :class="{ neg: Number(kpi?.gross_profit || 0) < 0 }"
            >
              ¥{{ formatMoney(kpi?.gross_profit) }}
            </div>
          </div>
        </div>
      </template>

      <div class="boss-section-head">
        <p class="h5-section-label" style="margin: 0">该盯的单</p>
        <span class="muted">急单 · 风险优先</span>
      </div>
      <div v-if="!focusOrders.length" class="h5-empty" style="padding: 24px">暂无重点订单</div>
      <article v-for="o in focusOrders" :key="o.id" class="h5-list-card boss-order">
        <div class="h5-list-card__head">
          <div class="h5-list-card__title">{{ o.order_no }}</div>
          <div class="boss-order__tags">
            <span v-if="o.is_rush" class="h5-pill h5-pill--danger">急单</span>
            <span v-if="o.at_risk" class="h5-pill h5-pill--warn">交期风险</span>
          </div>
        </div>
        <div class="boss-order__meta muted">
          {{ o.customer_name || '—' }} · {{ o.product_code || '—' }} · {{ o.total_qty }} 双
        </div>
        <div class="boss-order__row">
          <div class="boss-order__progress">
            <div class="boss-order__bar">
              <div class="boss-order__fill" :style="{ width: `${Math.min(100, o.overall_percent || 0)}%` }" />
            </div>
            <span class="h5-stat-num boss-order__pct">{{ o.overall_percent || 0 }}%</span>
          </div>
          <div class="boss-order__due" :class="{ danger: o.at_risk }">
            {{ o.delivery_date ? o.delivery_date.slice(5) : '无交期' }}
          </div>
        </div>
        <div v-if="o.bottleneck" class="boss-order__bn muted">
          瓶颈 {{ o.bottleneck.process_name }} · 剩 {{ o.bottleneck.remain_qty }}
        </div>
      </article>

      <p class="h5-section-label">工序瓶颈</p>
      <div v-if="!bottlenecks.length" class="card-block muted">暂无明显瓶颈</div>
      <div v-else class="boss-bn-list">
        <div v-for="b in bottlenecks.slice(0, 5)" :key="b.process_name" class="boss-bn card-block">
          <div class="boss-bn__name">{{ b.process_name }}</div>
          <div class="muted">卡住 {{ b.order_count }} 单 · 剩余 {{ b.remain_qty }}</div>
        </div>
      </div>

      <p class="h5-section-label">缺料卡住</p>
      <div v-if="!shortagePreview.length" class="card-block muted">暂无待采缺料</div>
      <div v-else>
        <div v-for="(s, i) in shortagePreview" :key="i" class="h5-list-card">
          <div class="h5-list-card__head">
            <div class="h5-list-card__title">{{ s.material_name || s.sku_name || '物料' }}</div>
            <span class="h5-pill h5-pill--warn">缺 {{ s.shortage_qty ?? s.to_buy_qty ?? '—' }}</span>
          </div>
          <div class="muted">
            {{ s.order_no || '' }}
            <template v-if="s.partner_name"> · {{ s.partner_name }}</template>
          </div>
        </div>
        <p v-if="alerts.shortage > 3" class="muted boss-more">还有 {{ alerts.shortage - 3 }} 行缺料未展示</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const showFinance = computed(() => auth.showFinanceHome)
const teamEmpty = ref(false)

const loading = ref(true)
const board = ref<any>(null)
const kpi = ref<any>(null)
const shortages = ref<any[]>([])

const alerts = reactive({
  rush: 0,
  risk: 0,
  shortage: 0,
  ar: 0,
})

const focusOrders = computed(() => {
  const rows = board.value?.orders || []
  const focus = rows.filter((o: any) => o.is_rush || o.at_risk)
  const list = focus.length ? focus : rows
  return list.slice(0, 6)
})

const bottlenecks = computed(() => board.value?.bottlenecks || [])
const shortagePreview = computed(() => shortages.value.slice(0, 3))

function formatMoney(v: any) {
  const n = Number(v || 0)
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return n.toFixed(0)
}

function formatWan(v: number) {
  if (!v) return '0'
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`
  return String(Math.round(v))
}

async function load() {
  loading.value = true
  try {
    if (auth.isTeamScoped) {
      const w: any = await http.get('/workers')
      if (w.data?.team_empty) {
        teamEmpty.value = true
        return
      }
    }
    teamEmpty.value = false
    const reqs: Promise<any>[] = [
      http.get('/progress/board'),
      http.get('/material-shortages', { params: { hide_purchased: true } }).catch(() => ({ data: [] })),
    ]
    if (showFinance.value) {
      reqs.splice(1, 0, http.get('/business-kpi'))
    }
    const results: any[] = await Promise.all(reqs)
    const b = results[0]
    const k = showFinance.value ? results[1] : null
    const s = showFinance.value ? results[2] : results[1]
    board.value = b.data
    kpi.value = k?.data || null
    const list = Array.isArray(s.data) ? s.data : s.data?.items || []
    shortages.value = list
    alerts.rush = Number(b.data?.summary?.rush_orders || 0)
    alerts.risk = Number(b.data?.summary?.at_risk_orders || 0)
    alerts.shortage = list.length
    alerts.ar = showFinance.value ? Number(k?.data?.customer_ar_balance || 0) : 0
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.boss-alerts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-bottom: 4px;
}

.boss-alerts--3 {
  grid-template-columns: repeat(3, 1fr);
}

.boss-alert {
  background: var(--ws-bg-elevated);
  border-radius: var(--ws-radius);
  padding: 14px 16px;
  box-shadow: var(--ws-shadow-soft);
}

.boss-alert.warn {
  background: rgba(255, 159, 10, 0.08);
}

.boss-alert.danger {
  background: rgba(255, 59, 48, 0.08);
}

.boss-alert__num {
  font-size: 28px;
  color: var(--ws-ink);
  margin-bottom: 4px;
}

.boss-alert__num--sm {
  font-size: 22px;
}

.boss-alert.warn .boss-alert__num {
  color: #c77700;
}

.boss-alert.danger .boss-alert__num {
  color: #d70015;
}

.boss-alert__cap {
  font-size: 12px;
  color: var(--ws-muted);
  font-weight: 600;
}

.boss-money {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 14px 12px;
}

.boss-money__item {
  text-align: center;
}

.boss-money__val {
  margin-top: 6px;
  font-size: 15px;
  color: var(--ws-ink);
  letter-spacing: -0.02em;
}

.boss-money__val.neg {
  color: var(--ws-danger);
}

.boss-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 18px 4px 10px;
}

.boss-order__tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.boss-order__meta {
  margin-top: 2px;
}

.boss-order__row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.boss-order__progress {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.boss-order__bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: rgba(60, 60, 67, 0.08);
  overflow: hidden;
}

.boss-order__fill {
  height: 100%;
  border-radius: 3px;
  background: var(--ws-primary);
}

.boss-order__pct {
  font-size: 13px;
  color: var(--ws-ink-secondary);
  min-width: 40px;
  text-align: right;
}

.boss-order__due {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-muted);
  white-space: nowrap;
}

.boss-order__due.danger {
  color: #d70015;
}

.boss-order__bn {
  margin-top: 8px;
  font-size: 12px;
}

.boss-bn-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.boss-bn {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.boss-bn__name {
  font-weight: 600;
  font-size: 15px;
}

.boss-more {
  margin: 4px 8px 12px;
  font-size: 12px;
}
</style>
