<template>
  <div
    class="workshop-board"
    :class="{ 'is-idle': idle }"
    @mousemove="bumpIdle"
    @mousedown="bumpIdle"
    @touchstart="bumpIdle"
  >
    <header class="wb-header">
      <div class="wb-brand">
        <span class="wb-brand-mark">铁玉兰</span>
        <span class="wb-brand-sub">{{ data?.factory_name || '车间看板' }}</span>
      </div>
      <div class="wb-header-meta">
        <div class="wb-clock">{{ clockText }}</div>
        <div class="wb-status" :class="{ err: offline }">
          {{ offline ? '连接中断' : refreshText }}
        </div>
      </div>
    </header>

    <section class="wb-kpis">
      <div class="wb-kpi">
        <div class="wb-kpi-label">昨日合格</div>
        <div class="wb-kpi-value">{{ anim.yesterdayQualified }}</div>
        <div class="wb-kpi-unit">双</div>
      </div>
      <div class="wb-kpi" :class="{ warn: defectHigh }">
        <div class="wb-kpi-label">昨日不良</div>
        <div class="wb-kpi-value">{{ anim.yesterdayDefect }}</div>
        <div class="wb-kpi-unit">
          双
          <span v-if="data" class="wb-kpi-rate">· {{ data.summary.yesterday_defect_rate }}%</span>
        </div>
      </div>
      <div class="wb-kpi accent-rush">
        <div class="wb-kpi-label">急单</div>
        <div class="wb-kpi-value">{{ anim.rush }}</div>
        <div class="wb-kpi-unit">单</div>
      </div>
      <div class="wb-kpi accent-mat">
        <div class="wb-kpi-label">待料卡住</div>
        <div class="wb-kpi-value">{{ anim.materialBlocked }}</div>
        <div class="wb-kpi-unit">单</div>
      </div>
    </section>

    <p class="wb-today">
      今日已报
      <strong>合格 {{ data?.summary?.today_reported?.qualified ?? 0 }}</strong>
      ·
      <strong>不良 {{ data?.summary?.today_reported?.defect ?? 0 }}</strong>
      双
    </p>

    <div class="wb-main">
      <section class="wb-focus">
        <div class="wb-section-title">焦点在制</div>
        <div v-if="!pageOrders.length" class="wb-empty">当前无在制焦点单</div>
        <ul v-else class="wb-order-list">
          <li
            v-for="row in pageOrders"
            :key="row.id"
            class="wb-order"
            :class="[`sig-${row.signal}`, { pulse: row.signal === 'rush' || row.signal === 'delivery_risk' }]"
          >
            <div class="wb-order-main">
              <div class="wb-order-no">{{ row.header_no || row.order_no }}</div>
              <div class="wb-order-meta">
                <span>{{ row.product_code || '—' }}</span>
                <span v-if="row.customer_name" class="wb-order-cust">{{ row.customer_name }}</span>
              </div>
            </div>
            <div class="wb-order-due" :class="{ hot: row.at_risk || row.is_rush }">
              {{ row.delivery_label }}
            </div>
            <div class="wb-order-progress">
              <div class="wb-bar-track">
                <div
                  class="wb-bar-fill"
                  :style="{ width: Math.min(100, Number(row.overall_percent) || 0) + '%' }"
                />
              </div>
              <div class="wb-bottleneck">
                <template v-if="row.bottleneck">
                  {{ row.bottleneck.process_name }}
                  {{ row.bottleneck.completed_qty }}/{{ row.bottleneck.plan_qty }}
                </template>
                <template v-else>已齐工序</template>
                <span v-if="row.material_blocked" class="wb-tag-mat">待料</span>
                <span v-if="row.is_rush" class="wb-tag-rush">插单</span>
              </div>
            </div>
          </li>
        </ul>
        <div v-if="pageCount > 1" class="wb-pages">
          <span
            v-for="i in pageCount"
            :key="i"
            class="wb-dot"
            :class="{ on: i - 1 === pageIndex }"
          />
        </div>
      </section>

      <section class="wb-levels-panel">
        <div class="wb-section-title">工序水位</div>
        <div v-if="!visibleLevels.length" class="wb-empty sm">暂无工序数据</div>
        <ul v-else class="wb-levels">
          <li
            v-for="p in visibleLevels"
            :key="p.process_name"
            class="wb-level"
            :class="{ bottleneck: p.is_bottleneck }"
          >
            <div class="wb-level-copy">
              <div class="wb-level-name">
                {{ p.process_name }}
                <span v-if="p.is_bottleneck" class="wb-level-flag">堵点</span>
              </div>
              <div class="wb-level-sub">在制剩余 · 昨日 {{ p.yesterday_qualified }}</div>
            </div>
            <div class="wb-level-remain">{{ p.remain_qty }}</div>
          </li>
        </ul>
      </section>
    </div>

    <footer class="wb-mats-bar">
      <div class="wb-mats-title">待料提醒</div>
      <div v-if="!materialBlocks.length" class="wb-mats-empty">物料齐套，可正常排产</div>
      <ul v-else class="wb-mats">
        <li v-for="m in materialBlocks" :key="m.order_id" class="wb-mat">
          <span class="wb-mat-no">{{ m.order_no }}</span>
          <span class="wb-mat-label">{{ m.label }}</span>
        </li>
      </ul>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type FocusOrder = {
  id: number
  order_no: string
  header_no?: string | null
  customer_name?: string
  product_code?: string
  delivery_label: string
  overall_percent: number
  bottleneck?: {
    process_name: string
    plan_qty: number
    completed_qty: number
  } | null
  at_risk: boolean
  is_rush: boolean
  material_blocked: boolean
  signal: string
}

type ProcessLevel = {
  process_name: string
  remain_qty: number
  yesterday_qualified: number
  is_bottleneck: boolean
}

type DisplayData = {
  factory_name: string
  summary: {
    yesterday_qualified: number
    yesterday_defect: number
    yesterday_defect_rate: number
    rush_orders: number
    material_blocked_orders: number
    today_reported: { qualified: number; defect: number }
  }
  focus_orders: FocusOrder[]
  process_levels: ProcessLevel[]
  material_blocks: Array<{
    order_id: number
    order_no: string
    label: string
  }>
}

const PAGE_SIZE = 6
const REFRESH_MS = 30000
const PAGE_MS = 12000
const IDLE_MS = 3000

const auth = useAuthStore()
const router = useRouter()
const data = ref<DisplayData | null>(null)
const offline = ref(false)
const lastOkAt = ref<number | null>(null)
const clockText = ref('')
const idle = ref(false)
const pageIndex = ref(0)
const anim = reactive({
  yesterdayQualified: 0,
  yesterdayDefect: 0,
  rush: 0,
  materialBlocked: 0,
})

let refreshTimer: number | undefined
let pageTimer: number | undefined
let clockTimer: number | undefined
let idleTimer: number | undefined
let animRaf = 0

const focusOrders = computed(() => data.value?.focus_orders || [])
const pageCount = computed(() => Math.max(1, Math.ceil(focusOrders.value.length / PAGE_SIZE)))
const pageOrders = computed(() => {
  const start = pageIndex.value * PAGE_SIZE
  return focusOrders.value.slice(start, start + PAGE_SIZE)
})
const visibleLevels = computed(() =>
  (data.value?.process_levels || []).filter(
    (p) => p.remain_qty > 0 || p.yesterday_qualified > 0 || p.is_bottleneck,
  ),
)
const materialBlocks = computed(() => data.value?.material_blocks || [])
const defectHigh = computed(() => (data.value?.summary.yesterday_defect_rate || 0) >= 3)
const refreshText = computed(() => {
  if (!lastOkAt.value) return '加载中…'
  const sec = Math.max(0, Math.floor((Date.now() - lastOkAt.value) / 1000))
  if (sec < 10) return '刚刚更新'
  if (sec < 60) return `${sec} 秒前更新`
  return `${Math.floor(sec / 60)} 分钟前更新`
})

function bumpIdle() {
  idle.value = false
  if (idleTimer) window.clearTimeout(idleTimer)
  idleTimer = window.setTimeout(() => {
    idle.value = true
  }, IDLE_MS)
}

function tickClock() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  clockText.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function animateTo(target: {
  yesterdayQualified: number
  yesterdayDefect: number
  rush: number
  materialBlocked: number
}) {
  const from = { ...anim }
  const start = performance.now()
  const dur = 700
  if (animRaf) cancelAnimationFrame(animRaf)
  const step = (t: number) => {
    const p = Math.min(1, (t - start) / dur)
    const e = 1 - Math.pow(1 - p, 3)
    anim.yesterdayQualified = Math.round(from.yesterdayQualified + (target.yesterdayQualified - from.yesterdayQualified) * e)
    anim.yesterdayDefect = Math.round(from.yesterdayDefect + (target.yesterdayDefect - from.yesterdayDefect) * e)
    anim.rush = Math.round(from.rush + (target.rush - from.rush) * e)
    anim.materialBlocked = Math.round(
      from.materialBlocked + (target.materialBlocked - from.materialBlocked) * e,
    )
    if (p < 1) animRaf = requestAnimationFrame(step)
  }
  animRaf = requestAnimationFrame(step)
}

async function load() {
  try {
    const res: any = await http.get('/workshop-display', { silent: true } as any)
    data.value = res.data
    offline.value = false
    lastOkAt.value = Date.now()
    const s = res.data.summary
    animateTo({
      yesterdayQualified: s.yesterday_qualified || 0,
      yesterdayDefect: s.yesterday_defect || 0,
      rush: s.rush_orders || 0,
      materialBlocked: s.material_blocked_orders || 0,
    })
    if (pageIndex.value >= pageCount.value) pageIndex.value = 0
  } catch {
    offline.value = true
  }
}

function nextPage() {
  if (pageCount.value <= 1) return
  pageIndex.value = (pageIndex.value + 1) % pageCount.value
}

onMounted(async () => {
  await auth.refreshPermissions()
  if (!auth.hasPermission('menu.board')) {
    router.replace('/admin')
    return
  }
  tickClock()
  clockTimer = window.setInterval(tickClock, 1000)
  bumpIdle()
  await load()
  refreshTimer = window.setInterval(load, REFRESH_MS)
  pageTimer = window.setInterval(nextPage, PAGE_MS)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (pageTimer) clearInterval(pageTimer)
  if (clockTimer) clearInterval(clockTimer)
  if (idleTimer) clearTimeout(idleTimer)
  if (animRaf) cancelAnimationFrame(animRaf)
})
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@500;700;900&family=Oswald:wght@500;700&display=swap');

body:has(.workshop-board) {
  overflow: hidden;
}

body:has(.workshop-board) #app {
  max-width: none;
  margin: 0;
  height: 100vh;
  overflow: hidden;
  background: #f3f5f7;
}
</style>

<style scoped>
.workshop-board {
  --wb-bg: #f3f5f7;
  --wb-ink: #121417;
  --wb-muted: #5c6570;
  --wb-line: #d7dde3;
  --wb-ok: #1f6b4a;
  --wb-warn: #c45c16;
  --wb-rush: #b42318;
  --wb-mat: #2f5f8a;
  --wb-paper: #eef1f4;
  box-sizing: border-box;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px 32px 20px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.65), transparent 120px),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 31px,
      rgba(18, 20, 23, 0.035) 31px,
      rgba(18, 20, 23, 0.035) 32px
    ),
    var(--wb-bg);
  color: var(--wb-ink);
  font-family: 'Noto Sans SC', 'PingFang SC', sans-serif;
  cursor: default;
  user-select: none;
}

.workshop-board.is-idle {
  cursor: none;
}

.wb-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex: 0 0 auto;
}

.wb-brand {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.wb-brand-mark {
  font-size: 40px;
  font-weight: 900;
  letter-spacing: 0.08em;
  line-height: 1;
}

.wb-brand-sub {
  font-size: 18px;
  color: var(--wb-muted);
  font-weight: 500;
}

.wb-header-meta {
  text-align: right;
}

.wb-clock {
  font-family: 'Oswald', 'Noto Sans SC', sans-serif;
  font-size: 34px;
  font-weight: 700;
  letter-spacing: 0.04em;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.wb-status {
  margin-top: 6px;
  font-size: 16px;
  color: var(--wb-muted);
}

.wb-status.err {
  color: var(--wb-rush);
  font-weight: 700;
}

.wb-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  flex: 0 0 auto;
}

.wb-kpi {
  padding: 14px 18px 12px;
  border-left: 6px solid var(--wb-ok);
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.35));
}

.wb-kpi.warn {
  border-left-color: var(--wb-rush);
}

.wb-kpi.accent-rush {
  border-left-color: var(--wb-rush);
}

.wb-kpi.accent-mat {
  border-left-color: var(--wb-mat);
}

.wb-kpi-label {
  font-size: 18px;
  font-weight: 700;
  color: var(--wb-muted);
}

.wb-kpi-value {
  margin-top: 2px;
  font-family: 'Oswald', 'Noto Sans SC', sans-serif;
  font-size: 72px;
  font-weight: 700;
  line-height: 0.95;
  font-variant-numeric: tabular-nums;
}

.wb-kpi-unit {
  margin-top: 2px;
  font-size: 16px;
  color: var(--wb-muted);
}

.wb-kpi-rate {
  margin-left: 4px;
}

.wb-today {
  margin: 0;
  font-size: 17px;
  color: var(--wb-muted);
  flex: 0 0 auto;
}

.wb-today strong {
  color: var(--wb-ink);
  font-weight: 700;
}

/* 中区：左焦点订单 + 右工序水位，互不嵌套 */
.wb-main {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.85fr);
  gap: 22px;
  overflow: hidden;
}

.wb-section-title {
  font-size: 20px;
  font-weight: 900;
  letter-spacing: 0.06em;
  margin-bottom: 12px;
  flex: 0 0 auto;
}

.wb-focus,
.wb-levels-panel {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.wb-order-list,
.wb-levels {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.wb-order {
  display: grid;
  grid-template-columns: minmax(140px, 1.1fr) 130px minmax(200px, 1.3fr);
  gap: 14px;
  align-items: center;
  padding: 12px 14px;
  border-left: 8px solid var(--wb-ok);
  background: rgba(255, 255, 255, 0.72);
  flex: 0 0 auto;
}

.wb-order.sig-rush {
  border-left-color: var(--wb-rush);
  background: rgba(180, 35, 24, 0.08);
}

.wb-order.sig-delivery_risk {
  border-left-color: var(--wb-warn);
  background: rgba(196, 92, 22, 0.08);
}

.wb-order.sig-material_block {
  border-left-color: var(--wb-mat);
  background: rgba(47, 95, 138, 0.08);
}

.wb-order.pulse {
  animation: wb-pulse 2.4s ease-in-out infinite;
}

@keyframes wb-pulse {
  0%,
  100% {
    filter: brightness(1);
  }
  50% {
    filter: brightness(0.97);
  }
}

.wb-order-no {
  font-family: 'Oswald', 'Noto Sans SC', sans-serif;
  font-size: 36px;
  font-weight: 700;
  line-height: 1;
}

.wb-order-meta {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 16px;
  color: var(--wb-muted);
}

.wb-order-due {
  font-size: 26px;
  font-weight: 900;
  text-align: center;
}

.wb-order-due.hot {
  color: var(--wb-rush);
}

.wb-bar-track {
  height: 12px;
  background: var(--wb-paper);
  overflow: hidden;
}

.wb-bar-fill {
  height: 100%;
  background: var(--wb-ok);
  transition: width 0.8s ease;
}

.wb-order.sig-rush .wb-bar-fill,
.wb-order.sig-delivery_risk .wb-bar-fill {
  background: var(--wb-warn);
}

.wb-bottleneck {
  margin-top: 6px;
  font-size: 18px;
  font-weight: 700;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.wb-tag-mat,
.wb-tag-rush,
.wb-level-flag {
  font-size: 13px;
  font-weight: 900;
  padding: 2px 8px;
  letter-spacing: 0.08em;
  color: #fff;
}

.wb-tag-mat {
  background: var(--wb-mat);
}

.wb-tag-rush,
.wb-level-flag {
  background: var(--wb-rush);
}

.wb-level-flag {
  background: var(--wb-warn);
}

.wb-pages {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 10px;
  flex: 0 0 auto;
}

.wb-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c5ccd4;
}

.wb-dot.on {
  background: var(--wb-ink);
}

.wb-level {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-left: 6px solid transparent;
  background: rgba(255, 255, 255, 0.72);
  flex: 0 0 auto;
}

.wb-level.bottleneck {
  border-left-color: var(--wb-warn);
  background: rgba(196, 92, 22, 0.1);
}

.wb-level-copy {
  min-width: 0;
}

.wb-level-name {
  font-size: 22px;
  font-weight: 900;
  display: flex;
  align-items: center;
  gap: 8px;
}

.wb-level-sub {
  margin-top: 4px;
  font-size: 14px;
  color: var(--wb-muted);
}

.wb-level-remain {
  flex: 0 0 auto;
  font-family: 'Oswald', 'Noto Sans SC', sans-serif;
  font-size: 44px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

/* 底栏：待料通栏，与中区完全分离 */
.wb-mats-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 0 0;
  border-top: 2px solid var(--wb-line);
  min-height: 72px;
}

.wb-mats-title {
  flex: 0 0 auto;
  font-size: 20px;
  font-weight: 900;
  letter-spacing: 0.06em;
  color: var(--wb-mat);
  padding-left: 10px;
  border-left: 6px solid var(--wb-mat);
}

.wb-mats-empty {
  font-size: 18px;
  font-weight: 700;
  color: var(--wb-muted);
}

.wb-mats {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
}

.wb-mat {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 8px 14px;
  border-left: 5px solid var(--wb-mat);
  background: rgba(47, 95, 138, 0.08);
}

.wb-mat-no {
  font-family: 'Oswald', 'Noto Sans SC', sans-serif;
  font-size: 26px;
  font-weight: 700;
}

.wb-mat-label {
  font-size: 16px;
  font-weight: 700;
  color: var(--wb-mat);
}

.wb-empty {
  padding: 40px 16px;
  text-align: center;
  font-size: 22px;
  font-weight: 700;
  color: var(--wb-muted);
  background: rgba(255, 255, 255, 0.5);
}

.wb-empty.sm {
  padding: 24px 12px;
  font-size: 18px;
}

@media (max-width: 1200px) {
  .workshop-board {
    height: auto;
    overflow: auto;
  }
  .wb-main {
    grid-template-columns: 1fr;
    overflow: visible;
  }
  .wb-focus,
  .wb-levels-panel {
    overflow: visible;
  }
  .wb-order-list,
  .wb-levels {
    overflow: visible;
  }
  .wb-kpi-value {
    font-size: 56px;
  }
  .wb-order {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .wb-order-due {
    text-align: left;
  }
  .wb-mats-bar {
    flex-wrap: wrap;
  }
}
</style>
