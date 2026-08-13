# Layouts

## Mobile app shell
- Path: `web/src/layouts/MainLayout.vue`
- Description: mobile-first authenticated shell with role-sensitive tab bar and scan affordance.

```vue
<template>
  <div class="h5-shell h5-app" :class="{ 'h5-app--staff': isStaff }">
    <van-nav-bar v-if="!isStaff" :title="navTitle" fixed placeholder :border="false">
      <template #right><button type="button" class="h5-nav-scan" aria-label="扫码报工" @click="scanShow = true"><van-icon name="scan" /></button></template>
    </van-nav-bar>
    <router-view />
    <van-tabbar route fixed placeholder :border="false" active-color="var(--ws-primary)" inactive-color="#8e8e93">
      <van-tabbar-item replace to="/home" icon="home-o">首页</van-tabbar-item>
      <template v-if="auth.actor === 'worker'"><van-tabbar-item replace to="/my-work-logs" icon="orders-o">报工</van-tabbar-item><van-tabbar-item replace to="/my-salary" icon="balance-o">工资</van-tabbar-item></template>
      <template v-else><van-tabbar-item replace to="/orders" icon="orders-o">订单</van-tabbar-item><van-tabbar-item replace to="/work-logs" icon="notes-o">报工</van-tabbar-item><van-tabbar-item replace to="/workers" icon="friends-o">员工</van-tabbar-item></template>
      <van-tabbar-item replace to="/mine" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
    <QrScanSheet v-if="!isStaff" v-model:show="scanShow" />
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import QrScanSheet from '@/components/QrScanSheet.vue'
const route = useRoute(); const auth = useAuthStore(); const scanShow = ref(false)
const isStaff = computed(() => auth.actor !== 'worker')
const navTitle = computed(() => ({ '/home':'', '/my-salary':'我的工资', '/my-work-logs':'报工', '/work-logs':'报工', '/mine':'我的' }[route.path] ?? '铁玉兰管家'))
onMounted(() => { if (auth.actor !== 'worker') auth.refreshPermissions() })
</script>
```

## Admin app shell
- Path: `web/src/layouts/AdminLayout.vue`
- Description: desktop ERP frame: collapsible navigation, top header, breadcrumb/content outlet. Its styling comes from `web/src/admin.css` and Element Plus.
