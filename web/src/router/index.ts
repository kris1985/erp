import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useOpsAuthStore } from '@/stores/opsAuth'
import { firstAdminLocation, sameAdminLocation } from '@/router/adminHome'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // Legacy mobile H5 compatibility routes. New mobile features belong in /uniapp;
    // migrate and redirect these one by one only after the UniApp page reaches parity.
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    { path: '/admin/login', component: () => import('@/views/AdminLoginView.vue') },
    { path: '/ops/login', component: () => import('@/views/OpsLoginView.vue') },
    {
      path: '/ops',
      component: () => import('@/views/ops/OpsTenantsView.vue'),
      meta: { ops: true },
    },
    {
      path: '/po/:token',
      component: () => import('@/views/PublicPoView.vue'),
    },
    {
      path: '/po-receive/:id',
      component: () => import('@/views/PoReceiveView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/scan/:code',
      component: () => import('@/views/ScanReportView.vue'),
    },
    {
      path: '/trace/:code',
      component: () => import('@/views/TraceUnitView.vue'),
    },
    {
      path: '/carton-report/:code',
      component: () => import('@/views/CartonReportView.vue'),
      meta: { auth: true },
    },
    {
      path: '/trace-print/:code',
      component: () => import('@/views/TracePrintView.vue'),
    },
    {
      path: '/stitch-board/:code',
      component: () => import('@/views/StitchBoardView.vue'),
      meta: { auth: true },
    },
    {
      path: '/trace-report',
      component: () => import('@/views/TraceReportView.vue'),
      meta: { auth: true, workerOnly: true },
    },
    {
      path: '/flow-card/:id',
      component: () => import('@/views/FlowCardScanView.vue'),
      meta: { auth: true },
    },
    {
      path: '/pickup-sign/:token',
      component: () => import('@/views/PickupSignView.vue'),
      meta: { auth: true },
    },
    {
      path: '/prep-sign/:token',
      component: () => import('@/views/PrepSignView.vue'),
      meta: { auth: true },
    },
    {
      path: '/line-report',
      component: () => import('@/views/LineReportView.vue'),
      meta: { auth: true },
    },
    {
      path: '/change-password',
      component: () => import('@/views/ChangePasswordView.vue'),
      meta: { auth: true, workerOnly: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { auth: true },
      children: [
        // 站点首页默认进 PC 后台；未登录由守卫送到 /admin/login。手机端请走 /login 或 UniApp
        { path: '', redirect: '/admin' },
        { path: 'home', name: 'home', component: () => import('@/views/HomeView.vue') },
        { path: 'workbench', component: () => import('@/views/MobileWorkbenchView.vue'), meta: { staffOnly: true } },
        { path: 'boss', redirect: '/home' },
        { path: 'workers', component: () => import('@/views/WorkersView.vue'), meta: { staffOnly: true } },
        { path: 'orders', component: () => import('@/views/OrdersView.vue'), meta: { staffOnly: true } },
        {
          path: 'work-logs',
          component: () => import('@/views/StaffWorkLogsView.vue'),
          meta: { staffOnly: true },
        },
        { path: 'my-salary', component: () => import('@/views/MySalaryView.vue') },
        { path: 'my-work-logs', component: () => import('@/views/MyWorkLogsView.vue') },
        { path: 'my-team', component: () => import('@/views/MyTeamView.vue'), meta: { workerOnly: true } },
        { path: 'mine', component: () => import('@/views/ProfileView.vue') },
      ],
    },
    {
      path: '/admin/purchase-orders/print/:id',
      component: () => import('@/views/admin/PurchaseOrderPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/shipments/print/:id',
      component: () => import('@/views/admin/ShipmentPrintView.vue'),
      meta: { auth: true, staffOnly: true, permissions: ['btn.fg_stocks.print'] },
    },
    {
      path: '/admin/sample-remakes/print/:id',
      component: () => import('@/views/admin/SampleRemakePrintView.vue'),
      meta: { auth: true, staffOnly: true, permissions: ['menu.sample_remakes'] },
    },
    {
      path: '/admin/account-statements/print/:id',
      component: () => import('@/views/admin/AccountStatementPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/subcontract-orders/print/:id',
      component: () => import('@/views/admin/SubcontractOrderPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/subcontract-orders/receipt-print/:id',
      component: () => import('@/views/admin/SubcontractReceiptPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/orders/print/:id',
      component: () => import('@/views/admin/OrderFlowCardPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/executions/print/:id',
      component: () => import('@/views/admin/OrderFlowCardPrintView.vue'),
      meta: { auth: true, staffOnly: true, executionHeader: true },
    },
    {
      path: '/admin/merge-batches/print/:id',
      component: () => import('@/views/admin/MergeBatchFlowCardPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/packing/print/:id',
      component: () => import('@/views/admin/CartonMarkPrintView.vue'),
      meta: { auth: true, staffOnly: true },
    },
    {
      path: '/admin/supplier-products/print',
      component: () => import('@/views/admin/MaterialLabelPrintView.vue'),
      meta: { auth: true, staffOnly: true, permissions: ['menu.supplier_products'] },
    },
    {
      path: '/admin/material-preps/qrs/print',
      component: () => import('@/views/admin/PrepQrPrintView.vue'),
      meta: { auth: true, staffOnly: true, permissions: ['menu.masters'] },
    },
    {
      path: '/material',
      component: () => import('@/views/MaterialLabelView.vue'),
      meta: { auth: true, staffOnly: true, permissions: ['menu.supplier_products'] },
    },
    {
      path: '/board',
      component: () => import('@/views/WorkshopBoardView.vue'),
      meta: { auth: true, staffOnly: true, board: true },
    },
    {
      path: '/admin',
      component: () => import('@/layouts/AdminLayout.vue'),
      meta: { auth: true, staffOnly: true },
      children: [
        { path: '', component: () => import('@/views/admin/DashboardView.vue') },
        { path: 'sales-orders', component: () => import('@/views/admin/SalesOrdersAdminView.vue'), meta: { permissions: ['menu.sales_orders'] } },
        { path: 'executions', component: () => import('@/views/admin/ExecutionsAdminView.vue'), meta: { permissions: ['menu.orders', 'menu.sales_orders'] } },
        {
          path: 'cut-material-usage',
          component: () => import('@/views/admin/CutMaterialUsageAdminView.vue'),
          meta: { permissions: ['menu.cut_material_usage'] },
        },
        {
          path: 'orders',
          component: () => import('@/views/admin/OrdersAdminView.vue'),
          meta: { permissions: ['menu.orders'] },
          beforeEnter: (to) => {
            // 干掉生产单 K1：默认跳执行单；运维排障用 ?legacy=1
            if (String(to.query.legacy || '') === '1') return true
            return {
              path: '/admin/executions',
              query: to.query.id || to.query.open
                ? { shop_order_id: String(to.query.id || to.query.open) }
                : {},
            }
          },
        },
        { path: 'schedule', component: () => import('@/views/admin/ScheduleAdminView.vue'), meta: { permissions: ['menu.schedule'] } },
        {
          path: 'schedule-assistant',
          component: () => import('@/views/admin/ScheduleAssistantView.vue'),
          meta: { permissions: ['menu.schedule'] },
        },
        { path: 'material-shortages', redirect: { path: '/admin/purchase', query: { tab: 'buy' } } },
        {
          path: 'subcontract-out',
          component: () => import('@/views/admin/SubcontractOutAdminView.vue'),
          meta: { permissions: ['menu.subcontract_out'] },
        },
        {
          path: 'purchase',
          component: () => import('@/views/admin/PurchaseAdminView.vue'),
          meta: { permissions: ['menu.purchase_orders', 'menu.material_shortages'] },
        },
        { path: 'purchase-orders', redirect: { path: '/admin/purchase', query: { tab: 'orders' } } },
        { path: 'shipments', redirect: { path: '/admin/fg-stocks', query: { tab: 'shipped' } } },
        { path: 'shared-materials', redirect: { path: '/admin/inventory', query: { tab: 'pool' } } },
        {
          path: 'inventory',
          component: () => import('@/views/admin/InventoryAdminView.vue'),
          meta: { permissions: ['menu.shared_materials', 'menu.tooling'] },
        },
        {
          path: 'fg-stocks',
          component: () => import('@/views/admin/FgStocksAdminView.vue'),
          meta: { permissions: ['menu.fg_stocks'] },
        },
        {
          path: 'settlements',
          component: () => import('@/views/admin/SettlementHubAdminView.vue'),
          meta: { permissions: ['menu.receivables', 'menu.payments', 'menu.payables', 'menu.supplier_payments', 'menu.subcontract_settlements'] },
        },
        {
          path: 'receivables',
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'customers' },
          }),
        },
        {
          path: 'account-statements',
          redirect: (to) => {
            const { section: _section, ...query } = to.query
            return { path: '/admin/settlements', query }
          },
        },
        {
          path: 'payments',
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'customers' },
          }),
        },
        {
          path: 'payables',
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'suppliers' },
          }),
        },
        {
          path: 'supplier-payments',
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'subcontractors' },
          }),
        },
        { path: 'profit', component: () => import('@/views/admin/ProfitAdminView.vue'), meta: { permissions: ['menu.profit', 'menu.order_profit'] } },
        {
          path: 'business-report',
          component: () => import('@/views/admin/BusinessReportAdminView.vue'),
          meta: { permissions: ['menu.business_report', 'menu.profit'] },
        },
        { path: 'work-logs', component: () => import('@/views/admin/WorkLogsAdminView.vue'), meta: { permissions: ['menu.work_logs'] } },
        {
          path: 'production-efficiency',
          component: () => import('@/views/admin/ProductionEfficiencyAdminView.vue'),
          meta: { permissions: ['menu.production_efficiency'] },
        },
        { path: 'salary', component: () => import('@/views/admin/SalaryAdminView.vue'), meta: { permissions: ['menu.salary'] } },
        {
          path: 'adjustments',
          component: () => import('@/views/admin/AdjustmentsAdminView.vue'),
          meta: { permissions: ['menu.adjustments'] },
        },
        {
          path: 'advances',
          component: () => import('@/views/admin/AdvancesAdminView.vue'),
          meta: { permissions: ['menu.advances'] },
        },
        {
          path: 'daily-expenses',
          component: () => import('@/views/admin/DailyExpensesAdminView.vue'),
          meta: { permissions: ['menu.daily_expenses'] },
        },
        {
          path: 'ledger',
          component: () => import('@/views/admin/LedgerAdminView.vue'),
          meta: { permissions: ['menu.ledger'] },
        },
        { path: 'employees', component: () => import('@/views/admin/EmployeesAdminView.vue'), meta: { permissions: ['menu.workers', 'menu.teams', 'menu.users'] } },
        { path: 'workers', redirect: { path: '/admin/employees' } },
        // 组织架构已并入「员工与部门」一页，旧链接兼容重定向
        { path: 'teams', redirect: { path: '/admin/employees' } },
        {
          path: 'attendance-rules',
          component: () => import('@/views/admin/AttendanceRulesAdminView.vue'),
          meta: { permissions: ['menu.attendance_rules'] },
        },
        {
          path: 'leaves',
          component: () => import('@/views/admin/LeavesAdminView.vue'),
          meta: { permissions: ['menu.leaves'] },
        },
        {
          path: 'org-setup',
          component: () => import('@/views/setup/OrgSetupWizardView.vue'),
          meta: { staffOnly: true },
        },
        {
          path: 'partners',
          component: () => import('@/views/admin/PartnersHubAdminView.vue'),
          meta: { permissions: ['menu.customers', 'menu.suppliers', 'menu.subcontractors', 'menu.brands'] },
        },
        {
          path: 'customers',
          redirect: { path: '/admin/partners', query: { tab: 'customers' } },
        },
        {
          path: 'suppliers',
          redirect: { path: '/admin/partners', query: { tab: 'suppliers' } },
        },
        {
          path: 'supplier-products',
          component: () => import('@/views/admin/SupplierProductsAdminView.vue'),
          meta: { permissions: ['menu.supplier_products'] },
        },
        {
          path: 'own-products',
          component: () => import('@/views/admin/OwnProductsAdminView.vue'),
          meta: { permissions: ['menu.own_products'] },
        },
        {
          path: 'sample-remakes',
          component: () => import('@/views/admin/SampleRemakesAdminView.vue'),
          meta: { permissions: ['menu.sample_remakes'] },
        },
        { path: 'masters', component: () => import('@/views/admin/MastersAdminView.vue'), meta: { permissions: ['menu.masters', 'menu.process_staff'] } },
        { path: 'stations', component: () => import('@/views/admin/StationsAdminView.vue'), meta: { permissions: ['menu.stations'] } },
        { path: 'defects', component: () => import('@/views/admin/DefectsAdminView.vue'), meta: { permissions: ['menu.defects'] } },
        { path: 'after-sales', component: () => import('@/views/admin/AfterSalesAdminView.vue'), meta: { permissions: ['menu.after_sales', 'menu.defects', 'menu.sales_orders'] } },
        { path: 'defects/:id', redirect: '/admin/defects' },
        { path: 'users', redirect: { path: '/admin/employees' } },
        {
          path: 'roles',
          component: () => import('@/views/admin/RolesAdminView.vue'),
          meta: { permissions: ['menu.roles'] },
        },
        {
          path: 'permissions',
          redirect: { path: '/admin/roles', query: { tab: 'matrix' } },
        },
        {
          path: 'inventory-settings',
          component: () => import('@/views/admin/InventorySettingsAdminView.vue'),
          meta: { permissions: ['menu.inventory_settings'] },
        },
        {
          path: 'workshop-settings',
          component: () => import('@/views/admin/WorkshopSettingsAdminView.vue'),
          meta: { permissions: ['menu.workshop_settings'] },
        },
        {
          path: 'im-alerts',
          component: () => import('@/views/admin/ImAlertsAdminView.vue'),
          meta: { permissions: ['menu.im_alerts'] },
        },
        {
          path: 'mcp-keys',
          component: () => import('@/views/admin/McpKeysAdminView.vue'),
          meta: { permissions: ['menu.mcp_keys'] },
        },
        {
          path: 'stock-issues',
          redirect: (to) => {
            const dir = String(to.query.direction || to.query.doc_type || '')
            const tab =
              dir === 'in' || dir === 'return_mat'
                ? 'in'
                : dir === 'out' || dir === 'issue'
                  ? 'out'
                  : 'out'
            return { path: '/admin/inventory', query: { ...to.query, tab } }
          },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  if (to.path.startsWith('/ops')) {
    const ops = useOpsAuthStore()
    if (to.path === '/ops/login') {
      if (ops.token) return '/ops'
      return
    }
    if (!ops.token) {
      return { path: '/ops/login', query: { redirect: to.fullPath } }
    }
    return
  }
  const auth = useAuthStore()
  const isAdminLogin = to.path === '/admin/login'
  const isH5Login = to.path === '/login'
  // 未登录：站点首页与后台进 PC 登录；其余 H5 页进手机端登录
  if (to.meta.auth && !auth.token) {
    const useAdminLogin = to.path.startsWith('/admin') || to.path === '/'
    return {
      path: useAdminLogin ? '/admin/login' : '/login',
      query: { redirect: to.path === '/' ? '/admin' : to.fullPath },
    }
  }
  if ((isAdminLogin || isH5Login) && auth.token) {
    const redirect = typeof to.query.redirect === 'string' ? to.query.redirect : ''
    if (isAdminLogin) {
      // 后台入口：纯员工送回手机端；有后台角色只跟随后台路径，避免被带进 h5 页
      if (auth.isPureStaff) return '/home'
      return redirect.startsWith('/admin') ? redirect : '/admin'
    }
    // 手机端入口：跟随原目标；无目标时按角色落点
    if (redirect) return redirect
    if (auth.isPureStaff) {
      return auth.mustChangePassword ? '/change-password' : '/home'
    }
    return '/workbench'
  }
  if (
    auth.token &&
    auth.isPureStaff &&
    auth.mustChangePassword &&
    to.path !== '/change-password' &&
    !to.path.startsWith('/po/') &&
    !to.path.startsWith('/pickup-sign/') &&
    !to.path.startsWith('/prep-sign/')
  ) {
    return '/change-password'
  }
  if (to.meta.staffOnly && auth.isPureStaff) return '/home'
  if (to.matched.some((r) => r.meta.adminOnly) && !auth.isAdmin()) {
    return '/admin'
  }
  const permissions = to.matched
    .flatMap((r) => (Array.isArray(r.meta.permissions) ? r.meta.permissions : []))
    .filter((code): code is string => typeof code === 'string')
  const cap = to.matched.map((r) => r.meta.capability).find(Boolean) as string | undefined
  const needsAccess = (permissions.length || cap || to.path === '/admin') && auth.token && !auth.isAdmin()
  // 非管理员的权限存在内存里。刷新瞬间是空的，不能据此把人送去工作台。
  if (needsAccess) {
    await auth.ensurePermissions()
  }
  const fallbackHome = () => {
    const next = firstAdminLocation(auth)
    if (!next || sameAdminLocation(to.path, to.query, next)) return false
    return next
  }
  if (to.path === '/admin' && auth.token && !auth.isAdmin() && !auth.hasPermission('menu.board')) {
    if (!auth.permissionsReady && !auth.permissions.length) return
    const next = firstAdminLocation(auth)
    if (!next || sameAdminLocation(to.path, to.query, next)) return
    return next
  }
  if (permissions.length && !permissions.some((code) => auth.hasPermission(code))) {
    if (!auth.permissionsReady && !auth.permissions.length) return
    return fallbackHome()
  }
  if (cap && !auth.hasCapability(cap)) {
    if (!auth.permissionsReady) return
    return fallbackHome()
  }
})

export default router
