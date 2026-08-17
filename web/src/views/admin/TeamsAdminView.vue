<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">班组</h1>
        <p class="page-desc">组长为员工 · 组员一人一组 · 数据隔离</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="openCreate">新建班组</el-button>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <span class="muted" style="font-size: 13px">多产线</span>
        <el-switch v-model="enableProductionLines" @change="toggleProductionLines" />
        <el-button @click="openLines">产线管理</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
        <el-table-column prop="name" label="班组" :width="colWidth('name', 140)" resizable />
        <el-table-column column-key="leader" label="组长" :width="colWidth('leader', 160)" resizable>
          <template #default="{ row }">
            {{ row.leader_name || '—' }}
            <span v-if="row.leader_mobile" class="muted">（{{ row.leader_mobile }}）</span>
          </template>
        </el-table-column>
        <el-table-column column-key="org" label="所属" :width="colWidth('org', 130)" resizable>
          <template #default="{ row }">
            <template v-if="enableProductionLines">{{ row.production_line_name || '—' }}</template>
            <template v-else>{{ row.department_name || '—' }}</template>
          </template>
        </el-table-column>
        <el-table-column column-key="member_count" label="人数" :width="colWidth('member_count', 80)" resizable>
          <template #default="{ row }">{{ row.member_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column column-key="members" label="组员" :min-width="flexColMinWidth('members', 220)" show-overflow-tooltip resizable>
          <template #default="{ row }">
            {{ (row.members || []).map((m: any) => m.name).join('、') || '—' }}
          </template>
        </el-table-column>
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 200)" resizable>
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link @click="openMembers(row)">成员</el-button>
            <el-button link @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>

    <el-dialog v-model="formVisible" :title="form.id ? '编辑班组' : '新建班组'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 针车一组" />
        </el-form-item>
        <el-form-item label="组长">
          <el-select v-model="form.leader_worker_id" filterable style="width: 100%" placeholder="选择员工">
            <el-option
              v-for="w in leaderWorkers"
              :key="w.id"
              :label="w.mobile ? `${w.name}（${w.mobile}）` : w.name"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="enableProductionLines" label="所属产线">
          <el-select v-model="form.production_line_id" clearable filterable style="width: 100%" placeholder="选择产线">
            <el-option v-for="l in lines" :key="l.id" :label="l.department_name ? `${l.name}（${l.department_name}）` : l.name" :value="l.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="所属部门">
          <el-select v-model="form.department_id" clearable filterable style="width: 100%" placeholder="选择部门">
            <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 产线管理 -->
    <el-dialog v-model="lineVisible" title="产线管理" width="560px">
      <div class="admin-toolbar" style="margin-bottom: 10px">
        <el-input v-model="lineForm.name" placeholder="产线名称，如 成型线A" style="width: 220px" />
        <el-select v-model="lineForm.department_id" clearable filterable placeholder="所属部门" style="width: 160px">
          <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-button type="primary" @click="saveLine">新增</el-button>
      </div>
      <el-table :data="lines" stripe border size="small">
        <el-table-column prop="name" label="产线" />
        <el-table-column prop="department_name" label="所属部门" width="120">
          <template #default="{ row }">{{ row.department_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="team_count" label="班组数" width="80" align="right" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="editLine(row)">编辑</el-button>
            <el-button link @click="deleteLine(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="lineVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="memberVisible"
      width="780px"
      class="team-members-dialog"
      destroy-on-close
      align-center
    >
      <template #header>
        <div class="tm-header">
          <div class="tm-header-text">
            <div class="tm-title">班组成员</div>
            <div class="tm-sub">
              <span class="tm-team-name">{{ editingTeamName }}</span>
              <span class="tm-dot">·</span>
              一人一组，点击即可加入或移除
            </div>
          </div>
          <div class="tm-stat">
            <strong>{{ memberIds.length }}</strong>
            <span>已选</span>
          </div>
        </div>
      </template>

      <div class="tm-body">
        <el-input
          v-model="memberKeyword"
          clearable
          placeholder="搜索姓名 / 手机号"
          class="tm-search"
        >
          <template #prefix>
            <el-icon class="tm-search-icon"><Search /></el-icon>
          </template>
        </el-input>

        <div class="tm-transfer">
          <section class="tm-pane">
            <header class="tm-pane-head">
              <span class="tm-pane-label">可选员工</span>
              <span class="tm-pane-count">{{ availableWorkers.length }}</span>
            </header>
            <div class="tm-pane-list">
              <button
                v-for="w in availableWorkers"
                :key="`avl-${w.id}`"
                type="button"
                class="tm-person"
                @click="addMember(w.id)"
              >
                <span class="tm-avatar" :style="avatarStyle(w.name)">{{ initialOf(w.name) }}</span>
                <span class="tm-person-meta">
                  <span class="tm-person-name">{{ w.name }}</span>
                  <span class="tm-person-sub">{{ w.mobile || '无手机号' }}</span>
                </span>
                <span class="tm-person-action">加入</span>
              </button>
              <div v-if="!availableWorkers.length" class="tm-empty">
                {{ memberKeyword.trim() ? '没有匹配的可选员工' : '暂无可选员工' }}
              </div>

              <template v-if="lockedWorkers.length">
                <div class="tm-locked-label">他组不可选 · {{ lockedWorkers.length }}</div>
                <div
                  v-for="w in lockedWorkers"
                  :key="`lock-${w.id}`"
                  class="tm-person tm-person-locked"
                >
                  <span class="tm-avatar tm-avatar-muted">{{ initialOf(w.name) }}</span>
                  <span class="tm-person-meta">
                    <span class="tm-person-name">{{ w.name }}</span>
                    <span class="tm-person-sub">已在「{{ otherTeamName(w.id) }}」</span>
                  </span>
                </div>
              </template>
            </div>
          </section>

          <div class="tm-bridge" aria-hidden="true">
            <div class="tm-bridge-pill">
              <el-icon><Right /></el-icon>
            </div>
          </div>

          <section class="tm-pane tm-pane-selected">
            <header class="tm-pane-head">
              <span class="tm-pane-label">已选成员</span>
              <span class="tm-pane-count is-selected">{{ selectedWorkers.length }}</span>
            </header>
            <div class="tm-pane-list">
              <button
                v-for="w in selectedWorkers"
                :key="`sel-${w.id}`"
                type="button"
                class="tm-person tm-person-selected"
                :class="{ 'is-leader': w.id === editingLeaderWorkerId }"
                @click="removeMember(w.id)"
              >
                <span class="tm-avatar is-selected" :style="avatarStyle(w.name)">{{ initialOf(w.name) }}</span>
                <span class="tm-person-meta">
                  <span class="tm-person-name">
                    {{ w.name }}
                    <span v-if="w.id === editingLeaderWorkerId" class="tm-leader-tag">组长</span>
                  </span>
                  <span class="tm-person-sub">{{ w.mobile || '无手机号' }}</span>
                </span>
                <span
                  class="tm-person-action"
                  :class="w.id === editingLeaderWorkerId ? 'is-locked' : 'is-remove'"
                >
                  {{ w.id === editingLeaderWorkerId ? '组长' : '移除' }}
                </span>
              </button>
              <div v-if="!selectedWorkers.length" class="tm-empty">
                {{ memberKeyword.trim() ? '没有匹配的已选成员' : '从左侧点击加入组员' }}
              </div>
            </div>
          </section>
        </div>
      </div>

      <template #footer>
        <div class="tm-footer">
          <span class="tm-footer-hint">共 {{ memberIds.length }} 人将保存到本组</span>
          <div class="tm-footer-actions">
            <el-button @click="memberVisible = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="saveMembers">保存成员</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Right, Search } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('teams-list', tableRef)
const rows = ref<any[]>([])
const workers = ref<any[]>([])
const leaderWorkers = ref<any[]>([])
const workerMap = ref<Record<number, { team_id: number; team_name: string }>>({})
const formVisible = ref(false)
const memberVisible = ref(false)
const memberKeyword = ref('')
const saving = ref(false)
const editingTeamId = ref<number | null>(null)
const editingTeamName = ref('')
const editingLeaderWorkerId = ref<number | null>(null)
const memberIds = ref<number[]>([])

const form = reactive<{
  id: number | null
  name: string
  leader_worker_id: number | null
  department_id: number | null
  production_line_id: number | null
}>({
  id: null,
  name: '',
  leader_worker_id: null,
  department_id: null,
  production_line_id: null,
})

// ── 多产线 / 产线管理 ──
const enableProductionLines = ref(false)
const depts = ref<any[]>([])
const lines = ref<any[]>([])
const lineVisible = ref(false)
const lineForm = reactive<{ id: number | null; name: string; department_id: number | null }>({
  id: null,
  name: '',
  department_id: null,
})

async function loadOrgData() {
  try {
    const [cfg, dRes, lRes]: any[] = await Promise.all([
      http.get('/production-lines/config'),
      http.get('/departments'),
      http.get('/production-lines'),
    ])
    enableProductionLines.value = !!cfg.data?.enable_production_lines
    depts.value = (dRes.data?.items || []).filter((d: any) => d.is_active !== false)
    lines.value = lRes.data?.items || []
  } catch {
    // 组织数据加载失败不影响班组列表
  }
}

async function toggleProductionLines(v: boolean | string | number) {
  await http.put('/production-lines/config', { enable_production_lines: !!v })
  ElMessage.success(v ? '已开启多产线（班组挂产线）' : '已关闭多产线（班组挂部门）')
  await loadOrgData()
}

function openLines() {
  lineForm.id = null
  lineForm.name = ''
  lineForm.department_id = null
  lineVisible.value = true
}

function editLine(row: any) {
  lineForm.id = row.id
  lineForm.name = row.name
  lineForm.department_id = row.department_id ?? null
  lineVisible.value = true
}

async function saveLine() {
  if (!lineForm.name.trim()) {
    ElMessage.warning('请填写产线名称')
    return
  }
  if (lineForm.id) {
    await http.patch(`/production-lines/${lineForm.id}`, {
      name: lineForm.name.trim(),
      department_id: lineForm.department_id ?? null,
    })
  } else {
    await http.post('/production-lines', {
      name: lineForm.name.trim(),
      department_id: lineForm.department_id ?? null,
    })
  }
  ElMessage.success('已保存')
  lineForm.id = null
  lineForm.name = ''
  lineForm.department_id = null
  await loadOrgData()
}

async function deleteLine(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除产线「${row.name}」？`, '删除产线', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await http.delete(`/production-lines/${row.id}`)
  ElMessage.success('已删除')
  await loadOrgData()
}

const AVATAR_COLORS = ['#0076ff', '#0f766e', '#b45309', '#be123c', '#4338ca', '#0369a1']

function initialOf(name?: string) {
  const n = String(name || '').trim()
  return n ? n.slice(0, 1) : '?'
}

function avatarStyle(name?: string) {
  const n = String(name || '')
  let hash = 0
  for (let i = 0; i < n.length; i++) hash = (hash * 31 + n.charCodeAt(i)) >>> 0
  const bg = AVATAR_COLORS[hash % AVATAR_COLORS.length]
  return { background: bg }
}

function matchWorker(w: any, q: string) {
  if (!q) return true
  const name = String(w.name || '').toLowerCase()
  const mobile = String(w.mobile || '').toLowerCase()
  return name.includes(q) || mobile.includes(q)
}

const memberKeywordNorm = computed(() => memberKeyword.value.trim().toLowerCase())

const selectedWorkers = computed(() => {
  const idSet = new Set(memberIds.value)
  const q = memberKeywordNorm.value
  return workers.value.filter((w: any) => idSet.has(w.id) && matchWorker(w, q))
})

const availableWorkers = computed(() => {
  const idSet = new Set(memberIds.value)
  const q = memberKeywordNorm.value
  return workers.value.filter(
    (w: any) => !idSet.has(w.id) && !isLockedToOther(w.id) && matchWorker(w, q),
  )
})

const lockedWorkers = computed(() => {
  const q = memberKeywordNorm.value
  return workers.value.filter((w: any) => isLockedToOther(w.id) && matchWorker(w, q))
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

function addMember(id: number) {
  if (memberIds.value.includes(id)) return
  memberIds.value = [...memberIds.value, id]
}

function removeMember(id: number) {
  if (editingLeaderWorkerId.value && id === editingLeaderWorkerId.value) {
    ElMessage.warning('组长不能移出班组')
    return
  }
  memberIds.value = memberIds.value.filter((x) => x !== id)
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
  leaderWorkers.value = u.data.items || []
  workerMap.value = m.data.map || {}
  await loadOrgData().catch(() => {})
}

function openCreate() {
  form.id = null
  form.name = ''
  form.leader_worker_id = leaderWorkers.value[0]?.id || null
  form.department_id = null
  form.production_line_id = null
  formVisible.value = true
}

function openEdit(row: any) {
  form.id = row.id
  form.name = row.name
  form.leader_worker_id = row.leader_worker_id
  form.department_id = row.department_id ?? null
  form.production_line_id = row.production_line_id ?? null
  formVisible.value = true
}

async function saveForm() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写班组名称')
    return
  }
  if (!form.leader_worker_id) {
    ElMessage.warning('请选择组长')
    return
  }
  saving.value = true
  try {
    const orgPayload = enableProductionLines.value
      ? { production_line_id: form.production_line_id ?? null }
      : { department_id: form.department_id ?? null }
    if (form.id) {
      await http.patch(`/teams/${form.id}`, {
        name: form.name.trim(),
        leader_worker_id: form.leader_worker_id,
        ...orgPayload,
      })
    } else {
      await http.post('/teams', {
        name: form.name.trim(),
        leader_worker_id: form.leader_worker_id,
        worker_ids: [],
        ...orgPayload,
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
  editingTeamName.value = row.name || ''
  editingLeaderWorkerId.value = row.leader_worker_id || null
  memberIds.value = (row.members || []).map((m: any) => m.id)
  memberKeyword.value = ''
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

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-right: 28px;
  width: 100%;
}
.tm-title {
  font-size: 17px;
  font-weight: 700;
  color: #111827;
  line-height: 1.3;
}
.tm-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
.tm-team-name {
  color: #0076ff;
  font-weight: 600;
}
.tm-dot {
  margin: 0 4px;
  opacity: 0.5;
}
.tm-stat {
  flex-shrink: 0;
  min-width: 64px;
  padding: 8px 12px;
  border-radius: 12px;
  background: linear-gradient(180deg, #e8f3ff 0%, #f0f7ff 100%);
  border: 1px solid #cce4ff;
  text-align: center;
}
.tm-stat strong {
  display: block;
  font-size: 20px;
  font-weight: 750;
  color: #0076ff;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.tm-stat span {
  font-size: 11px;
  color: #64748b;
}

.tm-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tm-search :deep(.el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #d0d7e2 inset;
  padding-left: 12px;
}
.tm-search :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #0076ff inset, 0 0 0 3px rgba(0, 118, 255, 0.12);
}
.tm-search-icon {
  color: #94a3b8;
}

.tm-transfer {
  display: grid;
  grid-template-columns: 1fr 36px 1fr;
  gap: 0;
  align-items: stretch;
  min-height: 360px;
}
.tm-pane {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #d0d7e2;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}
.tm-pane-selected {
  background: #f8fbff;
  border-color: #b3d4ff;
}
.tm-pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  background: #f7f9fc;
  border-bottom: 1px solid #e5eaf1;
}
.tm-pane-selected .tm-pane-head {
  background: #eef6ff;
  border-bottom-color: #d6e8ff;
}
.tm-pane-label {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}
.tm-pane-count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: #e8edf4;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-variant-numeric: tabular-nums;
}
.tm-pane-count.is-selected {
  background: #0076ff;
  color: #fff;
}
.tm-pane-list {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  max-height: 380px;
}

.tm-bridge {
  display: flex;
  align-items: center;
  justify-content: center;
}
.tm-bridge-pill {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  background: #fff;
  border: 1px solid #d0d7e2;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tm-person {
  appearance: none;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  background: transparent;
  border-radius: 0;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  cursor: pointer;
  width: 100%;
  transition: background 0.12s ease;
}
.tm-person:last-child {
  border-bottom: 0;
}
.tm-person:hover {
  background: #f0f7ff;
}
.tm-person:hover .tm-person-action {
  opacity: 1;
}
.tm-person-selected:hover {
  background: #fff1f2;
}
.tm-person-selected:hover .tm-person-action.is-remove {
  color: #dc2626;
}
.tm-person-locked {
  cursor: default;
  opacity: 0.65;
  background: transparent;
}
.tm-person-locked:hover {
  background: transparent;
}
.tm-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.tm-avatar.is-selected {
  box-shadow: 0 0 0 2px #e8f3ff;
}
.tm-avatar-muted {
  background: #94a3b8 !important;
}
.tm-person-meta {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.tm-person-name {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  line-height: 1.3;
  flex-shrink: 0;
}
.tm-person-sub {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tm-person-action {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #0076ff;
  opacity: 0;
  transition: opacity 0.12s ease;
}
.tm-person-action.is-remove {
  opacity: 0.7;
  color: #64748b;
}
.tm-person-action.is-locked {
  opacity: 1;
  color: #0076ff;
}
.tm-leader-tag {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 600;
  color: #0076ff;
  background: #e8f3ff;
  border-radius: 4px;
  padding: 1px 5px;
}
.tm-person.is-leader {
  cursor: default;
}
.tm-locked-label {
  margin: 6px 12px 2px;
  padding-top: 8px;
  border-top: 1px dashed #e5eaf1;
  font-size: 11px;
  font-weight: 650;
  color: #94a3b8;
}
.tm-empty {
  margin: auto;
  padding: 28px 12px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
}

.tm-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.tm-footer-hint {
  font-size: 12px;
  color: #94a3b8;
}
.tm-footer-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 720px) {
  .tm-transfer {
    grid-template-columns: 1fr;
    min-height: 0;
  }
  .tm-bridge {
    display: none;
  }
  .tm-pane-list {
    max-height: 240px;
  }
}
</style>

<style>
.team-members-dialog.el-dialog {
  border-radius: 16px;
  overflow: hidden;
}
.team-members-dialog .el-dialog__header {
  margin-right: 0;
  padding: 18px 20px 12px;
  border-bottom: 1px solid #eef2f7;
}
.team-members-dialog .el-dialog__body {
  padding: 16px 20px 8px;
}
.team-members-dialog .el-dialog__footer {
  padding: 12px 20px 18px;
  border-top: 1px solid #eef2f7;
}
</style>
