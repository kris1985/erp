<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PurchaseOrdersAdminView from '@/views/admin/PurchaseOrdersAdminView.vue'
import DemandShortagesAdminView from '@/views/admin/DemandShortagesAdminView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showOrders = computed(() => auth.hasPermission('menu.purchase_orders'))
const showShortages = computed(() => auth.hasPermission('menu.material_shortages'))

type PurchaseTab = 'buy' | 'orders'
const tab = ref<PurchaseTab>('buy')

function isKitRedirect(q: string) {
  return q === 'shortages' || q === 'shortage' || q === 'production' || q === 'stock' || q === 'replenish'
}

function redirectKitToBuy() {
  if (route.path !== '/admin/purchase') return
  void router.replace({ path: '/admin/purchase', query: { tab: 'buy' } })
}

function pickDefaultTab(): PurchaseTab {
  const q = String(route.query.tab || '')
  if ((q === 'orders' || q === 'po') && showOrders.value) return 'orders'
  if (showShortages.value) return 'buy'
  if (showOrders.value) return 'orders'
  return 'buy'
}

function syncQuery(next: PurchaseTab) {
  if (route.path !== '/admin/purchase') return
  const query: Record<string, string> = { ...route.query, tab: next } as Record<string, string>
  delete query.source
  const curTab = String(route.query.tab || '')
  const curSource = String(route.query.source || '')
  if (curTab === query.tab && !curSource) return
  router.replace({ path: '/admin/purchase', query })
}

onMounted(() => {
  const q = String(route.query.tab || '')
  if (isKitRedirect(q)) {
    redirectKitToBuy()
    return
  }
  tab.value = pickDefaultTab()
  syncQuery(tab.value)
})

watch(
  () => route.query.tab,
  () => {
    const q = String(route.query.tab || '')
    if (isKitRedirect(q)) {
      redirectKitToBuy()
      return
    }
    const next = pickDefaultTab()
    if (next !== tab.value) tab.value = next
  },
)
</script>

<template>
  <div class="purchase-page">
    <div v-if="tab === 'buy' && showShortages" class="purchase-pane">
      <DemandShortagesAdminView embedded />
    </div>
    <PurchaseOrdersAdminView v-else-if="tab === 'orders' && showOrders" class="purchase-pane" embedded />
    <div v-else class="admin-card purchase-empty">暂无采购相关权限</div>
  </div>
</template>

<style scoped>
.purchase-page,
.purchase-pane {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.purchase-pane > * {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.purchase-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
