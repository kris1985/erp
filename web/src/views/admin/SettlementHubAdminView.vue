<template>
  <div class="settlement-hub">
    <div v-if="activeComponent" class="settlement-hub-body">
      <component :is="activeComponent" :key="activeViewKey" />
    </div>

    <el-empty v-if="!activeComponent" description="当前账号没有往来结算查看权限" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const CustomerAccounts = defineAsyncComponent(
  () => import('@/views/admin/ReceivablesAdminView.vue'),
)
const SupplierAccounts = defineAsyncComponent(
  () => import('@/views/admin/PayablesAdminView.vue'),
)
const SubcontractAccounts = defineAsyncComponent(
  () => import('@/views/admin/SubcontractSettlementsAdminView.vue'),
)

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const sections = [
  { name: 'customers', label: '客户对账', permissions: ['menu.receivables', 'menu.payments'] },
  { name: 'suppliers', label: '供应商对账', permissions: ['menu.payables'] },
  {
    name: 'subcontractors',
    label: '外加工厂对账',
    permissions: ['menu.subcontract_out', 'menu.supplier_payments', 'menu.payables'],
  },
]

function canAny(permissions: string[]) {
  return permissions.some((permission) => auth.hasPermission(permission))
}

const visibleSections = computed(() => sections.filter((item) => canAny(item.permissions)))

const activeSection = computed(() => {
  const requested = String(route.query.section || '')
  if (visibleSections.value.some((item) => item.name === requested)) return requested
  return visibleSections.value[0]?.name || ''
})

const activeComponent = computed(() => {
  if (activeSection.value === 'customers') return CustomerAccounts
  if (activeSection.value === 'suppliers') return SupplierAccounts
  if (activeSection.value === 'subcontractors') return SubcontractAccounts
  return null
})

const activeViewKey = computed(() => activeSection.value)

function syncSection() {
  if (route.path !== '/admin/settlements') return
  const next = activeSection.value
  if (!next || String(route.query.section || '') === next) return
  const { tab: _tab, flow: _flow, ...query } = route.query
  void router.replace({
    path: '/admin/settlements',
    query: { ...query, section: next },
  })
}

onMounted(syncSection)
watch(() => route.query.section, syncSection)
</script>

<style scoped>
.settlement-hub-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.settlement-hub-body :deep(> div) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.settlement-hub-body :deep(> div > .page-hero) {
  flex: 0 0 auto;
}

.settlement-hub-body :deep(> div > .admin-card),
.settlement-hub-body :deep(> div > .el-tabs.admin-card) {
  flex: 1 1 auto;
  min-height: 0;
}

</style>
