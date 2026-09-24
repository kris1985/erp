<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PartnersAdminView from '@/views/admin/PartnersAdminView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showCustomers = computed(() => auth.hasPermission('menu.customers'))
const showSuppliers = computed(() => auth.hasPermission('menu.suppliers'))
const showSubcontractors = computed(() => auth.hasPermission('menu.subcontract_out'))

type PartnersTab = 'customers' | 'suppliers' | 'subcontractors'
const tab = ref<PartnersTab>('customers')

function pickDefaultTab(): PartnersTab {
  const q = String(route.query.tab || '')
  if ((q === 'customers' || q === 'customer' || q === 'customer_brand') && showCustomers.value) {
    return 'customers'
  }
  if ((q === 'suppliers' || q === 'supplier') && showSuppliers.value) return 'suppliers'
  if ((q === 'subcontractors' || q === 'subcontractor') && showSubcontractors.value) {
    return 'subcontractors'
  }
  if (showCustomers.value) return 'customers'
  if (showSuppliers.value) return 'suppliers'
  if (showSubcontractors.value) return 'subcontractors'
  return 'customers'
}

function syncQuery(next: PartnersTab) {
  if (route.path !== '/admin/partners') return
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/partners', query: { ...route.query, tab: next } })
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
  <div class="partners-page">
    <PartnersAdminView v-if="tab === 'customers' && showCustomers" class="partners-pane" embedded mode="customer_brand" />
    <PartnersAdminView v-else-if="tab === 'suppliers' && showSuppliers" class="partners-pane" embedded mode="supplier" />
    <PartnersAdminView v-else-if="tab === 'subcontractors' && showSubcontractors" class="partners-pane" embedded mode="subcontractor" />
    <div v-else class="admin-card partners-empty">暂无合作商相关权限</div>
  </div>
</template>

<style scoped>
.partners-page,
.partners-pane {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.partners-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
