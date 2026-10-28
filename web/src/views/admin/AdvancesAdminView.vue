<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">预支</h1>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select
          v-model="workerId"
          clearable
          filterable
          placeholder="全部员工"
          style="width: 180px"
          @change="load"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-select v-model="status" clearable placeholder="状态" style="width: 120px" @change="load">
          <el-option label="待扣回" value="open" />
          <el-option label="已扣回" value="repaid" />
          <el-option label="已作废" value="void" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.advances.write'" type="primary" @click="openCreate">登记预支</el-button>
      </div>
      <div class="muted" style="margin: -6px 0 10px; font-size: 12px">
        共 {{ summary.count || 0 }} 笔 · 待扣回 {{ formatMoney(summary.open_total) }} · 最近一期未结算工资发放时自动扣除
      </div>
      <div ref="tableHostRef">
      <el-table
        ref="tableRef"
        :data="rows"
        stripe
        border
        style="width: 100%"
        :max-height="tableMaxHeight"
        @header-dragend="onHeaderDragend"
      >
        <el-table-column prop="worker_name" label="员工" :width="colWidth('worker_name', 120)" show-overflow-tooltip resizable />
        <el-table-column column-key="amount" label="预支金额" :width="colWidth('amount', 120)" align="right" resizable>
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column prop="advanced_at" label="预支日期" :width="colWidth('advanced_at', 120)" resizable />
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 100)" resizable>
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'open' ? 'warning' : row.status === 'repaid' ? 'success' : 'info'"
              size="small"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" :width="colWidth('notes', 160)" show-overflow-tooltip resizable />
        <el-table-column column-key="actions" label="操作" width="100" fixed="right" :resizable="false">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'open' && canWrite"
              link
              type="danger"
              @click="voidAdvance(row)"
            >
              作废
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>

    <el-dialog v-model="dialog" title="登记预支" width="460px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="员工" required>
          <el-select v-model="form.worker_id" filterable placeholder="选择员工" style="width: 100%">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="发放账户">
          <el-select v-model="form.fund_account" clearable placeholder="可选" style="width: 100%">
            <el-option label="银行" value="bank" />
            <el-option label="现金" value="cash" />
            <el-option label="微信" value="wechat" />
            <el-option label="支付宝" value="alipay" />
            <el-option label="其它" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="金额" required>
          <el-input-number v-model="form.amount" :min="0.01" :precision="2" :step="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="预支日期">
          <el-date-picker v-model="form.advanced_at" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('btn.advances.write') || auth.isAdmin())
const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('salary-advances', tableRef, {
  flexKey: 'notes',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const now = new Date()
const workerId = ref<number | null>(null)
const status = ref<string | null>('open')
const workers = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const dialog = ref(false)
const saving = ref(false)

const form = reactive({
  worker_id: null as number | null,
  amount: 500,
  advanced_at: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`,
  fund_account: 'cash' as string | null,
  notes: '',
})

function formatMoney(v: any) {
  const n = Number(v || 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function statusLabel(s?: string) {
  if (s === 'open') return '待扣回'
  if (s === 'repaid') return '已扣回'
  if (s === 'void') return '已作废'
  return s || '—'
}

async function loadWorkers() {
  const res: any = await http.get('/workers', { params: { page: 1, page_size: 500, is_active: true } })
  workers.value = res.data?.items || []
}

async function load() {
  const res: any = await http.get('/salary-advances', {
    params: {
      worker_id: workerId.value || undefined,
      status: status.value || undefined,
    },
  })
  rows.value = res.data?.items || []
  summary.value = res.data?.summary || {}
}

function openCreate() {
  form.worker_id = null
  form.amount = 500
  form.advanced_at = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  form.fund_account = 'cash'
  form.notes = ''
  dialog.value = true
}

async function save() {
  if (!form.worker_id || !form.amount) {
    ElMessage.warning('请填写完整')
    return
  }
  saving.value = true
  try {
    await http.post('/salary-advances', {
      worker_id: form.worker_id,
      amount: form.amount,
      advanced_at: form.advanced_at || undefined,
      fund_account: form.fund_account || undefined,
      notes: form.notes || undefined,
    })
    ElMessage.success('已登记')
    dialog.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function voidAdvance(row: any) {
  await ElMessageBox.confirm(`作废 ${row.worker_name} 预支 ${formatMoney(row.amount)}？作废后不再从工资中扣除。`, '作废预支')
  await http.post(`/salary-advances/${row.id}/void`)
  ElMessage.success('已作废')
  await load()
}

onMounted(async () => {
  await loadWorkers()
  await load()
})
</script>
