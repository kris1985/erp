<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">待买</h1>
        <p class="page-desc">接单后还没排的料 · 按物料汇总</p>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="销售单/物料/供应商"
          style="width: 200px"
          @clear="applyFilter"
          @keyup.enter="applyFilter"
        />
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          placeholder="供应商"
          style="width: 180px"
          @change="applyFilter"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-checkbox v-model="onlyToBuy" @change="applyFilter">仅还要买</el-checkbox>
        <span v-if="meta.demand_count != null" class="muted demand-meta">
          待排 {{ meta.demand_count }} 行 · 还要买 {{ toBuyLines }} 项
        </span>
        <div class="spacer" />
        <el-button :loading="loading" @click="reload">刷新</el-button>
        <el-button type="primary" :loading="creating" :disabled="!canCreate" @click="createPo">
          去买料
        </el-button>
      </div>
      <p class="view-hint muted">
        接单后、还没排进执行单的料。已开草稿或在途会从「还要买」扣掉。开裁齐套请看执行单。
      </p>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="pagedRows"
          stripe
          border
          row-key="row_key"
          :max-height="tableMaxHeight"
          empty-text="没有要买的料。未到的请看采购单。"
          @selection-change="(v: any[]) => (selected = v)"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            type="selection"
            :width="colWidth('selection', 48)"
            align="center"
            :selectable="(row: any) => Number(row.to_buy_qty ?? row.shortage_qty) > 0"
          />
          <el-table-column
            column-key="image"
            label="物料图片"
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
            prop="partner_name"
            label="供应商"
            :width="colWidth('partner_name', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.partner_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="why"
            label="来源"
            :width="colWidth('why', 88)"
            resizable
          >
            <template #default>
              <el-tag size="small" type="info" effect="plain">接单备料</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            column-key="sales_orders"
            label="销售单"
            :width="colWidth('sales_orders', 160)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.sales_order_nos || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="products"
            label="产品编号"
            :width="colWidth('products', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.product_codes || '—' }}</template>
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
              <div v-if="row.product_image_urls?.length" class="product-thumbs">
                <el-image
                  v-for="(url, i) in row.product_image_urls"
                  :key="`${url}-${i}`"
                  :src="url"
                  :preview-src-list="row.product_image_urls"
                  :initial-index="i"
                  fit="contain"
                  class="product-thumb"
                  preview-teleported
                />
              </div>
              <span v-else class="muted mat-image-empty" />
            </template>
          </el-table-column>
          <el-table-column
            column-key="pair_usage"
            label="双数 × 用量"
            :width="colWidth('pair_usage', 120)"
            resizable
          >
            <template #default="{ row }">
              <div v-if="row.pair_usages?.length" class="pair-usage">
                <div v-for="(u, i) in row.pair_usages" :key="i" class="pair-usage-row">
                  <span v-if="row.pair_usages.length > 1 && u.product_code" class="pair-usage-code">{{ u.product_code }}</span>
                  <span>{{ formatQty(u.pair_qty) }} * {{ formatQty(u.qty_per_pair) }}</span>
                </div>
              </div>
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
          <el-table-column
            column-key="size_value"
            label="码数"
            :width="colWidth('size_value', 72)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="cover"
            label="覆盖"
            :width="colWidth('cover', 200)"
            resizable
          >
            <template #default="{ row }">
              <MaterialCoverCell
                :required="row.required_qty"
                :pool="row.pool_credit_qty ?? row.shared_qty"
                :transit="row.transit_credit_qty ?? row.in_transit_qty"
                :draft="row.draft_qty"
                :to-buy="row.to_buy_qty ?? row.shortage_qty"
              />
            </template>
          </el-table-column>
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
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="filteredRows.length"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import MaterialCoverCell from '@/components/MaterialCoverCell.vue'
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
const onlyToBuy = ref(true)
const allRows = ref<any[]>([])
const selected = ref<any[]>([])
const suppliers = ref<any[]>([])
const refs = ref<{ sales_order_id: number; line_id: number }[]>([])
const meta = reactive({
  demand_count: null as number | null,
  shortage_lines: null as number | null,
  to_buy_lines: null as number | null,
})
const filters = reactive({
  keyword: '',
  partner_id: null as number | null,
})
const page = ref(1)
const pageSize = ref(20)

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

const toBuyLines = computed(() => Number(meta.to_buy_lines ?? meta.shortage_lines ?? 0))

function enrichLine(row: any, idx: number) {
  const sources = Array.isArray(row.sources) ? row.sources : []
  const orderNos = [
    ...new Set(sources.map((s: any) => s.order_no).filter(Boolean)),
  ]
  const productCodes = [
    ...new Set(sources.map((s: any) => s.product_code).filter(Boolean)),
  ]
  const productImageUrls = [
    ...new Set(sources.map((s: any) => s.product_image_url).filter(Boolean)),
  ]
  const usageMap = new Map<string, { product_code: string; pair_qty: number; qty_per_pair: number }>()
  for (const s of sources) {
    const code = String(s.product_code || '')
    const per = Number(s.qty_per_pair)
    const pairs = Number(s.pair_qty)
    if (!Number.isFinite(per) && !Number.isFinite(pairs)) continue
    const key = `${code}:${Number.isFinite(per) ? per : ''}`
    const cur = usageMap.get(key)
    const add = Number.isFinite(pairs) ? pairs : 0
    if (cur) cur.pair_qty += add
    else usageMap.set(key, { product_code: code, pair_qty: add, qty_per_pair: Number.isFinite(per) ? per : Number(row.qty_per_pair) || 0 })
  }
  let pairUsages = [...usageMap.values()]
  if (!pairUsages.length && (row.qty_per_pair != null || row.pair_qty != null)) {
    pairUsages = [{
      product_code: productCodes[0] || '',
      pair_qty: Number(row.pair_qty) || 0,
      qty_per_pair: Number(row.qty_per_pair) || 0,
    }]
  }
  const lineRefs = []
  for (const s of sources) {
    const key = String(s.key || '')
    if (!key.startsWith('so_line:')) continue
    const lid = Number(key.slice('so_line:'.length))
    if (!Number.isFinite(lid)) continue
    lineRefs.push(lid)
  }
  return {
    ...row,
    row_key: `${row.supplier_product_id}-${row.size_id ?? 'x'}-${idx}`,
    sales_order_nos: orderNos.join(' / ') || '—',
    product_codes: productCodes.join(' / ') || '—',
    product_image_urls: productImageUrls,
    pair_usages: pairUsages,
    line_ids: [...new Set(lineRefs)],
  }
}

const filteredRows = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  const pid = filters.partner_id
  return allRows.value.filter((row) => {
    if (onlyToBuy.value && toBuyOf(row) <= 0) return false
    if (pid && Number(row.partner_id) !== Number(pid)) return false
    if (!kw) return true
    const hay = [
      row.supplier_product_code,
      row.supplier_product_name,
      row.partner_name,
      row.sales_order_nos,
      row.product_codes,
      row.size_value,
    ]
      .map((x) => String(x || '').toLowerCase())
      .join(' ')
    return hay.includes(kw)
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

const canCreate = computed(() => {
  if (creating.value || loading.value) return false
  if (selected.value.length) return selected.value.some((r) => toBuyOf(r) > 0)
  return refs.value.length > 0 && toBuyLines.value > 0
})

function applyFilter() {
  page.value = 1
}

function onPageChange() {
  selected.value = []
  void nextTick(measureTableHeight)
}

function onPageSizeChange() {
  page.value = 1
  selected.value = []
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function reload() {
  loading.value = true
  try {
    const res: any = await http.get('/sales-orders/demand-shortages', {
      params: { include_shared: true },
    })
    const data = res.data || {}
    meta.demand_count = data.demand_count ?? null
    meta.shortage_lines = data.shortage_lines ?? null
    meta.to_buy_lines = data.to_buy_lines ?? null
    refs.value = Array.isArray(data.refs) ? data.refs : []
    allRows.value = (data.lines || []).map((row: any, idx: number) => enrichLine(row, idx))
    selected.value = []
    page.value = 1
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载待买失败')
    allRows.value = []
    refs.value = []
  } finally {
    loading.value = false
    await nextTick()
    measureTableHeight()
    relayoutTable?.()
  }
}

function resolveCreateRefs(): { sales_order_id: number; line_id: number }[] {
  if (!selected.value.length) return [...refs.value]
  const want = new Set<number>()
  for (const row of selected.value) {
    for (const lid of row.line_ids || []) want.add(Number(lid))
  }
  if (!want.size) return [...refs.value]
  return refs.value.filter((r) => want.has(Number(r.line_id)))
}

async function createPo() {
  const lines = resolveCreateRefs()
  if (!lines.length) {
    ElMessage.warning('没有要买的料')
    return
  }
  const n = selected.value.length
    ? selected.value.filter((r) => toBuyOf(r) > 0).length
    : Number(meta.to_buy_lines || filteredRows.value.length || 0)
  try {
    await ElMessageBox.confirm(
      `按当前待买（约 ${n} 项）生成采购草稿？\n草稿还没发给供应商，下一步在采购单里下单。`,
      '去买料',
      { type: 'warning', confirmButtonText: '生成草稿' },
    )
  } catch {
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/sales-orders/lines/purchase-drafts-from-mrp', {
      lines,
      include_shared: true,
      shortages_only: true,
    })
    const count = Number(res.data?.count || res.data?.items?.length || 0)
    ElMessage.success(count ? `已开 ${count} 张草稿，还没发给供应商` : '已处理')
    selected.value = []
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

onMounted(async () => {
  await loadSuppliers()
  await reload()
})
</script>

<style scoped>
.view-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.4;
}
.demand-meta {
  font-size: 12px;
}
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
.product-thumbs {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pair-usage {
  font-size: 12px;
  line-height: 1.35;
}
.pair-usage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0 6px;
}
.pair-usage-code {
  font-weight: 600;
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
