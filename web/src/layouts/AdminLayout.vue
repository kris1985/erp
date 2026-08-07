<template>
  <div class="admin-app" :class="{ 'is-aside-collapsed': collapsed }">
    <div class="admin-layout">
      <aside class="admin-aside">
        <div class="admin-brand">
          <span class="admin-brand-text">{{ collapsed ? '铁' : '铁玉兰管家' }}</span>
          <button
            type="button"
            class="admin-collapse-btn"
            :title="collapsed ? '展开菜单' : '收起菜单'"
            @click="toggleCollapsed"
          >
            {{ collapsed ? '»' : '«' }}
          </button>
        </div>
        <nav class="admin-nav" aria-label="后台导航">
          <template v-for="entry in menuEntries" :key="entry.key">
            <RouterLink
              v-if="entry.type === 'item'"
              :to="entry.path"
              class="admin-nav-item"
              :class="{ 'is-active': active === entry.path }"
              :title="collapsed ? entry.label : undefined"
            >
              <span class="admin-nav-row">
                <span class="admin-nav-icon"><el-icon><component :is="entry.icon" /></el-icon></span>
                <span v-if="!collapsed" class="admin-nav-label">{{ entry.label }}</span>
              </span>
            </RouterLink>
            <el-popover
              v-else
              :visible="flyoutKey === entry.key"
              :trigger="finePointer ? 'hover' : 'click'"
              placement="right-start"
              :show-arrow="false"
              :offset="4"
              :width="168"
              :show-after="80"
              :hide-after="120"
              :teleported="true"
              popper-class="admin-nav-flyout-popper"
              @update:visible="(v) => onFlyoutVisible(entry.key, !!v)"
            >
              <template #reference>
                <button
                  type="button"
                  class="admin-nav-item admin-nav-group-trigger"
                  :class="{
                    'is-open': flyoutKey === entry.key,
                    'is-active': isGroupActive(entry),
                  }"
                  :title="collapsed ? entry.label : undefined"
                >
                  <span class="admin-nav-row">
                    <span class="admin-nav-icon"><el-icon><component :is="entry.icon" /></el-icon></span>
                    <span v-if="!collapsed" class="admin-nav-label">{{ entry.label }}</span>
                    <span v-if="!collapsed" class="admin-nav-chevron" aria-hidden="true">›</span>
                  </span>
                </button>
              </template>
              <div class="admin-nav-flyout">
                <div v-if="collapsed" class="admin-nav-flyout-head">{{ entry.label }}</div>
                <RouterLink
                  v-for="item in entry.items"
                  :key="item.path"
                  :to="item.path"
                  class="admin-nav-flyout-item"
                  :class="{ 'is-active': active === item.path }"
                  @click="closeFlyout"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
            </el-popover>
          </template>
        </nav>
        <div class="admin-aside-user">
          <el-dropdown trigger="click" placement="top-start" @command="onUserCommand">
            <button type="button" class="admin-user-trigger" :title="auth.displayName || '用户'">
              <span class="admin-user-avatar">{{ userInitial }}</span>
              <span v-if="!collapsed" class="admin-user-meta">
                <span class="admin-user-name">{{ auth.displayName || '用户' }}</span>
                <span class="admin-user-role">{{ roleLabel }}</span>
              </span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </aside>
      <div class="admin-main">
        <main class="admin-content" :class="{ 'is-flush': isFlushContent }">
          <router-view v-slot="{ Component, route: r }">
            <keep-alive :max="20">
              <component :is="Component" :key="r.path" />
            </keep-alive>
          </router-view>
        </main>
      </div>
    </div>

    <el-dialog
      v-model="profileVisible"
      title="个人中心"
      width="440px"
      destroy-on-close
      append-to-body
      @closed="resetPwdForm"
    >
      <el-descriptions :column="1" border size="small" style="margin-bottom: 16px">
        <el-descriptions-item label="显示名">{{ profile.display_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="用户名">{{ profile.username || '—' }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ profile.role_name || roleLabel }}</el-descriptions-item>
        <el-descriptions-item label="工厂">{{ profile.tenant_name || '—' }}</el-descriptions-item>
      </el-descriptions>

      <div style="font-weight: 600; margin-bottom: 10px">修改密码</div>
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="原密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="pwdForm.new_password"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="profileVisible = false">关闭</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePassword">保存新密码</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Box,
  Calendar,
  ChatDotRound,
  CreditCard,
  DataAnalysis,
  Document,
  Goods,
  Grid,
  List,
  Money,
  Notebook,
  Odometer,
  OfficeBuilding,
  Setting,
  ShoppingCart,
  Stamp,
  User,
  UserFilled,
  Van,
  Warning,
} from '@element-plus/icons-vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type MenuLeaf = {
  path: string
  label: string
  perm: string
  icon: any
  /** 租户库存能力；缺省不校验 */
  cap?: string
  /** 任一权限即可显示（用于合并菜单） */
  orPerm?: string
  orCap?: string
}

type MenuEntry =
  | {
      type: 'item'
      key: string
      path: string
      label: string
      perm: string
      icon: any
      cap?: string
      orPerm?: string
      orCap?: string
    }
  | { type: 'group'; key: string; label: string; icon: any; items: MenuLeaf[] }

const STORAGE_COLLAPSE = 'ws_admin_aside_collapsed'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const collapsed = ref(false)
const flyoutKey = ref<string | null>(null)
const finePointer = ref(true)
const profileVisible = ref(false)
const pwdSaving = ref(false)
let pointerMq: MediaQueryList | null = null
const profile = reactive({
  username: '',
  display_name: '',
  role: '',
  role_name: '',
  tenant_name: '',
})
const pwdForm = reactive({
  old_password: '',
  new_password: '',
  confirm: '',
})

function canMenu(perm: string, cap?: string) {
  if (cap && !auth.hasCapability(cap)) return false
  return auth.hasPermission(perm)
}

function canMenuLeaf(leaf: Pick<MenuLeaf, 'perm' | 'cap' | 'orPerm' | 'orCap'>) {
  if (canMenu(leaf.perm, leaf.cap)) return true
  if (leaf.orPerm && canMenu(leaf.orPerm, leaf.orCap)) return true
  return false
}

const menuEntries = computed(() => {
  const all: MenuEntry[] = [
    {
      type: 'item',
      key: 'board',
      path: '/admin',
      label: '工作台',
      perm: 'menu.board',
      icon: Odometer,
    },
    {
      type: 'item',
      key: 'schedule-assistant',
      path: '/admin/schedule-assistant',
      label: '车间军师',
      perm: 'menu.schedule',
      icon: ChatDotRound,
    },
    {
      type: 'item',
      key: 'partners',
      path: '/admin/partners',
      label: '合作商',
      perm: 'menu.customers',
      icon: OfficeBuilding,
      orPerm: 'menu.suppliers',
    },
    {
      type: 'item',
      key: 'supplier-products',
      path: '/admin/supplier-products',
      label: '物料色卡',
      perm: 'menu.supplier_products',
      icon: Goods,
    },
    {
      type: 'item',
      key: 'own-products',
      path: '/admin/own-products',
      label: '产品开发',
      perm: 'menu.own_products',
      icon: Grid,
    },
    {
      type: 'item',
      key: 'sales-orders',
      path: '/admin/sales-orders',
      label: '订单管理',
      perm: 'menu.sales_orders',
      icon: Document,
    },
    {
      type: 'item',
      key: 'orders',
      path: '/admin/orders',
      label: '生产订单',
      perm: 'menu.orders',
      icon: Document,
    },
    {
      type: 'item',
      key: 'purchase',
      path: '/admin/purchase',
      label: '采购',
      perm: 'menu.purchase_orders',
      icon: ShoppingCart,
      orPerm: 'menu.material_shortages',
    },
    {
      type: 'item',
      key: 'inventory',
      path: '/admin/inventory',
      label: '仓库管理',
      perm: 'menu.shared_materials',
      icon: Box,
      cap: 'shared_pool',
      orPerm: 'menu.stock_issues',
      orCap: 'stock_docs',
    },
    {
      type: 'item',
      key: 'stock-allocate',
      path: '/admin/stock-allocate',
      label: '锁料（高级）',
      perm: 'menu.stock_allocate',
      icon: List,
      cap: 'allocate_ui',
    },
    {
      type: 'item',
      key: 'schedule',
      path: '/admin/schedule',
      label: '排产',
      perm: 'menu.schedule',
      icon: Calendar,
    },
    {
      type: 'group',
      key: 'g-produce',
      label: '生产',
      icon: Stamp,
      items: [
        { path: '/admin/work-logs', label: '报工', perm: 'menu.work_logs', icon: Notebook },
        { path: '/admin/defects', label: '不良', perm: 'menu.defects', icon: Warning },
        { path: '/admin/stations', label: '工位码', perm: 'menu.stations', icon: Grid },
      ],
    },
    {
      type: 'group',
      key: 'g-ship',
      label: '出货回款',
      icon: Van,
      items: [
        { path: '/admin/shipments', label: '出货', perm: 'menu.shipments', icon: Van },
        { path: '/admin/receivables', label: '应收', perm: 'menu.receivables', icon: CreditCard },
        { path: '/admin/payments', label: '回款', perm: 'menu.payments', icon: Money },
        { path: '/admin/profit', label: '利润', perm: 'menu.profit', icon: DataAnalysis },
      ],
    },
    {
      type: 'group',
      key: 'g-hr',
      label: '人事工资',
      icon: UserFilled,
      items: [
        { path: '/admin/workers', label: '员工', perm: 'menu.workers', icon: User },
        { path: '/admin/teams', label: '班组', perm: 'menu.teams', icon: UserFilled },
        { path: '/admin/salary', label: '工资', perm: 'menu.salary', icon: Money },
      ],
    },
    {
      type: 'group',
      key: 'g-sys',
      label: '系统',
      icon: Setting,
      items: [
        { path: '/admin/users', label: '用户', perm: 'menu.users', icon: User },
        { path: '/admin/roles', label: '角色', perm: 'menu.roles', icon: Stamp },
        { path: '/admin/masters', label: '基础资料', perm: 'menu.masters', icon: Notebook },
        {
          path: '/admin/inventory-settings',
          label: '库存设置',
          perm: 'menu.inventory_settings',
          icon: Box,
        },
        {
          path: '/admin/workshop-settings',
          label: '报工规则',
          perm: 'menu.workshop_settings',
          icon: Stamp,
        },
      ],
    },
  ]

  return all
    .map((entry) => {
      if (entry.type === 'item') {
        return canMenuLeaf(entry) ? entry : null
      }
      const items = entry.items.filter((i) => canMenuLeaf(i))
      return items.length ? { ...entry, items } : null
    })
    .filter(Boolean) as MenuEntry[]
})

const active = computed(() => route.path)
const isFlushContent = computed(() => route.path.startsWith('/admin/schedule-assistant'))

const userInitial = computed(() => {
  const name = (auth.displayName || '用户').trim()
  return name.slice(0, 1) || '用'
})

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  manager: '主管',
  leader: '组长',
}

const roleLabel = computed(
  () => profile.role_name || ROLE_LABEL[auth.role] || auth.role || '账号',
)

function isGroupActive(entry: MenuEntry) {
  return entry.type === 'group' && entry.items.some((i) => i.path === active.value)
}

function onFlyoutVisible(key: string, visible: boolean) {
  if (visible) {
    flyoutKey.value = key
    return
  }
  if (flyoutKey.value === key) flyoutKey.value = null
}

function closeFlyout() {
  flyoutKey.value = null
}

function syncPointerMode() {
  finePointer.value = !!pointerMq?.matches
  closeFlyout()
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(STORAGE_COLLAPSE, collapsed.value ? '1' : '0')
  closeFlyout()
}

function initCollapsed() {
  const saved = localStorage.getItem(STORAGE_COLLAPSE)
  if (saved === '1' || saved === '0') {
    collapsed.value = saved === '1'
    return
  }
  collapsed.value = window.innerWidth < 1100
}

function resetPwdForm() {
  Object.assign(pwdForm, { old_password: '', new_password: '', confirm: '' })
}

async function openProfile() {
  resetPwdForm()
  profileVisible.value = true
  try {
    const res: any = await http.get('/auth/me')
    Object.assign(profile, {
      username: res.data?.username || '',
      display_name: res.data?.display_name || auth.displayName || '',
      role: res.data?.role || auth.role || '',
      role_name: res.data?.role_name || ROLE_LABEL[res.data?.role] || res.data?.role || '',
      tenant_name: res.data?.tenant_name || '',
    })
    if (res.data?.display_name) auth.displayName = res.data.display_name
    if (res.data?.role) auth.role = res.data.role
  } catch {
    Object.assign(profile, {
      username: '',
      display_name: auth.displayName || '',
      role: auth.role || '',
      role_name: ROLE_LABEL[auth.role] || auth.role || '',
      tenant_name: '',
    })
  }
}

async function savePassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写原密码和新密码')
    return
  }
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdSaving.value = true
  try {
    await http.post('/auth/change-password', {
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
    })
    ElMessage.success('密码已修改')
    resetPwdForm()
  } finally {
    pwdSaving.value = false
  }
}

function onUserCommand(cmd: string) {
  if (cmd === 'profile') {
    void openProfile()
    return
  }
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}

watch(
  () => route.path,
  () => {
    closeFlyout()
  },
)

onMounted(async () => {
  initCollapsed()
  pointerMq = window.matchMedia('(hover: hover) and (pointer: fine)')
  syncPointerMode()
  pointerMq.addEventListener('change', syncPointerMode)

  const me = await auth.refreshPermissions()
  if (me) {
    profile.role_name = me.role_name || ROLE_LABEL[me.role] || me.role || ''
    profile.username = me.username || ''
    profile.tenant_name = me.tenant_name || ''
    profile.display_name = me.display_name || auth.displayName || ''
    profile.role = me.role || auth.role || ''
  }
})

onUnmounted(() => {
  pointerMq?.removeEventListener('change', syncPointerMode)
  pointerMq = null
})
</script>
