<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type TimePeriod = { start: string; end: string }

type DeductTier = {
  up_to_minutes: number | null
  deduct_type: 'amount' | 'day_fraction' | 'half_day' | 'full_day'
  amount: number | null
  day_fraction: number | null
}

type DeductRule = {
  mode: 'fixed_amount' | 'per_minute' | 'tiered'
  fixed_amount: number
  amount_per_minute: number
  round_up_minutes: boolean
  tiers: DeductTier[]
  daily_cap_amount: number | null
}

type LateEarlyDeduction = DeductRule & {
  enabled: boolean
  grace_minutes: number
  monthly_free_times: number
  count_late_and_early_separate: boolean
  same_rule_for_early: boolean
  early: DeductRule
}

type AttendanceRules = {
  rest_day_mode: 'weekly' | 'monthly'
  weekly_rest_days: number[]
  monthly_rest_days: number[]
  work_periods: TimePeriod[]
  overtime_periods: TimePeriod[]
  special_holidays: TimePeriod[]
  special_overtimes: TimePeriod[]
  late_early_deduction: LateEarlyDeduction
}

const WEEKDAY_OPTIONS = [
  { value: 1, label: '周一' },
  { value: 2, label: '周二' },
  { value: 3, label: '周三' },
  { value: 4, label: '周四' },
  { value: 5, label: '周五' },
  { value: 6, label: '周六' },
  { value: 7, label: '周日' },
]

const MONTH_DAY_OPTIONS = Array.from({ length: 31 }, (_, i) => ({
  value: i + 1,
  label: `${i + 1} 号`,
}))

const DEDUCT_MODE_OPTIONS = [
  { value: 'fixed_amount', label: '每次固定金额', hint: '只要超出宽限，每次迟到/早退扣同一金额' },
  { value: 'per_minute', label: '按分钟扣', hint: '超出宽限的分钟 × 单价' },
  { value: 'tiered', label: '阶梯扣款', hint: '按分钟区间配置金额 / 日薪比例 / 半天 / 全天，最灵活' },
]

const DEDUCT_TYPE_OPTIONS = [
  { value: 'amount', label: '固定金额' },
  { value: 'day_fraction', label: '日薪比例' },
  { value: 'half_day', label: '扣半天' },
  { value: 'full_day', label: '扣全天' },
]

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const activePanel = ref<'schedule' | 'exceptions' | 'penalty'>('schedule')
const canWrite = computed(
  () => auth.hasPermission('btn.attendance_rules.write') || auth.isAdmin(),
)

const WEEKDAY_LABEL: Record<number, string> = {
  1: '一',
  2: '二',
  3: '三',
  4: '四',
  5: '五',
  6: '六',
  7: '日',
}

const MODE_LABEL: Record<string, string> = {
  fixed_amount: '每次固定',
  per_minute: '按分钟',
  tiered: '阶梯',
}

function goPanel(key: 'schedule' | 'exceptions' | 'penalty') {
  activePanel.value = key
}

function defaultTiers(): DeductTier[] {
  return [
    { up_to_minutes: 15, deduct_type: 'amount', amount: 10, day_fraction: null },
    { up_to_minutes: 30, deduct_type: 'amount', amount: 20, day_fraction: null },
    { up_to_minutes: 60, deduct_type: 'day_fraction', amount: null, day_fraction: 0.5 },
    { up_to_minutes: null, deduct_type: 'full_day', amount: null, day_fraction: null },
  ]
}

function defaultDeductRule(): DeductRule {
  return {
    mode: 'tiered',
    fixed_amount: 20,
    amount_per_minute: 1,
    round_up_minutes: true,
    tiers: defaultTiers(),
    daily_cap_amount: null,
  }
}

function defaultLateEarly(): LateEarlyDeduction {
  return {
    enabled: false,
    grace_minutes: 5,
    monthly_free_times: 0,
    count_late_and_early_separate: true,
    same_rule_for_early: true,
    ...defaultDeductRule(),
    early: defaultDeductRule(),
  }
}

const form = reactive<AttendanceRules>({
  rest_day_mode: 'weekly',
  weekly_rest_days: [6, 7],
  monthly_rest_days: [],
  work_periods: [
    { start: '08:00', end: '12:00' },
    { start: '13:30', end: '17:30' },
  ],
  overtime_periods: [],
  special_holidays: [],
  special_overtimes: [],
  late_early_deduction: defaultLateEarly(),
})

const scheduleSummary = computed(() => {
  const rest =
    form.rest_day_mode === 'weekly'
      ? `周${(form.weekly_rest_days || []).map((d) => WEEKDAY_LABEL[d] || d).join('') || '—'}`
      : `每月${(form.monthly_rest_days || []).join('、') || '—'}号`
  const work = `${form.work_periods.length} 段上班`
  const ot = form.overtime_periods.length ? `加班 ${form.overtime_periods.length} 段` : '无常规加班'
  return `${rest} · ${work} · ${ot}`
})

const exceptionsSummary = computed(() => {
  const h = form.special_holidays.length
  const o = form.special_overtimes.length
  if (!h && !o) return '暂无例外'
  return `放假 ${h} · 加班 ${o}`
})

const penaltySummary = computed(() => {
  const led = form.late_early_deduction
  if (!led.enabled) return '未启用扣款'
  const mode = MODE_LABEL[led.mode] || led.mode
  return `已启用 · ${mode} · 宽限 ${led.grace_minutes} 分`
})

const navItems = computed(() => [
  {
    key: 'schedule' as const,
    title: '日常作息',
    desc: '休息日与上下班',
    summary: scheduleSummary.value,
  },
  {
    key: 'exceptions' as const,
    title: '例外日期',
    desc: '特殊放假与加班',
    summary: exceptionsSummary.value,
  },
  {
    key: 'penalty' as const,
    title: '迟到早退',
    desc: '扣工资方式',
    summary: penaltySummary.value,
  },
])

function emptyPeriod(): TimePeriod {
  return { start: '', end: '' }
}

function emptyDatetimePeriod(): TimePeriod {
  return { start: '', end: '' }
}

function emptyTier(): DeductTier {
  return { up_to_minutes: 30, deduct_type: 'amount', amount: 10, day_fraction: null }
}

function mapTiers(raw: any[] | undefined | null): DeductTier[] {
  if (!Array.isArray(raw) || !raw.length) return defaultTiers()
  return raw.map((t) => ({
    up_to_minutes: t?.up_to_minutes == null ? null : Number(t.up_to_minutes),
    deduct_type: (['amount', 'day_fraction', 'half_day', 'full_day'].includes(t?.deduct_type)
      ? t.deduct_type
      : 'amount') as DeductTier['deduct_type'],
    amount: t?.amount == null ? null : Number(t.amount),
    day_fraction: t?.day_fraction == null ? null : Number(t.day_fraction),
  }))
}

function mapDeductRule(raw: any | undefined | null): DeductRule {
  const base = defaultDeductRule()
  if (!raw || typeof raw !== 'object') return base
  return {
    mode: (['fixed_amount', 'per_minute', 'tiered'].includes(raw.mode) ? raw.mode : base.mode) as DeductRule['mode'],
    fixed_amount: Number(raw.fixed_amount ?? base.fixed_amount),
    amount_per_minute: Number(raw.amount_per_minute ?? base.amount_per_minute),
    round_up_minutes: raw.round_up_minutes !== false,
    tiers: mapTiers(raw.tiers),
    daily_cap_amount: raw.daily_cap_amount == null || raw.daily_cap_amount === '' ? null : Number(raw.daily_cap_amount),
  }
}

function mapLateEarly(raw: any | undefined | null): LateEarlyDeduction {
  const base = defaultLateEarly()
  const rule = mapDeductRule(raw)
  return {
    enabled: !!raw?.enabled,
    grace_minutes: Number(raw?.grace_minutes ?? base.grace_minutes),
    monthly_free_times: Number(raw?.monthly_free_times ?? base.monthly_free_times),
    count_late_and_early_separate: raw?.count_late_and_early_separate !== false,
    same_rule_for_early: raw?.same_rule_for_early !== false,
    ...rule,
    early: mapDeductRule(raw?.early),
  }
}

function applyData(data: Partial<AttendanceRules> | null | undefined) {
  form.rest_day_mode = data?.rest_day_mode === 'monthly' ? 'monthly' : 'weekly'
  form.weekly_rest_days = Array.isArray(data?.weekly_rest_days) ? [...data!.weekly_rest_days] : []
  form.monthly_rest_days = Array.isArray(data?.monthly_rest_days) ? [...data!.monthly_rest_days] : []
  form.work_periods = (data?.work_periods || []).map((p) => ({ start: p.start || '', end: p.end || '' }))
  form.overtime_periods = (data?.overtime_periods || []).map((p) => ({
    start: p.start || '',
    end: p.end || '',
  }))
  form.special_holidays = (data?.special_holidays || []).map((p) => ({
    start: p.start || '',
    end: p.end || '',
  }))
  form.special_overtimes = (data?.special_overtimes || []).map((p) => ({
    start: p.start || '',
    end: p.end || '',
  }))
  const led = mapLateEarly(data?.late_early_deduction)
  const earlyRule = led.early
  Object.assign(form.late_early_deduction, { ...led, early: form.late_early_deduction.early })
  Object.assign(form.late_early_deduction.early, earlyRule)
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/attendance-rules')
    applyData(res.data)
  } finally {
    loading.value = false
  }
}

function validateDeductRule(rule: DeductRule, label: string): string | null {
  if (rule.mode === 'fixed_amount' && !(rule.fixed_amount >= 0)) {
    return `${label}：请填写每次固定金额`
  }
  if (rule.mode === 'per_minute' && !(rule.amount_per_minute >= 0)) {
    return `${label}：请填写每分钟扣款`
  }
  if (rule.mode === 'tiered') {
    if (!rule.tiers.length) return `${label}：阶梯至少一档`
    let prev = 0
    for (let i = 0; i < rule.tiers.length; i++) {
      const t = rule.tiers[i]
      if (t.up_to_minutes != null) {
        if (t.up_to_minutes <= prev) return `${label}：第 ${i + 1} 档分钟须大于上一档`
        prev = t.up_to_minutes
      }
      if (t.deduct_type === 'amount' && !(Number(t.amount) >= 0)) {
        return `${label}：第 ${i + 1} 档请填写金额`
      }
      if (t.deduct_type === 'day_fraction') {
        const f = Number(t.day_fraction)
        if (!(f > 0 && f <= 1)) return `${label}：第 ${i + 1} 档日薪比例须在 0–1`
      }
    }
  }
  return null
}

function validateBeforeSave(): string | null {
  if (form.rest_day_mode === 'weekly' && !form.weekly_rest_days.length) {
    goPanel('schedule')
    return '请选择每周固定休息日'
  }
  if (form.rest_day_mode === 'monthly' && !form.monthly_rest_days.length) {
    goPanel('schedule')
    return '请选择每月固定休息日'
  }
  for (let i = 0; i < form.work_periods.length; i++) {
    const p = form.work_periods[i]
    if (!p.start || !p.end) {
      goPanel('schedule')
      return `上下班时间段第 ${i + 1} 段请填完整`
    }
    if (p.start >= p.end) {
      goPanel('schedule')
      return `上下班时间段第 ${i + 1} 段开始须早于结束`
    }
  }
  for (let i = 0; i < form.overtime_periods.length; i++) {
    const p = form.overtime_periods[i]
    if (!p.start || !p.end) {
      goPanel('schedule')
      return `加班时间段第 ${i + 1} 段请填完整`
    }
    if (p.start >= p.end) {
      goPanel('schedule')
      return `加班时间段第 ${i + 1} 段开始须早于结束`
    }
  }
  for (let i = 0; i < form.special_holidays.length; i++) {
    const p = form.special_holidays[i]
    if (!p.start || !p.end) {
      goPanel('exceptions')
      return `特殊放假第 ${i + 1} 段请填完整`
    }
    if (p.start >= p.end) {
      goPanel('exceptions')
      return `特殊放假第 ${i + 1} 段开始须早于结束`
    }
  }
  for (let i = 0; i < form.special_overtimes.length; i++) {
    const p = form.special_overtimes[i]
    if (!p.start || !p.end) {
      goPanel('exceptions')
      return `特殊加班第 ${i + 1} 段请填完整`
    }
    if (p.start >= p.end) {
      goPanel('exceptions')
      return `特殊加班第 ${i + 1} 段开始须早于结束`
    }
  }
  if (form.late_early_deduction.enabled) {
    const lateErr = validateDeductRule(form.late_early_deduction, '迟到扣款')
    if (lateErr) {
      goPanel('penalty')
      return lateErr
    }
    if (!form.late_early_deduction.same_rule_for_early) {
      const earlyErr = validateDeductRule(form.late_early_deduction.early, '早退扣款')
      if (earlyErr) {
        goPanel('penalty')
        return earlyErr
      }
    }
  }
  return null
}

function toHourBound(value: string) {
  const text = (value || '').trim().replace('T', ' ')
  if (text.length >= 13) return `${text.slice(0, 13)}:00`
  return text
}

function periodsToHour(list: TimePeriod[]) {
  return list.map((p) => ({ start: toHourBound(p.start), end: toHourBound(p.end) }))
}

function dumpDeductRule(rule: DeductRule) {
  return {
    mode: rule.mode,
    fixed_amount: rule.fixed_amount,
    amount_per_minute: rule.amount_per_minute,
    round_up_minutes: rule.round_up_minutes,
    tiers: rule.tiers.map((t) => ({
      up_to_minutes: t.up_to_minutes,
      deduct_type: t.deduct_type,
      amount: t.amount,
      day_fraction: t.day_fraction,
    })),
    daily_cap_amount: rule.daily_cap_amount,
  }
}

async function save() {
  const err = validateBeforeSave()
  if (err) {
    ElMessage.warning(err)
    return
  }
  saving.value = true
  try {
    const led = form.late_early_deduction
    const res: any = await http.patch('/attendance-rules', {
      rest_day_mode: form.rest_day_mode,
      weekly_rest_days: form.weekly_rest_days,
      monthly_rest_days: form.monthly_rest_days,
      work_periods: form.work_periods,
      overtime_periods: form.overtime_periods,
      special_holidays: periodsToHour(form.special_holidays),
      special_overtimes: periodsToHour(form.special_overtimes),
      late_early_deduction: {
        enabled: led.enabled,
        grace_minutes: led.grace_minutes,
        monthly_free_times: led.monthly_free_times,
        count_late_and_early_separate: led.count_late_and_early_separate,
        same_rule_for_early: led.same_rule_for_early,
        ...dumpDeductRule(led),
        early: dumpDeductRule(led.early),
      },
    })
    applyData(res.data)
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ar-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">考勤规则</h1>
        <p class="page-desc">分三块配置：日常作息、例外日期、迟到早退扣款</p>
      </div>
    </header>

    <div class="ar-shell">
      <nav class="ar-nav" aria-label="考勤规则分区">
        <button
          v-for="item in navItems"
          :key="item.key"
          type="button"
          class="ar-nav-item"
          :class="{ 'is-active': activePanel === item.key }"
          @click="goPanel(item.key)"
        >
          <div class="ar-nav-title">{{ item.title }}</div>
          <div class="ar-nav-desc">{{ item.desc }}</div>
          <div class="ar-nav-summary">{{ item.summary }}</div>
        </button>
      </nav>

      <div class="ar-main admin-card">
        <!-- 日常作息 -->
        <section v-show="activePanel === 'schedule'" class="ar-panel">
          <header class="ar-panel-head">
            <h2>日常作息</h2>
            <p>固定休息日、上下班与常规加班时段</p>
          </header>

          <div class="ar-block">
            <div class="ar-block-title">固定休息日</div>
            <p class="ar-block-hint">每周或每月二选一</p>
            <el-radio-group v-model="form.rest_day_mode" :disabled="!canWrite" class="mode-row">
              <el-radio value="weekly">每周固定休息日</el-radio>
              <el-radio value="monthly">每月固定休息日</el-radio>
            </el-radio-group>
            <div v-if="form.rest_day_mode === 'weekly'" class="field-block">
              <el-checkbox-group v-model="form.weekly_rest_days" :disabled="!canWrite">
                <el-checkbox v-for="d in WEEKDAY_OPTIONS" :key="d.value" :value="d.value">
                  {{ d.label }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
            <div v-else class="field-block">
              <el-select
                v-model="form.monthly_rest_days"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                :disabled="!canWrite"
                placeholder="选择每月几号休息"
                style="width: min(420px, 100%)"
              >
                <el-option v-for="d in MONTH_DAY_OPTIONS" :key="d.value" :label="d.label" :value="d.value" />
              </el-select>
            </div>
          </div>

          <div class="ar-block">
            <div class="ar-block-title">上下班时间段</div>
            <p class="ar-block-hint">可多段，如上午 + 下午</p>
            <div v-for="(p, idx) in form.work_periods" :key="`work-${idx}`" class="period-row">
              <el-time-select v-model="p.start" :disabled="!canWrite" start="00:00" step="00:30" end="23:30" placeholder="开始" style="width: 120px" />
              <span class="period-sep">至</span>
              <el-time-select v-model="p.end" :disabled="!canWrite" start="00:00" step="00:30" end="23:30" placeholder="结束" style="width: 120px" />
              <el-button v-if="canWrite" link type="danger" @click="form.work_periods.splice(idx, 1)">删除</el-button>
            </div>
            <el-button v-if="canWrite" link type="primary" @click="form.work_periods.push(emptyPeriod())">＋ 添加时段</el-button>
          </div>

          <div class="ar-block">
            <div class="ar-block-title">常规加班时段</div>
            <p class="ar-block-hint">每天固定加班窗口，可多段；没有可留空</p>
            <div v-for="(p, idx) in form.overtime_periods" :key="`ot-${idx}`" class="period-row">
              <el-time-select v-model="p.start" :disabled="!canWrite" start="00:00" step="00:30" end="23:30" placeholder="开始" style="width: 120px" />
              <span class="period-sep">至</span>
              <el-time-select v-model="p.end" :disabled="!canWrite" start="00:00" step="00:30" end="23:30" placeholder="结束" style="width: 120px" />
              <el-button v-if="canWrite" link type="danger" @click="form.overtime_periods.splice(idx, 1)">删除</el-button>
            </div>
            <el-button v-if="canWrite" link type="primary" @click="form.overtime_periods.push(emptyPeriod())">＋ 添加时段</el-button>
            <div v-if="!form.overtime_periods.length" class="muted empty-tip">暂无常规加班时段</div>
          </div>
        </section>

        <!-- 例外日期 -->
        <section v-show="activePanel === 'exceptions'" class="ar-panel">
          <header class="ar-panel-head">
            <h2>例外日期</h2>
            <p>覆盖日常作息的特殊放假与特殊加班（精确到小时）</p>
          </header>

          <div class="ar-block">
            <div class="ar-block-title">特殊放假</div>
            <p class="ar-block-hint">法定节假日或临时放假</p>
            <div v-for="(p, idx) in form.special_holidays" :key="`hol-${idx}`" class="period-row">
              <el-date-picker v-model="p.start" type="datetime" :disabled="!canWrite" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:00" placeholder="开始" style="width: 200px" />
              <span class="period-sep">至</span>
              <el-date-picker v-model="p.end" type="datetime" :disabled="!canWrite" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:00" placeholder="结束" style="width: 200px" />
              <el-button v-if="canWrite" link type="danger" @click="form.special_holidays.splice(idx, 1)">删除</el-button>
            </div>
            <el-button v-if="canWrite" link type="primary" @click="form.special_holidays.push(emptyDatetimePeriod())">＋ 添加放假</el-button>
            <div v-if="!form.special_holidays.length" class="muted empty-tip">暂无特殊放假</div>
          </div>

          <div class="ar-block">
            <div class="ar-block-title">特殊加班</div>
            <p class="ar-block-hint">休息日加班或临时加班安排</p>
            <div v-for="(p, idx) in form.special_overtimes" :key="`sot-${idx}`" class="period-row">
              <el-date-picker v-model="p.start" type="datetime" :disabled="!canWrite" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:00" placeholder="开始" style="width: 200px" />
              <span class="period-sep">至</span>
              <el-date-picker v-model="p.end" type="datetime" :disabled="!canWrite" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:00" placeholder="结束" style="width: 200px" />
              <el-button v-if="canWrite" link type="danger" @click="form.special_overtimes.splice(idx, 1)">删除</el-button>
            </div>
            <el-button v-if="canWrite" link type="primary" @click="form.special_overtimes.push(emptyDatetimePeriod())">＋ 添加加班</el-button>
            <div v-if="!form.special_overtimes.length" class="muted empty-tip">暂无特殊加班</div>
          </div>
        </section>

        <!-- 迟到早退 -->
        <section v-show="activePanel === 'penalty'" class="ar-panel">
          <header class="ar-panel-head">
            <h2>迟到 / 早退扣款</h2>
            <p>宽限 → 月免次 → 扣款方式；可按公司习惯选固定、按分钟或阶梯</p>
          </header>

          <div class="switch-row">
            <div class="switch-copy">
              <div class="switch-name">启用扣款</div>
              <div class="switch-hint">关闭后只记迟到早退，不从工资扣除</div>
            </div>
            <el-switch v-if="canWrite" v-model="form.late_early_deduction.enabled" />
            <el-tag v-else :type="form.late_early_deduction.enabled ? 'success' : 'info'" size="small">
              {{ form.late_early_deduction.enabled ? '开' : '关' }}
            </el-tag>
          </div>

          <template v-if="form.late_early_deduction.enabled">
            <div class="field-grid">
              <div class="field-block">
                <div class="field-name">宽限（分钟）</div>
                <el-input-number v-model="form.late_early_deduction.grace_minutes" :min="0" :max="120" :disabled="!canWrite" />
                <div class="field-tip">不超过不算迟到/早退</div>
              </div>
              <div class="field-block">
                <div class="field-name">每月免费次数</div>
                <el-input-number v-model="form.late_early_deduction.monthly_free_times" :min="0" :max="31" :disabled="!canWrite" />
                <div class="field-tip">宽限外仍不扣（迟到+早退合计）</div>
              </div>
              <div class="field-block">
                <div class="field-name">单日封顶（元）</div>
                <el-input-number v-model="form.late_early_deduction.daily_cap_amount" :min="0" :precision="2" :disabled="!canWrite" controls-position="right" placeholder="不限制" />
                <div class="field-tip">空=不限制</div>
              </div>
            </div>

            <div class="switch-row">
              <div class="switch-copy">
                <div class="switch-name">同日迟到与早退分别扣</div>
                <div class="switch-hint">关闭则取较大分钟数只扣一次</div>
              </div>
              <el-switch v-if="canWrite" v-model="form.late_early_deduction.count_late_and_early_separate" />
            </div>

            <div class="switch-row">
              <div class="switch-copy">
                <div class="switch-name">早退与迟到同一规则</div>
                <div class="switch-hint">关闭后可单独配置早退</div>
              </div>
              <el-switch v-if="canWrite" v-model="form.late_early_deduction.same_rule_for_early" />
            </div>

            <div class="sub-label">{{ form.late_early_deduction.same_rule_for_early ? '扣款方式' : '迟到扣款方式' }}</div>
            <el-radio-group v-model="form.late_early_deduction.mode" :disabled="!canWrite" class="mode-col">
              <el-radio v-for="o in DEDUCT_MODE_OPTIONS" :key="o.value" :value="o.value">
                <span>{{ o.label }}</span>
                <span class="radio-hint">{{ o.hint }}</span>
              </el-radio>
            </el-radio-group>

            <div v-if="form.late_early_deduction.mode === 'fixed_amount'" class="field-block">
              <div class="field-name">每次扣款（元）</div>
              <el-input-number v-model="form.late_early_deduction.fixed_amount" :min="0" :precision="2" :disabled="!canWrite" />
            </div>

            <div v-else-if="form.late_early_deduction.mode === 'per_minute'" class="field-grid">
              <div class="field-block">
                <div class="field-name">每分钟（元）</div>
                <el-input-number v-model="form.late_early_deduction.amount_per_minute" :min="0" :precision="2" :disabled="!canWrite" />
              </div>
              <div class="field-block">
                <div class="field-name">不足 1 分钟进位</div>
                <el-switch v-if="canWrite" v-model="form.late_early_deduction.round_up_minutes" />
              </div>
            </div>

            <div v-else class="tier-block">
              <div v-for="(t, idx) in form.late_early_deduction.tiers" :key="`late-tier-${idx}`" class="tier-row">
                <span class="tier-prefix">≤</span>
                <el-input-number v-model="t.up_to_minutes" :min="1" :disabled="!canWrite || t.up_to_minutes === null" controls-position="right" style="width: 110px" />
                <span class="tier-prefix">分钟</span>
                <el-checkbox :model-value="t.up_to_minutes === null" :disabled="!canWrite" @change="(v: boolean) => (t.up_to_minutes = v ? null : 60)">及以上</el-checkbox>
                <el-select v-model="t.deduct_type" :disabled="!canWrite" style="width: 120px">
                  <el-option v-for="o in DEDUCT_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
                </el-select>
                <el-input-number v-if="t.deduct_type === 'amount'" v-model="t.amount" :min="0" :precision="2" :disabled="!canWrite" />
                <el-input-number v-else-if="t.deduct_type === 'day_fraction'" v-model="t.day_fraction" :min="0.01" :max="1" :step="0.1" :precision="2" :disabled="!canWrite" />
                <span v-else class="muted">按日薪{{ t.deduct_type === 'half_day' ? '×0.5' : '×1' }}</span>
                <el-button v-if="canWrite" link type="danger" @click="form.late_early_deduction.tiers.splice(idx, 1)">删除</el-button>
              </div>
              <el-button v-if="canWrite" link type="primary" @click="form.late_early_deduction.tiers.push(emptyTier())">＋ 添加档位</el-button>
            </div>

            <template v-if="!form.late_early_deduction.same_rule_for_early">
              <div class="sub-label">早退扣款方式</div>
              <el-radio-group v-model="form.late_early_deduction.early.mode" :disabled="!canWrite" class="mode-col">
                <el-radio v-for="o in DEDUCT_MODE_OPTIONS" :key="`e-${o.value}`" :value="o.value">
                  <span>{{ o.label }}</span>
                  <span class="radio-hint">{{ o.hint }}</span>
                </el-radio>
              </el-radio-group>
              <div v-if="form.late_early_deduction.early.mode === 'fixed_amount'" class="field-block">
                <div class="field-name">每次扣款（元）</div>
                <el-input-number v-model="form.late_early_deduction.early.fixed_amount" :min="0" :precision="2" :disabled="!canWrite" />
              </div>
              <div v-else-if="form.late_early_deduction.early.mode === 'per_minute'" class="field-grid">
                <div class="field-block">
                  <div class="field-name">每分钟（元）</div>
                  <el-input-number v-model="form.late_early_deduction.early.amount_per_minute" :min="0" :precision="2" :disabled="!canWrite" />
                </div>
                <div class="field-block">
                  <div class="field-name">不足 1 分钟进位</div>
                  <el-switch v-if="canWrite" v-model="form.late_early_deduction.early.round_up_minutes" />
                </div>
              </div>
              <div v-else class="tier-block">
                <div v-for="(t, idx) in form.late_early_deduction.early.tiers" :key="`early-tier-${idx}`" class="tier-row">
                  <span class="tier-prefix">≤</span>
                  <el-input-number v-model="t.up_to_minutes" :min="1" :disabled="!canWrite || t.up_to_minutes === null" controls-position="right" style="width: 110px" />
                  <span class="tier-prefix">分钟</span>
                  <el-checkbox :model-value="t.up_to_minutes === null" :disabled="!canWrite" @change="(v: boolean) => (t.up_to_minutes = v ? null : 60)">及以上</el-checkbox>
                  <el-select v-model="t.deduct_type" :disabled="!canWrite" style="width: 120px">
                    <el-option v-for="o in DEDUCT_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
                  </el-select>
                  <el-input-number v-if="t.deduct_type === 'amount'" v-model="t.amount" :min="0" :precision="2" :disabled="!canWrite" />
                  <el-input-number v-else-if="t.deduct_type === 'day_fraction'" v-model="t.day_fraction" :min="0.01" :max="1" :step="0.1" :precision="2" :disabled="!canWrite" />
                  <span v-else class="muted">按日薪{{ t.deduct_type === 'half_day' ? '×0.5' : '×1' }}</span>
                  <el-button v-if="canWrite" link type="danger" @click="form.late_early_deduction.early.tiers.splice(idx, 1)">删除</el-button>
                </div>
                <el-button v-if="canWrite" link type="primary" @click="form.late_early_deduction.early.tiers.push(emptyTier())">＋ 添加档位</el-button>
              </div>
              <div class="field-block" style="margin-top: 8px">
                <div class="field-name">早退单日封顶（元）</div>
                <el-input-number v-model="form.late_early_deduction.early.daily_cap_amount" :min="0" :precision="2" :disabled="!canWrite" placeholder="不限制" />
              </div>
            </template>
          </template>
          <div v-else class="ar-off-hint muted">扣款未启用。左侧摘要会显示「未启用扣款」。</div>
        </section>

        <footer v-if="canWrite" class="ar-footer">
          <el-button type="primary" :loading="saving" @click="save">保存全部</el-button>
          <el-button :loading="loading" @click="load">刷新</el-button>
          <span class="ar-footer-tip muted">三个分区共用一次保存</span>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ar-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.ar-nav {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ar-nav-item {
  text-align: left;
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.ar-nav-item:hover {
  border-color: #cbd5e1;
}

.ar-nav-item.is-active {
  border-color: var(--el-color-primary);
  box-shadow: inset 3px 0 0 var(--el-color-primary);
  background: var(--el-color-primary-light-9, #ecf5ff);
}

.ar-nav-title {
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.ar-nav-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #64748b;
}

.ar-nav-summary {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.4;
  color: #94a3b8;
}

.ar-nav-item.is-active .ar-nav-summary {
  color: #64748b;
}

.ar-main {
  min-width: 0;
  padding: 0;
  overflow: hidden;
}

.ar-panel {
  padding: 18px 20px 8px;
}

.ar-panel-head {
  margin-bottom: 14px;
}

.ar-panel-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  color: #0f172a;
}

.ar-panel-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.ar-block {
  padding: 14px 0;
  border-top: 1px solid #f1f5f9;
}

.ar-block:first-of-type {
  border-top: none;
  padding-top: 0;
}

.ar-block-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.ar-block-hint {
  margin: 4px 0 10px;
  font-size: 12px;
  color: #94a3b8;
}

.ar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
  position: sticky;
  bottom: 0;
}

.ar-footer-tip {
  margin-left: 4px;
  font-size: 12px;
}

.ar-off-hint {
  margin-top: 12px;
  font-size: 13px;
}

.mode-row {
  margin-bottom: 10px;
}

.mode-col {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}

.radio-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.field-block {
  margin-bottom: 8px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px 16px;
  margin: 12px 0;
}

.field-name {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 6px;
}

.field-tip {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}

.period-row,
.tier-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.period-sep,
.tier-prefix {
  color: #94a3b8;
  font-size: 13px;
}

.empty-tip {
  font-size: 12px;
  margin: 4px 0 0;
}

.muted {
  color: #94a3b8;
}

.switch-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.switch-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.switch-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.sub-label {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}

.tier-block {
  margin-top: 4px;
}

@media (max-width: 900px) {
  .ar-shell {
    grid-template-columns: 1fr;
  }

  .ar-nav {
    position: static;
    flex-direction: row;
    overflow-x: auto;
    gap: 8px;
    padding-bottom: 2px;
  }

  .ar-nav-item {
    min-width: 160px;
    flex: 0 0 auto;
  }
}
</style>
