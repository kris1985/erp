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
          @change="search"
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
      <div ref="tableHostRef">
      <el-table ref="tableRef" :data="orders" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 110)" resizable />
        <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 120)" resizable />
        <el-table-column prop="product_code" label="产品" :width="colWidth('product_code', 120)" resizable />
        <el-table-column prop="shipped_qty" label="已出货" :width="colWidth('shipped_qty', 80)" resizable />
        <el-table-column prop="revenue" label="收入" :width="colWidth('revenue', 90)" resizable />
        <el-table-column prop="material_cost" label="材料" :width="colWidth('material_cost', 90)" resizable />
        <el-table-column prop="labor_cost" label="人工" :width="colWidth('labor_cost', 90)" resizable />
        <el-table-column prop="other_cost" label="其它" :width="colWidth('other_cost', 90)" resizable />
        <el-table-column prop="gross_profit" label="毛利" :width="colWidth('gross_profit', 90)" resizable />
        <el-table-column column-key="margin" label="毛利率" :min-width="flexColMinWidth('margin', 90)" resizable>
          <template #default="{ row }">
            {{ row.gross_margin == null ? '—' : `${(Number(row.gross_margin) * 100).toFixed(1)}%` }}
          </template>
        </el-table-column>
      </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
      <p class="muted" style="margin-top: 8px">金额为估算毛利，供经营参考</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('profit-orders', tableRef)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const monthVal = ref(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`)
const orders = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const ym = computed(() => {
  const [y, m] = (monthVal.value || '').split('-').map(Number)
  return { year: y, month: m }
})

async function load() {
  const res: any = await http.get('/profit-report', {
    params: { ...ym.value, page: page.value, page_size: pageSize.value },
  })
  orders.value = res.data?.orders || res.data?.items || []
  total.value = res.data?.total ?? orders.value.length
  summary.value = res.data?.summary || {}
}

function search() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>
