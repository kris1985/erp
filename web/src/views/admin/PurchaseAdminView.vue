<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PurchaseOrdersAdminView from '@/views/admin/PurchaseOrdersAdminView.vue'
import DemandShortagesAdminView from '@/views/admin/DemandShortagesAdminView.vue'
import StockReplenishmentAdminView from '@/views/admin/StockReplenishmentAdminView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showOrders = computed(() => auth.hasPermission('menu.purchase_orders'))
const showShortages = computed(() => auth.hasPermission('menu.material_shortages'))

type PurchaseTab = 'buy' | 'orders'
type BuySource = 'order' | 'stock'
const tab = ref<PurchaseTab>('buy')
const buySource = ref<BuySource>('order')

function isKitRedirect(q: string) {
  return q === 'shortages' || q === 'shortage' || q === 'production'
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

function pickBuySource(): BuySource {
  const s = String(route.query.source || '')
  const q = String(route.query.tab || '')
  if (s === 'stock' || q === 'stock' || q === 'replenish') return 'stock'
  return 'order'
}

function syncQuery(next: PurchaseTab, source: BuySource) {
  if (route.path !== '/admin/purchase') return
  const query: Record<string, string> = { ...route.query, tab: next } as Record<string, string>
  if (next === 'buy') query.source = source
  else delete query.source
  const curTab = String(route.query.tab || '')
  const curSource = String(route.query.source || '')
  if (curTab === query.tab && (query.source || '') === curSource) return
  router.replace({ path: '/admin/purchase', query })
}

function onSourceChange(name: string | number | boolean) {
  buySource.value = String(name) as BuySource
  syncQuery('buy', buySource.value)
}

onMounted(() => {
  const q = String(route.query.tab || '')
  if (isKitRedirect(q)) {
    redirectKitToBuy()
    return
  }
  tab.value = pickDefaultTab()
  buySource.value = pickBuySource()
  syncQuery(tab.value, buySource.value)
})

watch(
  () => [route.query.tab, route.query.source],
  () => {
    const q = String(route.query.tab || '')
    if (isKitRedirect(q)) {
      redirectKitToBuy()
      return
    }
    const next = pickDefaultTab()
    const src = pickBuySource()
    if (next !== tab.value) tab.value = next
    if (src !== buySource.value) buySource.value = src
  },
)
</script>

<template>
  <div class="purchase-page">
    <div v-if="tab === 'buy' && showShortages" class="purchase-pane">
      <div class="buy-switch">
        <el-radio-group :model-value="buySource" size="small" @change="onSourceChange">
          <el-radio-button value="order">接单备料</el-radio-button>
          <el-radio-button value="stock">备库</el-radio-button>
        </el-radio-group>
      </div>
      <DemandShortagesAdminView v-if="buySource === 'order'" embedded />
      <StockReplenishmentAdminView v-else embedded />
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
.buy-switch {
  margin: 0 0 12px;
  flex-shrink: 0;
}
.purchase-pane > :not(.buy-switch) {
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
