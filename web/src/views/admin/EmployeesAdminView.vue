<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">员工与组织</h1>
        <p class="page-desc">左侧部门树；选中部门后，右侧可切换员工与{{ teamLabelText }}</p>
      </div>
    </header>

    <div class="admin-card emp-shell">
      <!-- 左：部门树；生产单位挂在当前选中部门下 -->
      <aside class="emp-tree-panel">
        <div class="emp-tab-fill">
          <div class="emp-tree-header">
            <span class="emp-tree-title">部门</span>
            <el-button link type="primary" size="small" @click="openDeptCreate()">＋ 新增部门</el-button>
          </div>
          <div class="emp-tree-search">
            <el-input
              v-model="deptKeyword"
              size="small"
              clearable
              placeholder="搜索部门..."
              :prefix-icon="Search"
            />
          </div>
          <div class="emp-tree-body">
            <el-tree
              :key="`${deptTreeKey}-${deptKeyword}`"
              ref="deptTreeRef"
              :data="filteredDeptTree"
              node-key="id"
              :props="{ label: 'name', children: 'children' }"
              highlight-current
              :expand-on-click-node="false"
              default-expand-all
              :current-node-key="selectedKey"
              @node-click="onDeptClick"
            >
              <template #default="{ data, node }">
                <div class="emp-tree-node">
                  <el-icon class="emp-tree-node__icon" :class="{ 'is-open': node.expanded }">
                    <component :is="node.expanded ? FolderOpened : Folder" />
                  </el-icon>
                  <span class="emp-tree-node__label">{{ data.name }}</span>
                  <el-tag v-if="data.segment_name" size="small" type="info" class="emp-tree-node__tag">{{ data.segment_name }}</el-tag>
                  <span v-if="data.employee_count" class="emp-tree-node__badge">{{ data.employee_count }}</span>
                  <span class="emp-tree-node__ops" @click.stop>
                    <el-button v-if="data.kind === 'dept'" link size="small" title="新增子部门" @click="openDeptCreate(data.dept_id)">＋子</el-button>
                    <el-button v-if="data.kind === 'dept'" link size="small" @click="openDeptEdit(data)">编辑</el-button>
                    <el-button v-if="data.kind === 'dept'" link type="danger" size="small" @click="deleteDept(data)">删除</el-button>
                  </span>
                </div>
              </template>
            </el-tree>
          </div>
        </div>
      </aside>

      <!-- 右：当前部门的生产单位（横条，不占左侧树高）+ 员工 / 详情 -->
      <section class="emp-list-panel">
        <div v-if="orgEnableTeams && typeof selectedDeptId === 'number'" class="emp-team-strip">
          <button
            type="button"
            class="emp-team-chip"
            :class="{ 'is-current': !selectedTeamId }"
            @click="clearTeamSelection"
          >员工</button>
          <template v-if="selectedDeptHasSegment">
            <button
              v-for="t in scopedTeams"
              :key="t.id"
              type="button"
              class="emp-team-chip"
              :class="{ 'is-current': selectedTeamId === t.id }"
              @click="onTeamClick(t)"
            >
              {{ t.name }}
              <span v-if="t.is_default" class="emp-team-chip__mark">默</span>
            </button>
            <el-tooltip :disabled="canCreateTeam" :content="teamCreateHint" placement="top">
              <span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="!canCreateTeam"
                  @click="openTeam()"
                >＋ {{ teamLabelText }}</el-button>
              </span>
            </el-tooltip>
          </template>
          <span v-else class="muted emp-team-strip__hint">未挂工序段，不能建{{ teamLabelText }}</span>
        </div>

        <!-- 班组详情 -->
        <div v-if="showTeamDetail" class="team-detail">
          <div class="team-detail-head">
            <h3>{{ selectedTeam.name }}</h3>
            <el-tag v-if="selectedTeam.is_default" type="warning">默认{{ teamLabelText }}</el-tag>
            <el-tag v-if="selectedTeam.segment_name" type="info">{{ selectedTeam.segment_name }}</el-tag>
          </div>
          <div class="team-detail-grid">
            <div class="team-detail-item"><span class="muted">{{ leaderLabelText }}</span><b>{{ selectedTeam.leader_name || '—' }}</b></div>
            <div class="team-detail-item"><span class="muted">所属部门</span><b>{{ selectedTeam.department_name || '—' }}</b></div>
            <div class="team-detail-item"><span class="muted">人数</span><b>{{ (selectedTeam.members || []).length }}</b></div>
            <div class="team-detail-item"><span class="muted">默认{{ teamLabelText }}</span><b>{{ selectedTeam.is_default ? '是' : '否' }}</b></div>
          </div>
          <div class="team-member-list">
            <div class="section-label">成员</div>
            <el-tag v-for="m in selectedTeam.members" :key="m.id" size="small" style="margin: 2px 4px 2px 0">
              {{ m.name }}
            </el-tag>
            <div v-if="!selectedTeam.members?.length" class="muted" style="font-size: 12px">暂无成员</div>
          </div>
          <div style="margin-top: 16px">
            <el-button type="primary" size="small" @click="manageMembers(selectedTeam)">成员管理</el-button>
            <el-button size="small" @click="editTeam(selectedTeam)">编辑{{ teamLabelText }}</el-button>
          </div>
        </div>
        <!-- 员工列表 -->
        <template v-else>
          <div class="admin-toolbar">
            <el-input
              v-model="filters.keyword"
              clearable
              placeholder="姓名 / 手机"
              style="width: 150px"
              @clear="search"
              @keyup.enter="search"
            />
            <el-select v-model="filters.position_id" clearable filterable placeholder="全部工种" style="width: 120px" @change="search">
              <el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select v-model="filters.has_account" clearable placeholder="账号" style="width: 95px" @change="search">
              <el-option label="有账号" :value="true" />
              <el-option label="无账号" :value="false" />
            </el-select>
            <el-select v-model="filters.is_active" clearable placeholder="状态" style="width: 95px" @change="search">
              <el-option label="在职" :value="true" />
              <el-option label="停用" :value="false" />
            </el-select>
            <div class="spacer" />
            <el-button @click="search">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
            <el-button type="primary" @click="openCreate">新增员工</el-button>
          </div>
          <div v-if="selectedDeptName" class="emp-scope-tip">
            当前范围：{{ selectedDeptName }}<template v-if="deptScopeInfo"><span class="muted"> · {{ deptScopeInfo }}</span></template>
          </div>

          <div ref="tableHostRef">
            <el-table
              ref="tableRef"
              :data="rows"
              stripe
              border
              :max-height="tableMaxHeight"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column prop="id" label="ID" :width="colWidth('id', 64)" resizable />
              <el-table-column prop="name" label="姓名" :width="colWidth('name', 90)" resizable />
              <el-table-column prop="mobile" label="手机" :width="colWidth('mobile', 120)" resizable />
              <el-table-column column-key="dept" label="部门" :width="colWidth('dept', 110)" resizable>
                <template #default="{ row }">{{ row.department_name || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="pos" label="工种" :width="colWidth('pos', 90)" resizable>
                <template #default="{ row }">{{ row.position_name || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="roles" label="后台角色" :min-width="flexColMinWidth('roles', 140)" resizable>
                <template #default="{ row }">
                  <template v-if="row.roles?.length">
                    <el-tag v-for="r in row.role_names" :key="r" size="small" style="margin-right: 4px">{{ r }}</el-tag>
                  </template>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column column-key="account" label="账号" :width="colWidth('account', 110)" resizable>
                <template #default="{ row }">
                  <span v-if="row.has_account">{{ row.username || row.mobile }}</span>
                  <span v-else class="muted">无账号</span>
                </template>
              </el-table-column>
              <el-table-column column-key="status" label="状态" :width="colWidth('status', 80)" resizable>
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                    {{ row.is_active ? '在职' : '停用' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 200)" :resizable="false">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                  <el-button v-if="row.has_account" link @click="resetPwd(row)">重置密码</el-button>
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
        </template>
      </section>
    </div>

    <!-- 员工新增/编辑 -->
    <el-dialog v-model="visible" :title="form.id ? '编辑员工' : '新增员工'" width="560px">
      <el-form label-width="90px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="姓名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="手机">
          <el-input v-model="form.mobile" placeholder="可选" @input="onMobileInput" />
        </el-form-item>
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" placeholder="登录账号，默认同手机号" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select
            v-model="form.department_id"
            clearable
            filterable
            placeholder="请选择"
            style="width: 100%"
            @change="onDeptSelectChange"
          >
            <el-option v-for="d in deptOptions" :key="d.id" :label="d.name" :value="d.id" />
            <el-option :value="__NEW_DEPT__" label="＋ 新建部门…" />
          </el-select>
        </el-form-item>
        <el-form-item label="工种">
          <el-select v-model="form.position_id" clearable placeholder="请选择" style="width: 100%">
            <el-option v-for="p in positionOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">计薪</el-divider>
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
        <el-form-item label="技能系数">
          <el-input-number v-model="form.skill_factor" :min="0.01" :max="9.99" :step="0.1" :precision="2" />
          <span class="muted" style="margin-left: 8px">组报工拆分预填权重</span>
        </el-form-item>
        <el-form-item label="收款户名"><el-input v-model="form.bank_account_name" placeholder="默认与姓名相同" /></el-form-item>
        <el-form-item label="银行卡号"><el-input v-model="form.bank_account" placeholder="银行代发用" /></el-form-item>
        <el-form-item label="开户行"><el-input v-model="form.bank_name" placeholder="如 工行XX支行" /></el-form-item>

        <el-divider content-position="left">后台权限</el-divider>
        <p class="muted" style="margin: 0 0 10px; font-size: 12px; line-height: 1.6">
          密码可不填（默认 123456，首次登录须修改）；只需选择权限角色。
        </p>
        <el-form-item label="权限角色">
          <el-select
            v-model="form.roles"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            :disabled="!isAdmin"
            placeholder="可多选，权限取并集；不选 = 纯生产员工"
            style="width: 100%"
          >
            <el-option v-for="r in roleOptions" :key="r.code" :label="r.name" :value="r.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 快捷新建部门（员工表单里顺手建，建完自动选中） -->
    <el-dialog v-model="quickDeptVisible" title="＋ 新建部门" width="380px">
      <el-form label-width="80px">
        <el-form-item label="名称" required><el-input v-model="quickDeptForm.name" placeholder="如：针车二部" /></el-form-item>
        <el-form-item label="工序段">
          <el-select v-model="quickDeptForm.process_segment_id" clearable filterable placeholder="未挂段" style="width: 100%">
            <el-option v-for="seg in quickDeptSegments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="quickDeptVisible = false">取消</el-button>
        <el-button type="primary" @click="saveQuickDept">保存并选中</el-button>
      </template>
    </el-dialog>

    <!-- 部门新增/编辑 -->
    <el-dialog v-model="deptVisible" :title="deptForm.id ? '编辑部门' : '新增部门'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="部门名称" required><el-input v-model="deptForm.name" /></el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="deptForm.parent_id" clearable filterable placeholder="留空=顶级部门" style="width: 100%">
            <el-option
              v-for="d in deptParentOptions"
              :key="d.id"
              :label="d.name"
              :value="d.id"
              :disabled="d.id === deptForm.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="工序段">
          <el-select v-model="deptForm.process_segment_id" clearable filterable placeholder="未挂段" style="width: 100%">
            <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select
            v-model="deptForm.leader_id"
            clearable
            filterable
            placeholder="选一名员工（可跨部门）；无班组时即组长，派工「派给负责人」用此"
            style="width: 100%"
          >
            <el-option v-for="e in employeeOptions" :key="e.id" :label="e.mobile ? `${e.name}（${e.mobile}）` : e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="deptForm.sort_order" :min="0" /></el-form-item>
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
        <el-form-item :label="leaderLabelText">
          <el-select v-model="teamForm.leader_worker_id" clearable filterable placeholder="可空" style="width: 100%">
            <el-option v-for="e in employeeOptions" :key="e.id" :label="e.mobile ? `${e.name}（${e.mobile}）` : e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门" required>
          <el-select v-model="teamForm.department_id" clearable filterable placeholder="仅挂工序段的部门可建" style="width: 100%">
            <el-option v-for="d in segmentDeptOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="teamVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTeam">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理 -->
    <el-dialog v-model="membersVisible" :title="`成员管理：${editingTeamName}`" width="460px">
      <el-transfer
        v-model="memberIds"
        :data="workerOptions"
        :titles="['全部工人', '成员']"
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
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderOpened, HomeFilled, Search } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { fetchOrgSettings } from '@/composables/useOrgSettings'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin())
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend, relayoutTable } = useTableColWidths('employees-list', tableRef, {
  flexKey: 'roles',
  flexDefaultMin: 140,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

// ── 左右分栏：部门树 + 当前部门下的生产单位 ──
const orgEnableTeams = ref(false)
const teamLabelText = ref('班组')
const leaderLabelText = computed(() => {
  if (teamLabelText.value === '产线') return '线长'
  if (teamLabelText.value === '班') return '班长'
  return '组长'
})

const showTeamDetail = computed(() => !!selectedTeam.value)

// ── 部门树（纯部门，不混班组） ──
interface OrgNode {
  id: string
  kind: 'root' | 'dept'
  name: string
  dept_id?: number
  parent_id: number | null
  manager_name?: string
  leader_name?: string
  segment_id?: number | null
  segment_name?: string
  employee_count: number
  is_active: boolean
  raw?: any
  children?: OrgNode[]
}

const depts = ref<any[]>([])
const segments = ref<any[]>([])
const deptTreeRef = ref()
const treeData = ref<OrgNode[]>([])
const deptTreeKey = ref(0)
const selectedKey = ref<string | null>(null)
const selectedDeptId = ref<number | null | 'all'>(null)
const selectedDeptName = ref(auth.tenantName || '全部员工')
const deptKeyword = ref('')

function buildDeptTree(list: any[]): OrgNode[] {
  const root: OrgNode = {
    id: 'all',
    kind: 'root',
    name: auth.tenantName || '全部员工',
    parent_id: null,
    employee_count: list.reduce((n, d) => n + (d.employee_count || 0), 0),
    is_active: true,
    children: [],
  }
  const byId = new Map<number, OrgNode>()
  for (const d of list) {
    byId.set(d.id, {
      id: `dept-${d.id}`,
      kind: 'dept',
      name: d.name,
      dept_id: d.id,
      parent_id: d.parent_id,
      manager_name: d.manager_name,
      leader_name: d.leader_name,
      segment_id: d.process_segment_id,
      segment_name: d.segment_name,
      employee_count: d.employee_count || 0,
      is_active: d.is_active,
      raw: d,
      children: [],
    })
  }
  const roots: OrgNode[] = []
  for (const node of byId.values()) {
    if (node.parent_id != null && byId.has(node.parent_id)) {
      byId.get(node.parent_id)!.children!.push(node)
    } else {
      roots.push(node)
    }
  }
  root.children = roots
  return [root]
}

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    if (n.children?.length) {
      const hit = findNode(n.children, id)
      if (hit) return hit
    }
  }
  return null
}

/** 搜索过滤：命中部门或命中其子孙时保留该分支（根节点始终保留）。 */
const filteredDeptTree = computed<OrgNode[]>(() => {
  const kw = deptKeyword.value.trim()
  if (!kw) return treeData.value
  const filter = (nodes: OrgNode[]): OrgNode[] =>
    nodes
      .map((n) => {
        const children = n.children?.length ? filter(n.children) : []
        if (n.name.includes(kw) || children.length) return { ...n, children }
        return null
      })
      .filter((n): n is OrgNode => n !== null)
  return filter(treeData.value)
})

function rebuildTree() {
  treeData.value = buildDeptTree(depts.value)
  deptTreeKey.value += 1
  // 树重建后同步选中态：节点消失则回落根
  if (selectedKey.value) {
    const node = findNode(treeData.value, selectedKey.value)
    if (!node) {
      selectedKey.value = null
      selectedDeptId.value = null
      selectedDeptName.value = auth.tenantName || '全部员工'
    } else {
      selectedDeptName.value = node.name
    }
  }
}

async function loadDepts() {
  const res: any = await http.get('/departments')
  depts.value = res.data?.items || []
  rebuildTree()
}

async function loadSegments() {
  const segRes: any = await http.get('/process-segments')
  segments.value = segRes.data?.items || []
}

function onDeptClick(data: OrgNode) {
  selectedKey.value = data.id
  selectedDeptId.value = data.kind === 'root' ? 'all' : (data.dept_id ?? null)
  selectedDeptName.value = data.name
  selectedTeam.value = null
  selectedTeamId.value = null
  page.value = 1
  void load()
}

/** 选中真实部门时，右侧提示附加人数/负责人/工序段。 */
const deptScopeInfo = computed(() => {
  if (selectedDeptId.value == null || selectedDeptId.value === 'all') return ''
  const raw = depts.value.find((d) => d.id === selectedDeptId.value)
  if (!raw) return ''
  const bits: string[] = []
  if (raw.employee_count) bits.push(`${raw.employee_count}人`)
  if (raw.leader_name) bits.push(`负责人：${raw.leader_name}`)
  if (raw.segment_name) bits.push(raw.segment_name)
  return bits.join(' · ')
})

// 部门下拉选项（含子部门平铺，缩进提示；不含根节点）
const deptOptions = computed(() => {
  const flat: any[] = []
  const walk = (nodes: OrgNode[], depth: number) => {
    for (const n of nodes) {
      if (n.kind === 'dept') flat.push({ id: n.dept_id, name: `${'　'.repeat(depth)}${n.name}` })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(treeData.value, 0)
  return flat
})

// 员工下拉（部门负责人 / 组长选择）
const employeeOptions = ref<any[]>([])
async function loadEmployeeOptions() {
  try {
    const res: any = await http.get('/employees', { params: { page_size: 500, is_active: true } })
    employeeOptions.value = res.data?.items || []
  } catch {
    employeeOptions.value = []
  }
}

// ── 部门 CRUD ──
const deptVisible = ref(false)
const deptForm = reactive<any>({
  id: null,
  name: '',
  parent_id: null,
  process_segment_id: null,
  leader_id: null,
  sort_order: 0,
})

function openDeptCreate(parentId?: number | null) {
  // 兜底默认上级：仅当当前选中部门仍真实存在时才沿用，避免下拉显示无匹配的原始 id
  const fallback =
    selectedDeptId.value !== 'all' && depts.value.some((d) => d.id === selectedDeptId.value)
      ? selectedDeptId.value
      : null
  Object.assign(deptForm, {
    id: null,
    name: '',
    parent_id: parentId ?? fallback,
    process_segment_id: null,
    leader_id: null,
    sort_order: 0,
  })
  deptVisible.value = true
}

function openDeptEdit(data: OrgNode) {
  const raw = depts.value.find((d) => d.id === data.dept_id)
  Object.assign(deptForm, {
    id: data.dept_id,
    name: data.name,
    parent_id: data.parent_id ?? null,
    process_segment_id: data.segment_id ?? null,
    leader_id: raw?.leader_id ?? null,
    sort_order: raw?.sort_order ?? 0,
  })
  deptVisible.value = true
}

const deptParentOptions = computed(() => deptOptions.value.filter((d) => d.id !== deptForm.id))

async function saveDept() {
  if (!String(deptForm.name || '').trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const payload = {
    name: deptForm.name.trim(),
    parent_id: deptForm.parent_id ?? null,
    process_segment_id: deptForm.process_segment_id ?? null,
    leader_id: deptForm.leader_id ?? null,
    sort_order: deptForm.sort_order || 0,
  }
  if (deptForm.id) {
    await http.patch(`/departments/${deptForm.id}`, payload)
  } else {
    await http.post('/departments', payload)
  }
  ElMessage.success('已保存')
  deptVisible.value = false
  await refreshOrg()
  await loadEmployeeOptions()
  await load()
}

async function deleteDept(data: OrgNode) {
  try {
    await ElMessageBox.confirm(
      `确定删除部门「${data.name}」？删除后不可恢复。`,
      '删除部门',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    // silent：守卫提示（有子部门/员工）由后端 detail 自己弹，避免拦截器双提示
    await http.delete(`/departments/${data.dept_id}`, { silent: true } as any)
    ElMessage.success('部门已删除')
    if (selectedDeptId.value === data.dept_id) {
      selectedKey.value = null
      selectedDeptId.value = null
      selectedDeptName.value = auth.tenantName || '全部员工'
      page.value = 1
    }
    await refreshOrg()
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.warning(typeof detail === 'string' ? detail : '无法删除该部门')
  }
}

// ── 班组（独立列表管理，不混入部门树） ──
const teams = ref<any[]>([])
const selectedTeam = ref<any | null>(null)
const selectedTeamId = ref<number | null>(null)

const selectedDeptHasSegment = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return false
  return depts.value.some((d) => d.id === selectedDeptId.value && d.process_segment_id)
})

const canCreateTeam = computed(() => selectedDeptHasSegment.value)

const teamCreateHint = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return `请先选中已挂工序段的部门，再新建${teamLabelText.value}`
  if (!selectedDeptHasSegment.value) return `需先给该部门挂工序段，才能建${teamLabelText.value}`
  return ''
})

const scopedTeams = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return []
  return teams.value.filter((t) => t.department_id === selectedDeptId.value)
})

/** 班组只能建在挂了工序段的部门下（D8），新建弹窗的部门下拉只列这些。 */
const segmentDeptOptions = computed(() => {
  const withSegment = new Set(depts.value.filter((d) => d.process_segment_id).map((d) => d.id))
  return deptOptions.value.filter((d) => withSegment.has(d.id))
})

async function loadTeams() {
  try {
    const res: any = await http.get('/teams', { params: { include_inactive: true } })
    teams.value = res.data?.items || []
  } catch {
    teams.value = []
  }
}

function onTeamClick(t: any) {
  selectedTeamId.value = t.id
  selectedTeam.value = t
}

function clearTeamSelection() {
  selectedTeamId.value = null
  selectedTeam.value = null
}

const teamVisible = ref(false)
const teamForm = reactive<any>({ id: null, name: '', leader_worker_id: null, department_id: null })

function openTeam() {
  Object.assign(teamForm, {
    id: null,
    name: '',
    leader_worker_id: null,
    department_id: typeof selectedDeptId.value === 'number' && selectedDeptHasSegment.value
      ? selectedDeptId.value
      : (segmentDeptOptions.value[0]?.id ?? null),
  })
  teamVisible.value = true
}

function editTeam(t: any) {
  Object.assign(teamForm, {
    id: t.id,
    name: t.name,
    leader_worker_id: t.leader_worker_id ?? null,
    department_id: t.department_id ?? null,
  })
  teamVisible.value = true
}

async function saveTeam() {
  if (!String(teamForm.name || '').trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (teamForm.department_id == null) {
    ElMessage.warning('请选择所属部门（需已挂工序段）')
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
  await refreshTeams()
}

// ── 组员管理 ──
const membersVisible = ref(false)
const memberIds = ref<number[]>([])
const editingTeamId = ref<number | null>(null)
const editingTeamName = ref('')
const workerOptions = ref<{ key: number; label: string }[]>([])

async function ensureWorkerMap() {
  if (workerOptions.value.length) return
  try {
    const res: any = await http.get('/teams/worker-map')
    workerOptions.value = Object.entries(res.data?.map || {}).map(([id, name]: any) => ({
      key: Number(id),
      label: name,
    }))
  } catch {
    workerOptions.value = []
  }
}

async function manageMembers(t: any) {
  editingTeamId.value = t.id
  editingTeamName.value = t.name
  memberIds.value = (t.members || []).map((m: any) => Number(m.id))
  await ensureWorkerMap()
  membersVisible.value = true
}

async function saveMembers() {
  if (editingTeamId.value == null) return
  await http.put(`/teams/${editingTeamId.value}/members`, { worker_ids: memberIds.value })
  ElMessage.success('已保存')
  membersVisible.value = false
  await refreshTeams()
}

async function refreshTeams() {
  await loadTeams()
  // 组员/班组数据变化后，同步右侧选中详情
  if (selectedTeamId.value != null) {
    const hit = teams.value.find((t) => t.id === selectedTeamId.value)
    selectedTeam.value = hit ?? null
    if (!hit) selectedTeamId.value = null
  }
}

async function refreshOrg() {
  await Promise.all([loadDepts(), loadTeams()])
}

// ── 员工表单：部门下拉快捷新建（D11/25.2） ──
const __NEW_DEPT__ = Symbol('new-dept')
const quickDeptVisible = ref(false)
const quickDeptForm = reactive<any>({ name: '', process_segment_id: null })
const quickDeptSegments = ref<any[]>([])
async function onDeptSelectChange(val: any) {
  if (val === __NEW_DEPT__) {
    form.department_id = null
    void quickAddDept()
  }
}
async function quickAddDept() {
  quickDeptForm.name = ''
  quickDeptForm.process_segment_id = null
  try {
    const segRes: any = await http.get('/process-segments')
    quickDeptSegments.value = segRes.data?.items || []
  } catch {
    quickDeptSegments.value = []
  }
  quickDeptVisible.value = true
}
async function saveQuickDept() {
  if (!String(quickDeptForm.name || '').trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const res: any = await http.post('/departments', {
    name: quickDeptForm.name.trim(),
    process_segment_id: quickDeptForm.process_segment_id,
  })
  quickDeptVisible.value = false
  ElMessage.success('已新建部门')
  await refreshOrg()
  await loadEmployeeOptions()
  form.department_id = res.data?.id ?? null
}

// ── 员工列表 ──
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const positions = ref<any[]>([])
const visible = ref(false)
const filters = reactive({
  keyword: '',
  position_id: null as number | null,
  has_account: null as boolean | null,
  is_active: null as boolean | null,
})
const form = reactive<any>({
  id: null,
  name: '',
  mobile: '',
  department_id: null,
  position_id: null,
  salary_model: 'pure_piece',
  base_salary: 0,
  base_quota: 0,
  skill_factor: 1,
  bank_account: '',
  bank_name: '',
  bank_account_name: '',
  username: '',
  roles: [] as string[],
  _lastMobile: '',
})

const positionOptions = computed(() => {
  const currentId = form.position_id
  return positions.value.filter((p) => p.is_active || p.id === currentId)
})

const roleOptions = ref<{ code: string; name: string }[]>([])

async function loadRoles() {
  try {
    const res: any = await http.get('/roles')
    const items = res.data?.items || []
    if (items.length) roleOptions.value = items.map((r: any) => ({ code: r.code, name: r.name }))
  } catch {
    roleOptions.value = []
  }
}

async function loadPositions() {
  const pRes: any = await http.get('/positions', { params: { page_size: 200 } })
  positions.value = pRes.data.items
}

async function load() {
  const params: any = {
    page: page.value,
    page_size: pageSize.value,
    keyword: filters.keyword.trim() || undefined,
    position_id: filters.position_id || undefined,
    role: filters.role || undefined,
    has_account: filters.has_account === null ? undefined : filters.has_account,
    is_active: filters.is_active === null ? undefined : filters.is_active,
  }
  if (selectedDeptId.value != null && selectedDeptId.value !== 'all') {
    params.department_id = selectedDeptId.value
  }
  const res: any = await http.get('/employees', { params })
  rows.value = res.data.items
  total.value = res.data.total || 0
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function search() {
  page.value = 1
  void load()
}

function resetFilters() {
  filters.keyword = ''
  filters.position_id = null
  filters.role = ''
  filters.has_account = null
  filters.is_active = null
  search()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

/** 手机号输入后，用户名自动填充为手机号（用户名为空或等于原手机号时）。 */
function onMobileInput() {
  const m = form.mobile || ''
  if (!form.username || form.username === form._lastMobile) {
    form.username = m
  }
  form._lastMobile = m
}

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    mobile: '',
    department_id: selectedDeptId.value !== 'all' ? selectedDeptId.value : null,
    position_id: null,
    salary_model: 'pure_piece',
    base_salary: 0,
    base_quota: 0,
    skill_factor: 1,
    bank_account: '',
    bank_name: '',
    bank_account_name: '',
    username: '',
    roles: [],
    _lastMobile: '',
  })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    mobile: row.mobile || '',
    department_id: row.department_id ?? null,
    position_id: row.position_id ?? null,
    salary_model: row.salary_model || 'pure_piece',
    base_salary: Number(row.base_salary || 0),
    base_quota: Number(row.base_quota || 0),
    skill_factor: Number(row.skill_factor ?? 1),
    bank_account: row.bank_account || '',
    bank_name: row.bank_name || '',
    bank_account_name: row.bank_account_name || '',
    username: row.username || '',
    roles: Array.isArray(row.roles) ? [...row.roles] : [],
    _lastMobile: row.mobile || '',
  })
  visible.value = true
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  const payload: any = {
    name: form.name.trim(),
    mobile: form.mobile || null,
    department_id: form.department_id ?? null,
    position_id: form.position_id ?? null,
    role: form.role,
    salary_model: form.salary_model,
    base_salary: form.base_salary,
    base_quota: form.base_quota,
    skill_factor: form.skill_factor,
    bank_account: form.bank_account || null,
    bank_name: form.bank_name || null,
    bank_account_name: form.bank_account_name || null,
  }
  payload.username = form.username?.trim() || null
  if (!form.id && !payload.username) {
    ElMessage.warning('请填写用户名（登录账号，默认同手机号）')
    return
  }
  if (isAdmin.value) payload.roles = form.roles || []
  else payload.roles = []
  if (form.id) {
    await http.patch(`/employees/${form.id}`, payload)
  } else {
    await http.post('/employees', payload)
  }
  ElMessage.success('已保存')
  visible.value = false
  await load()
  await refreshOrg()
  await loadEmployeeOptions()
}

async function toggleActive(row: any) {
  await http.patch(`/employees/${row.id}`, { is_active: !row.is_active })
  ElMessage.success('已更新')
  await load()
}

async function resetPwd(row: any) {
  await http.patch(`/employees/${row.id}`, { reset_password: true })
  ElMessage.success('已重置为默认密码 123456，下次登录须改密')
  await load()
}

onMounted(async () => {
  try {
    const orgSettings = await fetchOrgSettings()
    orgEnableTeams.value = orgSettings.enable_teams
    teamLabelText.value = orgSettings.team_label
  } catch {
    // 组织设置接口失败时按无班组模式处理
  }
  await Promise.all([loadDepts(), loadTeams(), loadSegments(), loadPositions(), loadRoles(), loadEmployeeOptions()])
  await load()
})
</script>

<style scoped>
.emp-shell {
  display: flex;
  /* admin.css 对「含分页的 admin-card」强制 column 布局，这里必须行向排列（左树右表） */
  flex-direction: row !important;
  gap: 12px;
  padding: 0;
  overflow: hidden;
}

.emp-tree-panel {
  width: 300px;
  min-width: 240px;
  min-height: 0;
  border-right: 1px solid var(--el-border-color-lighter, #e4e7ed);
  display: flex;
  flex-direction: column;
  padding: 8px 8px 12px 12px;
  /* 与全局背景（.admin-app #f3f5f8）保持一致，随主题透明继承 */
  background: transparent;
}

.emp-tab-fill {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.emp-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 4px 10px;
  flex-shrink: 0;
}

.emp-tree-title {
  font-size: 14px;
  font-weight: 600;
}

.emp-tree-search {
  padding: 0 4px 10px;
  flex-shrink: 0;
}

.emp-tree-body {
  flex: 1;
  overflow: auto;
  padding-bottom: 8px;
}

/* ── el-tree 基础：行高 / 悬停 / 选中态 ── */
.emp-tree-body :deep(.el-tree) {
  --el-tree-node-hover-bg-color: #f5f7fa;
  background: transparent;
}

.emp-tree-body :deep(.el-tree-node__content) {
  height: 36px;
  border-radius: 6px;
  margin: 1px 0;
  padding-right: 4px;
}

.emp-tree-body :deep(.el-tree-node__content:hover) {
  background: #f5f7fa;
}

/* 选中：浅蓝背景 + 主色文字 + 左侧蓝色指示条 */
.emp-tree-body :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: var(--el-color-primary-light-9, #e8f3ff);
  color: var(--el-color-primary);
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}

.emp-tree-body :deep(.el-tree-node.is-current > .el-tree-node__content .emp-tree-node__label) {
  color: var(--el-color-primary);
  font-weight: 600;
}

.emp-tree-body :deep(.el-tree-node__expand-icon) {
  font-size: 14px;
  color: #909399;
}

/* ── 树节点内容 ── */
.emp-tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  height: 36px;
}

.emp-tree-node__icon {
  font-size: 16px;
  color: #a0a6b0;
  flex-shrink: 0;
}

.emp-tree-node__icon.is-open {
  color: var(--el-color-primary);
}

.emp-tree-node__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  color: var(--el-text-color-primary, #303133);
}

/* 节点内小 tag（工序段）：不参与省略、不换行 */
.emp-tree-node__tag {
  flex-shrink: 0;
  margin-right: 0;
}

/* 人数徽章：圆角、右对齐 */
.emp-tree-node__badge {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  line-height: 18px;
  color: #6b7280;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 9px;
  padding: 0 8px;
  min-width: 24px;
  text-align: center;
}

.emp-tree-body :deep(.el-tree-node.is-current) .emp-tree-node__badge {
  border-color: var(--el-color-primary-light-7, #b3d4ff);
  color: var(--el-color-primary);
  background: #fff;
}

/* 悬停操作：右端图标按钮 */
.emp-tree-node__ops {
  display: none;
  align-items: center;
  margin-left: 4px;
  flex-shrink: 0;
}

.emp-tree-node__ops .el-button {
  margin-left: 0;
  padding: 4px;
}

.emp-tree-node:hover .emp-tree-node__ops {
  display: inline-flex;
}

.emp-tree-node:hover .emp-tree-node__badge {
  display: none;
}

.emp-list-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.emp-team-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: -4px 0 10px;
  flex-shrink: 0;
}

.emp-team-strip__hint {
  font-size: 12px;
}

.emp-team-chip {
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 16px;
  background: #fff;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 20px;
  color: var(--el-text-color-primary, #303133);
  cursor: pointer;
}

.emp-team-chip:hover {
  border-color: var(--el-color-primary-light-5, #a0cfff);
}

.emp-team-chip.is-current {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9, #e8f3ff);
  color: var(--el-color-primary);
  font-weight: 600;
}

.emp-team-chip__mark {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 500;
  opacity: 0.75;
}

.emp-scope-tip {
  font-size: 13px;
  color: var(--ws-muted, #909399);
  padding: 4px 2px 8px;
}

/* ── 班组详情（右侧选中班组时） ── */
.team-detail {
  padding: 8px 4px;
}

.team-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.team-detail-head h3 {
  margin: 0;
}

.team-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.team-detail-item span {
  display: block;
  font-size: 12px;
}

.team-detail-item b {
  font-size: 14px;
}

.team-member-list {
  margin-top: 16px;
}

.section-label {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
</style>
