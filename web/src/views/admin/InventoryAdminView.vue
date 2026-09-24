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
  if (route.path !== '/admin/inventory') return
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/inventory', query: { ...route.query, tab: next } })
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
  <div class="inv-page">
    <SharedMaterialsAdminView v-if="tab === 'pool' && showPool" class="inv-pane" embedded />
    <StockIssuesAdminView
      v-else-if="tab === 'out' && showDocs"
      class="inv-pane"
      embedded
      fixed-direction="out"
      issue-kind-filter="issue"
    />
    <StockIssuesAdminView
      v-else-if="tab === 'in' && showDocs"
      class="inv-pane"
      embedded
      fixed-direction="in"
    />
    <div v-else class="admin-card inv-empty">暂无库存相关权限</div>
  </div>
</template>

<style scoped>
.inv-page,
.inv-pane {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.inv-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
