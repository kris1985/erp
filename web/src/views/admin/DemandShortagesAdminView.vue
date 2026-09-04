<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">待买</h1>
        <p class="page-desc">生产单正式缺料 · 采购持续跟进</p>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="生产单/物料/供应商"
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
        <span v-if="meta.production_order_count != null" class="muted demand-meta">
          生产单 {{ meta.production_order_count }} 单 · 还要买 {{ toBuyLines }} 项
        </span>
        <div class="spacer" />
        <el-button :loading="loading" @click="reload">刷新</el-button>
        <el-button type="primary" :loading="creating" :disabled="!canCreate" @click="createPo">
          去买料
        </el-button>
      </div>
      <p class="view-hint muted">
        确认生产后正式生成缺料明细；合单按生产单汇总算料，不重复计算销售来源。
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
            prop="header_no"
            column-key="production_order"
            label="生产单"
            :width="colWidth('production_order', 160)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.header_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="products"
            label="工厂型号"
            :width="colWidth('products', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.product_code || '—' }}</template>
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
            column-key="shortage_qty"
            label="缺口"
            :width="colWidth('shortage_qty', 96)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span class="qty-shortage">{{ formatQty(row.to_buy_qty ?? row.shortage_qty) }}</span>
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
const requirementIds = ref<number[]>([])
const meta = reactive({
  production_order_count: null as number | null,
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
  const pairUsages = row.qty_per_pair != null || row.pair_qty != null
    ? [{
        product_code: String(row.product_code || ''),
        pair_qty: Number(row.pair_qty) || 0,
        qty_per_pair: Number(row.qty_per_pair) || 0,
      }]
    : []
  return {
    ...row,
    row_key: `${row.supplier_product_id}-${row.size_id ?? 'x'}-${idx}`,
    product_image_urls: row.product_image_url ? [row.product_image_url] : [],
    pair_usages: pairUsages,
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
      row.header_no,
      row.product_code,
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
  return requirementIds.value.length > 0 && toBuyLines.value > 0
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
    meta.production_order_count = data.production_order_count ?? null
    meta.shortage_lines = data.shortage_lines ?? null
    meta.to_buy_lines = data.to_buy_lines ?? null
    requirementIds.value = Array.isArray(data.requirement_ids) ? data.requirement_ids.map(Number) : []
    allRows.value = (data.lines || []).map((row: any, idx: number) => enrichLine(row, idx))
    selected.value = []
    page.value = 1
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载待买失败')
    allRows.value = []
    requirementIds.value = []
  } finally {
    loading.value = false
    await nextTick()
    measureTableHeight()
    relayoutTable?.()
  }
}

function resolveRequirementIds(): number[] {
  if (!selected.value.length) return [...requirementIds.value]
  return selected.value
    .map((row: any) => Number(row.requirement_id))
    .filter((id: number) => Number.isFinite(id) && id > 0)
}

async function createPo() {
  const requirement_ids = resolveRequirementIds()
  if (!requirement_ids.length) {
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
      lines: [],
      requirement_ids,
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
