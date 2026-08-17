<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">员工管理</h1>
        <p class="page-desc">档案 · 部门 · 账号 · 角色（左选部门，右看成员）</p>
      </div>
    </header>

    <div class="admin-card emp-shell">
      <!-- 左：部门树 -->
      <aside class="emp-tree-panel">
        <div class="emp-tree-header">
          <span class="emp-tree-title">部门</span>
          <el-button link type="primary" size="small" @click="openDeptCreate()">＋ 新增</el-button>
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
            :key="deptKeyword"
            ref="deptTreeRef"
            :data="filteredDeptTree"
            node-key="id"
            :props="{ label: 'name', children: 'children' }"
            highlight-current
            :expand-on-click-node="false"
            default-expand-all
            :current-node-key="selectedDeptId"
            @node-click="onDeptClick"
          >
            <template #default="{ data, node }">
              <el-tooltip
                :content="data.manager_name ? `主管：${data.manager_name}` : data.name"
                placement="top"
                :show-after="400"
              >
                <div class="emp-tree-node">
                  <el-icon class="emp-tree-node__icon" :class="{ 'is-open': node.expanded }">
                    <component :is="data.id === 'all' ? HomeFilled : node.expanded ? FolderOpened : Folder" />
                  </el-icon>
                  <span class="emp-tree-node__label">{{ data.name }}</span>
                  <span v-if="data.employee_count" class="emp-tree-node__badge">{{ data.employee_count }}</span>
                  <span class="emp-tree-node__ops" @click.stop>
                    <el-button link size="small" title="新增子部门" @click="openDeptCreate(data.id)">
                      <el-icon><Plus /></el-icon>
                    </el-button>
                    <el-button link size="small" title="编辑部门" @click="openDeptEdit(data)">
                      <el-icon><EditPen /></el-icon>
                    </el-button>
                    <el-button
                      v-if="data.id !== 'all'"
                      link
                      size="small"
                      title="删除部门"
                      @click="deleteDept(data)"
                    >
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </span>
                </div>
              </el-tooltip>
            </template>
          </el-tree>
        </div>
      </aside>

      <!-- 右：员工列表 -->
      <section class="emp-list-panel">
        <div class="admin-toolbar">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="姓名 / 手机"
            style="width: 150px"
            @clear="search"
            @keyup.enter="search"
          />
          <el-select v-model="filters.position_id" clearable filterable placeholder="全部职位" style="width: 120px" @change="search">
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
        <div v-if="selectedDeptName" class="emp-scope-tip">当前范围：{{ selectedDeptName }}</div>

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
            <el-table-column column-key="pos" label="职位" :width="colWidth('pos', 90)" resizable>
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
            <el-table-column column-key="pay" label="计薪" :width="colWidth('pay', 100)" resizable>
              <template #default="{ row }">{{ salaryLabel(row.salary_model) }}</template>
            </el-table-column>
            <el-table-column prop="base_salary" label="底薪" :width="colWidth('base_salary', 80)" align="right" resizable />
            <el-table-column column-key="bank" label="银行卡" :width="colWidth('bank', 130)" resizable>
              <template #default="{ row }">
                <span v-if="row.bank_account">{{ maskBank(row.bank_account) }}</span>
                <span v-else class="muted">未填</span>
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
          <el-select v-model="form.department_id" clearable filterable placeholder="请选择" style="width: 100%">
            <el-option v-for="d in deptOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="职位">
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
        <el-form-item label="主管">
          <el-select
            v-model="deptForm.manager_employee_id"
            clearable
            filterable
            placeholder="选一名员工（可跨部门）"
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
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  EditPen,
  Folder,
  FolderOpened,
  HomeFilled,
  Plus,
  Search,
} from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin())
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend, relayoutTable } = useTableColWidths('employees-list', tableRef, {
  flexKey: 'roles',
  flexDefaultMin: 140,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const SALARY_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  hourly: '计时',
  fixed: '固定',
}

function salaryLabel(v: string) {
  return SALARY_LABELS[v] || v
}
function maskBank(no: string) {
  const s = String(no || '')
  if (s.length <= 8) return s
  return `${s.slice(0, 4)}****${s.slice(-4)}`
}

// ── 部门树 ──
interface DeptNode {
  id: number | 'all'
  name: string
  parent_id: number | null
  manager_name?: string
  employee_count: number
  is_active: boolean
  children?: DeptNode[]
}

const depts = ref<any[]>([])
const deptTreeRef = ref()
const deptTreeData = ref<DeptNode[]>([])
const selectedDeptId = ref<number | null | 'all'>(null)
const selectedDeptName = ref('全部员工')
const deptKeyword = ref('')

/** 搜索过滤：命中部门或命中其子孙时保留该分支（根节点始终保留）。 */
const filteredDeptTree = computed<DeptNode[]>(() => {
  const kw = deptKeyword.value.trim()
  if (!kw) return deptTreeData.value
  const filter = (nodes: DeptNode[]): DeptNode[] =>
    nodes
      .map((n) => {
        const children = n.children?.length ? filter(n.children) : []
        if (n.name.includes(kw) || children.length) return { ...n, children }
        return null
      })
      .filter((n): n is DeptNode => n !== null)
  return filter(deptTreeData.value)
})

function buildDeptTree(list: any[]): DeptNode[] {
  const root: DeptNode = { id: 'all', name: '全部员工', parent_id: null, employee_count: list.reduce((n, d) => n + (d.employee_count || 0), 0), is_active: true, children: [] }
  const byId = new Map<number, DeptNode>()
  for (const d of list) {
    byId.set(d.id, {
      id: d.id,
      name: d.name,
      parent_id: d.parent_id,
      manager_name: d.manager_name,
      employee_count: d.employee_count || 0,
      is_active: d.is_active,
      children: [],
    })
  }
  const roots: DeptNode[] = []
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

async function loadDepts() {
  const res: any = await http.get('/departments')
  depts.value = res.data?.items || []
  deptTreeData.value = buildDeptTree(depts.value)
}

function onDeptClick(data: DeptNode) {
  selectedDeptId.value = data.id
  selectedDeptName.value = data.name
  page.value = 1
  void load()
}

// 部门下拉选项（含子部门平铺，缩进提示）
const deptOptions = computed(() => {
  const flat: any[] = []
  const walk = (nodes: DeptNode[], depth: number) => {
    for (const n of nodes) {
      if (n.id !== 'all') {
        flat.push({ ...n, name: `${'　'.repeat(depth)}${n.name}` })
        if (n.children?.length) walk(n.children, depth + 1)
      }
    }
  }
  walk(deptTreeData.value, 0)
  return flat
})

// 员工下拉（部门主管选择）
const employeeOptions = ref<any[]>([])
async function loadEmployeeOptions() {
  try {
    const res: any = await http.get('/employees', { params: { page_size: 500, is_active: true } })
    employeeOptions.value = res.data?.items || []
  } catch {
    employeeOptions.value = []
  }
}

const deptVisible = ref(false)
const deptForm = reactive<any>({ id: null, name: '', parent_id: null, manager_employee_id: null, sort_order: 0 })

function openDeptCreate(parentId?: number | null) {
  const defaultParent = parentId != null ? parentId : selectedDeptId.value === 'all' ? null : selectedDeptId.value
  Object.assign(deptForm, { id: null, name: '', parent_id: defaultParent, manager_employee_id: null, sort_order: 0 })
  deptVisible.value = true
}

function openDeptEdit(data: DeptNode) {
  const raw = depts.value.find((d) => d.id === data.id)
  Object.assign(deptForm, {
    id: data.id,
    name: data.name,
    parent_id: data.parent_id ?? null,
    manager_employee_id: raw?.manager_employee_id ?? null,
    sort_order: raw?.sort_order ?? 0,
  })
  deptVisible.value = true
}

const deptParentOptions = computed(() => deptOptions.value.filter((d) => d.id !== deptForm.id))

async function saveDept() {
  if (!deptForm.name?.trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const payload = {
    name: deptForm.name.trim(),
    parent_id: deptForm.parent_id ?? null,
    manager_employee_id: deptForm.manager_employee_id ?? null,
    sort_order: deptForm.sort_order || 0,
  }
  if (deptForm.id) {
    await http.patch(`/departments/${deptForm.id}`, payload)
  } else {
    await http.post('/departments', payload)
  }
  ElMessage.success('已保存')
  deptVisible.value = false
  await loadDepts()
  await loadEmployeeOptions()
}

async function deleteDept(data: DeptNode) {
  if (data.id === 'all') return
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
    await http.delete(`/departments/${data.id}`)
    ElMessage.success('部门已删除')
    if (selectedDeptId.value === data.id) {
      selectedDeptId.value = null
      selectedDeptName.value = '全部员工'
      page.value = 1
    }
    await loadDepts()
    await load()
  } catch (e: any) {
    // 守卫提示（有子部门/员工）由 http 拦截器统一弹出
    if (e?.response?.status === 400) {
      ElMessage.warning(e.response.data?.detail || '无法删除该部门')
      return
    }
  }
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
  await loadDepts()
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
  await Promise.all([loadDepts(), loadPositions(), loadRoles(), loadEmployeeOptions()])
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
  width: 260px;
  min-width: 220px;
  border-right: 1px solid var(--el-border-color-lighter, #e4e7ed);
  display: flex;
  flex-direction: column;
  padding: 12px 8px 12px 12px;
  /* 与全局背景（.admin-app #f3f5f8）保持一致，随主题透明继承 */
  background: transparent;
}

.emp-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 10px;
}

.emp-tree-title {
  font-size: 14px;
  font-weight: 600;
}

.emp-tree-search {
  padding: 0 4px 10px;
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

/* ── 节点内容 ── */
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

.emp-tree-node__ops .el-icon {
  font-size: 13px;
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
  padding: 12px;
}

.emp-scope-tip {
  font-size: 13px;
  color: var(--ws-muted, #909399);
  padding: 4px 2px 8px;
}
</style>
