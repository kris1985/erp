import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { auth: true },
      children: [
        { path: '', name: 'home', component: () => import('@/views/HomeView.vue') },
        { path: 'workers', component: () => import('@/views/WorkersView.vue') },
        { path: 'processes', component: () => import('@/views/ProcessesView.vue') },
        { path: 'styles', component: () => import('@/views/StylesView.vue') },
        { path: 'orders', component: () => import('@/views/OrdersView.vue') },
        { path: 'chat', component: () => import('@/views/ChatView.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.auth && !auth.token) return '/login'
  if (to.path === '/login' && auth.token) return '/'
})

export default router
