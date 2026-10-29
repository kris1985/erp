<template>
  <div class="admin-app">
    <div class="admin-layout">
      <aside class="admin-aside">
        <div class="admin-brand">
          <span aria-hidden="true"></span>
          <span class="admin-brand-text" title="铁玉兰运营">铁玉兰运营</span>
        </div>
        <nav class="admin-nav" aria-label="运营导航">
          <span class="admin-nav-item is-active">
            <span class="admin-nav-row">
              <span class="admin-nav-icon"><el-icon><OfficeBuilding /></el-icon></span>
              <span class="admin-nav-label">租户</span>
            </span>
          </span>
        </nav>
        <div class="admin-aside-user">
          <button type="button" class="admin-user-trigger" :title="ops.name || '运营'" @click="logout">
            <span class="admin-user-avatar">{{ userInitial }}</span>
            <span class="admin-user-meta">
              <span class="admin-user-name">{{ ops.name || '运营' }}</span>
              <span class="admin-user-role">退出登录</span>
            </span>
          </button>
        </div>
      </aside>
      <div class="admin-main has-content-head">
        <header class="admin-content-head">
          <h1 class="admin-content-title">租户</h1>
        </header>
        <div class="admin-content">
      <div class="admin-card">
        <div class="admin-toolbar">
          <el-input
            v-model="keyword"
            clearable
            placeholder="名称、管理员或手机号"
            style="width: 240px"
            @keyup.enter="load"
            @clear="load"
          />
          <el-button type="primary" @click="openCreate">新增租户</el-button>
          <el-button :loading="loading" @click="load">刷新</el-button>
        </div>
        <div ref="tableHostRef">
          <el-table
            ref="tableRef"
            :data="rows"
            stripe
            border
            style="width: 100%"
            v-loading="loading"
            :max-height="tableMaxHeight"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column prop="name" label="租户名称" :width="colWidth('name', 180)" show-overflow-tooltip resizable />
            <el-table-column prop="admin_name" label="管理员" :width="colWidth('admin_name', 120)" show-overflow-tooltip resizable />
            <el-table-column prop="admin_mobile" label="手机号" :width="colWidth('admin_mobile', 130)" resizable />
            <el-table-column column-key="expires_on" label="截止时间" :width="colWidth('expires_on', 120)" resizable>
              <template #default="{ row }">{{ row.expires_on || '长期' }}</template>
            </el-table-column>
            <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="employee_count" label="人数" :width="colWidth('employee_count', 72)" align="right" resizable />
            <el-table-column column-key="created_at" label="创建时间" :width="colWidth('created_at', 150)" resizable>
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 220)" resizable>
              <template #default="{ row }">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button link @click="openReset(row)">重置密码</el-button>
                <el-button link type="danger" @click="removeRow(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        </div>
      </div>
    </div>
    </div>
  </div>

    <el-dialog v-model="editVisible" :title="form.id ? '编辑租户' : '新增租户'" width="520px" destroy-on-close>
      <el-form label-width="108px">
        <el-form-item label="租户名称" required>
          <el-input v-model="form.name" maxlength="100" placeholder="工厂名称" />
        </el-form-item>
        <el-form-item label="管理员姓名">
          <el-input v-model="form.admin_name" maxlength="50" placeholder="默认：管理员" />
        </el-form-item>
        <el-form-item label="管理员手机号" required>
          <el-input v-model="form.admin_mobile" maxlength="11" placeholder="用于登录工厂后台" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="初始密码" required>
          <el-input v-model="form.password" type="password" show-password maxlength="64" placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker
            v-model="form.expires_on"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="不选则长期有效"
            clearable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" maxlength="500" placeholder="仅运营可见" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <p class="ops-hint">截止日当天仍可登录。停用或过期后，该厂所有账号不能进入系统。管理员手机号同时作为登录账号；同一手机号可开通多个工厂，登录时选择进入哪一家。</p>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" :title="`重置密码 · ${resetTarget?.name || ''}`" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="新密码" required>
          <el-input v-model="resetPassword" type="password" show-password maxlength="64" placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitReset">保存</el-button>
      </template>
    </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { OfficeBuilding } from '@element-plus/icons-vue'
import opsHttp from '@/api/opsHttp'
import { useOpsAuthStore } from '@/stores/opsAuth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type TenantRow = {
  id: number
  name: string
  admin_name: string
  admin_mobile: string
  expires_on: string | null
  is_active: boolean
  notes: string
  status: 'active' | 'expired' | 'disabled'
  employee_count: number
  created_at: string | null
}

const ops = useOpsAuthStore()
const router = useRouter()
const userInitial = computed(() => (ops.name || '运').slice(0, 1))
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const rows = ref<TenantRow[]>([])
const editVisible = ref(false)
const resetVisible = ref(false)
const resetting = ref(false)
const resetPassword = ref('')
const resetTarget = ref<TenantRow | null>(null)
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('ops-tenants', tableRef, {
  flexKey: 'name',
  flexDefaultMin: 180,
})

const form = reactive({
  id: 0,
  name: '',
  admin_name: '',
  admin_mobile: '',
  password: '',
  expires_on: '' as string | null,
  notes: '',
  is_active: true,
})

function statusLabel(status: string) {
  if (status === 'expired') return '已到期'
  if (status === 'disabled') return '已停用'
  return '正常'
}

function statusType(status: string) {
  if (status === 'expired') return 'danger'
  if (status === 'disabled') return 'info'
  return 'success'
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

async function load() {
  loading.value = true
  try {
    const res: any = await opsHttp.get('/operators/tenants', {
      params: { keyword: keyword.value.trim() || undefined },
    })
    rows.value = res.data || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
    measureTableHeight()
  }
}

function openCreate() {
  form.id = 0
  form.name = ''
  form.admin_name = ''
  form.admin_mobile = ''
  form.password = ''
  form.expires_on = ''
  form.notes = ''
  form.is_active = true
  editVisible.value = true
}

function openEdit(row: TenantRow) {
  form.id = row.id
  form.name = row.name
  form.admin_name = row.admin_name || ''
  form.admin_mobile = row.admin_mobile || ''
  form.password = ''
  form.expires_on = row.expires_on || ''
  form.notes = row.notes || ''
  form.is_active = row.is_active
  editVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写租户名称')
    return
  }
  if (!/^1\d{10}$/.test(form.admin_mobile.trim())) {
    ElMessage.warning('管理员手机号须为 11 位手机号')
    return
  }
  if (!form.id && form.password.length < 6) {
    ElMessage.warning('初始密码至少 6 位')
    return
  }
  saving.value = true
  const payload = {
    name: form.name.trim(),
    admin_name: form.admin_name.trim() || '管理员',
    admin_mobile: form.admin_mobile.trim(),
    password: form.id ? undefined : form.password,
    expires_on: form.expires_on || null,
    notes: form.notes.trim(),
    is_active: form.is_active,
  }
  try {
    if (form.id) {
      await opsHttp.put(`/operators/tenants/${form.id}`, payload)
      ElMessage.success('已保存')
    } else {
      await opsHttp.post('/operators/tenants', payload)
      ElMessage.success('已开通')
    }
    editVisible.value = false
    await load()
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    saving.value = false
  }
}

function openReset(row: TenantRow) {
  resetTarget.value = row
  resetPassword.value = ''
  resetVisible.value = true
}

async function submitReset() {
  if (!resetTarget.value) return
  if (resetPassword.value.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  resetting.value = true
  try {
    await opsHttp.post(`/operators/tenants/${resetTarget.value.id}/reset-password`, {
      password: resetPassword.value,
    })
    ElMessage.success('已重置管理员密码')
    resetVisible.value = false
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    resetting.value = false
  }
}

async function removeRow(row: TenantRow) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.name}」？已有人员或业务数据的租户不能删，请改为停用。`,
      '删除租户',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await opsHttp.delete(`/operators/tenants/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch {
    // 错误由 opsHttp 提示
  }
}

function logout() {
  ops.logout()
  router.replace('/ops/login')
}

onMounted(load)
</script>

<style scoped>
.ops-hint {
  margin: 0;
  color: var(--ws-muted);
  font-size: 12px;
  line-height: 1.6;
}
</style>
