<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import SharedMaterialsAdminView from '@/views/admin/SharedMaterialsAdminView.vue'
import StockIssuesAdminView from '@/views/admin/StockIssuesAdminView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showPool = computed(
  () => auth.hasPermission('menu.shared_materials') && auth.hasCapability('shared_pool'),
)
const showDocs = computed(
  () => auth.hasPermission('menu.stock_issues') && auth.hasCapability('stock_docs'),
)

type InvTab = 'pool' | 'out' | 'in'
const tab = ref<InvTab>('pool')

function pickDefaultTab(): InvTab {
  const q = String(route.query.tab || '')
  if (q === 'pool' && showPool.value) return 'pool'
  if (q === 'out' && showDocs.value) return 'out'
  if ((q === 'in' || q === 'inbound') && showDocs.value) return 'in'
  if (showPool.value) return 'pool'
  if (showDocs.value) return 'out'
  return 'pool'
}

function syncQuery(next: InvTab) {
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/inventory', query: { ...route.query, tab: next } })
}

function onTabChange(name: string | number) {
  const next = String(name) as InvTab
  tab.value = next
  syncQuery(next)
}

onMounted(() => {
  tab.value = pickDefaultTab()
  syncQuery(tab.value)
})

watch(
  () => route.query.tab,
  () => {
    const next = pickDefaultTab()
    if (next !== tab.value) tab.value = next
  },
)
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">仓库管理</h1>
        <p class="page-desc">现存量 / 可用 / 占用 / 在途 · 出库单（领料）· 入库单（退料等）</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card inv-tabs" @tab-change="onTabChange">
      <el-tab-pane v-if="showPool" label="库存池" name="pool" lazy>
        <SharedMaterialsAdminView embedded />
      </el-tab-pane>
      <el-tab-pane v-if="showDocs" label="出库单" name="out" lazy>
        <StockIssuesAdminView embedded fixed-direction="out" />
      </el-tab-pane>
      <el-tab-pane v-if="showDocs" label="入库单" name="in" lazy>
        <StockIssuesAdminView embedded fixed-direction="in" />
      </el-tab-pane>
    </el-tabs>

    <div v-if="!showPool && !showDocs" class="admin-card inv-empty">暂无库存相关权限</div>
  </div>
</template>

<style scoped>
.inv-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.inv-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
