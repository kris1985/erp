import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
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
        { path: 'sales-orders', component: () => import('@/views/admin/SalesOrdersAdminView.vue') },
        { path: 'executions', component: () => import('@/views/admin/ExecutionsAdminView.vue') },
        {
          path: 'orders',
          component: () => import('@/views/admin/OrdersAdminView.vue'),
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
        { path: 'schedule', component: () => import('@/views/admin/ScheduleAdminView.vue') },
        {
          path: 'schedule-assistant',
          component: () => import('@/views/admin/ScheduleAssistantView.vue'),
        },
        { path: 'material-shortages', redirect: { path: '/admin/executions', query: { tab: 'kit' } } },
        {
          path: 'customer-supply',
          component: () => import('@/views/admin/CustomerSupplyAdminView.vue'),
        },
        {
          path: 'purchase',
          component: () => import('@/views/admin/PurchaseAdminView.vue'),
        },
        { path: 'purchase-orders', redirect: { path: '/admin/purchase', query: { tab: 'orders' } } },
        {
          path: 'material-iqc',
          component: () => import('@/views/admin/MaterialIqcAdminView.vue'),
        },
        { path: 'shipments', component: () => import('@/views/admin/ShipmentsAdminView.vue') },
        { path: 'shared-materials', redirect: { path: '/admin/inventory', query: { tab: 'pool' } } },
        {
          path: 'inventory',
          component: () => import('@/views/admin/InventoryAdminView.vue'),
        },
        {
          path: 'fg-stocks',
          component: () => import('@/views/admin/FgStocksAdminView.vue'),
        },
        { path: 'receivables', component: () => import('@/views/admin/ReceivablesAdminView.vue') },
        { path: 'payments', component: () => import('@/views/admin/PaymentsAdminView.vue') },
        { path: 'payables', component: () => import('@/views/admin/PayablesAdminView.vue') },
        {
          path: 'supplier-payments',
          component: () => import('@/views/admin/SupplierPaymentsAdminView.vue'),
        },
        { path: 'profit', component: () => import('@/views/admin/ProfitAdminView.vue') },
        { path: 'work-logs', component: () => import('@/views/admin/WorkLogsAdminView.vue') },
        { path: 'salary', component: () => import('@/views/admin/SalaryAdminView.vue') },
        { path: 'workers', component: () => import('@/views/admin/WorkersAdminView.vue') },
        { path: 'teams', component: () => import('@/views/admin/TeamsAdminView.vue') },
        {
          path: 'partners',
          component: () => import('@/views/admin/PartnersHubAdminView.vue'),
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
        },
        {
          path: 'own-products',
          component: () => import('@/views/admin/OwnProductsAdminView.vue'),
        },
        { path: 'masters', component: () => import('@/views/admin/MastersAdminView.vue') },
        { path: 'stations', component: () => import('@/views/admin/StationsAdminView.vue') },
        { path: 'defects', component: () => import('@/views/admin/DefectsAdminView.vue') },
        {
          path: 'users',
          component: () => import('@/views/admin/UsersAdminView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'roles',
          component: () => import('@/views/admin/RolesAdminView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'permissions',
          redirect: { path: '/admin/roles', query: { tab: 'matrix' } },
        },
        {
          path: 'inventory-settings',
          component: () => import('@/views/admin/InventorySettingsAdminView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'workshop-settings',
          component: () => import('@/views/admin/WorkshopSettingsAdminView.vue'),
        },
        {
          path: 'im-alerts',
          component: () => import('@/views/admin/ImAlertsAdminView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'mcp-keys',
          component: () => import('@/views/admin/McpKeysAdminView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'stock-allocate',
          component: () => import('@/views/admin/StockAllocateAdminView.vue'),
          meta: { capability: 'allocate_ui' },
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
  if (to.meta.auth && !auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.token) {
    const redirect = typeof to.query.redirect === 'string' ? to.query.redirect : ''
    if (redirect) return redirect
    if (auth.actor === 'worker') {
      return auth.mustChangePassword ? '/change-password' : '/home'
    }
    return '/admin'
  }
  if (
    auth.token &&
    auth.actor === 'worker' &&
    auth.mustChangePassword &&
    to.path !== '/change-password' &&
    !to.path.startsWith('/po/')
  ) {
    return '/change-password'
  }
  if (to.meta.staffOnly && auth.actor === 'worker') return '/home'
  if (to.meta.workerOnly && auth.actor !== 'worker') return '/home'
  if (to.matched.some((r) => r.meta.adminOnly) && auth.role !== 'admin') {
    return '/admin'
  }
  const cap = to.matched.map((r) => r.meta.capability).find(Boolean) as string | undefined
  if (cap && !auth.hasCapability(cap)) {
    return '/admin'
  }
})

export default router
