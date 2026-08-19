<template>
  <div class="org-page" v-loading="loading">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">组织架构</h1>
        <p class="page-desc">部门 + {{ teamLabelText }}统一一棵树；{{ teamLabelText }}只能建在挂了工序段的部门下（D8）</p>
      </div>
    </header>

    <div class="org-layout">
      <!-- 左：树 -->
      <aside class="org-tree-panel">
        <div class="org-tree-header">
          <span class="org-tree-title">组织</span>
          <el-button link type="primary" size="small" @click="openDept()">＋ 新增部门</el-button>
        </div>
        <div class="org-tree-body">
          <el-tree
            :data="treeData"
            node-key="id"
            :props="{ label: 'label', children: 'children' }"
            default-expand-all
            highlight-current
            :current-node-key="selectedKey"
            @node-click="onNodeClick"
          >
            <template #default="{ data }">
              <div class="org-node">
                <span class="org-node__label">
                  {{ data.label }}
                  <el-tag v-if="data.kind === 'dept' && data.segment_name" size="small" type="info">{{ data.segment_name }}</el-tag>
                  <el-tag v-if="data.is_default" size="small" type="warning">默认</el-tag>
                  <span v-if="data.kind === 'dept' && data.employee_count" class="org-node__count">{{ data.employee_count }}人</span>
                  <span v-if="data.kind === 'team' && data.leader_name" class="org-node__leader">组长：{{ data.leader_name }}</span>
                </span>
                <span class="org-node__ops" @click.stop>
                  <el-button
                    v-if="data.kind === 'dept' && data.segment_id && orgEnableTeams"
                    link
                    size="small"
                    :title="'新建' + teamLabelText"
                    @click="openTeam(data)"
                  >
                    ＋ {{ teamLabelText }}
                  </el-button>
                  <el-button v-if="data.kind === 'dept'" link size="small" title="新增子部门" @click="openDept(data.dept_id)">
                    ＋子
                  </el-button>
                  <el-button v-if="data.kind === 'dept'" link size="small" @click="openDeptEdit(data)">编辑</el-button>
                  <el-button v-if="data.kind === 'team'" link type="primary" size="small" @click="editTeam(data)">编辑</el-button>
                  <el-button v-if="data.kind === 'team'" link size="small" @click="manageMembers(data)">组员</el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </div>
      </aside>

      <!-- 右：详情 -->
      <section class="org-detail-panel">
        <template v-if="selected">
          <div class="org-detail-head">
            <h3>{{ selected.label }}</h3>
            <el-tag v-if="selected.kind === 'dept' && selected.segment_name" type="info">{{ selected.segment_name }}</el-tag>
            <el-tag v-else-if="selected.kind === 'team' && selected.is_default" type="warning">默认组</el-tag>
          </div>
          <div class="org-detail-grid" v-if="selected.kind === 'dept'">
            <div class="org-detail-item"><span class="muted">负责人</span><b>{{ selected.leader_name || '—' }}</b></div>
            <div class="org-detail-item"><span class="muted">主管</span><b>{{ selected.manager_name || '—' }}</b></div>
            <div class="org-detail-item"><span class="muted">工序段</span><b>{{ selected.segment_name || '未挂段' }}</b></div>
            <div class="org-detail-item"><span class="muted">人数</span><b>{{ selected.employee_count || 0 }}</b></div>
          </div>
          <div class="org-detail-grid" v-else>
            <div class="org-detail-item"><span class="muted">组长</span><b>{{ selected.leader_name || '—' }}</b></div>
            <div class="org-detail-item"><span class="muted">工序段</span><b>{{ selected.segment_name || '—' }}</b></div>
            <div class="org-detail-item"><span class="muted">人数</span><b>{{ (selected.members || []).length }}</b></div>
            <div class="org-detail-item"><span class="muted">默认组</span><b>{{ selected.is_default ? '是' : '否' }}</b></div>
          </div>
          <div v-if="selected.kind === 'team' && selected.members?.length" class="org-member-list">
            <div class="section-label">组员</div>
            <el-tag v-for="m in selected.members" :key="m.id" size="small" style="margin: 2px 4px 2px 0">
              {{ m.name }}
            </el-tag>
          </div>
        </template>
        <div v-else class="muted" style="padding: 40px; text-align: center">选中左侧节点查看详情</div>
      </section>
    </div>

    <!-- 新增/编辑部门 -->
    <el-dialog v-model="deptVisible" :title="deptForm.id ? '编辑部门' : '新增部门'" width="440px">
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="deptForm.name" /></el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="deptForm.parent_id" clearable filterable placeholder="留空=顶级" style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属工序段">
          <el-select v-model="deptForm.process_segment_id" clearable filterable placeholder="未挂段" style="width: 100%">
            <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="deptForm.leader_id" clearable filterable placeholder="可选" style="width: 100%">
            <el-option v-for="e in leaderCandidates" :key="e.id" :label="`${e.name}${e.mobile ? '（' + e.mobile + '）' : ''}`" :value="e.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDept">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑班组 -->
    <el-dialog v-model="teamVisible" :title="teamForm.id ? '编辑' + teamLabelText : '新建' + teamLabelText" width="420px">
      <el-form label-width="90px">
        <el-form-item :label="teamLabelText + '名称'" required><el-input v-model="teamForm.name" /></el-form-item>
        <el-form-item label="组长">
          <el-select v-model="teamForm.leader_worker_id" clearable filterable placeholder="可空" style="width: 100%">
            <el-option v-for="e in leaderCandidates" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门">
          <el-input :model-value="teamDeptName" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="teamVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTeam">保存</el-button>
      </template>
    </el-dialog>

    <!-- 组员管理 -->
    <el-dialog v-model="membersVisible" :title="`组员管理：${editingTeamName}`" width="460px">
      <el-transfer
        v-model="memberIds"
        :data="workerOptions"
        :titles="['全部工人', '组员']"
        filterable
      />
      <template #footer>
        <el-button @click="membersVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMembers">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { fetchOrgSettings } from '@/composables/useOrgSettings'

const loading = ref(false)
const departments = ref<any[]>([])
const teams = ref<any[]>([])
const segments = ref<any[]>([])
const leaderCandidates = ref<any[]>([])
const workerOptions = ref<any[]>([])
const orgEnableTeams = ref(false)
const teamLabelText = ref('班组')

const treeData = computed(() => {
  const teamsByDept = new Map<number, any[]>()
  for (const t of teams.value) {
    if (t.department_id != null) {
      teamsByDept.set(Number(t.department_id), [...(teamsByDept.get(Number(t.department_id)) || []), t])
    }
  }
  const depts = departments.value
    .filter((d) => d.parent_id == null)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  const build = (deps: any[]): any[] =>
    deps.map((d) => {
      const node: any = {
        id: `dept-${d.id}`,
        kind: 'dept',
        label: d.name,
        raw: d,
        dept_id: d.id,
        segment_id: d.process_segment_id,
        segment_name: d.segment_name,
        leader_name: d.leader_name,
        manager_name: d.manager_name,
        employee_count: d.employee_count,
        children: [] as any[],
      }
      const kids = departments.value
        .filter((x) => x.parent_id === d.id)
        .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
      node.children = build(kids)
      if (orgEnableTeams.value) {
        const ts = (teamsByDept.get(Number(d.id)) || []).map((t) => ({
          id: `team-${t.id}`,
          kind: 'team',
          label: t.name,
          raw: t,
          team_id: t.id,
          segment_id: t.segment_id,
          segment_name: t.segment_name,
          leader_name: t.leader_name,
          is_default: !!t.is_default,
          members: t.members || [],
          department_id: t.department_id,
        }))
        node.children = [...node.children, ...ts]
      }
      return node
    })
  return build(depts)
})

const selectedKey = ref<string | null>(null)
const selected = ref<any>(null)
function onNodeClick(data: any) {
  selectedKey.value = data.id
  selected.value = data
}

const deptVisible = ref(false)
const deptForm = reactive<any>({
  id: null,
  name: '',
  parent_id: null,
  process_segment_id: null,
  leader_id: null,
})
function openDept(parentId: number | null = null) {
  Object.assign(deptForm, { id: null, name: '', parent_id: parentId, process_segment_id: null, leader_id: null })
  deptVisible.value = true
}
function openDeptEdit(data: any) {
  Object.assign(deptForm, {
    id: data.dept_id,
    name: data.raw.name,
    parent_id: data.raw.parent_id,
    process_segment_id: data.segment_id ?? null,
    leader_id: data.raw.leader_id ?? null,
  })
  deptVisible.value = true
}
async function saveDept() {
  if (!String(deptForm.name || '').trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const payload = {
    name: deptForm.name.trim(),
    parent_id: deptForm.parent_id,
    process_segment_id: deptForm.process_segment_id,
    leader_id: deptForm.leader_id,
  }
  if (deptForm.id) await http.patch(`/departments/${deptForm.id}`, payload)
  else await http.post('/departments', payload)
  ElMessage.success('已保存')
  deptVisible.value = false
  await load()
}

const teamVisible = ref(false)
const teamForm = reactive<any>({ id: null, name: '', leader_worker_id: null, department_id: null })
const teamDeptName = ref('')
function openTeam(deptNode: any) {
  Object.assign(teamForm, { id: null, name: '', leader_worker_id: null, department_id: deptNode.dept_id })
  teamDeptName.value = deptNode.label
  teamVisible.value = true
}
function editTeam(data: any) {
  Object.assign(teamForm, {
    id: data.team_id,
    name: data.raw.name,
    leader_worker_id: data.raw.leader_worker_id ?? null,
    department_id: data.department_id,
  })
  teamDeptName.value = departments.value.find((d) => d.id === data.department_id)?.name || ''
  teamVisible.value = true
}
async function saveTeam() {
  if (!String(teamForm.name || '').trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  const payload = {
    name: teamForm.name.trim(),
    leader_worker_id: teamForm.leader_worker_id,
    department_id: teamForm.department_id,
  }
  if (teamForm.id) await http.patch(`/teams/${teamForm.id}`, payload)
  else await http.post('/teams', payload)
  ElMessage.success('已保存')
  teamVisible.value = false
  await load()
}

const membersVisible = ref(false)
const memberIds = ref<number[]>([])
const editingTeamId = ref<number | null>(null)
const editingTeamName = ref('')
function manageMembers(data: any) {
  editingTeamId.value = data.team_id
  editingTeamName.value = data.label
  memberIds.value = (data.members || []).map((m: any) => Number(m.id))
  membersVisible.value = true
}
async function saveMembers() {
  if (editingTeamId.value == null) return
  await http.put(`/teams/${editingTeamId.value}/members`, { worker_ids: memberIds.value })
  ElMessage.success('已保存')
  membersVisible.value = false
  await load()
}

async function load() {
  loading.value = true
  try {
    const orgSettings = await fetchOrgSettings()
    orgEnableTeams.value = orgSettings.enable_teams
    teamLabelText.value = orgSettings.team_label
    const [depRes, teamRes, segRes, leaderRes, workerRes]: any[] = await Promise.all([
      http.get('/departments'),
      http.get('/teams', { params: { include_inactive: true } }),
      http.get('/process-segments'),
      http.get('/teams/leader-candidates'),
      http.get('/teams/worker-map'),
    ])
    departments.value = depRes.data?.items || []
    teams.value = teamRes.data?.items || []
    segments.value = segRes.data?.items || []
    leaderCandidates.value = leaderRes.data?.items || leaderRes.data || []
    workerOptions.value = Object.entries(workerRes.data?.map || {}).map(([id, name]: any) => ({
      key: Number(id),
      label: name,
    }))
    selected.value = null
    selectedKey.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.org-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.org-tree-panel {
  width: 380px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.org-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.org-tree-title {
  font-weight: 600;
  font-size: 13px;
}
.org-tree-body {
  max-height: 640px;
  overflow: auto;
  padding: 6px;
}
.org-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}
.org-node__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.org-node__count,
.org-node__leader {
  font-size: 12px;
  color: #94a3b8;
}
.org-node__ops {
  display: inline-flex;
  gap: 2px;
  visibility: hidden;
}
.org-node:hover .org-node__ops {
  visibility: visible;
}
.org-detail-panel {
  flex: 1;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
  min-height: 300px;
  padding: 16px;
}
.org-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.org-detail-head h3 {
  margin: 0;
}
.org-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}
.org-detail-item span {
  display: block;
  font-size: 12px;
}
.org-detail-item b {
  font-size: 14px;
}
.org-member-list {
  margin-top: 16px;
}
.section-label {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
</style>
