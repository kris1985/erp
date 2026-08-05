<template>
  <div class="page">
    <div class="salary-filter card-block">
      <van-field
        :model-value="monthLabel"
        is-link
        readonly
        label="月份"
        input-align="right"
        placeholder="选择月份"
        @click="openPicker"
      />
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
      <section class="salary-hero">
        <div class="salary-hero__label">应发合计</div>
        <div class="h5-stat-num salary-hero__amount">
          <span class="salary-hero__yen">¥</span>{{ Number(data.total_wage ?? data.total_piece_wage).toFixed(2) }}
        </div>
        <p class="salary-hero__msg">{{ data.message }}</p>
      </section>

      <div class="salary-meta card-block">
        <div class="salary-meta__row">
          <span class="muted">结算方式</span>
          <span>{{ settleLabel || '—' }}</span>
        </div>
        <div class="salary-meta__row">
          <span class="muted">底薪</span>
          <span class="h5-stat-num">¥{{ Number(data.base_salary || 0).toFixed(2) }}</span>
        </div>
        <div v-if="data.base_quota" class="salary-meta__row">
          <span class="muted">定额</span>
          <span>{{ data.base_quota }}</span>
        </div>
        <div class="salary-meta__row">
          <span class="muted">计件量</span>
          <span>{{ data.piece_qty || 0 }}</span>
        </div>
        <div class="salary-meta__row">
          <span class="muted">计件全额</span>
          <span class="h5-stat-num">¥{{ Number(data.total_piece_wage || 0).toFixed(2) }}</span>
        </div>
        <div class="salary-meta__row">
          <span class="muted">计件应发</span>
          <span class="h5-stat-num">¥{{ Number(data.payable_piece_wage ?? data.total_piece_wage).toFixed(2) }}</span>
        </div>
      </div>

      <div v-if="data.acknowledged" class="ack-ok">
        <van-icon name="passed" />
        已确认签字
        <template v-if="data.acknowledgement?.confirmed_at">
          · {{ formatTime(data.acknowledgement.confirmed_at) }}
        </template>
      </div>
      <div v-else-if="data.is_locked" class="ack-box">
        <div class="ack-box__title">工资确认</div>
        <p class="muted ack-box__hint">本月已月结锁定。请核对明细后签字确认；确认姓名须与档案姓名一致。</p>
        <van-field v-model="confirmName" label="确认姓名" :placeholder="`请填写 ${auth.displayName || '本人姓名'}`" />
        <div class="sig-wrap">
          <div class="muted sig-label">手写签名（可选）</div>
          <canvas
            ref="canvasRef"
            class="sig-canvas"
            width="320"
            height="120"
            @touchstart.prevent="onSigStart"
            @touchmove.prevent="onSigMove"
            @touchend.prevent="onSigEnd"
            @mousedown.prevent="onSigStart"
            @mousemove.prevent="onSigMove"
            @mouseup.prevent="onSigEnd"
            @mouseleave.prevent="onSigEnd"
          />
          <van-button size="small" plain round class="sig-clear" @click="clearSig">清除签名</van-button>
        </div>
        <van-checkbox v-model="agree" shape="square" class="ack-check">
          本人已核对上述工资明细，确认无误
        </van-checkbox>
        <van-button type="primary" block round :loading="confirming" :disabled="!agree" @click="confirm">
          签字确认
        </van-button>
      </div>
      <div v-else class="ack-box ack-box--pending">
        <div class="ack-box__title">工资确认</div>
        <p class="muted ack-box__hint">
          本月尚未月结锁定，暂不能签字。请等管理员在后台完成月结锁定后再来确认。
        </p>
        <van-button type="primary" block round disabled>签字确认</van-button>
      </div>

      <p class="h5-section-label">明细</p>
      <div v-if="!(data.details || []).length" class="h5-empty">
        <div class="h5-empty__mark">—</div>
        暂无明细
      </div>
      <div v-for="d in data.details" :key="d.work_log_id" class="h5-list-card">
        <div class="h5-list-card__head">
          <div class="h5-list-card__title">{{ d.order_no }} · {{ d.process_name }}</div>
          <span class="h5-stat-num detail-amt">¥{{ Number(d.amount).toFixed(2) }}</span>
        </div>
        <div class="muted">{{ d.report_type }}</div>
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
.salary-filter {
  padding: 2px 0;
}

.salary-filter :deep(.van-cell) {
  padding-left: 12px;
  padding-right: 12px;
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
