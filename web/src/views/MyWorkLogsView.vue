<template>
  <div class="page">
    <router-link to="/my-salary" class="worklogs-salary-link">
      <div>
        <span>本月收入</span>
        <strong>查看工资预估与结算明细</strong>
      </div>
      <van-icon name="arrow" aria-hidden="true" />
    </router-link>

    <van-tabs v-model:active="tab" shrink @change="load">
      <van-tab title="全部" name="" />
      <van-tab title="有效" name="valid" />
      <van-tab title="申诉中" name="appealed" />
    </van-tabs>

    <div v-if="loading" class="h5-empty">加载中…</div>
    <div v-else-if="!rows.length" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      暂无记录
    </div>
    <div v-else class="logs">
      <article v-for="(row, i) in rows" :key="row.id" class="h5-list-card log-card" :style="{ animationDelay: `${i * 0.04}s` }">
        <div class="h5-list-card__head">
          <div class="h5-list-card__title">{{ row.order_no }} · {{ row.process_name }}</div>
          <span class="h5-pill" :class="statusPill(row.status)">{{ statusLabel(row.status) }}</span>
        </div>
        <div class="log-card__meta">
          <span>{{ typeLabel(row.report_type) }}</span>
          <span class="log-card__dot">·</span>
          <template v-if="row.report_type === 'rework'">返修 {{ row.rework_qty }}</template>
          <template v-else>合格 {{ row.qualified_qty }}</template>
          <template v-if="row.color_name || row.size_value">
            <span class="log-card__dot">·</span>
            {{ row.color_name || '' }} {{ row.size_value || '' }}
          </template>
        </div>
        <div class="log-card__time">{{ formatTime(row.created_at) }}</div>
        <div v-if="row.review_note" class="log-card__note">备注：{{ row.review_note }}</div>
        <van-button
          v-if="row.status === 'valid'"
          size="small"
          round
          plain
          type="warning"
          class="log-card__action"
          @click="appeal(row)"
        >
          申诉
        </van-button>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'

const tab = ref('')
const rows = ref<any[]>([])
const loading = ref(false)

function statusLabel(s: string) {
  return ({ valid: '有效', appealed: '申诉中', void: '已作废', corrected: '已更正' } as any)[s] || s
}

function statusPill(s: string) {
  return (
    ({
      valid: 'h5-pill--ok',
      appealed: 'h5-pill--warn',
      void: 'h5-pill--danger',
      corrected: 'h5-pill--mute',
    } as any)[s] || 'h5-pill--mute'
  )
}

function typeLabel(t: string) {
  return (
    ({ normal: '正常', rework: '返修', group: '集体', supplement: '补数', tail: '尾数' } as any)[t] || t
  )
}

function formatTime(v?: string) {
  if (!v) return ''
  // Prefer raw YYYY-MM-DD to avoid timezone shifting the calendar day
  const m = String(v).match(/(\d{4})-(\d{2})-(\d{2})/)
  if (m) return `${m[1]}/${m[2]}/${m[3]}`
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 10)
  const yyyy = String(d.getFullYear())
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}`
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/work-logs', {
      params: {
        status: tab.value || undefined,
        page_size: 100,
      },
    })
    rows.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

async function appeal(row: any) {
  await showConfirmDialog({
    title: '提交申诉',
    message: `确认申诉计件记录 #${row.id}？申诉期间暂不计薪，等待主管审核。`,
  })
  const res: any = await http.post(`/work-logs/${row.id}/appeal`, {
    reason: '数量有误，请主管核实',
  })
  showToast(res.data?.message || '已申诉')
  await load()
}

onMounted(load)
</script>

<style scoped>
.worklogs-salary-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 2px 0 10px;
  border-radius: var(--ws-radius);
  padding: 14px 16px;
  background: var(--ws-primary-soft);
  color: inherit;
  text-decoration: none;
}

.worklogs-salary-link:active {
  transform: scale(0.98);
}

.worklogs-salary-link > div {
  display: grid;
  gap: 3px;
}

.worklogs-salary-link span {
  color: var(--ws-primary);
  font-size: 12px;
  font-weight: 700;
}

.worklogs-salary-link strong {
  color: var(--ws-ink);
  font-size: 15px;
}

.worklogs-salary-link :deep(.van-icon) {
  color: var(--ws-primary);
  font-size: 17px;
}

.logs {
  margin-top: 8px;
}

.log-card {
  animation: h5-rise 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.log-card__meta {
  font-size: 14px;
  color: var(--ws-ink-secondary);
  margin-top: 2px;
}

.log-card__dot {
  margin: 0 4px;
  color: var(--ws-muted);
}

.log-card__time {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ws-muted);
  font-variant-numeric: tabular-nums;
}

.log-card__note {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ws-muted);
  line-height: 1.4;
}

.log-card__action {
  margin-top: 12px;
}
</style>
