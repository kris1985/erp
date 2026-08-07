<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">角色</h1>
        <p class="page-desc">角色管理 · 菜单/按钮授权 · 权限矩阵</p>
      </div>
    </header>
    <el-tabs v-model="activeTab" class="admin-tabs">
      <el-tab-pane label="角色管理" name="roles" />
      <el-tab-pane label="权限矩阵" name="matrix" />
    </el-tabs>

    <div v-show="activeTab === 'roles'" class="admin-card">
      <div class="admin-toolbar">
        <el-switch v-model="includeInactive" active-text="含停用" @change="load" />
        <el-button type="primary" @click="openCreate">新增角色</el-button>
        <el-button @click="load" :loading="loading">刷新</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" v-loading="loading" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="name" label="角色" :width="colWidth('name', 120)" resizable />
        <el-table-column prop="code" label="编码" :width="colWidth('code', 120)" resizable />
        <el-table-column column-key="type" label="类型" :width="colWidth('type', 90)" resizable>
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_system ? 'info' : 'success'">
              {{ row.is_system ? '内置' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="接口级别" label="接口级别" :width="colWidth('接口级别', 100)" resizable>
          <template #default="{ row }">{{ baseLabel(row.base_role) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" :min-width="flexColMinWidth('description', 180)" resizable />
        <el-table-column column-key="权限数" label="权限数" :width="colWidth('权限数', 90)" resizable>
          <template #default="{ row }">{{ row.permission_count }}</template>
        </el-table-column>
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 80)" resizable>
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 280)" resizable>
          <template #default="{ row }">
            <el-button link type="primary" @click="openPerms(row)">
              {{ row.editable === false ? '查看权限' : '编辑权限' }}
            </el-button>
            <el-button link @click="openCopy(row)">复制</el-button>
            <el-button v-if="!row.is_system" link @click="openMeta(row)">改资料</el-button>
            <el-button
              v-if="!row.is_system"
              link
              type="danger"
              @click="removeRole(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>

    <div v-show="activeTab === 'matrix'" class="admin-card">
      <div class="admin-toolbar">
        <el-select v-model="moduleFilter" clearable placeholder="模块" style="width: 140px">
          <el-option v-for="m in modules" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="kindFilter" clearable placeholder="类型" style="width: 120px">
          <el-option label="菜单" value="menu" />
          <el-option label="按钮" value="button" />
        </el-select>
        <el-button @click="load" :loading="loading">刷新</el-button>
      </div>
      <div ref="tableHostRef1">
      <el-table :data="matrixFiltered" stripe border style="width: 100%" v-loading="loading" :max-height="tableMaxHeight1" @header-dragend="onHeaderDragend1">
        <el-table-column prop="module" label="模块" :width="colWidth1('module', 110)" resizable />
        <el-table-column column-key="type" label="类型" :width="colWidth1('type', 80)" resizable>
          <template #default="{ row }">{{ row.kind === 'menu' ? '菜单' : '按钮' }}</template>
        </el-table-column>
        <el-table-column prop="name" label="权限" :min-width="flexColMinWidth1('name', 140)" resizable />
        <el-table-column prop="code" label="编码" :width="colWidth1('code', 180)" resizable />
        <el-table-column
          column-key="r_name" v-for="r in matrixRoles"
          :key="r.code"
          :label="r.name"
          :width="colWidth1('r_name', 100)"
          align="center" resizable>
          <template #default="{ row }">
            <el-tag v-if="row.roles?.[r.code]" size="small" type="success">有</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>

    <el-dialog v-model="createVisible" title="新增角色" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="如：跟单员" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createRole">创建并编辑权限</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="copyVisible" title="复制角色" width="480px">
      <el-form label-width="80px">
        <el-form-item label="来源">
          <span>{{ copyForm.sourceName }}</span>
          <span class="muted" style="margin-left: 8px; font-size: 12px">
            将复制其菜单/按钮权限
          </span>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="copyForm.name" placeholder="新角色名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="copyForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="copyVisible = false">取消</el-button>
        <el-button type="primary" :loading="copying" @click="copyRole">复制并编辑权限</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="metaVisible" title="改角色资料" width="480px">
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="metaForm.name" />
        </el-form-item>
        <el-form-item label="接口级别">
          <el-select v-model="metaForm.base_role" style="width: 100%">
            <el-option label="主管级" value="manager" />
            <el-option label="组长级" value="leader" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="metaForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="metaForm.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="metaVisible = false">取消</el-button>
        <el-button type="primary" :loading="metaSaving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="editVisible"
      :title="`${editRole?.name || ''} · 权限`"
      class="perm-drawer"
      size="560px"
      destroy-on-close
    >
      <template v-if="editRole">
        <div class="perm-drawer-head">
          <p class="perm-drawer-desc">
            {{ editRole.description || '—' }}
            · 接口级别 {{ baseLabel(editRole.base_role) }}
          </p>
          <div class="perm-drawer-actions">
            <el-button size="small" :disabled="!canEdit" @click="selectAll">全选</el-button>
            <el-button size="small" :disabled="!canEdit" @click="clearAll">清空</el-button>
          </div>
        </div>

        <!-- 模块/菜单纵向；按钮权限横向 wrap -->
        <div class="perm-module-list">
          <section v-for="mod in moduleCards" :key="mod.id" class="perm-module-card">
            <header class="perm-module-head">
              <el-checkbox
                :model-value="mod.allChecked"
                :indeterminate="mod.indeterminate"
                :disabled="!canEdit"
                @change="(v) => toggleModule(mod, !!v)"
              >
                <span class="perm-module-title">{{ mod.label }}</span>
              </el-checkbox>
              <span class="perm-module-count">{{ mod.checkedCount }}/{{ mod.codes.length }}</span>
            </header>
            <div class="perm-module-body">
              <div
                v-for="menu in mod.menus"
                :key="menu.code"
                class="perm-menu-block"
                :style="{ paddingLeft: `${8 + menu.depth * 12}px` }"
              >
                <div class="perm-menu-row">
                  <el-checkbox
                    :model-value="checked.has(menu.code)"
                    :disabled="!canEdit"
                    @change="(v) => toggleCode(menu.code, !!v)"
                  >
                    {{ menu.label }}
                  </el-checkbox>
                </div>
                <div v-if="menu.buttons.length" class="perm-btn-row">
                  <el-checkbox
                    v-for="btn in menu.buttons"
                    :key="btn.code"
                    class="perm-btn-item"
                    :model-value="checked.has(btn.code)"
                    :disabled="!canEdit"
                    @change="(v) => toggleCode(btn.code, !!v)"
                  >
                    {{ btn.label }}
                  </el-checkbox>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="perm-drawer-footer">
          <el-button @click="editVisible = false">关闭</el-button>
          <el-button v-if="canEdit" type="primary" :loading="saving" @click="savePerms">保存</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const {
  tableHostRef: tableHostRef1,
  tableMaxHeight: tableMaxHeight1,
  measureTableHeight: measureTableHeight1,
} = useTableMaxHeight()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('roles-list', tableRef)
const { colWidth: colWidth1, flexColMinWidth: flexColMinWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('roles-permissions')
type PermNode = {
  id: string
  code?: string | null
  label: string
  is_group?: boolean
  children?: PermNode[]
}

type PermBtn = { code: string; label: string }

type PermMenu = {
  code: string
  label: string
  depth: number
  buttons: PermBtn[]
}

type ModuleCard = {
  id: string
  label: string
  codes: string[]
  menus: PermMenu[]
  allChecked: boolean
  indeterminate: boolean
  checkedCount: number
}

const BASE_LABEL: Record<string, string> = {
  admin: '管理员',
  manager: '主管',
  leader: '组长',
}

const route = useRoute()
const router = useRouter()
const activeTab = ref('roles')
const rows = ref<any[]>([])
const tree = ref<PermNode[]>([])
const matrixRoles = ref<{ code: string; name: string }[]>([])
const matrixItems = ref<any[]>([])
const moduleFilter = ref('')
const kindFilter = ref('')
const loading = ref(false)
const checked = ref<Set<string>>(new Set())
/** 触发视图更新（Set 本身非响应式深变） */
const checkedTick = ref(0)

const modules = computed(() => {
  const set = new Set(matrixItems.value.map((i) => i.module).filter(Boolean))
  return [...set]
})

const matrixFiltered = computed(() =>
  matrixItems.value.filter((i) => {
    if (moduleFilter.value && i.module !== moduleFilter.value) return false
    if (kindFilter.value && i.kind !== kindFilter.value) return false
    return true
  }),
)
const saving = ref(false)
const creating = ref(false)
const copying = ref(false)
const metaSaving = ref(false)
const includeInactive = ref(false)
const editVisible = ref(false)
const createVisible = ref(false)
const copyVisible = ref(false)
const metaVisible = ref(false)
const editRole = ref<any>(null)

const createForm = reactive({
  name: '',
  description: '',
})

const copyForm = reactive({
  sourceCode: '',
  sourceName: '',
  name: '',
  description: '',
})

const metaForm = reactive({
  code: '',
  name: '',
  description: '',
  base_role: 'leader',
  is_active: true,
})

const canEdit = computed(() => editRole.value && editRole.value.editable !== false)

/** code -> 祖先 codes（近到远） */
const parentMap = computed(() => {
  const map = new Map<string, string[]>()
  function walk(nodes: PermNode[], ancestors: string[]) {
    for (const n of nodes) {
      if (n.code) {
        map.set(n.code, ancestors)
        walk(n.children || [], [...ancestors, n.code])
      } else {
        walk(n.children || [], ancestors)
      }
    }
  }
  walk(tree.value, [])
  return map
})

/** code -> 所有后代 codes */
const descendantMap = computed(() => {
  const map = new Map<string, string[]>()
  function collect(nodes: PermNode[]): string[] {
    const acc: string[] = []
    for (const n of nodes) {
      if (n.code) {
        const childCodes = collect(n.children || [])
        map.set(n.code, childCodes)
        acc.push(n.code, ...childCodes)
      } else {
        acc.push(...collect(n.children || []))
      }
    }
    return acc
  }
  collect(tree.value)
  return map
})

const allLeafCodes = computed(() => collectLeafCodes(tree.value))

const moduleCards = computed((): ModuleCard[] => {
  void checkedTick.value
  const set = checked.value
  return tree.value.map((mod) => {
    const codes = collectLeafCodes([mod])
    const menus = flattenMenus(mod.children || [])
    const checkedCount = codes.filter((c) => set.has(c)).length
    const allChecked = codes.length > 0 && checkedCount === codes.length
    const indeterminate = checkedCount > 0 && !allChecked
    return {
      id: mod.id,
      label: mod.label,
      codes,
      menus,
      allChecked,
      indeterminate,
      checkedCount,
    }
  })
})

function baseLabel(code: string) {
  return BASE_LABEL[code] || code
}

function collectLeafCodes(nodes: PermNode[], acc: string[] = []): string[] {
  for (const n of nodes) {
    if (n.code) acc.push(n.code)
    if (n.children?.length) collectLeafCodes(n.children, acc)
  }
  return acc
}

function isButtonCode(code: string) {
  return String(code).startsWith('btn.')
}

/** 菜单纵向；每个菜单下的按钮抽成横向列表；嵌套菜单继续纵向 */
function flattenMenus(nodes: PermNode[], depth = 0): PermMenu[] {
  const out: PermMenu[] = []
  for (const n of nodes) {
    if (!n.code) {
      if (n.children?.length) out.push(...flattenMenus(n.children, depth))
      continue
    }
    if (isButtonCode(n.code)) {
      // 孤立按钮（无父菜单展示上下文时）仍单独成行，按钮列表为空旁的自身
      out.push({ code: n.code, label: n.label, depth, buttons: [] })
      continue
    }
    const children = n.children || []
    const buttons: PermBtn[] = []
    const nestedMenus: PermNode[] = []
    for (const c of children) {
      if (c.code && isButtonCode(c.code)) {
        buttons.push({ code: c.code, label: c.label })
      } else {
        nestedMenus.push(c)
      }
    }
    out.push({ code: n.code, label: n.label, depth, buttons })
    if (nestedMenus.length) out.push(...flattenMenus(nestedMenus, depth + 1))
  }
  return out
}

function bumpChecked() {
  checkedTick.value += 1
}

function setCheckedCodes(codes: string[]) {
  checked.value = new Set(codes.filter((c) => typeof c === 'string' && !c.startsWith('group:')))
  bumpChecked()
}

function toggleCode(code: string, on: boolean) {
  if (!canEdit.value) return
  const next = new Set(checked.value)
  const descendants = descendantMap.value.get(code) || []
  if (on) {
    next.add(code)
    for (const d of descendants) next.add(d)
    for (const a of parentMap.value.get(code) || []) next.add(a)
  } else {
    next.delete(code)
    for (const d of descendants) next.delete(d)
    // 祖先：若其下已无任何选中后代，则移除
    const ancestors = parentMap.value.get(code) || []
    for (const a of [...ancestors].reverse()) {
      const aDesc = descendantMap.value.get(a) || []
      if (!aDesc.some((d) => next.has(d))) next.delete(a)
    }
  }
  checked.value = next
  bumpChecked()
}

function toggleModule(mod: ModuleCard, on: boolean) {
  if (!canEdit.value) return
  const next = new Set(checked.value)
  if (on) {
    for (const c of mod.codes) next.add(c)
  } else {
    for (const c of mod.codes) next.delete(c)
  }
  checked.value = next
  bumpChecked()
}

function selectAll() {
  setCheckedCodes(allLeafCodes.value)
}

function clearAll() {
  setCheckedCodes([])
}

async function load() {
  loading.value = true
  try {
    const [rolesRes, permRes]: any[] = await Promise.all([
      http.get('/roles', { params: { include_inactive: includeInactive.value } }),
      http.get('/permissions'),
    ])
    rows.value = rolesRes.data?.items || []
    tree.value = permRes.data?.tree || []
    matrixRoles.value = permRes.data?.roles || []
    matrixItems.value = permRes.data?.items || []
  } finally {
    loading.value = false
    void nextTick(() => {
      measureTableHeight()
      measureTableHeight1()
    })
  }
}

function openCreate() {
  Object.assign(createForm, { name: '', description: '' })
  createVisible.value = true
}

async function createRole() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/roles', {
      name: createForm.name.trim(),
      description: createForm.description || null,
      permissions: [],
    })
    ElMessage.success('角色已创建')
    createVisible.value = false
    await load()
    const created = res.data
    if (created) openPerms(created)
  } finally {
    creating.value = false
  }
}

function openCopy(row: any) {
  Object.assign(copyForm, {
    sourceCode: row.code,
    sourceName: row.name,
    name: `${row.name} 副本`,
    description: row.description || '',
  })
  copyVisible.value = true
}

async function copyRole() {
  if (!copyForm.name.trim()) {
    ElMessage.warning('请填写新角色名称')
    return
  }
  if (!copyForm.sourceCode) {
    ElMessage.warning('缺少复制来源')
    return
  }
  copying.value = true
  try {
    const res: any = await http.post('/roles', {
      name: copyForm.name.trim(),
      description: copyForm.description || null,
      copy_from: copyForm.sourceCode,
    })
    ElMessage.success('角色已复制')
    copyVisible.value = false
    await load()
    const created = res.data
    if (created) openPerms(created)
  } finally {
    copying.value = false
  }
}

function openMeta(row: any) {
  Object.assign(metaForm, {
    code: row.code,
    name: row.name,
    description: row.description || '',
    base_role: row.base_role === 'manager' ? 'manager' : 'leader',
    is_active: !!row.is_active,
  })
  metaVisible.value = true
}

async function saveMeta() {
  if (!metaForm.name.trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  metaSaving.value = true
  try {
    await http.patch(`/roles/${metaForm.code}`, {
      name: metaForm.name.trim(),
      description: metaForm.description || null,
      base_role: metaForm.base_role,
      is_active: metaForm.is_active,
    })
    ElMessage.success('已保存')
    metaVisible.value = false
    await load()
  } finally {
    metaSaving.value = false
  }
}

async function removeRole(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除角色「${row.name}」？`, '删除角色', { type: 'warning' })
  } catch {
    return
  }
  await http.delete(`/roles/${row.code}`)
  ElMessage.success('已删除')
  await load()
}

async function openPerms(row: any) {
  editRole.value = row
  editVisible.value = true
  setCheckedCodes([])
  const res: any = await http.get(`/roles/${row.code}/permissions`)
  if (res.data?.tree?.length) tree.value = res.data.tree
  setCheckedCodes(res.data?.permissions || [])
}

async function savePerms() {
  if (!editRole.value || !canEdit.value) return
  const permissions = [...checked.value].filter(
    (id) => typeof id === 'string' && !id.startsWith('group:'),
  )
  saving.value = true
  try {
    await http.put(`/roles/${editRole.value.code}/permissions`, { permissions })
    ElMessage.success('权限已保存')
    editVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

watch(activeTab, (tab) => {
  const q = { ...route.query }
  if (tab === 'matrix') q.tab = 'matrix'
  else delete q.tab
  router.replace({ query: q })
  void nextTick(() => {
    measureTableHeight()
    measureTableHeight1()
  })
})

onMounted(() => {
  if (route.query.tab === 'matrix') activeTab.value = 'matrix'
  void load()
})
</script>

<style scoped>
.perm-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.perm-drawer-desc {
  margin: 0;
  flex: 1;
  min-width: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.perm-drawer-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.perm-module-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 64px;
}

.perm-module-card {
  border: 1px solid #e5eaf2;
  border-radius: 8px;
  background: #fff;
  min-width: 0;
  overflow: hidden;
}

.perm-module-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #eef2f7;
}

.perm-module-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.perm-module-count {
  flex-shrink: 0;
  font-size: 12px;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

.perm-module-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 8px 10px;
}

.perm-menu-block {
  padding-right: 4px;
}

.perm-menu-row {
  min-height: 32px;
  display: flex;
  align-items: center;
}

.perm-menu-row :deep(.el-checkbox__label) {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.perm-btn-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 14px;
  padding: 2px 0 6px 22px;
}

.perm-btn-item {
  margin-right: 0 !important;
  height: 28px;
}

.perm-btn-item :deep(.el-checkbox__label) {
  font-size: 12px;
  font-weight: 400;
  color: #64748b;
  padding-left: 6px;
}

.perm-drawer-footer {
  position: sticky;
  bottom: 0;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding: 12px 0 4px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), #fff 28%);
}
</style>
