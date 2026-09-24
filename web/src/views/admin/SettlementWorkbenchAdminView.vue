<template>
  <div class="settlement-workbench">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">往来结算</h1>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>

    <div class="settlement-metrics" v-loading="loading">
      <button type="button" class="settlement-metric" @click="go('customers')">
        <span>客户欠款</span>
        <strong>¥{{ money(metrics.customerBalance) }}</strong>
        <small>查看客户往来</small>
      </button>
      <button type="button" class="settlement-metric" @click="go('suppliers')">
        <span>供应商欠款</span>
        <strong>¥{{ money(metrics.supplierBalance) }}</strong>
        <small>查看供应商对账</small>
      </button>
      <button type="button" class="settlement-metric" @click="goStatements('draft')">
        <span>待确认对账单</span>
        <strong>{{ metrics.draftCount }}</strong>
        <small>检查并确认草稿</small>
      </button>
      <button type="button" class="settlement-metric is-warning" @click="goStatements()">
        <span>已逾期对账单</span>
        <strong>{{ metrics.overdueCount }}</strong>
        <small>仍有 ¥{{ money(metrics.overdueAmount) }} 未收付</small>
      </button>
    </div>

    <section class="settlement-due admin-card">
      <div class="settlement-section-head">
        <div>
          <h2>近期收付款</h2>
          <p>已确认且尚未结清的对账单，按到期日排序</p>
        </div>
        <el-button link type="primary" @click="goStatements()">查看全部</el-button>
      </div>
      <el-table :data="dueRows" border stripe size="small" empty-text="暂无待收付款对账单">
        <el-table-column prop="due_date" label="到期日" width="115" />
        <el-table-column prop="partner_name" label="往来单位" min-width="150" />
        <el-table-column label="方向" width="90">
          <template #default="{ row }">{{ row.direction === 'customer' ? '待收款' : '待付款' }}</template>
        </el-table-column>
        <el-table-column prop="statement_no" label="对账单号" min-width="145" />
        <el-table-column label="未结金额" width="130" align="right">
          <template #default="{ row }"><strong>¥{{ money(row.remaining_amount) }}</strong></template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="isOverdue(row) ? 'danger' : 'warning'" effect="light" size="small">
              {{ isOverdue(row) ? '已逾期' : '待收付' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openStatement(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/api/http'

const router = useRouter()
const loading = ref(false)
const dueRows = ref<any[]>([])
const metrics = reactive({
  customerBalance: 0,
  supplierBalance: 0,
  draftCount: 0,
  overdueCount: 0,
  overdueAmount: 0,
})

function money(value: any) {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function isOverdue(row: any) {
  return Boolean(row?.due_date && String(row.due_date) < new Date().toISOString().slice(0, 10))
}

async function load() {
  loading.value = true
  try {
    const [customersRes, suppliersRes, statementsRes]: any[] = await Promise.all([
      http.get('/receivables/sales-debt'),
      http.get('/payables/purchase-debt'),
      http.get('/account-statements', { params: { page: 1, page_size: 200 } }),
    ])
    const statements = (statementsRes.data?.items || []).filter(
      (row: any) => row.statement_kind !== 'purchase' && row.statement_kind !== 'sales',
    )
    const debt = suppliersRes.data || {}
    metrics.customerBalance = Number(customersRes.data?.debt || 0)
    metrics.supplierBalance = Number(debt.debt || 0)
    metrics.draftCount = statements.filter((row: any) => row.status === 'draft').length
    const unsettled = statements.filter(
      (row: any) => ['confirmed', 'partial'].includes(row.status) && Number(row.remaining_amount || 0) > 0,
    )
    const overdue = unsettled.filter(isOverdue)
    metrics.overdueCount = overdue.length
    metrics.overdueAmount = overdue.reduce(
      (sum: number, row: any) => sum + Number(row.remaining_amount || 0),
      0,
    )
    dueRows.value = unsettled
      .sort((left: any, right: any) => String(left.due_date || '').localeCompare(String(right.due_date || '')))
      .slice(0, 8)
  } finally {
    loading.value = false
  }
}

function go(section: string) {
  void router.replace({ path: '/admin/settlements', query: { section } })
}

function goStatements(status = '') {
  void router.replace({
    path: '/admin/settlements',
    query: { section: 'statements', status: status || undefined, all_periods: '1' },
  })
}

function openStatement(row: any) {
  void router.replace({
    path: '/admin/settlements',
    query: {
      section: 'statements',
      partner_type: row.partner_type || (row.direction === 'customer' ? 'customer' : 'supplier'),
      partner_id: String(row.partner_id || ''),
      month: String(row.period_end || '').slice(0, 7),
    },
  })
}

onMounted(load)
</script>

<style scoped>
.settlement-workbench {
  min-height: 0;
}

.settlement-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.settlement-metric {
  min-width: 0;
  padding: 18px;
  text-align: left;
  color: #111827;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
}

.settlement-metric:hover {
  border-color: #93c5fd;
  box-shadow: 0 6px 18px rgb(15 23 42 / 7%);
}

.settlement-metric span,
.settlement-metric small {
  display: block;
  color: #64748b;
}

.settlement-metric strong {
  display: block;
  margin: 8px 0 6px;
  font-size: 24px;
}

.settlement-metric.is-warning strong {
  color: #dc2626;
}

.settlement-due {
  padding: 16px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.settlement-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.settlement-section-head h2,
.settlement-section-head p {
  margin: 0;
}

.settlement-section-head h2 {
  font-size: 16px;
}

.settlement-section-head p {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .settlement-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
