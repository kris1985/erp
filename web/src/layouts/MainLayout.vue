<template>
  <div>
    <van-nav-bar :title="title" fixed placeholder>
      <template #right>
        <span class="muted" @click="onLogout">{{ auth.displayName }}</span>
      </template>
    </van-nav-bar>
    <router-view />
    <van-tabbar route fixed placeholder>
      <van-tabbar-item replace to="/" icon="home-o">首页</van-tabbar-item>
      <van-tabbar-item replace to="/orders" icon="orders-o">订单</van-tabbar-item>
      <van-tabbar-item replace to="/chat" icon="chat-o">对话</van-tabbar-item>
      <van-tabbar-item replace to="/workers" icon="friends-o">员工</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const title = computed(() => {
  const map: Record<string, string> = {
    '/': '车间智能助手',
    '/orders': '订单',
    '/chat': 'DevChat',
    '/workers': '员工',
    '/processes': '工序单价',
    '/styles': '款式路线',
  }
  return map[route.path] || '车间智能助手'
})

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>
