# Key page dependency trees

## /home
Entry: `web/src/views/HomeView.vue`
Dependencies:
- `web/src/components/BossOverview.vue`
- `web/src/api/http.ts`
- `web/src/stores/auth.ts`
- `web/src/layouts/MainLayout.vue`
  - `web/src/components/QrScanSheet.vue`

## /admin
Entry: `web/src/views/admin/DashboardView.vue`
Dependencies:
- `web/src/layouts/AdminLayout.vue`
- `web/src/admin.css`
- Element Plus components and ECharts

## /board
Entry: `web/src/views/WorkshopBoardView.vue`
Dependencies:
- `web/src/api/http.ts`
- `web/src/stores/auth.ts`

## /orders
Entry: `web/src/views/OrdersView.vue`
Dependencies:
- `web/src/layouts/MainLayout.vue`
- `web/src/api/http.ts`
