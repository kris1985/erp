<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">用户</h1>
        <p class="page-desc">后台登录账号 · 分配角色</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="openCreate">新增用户</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
        <el-table-column prop="username" label="用户名" :width="colWidth('username', 120)" resizable />
        <el-table-column prop="display_name" label="显示名" :width="colWidth('display_name', 120)" resizable />
        <el-table-column column-key="role" label="角色" :width="colWidth('role', 110)" resizable>
          <template #default="{ row }">{{ roleLabel(row.role) }}</template>
        </el-table-column>
        <el-table-column column-key="status" label="状态" :min-width="flexColMinWidth('status', 90)" resizable>
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 200)" resizable>
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
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
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑用户' : '新增用户'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!form.id" />
        </el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.code" :label="r.name" :value="r.code" />
          </el-select>
        </el-form-item>
        <el-form-item :label="form.id ? '新密码' : '密码'">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="form.id ? '不改请留空' : ''"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('users-list', tableRef)
const ROLE_FALLBACK = [
  { code: 'admin', name: '管理员' },
  { code: 'manager', name: '主管' },
  { code: 'leader', name: '组长' },
]

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const roleOptions = ref([...ROLE_FALLBACK])
const visible = ref(false)
const form = reactive<any>({ id: null, username: '', display_name: '', role: 'manager', password: '' })

function roleLabel(code: string) {
  return roleOptions.value.find((r) => r.code === code)?.name || code
}

async function loadRoles() {
  try {
    const res: any = await http.get('/roles')
    const items = res.data?.items || []
    if (items.length) {
      roleOptions.value = items.map((r: any) => ({ code: r.code, name: r.name }))
    }
  } catch {
    roleOptions.value = [...ROLE_FALLBACK]
  }
}

async function load() {
  const res: any = await http.get('/users', {
    params: { page: page.value, page_size: pageSize.value },
  })
  rows.value = res.data.items
  total.value = res.data.total || 0
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function openCreate() {
  Object.assign(form, { id: null, username: '', display_name: '', role: 'manager', password: '' })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, { ...row, password: '' })
  visible.value = true
}

async function save() {
  if (form.id) {
    const payload: any = { display_name: form.display_name, role: form.role }
    if (form.password) payload.password = form.password
    await http.patch(`/users/${form.id}`, payload)
  } else {
    if (!form.password) {
      ElMessage.warning('请设置密码')
      return
    }
    await http.post('/users', {
      username: form.username,
      password: form.password,
      display_name: form.display_name,
      role: form.role,
    })
  }
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

async function toggleActive(row: any) {
  await http.patch(`/users/${row.id}`, { is_active: !row.is_active })
  ElMessage.success('已更新')
  await load()
}

onMounted(async () => {
  await loadRoles()
  await load()
  measureTableHeight()
})
</script>
