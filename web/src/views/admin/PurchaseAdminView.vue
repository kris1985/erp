<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PurchaseOrdersAdminView from '@/views/admin/PurchaseOrdersAdminView.vue'
import MaterialShortagesAdminView from '@/views/admin/MaterialShortagesAdminView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showOrders = computed(() => auth.hasPermission('menu.purchase_orders'))
const showShortages = computed(() => auth.hasPermission('menu.material_shortages'))

type PurchaseTab = 'orders' | 'shortages'
const tab = ref<PurchaseTab>('shortages')

function pickDefaultTab(): PurchaseTab {
  const q = String(route.query.tab || '')
  if ((q === 'orders' || q === 'po') && showOrders.value) return 'orders'
  if ((q === 'shortages' || q === 'shortage') && showShortages.value) return 'shortages'
  if (showShortages.value) return 'shortages'
  if (showOrders.value) return 'orders'
  return 'shortages'
}

function syncQuery(next: PurchaseTab) {
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/purchase', query: { ...route.query, tab: next } })
}

function onTabChange(name: string | number) {
  const next = String(name) as PurchaseTab
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
        <h1 class="page-title">采购</h1>
        <p class="page-desc">缺料汇总 · 采购单（按供应商合并生成草稿）</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card purchase-tabs" @tab-change="onTabChange">
      <el-tab-pane v-if="showShortages" label="缺料汇总" name="shortages" lazy>
        <MaterialShortagesAdminView embedded />
      </el-tab-pane>
      <el-tab-pane v-if="showOrders" label="采购单" name="orders" lazy>
        <PurchaseOrdersAdminView embedded />
      </el-tab-pane>
    </el-tabs>

    <div v-if="!showOrders && !showShortages" class="admin-card purchase-empty">暂无采购相关权限</div>
  </div>
</template>

<style scoped>
.purchase-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.purchase-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
