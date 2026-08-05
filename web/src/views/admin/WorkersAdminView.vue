<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">员工管理</h1>
        <p class="page-desc">档案 · 计薪 · 账号</p>
      </div>
    </header>
  <div class="admin-card">
    <div class="admin-toolbar">
      <el-button type="primary" @click="openCreate">新增员工</el-button>
    </div>
    <el-table :data="rows" stripe border style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="姓名" min-width="100" />
      <el-table-column prop="mobile" label="手机" min-width="130" />
      <el-table-column label="职位" min-width="110">
        <template #default="{ row }">{{ row.position_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="角色" min-width="90">
        <template #default="{ row }">{{ roleLabel(row.role) }}</template>
      </el-table-column>
      <el-table-column label="计薪" min-width="120">
        <template #default="{ row }">{{ salaryLabel(row.salary_model) }}</template>
      </el-table-column>
      <el-table-column prop="base_salary" label="底薪" min-width="90" />
      <el-table-column prop="base_quota" label="定额" min-width="90" />
      <el-table-column label="银行卡" min-width="140">
        <template #default="{ row }">
          <span v-if="row.bank_account">{{ maskBank(row.bank_account) }}</span>
          <span v-else class="muted">未填</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '在职' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link @click="resetPwd(row)">重置密码</el-button>
          <el-button link @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
        </template>
      </el-table-column>
    </el-table>

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

    <el-dialog v-model="visible" :title="form.id ? '编辑员工' : '新增员工'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="form.mobile" /></el-form-item>
        <el-form-item label="职位">
          <el-select v-model="form.position_id" clearable placeholder="请选择" style="width: 100%">
            <el-option
              v-for="p in positionOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="工人" value="worker" />
            <el-option label="组长" value="leader" />
          </el-select>
        </el-form-item>
        <el-form-item label="计薪方式">
          <el-select v-model="form.salary_model" style="width: 100%">
            <el-option label="纯计件" value="pure_piece" />
            <el-option label="底薪+计件" value="base_plus_piece" />
            <el-option label="计时" value="hourly" />
            <el-option label="固定" value="fixed" />
          </el-select>
        </el-form-item>
        <el-form-item label="底薪"><el-input-number v-model="form.base_salary" :min="0" :precision="2" /></el-form-item>
        <el-form-item label="定额"><el-input-number v-model="form.base_quota" :min="0" /></el-form-item>
        <el-form-item label="收款户名">
          <el-input v-model="form.bank_account_name" placeholder="默认与姓名相同" />
        </el-form-item>
        <el-form-item label="银行卡号">
          <el-input v-model="form.bank_account" placeholder="银行代发用" />
        </el-form-item>
        <el-form-item label="开户行">
          <el-input v-model="form.bank_name" placeholder="如 工行XX支行" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const ROLE_LABELS: Record<string, string> = {
  worker: '工人',
  leader: '组长',
}
const SALARY_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  hourly: '计时',
  fixed: '固定',
}

function roleLabel(v: string) {
  return ROLE_LABELS[v] || v
}
function salaryLabel(v: string) {
  return SALARY_LABELS[v] || v
}

function maskBank(no: string) {
  const s = String(no || '')
  if (s.length <= 8) return s
  return `${s.slice(0, 4)}****${s.slice(-4)}`
}

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const positions = ref<any[]>([])
const visible = ref(false)
const form = reactive<any>({
  id: null,
  name: '',
  mobile: '',
  position_id: null,
  role: 'worker',
  salary_model: 'pure_piece',
  base_salary: 0,
  base_quota: 0,
  bank_account: '',
  bank_name: '',
  bank_account_name: '',
})

const positionOptions = computed(() => {
  const currentId = form.position_id
  return positions.value.filter((p) => p.is_active || p.id === currentId)
})

async function load() {
  const [wRes, pRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page: page.value, page_size: pageSize.value } }),
    http.get('/positions', { params: { page_size: 200 } }),
  ])
  rows.value = wRes.data.items
  total.value = wRes.data.total || 0
  positions.value = pRes.data.items
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    mobile: '',
    position_id: null,
    role: 'worker',
    salary_model: 'pure_piece',
    base_salary: 0,
    base_quota: 0,
    bank_account: '',
    bank_name: '',
    bank_account_name: '',
  })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, {
    ...row,
    position_id: row.position_id ?? null,
    base_salary: Number(row.base_salary || 0),
    base_quota: Number(row.base_quota || 0),
    bank_account: row.bank_account || '',
    bank_name: row.bank_name || '',
    bank_account_name: row.bank_account_name || '',
  })
  visible.value = true
}

async function save() {
  const payload = {
    name: form.name,
    mobile: form.mobile || null,
    position_id: form.position_id ?? null,
    role: form.role,
    salary_model: form.salary_model,
    base_salary: form.base_salary,
    base_quota: form.base_quota,
    bank_account: form.bank_account || null,
    bank_name: form.bank_name || null,
    bank_account_name: form.bank_account_name || null,
  }
  if (form.id) await http.patch(`/workers/${form.id}`, payload)
  else await http.post('/workers', payload)
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

async function toggleActive(row: any) {
  await http.patch(`/workers/${row.id}`, { is_active: !row.is_active })
  ElMessage.success('已更新')
  await load()
}

async function resetPwd(row: any) {
  await http.patch(`/workers/${row.id}`, { reset_password: true })
  ElMessage.success('已重置为默认密码 123456，下次登录须改密')
  await load()
}

onMounted(load)
</script>
