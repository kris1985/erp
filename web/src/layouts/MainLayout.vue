<template>
  <div class="h5-shell h5-app" :class="{ 'h5-app--staff': isStaff }">
    <!-- 工人端保留顶栏标题 + 扫码；管理员端不需要 -->
    <van-nav-bar v-if="!isStaff" :title="navTitle" fixed placeholder :border="false">
      <template #right>
        <button type="button" class="h5-nav-scan" aria-label="扫码报工" @click="scanShow = true">
          <van-icon name="scan" />
        </button>
      </template>
    </van-nav-bar>
    <router-view />
    <van-tabbar route fixed placeholder :border="false" active-color="var(--ws-primary)" inactive-color="#8e8e93">
      <van-tabbar-item replace to="/home" icon="home-o">首页</van-tabbar-item>
      <template v-if="auth.actor === 'worker'">
        <van-tabbar-item replace to="/my-work-logs" icon="orders-o">报工</van-tabbar-item>
        <van-tabbar-item replace to="/my-salary" icon="balance-o">工资</van-tabbar-item>
      </template>
      <template v-else>
        <van-tabbar-item replace to="/orders" icon="orders-o">订单</van-tabbar-item>
        <van-tabbar-item replace to="/work-logs" icon="notes-o">报工</van-tabbar-item>
        <van-tabbar-item replace to="/workers" icon="friends-o">员工</van-tabbar-item>
      </template>
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

const route = useRoute()
const auth = useAuthStore()
const scanShow = ref(false)

const isStaff = computed(() => auth.actor !== 'worker')

const navTitle = computed(() => {
  const map: Record<string, string> = {
    '/home': '',
    '/my-salary': '我的工资',
    '/my-work-logs': '报工',
    '/work-logs': '报工',
    '/mine': '我的',
  }
  return map[route.path] ?? '铁玉兰管家'
})

onMounted(() => {
  if (auth.actor !== 'worker') auth.refreshPermissions()
})
</script>

<style scoped>
.h5-app--staff .page {
  padding-top: calc(8px + env(safe-area-inset-top, 0px));
}

.h5-app :deep(.van-nav-bar__right) {
  padding-right: 10px;
}

.h5-nav-scan {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 10px;
  background: rgba(0, 118, 255, 0.1);
  color: var(--ws-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  padding: 0;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.h5-nav-scan:active {
  background: rgba(0, 118, 255, 0.18);
  transform: scale(0.96);
}
</style>
