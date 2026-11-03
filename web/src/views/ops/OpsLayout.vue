<template>
  <div class="admin-app">
    <div class="admin-layout">
      <aside class="admin-aside">
        <div class="admin-brand">
          <span aria-hidden="true"></span>
          <span class="admin-brand-text" title="铁玉兰运营">铁玉兰运营</span>
        </div>
        <nav class="admin-nav" aria-label="运营导航">
          <router-link to="/ops" class="admin-nav-item" exact-active-class="is-active">
            <span class="admin-nav-row">
              <span class="admin-nav-icon"><el-icon><OfficeBuilding /></el-icon></span>
              <span class="admin-nav-label">租户</span>
            </span>
          </router-link>
          <router-link to="/ops/app" class="admin-nav-item" active-class="is-active">
            <span class="admin-nav-row">
              <span class="admin-nav-icon"><el-icon><Cellphone /></el-icon></span>
              <span class="admin-nav-label">App 版本</span>
            </span>
          </router-link>
        </nav>
        <div class="admin-aside-user">
          <button type="button" class="admin-user-trigger" :title="ops.name || '运营'" @click="logout">
            <span class="admin-user-avatar">{{ userInitial }}</span>
            <span class="admin-user-meta">
              <span class="admin-user-name">{{ ops.name || '运营' }}</span>
              <span class="admin-user-role">退出登录</span>
            </span>
          </button>
        </div>
      </aside>
      <div class="admin-main has-content-head">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Cellphone, OfficeBuilding } from '@element-plus/icons-vue'
import { useOpsAuthStore } from '@/stores/opsAuth'

const ops = useOpsAuthStore()
const router = useRouter()
const userInitial = computed(() => (ops.name || '运').slice(0, 1))

function logout() {
  ops.logout()
  router.replace('/ops/login')
}
</script>

<style scoped>
.admin-main :deep(.ops-page) {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
</style>
