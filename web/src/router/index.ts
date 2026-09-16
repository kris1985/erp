import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // Legacy mobile H5 compatibility routes. New mobile features belong in /uniapp;
    // migrate and redirect these one by one only after the UniApp page reaches parity.
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    { path: '/admin/login', component: () => import('@/views/AdminLoginView.vue') },
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
        { path: '', redirect: '/home' },
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
      meta: { auth: true, staffOnly: true },
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
          path: 'customer-supply',
          component: () => import('@/views/admin/CustomerSupplyAdminView.vue'),
          meta: { permissions: ['menu.customer_supply'] },
        },
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
        {
          path: 'material-iqc',
          component: () => import('@/views/admin/MaterialIqcAdminView.vue'),
          meta: { permissions: ['menu.purchase_orders'] },
        },
        { path: 'shipments', component: () => import('@/views/admin/ShipmentsAdminView.vue'), meta: { permissions: ['menu.shipments'] } },
        { path: 'shared-materials', redirect: { path: '/admin/inventory', query: { tab: 'pool' } } },
        {
          path: 'inventory',
          component: () => import('@/views/admin/InventoryAdminView.vue'),
          meta: { permissions: ['menu.shared_materials', 'menu.stock_issues'] },
        },
        {
          path: 'fg-stocks',
          component: () => import('@/views/admin/FgStocksAdminView.vue'),
          meta: { permissions: ['menu.fg_stocks'] },
        },
        {
          path: 'settlements',
          component: () => import('@/views/admin/SettlementHubAdminView.vue'),
          meta: { permissions: ['menu.receivables', 'menu.payments', 'menu.payables', 'menu.supplier_payments'] },
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
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'statements' },
          }),
        },
        {
          path: 'payments',
          redirect: (to) => ({
            path: '/admin/settlements',
            query: { ...to.query, section: 'cash', flow: 'receipts' },
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
            query: { ...to.query, section: 'cash', flow: 'payments' },
          }),
        },
        { path: 'profit', component: () => import('@/views/admin/ProfitAdminView.vue'), meta: { permissions: ['menu.profit'] } },
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
          path: 'org-setup',
          component: () => import('@/views/setup/OrgSetupWizardView.vue'),
          meta: { staffOnly: true },
        },
        {
          path: 'partners',
          component: () => import('@/views/admin/PartnersHubAdminView.vue'),
          meta: { permissions: ['menu.customers', 'menu.suppliers', 'menu.subcontract_out'] },
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
        { path: 'masters', component: () => import('@/views/admin/MastersAdminView.vue'), meta: { permissions: ['menu.masters'] } },
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
          path: 'stock-allocate',
          component: () => import('@/views/admin/StockAllocateAdminView.vue'),
          meta: { capability: 'allocate_ui', permissions: ['menu.stock_allocate'] },
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

router.beforeEach((to) => {
  const auth = useAuthStore()
  const isAdminLogin = to.path === '/admin/login'
  const isH5Login = to.path === '/login'
  // 未登录：后台路径进后台登录页，其余进手机端登录页
  if (to.meta.auth && !auth.token) {
    return {
      path: to.path.startsWith('/admin') ? '/admin/login' : '/login',
      query: { redirect: to.fullPath },
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
    !to.path.startsWith('/po/')
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
  if (permissions.length && !permissions.some((code) => auth.hasPermission(code))) {
    return '/admin'
  }
  const cap = to.matched.map((r) => r.meta.capability).find(Boolean) as string | undefined
  if (cap && !auth.hasCapability(cap)) {
    return '/admin'
  }
})

export default router
