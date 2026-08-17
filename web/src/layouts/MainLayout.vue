<template>
  <div class="h5-shell h5-app" :class="{ 'h5-app--staff': isStaff, 'h5-app--worker': !isStaff }">
    <!-- 工人端保留标题；扫码作为一线员工的中置主操作 -->
    <van-nav-bar v-if="!isStaff" :title="navTitle" fixed placeholder :border="false">
    </van-nav-bar>
    <router-view />
    <van-tabbar route fixed placeholder :border="false" active-color="var(--ws-primary)" inactive-color="#8e8e93">
      <van-tabbar-item v-if="auth.isWorker" replace to="/home" icon="home-o">首页</van-tabbar-item>
      <template v-if="auth.isWorker">
        <van-tabbar-item replace to="/my-work-logs" icon="orders-o">计件</van-tabbar-item>
        <button type="button" class="h5-tabbar-scan" aria-label="扫码计件" @click="scanShow = true">
          <span class="h5-tabbar-scan__icon"><van-icon name="scan" /></span>
        </button>
        <van-tabbar-item replace to="/my-salary" icon="balance-o">工资</van-tabbar-item>
      </template>
      <template v-else>
        <van-tabbar-item replace to="/workbench" icon="apps-o">总览</van-tabbar-item>
        <van-tabbar-item replace to="/orders" icon="orders-o">订单</van-tabbar-item>
        <van-tabbar-item replace to="/work-logs" icon="todo-list-o">任务</van-tabbar-item>
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

const isStaff = computed(() => !auth.isWorker)

const navTitle = computed(() => {
  const map: Record<string, string> = {
    '/home': '',
    '/workbench': '工作台',
    '/my-salary': '我的工资',
    '/my-work-logs': '计件',
    '/my-team': '组员',
    '/work-logs': '生产记录',
    '/mine': '我的',
  }
  return map[route.path] ?? '铁玉兰管家'
})

onMounted(() => {
  if (!auth.isWorker) auth.refreshPermissions()
})
</script>

<style scoped>
.h5-app--staff .page {
  padding-top: calc(8px + env(safe-area-inset-top, 0px));
}

.h5-tabbar-scan {
  position: absolute;
  z-index: 2;
  top: -24px;
  left: 50%;
  width: 64px;
  height: 64px;
  border: none;
  background: transparent;
  color: var(--ws-primary);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 0;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transform: translateX(-50%);
}

.h5-tabbar-scan__icon {
  display: grid;
  width: 56px;
  height: 56px;
  place-items: center;
  border: 4px solid #fff;
  border-radius: 50%;
  background: var(--ws-primary);
  box-shadow: 0 6px 18px rgba(0, 118, 255, 0.3);
  color: #fff;
  font-size: 25px;
}

.h5-tabbar-scan:active {
  transform: translateX(-50%) scale(0.94);
}

/* 员工端预留中置扫码槽位：四个导航项按五等分定位。 */
.h5-app--worker :deep(.van-tabbar-item) {
  position: absolute;
  top: 0;
  width: 20%;
  height: var(--ws-tabbar-h);
}

.h5-app--worker :deep(.van-tabbar-item:nth-child(1)) {
  left: 0;
}

.h5-app--worker :deep(.van-tabbar-item:nth-child(2)) {
  left: 20%;
}

.h5-app--worker :deep(.van-tabbar-item:nth-child(4)) {
  left: 60%;
}

.h5-app--worker :deep(.van-tabbar-item:nth-child(5)) {
  left: 80%;
}

@media (prefers-reduced-motion: reduce) {
  .h5-tabbar-scan {
    transition: none;
  }
}
</style>
