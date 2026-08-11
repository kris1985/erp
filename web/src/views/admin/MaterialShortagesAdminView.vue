<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">缺料汇总</h1>
        <p class="page-desc">待采购缺口 · 按供应商合并生成采购草稿</p>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="生产单/物料/供应商"
          style="width: 200px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          placeholder="供应商"
          style="width: 180px"
          @change="search"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-checkbox v-model="filters.rush_only" @change="search">仅插单</el-checkbox>
        <div class="spacer" />
        <el-button @click="search" :loading="loading">查询</el-button>
        <el-button :loading="exporting" @click="exportXlsx">导出 Excel</el-button>
        <el-button :loading="pushing" @click="pushIm">推送企微</el-button>
        <el-button type="primary" :disabled="!selected.length" @click="createPo">生成采购草稿</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table
        ref="tableRef"
        :data="rows"
        stripe
        border
        row-key="id"
        :max-height="tableMaxHeight"
        @selection-change="(v: any[]) => (selected = v)"
        @header-dragend="onHeaderDragend"
      >
        <el-table-column type="selection" :width="colWidth('selection', 48)" align="center" :selectable="canSelect" />
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
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="supplier_product_code"
          label="物料编号"
          :width="colWidth('supplier_product_code', 120)"
          align="left"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="supplier_product_name"
          label="物料名称"
          :width="colWidth('supplier_product_name', 160)"
          align="left"
          show-overflow-tooltip
          resizable
        />
        <el-table-column column-key="color_name" label="颜色" :width="colWidth('color_name', 80)" align="center" resizable>
          <template #default="{ row }">{{ row.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="partner_name" label="供应商" :width="colWidth('partner_name', 120)" align="left" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ row.partner_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="order_no" label="生产单" :width="colWidth('order_no', 140)" align="left" show-overflow-tooltip resizable>
          <template #default="{ row }">
            {{ row.order_no }}
            <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 6px">插单</el-tag>
          </template>
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
              v-if="row.product_image_url"
              :src="row.product_image_url"
              :preview-src-list="[row.product_image_url]"
              fit="contain"
              class="product-thumb"
              preview-teleported
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column column-key="size_value" label="码数" :width="colWidth('size_value', 72)" align="center" resizable>
          <template #default="{ row }">{{ row.size_value || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="usage_pairs"
          label="用量×双数"
          :width="colWidth('usage_pairs', 140)"
          align="left"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ formatUsagePairs(row) }}</template>
        </el-table-column>
        <el-table-column prop="required_qty" label="总用量" :width="colWidth('required_qty', 80)" align="right" header-align="right" resizable />
        <el-table-column prop="shortage_qty" label="缺口" :width="colWidth('shortage_qty', 80)" align="right" header-align="right" resizable />
        <el-table-column column-key="unit" label="单位" :width="colWidth('unit', 64)" align="center" resizable>
          <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="unit_price"
          label="单价"
          :width="colWidth('unit_price', 88)"
          align="right"
          header-align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column
          column-key="expected_ready"
          label="预计到料日"
          :width="colWidth('expected_ready', 110)"
          align="center"
          resizable
        >
          <template #default="{ row }">{{ row.expected_ready_date || '—' }}</template>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
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
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('shortages-list', tableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const selected = ref<any[]>([])
const suppliers = ref<any[]>([])
const loading = ref(false)
const exporting = ref(false)
const pushing = ref(false)
/** 固定计入库存池（口径跟租户齐套一致，不再页面手拨） */
const includeShared = true
const filters = reactive({
  keyword: '',
  partner_id: null as number | null,
  rush_only: false,
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function formatUsagePairs(row: any) {
  const per = formatNum(row.qty_per_pair)
  const qty = row.order_qty
  if (per === '—' && (qty === null || qty === undefined || qty === '')) return '—'
  const pairs = qty === null || qty === undefined || Number.isNaN(Number(qty)) ? '—' : String(qty)
  return `${per} × ${pairs}`
}

function canSelect(row: any) {
  if (row.can_create_draft != null) return Boolean(row.can_create_draft)
  return Number(row.to_buy_qty) > 0 && !row.has_purchase
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/material-shortages', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        include_shared: includeShared,
        keyword: filters.keyword || undefined,
        partner_id: filters.partner_id || undefined,
        rush_only: filters.rush_only || undefined,
        hide_purchased: true,
      },
    })
    const payload = res.data
    rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
    total.value = payload?.total ?? rows.value.length
    selected.value = []
  } finally {
    loading.value = false
    await nextTick()
    measureTableHeight()
    relayoutTable?.()
  }
}

function search() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function filterParams() {
  return {
    keyword: filters.keyword || undefined,
    partner_id: filters.partner_id || undefined,
    rush_only: filters.rush_only || undefined,
    hide_purchased: true,
  }
}

async function exportXlsx() {
  exporting.value = true
  try {
    const res: any = await http.get('/material-shortages/export.xlsx', {
      params: filterParams(),
      responseType: 'blob',
    })
    const blob = res instanceof Blob ? res : new Blob([res.data || res], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `缺料催办_${new Date().toISOString().slice(0, 10)}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出')
  } catch (e: any) {
    ElMessage.error(e?.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

async function pushIm() {
  pushing.value = true
  try {
    const res: any = await http.post('/material-shortages/push-im', filterParams())
    const okPush = res?.data?.result?.ok
    if (okPush) ElMessage.success('已推送到企微/钉钉')
    else ElMessage.warning(res?.data?.result?.error || '已请求推送，请检查 Webhook 回执')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '推送失败')
  } finally {
    pushing.value = false
  }
}

async function createPo() {
  const picks = selected.value.filter((r) =>
    r.can_create_draft != null ? Boolean(r.can_create_draft) : Number(r.to_buy_qty) > 0 && !r.has_purchase,
  )
  if (!picks.length) {
    ElMessage.warning('请选择尚未生成过采购的待购行（每行仅可生成一次草稿）')
    return
  }
  const res: any = await http.post('/purchase-orders/from-shortages', {
    requirement_ids: picks.map((r) => r.id),
    include_shared: includeShared,
  })
  const created = res.data || []
  if (!created.length) {
    ElMessage.warning('没有可生成的采购（该行可能已生成过草稿或已下单）')
    await load()
    return
  }
  ElMessage.success(`已生成 ${created.length} 张采购草稿`)
  selected.value = []
  await load()
  await router.replace({
    path: '/admin/purchase',
    query: { tab: 'orders', refresh: String(Date.now()) },
  })
}

watch(
  () => String(route.query.tab || ''),
  (tab, prev) => {
    if (!props.embedded) return
    if (tab === prev) return
    if (tab === 'shortages' || tab === 'shortage') {
      void load()
    }
  },
)

onMounted(async () => {
  await loadSuppliers()
  await load()
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
:deep(td.mat-image-col) {
  padding: 2px !important;
}
:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}
:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}
:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.muted {
  color: #94a3b8;
  font-weight: 400;
}
.purchase-panel {
  min-width: 0;
}
</style>
