<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
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

type WarehouseTab = 'pending' | 'shipped' | 'statemented' | 'defective'

const route = useRoute()
const router = useRouter()
function tabFromQuery(value: unknown): WarehouseTab {
  if (value === 'shipped' || value === 'statemented' || value === 'defective') return value
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
const pendingTableRef = ref()
const defectiveTableRef = ref()
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('fg-stocks-pending', pendingTableRef, {
  flexKey: 'notes',
  flexDefaultMin: 72,
  fitToContainer: true,
  groupEdgeResize: true,
})
const {
  colWidth: defectiveColWidth,
  onHeaderDragend: onDefectiveHeaderDragend,
  relayoutTable: relayoutDefectiveTable,
} = useTableColWidths('fg-stocks-defective', defectiveTableRef, {
  flexKey: 'notes',
  flexDefaultMin: 72,
  fitToContainer: true,
  groupEdgeResize: true,
})
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
  if (tab.value === 'shipped' || tab.value === 'statemented') return
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
    relayoutTable()
    relayoutDefectiveTable()
    requestAnimationFrame(() => scheduleMeasure())
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

function pendingActions() {
  return [
    { cmd: 'ship', label: '出货' },
    { cmd: 'defective', label: '次品' },
  ]
}

function runPendingAction(row: OrderRow, cmd: string) {
  if (cmd === 'ship') return shipOrder(row)
  if (cmd === 'defective') return markDefective(row)
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
  if (next === 'pending' || next === 'defective') load()
}

watch(
  () => route.query.tab,
  (value) => {
    const next = tabFromQuery(value)
    if (next === tab.value) return
    tab.value = next
    if (next === 'pending' || next === 'defective') load()
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
              ref="pendingTableRef"
              v-loading="loading"
              :data="pagedOrders"
              row-key="row_key"
              stripe
              border
              size="small"
              class="no-x-table"
              style="width: 100%"
              :height="tableMaxHeight"
              empty-text="暂无完工入库的生产单"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column prop="order_no" label="订单号" :width="colWidth('order_no', 108)" show-overflow-tooltip resizable />
              <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.customer_name) }}</template>
              </el-table-column>
              <el-table-column prop="ordered_at" label="下单日期" :width="colWidth('ordered_at', 78)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.ordered_at) }}</template>
              </el-table-column>
              <el-table-column prop="product_code" label="工厂型号" :width="colWidth('product_code', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.product_code) }}</template>
              </el-table-column>
              <el-table-column column-key="image" label="图片" :width="colWidth('image', 44)" align="center" resizable>
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
              <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 48)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.color_name) }}</template>
              </el-table-column>
              <el-table-column prop="fabric" label="面料" :width="colWidth('fabric', 56)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.fabric) }}</template>
              </el-table-column>
              <el-table-column prop="lining" label="内里/垫脚" :width="colWidth('lining', 64)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.lining) }}</template>
              </el-table-column>
              <el-table-column prop="brand_name" label="品牌" :width="colWidth('brand_name', 52)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.brand_name) }}</template>
              </el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" :width="colWidth('customer_sku', 64)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.customer_sku) }}</template>
              </el-table-column>
              <el-table-column column-key="sizes" label="码数" align="center">
                <el-table-column
                  v-for="size in sizes"
                  :key="size.id"
                  :column-key="`size_${size.id}`"
                  :label="size.value"
                  :width="colWidth(`size_${size.id}`, 32)"
                  align="center"
                  resizable
                >
                  <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="carton_qty" label="箱数" :width="colWidth('carton_qty', 42)" align="right" resizable />
              <el-table-column prop="total_qty" label="数量" :width="colWidth('total_qty', 48)" align="right" resizable />
              <el-table-column prop="notes" label="备注" :width="colWidth('notes', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.notes) }}</template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="72" align="center" fixed="right" :resizable="false">
                <template #default="{ row }">
                  <div class="row-actions">
                    <el-dropdown trigger="click" @command="(cmd: string) => runPendingAction(row, cmd)">
                      <el-button
                        link
                        type="primary"
                        :icon="MoreFilled"
                        :loading="shippingId === row.id || markingId === row.id"
                        aria-label="更多操作"
                      />
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item v-for="action in pendingActions()" :key="action.cmd" :command="action.cmd">
                            {{ action.label }}
                          </el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
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
      <el-tab-pane label="已对账" name="statemented">
        <ShipmentsAdminView v-if="tab === 'statemented'" statemented embedded />
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
              ref="defectiveTableRef"
              v-loading="loading"
              :data="pagedOrders"
              row-key="row_key"
              stripe
              border
              size="small"
              class="no-x-table"
              style="width: 100%"
              :height="tableMaxHeight"
              empty-text="暂无次品记录"
              @header-dragend="onDefectiveHeaderDragend"
            >
              <el-table-column prop="order_no" label="订单号" :width="defectiveColWidth('order_no', 108)" show-overflow-tooltip resizable />
              <el-table-column prop="customer_name" label="客户" :width="defectiveColWidth('customer_name', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.customer_name) }}</template>
              </el-table-column>
              <el-table-column prop="ordered_at" label="下单日期" :width="defectiveColWidth('ordered_at', 78)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.ordered_at) }}</template>
              </el-table-column>
              <el-table-column prop="product_code" label="工厂型号" :width="defectiveColWidth('product_code', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.product_code) }}</template>
              </el-table-column>
              <el-table-column column-key="image" label="图片" :width="defectiveColWidth('image', 44)" align="center" resizable>
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
              <el-table-column prop="color_name" label="颜色" :width="defectiveColWidth('color_name', 48)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.color_name) }}</template>
              </el-table-column>
              <el-table-column prop="fabric" label="面料" :width="defectiveColWidth('fabric', 56)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.fabric) }}</template>
              </el-table-column>
              <el-table-column prop="lining" label="内里/垫脚" :width="defectiveColWidth('lining', 64)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.lining) }}</template>
              </el-table-column>
              <el-table-column prop="brand_name" label="品牌" :width="defectiveColWidth('brand_name', 52)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.brand_name) }}</template>
              </el-table-column>
              <el-table-column prop="customer_sku" label="客户型号" :width="defectiveColWidth('customer_sku', 64)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.customer_sku) }}</template>
              </el-table-column>
              <el-table-column column-key="sizes" label="码数" align="center">
                <el-table-column
                  v-for="size in sizes"
                  :key="size.id"
                  :column-key="`size_${size.id}`"
                  :label="size.value"
                  :width="defectiveColWidth(`size_${size.id}`, 32)"
                  align="center"
                  resizable
                >
                  <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="carton_qty" label="箱数" :width="defectiveColWidth('carton_qty', 42)" align="right" resizable />
              <el-table-column prop="total_qty" label="数量" :width="defectiveColWidth('total_qty', 48)" align="right" resizable />
              <el-table-column prop="notes" label="备注" :width="defectiveColWidth('notes', 72)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ text(row.notes) }}</template>
              </el-table-column>
              <el-table-column prop="defective_at" label="次品时间" :width="defectiveColWidth('defective_at', 132)" show-overflow-tooltip resizable>
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
.warehouse-tabs {
  flex: 1 1 auto;
  min-height: 0;
}
.warehouse-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.warehouse-tabs :deep(.el-tab-pane) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fg-pane {
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.fg-pane > .admin-toolbar { flex: 0 0 auto; height: auto; display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; }
.fg-table-host { flex: 1 1 auto; min-height: 0; min-width: 0; }
.fg-pane > .admin-pagination { flex: 0 0 auto; margin-top: 0; }
.spacer { flex: 1; }
.product-thumb { width: 32px; height: 26px; vertical-align: middle; }
.row-actions {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}
.row-actions :deep(.el-dropdown) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
.row-actions :deep(.el-button) { margin: 0; }
.no-x-table { width: 100% !important; max-width: 100%; }
.no-x-table :deep(.el-table__cell) { padding: 3px 0; }
.no-x-table :deep(.cell) { padding: 0 4px; font-size: 12px; line-height: 16px; }
.no-x-table :deep(th .cell) { white-space: normal; word-break: keep-all; }
@media (max-width: 760px) {
  .admin-toolbar :deep(.el-input) { width: 100% !important; }
}
</style>
