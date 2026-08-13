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
  const query: Record<string, string> = { ...route.query, tab: next } as Record<string, string>
  if (next === 'buy') query.source = source
  else delete query.source
  const curTab = String(route.query.tab || '')
  const curSource = String(route.query.source || '')
  if (curTab === query.tab && (query.source || '') === curSource) return
  router.replace({ path: '/admin/purchase', query })
}

function onTabChange(name: string | number) {
  const next = String(name) as PurchaseTab
  tab.value = next
  syncQuery(next, buySource.value)
}

function onSourceChange(name: string | number | boolean) {
  buySource.value = String(name) as BuySource
  syncQuery('buy', buySource.value)
}

onMounted(() => {
  const q = String(route.query.tab || '')
  if (isKitRedirect(q)) {
    void router.replace({ path: '/admin/executions', query: { tab: 'kit' } })
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
      void router.replace({ path: '/admin/executions', query: { tab: 'kit' } })
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
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">采购</h1>
        <p class="page-desc">待买 · 采购单</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card purchase-tabs" @tab-change="onTabChange">
      <el-tab-pane v-if="showShortages" label="待买" name="buy" lazy>
        <div class="buy-tab-body">
          <div class="buy-switch">
            <el-radio-group :model-value="buySource" size="small" @change="onSourceChange">
              <el-radio-button value="order">接单备料</el-radio-button>
              <el-radio-button value="stock">备库</el-radio-button>
            </el-radio-group>
          </div>
          <DemandShortagesAdminView v-if="buySource === 'order'" embedded />
          <StockReplenishmentAdminView v-else embedded />
        </div>
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
.buy-tab-body {
  min-height: 0;
}
.buy-switch {
  margin: 0 0 12px;
  flex-shrink: 0;
}
.buy-tab-body > :not(.buy-switch) {
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
