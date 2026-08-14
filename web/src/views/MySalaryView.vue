<template>
  <div class="page">
    <div class="salary-period">
      <span>工资月份</span>
      <button type="button" class="salary-period__picker" @click="openPicker">
        {{ monthLabel }}
        <van-icon name="calendar-o" />
      </button>
    </div>

    <van-popup
      v-model:show="pickerShow"
      position="bottom"
      round
      teleport="body"
      :z-index="3000"
      :style="{ minHeight: '320px' }"
    >
      <div class="month-cal">
        <div class="month-cal__title">选择月份</div>
        <div class="month-cal__head">
          <button type="button" class="month-cal__nav" aria-label="上一年" @click="shiftYear(-1)">
            ‹
          </button>
          <div class="month-cal__year">{{ viewYear }}年</div>
          <button
            type="button"
            class="month-cal__nav"
            aria-label="下一年"
            :disabled="!canNextYear"
            @click="shiftYear(1)"
          >
            ›
          </button>
        </div>
        <div class="month-cal__grid">
          <button
            v-for="m in months"
            :key="m"
            type="button"
            class="month-cal__cell"
            :class="{
              active: isSelected(viewYear, m),
              disabled: isFuture(viewYear, m),
              current: isCurrent(viewYear, m),
            }"
            :disabled="isFuture(viewYear, m)"
            @click="selectMonth(viewYear, m)"
          >
            {{ m }}月
          </button>
        </div>
      </div>
    </van-popup>

    <template v-if="data">
      <section class="salary-hero salary-hero--statement" :class="{ 'salary-hero--locked': data.is_locked }">
        <div class="salary-hero__top">
          <div>
            <div class="salary-hero__label">{{ data.is_locked ? '应发合计' : '本月预估' }}</div>
            <div class="h5-stat-num salary-hero__amount">
              <span class="salary-hero__yen">¥</span>{{ Number(data.total_wage ?? data.total_piece_wage).toFixed(2) }}
            </div>
          </div>
          <div class="salary-hero__status">
            <van-icon :name="data.is_locked ? 'passed' : 'clock-o'" />
            {{ data.is_locked ? '已月结' : '待核算' }}
          </div>
        </div>
        <div class="salary-hero__notice">
          <van-icon :name="data.is_locked ? 'passed' : 'info-o'" />
          <p>{{ data.is_locked ? '本月工资已锁定，请核对明细后确认。' : '当前为实时预估，单价、补数、返修与审核调整后可能变化，实际以月结锁定为准。' }}</p>
        </div>
      </section>

      <div class="salary-summary">
        <div class="salary-summary__item">
          <span>底薪</span>
          <strong class="h5-stat-num">¥{{ Number(data.base_salary || 0).toFixed(2) }}</strong>
        </div>
        <div class="salary-summary__item">
          <span>{{ data.is_locked ? '计件金额' : '计件预估' }}</span>
          <strong class="h5-stat-num">¥{{ Number(data.payable_piece_wage ?? data.total_piece_wage).toFixed(2) }}</strong>
        </div>
      </div>

      <div class="salary-detail-head">
        <div>
          <p class="h5-section-label">计件明细</p>
          <span>{{ (data.details || []).length }} 条</span>
        </div>
        <router-link to="/my-work-logs">查看全部记录</router-link>
      </div>
      <div v-if="!(data.details || []).length" class="h5-empty">
        <div class="h5-empty__mark">—</div>
        暂无明细
      </div>
      <div v-else class="salary-timeline">
        <section v-for="group in groupedDetails" :key="group.key" class="salary-day">
          <div class="salary-day__head">
            <span>{{ group.label }}</span>
            <em>{{ data.is_locked ? '当日金额' : '当日预估' }} ¥{{ group.amount.toFixed(2) }}</em>
          </div>
          <div class="salary-day__entries">
            <article v-for="d in group.items" :key="d.work_log_id" class="h5-list-card salary-detail">
              <div class="h5-list-card__head">
                <div class="h5-list-card__title">{{ d.order_no }} · {{ d.process_name }}</div>
                <strong class="h5-stat-num salary-detail__amount">¥{{ Number(d.amount).toFixed(2) }}</strong>
              </div>
              <div class="salary-detail__meta">
                <span class="h5-pill" :class="detailPill(d.report_type)">{{ detailTypeLabel(d.report_type) }}</span>
                <span>{{ detailQuantity(d) }}</span>
                <span v-if="d.unit_price !== undefined">× ¥{{ Number(d.unit_price).toFixed(2) }}</span>
              </div>
            </article>
          </div>
        </section>
      </div>

      <div v-if="data.acknowledged" class="ack-ok">
        <van-icon name="passed" />
        已确认签字
        <template v-if="data.acknowledgement?.confirmed_at"> · {{ formatTime(data.acknowledgement.confirmed_at) }} </template>
      </div>
      <div v-else-if="data.is_locked" class="ack-box">
        <div class="ack-box__title">工资确认</div>
        <p class="muted ack-box__hint">本月已月结锁定。请核对明细后签字确认；确认姓名须与档案姓名一致。</p>
        <van-field v-model="confirmName" label="确认姓名" :placeholder="`请填写 ${auth.displayName || '本人姓名'}`" />
        <div class="sig-wrap">
          <div class="muted sig-label">手写签名（可选）</div>
          <canvas ref="canvasRef" class="sig-canvas" width="320" height="120" @touchstart.prevent="onSigStart" @touchmove.prevent="onSigMove" @touchend.prevent="onSigEnd" @mousedown.prevent="onSigStart" @mousemove.prevent="onSigMove" @mouseup.prevent="onSigEnd" @mouseleave.prevent="onSigEnd" />
          <van-button size="small" plain round class="sig-clear" @click="clearSig">清除签名</van-button>
        </div>
        <van-checkbox v-model="agree" shape="square" class="ack-check">本人已核对上述工资明细，确认无误</van-checkbox>
        <van-button type="primary" block round :loading="confirming" :disabled="!agree" @click="confirm">签字确认</van-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const now = new Date()
const currentYear = now.getFullYear()
const currentMonth = now.getMonth() + 1
const month = ref(`${currentYear}-${String(currentMonth).padStart(2, '0')}`)
const pickerShow = ref(false)
const viewYear = ref(currentYear)
const minYear = currentYear - 5
const months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
const data = ref<any>(null)
const confirmName = ref('')
const agree = ref(false)
const confirming = ref(false)
const canvasRef = ref<HTMLCanvasElement | null>(null)
let drawing = false
let hasStroke = false

const monthLabel = computed(() => {
  const [y, m] = month.value.split('-')
  if (!y || !m) return month.value
  return `${y}年${Number(m)}月`
})

const groupedDetails = computed(() => {
  const groups = new Map<string, { key: string; label: string; amount: number; items: any[] }>()
  const details = [...(data.value?.details || [])].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  for (const detail of details) {
    const key = String(detail.created_at || '').slice(0, 10) || 'unknown'
    const group = groups.get(key) || {
      key,
      label: formatDetailDate(detail.created_at),
      amount: 0,
      items: [],
    }
    group.items.push(detail)
    group.amount += Number(detail.amount || 0)
    groups.set(key, group)
  }
  return [...groups.values()]
})

const canNextYear = computed(() => viewYear.value < currentYear)

function openPicker() {
  const [y] = month.value.split('-')
  const parsed = Number(y)
  viewYear.value = Number.isFinite(parsed) ? parsed : currentYear
  pickerShow.value = true
}

function shiftYear(delta: number) {
  const next = viewYear.value + delta
  if (next < minYear || next > currentYear) return
  viewYear.value = next
}

function isSelected(year: number, m: number) {
  return month.value === `${year}-${String(m).padStart(2, '0')}`
}

function isCurrent(year: number, m: number) {
  return year === currentYear && m === currentMonth
}

function isFuture(year: number, m: number) {
  if (year > currentYear) return true
  if (year < currentYear) return false
  return m > currentMonth
}

function selectMonth(year: number, m: number) {
  if (isFuture(year, m)) return
  const next = `${year}-${String(m).padStart(2, '0')}`
  pickerShow.value = false
  if (next === month.value) return
  month.value = next
  load()
}

const MODEL_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  hourly: '计时',
  fixed: '固定',
}

const settleLabel = computed(() => data.value?.settle_note || MODEL_LABELS[data.value?.salary_model] || '')

function formatTime(iso: string) {
  return iso.replace('T', ' ').slice(0, 19)
}

function formatDetailDate(value?: string) {
  if (!value) return '日期待补充'
  const match = String(value).match(/(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return String(value).slice(0, 10)
  return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`
}

function detailTypeLabel(value?: string) {
  return (
    ({ normal: '正常', group: '集体', rework: '返修', supplement: '补数', tail: '尾数' } as Record<string, string>)[
      value || ''
    ] || '其他'
  )
}

function detailPill(value?: string) {
  return value === 'rework' ? 'h5-pill--warn' : value === 'group' ? 'h5-pill--mute' : 'h5-pill--ok'
}

function detailQuantity(detail: any) {
  const isRework = detail.report_type === 'rework'
  return `${isRework ? '返修' : '合格'} ${isRework ? detail.rework_qty || 0 : detail.qualified_qty || 0}`
}

function pos(e: TouchEvent | MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height
  if ('touches' in e && e.touches[0]) {
    return {
      x: (e.touches[0].clientX - rect.left) * scaleX,
      y: (e.touches[0].clientY - rect.top) * scaleY,
    }
  }
  const me = e as MouseEvent
  return {
    x: (me.clientX - rect.left) * scaleX,
    y: (me.clientY - rect.top) * scaleY,
  }
}

function onSigStart(e: TouchEvent | MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  drawing = true
  const p = pos(e)
  ctx.beginPath()
  ctx.moveTo(p.x, p.y)
}

function onSigMove(e: TouchEvent | MouseEvent) {
  if (!drawing) return
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const p = pos(e)
  ctx.lineWidth = 2.5
  ctx.lineCap = 'round'
  ctx.strokeStyle = '#1c1c1e'
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
  hasStroke = true
}

function onSigEnd() {
  drawing = false
}

function clearSig() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  hasStroke = false
}

function initCanvas() {
  clearSig()
}

async function load() {
  if (!auth.workerId) return
  const res: any = await http.get(`/salary/${auth.workerId}`, { params: { year_month: month.value } })
  data.value = res.data
  confirmName.value = auth.displayName || ''
  agree.value = false
  await nextTick()
  initCanvas()
}

async function confirm() {
  if (!auth.workerId || !data.value) return
  if (!agree.value) {
    showToast('请先勾选确认无误')
    return
  }
  if (!confirmName.value.trim()) {
    showToast('请填写确认姓名')
    return
  }
  confirming.value = true
  try {
    const signature_data =
      hasStroke && canvasRef.value ? canvasRef.value.toDataURL('image/png') : undefined
    await http.post(`/salary/${auth.workerId}/confirm`, {
      year_month: month.value,
      confirm_name: confirmName.value.trim(),
      signature_data,
    })
    showToast('已确认')
    await load()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '确认失败')
  } finally {
    confirming.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.salary-period {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 2px 2px 16px;
  color: var(--ws-muted);
  font-size: 13px;
  font-weight: 600;
}

.salary-period__picker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  border: 0;
  border-radius: 999px;
  padding: 0 12px;
  background: var(--ws-bg-elevated);
  box-shadow: var(--ws-shadow-soft);
  color: var(--ws-ink);
  font: inherit;
  font-weight: 700;
}

.salary-period__picker :deep(.van-icon) {
  color: var(--ws-primary);
  font-size: 16px;
}

.salary-hero--statement {
  margin-bottom: 14px;
  padding: 22px;
}

.salary-hero__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.salary-hero__status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
  padding: 5px 8px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.88);
  font-size: 12px;
  font-weight: 600;
}

.salary-hero__notice {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 10px 11px;
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
}

.salary-hero__notice :deep(.van-icon) {
  flex: 0 0 auto;
  margin-top: 1px;
  font-size: 16px;
}

.salary-hero__notice p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.salary-hero--locked .salary-hero__status {
  background: rgba(52, 199, 89, 0.2);
}

.salary-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}

.salary-summary__item {
  border-radius: var(--ws-radius);
  padding: 15px;
  background: var(--ws-bg-elevated);
  box-shadow: var(--ws-shadow-soft);
}

.salary-summary__item span {
  display: block;
  margin-bottom: 5px;
  color: var(--ws-muted);
  font-size: 12px;
}

.salary-summary__item strong {
  color: var(--ws-ink);
  font-size: 18px;
}

.salary-summary__item:last-child strong {
  color: var(--ws-primary);
}

.salary-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 22px 4px 8px;
}

.salary-detail-head > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.salary-detail-head .h5-section-label {
  margin: 0;
}

.salary-detail-head span {
  color: var(--ws-muted);
  font-family: var(--ws-font-num);
  font-size: 12px;
  font-weight: 600;
}

.salary-detail-head a {
  color: var(--ws-primary);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.salary-detail {
  margin: 0;
  padding: 14px 15px;
  box-shadow: none;
  border: 1px solid rgba(60, 60, 67, 0.08);
}

.salary-detail__amount {
  color: var(--ws-ink);
  font-size: 17px;
}

.salary-detail__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  color: var(--ws-ink-secondary);
  font-size: 13px;
}

.salary-timeline {
  position: relative;
  margin: 0 0 24px 16px;
  padding-left: 16px;
  border-left: 1px solid var(--ws-line);
}

.salary-day {
  position: relative;
  padding-bottom: 20px;
}

.salary-day::before {
  position: absolute;
  top: 7px;
  left: -21px;
  width: 8px;
  height: 8px;
  border: 3px solid var(--ws-bg);
  border-radius: 50%;
  background: var(--ws-primary);
  box-shadow: 0 0 0 2px rgba(0, 118, 255, 0.15);
  content: '';
}

.salary-day__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.salary-day__head > span {
  color: var(--ws-muted);
  font-size: 13px;
  font-weight: 700;
}

.salary-day__head em {
  border-radius: 6px;
  padding: 3px 6px;
  background: var(--ws-primary-soft);
  color: var(--ws-primary);
  font-family: var(--ws-font-num);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

.salary-day__entries {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>

<style>
/* popup teleport 到 body，用非 scoped 保证样式生效 */
.month-cal {
  box-sizing: border-box;
  width: 100%;
  padding: 16px 16px calc(24px + env(safe-area-inset-bottom, 0px));
  background: #fff;
  color: #1c1c1e;
}

.month-cal__title {
  text-align: center;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 12px;
}

.month-cal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 16px;
}

.month-cal__year {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.month-cal__nav {
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 12px;
  background: rgba(0, 118, 255, 0.1);
  color: #0076ff;
  font-size: 28px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.month-cal__nav:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.month-cal__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.month-cal__cell {
  height: 52px;
  border: none;
  border-radius: 14px;
  background: #f2f2f7;
  color: #1c1c1e;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.month-cal__cell.current:not(.active) {
  color: #0076ff;
  background: rgba(0, 118, 255, 0.12);
}

.month-cal__cell.active {
  background: #0076ff;
  color: #fff;
  box-shadow: 0 4px 12px rgba(0, 118, 255, 0.28);
}

.month-cal__cell.disabled {
  color: #c7c7cc;
  background: #f7f7f9;
  cursor: not-allowed;
}

.salary-hero {
  background: linear-gradient(155deg, #4da0ff 0%, #0076ff 55%, #005fcc 100%);
  border-radius: var(--ws-radius-lg);
  padding: 28px 24px 24px;
  color: #fff;
  margin-bottom: 12px;
  box-shadow: 0 12px 32px rgba(0, 118, 255, 0.25);
  animation: h5-scale-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.salary-hero__label {
  font-size: 13px;
  font-weight: 600;
  opacity: 0.75;
  margin-bottom: 10px;
}

.salary-hero__amount {
  font-size: 42px;
  color: #fff;
  margin-bottom: 10px;
}

.salary-hero__yen {
  font-size: 22px;
  font-weight: 600;
  margin-right: 2px;
  opacity: 0.85;
}

.salary-hero__msg {
  margin: 0;
  font-size: 13px;
  opacity: 0.78;
  line-height: 1.45;
}

.salary-meta__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  font-size: 15px;
  border-bottom: 0.5px solid var(--ws-line);
}

.salary-meta__row:last-child {
  border-bottom: none;
  padding-bottom: 2px;
}

.salary-meta__row:first-child {
  padding-top: 2px;
}

.salary-lock-hint {
  margin: 0 4px 12px;
}

.ack-ok {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
  padding: 14px 16px;
  border-radius: var(--ws-radius);
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
}

.ack-box {
  border-radius: var(--ws-radius);
  padding: 18px 16px;
  margin-bottom: 14px;
  background: var(--ws-bg-elevated, #fff);
  box-shadow: var(--ws-shadow-soft, 0 1px 2px rgba(0, 0, 0, 0.03), 0 4px 12px rgba(0, 0, 0, 0.04));
}

.ack-box--pending {
  border: 1px dashed rgba(0, 118, 255, 0.28);
  background: rgba(0, 118, 255, 0.04);
}

.ack-box__title {
  font-weight: 700;
  font-size: 17px;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
}

.ack-box__hint {
  margin: 0 0 12px;
  font-size: 13px;
}

.sig-label {
  margin-bottom: 8px;
  font-size: 12px;
}

.sig-canvas {
  width: 100%;
  height: 120px;
  border-radius: 12px;
  background: #f9f9fb;
  border: 1px dashed var(--ws-separator);
  touch-action: none;
  display: block;
}

.sig-clear {
  margin-top: 10px;
}

.ack-check {
  margin: 16px 0;
  font-size: 14px;
}

.detail-amt {
  font-size: 16px;
  color: var(--ws-primary);
}
</style>
