<template>
  <div class="page home">
    <header class="home-hero">
      <p class="page-kicker">铁玉兰管家</p>
      <h1 class="home-greeting">{{ greeting }}，{{ firstName }}</h1>
      <p class="home-date">{{ dateLabel }}</p>
    </header>

    <template v-if="auth.isWorker && overview">
      <section class="home-today" :class="{ 'home-today--leader': overview.mode === 'leader' }">
        <div class="home-today__head">
          <div>
            <div class="home-today__eyebrow">{{ overview.mode === 'leader' ? overview.team_name || '我的班组' : '今日计件' }}</div>
            <div class="home-today__title">{{ overview.mode === 'leader' ? '今日班组' : '今天完成了多少' }}</div>
          </div>
          <span class="home-today__status"><van-icon name="notes-o" /> {{ overview.today.record_count }} 条</span>
        </div>
        <div class="home-today__metrics">
          <div>
            <strong class="h5-stat-num">{{ overview.today.qualified }}</strong>
            <span>合格</span>
          </div>
          <div>
            <strong class="h5-stat-num" :class="{ danger: overview.today.defects > 0 }">{{ overview.today.defects }}</strong>
            <span>不良</span>
          </div>
          <div v-if="overview.mode === 'leader'">
            <strong class="h5-stat-num">{{ overview.today.reporter_count }}</strong>
            <span>已报工</span>
          </div>
          <div v-else>
            <strong class="h5-stat-num">{{ overview.today.record_count }}</strong>
            <span>记录</span>
          </div>
        </div>
      </section>

      <section v-if="overview.mode === 'worker' && overview.month" class="home-month">
        <div>
          <div class="home-month__label">{{ overview.month.is_locked ? '本月工资已锁定' : '本月待核算' }}</div>
          <div class="home-month__hint">{{ overview.month.is_locked ? '可前往工资页核对确认' : '实际以月结锁定为准' }}</div>
        </div>
        <strong class="h5-stat-num">¥{{ Number(overview.month.amount || 0).toFixed(2) }}</strong>
      </section>

      <section v-if="overview.mode === 'leader' && overview.today.defects > 0" class="home-alert">
        <van-icon name="warning-o" />
        今日有 {{ overview.today.defects }} 件不良，请及时关注。
      </section>

      <router-link v-if="overview.mode === 'leader'" to="/my-team" class="home-team-shortcut">
        <div class="home-team-shortcut__copy">
          <span>班组管理</span>
          <strong>组员 {{ overview.team_member_count || 0 }} 人</strong>
          <em>管理成员，查看本组动态</em>
        </div>
        <van-icon name="arrow" aria-hidden="true" />
      </router-link>

      <div class="home-section-head">
        <p class="h5-section-label">{{ overview.mode === 'leader' ? '班组动态' : '最近计件' }}</p>
        <router-link :to="overview.mode === 'leader' ? '/my-team' : '/my-work-logs'">查看全部</router-link>
      </div>
      <div v-if="!overview.recent.length" class="home-empty">今天还没有计件记录</div>
      <div v-else class="home-records">
        <article v-for="row in overview.recent" :key="row.id" class="h5-list-card home-record">
          <div class="home-record__main">
            <div class="home-record__title">
              <span v-if="overview.mode === 'leader'" class="home-record__name">{{ row.worker_name }}</span>
              {{ row.process_name }}
            </div>
            <div class="home-record__meta">{{ typeLabel(row.report_type) }} · {{ formatTime(row.created_at) }}</div>
          </div>
          <strong class="h5-stat-num home-record__qty">{{ row.qty }}</strong>
        </article>
      </div>
    </template>

    <!-- 管理端保留全厂今日产量。 -->
    <section v-else-if="today" class="home-yield" aria-label="今日产量">
      <div class="home-yield__label">今日产量</div>
      <div class="home-yield__metrics">
        <div class="home-yield__item">
          <span class="h5-stat-num home-yield__num">{{ today.total_qualified ?? 0 }}</span>
          <span class="home-yield__cap">合格</span>
        </div>
        <div class="home-yield__sep" />
        <div class="home-yield__item">
          <span class="h5-stat-num home-yield__num" :class="{ danger: (today.total_defect ?? 0) > 0 }">
            {{ today.total_defect ?? 0 }}
          </span>
          <span class="home-yield__cap">不良</span>
        </div>
      </div>
    </section>

    <BossOverview v-if="!auth.isWorker" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import BossOverview from '@/components/BossOverview.vue'

const auth = useAuthStore()
const today = ref<any>(null)
const overview = ref<any>(null)

const firstName = computed(() => {
  const n = (auth.displayName || '同事').trim()
  return n.length > 6 ? n.slice(0, 6) : n
})

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const dateLabel = computed(() => {
  const d = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getMonth() + 1}月${d.getDate()}日 · 周${week}`
})

onMounted(async () => {
  try {
    if (auth.isWorker) {
      const res: any = await http.get('/home/overview')
      overview.value = res.data
      return
    }
    const res: any = await http.get('/progress/today')
    today.value = res.data
  } catch {
    if (auth.isWorker) overview.value = null
    else today.value = null
  }
})

function typeLabel(value?: string) {
  return ({ normal: '正常', group: '集体', rework: '返修', supplement: '补数', tail: '尾数' } as Record<string, string>)[value || ''] || '计件'
}

function formatTime(value?: string) {
  const match = String(value || '').match(/T(\d{2}):(\d{2})/)
  return match ? `${match[1]}:${match[2]}` : '刚刚'
}
</script>

<style scoped>
.home-hero {
  margin-bottom: 18px;
  animation: h5-rise 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.home-greeting {
  font-family: var(--ws-font-display);
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.035em;
  line-height: 1.15;
  margin: 0 0 6px;
  color: var(--ws-ink);
}

.home-date {
  margin: 0;
  font-size: 15px;
  color: var(--ws-muted);
  font-weight: 500;
}

.home-yield {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 4px;
  background: var(--ws-bg-elevated);
  border-radius: var(--ws-radius);
  box-shadow: var(--ws-shadow-soft);
  animation: h5-rise 0.45s cubic-bezier(0.22, 1, 0.36, 1) 0.04s both;
}

.home-yield__label {
  font-size: 15px;
  font-weight: 600;
  color: var(--ws-ink);
  flex-shrink: 0;
}

.home-yield__metrics {
  display: flex;
  align-items: center;
  gap: 14px;
}

.home-yield__item {
  display: flex;
  align-items: baseline;
  gap: 5px;
}

.home-yield__num {
  font-size: 22px;
  color: var(--ws-ink);
  letter-spacing: -0.03em;
}

.home-yield__num.danger {
  color: var(--ws-danger);
}

.home-yield__cap {
  font-size: 12px;
  font-weight: 500;
  color: var(--ws-muted);
}

.home-yield__sep {
  width: 1px;
  height: 16px;
  background: var(--ws-line);
}

.home-today {
  margin-bottom: 12px;
  border-radius: var(--ws-radius-lg);
  padding: 20px;
  background: linear-gradient(145deg, #4da0ff, var(--ws-primary) 62%, var(--ws-primary-dark));
  box-shadow: 0 12px 28px rgba(0, 118, 255, 0.2);
  color: #fff;
}

.home-today__head,
.home-section-head,
.home-month {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.home-today__eyebrow {
  margin-bottom: 4px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
  font-weight: 600;
}

.home-today__title {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.home-today__status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 7px;
  padding: 5px 7px;
  background: rgba(255, 255, 255, 0.16);
  color: rgba(255, 255, 255, 0.9);
  font-size: 11px;
  font-weight: 700;
}

.home-today__metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 22px;
}

.home-today__metrics > div {
  min-width: 0;
}

.home-today__metrics strong,
.home-today__metrics span {
  display: block;
}

.home-today__metrics strong {
  font-size: 27px;
  letter-spacing: -0.04em;
}

.home-today__metrics strong.danger {
  color: #ffd3cf;
}

.home-today__metrics span {
  margin-top: 3px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
}

.home-month {
  margin-bottom: 20px;
  border-radius: var(--ws-radius);
  padding: 15px 16px;
  background: var(--ws-bg-elevated);
  box-shadow: var(--ws-shadow-soft);
}

.home-month__label {
  color: var(--ws-ink);
  font-size: 15px;
  font-weight: 700;
}

.home-month__hint {
  margin-top: 3px;
  color: var(--ws-muted);
  font-size: 12px;
}

.home-month > strong {
  color: var(--ws-primary);
  font-size: 20px;
}

.home-alert {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 18px;
  border-radius: var(--ws-radius-sm);
  padding: 12px 14px;
  background: rgba(255, 159, 10, 0.11);
  color: #a86300;
  font-size: 13px;
  font-weight: 600;
}

.home-team-shortcut {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  border: 1px solid rgba(0, 118, 255, 0.1);
  border-radius: var(--ws-radius);
  padding: 15px 16px;
  background: var(--ws-bg-elevated);
  box-shadow: var(--ws-shadow-soft);
  color: inherit;
  text-decoration: none;
}

.home-team-shortcut:active {
  transform: scale(0.98);
}

.home-team-shortcut__copy {
  display: grid;
  gap: 3px;
}

.home-team-shortcut__copy > span {
  color: var(--ws-primary);
  font-size: 12px;
  font-weight: 700;
}

.home-team-shortcut__copy > strong {
  color: var(--ws-ink);
  font-size: 17px;
  letter-spacing: -0.02em;
}

.home-team-shortcut__copy > em {
  color: var(--ws-muted);
  font-size: 12px;
  font-style: normal;
}

.home-team-shortcut :deep(.van-icon) {
  color: var(--ws-muted);
  font-size: 17px;
}

.home-section-head {
  margin: 0 4px 8px;
}

.home-section-head .h5-section-label {
  margin: 0;
}

.home-section-head a {
  color: var(--ws-primary);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.home-records {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.home-record {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 0;
  padding: 14px 16px;
}

.home-record__main {
  min-width: 0;
  flex: 1;
}

.home-record__title {
  overflow: hidden;
  color: var(--ws-ink);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-record__name {
  margin-right: 5px;
  color: var(--ws-primary);
}

.home-record__meta,
.home-empty {
  margin-top: 4px;
  color: var(--ws-muted);
  font-size: 12px;
}

.home-record__qty {
  color: var(--ws-ink);
  font-size: 19px;
}

.home-empty {
  border-radius: var(--ws-radius);
  padding: 28px 16px;
  background: rgba(255, 255, 255, 0.55);
  text-align: center;
}
</style>
