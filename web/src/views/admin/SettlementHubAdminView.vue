<template>
  <div class="settlement-hub">
    <div class="admin-card settlement-hub-nav">
      <el-tabs :model-value="activeSection" @update:model-value="changeSection">
        <el-tab-pane
          v-for="item in visibleSections"
          :key="item.name"
          :label="item.label"
          :name="item.name"
        />
      </el-tabs>

      <el-radio-group
        v-if="activeSection === 'cash' && visibleCashFlows.length > 1"
        :model-value="activeCashFlow"
        size="small"
        class="settlement-cash-switch"
        @update:model-value="changeCashFlow"
      >
        <el-radio-button
          v-for="item in visibleCashFlows"
          :key="item.name"
          :value="item.name"
        >
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="activeComponent" class="settlement-hub-body">
      <component :is="activeComponent" :key="activeViewKey" />
    </div>

    <el-empty v-if="!activeComponent" description="当前账号没有往来结算查看权限" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const CustomerAccounts = defineAsyncComponent(
  () => import('@/views/admin/ReceivablesAdminView.vue'),
)
const SettlementWorkbench = defineAsyncComponent(
  () => import('@/views/admin/SettlementWorkbenchAdminView.vue'),
)
const SupplierAccounts = defineAsyncComponent(
  () => import('@/views/admin/PayablesAdminView.vue'),
)
const AccountStatements = defineAsyncComponent(
  () => import('@/views/admin/AccountStatementsAdminView.vue'),
)
const CustomerReceipts = defineAsyncComponent(
  () => import('@/views/admin/PaymentsAdminView.vue'),
)
const SupplierPayments = defineAsyncComponent(
  () => import('@/views/admin/SupplierPaymentsAdminView.vue'),
)

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const sections = [
  {
    name: 'overview',
    label: '往来工作台',
    permissions: ['menu.receivables', 'menu.payables', 'menu.payments', 'menu.supplier_payments'],
  },
  { name: 'customers', label: '客户往来', permissions: ['menu.receivables'] },
  { name: 'suppliers', label: '供应商往来', permissions: ['menu.payables'] },
  {
    name: 'statements',
    label: '对账单',
    permissions: ['menu.receivables', 'menu.payables'],
  },
  {
    name: 'cash',
    label: '收付款',
    permissions: ['menu.payments', 'menu.supplier_payments'],
  },
]

const cashFlows = [
  { name: 'receipts', label: '收款', permissions: ['menu.payments'] },
  { name: 'payments', label: '付款', permissions: ['menu.supplier_payments'] },
]

function canAny(permissions: string[]) {
  return permissions.some((permission) => auth.hasPermission(permission))
}

const visibleSections = computed(() => sections.filter((item) => canAny(item.permissions)))
const visibleCashFlows = computed(() => cashFlows.filter((item) => canAny(item.permissions)))

const activeSection = computed(() => {
  const requested = String(route.query.section || '')
  if (visibleSections.value.some((item) => item.name === requested)) return requested
  return visibleSections.value[0]?.name || ''
})

const activeCashFlow = computed(() => {
  const requested = String(route.query.flow || '')
  if (visibleCashFlows.value.some((item) => item.name === requested)) return requested
  return visibleCashFlows.value[0]?.name || ''
})

const activeComponent = computed(() => {
  if (activeSection.value === 'overview') return SettlementWorkbench
  if (activeSection.value === 'customers') return CustomerAccounts
  if (activeSection.value === 'suppliers') return SupplierAccounts
  if (activeSection.value === 'statements') return AccountStatements
  if (activeSection.value === 'cash' && activeCashFlow.value === 'receipts') {
    return CustomerReceipts
  }
  if (activeSection.value === 'cash' && activeCashFlow.value === 'payments') {
    return SupplierPayments
  }
  return null
})

const activeViewKey = computed(() => `${activeSection.value}:${activeCashFlow.value}`)

function changeSection(value: string | number) {
  const { tab: _tab, flow: _flow, ...query } = route.query
  void router.replace({
    path: '/admin/settlements',
    query: { ...query, section: String(value) },
  })
}

function changeCashFlow(value: string | number | boolean | undefined) {
  const { tab: _tab, ...query } = route.query
  void router.replace({
    path: '/admin/settlements',
    query: { ...query, section: 'cash', flow: String(value || '') },
  })
}
</script>

<style scoped>
.settlement-hub-nav {
  flex: 0 0 auto !important;
  margin-bottom: 16px;
  padding: 0 18px;
}

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

.settlement-hub-nav :deep(.el-tabs__header) {
  margin: 0;
}

.settlement-hub-nav :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}

.settlement-cash-switch {
  margin: 12px 0;
}
</style>
