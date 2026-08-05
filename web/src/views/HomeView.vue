<template>
  <div class="page home">
    <header class="home-hero">
      <p class="page-kicker">铁玉兰管家</p>
      <h1 class="home-greeting">{{ greeting }}，{{ firstName }}</h1>
      <p class="home-date">{{ dateLabel }}</p>
    </header>

    <!-- 产量收成一行白卡，不抢预警/盯单主角 -->
    <section v-if="today" class="home-yield" aria-label="今日产量">
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

    <BossOverview v-if="auth.actor !== 'worker'" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import BossOverview from '@/components/BossOverview.vue'

const auth = useAuthStore()
const today = ref<any>(null)

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
    const res: any = await http.get('/progress/today')
    today.value = res.data
  } catch {
    today.value = null
  }
})
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
</style>
