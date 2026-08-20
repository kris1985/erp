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
  const cur = String(route.query.tab || '')
  if (cur === next) return
  router.replace({ path: '/admin/partners', query: { ...route.query, tab: next } })
}

function onTabChange(name: string | number) {
  const next = String(name) as PartnersTab
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
        <h1 class="page-title">合作商</h1>
        <p class="page-desc">客户 · 供应商 · 外协厂档案与联系人</p>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card partners-tabs" @tab-change="onTabChange">
      <el-tab-pane v-if="showCustomers" label="客户" name="customers" lazy>
        <PartnersAdminView embedded mode="customer_brand" />
      </el-tab-pane>
      <el-tab-pane v-if="showSuppliers" label="供应商" name="suppliers" lazy>
        <PartnersAdminView embedded mode="supplier" />
      </el-tab-pane>
      <el-tab-pane v-if="showSubcontractors" label="外协厂" name="subcontractors" lazy>
        <PartnersAdminView embedded mode="subcontractor" />
      </el-tab-pane>
    </el-tabs>

    <div v-if="!showCustomers && !showSuppliers && !showSubcontractors" class="admin-card partners-empty">暂无合作商相关权限</div>
  </div>
</template>

<style scoped>
.partners-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.partners-empty {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
