<template>
  <div class="page">
    <div class="h5-filter">
      <van-icon name="search" class="h5-filter__icon" />
      <input
        v-model="keyword"
        class="h5-filter__input"
        type="text"
        inputmode="search"
        enterkeyhint="search"
        placeholder="订单号 / 员工"
      />
      <button
        v-if="keyword"
        type="button"
        class="h5-filter__clear"
        aria-label="清除"
        @click="keyword = ''"
      >
        <van-icon name="cross" />
      </button>
    </div>

    <van-tabs v-model:active="tab" shrink @change="load">
      <van-tab title="全部" name="" />
      <van-tab title="有效" name="valid" />
      <van-tab title="申诉中" name="appealed" />
      <van-tab title="作废" name="void" />
    </van-tabs>

    <div v-if="teamEmpty" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      尚未配置班组，请联系管理员
    </div>
    <div v-else-if="loading" class="h5-empty">加载中…</div>
    <div v-else-if="!filtered.length" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      {{ keyword.trim() ? '无匹配记录' : '暂无报工' }}
    </div>
    <div v-else class="logs">
      <article v-for="(row, i) in filtered" :key="row.id" class="h5-list-card log-card" :style="{ animationDelay: `${i * 0.03}s` }">
        <div class="h5-list-card__head">
          <div class="h5-list-card__title">{{ row.worker_name }} · {{ row.process_name }}</div>
          <span class="h5-pill" :class="statusPill(row.status)">{{ statusLabel(row.status) }}</span>
        </div>
        <div class="log-card__meta">
          {{ row.order_no }}
          <span class="log-card__dot">·</span>
          {{ typeLabel(row.report_type) }}
          <span class="log-card__dot">·</span>
          <template v-if="row.report_type === 'rework'">返修 {{ row.rework_qty }}</template>
          <template v-else>合格 {{ row.qualified_qty }}</template>
        </div>
        <div class="log-card__time">{{ formatTime(row.created_at) }}</div>
        <div v-if="canCorrect && (row.status === 'valid' || row.status === 'appealed')" class="log-card__actions">
          <van-button size="small" round plain type="danger" @click="voidLog(row)">作废</van-button>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const tab = ref('')
const rows = ref<any[]>([])
const loading = ref(false)
const keyword = ref('')
const teamEmpty = ref(false)

const canCorrect = computed(() => auth.hasPermission('btn.work_logs.correct'))

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => {
    const hay = [r.order_no, r.worker_name, r.process_name].map((x) => String(x || '').toLowerCase()).join(' ')
    return hay.includes(q)
  })
})

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
  const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (m) return `${m[1]}/${m[2]}/${m[3]}`
  return String(v).slice(0, 16).replace('T', ' ')
}

async function load() {
  loading.value = true
  try {
    // 探测班组是否为空（组长）
    if (auth.isTeamScoped) {
      const w: any = await http.get('/workers')
      if (w.data?.team_empty) {
        teamEmpty.value = true
        rows.value = []
        return
      }
      teamEmpty.value = false
    }
    const res: any = await http.get('/work-logs', {
      params: {
        status: tab.value || undefined,
        page_size: 100,
      },
    })
    rows.value = res.data.items || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function voidLog(row: any) {
  try {
    await showConfirmDialog({ title: '作废报工', message: `确认作废 #${row.id}？` })
    await http.patch(`/work-logs/${row.id}`, { status: 'void' })
    showToast('已作废')
    await load()
  } catch (e: any) {
    if (e !== 'cancel') showToast(e?.response?.data?.detail || '操作失败')
  }
}

onMounted(load)
</script>

<style scoped>
.logs {
  margin-top: 8px;
}

.log-card__meta {
  margin-top: 4px;
  font-size: 13px;
  color: var(--ws-ink-secondary);
}

.log-card__dot {
  margin: 0 4px;
  color: var(--ws-muted);
}

.log-card__time {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ws-muted);
}

.log-card__actions {
  margin-top: 10px;
}
</style>
