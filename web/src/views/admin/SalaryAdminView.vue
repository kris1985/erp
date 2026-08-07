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
      <el-tag v-if="isLocked" type="danger" effect="plain">已月结锁定</el-tag>
      <el-tag v-else type="success" effect="plain">未锁定</el-tag>
      <el-button v-if="!isLocked" type="warning" @click="toggleLock(true)">锁定本月</el-button>
      <el-button v-else type="primary" plain @click="toggleLock(false)">解锁本月</el-button>
      <el-button type="primary" @click="exportCsv">导出月结 CSV</el-button>
      <el-button type="success" :disabled="!isLocked" @click="exportBank">导出银行代发</el-button>
      <div class="spacer" />
      <span class="muted">
        应发合计 ¥{{ wageTotal.toFixed(2) }}
        <template v-if="isLocked"> · 已确认 {{ ackCount }}/{{ total }}</template>
      </span>
    </div>
    <div ref="tableHostRef">
    <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @row-click="openDetail" @header-dragend="onHeaderDragend">
      <el-table-column prop="worker_name" label="员工" :width="colWidth('worker_name', 100)" resizable />
      <el-table-column prop="salary_model" label="计薪" :width="colWidth('salary_model', 120)" resizable>
        <template #default="{ row }">{{ modelLabel(row.salary_model) }}</template>
      </el-table-column>
      <el-table-column prop="log_count" label="报工条数" :width="colWidth('log_count', 100)" resizable />
      <el-table-column prop="piece_qty" label="计件量" :width="colWidth('piece_qty', 90)" resizable />
      <el-table-column prop="base_salary" label="底薪" :width="colWidth('base_salary', 100)" resizable>
        <template #default="{ row }">¥{{ Number(row.base_salary || 0).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="total_piece_wage" label="计件全额" :width="colWidth('total_piece_wage', 110)" resizable>
        <template #default="{ row }">¥{{ Number(row.total_piece_wage).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="payable_piece_wage" label="计件应发" :width="colWidth('payable_piece_wage', 110)" resizable>
        <template #default="{ row }">¥{{ Number(row.payable_piece_wage ?? row.total_piece_wage).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="total_wage" label="应发合计" :width="colWidth('total_wage', 120)" resizable>
        <template #default="{ row }">
          <strong>¥{{ Number(row.total_wage ?? row.total_piece_wage).toFixed(2) }}</strong>
        </template>
      </el-table-column>
      <el-table-column column-key="确认" label="确认" :min-width="flexColMinWidth('确认', 90)" resizable>
        <template #default="{ row }">
          <el-tag v-if="row.acknowledged" type="success" size="small">已签</el-tag>
          <el-tag v-else-if="isLocked" type="warning" size="small">待签</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 100)" resizable>
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
          底薪 ¥{{ Number(detail.base_salary || 0).toFixed(2) }}
          <span v-if="detail.base_quota"> · 定额 {{ detail.base_quota }}</span>
          · 计件量 {{ detail.piece_qty || 0 }}
        </div>
        <div>
          计件全额 ¥{{ Number(detail.total_piece_wage || 0).toFixed(2) }}
          · 计件应发 ¥{{ Number(detail.payable_piece_wage ?? detail.total_piece_wage).toFixed(2) }}
          · <strong>应发合计 ¥{{ Number(detail.total_wage ?? detail.total_piece_wage).toFixed(2) }}</strong>
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
          <template #default="{ row }">¥{{ Number(row.amount).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </el-drawer>
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
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('salary-list', tableRef)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('salary-detail')
const auth = useAuthStore()
const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const isLocked = ref(false)
const ackCount = ref(0)
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

const wageTotal = computed(() =>
  rows.value.reduce((s, r) => s + Number(r.total_wage ?? r.total_piece_wage ?? 0), 0),
)

async function load() {
  const res: any = await http.get('/salary', {
    params: { year_month: month.value, page: page.value, page_size: pageSize.value },
  })
  rows.value = res.data.items
  total.value = res.data.total ?? rows.value.length
  isLocked.value = !!res.data.is_locked
  ackCount.value = Number(res.data.acknowledged_count || 0)
  void nextTick(measureTableHeight)
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

onMounted(load)
</script>

<style scoped>
.settle-summary {
  margin-bottom: 14px;
  line-height: 1.6;
}
</style>
