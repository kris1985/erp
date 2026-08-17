<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">工资管理</h1>
        <p class="page-desc">月结 · 计件 · 导出</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="month"
          type="month"
          value-format="YYYY-MM"
          placeholder="月份"
          @change="search"
        />
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
        <el-tag v-if="isLocked" type="danger" effect="plain">已月结锁定</el-tag>
        <el-tag v-else type="success" effect="plain">未锁定</el-tag>
        <el-button v-if="!isLocked" type="warning" @click="toggleLock(true)">锁定本月</el-button>
        <el-button v-else type="primary" plain @click="toggleLock(false)">解锁本月</el-button>
        <div class="spacer" />
        <el-button @click="search">查询</el-button>
        <el-button type="primary" @click="exportCsv">导出月结 CSV</el-button>
        <el-button type="success" :disabled="!isLocked" @click="exportBank">导出银行代发</el-button>
      </div>
      <div
        class="muted"
        style="margin: -6px 0 10px; font-size: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap"
      >
        <span>共 {{ count }} 人 · 应发合计 {{ formatMoney(totalWage) }}</span>
        <template v-if="isLocked">
          <span>· 已确认 {{ ackCount }}/{{ count }}</span>
          <el-tag v-if="allAcknowledged" type="success" size="small" effect="dark">全部签名完成</el-tag>
          <el-tag v-else type="warning" size="small" effect="plain">还有 {{ count - ackCount }} 人未签</el-tag>
        </template>
      </div>

      <div v-if="reconcile" class="reconcile-card">
        <div class="reconcile-head">
          <strong>工资 vs 实际人工成本（当月报工计件总额，同源口径）</strong>
          <el-button v-if="reconcile.variance?.significant" type="primary" size="small" @click="askAi">
            <el-icon><MagicStick /></el-icon>
            问 AI 军师原因
          </el-button>
        </div>
        <div class="reconcile-grid">
          <div class="reconcile-cell">
            <div class="rc-label">应发工资</div>
            <div class="rc-value">{{ formatMoney(reconcile.payroll?.total_wage) }}</div>
          </div>
          <div class="reconcile-cell">
            <div class="rc-label">实际人工成本</div>
            <div class="rc-value">{{ formatMoney(reconcile.labor_cost?.total) }}</div>
          </div>
          <div class="reconcile-cell">
            <div class="rc-label">差异（应发 − 人工成本）</div>
            <div class="rc-value" :class="reconcile.variance?.amount > 0 ? 'rc-pos' : reconcile.variance?.amount < 0 ? 'rc-neg' : ''">
              {{ formatSigned(reconcile.variance?.amount) }}
              <span v-if="reconcile.variance?.rate != null" class="muted">
                ({{ (reconcile.variance.rate > 0 ? '+' : '') + reconcile.variance.rate.toFixed(1) }}%)
              </span>
            </div>
          </div>
        </div>
        <div v-if="(reconcile.breakdown_nonzero || []).length" class="reconcile-breakdown">
          <div class="rc-label">差异根因分解</div>
          <div class="rc-chips">
            <el-tag
              v-for="b in reconcile.breakdown_nonzero"
              :key="b.key"
              :type="b.amount > 0 ? 'danger' : 'success'"
              effect="plain"
            >
              {{ b.label }} {{ formatSigned(b.amount) }}
            </el-tag>
            <el-tag
              v-if="reconcile.labor_cost?.unpaid_rework_count"
              type="info"
              effect="plain"
            >
              返修不计薪 {{ reconcile.labor_cost.unpaid_rework_count }} 条 ≈ ¥{{ formatNumber(reconcile.labor_cost.unpaid_rework_amount) }}
            </el-tag>
            <el-tag
              v-if="reconcile.payroll?.no_log_worker_count"
              type="warning"
              effect="plain"
            >
              无报工在职员工 {{ reconcile.payroll.no_log_worker_count }} 人
            </el-tag>
          </div>
        </div>
        <div v-else class="muted" style="font-size: 12px">应发工资与实际人工成本一致，无差异。</div>
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
          :max-height="tableMaxHeight"
          @row-click="openDetail"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="worker_name"
            label="员工"
            :width="colWidth('worker_name', 100)"
            resizable
          />
          <el-table-column prop="salary_model" label="计薪" :width="colWidth('salary_model', 120)" resizable>
            <template #default="{ row }">{{ modelLabel(row.salary_model) }}</template>
          </el-table-column>
          <el-table-column
            prop="log_count"
            label="报工条数"
            :width="colWidth('log_count', 100)"
            align="right"
            resizable
          />
          <el-table-column
            prop="piece_qty"
            label="计件量"
            :width="colWidth('piece_qty', 90)"
            align="right"
            resizable
          />
          <el-table-column
            prop="base_salary"
            label="底薪"
            :width="colWidth('base_salary', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.base_salary) }}</template>
          </el-table-column>
          <el-table-column
            prop="total_piece_wage"
            label="计件全额"
            :width="colWidth('total_piece_wage', 110)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.total_piece_wage) }}</template>
          </el-table-column>
          <el-table-column
            prop="payable_piece_wage"
            label="计件应发"
            :width="colWidth('payable_piece_wage', 110)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ formatMoney(row.payable_piece_wage ?? row.total_piece_wage) }}
            </template>
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
            底薪 {{ formatMoney(detail.base_salary) }}
            <span v-if="detail.base_quota"> · 定额 {{ detail.base_quota }}</span>
            · 计件量 {{ detail.piece_qty || 0 }}
          </div>
          <div>
            计件全额 {{ formatMoney(detail.total_piece_wage) }}
            · 计件应发 {{ formatMoney(detail.payable_piece_wage ?? detail.total_piece_wage) }}
            ·
            <strong>应发合计 {{ formatMoney(detail.total_wage ?? detail.total_piece_wage) }}</strong>
          </div>
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
          <el-table-column prop="report_type" label="类型" :width="colWidth1('report_type', 80)" resizable />
          <el-table-column prop="qualified_qty" label="合格" :width="colWidth1('qualified_qty', 70)" resizable />
          <el-table-column prop="rework_qty" label="返修" :width="colWidth1('rework_qty', 70)" resizable />
          <el-table-column prop="unit_price" label="单价" :width="colWidth1('unit_price', 80)" resizable />
          <el-table-column prop="amount" label="金额" :width="colWidth1('amount', 90)" resizable>
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
        </el-table>
      </el-drawer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const router = useRouter()
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
const workers = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const isLocked = ref(false)
const ackCount = ref(0)
const count = ref(0)
const totalWage = ref(0)
const allAcknowledged = ref(false)
const reconcile = ref<any>(null)
const drawer = ref(false)
const detail = ref<any>(null)

const MODEL_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
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

function formatNumber(v: any) {
  const n = Number(v ?? 0)
  if (Number.isNaN(n)) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatSigned(v: any) {
  const n = Number(v ?? 0)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}${formatMoney(Math.abs(n))}`
}

function askAi() {
  const ym = month.value
  const q =
    `请用「工资人工成本对账」分析 ${ym} 应发工资与实际人工成本（当月报工计件总额）差异的原因，` +
    `给出逐项根因分解；如有未签名人员也一并列出。`
  router.push({ path: '/admin/schedule-assistant', query: { q } })
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'log_count') return String(s.log_count ?? 0)
    if (key === 'piece_qty') return String(s.piece_qty ?? 0)
    if (key === 'base_salary') return formatMoney(s.base_salary)
    if (key === 'total_piece_wage') return formatMoney(s.total_piece_wage)
    if (key === 'payable_piece_wage') return formatMoney(s.payable_piece_wage)
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

async function load() {
  const res: any = await http.get('/salary', {
    params: {
      year_month: month.value,
      worker_id: workerId.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = res.data.items
  total.value = res.data.total ?? rows.value.length
  isLocked.value = !!res.data.is_locked
  ackCount.value = Number(res.data.acknowledged_count || 0)
  allAcknowledged.value = !!res.data.all_acknowledged
  count.value = Number(res.data.summary?.count ?? res.data.total ?? rows.value.length)
  totalWage.value = Number(res.data.summary?.total_wage ?? res.data.total_wage ?? 0)
  summary.value = res.data.summary || {
    total_wage: res.data.total_wage,
    total_piece_wage: res.data.total_piece_wage,
  }
  try {
    const rc: any = await http.get('/salary/reconcile', {
      params: { year_month: month.value },
    })
    reconcile.value = rc.data
  } catch {
    reconcile.value = null
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

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function toggleLock(locked: boolean) {
  const tip = locked
    ? `确认锁定 ${month.value}？锁定后该月报工不可作废/更正/申诉，新报工若落在本月也会被拦截。`
    : `确认解锁 ${month.value}？`
  try {
    await ElMessageBox.confirm(tip, locked ? '月结锁定' : '解锁月结', { type: 'warning' })
  } catch {
    return
  }
  await http.post('/salary/lock', { year_month: month.value, locked })
  ElMessage.success(locked ? '已锁定' : '已解锁')
  await load()
}

async function openDetail(row: any) {
  const res: any = await http.get(`/salary/${row.worker_id}`, { params: { year_month: month.value } })
  detail.value = res.data
  drawer.value = true
}

async function downloadCsv(path: string, filename: string) {
  const res = await fetch(`/api/v1${path}?year_month=${month.value}`, {
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
  await loadWorkers()
  await load()
})
</script>

<style scoped>
.settle-summary {
  margin-bottom: 14px;
  line-height: 1.6;
}

.reconcile-card {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: var(--el-fill-color-blank);
}

.reconcile-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.reconcile-grid {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.reconcile-cell {
  flex: 1 1 160px;
  max-width: 220px;
}

.rc-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}

.rc-value {
  font-size: 16px;
  font-weight: 600;
}

.rc-pos {
  color: var(--el-color-danger);
}

.rc-neg {
  color: var(--el-color-success);
}

.reconcile-breakdown {
  margin-top: 8px;
}

.rc-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
}
</style>
