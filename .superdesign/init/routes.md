# Routes

Framework: Vue 3 + Vue Router 4, Vite. Full router source: `web/src/router/index.ts`.

## Key product routes
- `/home` → `web/src/views/HomeView.vue`, inside `MainLayout.vue`; mobile home with yield and boss overview.
- `/orders`, `/work-logs`, `/workers`, `/mine` → mobile operational pages in `MainLayout.vue`.
- `/admin` → `web/src/views/admin/DashboardView.vue`, inside `AdminLayout.vue`.
- `/admin/sales-orders`, `/admin/executions`, `/admin/orders`, `/admin/schedule`, `/admin/purchase`, `/admin/inventory`, `/admin/shipments` → desktop ERP workflows in `AdminLayout.vue`.
- `/board` → `web/src/views/WorkshopBoardView.vue`; workshop display.
- `/login`, `/po/:token`, `/scan/:code`, `/trace/:code` → public / utility entry points.

Route access is enforced in the router guard by the auth store; admin routes additionally use staff/admin/capability metadata.
