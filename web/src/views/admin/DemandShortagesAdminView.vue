<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">待买</h1>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.product_code"
          clearable
          placeholder="物料编号"
          style="width: 140px"
        />
        <el-input
          v-model="filters.product_name"
          clearable
          placeholder="物料名称"
          style="width: 140px"
        />
        <el-input
          v-model="filters.color_name"
          clearable
          placeholder="颜色"
          style="width: 120px"
        />
        <el-input
          v-model="filters.partner_name"
          clearable
          placeholder="供应商"
          style="width: 140px"
        />
        <el-input
          v-model="filters.header_no"
          clearable
          placeholder="生产单"
          style="width: 150px"
        />
        <el-input
          v-model="filters.factory_model"
          clearable
          placeholder="工厂型号"
          style="width: 140px"
        />
        <div class="spacer" />
        <el-button :loading="loading" @click="reload">刷新</el-button>
        <el-button v-permission="'btn.material_shortages.create_po'" type="primary" :loading="creating" :disabled="!canCreate" @click="createPo">
          采购
        </el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="demand-table"
          v-loading="loading"
          :data="displayRows"
          border
          row-key="row_key"
          :max-height="tableMaxHeight"
          :span-method="spanOrders"
          :row-class-name="demandRowClass"
          :cell-class-name="demandCellClass"
          empty-text="没有要买的料。未到的请看采购单。"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            column-key="image"
            label="图片"
            :width="colWidth('image', 72)"
            align="center"
            class-name="mat-image-col"
            header-class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="contain"
                class="product-thumb"
                preview-teleported
              />
              <span v-else class="muted mat-image-empty" />
            </template>
          </el-table-column>
          <el-table-column
            prop="supplier_product_code"
            label="物料编号"
            :width="colWidth('supplier_product_code', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="物料名称"
            :width="colWidth('supplier_product_name', 160)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            column-key="category_name"
            label="分类"
            :width="colWidth('category_name', 100)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.category_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="material_color_name"
            label="颜色"
            :width="colWidth('material_color_name', 80)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.material_color_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="partner_name"
            label="供应商"
            :width="colWidth('partner_name', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.partner_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="header_no"
            column-key="production_order"
            label="生产单"
            :width="colWidth('production_order', 160)"
            resizable
          >
            <template #default="{ row }">{{ row._order?.header_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="products"
            label="工厂型号"
            :width="colWidth('products', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row._order?.product_code || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="product_image"
            label="产品图片"
            :width="colWidth('product_image', 72)"
            align="center"
            class-name="mat-image-col"
            header-class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row._order?.product_image_url"
                :src="row._order.product_image_url"
                :preview-src-list="[row._order.product_image_url]"
                fit="contain"
                class="product-thumb"
                preview-teleported
              />
              <span v-else class="muted mat-image-empty" />
            </template>
          </el-table-column>
          <el-table-column
            column-key="pair_usage"
            label="双数 × 用量"
            :width="colWidth('pair_usage', 120)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">
              <span v-if="row._order">{{ formatQty(row._order.plan_qty) }} * {{ row._order.usage_mixed ? '分码' : formatQty(row._order.qty_per_pair) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="unit"
            label="单位"
            :width="colWidth('unit', 64)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <template v-if="sizeColumns.length">
            <el-table-column label="总用量" align="center">
              <el-table-column
                v-for="size in sizeColumns"
                :key="`req_${size}`"
                :column-key="`req_${size}`"
                :label="size"
                :width="colWidth(`req_${size}`, 72)"
                align="right"
                resizable
              >
                <template #default="{ row }">
                  <span class="qty-total">{{ sizeMetric(row, size, 'required') }}</span>
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column label="库存预警" align="center">
              <el-table-column
                v-for="size in sizeColumns"
                :key="`alert_${size}`"
                :column-key="`alert_${size}`"
                :label="size"
                :width="colWidth(`alert_${size}`, 72)"
                align="right"
                resizable
              >
                <template #default="{ row }">
                  <span :class="alertClass(sizeMetric(row, size, 'alert'))">{{ sizeMetric(row, size, 'alert') }}</span>
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column label="待采购" align="center">
              <el-table-column
                v-for="size in sizeColumns"
                :key="`buy_${size}`"
                :column-key="`buy_${size}`"
                :label="size"
                :width="colWidth(`buy_${size}`, 72)"
                align="right"
                resizable
              >
                <template #default="{ row }">
                  <span class="qty-shortage">{{ sizeMetric(row, size, 'buy') }}</span>
                </template>
              </el-table-column>
            </el-table-column>
          </template>
          <template v-else>
            <el-table-column
              column-key="required_qty"
              label="总用量"
              :width="colWidth('required_qty', 96)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <span class="qty-total">{{ formatQty(row.required_qty) }}</span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="alert_qty"
              label="库存预警"
              :width="colWidth('alert_qty', 108)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <span :class="alertClass(formatQty(row.alert_qty))">{{ formatQty(row.alert_qty) }}</span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="shortage_qty"
              label="待采购"
              :width="colWidth('shortage_qty', 96)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <span class="qty-shortage">{{ formatQty(row.to_buy_qty ?? row.shortage_qty) }}</span>
              </template>
            </el-table-column>
          </template>
          <el-table-column
            column-key="unit_price"
            label="单价"
            :width="colWidth('unit_price', 88)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const props = withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  { embedded: false },
)

const route = useRoute()
const router = useRouter()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('demand-shortages-list', tableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const loading = ref(false)
const creating = ref(false)
const allRows = ref<any[]>([])
const filters = reactive({
  product_code: '',
  product_name: '',
  color_name: '',
  partner_name: '',
  header_no: '',
  factory_model: '',
})

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function formatQty(v: any) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (Number.isInteger(n)) return String(n)
  return n.toFixed(4).replace(/\.?0+$/, '')
}

function toBuyOf(row: any) {
  return Number(row.to_buy_qty ?? row.shortage_qty ?? 0)
}

function enrichLine(row: any, idx: number) {
  const orders = Array.isArray(row.orders) ? row.orders : []
  return {
    ...row,
    row_key: `${row.supplier_product_id}-${row.size_id ?? 'x'}-${idx}`,
    orders,
  }
}

function includesText(value: unknown, query: string) {
  if (!query) return true
  return String(value || '').toLowerCase().includes(query)
}

const filteredRows = computed(() => {
  const code = filters.product_code.trim().toLowerCase()
  const name = filters.product_name.trim().toLowerCase()
  const color = filters.color_name.trim().toLowerCase()
  const partner = filters.partner_name.trim().toLowerCase()
  const header = filters.header_no.trim().toLowerCase()
  const model = filters.factory_model.trim().toLowerCase()
  return allRows.value.filter((row) => {
    if (!includesText(row.supplier_product_code, code)) return false
    if (!includesText(row.supplier_product_name, name)) return false
    if (!includesText(row.material_color_name, color)) return false
    if (!includesText(row.partner_name, partner)) return false
    const orders = Array.isArray(row.orders) ? row.orders : []
    if (header) {
      const headers = [row.header_no, ...orders.map((order: any) => order.header_no)]
      if (!headers.some((value) => includesText(value, header))) return false
    }
    if (model) {
      const models = [row.product_code, ...orders.map((order: any) => order.product_code)]
      if (!models.some((value) => includesText(value, model))) return false
    }
    return true
  })
})

const SPLIT_COLUMNS = new Set(['production_order', 'products', 'product_image', 'pair_usage'])

function demandRowClass({ row }: { row: any }) {
  return row._groupIndex % 2 === 1 ? 'demand-row--stripe' : ''
}

function demandCellClass({ column }: { column: { type?: string; columnKey?: string; property?: string } }) {
  const key = column.columnKey || column.property || column.type || ''
  return SPLIT_COLUMNS.has(key) ? 'demand-cell--split' : 'demand-cell--merge'
}

function sizeColumnSize(key: string) {
  for (const prefix of ['req_', 'alert_', 'wh_', 'buy_']) {
    if (key.startsWith(prefix)) return key.slice(prefix.length)
  }
  return ''
}

function spanOrders({ row, column }: { row: any; column: { type?: string; columnKey?: string; property?: string } }) {
  const key = column.columnKey || column.property || column.type || ''
  const count = Number(row._orderCount) || 1
  const sizeKey = sizeColumnSize(key)
  if (sizeKey && sizeColumns.value.length && !row.has_sizes) {
    if (row._orderIndex !== 0) return [0, 0]
    if (sizeKey !== sizeColumns.value[0]) return [0, 0]
    return [count, sizeColumns.value.length]
  }
  if (SPLIT_COLUMNS.has(key)) return [1, 1]
  if (row._orderIndex === 0) return [count, 1]
  return [0, 0]
}

const materialRows = computed(() => {
  const groups = new Map<string, any>()
  for (const row of filteredRows.value) {
    const key = String(row.supplier_product_id)
    let group = groups.get(key)
    if (!group) {
      group = {
        ...row,
        requirement_ids: [],
        orders: [],
        size_qty: {},
        has_sizes: false,
        row_key: `mat-${row.supplier_product_id}`,
      }
      groups.set(key, group)
    }
    const ids = Array.isArray(row.requirement_ids) ? row.requirement_ids : []
    if (row.requirement_id != null) ids.push(row.requirement_id)
    group.requirement_ids.push(...ids)
    for (const order of row.orders || []) {
      const left = Number(order.unpurchased_qty)
      if (Number.isFinite(left) && left <= 0) continue
      const id = order.header_id ?? order.requirement_id
      const found = group.orders.find((item: any) => (item.header_id ?? item.requirement_id) === id)
      if (!found) group.orders.push({ ...order, _usages: [order.qty_per_pair] })
      else found._usages.push(order.qty_per_pair)
    }
    if (row.size_value) {
      group.has_sizes = true
      group.size_qty[String(row.size_value)] = {
        required: Number(row.required_qty || 0),
        warehouse: Number(row.warehouse_qty || 0),
        alert: Number(row.alert_qty || 0),
        buy: Number(row.to_buy_qty ?? row.shortage_qty ?? 0),
        sort: Number(row.size_sort_order || 0),
      }
    }
  }
  return [...groups.values()].map((group) => {
    const requirement_ids = [...new Set(group.requirement_ids.map((id: any) => Number(id)).filter((id: number) => id > 0))]
    const orders = group.orders.map((order: any) => {
      const usages = [...new Set((order._usages || []).map((value: any) => String(value ?? '')))]
      return {
        ...order,
        qty_per_pair: usages.length === 1 ? order._usages[0] : null,
        usage_mixed: usages.length > 1,
      }
    })
    const toBuy = group.has_sizes
      ? Object.values(group.size_qty as Record<string, { buy: number }>).reduce((sum, item) => sum + Number(item.buy || 0), 0)
      : Number(group.to_buy_qty ?? group.shortage_qty ?? 0)
    return {
      ...group,
      requirement_ids,
      requirement_id: requirement_ids[0],
      orders,
      to_buy_qty: toBuy,
      shortage_qty: toBuy,
    }
  }).filter((group) => Number(group.to_buy_qty) > 0)
})

const sizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const row of materialRows.value) {
    for (const [size, info] of Object.entries(row.size_qty || {}) as [string, { sort?: number }][]) {
      const sort = Number(info?.sort || 0)
      if (!order.has(size)) order.set(size, sort)
    }
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})

function alertClass(text: string) {
  const n = Number(text)
  if (!Number.isFinite(n) || n >= 0) return ''
  return 'qty-shortage'
}

function sizeMetric(row: any, size: string, metric: 'required' | 'warehouse' | 'alert' | 'buy') {
  if (!row.has_sizes) {
    if (size !== sizeColumns.value[0]) return ''
    if (metric === 'required') return formatQty(row.required_qty)
    if (metric === 'warehouse') return formatQty(row.warehouse_qty)
    if (metric === 'alert') return formatQty(row.alert_qty)
    return formatQty(row.to_buy_qty ?? row.shortage_qty)
  }
  const bucket = row.size_qty?.[size]
  if (!bucket) return '—'
  return formatQty(bucket[metric])
}

const displayRows = computed(() => {
  const lines: any[] = []
  materialRows.value.forEach((row, groupIndex) => {
    const orders = row.orders?.length ? row.orders : [null]
    orders.forEach((order: any, index: number) => {
      lines.push({
        ...row,
        _order: order,
        _orderIndex: index,
        _orderCount: orders.length,
        _groupIndex: groupIndex,
        row_key: `${row.row_key}-${order?.requirement_id ?? index}`,
      })
    })
  })
  return lines
})

const buyRows = computed(() => allRows.value.filter((row) => toBuyOf(row) > 0))

const canCreate = computed(() => {
  if (creating.value || loading.value) return false
  return buyRows.value.length > 0
})

async function reload() {
  loading.value = true
  try {
    const res: any = await http.get('/sales-orders/demand-shortages', {
      params: { include_shared: true },
    })
    const data = res.data || {}
    const lines = (data.lines || []).map((row: any, idx: number) => enrichLine(row, idx))
    allRows.value = lines
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载待买失败')
    allRows.value = []
  } finally {
    loading.value = false
    await nextTick()
    measureTableHeight()
    relayoutTable?.()
  }
}

function requirementIdsOf(rows: any[]) {
  const ids = rows.flatMap((row) => {
    const many = Array.isArray(row.requirement_ids) ? row.requirement_ids : []
    const one = row.requirement_id != null ? [row.requirement_id] : []
    return [...many, ...one]
  })
  return [...new Set(ids.map((id) => Number(id)).filter((id) => Number.isFinite(id) && id > 0))]
}

async function createPo() {
  const requirement_ids = requirementIdsOf(buyRows.value)
  if (!requirement_ids.length) {
    ElMessage.warning('没有要买的料')
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认采购？',
      '采购',
      { type: 'warning', confirmButtonText: '确认' },
    )
  } catch {
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/sales-orders/lines/purchase-drafts-from-mrp', {
      lines: [],
      requirement_ids,
      include_shared: true,
      shortages_only: true,
    })
    const count = Number(res.data?.count || res.data?.items?.length || 0)
    ElMessage.success(count ? `已开 ${count} 张草稿，还没发给供应商` : '已处理')
    await reload()
    await router.replace({
      path: '/admin/purchase',
      query: { tab: 'orders', refresh: String(Date.now()) },
    })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成失败')
  } finally {
    creating.value = false
  }
}

watch(
  () => [String(route.query.tab || ''), String(route.query.source || '')],
  ([tab, source], prev) => {
    if (!props.embedded) return
    if (tab === prev?.[0] && source === prev?.[1]) return
    if (tab === 'buy' || tab === 'demand' || tab === 'demand-shortage' || !tab) {
      if (source !== 'stock') void reload()
    }
  },
)

watch(sizeColumns, () => {
  void nextTick(() => tableRef.value?.doLayout?.())
})

onMounted(() => {
  void reload()
})
</script>

<style scoped>
.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.demand-table :deep(td.demand-cell--merge) {
  vertical-align: middle;
}
.demand-table :deep(td.demand-cell--split) {
  vertical-align: top;
}
.demand-table :deep(.demand-row--stripe > td.el-table__cell) {
  background: var(--ws-table-stripe, #eef2f7);
}
.qty-total,
.qty-shortage {
  font-variant-numeric: tabular-nums;
}
.qty-total {
  color: var(--el-text-color-primary);
}
.qty-shortage {
  color: var(--el-color-danger);
  font-weight: 700;
}
:deep(td.mat-image-col) {
  padding: 2px !important;
}
.mat-image-empty {
  display: inline-block;
  width: 100%;
  aspect-ratio: 1 / 1;
}
.purchase-panel {
  min-width: 0;
}
.spacer {
  flex: 1;
}
</style>
