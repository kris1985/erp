<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">请假登记</h1>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker v-model="month" type="month" value-format="YYYY-MM" placeholder="月份" @change="load" />
        <el-select v-model="workerId" clearable filterable placeholder="全部员工" style="width: 180px" @change="load">
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.leaves.write'" type="primary" @click="openCreate">登记</el-button>
      </div>
      <el-table :data="rows" stripe border>
        <el-table-column prop="worker_name" label="员工" min-width="100" />
        <el-table-column label="时间" min-width="220">
          <template #default="{ row }">{{ rangeText(row) }}</template>
        </el-table-column>
        <el-table-column label="天数" width="80" align="right">
          <template #default="{ row }">{{ Number(row.days || 0).toFixed(1) }}</template>
        </el-table-column>
        <el-table-column label="工资" width="70" align="center">
          <template #default="{ row }"><span v-if="row.pay_salary" class="leave-check">✓</span></template>
        </el-table-column>
        <el-table-column label="餐补" width="70" align="center">
          <template #default="{ row }"><span v-if="row.pay_meal" class="leave-check">✓</span></template>
        </el-table-column>
        <el-table-column label="住宿补" width="80" align="center">
          <template #default="{ row }"><span v-if="row.pay_housing" class="leave-check">✓</span></template>
        </el-table-column>
        <el-table-column label="其它补" width="80" align="center">
          <template #default="{ row }"><span v-if="row.pay_other" class="leave-check">✓</span></template>
        </el-table-column>
        <el-table-column prop="notes" label="请假原因" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button v-permission="'btn.leaves.write'" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-permission="'btn.leaves.write'" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="form.id ? '编辑请假' : '登记请假'" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="员工" required>
          <el-select v-model="form.worker_id" filterable placeholder="选择员工" style="width: 100%">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始" required>
          <div class="leave-range">
            <el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" placeholder="日期" />
            <el-radio-group v-model="form.start_half">
              <el-radio value="am">上午</el-radio>
              <el-radio value="pm">下午</el-radio>
            </el-radio-group>
          </div>
        </el-form-item>
        <el-form-item label="结束" required>
          <div class="leave-range">
            <el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" placeholder="日期" />
            <el-radio-group v-model="form.end_half">
              <el-radio value="am">上午</el-radio>
              <el-radio value="pm">下午</el-radio>
            </el-radio-group>
          </div>
        </el-form-item>
        <el-form-item label="天数">
          <span>{{ previewDays }}</span>
          <span class="muted">同一天只选上午或下午是 0.5 天，上午到下午是 1 天</span>
        </el-form-item>
        <el-form-item label="照发">
          <el-checkbox v-model="form.pay_salary">工资</el-checkbox>
          <el-checkbox v-model="form.pay_meal">餐补</el-checkbox>
          <el-checkbox v-model="form.pay_housing">住宿补</el-checkbox>
          <el-checkbox v-model="form.pay_other">其它补</el-checkbox>
          <div class="muted">不勾工资就按日工资扣。日工资 = 月底薪 ÷ 当月天数，四舍五入到元。</div>
        </el-form-item>
        <el-form-item label="请假原因">
          <el-input v-model="form.notes" maxlength="255" placeholder="请假原因" />
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

const month = ref(new Date().toISOString().slice(0, 7))
const workerId = ref<number | null>(null)
const workers = ref<any[]>([])
const rows = ref<any[]>([])
const dialog = ref(false)
const saving = ref(false)
const form = reactive<any>({
  id: null,
  worker_id: null,
  start_date: '',
  end_date: '',
  start_half: 'am',
  end_half: 'pm',
  pay_salary: false,
  pay_meal: false,
  pay_housing: false,
  pay_other: false,
  notes: '',
})

const previewDays = computed(() => {
  if (!form.start_date || !form.end_date) return '—'
  const start = new Date(`${form.start_date}T00:00:00`)
  const end = new Date(`${form.end_date}T00:00:00`)
  if (end < start || (form.start_date === form.end_date && form.start_half === 'pm' && form.end_half === 'am')) return '时间不对'
  if (form.start_date === form.end_date) return form.start_half === form.end_half ? '0.5' : '1.0'
  const middle = Math.round((end.getTime() - start.getTime()) / 86400000) - 1
  const first = form.start_half === 'am' ? 1 : 0.5
  const last = form.end_half === 'pm' ? 1 : 0.5
  return (first + Math.max(0, middle) + last).toFixed(1)
})

function halfLabel(value: string) {
  return value === 'pm' ? '下午' : '上午'
}
function rangeText(row: any) {
  const start = `${row.start_date} ${halfLabel(row.start_half)}`
  const end = `${row.end_date} ${halfLabel(row.end_half)}`
  return start === end ? start : `${start} 至 ${end}`
}
function monthRange(value: string) {
  const [year, mon] = value.split('-').map(Number)
  const last = new Date(year, mon, 0).getDate()
  const pad = String(mon).padStart(2, '0')
  return { date_from: `${year}-${pad}-01`, date_to: `${year}-${pad}-${String(last).padStart(2, '0')}` }
}

async function loadWorkers() {
  const res: any = await http.get('/workers', { params: { page: 1, page_size: 500, is_active: true } })
  workers.value = res.data?.items || []
}
async function load() {
  const range = month.value ? monthRange(month.value) : {}
  const res: any = await http.get('/leaves', { params: { ...range, worker_id: workerId.value || undefined } })
  rows.value = Array.isArray(res.data) ? res.data : []
}
function openCreate() {
  const today = new Date().toISOString().slice(0, 10)
  Object.assign(form, {
    id: null,
    worker_id: workerId.value,
    start_date: today,
    end_date: today,
    start_half: 'am',
    end_half: 'pm',
    pay_salary: false,
    pay_meal: false,
    pay_housing: false,
    pay_other: false,
    notes: '',
  })
  dialog.value = true
}
function openEdit(row: any) {
  Object.assign(form, {
    id: row.id,
    worker_id: row.worker_id,
    start_date: row.start_date,
    end_date: row.end_date,
    start_half: row.start_half,
    end_half: row.end_half,
    pay_salary: !!row.pay_salary,
    pay_meal: !!row.pay_meal,
    pay_housing: !!row.pay_housing,
    pay_other: !!row.pay_other,
    notes: row.notes || '',
  })
  dialog.value = true
}
async function save() {
  if (!form.worker_id || !form.start_date || !form.end_date) {
    ElMessage.warning('请选择员工和时间')
    return
  }
  saving.value = true
  try {
    const body = {
      worker_id: form.worker_id,
      start_date: form.start_date,
      end_date: form.end_date,
      start_half: form.start_half,
      end_half: form.end_half,
      pay_salary: !!form.pay_salary,
      pay_meal: !!form.pay_meal,
      pay_housing: !!form.pay_housing,
      pay_other: !!form.pay_other,
      notes: form.notes || null,
    }
    if (form.id) await http.patch(`/leaves/${form.id}`, body)
    else await http.post('/leaves', body)
    ElMessage.success('已保存')
    dialog.value = false
    await load()
  } finally {
    saving.value = false
  }
}
async function remove(row: any) {
  await ElMessageBox.confirm(`删除 ${row.worker_name} 的这条请假？`, '删除请假')
  await http.delete(`/leaves/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(async () => {
  await loadWorkers()
  await load()
})
</script>

<style scoped>
.leave-range {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  align-items: center;
}
.muted {
  margin-left: 8px;
  color: #94a3b8;
  font-size: 12px;
}
.leave-check {
  color: #067a3e;
  font-weight: 700;
}
</style>
