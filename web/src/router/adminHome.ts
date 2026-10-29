import type { RouteLocationRaw } from 'vue-router'

type HomeLeaf = {
  path: string
  perm: string
  query?: Record<string, string>
  cap?: string
  orPerm?: string
  orCap?: string
  anyPerms?: string[]
  hidden?: boolean
}

type HomeEntry =
  | HomeLeaf
  | { items: HomeLeaf[] }

type Access = {
  hasPermission: (code: string) => boolean
  hasCapability: (code: string) => boolean
}

/** 与后台侧栏顺序一致。没勾工作台时，默认打开这里的第一个可见菜单。 */
const ADMIN_HOME_MENU: HomeEntry[] = [
  { path: '/admin', perm: 'menu.board' },
  { path: '/admin/business-report', perm: 'menu.business_report', orPerm: 'menu.profit' },
  { path: '/admin/supplier-products', perm: 'menu.supplier_products' },
  {
    items: [
      { path: '/admin/own-products', perm: 'menu.own_products' },
      { path: '/admin/sample-remakes', perm: 'menu.sample_remakes' },
    ],
  },
  { path: '/admin/sales-orders', perm: 'menu.sales_orders' },
  {
    items: [
      { path: '/admin/purchase', perm: 'menu.material_shortages', query: { tab: 'buy' } },
      { path: '/admin/purchase', perm: 'menu.purchase_orders', query: { tab: 'orders' } },
    ],
  },
  {
    items: [
      { path: '/admin/inventory', perm: 'menu.shared_materials', cap: 'shared_pool', query: { tab: 'pool' } },
      { path: '/admin/inventory', perm: 'menu.tooling', cap: 'shared_pool', query: { tab: 'tooling' } },
    ],
  },
  {
    items: [
      { path: '/admin/executions', perm: 'menu.orders', orPerm: 'menu.sales_orders' },
      { path: '/admin/fg-stocks', perm: 'menu.fg_stocks' },
      { path: '/admin/cut-material-usage', perm: 'menu.cut_material_usage' },
      { path: '/admin/work-logs', perm: 'menu.work_logs' },
      { path: '/admin/production-efficiency', perm: 'menu.production_efficiency' },
      { path: '/admin/defects', perm: 'menu.defects' },
      { path: '/admin/subcontract-out', perm: 'menu.subcontract_out' },
    ],
  },
  {
    items: [
      {
        path: '/admin/settlements',
        perm: 'menu.receivables',
        anyPerms: ['menu.receivables', 'menu.payments'],
        query: { section: 'customers' },
      },
      { path: '/admin/settlements', perm: 'menu.payables', query: { section: 'suppliers' } },
      {
        path: '/admin/settlements',
        perm: 'menu.subcontract_settlements',
        query: { section: 'subcontractors' },
      },
      { path: '/admin/salary', perm: 'menu.salary' },
      { path: '/admin/adjustments', perm: 'menu.adjustments' },
      { path: '/admin/advances', perm: 'menu.advances' },
      { path: '/admin/daily-expenses', perm: 'menu.daily_expenses' },
      { path: '/admin/ledger', perm: 'menu.ledger' },
      { path: '/admin/profit', perm: 'menu.profit', query: { tab: 'cost' } },
      { path: '/admin/profit', perm: 'menu.order_profit', query: { tab: 'orders' } },
    ],
  },
  {
    items: [
      { path: '/admin/employees', perm: 'menu.workers', orPerm: 'menu.teams', anyPerms: ['menu.users'] },
      { path: '/admin/masters', perm: 'menu.process_staff', query: { tab: 'processes', view: 'people' } },
      { path: '/admin/attendance-rules', perm: 'menu.attendance_rules' },
      { path: '/admin/leaves', perm: 'menu.leaves' },
    ],
  },
  { path: '/admin/after-sales', perm: 'menu.after_sales', anyPerms: ['menu.defects', 'menu.sales_orders'] },
  {
    items: [
      { path: '/admin/partners', perm: 'menu.customers', query: { tab: 'customers' } },
      { path: '/admin/partners', perm: 'menu.brands', query: { tab: 'brands' } },
      { path: '/admin/partners', perm: 'menu.suppliers', query: { tab: 'suppliers' } },
      { path: '/admin/partners', perm: 'menu.subcontractors', query: { tab: 'subcontractors' } },
    ],
  },
  { path: '/admin/schedule-assistant', perm: 'menu.schedule' },
  {
    items: [
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'colors' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'sizes' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'categories' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'units' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'segments' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'processes' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'otherCosts' } },
      { path: '/admin/masters', perm: 'menu.masters', query: { tab: 'prepQrs' } },
    ],
  },
  { path: '/admin/roles', perm: 'menu.roles' },
]

function canSee(leaf: HomeLeaf, access: Access) {
  if (leaf.hidden) return false
  const allow = (perm: string, cap?: string) => {
    if (cap && !access.hasCapability(cap)) return false
    return access.hasPermission(perm)
  }
  if (allow(leaf.perm, leaf.cap)) return true
  if (leaf.orPerm && allow(leaf.orPerm, leaf.orCap)) return true
  if (leaf.anyPerms?.some((perm) => access.hasPermission(perm))) return true
  return false
}

function leaves(): HomeLeaf[] {
  return ADMIN_HOME_MENU.flatMap((entry) => ('items' in entry ? entry.items : [entry]))
}

export function firstAdminLocation(access: Access): RouteLocationRaw | null {
  const leaf = leaves().find((item) => canSee(item, access))
  if (!leaf) return null
  return leaf.query ? { path: leaf.path, query: leaf.query } : { path: leaf.path }
}

export function sameAdminLocation(
  path: string,
  query: Record<string, unknown>,
  target: RouteLocationRaw,
) {
  if (typeof target === 'string') return path === target && Object.keys(query).length === 0
  if (!('path' in target) || !target.path) return false
  if (target.path !== path) return false
  const expected = target.query || {}
  const keys = new Set([...Object.keys(expected), ...Object.keys(query)])
  for (const key of keys) {
    if (String(query[key] ?? '') !== String(expected[key] ?? '')) return false
  }
  return true
}
