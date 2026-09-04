<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type CartonRow = {
  id: number; code: string; total_qty: number; warehoused_at: string
  customer_name: string | null; brand_name: string | null; customer_sku: string | null
  sales_order_no: string | null; product_code: string | null; assortment: string
  product_image_url: string | null
  color_name: string | null; fabric: string | null; lining: string | null
  lines: Array<{ size_id: number; size_value: string; qty: number }>
  shipment_id?: number | null; shipment_no?: string | null
  shipped_at?: string | null; shipped_by?: string | null
}

const activeTab = ref('stock')
const loading = ref(false)
const shippingId = ref<number | null>(null)
const batchShipping = ref(false)
const selectedCartons = ref<CartonRow[]>([])
const cartons = ref<CartonRow[]>([])
const shippedCartons = ref<CartonRow[]>([])
const keyword = ref('')
const shippedDateRange = ref<[string, string] | []>([])
const cartonPage = ref(1)
const cartonPageSize = ref(20)
const shippedPage = ref(1)
const shippedPageSize = ref(20)
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()
const selectedQty = computed(() => selectedCartons.value.reduce((sum, row) => sum + Number(row.total_qty || 0), 0))
const pagedCartons = computed(() => {
  const start = (cartonPage.value - 1) * cartonPageSize.value
  return cartons.value.slice(start, start + cartonPageSize.value)
})
const pagedShippedCartons = computed(() => {
  const start = (shippedPage.value - 1) * shippedPageSize.value
  return shippedCartons.value.slice(start, start + shippedPageSize.value)
})
const cartonSizes = computed(() => {
  const sizes = new Map<number, string>()
  ;[...cartons.value, ...shippedCartons.value].forEach((carton) => {
    carton.lines?.forEach((line) => sizes.set(Number(line.size_id), String(line.size_value || line.size_id)))
  })
  return [...sizes.entries()]
    .map(([id, value]) => ({ id, value }))
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { numeric: true }))
})

function cartonSizeQty(row: CartonRow, sizeId: number) {
  return row.lines?.find((line) => Number(line.size_id) === sizeId)?.qty || 0
}

async function load() {
  loading.value = true
  try {
    const commonParams = { q: keyword.value.trim() || undefined, limit: 500 }
    const [cartonRes, shippedRes]: any[] = await Promise.all([
      http.get('/fg-stocks/cartons', { params: commonParams }),
      http.get('/fg-stocks/cartons', {
        params: {
          ...commonParams,
          status: 'shipped',
          date_from: shippedDateRange.value[0] || undefined,
          date_to: shippedDateRange.value[1] || undefined,
        },
      }),
    ])
    cartons.value = cartonRes.data?.items || []
    shippedCartons.value = shippedRes.data?.items || []
    selectedCartons.value = []
    cartonPage.value = 1
    shippedPage.value = 1
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onCartonSelectionChange(rows: CartonRow[]) {
  selectedCartons.value = rows
}

async function batchShipCartons() {
  if (!selectedCartons.value.length) return
  const owners = new Set(
    selectedCartons.value.map((row) => `${row.customer_name || '通用库存'} / ${row.brand_name || '未指定品牌'}`),
  )
  await ElMessageBox.confirm(
    `确认批量出库 ${selectedCartons.value.length} 箱、共 ${selectedQty.value} 双？涉及 ${owners.size} 个客户品牌归属，系统将逐箱生成出货记录。`,
    '批量按箱出库',
    { type: 'warning', confirmButtonText: '确认批量出库', cancelButtonText: '取消' },
  )
  batchShipping.value = true
  try {
    const res: any = await http.post('/packing-cartons/batch-ship', {
      carton_ids: selectedCartons.value.map((row) => row.id),
    })
    const success = Number(res.data?.success_count || 0)
    const failed = Number(res.data?.failed_count || 0)
    if (failed) {
      ElMessage.warning(`已出库 ${success} 箱；${res.data?.failed?.[0]?.message || `${failed} 箱失败`}`)
    } else {
      ElMessage.success(`批量出库完成：${success} 箱 / ${Number(res.data?.total_qty || 0)} 双`)
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '批量出库失败')
  } finally {
    batchShipping.value = false
  }
}

function printShipment(row: CartonRow) {
  if (!row.shipment_id) return
  window.open(`${window.location.origin}/admin/shipments/print/${row.shipment_id}`, '_blank')
}

async function shipCarton(row: CartonRow) {
  await ElMessageBox.confirm(
    `确认出库箱 ${row.code}（${row.total_qty} 双）？系统将按 ${row.customer_name || '未指定客户'} / ${row.brand_name || '未指定品牌'} 的销售归属生成出货单。`,
    '按箱出库',
    { type: 'warning', confirmButtonText: '确认出库', cancelButtonText: '取消' },
  )
  shippingId.value = row.id
  try {
    await http.post(`/packing-cartons/${row.id}/ship`, {})
    ElMessage.success(`箱 ${row.code} 已出库`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '出库失败')
  } finally {
    shippingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">成品仓</h1>
        <p class="page-desc">一箱一库存载体 · 客户与品牌归属隔离 · 箱内色码汇总对账</p>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input v-model="keyword" clearable placeholder="箱码 / 客户 / 品牌 / 客户型号 / 工厂型号 / 订单号" style="width: 390px" @clear="load" @keyup.enter="load" />
        <el-date-picker
          v-if="activeTab === 'shipped'"
          v-model="shippedDateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="出库开始日期"
          end-placeholder="出库结束日期"
          style="width: 250px"
          @change="load"
        />
        <div class="spacer" />
        <el-button v-if="activeTab === 'stock'" type="success" :disabled="!selectedCartons.length" :loading="batchShipping" @click="batchShipCartons">
          批量出库{{ selectedCartons.length ? ` (${selectedCartons.length})` : '' }}
        </el-button>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="load">刷新</el-button>
      </div>

      <el-tabs v-model="activeTab" class="warehouse-tabs">
        <el-tab-pane name="stock" label="在库箱码">
          <div ref="tableHostRef" class="table-pane-layout">
            <el-table v-loading="loading" :data="pagedCartons" row-key="id" stripe border size="small" table-layout="fixed" class="no-x-table" style="width: 100%" :max-height="tableMaxHeight" empty-text="暂无已入库未出库箱码" @selection-change="onCartonSelectionChange">
              <el-table-column type="selection" width="34" reserve-selection />
              <el-table-column prop="code" label="箱码" min-width="58" show-overflow-tooltip />
              <el-table-column prop="sales_order_no" label="订单号" min-width="62" show-overflow-tooltip><template #default="{ row }">{{ row.sales_order_no || '—' }}</template></el-table-column>
              <el-table-column prop="customer_name" label="客户" min-width="48" show-overflow-tooltip><template #default="{ row }">{{ row.customer_name || '通用库存' }}</template></el-table-column>
              <el-table-column prop="product_code" label="工厂型号" min-width="56" show-overflow-tooltip><template #default="{ row }">{{ row.product_code || '—' }}</template></el-table-column>
              <el-table-column label="图片" width="44" align="center">
                <template #default="{ row }"><el-image v-if="row.product_image_url" :src="row.product_image_url" :preview-src-list="[row.product_image_url]" fit="contain" preview-teleported class="product-thumb" /><span v-else>—</span></template>
              </el-table-column>
              <el-table-column prop="color_name" label="颜色" min-width="42" show-overflow-tooltip><template #default="{ row }">{{ row.color_name || '—' }}</template></el-table-column>
              <el-table-column prop="brand_name" label="品牌" min-width="46" show-overflow-tooltip><template #default="{ row }">{{ row.brand_name || '未指定' }}</template></el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" min-width="54" show-overflow-tooltip><template #default="{ row }">{{ row.customer_sku || '—' }}</template></el-table-column>
              <el-table-column label="码数" align="center">
                <el-table-column v-for="size in cartonSizes" :key="size.id" :label="size.value" width="30" align="center">
                  <template #default="{ row }">{{ cartonSizeQty(row, size.id) || '—' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="total_qty" label="双数" width="40" align="right" />
              <el-table-column prop="warehoused_at" label="入库时间" min-width="78" show-overflow-tooltip />
              <el-table-column label="操作" width="48"><template #default="{ row }"><el-button link type="success" :loading="shippingId === row.id" @click="shipCarton(row)">出库</el-button></template></el-table-column>
            </el-table>
            <div class="admin-pagination">
              <el-pagination
                v-model:current-page="cartonPage"
                v-model:page-size="cartonPageSize"
                background
                :page-sizes="[10, 20, 50, 100]"
                :total="cartons.length"
                layout="total, sizes, prev, pager, next"
              />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane name="shipped" label="出库记录">
          <div class="table-pane-layout">
            <el-table v-loading="loading" :data="pagedShippedCartons" stripe border size="small" table-layout="fixed" class="no-x-table" style="width: 100%" :max-height="tableMaxHeight" empty-text="暂无出库记录">
              <el-table-column prop="code" label="箱码" min-width="52" show-overflow-tooltip />
              <el-table-column prop="sales_order_no" label="订单号" min-width="56" show-overflow-tooltip><template #default="{ row }">{{ row.sales_order_no || '—' }}</template></el-table-column>
              <el-table-column prop="customer_name" label="客户" min-width="44" show-overflow-tooltip><template #default="{ row }">{{ row.customer_name || '通用库存' }}</template></el-table-column>
              <el-table-column prop="product_code" label="工厂型号" min-width="50" show-overflow-tooltip><template #default="{ row }">{{ row.product_code || '—' }}</template></el-table-column>
              <el-table-column label="图片" width="42" align="center">
                <template #default="{ row }"><el-image v-if="row.product_image_url" :src="row.product_image_url" :preview-src-list="[row.product_image_url]" fit="contain" preview-teleported class="product-thumb" /><span v-else>—</span></template>
              </el-table-column>
              <el-table-column prop="color_name" label="颜色" min-width="38" show-overflow-tooltip><template #default="{ row }">{{ row.color_name || '—' }}</template></el-table-column>
              <el-table-column prop="brand_name" label="品牌" min-width="42" show-overflow-tooltip><template #default="{ row }">{{ row.brand_name || '未指定' }}</template></el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" min-width="48" show-overflow-tooltip><template #default="{ row }">{{ row.customer_sku || '—' }}</template></el-table-column>
              <el-table-column label="码数" align="center">
                <el-table-column v-for="size in cartonSizes" :key="size.id" :label="size.value" width="28" align="center">
                  <template #default="{ row }">{{ cartonSizeQty(row, size.id) || '—' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="total_qty" label="双数" width="38" align="right" />
              <el-table-column prop="shipment_no" label="出货单号" min-width="54" show-overflow-tooltip><template #default="{ row }">{{ row.shipment_no || '—' }}</template></el-table-column>
              <el-table-column prop="shipped_at" label="出库时间" min-width="68" show-overflow-tooltip />
              <el-table-column prop="shipped_by" label="操作人" min-width="40" show-overflow-tooltip><template #default="{ row }">{{ row.shipped_by || '—' }}</template></el-table-column>
              <el-table-column label="操作" width="60"><template #default="{ row }"><el-button link type="primary" @click="printShipment(row)">出货单</el-button></template></el-table-column>
            </el-table>
            <div class="admin-pagination">
              <el-pagination
                v-model:current-page="shippedPage"
                v-model:page-size="shippedPageSize"
                background
                :page-sizes="[10, 20, 50, 100]"
                :total="shippedCartons.length"
                layout="total, sizes, prev, pager, next"
              />
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.admin-toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }
.spacer { flex: 1; }
.warehouse-tabs { width: 100%; max-width: 100%; flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.warehouse-tabs :deep(.el-tabs__header) { flex-shrink: 0; }
.warehouse-tabs :deep(.el-tabs__content) { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.warehouse-tabs :deep(.el-tab-pane) { height: 100%; }
.table-pane-layout { width: 100%; max-width: 100%; flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.product-thumb { width: 32px; height: 26px; vertical-align: middle; }
.no-x-table { width: 100% !important; max-width: 100%; }
.no-x-table :deep(.el-table__inner-wrapper),
.no-x-table :deep(.el-table__header-wrapper),
.no-x-table :deep(.el-table__body-wrapper) { width: 100% !important; max-width: 100%; }
.no-x-table :deep(.el-table__cell) { padding: 3px 0; }
.no-x-table :deep(.cell) { padding: 0 2px; font-size: 11px; line-height: 15px; }
.no-x-table :deep(th .cell) { white-space: normal; word-break: keep-all; }
.no-x-table :deep(.el-table__body-wrapper .el-scrollbar__wrap),
.no-x-table :deep(.el-table__header-wrapper) { overflow-x: hidden !important; }
.no-x-table :deep(.el-scrollbar__bar.is-horizontal) { display: none !important; }
@media (max-width: 760px) {
  .admin-toolbar :deep(.el-input) { width: 100% !important; }
}
</style>
