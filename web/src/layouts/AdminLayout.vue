<template>
  <div
    class="admin-app"
    :class="{ 'is-aside-collapsed': collapsed, 'is-aside-expanding': asideExpanding }"
  >
    <div class="admin-layout">
      <aside ref="asideRef" class="admin-aside" @transitionend="onAsideTransitionEnd">
        <div class="admin-brand">
          <button
            type="button"
            class="admin-collapse-btn"
            :title="collapsed ? '展开菜单' : '收起菜单'"
            @click="toggleCollapsed"
          >
            {{ collapsed ? '»' : '«' }}
          </button>
          <span class="admin-brand-text">铁玉兰管家</span>
        </div>
        <nav class="admin-nav" aria-label="后台导航">
          <template v-for="entry in menuEntries" :key="entry.key">
            <el-tooltip
              v-if="entry.type === 'item'"
              :content="entry.label"
              placement="right"
              :disabled="!collapsed"
              :show-after="200"
              :hide-after="0"
            >
              <RouterLink
                :to="entry.path"
                class="admin-nav-item"
                :class="{ 'is-active': active === entry.path }"
              >
                <span class="admin-nav-row">
                  <span class="admin-nav-icon"><el-icon><component :is="entry.icon" /></el-icon></span>
                  <span class="admin-nav-label">{{ entry.label }}</span>
                </span>
              </RouterLink>
            </el-tooltip>
            <el-tooltip
              v-else
              :content="entry.label"
              placement="right"
              :disabled="!collapsed"
              :show-after="200"
              :hide-after="0"
            >
              <RouterLink
                :to="groupTarget(entry)"
                class="admin-nav-item"
                :class="{ 'is-active': isGroupActive(entry) }"
              >
                <span class="admin-nav-row">
                  <span class="admin-nav-icon"><el-icon><component :is="entry.icon" /></el-icon></span>
                  <span class="admin-nav-label">{{ entry.label }}</span>
                </span>
              </RouterLink>
            </el-tooltip>
          </template>
        </nav>
        <div class="admin-aside-user">
          <el-dropdown trigger="click" placement="top-start" @command="onUserCommand">
            <button type="button" class="admin-user-trigger" :title="auth.displayName || '用户'">
              <span class="admin-user-avatar">{{ userInitial }}</span>
              <span class="admin-user-meta">
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
      <div class="admin-main" :class="{ 'has-content-head': contentHead != null }">
        <header v-if="contentHead" class="admin-content-head">
          <nav
            v-if="contentHead.kind === 'tabs'"
            class="admin-content-tabs"
            aria-label="二级菜单"
          >
            <RouterLink
              v-for="item in contentHead.items"
              :key="leafKey(item)"
              v-slot="{ href, navigate }"
              custom
              :to="leafTo(item)"
            >
              <a
                :href="href"
                class="admin-content-tab"
                :class="{ 'is-active': isLeafActive(item) }"
                :aria-current="isLeafActive(item) ? 'page' : undefined"
                @click="navigate"
              >
                {{ item.label }}
              </a>
            </RouterLink>
          </nav>
          <h1 v-else class="admin-content-title">{{ contentHead.label }}</h1>
        </header>
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Box,
  Calendar,
  ChatDotRound,
  Clock,
  DataAnalysis,
  Document,
  Goods,
  Grid,
  Key,
  List,
  Money,
  Notebook,
  Odometer,
  OfficeBuilding,
  Setting,
  ShoppingCart,
  Stamp,
  TrendCharts,
  User,
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
  /** 与 path 一起标识子菜单，例如采购的待买 / 采购单 */
  query?: Record<string, string>
  /** 租户库存能力；缺省不校验 */
  cap?: string
  /** 任一权限即可显示（用于合并菜单） */
  orPerm?: string
  orCap?: string
  /** 任一权限即可显示（用于跨多个旧权限的统一入口） */
  anyPerms?: string[]
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
      anyPerms?: string[]
    }
  | { type: 'group'; key: string; label: string; icon: any; items: MenuLeaf[] }

const STORAGE_COLLAPSE = 'ws_admin_aside_collapsed'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const collapsed = ref(false)
/** 展开动画中：用同色底板盖住菜单与内容之间的空隙 */
const asideExpanding = ref(false)
const asideRef = ref<HTMLElement | null>(null)
let asideMotion = false
let asideEndTimer: ReturnType<typeof setTimeout> | null = null
let pinnedPage: HTMLElement | null = null
let pinnedSnapshot: Record<string, string> | null = null
const profileVisible = ref(false)
const pwdSaving = ref(false)
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

function canMenuLeaf(leaf: Pick<MenuLeaf, 'perm' | 'cap' | 'orPerm' | 'orCap' | 'anyPerms'>) {
  if (canMenu(leaf.perm, leaf.cap)) return true
  if (leaf.orPerm && canMenu(leaf.orPerm, leaf.orCap)) return true
  if (leaf.anyPerms?.some((perm) => auth.hasPermission(perm))) return true
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
      key: 'business-report',
      path: '/admin/business-report',
      label: '经营报告',
      perm: 'menu.business_report',
      icon: TrendCharts,
      orPerm: 'menu.profit',
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
    // 遗留内部单：默认菜单隐藏；需要时 /admin/orders?legacy=1
    {
      type: 'group',
      key: 'g-purchase',
      label: '采购',
      icon: ShoppingCart,
      items: [
        {
          path: '/admin/purchase',
          label: '待买',
          perm: 'menu.material_shortages',
          icon: ShoppingCart,
          query: { tab: 'buy' },
        },
        {
          path: '/admin/purchase',
          label: '采购单',
          perm: 'menu.purchase_orders',
          icon: Document,
          query: { tab: 'orders' },
        },
      ],
    },
    {
      type: 'group',
      key: 'g-warehouse',
      label: '仓库',
      icon: Box,
      items: [
        {
          path: '/admin/inventory',
          label: '库存池',
          perm: 'menu.shared_materials',
          icon: Box,
          cap: 'shared_pool',
          query: { tab: 'pool' },
        },
        {
          path: '/admin/inventory',
          label: '出库单',
          perm: 'menu.stock_issues',
          icon: Box,
          cap: 'stock_docs',
          query: { tab: 'out' },
        },
        {
          path: '/admin/inventory',
          label: '入库单',
          perm: 'menu.stock_issues',
          icon: Box,
          cap: 'stock_docs',
          query: { tab: 'in' },
        },
        { path: '/admin/customer-supply', label: '客供收货', perm: 'menu.customer_supply', icon: Goods },
        { path: '/admin/fg-stocks', label: '成品仓', perm: 'menu.fg_stocks', icon: Goods },
      ],
    },
    {
      type: 'group',
      key: 'g-production',
      label: '生产',
      icon: Calendar,
      items: [
        {
          path: '/admin/executions',
          label: '生产进度',
          perm: 'menu.orders',
          icon: List,
          orPerm: 'menu.sales_orders',
        },
        { path: '/admin/work-logs', label: '考勤&报工', perm: 'menu.work_logs', icon: Notebook },
        {
          path: '/admin/production-efficiency',
          label: '生产效率',
          perm: 'menu.production_efficiency',
          icon: DataAnalysis,
        },
        { path: '/admin/defects', label: '报废记录', perm: 'menu.defects', icon: Warning },
        {
          path: '/admin/subcontract-out',
          label: '外发记录',
          perm: 'menu.subcontract_out',
          icon: Van,
        },
      ],
    },
    {
      type: 'group',
      key: 'g-finance',
      label: '财务',
      icon: Money,
      items: [
        { path: '/admin/shipments', label: '出货', perm: 'menu.shipments', icon: Van },
        {
          path: '/admin/settlements',
          label: '客户对账',
          perm: 'menu.receivables',
          icon: List,
          anyPerms: ['menu.receivables', 'menu.payments'],
          query: { section: 'customers' },
        },
        {
          path: '/admin/settlements',
          label: '供应商对账',
          perm: 'menu.payables',
          icon: List,
          query: { section: 'suppliers' },
        },
        {
          path: '/admin/settlements',
          label: '外加工厂对账',
          perm: 'menu.subcontract_out',
          icon: List,
          anyPerms: ['menu.subcontract_out', 'menu.supplier_payments', 'menu.payables'],
          query: { section: 'subcontractors' },
        },
        {
          path: '/admin/profit',
          label: '订单利润',
          perm: 'menu.profit',
          icon: DataAnalysis,
          query: { tab: 'orders' },
        },
        {
          path: '/admin/profit',
          label: '成本分析',
          perm: 'menu.profit',
          icon: DataAnalysis,
          query: { tab: 'cost' },
        },
        { path: '/admin/salary', label: '工资', perm: 'menu.salary', icon: Money },
        { path: '/admin/adjustments', label: '奖惩', perm: 'menu.adjustments', icon: Money },
        { path: '/admin/advances', label: '预支', perm: 'menu.advances', icon: Money },
        {
          path: '/admin/daily-expenses',
          label: '日常开支',
          perm: 'menu.daily_expenses',
          icon: Money,
        },
        { path: '/admin/ledger', label: '总账', perm: 'menu.ledger', icon: Money },
      ],
    },
    {
      type: 'group',
      key: 'g-hr',
      label: '人事管理',
      icon: User,
      items: [
        {
          path: '/admin/employees',
          label: '员工与部门',
          perm: 'menu.workers',
          icon: User,
          orPerm: 'menu.teams',
          anyPerms: ['menu.users'],
        },
        {
          path: '/admin/attendance-rules',
          label: '考勤规则',
          perm: 'menu.attendance_rules',
          icon: Clock,
        },
      ],
    },
    {
      type: 'item',
      key: 'after-sales',
      path: '/admin/after-sales',
      label: '售后服务',
      perm: 'menu.after_sales',
      icon: ChatDotRound,
      anyPerms: ['menu.defects', 'menu.sales_orders'],
    },
    {
      type: 'group',
      key: 'g-partners',
      label: '合作商',
      icon: OfficeBuilding,
      items: [
        {
          path: '/admin/partners',
          label: '客户',
          perm: 'menu.customers',
          icon: OfficeBuilding,
          query: { tab: 'customers' },
        },
        {
          path: '/admin/partners',
          label: '供应商',
          perm: 'menu.suppliers',
          icon: OfficeBuilding,
          query: { tab: 'suppliers' },
        },
        {
          path: '/admin/partners',
          label: '外加工厂',
          perm: 'menu.subcontract_out',
          icon: OfficeBuilding,
          query: { tab: 'subcontractors' },
        },
      ],
    },
    {
      type: 'item',
      key: 'schedule-assistant',
      path: '/admin/schedule-assistant',
      label: 'AI分析',
      perm: 'menu.schedule',
      icon: ChatDotRound,
    },
    {
      type: 'group',
      key: 'g-masters',
      label: '基础数据',
      icon: Notebook,
      items: [
        { path: '/admin/masters', label: '颜色', perm: 'menu.masters', icon: Notebook, query: { tab: 'colors' } },
        { path: '/admin/masters', label: '尺码', perm: 'menu.masters', icon: Notebook, query: { tab: 'sizes' } },
        { path: '/admin/masters', label: '用量码表', perm: 'menu.masters', icon: Notebook, query: { tab: 'size-usage' } },
        { path: '/admin/masters', label: '物料分类', perm: 'menu.masters', icon: Notebook, query: { tab: 'categories' } },
        { path: '/admin/masters', label: '计价单位', perm: 'menu.masters', icon: Notebook, query: { tab: 'units' } },
        { path: '/admin/masters', label: '工种', perm: 'menu.masters', icon: Notebook, query: { tab: 'positions' } },
        { path: '/admin/masters', label: '工序段管理', perm: 'menu.masters', icon: Notebook, query: { tab: 'segments' } },
        { path: '/admin/masters', label: '工序', perm: 'menu.masters', icon: Notebook, query: { tab: 'processes' } },
        { path: '/admin/masters', label: '部件', perm: 'menu.masters', icon: Notebook, query: { tab: 'parts' } },
        { path: '/admin/masters', label: '其它成本', perm: 'menu.masters', icon: Notebook, query: { tab: 'otherCosts' } },
        { path: '/admin/masters', label: '框码管理', perm: 'menu.masters', icon: Notebook, query: { tab: 'baskets' } },
      ],
    },
    {
      type: 'group',
      key: 'g-sys',
      label: '系统管理',
      icon: Setting,
      items: [
        { path: '/admin/roles', label: '角色', perm: 'menu.roles', icon: Stamp },
        { path: '/admin/stations', label: '工位码', perm: 'menu.stations', icon: Grid },
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
        {
          path: '/admin/im-alerts',
          label: 'IM 预警推送',
          perm: 'menu.im_alerts',
          icon: ChatDotRound,
        },
        {
          path: '/admin/mcp-keys',
          label: 'MCP 密钥',
          perm: 'menu.mcp_keys',
          icon: Key,
        },
      ],
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

const contentHead = computed(() => {
  const path = active.value
  for (const entry of menuEntries.value) {
    if (entry.type === 'item' && entry.path === path) {
      return { kind: 'title' as const, label: entry.label }
    }
    if (entry.type === 'group' && entry.items.some((item) => item.path === path)) {
      return { kind: 'tabs' as const, items: entry.items }
    }
  }
  return null
})

const userInitial = computed(() => {
  const name = (auth.displayName || '用户').trim()
  return name.slice(0, 1) || '用'
})

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  manager: '主管',
  worker: '员工',
}

const roleLabel = computed(
  () => profile.role_name || ROLE_LABEL[auth.role] || auth.role || '账号',
)

function leafKey(item: MenuLeaf) {
  const q = item.query ? Object.entries(item.query).map(([k, v]) => `${k}=${v}`).join('&') : ''
  return q ? `${item.path}?${q}` : item.path
}

function leafTo(item: MenuLeaf) {
  return item.query ? { path: item.path, query: item.query } : item.path
}

function isLeafActive(item: MenuLeaf) {
  if (item.path !== route.path) return false
  if (!item.query) return true
  return Object.entries(item.query).every(([key, value]) => String(route.query[key] ?? '') === value)
}

function isGroupActive(entry: MenuEntry) {
  return entry.type === 'group' && entry.items.some((item) => item.path === active.value)
}

function groupTarget(entry: Extract<MenuEntry, { type: 'group' }>) {
  const current = entry.items.find((item) => isLeafActive(item))
  if (current) return leafTo(current)
  if (entry.items.some((item) => item.path === route.path)) {
    return { path: route.path, query: route.query }
  }
  const first = entry.items[0]
  return first ? leafTo(first) : '/admin'
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function asideWidths() {
  const app = document.querySelector('.admin-app')
  const cs = app ? getComputedStyle(app) : null
  const expanded = parseFloat(cs?.getPropertyValue('--aside-expanded') || '') || 180
  const collapsedW = parseFloat(cs?.getPropertyValue('--aside-collapsed') || '') || 64
  return { expanded, collapsedW }
}

function pageEl(): HTMLElement | null {
  return document.querySelector('.admin-content')?.firstElementChild as HTMLElement | null
}

function releasePagePin() {
  const page = pinnedPage
  const prev = pinnedSnapshot
  pinnedPage = null
  pinnedSnapshot = null
  if (!page || !prev) return
  for (const [prop, value] of Object.entries(prev)) {
    if (value) page.style.setProperty(prop, value)
    else page.style.removeProperty(prop)
  }
}

/**
 * 表格按最终宽度一次排好，整页钉在视口右侧。
 * 侧栏宽度动画只改变裁切窗口，列宽和右侧操作列不再跟着重排。
 */
function startAsideMotion(nextCollapsed: boolean) {
  releasePagePin()
  const page = pageEl()
  const aside = asideRef.value
  if (!page || !aside) return
  const { expanded, collapsedW } = asideWidths()
  const asideNow = aside.offsetWidth
  const asideEnd = nextCollapsed ? collapsedW : expanded
  const delta = asideNow - asideEnd
  if (!delta) return
  const dest = page.offsetWidth + delta
  if (dest < 32) return
  pinnedSnapshot = {
    width: page.style.getPropertyValue('width'),
    'min-width': page.style.getPropertyValue('min-width'),
    'max-width': page.style.getPropertyValue('max-width'),
    flex: page.style.getPropertyValue('flex'),
    position: page.style.getPropertyValue('position'),
    left: page.style.getPropertyValue('left'),
    background: page.style.getPropertyValue('background'),
  }
  const px = `${dest}px`
  page.style.setProperty('width', px, 'important')
  page.style.setProperty('min-width', px, 'important')
  page.style.setProperty('max-width', px, 'important')
  page.style.setProperty('flex', '0 0 auto', 'important')
  page.style.setProperty('position', 'relative', 'important')
  page.style.setProperty('left', `calc(100% - ${px})`, 'important')
  page.style.setProperty('background', '#f3f5f8', 'important')
  pinnedPage = page
  void page.offsetWidth
  asideMotion = true
  asideExpanding.value = !nextCollapsed
  window.dispatchEvent(new CustomEvent('admin-aside-prepare'))
}

function endAsideMotion() {
  if (asideEndTimer != null) {
    clearTimeout(asideEndTimer)
    asideEndTimer = null
  }
  if (!asideMotion && !pinnedPage) return
  asideMotion = false
  asideExpanding.value = false
  releasePagePin()
  window.dispatchEvent(new CustomEvent('admin-aside-finish'))
}

function toggleCollapsed() {
  const next = !collapsed.value
  startAsideMotion(next)
  collapsed.value = next
  localStorage.setItem(STORAGE_COLLAPSE, next ? '1' : '0')
  if (prefersReducedMotion()) {
    nextTick(() => endAsideMotion())
    return
  }
  if (asideEndTimer != null) clearTimeout(asideEndTimer)
  asideEndTimer = setTimeout(() => endAsideMotion(), 320)
}

function onAsideTransitionEnd(ev: TransitionEvent) {
  if (ev.target !== asideRef.value || ev.propertyName !== 'width') return
  endAsideMotion()
}

function initCollapsed() {
  const saved = localStorage.getItem(STORAGE_COLLAPSE)
  if (saved === '1' || saved === '0') {
    collapsed.value = saved === '1'
  } else {
    collapsed.value = window.innerWidth < 1100
  }
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
      display_name: res.data?.display_name || res.data?.name || auth.displayName || '',
      role: res.data?.role || auth.role || '',
      role_name: res.data?.role_name || ROLE_LABEL[res.data?.role] || res.data?.role || '',
      tenant_name: res.data?.tenant_name || '',
    })
    if (res.data?.name) auth.displayName = res.data.name
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
    router.push('/admin/login')
  }
}

onMounted(async () => {
  initCollapsed()

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
  if (asideEndTimer != null) clearTimeout(asideEndTimer)
  releasePagePin()
})
</script>
