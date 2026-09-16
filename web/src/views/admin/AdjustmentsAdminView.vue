<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">奖惩</h1>
        <p class="page-desc">奖励 · 惩罚 · 计入对应结算月应发</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="month"
          type="month"
          value-format="YYYY-MM"
          placeholder="结算月"
          @change="load"
        />
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
        <el-select v-model="kind" clearable placeholder="类型" style="width: 110px" @change="load">
          <el-option label="奖励" value="reward" />
          <el-option label="惩罚" value="penalty" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <el-button
          v-permission="'btn.adjustments.write'"
          :disabled="isLocked"
          @click="rebuildLate"
        >
          重算迟到扣款
        </el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.adjustments.write'" type="primary" :disabled="isLocked" @click="openCreate">
          录入
        </el-button>
      </div>
      <div class="muted" style="margin: -6px 0 10px; font-size: 12px">
        共 {{ summary.count || 0 }} 条 · 奖励 {{ formatMoney(summary.reward_total) }} · 扣罚
        {{ formatMoney(summary.penalty_total) }} · 净额 {{ formatMoney(summary.net) }}
        <el-tag v-if="isLocked" type="danger" size="small" effect="plain" style="margin-left: 8px">
          本月已锁定
        </el-tag>
      </div>
      <el-table :data="rows" stripe border>
        <el-table-column prop="worker_name" label="员工" min-width="100" />
        <el-table-column prop="year_month" label="结算月" width="100" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'reward' ? 'success' : 'danger'" size="small">
              {{ row.kind === 'reward' ? '奖励' : '惩罚' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="category_label" label="分类" width="110" />
        <el-table-column label="金额" width="110" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.kind === 'reward' ? '#067a3e' : '#c03639' }">
              {{ row.kind === 'reward' ? '+' : '-' }}{{ formatMoney(row.amount) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="120" show-overflow-tooltip />
        <el-table-column prop="notes" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">{{ sourceLabel(row.source) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <template v-if="row.source === 'manual' && canWrite && !isLocked">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="form.id ? '编辑奖惩' : '录入奖惩'" width="480px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="员工" required>
          <el-select v-model="form.worker_id" filterable placeholder="选择员工" style="width: 100%" :disabled="!!form.id">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="结算月" required>
          <el-date-picker v-model="form.year_month" type="month" value-format="YYYY-MM" style="width: 100%" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group v-model="form.kind">
            <el-radio value="reward">奖励</el-radio>
            <el-radio value="penalty">惩罚</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" style="width: 100%">
            <el-option v-for="c in categories" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="金额" required>
          <el-input-number v-model="form.amount" :min="0.01" :precision="2" :step="10" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" maxlength="100" />
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
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('btn.adjustments.write') || auth.isAdmin())

const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const workerId = ref<number | null>(null)
const kind = ref<string | null>(null)
const workers = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const isLocked = ref(false)
const dialog = ref(false)
const saving = ref(false)

const categories = [
  { value: 'full_attendance', label: '全勤奖' },
  { value: 'overtime', label: '加班奖' },
  { value: 'late', label: '迟到扣款' },
  { value: 'early', label: '早退扣款' },
  { value: 'other', label: '其它' },
]

const form = reactive({
  id: null as number | null,
  worker_id: null as number | null,
  year_month: month.value,
  kind: 'reward',
  category: 'other',
  amount: 100,
  title: '',
  notes: '',
})

function formatMoney(v: any) {
  const n = Number(v || 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function sourceLabel(s?: string) {
  if (s === 'auto_late') return '考勤自动'
  if (s === 'advance') return '预支扣回'
  return '手工'
}

async function loadWorkers() {
  const res: any = await http.get('/workers', { params: { page: 1, page_size: 500, is_active: true } })
  workers.value = res.data?.items || []
}

async function loadLock() {
  if (!month.value) return
  try {
    const res: any = await http.get('/salary/lock', { params: { year_month: month.value } })
    isLocked.value = !!res.data?.is_locked
  } catch {
    isLocked.value = false
  }
}

async function load() {
  await loadLock()
  const res: any = await http.get('/worker-adjustments', {
    params: {
      year_month: month.value || undefined,
      worker_id: workerId.value || undefined,
      kind: kind.value || undefined,
    },
  })
  rows.value = res.data?.items || []
  summary.value = res.data?.summary || {}
}

function openCreate() {
  form.id = null
  form.worker_id = null
  form.year_month = month.value
  form.kind = 'reward'
  form.category = 'full_attendance'
  form.amount = 100
  form.title = ''
  form.notes = ''
  dialog.value = true
}

function openEdit(row: any) {
  form.id = row.id
  form.worker_id = row.worker_id
  form.year_month = row.year_month
  form.kind = row.kind
  form.category = row.category
  form.amount = Number(row.amount)
  form.title = row.title || ''
  form.notes = row.notes || ''
  dialog.value = true
}

async function save() {
  if (!form.worker_id || !form.year_month || !form.amount) {
    ElMessage.warning('请填写完整')
    return
  }
  saving.value = true
  try {
    const payload = {
      worker_id: form.worker_id,
      year_month: form.year_month,
      kind: form.kind,
      category: form.category,
      amount: form.amount,
      title: form.title || undefined,
      notes: form.notes || undefined,
    }
    if (form.id) {
      await http.patch(`/worker-adjustments/${form.id}`, payload)
    } else {
      await http.post('/worker-adjustments', payload)
    }
    ElMessage.success('已保存')
    dialog.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`删除「${row.worker_name}」${row.title || row.category_label}？`, '确认')
  await http.delete(`/worker-adjustments/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

async function rebuildLate() {
  if (!month.value) return
  await ElMessageBox.confirm(`按考勤规则重算 ${month.value} 迟到/早退扣款？将覆盖自动项。`, '重算迟到扣款')
  const res: any = await http.post('/salary/rebuild-late-deductions', { year_month: month.value })
  const d = res.data || {}
  if (!d.enabled) {
    ElMessage.info('迟到扣款规则未启用，已清除自动项')
  } else {
    ElMessage.success(`已生成 ${d.workers || 0} 人，合计 ${formatMoney(d.total_amount)}`)
  }
  await load()
}

onMounted(async () => {
  await loadWorkers()
  await load()
})
</script>
