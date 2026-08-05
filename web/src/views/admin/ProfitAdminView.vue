<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">利润复盘</h1>
        <p class="page-desc">估算毛利 · 收入 − 材料 − 人工 − 其它</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="monthVal"
          type="month"
          value-format="YYYY-MM"
          placeholder="月份"
          @change="load"
        />
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="admin-toolbar" style="gap: 32px; margin-bottom: 16px">
        <el-statistic title="出货收入" :value="Number(summary.revenue || 0)" />
        <el-statistic title="材料成本" :value="Number(summary.material_cost || 0)" />
        <el-statistic title="人工成本" :value="Number(summary.labor_cost || 0)" />
        <el-statistic title="其它成本" :value="Number(summary.other_cost || 0)" />
        <el-statistic title="毛利(估算)" :value="Number(summary.gross_profit || 0)" />
      </div>
      <el-table :data="orders" stripe border style="width: 100%">
        <el-table-column prop="order_no" label="订单" min-width="110" />
        <el-table-column prop="customer_name" label="客户" min-width="120" />
        <el-table-column prop="product_code" label="产品" min-width="120" />
        <el-table-column prop="shipped_qty" label="已出货" min-width="80" />
        <el-table-column prop="revenue" label="收入" min-width="90" />
        <el-table-column prop="material_cost" label="材料" min-width="90" />
        <el-table-column prop="labor_cost" label="人工" min-width="90" />
        <el-table-column prop="other_cost" label="其它" min-width="90" />
        <el-table-column prop="gross_profit" label="毛利" min-width="90" />
        <el-table-column label="毛利率" min-width="90">
          <template #default="{ row }">
            {{ row.gross_margin == null ? '—' : `${(Number(row.gross_margin) * 100).toFixed(1)}%` }}
          </template>
        </el-table-column>
      </el-table>
      <p class="muted" style="margin-top: 8px">金额为估算毛利，供经营参考</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'

const monthVal = ref(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`)
const orders = ref<any[]>([])
const summary = ref<any>({})

const ym = computed(() => {
  const [y, m] = (monthVal.value || '').split('-').map(Number)
  return { year: y, month: m }
})

async function load() {
  const res: any = await http.get('/profit-report', { params: ym.value })
  orders.value = res.data?.orders || []
  summary.value = res.data?.summary || {}
}

onMounted(load)
</script>
