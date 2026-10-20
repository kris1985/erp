<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import ShipmentsAdminView from '@/views/admin/ShipmentsAdminView.vue'

type SizeLine = { size_id: number; size_value: string; qty: number }
type OrderRow = {
  id: number
  row_key?: string
  sales_order_id?: number | null
  header_no: string
  order_no: string
  customer_name: string
  ordered_at: string | null
  sort_no: number
  product_code: string
  product_image_url: string | null
  color_name: string | null
  fabric: string
  lining: string
  brand_name: string
  customer_sku: string
  lines: SizeLine[]
  carton_qty: number
  total_qty: number
  delivery_date: string | null
  notes: string
  defective_at?: string | null
}

type WarehouseTab = 'pending' | 'shipped' | 'defective'

const route = useRoute()
const router = useRouter()
function tabFromQuery(value: unknown): WarehouseTab {
  if (value === 'shipped' || value === 'defective') return value
  return 'pending'
}

const tab = ref<WarehouseTab>(tabFromQuery(route.query.tab))
const shippedTick = ref(0)
const loading = ref(false)
const shippingId = ref<number | null>(null)
const markingId = ref<number | null>(null)
const orders = ref<OrderRow[]>([])
const sizes = ref<Array<{ id: number; value: string }>>([])
const keyword = ref('')
const orderPage = ref(1)
const orderPageSize = ref(20)
const { tableHostRef, tableMaxHeight, scheduleMeasure } = useTableMaxHeight()

const pagedOrders = computed(() => {
  const start = (orderPage.value - 1) * orderPageSize.value
  return orders.value.slice(start, start + orderPageSize.value)
})

function sizeQty(row: OrderRow, sizeId: number) {
  const qty = Number(row.lines?.find((line) => Number(line.size_id) === sizeId)?.qty) || 0
  if (!qty) return 0
  const boxes = Number(row.carton_qty) || 0
  if (boxes <= 1) return qty
  return qty % boxes === 0 ? qty / boxes : Math.round(qty / boxes)
}

function text(value: string | number | null | undefined) {
  const raw = String(value ?? '').trim()
  return raw || '—'
}

async function load() {
  if (tab.value === 'shipped') return
  loading.value = true
  try {
    const stockRes: any = await http.get('/fg-stocks/orders', {
      params: {
        q: keyword.value.trim() || undefined,
        limit: 500,
        status: tab.value === 'defective' ? 'defective' : 'in_stock',
      },
    })
    orders.value = stockRes.data?.items || []
    sizes.value = (stockRes.data?.sizes || [])
      .map((size: any) => ({ id: Number(size.id), value: String(size.value) }))
      .sort((a: { value: string }, b: { value: string }) => a.value.localeCompare(b.value, undefined, { numeric: true }))
    orderPage.value = 1
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载失败')
  } finally {
    loading.value = false
    scheduleMeasure()
  }
}

async function shipOrder(row: OrderRow) {
  await ElMessageBox.confirm(
    `确认出货 ${row.order_no}（${row.product_code || row.header_no}，${row.total_qty} 双）？将直接生成出货单。`,
    '出货',
    { type: 'warning', confirmButtonText: '确认出货', cancelButtonText: '取消' },
  )
  shippingId.value = row.id
  try {
    await http.post(`/fg-stocks/orders/${row.id}/ship`, {
      sales_order_id: row.sales_order_id || undefined,
    })
    ElMessage.success(`${row.order_no} 已生成出货单`)
    await load()
    shippedTick.value += 1
    tab.value = 'shipped'
    syncTab('shipped')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '出货失败')
  } finally {
    shippingId.value = null
  }
}

async function markDefective(row: OrderRow) {
  try {
    await ElMessageBox.confirm(
      `确认将 ${row.order_no}（${row.product_code || row.header_no}，${row.total_qty} 双）放入次品记录？放入后不再待出货。`,
      '次品',
      { type: 'warning', confirmButtonText: '放入次品', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  markingId.value = row.id
  try {
    await http.post(`/fg-stocks/orders/${row.id}/defective`, {})
    ElMessage.success(`${row.order_no} 已放入次品记录`)
    tab.value = 'defective'
    syncTab('defective')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '放入次品失败')
  } finally {
    markingId.value = null
  }
}

function syncTab(next: WarehouseTab) {
  if (route.path !== '/admin/fg-stocks') return
  if (String(route.query.tab || 'pending') === next) return
  router.replace({ path: '/admin/fg-stocks', query: { ...route.query, tab: next } })
}

function onTab(name: string | number) {
  const next = tabFromQuery(name)
  tab.value = next
  syncTab(next)
  if (next !== 'shipped') load()
}

watch(
  () => route.query.tab,
  (value) => {
    const next = tabFromQuery(value)
    if (next === tab.value) return
    tab.value = next
    if (next !== 'shipped') load()
  },
)

onMounted(() => {
  syncTab(tab.value)
  load()
})
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">成品仓</h1>
      </div>
    </header>

    <el-tabs v-model="tab" class="admin-card warehouse-tabs" @tab-change="onTab">
      <el-tab-pane label="待出货" name="pending">
      <div class="fg-pane">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="订单号 / 客户 / 工厂型号 / 品牌 / 客户型号"
          style="width: 360px"
          @clear="load"
          @keyup.enter="load"
        />
        <div class="spacer" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="load">刷新</el-button>
      </div>

      <div ref="tableHostRef" class="fg-table-host">
            <el-table
              v-loading="loading"
              :data="pagedOrders"
              row-key="row_key"
              stripe
              border
              size="small"
              table-layout="fixed"
              class="no-x-table"
              style="width: 100%"
              :max-height="tableMaxHeight"
              empty-text="暂无完工入库的生产单"
            >
              <el-table-column prop="order_no" label="订单号" min-width="108" show-overflow-tooltip />
              <el-table-column prop="customer_name" label="客户" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.customer_name) }}</template>
              </el-table-column>
              <el-table-column prop="ordered_at" label="下单日期" min-width="78" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.ordered_at) }}</template>
              </el-table-column>
              <el-table-column prop="sort_no" label="序号" width="42" align="center" />
              <el-table-column prop="product_code" label="工厂型号" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.product_code) }}</template>
              </el-table-column>
              <el-table-column label="图片" width="44" align="center">
                <template #default="{ row }">
                  <el-image
                    v-if="row.product_image_url"
                    :src="row.product_image_url"
                    :preview-src-list="[row.product_image_url]"
                    fit="contain"
                    preview-teleported
                    class="product-thumb"
                  />
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column prop="color_name" label="颜色" min-width="48" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.color_name) }}</template>
              </el-table-column>
              <el-table-column prop="fabric" label="面料" min-width="56" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.fabric) }}</template>
              </el-table-column>
              <el-table-column prop="lining" label="内里/垫脚" min-width="64" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.lining) }}</template>
              </el-table-column>
              <el-table-column prop="brand_name" label="品牌" min-width="52" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.brand_name) }}</template>
              </el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" min-width="64" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.customer_sku) }}</template>
              </el-table-column>
              <el-table-column label="码数" align="center">
                <el-table-column v-for="size in sizes" :key="size.id" :label="size.value" width="32" align="center">
                  <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="carton_qty" label="箱数" width="42" align="right" />
              <el-table-column prop="total_qty" label="数量" width="48" align="right" />
              <el-table-column prop="delivery_date" label="交货日期" min-width="78" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.delivery_date) }}</template>
              </el-table-column>
              <el-table-column prop="notes" label="备注" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.notes) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="96" align="center" fixed="right">
                <template #default="{ row }">
                  <el-button link type="success" :loading="shippingId === row.id" @click="shipOrder(row)">出货</el-button>
                  <el-button link type="warning" :loading="markingId === row.id" @click="markDefective(row)">次品</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="admin-pagination">
            <el-pagination
              v-model:current-page="orderPage"
              v-model:page-size="orderPageSize"
              background
              :page-sizes="[10, 20, 50, 100]"
              :total="orders.length"
              layout="total, sizes, prev, pager, next"
            />
          </div>
      </div>
      </el-tab-pane>
      <el-tab-pane label="已出货" name="shipped">
        <ShipmentsAdminView v-if="tab === 'shipped'" :key="shippedTick" embedded />
      </el-tab-pane>
      <el-tab-pane label="次品" name="defective">
        <div v-if="tab === 'defective'" class="fg-pane">
          <div class="admin-toolbar">
            <el-input
              v-model="keyword"
              clearable
              placeholder="订单号 / 客户 / 工厂型号 / 品牌 / 客户型号"
              style="width: 360px"
              @clear="load"
              @keyup.enter="load"
            />
            <div class="spacer" />
            <el-button type="primary" @click="load">查询</el-button>
            <el-button @click="load">刷新</el-button>
          </div>
          <div class="fg-table-host">
            <el-table
              v-loading="loading"
              :data="pagedOrders"
              row-key="row_key"
              stripe
              border
              size="small"
              table-layout="fixed"
              class="no-x-table"
              style="width: 100%"
              :max-height="tableMaxHeight"
              empty-text="暂无次品记录"
            >
              <el-table-column prop="order_no" label="订单号" min-width="108" show-overflow-tooltip />
              <el-table-column prop="customer_name" label="客户" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.customer_name) }}</template>
              </el-table-column>
              <el-table-column prop="ordered_at" label="下单日期" min-width="78" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.ordered_at) }}</template>
              </el-table-column>
              <el-table-column prop="sort_no" label="序号" width="42" align="center" />
              <el-table-column prop="product_code" label="工厂型号" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.product_code) }}</template>
              </el-table-column>
              <el-table-column label="图片" width="44" align="center">
                <template #default="{ row }">
                  <el-image
                    v-if="row.product_image_url"
                    :src="row.product_image_url"
                    :preview-src-list="[row.product_image_url]"
                    fit="contain"
                    preview-teleported
                    class="product-thumb"
                  />
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column prop="color_name" label="颜色" min-width="48" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.color_name) }}</template>
              </el-table-column>
              <el-table-column prop="fabric" label="面料" min-width="56" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.fabric) }}</template>
              </el-table-column>
              <el-table-column prop="lining" label="内里/垫脚" min-width="64" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.lining) }}</template>
              </el-table-column>
              <el-table-column prop="brand_name" label="品牌" min-width="52" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.brand_name) }}</template>
              </el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" min-width="64" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.customer_sku) }}</template>
              </el-table-column>
              <el-table-column label="码数" align="center">
                <el-table-column v-for="size in sizes" :key="size.id" :label="size.value" width="32" align="center">
                  <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="carton_qty" label="箱数" width="42" align="right" />
              <el-table-column prop="total_qty" label="数量" width="48" align="right" />
              <el-table-column prop="delivery_date" label="交货日期" min-width="78" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.delivery_date) }}</template>
              </el-table-column>
              <el-table-column prop="notes" label="备注" min-width="72" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.notes) }}</template>
              </el-table-column>
              <el-table-column prop="defective_at" label="次品时间" min-width="132" show-overflow-tooltip>
                <template #default="{ row }">{{ text(row.defective_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div class="admin-pagination">
            <el-pagination
              v-model:current-page="orderPage"
              v-model:page-size="orderPageSize"
              background
              :page-sizes="[10, 20, 50, 100]"
              :total="orders.length"
              layout="total, sizes, prev, pager, next"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.fg-pane { min-height: 0; }
.fg-pane > .admin-toolbar { flex: 0 0 auto; height: auto; display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; }
.fg-table-host { flex: 1 1 auto; min-height: 0; min-width: 0; }
.spacer { flex: 1; }
.product-thumb { width: 32px; height: 26px; vertical-align: middle; }
.no-x-table { width: 100% !important; max-width: 100%; }
.no-x-table :deep(.el-table__cell) { padding: 3px 0; }
.no-x-table :deep(.cell) { padding: 0 4px; font-size: 12px; line-height: 16px; }
.no-x-table :deep(th .cell) { white-space: normal; word-break: keep-all; }
@media (max-width: 760px) {
  .admin-toolbar :deep(.el-input) { width: 100% !important; }
}
</style>
