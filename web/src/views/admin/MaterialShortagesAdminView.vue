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
          placeholder="订单/物料/供应商"
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
        <el-checkbox v-model="filters.hidePurchased" @change="search">隐藏已采购</el-checkbox>
        <el-checkbox v-model="showDetail">显示明细</el-checkbox>
        <div class="spacer" />
        <el-button @click="search" :loading="loading">查询</el-button>
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
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 140)" align="left" resizable>
          <template #default="{ row }">
            {{ row.order_no }}
            <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 6px">插单</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="partner_name" label="供应商" :width="colWidth('partner_name', 120)" align="left" resizable>
          <template #default="{ row }">{{ row.partner_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料编码" :width="colWidth('supplier_product_code', 120)" align="left" resizable />
        <el-table-column
          prop="supplier_product_name"
          label="物料"
          :width="colWidth('supplier_product_name', 160)"
          align="left"
          resizable
        />
        <el-table-column column-key="size_value" label="尺码" :width="colWidth('size_value', 72)" align="center" resizable>
          <template #default="{ row }">{{ row.size_value || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="采购状态" label="采购状态" :width="colWidth('采购状态', 110)" align="left" resizable>
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.purchase_status)" size="small" effect="plain">
              {{ row.purchase_status_label || '待采购' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="required_qty" label="需求" :width="colWidth('required_qty', 80)" align="right" header-align="right" resizable />
        <el-table-column
          v-if="showDetail"
          prop="arrived_qty"
          label="已到"
          :width="colWidth('arrived_qty', 70)"
          align="right"
          header-align="right"
          resizable
        />
        <el-table-column
          v-if="showDetail"
          column-key="draft_qty"
          label="草稿"
          :width="colWidth('draft_qty', 70)"
          align="right"
          header-align="right"
          resizable
        >
          <template #default="{ row }">{{ formatNum(row.draft_qty) }}</template>
        </el-table-column>
        <el-table-column
          v-if="showDetail"
          column-key="in_transit"
          label="在途"
          :width="colWidth('in_transit', 70)"
          align="right"
          header-align="right"
          resizable
        >
          <template #default="{ row }">{{ formatNum(row.in_transit_qty) }}</template>
        </el-table-column>
        <el-table-column
          v-if="showDetail"
          prop="shared_qty"
          label="池承诺"
          :width="colWidth('shared_qty', 90)"
          align="right"
          header-align="right"
          resizable
        />
        <el-table-column
          v-if="showDetail"
          prop="pool_qty"
          label="池余额"
          :width="colWidth('pool_qty', 90)"
          align="right"
          header-align="right"
          resizable
        />
        <el-table-column prop="shortage_qty" label="缺口" :width="colWidth('shortage_qty', 80)" align="right" header-align="right" resizable />
        <el-table-column
          column-key="expected_ready"
          label="预计到料日"
          :width="colWidth('expected_ready', 110)"
          align="center"
          resizable
        >
          <template #default="{ row }">{{ row.expected_ready_date || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="to_purchase" label="待购" :width="colWidth('to_purchase', 80)" align="right" header-align="right" resizable>
          <template #default="{ row }">
            <strong :class="{ muted: Number(row.to_buy_qty) <= 0 }">{{ formatNum(row.to_buy_qty) }}</strong>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  { embedded: false },
)

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
/** 固定计入库存池（口径跟租户齐套一致，不再页面手拨） */
const includeShared = true
const showDetail = ref(false)
const filters = reactive({
  keyword: '',
  partner_id: null as number | null,
  rush_only: false,
  hidePurchased: true,
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function canSelect(row: any) {
  return Number(row.to_buy_qty) > 0
}

function statusTagType(status: string) {
  if (status === 'ordered') return 'success'
  if (status === 'draft') return 'warning'
  if (status === 'partial') return 'info'
  return 'danger'
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
        hide_purchased: filters.hidePurchased,
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

async function createPo() {
  const picks = selected.value.filter((r) => Number(r.to_buy_qty) > 0)
  if (!picks.length) {
    ElMessage.warning('请选择仍有待购数量的行')
    return
  }
  const res: any = await http.post('/purchase-orders/from-shortages', {
    requirement_ids: picks.map((r) => r.id),
    include_shared: includeShared,
  })
  const created = res.data || []
  if (!created.length) {
    ElMessage.warning('没有可生成的采购（可能已有草稿或已下单）')
  } else {
    ElMessage.success(`已生成 ${created.length} 张采购草稿`)
  }
  await load()
}

watch(showDetail, async () => {
  await nextTick()
  measureTableHeight()
  relayoutTable?.()
})

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
