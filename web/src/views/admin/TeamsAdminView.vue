<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">班组</h1>
        <p class="page-desc">组长账号 · 组员一人一组 · 数据隔离</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="openCreate">新建班组</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="rows" stripe border style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="班组" min-width="140" />
        <el-table-column label="组长" min-width="160">
          <template #default="{ row }">
            {{ row.leader_name || '—' }}
            <span v-if="row.leader_username" class="muted">（{{ row.leader_username }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="人数" width="80">
          <template #default="{ row }">{{ row.member_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="组员" min-width="220">
          <template #default="{ row }">
            {{ (row.members || []).map((m: any) => m.name).join('、') || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link @click="openMembers(row)">成员</el-button>
            <el-button link @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="formVisible" :title="form.id ? '编辑班组' : '新建班组'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 针车一组" />
        </el-form-item>
        <el-form-item label="组长账号">
          <el-select v-model="form.leader_user_id" filterable style="width: 100%" placeholder="选择员工账号">
            <el-option
              v-for="u in leaderUsers"
              :key="u.id"
              :label="`${u.display_name}（${u.username}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberVisible" title="班组成员" width="520px">
      <p class="muted" style="margin: 0 0 12px">一人只能在一个班组；已在他组的不可选。</p>
      <el-checkbox-group v-model="memberIds">
        <div v-for="w in workers" :key="w.id" style="margin-bottom: 8px">
          <el-checkbox
            :label="w.id"
            :disabled="isLockedToOther(w.id)"
          >
            {{ w.name }}
            <span v-if="w.mobile" class="muted"> · {{ w.mobile }}</span>
            <span v-if="otherTeamName(w.id)" class="muted"> · 已在「{{ otherTeamName(w.id) }}」</span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="memberVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMembers">保存成员</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const workers = ref<any[]>([])
const leaderUsers = ref<any[]>([])
const workerMap = ref<Record<number, { team_id: number; team_name: string }>>({})
const formVisible = ref(false)
const memberVisible = ref(false)
const saving = ref(false)
const editingTeamId = ref<number | null>(null)
const memberIds = ref<number[]>([])

const form = reactive<{ id: number | null; name: string; leader_user_id: number | null }>({
  id: null,
  name: '',
  leader_user_id: null,
})

function isLockedToOther(workerId: number) {
  const hit = workerMap.value[workerId]
  if (!hit) return false
  return hit.team_id !== editingTeamId.value
}

function otherTeamName(workerId: number) {
  const hit = workerMap.value[workerId]
  if (!hit || hit.team_id === editingTeamId.value) return ''
  return hit.team_name
}

async function load() {
  const [t, w, u, m]: any[] = await Promise.all([
    http.get('/teams', { params: { include_inactive: true } }),
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/teams/leader-candidates'),
    http.get('/teams/worker-map'),
  ])
  rows.value = t.data.items || []
  workers.value = (w.data.items || []).filter((x: any) => x.is_active !== false)
  leaderUsers.value = u.data.items || []
  workerMap.value = m.data.map || {}
}

function openCreate() {
  form.id = null
  form.name = ''
  form.leader_user_id = leaderUsers.value[0]?.id || null
  formVisible.value = true
}

function openEdit(row: any) {
  form.id = row.id
  form.name = row.name
  form.leader_user_id = row.leader_user_id
  formVisible.value = true
}

async function saveForm() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写班组名称')
    return
  }
  if (!form.leader_user_id) {
    ElMessage.warning('请选择组长账号')
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await http.patch(`/teams/${form.id}`, {
        name: form.name.trim(),
        leader_user_id: form.leader_user_id,
      })
    } else {
      await http.post('/teams', {
        name: form.name.trim(),
        leader_user_id: form.leader_user_id,
        worker_ids: [],
      })
    }
    ElMessage.success('已保存')
    formVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function openMembers(row: any) {
  editingTeamId.value = row.id
  memberIds.value = (row.members || []).map((m: any) => m.id)
  memberVisible.value = true
}

async function saveMembers() {
  if (!editingTeamId.value) return
  saving.value = true
  try {
    await http.put(`/teams/${editingTeamId.value}/members`, { worker_ids: memberIds.value })
    ElMessage.success('成员已更新')
    memberVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleActive(row: any) {
  try {
    await http.patch(`/teams/${row.id}`, { is_active: !row.is_active })
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

onMounted(load)
</script>
