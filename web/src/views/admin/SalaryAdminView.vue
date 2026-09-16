<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">工资管理</h1>
        <p class="page-desc">月结 · 计件 · 加减项 · 导出</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select
          v-model="departmentId"
          clearable
          filterable
          placeholder="全部部门"
          style="width: 160px"
          @change="search"
        >
          <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select
          v-model="workerId"
          clearable
          filterable
          placeholder="全部员工"
          style="width: 180px"
          @change="search"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-date-picker
          v-model="month"
          type="month"
          value-format="YYYY-MM"
          placeholder="月份"
          @change="onMonthChange"
        />
        <el-tag v-if="settleThrough" type="warning" effect="plain">截至 {{ settleThrough }}</el-tag>
        <el-button v-if="!isLocked" type="warning" @click="openLockDialog">提前结算</el-button>
        <el-button v-else-if="!isPastMonth" type="primary" plain @click="toggleUnlock">解锁本月</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.salary.export'" type="primary" @click="exportCsv">导出</el-button>
        <el-button v-permission="'btn.salary.export'" type="success" :disabled="!isLocked" @click="exportBank">导出银行代发</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="salary-table"
          :data="rows"
          stripe
          border
          show-summary
          :summary-method="getSummaries"
          :span-method="salarySpanMethod"
          :max-height="tableMaxHeight"
          @row-click="openDetail"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="department_name"
            label="部门"
            :width="colWidth('department_name', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.department_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="worker_name"
            label="员工姓名"
            :width="colWidth('worker_name', 100)"
            resizable
          />
          <el-table-column prop="salary_model" label="计薪方式" :width="colWidth('salary_model', 110)" resizable>
            <template #default="{ row }">{{ modelLabel(row.salary_model) }}</template>
          </el-table-column>
          <el-table-column
            prop="fixed_pay"
            label="固定工资"
            :width="colWidth('fixed_pay', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ Number(row.fixed_pay || 0) > 0 ? formatMoney(row.fixed_pay) : '—' }}
            </template>
          </el-table-column>
          <el-table-column
            prop="base_pay"
            label="底薪"
            :width="colWidth('base_pay', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ Number(row.base_pay || 0) > 0 ? formatMoney(row.base_pay) : '—' }}
            </template>
          </el-table-column>
          <el-table-column
            prop="guarantee_pay"
            label="保底"
            :width="colWidth('guarantee_pay', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ Number(row.guarantee_pay || 0) > 0 ? formatMoney(row.guarantee_pay) : '—' }}
            </template>
          </el-table-column>
          <el-table-column
            prop="overtime_pay"
            label="加班费"
            :width="colWidth('overtime_pay', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ row.salary_model === 'fixed' ? formatMoney(row.overtime_pay) : '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="piece_qty"
            label="计件量"
            :width="colWidth('piece_qty', 90)"
            align="right"
            resizable
          />
          <el-table-column
            prop="total_piece_wage"
            label="计件工资"
            :width="colWidth('total_piece_wage', 110)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.total_piece_wage) }}</template>
          </el-table-column>
          <el-table-column prop="loss_deduction" label="损耗扣款" :width="colWidth('loss_deduction', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.loss_deduction || 0) }}</template>
          </el-table-column>
          <el-table-column prop="late_deduction" label="迟到扣款" :width="colWidth('late_deduction', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.late_deduction || 0) }}</template>
          </el-table-column>
          <el-table-column prop="advance_repay" label="预支扣回" :width="colWidth('advance_repay', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.advance_repay || 0) }}</template>
          </el-table-column>
          <el-table-column prop="meal_allowance" label="餐费补贴" :width="colWidth('meal_allowance', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.meal_allowance || 0) }}</template>
          </el-table-column>
          <el-table-column prop="housing_allowance" label="住宿补贴" :width="colWidth('housing_allowance', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.housing_allowance || 0) }}</template>
          </el-table-column>
          <el-table-column prop="reward_total" label="奖励" :width="colWidth('reward_total', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.reward_total || 0) }}</template>
          </el-table-column>
          <el-table-column prop="penalty_total" label="惩罚" :width="colWidth('penalty_total', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.penalty_total || 0) }}</template>
          </el-table-column>
          <el-table-column
            prop="total_wage"
            label="应发合计"
            :width="colWidth('total_wage', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <strong>{{ formatMoney(row.total_wage ?? row.total_piece_wage) }}</strong>
            </template>
          </el-table-column>
          <el-table-column column-key="确认" label="确认" :width="colWidth('确认', 90)" resizable>
            <template #default="{ row }">
              <el-tag v-if="row.acknowledged" type="success" size="small">已签</el-tag>
              <el-tag v-else-if="isLocked" type="warning" size="small">待签</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="80" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openDetail(row)">明细</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>

      <el-drawer v-model="drawer" :title="`${detail?.worker_name || ''} ${month} 明细`" size="50%">
        <div v-if="detail" class="settle-summary">
          <div>{{ detail.settle_note || modelLabel(detail.salary_model) }}</div>
          <div class="muted">
            <template v-if="detail.salary_model !== 'pure_piece'">
              {{ detail.salary_model === 'guaranteed_piece' ? '保底金额' : detail.salary_model === 'fixed' ? '固定工资' : '底薪' }}
              {{ formatMoney(detail.base_salary) }} ·
            </template>
            计件量 {{ detail.piece_qty || 0 }}
          </div>
          <div v-if="detail.salary_model === 'fixed'" class="muted">
            加班 {{ Number(detail.overtime_hours || 0).toFixed(2) }} 小时
            × {{ formatMoney(detail.overtime_hourly_rate || 0) }}/小时
            = {{ formatMoney(detail.overtime_pay || 0) }}
          </div>
          <div>
            计件 {{ formatMoney(detail.total_piece_wage) }}
            · 餐补 {{ formatMoney(detail.meal_allowance || 0) }}
            · 住宿补 {{ formatMoney(detail.housing_allowance || 0) }}
            · 损失 {{ formatMoney(detail.loss_deduction || 0) }}
            · 奖励 {{ formatMoney(detail.reward_total || 0) }}
            · 惩罚 {{ formatMoney(detail.penalty_total || 0) }}
            · 迟到 {{ formatMoney(detail.late_deduction || 0) }}
            · 预支扣回 {{ formatMoney(detail.advance_repay || 0) }}
            ·
            <strong>应发合计 {{ formatMoney(detail.total_wage ?? detail.total_piece_wage) }}</strong>
          </div>
          <el-table
            v-if="(detail.adjustments || []).length"
            :data="detail.adjustments"
            stripe
            border
            size="small"
            style="margin: 12px 0"
          >
            <el-table-column label="类型" width="70">
              <template #default="{ row }">{{ row.kind === 'reward' ? '奖励' : '扣款' }}</template>
            </el-table-column>
            <el-table-column prop="category_label" label="分类" width="100" />
            <el-table-column label="金额" width="100" align="right">
              <template #default="{ row }">
                {{ row.kind === 'reward' ? '+' : '-' }}{{ formatMoney(row.amount) }}
              </template>
            </el-table-column>
            <el-table-column prop="title" label="说明" min-width="120" show-overflow-tooltip />
          </el-table>
          <div v-if="detail.acknowledged" style="margin-top: 8px; color: #067a3e">
            已电子确认
            <template v-if="detail.acknowledgement?.confirmed_at">
              · {{ detail.acknowledgement.confirmed_at.replace('T', ' ').slice(0, 19) }}
            </template>
            · {{ detail.acknowledgement?.confirm_name }}
          </div>
          <div v-else-if="detail.is_locked" class="muted" style="margin-top: 8px">待员工签字确认</div>
        </div>
        <el-table :data="detail?.details || []" stripe border size="small" @header-dragend="onHeaderDragend1">
          <el-table-column prop="created_at" label="时间" :width="colWidth1('created_at', 170)" resizable />
          <el-table-column prop="order_no" label="订单" :width="colWidth1('order_no', 100)" resizable />
          <el-table-column prop="process_name" label="工序" :width="colWidth1('process_name', 90)" resizable />
          <el-table-column prop="segment_name" label="工序段" :width="colWidth1('segment_name', 90)" resizable>
            <template #default="{ row }">
              <el-tag v-if="row.segment_name && row.segment_name !== '未分段'" size="small">{{ row.segment_name }}</el-tag>
              <span v-else class="muted">{{ row.segment_name || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="report_type" label="类型" :width="colWidth1('report_type', 80)" resizable />
          <el-table-column prop="qualified_qty" label="合格" :width="colWidth1('qualified_qty', 70)" resizable />
          <el-table-column prop="rework_qty" label="返修" :width="colWidth1('rework_qty', 70)" resizable />
          <el-table-column prop="unit_price" label="单价" :width="colWidth1('unit_price', 80)" resizable />
          <el-table-column prop="loss_amount" label="损失扣减" :width="colWidth1('loss_amount', 100)" resizable>
            <template #default="{ row }">{{ Number(row.loss_borne_percent || 0) > 0 ? formatMoney(row.wage_deduction || 0) : '—' }}</template>
          </el-table-column>
          <el-table-column prop="amount" label="金额" :width="colWidth1('amount', 90)" resizable>
            <template #default="{ row }">{{ formatMoney(row.net_amount ?? row.amount) }}</template>
          </el-table-column>
        </el-table>
      </el-drawer>

      <el-dialog v-model="lockDialog" title="月结锁定" width="440px" destroy-on-close>
        <el-form label-width="100px">
          <el-form-item label="结算月">
            <span>{{ month }}</span>
          </el-form-item>
          <el-form-item label="截止日期" required>
            <el-date-picker
              v-model="lockSettleThrough"
              type="date"
              value-format="YYYY-MM-DD"
              :disabled-date="disableLockDate"
              placeholder="选择截止日期"
              style="width: 100%"
            />
          </el-form-item>
          <p class="muted" style="margin: 0 0 0 100px; font-size: 12px; line-height: 1.5">
            按截止日（含）结算：固定/底薪/保底按日折算，计件只计截止日前报工。锁定后该月报工不可作废/更正。
          </p>
        </el-form>
        <template #footer>
          <el-button @click="lockDialog = false">取消</el-button>
          <el-button type="warning" :loading="lockSaving" @click="confirmLock">确认锁定</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('salary-list', tableRef, {
  flexKey: 'worker_name',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('salary-detail')
const auth = useAuthStore()
const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const workerId = ref<number | null>(null)
const departmentId = ref<number | null>(null)
const workers = ref<any[]>([])
const departments = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const isLocked = ref(false)
const drawer = ref(false)
const detail = ref<any>(null)
const settleThrough = ref<string | null>(null)
const lockDialog = ref(false)
const lockSettleThrough = ref<string | null>(null)
const lockSaving = ref(false)

/** 当月之前的已锁月：不再显示解锁（避免历史月结被改） */
const isPastMonth = computed(() => {
  const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return !!month.value && month.value < cur
})

const MODEL_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  guaranteed_piece: '保底+计件',
  hourly: '计时',
  fixed: '固定',
}

function modelLabel(m?: string) {
  return (m && MODEL_LABELS[m]) || m || '-'
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function applyDeptSpans(list: any[]) {
  const out = list.map((r) => ({ ...r, _dept_span: 0 }))
  let i = 0
  while (i < out.length) {
    const name = out[i].department_name || ''
    let j = i + 1
    while (j < out.length && (out[j].department_name || '') === name) j++
    out[i]._dept_span = j - i
    for (let k = i + 1; k < j; k++) out[k]._dept_span = 0
    i = j
  }
  return out
}

function salarySpanMethod({ row, column }: { row: any; column: any }) {
  const key = column.property || column.columnKey
  if (key === 'department_name') {
    return row._dept_span > 0 ? [row._dept_span, 1] : [0, 0]
  }
  return [1, 1]
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'piece_qty') return String(s.piece_qty ?? 0)
    if (key === 'base_pay') return formatMoney(s.base_pay)
    if (key === 'fixed_pay') return formatMoney(s.fixed_pay)
    if (key === 'guarantee_pay') return formatMoney(s.guarantee_pay)
    if (key === 'overtime_pay') return formatMoney(s.overtime_pay)
    if (key === 'meal_allowance') return formatMoney(s.meal_allowance)
    if (key === 'housing_allowance') return formatMoney(s.housing_allowance)
    if (key === 'total_piece_wage') return formatMoney(s.total_piece_wage)
    if (key === 'loss_deduction') return formatMoney(s.loss_deduction)
    if (key === 'reward_total') return formatMoney(s.reward_total)
    if (key === 'penalty_total') return formatMoney(s.penalty_total)
    if (key === 'late_deduction') return formatMoney(s.late_deduction)
    if (key === 'advance_repay') return formatMoney(s.advance_repay)
    if (key === 'total_wage') return formatMoney(s.total_wage)
    return ''
  })
}

async function loadWorkers() {
  const res: any = await http.get('/workers', {
    params: { page: 1, page_size: 500, is_active: true },
  })
  workers.value = res.data?.items || []
}

async function loadDepartments() {
  const res: any = await http.get('/departments')
  departments.value = (res.data?.items || []).filter((d: any) => d.is_active)
}

async function load() {
  const res: any = await http.get('/salary', {
    params: {
      year_month: month.value,
      worker_id: workerId.value || undefined,
      department_id: departmentId.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = applyDeptSpans(res.data.items || [])
  total.value = res.data.total ?? rows.value.length
  isLocked.value = !!res.data.is_locked
  settleThrough.value = res.data.settle_through || res.data.lock?.settle_through || null
  summary.value = res.data.summary || {
    total_wage: res.data.total_wage,
    total_piece_wage: res.data.total_piece_wage,
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function search() {
  page.value = 1
  void load()
}

function onMonthChange() {
  search()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function monthLastDay(ym: string) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(y, m, 0).getDate()
}

function disableLockDate(d: Date) {
  const [y, m] = month.value.split('-').map(Number)
  return d.getFullYear() !== y || d.getMonth() + 1 !== m
}

function openLockDialog() {
  const last = monthLastDay(month.value)
  lockSettleThrough.value = `${month.value}-${String(last).padStart(2, '0')}`
  lockDialog.value = true
}

async function confirmLock() {
  if (!lockSettleThrough.value) {
    ElMessage.warning('请选择截止日期')
    return
  }
  const through = lockSettleThrough.value
  lockSaving.value = true
  try {
    await http.post('/salary/lock', {
      year_month: month.value,
      locked: true,
      settle_through: through,
    })
    ElMessage.success(`已锁定（截至 ${through}）`)
    lockDialog.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '锁定失败')
  } finally {
    lockSaving.value = false
  }
}

async function toggleUnlock() {
  try {
    await ElMessageBox.confirm(`确认解锁 ${month.value}？解锁后需重新签字。`, '解锁月结', {
      type: 'warning',
    })
  } catch {
    return
  }
  await http.post('/salary/lock', { year_month: month.value, locked: false })
  ElMessage.success('已解锁')
  await load()
}

async function openDetail(row: any) {
  const res: any = await http.get(`/salary/${row.worker_id}`, {
    params: {
      year_month: month.value,
      settle_through: settleThrough.value || undefined,
    },
  })
  detail.value = res.data
  drawer.value = true
}

async function downloadCsv(path: string, filename: string) {
  const query = new URLSearchParams({ year_month: month.value })
  if (departmentId.value) query.set('department_id', String(departmentId.value))
  const res = await fetch(`/api/v1${path}?${query.toString()}`, {
    headers: { Authorization: `Bearer ${auth.token}` },
  })
  if (!res.ok) {
    let msg = '导出失败'
    try {
      const j = await res.json()
      msg = j.detail || msg
    } catch {
      /* ignore */
    }
    ElMessage.error(msg)
    return
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已下载')
}

async function exportCsv() {
  await downloadCsv('/salary/export', `salary_${month.value}.csv`)
}

async function exportBank() {
  if (!isLocked.value) {
    ElMessage.warning('请先锁定本月再导出银行代发')
    return
  }
  await downloadCsv('/salary/export-bank', `bank_payroll_${month.value}.csv`)
}

onMounted(async () => {
  await Promise.all([loadWorkers(), loadDepartments()])
  await load()
})
</script>

<style scoped>
.settle-summary {
  margin-bottom: 14px;
  line-height: 1.6;
}
</style>
